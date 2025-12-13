# backend/src/api/v1/auth.py
"""
Endpoints d'authentification : login, logout, refresh token
AMÉLIORATION : Inclut le nom de l'organisation dans la réponse de login
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, text
from datetime import datetime, timedelta
from typing import Optional
import jwt
from pydantic import BaseModel, EmailStr

from src.database import get_db
from src.models.audit import User
from src.models.tenant import Tenant
from src.models.organization import Organization
from src.utils.security import verify_password

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Configuration JWT
SECRET_KEY = "votre-cle-secrete-super-longue-a-changer-en-production-123456789"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 heures


# ============================================================================
# SCHÉMAS PYDANTIC
# ============================================================================

class LoginRequest(BaseModel):
    """Schéma pour la requête de login"""
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Schéma pour la réponse de login"""
    access_token: str
    token_type: str
    user: dict


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Crée un token JWT"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authentifie un utilisateur et retourne un token JWT
    
    Endpoint: POST /api/v1/auth/login
    
    ✨ AMÉLIORATION : Inclut maintenant le nom de l'organisation dans la réponse
    """
    
    logger.info(f"🔐 Tentative de connexion: {credentials.email}")
    
    try:
        # 1. Récupérer l'utilisateur par email
        user = db.execute(
            select(User).where(User.email == credentials.email)
        ).scalar_one_or_none()
        
        if not user:
            logger.warning(f"❌ Utilisateur introuvable: {credentials.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou mot de passe incorrect"
            )
        
        # 2. Vérifier le mot de passe
        if not verify_password(credentials.password, user.password_hash):
            logger.warning(f"❌ Mot de passe incorrect pour: {credentials.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou mot de passe incorrect"
            )
        
        # 3. Vérifier que l'utilisateur est actif
        if not user.is_active:
            logger.warning(f"❌ Utilisateur désactivé: {credentials.email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Compte désactivé"
            )
        
        # 4. Vérifier que le tenant est actif
        if user.tenant_id:
            tenant = db.get(Tenant, user.tenant_id)
            if not tenant or not tenant.is_active:
                logger.warning(f"❌ Tenant désactivé pour: {credentials.email}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organisation désactivée"
                )
        
        # 5. ✨ NOUVEAU : Récupérer les données de l'organisation
        organization_name = None
        organization_domain = None
        if user.default_org_id:
            org = db.get(Organization, user.default_org_id)
            if not org or not org.is_active:
                logger.warning(f"❌ Organisation désactivée pour: {credentials.email}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organisation désactivée"
                )
            # Récupérer le nom et le domaine de l'organisation
            organization_name = org.name
            organization_domain = org.domain
        
        # 6. Vérifier que l'utilisateur a un rôle
        role = None
        if user.default_org_id:
            # Requête SQL directe à la table user_organization_role
            result = db.execute(
                text("""
                    SELECT role, is_active 
                    FROM user_organization_role 
                    WHERE user_id = :user_id AND organization_id = :org_id
                """),
                {"user_id": str(user.id), "org_id": str(user.default_org_id)}
            ).first()
            
            if not result:
                logger.warning(f"❌ Aucun rôle pour: {credentials.email}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Aucun rôle assigné"
                )
            
            # Créer un objet simple pour stocker les infos du rôle
            class RoleInfo:
                def __init__(self, role_name, is_active):
                    self.role = role_name
                    self.is_active = is_active
            
            role = RoleInfo(result[0], result[1])
            
            if not role.is_active:
                logger.warning(f"❌ Rôle désactivé pour: {credentials.email}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Rôle désactivé"
                )
        
        # 7. Mettre à jour last_login_at
        user.last_login_at = datetime.utcnow()
        db.commit()
        
        # 8. Créer le token JWT
        token_data = {
            "user_id": str(user.id),
            "email": user.email,
            "tenant_id": str(user.tenant_id) if user.tenant_id else None,
            "organization_id": str(user.default_org_id) if user.default_org_id else None,
            "role": role.role if role else "USER"
        }
        
        access_token = create_access_token(data=token_data)
        
        logger.info(f"✅ Connexion réussie: {credentials.email} (rôle: {role.role if role else 'USER'})")
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "firstName": user.first_name,
                "lastName": user.last_name,
                "role": role.role if role else "USER",
                "organizationId": str(user.default_org_id) if user.default_org_id else None,
                "organizationName": organization_name,
                "organizationDomain": organization_domain,
                "tenantId": str(user.tenant_id) if user.tenant_id else None
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la connexion: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur serveur: {str(e)}"
        )


@router.post("/logout")
async def logout():
    """Déconnexion"""
    return {"message": "Déconnexion réussie"}