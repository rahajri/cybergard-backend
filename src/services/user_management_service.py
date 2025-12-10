"""
API pour la gestion des utilisateurs
VERSION CORRIGÉE - Fix bcrypt + Support role_code + Password optionnel + CRÉATION AUTO RÔLES
"""
from typing import List, Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func, text
import secrets
import string

from src.database import get_db
from src.models.audit import User
from src.models.tenant import Tenant
from src.models.organization import Organization
from src.utils.security import hash_password, verify_password

import logging

logger = logging.getLogger(__name__)

# ✅ Le préfixe /users est défini ici pour correspondre à votre frontend
router = APIRouter(prefix="/users")

def generate_temp_password(length: int = 12) -> str:
    """Génère un mot de passe temporaire sécurisé"""
    alphabet = string.ascii_letters + string.digits + "!@#$%&"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ============================================================================
# SCHÉMAS PYDANTIC (inline pour simplifier)
# ============================================================================

from pydantic import BaseModel, EmailStr, Field
from datetime import datetime


class UserBase(BaseModel):
    """Schéma de base pour un utilisateur"""
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    tenant_id: Optional[UUID] = None
    default_org_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None


class UserCreate(UserBase):
    """Schéma pour créer un utilisateur"""
    password: Optional[str] = Field(None, min_length=8, max_length=72)  # ✅ Optionnel et limité à 72
    role_code: Optional[str] = None  # ✅ Ajout role_code
    is_active: bool = True


class UserUpdate(BaseModel):
    """Schéma pour mettre à jour un utilisateur"""
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, min_length=8, max_length=72)  # ✅ Limité à 72
    is_active: Optional[bool] = None
    is_email_verified: Optional[bool] = None
    default_org_id: Optional[UUID] = None


class UserResponse(UserBase):
    """Schéma de réponse pour un utilisateur"""
    id: UUID
    is_active: bool
    is_email_verified: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Schéma de réponse pour une liste d'utilisateurs"""
    items: list[UserResponse]
    total: int
    skip: int
    limit: int


# ============================================================================
# ENDPOINTS : Users
# ============================================================================

@router.post("/admin/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Crée un nouvel utilisateur avec attribution automatique du rôle
    
    Endpoint final: POST /api/v1/users/admin/create
    
    - **email**: Email unique de l'utilisateur
    - **first_name**: Prénom
    - **last_name**: Nom
    - **password**: Mot de passe (sera hashé) - OPTIONNEL, généré si absent
    - **tenant_id**: ID du tenant
    - **default_org_id**: ID de l'organisation par défaut (optionnel)
    - **role_code**: Code du rôle (ex: SUPER_ADMIN) - optionnel, créera automatiquement le rôle
    """
    
    logger.info(f"🔵 Tentative de création d'utilisateur: {user.email}")
    
    # Vérifier que l'email n'existe pas déjà
    existing_user = db.execute(
        select(User).where(User.email == user.email)
    ).scalar_one_or_none()
    
    if existing_user:
        logger.warning(f"❌ Email déjà utilisé: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un utilisateur avec l'email '{user.email}' existe déjà"
        )
    
    # Vérifier que le tenant existe
    if user.tenant_id:
        tenant = db.get(Tenant, user.tenant_id)
        if not tenant:
            logger.error(f"❌ Tenant introuvable: {user.tenant_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant {user.tenant_id} introuvable"
            )
        
        # Vérifier la limite d'utilisateurs
        user_count = db.execute(
            select(func.count(User.id)).where(User.tenant_id == user.tenant_id)
        ).scalar()
        
        if user_count >= tenant.max_users:
            logger.warning(f"❌ Limite d'utilisateurs atteinte pour tenant {user.tenant_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Limite d'utilisateurs atteinte ({tenant.max_users}) pour ce tenant"
            )
    
    # Vérifier que l'organisation existe si spécifiée
    if user.default_org_id:
        org = db.get(Organization, user.default_org_id)
        if not org:
            logger.error(f"❌ Organisation introuvable: {user.default_org_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organisation {user.default_org_id} introuvable"
            )
    
    # ✅ Gérer le mot de passe : générer si absent
    if user.password:
        password_to_hash = user.password
    else:
        password_to_hash = generate_temp_password()
        logger.info(f"🔑 Mot de passe temporaire généré pour {user.email}: {password_to_hash}")
    
    # Hasher le mot de passe
    hashed_password = hash_password(password_to_hash)
    
    # Créer l'utilisateur
    db_user = User(
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        password_hash=hashed_password,
        tenant_id=user.tenant_id,
        default_org_id=user.default_org_id,
        is_active=user.is_active if hasattr(user, 'is_active') else True,
        is_email_verified=False
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    logger.info(f"✅ Utilisateur créé: {db_user.email} ({db_user.id})")
    
    # ============================================================================
    # ✅ CRÉATION AUTOMATIQUE DU RÔLE SUPER_ADMIN dans user_organization_role
    # ============================================================================
    if hasattr(user, 'role_code') and user.role_code and user.default_org_id:
        logger.info(f"🔐 Attribution du rôle {user.role_code} à {db_user.email}")
        
        try:
            # Créer l'entrée dans user_organization_role
            insert_role_sql = text("""
                INSERT INTO user_organization_role (
                    id, 
                    user_id, 
                    organization_id, 
                    role, 
                    is_active, 
                    permissions, 
                    created_at
                )
                VALUES (
                    :id, 
                    :user_id, 
                    :org_id, 
                    :role, 
                    :is_active, 
                    :permissions, 
                    NOW()
                )
                ON CONFLICT DO NOTHING
            """)
            
            db.execute(insert_role_sql, {
                "id": str(uuid4()),
                "user_id": str(db_user.id),
                "org_id": str(user.default_org_id),
                "role": user.role_code,
                "is_active": True,
                "permissions": '{"can_manage_users": true, "can_manage_org": true, "can_view_all": true}'
            })
            
            db.commit()  # Commit la création du rôle
            
            logger.info(f"✅ Rôle {user.role_code} assigné à {db_user.email} pour l'organisation {user.default_org_id}")
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la création du rôle: {e}")
            # On continue quand même, l'utilisateur est créé
            # Vous pouvez choisir de raise une exception ici si vous voulez que tout échoue
    
    return db_user


@router.get("/admin", response_model=UserListResponse)
async def list_users(
    tenant_id: Optional[UUID] = Query(None, description="Filtrer par tenant"),
    organization_id: Optional[UUID] = Query(None, description="Filtrer par organisation"),
    is_active: Optional[bool] = Query(None, description="Filtrer par statut actif"),
    skip: int = Query(0, ge=0, description="Nombre d'éléments à sauter"),
    limit: int = Query(100, ge=1, le=1000, description="Nombre d'éléments à retourner"),
    db: Session = Depends(get_db)
):
    """
    Liste tous les utilisateurs avec filtres et pagination
    
    Endpoint final: GET /api/v1/users/admin
    """
    
    query = select(User)
    
    # Filtres
    if tenant_id:
        query = query.where(User.tenant_id == tenant_id)
    
    if organization_id:
        query = query.where(User.default_org_id == organization_id)
    
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    
    # Tri par date de création (plus récent en premier)
    query = query.order_by(User.created_at.desc())
    
    # Pagination
    query = query.offset(skip).limit(limit)
    
    # Exécution
    result = db.execute(query)
    users = result.scalars().all()
    
    # Count total
    count_query = select(func.count()).select_from(User)
    if tenant_id:
        count_query = count_query.where(User.tenant_id == tenant_id)
    if organization_id:
        count_query = count_query.where(User.default_org_id == organization_id)
    if is_active is not None:
        count_query = count_query.where(User.is_active == is_active)
    total = db.execute(count_query).scalar()
    
    logger.info(f"📋 Liste utilisateurs: {len(users)} résultats (total: {total})")
    
    return {
        "items": users,
        "total": total or 0,
        "skip": skip,
        "limit": limit
    }


@router.get("/admin/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Récupère un utilisateur par son ID
    
    Endpoint final: GET /api/v1/users/admin/{user_id}
    """
    
    user = db.get(User, user_id)
    
    if not user:
        logger.warning(f"❌ Utilisateur introuvable: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Utilisateur {user_id} introuvable"
        )
    
    logger.info(f"👤 Utilisateur récupéré: {user.email}")
    
    return user


@router.put("/admin/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_update: UserUpdate,
    db: Session = Depends(get_db)
):
    """
    Met à jour un utilisateur
    
    Endpoint final: PUT /api/v1/users/admin/{user_id}
    """
    
    db_user = db.get(User, user_id)
    
    if not db_user:
        logger.warning(f"❌ Utilisateur introuvable: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Utilisateur {user_id} introuvable"
        )
    
    # Mettre à jour les champs fournis
    update_data = user_update.model_dump(exclude_unset=True)
    
    # Si le mot de passe est fourni, le hasher
    if 'password' in update_data:
        update_data['password_hash'] = hash_password(update_data.pop('password'))
    
    for field, value in update_data.items():
        setattr(db_user, field, value)
    
    db.commit()
    db.refresh(db_user)
    
    logger.info(f"✅ Utilisateur modifié: {db_user.email}")
    
    return db_user


@router.delete("/admin/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Supprime un utilisateur
    
    Endpoint final: DELETE /api/v1/users/admin/{user_id}
    """
    
    db_user = db.get(User, user_id)
    
    if not db_user:
        logger.warning(f"❌ Utilisateur introuvable: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Utilisateur {user_id} introuvable"
        )
    
    email = db_user.email
    
    db.delete(db_user)
    db.commit()
    
    logger.info(f"🗑️ Utilisateur supprimé: {email}")
    
    return None


@router.get("/admin/by-organization/{org_id}", response_model=UserListResponse)
async def get_users_by_organization(
    org_id: UUID,
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    Récupère tous les utilisateurs d'une organisation
    
    Endpoint final: GET /api/v1/users/admin/by-organization/{org_id}
    """
    
    # Vérifier que l'organisation existe
    org = db.get(Organization, org_id)
    if not org:
        logger.warning(f"❌ Organisation introuvable: {org_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organisation {org_id} introuvable"
        )
    
    query = select(User).where(User.default_org_id == org_id)
    
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    
    query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
    
    result = db.execute(query)
    users = result.scalars().all()
    
    # Count total
    count_query = select(func.count()).select_from(User).where(User.default_org_id == org_id)
    if is_active is not None:
        count_query = count_query.where(User.is_active == is_active)
    total = db.execute(count_query).scalar()
    
    logger.info(f"📋 Utilisateurs de l'organisation {org_id}: {len(users)} résultats")
    
    return {
        "items": users,
        "total": total or 0,
        "skip": skip,
        "limit": limit
    }