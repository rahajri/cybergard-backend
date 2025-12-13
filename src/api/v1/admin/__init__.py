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
from src.services.keycloak_service import get_keycloak_service  # ✅ Import du service Keycloak
from src.utils.security import hash_password  # ✅ Import de la fonction de hachage
from src.api.v1.user_management import generate_activation_token  # ✅ Import de la génération de token
from src.api.v1.admin.organizations import _legacy_to_current_payload  # ✅ Import du helper
from src.services.email_service import send_client_admin_creation_email  # ✅ Import de l'envoi d'email
import os

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
    db: Session = Depends(get_db)
):
    """Liste toutes les organizations avec filtres et pagination"""
    
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
    
    return {
        "items": organizations,
        "total": total or 0,
        "skip": skip,
        "limit": limit
    }


@router.post("/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    organization: OrganizationCreate,
    create_tenant: bool = Query(True, description="Créer automatiquement un tenant associé"),
    admin_email: Optional[str] = Query(None, description="Email de l'utilisateur admin à créer"),
    admin_first_name: Optional[str] = Query(None, description="Prénom de l'admin"),
    admin_last_name: Optional[str] = Query(None, description="Nom de l'admin"),
    admin_password: Optional[str] = Query(None, description="Mot de passe admin (généré si absent)"),
    db: Session = Depends(get_db)
):
    """
    Crée une nouvelle organization (client) avec tenant et utilisateur admin
    
    Si create_tenant=True, un tenant sera automatiquement créé et associé.
    Si admin_email est fourni, un utilisateur admin sera créé automatiquement avec le rôle SUPER_ADMIN.
    """
    # 🔍 DEBUG: Afficher les paramètres reçus
    logger.info(f"🔍 Création organisation - Paramètres admin:")
    logger.info(f"  - admin_email: {admin_email}")
    logger.info(f"  - admin_first_name: {admin_first_name}")
    logger.info(f"  - admin_last_name: {admin_last_name}")
    logger.info(f"  - admin_password fourni: {bool(admin_password)}")

    org_data = organization.model_dump()

    # ✅ IMPORTANT: Appliquer le mapping des champs legacy (sector → activity, etc.)
    org_data = _legacy_to_current_payload(org_data)

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
    # _legacy_to_current_payload a déjà retiré les champs INSEE et les a mis dans insee_data
    org_create_data = org_data.copy()

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
            # ÉTAPE 3.1 : Créer l'utilisateur dans Keycloak
            # ============================================================================
            try:
                keycloak_service = get_keycloak_service()

                # Obtenir un token admin
                admin_token = await keycloak_service.get_admin_token()
                if not admin_token:
                    logger.error("❌ Impossible d'obtenir un token admin Keycloak")
                    raise Exception("Erreur lors de la communication avec Keycloak")

                # Préparer les données utilisateur pour Keycloak
                keycloak_user_data = {
                    "username": admin_email,
                    "email": admin_email,
                    "firstName": admin_first_name or "Admin",
                    "lastName": admin_last_name or organization.name,
                    "enabled": False,  # Désactivé jusqu'à l'activation
                    "emailVerified": False,  # Email non vérifié jusqu'à l'activation
                    "attributes": {
                        "tenant_id": [str(tenant_id)],
                        "organization_id": [str(db_org.id)],
                        "user_id": [str(admin_user.id)]  # ID PostgreSQL pour référence
                    }
                }

                # Créer l'utilisateur dans Keycloak
                keycloak_user_id = await keycloak_service.create_user(admin_token, keycloak_user_data)

                if not keycloak_user_id:
                    logger.error(f"❌ Échec de la création de l'utilisateur dans Keycloak: {admin_email}")
                    # Rollback la transaction PostgreSQL
                    db.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Erreur lors de la création du compte dans le système d'authentification"
                    )

                # Sauvegarder le keycloak_id dans PostgreSQL
                admin_user.keycloak_id = keycloak_user_id
                db.flush()

                logger.info(f"✅ Utilisateur créé dans Keycloak: {keycloak_user_id}")

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"❌ Erreur lors de la création Keycloak: {e}")
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erreur lors de la création du compte: {str(e)}"
                )

            # ============================================================================
            # ÉTAPE 3.5 : Envoyer l'email d'activation au nouvel admin
            # ============================================================================
            try:
                from datetime import datetime, timedelta
                from sqlalchemy import text

                # Créer le token d'activation
                activation_token = generate_activation_token()
                token_expires = datetime.utcnow() + timedelta(days=7)

                # Sauvegarder le token dans la base de données
                insert_token_sql = text("""
                    INSERT INTO activation_tokens (
                        id, user_id, token, expires_at, is_used, created_at
                    )
                    VALUES (
                        gen_random_uuid(), :user_id, :token, :expires_at, false, CURRENT_TIMESTAMP
                    )
                """)

                db.execute(insert_token_sql, {
                    "user_id": str(admin_user.id),
                    "token": activation_token,
                    "expires_at": token_expires
                })

                logger.info(f"✅ Token d'activation sauvegardé (expire: {token_expires})")

                # Construire l'URL d'activation
                frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
                activation_url = f"{frontend_url}/activate-account?token={activation_token}"

                # Envoyer l'email avec ou sans mot de passe temporaire
                send_client_admin_creation_email(
                    to_email=admin_user.email,
                    user_name=f"{admin_user.first_name} {admin_user.last_name}",
                    organization_name=organization.name,
                    activation_url=activation_url,
                    temp_password=password if not admin_password else None
                )

                logger.info(f"✅ Email d'activation envoyé à {admin_user.email}")
            except Exception as e:
                logger.error(f"⚠️ Erreur lors de l'envoi de l'email d'activation: {e}")
                # Ne pas bloquer la création du client si l'email échoue
                # L'admin peut toujours activer son compte manuellement

        # ============================================================================
        # ÉTAPE 4 : Créer le rôle ADMIN dans user_organization_role
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
            "role": "ADMIN",
            "is_active": True,
            "permissions": '{"can_manage_users": true, "can_manage_org": true, "can_view_all": true}'
        })

        logger.info(f"✓ Rôle ADMIN assigné à {admin_user.email} pour l'organisation {db_org.name}")
    
    # ============================================================================
    # COMMIT FINAL
    # ============================================================================
    db.commit()
    db.refresh(db_org)
    
    logger.info(f"✅ Client complet créé: {db_org.name} avec admin {admin_email if admin_email else 'sans admin'}")
    
    return db_org


@router.get("/organizations/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
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

    # Vérifier si le statut is_active change
    status_changed = 'is_active' in update_data and update_data['is_active'] != db_org.is_active
    old_status = db_org.is_active
    new_status = update_data.get('is_active', old_status)

    for field, value in update_data.items():
        setattr(db_org, field, value)

    # Si le statut change, désactiver/réactiver tous les utilisateurs du tenant
    if status_changed and db_org.tenant_id:
        from sqlalchemy import text

        if new_status == False:
            # Désactiver tous les utilisateurs du tenant
            result = db.execute(
                text("""
                    UPDATE users
                    SET is_active = false, updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                    RETURNING id
                """),
                {"tenant_id": str(db_org.tenant_id)}
            )
            user_count = len(result.fetchall())
            logger.warning(f"⚠️ Organisation {db_org.name} désactivée → {user_count} utilisateur(s) désactivé(s)")
        else:
            # Réactiver tous les utilisateurs du tenant
            result = db.execute(
                text("""
                    UPDATE users
                    SET is_active = true, updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                    RETURNING id
                """),
                {"tenant_id": str(db_org.tenant_id)}
            )
            user_count = len(result.fetchall())
            logger.info(f"✅ Organisation {db_org.name} activée → {user_count} utilisateur(s) réactivé(s)")

    db.commit()
    db.refresh(db_org)

    logger.info(f"✓ Organisation mise à jour: {db_org.name} ({db_org.id})")
    return db_org


@router.delete("/organizations/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    force: bool = Query(False, description="Forcer la suppression même si l'organisation a des données"),
    delete_tenant: bool = Query(False, description="Supprimer aussi le tenant associé"),
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
    
    logger.info(f"✓ Organisation supprimée: {organization_id}")


@router.post("/organizations/{organization_id}/activate", response_model=OrganizationResponse)
async def activate_organization(
    organization_id: UUID,
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
    
    logger.info(f"✓ Organisation activée: {db_org.name}")
    return db_org


@router.post("/organizations/{organization_id}/deactivate", response_model=OrganizationResponse)
async def deactivate_organization(
    organization_id: UUID,
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
    
    logger.info(f"✓ Organisation désactivée: {db_org.name}")
    return db_org


# ============================================================================
# ENDPOINTS : Statistiques
# ============================================================================

@router.get("/organizations/stats/overview", response_model=OrganizationStats)
async def get_organizations_stats(
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