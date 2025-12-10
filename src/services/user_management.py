# backend/src/api/v1/user_management.py
"""
Endpoints API pour la gestion des utilisateurs admin dans les organisations
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, validator

from src.database import get_db
from src.services.user_management_service import UserManagementService

router = APIRouter(prefix="/api/v1/users", tags=["User Management"])


# ==========================================
# SCHÉMAS PYDANTIC
# ==========================================

class CreateAdminUserRequest(BaseModel):
    """Schéma pour créer un utilisateur admin"""
    email: EmailStr
    first_name: str
    last_name: str
    organization_id: UUID
    tenant_id: UUID
    role_code: str = "SUPER_ADMIN"
    send_invitation: bool = True
    
    @validator('first_name', 'last_name')
    def validate_name(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError("Le nom doit contenir au moins 2 caractères")
        return v.strip()
    
    @validator('role_code')
    def validate_role(cls, v):
        valid_roles = [
            "SUPER_ADMIN", "RSSI", "RSSI_EXTERNE", 
            "DIR_CONFORMITE_DPO", "DPO_EXTERNE",
            "CHEF_PROJET", "AUDITEUR",
            "AUDITE_RESP", "AUDITE_CONTRIB"
        ]
        if v not in valid_roles:
            raise ValueError(f"Rôle invalide. Rôles valides: {', '.join(valid_roles)}")
        return v


class CreateAdminUserResponse(BaseModel):
    """Réponse après création d'utilisateur"""
    user_id: str
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    invitation_token: Optional[str]
    invitation_expires: Optional[str]
    alert_limit_reached: bool
    current_users: int
    max_users: int


class ActivateAccountRequest(BaseModel):
    """Schéma pour activer un compte"""
    token: str
    password: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        if not any(c.isupper() for c in v):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule")
        if not any(c.islower() for c in v):
            raise ValueError("Le mot de passe doit contenir au moins une minuscule")
        if not any(c.isdigit() for c in v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        return v


class UpdateUserRoleRequest(BaseModel):
    """Schéma pour modifier le rôle d'un utilisateur"""
    role_code: str
    permissions: Optional[dict] = None
    
    @validator('role_code')
    def validate_role(cls, v):
        valid_roles = [
            "SUPER_ADMIN", "RSSI", "RSSI_EXTERNE", 
            "DIR_CONFORMITE_DPO", "DPO_EXTERNE",
            "CHEF_PROJET", "AUDITEUR",
            "AUDITE_RESP", "AUDITE_CONTRIB"
        ]
        if v not in valid_roles:
            raise ValueError(f"Rôle invalide. Rôles valides: {', '.join(valid_roles)}")
        return v


class UserListItem(BaseModel):
    """Item de la liste des utilisateurs"""
    id: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    role: str
    is_active: bool
    is_email_verified: bool
    last_login_at: Optional[str]
    created_at: str
    permissions: dict


class UserListResponse(BaseModel):
    """Réponse de la liste des utilisateurs"""
    total: int
    skip: int
    limit: int
    users: List[UserListItem]


# ==========================================
# ENDPOINTS
# ==========================================

@router.post(
    "/admin/create",
    response_model=CreateAdminUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un utilisateur admin",
    description="Crée un nouvel utilisateur administrateur et envoie une invitation par email"
)
async def create_admin_user(
    request: CreateAdminUserRequest,
    db: Session = Depends(get_db)
):
    """
    Crée un nouvel utilisateur administrateur pour une organisation.
    
    - Génère un token d'invitation
    - Envoie un email avec lien d'activation
    - Alerte si limite d'utilisateurs atteinte
    - Associe l'utilisateur à l'organisation avec le rôle spécifié
    """
    try:
        service = UserManagementService(db)
        result = service.create_admin_user(
            email=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
            organization_id=request.organization_id,
            tenant_id=request.tenant_id,
            role_code=request.role_code,
            send_invitation=request.send_invitation
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création de l'utilisateur: {str(e)}"
        )


@router.post(
    "/activate",
    status_code=status.HTTP_200_OK,
    summary="Activer un compte utilisateur",
    description="Active un compte utilisateur avec le token d'invitation et définit le mot de passe"
)
async def activate_account(
    request: ActivateAccountRequest,
    db: Session = Depends(get_db)
):
    """
    Active un compte utilisateur avec le token d'invitation.
    
    - Vérifie la validité du token
    - Vérifie l'expiration
    - Définit le mot de passe
    - Active le compte
    """
    try:
        service = UserManagementService(db)
        result = service.activate_user_account(
            token=request.token,
            password=request.password
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'activation du compte: {str(e)}"
        )


@router.get(
    "/organization/{organization_id}",
    response_model=UserListResponse,
    summary="Lister les utilisateurs d'une organisation",
    description="Récupère la liste de tous les utilisateurs d'une organisation"
)
async def list_organization_users(
    organization_id: UUID,
    tenant_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Liste tous les utilisateurs d'une organisation avec leurs rôles.
    
    - Pagination disponible
    - Filtre par tenant
    - Inclut les permissions de chaque utilisateur
    """
    try:
        service = UserManagementService(db)
        result = service.list_organization_users(
            organization_id=organization_id,
            tenant_id=tenant_id,
            skip=skip,
            limit=limit
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des utilisateurs: {str(e)}"
        )


@router.put(
    "/{user_id}/role",
    summary="Modifier le rôle d'un utilisateur",
    description="Modifie le rôle et les permissions d'un utilisateur dans une organisation"
)
async def update_user_role(
    user_id: UUID,
    organization_id: UUID,
    request: UpdateUserRoleRequest,
    db: Session = Depends(get_db)
):
    """
    Modifie le rôle d'un utilisateur dans une organisation.
    
    - Change le code de rôle
    - Met à jour les permissions si fournies
    """
    try:
        service = UserManagementService(db)
        result = service.update_user_role(
            user_id=user_id,
            organization_id=organization_id,
            new_role=request.role_code,
            new_permissions=request.permissions
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la modification du rôle: {str(e)}"
        )


@router.delete(
    "/{user_id}/organization/{organization_id}",
    summary="Désactiver un utilisateur",
    description="Désactive un utilisateur dans une organisation"
)
async def deactivate_user(
    user_id: UUID,
    organization_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Désactive un utilisateur dans une organisation.
    
    - Marque la relation comme inactive
    - Désactive l'utilisateur si c'est son organisation par défaut
    """
    try:
        service = UserManagementService(db)
        result = service.deactivate_user(
            user_id=user_id,
            organization_id=organization_id
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la désactivation de l'utilisateur: {str(e)}"
        )


@router.post(
    "/{user_id}/resend-invitation",
    summary="Renvoyer l'invitation",
    description="Génère un nouveau token et renvoie l'email d'invitation"
)
async def resend_invitation(
    user_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Renvoie l'email d'invitation à un utilisateur.
    
    - Génère un nouveau token
    - Prolonge la date d'expiration
    - Renvoie l'email
    """
    # TODO: Implémenter
    return {"message": "Invitation renvoyée avec succès"}


@router.get(
    "/roles",
    summary="Lister les rôles disponibles",
    description="Récupère la liste de tous les rôles système disponibles"
)
async def list_available_roles(db: Session = Depends(get_db)):
    """
    Liste tous les rôles disponibles dans le système.
    
    Retourne les rôles système avec leurs descriptions.
    """
    roles = [
        {
            "code": "SUPER_ADMIN",
            "name": "Super Admin",
            "description": "Administrateur complet avec tous les droits"
        },
        {
            "code": "RSSI",
            "name": "RSSI",
            "description": "Responsable de la Sécurité des Systèmes d'Information"
        },
        {
            "code": "RSSI_EXTERNE",
            "name": "RSSI externe",
            "description": "RSSI externe à l'organisation"
        },
        {
            "code": "DIR_CONFORMITE_DPO",
            "name": "Directeur de conformité / DPO",
            "description": "Responsable de la conformité et DPO"
        },
        {
            "code": "DPO_EXTERNE",
            "name": "DPO externe",
            "description": "DPO externe à l'organisation"
        },
        {
            "code": "CHEF_PROJET",
            "name": "Chef de projet",
            "description": "Responsable de projet d'audit"
        },
        {
            "code": "AUDITEUR",
            "name": "Auditeur",
            "description": "Auditeur réalisant les audits"
        },
        {
            "code": "AUDITE_RESP",
            "name": "Audité (responsable)",
            "description": "Responsable d'une entité auditée"
        },
        {
            "code": "AUDITE_CONTRIB",
            "name": "Audité (contributeur)",
            "description": "Contributeur dans une entité auditée"
        }
    ]
    return {"roles": roles}
