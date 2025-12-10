"""
Schémas Pydantic pour les Clients
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


# ============================================================================
# BASE SCHEMAS
# ============================================================================

class ClientBase(BaseModel):
    """Schéma de base pour un client"""
    name: str = Field(..., min_length=1, max_length=255, description="Nom du client")
    domain: Optional[str] = Field(None, max_length=100, description="Domaine du client (ex: acme.com)")
    subscription_type: str = Field(default="starter", description="Type d'abonnement")
    billing_email: Optional[EmailStr] = Field(None, description="Email de facturation")
    country_code: str = Field(default="FR", min_length=2, max_length=2, description="Code pays ISO")
    sector: Optional[str] = Field(None, max_length=100, description="Secteur d'activité")
    size_category: Optional[str] = Field(None, description="Catégorie de taille")
    employee_count: Optional[int] = Field(None, ge=0, description="Nombre d'employés")
    max_organizations: int = Field(default=10, ge=1, description="Limite d'organisations")
    max_auditors: int = Field(default=5, ge=1, description="Limite d'auditeurs")


# ============================================================================
# REQUEST SCHEMAS
# ============================================================================

class ClientCreate(ClientBase):
    """Schéma pour la création d'un client"""
    pass


class ClientUpdate(BaseModel):
    """Schéma pour la mise à jour d'un client"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    domain: Optional[str] = Field(None, max_length=100)
    subscription_type: Optional[str] = None
    billing_email: Optional[EmailStr] = None
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    sector: Optional[str] = Field(None, max_length=100)
    size_category: Optional[str] = None
    employee_count: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    max_organizations: Optional[int] = Field(None, ge=1)
    max_auditors: Optional[int] = Field(None, ge=1)


# ============================================================================
# RESPONSE SCHEMAS
# ============================================================================

class ClientResponse(ClientBase):
    """Schéma de réponse pour un client"""
    id: UUID
    tenant_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ClientListResponse(BaseModel):
    """Schéma de réponse pour une liste paginée de clients"""
    items: List[ClientResponse]
    total: int
    skip: int
    limit: int


# ============================================================================
# SCHEMAS STATISTIQUES
# ============================================================================

class ClientStats(BaseModel):
    """Statistiques des clients"""
    total_clients: int
    active_clients: int
    inactive_clients: int
    subscription_breakdown: dict
    
    class Config:
        from_attributes = True


# ============================================================================
# UTILITY SCHEMAS
# ============================================================================

class TenantCreateData(BaseModel):
    """Données pour créer un tenant associé"""
    name: str
    subscription_type: str = "starter"
    max_users: int = 5
    max_organizations: int = 1