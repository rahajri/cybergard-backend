# backend/src/api/v1/dashboard.py
"""
API endpoint pour le Dashboard orienté Conformité & Audit.

Fournit toutes les statistiques nécessaires au tableau de bord :
- Score de conformité global
- Statistiques des campagnes
- Conformité par référentiel
- Actions prioritaires
- Entités à risque
- Activité récente
- Insights IA
"""

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from uuid import UUID
import logging
from datetime import datetime, timedelta

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def get_user_tenant_id(current_user: dict, db: Session) -> str:
    """Récupère le tenant_id de l'utilisateur connecté."""
    user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email

    # Chercher dans users
    user_query = text("""
        SELECT tenant_id FROM users WHERE email = :email AND is_active = true LIMIT 1
    """)
    result = db.execute(user_query, {"email": user_email}).fetchone()

    if result and result.tenant_id:
        return str(result.tenant_id)

    # Chercher dans entity_member
    member_query = text("""
        SELECT ee.tenant_id
        FROM entity_member em
        JOIN ecosystem_entity ee ON em.entity_id = ee.id
        WHERE em.email = :email AND em.is_active = true
        LIMIT 1
    """)
    result = db.execute(member_query, {"email": user_email}).fetchone()

    if result and result.tenant_id:
        return str(result.tenant_id)

    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail="Tenant non trouvé pour cet utilisateur"
    )


@router.get("/stats")
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Récupère toutes les statistiques du dashboard.
    """
    try:
        tenant_id = get_user_tenant_id(current_user, db)

        # DEBUG: Vérifier les données disponibles
        # audit_type est maintenant sur la table CAMPAIGN (pas audit)
        debug_query = text("""
            SELECT
                c.id as campaign_id,
                c.title,
                c.status as campaign_status,
                COALESCE(c.audit_type, 'external') as audit_type,
                COUNT(qa.id) as total_answers,
                COUNT(qa.compliance_status) as answers_with_status,
                COUNT(CASE WHEN qa.compliance_status = 'compliant' THEN 1 END) as compliant,
                COUNT(CASE WHEN qa.compliance_status = 'non_compliant_minor' THEN 1 END) as minor,
                COUNT(CASE WHEN qa.compliance_status = 'non_compliant_major' THEN 1 END) as major
            FROM campaign c
            LEFT JOIN question_answer qa ON qa.campaign_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.status IN ('ongoing', 'late', 'completed', 'frozen')
            GROUP BY c.id, c.title, c.status, c.audit_type
            ORDER BY c.title
        """)
        debug_results = db.execute(debug_query, {"tenant_id": tenant_id}).fetchall()
        for row in debug_results:
            logger.info(f"📊 DEBUG Dashboard - Campaign: {row.title} | Status: {row.campaign_status} | Type: {row.audit_type} | Answers: {row.total_answers} | With status: {row.answers_with_status} | Compliant: {row.compliant} | Minor: {row.minor} | Major: {row.major}")

        # ============================================================
        # 1. SCORE DE CONFORMITÉ GLOBAL (Interne + Externe)
        # ============================================================
        # compliance_status: compliant, non_compliant_minor, non_compliant_major, not_applicable, pending
        # Statuts campagne: draft, ongoing, late, frozen, completed, cancelled
        # audit_type est maintenant sur la table CAMPAIGN (pas audit)
        # Valeurs: 'internal' (interne) ou 'external' (externe), défaut='external'

        # Score Global (toutes campagnes)
        score_query = text("""
            SELECT
                COALESCE(AVG(
                    CASE
                        WHEN qa.compliance_status = 'compliant' THEN 100
                        WHEN qa.compliance_status = 'non_compliant_minor' THEN 50
                        WHEN qa.compliance_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END
                ), 0) as avg_score
            FROM question_answer qa
            JOIN campaign c ON qa.campaign_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.status IN ('ongoing', 'late', 'completed', 'frozen')
              AND qa.compliance_status IS NOT NULL
              AND qa.compliance_status NOT IN ('not_applicable', 'pending')
        """)
        score_result = db.execute(score_query, {"tenant_id": tenant_id}).fetchone()
        global_score = round(score_result.avg_score, 1) if score_result and score_result.avg_score else 0

        # Score Interne (campaign.audit_type = 'internal')
        internal_score_query = text("""
            SELECT
                COALESCE(AVG(
                    CASE
                        WHEN qa.compliance_status = 'compliant' THEN 100
                        WHEN qa.compliance_status = 'non_compliant_minor' THEN 50
                        WHEN qa.compliance_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END
                ), 0) as avg_score
            FROM question_answer qa
            JOIN campaign c ON qa.campaign_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.status IN ('ongoing', 'late', 'completed', 'frozen')
              AND c.audit_type = 'internal'
              AND qa.compliance_status IS NOT NULL
              AND qa.compliance_status NOT IN ('not_applicable', 'pending')
        """)
        internal_result = db.execute(internal_score_query, {"tenant_id": tenant_id}).fetchone()
        internal_score = round(internal_result.avg_score, 1) if internal_result and internal_result.avg_score else 0

        # Score Externe (campaign.audit_type = 'external' OU NULL - défaut)
        external_score_query = text("""
            SELECT
                COALESCE(AVG(
                    CASE
                        WHEN qa.compliance_status = 'compliant' THEN 100
                        WHEN qa.compliance_status = 'non_compliant_minor' THEN 50
                        WHEN qa.compliance_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END
                ), 0) as avg_score
            FROM question_answer qa
            JOIN campaign c ON qa.campaign_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.status IN ('ongoing', 'late', 'completed', 'frozen')
              AND (c.audit_type = 'external' OR c.audit_type IS NULL)
              AND qa.compliance_status IS NOT NULL
              AND qa.compliance_status NOT IN ('not_applicable', 'pending')
        """)
        external_result = db.execute(external_score_query, {"tenant_id": tenant_id}).fetchone()
        external_score = round(external_result.avg_score, 1) if external_result and external_result.avg_score else 0

        # Calcul du trend (comparaison avec les 3 derniers mois)
        trend_query = text("""
            SELECT
                COALESCE(AVG(
                    CASE
                        WHEN qa.compliance_status = 'compliant' THEN 100
                        WHEN qa.compliance_status = 'non_compliant_minor' THEN 50
                        WHEN qa.compliance_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END
                ), 0) as avg_score
            FROM question_answer qa
            JOIN campaign c ON qa.campaign_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.status IN ('ongoing', 'late', 'completed', 'frozen')
              AND c.created_at < NOW() - INTERVAL '3 months'
              AND qa.compliance_status IS NOT NULL
              AND qa.compliance_status NOT IN ('not_applicable', 'pending')
        """)
        trend_result = db.execute(trend_query, {"tenant_id": tenant_id}).fetchone()
        previous_score = round(trend_result.avg_score, 1) if trend_result and trend_result.avg_score else 0
        score_trend = round(global_score - previous_score, 1) if previous_score > 0 else 0

        # Dernière campagne terminée ou figée
        last_campaign_query = text("""
            SELECT title, due_date
            FROM campaign
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND status IN ('completed', 'frozen')
            ORDER BY frozen_date DESC NULLS LAST, due_date DESC NULLS LAST
            LIMIT 1
        """)
        last_campaign_result = db.execute(last_campaign_query, {"tenant_id": tenant_id}).fetchone()
        last_campaign = {
            "title": last_campaign_result.title if last_campaign_result else None,
            "date": last_campaign_result.due_date.isoformat() if last_campaign_result and last_campaign_result.due_date else None
        }

        # ============================================================
        # 2. STATISTIQUES DES CAMPAGNES
        # ============================================================
        # Statuts: draft, ongoing, late, frozen, completed, cancelled
        campaigns_query = text("""
            SELECT
                COUNT(*) FILTER (WHERE status IN ('ongoing', 'late')) as in_progress,
                COUNT(*) FILTER (WHERE status = 'draft') as draft,
                COUNT(*) FILTER (WHERE status IN ('completed', 'frozen')) as completed,
                COUNT(*) FILTER (WHERE status = 'late') as overdue
            FROM campaign
            WHERE tenant_id = CAST(:tenant_id AS uuid)
        """)
        campaigns_result = db.execute(campaigns_query, {"tenant_id": tenant_id}).fetchone()

        # Nombre d'entités en attente de réponses (via campaign_scope)
        pending_entities_query = text("""
            SELECT COUNT(DISTINCT entity_id) as count
            FROM (
                SELECT unnest(cs.entity_ids) as entity_id
                FROM campaign_scope cs
                JOIN campaign c ON cs.id = c.scope_id
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.status IN ('ongoing', 'late')
            ) sub
        """)
        try:
            pending_entities_result = db.execute(pending_entities_query, {"tenant_id": tenant_id}).fetchone()
            pending_entities_count = pending_entities_result.count if pending_entities_result else 0
        except:
            pending_entities_count = 0

        campaigns_stats = {
            "inProgress": campaigns_result.in_progress if campaigns_result else 0,
            "draft": campaigns_result.draft if campaigns_result else 0,
            "completed": campaigns_result.completed if campaigns_result else 0,
            "overdue": campaigns_result.overdue if campaigns_result else 0,
            "pendingEntities": pending_entities_count
        }

        # ============================================================
        # 3. CONFORMITÉ PAR RÉFÉRENTIEL
        # ============================================================
        referentials_query = text("""
            SELECT
                r.name as referential_name,
                r.code as referential_code,
                COALESCE(AVG(
                    CASE
                        WHEN qa.compliance_status = 'compliant' THEN 100
                        WHEN qa.compliance_status = 'non_compliant_minor' THEN 50
                        WHEN qa.compliance_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END
                ), 0) as score
            FROM referential r
            LEFT JOIN questionnaire q ON q.referential_id = r.id
            LEFT JOIN campaign c ON c.questionnaire_id = q.id AND c.tenant_id = CAST(:tenant_id AS uuid)
            LEFT JOIN question_answer qa ON qa.campaign_id = c.id
                AND qa.compliance_status IS NOT NULL
                AND qa.compliance_status NOT IN ('not_applicable', 'pending')
            WHERE r.is_active = true
            GROUP BY r.id, r.name, r.code
            HAVING COUNT(qa.id) > 0
            ORDER BY score ASC
            LIMIT 6
        """)
        try:
            referentials_results = db.execute(referentials_query, {"tenant_id": tenant_id}).fetchall()
            referentials = [
                {
                    "name": row.referential_name,
                    "code": row.referential_code,
                    "score": round(row.score, 1),
                    "isLow": row.score < 60
                }
                for row in referentials_results
            ]
        except Exception as e:
            logger.warning(f"Erreur récupération référentiels: {e}")
            referentials = []

        # ============================================================
        # 4. ACTIONS CRITIQUES
        # ============================================================
        # Actions en retard
        critical_actions_query = text("""
            SELECT
                a.id, a.title, a.due_date, a.priority, a.status,
                EXTRACT(DAY FROM NOW() - a.due_date) as days_overdue
            FROM action a
            JOIN action_plan ap ON a.action_plan_id = ap.id
            JOIN campaign c ON ap.campaign_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND a.due_date < NOW()
              AND a.status NOT IN ('completed', 'cancelled')
            ORDER BY a.due_date ASC
            LIMIT 5
        """)
        try:
            critical_results = db.execute(critical_actions_query, {"tenant_id": tenant_id}).fetchall()
            critical_actions = [
                {
                    "id": str(row.id),
                    "title": row.title,
                    "dueDate": row.due_date.isoformat() if row.due_date else None,
                    "daysOverdue": int(row.days_overdue) if row.days_overdue else 0,
                    "priority": row.priority,
                    "status": row.status
                }
                for row in critical_results
            ]
        except Exception as e:
            logger.warning(f"Erreur récupération actions critiques: {e}")
            critical_actions = []

        # Actions en attente d'approbation
        pending_approvals_query = text("""
            SELECT COUNT(*) as count
            FROM action a
            JOIN action_plan ap ON a.action_plan_id = ap.id
            JOIN campaign c ON ap.campaign_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND a.status = 'pending_validation'
        """)
        try:
            pending_approvals_result = db.execute(pending_approvals_query, {"tenant_id": tenant_id}).fetchone()
            pending_approvals_count = pending_approvals_result.count if pending_approvals_result else 0
        except:
            pending_approvals_count = 0

        # Actions à échéance proche (≤7 jours)
        upcoming_query = text("""
            SELECT
                a.id, a.title, a.due_date,
                EXTRACT(DAY FROM a.due_date - NOW()) as days_remaining
            FROM action a
            JOIN action_plan ap ON a.action_plan_id = ap.id
            JOIN campaign c ON ap.campaign_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND a.due_date BETWEEN NOW() AND NOW() + INTERVAL '7 days'
              AND a.status NOT IN ('completed', 'cancelled')
            ORDER BY a.due_date ASC
            LIMIT 5
        """)
        try:
            upcoming_results = db.execute(upcoming_query, {"tenant_id": tenant_id}).fetchall()
            upcoming_deadlines = [
                {
                    "id": str(row.id),
                    "title": row.title,
                    "dueDate": row.due_date.isoformat() if row.due_date else None,
                    "daysRemaining": int(row.days_remaining) if row.days_remaining else 0
                }
                for row in upcoming_results
            ]
        except Exception as e:
            logger.warning(f"Erreur récupération échéances: {e}")
            upcoming_deadlines = []

        # ============================================================
        # 5. ENTITÉS À RISQUE
        # ============================================================
        entities_at_risk_query = text("""
            SELECT
                ee.id,
                ee.name as entity_name,
                COALESCE(AVG(
                    CASE
                        WHEN qa.compliance_status = 'compliant' THEN 100
                        WHEN qa.compliance_status = 'non_compliant_minor' THEN 50
                        WHEN qa.compliance_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END
                ), 0) as score
            FROM ecosystem_entity ee
            LEFT JOIN question_answer qa ON qa.entity_id = ee.id
                AND qa.compliance_status IS NOT NULL
                AND qa.compliance_status NOT IN ('not_applicable', 'pending')
            LEFT JOIN campaign c ON qa.campaign_id = c.id
            WHERE ee.tenant_id = CAST(:tenant_id AS uuid)
              AND ee.deleted_at IS NULL
              AND (c.id IS NULL OR c.tenant_id = CAST(:tenant_id AS uuid))
            GROUP BY ee.id, ee.name
            HAVING COUNT(qa.id) > 0
               AND COALESCE(AVG(
                    CASE
                        WHEN qa.compliance_status = 'compliant' THEN 100
                        WHEN qa.compliance_status = 'non_compliant_minor' THEN 50
                        WHEN qa.compliance_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END
                ), 100) < 70
            ORDER BY score ASC
            LIMIT 5
        """)
        try:
            entities_results = db.execute(entities_at_risk_query, {"tenant_id": tenant_id}).fetchall()
            entities_at_risk = [
                {
                    "id": str(row.id),
                    "name": row.entity_name,
                    "score": round(row.score, 1),
                    "overdueActions": 0  # Simplifié
                }
                for row in entities_results
            ]
        except Exception as e:
            logger.warning(f"Erreur récupération entités à risque: {e}")
            entities_at_risk = []

        # ============================================================
        # 6. ACTIVITÉ RÉCENTE
        # ============================================================
        activity_query = text("""
            (
                SELECT
                    'campaign_created' as type,
                    NULL as entity_name,
                    c.title as campaign_title,
                    c.created_at as activity_date,
                    NULL as extra_info
                FROM campaign c
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.created_at > NOW() - INTERVAL '30 days'
            )
            UNION ALL
            (
                SELECT
                    'action_completed' as type,
                    NULL as entity_name,
                    c.title as campaign_title,
                    a.updated_at as activity_date,
                    a.title as extra_info
                FROM action a
                JOIN action_plan ap ON a.action_plan_id = ap.id
                JOIN campaign c ON ap.campaign_id = c.id
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND a.status = 'completed'
                  AND a.updated_at > NOW() - INTERVAL '30 days'
            )
            ORDER BY activity_date DESC
            LIMIT 8
        """)
        try:
            activity_results = db.execute(activity_query, {"tenant_id": tenant_id}).fetchall()
            recent_activity = []
            for row in activity_results:
                activity_item = {
                    "type": row.type,
                    "date": row.activity_date.isoformat() if row.activity_date else None,
                    "campaignTitle": row.campaign_title
                }

                if row.type == "questionnaire_submitted":
                    activity_item["message"] = f"{row.entity_name} a soumis son questionnaire"
                    activity_item["color"] = "green"
                elif row.type == "action_completed":
                    activity_item["message"] = f"Action terminée : {row.extra_info}"
                    activity_item["color"] = "blue"
                elif row.type == "campaign_created":
                    activity_item["message"] = f"Nouvelle campagne : {row.campaign_title}"
                    activity_item["color"] = "purple"
                else:
                    activity_item["message"] = row.extra_info or "Activité"
                    activity_item["color"] = "gray"

                recent_activity.append(activity_item)
        except Exception as e:
            logger.warning(f"Erreur récupération activité: {e}")
            recent_activity = []

        # ============================================================
        # 7. INSIGHTS IA (basé sur les données)
        # ============================================================
        insights = []

        # Insight 1: Référentiel le plus faible
        if referentials and len(referentials) > 0:
            lowest_ref = referentials[0]
            if lowest_ref["score"] < 60:
                insights.append({
                    "type": "warning",
                    "icon": "alert",
                    "message": f"Votre conformité {lowest_ref['code']} ({lowest_ref['score']}%) est inférieure au seuil recommandé de 60%.",
                    "action": "Prioriser les actions correctives sur ce référentiel"
                })

        # Insight 2: Actions en retard
        if len(critical_actions) > 0:
            insights.append({
                "type": "critical",
                "icon": "clock",
                "message": f"{len(critical_actions)} action(s) sont en retard et nécessitent une attention immédiate.",
                "action": "Voir le plan d'action"
            })

        # Insight 3: Entités à risque
        if len(entities_at_risk) > 0:
            insights.append({
                "type": "info",
                "icon": "building",
                "message": f"{len(entities_at_risk)} entité(s) présentent un score de conformité inférieur à 70%.",
                "action": "Accompagner ces entités"
            })

        # Insight 4: Tendance positive
        if score_trend > 5:
            insights.append({
                "type": "success",
                "icon": "trending-up",
                "message": f"Votre score de conformité a augmenté de {score_trend}% ce trimestre.",
                "action": "Maintenir les efforts"
            })

        # Insight par défaut si pas d'insights
        if len(insights) == 0:
            insights.append({
                "type": "info",
                "icon": "check",
                "message": "Votre conformité est stable. Continuez à suivre vos plans d'action.",
                "action": "Voir les détails"
            })

        # ============================================================
        # 8. STATISTIQUES GLOBALES RAPIDES
        # ============================================================
        quick_stats_query = text("""
            SELECT
                (SELECT COUNT(*) FROM ecosystem_entity WHERE tenant_id = CAST(:tenant_id AS uuid) AND deleted_at IS NULL) as total_entities,
                (SELECT COUNT(*) FROM entity_member em
                 JOIN ecosystem_entity ee ON em.entity_id = ee.id
                 WHERE ee.tenant_id = CAST(:tenant_id AS uuid) AND em.is_active = true) as total_members,
                (SELECT COUNT(*) FROM action a
                 JOIN action_plan ap ON a.action_plan_id = ap.id
                 JOIN campaign c ON ap.campaign_id = c.id
                 WHERE c.tenant_id = CAST(:tenant_id AS uuid)) as total_actions,
                (SELECT COUNT(*) FROM action a
                 JOIN action_plan ap ON a.action_plan_id = ap.id
                 JOIN campaign c ON ap.campaign_id = c.id
                 WHERE c.tenant_id = CAST(:tenant_id AS uuid) AND a.status = 'completed') as completed_actions
        """)
        try:
            quick_stats_result = db.execute(quick_stats_query, {"tenant_id": tenant_id}).fetchone()
            quick_stats = {
                "totalEntities": quick_stats_result.total_entities if quick_stats_result else 0,
                "totalMembers": quick_stats_result.total_members if quick_stats_result else 0,
                "totalActions": quick_stats_result.total_actions if quick_stats_result else 0,
                "completedActions": quick_stats_result.completed_actions if quick_stats_result else 0
            }
        except:
            quick_stats = {
                "totalEntities": 0,
                "totalMembers": 0,
                "totalActions": 0,
                "completedActions": 0
            }

        return {
            "globalScore": global_score,
            "internalScore": internal_score,
            "externalScore": external_score,
            "scoreTrend": score_trend,
            "lastCampaign": last_campaign,
            "campaigns": campaigns_stats,
            "referentials": referentials,
            "criticalActions": critical_actions,
            "pendingApprovalsCount": pending_approvals_count,
            "upcomingDeadlines": upcoming_deadlines,
            "entitiesAtRisk": entities_at_risk,
            "recentActivity": recent_activity,
            "aiInsights": insights,
            "quickStats": quick_stats
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des stats dashboard: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
