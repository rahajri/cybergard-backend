"""
API endpoints pour le module Plan d'Action IA
"""
from fastapi import APIRouter, Depends, HTTPException, status as http_status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, text
from typing import Optional, AsyncGenerator, List
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import logging
import json
import asyncio

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak, require_permission
from src.models.audit import User
from src.models.action_plan import ActionPlan, ActionPlanItem, ActionPlanStatus, PublishedAction
from src.schemas.action_plan import (
    ActionPlanGetResponse,
    ActionPlanResponse,
    ActionPlanGenerateRequest,
    ActionPlanGenerateResponse,
    GenerationProgress,
    PhaseStatus
)
from src.services.action_plan_service import ActionPlanService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["Action Plans"])


# ============================================================================
# ENDPOINT : Récupérer le plan d'action d'une campagne
# ============================================================================

@router.get("/{campaign_id}/action-plan", response_model=ActionPlanGetResponse)
async def get_action_plan(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("ACTION_PLAN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère le plan d'action d'une campagne.

    Returns:
        - action_plan: ActionPlanResponse si le plan existe
        - action_plan: null si aucun plan n'existe encore (NOT_STARTED)
        - campaign_status: Statut de la campagne (pour vérifier si figée)
        - can_generate: Boolean indiquant si la génération est autorisée

    États possibles:
        - null: Pas de plan généré
        - GENERATING: Génération en cours (4 phases)
        - DRAFT: Plan généré, éditable
        - PUBLISHED: Plan publié, actions créées
    """
    try:
        # Récupérer le statut de la campagne
        from src.models.campaign import Campaign
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign_result = db.execute(campaign_query)
        campaign = campaign_result.scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne introuvable"
            )

        # Récupérer le plan d'action
        query = select(ActionPlan).where(
            and_(
                ActionPlan.campaign_id == campaign_id,
                ActionPlan.tenant_id == current_user.tenant_id
            )
        )
        result = db.execute(query)
        action_plan = result.scalar_one_or_none()

        if not action_plan:
            # Aucun plan n'existe - vérifier si génération autorisée
            can_generate = campaign.status == 'frozen'
            return ActionPlanGetResponse(
                action_plan=None,
                campaign_status=campaign.status,
                can_generate=can_generate
            )

        # Construire la réponse
        response_data = {
            "id": action_plan.id,
            "campaign_id": action_plan.campaign_id,
            "tenant_id": action_plan.tenant_id,
            "status": action_plan.status,
            "summary_title": action_plan.summary_title,
            "overall_risk_level": action_plan.overall_risk_level,
            "dominant_language": action_plan.dominant_language,
            "total_actions": action_plan.total_actions,
            "critical_count": action_plan.critical_count,
            "major_count": action_plan.major_count,
            "minor_count": action_plan.minor_count,
            "info_count": action_plan.info_count,
            "generated_at": action_plan.generated_at,
            "published_at": action_plan.published_at,
            "created_at": action_plan.created_at,
            "updated_at": action_plan.updated_at,
            "generated_by": action_plan.generated_by,
            "published_by": action_plan.published_by,
        }

        # Si génération en cours, inclure la progression
        if action_plan.status == "GENERATING" and action_plan.generation_progress:
            response_data["generation_progress"] = GenerationProgress(**action_plan.generation_progress)

        action_plan_response = ActionPlanResponse(**response_data)

        # Déterminer si génération possible (pas déjà publié)
        can_generate = campaign.status == 'frozen' and action_plan.status not in ['PUBLISHED']

        return ActionPlanGetResponse(
            action_plan=action_plan_response,
            campaign_status=campaign.status,
            can_generate=can_generate
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du plan d'action: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du plan d'action: {str(e)}"
        )


# ============================================================================
# NOTE: L'endpoint de génération (/action-plan/generate/stream) a été déplacé
# vers backend/src/api/v1/action_plan_generate.py
#
# Il suit le workflow à 5 phases documenté dans :
# intiale/Plan d'action/WORKFLOW_FONCTIONNEL_5_PHASES.md
#
# Phase 5 crée le plan en DB avec status=DRAFT (pas GENERATING)
# ============================================================================


# ============================================================================
# SCHEMAS pour les endpoints de publication
# ============================================================================

class PublishToActionsResponse(BaseModel):
    """Réponse de l'endpoint de publication"""
    success: bool
    message: str
    published_count: int
    already_published_count: int
    skipped_count: int  # Items exclus (included=False)


# ============================================================================
# ENDPOINT : Publier les items du plan d'action vers le module Actions
# ============================================================================

@router.post("/{campaign_id}/action-plan/publish-to-actions", response_model=PublishToActionsResponse)
async def publish_action_plan_to_actions(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("ACTION_PLAN_PUBLISH")),
    db: Session = Depends(get_db)
):
    """
    Publie les items du plan d'action vers le module Actions.

    Cette action :
    - Crée des entrées dans la table published_action pour chaque item inclus
    - Met à jour le statut de chaque item à PUBLISHED
    - Met à jour le statut du plan d'action à PUBLISHED
    - Ne republie pas les items déjà publiés (created_action_id non null)

    Returns:
        - published_count: Nombre d'actions publiées
        - already_published_count: Nombre d'items déjà publiés (ignorés)
        - skipped_count: Nombre d'items exclus (included=False)
    """
    try:
        from src.models.campaign import Campaign

        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign_result = db.execute(campaign_query)
        campaign = campaign_result.scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne introuvable"
            )

        # Récupérer le plan d'action
        action_plan_query = select(ActionPlan).where(
            and_(
                ActionPlan.campaign_id == campaign_id,
                ActionPlan.tenant_id == current_user.tenant_id
            )
        )
        action_plan_result = db.execute(action_plan_query)
        action_plan = action_plan_result.scalar_one_or_none()

        if not action_plan:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Aucun plan d'action trouvé pour cette campagne"
            )

        if action_plan.status == ActionPlanStatus.GENERATING:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="La génération du plan d'action est en cours. Veuillez attendre."
            )

        # Récupérer tous les items du plan d'action
        items_query = select(ActionPlanItem).where(
            ActionPlanItem.action_plan_id == action_plan.id
        ).order_by(ActionPlanItem.order_index)

        items_result = db.execute(items_query)
        items = items_result.scalars().all()

        if not items:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Le plan d'action ne contient aucune action à publier"
            )

        # Compteurs
        published_count = 0
        already_published_count = 0
        skipped_count = 0
        now = datetime.now(timezone.utc)

        for item in items:
            # Ignorer les items exclus
            if not item.included:
                skipped_count += 1
                continue

            # Ignorer les items déjà publiés
            if item.created_action_id is not None:
                already_published_count += 1
                continue

            # Calculer la date d'échéance
            due_date = now + timedelta(days=item.recommended_due_days) if item.recommended_due_days else None

            # Récupérer le nom de l'entité si manquant mais entity_id présent
            entity_name = item.entity_name
            if not entity_name and item.entity_id:
                entity_query = text("""
                    SELECT name FROM ecosystem_entity WHERE id = CAST(:entity_id AS uuid)
                """)
                entity_result = db.execute(entity_query, {"entity_id": str(item.entity_id)})
                entity_row = entity_result.first()
                if entity_row:
                    entity_name = entity_row[0]
                    logger.info(f"📍 Entity name récupéré pour item {item.id}: {entity_name}")

            # Récupérer l'audité responsable de l'entité (priorité sur assigned_user_id)
            # L'audité est défini dans le scope de la campagne, PAS l'auditeur
            assigned_user_id_to_use = None

            if item.entity_id:
                # PRIORITÉ 1 : Chercher l'audité responsable (audite_resp) de l'entité
                audite_resp_query = text("""
                    SELECT em.id
                    FROM entity_member em
                    WHERE em.entity_id = CAST(:entity_id AS uuid)
                      AND em.is_active = true
                      AND em.roles::jsonb ? 'audite_resp'
                    ORDER BY em.created_at ASC
                    LIMIT 1
                """)
                audite_result = db.execute(audite_resp_query, {"entity_id": str(item.entity_id)})
                audite_row = audite_result.first()
                if audite_row:
                    assigned_user_id_to_use = audite_row[0]
                    logger.info(f"✅ Publication: Audité responsable trouvé pour entité {item.entity_id}: {assigned_user_id_to_use}")
                else:
                    # PRIORITÉ 2 : Chercher n'importe quel membre actif de l'entité
                    any_member_query = text("""
                        SELECT em.id
                        FROM entity_member em
                        WHERE em.entity_id = CAST(:entity_id AS uuid)
                          AND em.is_active = true
                        ORDER BY em.created_at ASC
                        LIMIT 1
                    """)
                    any_member_result = db.execute(any_member_query, {"entity_id": str(item.entity_id)})
                    any_member_row = any_member_result.first()
                    if any_member_row:
                        assigned_user_id_to_use = any_member_row[0]
                        logger.info(f"✅ Publication: Membre d'entité trouvé (fallback): {assigned_user_id_to_use}")

            # PRIORITÉ 3 : Si aucun audité trouvé, vérifier que assigned_user_id est un audité (entity_member)
            if not assigned_user_id_to_use and item.assigned_user_id:
                check_audite_query = text("""
                    SELECT id FROM entity_member WHERE id = CAST(:user_id AS uuid) LIMIT 1
                """)
                check_result = db.execute(check_audite_query, {"user_id": str(item.assigned_user_id)})
                if check_result.first():
                    # C'est bien un audité, on peut l'utiliser
                    assigned_user_id_to_use = item.assigned_user_id
                    logger.info(f"✅ Publication: assigned_user_id existant est un audité: {assigned_user_id_to_use}")
                # NOTE: On ignore si c'est un auditeur (table users)

            # Créer l'action publiée
            published_action = PublishedAction(
                id=uuid4(),
                action_plan_item_id=item.id,
                action_plan_id=action_plan.id,
                campaign_id=campaign_id,
                tenant_id=current_user.tenant_id,
                code_action=item.code_action,  # ✅ Copier le code d'action
                title=item.title,
                description=item.description,
                objective=item.objective,
                deliverables=item.deliverables,
                severity=item.severity,
                priority=item.priority,
                status="pending",
                suggested_role=item.suggested_role,
                assigned_user_id=assigned_user_id_to_use,  # Utiliser l'audité responsable
                assignment_method=item.assignment_method,
                entity_id=item.entity_id,
                entity_name=entity_name,
                due_date=due_date,
                recommended_due_days=item.recommended_due_days,
                source_question_ids=item.source_question_ids or [],
                control_point_ids=item.control_point_ids or [],
                ai_justifications=item.ai_justifications,
                published_at=now,
                published_by=current_user.id,
                created_at=now,
                updated_at=now
            )

            db.add(published_action)

            # Mettre à jour l'item avec l'ID de l'action créée
            item.created_action_id = published_action.id
            item.status = "PUBLISHED"
            item.updated_at = now

            published_count += 1

        # Mettre à jour le statut du plan d'action si des items ont été publiés
        if published_count > 0:
            action_plan.status = ActionPlanStatus.PUBLISHED
            action_plan.published_at = now
            action_plan.published_by = current_user.id
            action_plan.updated_at = now

            # Passer la campagne à 'completed' après publication des actions
            # La campagne devient en lecture seule (même si la date de fin est à venir)
            campaign.status = "completed"
            campaign.updated_at = now
            logger.info(f"📌 Campagne {campaign_id} passée au statut 'completed' après publication des actions")

        db.commit()

        logger.info(
            f"✅ Publication plan d'action campagne {campaign_id}: "
            f"{published_count} publiées, {already_published_count} déjà publiées, {skipped_count} exclues"
        )

        return PublishToActionsResponse(
            success=True,
            message=f"{published_count} action(s) publiée(s) avec succès vers le module Actions",
            published_count=published_count,
            already_published_count=already_published_count,
            skipped_count=skipped_count
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la publication du plan d'action: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la publication: {str(e)}"
        )


# ============================================================================
# SCHEMAS pour la dépublication
# ============================================================================

class UnpublishActionsResponse(BaseModel):
    """Réponse de l'endpoint de dépublication"""
    success: bool
    message: str
    deleted_actions_count: int
    reset_items_count: int


# ============================================================================
# ENDPOINT : Supprimer les actions publiées et remettre la campagne en cours
# ============================================================================

@router.delete("/{campaign_id}/action-plan/unpublish")
async def unpublish_action_plan(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("ACTION_PLAN_PUBLISH")),
    db: Session = Depends(get_db)
):
    """
    Supprime les actions publiées d'une campagne et remet la campagne en statut 'frozen'.

    Cette action permet de republier les actions après correction du plan d'action.

    Cette action :
    - Supprime toutes les entrées de la table published_action pour cette campagne
    - Réinitialise les items du plan d'action (status=PENDING, created_action_id=null)
    - Remet le plan d'action au statut DRAFT
    - Remet la campagne au statut 'frozen' (pour permettre une nouvelle publication)

    Returns:
        - deleted_actions_count: Nombre d'actions supprimées
        - reset_items_count: Nombre d'items réinitialisés
    """
    try:
        from src.models.campaign import Campaign

        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign_result = db.execute(campaign_query)
        campaign = campaign_result.scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne introuvable"
            )

        # Vérifier que la campagne est bien en statut 'completed'
        if campaign.status != 'completed':
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"La campagne doit être au statut 'completed' pour dépublier les actions. Statut actuel: {campaign.status}"
            )

        # Récupérer le plan d'action
        action_plan_query = select(ActionPlan).where(
            and_(
                ActionPlan.campaign_id == campaign_id,
                ActionPlan.tenant_id == current_user.tenant_id
            )
        )
        action_plan_result = db.execute(action_plan_query)
        action_plan = action_plan_result.scalar_one_or_none()

        if not action_plan:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Aucun plan d'action trouvé pour cette campagne"
            )

        now = datetime.now(timezone.utc)

        # 1. Supprimer toutes les actions publiées pour cette campagne
        delete_actions_query = text("""
            DELETE FROM published_action
            WHERE campaign_id = CAST(:campaign_id AS uuid)
            RETURNING id
        """)
        delete_result = db.execute(delete_actions_query, {"campaign_id": str(campaign_id)})
        deleted_actions = delete_result.fetchall()
        deleted_actions_count = len(deleted_actions)

        # 2. Réinitialiser les items du plan d'action
        # Note: Les statuts valides sont PROPOSED, VALIDATED, EXCLUDED, PUBLISHED
        # On remet au statut VALIDATED car les items étaient validés avant publication
        reset_items_query = text("""
            UPDATE action_plan_item
            SET status = 'VALIDATED',
                created_action_id = NULL,
                updated_at = :now
            WHERE action_plan_id = CAST(:action_plan_id AS uuid)
            RETURNING id
        """)
        reset_result = db.execute(reset_items_query, {
            "action_plan_id": str(action_plan.id),
            "now": now
        })
        reset_items = reset_result.fetchall()
        reset_items_count = len(reset_items)

        # 3. Remettre le plan d'action au statut DRAFT
        action_plan.status = ActionPlanStatus.DRAFT
        action_plan.published_at = None
        action_plan.published_by = None
        action_plan.updated_at = now

        # 4. Remettre la campagne au statut 'frozen'
        campaign.status = 'frozen'
        campaign.updated_at = now

        db.commit()

        logger.info(
            f"✅ Dépublication plan d'action campagne {campaign_id}: "
            f"{deleted_actions_count} actions supprimées, {reset_items_count} items réinitialisés, "
            f"campagne remise au statut 'frozen'"
        )

        return UnpublishActionsResponse(
            success=True,
            message=f"{deleted_actions_count} action(s) supprimée(s). Campagne remise au statut 'frozen' pour permettre une nouvelle publication.",
            deleted_actions_count=deleted_actions_count,
            reset_items_count=reset_items_count
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la dépublication du plan d'action: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la dépublication: {str(e)}"
        )
