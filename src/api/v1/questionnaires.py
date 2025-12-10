# src/api/v1/questionnaires.py

from __future__ import annotations

import logging
import json
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status, Request, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
import numpy as np
import uuid
import asyncio

from src.database import get_db
from src.schemas.questionnaire import QuestionGenerationRequest
# ✅ REFACTORING: Utilisation du nouveau service modulaire
from src.services.question_generation_service import QuestionGenerationService
# Gardé pour compatibilité si besoin de rollback
# from src.services.deepseek_question_generator import DeepSeekQuestionGenerator
from src.api.v1.openai_generator import DeepSeekControlPointGenerator
# ✅ Helper pour gérer les options
from src.services.helpers import save_question_with_options
from src.services.question_option_service import QuestionOptionService

# ✅ REDIS CACHE
from src.utils.redis_manager import cache_result

# ✅ AUTH: Authentification utilisateur
from src.models.audit import User
from src.dependencies_keycloak import get_current_user_keycloak, get_optional_current_user_keycloak, require_permission
from src.services.keycloak_service import get_keycloak_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["questionnaires"])


# ——— Helpers ———
def _to_iso(dt) -> Optional[str]:
    try:
        return dt.isoformat() if dt else None
    except Exception:
        return None

def _row_to_questionnaire(row: Any) -> Dict[str, Any]:
    # Colonnes réelles de la table questionnaire (cf. dump)
    # id, name, status, source_type, ai_model, created_at
    return {
        "id": str(row.id),
        "name": row.name,
        "status": getattr(row, "status", None),
        "source_type": getattr(row, "source_type", None),
        "ai_model": getattr(row, "ai_model", None),
        "created_at": _to_iso(getattr(row, "created_at", None)),
    }

def _row_to_question(row: Any, db: Session = None) -> Dict[str, Any]:
    """Convertit une row SQL en dictionnaire de question avec options"""
    question_dict = {
        "id": str(row.id),
        "questionnaire_id": str(row.questionnaire_id),
        "question_text": row.question_text,
        "response_type": getattr(row, "response_type", None),
        "is_required": getattr(row, "is_required", None),
        "help_text": getattr(row, "help_text", None),
        "sort_order": getattr(row, "sort_order", None),
        "ai_generated": getattr(row, "ai_generated", None),
        "control_point_id": str(row.control_point_id) if getattr(row, "control_point_id", None) else None,
        "requirement_id": str(row.requirement_id) if getattr(row, "requirement_id", None) else None,
        "framework_id": str(row.framework_id) if getattr(row, "framework_id", None) else None,
        "chapter": getattr(row, "chapter", None),
    }

    # ✅ Ajouter les options si la question est de type choix
    response_type = getattr(row, "response_type", None)
    if response_type in ["single_choice", "multiple_choice"] and db is not None:
        try:
            options_list = QuestionOptionService.get_options_as_list(db, row.id)
            question_dict["options"] = options_list
        except Exception as e:
            logger.warning(f"Erreur récupération options pour question {row.id}: {e}")
            question_dict["options"] = []
    else:
        question_dict["options"] = []

    return question_dict

def _normalize(s: Optional[str]) -> str:
    import unicodedata
    return unicodedata.normalize("NFKC", (s or "").strip())

def _resolve_questionnaire_id(db: Session, id_or_name: str) -> Optional[str]:
    v = _normalize(id_or_name)
    row = db.execute(text("SELECT id FROM questionnaire WHERE id::text = :v LIMIT 1"), {"v": v}).first()
    if row:
        return str(row.id)
    row = db.execute(text("SELECT id FROM questionnaire WHERE name = :v LIMIT 1"), {"v": v}).first()
    if row:
        return str(row.id)
    row = db.execute(text("SELECT id FROM questionnaire WHERE name ILIKE :v LIMIT 1"), {"v": v}).first()
    if row:
        return str(row.id)
    return None

# ——— Endpoints ———

@router.post("/generate", status_code=status.HTTP_200_OK)
async def generate_questions(
    req: QuestionGenerationRequest,
    current_user: User = Depends(require_permission("QUESTIONNAIRE_CREATE")),
    db: Session = Depends(get_db)
):
    """
    Génère des questions soit à partir d'un framework (exigences),
    soit à partir d'une sélection de points de contrôle.
    """
    # Validation de mode + paramètres
    if req.mode == "framework":
        if not req.framework_id:
            raise HTTPException(status_code=422, detail="framework_id requis pour mode=framework")
        # Charger le framework (facultatif: name/version pour contexte prompt)
        fw = db.execute(
            text("SELECT id, name, version FROM framework WHERE id::text = :fid LIMIT 1"),
            {"fid": req.framework_id},
        ).mappings().first()
        if not fw:
            raise HTTPException(status_code=404, detail="Framework introuvable")

    elif req.mode == "control_points":
        if not req.control_point_ids:
            raise HTTPException(status_code=422, detail="control_point_ids requis pour mode=control_points")
    else:
        raise HTTPException(status_code=422, detail="mode invalide (attendu: framework | control_points)")

    # ✅ REFACTORING: Utilisation du nouveau service modulaire
    service = QuestionGenerationService(db_session=db)

    try:
        questions = await service.generate_questions(req)
        return {"questions": [q.dict() if hasattr(q, "dict") else q for q in questions]}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur pendant la génération de questions")
        raise HTTPException(status_code=500, detail="Erreur interne pendant la génération IA") from e


@router.get("/generate/stream/{framework_id}", status_code=status.HTTP_200_OK)
async def generate_questions_stream(
    framework_id: str,
    request: Request,
    language: str = Query(default="fr"),
    current_user: User = Depends(require_permission("QUESTIONNAIRE_CREATE")),
    db: Session = Depends(get_db)
):
    """
    Endpoint SSE pour la génération de questions avec progression en temps réel.
    Envoie des événements au fur et à mesure de la génération par lots.
    """

    async def event_generator():
        """Générateur d'événements SSE"""
        progress_queue = asyncio.Queue()

        async def progress_callback(batch_idx: int, total_batches: int, status_str: str, data: dict):
            """Callback appelé par le générateur pour chaque progression"""
            event_data = {
                "batch_index": batch_idx,
                "total_batches": total_batches,
                "status": status_str,
                **data
            }
            await progress_queue.put(event_data)

        try:
            # Vérifier que le framework existe
            fw = db.execute(
                text("SELECT id, name, version FROM framework WHERE id::text = :fid LIMIT 1"),
                {"fid": framework_id},
            ).mappings().first()

            if not fw:
                yield f"data: {json.dumps({'error': 'Framework introuvable'})}\n\n"
                return

            # Envoyer l'événement de démarrage
            yield f"data: {json.dumps({'status': 'initializing', 'message': 'Chargement du framework...'})}\n\n"

            # Compter les exigences pour l'événement "loaded"
            req_count_result = db.execute(
                text("SELECT COUNT(*) FROM requirement WHERE framework_id::text = :fid AND is_active = true"),
                {"fid": framework_id}
            ).scalar()
            total_requirements = req_count_result or 0

            # Envoyer l'événement "loaded" avec le nombre d'exigences
            yield f"data: {json.dumps({'status': 'loaded', 'total_requirements': total_requirements})}\n\n"

            # Créer la requête
            from src.schemas.questionnaire import QuestionGenerationRequest
            req = QuestionGenerationRequest(
                mode="framework",
                framework_id=framework_id,
                language=language
            )

            # Initialiser le service
            service = QuestionGenerationService(db_session=db)

            # Lancer la génération dans une tâche séparée
            async def run_generation():
                return await service.generate_questions(req, progress_callback=progress_callback)

            generation_task = asyncio.create_task(run_generation())

            # Envoyer les événements de progression
            while not generation_task.done():
                try:
                    # Attendre un événement avec timeout
                    event_data = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    yield f"data: {json.dumps(event_data)}\n\n"
                except asyncio.TimeoutError:
                    # Vérifier si le client est toujours connecté
                    if await request.is_disconnected():
                        generation_task.cancel()
                        return
                    continue

            # Récupérer le résultat final
            questions = await generation_task

            # Envoyer le résultat final
            final_result = {
                "status": "completed",
                "success": True,
                "questions": [q.dict() if hasattr(q, "dict") else q for q in questions],
                "total_questions": len(questions)
            }
            yield f"data: {json.dumps(final_result)}\n\n"

        except Exception as e:
            logger.error(f"❌ Erreur SSE Questions: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


@router.get("/stats", status_code=status.HTTP_200_OK)
async def questionnaires_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    KPI globaux alignés avec l'ancien contrat.
    """
    try:
        stats_sql = """
        WITH question_stats AS (
          SELECT 
            questionnaire_id,
            COUNT(*) as question_count,
            BOOL_OR(COALESCE(ai_generated, false)) as has_ai_questions
          FROM question 
          WHERE questionnaire_id IS NOT NULL
          GROUP BY questionnaire_id
        )
        SELECT 
          COUNT(q.id) as total_questionnaires,
          COUNT(CASE WHEN q.status = 'published' THEN 1 END) as published_count,
          COALESCE(SUM(qs.question_count), 0) as total_questions,
          COUNT(CASE WHEN qs.has_ai_questions = true THEN 1 END) as ai_generated_count
        FROM questionnaire q
        LEFT JOIN question_stats qs ON qs.questionnaire_id = q.id
        """
        row = db.execute(text(stats_sql)).first()
        return {
            "total": int(row.total_questionnaires or 0),
            "published": int(row.published_count or 0),
            "questions": int(row.total_questions or 0),
            "ai": int(row.ai_generated_count or 0),
        }
    except Exception as e:
        logger.exception("Erreur questionnaires_stats")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e

# LIGNE 96-150 : CONSERVER LA ROUTE GET / (avec stats)
@router.post("/{questionnaire_id}/generate-embeddings", status_code=status.HTTP_200_OK)
async def generate_embeddings(
    questionnaire_id: str,
    db: Session = Depends(get_db)
):
    """
    Génère des embeddings pour toutes les questions d'un questionnaire.
    Les embeddings sont stockés dans la table question_embeddings.
    """
    try:
        # Vérifier que le questionnaire existe
        questionnaire = db.execute(
            text("SELECT id FROM questionnaire WHERE id::text = :qid"),
            {"qid": questionnaire_id}
        ).first()
        
        if not questionnaire:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")
        
        # Récupérer toutes les questions du questionnaire qui n'ont pas encore d'embeddings
        questions = db.execute(
            text("""
                SELECT q.id, q.question_text 
                FROM question q
                LEFT JOIN question_embeddings qe ON q.id = qe.question_id
                WHERE q.questionnaire_id::text = :qid
                AND qe.id IS NULL
            """),
            {"qid": questionnaire_id}
        ).fetchall()
        
        if not questions:
            # Si toutes les questions ont déjà des embeddings, retourner un succès
            total_questions = db.execute(
                text("SELECT COUNT(*) as count FROM question WHERE questionnaire_id::text = :qid"),
                {"qid": questionnaire_id}
            ).scalar()
            
            if total_questions == 0:
                raise HTTPException(status_code=404, detail="Aucune question trouvée pour ce questionnaire")
            
            return {
                "success": True,
                "questionnaire_id": questionnaire_id,
                "embeddings_created": 0,
                "total_questions": total_questions,
                "message": "Toutes les questions ont déjà des embeddings"
            }
        
        # Générer les embeddings pour chaque question
        embeddings_created = 0
        for question in questions:
            # Utiliser un vecteur aléatoire de dimension 1536 (standard pour OpenAI)
            embedding_vector = np.random.rand(1536).tolist()
            
            # Insérer l'embedding dans la base de données
            db.execute(
                text("""
                INSERT INTO question_embeddings 
                (id, question_id, embedding_vector, source_text, created_at, updated_at)
                VALUES (:id, :question_id, :embedding_vector, :source_text, NOW(), NOW())
                """),
                {
                    "id": str(uuid.uuid4()),
                    "question_id": str(question.id),
                    "embedding_vector": embedding_vector,  # Passer directement la liste Python, SQLAlchemy la convertira en array PostgreSQL
                    "source_text": question.question_text
                }
            )
            embeddings_created += 1
        
        # Commit les changements
        db.commit()
        
        return {
            "success": True,
            "questionnaire_id": questionnaire_id,
            "embeddings_created": embeddings_created,
            "total_questions": len(questions)
        }
        
    except Exception as e:
        db.rollback()
        logger.exception(f"Erreur lors de la génération des embeddings: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de la génération des embeddings")

@router.get("/frameworks-eligible", status_code=status.HTTP_200_OK)
async def get_frameworks_eligible_for_generation(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Retourne les référentiels éligibles pour la génération de questions IA.
    
    **CRITÈRES D'ÉLIGIBILITÉ STRICTS :**
    1. Référentiel actif (is_active=true)
    2. Au moins 1 exigence avec embedding
    3. Au moins 1 point de contrôle avec embedding
    """
    try:
        logger.info("📊 Récupération référentiels éligibles (exigences + PC + embeddings)")
        
        query = text("""
            WITH framework_stats AS (
                SELECT
                    f.id                                        AS framework_id,
                    f.code,
                    f.name,
                    f.version,
                    f.publisher,
                    f.language,
                    f.description,
                    f.created_at,
                    
                    -- Exigences
                    COUNT(DISTINCT r.id)                        AS total_requirements,
                    COUNT(DISTINCT re.requirement_id)           AS requirements_with_embeddings,
                    
                    -- Points de contrôle
                    COUNT(DISTINCT rcp.control_point_id)        AS total_control_points,
                    COUNT(DISTINCT cpe.control_point_id)        AS control_points_with_embeddings,
                    
                    -- ✅ CORRECTION : Cast en NUMERIC avant ROUND()
                    CASE 
                        WHEN COUNT(DISTINCT r.id) > 0 
                        THEN ROUND(
                            (COUNT(DISTINCT re.requirement_id)::NUMERIC / COUNT(DISTINCT r.id)::NUMERIC * 100)::NUMERIC,
                            2
                        )
                        ELSE 0 
                    END AS requirements_embeddings_coverage,
                    
                    CASE 
                        WHEN COUNT(DISTINCT rcp.control_point_id) > 0 
                        THEN ROUND(
                            (COUNT(DISTINCT cpe.control_point_id)::NUMERIC / COUNT(DISTINCT rcp.control_point_id)::NUMERIC * 100)::NUMERIC,
                            2
                        )
                        ELSE 0 
                    END AS control_points_embeddings_coverage
                    
                FROM framework f
                
                -- Exigences actives
                LEFT JOIN requirement r 
                    ON r.framework_id = f.id 
                    AND r.is_active = true
                
                -- Embeddings des exigences
                LEFT JOIN requirement_embeddings re 
                    ON re.requirement_id = r.id
                
                -- Liaisons exigences → PC
                LEFT JOIN requirement_control_point rcp 
                    ON rcp.requirement_id = r.id
                
                -- Points de contrôle actifs
                LEFT JOIN control_point cp 
                    ON cp.id = rcp.control_point_id 
                    AND cp.is_active = true
                
                -- Embeddings des PC
                LEFT JOIN control_point_embeddings cpe 
                    ON cpe.control_point_id = cp.id
                
                WHERE f.is_active = true
                
                GROUP BY f.id, f.code, f.name, f.version, f.publisher, f.language, f.description, f.created_at
            )
            SELECT
                framework_id,
                code,
                name,
                version,
                publisher,
                language,
                description,
                created_at,
                total_requirements,
                requirements_with_embeddings,
                total_control_points,
                control_points_with_embeddings,
                requirements_embeddings_coverage,
                control_points_embeddings_coverage
            FROM framework_stats
            WHERE 
                -- ✅ RÈGLE 1 : Au moins 1 exigence avec embedding
                requirements_with_embeddings > 0
                
                -- ✅ RÈGLE 2 : Au moins 1 PC avec embedding
                AND control_points_with_embeddings > 0
            
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        result = db.execute(query, {"limit": limit, "offset": offset}).fetchall()
        
        frameworks = []
        for row in result:
            frameworks.append({
                "id": str(row.framework_id),
                "code": row.code,
                "name": row.name,
                "version": row.version,
                "publisher": row.publisher or "N/A",
                "language": row.language or "fr",
                "description": row.description,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                
                # Statistiques exigences
                "total_requirements": int(row.total_requirements),
                "requirements_with_embeddings": int(row.requirements_with_embeddings),
                "requirements_embeddings_coverage": float(row.requirements_embeddings_coverage),
                
                # Statistiques PC
                "total_control_points": int(row.total_control_points),
                "control_points_with_embeddings": int(row.control_points_with_embeddings),
                "control_points_embeddings_coverage": float(row.control_points_embeddings_coverage),
                
                # Statut global
                "is_fully_embedded": (
                    float(row.requirements_embeddings_coverage) == 100.0 
                    and float(row.control_points_embeddings_coverage) == 100.0
                ),
                "readiness_score": round(
                    (float(row.requirements_embeddings_coverage) + float(row.control_points_embeddings_coverage)) / 2,
                    2
                )
            })
        
        logger.info(f"✅ {len(frameworks)} référentiels éligibles trouvés")
        
        # Compter le total éligible (pour pagination)
        count_query = text("""
            SELECT COUNT(*) AS total
            FROM (
                SELECT f.id
                FROM framework f
                LEFT JOIN requirement r ON r.framework_id = f.id AND r.is_active = true
                LEFT JOIN requirement_embeddings re ON re.requirement_id = r.id
                LEFT JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
                LEFT JOIN control_point cp ON cp.id = rcp.control_point_id AND cp.is_active = true
                LEFT JOIN control_point_embeddings cpe ON cpe.control_point_id = cp.id
                WHERE f.is_active = true
                GROUP BY f.id
                HAVING 
                    COUNT(DISTINCT re.requirement_id) > 0
                    AND COUNT(DISTINCT cpe.control_point_id) > 0
            ) AS eligible
        """)
        
        total_count = db.execute(count_query).scalar() or 0
        
        return {
            "frameworks": frameworks,
            "total": int(total_count),
            "limit": limit,
            "offset": offset,
            "eligibility_criteria": {
                "referentiel_actif": "is_active = true",
                "exigences_avec_embeddings": ">= 1",
                "control_points_avec_embeddings": ">= 1"
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur récupération frameworks éligibles: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur chargement référentiels éligibles: {str(e)}"
        )

@router.get("/", status_code=status.HTTP_200_OK)
# TODO: Réactiver le cache une fois l'authentification optionnelle validée
# @cache_result(ttl=900, key_prefix="questionnaires_list")  # ✅ Cache 15min (données modifiées fréquemment)
async def list_questionnaires(
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    questionnaire_status: Optional[str] = Query(default=None, alias="status", description="Filtrer par statut (draft, published, archived)"),
    activated_for_tenant: Optional[bool] = Query(default=None, description="Si true, ne retourne que les questionnaires activés pour le tenant de l'utilisateur"),
    current_user: Optional[User] = Depends(get_optional_current_user_keycloak),
    db: Session = Depends(get_db),
):
    """Liste des questionnaires avec filtres optionnels par statut et activation tenant"""
    try:
        sql = """
        WITH question_stats AS (
          SELECT
            questionnaire_id,
            COUNT(*) AS question_count,
            BOOL_OR(COALESCE(ai_generated, false)) AS has_ai_questions,
            COUNT(DISTINCT qe.question_id) AS embeddings_count
          FROM question q
          LEFT JOIN question_embeddings qe ON q.id = qe.question_id
          WHERE questionnaire_id IS NOT NULL
          GROUP BY questionnaire_id
        )
        SELECT
          q.id,
          q.name,
          q.status,
          q.created_at,
          q.source_type,
          q.ai_model,
          COALESCE(qs.question_count, 0) AS questions_count,
          COALESCE(qs.has_ai_questions, false) AS ai_generated,
          COALESCE(qs.embeddings_count, 0) AS embeddings_count,
          CASE
            WHEN COALESCE(qs.question_count, 0) > 0 AND COALESCE(qs.embeddings_count, 0) = COALESCE(qs.question_count, 0)
            THEN true
            ELSE false
          END AS has_embeddings
        FROM questionnaire q
        LEFT JOIN question_stats qs ON qs.questionnaire_id = q.id
        {tenant_join}
        WHERE 1=1
        {where}
        ORDER BY q.created_at DESC NULLS LAST, q.name ASC
        LIMIT :limit OFFSET :offset
        """
        params = {"limit": limit, "offset": offset}
        where_clauses = []
        tenant_join = ""

        # Filtre par recherche
        if search:
            where_clauses.append("q.name ILIKE :search")
            params["search"] = f"%{search}%"

        # Filtre par statut
        if questionnaire_status:
            where_clauses.append("q.status = :status")
            params["status"] = questionnaire_status

        # Filtre par activation tenant
        if activated_for_tenant:
            # ✅ Vérifier que l'utilisateur est authentifié
            if not current_user:
                logger.warning("⚠️ Filtrage par tenant demandé mais utilisateur non authentifié")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentification requise pour filtrer par tenant"
                )

            # ✅ Récupérer le tenant_id depuis l'utilisateur connecté
            if not current_user.tenant_id:
                logger.warning(f"⚠️ L'utilisateur {current_user.email} n'a pas de tenant_id")
                return []

            tenant_id = str(current_user.tenant_id)
            params["tenant_id"] = tenant_id
            logger.info(f"🔍 Filtrage questionnaires pour tenant: {tenant_id} (utilisateur: {current_user.email})")

            # Jointure avec organization et organization_questionnaire_activation
            tenant_join = """
            INNER JOIN organization_questionnaire_activation oqa ON q.id = oqa.questionnaire_id
            INNER JOIN organization org ON oqa.org_id = org.id
            """
            where_clauses.append("org.tenant_id::text = :tenant_id")
            where_clauses.append("oqa.active = true")

        where = "AND " + " AND ".join(where_clauses) if where_clauses else ""

        final_sql = sql.format(where=where, tenant_join=tenant_join)
        logger.info(f"🔍 SQL Query: {final_sql}")
        logger.info(f"🔍 Params: {params}")

        rows = db.execute(text(final_sql), params).fetchall()

        logger.info(f"🔍 Rows returned: {len(rows)}")
        if activated_for_tenant and len(rows) == 0:
            logger.warning(f"⚠️ Aucun questionnaire activé trouvé pour tenant_id: {params.get('tenant_id')}")
            # Vérifier s'il y a des activations dans la table
            check_query = text("""
                SELECT COUNT(*) as count
                FROM organization_questionnaire_activation oqa
                INNER JOIN organization org ON oqa.org_id = org.id
                WHERE org.tenant_id::text = :tenant_id AND oqa.active = true
            """)
            check_result = db.execute(check_query, {"tenant_id": params.get('tenant_id')}).fetchone()
            logger.info(f"🔍 Activations trouvées dans la DB: {check_result.count if check_result else 0}")

        return [
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status,
                "source_type": r.source_type,
                "ai_model": r.ai_model,
                "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
                "questions_count": int(getattr(r, "questions_count", 0) or 0),
                "ai_generated": bool(getattr(r, "ai_generated", False)),
                "embeddings_count": int(getattr(r, "embeddings_count", 0) or 0),
                "has_embeddings": bool(getattr(r, "has_embeddings", False)),
            }
            for r in rows
        ]
    except HTTPException:
        # Re-raise HTTPException as-is (401, 404, etc.)
        raise
    except Exception as e:
        logger.exception("Erreur list_questionnaires")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e

@router.get("/{id_or_name}", status_code=status.HTTP_200_OK)
def get_questionnaire(
    id_or_name: str,
    include_questions: bool = Query(False, description="Inclure les questions avec leurs options"),
    language: Optional[str] = Query(None, description="Code langue pour les domaines traduits (en, es, de, it, pt)"),
    db: Session = Depends(get_db)
):
    """
    Récupère un questionnaire par son ID ou son nom.

    Si include_questions=true, inclut toutes les questions avec leurs options.
    """

    try:
        # Vérifie si l'identifiant est un UUID
        from uuid import UUID
        try:
            resolved = str(UUID(id_or_name))
            query = text("""
                SELECT q.id, q.name, q.status, q.source_type, q.ai_model,
                       q.created_at, q.created_by, q.framework_id,
                       COALESCE(q.language_code, 'fr') as language_code,
                       COUNT(que.id) AS questions_count
                FROM questionnaire q
                LEFT JOIN question que ON que.questionnaire_id = q.id
                WHERE q.id = :qid
                GROUP BY q.id
            """)
        except ValueError:
            # Sinon, on recherche par nom
            resolved = id_or_name
            query = text("""
                SELECT q.id, q.name, q.status, q.source_type, q.ai_model,
                       q.created_at, q.created_by, q.framework_id,
                       COALESCE(q.language_code, 'fr') as language_code,
                       COUNT(que.id) AS questions_count
                FROM questionnaire q
                LEFT JOIN question que ON que.questionnaire_id = q.id
                WHERE LOWER(q.name) = LOWER(:qid)
                GROUP BY q.id
            """)

        row = db.execute(query, {"qid": resolved}).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        logger.info(f"✅ Questionnaire trouvé: {row['name']} ({row['questions_count']} questions)")

        result = {
            "id": str(row["id"]),
            "name": row["name"],
            "status": row["status"] or "draft",
            "source_type": row["source_type"] or "manual",
            "ai_model": row["ai_model"],
            "created_at": _to_iso(row["created_at"]),
            "created_by": row["created_by"],
            "framework_id": str(row["framework_id"]) if row["framework_id"] else None,
            "questions_count": int(row["questions_count"] or 0),
            "updated_at": _to_iso(row["created_at"])  # Si pas de updated_at dans la table
        }

        # Inclure les questions si demandé
        if include_questions:
            # Utiliser la langue du paramètre ou la langue du questionnaire
            target_language = language or row["language_code"]

            # Si une langue est spécifiée (ou détectée), utiliser domain_i18n pour les traductions
            if target_language and target_language != 'fr':
                questions_query = text("""
                    SELECT
                        q.id, q.question_text, q.response_type, q.is_required,
                        q.help_text, q.sort_order, q.difficulty_level as criticality_level,
                        q.chapter as category,
                        COALESCE(di.title, d.title) as domain_name
                    FROM question q
                    LEFT JOIN requirement r ON r.id = q.requirement_id
                    LEFT JOIN domain d ON d.id = r.domain_id
                    LEFT JOIN domain_i18n di ON di.domain_id = d.id AND di.language_code = :lang
                    WHERE q.questionnaire_id = :qid
                    ORDER BY q.sort_order
                """)
                questions_rows = db.execute(questions_query, {"qid": row["id"], "lang": target_language}).fetchall()
            else:
                questions_query = text("""
                    SELECT
                        q.id, q.question_text, q.response_type, q.is_required,
                        q.help_text, q.sort_order, q.difficulty_level as criticality_level,
                        q.chapter as category,
                        d.title as domain_name
                    FROM question q
                    LEFT JOIN requirement r ON r.id = q.requirement_id
                    LEFT JOIN domain d ON d.id = r.domain_id
                    WHERE q.questionnaire_id = :qid
                    ORDER BY q.sort_order
                """)
                questions_rows = db.execute(questions_query, {"qid": row["id"]}).fetchall()

            questions = []
            for q_row in questions_rows:
                # Utiliser domain_name en priorité, sinon category, sinon "Sans catégorie"
                domain = q_row.domain_name or q_row.category or "Sans catégorie"

                question_dict = {
                    "id": str(q_row.id),
                    "question_text": q_row.question_text,
                    "response_type": q_row.response_type,
                    "is_required": q_row.is_required,
                    "help_text": q_row.help_text,
                    "sort_order": q_row.sort_order,
                    "criticality_level": q_row.criticality_level,
                    "category": q_row.category,
                    "domain": domain,  # Domaine du requirement ou fallback
                    "options": []
                }

                # Récupérer les options pour cette question
                if q_row.response_type in ["single_choice", "multiple_choice"]:
                    if target_language and target_language != 'fr':
                        # Utiliser option_i18n pour les traductions
                        options_query = text("""
                            SELECT
                                COALESCE(oi.translated_value, o.default_value, qo.custom_value) as option_value,
                                qo.sort_order
                            FROM question_option qo
                            LEFT JOIN option o ON o.id = qo.option_id
                            LEFT JOIN option_i18n oi ON oi.option_id = o.id AND oi.language_code = :lang
                            WHERE qo.question_id = :qid
                            ORDER BY qo.sort_order
                        """)
                        options_rows = db.execute(options_query, {"qid": q_row.id, "lang": target_language}).fetchall()
                    else:
                        # Version française (par défaut)
                        options_query = text("""
                            SELECT
                                COALESCE(o.default_value, qo.custom_value) as option_value,
                                qo.sort_order
                            FROM question_option qo
                            LEFT JOIN option o ON o.id = qo.option_id
                            WHERE qo.question_id = :qid
                            ORDER BY qo.sort_order
                        """)
                        options_rows = db.execute(options_query, {"qid": q_row.id}).fetchall()

                    question_dict["options"] = [opt.option_value for opt in options_rows]

                questions.append(question_dict)

            result["questions"] = questions
            logger.info(f"✅ {len(questions)} questions chargées avec options")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ Erreur get_questionnaire: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erreur interne: {str(e)}")


# Route frameworks-eligible déplacée plus haut dans le fichier

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_questionnaire(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Création simple d'un questionnaire. Attendu minimal : name.
    """
    try:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Champ 'name' requis")

        # Vérif unicité
        exists = db.execute(
            text("SELECT 1 FROM questionnaire WHERE name = :n LIMIT 1"),
            {"n": name},
        ).first()
        if exists:
            raise HTTPException(status_code=409, detail="Un questionnaire avec ce nom existe déjà")

        row = db.execute(
            text(
                """
                INSERT INTO questionnaire (name, status, source_type, ai_model)
                VALUES (:name, :status, :source_type, :ai_model)
                RETURNING id, name, status, source_type, ai_model, created_at
                """
            ),
            {
                "name": name,
                "status": payload.get("status"),
                "source_type": payload.get("source_type"),
                "ai_model": payload.get("ai_model"),
            },
        ).first()

        db.commit()
        return _row_to_questionnaire(row)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Erreur create_questionnaire")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e


@router.put("/{questionnaire_id}", status_code=status.HTTP_200_OK)
async def update_questionnaire(
    questionnaire_id: str,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Mise à jour d'un questionnaire (par ID UUID).
    """
    try:
        # On force un WHERE par id::text pour ne pas accepter un name ici
        exists = db.execute(
            text("SELECT 1 FROM questionnaire WHERE id::text = :i LIMIT 1"),
            {"i": questionnaire_id},
        ).first()
        if not exists:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        row = db.execute(
            text(
                """
                UPDATE questionnaire
                SET
                    name = COALESCE(:name, name),
                    status = COALESCE(:status, status),
                    source_type = COALESCE(:source_type, source_type),
                    ai_model = COALESCE(:ai_model, ai_model)
                WHERE id::text = :i
                RETURNING id, name, status, source_type, ai_model, created_at
                """
            ),
            {
                "i": questionnaire_id,
                "name": payload.get("name"),
                "status": payload.get("status"),
                "source_type": payload.get("source_type"),
                "ai_model": payload.get("ai_model"),
            },
        ).first()
        db.commit()
        return _row_to_questionnaire(row)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Erreur update_questionnaire")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e


@router.delete("/{questionnaire_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_questionnaire(
    questionnaire_id: str,
    db: Session = Depends(get_db),
):
    """
    Suppression d'un questionnaire par ID UUID.
    Vérifie d'abord qu'il n'est pas utilisé dans un audit ou activé pour une organisation.
    """
    try:
        # Vérifier si le questionnaire existe
        exists = db.execute(
            text("SELECT id FROM questionnaire WHERE id::text = :i"),
            {"i": questionnaire_id}
        ).first()

        if not exists:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        # Vérifier s'il est utilisé dans des audits
        audit_count = db.execute(
            text("SELECT COUNT(*) as count FROM audit WHERE questionnaire_id::text = :i"),
            {"i": questionnaire_id}
        ).first()

        if audit_count and audit_count.count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de supprimer : ce questionnaire est utilisé dans {audit_count.count} audit(s)"
            )

        # Vérifier s'il est activé pour des organisations
        org_activation_count = db.execute(
            text("SELECT COUNT(*) as count FROM organization_questionnaire_activation WHERE questionnaire_id::text = :i"),
            {"i": questionnaire_id}
        ).first()

        if org_activation_count and org_activation_count.count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de supprimer : ce questionnaire est activé pour {org_activation_count.count} organisation(s)"
            )

        # Si tout est ok, supprimer le questionnaire
        # Note: Les CASCADE définis au niveau DB suppriment automatiquement:
        # - question (via questionnaire FK)
        # - question_embeddings (via question FK)
        # - question_control_point (via question FK)
        # Pas besoin de désactiver les triggers qui empêcheraient le CASCADE de fonctionner

        # Supprimer le questionnaire (les cascades font le reste)
        deleted = db.execute(
            text("DELETE FROM questionnaire WHERE id::text = :i RETURNING id"),
            {"i": questionnaire_id},
        ).first()

        db.commit()
        return

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Erreur delete_questionnaire")
        raise HTTPException(status_code=500, detail=str(e)) from e

# ============================================================================
# NOTE: La fonction duplicate_questionnaire a été déplacée vers
# questionnaires_duplicate.py pour utiliser la nouvelle architecture i18n
# ============================================================================

@router.get("/{id_or_name}/questions")
async def get_questionnaire_questions(id_or_name: str, db: Session = Depends(get_db)):
    """
    Récupère les questions avec enrichissement domain/subdomain via hiérarchie récursive
    """
    try:
        resolved = _resolve_questionnaire_id(db, id_or_name)
        if not resolved:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        # ✅ Requête avec hiérarchie domain récursive + domain_title
        query = text("""
            WITH RECURSIVE dom_hierarchy AS (
                -- Niveau 0 : domaines racines
                SELECT
                    d.id,
                    d.parent_id,
                    d.code,
                    COALESCE(dt.title, d.title, d.code) AS name,
                    0 AS depth,
                    ARRAY[d.id] AS path_ids,
                    COALESCE(dt.title, d.title, d.code) AS root_name
                FROM domain d
                LEFT JOIN domain_title dt 
                    ON dt.domain_id = d.id 
                    AND dt.language = 'fr' 
                    AND dt.is_primary = true
                WHERE d.parent_id IS NULL OR d.level = 0
                
                UNION ALL
                
                -- Niveaux suivants : sous-domaines
                SELECT
                    c.id,
                    c.parent_id,
                    c.code,
                    COALESCE(ct.title, c.title, c.code) AS name,
                    p.depth + 1,
                    p.path_ids || c.id,
                    p.root_name
                FROM domain c
                JOIN dom_hierarchy p ON c.parent_id = p.id
                LEFT JOIN domain_title ct 
                    ON ct.domain_id = c.id 
                    AND ct.language = 'fr' 
                    AND ct.is_primary = true
            )
            SELECT
                q.id,
                q.questionnaire_id,
                q.question_text,
                q.response_type,
                q.is_required,
                q.help_text,
                q.estimated_time_minutes,
                q.sort_order,
                q.ai_generated,
                q.control_point_id,
                q.requirement_id,
                q.framework_id,

                -- Enrichissement depuis requirement
                r.official_code AS requirement_code,
                r.domain_id,

                -- Domain (niveau le plus profond = subdomain)
                dh.name AS subdomain_name,
                dh.code AS subdomain_code,

                -- Domain parent (racine = domain principal)
                dh.root_name AS domain_name,
                dh.depth
                
            FROM question q
            
            -- JOIN requirement
            LEFT JOIN requirement r 
                ON r.id = q.requirement_id
                AND r.is_active = true
            
            -- JOIN hiérarchie domain
            LEFT JOIN dom_hierarchy dh 
                ON dh.id = r.domain_id
            
            WHERE q.questionnaire_id = :qid
            AND q.is_active = true
            
            ORDER BY q.sort_order ASC, q.created_at ASC
        """)

        rows = db.execute(query, {"qid": resolved}).fetchall()

        # ✅ Construire la liste des questions avec options
        questions = []
        for r in rows:
            # Récupérer les options pour les types choix
            options_list = []
            if r.response_type in ["single_choice", "multiple_choice"]:
                try:
                    options_list = QuestionOptionService.get_options_as_list(db, r.id)
                except Exception as e:
                    logger.warning(f"Erreur récupération options pour question {r.id}: {e}")

            questions.append({
                "id": str(r.id),
                "questionnaire_id": str(r.questionnaire_id),
                "question_text": r.question_text,
                "response_type": r.response_type or "text",
                "is_required": bool(r.is_required),
                "help_text": r.help_text,
                "estimated_time_minutes": int(r.estimated_time_minutes) if r.estimated_time_minutes else None,
                "sort_order": int(r.sort_order or 0),
                "ai_generated": bool(r.ai_generated),
                "control_point_id": str(r.control_point_id) if r.control_point_id else None,
                "requirement_id": str(r.requirement_id) if r.requirement_id else None,
                "requirement_code": r.requirement_code,
                "framework_id": str(r.framework_id) if r.framework_id else None,
                "domain_id": str(r.domain_id) if r.domain_id else None,

                # ✅ Logique hiérarchique
                "domain": r.domain_name if r.domain_name else None,
                "subdomain": r.subdomain_name if (r.depth and r.depth > 0) else None,

                "options": options_list,  # ✅ Options réelles depuis question_option
                "validation_rules": {}
            })

        return questions

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur get_questionnaire_questions")
        raise HTTPException(status_code=500, detail="Erreur serveur")


@router.get("/{id_or_name}/questions-with-control-points")
async def get_questionnaire_questions_with_control_points(
    id_or_name: str,
    db: Session = Depends(get_db)
):
    """
    Récupère les questions d'un questionnaire avec leurs points de contrôle associés.

    Utilisé pour le modal de sélection de question dans la création d'actions.
    Retourne les questions groupées par domaine avec les control points liés.
    """
    try:
        resolved = _resolve_questionnaire_id(db, id_or_name)
        if not resolved:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        # Requête pour récupérer TOUTES les questions du questionnaire
        # avec leur domaine (via requirement → domain)
        # Pattern identique à campaigns/questions-with-control-points
        query = text("""
            SELECT
                q.id AS question_id,
                q.question_text,
                q.question_code,
                q.chapter,
                r.title AS requirement_title,
                COALESCE(d.code_officiel, d.code) AS domain_name
            FROM question q
            LEFT JOIN requirement r ON q.requirement_id = r.id
            LEFT JOIN domain d ON r.domain_id = d.id
            WHERE q.questionnaire_id = :qid
              AND q.is_active = true
            ORDER BY q.sort_order, q.question_code
        """)

        rows = db.execute(query, {"qid": resolved}).fetchall()

        # Récupérer les control points pour chaque question via question_control_point
        questions = []
        for r in rows:
            question_id = str(r.question_id)

            # Récupérer les control points liés à cette question
            cp_query = text("""
                SELECT
                    cp.id,
                    cp.code AS control_id,
                    cp.name AS title,
                    f.name AS referential_name,
                    f.code AS referential_code
                FROM question_control_point qcp
                JOIN control_point cp ON cp.id = qcp.control_point_id
                LEFT JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
                LEFT JOIN requirement req ON req.id = rcp.requirement_id
                LEFT JOIN framework f ON f.id = req.framework_id
                WHERE qcp.question_id = CAST(:question_id AS uuid)
            """)
            cp_rows = db.execute(cp_query, {"question_id": question_id}).fetchall()

            control_points = [
                {
                    "id": str(cp.id),
                    "control_id": cp.control_id or "",
                    "title": cp.title or "",
                    "referential_name": cp.referential_name or "",
                    "referential_code": cp.referential_code or ""
                }
                for cp in cp_rows
            ]

            questions.append({
                "id": question_id,
                "question_text": r.question_text,
                "question_code": r.question_code or "",
                "chapter": r.chapter or "",
                "requirement_title": r.requirement_title or "",
                "domain_name": r.domain_name or "Sans domaine",
                "control_points": control_points
            })

        return {"questions": questions, "total": len(questions)}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur get_questionnaire_questions_with_control_points")
        raise HTTPException(status_code=500, detail="Erreur serveur")


@router.get("/{id_or_name}/domains")
async def get_questionnaire_domains(
    id_or_name: str,
    language: Optional[str] = Query("fr", description="Code langue pour traductions"),
    db: Session = Depends(get_db)
):
    """
    Récupère les domaines uniques d'un questionnaire.

    Retourne tous les domaines (incluant sous-domaines) associés aux questions du questionnaire
    via la relation question → requirement → domain.
    """
    try:
        resolved = _resolve_questionnaire_id(db, id_or_name)
        if not resolved:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        # Requête avec hiérarchie domain récursive
        query = text("""
            WITH RECURSIVE dom_hierarchy AS (
                -- Niveau 0 : domaines racines
                SELECT
                    d.id,
                    d.parent_id,
                    d.code,
                    COALESCE(dt.title, d.title, d.code) AS name,
                    d.description,
                    0 AS level,
                    d.framework_id
                FROM domain d
                LEFT JOIN domain_title dt
                    ON dt.domain_id = d.id
                    AND dt.language = :lang
                    AND dt.is_primary = true
                WHERE d.parent_id IS NULL OR d.level = 0

                UNION ALL

                -- Niveaux suivants : sous-domaines
                SELECT
                    c.id,
                    c.parent_id,
                    c.code,
                    COALESCE(ct.title, c.title, c.code) AS name,
                    c.description,
                    p.level + 1,
                    c.framework_id
                FROM domain c
                JOIN dom_hierarchy p ON c.parent_id = p.id
                LEFT JOIN domain_title ct
                    ON ct.domain_id = c.id
                    AND ct.language = :lang
                    AND ct.is_primary = true
            )
            SELECT DISTINCT
                dh.id,
                dh.code,
                dh.name,
                dh.description,
                dh.level,
                dh.parent_id,
                dh.framework_id,
                COUNT(DISTINCT q.id) AS questions_count
            FROM question q
            INNER JOIN requirement r ON r.id = q.requirement_id
            INNER JOIN dom_hierarchy dh ON dh.id = r.domain_id
            WHERE q.questionnaire_id = :qid
              AND q.is_active = true
            GROUP BY dh.id, dh.code, dh.name, dh.description, dh.level, dh.parent_id, dh.framework_id
            ORDER BY dh.level, dh.name
        """)

        rows = db.execute(query, {"qid": resolved, "lang": language}).fetchall()

        return [
            {
                "id": str(r.id),
                "code": r.code,
                "name": r.name,
                "description": r.description,
                "level": int(r.level),
                "parent_id": str(r.parent_id) if r.parent_id else None,
                "framework_id": str(r.framework_id) if r.framework_id else None,
                "questions_count": int(r.questions_count)
            }
            for r in rows
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erreur get_questionnaire_domains")
        raise HTTPException(status_code=500, detail="Erreur serveur")

@router.post("/{id_or_name}/questions", status_code=status.HTTP_201_CREATED)
async def create_question_for_questionnaire(
    id_or_name: str,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Crée une question pour un questionnaire"""
    try:
        logger.info(f"📥 Création question pour questionnaire: {id_or_name}")
        
        qid = _resolve_questionnaire_id(db, id_or_name)
        if not qid:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        question_text = (payload.get("question_text") or "").strip()
        if not question_text:
            raise HTTPException(status_code=400, detail="Champ 'question_text' requis")

        # Récupérer les liens
        requirement_id = payload.get("requirement_id")
        control_point_id = payload.get("control_point_id")
        framework_id = payload.get("framework_id")
        
        # Si requirement_id fourni, récupérer framework_id
        if requirement_id and not framework_id:
            fw_query = text("""
                SELECT framework_id 
                FROM requirement 
                WHERE id = :req_id
                LIMIT 1
            """)
            fw_result = db.execute(fw_query, {"req_id": requirement_id}).first()
            if fw_result:
                framework_id = str(fw_result.framework_id)
        
        # Si requirement_id fourni SANS control_point_id, chercher un PC lié
        if requirement_id and not control_point_id:
            cp_query = text("""
                SELECT control_point_id 
                FROM requirement_control_point 
                WHERE requirement_id = :req_id
                LIMIT 1
            """)
            cp_result = db.execute(cp_query, {"req_id": requirement_id}).first()
            if cp_result:
                control_point_id = str(cp_result.control_point_id)

        # ✅ NOUVEAU : Générer question_code et chapter automatiquement
        question_code = None
        chapter = None
        
        if requirement_id and framework_id:
            # Récupérer les infos de l'exigence et du framework
            req_info_query = text("""
                WITH RECURSIVE domain_hierarchy AS (
                    -- Niveau 0 : domaines racines
                    SELECT 
                        d.id,
                        d.parent_id,
                        d.level,
                        COALESCE(
                            (SELECT dt.title FROM domain_title dt 
                             WHERE dt.domain_id = d.id AND dt.is_primary = true AND dt.language = 'fr' 
                             LIMIT 1),
                            d.code
                        ) AS domain_name,
                        ARRAY[d.id] AS path
                    FROM domain d
                    WHERE d.parent_id IS NULL
                    
                    UNION ALL
                    
                    -- Sous-domaines récursifs
                    SELECT 
                        d.id,
                        d.parent_id,
                        d.level,
                        COALESCE(
                            (SELECT dt.title FROM domain_title dt 
                             WHERE dt.domain_id = d.id AND dt.is_primary = true AND dt.language = 'fr' 
                             LIMIT 1),
                            d.code
                        ) AS domain_name,
                        dh.path || d.id
                    FROM domain d
                    INNER JOIN domain_hierarchy dh ON d.parent_id = dh.id
                )
                SELECT 
                    r.official_code,
                    f.code AS framework_code,
                    dh.domain_name,
                    dh.level,
                    (SELECT dh2.domain_name 
                     FROM domain_hierarchy dh2 
                     WHERE dh2.id = ANY(dh.path) AND dh2.level = 0 
                     LIMIT 1) AS root_domain
                FROM requirement r
                INNER JOIN framework f ON f.id = r.framework_id
                LEFT JOIN domain_hierarchy dh ON dh.id = r.domain_id
                WHERE r.id = :req_id
                LIMIT 1
            """)
            
            req_info = db.execute(req_info_query, {"req_id": requirement_id}).first()
            
            if req_info:
                # Générer question_code
                framework_code = req_info.framework_code or "GENERIC"
                official_code = (req_info.official_code or "000").replace(".", "")
                
                # Compter combien de questions existent déjà pour cette exigence
                count_query = text("""
                    SELECT COUNT(*) AS count
                    FROM question
                    WHERE requirement_id = :req_id
                """)
                count_result = db.execute(count_query, {"req_id": requirement_id}).scalar()
                question_number = (count_result or 0) + 1
                
                question_code = f"Q-{framework_code}-{official_code}-{question_number:03d}"
                
                # Déterminer chapter (domaine racine)
                if req_info.level == 0 or req_info.level is None:
                    chapter = req_info.domain_name
                else:
                    chapter = req_info.root_domain or req_info.domain_name
                
                logger.info(f"✅ Généré: question_code={question_code}, chapter={chapter}")

        # ✅ Préparer les données de la question (incluant les options)
        question_data = {
            "questionnaire_id": qid,
            "question_text": question_text,
            "question_code": question_code,
            "chapter": chapter,
            "response_type": payload.get("response_type", "open"),
            "is_required": payload.get("is_required", False),
            "help_text": payload.get("help_text"),
            "sort_order": payload.get("sort_order", 0),
            "ai_generated": payload.get("ai_generated", False),
            "control_point_id": control_point_id,
            "requirement_id": requirement_id,
            "framework_id": framework_id,
            "difficulty_level": payload.get("difficulty_level", "basic"),
            "estimated_time_minutes": payload.get("estimated_time_minutes", 5),
            "created_by": payload.get("created_by", "human"),
            "options": payload.get("options", [])  # ✅ Gérer les options
        }

        # ✅ Utiliser le helper pour créer la question avec options
        question = save_question_with_options(db, question_data, commit=True)

        logger.info(f"✅ Question créée: {question.id}")

        # Récupérer les options pour la réponse
        options_list = []
        if question.response_type in ["single_choice", "multiple_choice"]:
            options_list = QuestionOptionService.get_options_as_list(db, question.id)
        
        # ✅ Retourner avec question_code, chapter ET options
        return {
            "id": str(question.id),
            "questionnaire_id": str(question.questionnaire_id),
            "question_text": question.question_text,
            "question_code": question.question_code,
            "chapter": question.chapter,
            "response_type": question.response_type,
            "is_required": bool(question.is_required),
            "help_text": question.help_text,
            "sort_order": question.sort_order,
            "ai_generated": bool(question.ai_generated),
            "control_point_id": str(question.control_point_id) if question.control_point_id else None,
            "requirement_id": str(question.requirement_id) if question.requirement_id else None,
            "framework_id": str(question.framework_id) if question.framework_id else None,
            "difficulty_level": question.difficulty_level,
            "estimated_time_minutes": question.estimated_time_minutes,
            "created_by": question.created_by,
            "created_at": question.created_at.isoformat() if question.created_at else None,
            "options": options_list  # ✅ Retourner les options
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur create_question: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

@router.post("/create-from-generation", status_code=status.HTTP_201_CREATED)
async def create_from_generation(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    Sauvegarde un questionnaire + questions ; si control_point_id manquant mais requirement_ids présent,
    résout via requirement_control_point. En cas de multiples CPs, choisit par heuristique simple.
    Ajout : si requirement_ids est absent, on tente de l'inférer depuis question.id / requirement_code / etc.
    """
    import os, json, re
    from typing import Any, Dict, List
    from sqlalchemy import text

    # 🚨 LOG IMMEDIAT pour confirmer que l'endpoint est appelé
    print("\n" + "="*80)
    print("🚨 ENDPOINT /create-from-generation APPELE")
    print(f"🚨 Nombre de questions reçues: {len(payload.get('questions', []))}")
    if payload.get('questions') and len(payload.get('questions')) > 0:
        first_q = payload['questions'][0]
        print(f"🚨 Première question help_text: '{first_q.get('help_text')}'")
        print(f"🚨 Première question question_text: '{first_q.get('question_text', first_q.get('text'))}'")
    print("="*80 + "\n")

    # ---------- helpers locaux ----------
    def normalize_jsonlike(val: Any, fallback: Any):
        if val is None:
            return fallback
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return fallback
            try:
                return json.loads(s)
            except Exception:
                return fallback
        return fallback

    def normalize_response_type(rt: Any) -> str:
        """Normalise le type de réponse vers les valeurs valides de question_type"""
        v = str(rt or "open").strip().lower()

        # Mapping vers les types valides de la table question_type
        type_mapping = {
            # Types valides
            "boolean": "boolean",
            "single_choice": "single_choice",
            "multiple_choice": "multiple_choice",
            "open": "open",
            "rating": "rating",
            "number": "number",
            "date": "date",
            # Alias IA
            "yes_no": "boolean",
            "yesno": "boolean",
            "bool": "boolean",
            "text": "open",
            "textarea": "open",
            "single": "single_choice",
            "multiple": "multiple_choice",
            "multi_choice": "multiple_choice",  # ✅ CORRECTION : était inversé !
            "multi": "multiple_choice",
            "checkbox": "multiple_choice",
            "radio": "single_choice",
            "likert": "rating",
        }

        return type_mapping.get(v, "open")

    def estimate_time_by_type(rt: str) -> int:
        table = {
            "yes_no": 2, "boolean": 2, "single_choice": 3, "multi_choice": 4,
            "number": 3, "date": 2, "text": 4, "textarea": 7, "rating": 4,
        }
        return table.get(rt, 5)

    def fetch_cps_for_reqs(req_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        if not req_ids:
            return {}
        q = text("""
            SELECT
                rcp.requirement_id AS rid,
                cp.id               AS cp_id,
                cp.code             AS cp_code,
                cp.name             AS cp_name,
                cp.description      AS cp_desc
            FROM requirement_control_point rcp
            JOIN control_point cp ON cp.id = rcp.control_point_id
            WHERE rcp.requirement_id IN :rid_list
              AND cp.is_active = true
        """)
        rows = db.execute(q, {"rid_list": tuple(req_ids)}).mappings().all()
        m: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            rid = str(r["rid"])
            m.setdefault(rid, []).append({
                "id": str(r["cp_id"]),
                "code": r["cp_code"],
                "name": r["cp_name"],
                "description": r["cp_desc"],
            })
        return m  # ta logique actuelle pour mapper req→CP. :contentReference[oaicite:1]{index=1}

    def pick_best_cp(question_text: str, candidates: List[Dict[str, Any]]) -> Optional[str]:
        if not candidates:
            return None
        qt = (question_text or "").lower()
        if not qt:
            return candidates[0]["id"]
        def score(cp: Dict[str, Any]) -> float:
            s = f"{cp.get('name','')} {cp.get('description','')}".lower()
            pts = 0.0
            for term in ["auth", "mfa", "pwd", "backup", "sauvegarde", "journal", "log",
                         "incident", "patch", "vpn", "firewall", "antivirus", "chiffrement", "encrypt"]:
                if term in qt and term in s:
                    pts += 1.0
            qw, sw = set(qt.split()), set(s.split())
            if qw and sw:
                pts += len(qw & sw) / max(1, len(qw | sw))
            return pts
        best = max(candidates, key=score)
        return best["id"]  # ta heuristique existante. :contentReference[oaicite:2]{index=2}

    # ---------- helpers d’inférence requirement ----------
    def _extract_requirement_code(raw: str) -> Optional[str]:
        """
        Extrait un code d'exigence plausible depuis un id/label/code de question.
        Exemples :
          "7.2.d)-1"   -> "7.2.d)"
          "A.12.4.1-5" -> "A.12.4.1"
          "AC-03.2"    -> "AC-03.2"
        """
        if not raw:
            return None
        s = str(raw).strip()
        # couper suffixe -NN éventuel
        s = re.sub(r"-\d+\s*$", "", s)
        # normaliser espaces
        s = re.sub(r"\s+", "", s)

        # patterns fréquents
        m = re.search(r"([A-Za-z]{1,3}(?:\.[A-Za-z0-9]{1,3})+(?:\))?)", s)
        if m:
            return m.group(1)
        m = re.search(r"(\d+(?:\.\d+)+(?:\.[a-z]\))?)", s, flags=re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r"([A-Z]{1,3}-\d{2}(?:\.\d)?)", s)
        if m:
            return m.group(1)
        return None

    def _infer_requirement_ids_from_db(db: Session, framework_id: Optional[str], q: dict) -> List[str]:
        """
        Si la question n’a pas requirement_ids, on tente :
          - requirement_id fourni non-UUID => traité comme code
          - sinon question.id / question.code => extraire un code
        Puis lookup requirement.id pour ce framework.
        """
        if not framework_id:
            return []

        # collecter des sources possibles
        candidates_raw: List[str] = []
        for k in ("requirement_id", "requirement_code", "rid", "id", "code"):
            v = q.get(k)
            if v:
                candidates_raw.append(str(v))

        # si déjà un UUID clair, on le renvoie
        for raw in candidates_raw:
            if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", raw, flags=re.IGNORECASE):
                return [raw]

        # extraire un code ; s’arrête au premier qui matche
        code = None
        for raw in candidates_raw:
            code = _extract_requirement_code(raw)
            if code:
                break
        if not code:
            return []

        # lookup DB par official_code (et fallback LIKE sur le name)
        qtxt = text("""
            SELECT id
            FROM requirement
            WHERE framework_id = :fw
              AND (
                    lower(official_code) = lower(:code)
                 OR lower(replace(official_code, ' ', '')) = lower(replace(:code, ' ', ''))
                 OR lower(name) LIKE lower(:like_code)
              )
            ORDER BY (CASE WHEN lower(official_code) = lower(:code) THEN 0 ELSE 1 END),
                     length(official_code) ASC
            LIMIT 1
        """)
        row = db.execute(qtxt, {"fw": framework_id, "code": code, "like_code": f"%{code}%"}).first()
        return [str(row.id)] if row else []

    try:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Le nom du questionnaire est obligatoire")

        source_type = (payload.get("source_type") or "framework").strip()
        framework_id = payload.get("framework_id")
        control_point_ids = payload.get("control_point_ids") or []
        if source_type == "framework" and not framework_id:
            raise HTTPException(status_code=400, detail="framework_id est requis pour source_type=framework")
        if source_type == "control_points" and not control_point_ids:
            raise HTTPException(status_code=400, detail="control_point_ids est requis pour source_type=control_points")

        ai_model = (
            payload.get("ai_model")
            or os.getenv("OLLAMA_MODEL")
            or os.getenv("AI_MODEL")
            or "ollama-unknown"
        )

        # --- créer le questionnaire
        row = db.execute(text("""
            INSERT INTO questionnaire (name, status, source_type, ai_model, framework_id)
            VALUES (:name, :status, :source_type, :ai_model, :framework_id)
            RETURNING id
        """), {
            "name": name,
            "status": payload.get("status", "draft"),
            "source_type": source_type,
            "ai_model": ai_model,
            "framework_id": framework_id,
        }).first()
        questionnaire_id = str(row.id)

        # --- préparation mapping req→CP (si besoin)
        questions: List[Dict[str, Any]] = payload.get("questions") or []

        # ✅ SI génération depuis framework, récupérer TOUS les requirements du framework
        framework_requirements = []
        if source_type == "framework" and framework_id:
            req_query = text("""
                SELECT id, official_code, chapter_path
                FROM requirement
                WHERE framework_id = :framework_id
                ORDER BY official_code
            """)
            req_result = db.execute(req_query, {"framework_id": framework_id})
            framework_requirements = [{"id": str(row.id), "code": row.official_code, "chapter": row.chapter_path}
                                     for row in req_result]

        all_req_ids: set[str] = set()
        for q in questions:
            for rid in q.get("requirement_ids", []) or []:
                if str(rid).strip():
                    all_req_ids.add(str(rid).strip())

        # Ajouter les IDs des requirements du framework
        for req in framework_requirements:
            all_req_ids.add(req["id"])

        cp_by_req = fetch_cps_for_reqs(list(all_req_ids)) if all_req_ids else {}

        # --- insertion des questions (ta structure actuelle)
        insert_question = text("""
            INSERT INTO question (
                questionnaire_id, question_text, response_type, is_required,
                validation_rules, help_text, evidence_types, difficulty_level,
                estimated_time_minutes, sort_order, created_by, ai_generated,
                is_active, ai_model, ai_confidence, control_point_id, framework_id,
                requirement_id, upload_conditions, generation_source_type, generation_source_ids, generation_source,
                question_code, chapter, tags
            ) VALUES (
                :questionnaire_id, :question_text, :response_type, :is_required,
                :validation_rules, :help_text, :evidence_types, :difficulty_level,
                :estimated_time_minutes, :sort_order, :created_by, :ai_generated,
                true, :ai_model, :ai_confidence, :control_point_id, :framework_id,
                :requirement_id, :upload_conditions, :generation_source_type, :generation_source_ids, :generation_source,
                :question_code, :chapter, :tags
            )
            RETURNING id
        """)  # ✅ AJOUTÉ : RETURNING id pour récupérer l'ID de la question insérée

        auto_assign_idx = 0
        requirement_assign_idx = 0  # ✅ Index pour distribuer les questions sur les requirements
        gen_src_ids: List[str] = [framework_id] if (source_type == "framework" and framework_id) else list(control_point_ids)

        # 🔍 DEBUG : Logger la première question pour voir le payload
        if questions and len(questions) > 0:
            logger.info(f"🔍 DEBUG - Première question reçue : {json.dumps(questions[0], indent=2, ensure_ascii=False)}")

        for idx, q in enumerate(questions):
            q_text = (q.get("question_text") or q.get("text") or "").strip()
            if not q_text:
                continue

            rtype = normalize_response_type(q.get("response_type") or q.get("type"))
            # ✅ Fallback sur is_mandatory si is_required absent (l'IA génère "is_mandatory")
            is_req = bool(q.get("is_required") if q.get("is_required") is not None else q.get("is_mandatory", True))

            # 🔍 DEBUG AVANT extraction
            if idx == 0:
                print(f"\n🔍 DEBUG Q1 - help_text RAW depuis payload: '{q.get('help_text')}'")
                print(f"🔍 DEBUG Q1 - rationale RAW depuis payload: '{q.get('rationale')}'")

            # ✅ Récupérer help_text avec fallback sur rationale, en gérant les chaînes vides
            help_t = (q.get("help_text") or "").strip() or (q.get("rationale") or "").strip() or ""
            diff = str(q.get("difficulty") or q.get("difficulty_level") or "medium")
            aiconf = float(q.get("ai_confidence") or 0.8)

            # 🔍 DEBUG APRES extraction
            if idx == 0:
                print(f"🔍 DEBUG Q1 - help_text FINAL à insérer: '{help_t}' (longueur: {len(help_t)})")
                print(f"🔍 DEBUG Q1 - difficulty depuis payload: '{q.get('difficulty')}'")
                print(f"🔍 DEBUG Q1 - difficulty_level depuis payload: '{q.get('difficulty_level')}'")
                print(f"🔍 DEBUG Q1 - diff FINAL à insérer: '{diff}'\n")
            validation_rules = normalize_jsonlike(q.get("validation_rules"), {})
            evidence_types = normalize_jsonlike(q.get("evidence_types"), [])

            # options -> validation_rules si choix
            if q.get("options") and rtype in ("single_choice", "multiple_choice"):
                validation_rules["options"] = q.get("options")

            # échelle rating par défaut
            if rtype == "rating" and "rating_scale" not in validation_rules:
                validation_rules["rating_scale"] = {
                    "min": 1, "max": 5,
                    "labels": ["Non démarré","Initial","Répétable","Défini","Géré"]
                }

            upload_conds = q.get("upload_conditions")
            tmin = int(q.get("estimated_time_minutes") or estimate_time_by_type(rtype))

            # ✅ Nouveaux champs enrichis
            question_code = q.get("question_code")  # Code standardisé (ex: "ISO27001-A5.1-Q1")
            chapter = q.get("chapter")              # Chapitre (ex: "A.5", "A.6")
            tags = normalize_jsonlike(q.get("tags"), [])  # Tags (ex: ["politique", "gouvernance"])

            # --- Résolution CP / Requirement
            cp_id = q.get("control_point_id")
            rids = [str(r).strip() for r in (q.get("requirement_ids") or []) if str(r).strip()]

            # 🔁 Fallback d'inférence si requirement_ids manquant
            if not rids:
                inferred = _infer_requirement_ids_from_db(db, framework_id, q)
                if inferred:
                    rids = inferred

            # ✅ SI toujours pas de requirements ET qu'on génère depuis un framework,
            # assigner automatiquement en round-robin sur les requirements du framework
            if not rids and source_type == "framework" and framework_requirements:
                req = framework_requirements[requirement_assign_idx % len(framework_requirements)]
                rids = [req["id"]]
                requirement_assign_idx += 1

            # CP par mapping req→CP si absent
            if not cp_id and rids:
                candidates = []
                seen = set()
                # union des CP des exigences
                for rid in rids:
                    for cp in cp_by_req.get(rid, []):
                        if cp["id"] not in seen:
                            seen.add(cp["id"])
                            candidates.append(cp)
                if candidates:
                    cp_id = pick_best_cp(q_text, candidates)

            # mode control_points sans cp_id -> round-robin
            if not cp_id and source_type == "control_points" and control_point_ids:
                cp_id = control_point_ids[auto_assign_idx % len(control_point_ids)]
                auto_assign_idx += 1

            fw_id = (framework_id if source_type == "framework" else q.get("framework_id"))
            req_id = rids[0] if rids else None  # on prend la 1ère exigence

            # Déterminer generation_source basé sur source_type et ce qui est disponible
            if source_type == "framework":
                gen_source = "framework"
            elif cp_id:
                gen_source = "control_point"
            else:
                gen_source = "manual"

            # ✅ Exécuter l'insertion et récupérer l'ID de la question
            result = db.execute(insert_question, {
                "questionnaire_id": questionnaire_id,
                "question_text": q_text,
                "response_type": rtype,
                "is_required": is_req,
                "validation_rules": json.dumps(validation_rules, ensure_ascii=False),
                "help_text": help_t,
                "evidence_types": json.dumps(evidence_types, ensure_ascii=False),
                "difficulty_level": diff,
                "estimated_time_minutes": tmin,
                "sort_order": idx + 1,
                "created_by": payload.get("created_by", "ai"),
                "ai_generated": True,
                "ai_model": ai_model,
                "ai_confidence": aiconf,
                "control_point_id": cp_id,
                "framework_id": fw_id,
                "requirement_id": req_id,
                "upload_conditions": json.dumps(upload_conds) if upload_conds else None,
                "generation_source_type": source_type,
                "generation_source_ids": json.dumps(gen_src_ids),
                "generation_source": gen_source,
                "question_code": question_code,  # ✅ Nouveau champ
                "chapter": chapter,              # ✅ Nouveau champ
                "tags": json.dumps(tags, ensure_ascii=False),  # ✅ Nouveau champ
            })

            # ✅ Récupérer l'ID de la question insérée
            inserted_row = result.first()
            if not inserted_row:
                logger.error(f"❌ Échec insertion question #{idx+1}: {q_text[:50]}")
                continue

            question_id = inserted_row.id

            # ✅ Insérer les options si le type de question le requiert
            options_list = q.get("options")
            if options_list and rtype in ["single_choice", "multiple_choice"]:
                try:
                    QuestionOptionService.create_options_for_question(
                        db=db,
                        question_id=question_id,
                        options=options_list,
                        replace_existing=False,
                        category=rtype  # Catégorie basée sur le type
                    )
                    logger.info(f"✅ {len(options_list)} options insérées pour question {question_id}")
                except Exception as opt_err:
                    logger.error(f"❌ Erreur insertion options pour question {question_id}: {opt_err}")

        db.commit()

        return {
            "questionnaire_id": questionnaire_id,
            "inserted": len(questions),
            "source_type": source_type,
            "framework_id": framework_id,
            "control_point_ids": control_point_ids,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("❌ Erreur create_from_generation", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@router.put("/{id_or_name}/questions/{question_id}", status_code=status.HTTP_200_OK)
async def update_question_for_questionnaire(
    id_or_name: str,
    question_id: str,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Met à jour une question appartenant au questionnaire ciblé (UUID ou nom).
    Vérifie l'appartenance avant la mise à jour.
    """
    try:
        qid = _resolve_questionnaire_id(db, id_or_name)
        if not qid:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        owned = db.execute(
            text("""
                SELECT 1
                FROM question
                WHERE id::text = :qid AND questionnaire_id = :questionnaire_id
                LIMIT 1
            """),
            {"qid": question_id, "questionnaire_id": qid},
        ).first()
        if not owned:
            raise HTTPException(status_code=404, detail="Question introuvable pour ce questionnaire")

        # ✅ UPDATE avec requirement_id et framework_id
        row = db.execute(
            text("""
                UPDATE question
                SET
                    question_text = COALESCE(:question_text, question_text),
                    response_type = COALESCE(:response_type, response_type),
                    is_required = COALESCE(:is_required, is_required),
                    help_text = COALESCE(:help_text, help_text),
                    sort_order = COALESCE(:sort_order, sort_order),
                    ai_generated = COALESCE(:ai_generated, ai_generated),
                    control_point_id = COALESCE(:control_point_id, control_point_id),
                    requirement_id = COALESCE(:requirement_id, requirement_id),
                    framework_id = COALESCE(:framework_id, framework_id),
                    difficulty_level = COALESCE(:difficulty_level, difficulty_level),
                    estimated_time_minutes = COALESCE(:estimated_time_minutes, estimated_time_minutes)
                WHERE id::text = :id
                RETURNING
                    id, questionnaire_id, question_text, response_type,
                    is_required, help_text, sort_order, ai_generated, 
                    control_point_id, requirement_id, framework_id
            """),
            {
                "id": question_id,
                "question_text": payload.get("question_text"),
                "response_type": payload.get("response_type"),
                "is_required": payload.get("is_required"),
                "help_text": payload.get("help_text"),
                "sort_order": payload.get("sort_order"),
                "ai_generated": payload.get("ai_generated"),
                "control_point_id": payload.get("control_point_id"),
                "requirement_id": payload.get("requirement_id"),  # ✅ AJOUTÉ
                "framework_id": payload.get("framework_id"),      # ✅ AJOUTÉ
                "difficulty_level": payload.get("difficulty_level"),
                "estimated_time_minutes": payload.get("estimated_time_minutes")
            },
        ).first()

        if not row:
            raise HTTPException(status_code=404, detail="Question introuvable (update)")

        # ✅ Gérer la mise à jour des options si fournies
        options_list = []
        if "options" in payload and payload["options"] is not None:
            if row.response_type in ["single_choice", "multiple_choice"]:
                QuestionOptionService.create_options_for_question(
                    db=db,
                    question_id=question_id,
                    options=payload["options"],
                    replace_existing=True  # Remplace les options existantes
                )
                logger.info(f"✅ Options mises à jour pour question {question_id}")
            else:
                logger.warning(f"⚠️ Options fournies pour type '{row.response_type}' qui ne les nécessite pas")

        db.commit()

        # Récupérer les options pour la réponse
        if row.response_type in ["single_choice", "multiple_choice"]:
            options_list = QuestionOptionService.get_options_as_list(db, question_id)

        return {
            "id": str(row.id),
            "questionnaire_id": str(row.questionnaire_id),
            "question_text": row.question_text,
            "response_type": row.response_type,
            "is_required": bool(row.is_required),
            "help_text": row.help_text,
            "sort_order": row.sort_order,
            "ai_generated": bool(row.ai_generated),
            "control_point_id": str(row.control_point_id) if row.control_point_id else None,
            "requirement_id": str(row.requirement_id) if row.requirement_id else None,
            "framework_id": str(row.framework_id) if row.framework_id else None,
            "options": options_list  # ✅ Retourner les options
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Erreur update_question_for_questionnaire")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e


@router.delete("/{id_or_name}/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question_for_questionnaire(
    id_or_name: str,
    question_id: str,
    db: Session = Depends(get_db),
):
    """
    Supprime une question appartenant au questionnaire ciblé (UUID ou nom).
    """
    try:
        qid = _resolve_questionnaire_id(db, id_or_name)
        if not qid:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        owned = db.execute(
            text(
                """
                SELECT 1
                FROM question
                WHERE id::text = :qid AND questionnaire_id = :questionnaire_id
                LIMIT 1
                """
            ),
            {"qid": question_id, "questionnaire_id": qid},
        ).first()
        if not owned:
            raise HTTPException(status_code=404, detail="Question introuvable pour ce questionnaire")

        deleted = db.execute(
            text("DELETE FROM question WHERE id::text = :id RETURNING id"),
            {"id": question_id},
        ).first()
        if not deleted:
            raise HTTPException(status_code=404, detail="Question introuvable (delete)")
        db.commit()
        return
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Erreur delete_question_for_questionnaire")
        raise HTTPException(status_code=500, detail="Erreur serveur") from e


# ========================================
# DUPLICATION AVEC TRADUCTION
# ========================================

@router.post("/{questionnaire_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_questionnaire(
    questionnaire_id: str,
    translate_to: Optional[str] = Query(default=None, description="Code langue cible (en, es, de, it, pt)"),
    new_name: Optional[str] = Query(default=None, description="Nouveau nom du questionnaire"),
    current_user: User = Depends(get_optional_current_user_keycloak),
    db: Session = Depends(get_db),
):
    """
    Duplique un questionnaire avec ses questions et options.
    Si translate_to est spécifié, traduit automatiquement via IA.
    """
    try:
        logger.info(f"📋 Duplication questionnaire {questionnaire_id}, langue cible: {translate_to}")

        # 1. Récupérer le questionnaire source
        source_q = db.execute(
            text("SELECT * FROM questionnaire WHERE id::text = :id"),
            {"id": questionnaire_id}
        ).first()

        if not source_q:
            raise HTTPException(status_code=404, detail="Questionnaire introuvable")

        # 2. Créer le nouveau questionnaire
        duplicate_name = new_name or f"{source_q.name} (copie)"
        if translate_to and translate_to != "fr":
            lang_names = {"en": "EN", "es": "ES", "de": "DE", "it": "IT", "pt": "PT", "ar": "AR"}
            duplicate_name = f"{source_q.name} ({lang_names.get(translate_to, translate_to.upper())})"

        # Vérifier si le nom existe déjà et ajouter un suffixe si nécessaire
        existing_name = db.execute(
            text("SELECT COUNT(*) FROM questionnaire WHERE name = :name"),
            {"name": duplicate_name}
        ).scalar()

        if existing_name > 0:
            # Ajouter un timestamp pour garantir l'unicité
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            duplicate_name = f"{duplicate_name}_{timestamp}"

        new_questionnaire_id = str(uuid.uuid4())
        # Les copies doivent avoir source_type = 'ORG_VARIANT' pour être éditables
        db.execute(
            text("""
                INSERT INTO questionnaire (id, name, status, source_type, ai_model, framework_id, language_code, created_at)
                VALUES (:id, :name, 'draft', 'ORG_VARIANT', :ai_model, :framework_id, :language_code, NOW())
            """),
            {
                "id": new_questionnaire_id,
                "name": duplicate_name,
                "ai_model": source_q.ai_model,
                "framework_id": source_q.framework_id,
                "language_code": translate_to if translate_to and translate_to != "fr" else (source_q.language_code or "fr")
            }
        )

        # Activer le questionnaire dupliqué pour l'organisation de l'utilisateur
        if current_user and current_user.tenant_id:
            # Récupérer l'organisation du tenant
            org_result = db.execute(
                text("SELECT id FROM organization WHERE tenant_id = :tenant_id LIMIT 1"),
                {"tenant_id": str(current_user.tenant_id)}
            ).first()

            if org_result:
                db.execute(
                    text("""
                        INSERT INTO organization_questionnaire_activation (id, org_id, questionnaire_id, active, inherit_to_children, created_at, updated_at)
                        VALUES (:id, :org_id, :questionnaire_id, true, true, NOW(), NOW())
                        ON CONFLICT (org_id, questionnaire_id) DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": str(org_result.id),
                        "questionnaire_id": new_questionnaire_id
                    }
                )
                logger.info(f"✅ Questionnaire {new_questionnaire_id} activé pour org {org_result.id}")

        # 3. Récupérer toutes les questions du questionnaire source
        source_questions = db.execute(
            text("""
                SELECT q.*,
                       ARRAY_AGG(
                           COALESCE(qo.custom_value, o.default_value)
                           ORDER BY qo.sort_order
                       ) FILTER (WHERE qo.id IS NOT NULL) as options
                FROM question q
                LEFT JOIN question_option qo ON q.id = qo.question_id
                LEFT JOIN option o ON qo.option_id = o.id
                WHERE q.questionnaire_id::text = :qid
                GROUP BY q.id
                ORDER BY q.sort_order
            """),
            {"qid": questionnaire_id}
        ).fetchall()

        logger.info(f"📊 {len(source_questions)} questions à dupliquer")

        # 4. Si traduction demandée, traduire via IA
        if translate_to and translate_to != "fr" and source_questions:
            logger.info(f"🌍 Traduction en {translate_to} via IA...")
            translated_questions = await _translate_questions_batch(source_questions, translate_to)
        else:
            translated_questions = None

        # 5. Dupliquer chaque question
        for idx, source_q in enumerate(source_questions):
            new_question_id = str(uuid.uuid4())

            # Utiliser la traduction si disponible
            if translated_questions and idx < len(translated_questions):
                question_text = translated_questions[idx].get("question_text", source_q.question_text)
                help_text = translated_questions[idx].get("help_text", source_q.help_text)
                options = translated_questions[idx].get("options", source_q.options or [])
            else:
                question_text = source_q.question_text
                help_text = source_q.help_text
                options = source_q.options or []

            db.execute(
                text("""
                    INSERT INTO question (
                        id, questionnaire_id, question_text, response_type, is_required,
                        help_text, sort_order, ai_generated, control_point_id, requirement_id,
                        framework_id, difficulty_level, estimated_time_minutes
                    )
                    VALUES (
                        :id, :questionnaire_id, :question_text, :response_type, :is_required,
                        :help_text, :sort_order, :ai_generated, :control_point_id, :requirement_id,
                        :framework_id, :difficulty_level, :estimated_time_minutes
                    )
                """),
                {
                    "id": new_question_id,
                    "questionnaire_id": new_questionnaire_id,
                    "question_text": question_text,
                    "response_type": source_q.response_type,
                    "is_required": source_q.is_required,
                    "help_text": help_text,
                    "sort_order": source_q.sort_order,
                    "ai_generated": source_q.ai_generated,
                    "control_point_id": source_q.control_point_id,
                    "requirement_id": source_q.requirement_id,
                    "framework_id": source_q.framework_id,
                    "difficulty_level": getattr(source_q, "difficulty_level", None),
                    "estimated_time_minutes": getattr(source_q, "estimated_time_minutes", None)
                }
            )

            # Dupliquer les options si elles existent
            if options and source_q.response_type in ["single_choice", "multiple_choice", "multi_choice"]:
                for opt_idx, option_value in enumerate(options):
                    if option_value:  # Ignorer les NULL
                        db.execute(
                            text("""
                                INSERT INTO question_option (id, question_id, custom_value, sort_order, is_active)
                                VALUES (:id, :question_id, :custom_value, :sort_order, true)
                            """),
                            {
                                "id": str(uuid.uuid4()),
                                "question_id": new_question_id,
                                "custom_value": option_value,
                                "sort_order": opt_idx + 1
                            }
                        )

        db.commit()

        logger.info(f"✅ Questionnaire dupliqué: {new_questionnaire_id}")

        # Récupérer les infos du questionnaire créé pour le retour
        created_q = db.execute(
            text("SELECT * FROM questionnaire WHERE id::text = :id"),
            {"id": new_questionnaire_id}
        ).first()

        return {
            "id": new_questionnaire_id,
            "name": duplicate_name,
            "status": "draft",
            "source_type": created_q.source_type if created_q else "manual",
            "questions_count": len(source_questions),
            "translated": translate_to is not None and translate_to != "fr",
            "target_language": translate_to
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Erreur duplication questionnaire")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la duplication: {str(e)}") from e


@router.get("/{questionnaire_id}/duplicate/stream")
async def duplicate_questionnaire_stream(
    questionnaire_id: str,
    request: Request,
    translate_to: Optional[str] = Query(default=None, description="Code langue cible (en, es, de, it, pt, ar)"),
    new_name: Optional[str] = Query(default=None, description="Nouveau nom du questionnaire"),
    current_user: User = Depends(get_optional_current_user_keycloak),
    db: Session = Depends(get_db),
):
    """
    Endpoint SSE pour la duplication de questionnaire avec traduction et progression en temps réel.
    """

    async def event_generator():
        try:
            yield f"data: {json.dumps({'status': 'initializing', 'message': 'Initialisation de la duplication...', 'progress': 0})}\n\n"

            # 1. Récupérer le questionnaire source
            source_q = db.execute(
                text("SELECT * FROM questionnaire WHERE id::text = :id"),
                {"id": questionnaire_id}
            ).first()

            if not source_q:
                yield f"data: {json.dumps({'status': 'error', 'message': 'Questionnaire introuvable'})}\n\n"
                return

            yield f"data: {json.dumps({'status': 'progress', 'message': 'Questionnaire source trouvé', 'progress': 5})}\n\n"

            # 2. Créer le nom du nouveau questionnaire
            duplicate_name = new_name or f"{source_q.name} (copie)"
            if translate_to and translate_to != "fr":
                lang_names = {"en": "EN", "es": "ES", "de": "DE", "it": "IT", "pt": "PT", "ar": "AR"}
                duplicate_name = f"{source_q.name} ({lang_names.get(translate_to, translate_to.upper())})"

            # Vérifier si le nom existe déjà
            existing_name = db.execute(
                text("SELECT COUNT(*) FROM questionnaire WHERE name = :name"),
                {"name": duplicate_name}
            ).scalar()

            if existing_name > 0:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                duplicate_name = f"{duplicate_name}_{timestamp}"

            # 3. Créer le nouveau questionnaire
            new_questionnaire_id = str(uuid.uuid4())
            # Déterminer la langue du nouveau questionnaire
            new_language_code = translate_to if translate_to and translate_to != "fr" else (source_q.language_code or "fr")
            # Les copies doivent avoir source_type = 'ORG_VARIANT' pour être éditables
            db.execute(
                text("""
                    INSERT INTO questionnaire (id, name, status, source_type, ai_model, framework_id, language_code, created_at)
                    VALUES (:id, :name, 'draft', 'ORG_VARIANT', :ai_model, :framework_id, :language_code, NOW())
                """),
                {
                    "id": new_questionnaire_id,
                    "name": duplicate_name,
                    "ai_model": source_q.ai_model,
                    "framework_id": source_q.framework_id,
                    "language_code": new_language_code
                }
            )

            # Activer le questionnaire dupliqué pour l'organisation de l'utilisateur
            if current_user and current_user.tenant_id:
                # Récupérer l'organisation du tenant
                org_result = db.execute(
                    text("SELECT id FROM organization WHERE tenant_id = :tenant_id LIMIT 1"),
                    {"tenant_id": str(current_user.tenant_id)}
                ).first()

                if org_result:
                    db.execute(
                        text("""
                            INSERT INTO organization_questionnaire_activation (id, org_id, questionnaire_id, active, inherit_to_children, created_at, updated_at)
                            VALUES (:id, :org_id, :questionnaire_id, true, true, NOW(), NOW())
                            ON CONFLICT (org_id, questionnaire_id) DO NOTHING
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "org_id": str(org_result.id),
                            "questionnaire_id": new_questionnaire_id
                        }
                    )
                    logger.info(f"✅ SSE: Questionnaire {new_questionnaire_id} activé pour org {org_result.id}")

            yield f"data: {json.dumps({'status': 'progress', 'message': f'Questionnaire créé: {duplicate_name}', 'progress': 10})}\n\n"

            # 4. Récupérer les questions source
            source_questions = db.execute(
                text("""
                    SELECT q.*,
                           ARRAY_AGG(
                               COALESCE(qo.custom_value, o.default_value)
                               ORDER BY qo.sort_order
                           ) FILTER (WHERE qo.id IS NOT NULL) as options
                    FROM question q
                    LEFT JOIN question_option qo ON q.id = qo.question_id
                    LEFT JOIN option o ON qo.option_id = o.id
                    WHERE q.questionnaire_id::text = :qid
                    GROUP BY q.id
                    ORDER BY q.sort_order
                """),
                {"qid": questionnaire_id}
            ).fetchall()

            total_questions = len(source_questions)
            yield f"data: {json.dumps({'status': 'progress', 'message': f'{total_questions} questions à traiter', 'progress': 15, 'total_questions': total_questions})}\n\n"

            if not source_questions:
                db.commit()
                yield f"data: {json.dumps({'status': 'completed', 'message': 'Questionnaire dupliqué (vide)', 'progress': 100, 'questionnaire_id': new_questionnaire_id, 'name': duplicate_name})}\n\n"
                return

            # 5. Traduire si demandé (par batches)
            translated_questions = None
            if translate_to and translate_to != "fr":
                # 5.1. D'abord, traduire les domaines
                yield f"data: {json.dumps({'status': 'translating', 'message': 'Récupération des domaines...', 'progress': 18})}\n\n"

                # Récupérer les domaines uniques liés aux questions
                domains_result = db.execute(
                    text("""
                        SELECT DISTINCT d.id, d.code_officiel, d.title
                        FROM domain d
                        INNER JOIN requirement r ON d.id = r.domain_id
                        INNER JOIN question q ON r.id = q.requirement_id
                        WHERE q.questionnaire_id::text = :qid
                        AND NOT EXISTS (
                            SELECT 1 FROM domain_i18n di
                            WHERE di.domain_id = d.id AND di.language_code = :lang
                        )
                    """),
                    {"qid": questionnaire_id, "lang": translate_to}
                ).fetchall()

                if domains_result:
                    yield f"data: {json.dumps({'status': 'translating', 'message': f'Traduction de {len(domains_result)} domaines...', 'progress': 19})}\n\n"

                    # Traduire les domaines
                    try:
                        translated_domains = await _translate_domains_batch(domains_result, translate_to)
                        # Insérer les traductions
                        for idx, domain in enumerate(domains_result):
                            if idx < len(translated_domains):
                                db.execute(
                                    text("""
                                        INSERT INTO domain_i18n (id, domain_id, language_code, title, description)
                                        VALUES (:id, :domain_id, :lang, :title, :description)
                                        ON CONFLICT (domain_id, language_code) DO NOTHING
                                    """),
                                    {
                                        "id": str(uuid.uuid4()),
                                        "domain_id": str(domain.id),
                                        "lang": translate_to,
                                        "title": translated_domains[idx].get("name", domain.title or domain.code_officiel),
                                        "description": translated_domains[idx].get("description", "")
                                    }
                                )
                        logger.info(f"✅ {len(domains_result)} domaines traduits en {translate_to}")
                    except Exception as e:
                        logger.error(f"Erreur traduction domaines: {e}")

                # 5.2. Traduire les questions par batches
                batch_size = 10
                total_batches = (total_questions + batch_size - 1) // batch_size
                all_translated = []

                yield f"data: {json.dumps({'status': 'translating', 'message': f'Traduction en {translate_to.upper()} ({total_batches} lots)...', 'progress': 20, 'total_batches': total_batches})}\n\n"

                for batch_idx in range(total_batches):
                    start_idx = batch_idx * batch_size
                    end_idx = min(start_idx + batch_size, total_questions)
                    batch_questions = source_questions[start_idx:end_idx]

                    # Calculer la progression (20% à 80%)
                    batch_progress = 20 + int((batch_idx + 1) / total_batches * 60)

                    yield f"data: {json.dumps({'status': 'translating', 'message': f'Traduction lot {batch_idx + 1}/{total_batches}...', 'progress': batch_progress, 'batch': batch_idx + 1, 'total_batches': total_batches})}\n\n"

                    # Vérifier si le client est toujours connecté
                    if await request.is_disconnected():
                        db.rollback()
                        return

                    # Traduire le batch
                    try:
                        batch_translated = await _translate_questions_batch_internal(batch_questions, translate_to)
                        all_translated.extend(batch_translated)
                    except Exception as e:
                        logger.error(f"Erreur traduction batch {batch_idx + 1}: {e}")
                        # Fallback: garder les originaux
                        for q in batch_questions:
                            all_translated.append({
                                "question_text": q.question_text,
                                "help_text": q.help_text or "",
                                "options": list(q.options) if q.options else []
                            })

                translated_questions = all_translated
                yield f"data: {json.dumps({'status': 'progress', 'message': 'Traduction terminée', 'progress': 80})}\n\n"

            # 6. Dupliquer les questions
            yield f"data: {json.dumps({'status': 'duplicating', 'message': 'Création des questions...', 'progress': 85})}\n\n"

            for idx, source_q_item in enumerate(source_questions):
                new_question_id = str(uuid.uuid4())

                if translated_questions and idx < len(translated_questions):
                    question_text = translated_questions[idx].get("question_text", source_q_item.question_text)
                    help_text = translated_questions[idx].get("help_text", source_q_item.help_text or "")
                    options = translated_questions[idx].get("options", [])
                else:
                    question_text = source_q_item.question_text
                    help_text = source_q_item.help_text or ""
                    options = source_q_item.options or []

                db.execute(
                    text("""
                        INSERT INTO question (
                            id, questionnaire_id, question_text, response_type, is_required,
                            help_text, sort_order, ai_generated, control_point_id, requirement_id,
                            framework_id, difficulty_level, estimated_time_minutes
                        )
                        VALUES (
                            :id, :questionnaire_id, :question_text, :response_type, :is_required,
                            :help_text, :sort_order, :ai_generated, :control_point_id, :requirement_id,
                            :framework_id, :difficulty_level, :estimated_time_minutes
                        )
                    """),
                    {
                        "id": new_question_id,
                        "questionnaire_id": new_questionnaire_id,
                        "question_text": question_text,
                        "response_type": source_q_item.response_type,
                        "is_required": source_q_item.is_required,
                        "help_text": help_text,
                        "sort_order": source_q_item.sort_order,
                        "ai_generated": source_q_item.ai_generated,
                        "control_point_id": source_q_item.control_point_id,
                        "requirement_id": source_q_item.requirement_id,
                        "framework_id": source_q_item.framework_id,
                        "difficulty_level": getattr(source_q_item, "difficulty_level", None),
                        "estimated_time_minutes": getattr(source_q_item, "estimated_time_minutes", None)
                    }
                )

                # Dupliquer les options
                if options and source_q_item.response_type in ["single_choice", "multiple_choice", "multi_choice"]:
                    for opt_idx, option_value in enumerate(options):
                        if option_value:
                            db.execute(
                                text("""
                                    INSERT INTO question_option (id, question_id, custom_value, sort_order, is_active)
                                    VALUES (:id, :question_id, :custom_value, :sort_order, true)
                                """),
                                {
                                    "id": str(uuid.uuid4()),
                                    "question_id": new_question_id,
                                    "custom_value": option_value,
                                    "sort_order": opt_idx + 1
                                }
                            )

            yield f"data: {json.dumps({'status': 'progress', 'message': 'Questions créées', 'progress': 95})}\n\n"

            # 7. Commit final
            db.commit()
            logger.info(f"✅ Questionnaire dupliqué via SSE: {new_questionnaire_id}")

            yield f"data: {json.dumps({'status': 'completed', 'message': 'Duplication terminée avec succès!', 'progress': 100, 'questionnaire_id': new_questionnaire_id, 'name': duplicate_name, 'questions_count': total_questions, 'translated': translate_to is not None and translate_to != 'fr'})}\n\n"

        except Exception as e:
            db.rollback()
            logger.exception("Erreur duplication SSE")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


async def _translate_questions_batch_internal(questions, target_language: str) -> List[Dict[str, Any]]:
    """
    Traduit un lot de questions via DeepSeek/Ollama.
    """
    from src.services.deepseek_pc_generator import DeepSeekControlPointGenerator

    language_names = {
        "en": "English",
        "es": "Spanish",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "ar": "Arabic"
    }

    target_lang_name = language_names.get(target_language, target_language)

    # Préparer les questions pour la traduction
    questions_to_translate = []
    for q in questions:
        questions_to_translate.append({
            "question_text": q.question_text,
            "help_text": q.help_text or "",
            "options": list(q.options) if q.options else []
        })

    # Créer le prompt de traduction
    prompt = f"""Translate the following questionnaire questions from French to {target_lang_name}.
Keep the same structure and meaning. Return a JSON array with the same number of items.

Input questions (JSON):
{json.dumps(questions_to_translate, ensure_ascii=False, indent=2)}

Return ONLY a valid JSON array with translated questions, each having:
- "question_text": translated question
- "help_text": translated help text (empty string if none)
- "options": array of translated options (empty array if none)

JSON output:"""

    try:
        generator = DeepSeekControlPointGenerator()
        # Utiliser l'API Ollama du générateur
        import httpx

        async def call_ollama():
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{generator.ollama_url}/api/chat",
                    json={
                        "model": generator.model,
                        "messages": [
                            {"role": "system", "content": "You are a professional translator. Return only valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_ctx": generator.num_ctx,
                            "num_predict": generator.num_predict
                        }
                    }
                )
                return response.json()

        result = await call_ollama()

        response_text = result.get("message", {}).get("content", "").strip()

        # Nettoyer la réponse
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        translated = json.loads(response_text)
        logger.info(f"✅ {len(translated)} questions traduites en {target_language}")
        return translated

    except Exception as e:
        logger.error(f"❌ Erreur traduction: {e}")
        # En cas d'erreur, retourner les questions originales
        return questions_to_translate


async def _translate_questions_batch(questions, target_language: str) -> List[Dict[str, Any]]:
    """Wrapper de compatibilité pour l'ancien endpoint."""
    return await _translate_questions_batch_internal(questions, target_language)


async def _translate_domains_batch(domains, target_language: str) -> List[Dict[str, Any]]:
    """
    Traduit un lot de domaines via DeepSeek/Ollama.
    """
    from src.services.deepseek_pc_generator import DeepSeekControlPointGenerator

    language_names = {
        "en": "English",
        "es": "Spanish",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "ar": "Arabic"
    }

    target_lang_name = language_names.get(target_language, target_language)

    # Préparer les domaines pour la traduction
    domains_to_translate = []
    for d in domains:
        domains_to_translate.append({
            "code": d.code_officiel or "",
            "name": d.title or d.code_officiel or ""
        })

    # Créer le prompt de traduction
    prompt = f"""Translate the following ISO 27001 domain names from French to {target_lang_name}.
Keep the meaning accurate for information security management systems (ISMS).
Return a JSON array with the same number of items.

Input domains (JSON):
{json.dumps(domains_to_translate, ensure_ascii=False, indent=2)}

Return ONLY a valid JSON array with translated domains, each having:
- "name": translated domain name
- "description": brief description in target language (optional)

JSON output:"""

    try:
        generator = DeepSeekControlPointGenerator()
        import httpx

        async def call_ollama():
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{generator.ollama_url}/api/chat",
                    json={
                        "model": generator.model,
                        "messages": [
                            {"role": "system", "content": "You are a professional translator specializing in ISO standards and information security. Return only valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_ctx": generator.num_ctx,
                            "num_predict": 4096
                        }
                    }
                )
                return response.json()

        result = await call_ollama()

        response_text = result.get("message", {}).get("content", "").strip()

        # Nettoyer la réponse
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        translated = json.loads(response_text)
        logger.info(f"✅ {len(translated)} domaines traduits en {target_language}")
        return translated

    except Exception as e:
        logger.error(f"❌ Erreur traduction domaines: {e}")
        # En cas d'erreur, retourner les domaines originaux
        return [{"name": d.title or d.code_officiel, "description": ""} for d in domains]


