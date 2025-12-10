"""
API endpoints pour le module Actions (actions publiées)
"""
from fastapi import APIRouter, Depends, HTTPException, status as http_status, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, func, desc, text
from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel
import logging

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak, require_permission
from src.models.audit import User, Action
from src.models.action_plan import PublishedAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/actions", tags=["Actions"])


# ============================================================================
# SCHEMAS
# ============================================================================

class ControlPointInfo(BaseModel):
    """Information sur un point de contrôle"""
    id: UUID
    control_id: str
    title: str
    referential_name: Optional[str] = None
    referential_code: Optional[str] = None

    class Config:
        from_attributes = True


class SourceQuestionInfo(BaseModel):
    """Information sur une question source"""
    id: UUID
    question_text: str
    question_code: Optional[str] = None
    domain_name: Optional[str] = None

    class Config:
        from_attributes = True


class PublishedActionResponse(BaseModel):
    """Réponse pour une action publiée ou standalone"""
    id: UUID
    code_action: Optional[str] = None  # Code unique (ACT_001, ACT_002, etc.)
    action_plan_item_id: Optional[UUID] = None  # Null pour actions standalone
    action_plan_id: Optional[UUID] = None  # Null pour actions standalone
    campaign_id: Optional[UUID] = None  # Null pour actions standalone
    tenant_id: Optional[UUID] = None

    # Contenu
    title: str
    description: str
    objective: Optional[str] = None
    deliverables: Optional[str] = None

    # Classification
    severity: str
    priority: str
    status: str

    # Assignation
    suggested_role: str
    assigned_user_id: Optional[UUID] = None
    assigned_user_name: Optional[str] = None  # Nom de la personne assignée
    assignment_method: str

    # Entité
    entity_id: Optional[UUID] = None
    entity_name: Optional[str] = None

    # Dates
    due_date: Optional[datetime] = None
    recommended_due_days: int
    published_at: Optional[datetime] = None
    completion_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Sources (IDs bruts)
    source_question_ids: List[UUID] = []
    control_point_ids: List[UUID] = []

    # Sources enrichies (avec détails)
    control_points: List[ControlPointInfo] = []
    source_question: Optional[SourceQuestionInfo] = None

    # Suivi
    progress_notes: Optional[str] = None
    ai_justifications: Optional[dict] = None

    # CVE et informations de vulnérabilité (pour actions issues de scans)
    cve_ids: Optional[List[str]] = None  # Liste des CVE (ex: ["CVE-2017-13099"])
    cvss_score: Optional[float] = None  # Score CVSS (0.0-10.0)
    cve_source_url: Optional[str] = None  # Lien vers la source NVD

    class Config:
        from_attributes = True


class ActionsListResponse(BaseModel):
    """Réponse paginée pour la liste des actions"""
    items: List[PublishedActionResponse]
    total: int
    limit: int
    offset: int
    has_more: bool

    # Statistiques
    stats: dict


class ActionUpdateRequest(BaseModel):
    """Request pour mise à jour d'une action"""
    # Champs de base
    title: Optional[str] = None
    description: Optional[str] = None
    objective: Optional[str] = None
    deliverables: Optional[str] = None

    # Classification
    status: Optional[str] = None
    severity: Optional[str] = None
    priority: Optional[str] = None

    # Assignation
    suggested_role: Optional[str] = None
    assigned_user_id: Optional[UUID] = None
    entity_id: Optional[UUID] = None

    # Délais
    recommended_due_days: Optional[int] = None

    # Notes
    progress_notes: Optional[str] = None


class ActionUpdateResponse(BaseModel):
    """Réponse après mise à jour d'une action"""
    success: bool
    message: str
    action: PublishedActionResponse


# ============================================================================
# HELPERS
# ============================================================================

def fetch_control_points_details(db: Session, control_point_ids: List[UUID]) -> List[ControlPointInfo]:
    """
    Récupère les détails des points de contrôle.

    Note: La table control_point a les colonnes 'code' et 'name' (pas control_id/title).
    Le framework (référentiel) est obtenu via requirement_control_point → requirement → framework.
    """
    if not control_point_ids:
        return []

    query = text("""
        SELECT DISTINCT
            cp.id,
            cp.code,
            cp.name,
            f.name as framework_name,
            f.code as framework_code
        FROM control_point cp
        LEFT JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
        LEFT JOIN requirement r ON r.id = rcp.requirement_id
        LEFT JOIN framework f ON f.id = r.framework_id
        WHERE cp.id = ANY(CAST(:cp_ids AS uuid[]))
        ORDER BY cp.code
    """)

    result = db.execute(query, {"cp_ids": [str(cp_id) for cp_id in control_point_ids]})
    rows = result.fetchall()

    return [
        ControlPointInfo(
            id=row[0],
            control_id=row[1],  # cp.code
            title=row[2],       # cp.name
            referential_name=row[3],  # framework.name
            referential_code=row[4]   # framework.code
        )
        for row in rows
    ]


def fetch_assigned_user_name(db: Session, assigned_user_id: Optional[UUID], campaign_id: Optional[UUID]) -> Optional[str]:
    """
    Récupère le nom de l'utilisateur assigné.

    Stratégie de recherche:
    1. Chercher d'abord dans entity_member (audités externes - cas le plus courant)
    2. Si non trouvé, chercher dans users (utilisateurs internes)

    Note: Le champ audit_type est dans la table 'audit', pas 'campaign'.
    Pour les actions publiées, on cherche d'abord dans entity_member car les
    actions concernent généralement des tâches assignées aux audités.

    Args:
        db: Session de base de données
        assigned_user_id: UUID de l'utilisateur assigné
        campaign_id: UUID de la campagne (non utilisé actuellement, conservé pour compatibilité)

    Returns:
        Nom complet de l'utilisateur ou None
    """
    if not assigned_user_id:
        return None

    # 1. Chercher d'abord dans entity_member (audités externes)
    query = text("""
        SELECT CONCAT(first_name, ' ', last_name) as full_name
        FROM entity_member
        WHERE id = CAST(:user_id AS uuid)
        LIMIT 1
    """)
    result = db.execute(query, {"user_id": str(assigned_user_id)})
    row = result.fetchone()
    if row and row[0]:
        return row[0]

    # 2. Si non trouvé, chercher dans users (utilisateurs internes)
    query = text("""
        SELECT CONCAT(first_name, ' ', last_name) as full_name
        FROM users
        WHERE id = CAST(:user_id AS uuid)
        LIMIT 1
    """)
    result = db.execute(query, {"user_id": str(assigned_user_id)})
    row = result.fetchone()
    if row and row[0]:
        return row[0]

    return None


def fetch_source_question_details(db: Session, source_question_ids: List[UUID]) -> Optional[SourceQuestionInfo]:
    """
    Récupère les détails de la première question source.

    Note: On prend uniquement la première question source car elle représente
    la question d'audit principale qui a généré l'action.
    """
    if not source_question_ids:
        return None

    question_id = source_question_ids[0]

    query = text("""
        SELECT
            q.id,
            q.question_text,
            q.question_code,
            COALESCE(d.code_officiel, d.code) as domain_name
        FROM question q
        LEFT JOIN requirement r ON q.requirement_id = r.id
        LEFT JOIN domain d ON r.domain_id = d.id
        WHERE q.id = CAST(:q_id AS uuid)
    """)

    result = db.execute(query, {"q_id": str(question_id)})
    row = result.fetchone()

    if row:
        return SourceQuestionInfo(
            id=row[0],              # q.id
            question_text=row[1],   # q.question_text
            question_code=row[2],   # q.question_code
            domain_name=row[3]      # d.name
        )

    return None


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("", response_model=ActionsListResponse)
async def get_actions(
    status: Optional[str] = Query(None, description="Filtrer par statut (pending, in_progress, completed, blocked)"),
    priority: Optional[str] = Query(None, description="Filtrer par priorité (P1, P2, P3)"),
    severity: Optional[str] = Query(None, description="Filtrer par sévérité (critical, major, minor, info)"),
    entity_id: Optional[UUID] = Query(None, description="Filtrer par entité"),
    campaign_id: Optional[UUID] = Query(None, description="Filtrer par campagne"),
    search: Optional[str] = Query(None, description="Recherche dans titre et description"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("ACTIONS_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la liste de toutes les actions (publiées + standalone).

    Cette requête fait une UNION entre :
    - published_action : actions issues des campagnes d'audit
    - action : actions standalone créées manuellement

    Paramètres de filtrage:
    - status: pending, in_progress, completed, blocked
    - priority: P1, P2, P3
    - severity: critical, major, minor, info
    - entity_id: UUID de l'entité
    - campaign_id: UUID de la campagne
    - search: Recherche textuelle

    Returns:
        - items: Liste des actions
        - total: Nombre total d'actions
        - stats: Statistiques (par statut, priorité, sévérité)
    """
    try:
        # Construire les filtres dynamiques
        filters = []
        params = {"tenant_id": str(current_user.tenant_id)}

        if status:
            filters.append("status = :status")
            params["status"] = status

        if priority:
            filters.append("priority = :priority")
            params["priority"] = priority

        if severity:
            filters.append("severity = :severity")
            params["severity"] = severity

        if entity_id:
            filters.append("entity_id = CAST(:entity_id AS uuid)")
            params["entity_id"] = str(entity_id)

        if campaign_id:
            filters.append("campaign_id = CAST(:campaign_id AS uuid)")
            params["campaign_id"] = str(campaign_id)

        if search:
            filters.append("(title ILIKE :search OR description ILIKE :search)")
            params["search"] = f"%{search}%"

        # Clause WHERE commune
        where_clause = " AND ".join(filters) if filters else "1=1"

        # Requête UNION pour combiner les deux tables
        # published_action : actions issues des campagnes (avec action_plan_item_id, campaign_id, etc.)
        # action : actions standalone (audit_id nullable, pas de campaign_id)
        # Note: On utilise UNION (pas UNION ALL) pour éliminer automatiquement les doublons
        #       basés sur l'ID. On vérifie aussi que l'action standalone n'a pas d'audit_id
        #       pour s'assurer que c'est bien une action créée manuellement.
        union_query = text(f"""
            WITH all_actions AS (
                -- Actions publiées (issues des campagnes)
                SELECT
                    pa.id,
                    pa.code_action,
                    pa.action_plan_item_id,
                    pa.action_plan_id,
                    pa.campaign_id,
                    pa.tenant_id,
                    pa.title,
                    pa.description,
                    pa.objective,
                    pa.deliverables,
                    pa.severity,
                    pa.priority,
                    pa.status,
                    pa.suggested_role,
                    pa.assigned_user_id,
                    pa.assignment_method,
                    pa.entity_id,
                    pa.entity_name,
                    pa.due_date,
                    pa.recommended_due_days,
                    pa.published_at,
                    pa.completion_date,
                    pa.created_at,
                    pa.updated_at,
                    pa.source_question_ids,
                    pa.control_point_ids,
                    pa.progress_notes,
                    pa.ai_justifications,
                    pa.cve_ids,
                    pa.cvss_score,
                    pa.cve_source_url,
                    'published' AS source_type
                FROM published_action pa
                WHERE pa.tenant_id = CAST(:tenant_id AS uuid)
                  AND {where_clause}

                UNION ALL

                -- Actions standalone (créées manuellement depuis le menu Actions)
                -- On ne prend QUE les actions qui:
                -- 1. N'ont PAS d'audit_id (vraiment standalone, pas liées à un audit)
                -- 2. Ont un code_action qui commence par 'ACT_' (pas ACT_CAMP_)
                -- Note: external_assignee_id pour mode externe, assignee pour mode interne
                SELECT
                    a.id,
                    a.code_action,
                    NULL::uuid AS action_plan_item_id,
                    NULL::uuid AS action_plan_id,
                    NULL::uuid AS campaign_id,
                    a.tenant_id,
                    a.title,
                    a.description,
                    a.objective,
                    a.deliverables,
                    a.severity,
                    a.priority,
                    a.status,
                    a.suggested_role,
                    COALESCE(a.external_assignee_id, a.assignee) AS assigned_user_id,
                    CASE WHEN a.external_assignee_id IS NOT NULL OR a.assignee IS NOT NULL THEN 'manual' ELSE 'unassigned' END AS assignment_method,
                    a.entity_id,
                    a.entity_name,
                    a.due_date::timestamp AS due_date,
                    a.recommended_due_days,
                    NULL::timestamp AS published_at,
                    NULL::timestamp AS completion_date,
                    a.created_at,
                    a.updated_at,
                    a.source_question_ids,
                    a.control_point_ids,
                    NULL AS progress_notes,
                    NULL::jsonb AS ai_justifications,
                    NULL::text[] AS cve_ids,
                    NULL::float AS cvss_score,
                    NULL::text AS cve_source_url,
                    'standalone' AS source_type
                FROM action a
                WHERE a.tenant_id = CAST(:tenant_id AS uuid)
                  AND a.audit_id IS NULL
                  AND {where_clause.replace('campaign_id', 'NULL::uuid')}
            )
            SELECT * FROM all_actions
            ORDER BY priority ASC, due_date ASC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """)

        params["limit"] = limit
        params["offset"] = offset

        result = db.execute(union_query, params)
        rows = result.fetchall()

        # Requête pour le total (UNION des deux tables, sans doublons)
        count_query = text(f"""
            SELECT COUNT(*) FROM (
                SELECT id FROM published_action
                WHERE tenant_id = CAST(:tenant_id AS uuid) AND {where_clause}
                UNION ALL
                SELECT id FROM action
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND audit_id IS NULL
                  AND {where_clause.replace('campaign_id', 'NULL::uuid')}
            ) AS combined
        """)
        total_result = db.execute(count_query, params)
        total = total_result.scalar() or 0

        # Statistiques (sur le tenant entier, sans doublons)
        stats_query = text("""
            WITH all_stats AS (
                SELECT status, priority, severity FROM published_action WHERE tenant_id = CAST(:tenant_id AS uuid)
                UNION ALL
                SELECT status, priority, severity FROM action
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND audit_id IS NULL
            )
            SELECT
                'status' AS stat_type, status AS stat_value, COUNT(*) AS count
            FROM all_stats GROUP BY status
            UNION ALL
            SELECT
                'priority' AS stat_type, priority AS stat_value, COUNT(*) AS count
            FROM all_stats GROUP BY priority
            UNION ALL
            SELECT
                'severity' AS stat_type, severity AS stat_value, COUNT(*) AS count
            FROM all_stats GROUP BY severity
        """)
        stats_result = db.execute(stats_query, {"tenant_id": str(current_user.tenant_id)})
        stats_rows = stats_result.fetchall()

        status_stats = {}
        priority_stats = {}
        severity_stats = {}
        for row in stats_rows:
            if row[0] == 'status' and row[1]:
                status_stats[row[1]] = row[2]
            elif row[0] == 'priority' and row[1]:
                priority_stats[row[1]] = row[2]
            elif row[0] == 'severity' and row[1]:
                severity_stats[row[1]] = row[2]

        stats = {
            "total": total,
            "by_status": status_stats,
            "by_priority": priority_stats,
            "by_severity": severity_stats
        }

        # Conversion en réponse avec enrichissement des données
        items = []
        for row in rows:
            # Extraire les valeurs de la row (code_action ajouté en position 1)
            action_id = row[0]
            code_action = row[1]
            action_plan_item_id = row[2]
            action_plan_id = row[3]
            campaign_id_val = row[4]
            tenant_id_val = row[5]
            title = row[6]
            description = row[7]
            objective = row[8]
            deliverables = row[9]
            severity_val = row[10]
            priority_val = row[11]
            status_val = row[12]
            suggested_role = row[13]
            assigned_user_id = row[14]
            assignment_method = row[15]
            entity_id_val = row[16]
            entity_name = row[17]
            due_date = row[18]
            recommended_due_days = row[19]
            published_at = row[20]
            completion_date = row[21]
            created_at = row[22]
            updated_at = row[23]
            source_question_ids = row[24] or []
            control_point_ids_val = row[25] or []
            progress_notes = row[26]
            ai_justifications = row[27]
            cve_ids_val = row[28] if len(row) > 28 else None
            cvss_score_val = row[29] if len(row) > 29 else None
            cve_source_url_val = row[30] if len(row) > 30 else None

            # Récupérer les détails enrichis
            control_points = fetch_control_points_details(db, control_point_ids_val)
            source_question = fetch_source_question_details(db, source_question_ids)
            assigned_user_name = fetch_assigned_user_name(db, assigned_user_id, campaign_id_val)

            items.append(PublishedActionResponse(
                id=action_id,
                code_action=code_action,
                action_plan_item_id=action_plan_item_id,
                action_plan_id=action_plan_id,
                campaign_id=campaign_id_val,
                tenant_id=tenant_id_val,
                title=title,
                description=description or "",
                objective=objective,
                deliverables=deliverables,
                severity=severity_val or "minor",
                priority=priority_val or "P2",
                status=status_val or "pending",
                suggested_role=suggested_role or "Non défini",
                assigned_user_id=assigned_user_id,
                assigned_user_name=assigned_user_name,
                assignment_method=assignment_method or "unassigned",
                entity_id=entity_id_val,
                entity_name=entity_name,
                due_date=due_date,
                recommended_due_days=recommended_due_days or 30,
                published_at=published_at,
                completion_date=completion_date,
                created_at=created_at,
                updated_at=updated_at,
                source_question_ids=source_question_ids,
                control_point_ids=control_point_ids_val,
                control_points=control_points,
                source_question=source_question,
                progress_notes=progress_notes,
                ai_justifications=ai_justifications,
                cve_ids=cve_ids_val,
                cvss_score=cvss_score_val,
                cve_source_url=cve_source_url_val
            ))

        return ActionsListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            has_more=(offset + len(items)) < total,
            stats=stats
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des actions: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des actions: {str(e)}"
        )


# ============================================================================
# SCHEMAS POUR SCOPE ENTITIES (Mode Externe) - AVANT les routes avec {action_id}
# ============================================================================

class ScopeEntityMember(BaseModel):
    """Membre d'une entité du scope"""
    id: str
    first_name: str
    last_name: str
    email: str
    role: Optional[str] = None


class ScopeEntity(BaseModel):
    """Entité du scope avec ses membres"""
    id: str
    name: str
    stakeholder_type: str
    entity_category: Optional[str] = None  # Catégorie directe (ex: MAROC, Fournisseurs)
    parent_category: Optional[str] = None  # Catégorie parente (ex: Fournisseurs)
    members: List[ScopeEntityMember] = []


class ScopeEntitiesResponse(BaseModel):
    """Réponse pour les entités du scope"""
    entities: List[ScopeEntity]
    total: int


# ============================================================================
# SCHEMAS POUR LES RÔLES (Mode Interne) - AVANT les routes avec {action_id}
# ============================================================================

class RoleInfo(BaseModel):
    """Information sur un rôle"""
    id: UUID
    code: str
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class RolesListResponse(BaseModel):
    """Liste des rôles disponibles"""
    roles: List[RoleInfo]
    total: int
    tenant_name: Optional[str] = None  # Nom du tenant pour affichage "Interne"


class UserByRole(BaseModel):
    """Utilisateur associé à un rôle"""
    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: str

    class Config:
        from_attributes = True


class UsersByRoleResponse(BaseModel):
    """Liste des utilisateurs pour un rôle donné"""
    users: List[UserByRole]
    total: int
    role_code: str
    role_name: str


# ============================================================================
# ENDPOINT SCOPE ENTITIES (Pour mode Externe des actions standalone)
# IMPORTANT: Doit être AVANT /{action_id} pour éviter conflit de routes
# ============================================================================

@router.get("/scope-entities", response_model=ScopeEntitiesResponse)
async def get_scope_entities(
    current_user: User = Depends(require_permission("ACTIONS_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère toutes les entités externes du tenant avec leurs membres.

    Utilisé pour l'assignation d'actions en mode "Externe" dans le module Actions standalone.
    Retourne les entités avec leurs catégories parentes pour le filtrage hiérarchique.

    Returns:
        Liste des entités avec catégorie, catégorie parente et membres
    """
    try:
        # Récupérer toutes les entités externes du tenant avec catégorie parente
        entities_query = text("""
            SELECT
                e.id,
                e.name,
                e.stakeholder_type,
                COALESCE(c.name, e.entity_category) as category_name,
                pc.name as parent_category_name
            FROM ecosystem_entity e
            LEFT JOIN categories c ON e.category_id = c.id
            LEFT JOIN categories pc ON c.parent_category_id = pc.id
            WHERE e.tenant_id = CAST(:tenant_id AS uuid)
              AND e.is_active = true
              AND e.stakeholder_type = 'external'
            ORDER BY e.name
        """)

        entities_result = db.execute(entities_query, {"tenant_id": str(current_user.tenant_id)})
        entities_rows = entities_result.fetchall()

        entities_list = []
        for row in entities_rows:
            entity_id = str(row[0])

            # Récupérer les membres de cette entité
            members_query = text("""
                SELECT
                    em.id,
                    em.first_name,
                    em.last_name,
                    em.email,
                    em.job_title as role
                FROM entity_member em
                WHERE em.entity_id = CAST(:entity_id AS uuid)
                  AND em.is_active = true
                ORDER BY em.last_name, em.first_name
            """)
            members_result = db.execute(members_query, {"entity_id": entity_id})
            members_rows = members_result.fetchall()

            members = [
                ScopeEntityMember(
                    id=str(m[0]),
                    first_name=m[1] or "",
                    last_name=m[2] or "",
                    email=m[3] or "",
                    role=m[4]
                )
                for m in members_rows
            ]

            entities_list.append(ScopeEntity(
                id=entity_id,
                name=row[1],
                stakeholder_type=row[2] or "external",
                entity_category=row[3],  # Catégorie directe (ou nom depuis table categories)
                parent_category=row[4],  # Catégorie parente si existe
                members=members
            ))

        logger.info(f"✅ Récupération de {len(entities_list)} entités externes pour le tenant {current_user.tenant_id}")

        return ScopeEntitiesResponse(
            entities=entities_list,
            total=len(entities_list)
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des scope entities: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des entités: {str(e)}"
        )


# ============================================================================
# ENDPOINTS POUR LES RÔLES - AVANT /{action_id}
# ============================================================================

@router.get("/roles/list", response_model=RolesListResponse)
async def get_roles(
    current_user: User = Depends(require_permission("ACTIONS_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la liste des rôles disponibles pour le tenant.

    Ces rôles servent à assigner des actions aux utilisateurs.
    Note:
    - SUPER_ADMIN est exclu car c'est un rôle système
    - Seuls les rôles utilisés par au moins un utilisateur du tenant sont affichés
    - Retourne également le nom du tenant pour l'affichage "Interne"
    """
    try:
        # Récupérer le nom du tenant
        tenant_query = text("SELECT name FROM tenant WHERE id = CAST(:tenant_id AS uuid)")
        tenant_result = db.execute(tenant_query, {"tenant_id": str(current_user.tenant_id)})
        tenant_row = tenant_result.fetchone()
        tenant_name = tenant_row[0] if tenant_row else "Interne"

        # Récupérer les rôles
        query = text("""
            SELECT DISTINCT r.id, r.code, r.name, r.description
            FROM role r
            JOIN user_role ur ON ur.role_id = r.id
            JOIN users u ON u.id = ur.user_id
            WHERE u.tenant_id = CAST(:tenant_id AS uuid)
              AND r.code != 'SUPER_ADMIN'
              AND u.is_active = true
            ORDER BY r.name ASC
        """)

        result = db.execute(query, {"tenant_id": str(current_user.tenant_id)})
        rows = result.fetchall()

        roles = [
            RoleInfo(
                id=row[0],
                code=row[1],
                name=row[2],
                description=row[3]
            )
            for row in rows
        ]

        return RolesListResponse(
            roles=roles,
            total=len(roles),
            tenant_name=tenant_name
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des rôles: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des rôles: {str(e)}"
        )


@router.get("/roles/{role_code}/users", response_model=UsersByRoleResponse)
async def get_users_by_role(
    role_code: str,
    current_user: User = Depends(require_permission("ACTIONS_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les utilisateurs ayant un rôle spécifique dans le tenant.

    Cherche par code OU par nom de rôle pour plus de flexibilité.

    Args:
        role_code: Code ou nom du rôle (ex: "RSSI", "DSI", "Chef de projet")

    Returns:
        Liste des utilisateurs avec ce rôle
    """
    try:
        # Chercher par code OU par nom (case insensitive)
        query = text("""
            SELECT DISTINCT
                u.id,
                u.first_name,
                u.last_name,
                u.email,
                r.code as role_code,
                r.name as role_name
            FROM users u
            JOIN user_role ur ON ur.user_id = u.id
            JOIN role r ON r.id = ur.role_id
            WHERE u.tenant_id = CAST(:tenant_id AS uuid)
              AND (r.code = :role_code OR LOWER(r.name) = LOWER(:role_code))
              AND u.is_active = true
            ORDER BY u.last_name, u.first_name
        """)

        result = db.execute(query, {
            "tenant_id": str(current_user.tenant_id),
            "role_code": role_code
        })
        rows = result.fetchall()

        # Récupérer le nom du rôle depuis le premier résultat
        actual_role_code = rows[0][4] if rows else role_code
        actual_role_name = rows[0][5] if rows else role_code

        users = [
            UserByRole(
                id=row[0],
                email=row[3],
                first_name=row[1],
                last_name=row[2],
                full_name=f"{row[1] or ''} {row[2] or ''}".strip() or row[3]
            )
            for row in rows
        ]

        return UsersByRoleResponse(
            users=users,
            total=len(users),
            role_code=actual_role_code,
            role_name=actual_role_name
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des utilisateurs par rôle: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des utilisateurs: {str(e)}"
        )


# ============================================================================
# ENDPOINT GET ACTION BY ID (doit être APRÈS les routes statiques)
# ============================================================================

@router.get("/{action_id}", response_model=PublishedActionResponse)
async def get_action(
    action_id: UUID,
    current_user: User = Depends(require_permission("ACTIONS_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère une action par son ID (publiée ou standalone).

    Cherche d'abord dans published_action, puis dans action si non trouvée.
    """
    try:
        # Chercher d'abord dans published_action
        query = select(PublishedAction).where(
            and_(
                PublishedAction.id == action_id,
                PublishedAction.tenant_id == current_user.tenant_id
            )
        )
        result = db.execute(query)
        action = result.scalar_one_or_none()

        if action:
            # Action publiée trouvée
            control_points = fetch_control_points_details(db, action.control_point_ids or [])
            source_question = fetch_source_question_details(db, action.source_question_ids or [])
            assigned_user_name = fetch_assigned_user_name(db, action.assigned_user_id, action.campaign_id)

            return PublishedActionResponse(
                id=action.id,
                code_action=action.code_action,
                action_plan_item_id=action.action_plan_item_id,
                action_plan_id=action.action_plan_id,
                campaign_id=action.campaign_id,
                tenant_id=action.tenant_id,
                title=action.title,
                description=action.description,
                objective=action.objective,
                deliverables=action.deliverables,
                severity=action.severity,
                priority=action.priority,
                status=action.status,
                suggested_role=action.suggested_role,
                assigned_user_id=action.assigned_user_id,
                assigned_user_name=assigned_user_name,
                assignment_method=action.assignment_method,
                entity_id=action.entity_id,
                entity_name=action.entity_name,
                due_date=action.due_date,
                recommended_due_days=action.recommended_due_days,
                published_at=action.published_at,
                completion_date=action.completion_date,
                created_at=action.created_at,
                updated_at=action.updated_at,
                source_question_ids=action.source_question_ids or [],
                control_point_ids=action.control_point_ids or [],
                control_points=control_points,
                source_question=source_question,
                progress_notes=action.progress_notes,
                ai_justifications=action.ai_justifications,
                cve_ids=action.cve_ids,
                cvss_score=action.cvss_score,
                cve_source_url=action.cve_source_url
            )

        # Chercher dans la table action (standalone)
        standalone_query = select(Action).where(
            and_(
                Action.id == action_id,
                Action.tenant_id == current_user.tenant_id
            )
        )
        standalone_result = db.execute(standalone_query)
        standalone_action = standalone_result.scalar_one_or_none()

        if not standalone_action:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Action introuvable"
            )

        # Action standalone trouvée
        control_points = fetch_control_points_details(db, standalone_action.control_point_ids or [])
        source_question = fetch_source_question_details(db, standalone_action.source_question_ids or [])
        # Pour standalone: utiliser external_assignee_id (mode externe) ou assignee (mode interne)
        effective_assignee_id = standalone_action.external_assignee_id or standalone_action.assignee
        assigned_user_name = fetch_assigned_user_name(db, effective_assignee_id, None)

        return PublishedActionResponse(
            id=standalone_action.id,
            code_action=standalone_action.code_action,
            action_plan_item_id=None,
            action_plan_id=None,
            campaign_id=None,
            tenant_id=standalone_action.tenant_id,
            title=standalone_action.title,
            description=standalone_action.description or "",
            objective=standalone_action.objective,
            deliverables=standalone_action.deliverables,
            severity=standalone_action.severity or "minor",
            priority=standalone_action.priority or "P2",
            status=standalone_action.status or "pending",
            suggested_role=standalone_action.suggested_role or "Non défini",
            assigned_user_id=effective_assignee_id,
            assigned_user_name=assigned_user_name,
            assignment_method="manual" if effective_assignee_id else "unassigned",
            entity_id=standalone_action.entity_id,
            entity_name=standalone_action.entity_name,
            due_date=datetime.combine(standalone_action.due_date, datetime.min.time()) if standalone_action.due_date else None,
            recommended_due_days=standalone_action.recommended_due_days or 30,
            published_at=None,
            completion_date=None,
            created_at=standalone_action.created_at,
            updated_at=standalone_action.updated_at,
            source_question_ids=standalone_action.source_question_ids or [],
            control_point_ids=standalone_action.control_point_ids or [],
            control_points=control_points,
            source_question=source_question,
            progress_notes=None,
            ai_justifications=None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération de l'action: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération de l'action: {str(e)}"
        )


@router.patch("/{action_id}", response_model=ActionUpdateResponse)
@router.put("/{action_id}", response_model=ActionUpdateResponse)
async def update_action(
    action_id: UUID,
    update_data: ActionUpdateRequest,
    current_user: User = Depends(require_permission("ACTIONS_WRITE")),
    db: Session = Depends(get_db)
):
    """
    Met à jour une action (publiée ou standalone).

    Cherche d'abord dans published_action, puis dans action si non trouvée.

    Champs modifiables:
    - status: Changer le statut (pending, in_progress, completed, blocked)
    - progress_notes: Ajouter des notes de progression
    - assigned_user_id: Réassigner l'action
    """
    try:
        now = datetime.now(timezone.utc)
        changes = []
        is_standalone = False

        # Chercher d'abord dans published_action
        query = select(PublishedAction).where(
            and_(
                PublishedAction.id == action_id,
                PublishedAction.tenant_id == current_user.tenant_id
            )
        )
        result = db.execute(query)
        action = result.scalar_one_or_none()

        if not action:
            # Chercher dans la table action (standalone)
            standalone_query = select(Action).where(
                and_(
                    Action.id == action_id,
                    Action.tenant_id == current_user.tenant_id
                )
            )
            standalone_result = db.execute(standalone_query)
            action = standalone_result.scalar_one_or_none()
            is_standalone = True

        if not action:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Action introuvable"
            )

        # Mise à jour des champs de base
        if update_data.title is not None and update_data.title != action.title:
            action.title = update_data.title
            changes.append("titre")

        if update_data.description is not None and update_data.description != action.description:
            action.description = update_data.description
            changes.append("description")

        if update_data.objective is not None and update_data.objective != action.objective:
            action.objective = update_data.objective
            changes.append("objectif")

        if update_data.deliverables is not None and update_data.deliverables != action.deliverables:
            action.deliverables = update_data.deliverables
            changes.append("livrables")

        # Mise à jour du statut
        if update_data.status is not None and update_data.status != action.status:
            valid_statuses = ["pending", "in_progress", "completed", "blocked"]
            if update_data.status not in valid_statuses:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"Statut invalide. Valeurs acceptées: {valid_statuses}"
                )
            action.status = update_data.status
            changes.append(f"statut → {update_data.status}")

            # Si complété, enregistrer la date (seulement pour published_action)
            if update_data.status == "completed" and not is_standalone:
                action.completion_date = now

        # Mise à jour de la sévérité
        if update_data.severity is not None and update_data.severity != action.severity:
            valid_severities = ["critical", "major", "minor", "info"]
            if update_data.severity not in valid_severities:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"Sévérité invalide. Valeurs acceptées: {valid_severities}"
                )
            action.severity = update_data.severity
            changes.append(f"sévérité → {update_data.severity}")

        # Mise à jour de la priorité
        if update_data.priority is not None and update_data.priority != action.priority:
            valid_priorities = ["P1", "P2", "P3"]
            if update_data.priority not in valid_priorities:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=f"Priorité invalide. Valeurs acceptées: {valid_priorities}"
                )
            action.priority = update_data.priority
            changes.append(f"priorité → {update_data.priority}")

        # Mise à jour du rôle suggéré
        if update_data.suggested_role is not None and update_data.suggested_role != action.suggested_role:
            action.suggested_role = update_data.suggested_role
            changes.append("rôle suggéré")

        # Mise à jour du délai recommandé
        if update_data.recommended_due_days is not None and update_data.recommended_due_days != action.recommended_due_days:
            action.recommended_due_days = update_data.recommended_due_days
            changes.append(f"délai → {update_data.recommended_due_days} jours")

        # Mise à jour des notes de progression (seulement pour published_action)
        if update_data.progress_notes is not None and not is_standalone:
            action.progress_notes = update_data.progress_notes
            changes.append("notes de progression")

        # Mise à jour de l'assignation
        if update_data.assigned_user_id is not None:
            if is_standalone:
                # Pour les actions standalone, déterminer le mode (Interne vs Externe)
                # Mode Externe : entity_id présent → stocker dans external_assignee_id
                # Mode Interne : entity_id absent ou "Interne" → stocker dans assignee
                is_external_mode = action.entity_id is not None

                if is_external_mode:
                    # Mode externe : entity_member → external_assignee_id
                    action.external_assignee_id = update_data.assigned_user_id if update_data.assigned_user_id else None
                    action.assignee = None  # S'assurer que assignee est vide
                else:
                    # Mode interne : users → assignee
                    action.assignee = update_data.assigned_user_id if update_data.assigned_user_id else None
                    action.external_assignee_id = None  # S'assurer que external_assignee_id est vide
            else:
                action.assigned_user_id = update_data.assigned_user_id if update_data.assigned_user_id else None
                action.assignment_method = "manual" if update_data.assigned_user_id else "unassigned"
            changes.append("assignation")

        # Mise à jour de l'entité (seulement pour actions qui supportent entity_id)
        if update_data.entity_id is not None:
            action.entity_id = update_data.entity_id
            changes.append("entité")

        action.updated_at = now
        db.commit()

        logger.info(f"✅ Action {action_id} mise à jour: {', '.join(changes)}")

        # Récupérer le nom de l'utilisateur assigné
        if is_standalone:
            # Pour standalone: utiliser external_assignee_id (mode externe) ou assignee (mode interne)
            effective_assignee_id = action.external_assignee_id or action.assignee
            assigned_user_name = fetch_assigned_user_name(db, effective_assignee_id, None)
            return ActionUpdateResponse(
                success=True,
                message=f"Action mise à jour: {', '.join(changes)}" if changes else "Aucune modification",
                action=PublishedActionResponse(
                    id=action.id,
                    code_action=action.code_action,
                    action_plan_item_id=None,
                    action_plan_id=None,
                    campaign_id=None,
                    tenant_id=action.tenant_id,
                    title=action.title,
                    description=action.description or "",
                    objective=action.objective,
                    deliverables=action.deliverables,
                    severity=action.severity or "minor",
                    priority=action.priority or "P2",
                    status=action.status or "pending",
                    suggested_role=action.suggested_role or "Non défini",
                    assigned_user_id=effective_assignee_id,
                    assigned_user_name=assigned_user_name,
                    assignment_method="manual" if effective_assignee_id else "unassigned",
                    entity_id=action.entity_id,
                    entity_name=action.entity_name,
                    due_date=datetime.combine(action.due_date, datetime.min.time()) if action.due_date else None,
                    recommended_due_days=action.recommended_due_days or 30,
                    published_at=None,
                    completion_date=None,
                    created_at=action.created_at,
                    updated_at=action.updated_at,
                    source_question_ids=action.source_question_ids or [],
                    control_point_ids=action.control_point_ids or [],
                    progress_notes=None,
                    ai_justifications=None
                )
            )

        assigned_user_name = fetch_assigned_user_name(db, action.assigned_user_id, action.campaign_id)

        return ActionUpdateResponse(
            success=True,
            message=f"Action mise à jour: {', '.join(changes)}" if changes else "Aucune modification",
            action=PublishedActionResponse(
                id=action.id,
                code_action=action.code_action,
                action_plan_item_id=action.action_plan_item_id,
                action_plan_id=action.action_plan_id,
                campaign_id=action.campaign_id,
                tenant_id=action.tenant_id,
                title=action.title,
                description=action.description,
                objective=action.objective,
                deliverables=action.deliverables,
                severity=action.severity,
                priority=action.priority,
                status=action.status,
                suggested_role=action.suggested_role,
                assigned_user_id=action.assigned_user_id,
                assigned_user_name=assigned_user_name,
                assignment_method=action.assignment_method,
                entity_id=action.entity_id,
                entity_name=action.entity_name,
                due_date=action.due_date,
                recommended_due_days=action.recommended_due_days,
                published_at=action.published_at,
                completion_date=action.completion_date,
                created_at=action.created_at,
                updated_at=action.updated_at,
                source_question_ids=action.source_question_ids or [],
                control_point_ids=action.control_point_ids or [],
                progress_notes=action.progress_notes,
                ai_justifications=action.ai_justifications
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la mise à jour de l'action: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour de l'action: {str(e)}"
        )


# ============================================================================
# SCHEMAS POUR CRÉATION D'ACTION STANDALONE
# ============================================================================

class CreateStandaloneActionRequest(BaseModel):
    """Request pour créer une action standalone (hors campagne)"""
    title: str
    description: str
    objective: Optional[str] = None
    deliverables: Optional[str] = None
    severity: str = "minor"  # critical, major, minor, info
    priority: str = "P2"  # P1, P2, P3
    status: str = "pending"  # pending, in_progress, completed, blocked
    recommended_due_days: int = 30
    suggested_role: str = ""  # Rôle suggéré (texte libre ou code de rôle)
    entity_id: Optional[UUID] = None  # Entité concernée (null pour actions internes)
    entity_name: Optional[str] = None  # Nom de l'entité (ex: "Interne" pour rôles existants)
    assigned_user_id: Optional[UUID] = None  # Utilisateur assigné
    source_question_ids: List[UUID] = []  # Questions sources (optionnel)
    control_point_ids: List[UUID] = []  # Points de contrôle (optionnel)


class CreateStandaloneActionResponse(BaseModel):
    """Response après création d'une action standalone"""
    success: bool
    message: str
    action: PublishedActionResponse


# ============================================================================
# ENDPOINT CRÉATION ACTION STANDALONE
# ============================================================================

@router.post("", response_model=CreateStandaloneActionResponse)
async def create_standalone_action(
    action_data: CreateStandaloneActionRequest,
    current_user: User = Depends(require_permission("ACTIONS_WRITE")),
    db: Session = Depends(get_db)
):
    """
    Crée une nouvelle action standalone (hors campagne).

    Cette action n'est pas liée à une campagne d'audit spécifique.
    Elle permet de créer des actions correctrices manuellement.

    Args:
        action_data: Données de l'action à créer

    Returns:
        L'action créée avec ses détails
    """
    try:
        import uuid as uuid_module
        from datetime import timedelta

        now = datetime.now(timezone.utc)

        # Valider les valeurs
        valid_severities = ["critical", "major", "minor", "info"]
        if action_data.severity not in valid_severities:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Sévérité invalide. Valeurs acceptées: {valid_severities}"
            )

        valid_priorities = ["P1", "P2", "P3"]
        if action_data.priority not in valid_priorities:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Priorité invalide. Valeurs acceptées: {valid_priorities}"
            )

        valid_statuses = ["pending", "in_progress", "completed", "blocked"]
        if action_data.status not in valid_statuses:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Statut invalide. Valeurs acceptées: {valid_statuses}"
            )

        # Récupérer le nom de l'entité
        # Priorité : 1) entity_name fourni dans la requête (ex: "Interne")
        #            2) Récupérer depuis ecosystem_entity si entity_id fourni
        entity_name = action_data.entity_name
        if not entity_name and action_data.entity_id:
            entity_query = text("""
                SELECT name FROM ecosystem_entity
                WHERE id = CAST(:entity_id AS uuid)
                LIMIT 1
            """)
            entity_result = db.execute(entity_query, {"entity_id": str(action_data.entity_id)})
            entity_row = entity_result.fetchone()
            if entity_row:
                entity_name = entity_row[0]

        # Si aucun entity_name et aucun entity_id, utiliser "Interne" par défaut
        if not entity_name:
            entity_name = "Interne"

        # Calculer la date d'échéance
        due_date = (now + timedelta(days=action_data.recommended_due_days)).date()

        # Déterminer le mode d'assignation (Interne vs Externe)
        # Mode Interne : entity_name = "Interne" → assignee peut être un user (FK vers users)
        # Mode Externe : entity_id fourni → assignee vient de entity_member (stocké dans external_assignee_id)
        is_external_mode = action_data.entity_id is not None

        # Gérer l'assignation selon le mode
        assignee_value = None  # Pour users (mode interne)
        external_assignee_value = None  # Pour entity_member (mode externe)

        if is_external_mode and action_data.assigned_user_id:
            # Mode Externe : stocker dans external_assignee_id (pas de FK, c'est un entity_member)
            external_assignee_value = action_data.assigned_user_id
        elif not is_external_mode and action_data.assigned_user_id:
            # Mode Interne : stocker dans assignee (FK vers users)
            assignee_value = action_data.assigned_user_id

        # Générer le code d'action unique
        max_code_query = text("""
            SELECT COALESCE(MAX(code_num), 0) as max_code FROM (
                SELECT CAST(SUBSTRING(code_action FROM 5) AS INTEGER) as code_num
                FROM action_plan_item
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND code_action IS NOT NULL
                  AND code_action ~ '^ACT_[0-9]+$'
                UNION ALL
                SELECT CAST(SUBSTRING(code_action FROM 5) AS INTEGER) as code_num
                FROM published_action
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND code_action IS NOT NULL
                  AND code_action ~ '^ACT_[0-9]+$'
                UNION ALL
                SELECT CAST(SUBSTRING(code_action FROM 5) AS INTEGER) as code_num
                FROM action
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND code_action IS NOT NULL
                  AND code_action ~ '^ACT_[0-9]+$'
            ) all_codes
        """)
        max_result = db.execute(max_code_query, {"tenant_id": str(current_user.tenant_id)})
        max_row = max_result.first()
        max_code = max_row[0] if max_row and max_row[0] else 0
        code_action = f"ACT_{max_code + 1:03d}"

        # Créer l'action dans la table 'action' (pas 'published_action')
        # La table 'action' est pour toutes les actions (standalone ou issues de campagnes)
        new_action = Action(
            id=uuid_module.uuid4(),
            code_action=code_action,  # ✅ Code unique de l'action
            tenant_id=current_user.tenant_id,
            # Pas d'audit_id pour les actions standalone
            audit_id=None,
            control_point_id=action_data.control_point_ids[0] if action_data.control_point_ids else None,
            title=action_data.title,
            description=action_data.description,
            objective=action_data.objective,
            deliverables=action_data.deliverables,
            severity=action_data.severity,
            priority=action_data.priority,
            status=action_data.status,
            suggested_role=action_data.suggested_role or "Non défini",
            assignee=assignee_value,  # UUID en mode interne (users), None en mode externe
            external_assignee_id=external_assignee_value,  # UUID en mode externe (entity_member), None en mode interne
            entity_id=action_data.entity_id,
            entity_name=entity_name,
            due_date=due_date,
            recommended_due_days=action_data.recommended_due_days,
            source_question_ids=action_data.source_question_ids or [],
            control_point_ids=action_data.control_point_ids or [],
            created_by=str(current_user.id),
            created_at=now,
            updated_at=now
        )

        db.add(new_action)
        db.commit()
        db.refresh(new_action)

        logger.info(f"✅ Action standalone créée: {new_action.id} - {new_action.title}")

        # Récupérer les détails enrichis
        control_points = fetch_control_points_details(db, action_data.control_point_ids or [])
        source_question = fetch_source_question_details(db, new_action.source_question_ids or [])

        # Pour l'assignation en mode externe, l'ID vient de entity_member
        # En mode interne, l'ID vient de users (stocké dans assignee)
        if is_external_mode and action_data.assigned_user_id:
            # Mode externe : chercher le nom dans entity_member
            assigned_user_name = fetch_assigned_user_name(db, action_data.assigned_user_id, None)
            response_assigned_user_id = action_data.assigned_user_id
            assignment_method = "manual"
        else:
            # Mode interne : utiliser assignee (users)
            assigned_user_name = fetch_assigned_user_name(db, new_action.assignee, None)
            response_assigned_user_id = new_action.assignee
            assignment_method = "manual" if new_action.assignee else "unassigned"

        return CreateStandaloneActionResponse(
            success=True,
            message="Action créée avec succès",
            action=PublishedActionResponse(
                id=new_action.id,
                code_action=new_action.code_action,
                action_plan_item_id=None,  # Pas de plan d'action pour standalone
                action_plan_id=None,
                campaign_id=None,  # Pas de campagne pour standalone
                tenant_id=new_action.tenant_id,
                title=new_action.title,
                description=new_action.description,
                objective=new_action.objective,
                deliverables=new_action.deliverables,
                severity=new_action.severity,
                priority=new_action.priority,
                status=new_action.status,
                suggested_role=new_action.suggested_role,
                assigned_user_id=response_assigned_user_id,
                assigned_user_name=assigned_user_name,
                assignment_method=assignment_method,
                entity_id=new_action.entity_id,
                entity_name=new_action.entity_name,
                due_date=datetime.combine(new_action.due_date, datetime.min.time()) if new_action.due_date else None,
                recommended_due_days=new_action.recommended_due_days,
                published_at=None,  # Pas de publication pour action standalone
                completion_date=None,
                created_at=new_action.created_at,
                updated_at=new_action.updated_at,
                source_question_ids=new_action.source_question_ids or [],
                control_point_ids=action_data.control_point_ids or [],
                control_points=control_points,
                source_question=source_question,
                progress_notes=None,
                ai_justifications=None
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la création de l'action: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création de l'action: {str(e)}"
        )


# ============================================================================
# ENDPOINT SUPPRESSION D'ACTION
# ============================================================================

class DeleteActionResponse(BaseModel):
    """Response après suppression d'une action"""
    success: bool
    message: str
    deleted_id: UUID
    code_action: Optional[str] = None


@router.delete("/{action_id}", response_model=DeleteActionResponse)
async def delete_action(
    action_id: UUID,
    current_user: User = Depends(require_permission("ACTIONS_WRITE")),
    db: Session = Depends(get_db)
):
    """
    Supprime une action (publiée ou standalone).

    Cherche d'abord dans published_action, puis dans action si non trouvée.
    La suppression est définitive (hard delete).

    Args:
        action_id: UUID de l'action à supprimer

    Returns:
        Confirmation de suppression avec l'ID et le code de l'action
    """
    try:
        code_action = None

        # Chercher d'abord dans published_action
        query = select(PublishedAction).where(
            and_(
                PublishedAction.id == action_id,
                PublishedAction.tenant_id == current_user.tenant_id
            )
        )
        result = db.execute(query)
        action = result.scalar_one_or_none()

        if action:
            # Action publiée trouvée - la supprimer
            code_action = action.code_action
            db.delete(action)
            db.commit()
            logger.info(f"✅ Action publiée supprimée: {action_id} ({code_action})")
            return DeleteActionResponse(
                success=True,
                message="Action publiée supprimée avec succès",
                deleted_id=action_id,
                code_action=code_action
            )

        # Chercher dans la table action (standalone)
        standalone_query = select(Action).where(
            and_(
                Action.id == action_id,
                Action.tenant_id == current_user.tenant_id
            )
        )
        standalone_result = db.execute(standalone_query)
        standalone_action = standalone_result.scalar_one_or_none()

        if not standalone_action:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Action introuvable"
            )

        # Action standalone trouvée - la supprimer
        code_action = standalone_action.code_action
        db.delete(standalone_action)
        db.commit()
        logger.info(f"✅ Action standalone supprimée: {action_id} ({code_action})")

        return DeleteActionResponse(
            success=True,
            message="Action supprimée avec succès",
            deleted_id=action_id,
            code_action=code_action
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la suppression de l'action: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression de l'action: {str(e)}"
        )
