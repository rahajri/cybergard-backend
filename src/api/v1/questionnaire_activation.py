"""
API endpoints pour la gestion des activations de questionnaires pour les organizations
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, select, func
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging

from src.database import get_db
from src.schemas.questionnaire_activation import (
    QuestionnaireActivationCreate,
    QuestionnaireActivationResponse,
    QuestionnaireActivationList,
    OrganizationWithActivation,
    QuestionnaireWithActivation
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/questionnaires", tags=["Questionnaire Activation"])


# ============================================================================
# ENDPOINTS : Activation de questionnaires pour les organizations
# ============================================================================

@router.post(
    "/organizations/{org_id}/questionnaires/{questionnaire_id}/activate",
    response_model=QuestionnaireActivationResponse,
    status_code=status.HTTP_201_CREATED
)
async def activate_questionnaire_for_organization(
    org_id: UUID,
    questionnaire_id: UUID,
    request: QuestionnaireActivationCreate,
    db: Session = Depends(get_db)
):
    """
    Active un questionnaire pour une organization.

    Règles:
    - Le questionnaire doit avoir status='published'
    - L'organization doit exister
    - Crée ou met à jour l'activation
    """
    try:
        from src.models.organization import Organization
        from src.models.organization_questionnaire_activation import OrganizationQuestionnaireActivation

        logger.info(f"🔄 Activation questionnaire {questionnaire_id} pour org {org_id}")

        # 1. Vérifier que l'organization existe
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} introuvable"
            )

        # 2. Vérifier que le questionnaire existe et est publié
        from sqlalchemy import text
        result = db.execute(
            text("SELECT id, name, status FROM questionnaire WHERE id = :qid"),
            {"qid": str(questionnaire_id)}
        ).first()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Questionnaire {questionnaire_id} introuvable"
            )

        q_id, q_name, q_status = result

        if q_status != 'published':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Le questionnaire '{q_name}' doit être publié (status='published') avant d'être activé. Status actuel: '{q_status}'"
            )

        # 3. Vérifier si l'activation existe déjà
        existing = db.query(OrganizationQuestionnaireActivation).filter(
            and_(
                OrganizationQuestionnaireActivation.org_id == org_id,
                OrganizationQuestionnaireActivation.questionnaire_id == questionnaire_id
            )
        ).first()

        if existing:
            # Mettre à jour l'activation existante
            existing.active = True
            existing.inherit_to_children = request.inherit_to_children
            existing.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(existing)

            logger.info(f"✅ Activation mise à jour pour org {org.name}")

            return QuestionnaireActivationResponse(
                id=str(existing.id),
                org_id=str(existing.org_id),
                org_name=org.name,
                questionnaire_id=str(existing.questionnaire_id),
                questionnaire_name=q_name,
                active=existing.active,
                inherit_to_children=existing.inherit_to_children,
                created_at=existing.created_at,
                updated_at=existing.updated_at
            )

        # 4. Créer nouvelle activation
        from uuid import uuid4
        activation = OrganizationQuestionnaireActivation(
            id=uuid4(),
            org_id=org_id,
            questionnaire_id=questionnaire_id,
            active=True,
            inherit_to_children=request.inherit_to_children,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        db.add(activation)
        db.commit()
        db.refresh(activation)

        logger.info(f"✅ Questionnaire '{q_name}' activé pour organization '{org.name}'")

        return QuestionnaireActivationResponse(
            id=str(activation.id),
            org_id=str(activation.org_id),
            org_name=org.name,
            questionnaire_id=str(activation.questionnaire_id),
            questionnaire_name=q_name,
            active=activation.active,
            inherit_to_children=activation.inherit_to_children,
            created_at=activation.created_at,
            updated_at=activation.updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur activation questionnaire: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'activation: {str(e)}"
        )


@router.delete(
    "/organizations/{org_id}/questionnaires/{questionnaire_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT
)
async def deactivate_questionnaire_for_organization(
    org_id: UUID,
    questionnaire_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Désactive un questionnaire pour une organization.
    Met active=False au lieu de supprimer l'enregistrement.
    """
    try:
        from src.models.organization_questionnaire_activation import OrganizationQuestionnaireActivation

        logger.info(f"🔄 Désactivation questionnaire {questionnaire_id} pour org {org_id}")

        # Trouver l'activation
        activation = db.query(OrganizationQuestionnaireActivation).filter(
            and_(
                OrganizationQuestionnaireActivation.org_id == org_id,
                OrganizationQuestionnaireActivation.questionnaire_id == questionnaire_id
            )
        ).first()

        if not activation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activation introuvable"
            )

        # Désactiver (au lieu de supprimer)
        activation.active = False
        activation.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"✅ Questionnaire désactivé pour org {org_id}")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur désactivation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la désactivation: {str(e)}"
        )


@router.get(
    "/organizations/{org_id}/questionnaires",
    response_model=QuestionnaireActivationList
)
async def list_questionnaires_for_organization(
    org_id: UUID,
    active_only: bool = Query(True, description="Afficher seulement les questionnaires actifs"),
    db: Session = Depends(get_db)
):
    """
    Liste tous les questionnaires avec leur statut d'activation pour une organization.
    """
    try:
        from src.models.organization import Organization
        from sqlalchemy import text

        logger.info(f"📋 Liste questionnaires pour org {org_id}")

        # Vérifier que l'org existe
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {org_id} introuvable"
            )

        # Récupérer tous les questionnaires publiés avec leur statut d'activation
        query = text("""
            SELECT
                q.id,
                q.name,
                q.status,
                q.created_at,
                (SELECT COUNT(*) FROM question WHERE questionnaire_id = q.id) as question_count,
                oqa.id as activation_id,
                oqa.active,
                oqa.inherit_to_children,
                oqa.created_at as activated_at
            FROM questionnaire q
            LEFT JOIN organization_questionnaire_activation oqa
                ON q.id = oqa.questionnaire_id AND oqa.org_id = :org_id
            WHERE q.status = 'published'
            ORDER BY q.created_at DESC
        """)

        results = db.execute(query, {"org_id": str(org_id)}).fetchall()

        questionnaires = []
        for row in results:
            # Si active_only=True, ne garder que les questionnaires actifs
            if active_only and not row.active:
                continue

            questionnaires.append(QuestionnaireWithActivation(
                id=str(row.id),
                name=row.name,
                status=row.status,
                question_count=row.question_count,
                created_at=row.created_at,
                is_activated=row.activation_id is not None,
                is_active=row.active or False,
                inherit_to_children=row.inherit_to_children or True,
                activated_at=row.activated_at
            ))

        logger.info(f"✅ {len(questionnaires)} questionnaire(s) trouvé(s)")

        return QuestionnaireActivationList(
            org_id=str(org_id),
            org_name=org.name,
            questionnaires=questionnaires,
            total_count=len(questionnaires)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur liste questionnaires: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )


@router.get(
    "/{questionnaire_id}/organizations",
    response_model=List[OrganizationWithActivation]
)
async def list_organizations_with_questionnaire(
    questionnaire_id: UUID,
    active_only: bool = Query(True, description="Afficher seulement les activations actives"),
    db: Session = Depends(get_db)
):
    """
    Liste toutes les organizations qui ont activé un questionnaire.
    """
    try:
        from sqlalchemy import text

        logger.info(f"📋 Liste organizations pour questionnaire {questionnaire_id}")

        # Vérifier que le questionnaire existe
        q_result = db.execute(
            text("SELECT name FROM questionnaire WHERE id = :qid"),
            {"qid": str(questionnaire_id)}
        ).first()

        if not q_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Questionnaire {questionnaire_id} introuvable"
            )

        # Récupérer les organizations avec activation
        active_filter = "AND oqa.active = true" if active_only else ""

        query = text(f"""
            SELECT
                o.id,
                o.name,
                o.tenant_id,
                t.name as tenant_name,
                oqa.active,
                oqa.inherit_to_children,
                oqa.created_at as activated_at
            FROM organization o
            JOIN tenant t ON o.tenant_id = t.id
            JOIN organization_questionnaire_activation oqa
                ON o.id = oqa.org_id
            WHERE oqa.questionnaire_id = :qid
            {active_filter}
            ORDER BY o.name
        """)

        results = db.execute(query, {"qid": str(questionnaire_id)}).fetchall()

        organizations = []
        for row in results:
            organizations.append(OrganizationWithActivation(
                id=str(row.id),
                name=row.name,
                tenant_id=str(row.tenant_id),
                tenant_name=row.tenant_name,
                is_active=row.active,
                inherit_to_children=row.inherit_to_children,
                activated_at=row.activated_at
            ))

        logger.info(f"✅ {len(organizations)} organization(s) trouvée(s)")

        return organizations

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur liste organizations: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )


@router.get(
    "/available",
    response_model=List[dict]
)
async def list_available_questionnaires(
    status_filter: Optional[str] = Query("published", description="Filtrer par statut"),
    db: Session = Depends(get_db)
):
    """
    Liste tous les questionnaires disponibles pour activation (status='published').
    """
    try:
        from sqlalchemy import text

        logger.info(f"📋 Liste questionnaires disponibles (status={status_filter})")

        query = text("""
            SELECT
                q.id,
                q.name,
                q.status,
                q.language_code,
                q.created_at,
                (SELECT COUNT(*) FROM question WHERE questionnaire_id = q.id) as question_count,
                (SELECT COUNT(*) FROM organization_questionnaire_activation
                 WHERE questionnaire_id = q.id AND active = true) as active_org_count
            FROM questionnaire q
            WHERE q.status = :status
            ORDER BY q.created_at DESC
        """)

        results = db.execute(query, {"status": status_filter}).fetchall()

        questionnaires = []
        for row in results:
            questionnaires.append({
                "id": str(row.id),
                "name": row.name,
                "status": row.status,
                "language_code": row.language_code,
                "question_count": row.question_count,
                "active_org_count": row.active_org_count,
                "created_at": row.created_at.isoformat() if row.created_at else None
            })

        logger.info(f"✅ {len(questionnaires)} questionnaire(s) disponible(s)")

        return questionnaires

    except Exception as e:
        logger.error(f"❌ Erreur liste disponibles: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )
