# backend/src/schemas/user.py
"""
Schémas Pydantic pour les utilisateurs
"""

from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import Optional
from uuid import UUID
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    """Rôles des utilisateurs"""
    SUPER_ADMIN = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    ORG_ADMIN = "org_admin"
    AUDITOR = "auditor"
    USER = "user"


# ============================================================================
# Schémas de base
# ============================================================================

class UserBase(BaseModel):
    """Schéma de base pour un utilisateur"""
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = None
    role: UserRole = UserRole.USER
    is_active: bool = True
    organization_id: Optional[UUID] = None


class UserCreate(UserBase):
    """Schéma pour créer un utilisateur"""
    password: str = Field(..., min_length=8, max_length=100)
    tenant_id: UUID


class UserUpdate(BaseModel):
    """Schéma pour mettre à jour un utilisateur"""
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserUpdatePassword(BaseModel):
    """Schéma pour changer le mot de passe"""
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=100)


# ============================================================================
# Schémas de réponse
# ============================================================================

class UserResponse(UserBase):
    """Schéma de réponse pour un utilisateur"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    tenant_id: UUID
    is_email_verified: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class UserListResponse(BaseModel):
    """Schéma de réponse pour une liste d'utilisateurs"""
    items: list[UserResponse]
    total: int
    skip: int
    limit: int


# ============================================================================
# Schémas d'authentification
# ============================================================================

class UserLogin(BaseModel):
    """Schéma pour la connexion"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Schéma pour le token JWT"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenData(BaseModel):
    """Données contenues dans le token"""
    user_id: UUID
    tenant_id: UUID
    email: str
    role: UserRole