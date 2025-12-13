"""
API Admin pour la gestion des clients/organizations
VERSION CORRIGÉE - Création automatique de l'utilisateur admin avec rôle SUPER_ADMIN
"""
from typing import List, Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import Session
import secrets
import string
import hashlib

from src.database import get_db
from src.models.organization import Organization
from src.models.tenant import Tenant
from src.models.audit import User  # ✅ Import du modèle User
from src.schemas.organization import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationListResponse,
    OrganizationStats,
    TenantCreateData
)
from src.services.insee_service import get_insee_service
from src.utils.security import hash_password  # ✅ Import de la fonction de hachage
from src.utils.redis_manager import redis_manager  # ✅ Import Redis
from src.dependencies_keycloak import get_current_user_keycloak, require_role  # ✅ Keycloak auth

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Administration"])


# ============================================================================
# HELPERS
# ============================================================================

def generate_temp_password(length: int = 12) -> str:
    """Génère un mot de passe temporaire sécurisé"""
    alphabet = string.ascii_letters + string.digits + "!@#$%&"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ============================================================================
# ENDPOINTS : Organizations (Clients)
# ============================================================================

@router.get("/organizations", response_model=OrganizationListResponse)
async def list_organizations(
    is_active: Optional[bool] = Query(None),
    subscription_type: Optional[str] = Query(None),
    sector: Optional[str] = Query(None),
    size_category: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_role("SUPER_ADMIN")),
    db: Session = Depends(get_db)
):
    """Liste toutes les organizations avec filtres et pagination"""

    # ✅ Générer une clé de cache basée sur les paramètres et le code source
    import inspect
    source_code = inspect.getsource(list_organizations)
    source_hash = hashlib.md5(source_code.encode()).hexdigest()[:8]

    cache_params = f"active={is_active}_sub={subscription_type}_sector={sector}_size={size_category}_skip={skip}_limit={limit}"
    cache_key = f"admin:organizations:list:{cache_params}:v{source_hash}"

    # ✅ Tenter de récupérer depuis le cache
    if redis_manager.is_connected:
        cached = redis_manager.get(cache_key)
        if cached:
            logger.info(f"✅ Cache HIT pour liste organizations")
            return cached

    query = select(Organization)

    # Filtres
    if is_active is not None:
        query = query.where(Organization.is_active == is_active)

    if subscription_type:
        query = query.where(Organization.subscription_type == subscription_type)

    if sector:
        query = query.where(Organization.sector.ilike(f"%{sector}%"))

    if size_category:
        query = query.where(Organization.size_category == size_category)

    # Tri par date de création (plus récent en premier)
    query = query.order_by(Organization.created_at.desc())

    # Pagination
    query = query.offset(skip).limit(limit)

    # Exécution
    result = db.execute(query)
    organizations = result.scalars().all()

    # Count total
    count_query = select(func.count()).select_from(Organization)
    if is_active is not None:
        count_query = count_query.where(Organization.is_active == is_active)
    if subscription_type:
        count_query = count_query.where(Organization.subscription_type == subscription_type)
    total = db.execute(count_query).scalar()

    response_data = {
        "items": organizations,
        "total": total or 0,
        "skip": skip,
        "limit": limit
    }

    # ✅ Mettre en cache pour 5 minutes (300 secondes)
    if redis_manager.is_connected:
        redis_manager.set(cache_key, response_data, ttl=300)
        logger.info(f"✅ Mise en cache de la liste organizations")

    return response_data


@router.post("/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    organization: OrganizationCreate,
    create_tenant: bool = Query(True, description="Créer automatiquement un tenant associé"),
    admin_email: Optional[str] = Query(None, description="Email de l'utilisateur admin à créer"),
    admin_first_name: Optional[str] = Query(None, description="Prénom de l'admin"),
    admin_last_name: Optional[str] = Query(None, description="Nom de l'admin"),
    admin_password: Optional[str] = Query(None, description="Mot de passe admin (généré si absent)"),
    current_user: User = Depends(require_role("SUPER_ADMIN")),
    db: Session = Depends(get_db)
):
    """
    Crée une nouvelle organization (client) avec tenant et utilisateur admin
    
    Si create_tenant=True, un tenant sera automatiquement créé et associé.
    Si admin_email est fourni, un utilisateur admin sera créé automatiquement avec le rôle SUPER_ADMIN.
    """
    org_data = organization.model_dump()
    
    # ============================================================================
    # ÉTAPE 1 : Créer le tenant
    # ============================================================================
    tenant_id = None
    if create_tenant:
        tenant_data = TenantCreateData(
            name=organization.name,
            subscription_type=organization.subscription_type,
            max_users=50 if organization.subscription_type == "enterprise" else 20 if organization.subscription_type == "professional" else 5,
            max_organizations=1
        )
        
        db_tenant = Tenant(
            id=uuid4(),
            **tenant_data.model_dump()
        )
        
        db.add(db_tenant)
        db.flush()  # Pour obtenir l'ID
        tenant_id = db_tenant.id
        
        logger.info(f"✓ Tenant créé: {db_tenant.name} ({db_tenant.id})")
    
    # ============================================================================
    # ÉTAPE 2 : Créer l'organisation
    # ============================================================================
    
    # Vérifier que le nom n'existe pas déjà
    existing_org = db.execute(
        select(Organization).where(Organization.name == organization.name)
    ).scalar_one_or_none()
    
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Une organisation avec le nom '{organization.name}' existe déjà"
        )
    
    # Préparer les données de l'organisation
    # Retirer les champs INSEE qui ne sont pas dans le modèle Organization
    insee_fields = ['siret', 'siren', 'ape_code', 'address_line1', 'postal_code', 'city']
    org_create_data = {k: v for k, v in org_data.items() if k not in insee_fields}
    
    # Ajouter le tenant_id
    org_create_data['tenant_id'] = tenant_id
    
    # Créer l'organisation
    db_org = Organization(**org_create_data)
    
    db.add(db_org)
    db.flush()  # ✅ Important : flush pour avoir l'ID avant de créer l'admin
    
    logger.info(f"✓ Organisation créée: {db_org.name} ({db_org.id})")
    
    # ============================================================================
    # ÉTAPE 3 : Créer l'utilisateur admin (si email fourni)
    # ============================================================================
    if admin_email and tenant_id:
        # Vérifier que l'email n'existe pas
        existing_user = db.execute(
            select(User).where(User.email == admin_email)
        ).scalar_one_or_none()
        
        if existing_user:
            logger.warning(f"⚠️ Email admin déjà utilisé: {admin_email}, utilisateur existant associé")
            admin_user = existing_user
        else:
            # Générer un mot de passe si non fourni
            password = admin_password if admin_password else generate_temp_password()
            
            # Créer l'utilisateur admin
            admin_user = User(
                id=uuid4(),
                email=admin_email,
                first_name=admin_first_name or "Admin",
                last_name=admin_last_name or organization.name,
                password_hash=hash_password(password),
                tenant_id=tenant_id,
                default_org_id=db_org.id,
                is_active=True,
                is_email_verified=False
            )
            
            db.add(admin_user)
            db.flush()  # Pour avoir l'ID
            
            logger.info(f"✓ Utilisateur admin créé: {admin_user.email} ({admin_user.id})")
            
            if not admin_password:
                logger.info(f"🔑 Mot de passe temporaire généré: {password}")
        
        # ============================================================================
        # ÉTAPE 4 : Créer le rôle SUPER_ADMIN dans user_organization_role
        # ============================================================================
        from sqlalchemy import text
        
        # Créer directement l'entrée dans user_organization_role
        insert_role_sql = text("""
            INSERT INTO user_organization_role (id, user_id, organization_id, role, is_active, permissions, created_at)
            VALUES (:id, :user_id, :org_id, :role, :is_active, :permissions, NOW())
            ON CONFLICT DO NOTHING
        """)
        
        db.execute(insert_role_sql, {
            "id": str(uuid4()),
            "user_id": str(admin_user.id),
            "org_id": str(db_org.id),
            "role": "SUPER_ADMIN",
            "is_active": True,
            "permissions": '{"can_manage_users": true, "can_manage_org": true, "can_view_all": true}'
        })
        
        logger.info(f"✓ Rôle SUPER_ADMIN assigné à {admin_user.email} pour l'organisation {db_org.name}")
    
    # ============================================================================
    # COMMIT FINAL
    # ============================================================================
    db.commit()
    db.refresh(db_org)

    # ✅ Invalider le cache des organizations
    if redis_manager.is_connected:
        redis_manager.delete_pattern("admin:organizations:list:*")
        logger.info(f"✅ Cache organizations invalidé après création")

    logger.info(f"✅ Client complet créé: {db_org.name} avec admin {admin_email if admin_email else 'sans admin'}")

    return db_org


@router.get("/organizations/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    current_user: User = Depends(require_role("SUPER_ADMIN")),
    db: Session = Depends(get_db)
):
    """Récupère une organization par son ID avec statistiques"""
    
    organization = db.get(Organization, organization_id)
    
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation non trouvée"
        )
    
    return organization


@router.patch("/organizations/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    organization_update: OrganizationUpdate,
    current_user: User = Depends(require_role("SUPER_ADMIN")),
    db: Session = Depends(get_db)
):
    """Met à jour une organization"""
    
    db_org = db.get(Organization, organization_id)
    
    if not db_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation non trouvée"
        )
    
    # Vérifier l'unicité du nom si il est modifié
    if organization_update.name and organization_update.name != db_org.name:
        existing_org = db.execute(
            select(Organization).where(
                and_(
                    Organization.name == organization_update.name,
                    Organization.id != organization_id
                )
            )
        ).scalar_one_or_none()
        
        if existing_org:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Une organisation avec le nom '{organization_update.name}' existe déjà"
            )
    
    # Mettre à jour les champs
    update_data = organization_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_org, field, value)

    db.commit()
    db.refresh(db_org)

    # ✅ Invalider le cache des organizations
    if redis_manager.is_connected:
        redis_manager.delete_pattern("admin:organizations:list:*")
        logger.info(f"✅ Cache organizations invalidé après mise à jour")

    logger.info(f"✓ Organisation mise à jour: {db_org.name} ({db_org.id})")
    return db_org


@router.delete("/organizations/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    force: bool = Query(False, description="Forcer la suppression même si l'organisation a des données"),
    delete_tenant: bool = Query(False, description="Supprimer aussi le tenant associé"),
    current_user: User = Depends(require_role("SUPER_ADMIN")),
    db: Session = Depends(get_db)
):
    """
    Supprime une organization
    """
    
    db_org = db.get(Organization, organization_id)
    
    if not db_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation non trouvée"
        )
    
    tenant_id = db_org.tenant_id
    
    # Supprimer l'organisation
    db.delete(db_org)

    # Supprimer le tenant si demandé
    if delete_tenant and tenant_id:
        tenant = db.get(Tenant, tenant_id)
        if tenant:
            db.delete(tenant)
            logger.info(f"✓ Tenant supprimé: {tenant_id}")

    db.commit()

    # ✅ Invalider le cache des organizations
    if redis_manager.is_connected:
        redis_manager.delete_pattern("admin:organizations:list:*")
        logger.info(f"✅ Cache organizations invalidé après suppression")

    logger.info(f"✓ Organisation supprimée: {organization_id}")


@router.post("/organizations/{organization_id}/activate", response_model=OrganizationResponse)
async def activate_organization(
    organization_id: UUID,
    current_user: User = Depends(require_role("SUPER_ADMIN")),
    db: Session = Depends(get_db)
):
    """Active une organization"""
    
    db_org = db.get(Organization, organization_id)
    
    if not db_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation non trouvée"
        )
    
    db_org.is_active = True
    
    # ✅ Activer également le tenant associé
    if db_org.tenant_id:
        tenant = db.get(Tenant, db_org.tenant_id)
        if tenant and not tenant.is_active:
            tenant.is_active = True
            logger.info(f"✓ Tenant activé: {tenant.name}")

    db.commit()
    db.refresh(db_org)

    # ✅ Invalider le cache des organizations
    if redis_manager.is_connected:
        redis_manager.delete_pattern("admin:organizations:list:*")
        logger.info(f"✅ Cache organizations invalidé après activation")

    logger.info(f"✓ Organisation activée: {db_org.name}")
    return db_org


@router.post("/organizations/{organization_id}/deactivate", response_model=OrganizationResponse)
async def deactivate_organization(
    organization_id: UUID,
    current_user: User = Depends(require_role("SUPER_ADMIN")),
    db: Session = Depends(get_db)
):
    """Désactive une organization"""
    
    db_org = db.get(Organization, organization_id)
    
    if not db_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation non trouvée"
        )
    
    db_org.is_active = False

    # ✅ Désactiver également le tenant associé pour bloquer les connexions
    if db_org.tenant_id:
        tenant = db.get(Tenant, db_org.tenant_id)
        if tenant and tenant.is_active:
            tenant.is_active = False
            logger.info(f"✓ Tenant désactivé: {tenant.name}")

    db.commit()
    db.refresh(db_org)

    # ✅ Invalider le cache des organizations
    if redis_manager.is_connected:
        redis_manager.delete_pattern("admin:organizations:list:*")
        logger.info(f"✅ Cache organizations invalidé après désactivation")

    logger.info(f"✓ Organisation désactivée: {db_org.name}")
    return db_org


# ============================================================================
# ENDPOINTS : Statistiques
# ============================================================================

@router.get("/organizations/stats/overview", response_model=OrganizationStats)
async def get_organizations_stats(
    current_user: User = Depends(require_role("SUPER_ADMIN")),
    db: Session = Depends(get_db)
):
    """Récupère les statistiques globales des organizations"""
    
    # Total organizations
    total_clients = db.scalar(
        select(func.count(Organization.id))
    ) or 0
    
    # Organizations actives
    active_clients = db.scalar(
        select(func.count(Organization.id))
        .where(Organization.is_active == True)
    ) or 0
    
    # Organizations inactives
    inactive_clients = total_clients - active_clients
    
    # Répartition par type d'abonnement
    subscription_breakdown = {}
    for sub_type in ['starter', 'professional', 'enterprise']:
        count = db.scalar(
            select(func.count(Organization.id))
            .where(Organization.subscription_type == sub_type)
        ) or 0
        subscription_breakdown[sub_type] = count
    
    # Total utilisateurs
    total_users = db.scalar(select(func.count(User.id))) or 0
    
    return {
        "total_clients": total_clients,
        "active_clients": active_clients,
        "inactive_clients": inactive_clients,
        "total_users": total_users,
        "subscription_breakdown": subscription_breakdown
    }