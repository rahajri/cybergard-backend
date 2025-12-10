# backend/src/api/v1/organizations.py
"""
API FastAPI pour le module Organizations (Clients)
Endpoints CRUD pour les organizations clientes
"""

from typing import Optional, Literal, Dict, Any, List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.orm import Session

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak, require_role, require_permission, SUPERUSER_ROLES
from src.models.audit import User
from src.models.organization import Organization
from src.models.tenant import Tenant
from src.utils.audit_logger import audit_log
from src.schemas.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationListResponse,
    OrganizationStats,
    TenantCreateData,
)

import logging

logger = logging.getLogger(__name__)

# Router sans prefix - le prefix est déjà dans main.py (/api/v1/organizations)
router = APIRouter(tags=["Organizations"])

# ============================================================================
# Helpers
# ============================================================================

def _check_organization_permission(current_user: User, action: str, db: Session) -> None:
    """
    Vérifie si l'utilisateur a les permissions pour effectuer une action sur les organisations.

    🔒 IMPORTANT: Vérifie les permissions via la table role_permission, pas les rôles directement.

    Mapping action -> permission:
    - "read" -> ORGANIZATION_READ
    - "create" -> ORGANIZATION_CREATE
    - "update" -> ORGANIZATION_UPDATE
    - "delete" -> ORGANIZATION_DELETE
    - "export" -> ORGANIZATION_READ (réutilise read)

    Args:
        current_user: Utilisateur authentifié
        action: Action à vérifier ("create", "update", "delete", "export", "read")
        db: Session de base de données

    Raises:
        HTTPException: Si l'utilisateur n'a pas les permissions
    """
    # Super-admin: toutes les permissions
    user_roles = [role.code for role in current_user.roles] if current_user.roles else []

    if any(role in SUPERUSER_ROLES for role in user_roles):
        logger.info(f"👑 Super-admin: permission {action} accordée pour {current_user.email}")
        return

    # Vérifier qu'ils ont un tenant
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : utilisateur sans tenant"
        )

    # Mapper l'action vers le code de permission
    action_to_permission = {
        "read": "ORGANIZATION_READ",
        "create": "ORGANIZATION_CREATE",
        "update": "ORGANIZATION_UPDATE",
        "delete": "ORGANIZATION_DELETE",
        "export": "ORGANIZATION_READ",  # Export utilise la permission de lecture
    }

    permission_code = action_to_permission.get(action)
    if not permission_code:
        logger.error(f"❌ Action inconnue: {action}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action inconnue: {action}"
        )

    # 🔒 Vérifier la permission dans la BDD via role_permission
    permission_query = text("""
        SELECT COUNT(*) as count
        FROM role_permission rp
        JOIN role r ON rp.role_id = r.id
        JOIN permission p ON rp.permission_id = p.id
        JOIN user_role ur ON ur.role_id = r.id
        WHERE ur.user_id = :user_id
        AND p.code = :permission_code
    """)

    result = db.execute(permission_query, {
        "user_id": str(current_user.id),
        "permission_code": permission_code
    }).scalar()

    if result and result > 0:
        logger.info(f"✅ Permission {permission_code} accordée pour {current_user.email}")
        return

    # Si on arrive ici, l'utilisateur n'a pas les permissions
    logger.warning(f"⛔ Permission {permission_code} REFUSÉE pour {current_user.email} (rôles: {user_roles})")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Vous n'avez pas la permission '{permission_code}'. Contactez votre administrateur."
    )


def _legacy_to_current_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remappe d'éventuelles clés héritées de l'ancien schéma vers le schéma courant.
      - sector -> activity
      - enterprise_category -> category
      - employee_count -> workforce
    Supprime aussi les champs INSEE transitoires non persistés dans Organization.
    """
    d = dict(data)

    if "sector" in d and "activity" not in d:
        d["activity"] = d.pop("sector")

    if "enterprise_category" in d and "category" not in d:
        d["category"] = d.pop("enterprise_category")

    if "employee_count" in d and "workforce" not in d:
        # accepte int/str, laisse None sinon
        try:
            d["workforce"] = int(d.pop("employee_count"))
        except Exception:
            d.pop("employee_count", None)

    # champs INSEE transportés côté front mais non mappés dans le modèle
    insee_transient = {"siren", "ape_code", "address_line1", "postal_code", "city"}
    for k in list(d.keys()):
        if k in insee_transient:
            d.pop(k, None)

    return d


# ============================================================================
# ENDPOINTS : Organizations (CRUD)
# ============================================================================

@router.get("/", response_model=OrganizationListResponse)
async def list_organizations(
    is_active: Optional[bool] = Query(None),
    subscription_type: Optional[Literal["starter", "professional", "enterprise"]] = Query(None),
    # recherche plein texte
    search: Optional[str] = Query(None, description="Recherche par nom ou domaine"),
    # filtres métier
    activity: Optional[str] = Query(None, description="Secteur d'activité (libellé NAF)"),
    category: Optional[Literal["MIC", "PME", "ETI", "GE"]] = Query(None, description="Catégorie INSEE"),
    tenant_id: Optional[UUID] = Query(None, description="Filtrer par tenant (super-admin only)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db),
):
    """
    Liste toutes les organizations avec filtres et recherche.

    **Utilisateurs normaux**: Voient uniquement les organisations de leur tenant.
    **Super-admins**: Peuvent voir toutes les organisations ou filtrer par tenant.
    """
    # 🔒 Vérification des permissions
    _check_organization_permission(current_user, "read", db)

    is_super_admin = current_user.is_super_admin()

    # 🔒 Filtrage par tenant
    if is_super_admin:
        # Super-admin: peut voir tous les tenants ou filtrer
        if tenant_id:
            logger.info(f"👑 Super-admin: liste des organisations pour tenant: {tenant_id}")
            query = select(Organization).where(Organization.tenant_id == tenant_id)
        else:
            logger.info(f"👑 Super-admin: liste de TOUTES les organisations")
            query = select(Organization)
    else:
        # Utilisateur normal: doit avoir un tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        logger.info(f"📋 Liste des organisations pour tenant: {current_user.tenant_id}")
        query = select(Organization).where(Organization.tenant_id == current_user.tenant_id)

    # Filtres
    if is_active is not None:
        query = query.where(Organization.is_active == is_active)

    if subscription_type:
        query = query.where(Organization.subscription_type == subscription_type)

    if activity:
        query = query.where(Organization.activity.ilike(f"%{activity}%"))

    if category:
        query = query.where(Organization.category == category)

    if search:
        sp = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(Organization.name).like(sp),
                func.lower(Organization.domain).like(sp),
                func.lower(Organization.naf_title).like(sp),
            )
        )

    # Tri + pagination
    query = query.order_by(Organization.created_at.desc()).offset(skip).limit(limit)

    organizations = db.execute(query).scalars().all()

    # Total
    if is_super_admin:
        if tenant_id:
            count_q = select(func.count()).select_from(Organization).where(
                Organization.tenant_id == tenant_id
            )
        else:
            count_q = select(func.count()).select_from(Organization)
    else:
        count_q = select(func.count()).select_from(Organization).where(
            Organization.tenant_id == current_user.tenant_id
        )
    if is_active is not None:
        count_q = count_q.where(Organization.is_active == is_active)
    if subscription_type:
        count_q = count_q.where(Organization.subscription_type == subscription_type)
    if activity:
        count_q = count_q.where(Organization.activity.ilike(f"%{activity}%"))
    if category:
        count_q = count_q.where(Organization.category == category)
    if search:
        sp = f"%{search.lower()}%"
        count_q = count_q.where(
            or_(
                func.lower(Organization.name).like(sp),
                func.lower(Organization.domain).like(sp),
                func.lower(Organization.naf_title).like(sp),
            )
        )
    total = db.execute(count_q).scalar() or 0

    return {"items": organizations, "total": total, "skip": skip, "limit": limit}


@router.post("/", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
@audit_log(action="CREATE_ORGANIZATION", resource_type="organization")
async def create_organization(
    organization: OrganizationCreate,
    create_tenant: bool = Query(True, description="Créer automatiquement un tenant associé (super-admin only)"),
    target_tenant_id: Optional[UUID] = Query(None, description="ID du tenant cible (super-admin only)"),
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db),
):
    """
    Crée une nouvelle organization cliente.

    **Utilisateurs normaux**: Créent une organisation dans leur propre tenant.
    **Super-admins**: Peuvent créer une organisation pour n'importe quel tenant (via target_tenant_id)
                       ou créer un nouveau tenant avec son organisation.
    """
    # 🔒 Vérification des permissions
    _check_organization_permission(current_user, "create", db)

    is_super_admin = current_user.is_super_admin()

    # 🔒 Déterminer le tenant cible
    if is_super_admin:
        # Super-admin peut:
        # 1. Spécifier un tenant existant via target_tenant_id
        # 2. Créer un nouveau tenant si create_tenant=True et target_tenant_id=None
        if target_tenant_id:
            # Vérifier que le tenant existe
            target_tenant = db.get(Tenant, target_tenant_id)
            if not target_tenant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant {target_tenant_id} introuvable"
                )
            tenant_id = target_tenant_id
            logger.info(f"👑 Super-admin: création d'organisation pour tenant existant: {tenant_id}")
        elif create_tenant:
            # Créer un nouveau tenant
            limits = {
                "starter": {"max_users": 5, "max_organizations": 1},
                "professional": {"max_users": 50, "max_organizations": 5},
                "enterprise": {"max_users": 500, "max_organizations": 50},
            }
            lcfg = limits.get(organization.subscription_type, limits["starter"])
            new_tenant = Tenant(
                id=uuid4(),
                name=organization.name,
                is_active=organization.is_active,
                subscription_type=organization.subscription_type,
                max_users=lcfg["max_users"],
                max_organizations=lcfg["max_organizations"],
            )
            db.add(new_tenant)
            db.flush()
            tenant_id = new_tenant.id
            logger.info(f"👑 Super-admin: nouveau tenant créé: {new_tenant.name} ({tenant_id})")
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Super-admin doit spécifier target_tenant_id ou create_tenant=true"
            )
    else:
        # Utilisateur normal: doit avoir un tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )

        # Ignorer target_tenant_id et create_tenant pour les utilisateurs normaux
        if target_tenant_id or create_tenant:
            logger.warning(f"⚠️ Utilisateur non super-admin tente de spécifier tenant: {current_user.email}")

        tenant_id = current_user.tenant_id
        logger.info(f"📝 Création d'organisation pour tenant: {tenant_id}")

    # Remap legacy -> schéma courant
    org_data = _legacy_to_current_payload(organization.model_dump())
    org_data["tenant_id"] = tenant_id

    # Unicité nom PAR TENANT
    existing_org = db.execute(
        select(Organization).where(
            Organization.name == organization.name,
            Organization.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Une organisation avec le nom '{organization.name}' existe déjà dans ce tenant",
        )

    # Création
    db_organization = Organization(**org_data)
    db.add(db_organization)
    db.commit()
    db.refresh(db_organization)

    logger.info(f"✓ Organization créée: {db_organization.name} ({db_organization.id})")
    return db_organization


@router.get("/{organization_id}/admin-info")
async def get_organization_admin_info(
    organization_id: UUID,
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère les informations de l'administrateur du tenant associé à l'organisation.

    Retourne:
      - first_name, last_name, email, phone de l'admin du tenant
      - L'admin est défini comme l'utilisateur avec is_tenant_owner = true
    """
    # 🔒 Vérification des permissions
    _check_organization_permission(current_user, "read", db)

    # Récupérer l'organisation
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization non trouvée"
        )

    if not organization.tenant_id:
        return {
            "has_admin": False,
            "message": "Aucun tenant associé à cette organisation"
        }

    # Chercher l'utilisateur proprietaire du tenant (is_tenant_owner = true)
    owner_query = text("""
        SELECT
            u.id,
            u.email,
            u.first_name,
            u.last_name,
            u.phone,
            u.created_at,
            u.last_login_at
        FROM users u
        WHERE u.tenant_id = :tenant_id
          AND u.is_tenant_owner = true
          AND u.is_active = true
        LIMIT 1
    """)

    result = db.execute(owner_query, {"tenant_id": str(organization.tenant_id)}).first()

    if not result:
        # Fallback 1: Chercher utilisateur avec role TENANT_ADMIN
        admin_query = text("""
            SELECT
                u.id,
                u.email,
                u.first_name,
                u.last_name,
                u.phone,
                u.created_at,
                u.last_login_at
            FROM users u
            JOIN user_role ur ON u.id = ur.user_id
            JOIN role r ON ur.role_id = r.id
            WHERE u.tenant_id = :tenant_id
              AND r.code = 'TENANT_ADMIN'
              AND u.is_active = true
            ORDER BY u.created_at ASC
            LIMIT 1
        """)
        result = db.execute(admin_query, {"tenant_id": str(organization.tenant_id)}).first()

    if not result:
        # Fallback 2: prendre le premier utilisateur actif du tenant
        fallback_query = text("""
            SELECT
                u.id,
                u.email,
                u.first_name,
                u.last_name,
                u.phone,
                u.created_at,
                u.last_login_at
            FROM users u
            WHERE u.tenant_id = :tenant_id
              AND u.is_active = true
            ORDER BY u.created_at ASC
            LIMIT 1
        """)
        result = db.execute(fallback_query, {"tenant_id": str(organization.tenant_id)}).first()

    if not result:
        return {
            "has_admin": False,
            "message": "Aucun utilisateur actif trouve pour ce tenant"
        }

    return {
        "has_admin": True,
        "admin": {
            "id": str(result.id),
            "email": result.email,
            "first_name": result.first_name,
            "last_name": result.last_name,
            "phone": result.phone,
            "created_at": result.created_at.isoformat() if result.created_at else None,
            "last_login_at": result.last_login_at.isoformat() if result.last_login_at else None
        }
    }


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db)
):
    """Récupère une organization par son ID."""
    # 🔒 Vérification des permissions
    _check_organization_permission(current_user, "read", db)

    is_super_admin = current_user.is_super_admin()

    # 🔒 Récupérer l'organisation avec vérification tenant
    if is_super_admin:
        # Super-admin: peut accéder à n'importe quelle organisation
        organization = db.get(Organization, organization_id)
    else:
        # Utilisateur normal: uniquement son tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        organization = db.execute(
            select(Organization).where(
                Organization.id == organization_id,
                Organization.tenant_id == current_user.tenant_id
            )
        ).scalar_one_or_none()

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization non trouvée"
        )
    return organization


@router.patch("/{organization_id}", response_model=OrganizationResponse)
@audit_log(action="UPDATE_ORGANIZATION", resource_type="organization")
async def update_organization(
    organization_id: UUID,
    organization_update: OrganizationUpdate,
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db),
):
    """Met à jour une organization."""
    # 🔒 Vérification des permissions
    _check_organization_permission(current_user, "update", db)

    is_super_admin = current_user.is_super_admin()

    # 🔒 Récupérer l'organisation avec vérification tenant
    if is_super_admin:
        # Super-admin: peut modifier n'importe quelle organisation
        db_org = db.get(Organization, organization_id)
    else:
        # Utilisateur normal: uniquement son tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        db_org = db.execute(
            select(Organization).where(
                Organization.id == organization_id,
                Organization.tenant_id == current_user.tenant_id
            )
        ).scalar_one_or_none()

    if not db_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization non trouvée"
        )

    # Unicité du nom si modifié (dans le tenant)
    if organization_update.name and organization_update.name != db_org.name:
        # Pour super-admin, vérifier unicité dans le même tenant que l'organisation
        # Pour utilisateur normal, vérifier dans son tenant
        target_tenant = db_org.tenant_id if is_super_admin else current_user.tenant_id

        conflict = db.execute(
            select(Organization).where(
                and_(
                    Organization.name == organization_update.name,
                    Organization.id != organization_id,
                    Organization.tenant_id == target_tenant
                )
            )
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Une organisation avec le nom '{organization_update.name}' existe déjà dans ce tenant",
            )

    # Remap legacy -> schéma courant puis update
    update_data = _legacy_to_current_payload(
        organization_update.model_dump(exclude_unset=True)
    )
    for k, v in update_data.items():
        setattr(db_org, k, v)

    db.commit()
    db.refresh(db_org)
    logger.info(f"✓ Organization mise à jour: {db_org.name} ({db_org.id})")
    return db_org


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
@audit_log(action="DELETE_ORGANIZATION", resource_type="organization")
async def delete_organization(
    organization_id: UUID,
    force: bool = Query(False, description="Forcer la suppression même avec des données liées"),
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db),
):
    """
    Supprime complètement une organisation et toutes ses dépendances

    Ordre de suppression (IMPORTANT) :
    1. Rôles des utilisateurs (user_role) - aucune contrainte
    2. Utilisateurs (users) - référence organization
    3. Organisation (organization) - référence tenant
    4. Tenant (tenant) - si non partagé
    """
    # 🔒 Vérification des permissions
    _check_organization_permission(current_user, "delete", db)

    is_super_admin = current_user.is_super_admin()

    logger.info(f"🔴 Tentative de suppression de l'organisation: {organization_id} par {'super-admin' if is_super_admin else f'tenant: {current_user.tenant_id}'}")

    # 1. 🔒 Vérifier que l'organisation existe ET appartient au tenant (sauf super-admin)
    if is_super_admin:
        # Super-admin: peut supprimer n'importe quelle organisation
        org_result = db.execute(
            text("SELECT name, tenant_id FROM organization WHERE id = :org_id"),
            {"org_id": str(organization_id)}
        ).first()
    else:
        # Utilisateur normal: uniquement son tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        org_result = db.execute(
            text("SELECT name, tenant_id FROM organization WHERE id = :org_id AND tenant_id = :tenant_id"),
            {"org_id": str(organization_id), "tenant_id": str(current_user.tenant_id)}
        ).first()

    if not org_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation non trouvée"
        )
    
    org_name = org_result[0]
    tenant_id = org_result[1]
    
    # 2. Vérifier les dépendances critiques si force=False
    if not force:
        try:
            audit_count = db.execute(
                text("SELECT COUNT(*) FROM audit WHERE organization_id = :org_id"),
                {"org_id": str(organization_id)}
            ).scalar()
            
            if audit_count and audit_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Impossible de supprimer : {audit_count} audit(s) lié(s). Utilisez force=true."
                )
        except Exception as e:
            if "relation" not in str(e).lower():  # Si ce n'est pas une erreur de table inexistante
                logger.warning(f"⚠️ Erreur vérification audits: {e}")
    
    try:
        # 3. Récupérer les IDs des utilisateurs
        user_ids_result = db.execute(
            text("SELECT id FROM users WHERE default_org_id = :org_id"),
            {"org_id": str(organization_id)}
        ).fetchall()
        
        user_ids = [str(row[0]) for row in user_ids_result]
        user_count = len(user_ids)
        
        logger.info(f"📋 Trouvé {user_count} utilisateur(s) à supprimer")
        
        # 4. Supprimer les rôles des utilisateurs (ÉTAPE 1 - aucune contrainte)
        if user_ids:
            user_ids_str = "'" + "','".join(user_ids) + "'"
            roles_deleted = db.execute(
                text(f"DELETE FROM user_role WHERE user_id IN ({user_ids_str})")
            )
            logger.info(f"✅ Rôles supprimés pour {user_count} utilisateur(s)")
        
        # 5. Supprimer les utilisateurs (ÉTAPE 2 - avant l'organisation)
        if user_count > 0:
            users_deleted = db.execute(
                text("DELETE FROM users WHERE default_org_id = :org_id"),
                {"org_id": str(organization_id)}
            )
            logger.info(f"✅ {user_count} utilisateur(s) supprimé(s)")
        
        # 6. Supprimer l'organisation (ÉTAPE 3 - après les utilisateurs)
        org_deleted = db.execute(
            text("DELETE FROM organization WHERE id = :org_id"),
            {"org_id": str(organization_id)}
        )
        logger.info(f"✅ Organisation supprimée: {org_name}")
        
        # 7. Supprimer le tenant SI aucune autre organisation ne l'utilise (ÉTAPE 4)
        if tenant_id:
            other_orgs_count = db.execute(
                text("""
                    SELECT COUNT(*) FROM organization 
                    WHERE tenant_id = :tenant_id AND id != :org_id
                """),
                {"tenant_id": str(tenant_id), "org_id": str(organization_id)}
            ).scalar()
            
            if other_orgs_count == 0:
                db.execute(
                    text("DELETE FROM tenant WHERE id = :tenant_id"),
                    {"tenant_id": str(tenant_id)}
                )
                logger.info(f"✅ Tenant supprimé: {tenant_id} (aucune autre organisation)")
            else:
                logger.info(f"ℹ️ Tenant conservé: {tenant_id} ({other_orgs_count} autre(s) organisation(s))")
        
        # 8. Commit de toutes les suppressions
        db.commit()
        
        logger.info(f"🎉 Suppression complète réussie: {org_name} ({organization_id})")
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la suppression: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )


@router.patch("/{organization_id}/toggle-active", response_model=OrganizationResponse)
@audit_log(action="TOGGLE_ORGANIZATION_ACTIVE", resource_type="organization")
async def toggle_organization_active(
    organization_id: UUID,
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db)
):
    """
    Active ou désactive une organisation et tous ses utilisateurs

    Quand désactivée: tous les utilisateurs ne peuvent plus se connecter
    Quand réactivée: tous les utilisateurs peuvent à nouveau se connecter
    """
    # 🔒 Vérification des permissions
    _check_organization_permission(current_user, "update", db)

    is_super_admin = current_user.is_super_admin()

    logger.info(f"🔄 Toggle active pour: {organization_id} par {'super-admin' if is_super_admin else f'tenant: {current_user.tenant_id}'}")

    # 🔒 Récupérer l'organisation avec vérification tenant
    if is_super_admin:
        # Super-admin: peut toggle n'importe quelle organisation
        db_org = db.get(Organization, organization_id)
    else:
        # Utilisateur normal: uniquement son tenant
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        db_org = db.execute(
            select(Organization).where(
                Organization.id == organization_id,
                Organization.tenant_id == current_user.tenant_id
            )
        ).scalar_one_or_none()

    if not db_org:
        raise HTTPException(status_code=404, detail="Organisation non trouvée")
    
    new_status = not db_org.is_active
    db_org.is_active = new_status
    
    try:
        result = db.execute(
            text("UPDATE users SET is_active = :status WHERE default_org_id = :org_id RETURNING id"),
            {"status": new_status, "org_id": str(organization_id)}
        )
        
        updated_count = len(result.fetchall())
        db.commit()
        db.refresh(db_org)
        
        status_text = "activée" if new_status else "désactivée"
        logger.info(f"✅ Organisation {status_text}: {db_org.name}")
        logger.info(f"✅ {updated_count} utilisateur(s) {status_text}(s)")
        
        return db_org
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ENDPOINTS : Statistiques
# ============================================================================

@router.get("/stats/overview", response_model=OrganizationStats)
def get_organizations_overview(
    tenant_id: Optional[UUID] = Query(None, description="[Super-admin only] Filter par tenant spécifique"),
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db)
) -> "OrganizationStats":
    """
    Vue synthétique des organisations :
      - total_clients / active_clients / inactive_clients
      - total_users (somme workforce)
      - subscription_breakdown

    Super-admin: peut voir les stats globales ou filtrer par tenant_id
    Utilisateurs normaux: voient uniquement leur tenant
    """
    # 🔒 Vérification RBAC
    _check_organization_permission(current_user, "read", db)

    is_super_admin = current_user.is_super_admin()

    # Déterminer le tenant cible
    if is_super_admin:
        target_tenant_id = tenant_id  # None = tous les tenants, ou un tenant spécifique
    else:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        target_tenant_id = current_user.tenant_id

    # Construire les requêtes avec filtrage conditionnel
    base_filter = []
    if target_tenant_id:
        base_filter.append(Organization.tenant_id == target_tenant_id)

    # 🔒 Filtrage par tenant (conditionnel pour super-admin)
    total_clients = db.scalar(
        select(func.count(Organization.id)).where(*base_filter)
    ) or 0
    active_clients = (
        db.scalar(
            select(func.count(Organization.id)).where(
                Organization.is_active.is_(True),
                *base_filter
            )
        )
        or 0
    )
    inactive_clients = total_clients - active_clients

    # Répartition par type d'abonnement
    sub_query = select(Organization.subscription_type, func.count(Organization.id))
    if base_filter:
        sub_query = sub_query.where(*base_filter)
    sub_rows = db.execute(
        sub_query.group_by(Organization.subscription_type)
    ).all()
    counted = {(k or "starter"): v for (k, v) in sub_rows}
    subscription_breakdown = {
        "starter": counted.get("starter", 0),
        "professional": counted.get("professional", 0),
        "enterprise": counted.get("enterprise", 0),
    }

    # Total utilisateurs = somme workforce
    workforce_query = select(func.coalesce(func.sum(Organization.workforce), 0))
    if base_filter:
        workforce_query = workforce_query.where(*base_filter)
    total_users = db.scalar(workforce_query) or 0

    return {
        "total_clients": int(total_clients),
        "active_clients": int(active_clients),
        "inactive_clients": int(inactive_clients),
        "total_users": int(total_users),
        "subscription_breakdown": subscription_breakdown,
    }


@router.get("/stats/by-subscription")
async def get_stats_by_subscription(
    tenant_id: Optional[UUID] = Query(None, description="[Super-admin only] Filter par tenant spécifique"),
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db)
):
    """
    Statistiques par type d'abonnement.

    Super-admin: peut voir les stats globales ou filtrer par tenant_id
    Utilisateurs normaux: voient uniquement leur tenant
    """
    # 🔒 Vérification RBAC
    _check_organization_permission(current_user, "read", db)

    is_super_admin = current_user.is_super_admin()

    # Déterminer le tenant cible
    if is_super_admin:
        target_tenant_id = tenant_id  # None = tous les tenants, ou un tenant spécifique
    else:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        target_tenant_id = current_user.tenant_id

    # 🔒 Filtrage par tenant (conditionnel pour super-admin)
    query = select(
        Organization.subscription_type,
        func.count(Organization.id).label("total"),
        func.count(Organization.id)
        .filter(Organization.is_active.is_(True))
        .label("active"),
        func.coalesce(func.avg(Organization.workforce), 0).label("avg_employees"),
        func.coalesce(func.sum(Organization.workforce), 0).label("total_employees"),
    )

    if target_tenant_id:
        query = query.where(Organization.tenant_id == target_tenant_id)

    rows = db.execute(
        query.group_by(Organization.subscription_type)
    ).all()

    return [
        {
            "subscription_type": r.subscription_type,
            "total": r.total,
            "active": r.active,
            "inactive": r.total - r.active,
            "avg_employees": round(float(r.avg_employees), 1),
            "total_employees": int(r.total_employees),
        }
        for r in rows
    ]


@router.get("/stats/by-sector")
async def get_stats_by_sector(
    tenant_id: Optional[UUID] = Query(None, description="[Super-admin only] Filter par tenant spécifique"),
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db)
):
    """
    Top secteurs d'activité (libellé NAF, champ `activity`).

    Super-admin: peut voir les stats globales ou filtrer par tenant_id
    Utilisateurs normaux: voient uniquement leur tenant
    """
    # 🔒 Vérification RBAC
    _check_organization_permission(current_user, "read", db)

    is_super_admin = current_user.is_super_admin()

    # Déterminer le tenant cible
    if is_super_admin:
        target_tenant_id = tenant_id  # None = tous les tenants, ou un tenant spécifique
    else:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        target_tenant_id = current_user.tenant_id

    # 🔒 Filtrage par tenant (conditionnel pour super-admin)
    query = select(Organization.activity, func.count(Organization.id).label("count")).where(
        Organization.activity.isnot(None)
    )

    if target_tenant_id:
        query = query.where(Organization.tenant_id == target_tenant_id)

    rows = db.execute(
        query.group_by(Organization.activity)
        .order_by(func.count(Organization.id).desc())
        .limit(10)
    ).all()
    return [{"activity": r.activity, "count": r.count} for r in rows]


# ============================================================================
# ENDPOINTS : Recherche & Export
# ============================================================================

@router.get("/search")
async def search_organizations(
    q: str = Query(..., min_length=2, description="Terme de recherche"),
    limit: int = Query(10, ge=1, le=50),
    tenant_id: Optional[UUID] = Query(None, description="[Super-admin only] Filter par tenant spécifique"),
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db),
):
    """
    Recherche rapide d'organizations par nom/domaine/libellé NAF.

    Super-admin: peut rechercher dans tous les tenants ou filtrer par tenant_id
    Utilisateurs normaux: recherchent uniquement dans leur tenant
    """
    # 🔒 Vérification RBAC
    _check_organization_permission(current_user, "read", db)

    is_super_admin = current_user.is_super_admin()

    # Déterminer le tenant cible
    if is_super_admin:
        target_tenant_id = tenant_id  # None = tous les tenants, ou un tenant spécifique
    else:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        target_tenant_id = current_user.tenant_id

    sp = f"%{q.lower()}%"
    # 🔒 Filtrage par tenant (conditionnel pour super-admin)
    query = select(Organization).where(
        or_(
            func.lower(Organization.name).like(sp),
            func.lower(Organization.domain).like(sp),
            func.lower(Organization.naf_title).like(sp),
        )
    )

    if target_tenant_id:
        query = query.where(Organization.tenant_id == target_tenant_id)

    orgs = db.execute(query.limit(limit)).scalars().all()

    return [
        {
            "id": org.id,
            "name": org.name,
            "domain": org.domain,
            "subscription_type": org.subscription_type,
            "is_active": org.is_active,
        }
        for org in orgs
    ]


@router.get("/export")
async def export_organizations(
    format: str = Query("json", pattern="^(json|csv)$"),
    is_active: Optional[bool] = Query(None),
    subscription_type: Optional[str] = Query(None),
    tenant_id: Optional[UUID] = Query(None, description="[Super-admin only] Filter par tenant spécifique"),
    current_user: User = Depends(require_permission("ORGANIZATION_READ")),
    db: Session = Depends(get_db),
):
    """
    Export JSON/CSV des organizations (schéma courant).

    Super-admin: peut exporter toutes les organisations ou filtrer par tenant_id
    Utilisateurs normaux: exportent uniquement leur tenant
    """
    # 🔒 Vérification des permissions
    _check_organization_permission(current_user, "export", db)

    is_super_admin = current_user.is_super_admin()

    # Déterminer le tenant cible
    if is_super_admin:
        target_tenant_id = tenant_id  # None = tous les tenants, ou un tenant spécifique
    else:
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès interdit : utilisateur sans tenant"
            )
        target_tenant_id = current_user.tenant_id

    # 🔒 Filtrage par tenant (conditionnel pour super-admin)
    query = select(Organization)

    if target_tenant_id:
        query = query.where(Organization.tenant_id == target_tenant_id)

    if is_active is not None:
        query = query.where(Organization.is_active == is_active)
    if subscription_type:
        query = query.where(Organization.subscription_type == subscription_type)

    orgs = db.execute(query).scalars().all()

    if format == "json":
        from fastapi.responses import JSONResponse

        data = [
            OrganizationResponse.model_validate(o).model_dump(mode="json") for o in orgs
        ]
        return JSONResponse(content=data)

    # CSV
    import csv
    from io import StringIO
    from fastapi.responses import StreamingResponse

    output = StringIO()
    writer = csv.writer(output)

    headers = [
        "id",
        "name",
        "domain",
        "subscription_type",
        "email",
        "phone",
        "country_code",
        "category",
        "activity",
        "workforce",
        "siret",
        "naf",
        "naf_title",
        "is_active",
        "created_at",
        "updated_at",
    ]
    writer.writerow(headers)

    for o in orgs:
        writer.writerow(
            [
                str(o.id),
                o.name,
                o.domain or "",
                o.subscription_type or "",
                o.email or "",
                o.phone or "",
                o.country_code or "FR",
                o.category or "",
                o.activity or "",
                o.workforce or 0,
                o.siret or "",
                o.naf or "",
                o.naf_title or "",
                bool(o.is_active),
                o.created_at.isoformat() if o.created_at else "",
                o.updated_at.isoformat() if o.updated_at else "",
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=organizations_export.csv"},
    )