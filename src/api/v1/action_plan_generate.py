"""
API endpoint pour la génération de plan d'action (SSE streaming).

Pattern identique à la génération de questions:
- Génération complète EN MÉMOIRE
- Streaming SSE de la progression
- Retourne JSON au frontend
- Pas d'écriture en base de données

Version: 2.0 - Refactorisation complète
Date: 2025-01-23
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import AsyncGenerator
from uuid import UUID
from datetime import datetime, timezone
import logging
import json
import asyncio
import os

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak, require_permission
from src.models.audit import User
from src.services.action_plan_generation_service import ActionPlanGenerationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["Action Plan Generation"])


async def get_next_action_code(db: Session, tenant_id: UUID, campaign_id: UUID = None) -> str:
    """
    Génère le prochain code d'action disponible pour un tenant.

    Format:
    - Actions de campagne: ACT_CAMP_XXX_NNN (XXX = numéro campagne, NNN = numéro séquentiel)
    - Actions standalone: ACT_NNN (NNN = numéro séquentiel global)

    Cherche dans toutes les tables (action_plan_item, published_action, action)
    pour éviter les doublons.

    Args:
        db: Session de base de données
        tenant_id: ID du tenant
        campaign_id: ID de la campagne (optionnel, si fourni utilise format campagne)

    Returns:
        Le prochain code disponible (ex: "ACT_CAMP_001_042" ou "ACT_042")
    """
    if campaign_id:
        # Format campagne: ACT_CAMP_XXX_NNN
        # Récupérer le numéro séquentiel de la campagne
        campaign_num_query = text("""
            SELECT COUNT(*) + 1 as campaign_num
            FROM campaign
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id != CAST(:campaign_id AS uuid)
              AND created_at <= (SELECT created_at FROM campaign WHERE id = CAST(:campaign_id AS uuid))
        """)
        campaign_num_result = db.execute(campaign_num_query, {
            "tenant_id": str(tenant_id),
            "campaign_id": str(campaign_id)
        })
        campaign_num_row = campaign_num_result.first()
        campaign_num = campaign_num_row[0] if campaign_num_row else 1

        campaign_code_prefix = f"ACT_CAMP_{campaign_num:03d}_"

        # Récupérer le max code pour cette campagne
        max_code_query = text("""
            SELECT COALESCE(MAX(code_num), 0) as max_code FROM (
                SELECT CAST(SUBSTRING(code_action FROM :prefix_len) AS INTEGER) as code_num
                FROM action_plan_item
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND code_action IS NOT NULL
                  AND code_action LIKE :prefix || '%'
                  AND code_action ~ ('^' || :prefix || '[0-9]+$')
                UNION ALL
                SELECT CAST(SUBSTRING(code_action FROM :prefix_len) AS INTEGER) as code_num
                FROM published_action
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND code_action IS NOT NULL
                  AND code_action LIKE :prefix || '%'
                  AND code_action ~ ('^' || :prefix || '[0-9]+$')
            ) all_codes
        """)

        result = db.execute(max_code_query, {
            "tenant_id": str(tenant_id),
            "prefix": campaign_code_prefix,
            "prefix_len": len(campaign_code_prefix) + 1
        })
        row = result.first()
        max_code = row[0] if row and row[0] else 0
        next_code = max_code + 1
        return f"{campaign_code_prefix}{next_code:03d}"

    else:
        # Format standalone: ACT_NNN
        max_code_query = text("""
            SELECT COALESCE(MAX(code_num), 0) as max_code FROM (
                SELECT CAST(SUBSTRING(code_action FROM 5) AS INTEGER) as code_num
                FROM action
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND code_action IS NOT NULL
                  AND code_action ~ '^ACT_[0-9]+$'
            ) all_codes
        """)

        result = db.execute(max_code_query, {"tenant_id": str(tenant_id)})
        row = result.first()
        max_code = row[0] if row and row[0] else 0

        next_code = max_code + 1
        return f"ACT_{next_code:03d}"


@router.get("/{campaign_id}/action-plan/generate/stream")
async def generate_action_plan_stream(
    campaign_id: UUID,
    request: Request,
    current_user: User = Depends(require_permission("ACTION_PLAN_CREATE")),
    db: Session = Depends(get_db)
):
    """
    Génère un plan d'action EN MÉMOIRE avec streaming SSE temps réel.

    Pattern identique à la génération de questions:
    1. Service génère les données en mémoire (aucune DB)
    2. Progression streamée via SSE
    3. Résultat final retourné en JSON
    4. Frontend affiche l'interface de validation
    5. Utilisateur valide/modifie
    6. Frontend appelle /publish pour sauvegarder

    Événements SSE:
    - status: "initializing" → Vérifications initiales
    - status: "phase1_started" → Début Phase 1
    - status: "phase1_progress" → Progression Phase 1
    - status: "phase1_completed" → Fin Phase 1
    - ... (idem pour phases 2, 3, 4)
    - status: "completed" → Génération terminée (avec JSON complet)
    - status: "error" → Erreur fatale
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        """Générateur d'événements SSE"""
        progress_queue = asyncio.Queue()

        async def progress_callback(status: str, data: dict):
            """Callback appelé par le service pour chaque progression"""
            event_data = {
                "status": status,
                **data
            }
            await progress_queue.put(event_data)

        try:
            logger.info(f"🚀 Début génération SSE pour campagne {campaign_id}")

            # ========== VÉRIFICATION: Campagne doit être figée ==========
            campaign_query = text("""
                SELECT id, title, status, tenant_id
                FROM campaign
                WHERE id = CAST(:campaign_id AS uuid)
            """)
            campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)})
            campaign = campaign_result.mappings().first()

            if not campaign:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Campagne introuvable'})}\n\n"
                return

            if campaign.status != 'frozen':
                yield f"data: {json.dumps({'status': 'error', 'message': f'La campagne doit être figée. Statut actuel: {campaign.status}'})}\n\n"
                return

            logger.info(f"✅ Campagne {campaign_id} figée, génération autorisée")

            # ========== INITIALISATION ==========
            yield f"data: {json.dumps({'status': 'initializing', 'message': 'Initialisation de la génération...'})}\n\n"
            await asyncio.sleep(0.1)

            # Initialiser le service avec les variables d'environnement
            ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
            ollama_model = os.getenv("OLLAMA_MODEL", "deepseek-v3.1:671b-cloud")
            logger.info(f"🤖 Modèle IA configuré: {ollama_model}")
            service = ActionPlanGenerationService(
                ollama_base_url=ollama_url,
                model=ollama_model
            )

            # Lancer la génération dans une tâche séparée
            async def run_generation():
                return await service.generate_action_plan(
                    campaign_id=campaign_id,
                    db=db,
                    progress_callback=progress_callback
                )

            generation_task = asyncio.create_task(run_generation())

            # ========== STREAMING DES ÉVÉNEMENTS DE PROGRESSION ==========
            heartbeat_counter = 0
            while not generation_task.done():
                try:
                    # Attendre un événement avec timeout
                    event_data = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event_data)}\n\n"
                    heartbeat_counter = 0  # Reset heartbeat après événement réel
                except asyncio.TimeoutError:
                    # Vérifier si le client est toujours connecté
                    if await request.is_disconnected():
                        logger.warning("Client déconnecté, annulation de la génération")
                        generation_task.cancel()
                        return

                    # Envoyer un heartbeat toutes les 2 secondes pour montrer que ça progresse
                    heartbeat_counter += 1
                    if heartbeat_counter >= 2:  # Toutes les 2 secondes (2 * 1.0s timeout)
                        heartbeat_data = {
                            "status": "heartbeat",
                            "message": "⏳ Génération en cours...",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                        yield f"data: {json.dumps(heartbeat_data)}\n\n"
                        heartbeat_counter = 0
                    continue

            # ========== RÉCUPÉRATION DU RÉSULTAT FINAL ==========
            action_plan_data = await generation_task

            # ========== DEBUG : VÉRIFIER NOMBRE D'ACTIONS ==========
            num_actions = len(action_plan_data.get("actions", []))
            logger.info(f"🔍 DEBUG: Plan généré contient {num_actions} actions")
            logger.info(f"🔍 DEBUG: Actions IDs: {[a.get('local_id', 'NO_ID') for a in action_plan_data.get('actions', [])]}")

            # ========== ÉVÉNEMENT FINAL : COMPLETED ==========
            final_result = {
                "status": "completed",
                "success": True,
                "action_plan": action_plan_data,  # JSON complet du plan
                "message": "✅ Plan d'action généré avec succès"
            }

            # Vérifier que le JSON est sérialisable
            json_str = json.dumps(final_result)
            logger.info(f"🔍 DEBUG: Taille JSON envoyé au frontend: {len(json_str)} bytes")

            # Compter les occurrences de "local_id" dans le JSON
            local_id_count = json_str.count('"local_id"')
            logger.info(f"🔍 DEBUG: Nombre d'actions dans JSON final: {local_id_count}")

            yield f"data: {json_str}\n\n"

            logger.info(f"✅ Génération SSE terminée pour campagne {campaign_id}")

        except Exception as e:
            logger.error(f"❌ Erreur génération SSE: {str(e)}", exc_info=True)
            error_data = {
                "status": "error",
                "message": str(e),
                "error": True
            }
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.get("/{campaign_id}/action-plan/items")
async def get_action_plan_items(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("ACTION_PLAN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les items du plan d'action publié.

    Returns:
        Liste des ActionPlanItem avec leurs détails
    """
    try:
        logger.info(f"📋 Récupération des items du plan d'action pour campagne {campaign_id}")

        # Vérifier que la campagne existe
        campaign_query = text("""
            SELECT id FROM campaign WHERE id = CAST(:campaign_id AS uuid)
        """)
        campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)})
        campaign = campaign_result.first()

        if not campaign:
            raise HTTPException(status_code=404, detail="Campagne introuvable")

        # Récupérer le plan d'action
        plan_query = text("""
            SELECT id, status, total_actions, summary_title
            FROM action_plan
            WHERE campaign_id = CAST(:campaign_id AS uuid)
            LIMIT 1
        """)
        plan_result = db.execute(plan_query, {"campaign_id": str(campaign_id)})
        plan = plan_result.mappings().first()

        if not plan:
            return {
                "action_plan_id": None,
                "status": None,
                "items": []
            }

        # Récupérer les items du plan
        items_query = text("""
            SELECT
                id,
                code_action,
                order_index,
                title,
                description,
                objective,
                deliverables,
                severity,
                priority,
                status,
                recommended_due_days,
                suggested_role,
                assigned_user_id,
                assignment_method,
                source_question_ids,
                control_point_ids,
                ai_justifications,
                entity_id,
                entity_name,
                created_action_id,
                created_at,
                updated_at
            FROM action_plan_item
            WHERE action_plan_id = CAST(:plan_id AS uuid)
            ORDER BY order_index ASC
        """)
        items_result = db.execute(items_query, {"plan_id": str(plan.id)})
        items = items_result.mappings().all()

        # Convertir en JSON
        items_list = []
        for item in items:
            # Enrichir les control points avec leurs labels depuis la BDD
            control_point_details = []
            if item.control_point_ids:
                cp_query = text("""
                    SELECT
                        cp.id,
                        cp.code as control_id,
                        cp.name as title,
                        cp.category,
                        cp.description
                    FROM control_point cp
                    WHERE cp.id = ANY(CAST(:cp_ids AS uuid[]))
                """)

                cp_result = db.execute(cp_query, {
                    "cp_ids": [str(cp_id) for cp_id in item.control_point_ids]
                })

                for cp_row in cp_result.mappings():
                    control_point_details.append({
                        "id": str(cp_row.id),
                        "control_id": cp_row.control_id,
                        "title": cp_row.title,
                        "category": cp_row.category,
                        "description": cp_row.description,
                        "label": f"{cp_row.control_id}: {cp_row.title}"
                    })

            # Récupérer la question source si présente
            source_question = None
            if item.source_question_ids and len(item.source_question_ids) > 0:
                question_id = item.source_question_ids[0]  # On prend la première question
                question_query = text("""
                    SELECT
                        q.id,
                        q.question_text,
                        q.question_code,
                        COALESCE(d.code_officiel, d.code) as domain_name
                    FROM question q
                    LEFT JOIN requirement r ON q.requirement_id = r.id
                    LEFT JOIN domain d ON r.domain_id = d.id
                    WHERE q.id = CAST(:question_id AS uuid)
                """)
                question_result = db.execute(question_query, {"question_id": str(question_id)})
                question_row = question_result.first()
                if question_row:
                    source_question = {
                        "id": str(question_row[0]),
                        "question_text": question_row[1],
                        "question_code": question_row[2],
                        "domain_name": question_row[3]
                    }

            # Récupérer le nom et l'ID de l'entité
            # Depuis la nouvelle version, l'IA fournit directement entity_id et entity_name
            entity_name = getattr(item, 'entity_name', None)
            entity_id = getattr(item, 'entity_id', None)

            logger.info(f"🔍 Item {item.id}: entity_id={entity_id}, entity_name={entity_name}")

            # Fallback UNIQUEMENT si l'IA n'a pas fourni l'entity_id
            if not entity_id and item.source_question_ids and len(item.source_question_ids) > 0:
                logger.warning(f"⚠️ Entity non fournie par l'IA, utilisation du fallback")
                try:
                    # Récupérer l'entité depuis l'audit_id de la question-réponse
                    entity_query = text("""
                        SELECT DISTINCT ee.id, ee.name
                        FROM question_answer qa
                        JOIN audit a ON qa.audit_id = a.id
                        JOIN ecosystem_entity ee ON ee.id = a.target_org_id
                        WHERE qa.question_id = ANY(CAST(:question_ids AS uuid[]))
                          AND qa.campaign_id = CAST(:campaign_id AS uuid)
                        LIMIT 1
                    """)

                    entity_result = db.execute(entity_query, {
                        "question_ids": [str(qid) for qid in item.source_question_ids],
                        "campaign_id": str(campaign_id)
                    })

                    entity_row = entity_result.first()
                    if entity_row:
                        entity_id = entity_row[0]
                        entity_name = entity_row[1]
                        logger.info(f"✅ Entity trouvée via fallback: {entity_name} (ID: {entity_id})")
                    else:
                        logger.error(f"❌ Fallback échoué - Aucune entité trouvée pour {item.id}")
                except Exception as e:
                    logger.error(f"❌ Erreur fallback entity: {str(e)}", exc_info=True)
            else:
                logger.info(f"✅ Entity fournie par l'IA: {entity_name} (ID: {entity_id})")

            # Récupérer le nom de l'utilisateur assigné
            # PRIORITÉ : Toujours chercher l'audité responsable (audite_resp) de l'entité
            # L'audité est défini dans le scope de la campagne, PAS l'auditeur
            assigned_user_name = None
            assigned_user_id_value = None  # On réinitialise car on veut l'audité, pas l'auditeur

            if entity_id:
                # PRIORITÉ 1 : Chercher l'audité responsable (audite_resp) de l'entité
                # C'est la personne assignée au scope de la campagne
                audite_resp_query = text("""
                    SELECT em.id, CONCAT(em.first_name, ' ', em.last_name) as full_name
                    FROM entity_member em
                    WHERE em.entity_id = CAST(:entity_id AS uuid)
                      AND em.is_active = true
                      AND em.roles::jsonb ? 'audite_resp'
                    ORDER BY em.created_at ASC
                    LIMIT 1
                """)
                audite_result = db.execute(audite_resp_query, {"entity_id": str(entity_id)})
                audite_row = audite_result.first()
                if audite_row:
                    assigned_user_id_value = audite_row[0]
                    assigned_user_name = audite_row[1]
                    logger.info(f"✅ Audité responsable trouvé pour entité {entity_id}: {assigned_user_name}")
                else:
                    # PRIORITÉ 2 : Chercher n'importe quel membre actif de l'entité
                    any_member_query = text("""
                        SELECT em.id, CONCAT(em.first_name, ' ', em.last_name) as full_name
                        FROM entity_member em
                        WHERE em.entity_id = CAST(:entity_id AS uuid)
                          AND em.is_active = true
                        ORDER BY em.created_at ASC
                        LIMIT 1
                    """)
                    any_member_result = db.execute(any_member_query, {"entity_id": str(entity_id)})
                    any_member_row = any_member_result.first()
                    if any_member_row:
                        assigned_user_id_value = any_member_row[0]
                        assigned_user_name = any_member_row[1]
                        logger.info(f"✅ Membre d'entité trouvé (fallback): {assigned_user_name}")

            # PRIORITÉ 3 : Si aucun audité trouvé ET un assigned_user_id existe,
            # vérifier que c'est bien un audité (entity_member) et PAS un auditeur (users)
            if not assigned_user_name and item.assigned_user_id:
                user_query = text("""
                    SELECT CONCAT(first_name, ' ', last_name) as full_name
                    FROM entity_member
                    WHERE id = CAST(:user_id AS uuid)
                    LIMIT 1
                """)
                user_result = db.execute(user_query, {"user_id": str(item.assigned_user_id)})
                user_row = user_result.first()
                if user_row and user_row[0]:
                    # C'est bien un audité (entity_member), on peut l'utiliser
                    assigned_user_id_value = item.assigned_user_id
                    assigned_user_name = user_row[0]
                    logger.info(f"✅ Utilisateur assigné trouvé dans entity_member: {assigned_user_name}")
                # NOTE: On ne cherche PAS dans la table users car ce sont les auditeurs internes

            items_list.append({
                "id": str(item.id),
                "code_action": item.code_action,  # ✅ Code unique de l'action
                "order_index": item.order_index,
                "title": item.title,
                "description": item.description,
                "objective": item.objective,  # ✅ Ajout objective
                "deliverables": item.deliverables,  # ✅ Ajout deliverables
                "severity": item.severity,
                "priority": item.priority,
                "status": item.status,
                "recommended_due_days": item.recommended_due_days,
                "suggested_role": item.suggested_role,
                "assigned_user_id": str(assigned_user_id_value) if assigned_user_id_value else None,
                "assigned_user_name": assigned_user_name,  # ✅ Nom de l'utilisateur assigné
                "assignment_method": item.assignment_method,
                "source_question_ids": item.source_question_ids,
                "source_question": source_question,  # ✅ Ajout question source avec détails
                "control_points": control_point_details,  # Détails complets des control points
                "entity_id": str(entity_id) if entity_id else None,  # ID de l'entité
                "entity_name": entity_name,  # Nom de l'entité pour groupement
                "ai_justifications": item.ai_justifications,
                "created_action_id": str(item.created_action_id) if item.created_action_id else None,  # ID action publiée
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None
            })

        logger.info(f"✅ {len(items_list)} items récupérés pour plan {plan.id}")

        return {
            "action_plan_id": str(plan.id),
            "status": plan.status,
            "total_actions": plan.total_actions,
            "summary_title": plan.summary_title,
            "items": items_list
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur récupération items : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération: {str(e)}")


@router.put("/action-plan/items/{item_id}")
async def update_action_plan_item(
    item_id: UUID,
    update_data: dict,
    current_user: User = Depends(require_permission("ACTION_PLAN_UPDATE")),
    db: Session = Depends(get_db)
):
    """
    Met à jour un item du plan d'action publié.

    Args:
        item_id: ID de l'item à mettre à jour
        update_data: Données de mise à jour (title, description, severity, priority, etc.)

    Returns:
        L'item mis à jour
    """
    try:
        logger.info(f"📝 Mise à jour de l'item {item_id}")

        # Vérifier que l'item existe
        check_query = text("""
            SELECT api.id, ap.campaign_id
            FROM action_plan_item api
            JOIN action_plan ap ON api.action_plan_id = ap.id
            WHERE api.id = CAST(:item_id AS uuid)
        """)

        item_result = db.execute(check_query, {"item_id": str(item_id)}).fetchone()

        if not item_result:
            raise HTTPException(status_code=404, detail="Item non trouvé")

        # Construire la requête de mise à jour dynamiquement
        update_fields = []
        params = {"item_id": str(item_id)}

        allowed_fields = {
            "title": "title",
            "description": "description",
            "objective": "objective",
            "deliverables": "deliverables",
            "severity": "severity",
            "priority": "priority",
            "status": "status",
            "recommended_due_days": "recommended_due_days",
            "suggested_role": "suggested_role",
            "assigned_user_id": "assigned_user_id",
            "entity_id": "entity_id"
        }

        for field_name, db_column in allowed_fields.items():
            if field_name in update_data:
                if field_name in ["assigned_user_id", "entity_id"]:
                    # Gérer le cas NULL pour assigned_user_id et entity_id
                    if update_data[field_name]:
                        update_fields.append(f"{db_column} = CAST(:{field_name} AS uuid)")
                        params[field_name] = str(update_data[field_name])
                    else:
                        update_fields.append(f"{db_column} = NULL")
                else:
                    update_fields.append(f"{db_column} = :{field_name}")
                    params[field_name] = update_data[field_name]

        if not update_fields:
            raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")

        # Ajouter updated_at
        update_fields.append("updated_at = CURRENT_TIMESTAMP")

        update_query = text(f"""
            UPDATE action_plan_item
            SET {', '.join(update_fields)}
            WHERE id = CAST(:item_id AS uuid)
            RETURNING id
        """)

        result = db.execute(update_query, params)
        db.commit()

        if not result.fetchone():
            raise HTTPException(status_code=500, detail="Erreur lors de la mise à jour")

        logger.info(f"✅ Item {item_id} mis à jour avec succès")

        return {"success": True, "item_id": str(item_id)}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur mise à jour item : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour: {str(e)}")


@router.post("/{campaign_id}/action-plan/publish")
async def publish_action_plan(
    campaign_id: UUID,
    action_plan_data: dict,
    current_user: User = Depends(require_permission("ACTION_PLAN_CREATE")),
    db: Session = Depends(get_db)
):
    """
    Publie le plan d'action validé par l'utilisateur en base de données.

    Appelé APRÈS que l'utilisateur a validé/modifié le plan dans l'interface.

    Crée:
    - 1 ActionPlan (status=PUBLISHED)
    - N ActionPlanItem (status=ACCEPTED pour les actions cochées)

    Args:
        campaign_id: ID de la campagne
        action_plan_data: JSON du plan validé (peut avoir été modifié par l'utilisateur)

    Returns:
        {"action_plan_id": UUID, "total_actions": int}
    """
    from uuid import uuid4
    from src.models.action_plan import (
        ActionPlan,
        ActionPlanItem,
        ActionPlanStatus,
        ActionPlanItemStatus,
        ActionSeverity,
        ActionPriority,
        AssignmentMethod
    )

    try:
        logger.info(f"📝 Publication du plan d'action pour campagne {campaign_id}")

        # Vérifier que la campagne existe et est figée
        campaign_query = text("""
            SELECT id, tenant_id, status FROM campaign
            WHERE id = CAST(:campaign_id AS uuid)
        """)
        campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)})
        campaign = campaign_result.mappings().first()

        if not campaign:
            raise HTTPException(status_code=404, detail="Campagne introuvable")

        if campaign.status != 'frozen':
            raise HTTPException(
                status_code=400,
                detail=f"La campagne doit être figée. Statut actuel: {campaign.status}"
            )

        tenant_id = campaign.tenant_id

        # Supprimer un plan existant si présent
        existing_plan_query = text("""
            SELECT id FROM action_plan WHERE campaign_id = CAST(:campaign_id AS uuid)
        """)
        existing_result = db.execute(existing_plan_query, {"campaign_id": str(campaign_id)})
        existing_row = existing_result.first()

        if existing_row:
            logger.info(f"⚠️ Plan existant trouvé ({existing_row[0]}), suppression...")
            delete_query = text("""
                DELETE FROM action_plan WHERE id = CAST(:plan_id AS uuid)
            """)
            db.execute(delete_query, {"plan_id": str(existing_row[0])})
            db.commit()

        # Créer le plan d'action
        action_plan_id = uuid4()
        summary = action_plan_data.get("action_plan_summary", {})
        stats = action_plan_data.get("statistics", {})

        action_plan = ActionPlan(
            id=action_plan_id,
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            status=ActionPlanStatus.PUBLISHED,
            summary_title=summary.get("title", f"Plan d'actions - {campaign_id}"),
            overall_risk_level=stats.get("overall_risk_level", "moyen"),
            dominant_language="fr",
            total_actions=len(action_plan_data.get("actions", [])),
            critical_count=stats.get("critical_count", 0),
            major_count=stats.get("major_count", 0),
            minor_count=stats.get("minor_count", 0),
            info_count=stats.get("info_count", 0),
            generated_at=datetime.now(timezone.utc),
            generated_by=current_user.id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            generation_progress={}
        )

        db.add(action_plan)
        db.flush()

        # Créer les ActionPlanItem (uniquement celles cochées par l'utilisateur)
        actions = action_plan_data.get("actions", [])
        created_count = 0

        # Récupérer le numéro de campagne pour le format ACT_CAMP_XXX_NNN
        # Chercher le numéro séquentiel de la campagne pour ce tenant
        campaign_num_query = text("""
            SELECT COUNT(*) + 1 as campaign_num
            FROM campaign
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND id != CAST(:campaign_id AS uuid)
              AND created_at <= (SELECT created_at FROM campaign WHERE id = CAST(:campaign_id AS uuid))
        """)
        campaign_num_result = db.execute(campaign_num_query, {
            "tenant_id": str(current_user.tenant_id),
            "campaign_id": str(campaign_id)
        })
        campaign_num_row = campaign_num_result.first()
        campaign_num = campaign_num_row[0] if campaign_num_row else 1

        # Récupérer le compteur de code actuel pour cette campagne spécifique
        # Format: ACT_CAMP_XXX_NNN où XXX est le numéro de campagne
        campaign_code_prefix = f"ACT_CAMP_{campaign_num:03d}_"
        max_code_query = text("""
            SELECT COALESCE(MAX(code_num), 0) as max_code FROM (
                SELECT CAST(SUBSTRING(code_action FROM :prefix_len) AS INTEGER) as code_num
                FROM action_plan_item
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND code_action IS NOT NULL
                  AND code_action LIKE :prefix || '%'
                  AND code_action ~ ('^' || :prefix || '[0-9]+$')
                UNION ALL
                SELECT CAST(SUBSTRING(code_action FROM :prefix_len) AS INTEGER) as code_num
                FROM published_action
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND code_action IS NOT NULL
                  AND code_action LIKE :prefix || '%'
                  AND code_action ~ ('^' || :prefix || '[0-9]+$')
            ) all_codes
        """)
        max_result = db.execute(max_code_query, {
            "tenant_id": str(current_user.tenant_id),
            "prefix": campaign_code_prefix,
            "prefix_len": len(campaign_code_prefix) + 1  # +1 pour SUBSTRING 1-indexed
        })
        max_row = max_result.first()
        current_code_counter = max_row[0] if max_row and max_row[0] else 0

        for action_data in actions:
            # Vérifier si l'action est incluse (checkbox cochée)
            if not action_data.get("included", True):
                continue

            # Mapper severity (passer directement la string lowercase)
            severity_str = action_data.get("severity", "minor").lower()  # Forcer lowercase
            if severity_str not in ["critical", "major", "minor", "info"]:
                severity_str = "minor"

            # Mapper priority (garder tel quel)
            priority_str = action_data.get("priority", "P2")
            if priority_str not in ["P1", "P2", "P3"]:
                priority_str = "P2"

            # Extraire description, objective et deliverables séparément
            description = action_data.get("description", "")
            objective = action_data.get("objective", "")
            deliverables_list = action_data.get("deliverables", [])

            # Convertir deliverables (liste) en HTML riche si présent
            deliverables_html = None
            if deliverables_list:
                deliverables_html = "<ul>" + "".join([f"<li>{d}</li>" for d in deliverables_list]) + "</ul>"

            # Convertir assigned_user_id en UUID si présent
            assigned_user_id_value = action_data.get("assigned_user_id")
            if assigned_user_id_value and isinstance(assigned_user_id_value, str):
                try:
                    assigned_user_id_value = UUID(assigned_user_id_value)
                except (ValueError, AttributeError):
                    assigned_user_id_value = None

            # assignment_method: passer directement la string lowercase
            assignment_method_str = "direct" if assigned_user_id_value else "unassigned"

            # ========== RÉCUPÉRER LES CONTROL POINTS DEPUIS LA BDD ==========
            # Les control_point_ids doivent être déduits des source_questions
            # Utiliser la table question_control_point (many-to-many)
            source_question_ids = action_data.get("source_questions", [])
            control_point_ids = []

            if source_question_ids:
                try:
                    # Récupérer les control_point_id via la table many-to-many
                    control_points_query = text("""
                        SELECT DISTINCT qcp.control_point_id
                        FROM question_control_point qcp
                        WHERE qcp.question_id = ANY(CAST(:question_ids AS uuid[]))
                    """)

                    cp_result = db.execute(control_points_query, {
                        "question_ids": [str(qid) for qid in source_question_ids]
                    })

                    control_point_ids = [str(row[0]) for row in cp_result if row[0]]

                    logger.debug(f"Action '{action_data.get('title', '')[:50]}...': {len(source_question_ids)} questions → {len(control_point_ids)} control points")
                except Exception as e:
                    logger.warning(f"Impossible de récupérer control_point_ids: {e}")
                    control_point_ids = []

            # Récupérer entity_id et entity_name depuis action_data
            entity_id_value = action_data.get("entity_id")
            entity_name_value = action_data.get("entity_name")

            # Convertir entity_id en UUID si présent
            if entity_id_value and isinstance(entity_id_value, str):
                try:
                    entity_id_value = UUID(entity_id_value)
                except (ValueError, AttributeError):
                    entity_id_value = None

            # Générer le code d'action unique (format: ACT_CAMP_XXX_NNN)
            current_code_counter += 1
            code_action = f"{campaign_code_prefix}{current_code_counter:03d}"

            item = ActionPlanItem(
                id=uuid4(),
                action_plan_id=action_plan_id,
                tenant_id=current_user.tenant_id,
                code_action=code_action,  # ✅ Code unique de l'action
                status="VALIDATED",  # Status utilise UPPERCASE
                order_index=created_count,
                title=action_data.get("title", ""),
                description=description,
                objective=objective if objective else None,  # ✅ Stockage séparé
                deliverables=deliverables_html,  # ✅ Stockage séparé en HTML
                severity=severity_str,  # Passer string lowercase directement
                priority=priority_str,  # Passer string directement
                recommended_due_days=action_data.get("recommended_due_days", 60),
                suggested_role=action_data.get("suggested_role", ""),
                assigned_user_id=assigned_user_id_value,
                assignment_method=assignment_method_str,  # Passer string lowercase directement
                source_question_ids=source_question_ids,
                control_point_ids=control_point_ids,  # IDs réels depuis la BDD
                ai_justifications=action_data.get("justification", {}),
                entity_id=entity_id_value,  # ✅ Ajout entity_id
                entity_name=entity_name_value,  # ✅ Ajout entity_name
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            db.add(item)
            created_count += 1

        # Mettre à jour le total
        action_plan.total_actions = created_count

        # Commit final
        db.commit()
        db.refresh(action_plan)

        logger.info(f"✅ Plan publié : {action_plan_id} ({created_count} actions)")

        return {
            "success": True,
            "action_plan_id": str(action_plan_id),
            "total_actions": created_count,
            "message": f"Plan d'action publié avec succès ({created_count} actions)"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur publication : {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur lors de la publication: {str(e)}")


@router.post("/{campaign_id}/action-plan/items")
async def create_action_plan_item(
    campaign_id: UUID,
    item_data: dict,
    current_user: User = Depends(require_permission("ACTION_PLAN_CREATE")),
    db: Session = Depends(get_db)
):
    """
    Crée un nouvel item dans le plan d'action existant.

    Args:
        campaign_id: ID de la campagne
        item_data: Données de l'item (title, description, severity, priority, entity_id, assigned_user_id)
        current_user: Utilisateur authentifié
        db: Session database

    Returns:
        L'item créé avec son ID

    Raises:
        HTTPException 404: Si la campagne ou le plan n'existe pas
        HTTPException 500: En cas d'erreur lors de la création
    """
    from uuid import uuid4

    try:
        logger.info(f"📝 Création d'une action pour campagne {campaign_id}")

        # Vérifier que la campagne existe
        campaign_query = text("""
            SELECT id, tenant_id FROM campaign WHERE id = CAST(:campaign_id AS uuid)
        """)
        campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)})
        campaign = campaign_result.mappings().first()

        if not campaign:
            raise HTTPException(status_code=404, detail="Campagne introuvable")

        # Récupérer le plan d'action existant
        plan_query = text("""
            SELECT id, total_actions FROM action_plan
            WHERE campaign_id = CAST(:campaign_id AS uuid)
            LIMIT 1
        """)
        plan_result = db.execute(plan_query, {"campaign_id": str(campaign_id)})
        plan = plan_result.mappings().first()

        if not plan:
            raise HTTPException(status_code=404, detail="Aucun plan d'action trouvé. Générez d'abord un plan.")

        action_plan_id = plan.id
        current_order = plan.total_actions or 0

        # Récupérer le nom de l'entité si entity_id fourni
        entity_name = None
        entity_id_value = item_data.get("entity_id")
        if entity_id_value:
            entity_query = text("""
                SELECT name FROM ecosystem_entity WHERE id = CAST(:entity_id AS uuid)
            """)
            entity_result = db.execute(entity_query, {"entity_id": str(entity_id_value)})
            entity_row = entity_result.first()
            if entity_row:
                entity_name = entity_row[0]

        # Mapper severity
        severity_str = item_data.get("severity", "minor").lower()
        if severity_str not in ["critical", "major", "minor", "info"]:
            severity_str = "minor"

        # Mapper priority
        priority_str = item_data.get("priority", "P2")
        if priority_str not in ["P1", "P2", "P3"]:
            priority_str = "P2"

        # Mapper status - Les statuts DB valides sont: PROPOSED, VALIDATED, EXCLUDED, PUBLISHED
        status_str = item_data.get("status", "PROPOSED")
        # Mapper les statuts frontend vers les statuts DB
        status_mapping = {
            "pending": "PROPOSED",
            "in_progress": "VALIDATED",
            "completed": "PUBLISHED",
            "blocked": "EXCLUDED",
            # Statuts déjà valides
            "PROPOSED": "PROPOSED",
            "VALIDATED": "VALIDATED",
            "EXCLUDED": "EXCLUDED",
            "PUBLISHED": "PUBLISHED",
        }
        status_str = status_mapping.get(status_str, "PROPOSED")

        # Convertir assigned_user_id en UUID si présent
        assigned_user_id_value = item_data.get("assigned_user_id")
        assignment_method_str = "unassigned"
        if assigned_user_id_value:
            assignment_method_str = "direct"

        # Récupérer les source_question_ids et control_point_ids
        source_question_ids = item_data.get("source_question_ids", [])
        control_point_ids = item_data.get("control_point_ids", [])

        # Générer le code d'action unique (format: ACT_CAMP_XXX_NNN)
        code_action = await get_next_action_code(db, campaign.tenant_id, campaign_id)

        # Créer l'item
        item_id = uuid4()
        insert_query = text("""
            INSERT INTO action_plan_item (
                id, action_plan_id, tenant_id, code_action, status, order_index,
                title, description, objective, deliverables,
                severity, priority, recommended_due_days, suggested_role,
                assigned_user_id, assignment_method,
                entity_id, entity_name,
                source_question_ids, control_point_ids,
                created_at, updated_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:action_plan_id AS uuid),
                CAST(:tenant_id AS uuid),
                :code_action,
                :status,
                :order_index,
                :title,
                :description,
                :objective,
                :deliverables,
                :severity,
                :priority,
                :recommended_due_days,
                :suggested_role,
                CAST(:assigned_user_id AS uuid),
                :assignment_method,
                CAST(:entity_id AS uuid),
                :entity_name,
                CAST(:source_question_ids AS uuid[]),
                :control_point_ids,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            RETURNING id
        """)

        db.execute(insert_query, {
            "id": str(item_id),
            "action_plan_id": str(action_plan_id),
            "tenant_id": str(campaign.tenant_id),
            "code_action": code_action,
            "status": status_str,
            "order_index": current_order,
            "title": item_data.get("title", "Nouvelle action"),
            "description": item_data.get("description", ""),
            "objective": item_data.get("objective"),
            "deliverables": item_data.get("deliverables"),
            "severity": severity_str,
            "priority": priority_str,
            "recommended_due_days": item_data.get("recommended_due_days", 30),
            "suggested_role": item_data.get("suggested_role", ""),
            "assigned_user_id": str(assigned_user_id_value) if assigned_user_id_value else None,
            "assignment_method": assignment_method_str,
            "entity_id": str(entity_id_value) if entity_id_value else None,
            "entity_name": entity_name,
            "source_question_ids": source_question_ids if source_question_ids else [],
            "control_point_ids": control_point_ids if control_point_ids else []
        })

        # Mettre à jour le compteur du plan
        update_plan_query = text("""
            UPDATE action_plan
            SET total_actions = total_actions + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = CAST(:action_plan_id AS uuid)
        """)
        db.execute(update_plan_query, {"action_plan_id": str(action_plan_id)})

        db.commit()

        logger.info(f"✅ Item créé : {item_id}")

        return {
            "success": True,
            "item_id": str(item_id),
            "message": "Action créée avec succès"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur création item : {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création: {str(e)}")


@router.delete("/action-plan/items/{item_id}")
async def delete_action_plan_item(
    item_id: UUID,
    current_user: User = Depends(require_permission("ACTION_PLAN_DELETE")),
    db: Session = Depends(get_db)
):
    """
    Supprime un item spécifique du plan d'action.

    Args:
        item_id: ID de l'item à supprimer
        current_user: Utilisateur authentifié
        db: Session database

    Returns:
        Message de confirmation

    Raises:
        HTTPException 404: Si l'item n'existe pas
        HTTPException 500: En cas d'erreur lors de la suppression
    """
    try:
        logger.info(f"🗑️ Suppression de l'item {item_id}")

        # Vérifier que l'item existe et récupérer l'action_plan_id
        check_query = text("""
            SELECT api.id, api.title, ap.id as action_plan_id, ap.total_actions
            FROM action_plan_item api
            JOIN action_plan ap ON api.action_plan_id = ap.id
            WHERE api.id = CAST(:item_id AS uuid)
        """)

        item_result = db.execute(check_query, {"item_id": str(item_id)}).mappings().first()

        if not item_result:
            raise HTTPException(status_code=404, detail="Item non trouvé")

        action_plan_id = item_result.action_plan_id
        item_title = item_result.title

        # Supprimer l'item
        delete_query = text("""
            DELETE FROM action_plan_item
            WHERE id = CAST(:item_id AS uuid)
        """)
        db.execute(delete_query, {"item_id": str(item_id)})

        # Mettre à jour le compteur du plan d'action
        update_plan_query = text("""
            UPDATE action_plan
            SET total_actions = total_actions - 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = CAST(:action_plan_id AS uuid)
        """)
        db.execute(update_plan_query, {"action_plan_id": str(action_plan_id)})

        db.commit()

        logger.info(f"✅ Item supprimé : {item_id} ({item_title[:50]}...)")

        return {
            "success": True,
            "item_id": str(item_id),
            "message": f"Action supprimée avec succès"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur suppression item : {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression: {str(e)}")


@router.delete("/{campaign_id}/action-plan")
async def delete_action_plan(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("ACTION_PLAN_DELETE")),
    db: Session = Depends(get_db)
):
    """
    Supprime le plan d'action et tous les items associés pour une campagne.

    Cette opération est irréversible et supprime :
    - Le plan d'action (action_plan)
    - Tous les items d'action associés (action_plan_item)

    Args:
        campaign_id: ID de la campagne
        current_user: Utilisateur authentifié
        db: Session database

    Returns:
        Message de confirmation avec nombre d'items supprimés

    Raises:
        HTTPException 404: Si la campagne ou le plan n'existe pas
        HTTPException 500: En cas d'erreur lors de la suppression
    """
    try:
        logger.info(f"🗑️ Suppression du plan d'action pour campagne {campaign_id}")

        # Vérifier que la campagne existe
        campaign_query = text("""
            SELECT id FROM campaign WHERE id = CAST(:campaign_id AS uuid)
        """)
        campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)})
        campaign = campaign_result.first()

        if not campaign:
            raise HTTPException(status_code=404, detail="Campagne introuvable")

        # Récupérer le plan d'action
        plan_query = text("""
            SELECT id FROM action_plan
            WHERE campaign_id = CAST(:campaign_id AS uuid)
            LIMIT 1
        """)
        plan_result = db.execute(plan_query, {"campaign_id": str(campaign_id)})
        plan = plan_result.first()

        if not plan:
            raise HTTPException(status_code=404, detail="Aucun plan d'action trouvé pour cette campagne")

        action_plan_id = plan[0]

        # Compter les items avant suppression
        count_query = text("""
            SELECT COUNT(*) FROM action_plan_item
            WHERE action_plan_id = CAST(:action_plan_id AS uuid)
        """)
        count_result = db.execute(count_query, {"action_plan_id": str(action_plan_id)})
        items_count = count_result.scalar()

        logger.info(f"📋 {items_count} items à supprimer")

        # Supprimer tous les items d'action
        delete_items_query = text("""
            DELETE FROM action_plan_item
            WHERE action_plan_id = CAST(:action_plan_id AS uuid)
        """)
        db.execute(delete_items_query, {"action_plan_id": str(action_plan_id)})

        logger.info(f"✅ {items_count} items supprimés")

        # Supprimer le plan d'action
        delete_plan_query = text("""
            DELETE FROM action_plan
            WHERE id = CAST(:action_plan_id AS uuid)
        """)
        db.execute(delete_plan_query, {"action_plan_id": str(action_plan_id)})

        db.commit()

        logger.info(f"✅ Plan d'action supprimé : {action_plan_id}")

        return {
            "success": True,
            "action_plan_id": str(action_plan_id),
            "items_deleted": items_count,
            "message": f"Plan d'action supprimé avec succès ({items_count} items supprimés)"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur suppression : {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression: {str(e)}")


@router.get("/{campaign_id}/questions-with-control-points")
async def get_campaign_questions_with_control_points(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("ACTION_PLAN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les questions du questionnaire de la campagne avec leurs points de contrôle associés.

    Utilisé pour le modal de création d'action afin de pouvoir sélectionner une question source
    et afficher les points de contrôle correspondants.

    Args:
        campaign_id: ID de la campagne
        current_user: Utilisateur authentifié
        db: Session database

    Returns:
        Liste des questions avec leurs control points
    """
    try:
        logger.info(f"📋 Récupération questions avec CPs pour campagne {campaign_id}")

        # Récupérer le questionnaire_id de la campagne
        campaign_query = text("""
            SELECT questionnaire_id FROM campaign
            WHERE id = CAST(:campaign_id AS uuid)
        """)
        campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)})
        campaign = campaign_result.first()

        if not campaign or not campaign[0]:
            raise HTTPException(status_code=404, detail="Campagne ou questionnaire introuvable")

        questionnaire_id = campaign[0]

        # Récupérer les questions avec leurs control points via la table many-to-many
        questions_query = text("""
            SELECT
                q.id,
                q.question_text,
                q.question_code,
                q.chapter,
                r.title as requirement_title,
                COALESCE(d.code_officiel, d.code) as domain_name
            FROM question q
            LEFT JOIN requirement r ON q.requirement_id = r.id
            LEFT JOIN domain d ON r.domain_id = d.id
            WHERE q.questionnaire_id = CAST(:questionnaire_id AS uuid)
              AND q.is_active = true
            ORDER BY q.sort_order, q.question_code
        """)

        questions_result = db.execute(questions_query, {"questionnaire_id": str(questionnaire_id)})

        questions = []
        for row in questions_result:
            question_id = row[0]

            # Récupérer les control points associés via question_control_point
            # Note: control_point a 'code' et 'name' (pas control_id/title)
            # Pour le framework, on passe par requirement_control_point → requirement → framework
            cps_query = text("""
                SELECT DISTINCT
                    cp.id,
                    cp.code,
                    cp.name,
                    f.name as framework_name,
                    f.code as framework_code
                FROM question_control_point qcp
                JOIN control_point cp ON qcp.control_point_id = cp.id
                LEFT JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
                LEFT JOIN requirement r ON r.id = rcp.requirement_id
                LEFT JOIN framework f ON f.id = r.framework_id
                WHERE qcp.question_id = CAST(:question_id AS uuid)
                ORDER BY cp.code
            """)
            cps_result = db.execute(cps_query, {"question_id": str(question_id)})

            control_points = []
            for cp_row in cps_result:
                control_points.append({
                    "id": str(cp_row[0]),
                    "control_id": cp_row[1],  # cp.code
                    "title": cp_row[2],        # cp.name
                    "referential_name": cp_row[3],  # framework.name
                    "referential_code": cp_row[4]   # framework.code
                })

            questions.append({
                "id": str(question_id),
                "question_text": row[1],
                "question_code": row[2],
                "chapter": row[3],
                "requirement_title": row[4],
                "domain_name": row[5],
                "control_points": control_points
            })

        logger.info(f"✅ {len(questions)} questions récupérées")

        return {
            "questions": questions,
            "total": len(questions)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur récupération questions : {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")
