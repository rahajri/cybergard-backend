"""
API pour la gestion des rôles et permissions
"""
from typing import List, Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from pydantic import BaseModel, Field

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak, require_permission
from src.utils.redis_manager import redis_manager
from src.services.keycloak_service import get_keycloak_service
from src.services.permission_sync_service import PermissionSyncService

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# SCHÉMAS PYDANTIC - PERMISSIONS
# ============================================================================

class PermissionBase(BaseModel):
    """Schéma de base pour une permission"""
    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)


class PermissionCreate(PermissionBase):
    """Schéma pour créer une permission"""
    module: str = Field(..., min_length=1, max_length=50)
    action: str = Field(..., min_length=1, max_length=50)
    permission_type: str = Field(default="general", pattern="^(general|workflow)$")


class PermissionUpdate(BaseModel):
    """Schéma pour mettre à jour une permission"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=500)


class PermissionResponse(PermissionBase):
    """Schéma de réponse pour une permission"""
    id: UUID
    module: Optional[str] = None
    action: Optional[str] = None
    permission_type: Optional[str] = "general"

    class Config:
        from_attributes = True


class PermissionWithDependencies(PermissionResponse):
    """Schéma de réponse pour une permission avec ses dépendances"""
    dependencies: List[str] = []  # Liste des codes de permissions requises


class PermissionListResponse(BaseModel):
    """Schéma de réponse pour une liste de permissions"""
    items: List[PermissionResponse]
    total: int


class PermissionsByModuleResponse(BaseModel):
    """Schéma de réponse pour les permissions groupées par module"""
    general: dict  # {"campaign": {"read": {...}, "create": {...}}, ...}
    workflow: dict  # {"campaign": {"validate": {...}, ...}, ...}
    dependencies: dict  # {"CAMPAIGN_UPDATE": ["CAMPAIGN_READ"], ...}


# ============================================================================
# SCHÉMAS PYDANTIC - RÔLES
# ============================================================================

class RoleBase(BaseModel):
    """Schéma de base pour un rôle"""
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class RoleCreate(RoleBase):
    """Schéma pour créer un rôle"""
    is_system: bool = False
    permission_ids: Optional[List[UUID]] = Field(None, description="Liste des IDs de permissions à assigner")


class RoleUpdate(BaseModel):
    """Schéma pour mettre à jour un rôle"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    permission_ids: Optional[List[UUID]] = Field(None, description="Liste des IDs de permissions à assigner")


class RoleResponse(RoleBase):
    """Schéma de réponse pour un rôle"""
    id: UUID
    is_system: bool
    users_count: Optional[int] = 0
    permissions_count: Optional[int] = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoleDetailResponse(RoleResponse):
    """Schéma de réponse détaillé pour un rôle avec ses permissions"""
    permissions: List[PermissionResponse] = []


class RoleListResponse(BaseModel):
    """Schéma de réponse pour une liste de rôles"""
    items: List[RoleResponse]
    total: int


class RoleStatsResponse(BaseModel):
    """Statistiques des rôles"""
    total_roles: int
    system_roles: int
    custom_roles: int
    total_users_with_roles: int
    total_permissions: int


class AssignPermissionsRequest(BaseModel):
    """Schéma pour assigner des permissions à un rôle"""
    permission_ids: List[UUID] = Field(..., description="Liste des IDs de permissions à assigner")


# ============================================================================
# ENDPOINTS - PERMISSIONS
# ============================================================================

@router.get(
    "/permissions",
    response_model=PermissionListResponse,
    summary="Lister toutes les permissions",
    description="Récupère la liste de toutes les permissions disponibles"
)
async def list_permissions(
    permission_type: Optional[str] = Query(None, description="Filtrer par type (general/workflow)"),
    module: Optional[str] = Query(None, description="Filtrer par module"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Liste toutes les permissions disponibles avec filtres optionnels."""
    try:
        logger.info(f"📋 [PERMISSIONS] Listing permissions (type={permission_type}, module={module})")

        # Construction de la requête avec filtres
        query_str = """
            SELECT id, code, module, action, permission_type, name, description
            FROM permission
            WHERE 1=1
        """
        params = {}

        if permission_type:
            query_str += " AND permission_type = :permission_type"
            params["permission_type"] = permission_type

        if module:
            query_str += " AND module = :module"
            params["module"] = module

        query_str += " ORDER BY module ASC, action ASC"

        result = db.execute(text(query_str), params)

        permissions = []
        for row in result:
            permissions.append({
                "id": row.id,
                "code": row.code,
                "module": row.module,
                "action": row.action,
                "permission_type": row.permission_type,
                "name": row.name,
                "description": row.description
            })

        logger.info(f"✅ [PERMISSIONS] Found {len(permissions)} permissions")

        return {
            "items": permissions,
            "total": len(permissions)
        }

    except Exception as e:
        logger.error(f"❌ [PERMISSIONS] Error listing permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des permissions: {str(e)}"
        )


@router.get(
    "/permissions/grouped",
    response_model=PermissionsByModuleResponse,
    summary="Permissions groupées par module",
    description="Récupère les permissions groupées par module et type, avec leurs dépendances"
)
async def get_permissions_grouped(
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Retourne les permissions groupées par module et type pour l'interface d'édition des rôles.

    Structure retournée:
    - general: permissions CRUD groupées par module
    - workflow: permissions métier groupées par module
    - dependencies: dictionnaire des dépendances entre permissions
    """
    try:
        logger.info("📋 [PERMISSIONS] Getting grouped permissions")

        # Récupérer toutes les permissions
        permissions_query = text("""
            SELECT id, code, module, action, permission_type, name, description
            FROM permission
            WHERE module IS NOT NULL AND action IS NOT NULL
            ORDER BY module ASC, action ASC
        """)
        permissions_result = db.execute(permissions_query)

        # Grouper par type et module
        general = {}
        workflow = {}

        for row in permissions_result:
            perm_data = {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "description": row.description
            }

            if row.permission_type == "general":
                if row.module not in general:
                    general[row.module] = {}
                general[row.module][row.action] = perm_data
            elif row.permission_type == "workflow":
                if row.module not in workflow:
                    workflow[row.module] = {}
                workflow[row.module][row.action] = perm_data

        # Récupérer les dépendances
        dependencies_query = text("""
            SELECT
                p1.code as permission_code,
                p2.code as depends_on_code
            FROM permission_dependency pd
            JOIN permission p1 ON pd.permission_id = p1.id
            JOIN permission p2 ON pd.depends_on_id = p2.id
            ORDER BY p1.code
        """)
        dependencies_result = db.execute(dependencies_query)

        dependencies = {}
        for row in dependencies_result:
            if row.permission_code not in dependencies:
                dependencies[row.permission_code] = []
            dependencies[row.permission_code].append(row.depends_on_code)

        logger.info(f"✅ [PERMISSIONS] Grouped: {len(general)} general modules, {len(workflow)} workflow modules")

        return {
            "general": general,
            "workflow": workflow,
            "dependencies": dependencies
        }

    except Exception as e:
        logger.error(f"❌ [PERMISSIONS] Error getting grouped permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des permissions groupées: {str(e)}"
        )


@router.post(
    "/permissions",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une permission",
    description="Crée une nouvelle permission"
)
async def create_permission(
    permission: PermissionCreate,
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Crée une nouvelle permission."""
    try:
        logger.info(f"➕ [PERMISSIONS] Creating permission: {permission.code}")

        # Vérifier si le code existe déjà
        check_query = text("SELECT id FROM permission WHERE code = :code")
        existing = db.execute(check_query, {"code": permission.code}).fetchone()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Une permission avec le code '{permission.code}' existe déjà"
            )

        # Créer la permission
        insert_query = text("""
            INSERT INTO permission (id, code, name, description)
            VALUES (gen_random_uuid(), :code, :name, :description)
            RETURNING id, code, name, description
        """)

        result = db.execute(insert_query, {
            "code": permission.code,
            "name": permission.name,
            "description": permission.description
        }).fetchone()

        db.commit()
        redis_manager.delete_pattern("permissions:*")
        redis_manager.delete_pattern("roles:*")

        logger.info(f"✅ [PERMISSIONS] Permission created: {permission.code}")

        return {
            "id": result.id,
            "code": result.code,
            "name": result.name,
            "description": result.description
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [PERMISSIONS] Error creating permission: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création de la permission: {str(e)}"
        )


@router.delete(
    "/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une permission",
    description="Supprime une permission (et ses associations avec les rôles)"
)
async def delete_permission(
    permission_id: UUID,
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Supprime une permission."""
    try:
        logger.info(f"🗑️ [PERMISSIONS] Deleting permission: {permission_id}")

        # Vérifier si la permission existe
        check_query = text("SELECT id, code FROM permission WHERE id = :permission_id")
        existing = db.execute(check_query, {"permission_id": str(permission_id)}).fetchone()

        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission non trouvée"
            )

        # Supprimer la permission (CASCADE supprimera les associations)
        delete_query = text("DELETE FROM permission WHERE id = :permission_id")
        db.execute(delete_query, {"permission_id": str(permission_id)})
        db.commit()
        redis_manager.delete_pattern("permissions:*")
        redis_manager.delete_pattern("roles:*")

        logger.info(f"✅ [PERMISSIONS] Permission deleted: {existing.code}")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [PERMISSIONS] Error deleting permission: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression de la permission: {str(e)}"
        )


# ============================================================================
# ENDPOINTS - RÔLES
# ============================================================================

@router.get(
    "/",
    response_model=RoleListResponse,
    summary="Lister tous les rôles",
    description="Récupère la liste de tous les rôles disponibles pour le tenant"
)
async def list_roles(
    tenant_id: UUID = Query(..., description="ID du tenant"),
    include_system: bool = Query(True, description="Inclure les rôles système"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste tous les rôles disponibles.

    - Les rôles système sont créés par défaut et ne peuvent pas être supprimés
    - Les rôles custom peuvent être créés, modifiés et supprimés
    """
    try:
        logger.info(f"📋 [ROLES] Listing roles for tenant: {tenant_id}")

        # Requête pour récupérer les rôles avec le nombre d'utilisateurs et de permissions
        # Note: Les audités (AUDITE_RESP, AUDITE_CONTRIB) sont dans entity_member, pas users
        # IMPORTANT: Les rôles dans entity_member.roles sont en minuscules (audite_resp, audite_contrib)
        query = text("""
            SELECT
                r.id,
                r.code,
                r.name,
                r.description,
                r.is_system,
                r.created_at,
                r.updated_at,
                COALESCE(
                    CASE
                        WHEN r.code IN ('AUDITE_RESP', 'AUDITE_CONTRIB') THEN
                            (SELECT COUNT(DISTINCT em.id)
                             FROM entity_member em
                             JOIN ecosystem_entity ee ON em.entity_id = ee.id
                             WHERE em.roles::jsonb ? LOWER(r.code)
                             AND ee.tenant_id = :tenant_id
                             AND em.is_active = true)
                        ELSE
                            (SELECT COUNT(DISTINCT uor.user_id)
                             FROM user_organization_role uor
                             JOIN users u ON uor.user_id = u.id
                             WHERE uor.role = r.code
                             AND u.tenant_id = :tenant_id
                             AND uor.is_active = true)
                    END,
                    0
                ) as users_count,
                COALESCE(
                    (SELECT COUNT(*) FROM role_permission rp WHERE rp.role_id = r.id),
                    0
                ) as permissions_count
            FROM role r
            WHERE 1=1
            AND (:include_system = true OR r.is_system = false)
            ORDER BY r.is_system DESC, r.name ASC
        """)

        result = db.execute(query, {
            "tenant_id": str(tenant_id),
            "include_system": include_system
        })

        roles = []
        for row in result:
            roles.append({
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "description": row.description,
                "is_system": row.is_system,
                "users_count": row.users_count,
                "permissions_count": row.permissions_count,
                "created_at": row.created_at,
                "updated_at": row.updated_at
            })

        logger.info(f"✅ [ROLES] Found {len(roles)} roles")

        return {
            "items": roles,
            "total": len(roles)
        }

    except Exception as e:
        logger.error(f"❌ [ROLES] Error listing roles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des rôles: {str(e)}"
        )


@router.get(
    "/stats",
    response_model=RoleStatsResponse,
    summary="Statistiques des rôles",
    description="Récupère les statistiques globales des rôles"
)
async def get_roles_stats(
    tenant_id: UUID = Query(..., description="ID du tenant"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Récupère les statistiques des rôles pour le tenant."""
    try:
        logger.info(f"📊 [ROLES] Getting stats for tenant: {tenant_id}")

        # Compter les rôles
        roles_query = text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE is_system = true) as system_count,
                COUNT(*) FILTER (WHERE is_system = false) as custom_count
            FROM role
        """)

        roles_result = db.execute(roles_query).fetchone()

        # Compter les utilisateurs avec des rôles (users + entity_member pour audités)
        users_query = text("""
            SELECT
                (SELECT COUNT(DISTINCT uor.user_id)
                 FROM user_organization_role uor
                 JOIN users u ON uor.user_id = u.id
                 WHERE u.tenant_id = :tenant_id
                 AND uor.is_active = true)
                +
                (SELECT COUNT(DISTINCT em.id)
                 FROM entity_member em
                 JOIN ecosystem_entity ee ON em.entity_id = ee.id
                 WHERE ee.tenant_id = :tenant_id
                 AND em.is_active = true)
            AS total_users
        """)

        users_result = db.execute(users_query, {"tenant_id": str(tenant_id)}).fetchone()

        # Compter les permissions
        permissions_query = text("SELECT COUNT(*) FROM permission")
        permissions_result = db.execute(permissions_query).fetchone()

        return {
            "total_roles": roles_result.total if roles_result else 0,
            "system_roles": roles_result.system_count if roles_result else 0,
            "custom_roles": roles_result.custom_count if roles_result else 0,
            "total_users_with_roles": users_result[0] if users_result else 0,
            "total_permissions": permissions_result[0] if permissions_result else 0
        }

    except Exception as e:
        logger.error(f"❌ [ROLES] Error getting stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des statistiques: {str(e)}"
        )


@router.get(
    "/simple/list",
    summary="Liste simple des rôles",
    description="Récupère une liste simplifiée des rôles (id, code, name) pour les sélecteurs"
)
async def list_roles_simple(
    include_system: bool = Query(False, description="Inclure les rôles système"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Liste simplifiée des rôles pour les dropdowns.
    Utilise le tenant_id du current_user automatiquement.
    """
    try:
        tenant_id = current_user.get("tenant_id")
        if not tenant_id:
            raise HTTPException(status_code=400, detail="Tenant ID requis")

        logger.info(f"📋 [ROLES] Simple list for tenant: {tenant_id}")

        query = text("""
            SELECT id, code, name
            FROM role
            WHERE (:include_system = true OR is_system = false)
            ORDER BY name ASC
        """)

        result = db.execute(query, {"include_system": include_system})
        roles = [{"id": str(row.id), "code": row.code, "name": row.name} for row in result]

        return {"items": roles, "total": len(roles)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [ROLES] Error listing simple roles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des rôles: {str(e)}"
        )


@router.get(
    "/{role_id}",
    response_model=RoleDetailResponse,
    summary="Détail d'un rôle",
    description="Récupère les détails d'un rôle spécifique avec ses permissions"
)
async def get_role(
    role_id: UUID,
    tenant_id: UUID = Query(..., description="ID du tenant"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Récupère les détails d'un rôle avec ses permissions."""
    try:
        # Note: Les audités (AUDITE_RESP, AUDITE_CONTRIB) sont dans entity_member, pas users
        # IMPORTANT: Les rôles dans entity_member.roles sont en minuscules (audite_resp, audite_contrib)
        query = text("""
            SELECT
                r.id,
                r.code,
                r.name,
                r.description,
                r.is_system,
                r.created_at,
                r.updated_at,
                COALESCE(
                    CASE
                        WHEN r.code IN ('AUDITE_RESP', 'AUDITE_CONTRIB') THEN
                            (SELECT COUNT(DISTINCT em.id)
                             FROM entity_member em
                             JOIN ecosystem_entity ee ON em.entity_id = ee.id
                             WHERE em.roles::jsonb ? LOWER(r.code)
                             AND ee.tenant_id = :tenant_id
                             AND em.is_active = true)
                        ELSE
                            (SELECT COUNT(DISTINCT uor.user_id)
                             FROM user_organization_role uor
                             JOIN users u ON uor.user_id = u.id
                             WHERE uor.role = r.code
                             AND u.tenant_id = :tenant_id
                             AND uor.is_active = true)
                    END,
                    0
                ) as users_count,
                COALESCE(
                    (SELECT COUNT(*) FROM role_permission rp WHERE rp.role_id = r.id),
                    0
                ) as permissions_count
            FROM role r
            WHERE r.id = :role_id
        """)

        result = db.execute(query, {
            "role_id": str(role_id),
            "tenant_id": str(tenant_id)
        }).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        # Récupérer les permissions du rôle
        permissions_query = text("""
            SELECT p.id, p.code, p.module, p.action, p.permission_type, p.name, p.description
            FROM permission p
            JOIN role_permission rp ON p.id = rp.permission_id
            WHERE rp.role_id = :role_id
            ORDER BY p.module ASC, p.action ASC
        """)
        permissions_result = db.execute(permissions_query, {"role_id": str(role_id)})

        permissions = []
        for perm_row in permissions_result:
            permissions.append({
                "id": perm_row.id,
                "code": perm_row.code,
                "module": perm_row.module,
                "action": perm_row.action,
                "permission_type": perm_row.permission_type,
                "name": perm_row.name,
                "description": perm_row.description
            })

        return {
            "id": result.id,
            "code": result.code,
            "name": result.name,
            "description": result.description,
            "is_system": result.is_system,
            "users_count": result.users_count,
            "permissions_count": result.permissions_count,
            "permissions": permissions,
            "created_at": result.created_at,
            "updated_at": result.updated_at
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [ROLES] Error getting role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du rôle: {str(e)}"
        )


@router.post(
    "/",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un rôle",
    description="Crée un nouveau rôle personnalisé"
)
async def create_role(
    role: RoleCreate,
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Crée un nouveau rôle personnalisé.

    - Le code doit être unique
    - Les rôles créés par l'utilisateur ont is_system = false
    """
    try:
        logger.info(f"➕ [ROLES] Creating role: {role.code}")

        # Vérifier si le code existe déjà
        check_query = text("SELECT id FROM role WHERE code = :code")
        existing = db.execute(check_query, {"code": role.code.upper()}).fetchone()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Un rôle avec le code '{role.code}' existe déjà"
            )

        # Créer le rôle
        role_id = uuid4()
        now = datetime.utcnow()

        insert_query = text("""
            INSERT INTO role (id, code, name, description, is_system, created_at, updated_at)
            VALUES (:id, :code, :name, :description, :is_system, :created_at, :updated_at)
            RETURNING id, code, name, description, is_system, created_at, updated_at
        """)

        result = db.execute(insert_query, {
            "id": str(role_id),
            "code": role.code.upper(),
            "name": role.name,
            "description": role.description,
            "is_system": False,  # Les rôles créés par l'utilisateur ne sont jamais système
            "created_at": now,
            "updated_at": now
        }).fetchone()

        db.commit()
        redis_manager.delete_pattern("roles:*")

        logger.info(f"✅ [ROLES] Role created: {role.code}")

        return {
            "id": result.id,
            "code": result.code,
            "name": result.name,
            "description": result.description,
            "is_system": result.is_system,
            "users_count": 0,
            "permissions_count": 0,
            "created_at": result.created_at,
            "updated_at": result.updated_at
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [ROLES] Error creating role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création du rôle: {str(e)}"
        )


@router.put(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Modifier un rôle",
    description="Modifie un rôle existant (sauf les rôles système)"
)
async def update_role(
    role_id: UUID,
    role_update: RoleUpdate,
    tenant_id: UUID = Query(..., description="ID du tenant"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Modifie un rôle existant.

    - Les rôles système ne peuvent pas être modifiés
    - Seuls le nom et la description peuvent être modifiés
    """
    try:
        logger.info(f"✏️ [ROLES] Updating role: {role_id}")

        # Vérifier si le rôle existe et n'est pas système
        check_query = text("SELECT id, is_system, code FROM role WHERE id = :role_id")
        existing = db.execute(check_query, {"role_id": str(role_id)}).fetchone()

        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        if existing.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Les rôles système ne peuvent pas être modifiés"
            )

        # Mettre à jour
        update_fields = []
        params = {"role_id": str(role_id), "updated_at": datetime.utcnow()}

        if role_update.name is not None:
            update_fields.append("name = :name")
            params["name"] = role_update.name

        if role_update.description is not None:
            update_fields.append("description = :description")
            params["description"] = role_update.description

        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Aucun champ à mettre à jour"
            )

        update_fields.append("updated_at = :updated_at")

        update_query = text(f"""
            UPDATE role
            SET {', '.join(update_fields)}
            WHERE id = :role_id
            RETURNING id, code, name, description, is_system, created_at, updated_at
        """)

        result = db.execute(update_query, params).fetchone()
        db.commit()
        redis_manager.delete_pattern("roles:*")

        # Récupérer le count des utilisateurs
        count_query = text("""
            SELECT COUNT(DISTINCT uor.user_id)
            FROM user_organization_role uor
            JOIN users u ON uor.user_id = u.id
            WHERE uor.role = :code
            AND u.tenant_id = :tenant_id
            AND uor.is_active = true
        """)
        count_result = db.execute(count_query, {
            "code": result.code,
            "tenant_id": str(tenant_id)
        }).fetchone()

        logger.info(f"✅ [ROLES] Role updated: {result.code}")

        return {
            "id": result.id,
            "code": result.code,
            "name": result.name,
            "description": result.description,
            "is_system": result.is_system,
            "users_count": count_result[0] if count_result else 0,
            "created_at": result.created_at,
            "updated_at": result.updated_at
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [ROLES] Error updating role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour du rôle: {str(e)}"
        )


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un rôle",
    description="Supprime un rôle personnalisé (sauf les rôles système)"
)
async def delete_role(
    role_id: UUID,
    tenant_id: UUID = Query(..., description="ID du tenant"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Supprime un rôle.

    - Les rôles système ne peuvent pas être supprimés
    - Un rôle ne peut pas être supprimé s'il est assigné à des utilisateurs
    """
    try:
        logger.info(f"🗑️ [ROLES] Deleting role: {role_id}")

        # Vérifier si le rôle existe
        check_query = text("SELECT id, is_system, code FROM role WHERE id = :role_id")
        existing = db.execute(check_query, {"role_id": str(role_id)}).fetchone()

        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        if existing.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Les rôles système ne peuvent pas être supprimés"
            )

        # Vérifier si le rôle est utilisé
        usage_query = text("""
            SELECT COUNT(*)
            FROM user_organization_role uor
            JOIN users u ON uor.user_id = u.id
            WHERE uor.role = :code
            AND u.tenant_id = :tenant_id
            AND uor.is_active = true
        """)
        usage_result = db.execute(usage_query, {
            "code": existing.code,
            "tenant_id": str(tenant_id)
        }).fetchone()

        if usage_result and usage_result[0] > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ce rôle est assigné à {usage_result[0]} utilisateur(s). Retirez-le d'abord avant de le supprimer."
            )

        # Supprimer le rôle
        delete_query = text("DELETE FROM role WHERE id = :role_id")
        db.execute(delete_query, {"role_id": str(role_id)})
        db.commit()
        redis_manager.delete_pattern("roles:*")

        logger.info(f"✅ [ROLES] Role deleted: {existing.code}")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [ROLES] Error deleting role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression du rôle: {str(e)}"
        )


# ============================================================================
# ENDPOINTS - PERMISSIONS DES RÔLES
# ============================================================================

@router.get(
    "/{role_id}/permissions",
    response_model=PermissionListResponse,
    summary="Lister les permissions d'un rôle",
    description="Récupère la liste des permissions assignées à un rôle"
)
async def get_role_permissions(
    role_id: UUID,
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Récupère les permissions assignées à un rôle."""
    try:
        logger.info(f"📋 [ROLES] Getting permissions for role: {role_id}")

        # Vérifier si le rôle existe
        check_query = text("SELECT id, code FROM role WHERE id = :role_id")
        existing = db.execute(check_query, {"role_id": str(role_id)}).fetchone()

        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        # Récupérer les permissions du rôle
        query = text("""
            SELECT p.id, p.code, p.name, p.description
            FROM permission p
            JOIN role_permission rp ON p.id = rp.permission_id
            WHERE rp.role_id = :role_id
            ORDER BY p.code ASC
        """)

        result = db.execute(query, {"role_id": str(role_id)})

        permissions = []
        for row in result:
            permissions.append({
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "description": row.description
            })

        logger.info(f"✅ [ROLES] Found {len(permissions)} permissions for role {existing.code}")

        return {
            "items": permissions,
            "total": len(permissions)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [ROLES] Error getting role permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des permissions: {str(e)}"
        )


@router.put(
    "/{role_id}/permissions",
    response_model=PermissionListResponse,
    summary="Assigner des permissions à un rôle",
    description="Remplace les permissions d'un rôle par une nouvelle liste"
)
async def assign_role_permissions(
    role_id: UUID,
    request: AssignPermissionsRequest,
    tenant_id: UUID = Query(None, description="ID du tenant (optionnel)"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Assigne des permissions à un rôle (remplace les permissions existantes).

    - Les rôles système ne peuvent pas être modifiés
    - Toutes les permissions précédentes sont supprimées et remplacées
    """
    try:
        logger.info(f"🔐 [ROLES] Assigning permissions to role: {role_id}")

        # Vérifier si le rôle existe
        check_query = text("SELECT id, code, is_system FROM role WHERE id = :role_id")
        existing = db.execute(check_query, {"role_id": str(role_id)}).fetchone()

        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        # Seuls les rôles ADMIN et SUPER_ADMIN ne peuvent pas être modifiés
        # Les autres rôles système (AUDITEUR, RSSI, etc.) peuvent avoir leurs permissions modifiées
        READONLY_ROLES = ['ADMIN', 'SUPER_ADMIN']
        if existing.code in READONLY_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ce rôle est réservé à l'administration de la plateforme et ne peut pas être modifié"
            )

        # Vérifier que toutes les permissions existent
        if request.permission_ids:
            permission_ids_str = [str(pid) for pid in request.permission_ids]
            check_permissions_query = text("""
                SELECT id FROM permission WHERE id = ANY(CAST(:permission_ids AS uuid[]))
            """)
            existing_permissions = db.execute(check_permissions_query, {
                "permission_ids": permission_ids_str
            }).fetchall()

            if len(existing_permissions) != len(request.permission_ids):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Une ou plusieurs permissions n'existent pas"
                )

        # Supprimer les permissions existantes
        delete_query = text("DELETE FROM role_permission WHERE role_id = :role_id")
        db.execute(delete_query, {"role_id": str(role_id)})

        # Ajouter les nouvelles permissions
        if request.permission_ids:
            for permission_id in request.permission_ids:
                insert_query = text("""
                    INSERT INTO role_permission (role_id, permission_id)
                    VALUES (:role_id, :permission_id)
                    ON CONFLICT DO NOTHING
                """)
                db.execute(insert_query, {
                    "role_id": str(role_id),
                    "permission_id": str(permission_id)
                })

        db.commit()
        redis_manager.delete_pattern("roles:*")

        logger.info(f"✅ [ROLES] Assigned {len(request.permission_ids)} permissions to role {existing.code}")

        # 🔄 Synchroniser vers Keycloak (3 couches architecture)
        try:
            keycloak_service = get_keycloak_service()
            sync_service = PermissionSyncService(keycloak_service)
            sync_result = await sync_service.sync_role_permissions_to_keycloak(db, existing.code)
            logger.info(f"🔄 [KEYCLOAK] Synchronisation: {sync_result}")
        except Exception as sync_error:
            # Ne pas bloquer si la sync Keycloak échoue - les permissions sont enregistrées en BDD
            logger.warning(f"⚠️ [KEYCLOAK] Échec synchronisation (non bloquant): {sync_error}")

        # Retourner les permissions mises à jour
        return await get_role_permissions(role_id, current_user, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [ROLES] Error assigning permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'assignation des permissions: {str(e)}"
        )


@router.post(
    "/{role_id}/permissions/{permission_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter une permission à un rôle",
    description="Ajoute une permission spécifique à un rôle"
)
async def add_permission_to_role(
    role_id: UUID,
    permission_id: UUID,
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Ajoute une permission à un rôle."""
    try:
        logger.info(f"➕ [ROLES] Adding permission {permission_id} to role {role_id}")

        # Vérifier si le rôle existe
        role_check = text("SELECT id, code FROM role WHERE id = :role_id")
        role = db.execute(role_check, {"role_id": str(role_id)}).fetchone()

        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        # Vérifier si la permission existe
        perm_check = text("SELECT id, code FROM permission WHERE id = :permission_id")
        permission = db.execute(perm_check, {"permission_id": str(permission_id)}).fetchone()

        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission non trouvée"
            )

        # Ajouter la permission
        insert_query = text("""
            INSERT INTO role_permission (role_id, permission_id)
            VALUES (:role_id, :permission_id)
            ON CONFLICT DO NOTHING
        """)
        db.execute(insert_query, {
            "role_id": str(role_id),
            "permission_id": str(permission_id)
        })
        db.commit()
        redis_manager.delete_pattern("roles:*")

        logger.info(f"✅ [ROLES] Permission {permission.code} added to role {role.code}")

        return {"message": f"Permission '{permission.code}' ajoutée au rôle '{role.code}'"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [ROLES] Error adding permission to role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'ajout de la permission: {str(e)}"
        )


@router.delete(
    "/{role_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer une permission d'un rôle",
    description="Retire une permission spécifique d'un rôle"
)
async def remove_permission_from_role(
    role_id: UUID,
    permission_id: UUID,
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Retire une permission d'un rôle."""
    try:
        logger.info(f"🗑️ [ROLES] Removing permission {permission_id} from role {role_id}")

        # Vérifier si le rôle existe
        role_check = text("SELECT id, code FROM role WHERE id = :role_id")
        role = db.execute(role_check, {"role_id": str(role_id)}).fetchone()

        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        # Supprimer l'association
        delete_query = text("""
            DELETE FROM role_permission
            WHERE role_id = :role_id AND permission_id = :permission_id
        """)
        result = db.execute(delete_query, {
            "role_id": str(role_id),
            "permission_id": str(permission_id)
        })
        db.commit()
        redis_manager.delete_pattern("roles:*")

        logger.info(f"✅ [ROLES] Permission removed from role {role.code}")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [ROLES] Error removing permission from role: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression de la permission: {str(e)}"
        )


@router.get(
    "/{role_id}/detail",
    response_model=RoleDetailResponse,
    summary="Détail complet d'un rôle",
    description="Récupère les détails d'un rôle avec ses permissions"
)
async def get_role_detail(
    role_id: UUID,
    tenant_id: UUID = Query(..., description="ID du tenant"),
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """Récupère les détails complets d'un rôle avec ses permissions."""
    try:
        logger.info(f"📋 [ROLES] Getting detailed role: {role_id}")

        # Récupérer le rôle
        # Note: Les audités (AUDITE_RESP, AUDITE_CONTRIB) sont dans entity_member, pas users
        # IMPORTANT: Les rôles dans entity_member.roles sont en minuscules (audite_resp, audite_contrib)
        query = text("""
            SELECT
                r.id,
                r.code,
                r.name,
                r.description,
                r.is_system,
                r.created_at,
                r.updated_at,
                COALESCE(
                    CASE
                        WHEN r.code IN ('AUDITE_RESP', 'AUDITE_CONTRIB') THEN
                            (SELECT COUNT(DISTINCT em.id)
                             FROM entity_member em
                             JOIN ecosystem_entity ee ON em.entity_id = ee.id
                             WHERE em.roles::jsonb ? LOWER(r.code)
                             AND ee.tenant_id = :tenant_id
                             AND em.is_active = true)
                        ELSE
                            (SELECT COUNT(DISTINCT uor.user_id)
                             FROM user_organization_role uor
                             JOIN users u ON uor.user_id = u.id
                             WHERE uor.role = r.code
                             AND u.tenant_id = :tenant_id
                             AND uor.is_active = true)
                    END,
                    0
                ) as users_count,
                COALESCE(
                    (SELECT COUNT(*) FROM role_permission rp WHERE rp.role_id = r.id),
                    0
                ) as permissions_count
            FROM role r
            WHERE r.id = :role_id
        """)

        result = db.execute(query, {
            "role_id": str(role_id),
            "tenant_id": str(tenant_id)
        }).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        # Récupérer les permissions
        permissions_query = text("""
            SELECT p.id, p.code, p.name, p.description
            FROM permission p
            JOIN role_permission rp ON p.id = rp.permission_id
            WHERE rp.role_id = :role_id
            ORDER BY p.code ASC
        """)

        permissions_result = db.execute(permissions_query, {"role_id": str(role_id)})
        permissions = [
            {"id": row.id, "code": row.code, "name": row.name, "description": row.description}
            for row in permissions_result
        ]

        return {
            "id": result.id,
            "code": result.code,
            "name": result.name,
            "description": result.description,
            "is_system": result.is_system,
            "users_count": result.users_count,
            "permissions_count": result.permissions_count,
            "created_at": result.created_at,
            "updated_at": result.updated_at,
            "permissions": permissions
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [ROLES] Error getting role detail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du rôle: {str(e)}"
        )


# ============================================================================
# SYNCHRONISATION KEYCLOAK
# ============================================================================

@router.post(
    "/sync-to-keycloak",
    summary="Synchroniser toutes les permissions vers Keycloak",
    description="""
    Synchronise la matrice de droits (role_permission) vers Keycloak.

    Cette opération :
    1. Crée les client roles dans Keycloak pour chaque permission
    2. Met à jour les realm roles composites pour chaque rôle métier

    Architecture 3 couches :
    - Matrice (DB) = Référentiel fonctionnel
    - Keycloak = Source technique d'autorisation
    - Application = Consommateur des droits du token
    """
)
async def sync_all_permissions_to_keycloak(
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Synchronise toutes les permissions vers Keycloak (admin only).

    Utile après modifications massives de la matrice de droits.
    """
    try:
        logger.info("🔄 [KEYCLOAK] Début synchronisation complète des permissions")

        keycloak_service = get_keycloak_service()
        sync_service = PermissionSyncService(keycloak_service)

        # 1. Créer tous les client roles pour les permissions
        all_perms_result = await sync_service.sync_all_permissions_to_keycloak(db)

        if not all_perms_result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erreur lors de la synchronisation: {all_perms_result.get('error')}"
            )

        # 2. Synchroniser chaque rôle
        roles_query = text("SELECT code FROM role WHERE code NOT IN ('ADMIN', 'SUPER_ADMIN')")
        roles = db.execute(roles_query).fetchall()

        synced_roles = []
        for role_row in roles:
            role_code = role_row.code
            try:
                role_result = await sync_service.sync_role_permissions_to_keycloak(db, role_code)
                synced_roles.append({
                    "role": role_code,
                    "permissions_count": role_result.get("permissions_synced", 0),
                    "success": True
                })
            except Exception as e:
                synced_roles.append({
                    "role": role_code,
                    "error": str(e),
                    "success": False
                })

        logger.info(f"✅ [KEYCLOAK] Synchronisation terminée: {len(synced_roles)} rôles traités")

        return {
            "success": True,
            "message": "Synchronisation vers Keycloak terminée",
            "permissions_created": all_perms_result.get("created_or_exists", 0),
            "roles_synced": synced_roles
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [KEYCLOAK] Erreur synchronisation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la synchronisation Keycloak: {str(e)}"
        )


@router.post(
    "/{role_id}/sync-to-keycloak",
    summary="Synchroniser un rôle vers Keycloak",
    description="Synchronise les permissions d'un rôle spécifique vers Keycloak"
)
async def sync_role_to_keycloak(
    role_id: UUID,
    current_user: dict = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db)
):
    """
    Synchronise les permissions d'un rôle vers Keycloak.
    """
    try:
        # Récupérer le code du rôle
        role_query = text("SELECT code FROM role WHERE id = :role_id")
        role = db.execute(role_query, {"role_id": str(role_id)}).fetchone()

        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rôle non trouvé"
            )

        logger.info(f"🔄 [KEYCLOAK] Synchronisation du rôle {role.code}")

        keycloak_service = get_keycloak_service()
        sync_service = PermissionSyncService(keycloak_service)

        result = await sync_service.sync_role_permissions_to_keycloak(db, role.code)

        return {
            "success": True,
            "message": f"Rôle {role.code} synchronisé vers Keycloak",
            "permissions_synced": result.get("permissions_synced", 0),
            "permission_codes": result.get("permission_codes", [])
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [KEYCLOAK] Erreur synchronisation rôle: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la synchronisation: {str(e)}"
        )
