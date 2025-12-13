"""
Schémas Pydantic pour les Pôles
"""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List


class PoleBase(BaseModel):
    """Schéma de base pour un pôle"""
    name: str = Field(..., min_length=1, max_length=200, description="Nom du pôle")
    description: Optional[str] = Field(None, description="Description du pôle")
    short_code: Optional[str] = Field(None, max_length=50, description="Code court du pôle")
    client_organization_id: Optional[str] = Field(None, max_length=100, description="ID de l'organisation cliente")


class PoleCreate(PoleBase):
    """Schéma pour créer un pôle"""
    ecosystem_domain_id: Optional[UUID] = Field(None, description="ID du domaine écosystème (auto-résolu si non fourni)")
    tenant_id: Optional[UUID] = Field(None, description="ID du tenant")
    is_base_template: bool = Field(False, description="Est-ce un template de base")
    status: str = Field("active", description="Statut du pôle")
    created_by: Optional[str] = Field(None, max_length=100, description="Créé par")


class PoleUpdate(BaseModel):
    """Schéma pour mettre à jour un pôle"""
    name: Optional[str] = Field(None, min_length=1, max_length=200, description="Nom du pôle")
    description: Optional[str] = Field(None, description="Description du pôle")
    short_code: Optional[str] = Field(None, max_length=50, description="Code court du pôle")
    is_active: Optional[bool] = Field(None, description="Statut actif")
    status: Optional[str] = Field(None, description="Statut du pôle")
    updated_by: Optional[str] = Field(None, max_length=100, description="Mis à jour par")


class PoleResponse(PoleBase):
    """Schéma de réponse pour un pôle"""
    id: UUID
    ecosystem_domain_id: UUID
    tenant_id: Optional[UUID] = None
    parent_pole_id: Optional[UUID] = None
    hierarchy_level: int = 1
    hierarchy_path: Optional[str] = None
    is_base_template: bool
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True


class PoleListResponse(BaseModel):
    """Schéma de réponse pour une liste de pôles"""
    items: list[PoleResponse]
    total: int
    skip: int
    limit: int

class PoleCreateWithTenant(BaseModel):
    """Schéma pour créer un pôle avec tenant_id"""
    ecosystem_domain_id: UUID
    tenant_id: Optional[UUID] = None
    client_organization_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    short_code: Optional[str] = Field(None, max_length=50)
    parent_pole_id: Optional[UUID] = Field(None, description="ID du pôle parent (NULL pour pôle racine)")
    is_base_template: bool = False  # False par défaut pour les pôles personnalisés
    status: str = "active"
    is_active: bool = True

# À ajouter dans src/schemas/category.py
class CategoryCreateWithTenant(BaseModel):
    """Schéma pour créer une catégorie avec tenant_id"""
    ecosystem_domain_id: UUID
    pole_id: UUID
    tenant_id: Optional[UUID] = None
    client_organization_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    entity_category: str = Field(..., description="Type de catégorie: client, supplier, partner, etc.")
    description: Optional[str] = None
    short_code: Optional[str] = Field(None, max_length=50)
    parent_category_id: Optional[UUID] = None
    hierarchy_level: int = Field(2, ge=1, le=10)
    is_base_template: bool = False  # False par défaut pour les catégories personnalisées
    keywords: Optional[List[str]] = []
    status: str = "active"
    is_active: bool = True