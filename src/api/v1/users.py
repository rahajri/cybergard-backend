# backend/src/api/v1/users.py
"""
API FastAPI pour la gestion des utilisateurs admin
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from src.utils.security import hash_password, verify_password
from src.dependencies import get_current_user
from src.dependencies_keycloak import require_permission
from src.database import get_db
from src.utils.redis_manager import cache_result, redis_manager
from src.services.keycloak_service import KeycloakService, get_keycloak_service

# ✅ CORRECTION : Import depuis models.__init__ qui re-exporte User depuis audit.py
from src.models import User
from src.models.tenant import Tenant

from src.schemas.user import (
    UserRole,
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    UserUpdatePassword,
)

import logging

logger = logging.getLogger(__name__)

# ✅ Initialiser le router
router = APIRouter(tags=["Users"])


# ============================================================================
# ENDPOINTS : CRUD Utilisateurs
# ============================================================================

@router.get("/", response_model=UserListResponse)
@cache_result(
    ttl=300,  # Cache de 5 minutes
    key_prefix="users:list",
    include_args=True,
    version_sensitive=True
)
async def list_users(
    tenant_id: Optional[UUID] = Query(None, description="Filtrer par tenant"),
    role: Optional[UserRole] = Query(None, description="Filtrer par rôle"),
    is_active: Optional[bool] = Query(None, description="Filtrer par statut"),
    search: Optional[str] = Query(None, description="Recherche par nom ou email"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_permission("USERS_READ")),
    db: Session = Depends(get_db),
):
    """Liste tous les utilisateurs avec filtres"""

    query = select(User)
    
    # Filtres
    if tenant_id:
        query = query.where(User.tenant_id == tenant_id)
    
    if role:
        query = query.where(User.role == role)
    
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    
    if search:
        sp = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(User.email).like(sp),
                func.lower(User.first_name).like(sp),
                func.lower(User.last_name).like(sp),
            )
        )
    
    # Tri et pagination
    query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
    users = db.execute(query).scalars().all()
    
    # Total
    count_q = select(func.count()).select_from(User)
    if tenant_id:
        count_q = count_q.where(User.tenant_id == tenant_id)
    if role:
        count_q = count_q.where(User.role == role)
    if is_active is not None:
        count_q = count_q.where(User.is_active == is_active)
    if search:
        sp = f"%{search.lower()}%"
        count_q = count_q.where(
            or_(
                func.lower(User.email).like(sp),
                func.lower(User.first_name).like(sp),
                func.lower(User.last_name).like(sp),
            )
        )
    total = db.execute(count_q).scalar() or 0

    logger.info(f"✅ {len(users)} utilisateur(s) récupéré(s) (tenant={tenant_id}, role={role}, is_active={is_active})")

    return {"items": users, "total": total, "skip": skip, "limit": limit}


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    current_user: User = Depends(require_permission("USERS_CREATE")),
    db: Session = Depends(get_db),
    keycloak: KeycloakService = Depends(get_keycloak_service),
):
    """
    Crée un nouvel utilisateur dans PostgreSQL ET Keycloak
    """
    from src.models.role import Role, user_role as user_role_table
    from datetime import datetime, timezone

    # Vérifier que l'email n'existe pas déjà
    existing_user = db.execute(
        select(User).where(User.email == user.email)
    ).scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un utilisateur avec l'email '{user.email}' existe déjà"
        )

    # Vérifier que le tenant existe
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {user.tenant_id} non trouvé"
        )

    # Vérifier les limites du tenant
    current_users_count = db.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == user.tenant_id)
    ) or 0

    if current_users_count >= tenant.max_users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Limite d'utilisateurs atteinte pour ce tenant ({tenant.max_users} max)"
        )

    # 1. Créer l'utilisateur dans Keycloak
    try:
        # Obtenir le token admin
        admin_token = await keycloak.get_admin_token()

        # Créer l'utilisateur dans Keycloak
        keycloak_user_id = await keycloak.create_user(
            admin_token=admin_token,
            user_data={
                "email": user.email,
                "firstName": user.first_name,
                "lastName": user.last_name,
                "enabled": user.is_active,
                "emailVerified": False,
                "credentials": [{
                    "type": "password",
                    "value": user.password,
                    "temporary": False
                }]
            }
        )

        logger.info(f"✓ Utilisateur créé dans Keycloak: {user.email} (ID: {keycloak_user_id})")

        # 2. Assigner le rôle dans Keycloak (si fourni)
        if user.role:
            # Normaliser le nom du rôle pour Keycloak (minuscules)
            keycloak_role_name = user.role.lower()

            try:
                await keycloak.assign_role_to_user(
                    admin_token=admin_token,
                    user_id=keycloak_user_id,
                    role_name=keycloak_role_name
                )
                logger.info(f"✓ Rôle '{keycloak_role_name}' assigné dans Keycloak")
            except Exception as role_error:
                logger.warning(f"⚠️ Erreur assignation rôle Keycloak: {role_error}")
                # Ne pas bloquer la création si le rôle n'existe pas dans Keycloak

    except Exception as e:
        logger.error(f"❌ Erreur création Keycloak: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création dans Keycloak: {str(e)}"
        )

    # 3. Créer l'utilisateur en BDD
    db_user = User(
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        is_active=user.is_active,
        tenant_id=user.tenant_id,
        password_hash=hash_password(user.password),
        keycloak_id=keycloak_user_id
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # 4. Assigner le rôle dans user_role (si fourni)
    if user.role:
        # Récupérer le rôle depuis la table role
        role_obj = db.execute(
            select(Role).where(Role.code == user.role)
        ).scalar_one_or_none()

        if role_obj:
            # Insérer dans user_role
            db.execute(
                user_role_table.insert().values(
                    user_id=db_user.id,
                    role_id=role_obj.id,
                    assigned_at=datetime.now(timezone.utc),
                    assigned_by=db_user.id  # Self-assigned lors de la création
                )
            )
            db.commit()
            logger.info(f"✓ Rôle '{user.role}' assigné en BDD")
        else:
            logger.warning(f"⚠️ Rôle '{user.role}' non trouvé en BDD")

    # Invalider le cache des utilisateurs
    redis_manager.delete_pattern("users:*")

    logger.info(f"✓ Utilisateur créé: {db_user.email} ({db_user.id})")
    return db_user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(require_permission("USERS_READ")),
    db: Session = Depends(get_db)
):
    """Récupère un utilisateur par son ID"""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_update: UserUpdate,
    current_user: User = Depends(require_permission("USERS_UPDATE")),
    db: Session = Depends(get_db),
):
    """Met à jour un utilisateur"""
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    # Vérifier l'unicité de l'email si modifié
    if user_update.email and user_update.email != db_user.email:
        conflict = db.execute(
            select(User).where(
                User.email == user_update.email,
                User.id != user_id
            )
        ).scalar_one_or_none()
        
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Un utilisateur avec l'email '{user_update.email}' existe déjà"
            )
    
    # Mettre à jour les champs
    update_data = user_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_user, field, value)
    
    db.commit()
    db.refresh(db_user)

    # Invalider le cache des utilisateurs
    redis_manager.delete_pattern("users:*")

    logger.info(f"✓ Utilisateur mis à jour: {db_user.email}")
    return db_user


@router.patch("/{user_id}/password", response_model=UserResponse)
async def update_user_password(
    user_id: UUID,
    password_update: UserUpdatePassword,
    current_user: User = Depends(require_permission("USERS_UPDATE")),
    db: Session = Depends(get_db),
):
    """Change le mot de passe d'un utilisateur"""
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    # Vérifier l'ancien mot de passe
    if not verify_password(password_update.old_password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe actuel incorrect"
        )
    
    # Mettre à jour le mot de passe
    db_user.password_hash = hash_password(password_update.new_password)
    db.commit()
    db.refresh(db_user)

    # Invalider le cache des utilisateurs (optionnel pour password mais cohérent)
    redis_manager.delete_pattern("users:*")

    logger.info(f"✓ Mot de passe changé: {db_user.email}")
    return db_user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    force: bool = Query(False, description="Force la suppression"),
    current_user: User = Depends(require_permission("USERS_DELETE")),
    db: Session = Depends(get_db),
):
    """Supprime un utilisateur"""
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    # Empêcher la suppression des super admins sans force
    if db_user.role == UserRole.SUPER_ADMIN and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de supprimer un super admin sans force=true"
        )
    
    db.delete(db_user)
    db.commit()

    # Invalider le cache des utilisateurs
    redis_manager.delete_pattern("users:*")

    logger.info(f"✓ Utilisateur supprimé: {user_id}")


@router.post("/{user_id}/toggle-status", response_model=UserResponse)
async def toggle_user_status(
    user_id: UUID,
    current_user: User = Depends(require_permission("USERS_UPDATE")),
    db: Session = Depends(get_db)
):
    """Active/désactive un utilisateur"""
    db_user = db.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    db_user.is_active = not db_user.is_active
    db.commit()
    db.refresh(db_user)

    # Invalider le cache des utilisateurs
    redis_manager.delete_pattern("users:*")

    logger.info(f"✓ Statut utilisateur basculé: {db_user.email}")
    return db_user


# ============================================================================
# ENDPOINTS : Gestion par Tenant
# ============================================================================

@router.get("/tenant/{tenant_id}/admins", response_model=UserListResponse)
async def get_tenant_admins(
    tenant_id: UUID,
    current_user: User = Depends(require_permission("USERS_READ")),
    db: Session = Depends(get_db)
):
    """Liste tous les admins d'un tenant"""
    
    # Vérifier que le tenant existe
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )
    
    # Récupérer les admins
    query = select(User).where(
        User.tenant_id == tenant_id,
        User.role.in_([UserRole.TENANT_ADMIN, UserRole.ORG_ADMIN])
    ).order_by(User.created_at.desc())
    
    users = db.execute(query).scalars().all()
    total = len(users)
    
    return {"items": users, "total": total, "skip": 0, "limit": total}


@router.get("/tenant/{tenant_id}/stats")
async def get_tenant_user_stats(
    tenant_id: UUID,
    current_user: User = Depends(require_permission("USERS_READ")),
    db: Session = Depends(get_db)
):
    """Statistiques des utilisateurs d'un tenant"""
    
    # Vérifier que le tenant existe
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )
    
    # Compter les utilisateurs
    total_users = db.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
    ) or 0
    
    active_users = db.scalar(
        select(func.count()).select_from(User).where(
            User.tenant_id == tenant_id,
            User.is_active == True
        )
    ) or 0
    
    # Répartition par rôle
    role_rows = db.execute(
        select(User.role, func.count(User.id))
        .where(User.tenant_id == tenant_id)
        .group_by(User.role)
    ).all()
    
    role_breakdown = {str(role): count for role, count in role_rows}
    
    return {
        "tenant_id": tenant_id,
        "tenant_name": tenant.name,
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": total_users - active_users,
        "max_users": tenant.max_users,
        "remaining_slots": tenant.max_users - total_users,
        "role_breakdown": role_breakdown,
    }

@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Récupère les informations de l'utilisateur actuellement connecté.
    
    Cette route est utilisée par le frontend pour charger les informations
    de l'utilisateur, notamment son organization_id et tenant_id.
    
    Authentification requise via JWT (header Authorization ou cookie access_token).
    
    Returns:
        dict: Informations de l'utilisateur incluant organization_id
    
    Example:
        GET /api/v1/users/me
        Authorization: Bearer <token>
        
        Réponse:
        {
          "id": "...",
          "email": "user@example.com",
          "organization_id": "bf787e86-7df2-4a0d-b24f-88fe54a618dd",
          "organization_name": "Vision Agile",
          "tenant_id": "a7f8ab96-1acb-4f01-a6d7-9cdee2ec2ce0",
          ...
        }
    """
    
    logger.info(f"📊 Requête /me pour utilisateur: {current_user.email}")
    
    # Récupérer l'organisation de l'utilisateur
    organization_id = None
    organization_name = None
    
    if current_user.default_org_id:
        from src.models.organization import Organization
        from sqlalchemy import select
        
        org = db.execute(
            select(Organization).where(Organization.id == current_user.default_org_id)
        ).scalar_one_or_none()
        
        if org:
            organization_id = str(org.id)
            organization_name = org.name
            logger.info(f"✅ Organisation trouvée: {organization_name} ({organization_id})")
        else:
            logger.warning(f"⚠️ Organisation {current_user.default_org_id} non trouvée en base")
    else:
        logger.warning(f"⚠️ Utilisateur {current_user.email} n'a pas de default_org_id")
    
    response = {
        "id": str(current_user.id),
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role,
        "organization_id": organization_id,  # ✅ CLEF IMPORTANTE !
        "organization_name": organization_name,
        "tenant_id": str(current_user.tenant_id) if current_user.tenant_id else None,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "updated_at": current_user.updated_at.isoformat() if current_user.updated_at else None,
    }
    
    logger.info(f"✅ Réponse /me: organization_id={organization_id}")
    return response


@router.get("/count/by-organization/{organization_id}")
async def count_users_by_organization(
    organization_id: UUID,
    current_user: User = Depends(require_permission("USERS_READ")),
    db: Session = Depends(get_db)
):
    """
    Compte le nombre d'utilisateurs pour une organisation donnée

    Args:
        organization_id: ID de l'organisation

    Returns:
        dict: Nombre total d'utilisateurs et nombre d'utilisateurs actifs
    """
    from src.models.organization import Organization
    from sqlalchemy import text

    # Vérifier que l'organisation existe
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organisation {organization_id} non trouvée"
        )

    # Récupérer le tenant_id de l'organisation
    if not org.tenant_id:
        logger.warning(f"⚠️ Organisation {organization_id} sans tenant_id")
        return {
            "organization_id": str(organization_id),
            "organization_name": org.name,
            "total": 0,
            "active": 0,
            "inactive": 0
        }

    # Compter les utilisateurs par tenant_id
    total_count = db.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == org.tenant_id)
    ) or 0

    active_count = db.scalar(
        select(func.count()).select_from(User).where(
            User.tenant_id == org.tenant_id,
            User.is_active == True
        )
    ) or 0

    logger.info(f"📊 Organisation {org.name}: {total_count} utilisateurs ({active_count} actifs)")

    return {
        "organization_id": str(organization_id),
        "organization_name": org.name,
        "tenant_id": str(org.tenant_id),
        "total": total_count,
        "active": active_count,
        "inactive": total_count - active_count
    }


"""
Template d'email HTML pour l'activation de compte utilisateur
À utiliser dans le backend pour envoyer les emails d'invitation
"""

def get_activation_email_template(
    user_name: str,
    activation_link: str,
    organization_name: str,
    sender_name: str
) -> dict:
    """
    Génère le contenu HTML de l'email d'activation
    
    Args:
        user_name: Prénom et nom de l'utilisateur
        activation_link: Lien complet d'activation (avec token)
        organization_name: Nom de l'organisation
        sender_name: Nom de la personne qui a invité l'utilisateur
    
    Returns:
        dict avec 'subject', 'html_body' et 'text_body'
    """
    
    html_body = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Activez votre compte CYBERGARD AI</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #f3f4f6;
            line-height: 1.6;
        }}
        .email-container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
        }}
        .header {{
            background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
            padding: 40px 30px;
            text-align: center;
        }}
        .logo {{
            width: 60px;
            height: 60px;
            background-color: rgba(255, 255, 255, 0.2);
            border-radius: 16px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 20px;
        }}
        .logo svg {{
            width: 36px;
            height: 36px;
            color: white;
        }}
        .header h1 {{
            color: #ffffff;
            font-size: 28px;
            font-weight: 700;
            margin: 0;
            letter-spacing: -0.5px;
        }}
        .header p {{
            color: rgba(255, 255, 255, 0.9);
            font-size: 16px;
            margin: 10px 0 0 0;
        }}
        .content {{
            padding: 40px 30px;
            color: #374151;
        }}
        .greeting {{
            font-size: 18px;
            font-weight: 600;
            color: #111827;
            margin-bottom: 20px;
        }}
        .message {{
            font-size: 15px;
            color: #4b5563;
            margin-bottom: 30px;
            line-height: 1.7;
        }}
        .info-box {{
            background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
            border-left: 4px solid #3b82f6;
            padding: 20px;
            border-radius: 8px;
            margin: 30px 0;
        }}
        .info-box p {{
            margin: 0;
            color: #1e40af;
            font-size: 14px;
            line-height: 1.6;
        }}
        .info-box strong {{
            color: #1e3a8a;
            display: block;
            margin-bottom: 8px;
            font-size: 15px;
        }}
        .cta-button {{
            display: inline-block;
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
            color: #ffffff !important;
            text-decoration: none;
            padding: 16px 40px;
            border-radius: 10px;
            font-weight: 600;
            font-size: 16px;
            margin: 20px 0;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
            transition: all 0.3s;
        }}
        .cta-button:hover {{
            box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4);
            transform: translateY(-1px);
        }}
        .alternative-link {{
            background-color: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 15px;
            margin: 30px 0;
        }}
        .alternative-link p {{
            margin: 0 0 10px 0;
            font-size: 13px;
            color: #6b7280;
        }}
        .alternative-link a {{
            color: #3b82f6;
            word-break: break-all;
            font-size: 12px;
            text-decoration: none;
        }}
        .requirements {{
            background-color: #fefce8;
            border-left: 4px solid #eab308;
            padding: 20px;
            border-radius: 8px;
            margin: 30px 0;
        }}
        .requirements h3 {{
            margin: 0 0 15px 0;
            color: #854d0e;
            font-size: 15px;
            font-weight: 600;
        }}
        .requirements ul {{
            margin: 0;
            padding-left: 20px;
            color: #713f12;
            font-size: 14px;
        }}
        .requirements li {{
            margin: 8px 0;
        }}
        .footer {{
            background-color: #f9fafb;
            padding: 30px;
            text-align: center;
            border-top: 1px solid #e5e7eb;
        }}
        .footer p {{
            margin: 5px 0;
            font-size: 13px;
            color: #6b7280;
        }}
        .footer a {{
            color: #3b82f6;
            text-decoration: none;
        }}
        .divider {{
            height: 1px;
            background-color: #e5e7eb;
            margin: 30px 0;
        }}
        @media only screen and (max-width: 600px) {{
            .content {{
                padding: 30px 20px;
            }}
            .header {{
                padding: 30px 20px;
            }}
            .header h1 {{
                font-size: 24px;
            }}
            .cta-button {{
                display: block;
                text-align: center;
            }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <!-- Header -->
        <div class="header">
            <div class="logo">
                <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/>
                </svg>
            </div>
            <h1>CYBERGARD AI</h1>
            <p>Activez votre compte</p>
        </div>

        <!-- Content -->
        <div class="content">
            <p class="greeting">Bonjour {user_name},</p>
            
            <p class="message">
                <strong>{sender_name}</strong> vous a invité à rejoindre <strong>{organization_name}</strong> sur CYBERGARD AI.
            </p>
            
            <p class="message">
                Pour activer votre compte et accéder à la plateforme, veuillez cliquer sur le bouton ci-dessous et définir votre mot de passe.
            </p>

            <!-- CTA Button -->
            <div style="text-align: center; margin: 40px 0;">
                <a href="{activation_link}" class="cta-button">
                    🔐 Activer mon compte
                </a>
            </div>

            <!-- Info Box -->
            <div class="info-box">
                <strong>⏰ Lien valide pendant 48 heures</strong>
                <p>
                    Ce lien d'activation est valable pendant 48 heures. 
                    Passé ce délai, vous devrez demander un nouvel email d'activation.
                </p>
            </div>

            <!-- Password Requirements -->
            <div class="requirements">
                <h3>🔒 Exigences pour le mot de passe :</h3>
                <ul>
                    <li>Minimum 12 caractères</li>
                    <li>Au moins une lettre majuscule (A-Z)</li>
                    <li>Au moins une lettre minuscule (a-z)</li>
                    <li>Au moins un chiffre (0-9)</li>
                    <li>Au moins un caractère spécial (!@#$%^&*)</li>
                </ul>
            </div>

            <div class="divider"></div>

            <!-- Alternative Link -->
            <div class="alternative-link">
                <p><strong>Le bouton ne fonctionne pas ?</strong></p>
                <p>Copiez et collez ce lien dans votre navigateur :</p>
                <a href="{activation_link}">{activation_link}</a>
            </div>

            <p class="message" style="margin-top: 30px; font-size: 14px; color: #6b7280;">
                Si vous n'avez pas demandé cette invitation, vous pouvez ignorer cet email en toute sécurité.
            </p>
        </div>

        <!-- Footer -->
        <div class="footer">
            <p style="font-weight: 600; color: #111827; margin-bottom: 10px;">CYBERGARD AI</p>
            <p>Plateforme de gestion de la conformité et de la cybersécurité</p>
            <p style="margin-top: 15px;">
                <a href="mailto:support@cyberguard.pro">support@cyberguard.pro</a>
            </p>
            <p style="margin-top: 20px; font-size: 12px;">
                © 2025 CYBERGARD AI. Tous droits réservés.
            </p>
        </div>
    </div>
</body>
</html>
    """
    
    text_body = f"""
Bonjour {user_name},

{sender_name} vous a invité à rejoindre {organization_name} sur CYBERGARD AI.

Pour activer votre compte, veuillez cliquer sur le lien ci-dessous :
{activation_link}

Ce lien est valable pendant 48 heures.

Exigences pour le mot de passe :
- Minimum 12 caractères
- Au moins une lettre majuscule (A-Z)
- Au moins une lettre minuscule (a-z)
- Au moins un chiffre (0-9)
- Au moins un caractère spécial (!@#$%^&*)

Si vous n'avez pas demandé cette invitation, vous pouvez ignorer cet email.

---
CYBERGARD AI
support@cyberguard.pro
© 2025 CYBERGARD AI. Tous droits réservés.
    """
    
    return {
        "subject": f"Activez votre compte CYBERGARD AI - {organization_name}",
        "html_body": html_body.strip(),
        "text_body": text_body.strip()
    }


# Exemple d'utilisation
if __name__ == "__main__":
    example = get_activation_email_template(
        user_name="Jean Dupont",
        activation_link="https://app.cyberguard.pro/activate-account?token=abc123xyz789",
        organization_name="Vision Agile",
        sender_name="Rachid AHAJRI"
    )
    
    print("Subject:", example["subject"])
    print("\nHTML Preview saved to: activation_email_preview.html")
    
    with open("activation_email_preview.html", "w", encoding="utf-8") as f:
        f.write(example["html_body"])