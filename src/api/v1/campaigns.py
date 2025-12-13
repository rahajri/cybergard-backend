"""
API endpoints pour la gestion des campagnes d'audit
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, text
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak, require_permission
from src.models.audit import User, Question, QuestionAnswer
from src.models.campaign import Campaign, CampaignUser, CampaignScope
from src.models.ecosystem import EcosystemEntity
from src.schemas.campaign import (
    CampaignCreate,
    CampaignUpdate,
    CampaignResponse,
    CampaignListResponse,
    CampaignStatsResponse,
    CampaignDetailsResponse,
    CampaignKPIs,
    StakeholderResponse,
    CampaignProgressResponse,
    EntityProgressResponse,
    ContributorProgressResponse,
    CampaignScopeResponse,
    EntityScopeResponse,
    CampaignCrossReferentialResponse,
    FrameworkCoverageResponse,
    CampaignDocumentsResponse,
    DocumentResponse,
    DocumentStats,
    CampaignFreezeResponse
)
from src.services.magic_link_service import generate_magic_link
from src.services.email_service import send_magic_link_email, send_campaign_invitation_email, send_campaign_reminder_email
from pydantic import BaseModel, Field
import os

logger = logging.getLogger(__name__)

# Configuration
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


# ============================================================================
# ENDPOINTS : Campagnes d'audit
# ============================================================================

@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    status: Optional[str] = Query(None, description="Filtrer par statut"),
    recurrence_type: Optional[str] = Query(None, description="Filtrer par type de récurrence"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste toutes les campagnes avec filtres et pagination (isolées par tenant)
    """
    try:
        # ✅ Isolation par tenant : vérifier que l'utilisateur a un tenant_id
        if not current_user.tenant_id:
            logger.error(f"❌ Utilisateur sans tenant_id: {current_user.email}")
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        logger.info(f"📋 Chargement campagnes pour tenant: {current_user.tenant_id}")
        # Requête SQL native pour récupérer les campagnes avec les infos du questionnaire
        query = text("""
            SELECT
                c.id,
                c.tenant_id,
                c.questionnaire_id,
                c.title,
                c.description,
                c.status,
                c.recurrence_type,
                c.recurrence_interval,
                c.next_occurrence_date,
                c.recurrence_end_date,
                c.launch_date,
                c.due_date,
                c.frozen_date,
                c.created_at,
                c.updated_at,
                c.created_by,
                c.scope_id,
                q.name as questionnaire_name,
                -- Calcul du total de questions : nombre de questions × nombre d'entités
                COALESCE(
                    question_stats.total_questions * COALESCE(array_length(cs.entity_ids, 1), 1),
                    0
                ) as questions_total,
                -- Nombre de réponses (toutes entités confondues, toutes questions)
                COALESCE(answer_stats.answered_questions, 0) as questions_answered,
                -- Pourcentage de progression
                COALESCE(
                    CASE
                        WHEN question_stats.total_questions > 0 AND array_length(cs.entity_ids, 1) > 0
                        THEN ROUND(
                            (answer_stats.answered_questions::decimal /
                            (question_stats.total_questions * array_length(cs.entity_ids, 1))) * 100
                        )
                        ELSE 0
                    END,
                    0
                ) as progress,
                cs.auditor_ids,
                cs.entity_ids
            FROM campaign c
            LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
            LEFT JOIN campaign_scope cs ON c.scope_id = cs.id
            LEFT JOIN (
                SELECT
                    questionnaire_id,
                    COUNT(DISTINCT id) as total_questions
                FROM question
                WHERE questionnaire_id IS NOT NULL
                GROUP BY questionnaire_id
            ) question_stats ON c.questionnaire_id = question_stats.questionnaire_id
            LEFT JOIN (
                SELECT
                    campaign_id,
                    -- Compter TOUTES les réponses (pas juste les questions distinctes)
                    -- car chaque entité répond aux mêmes questions
                    COUNT(DISTINCT CONCAT(question_id::text, '-', audit_id::text)) as answered_questions
                FROM question_answer
                WHERE campaign_id IS NOT NULL
                  AND is_current = true
                GROUP BY campaign_id
            ) answer_stats ON c.id = answer_stats.campaign_id
            WHERE c.tenant_id = :tenant_id
                {status_filter}
                {recurrence_filter}
            ORDER BY c.created_at DESC
            LIMIT :limit OFFSET :skip
        """)

        # Construction des filtres dynamiques
        status_filter = "AND c.status = :status" if status else ""
        recurrence_filter = "AND c.recurrence_type = :recurrence_type" if recurrence_type else ""

        query = text(query.text.format(
            status_filter=status_filter,
            recurrence_filter=recurrence_filter
        ))

        # Paramètres de la requête
        params = {
            "tenant_id": str(current_user.tenant_id),
            "limit": limit,
            "skip": skip
        }
        if status:
            params["status"] = status
        if recurrence_type:
            params["recurrence_type"] = recurrence_type

        # Exécution
        result = db.execute(query, params)
        campaigns_data = result.fetchall()

        # Conversion en liste de dictionnaires
        campaigns = []
        for row in campaigns_data:
            campaigns.append({
                "id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "questionnaire_id": str(row.questionnaire_id),
                "title": row.title,
                "description": row.description,
                "status": row.status,
                "recurrence_type": row.recurrence_type,
                "recurrence_interval": row.recurrence_interval,
                "next_occurrence_date": row.next_occurrence_date,
                "recurrence_end_date": row.recurrence_end_date,
                "launch_date": row.launch_date,
                "due_date": row.due_date,
                "frozen_date": row.frozen_date,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "created_by": str(row.created_by) if row.created_by else None,
                "scope_id": str(row.scope_id) if row.scope_id else None,
                "questionnaire_name": row.questionnaire_name,
                "questions_total": row.questions_total,
                "questions_answered": row.questions_answered,
                "progress": int(row.progress),
                "auditor_ids": [str(aid) for aid in (row.auditor_ids or [])],
                "entity_ids": [str(eid) for eid in (row.entity_ids or [])]
            })

        # Count total
        count_query = text("""
            SELECT COUNT(*)
            FROM campaign c
            WHERE c.tenant_id = :tenant_id
                {status_filter}
                {recurrence_filter}
        """.format(
            status_filter=status_filter,
            recurrence_filter=recurrence_filter
        ))

        count_params = {"tenant_id": str(current_user.tenant_id)}
        if status:
            count_params["status"] = status
        if recurrence_type:
            count_params["recurrence_type"] = recurrence_type

        total = db.execute(count_query, count_params).scalar()

        logger.info(f"✅ {len(campaigns)} campagne(s) récupérée(s) pour tenant {current_user.tenant_id}")

        return {
            "items": campaigns,
            "total": total or 0,
            "skip": skip,
            "limit": limit
        }

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des campagnes: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des campagnes: {str(e)}"
        )


@router.get("/stats", response_model=CampaignStatsResponse)
async def get_campaigns_stats(
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les statistiques globales des campagnes (isolées par tenant)
    """
    try:
        # ✅ Isolation par tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        query = text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'draft') as draft,
                COUNT(*) FILTER (WHERE status = 'ongoing') as ongoing,
                COUNT(*) FILTER (WHERE status = 'late') as late,
                COUNT(*) FILTER (WHERE status = 'frozen') as frozen,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled
            FROM campaign
            WHERE tenant_id = :tenant_id
        """)

        result = db.execute(query, {"tenant_id": str(current_user.tenant_id)}).fetchone()

        return {
            "total": result.total,
            "draft": result.draft,
            "ongoing": result.ongoing,
            "late": result.late,
            "frozen": result.frozen,
            "completed": result.completed,
            "cancelled": result.cancelled
        }

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des statistiques: {str(e)}"
        )


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les détails d'une campagne (isolée par tenant)
    """
    try:
        # ✅ Isolation par tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        query = text("""
            SELECT
                c.id,
                c.tenant_id,
                c.questionnaire_id,
                c.title,
                c.description,
                c.status,
                c.recurrence_type,
                c.recurrence_interval,
                c.next_occurrence_date,
                c.recurrence_end_date,
                c.launch_date,
                c.due_date,
                c.frozen_date,
                c.created_at,
                c.updated_at,
                c.created_by,
                c.scope_id,
                q.name as questionnaire_name,
                -- Calcul du total de questions : nombre de questions × nombre d'entités
                COALESCE(
                    question_stats.total_questions * COALESCE(array_length(cs.entity_ids, 1), 1),
                    0
                ) as questions_total,
                -- Nombre de réponses (toutes entités confondues, toutes questions)
                COALESCE(answer_stats.answered_questions, 0) as questions_answered,
                -- Pourcentage de progression
                COALESCE(
                    CASE
                        WHEN question_stats.total_questions > 0 AND array_length(cs.entity_ids, 1) > 0
                        THEN ROUND(
                            (answer_stats.answered_questions::decimal /
                            (question_stats.total_questions * array_length(cs.entity_ids, 1))) * 100
                        )
                        ELSE 0
                    END,
                    0
                ) as progress
            FROM campaign c
            LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
            LEFT JOIN campaign_scope cs ON c.scope_id = cs.id
            LEFT JOIN (
                SELECT
                    questionnaire_id,
                    COUNT(DISTINCT id) as total_questions
                FROM question
                WHERE questionnaire_id IS NOT NULL
                GROUP BY questionnaire_id
            ) question_stats ON c.questionnaire_id = question_stats.questionnaire_id
            LEFT JOIN (
                SELECT
                    campaign_id,
                    -- Compter TOUTES les réponses (pas juste les questions distinctes)
                    -- car chaque entité répond aux mêmes questions
                    COUNT(DISTINCT CONCAT(question_id::text, '-', audit_id::text)) as answered_questions
                FROM question_answer
                WHERE campaign_id IS NOT NULL
                  AND is_current = true
                GROUP BY campaign_id
            ) answer_stats ON c.id = answer_stats.campaign_id
            WHERE c.id = :campaign_id
              AND c.tenant_id = :tenant_id
        """)

        result = db.execute(query, {
            "campaign_id": str(campaign_id),
            "tenant_id": str(current_user.tenant_id)
        }).fetchone()

        if not result:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Campagne {campaign_id} introuvable ou accès refusé"
            )

        # Charger les pilotes assignés
        pilot_query = text("""
            SELECT user_id
            FROM campaign_user
            WHERE campaign_id = :campaign_id
              AND is_active = true
              AND role = 'manager'
        """)
        pilot_results = db.execute(pilot_query, {"campaign_id": str(campaign_id)}).fetchall()
        pilot_user_ids = [str(row.user_id) for row in pilot_results]

        # Charger le scope (entités et auditeurs)
        entity_ids = []
        auditor_ids = []
        audited_domain_scope = {}
        campaign_type = None
        pole_ids = []
        category_ids = []

        # Récupérer les audités depuis audite_domain_scope (nouvelle architecture)
        audited_query = text("""
            SELECT ads.entity_member_id, ads.domain_ids, ads.all_domains, em.entity_id
            FROM audite_domain_scope ads
            LEFT JOIN entity_member em ON em.id = ads.entity_member_id
            WHERE ads.campaign_id = :campaign_id
        """)
        audited_results = db.execute(audited_query, {"campaign_id": str(campaign_id)}).fetchall()

        entity_ids_set = set()
        for row in audited_results:
            member_id = str(row.entity_member_id)
            auditor_ids.append(member_id)
            audited_domain_scope[member_id] = {
                "domain_ids": row.domain_ids or [],
                "all_domains": row.all_domains
            }
            # Collecter les entity_ids depuis les audités
            if row.entity_id:
                entity_ids_set.add(str(row.entity_id))

        entity_ids = list(entity_ids_set)

        # Si pas d'audités dans audite_domain_scope, fallback sur campaign_scope (rétrocompatibilité)
        if not auditor_ids and result.scope_id:
            scope_query = text("""
                SELECT entity_ids, auditor_ids
                FROM campaign_scope
                WHERE id = :scope_id
            """)
            scope_result = db.execute(scope_query, {"scope_id": str(result.scope_id)}).fetchone()
            if scope_result:
                entity_ids = [str(eid) for eid in (scope_result.entity_ids or [])]
                auditor_ids = [str(aid) for aid in (scope_result.auditor_ids or [])]

        # Détecter le type de campagne et récupérer les pôles/catégories depuis les entités
        if entity_ids:
            placeholders = ', '.join([f':entity_id_{i}' for i in range(len(entity_ids))])
            entities_query = text(f"""
                SELECT stakeholder_type, pole_id, category_id
                FROM ecosystem_entity
                WHERE id::text IN ({placeholders})
            """)
            params = {f'entity_id_{i}': eid for i, eid in enumerate(entity_ids)}
            entities_result = db.execute(entities_query, params).fetchall()

            if entities_result:
                # Type de campagne (première entité)
                campaign_type = entities_result[0].stakeholder_type

                # Extraire les pôles et catégories uniques
                pole_ids = list(set([str(e.pole_id) for e in entities_result if e.pole_id]))
                category_ids = list(set([str(e.category_id) for e in entities_result if e.category_id]))

        return {
            "id": str(result.id),
            "tenant_id": str(result.tenant_id),
            "questionnaire_id": str(result.questionnaire_id),
            "title": result.title,
            "description": result.description,
            "status": result.status,
            "recurrence_type": result.recurrence_type,
            "recurrence_interval": result.recurrence_interval,
            "next_occurrence_date": result.next_occurrence_date,
            "recurrence_end_date": result.recurrence_end_date,
            "launch_date": result.launch_date,
            "due_date": result.due_date,
            "frozen_date": result.frozen_date,
            "created_at": result.created_at,
            "updated_at": result.updated_at,
            "created_by": str(result.created_by) if result.created_by else None,
            "scope_id": str(result.scope_id) if result.scope_id else None,
            "questionnaire_name": result.questionnaire_name,
            "questions_total": result.questions_total,
            "questions_answered": result.questions_answered,
            "progress": int(result.progress),
            "pilot_user_ids": pilot_user_ids,
            "entity_ids": entity_ids,
            "auditor_ids": auditor_ids,
            "audited_domain_scope": audited_domain_scope,  # Nouveau : domain scopes par audité
            "campaign_type": campaign_type,
            "pole_ids": pole_ids,
            "category_ids": category_ids
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération de la campagne: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération de la campagne: {str(e)}"
        )


@router.post("", response_model=CampaignResponse, status_code=http_status.HTTP_201_CREATED)
async def create_campaign(
    campaign: CampaignCreate,
    current_user: User = Depends(require_permission("CAMPAIGN_CREATE")),
    db: Session = Depends(get_db)
):
    """
    Crée une nouvelle campagne avec statut 'draft'
    """
    try:
        # Récupérer le tenant_id de l'utilisateur connecté
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Utilisateur sans tenant. Impossible de créer une campagne."
            )

        tenant_id = str(current_user.tenant_id)
        created_by = str(current_user.id)

        # Créer la campagne
        insert_query = text("""
            INSERT INTO campaign (
                tenant_id,
                questionnaire_id,
                title,
                description,
                scope_id,
                audit_type,
                recurrence_type,
                recurrence_interval,
                next_occurrence_date,
                recurrence_end_date,
                launch_date,
                due_date,
                status,
                created_by,
                created_at,
                updated_at
            ) VALUES (
                :tenant_id,
                :questionnaire_id,
                :title,
                :description,
                :scope_id,
                :audit_type,
                :recurrence_type,
                :recurrence_interval,
                :next_occurrence_date,
                :recurrence_end_date,
                :launch_date,
                :due_date,
                'draft',
                :created_by,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            RETURNING id
        """)

        params = {
            "tenant_id": tenant_id,
            "questionnaire_id": str(campaign.questionnaire_id),
            "title": campaign.title,
            "description": campaign.description,
            "scope_id": str(campaign.scope_id) if campaign.scope_id else None,
            "audit_type": campaign.audit_type or 'external',  # external par défaut
            "recurrence_type": campaign.recurrence_type or 'once',
            "recurrence_interval": campaign.recurrence_interval,
            "next_occurrence_date": None,  # Sera calculé au lancement
            "recurrence_end_date": campaign.recurrence_end_date,
            "launch_date": campaign.launch_date,
            "due_date": campaign.due_date,
            "created_by": created_by,
        }

        result = db.execute(insert_query, params)
        campaign_id = result.fetchone().id
        db.commit()

        logger.info(f"✅ Campagne créée: {campaign_id} - {campaign.title}")

        # Récupérer la campagne créée
        return await get_campaign(campaign_id, current_user, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la création de la campagne: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création de la campagne: {str(e)}"
        )


@router.post("/{campaign_id}/launch", response_model=CampaignResponse)
async def launch_campaign(
    campaign_id: UUID,
    current_user: User = Depends(get_current_user_keycloak),
    db: Session = Depends(get_db)
):
    """
    Lance une campagne en brouillon (isolée par tenant) :
    - Change le statut de 'draft' à 'ongoing'
    - Met à jour launch_date à la date du jour
    - Envoie les invitations par email aux contacts audités
    """
    try:
        # ✅ Isolation par tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        # Vérifier que la campagne existe et appartient au tenant
        # Inclure created_by pour vérifier si l'utilisateur est le créateur
        campaign_query = text("""
            SELECT id, tenant_id, questionnaire_id, title, status, scope_id, created_by
            FROM campaign
            WHERE id = :campaign_id
              AND tenant_id = :tenant_id
        """)
        campaign_result = db.execute(campaign_query, {
            "campaign_id": str(campaign_id),
            "tenant_id": str(current_user.tenant_id)
        }).fetchone()

        if not campaign_result:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Campagne {campaign_id} introuvable ou accès refusé"
            )

        # Vérifier les permissions : créateur OU permission CAMPAIGN_CREATE
        is_creator = campaign_result.created_by and str(campaign_result.created_by) == str(current_user.id)

        # Vérifier si l'utilisateur a la permission CAMPAIGN_CREATE via les rôles
        perm_check = db.execute(text("""
            SELECT 1 FROM user_role ur
            JOIN role_permission rp ON ur.role_id = rp.role_id
            JOIN permission p ON rp.permission_id = p.id
            WHERE ur.user_id = :user_id AND p.code = 'CAMPAIGN_CREATE'
            LIMIT 1
        """), {"user_id": str(current_user.id)}).fetchone()
        has_permission = perm_check is not None

        if not is_creator and not has_permission:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Vous n'êtes pas autorisé à lancer cette campagne. Seul le créateur ou un utilisateur avec la permission 'Création de campagnes' peut le faire."
            )

        if campaign_result.status != 'draft':
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Seules les campagnes en brouillon peuvent être lancées. Statut actuel : {campaign_result.status}"
            )

        # VERSION 2.1 - Récupérer les contacts audités depuis entity_member (entités du scope)
        logger.info("🔧 [VERSION 2.1] Récupération des contacts depuis entity_member (scope de la campagne)")

        # Récupérer les entités du scope de la campagne
        scope_query = text("""
            SELECT entity_ids FROM campaign_scope WHERE id = :scope_id
        """)
        scope_result = db.execute(scope_query, {"scope_id": str(campaign_result.scope_id)}).fetchone()

        if not scope_result or not scope_result.entity_ids:
            logger.warning(f"⚠️ Aucune entité dans le scope de la campagne {campaign_id}")
            audited_contacts = []
        else:
            entity_ids = scope_result.entity_ids
            logger.info(f"📋 Entités dans le scope: {entity_ids}")

            # Récupérer tous les contacts (entity_member) de ces entités
            contacts_query = text("""
                SELECT DISTINCT em.id, em.email, em.first_name, em.last_name, em.entity_id
                FROM entity_member em
                WHERE em.entity_id = ANY(:entity_ids)
                  AND em.is_active = true
                  AND em.email IS NOT NULL
            """)
            contacts_result = db.execute(contacts_query, {"entity_ids": entity_ids}).fetchall()
            audited_contacts = contacts_result

        logger.info(f"🚀 [VERSION 2.1] Lancement de la campagne {campaign_id} : {len(audited_contacts)} contact(s) à inviter")

        # Mettre à jour le statut de la campagne
        update_query = text("""
            UPDATE campaign
            SET status = 'ongoing',
                launch_date = CURRENT_DATE,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :campaign_id
            RETURNING id
        """)
        db.execute(update_query, {"campaign_id": str(campaign_id)})
        db.commit()

        # Récupérer le nom du tenant (organisation cliente)
        tenant_query = text("SELECT name FROM tenant WHERE id = :tenant_id")
        tenant_result = db.execute(tenant_query, {"tenant_id": str(campaign_result.tenant_id)}).fetchone()
        organization_name = tenant_result.name if tenant_result else "CYBERGARD AI"

        # Envoyer les magic links aux contacts audités
        emails_sent = 0
        for contact in audited_contacts:
            try:
                # Générer le magic link
                magic_link, _ = generate_magic_link(
                    db=db,
                    user_email=contact.email,
                    campaign_id=campaign_id,
                    questionnaire_id=campaign_result.questionnaire_id,
                    tenant_id=campaign_result.tenant_id
                )

                # Récupérer le nom de l'entité
                entity_query = text("SELECT name FROM ecosystem_entity WHERE id = :entity_id")
                entity_result = db.execute(entity_query, {"entity_id": str(contact.entity_id)}).fetchone()
                entity_name = entity_result.name if entity_result else "Votre organisation"

                # Envoyer l'email avec le nom de l'organisation (tenant)
                send_magic_link_email(
                    to_email=contact.email,
                    user_name=f"{contact.first_name} {contact.last_name}",
                    magic_link=magic_link,
                    campaign_name=campaign_result.title,
                    entity_name=entity_name,
                    organization_name=organization_name
                )
                emails_sent += 1
                logger.info(f"✅ Email envoyé à {contact.email}")

            except Exception as e:
                logger.error(f"❌ Erreur envoi email à {contact.email}: {e}")
                # Continue avec les autres contacts même en cas d'erreur

        logger.info(f"✅ Campagne lancée : {emails_sent}/{len(audited_contacts)} email(s) envoyé(s) aux contacts audités")

        # VERSION 2.1.1 - Envoyer les magic links aux contributeurs (audite_contrib)
        logger.info("🔧 [VERSION 2.1.1] Envoi des magic links aux contributeurs transverses")

        # Récupérer tous les contributeurs (audite_contrib) des entités du scope
        if scope_result and scope_result.entity_ids:
            contributors_query = text("""
                SELECT DISTINCT em.id, em.email, em.first_name, em.last_name, em.entity_id
                FROM entity_member em
                WHERE em.entity_id = ANY(:entity_ids)
                  AND em.is_active = true
                  AND em.email IS NOT NULL
                  AND em.roles::text LIKE '%audite_contrib%'
            """)
            contributors_result = db.execute(contributors_query, {"entity_ids": entity_ids}).fetchall()

            logger.info(f"📋 {len(contributors_result)} contributeur(s) transverse(s) trouvé(s)")

            # Envoyer les magic links aux contributeurs
            contributors_emails_sent = 0
            for contributor in contributors_result:
                try:
                    # Générer le magic link
                    magic_link, _ = generate_magic_link(
                        db=db,
                        user_email=contributor.email,
                        campaign_id=campaign_id,
                        questionnaire_id=campaign_result.questionnaire_id,
                        tenant_id=campaign_result.tenant_id
                    )

                    # Récupérer le nom de l'entité
                    entity_query = text("SELECT name FROM ecosystem_entity WHERE id = :entity_id")
                    entity_result = db.execute(entity_query, {"entity_id": str(contributor.entity_id)}).fetchone()
                    entity_name = entity_result.name if entity_result else "Votre organisation"

                    # Envoyer l'email
                    send_magic_link_email(
                        to_email=contributor.email,
                        user_name=f"{contributor.first_name} {contributor.last_name}",
                        magic_link=magic_link,
                        campaign_name=campaign_result.title,
                        entity_name=entity_name,
                        organization_name=organization_name
                    )
                    contributors_emails_sent += 1
                    logger.info(f"✅ Email envoyé au contributeur {contributor.email}")

                except Exception as e:
                    logger.error(f"❌ Erreur envoi email au contributeur {contributor.email}: {e}")

            logger.info(f"✅ Contributeurs notifiés : {contributors_emails_sent}/{len(contributors_result)} email(s) envoyé(s)")

        # VERSION 2.2 - Envoyer les invitations aux parties prenantes internes (campaign_user)
        logger.info("🔧 [VERSION 2.2] Envoi des invitations aux parties prenantes internes")

        # Récupérer les parties prenantes internes de la campagne
        stakeholders_query = text("""
            SELECT cu.user_id, cu.role, u.email, u.first_name, u.last_name
            FROM campaign_user cu
            JOIN users u ON cu.user_id = u.id
            WHERE cu.campaign_id = :campaign_id
              AND cu.is_active = true
              AND u.email IS NOT NULL
        """)
        stakeholders_result = db.execute(stakeholders_query, {"campaign_id": str(campaign_id)}).fetchall()

        logger.info(f"📋 {len(stakeholders_result)} partie(s) prenante(s) interne(s) à notifier")

        # Récupérer les informations du questionnaire pour le nom du framework
        questionnaire_query = text("""
            SELECT q.name, f.name as framework_name
            FROM questionnaire q
            LEFT JOIN framework f ON q.framework_id = f.id
            WHERE q.id = :questionnaire_id
        """)
        questionnaire_result = db.execute(questionnaire_query, {"questionnaire_id": str(campaign_result.questionnaire_id)}).fetchone()
        framework_name = questionnaire_result.framework_name if questionnaire_result and questionnaire_result.framework_name else "ISO 27001"

        # Récupérer les dates de la campagne
        campaign_dates_query = text("""
            SELECT launch_date, due_date FROM campaign WHERE id = :campaign_id
        """)
        campaign_dates_result = db.execute(campaign_dates_query, {"campaign_id": str(campaign_id)}).fetchone()

        # Formater les dates
        start_date_str = campaign_dates_result.launch_date.strftime("%d/%m/%Y") if campaign_dates_result.launch_date else "Non définie"
        end_date_str = campaign_dates_result.due_date.strftime("%d/%m/%Y") if campaign_dates_result.due_date else "Non définie"

        # URL d'accès à la campagne (lien classique, pas Magic Link)
        campaign_url = f"{FRONTEND_URL}/client/campagnes/{campaign_id}"

        stakeholder_emails_sent = 0
        for stakeholder in stakeholders_result:
            try:
                # Debug: Log du rôle brut depuis la BDD
                logger.info(f"🔍 DEBUG: {stakeholder.email} - Rôle BDD brut = '{stakeholder.role}'")

                # Mapper le rôle technique au libellé utilisateur
                role_label_map = {
                    "owner": "Propriétaire",
                    "manager": "Chef de projet",
                    "auditor": "Auditeur interne",
                    "viewer": "Contributeur"
                }
                recipient_role = role_label_map.get(stakeholder.role, stakeholder.role)

                # Debug: Log du rôle après mapping
                logger.info(f"🔍 DEBUG: {stakeholder.email} - Rôle après mapping = '{recipient_role}'")

                send_campaign_invitation_email(
                    to_email=stakeholder.email,
                    recipient_name=f"{stakeholder.first_name} {stakeholder.last_name}",
                    recipient_role=recipient_role,
                    campaign_name=campaign_result.title,
                    client_name=organization_name,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    framework_name=framework_name,
                    campaign_url=campaign_url
                )
                stakeholder_emails_sent += 1
                logger.info(f"✅ Invitation envoyée à {stakeholder.email} (rôle: {recipient_role})")

            except Exception as e:
                logger.error(f"❌ Erreur envoi invitation à {stakeholder.email}: {e}")
                # Continue avec les autres parties prenantes même en cas d'erreur

        logger.info(f"✅ Invitations envoyées : {stakeholder_emails_sent}/{len(stakeholders_result)} partie(s) prenante(s)")

        total_emails = emails_sent + stakeholder_emails_sent
        logger.info(f"✅ Campagne lancée : {total_emails} email(s) au total ({emails_sent} contacts audités + {stakeholder_emails_sent} parties prenantes)")

        # Retourner la campagne mise à jour
        return await get_campaign(campaign_id, current_user, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors du lancement de la campagne: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du lancement de la campagne: {str(e)}"
        )


@router.get("/{campaign_id}/contacts-count")
async def get_campaign_contacts_count(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Retourne le nombre de contacts qui seront invités lors du lancement de la campagne.
    Basé sur les entity_member des entités du scope.
    """
    try:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = text("""
            SELECT c.id, c.scope_id, c.tenant_id
            FROM campaign c
            WHERE c.id = :campaign_id
              AND c.tenant_id = :tenant_id
        """)
        campaign_result = db.execute(campaign_query, {
            "campaign_id": str(campaign_id),
            "tenant_id": str(current_user.tenant_id)
        }).fetchone()

        if not campaign_result:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Campagne {campaign_id} introuvable ou accès refusé"
            )

        # Vérifier si la campagne a un scope_id
        if not campaign_result.scope_id:
            logger.warning(f"⚠️ Campagne {campaign_id} n'a pas de scope_id défini")
            return {"count": 0, "emails": [], "warning": "Aucun périmètre défini pour cette campagne"}

        # Récupérer les entités du scope
        scope_query = text("""
            SELECT entity_ids FROM campaign_scope WHERE id = :scope_id
        """)
        scope_result = db.execute(scope_query, {"scope_id": str(campaign_result.scope_id)}).fetchone()

        if not scope_result or not scope_result.entity_ids:
            return {"count": 0, "emails": []}

        entity_ids = scope_result.entity_ids

        # Compter les contacts actifs avec email
        contacts_query = text("""
            SELECT COUNT(DISTINCT em.id) as total,
                   array_agg(DISTINCT em.email) as emails
            FROM entity_member em
            WHERE em.entity_id = ANY(:entity_ids)
              AND em.is_active = true
              AND em.email IS NOT NULL
        """)
        contacts_result = db.execute(contacts_query, {"entity_ids": entity_ids}).fetchone()

        total = contacts_result.total if contacts_result else 0
        emails = contacts_result.emails if contacts_result and contacts_result.emails else []
        # Filtrer les None dans la liste d'emails
        emails = [e for e in emails if e]

        logger.info(f"📊 Campagne {campaign_id}: {total} contact(s) dans le scope")

        return {
            "count": total,
            "emails": emails
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur comptage contacts: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du comptage des contacts: {str(e)}"
        )


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: UUID,
    campaign_update: CampaignUpdate,
    current_user: User = Depends(require_permission("CAMPAIGN_UPDATE")),
    db: Session = Depends(get_db)
):
    """
    Met à jour une campagne (isolée par tenant, uniquement si status = 'draft')
    """
    try:
        # ✅ Isolation par tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        # Vérifier que la campagne existe, appartient au tenant et est en brouillon
        check_query = text("""
            SELECT id, status FROM campaign
            WHERE id = :campaign_id
              AND tenant_id = :tenant_id
        """)
        campaign = db.execute(check_query, {
            "campaign_id": str(campaign_id),
            "tenant_id": str(current_user.tenant_id)
        }).fetchone()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Campagne {campaign_id} introuvable ou accès refusé"
            )

        if campaign.status != 'draft':
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Seules les campagnes en brouillon peuvent être modifiées"
            )

        # Construire la requête de mise à jour dynamique
        updates = []
        params = {"campaign_id": str(campaign_id)}

        if campaign_update.title is not None:
            updates.append("title = :title")
            params["title"] = campaign_update.title

        if campaign_update.description is not None:
            updates.append("description = :description")
            params["description"] = campaign_update.description

        if campaign_update.status is not None:
            updates.append("status = :status")
            params["status"] = campaign_update.status

        if campaign_update.launch_date is not None:
            updates.append("launch_date = :launch_date")
            params["launch_date"] = campaign_update.launch_date

        if campaign_update.due_date is not None:
            updates.append("due_date = :due_date")
            params["due_date"] = campaign_update.due_date

        if campaign_update.frozen_date is not None:
            updates.append("frozen_date = :frozen_date")
            params["frozen_date"] = campaign_update.frozen_date

        if not updates:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Aucune modification fournie"
            )

        # Toujours mettre à jour updated_at
        updates.append("updated_at = CURRENT_TIMESTAMP")

        update_query = text(f"""
            UPDATE campaign
            SET {", ".join(updates)}
            WHERE id = :campaign_id
        """)

        db.execute(update_query, params)
        db.commit()

        logger.info(f"✅ Campagne mise à jour: {campaign_id}")

        # Récupérer la campagne mise à jour
        return await get_campaign(campaign_id, current_user, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la mise à jour de la campagne: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour de la campagne: {str(e)}"
        )


@router.delete("/{campaign_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_DELETE")),
    db: Session = Depends(get_db)
):
    """
    Supprime une campagne (isolée par tenant)
    """
    # ✅ Isolation par tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # TODO: Vérifier que la campagne appartient au tenant avant suppression
    # TODO: À implémenter
    raise HTTPException(
        status_code=http_status.HTTP_501_NOT_IMPLEMENTED,
        detail="La suppression de campagne sera implémentée prochainement"
    )


# ============================================================================
# ENDPOINTS : Gestion des utilisateurs de campagne
# ============================================================================

class CampaignUserCreate(BaseModel):
    """
    Schéma pour ajouter un utilisateur à une campagne.
    Le rôle doit être spécifié explicitement (owner, manager, auditor, viewer).
    """
    user_id: UUID
    role: str = Field(..., pattern='^(owner|manager|auditor|viewer)$', description="Rôle: owner, manager, auditor, ou viewer")


class CampaignUserResponse(BaseModel):
    id: UUID
    campaign_id: UUID
    user_id: UUID
    role: str
    assigned_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


@router.post("/{campaign_id}/users", response_model=CampaignUserResponse, status_code=http_status.HTTP_201_CREATED)
async def add_campaign_user(
    campaign_id: UUID,
    user_data: CampaignUserCreate,
    current_user: User = Depends(require_permission("CAMPAIGN_UPDATE")),
    db: Session = Depends(get_db)
):
    """
    Assigne un utilisateur à une campagne (isolée par tenant)
    """
    try:
        # ✅ Isolation par tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        # Vérifier que la campagne existe et appartient au tenant
        campaign_exists = db.execute(
            select(Campaign).where(
                and_(
                    Campaign.id == campaign_id,
                    Campaign.tenant_id == current_user.tenant_id
                )
            )
        ).scalar_one_or_none()

        if not campaign_exists:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Campagne {campaign_id} introuvable ou accès refusé"
            )

        # Vérifier que l'utilisateur existe
        user_exists = db.execute(
            select(User).where(User.id == user_data.user_id)
        ).scalar_one_or_none()

        if not user_exists:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Utilisateur {user_data.user_id} non trouvé"
            )

        # Vérifier si l'assignation existe déjà
        existing = db.execute(
            select(CampaignUser).where(
                and_(
                    CampaignUser.campaign_id == campaign_id,
                    CampaignUser.user_id == user_data.user_id
                )
            )
        ).scalar_one_or_none()

        if existing:
            # Réactiver si désactivé
            if not existing.is_active:
                existing.is_active = True
                existing.role = user_data.role
                db.commit()
                db.refresh(existing)
                logger.info(f"✅ Utilisateur {user_data.user_id} réassigné à la campagne {campaign_id}")
                return existing
            else:
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail="Utilisateur déjà assigné à cette campagne"
                )

        # Créer nouvelle assignation
        campaign_user = CampaignUser(
            campaign_id=campaign_id,
            user_id=user_data.user_id,
            role=user_data.role,
            assigned_by=current_user.id,
            is_active=True
        )

        db.add(campaign_user)
        db.commit()
        db.refresh(campaign_user)

        logger.info(f"✅ Utilisateur {user_data.user_id} assigné à la campagne {campaign_id} avec le rôle {user_data.role}")
        return campaign_user

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de l'assignation de l'utilisateur: {str(e)}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'assignation de l'utilisateur: {str(e)}"
        )


# ============================================================================
# GESTION DU PÉRIMÈTRE DE DOMAINES DES AUDITÉS RESPONSABLES
# ============================================================================

class AuditeDomainScopeCreate(BaseModel):
    """Schema pour créer/mettre à jour le périmètre de domaines d'un audité"""
    entity_member_id: UUID
    domain_ids: List[str] = []  # Liste des IDs de domaines (ex: ['D1', 'D1.1', 'D2'])
    all_domains: bool = False  # Si True, accès à tous les domaines

class AuditeDomainScopeResponse(BaseModel):
    """Schema pour la réponse du périmètre de domaines"""
    id: UUID
    campaign_id: UUID
    entity_member_id: UUID
    domain_ids: List[str]
    all_domains: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.post("/{campaign_id}/domain-scope", response_model=AuditeDomainScopeResponse, status_code=http_status.HTTP_201_CREATED)
async def set_audite_domain_scope(
    campaign_id: UUID,
    scope_data: AuditeDomainScopeCreate,
    current_user: User = Depends(require_permission("CAMPAIGN_UPDATE")),
    db: Session = Depends(get_db)
):
    """
    Définit le périmètre de domaines pour un audité responsable dans une campagne (isolée par tenant).
    Si all_domains=True, l'audité aura accès à tous les domaines du questionnaire.
    Sinon, seuls les domaines listés dans domain_ids seront accessibles.
    """
    try:
        # ✅ Isolation par tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        # Vérifier que la campagne existe et appartient au tenant
        campaign_exists = db.execute(
            text("SELECT id FROM campaign WHERE id = :campaign_id AND tenant_id = :tenant_id"),
            {
                "campaign_id": str(campaign_id),
                "tenant_id": str(current_user.tenant_id)
            }
        ).fetchone()

        if not campaign_exists:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Campagne {campaign_id} introuvable ou accès refusé"
            )

        # Vérifier que l'entity_member existe et a le rôle audite_resp
        member_check = db.execute(
            text("""
                SELECT id, roles FROM entity_member
                WHERE id = :member_id
            """),
            {"member_id": str(scope_data.entity_member_id)}
        ).fetchone()

        if not member_check:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Membre {scope_data.entity_member_id} non trouvé"
            )

        # Vérifier le rôle
        import json
        member_roles = json.loads(member_check.roles) if isinstance(member_check.roles, str) else member_check.roles
        member_roles_lower = [role.lower() if isinstance(role, str) else role for role in member_roles]

        if 'audite_resp' not in member_roles_lower:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Le membre doit avoir le rôle AUDITE_RESP"
            )

        # Vérifier si un périmètre existe déjà
        existing_scope = db.execute(
            text("""
                SELECT id FROM audite_domain_scope
                WHERE campaign_id = :campaign_id AND entity_member_id = :member_id
            """),
            {
                "campaign_id": str(campaign_id),
                "member_id": str(scope_data.entity_member_id)
            }
        ).fetchone()

        if existing_scope:
            # Mettre à jour le périmètre existant
            db.execute(
                text("""
                    UPDATE audite_domain_scope
                    SET domain_ids = :domain_ids,
                        all_domains = :all_domains,
                        updated_at = NOW()
                    WHERE id = :scope_id
                """),
                {
                    "scope_id": str(existing_scope.id),
                    "domain_ids": scope_data.domain_ids,
                    "all_domains": scope_data.all_domains
                }
            )
            scope_id = existing_scope.id
            logger.info(f"✅ Périmètre mis à jour pour member {scope_data.entity_member_id} dans campagne {campaign_id}")
        else:
            # Créer un nouveau périmètre
            import uuid
            scope_id = uuid.uuid4()
            db.execute(
                text("""
                    INSERT INTO audite_domain_scope (
                        id, campaign_id, entity_member_id, domain_ids, all_domains, created_at, updated_at
                    )
                    VALUES (:id, :campaign_id, :member_id, :domain_ids, :all_domains, NOW(), NOW())
                """),
                {
                    "id": str(scope_id),
                    "campaign_id": str(campaign_id),
                    "member_id": str(scope_data.entity_member_id),
                    "domain_ids": scope_data.domain_ids,
                    "all_domains": scope_data.all_domains
                }
            )
            logger.info(f"✅ Périmètre créé pour member {scope_data.entity_member_id} dans campagne {campaign_id}")

        db.commit()

        # Récupérer le périmètre créé/mis à jour
        result = db.execute(
            text("""
                SELECT id, campaign_id, entity_member_id, domain_ids, all_domains, created_at, updated_at
                FROM audite_domain_scope
                WHERE id = :scope_id
            """),
            {"scope_id": str(scope_id)}
        ).fetchone()

        return AuditeDomainScopeResponse(
            id=result.id,
            campaign_id=result.campaign_id,
            entity_member_id=result.entity_member_id,
            domain_ids=result.domain_ids or [],
            all_domains=result.all_domains,
            created_at=result.created_at,
            updated_at=result.updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la définition du périmètre: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la définition du périmètre: {str(e)}"
        )


@router.get("/{campaign_id}/domain-scope/{entity_member_id}", response_model=Optional[AuditeDomainScopeResponse])
async def get_audite_domain_scope(
    campaign_id: UUID,
    entity_member_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère le périmètre de domaines d'un audité responsable dans une campagne (isolée par tenant).
    Retourne None si aucun périmètre n'est défini (= accès complet par défaut).
    """
    try:
        # ✅ Isolation par tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        # Vérifier que la campagne appartient au tenant
        campaign_check = db.execute(
            text("SELECT id FROM campaign WHERE id = :campaign_id AND tenant_id = :tenant_id"),
            {
                "campaign_id": str(campaign_id),
                "tenant_id": str(current_user.tenant_id)
            }
        ).fetchone()

        if not campaign_check:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Campagne {campaign_id} introuvable ou accès refusé"
            )

        result = db.execute(
            text("""
                SELECT id, campaign_id, entity_member_id, domain_ids, all_domains, created_at, updated_at
                FROM audite_domain_scope
                WHERE campaign_id = :campaign_id AND entity_member_id = :member_id
            """),
            {
                "campaign_id": str(campaign_id),
                "member_id": str(entity_member_id)
            }
        ).fetchone()

        if not result:
            return None

        return AuditeDomainScopeResponse(
            id=result.id,
            campaign_id=result.campaign_id,
            entity_member_id=result.entity_member_id,
            domain_ids=result.domain_ids or [],
            all_domains=result.all_domains,
            created_at=result.created_at,
            updated_at=result.updated_at
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du périmètre: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du périmètre: {str(e)}"
        )


@router.get("/{campaign_id}/details", response_model=CampaignDetailsResponse)
async def get_campaign_details(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les détails complets d'une campagne avec KPIs et stakeholders
    pour la page de détail de campagne
    """
    try:
        # Récupérer la campagne
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        # Construire la réponse de base de la campagne
        campaign_response = CampaignResponse(
            id=campaign.id,
            tenant_id=campaign.tenant_id,
            title=campaign.title,
            description=campaign.description,
            questionnaire_id=campaign.questionnaire_id,
            status=campaign.status or 'draft',
            scope_id=campaign.scope_id,
            recurrence_type=campaign.recurrence_type,
            recurrence_interval=campaign.recurrence_interval or 1,
            next_occurrence_date=campaign.next_occurrence_date,
            recurrence_end_date=campaign.recurrence_end_date,
            launch_date=campaign.launch_date,
            due_date=campaign.due_date,
            frozen_date=campaign.frozen_date,
            created_at=campaign.created_at,
            updated_at=campaign.updated_at,
            created_by=campaign.created_by
        )

        # Calculer les KPIs
        kpis = CampaignKPIs()

        # Importer tous les modèles nécessaires depuis audit.py
        from src.models.audit import Question, Questionnaire, QuestionAnswer

        # 1. Questions total (depuis le questionnaire)
        questionnaire_query = select(Questionnaire).where(Questionnaire.id == campaign.questionnaire_id)
        questionnaire = db.execute(questionnaire_query).scalar_one_or_none()

        if questionnaire:
            questions_count_query = select(func.count(Question.id)).where(
                Question.questionnaire_id == questionnaire.id
            )
            kpis.total_questions = db.execute(questions_count_query).scalar() or 0

        # 2. Questions répondues (depuis question_answer)
        answered_query = select(func.count(func.distinct(QuestionAnswer.question_id))).where(
            and_(
                QuestionAnswer.campaign_id == campaign_id,
                QuestionAnswer.answer_value.isnot(None)
            )
        )
        kpis.answered_questions = db.execute(answered_query).scalar() or 0

        # 3. Questions validées
        # TODO: Implémenter quand le modèle AuditQuestionReview sera créé
        # Pour l'instant, on laisse à 0
        kpis.validated_questions = 0

        # 4. Progression globale
        if kpis.total_questions > 0:
            kpis.global_progress = int((kpis.answered_questions / kpis.total_questions) * 100)

        # 5. Organismes (entités auditées)
        # Récupérer les entités depuis campaign_scope via campaign.scope_id
        from src.models.campaign import CampaignScope
        from src.models.audit import Audit

        logger.info(f"🔍 Campaign scope_id: {campaign.scope_id}")

        if campaign.scope_id:
            scope_query = select(CampaignScope).where(CampaignScope.id == campaign.scope_id)
            scope = db.execute(scope_query).scalar_one_or_none()
            logger.info(f"🔍 Scope trouvé: {scope is not None}, entity_ids: {scope.entity_ids if scope else 'N/A'}")
        else:
            scope = None
            logger.info("⚠️ Pas de scope_id sur cette campagne")

        if scope and scope.entity_ids:
            kpis.entities_count = len(scope.entity_ids)
            logger.info(f"✅ Nombre d'entités: {kpis.entities_count}")

            # Compter les audits créés pour cette campagne
            # Via QuestionAnswer.audit_id distinct (car Audit n'a pas de campaign_id)
            audits_count_query = select(func.count(func.distinct(QuestionAnswer.audit_id))).where(
                QuestionAnswer.campaign_id == campaign_id
            )
            total_audits = db.execute(audits_count_query).scalar() or 0
            logger.info(f"📊 Nombre d'audits créés: {total_audits}")

            # Compter les audits complétés (toutes questions répondues)
            # On groupe par audit_id et on compte les réponses complètes
            completed_audits_subquery = select(QuestionAnswer.audit_id).where(
                and_(
                    QuestionAnswer.campaign_id == campaign_id,
                    QuestionAnswer.answer_value.isnot(None)
                )
            ).group_by(QuestionAnswer.audit_id).having(
                func.count(QuestionAnswer.id) >= kpis.total_questions
            ).subquery()

            completed_count_query = select(func.count()).select_from(completed_audits_subquery)
            kpis.entities_completed = db.execute(completed_count_query).scalar() or 0
            logger.info(f"✅ Audits complétés: {kpis.entities_completed}")
        else:
            kpis.entities_count = 0
            kpis.entities_completed = 0
            logger.warning("⚠️ Aucune entité trouvée dans le scope")

        # 6. Contributeurs (entity_member qui ont répondu)
        contributors_total_query = select(func.count(func.distinct(QuestionAnswer.answered_by))).where(
            QuestionAnswer.campaign_id == campaign_id
        )
        kpis.contributors_total = db.execute(contributors_total_query).scalar() or 0

        # Contributeurs actifs (qui ont répondu récemment)
        contributors_active_query = select(func.count(func.distinct(QuestionAnswer.answered_by))).where(
            and_(
                QuestionAnswer.campaign_id == campaign_id,
                QuestionAnswer.answered_at >= func.current_timestamp() - text("INTERVAL '7 days'")
            )
        )
        kpis.contributors_active = db.execute(contributors_active_query).scalar() or 0

        # 7. Non-conformités
        # Compter les NC majeures (non_compliant_major)
        nc_major_query = select(func.count(QuestionAnswer.id)).where(
            and_(
                QuestionAnswer.campaign_id == campaign_id,
                QuestionAnswer.compliance_status == 'non_compliant_major'
            )
        )
        kpis.nc_major = db.execute(nc_major_query).scalar() or 0

        # Compter les NC mineures (non_compliant_minor)
        nc_minor_query = select(func.count(QuestionAnswer.id)).where(
            and_(
                QuestionAnswer.campaign_id == campaign_id,
                QuestionAnswer.compliance_status == 'non_compliant_minor'
            )
        )
        kpis.nc_minor = db.execute(nc_minor_query).scalar() or 0

        logger.info(f"📊 NC Majeures: {kpis.nc_major}, NC Mineures: {kpis.nc_minor}")

        # 8. Documents
        from src.models.attachment import AnswerAttachment

        # Compter les documents fournis
        # AnswerAttachment n'a pas de campaign_id direct, on doit joindre via QuestionAnswer
        documents_provided_query = select(func.count(AnswerAttachment.id)).select_from(AnswerAttachment).join(
            QuestionAnswer, QuestionAnswer.id == AnswerAttachment.answer_id
        ).where(
            and_(
                QuestionAnswer.campaign_id == campaign_id,
                AnswerAttachment.deleted_at.is_(None)
            )
        )
        kpis.documents_provided = db.execute(documents_provided_query).scalar() or 0

        # Compter les questions qui requièrent des documents
        # On compte les questions qui ont evidence_types défini (non null et non vide)
        # evidence_types est JSONB, on vérifie que c'est un tableau non vide
        documents_required_query = select(func.count(Question.id)).where(
            and_(
                Question.questionnaire_id == campaign.questionnaire_id,
                Question.evidence_types.isnot(None),
                func.jsonb_array_length(Question.evidence_types) > 0
            )
        )
        kpis.documents_required = db.execute(documents_required_query).scalar() or 0

        # 9. Temps écoulé
        if campaign.launch_date:
            from datetime import date
            today = date.today()
            kpis.days_elapsed = (today - campaign.launch_date).days

            if campaign.due_date:
                kpis.days_remaining = (campaign.due_date - today).days

        # Récupérer les stakeholders
        stakeholders_query = select(
            CampaignUser.id,
            CampaignUser.user_id,
            CampaignUser.role,
            CampaignUser.assigned_at,
            User.first_name,
            User.last_name,
            User.email
        ).join(
            User, CampaignUser.user_id == User.id
        ).where(
            and_(
                CampaignUser.campaign_id == campaign_id,
                CampaignUser.is_active == True
            )
        ).order_by(CampaignUser.assigned_at)

        stakeholders_result = db.execute(stakeholders_query).all()

        stakeholders = [
            StakeholderResponse(
                id=row.id,
                user_id=row.user_id,
                first_name=row.first_name or '',
                last_name=row.last_name or '',
                email=row.email,
                role=row.role,
                assigned_at=row.assigned_at
            )
            for row in stakeholders_result
        ]

        return CampaignDetailsResponse(
            campaign=campaign_response,
            kpis=kpis,
            stakeholders=stakeholders
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des détails: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des détails: {str(e)}"
        )


# ============================================================================
# ENDPOINT : Onglet Progression
# ============================================================================

@router.get("/{campaign_id}/progress", response_model=CampaignProgressResponse)
async def get_campaign_progress(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les données de progression pour l'onglet Progression
    - Progression par organisme (Niveau 2)
    - Progression par contributeur (Niveau 3)
    """
    try:
        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        entities = []
        contributors = []

        # Récupérer le scope de la campagne
        if campaign.scope_id:
            scope_query = select(CampaignScope).where(CampaignScope.id == campaign.scope_id)
            scope = db.execute(scope_query).scalar_one_or_none()

            if scope and scope.entity_ids:
                # Récupérer les entités du scope
                entities_query = select(EcosystemEntity).where(
                    EcosystemEntity.id.in_(scope.entity_ids)
                )
                entities_data = db.execute(entities_query).scalars().all()

                # Récupérer le nombre total de questions du questionnaire
                total_questions_query = select(func.count(Question.id)).where(
                    and_(
                        Question.questionnaire_id == campaign.questionnaire_id,
                        Question.is_active == True
                    )
                )
                total_questions = db.execute(total_questions_query).scalar() or 0

                # Construire la liste des progressions par entité
                for entity in entities_data:
                    # Trouver tous les members de cette entité
                    members_query = text("""
                        SELECT id FROM entity_member
                        WHERE entity_id = :entity_id
                    """)
                    members_result = db.execute(members_query, {"entity_id": str(entity.id)}).fetchall()
                    member_ids = [str(row.id) for row in members_result]

                    # Compter les réponses données par les members de cette entité
                    if member_ids:
                        answered_questions_query = select(func.count(func.distinct(QuestionAnswer.question_id))).where(
                            and_(
                                QuestionAnswer.campaign_id == campaign_id,
                                QuestionAnswer.answered_by.in_(member_ids),
                                QuestionAnswer.is_current == True
                            )
                        )
                        questions_answered = db.execute(answered_questions_query).scalar() or 0
                    else:
                        questions_answered = 0

                    # Calculer le pourcentage
                    progress_percent = int((questions_answered / total_questions * 100)) if total_questions > 0 else 0

                    entity_progress = EntityProgressResponse(
                        entity_id=entity.id,
                        entity_name=entity.name,
                        invited_at=campaign.launch_date or campaign.created_at,
                        progress_percent=progress_percent,
                        questions_answered=questions_answered,
                        questions_total=total_questions,
                        last_activity=None,  # TODO: Max(updated_at) depuis question_answer
                        is_inactive=False  # TODO: Calculer selon last_activity
                    )
                    entities.append(entity_progress)

                # TODO: Récupérer les contributeurs
                # Nécessite la table entity_member ou une relation campaign -> users -> entity
                contributors = []
        else:
            logger.warning(f"⚠️ Aucun scope_id pour la campagne {campaign_id}")

        return CampaignProgressResponse(
            entities=entities,
            contributors=contributors
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération de la progression: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération de la progression: {str(e)}"
        )


# ============================================================================
# ENDPOINT : Relance de campagne
# ============================================================================

@router.post("/{campaign_id}/entities/{entity_id}/remind")
async def send_campaign_reminder(
    campaign_id: UUID,
    entity_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_UPDATE")),
    db: Session = Depends(get_db)
):
    """
    Envoie un email de relance aux membres d'une entité qui n'ont pas encore complété leur audit

    Conditions:
    - L'entité doit avoir une progression < 100%
    - Envoie l'email à tous les entity_member de cette entité
    - Utilise le magic_link existant stocké dans audit_token
    """
    try:
        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        # Récupérer le nom du questionnaire/référentiel
        questionnaire_query = text("""
            SELECT name FROM questionnaire WHERE id = :questionnaire_id
        """)
        questionnaire_result = db.execute(
            questionnaire_query,
            {"questionnaire_id": str(campaign.questionnaire_id)}
        ).fetchone()
        referentiel_name = questionnaire_result.name if questionnaire_result else "Audit"

        # Récupérer les informations de l'entité
        entity_query = select(EcosystemEntity).where(
            and_(
                EcosystemEntity.id == entity_id,
                EcosystemEntity.tenant_id == current_user.tenant_id
            )
        )
        entity = db.execute(entity_query).scalar_one_or_none()

        if not entity:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Entité non trouvée"
            )

        logger.info(f"🎯 Entité sélectionnée: {entity.name} (ID: {entity_id})")

        # Calculer la progression de cette entité
        total_questions_query = select(func.count(Question.id)).where(
            and_(
                Question.questionnaire_id == campaign.questionnaire_id,
                Question.is_active == True
            )
        )
        total_questions = db.execute(total_questions_query).scalar() or 0

        # Trouver tous les members de cette entité
        logger.info(f"🔍 Recherche des membres pour entity_id={entity_id}")
        members_query = text("""
            SELECT id, email, first_name, last_name FROM entity_member
            WHERE entity_id = :entity_id AND is_active = true AND email IS NOT NULL
        """)
        members_result = db.execute(members_query, {"entity_id": str(entity_id)}).fetchall()
        logger.info(f"👥 {len(members_result)} membres trouvés: {[m.email for m in members_result]}")

        if not members_result:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Aucun membre actif trouvé pour cette entité"
            )

        member_ids = [str(row.id) for row in members_result]

        # Compter les réponses données par les members de cette entité
        if member_ids:
            answered_questions_query = select(func.count(func.distinct(QuestionAnswer.question_id))).where(
                and_(
                    QuestionAnswer.campaign_id == campaign_id,
                    QuestionAnswer.answered_by.in_(member_ids),
                    QuestionAnswer.is_current == True
                )
            )
            questions_answered = db.execute(answered_questions_query).scalar() or 0
        else:
            questions_answered = 0

        # Calculer le pourcentage
        progress_percent = int((questions_answered / total_questions * 100)) if total_questions > 0 else 0

        # Vérifier que la progression est < 100%
        if progress_percent >= 100:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cette entité a déjà complété l'audit (100%)"
            )

        logger.info(
            f"📧 [RELANCE] Entité {entity.name} - Progression: {progress_percent}% "
            f"({questions_answered}/{total_questions})"
        )

        # Envoyer l'email de relance à chaque membre
        emails_sent = 0
        errors = []

        for member in members_result:
            try:
                # Récupérer le magic_link existant depuis audit_tokens
                token_query = text("""
                    SELECT token_hash, expires_at FROM audit_tokens
                    WHERE campaign_id = :campaign_id
                      AND user_email = :email
                      AND revoked = false
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                token_result = db.execute(
                    token_query,
                    {
                        "campaign_id": str(campaign_id),
                        "email": member.email
                    }
                ).fetchone()

                if not token_result:
                    logger.warning(
                        f"⚠️ Aucun magic link trouvé pour {member.email} - "
                        f"Cette personne n'a probablement pas été invitée"
                    )
                    errors.append(f"{member.email}: Aucun lien magique trouvé")
                    continue

                # Reconstruire le magic link depuis le hash stocké
                # Note: Nous ne pouvons pas reconstruire le JWT original depuis le hash
                # Il faut générer un nouveau token ou stocker le token original
                # Pour simplifier, on va générer un nouveau magic link

                from src.services.magic_link_service import generate_magic_link

                magic_link, _ = generate_magic_link(
                    db=db,
                    user_email=member.email,
                    campaign_id=campaign_id,
                    questionnaire_id=campaign.questionnaire_id,
                    tenant_id=current_user.tenant_id
                )

                # Formater la date d'expiration
                expires_at = token_result.expires_at
                expiration_date = expires_at.strftime("%d %B %Y") if expires_at else "date non définie"

                # Envoyer l'email de relance
                logger.info(f"📤 Envoi relance à {member.email} pour entité '{entity.name}'")
                send_campaign_reminder_email(
                    to_email=member.email,
                    audite_firstname=member.first_name or "",
                    audite_lastname=member.last_name or "",
                    referentiel_name=referentiel_name,
                    entity_name=entity.name,
                    magic_link=magic_link,
                    expiration_date=expiration_date
                )

                emails_sent += 1
                logger.info(f"✅ Relance envoyée à {member.email} (entité: {entity.name})")

            except Exception as e:
                # Rollback en cas d'erreur SQL pour permettre aux tentatives suivantes
                db.rollback()
                error_msg = f"{member.email}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"❌ Erreur envoi relance à {member.email}: {e}")

        # Retourner le résumé
        return {
            "success": True,
            "entity_name": entity.name,
            "progress_percent": progress_percent,
            "emails_sent": emails_sent,
            "total_members": len(members_result),
            "errors": errors if errors else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'envoi des relances: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'envoi des relances: {str(e)}"
        )


# ============================================================================
# ENDPOINT : Onglet Périmètre
# ============================================================================

@router.get("/{campaign_id}/scope", response_model=CampaignScopeResponse)
async def get_campaign_scope(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la liste des organismes du périmètre pour l'onglet Périmètre
    """
    try:
        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        entities = []

        # Récupérer le scope de la campagne
        if campaign.scope_id:
            scope_query = select(CampaignScope).where(CampaignScope.id == campaign.scope_id)
            scope = db.execute(scope_query).scalar_one_or_none()

            if scope and scope.entity_ids:
                # Récupérer les entités du scope
                entities_query = select(EcosystemEntity).where(
                    EcosystemEntity.id.in_(scope.entity_ids)
                )
                entities_data = db.execute(entities_query).scalars().all()

                # Construire un mapping code APE -> libellé
                ape_codes = [e.ape_code for e in entities_data if e.ape_code]
                ape_labels = {}
                if ape_codes:
                    ape_query = text("SELECT code, label FROM naf_codes WHERE code = ANY(:codes)")
                    ape_results = db.execute(ape_query, {"codes": ape_codes}).fetchall()
                    ape_labels = {row[0]: row[1] for row in ape_results}

                # Construire la liste des entités du périmètre
                for entity in entities_data:
                    # Utiliser le libellé NAF si disponible, sinon le code brut
                    sector_label = ape_labels.get(entity.ape_code, entity.ape_code)

                    entity_scope = EntityScopeResponse(
                        entity_id=entity.id,
                        entity_name=entity.name,
                        entity_type=entity.entity_category,
                        country=entity.country_code,
                        sector=sector_label,  # Libellé NAF au lieu du code
                        added_at=scope.created_at,
                        contributors_count=0,  # TODO: Compter depuis entity_member
                        last_audit_date=None,  # TODO: Récupérer depuis historique
                        last_audit_score=None  # TODO: Récupérer depuis historique
                    )
                    entities.append(entity_scope)

        return CampaignScopeResponse(
            entities=entities,
            total_count=len(entities)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du périmètre: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du périmètre: {str(e)}"
        )


@router.get("/{campaign_id}/entities", response_model=List[dict])
async def get_campaign_entities(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la liste simplifiée des entités d'une campagne pour le dropdown Organisme.

    Retourne: [{"id": "uuid", "name": "Nom de l'entité"}, ...]
    """
    try:
        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        entities = []

        # Récupérer le scope de la campagne
        if campaign.scope_id:
            scope_query = select(CampaignScope).where(CampaignScope.id == campaign.scope_id)
            scope = db.execute(scope_query).scalar_one_or_none()

            if scope and scope.entity_ids:
                # Récupérer les entités du scope
                entities_query = select(EcosystemEntity).where(
                    EcosystemEntity.id.in_(scope.entity_ids)
                )
                entities_data = db.execute(entities_query).scalars().all()

                # Construire la liste simplifiée
                for entity in entities_data:
                    entities.append({
                        "id": str(entity.id),
                        "name": entity.name
                    })

        return entities

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des entités: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des entités: {str(e)}"
        )


# ============================================================================
# ENDPOINT : Couverture Cross-Référentielle
# ============================================================================

@router.get("/{campaign_id}/cross-referential-coverage", response_model=CampaignCrossReferentialResponse)
async def get_campaign_cross_referential_coverage(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Calcule la couverture cross-référentielle d'une campagne.

    Pour une campagne basée sur un framework (ex: ISO 27001), retourne le % de couverture
    des autres frameworks (ISO 27002, PSSI, etc.) via les Control Points partagés.

    IMPORTANT: La couverture est calculée uniquement sur les requirements effectivement
    inclus dans le questionnaire de la campagne (qui peut être un sous-ensemble du framework complet).
    """
    try:
        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        # Requête SQL pour calculer la couverture cross-référentielle
        coverage_query = text("""
            WITH campaign_info AS (
                SELECT
                    c.id as campaign_id,
                    c.questionnaire_id,
                    c.title as campaign_title
                FROM campaign c
                WHERE c.id = :campaign_id
            ),
            campaign_requirements AS (
                -- Requirements effectivement inclus dans le questionnaire de la campagne
                SELECT DISTINCT q.requirement_id
                FROM question q
                JOIN campaign_info ci ON ci.questionnaire_id = q.questionnaire_id
                WHERE q.requirement_id IS NOT NULL
            ),
            campaign_framework AS (
                -- Framework de base de la campagne (déterminé depuis les requirements)
                SELECT DISTINCT
                    r.framework_id,
                    f.code as framework_code,
                    f.name as framework_name
                FROM requirement r
                JOIN framework f ON f.id = r.framework_id
                WHERE r.id IN (SELECT requirement_id FROM campaign_requirements)
                LIMIT 1
            ),
            campaign_control_points AS (
                -- Control Points liés aux requirements de la campagne
                SELECT DISTINCT rcp.control_point_id
                FROM requirement_control_point rcp
                WHERE rcp.requirement_id IN (SELECT requirement_id FROM campaign_requirements)
            ),
            cross_framework_coverage AS (
                -- Couverture des autres frameworks via les CPs partagés
                SELECT
                    f.id as framework_id,
                    f.code as framework_code,
                    f.name as framework_name,
                    COUNT(DISTINCT r.id) as requirements_covered,
                    (
                        SELECT COUNT(DISTINCT r2.id)
                        FROM requirement r2
                        WHERE r2.framework_id = f.id
                    ) as total_requirements
                FROM framework f
                JOIN requirement r ON r.framework_id = f.id
                JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
                WHERE rcp.control_point_id IN (SELECT control_point_id FROM campaign_control_points)
                  AND f.id != COALESCE((SELECT framework_id FROM campaign_framework), '00000000-0000-0000-0000-000000000000'::uuid)
                  AND f.is_active = true
                GROUP BY f.id, f.code, f.name
            ),
            campaign_stats AS (
                SELECT
                    (SELECT COUNT(*) FROM campaign_requirements) as total_requirements_in_campaign,
                    (SELECT COUNT(*) FROM campaign_control_points) as total_control_points
            )
            SELECT
                ci.campaign_id,
                ci.campaign_title,
                cf.framework_code as base_framework_code,
                cf.framework_name as base_framework_name,
                cs.total_requirements_in_campaign,
                cs.total_control_points,
                COALESCE(
                    JSON_AGG(
                        JSON_BUILD_OBJECT(
                            'framework_code', cfc.framework_code,
                            'framework_name', cfc.framework_name,
                            'requirements_covered', cfc.requirements_covered,
                            'total_requirements', cfc.total_requirements,
                            'coverage_percentage', ROUND((cfc.requirements_covered::numeric / cfc.total_requirements::numeric * 100), 1)
                        ) ORDER BY (cfc.requirements_covered::numeric / cfc.total_requirements::numeric) DESC
                    ),
                    '[]'::json
                ) as frameworks_coverage
            FROM campaign_info ci
            CROSS JOIN campaign_stats cs
            LEFT JOIN campaign_framework cf ON true
            LEFT JOIN cross_framework_coverage cfc ON true
            GROUP BY ci.campaign_id, ci.campaign_title, cf.framework_code, cf.framework_name,
                     cs.total_requirements_in_campaign, cs.total_control_points
        """)

        result = db.execute(coverage_query, {"campaign_id": str(campaign_id)}).fetchone()

        if not result:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Impossible de calculer la couverture"
            )

        # Parser le résultat
        frameworks_coverage = []
        if result.frameworks_coverage and result.frameworks_coverage != []:
            for fw_data in result.frameworks_coverage:
                if fw_data and isinstance(fw_data, dict) and fw_data.get('framework_code'):
                    frameworks_coverage.append(FrameworkCoverageResponse(
                        framework_code=fw_data['framework_code'],
                        framework_name=fw_data['framework_name'],
                        requirements_covered=fw_data['requirements_covered'],
                        total_requirements=fw_data['total_requirements'],
                        coverage_percentage=fw_data['coverage_percentage']
                    ))

        return CampaignCrossReferentialResponse(
            campaign_id=result.campaign_id,
            campaign_title=result.campaign_title,
            base_framework_code=result.base_framework_code,
            base_framework_name=result.base_framework_name,
            total_requirements_in_campaign=result.total_requirements_in_campaign or 0,
            total_control_points=result.total_control_points or 0,
            frameworks_coverage=frameworks_coverage
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors du calcul de la couverture cross-référentielle: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du calcul de la couverture: {str(e)}"
        )


@router.get("/{campaign_id}/documents", response_model=CampaignDocumentsResponse)
async def get_campaign_documents(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère tous les documents uploadés pour une campagne (Onglet Documents)

    Requiert les permissions:
    - CAMPAIGN_READ : Pour accéder à la campagne
    - GED_READ : Pour voir les documents (sauf ADMIN/SUPER_ADMIN)
    """
    try:
        # Vérifier la permission GED_READ (sauf pour ADMIN/SUPER_ADMIN)
        from src.dependencies_keycloak import get_user_permissions_from_db

        user_permissions = get_user_permissions_from_db(db, current_user)
        is_admin = any(role.code in ['ADMIN', 'SUPER_ADMIN'] for role in current_user.roles) if hasattr(current_user, 'roles') and current_user.roles else False

        # Vérifier aussi via la requête SQL si l'utilisateur est admin
        if not is_admin:
            admin_check = text("""
                SELECT 1 FROM user_role ur
                JOIN role r ON r.id = ur.role_id
                WHERE ur.user_id = CAST(:user_id AS uuid)
                  AND r.code IN ('ADMIN', 'SUPER_ADMIN')
                LIMIT 1
            """)
            is_admin = db.execute(admin_check, {"user_id": str(current_user.id)}).fetchone() is not None

        if not is_admin and 'GED_READ' not in user_permissions:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Vous n'avez pas la permission de consulter les documents (GED_READ requise)"
            )

        # Vérifier l'existence de la campagne et l'accès
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne introuvable"
            )

        # Les admins avec GED_READ peuvent accéder directement aux documents
        # Sans avoir besoin d'être assignés à la campagne via campaign_user
        if is_admin or 'GED_READ' in user_permissions:
            user_role = 'admin'  # Rôle virtuel pour les admins
            logger.info(f"📄 Accès admin/GED aux documents pour campagne {campaign_id}")
        else:
            # Pour les autres utilisateurs, vérifier le rôle dans la campagne
            user_role_query = text("""
                SELECT role
                FROM campaign_user
                WHERE campaign_id = :campaign_id
                  AND user_id = :user_id
                  AND is_active = true
            """)

            user_role_result = db.execute(
                user_role_query,
                {
                    "campaign_id": str(campaign_id),
                    "user_id": str(current_user.id)
                }
            ).fetchone()

            if not user_role_result:
                raise HTTPException(
                    status_code=http_status.HTTP_403_FORBIDDEN,
                    detail="Vous n'êtes pas autorisé à accéder à cette campagne"
                )

            # Seuls les owner, manager et auditor peuvent accéder aux documents
            # viewer ne peut pas accéder aux documents
            user_role = user_role_result[0]
            if user_role == 'viewer':
                raise HTTPException(
                    status_code=http_status.HTTP_403_FORBIDDEN,
                    detail="Vous n'avez pas les droits nécessaires pour accéder aux documents de cette campagne"
                )

        logger.info(f"📄 Récupération documents pour campagne {campaign_id} (user_role={user_role})")

        # Récupérer tous les documents via SQL
        documents_query = text("""
            WITH campaign_audits AS (
                -- Récupérer tous les audits liés à la campagne via audit_tokens
                SELECT DISTINCT a.id as audit_id
                FROM audit a
                INNER JOIN audit_tokens at ON a.questionnaire_id = at.questionnaire_id
                WHERE at.campaign_id = :campaign_id
                  AND a.tenant_id = :tenant_id
                  AND at.revoked = false
            )
            SELECT
                aa.id,
                aa.answer_id,
                aa.audit_id,
                aa.filename,
                aa.original_filename,
                aa.file_size,
                aa.mime_type,
                aa.file_extension,
                aa.attachment_type,
                aa.description,
                aa.virus_scan_status,
                aa.uploaded_by,
                aa.uploaded_at,

                -- Infos de l'utilisateur (users OU entity_member)
                COALESCE(u.first_name, em_uploader.first_name) as uploaded_by_first_name,
                COALESCE(u.last_name, em_uploader.last_name) as uploaded_by_last_name,
                COALESCE(u.email, em_uploader.email) as uploaded_by_email,

                -- Infos de la question
                q.id as question_id,
                q.question_text as question_text,
                q.sort_order as question_order,

                -- Infos de l'entité (via question_answer.answered_by → entity_member → ecosystem_entity)
                em.entity_id as entity_id,
                ee.name as entity_name

            FROM answer_attachment aa
            INNER JOIN campaign_audits ca ON aa.audit_id = ca.audit_id
            INNER JOIN question_answer qa ON aa.answer_id = qa.id
            INNER JOIN question q ON qa.question_id = q.id
            LEFT JOIN users u ON aa.uploaded_by = u.id
            LEFT JOIN entity_member em ON qa.answered_by = em.id
            LEFT JOIN entity_member em_uploader ON aa.uploaded_by = em_uploader.id
            LEFT JOIN ecosystem_entity ee ON em.entity_id = ee.id
            WHERE aa.is_active = true
              AND aa.deleted_at IS NULL
            ORDER BY aa.uploaded_at DESC
        """)

        results = db.execute(
            documents_query,
            {
                "campaign_id": str(campaign_id),
                "tenant_id": str(current_user.tenant_id)
            }
        ).fetchall()

        # Construire la liste des documents
        documents = []
        total_size_bytes = 0
        by_type = {}
        by_entity = {}

        for row in results:
            file_size_mb = round(row.file_size / (1024 * 1024), 2)
            total_size_bytes += row.file_size

            # Compter par type
            doc_type = row.attachment_type or 'other'
            by_type[doc_type] = by_type.get(doc_type, 0) + 1

            # Compter par entité
            entity_name = row.entity_name or 'Non assigné'
            by_entity[entity_name] = by_entity.get(entity_name, 0) + 1

            # Logs pour debug uploaded_by
            logger.info(f"📄 Document {row.original_filename}: uploaded_by={row.uploaded_by}, first_name={row.uploaded_by_first_name}, last_name={row.uploaded_by_last_name}, email={row.uploaded_by_email}")

            doc = DocumentResponse(
                id=row.id,
                answer_id=row.answer_id,
                audit_id=row.audit_id,
                question_id=row.question_id,
                question_text=row.question_text,
                question_order=row.question_order,
                filename=row.filename,
                original_filename=row.original_filename,
                file_size=row.file_size,
                file_size_mb=file_size_mb,
                mime_type=row.mime_type,
                file_extension=row.file_extension,
                attachment_type=row.attachment_type,
                description=row.description,
                virus_scan_status=row.virus_scan_status,
                is_safe=row.virus_scan_status in ('clean', 'skipped'),
                uploaded_by=row.uploaded_by,
                uploaded_by_name=f"{row.uploaded_by_first_name or ''} {row.uploaded_by_last_name or ''}".strip() if row.uploaded_by_first_name else None,
                uploaded_by_email=row.uploaded_by_email,
                uploaded_at=row.uploaded_at,
                entity_id=row.entity_id,
                entity_name=row.entity_name
            )
            documents.append(doc)

        # Statistiques
        stats = DocumentStats(
            total_documents=len(documents),
            total_size_mb=round(total_size_bytes / (1024 * 1024), 2),
            by_type=by_type,
            by_entity=by_entity,
            # TODO: Calculer les questions nécessitant des docs
            total_questions_requiring_docs=0,
            questions_with_docs=len(set(doc.question_id for doc in documents))
        )

        logger.info(f"✅ {len(documents)} documents trouvés")

        return CampaignDocumentsResponse(
            stats=stats,
            documents=documents,
            total_count=len(documents)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur documents campagne: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des documents: {str(e)}"
        )


# ============================================================================
# ENDPOINT : Gel (Freeze) d'une campagne
# ============================================================================

@router.post("/{campaign_id}/freeze", response_model=CampaignFreezeResponse)
async def freeze_campaign(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_UPDATE")),
    db: Session = Depends(get_db)
) -> CampaignFreezeResponse:
    """
    Gèle une campagne d'audit (transition vers status='frozen')

    Conditions:
    - Seuls les auditeurs (campaign_user avec role='auditor'/'owner'/'manager') peuvent geler
    - La campagne doit être en cours (status='ongoing')
    - Une fois figée, aucune écriture n'est possible (réponses, fichiers)

    Returns:
        CampaignFreezeResponse: Message de confirmation avec la date de gel
    """
    try:
        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.tenant_id == current_user.tenant_id
            )
        )
        campaign = db.execute(campaign_query).scalar_one_or_none()

        if not campaign:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne introuvable"
            )

        # Vérifier que l'utilisateur a le droit de geler (owner, manager, auditor)
        user_role_query = text("""
            SELECT role
            FROM campaign_user
            WHERE campaign_id = :campaign_id
              AND user_id = :user_id
              AND is_active = true
        """)

        user_role_result = db.execute(
            user_role_query,
            {
                "campaign_id": str(campaign_id),
                "user_id": str(current_user.id)
            }
        ).fetchone()

        if not user_role_result:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Vous n'êtes pas autorisé à gérer cette campagne"
            )

        user_role = user_role_result[0]
        if user_role not in ['owner', 'manager', 'auditor']:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Seuls les auditeurs, managers et propriétaires peuvent geler une campagne"
            )

        # Vérifier que la campagne n'est pas déjà figée
        if campaign.status == 'frozen':
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="La campagne est déjà figée"
            )

        # Mettre à jour le statut et la date de gel
        from datetime import date
        campaign.status = 'frozen'
        campaign.frozen_date = date.today()
        campaign.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(campaign)

        logger.info(f"🔒 Campagne {campaign_id} figée par {current_user.email} (role={user_role})")

        return CampaignFreezeResponse(
            success=True,
            message="Campagne figée avec succès",
            campaign_id=campaign_id,
            frozen_date=campaign.frozen_date,
            status=campaign.status
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors du gel de la campagne: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du gel de la campagne: {str(e)}"
        )


# ============================================================================
# ENDPOINTS : Entités de la campagne (pour création d'action)
# ============================================================================

@router.get("/{campaign_id}/entities")
async def get_campaign_entities(
    campaign_id: UUID,
    current_user: User = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la liste des entités (organismes) associées à une campagne.
    Utilisé pour le modal de création d'action dans le plan d'action.

    Args:
        campaign_id: ID de la campagne

    Returns:
        Liste des entités avec id et name
    """
    try:
        logger.info(f"📋 Récupération des entités pour campagne {campaign_id}")

        # Vérifier que la campagne existe et appartient au tenant
        campaign_query = text("""
            SELECT c.id, cs.entity_ids
            FROM campaign c
            LEFT JOIN campaign_scope cs ON c.scope_id = cs.id
            WHERE c.id = CAST(:campaign_id AS uuid)
              AND c.tenant_id = CAST(:tenant_id AS uuid)
        """)
        campaign_result = db.execute(campaign_query, {
            "campaign_id": str(campaign_id),
            "tenant_id": str(current_user.tenant_id)
        }).mappings().first()

        if not campaign_result:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Campagne non trouvée"
            )

        entity_ids = campaign_result.entity_ids or []

        if not entity_ids:
            return {"entities": []}

        # Récupérer les détails des entités
        entities_query = text("""
            SELECT id, name
            FROM ecosystem_entity
            WHERE id = ANY(CAST(:entity_ids AS uuid[]))
            ORDER BY name ASC
        """)
        entities_result = db.execute(entities_query, {
            "entity_ids": [str(eid) for eid in entity_ids]
        }).mappings().all()

        entities = [{"id": str(e.id), "name": e.name} for e in entities_result]

        logger.info(f"✅ {len(entities)} entités trouvées pour campagne {campaign_id}")

        return {"entities": entities}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur récupération entités: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des entités: {str(e)}"
        )
