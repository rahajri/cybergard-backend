# backend/src/schemas/category.py
"""
Schémas Pydantic pour les catégories
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CategoryCreate(BaseModel):
    """Schéma pour créer une nouvelle catégorie"""
    name: str = Field(..., description="Nom de la catégorie")
    entity_category: str = Field(..., description="Type de catégorie (client, supplier, partner, etc.)")
    description: Optional[str] = Field(None, description="Description optionnelle")
    parent_category_id: Optional[str] = Field(None, description="ID de la catégorie parente (pour sous-catégories)")
    client_organization_id: Optional[str] = Field(None, description="ID de l'organisation cliente")
    tenant_id: Optional[str] = Field(None, description="ID du tenant")
    stakeholder_type: str = Field(..., description="Type: 'internal' ou 'external'")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Fournisseurs IT",
                "entity_category": "supplier",
                "description": "Fournisseurs de services informatiques",
                "parent_category_id": "5871341e-bc83-4f47-8cbf-f938658203eb",
                "client_organization_id": "bf787e86-7df2-4a0d-b24f-88fe54a618dd",
                "tenant_id": "a7f8ab96-1acb-4f01-a6d7-9cdee2ec2ce0",
                "stakeholder_type": "external"
            }
        }


class CategoryResponse(BaseModel):
    """Schéma de réponse pour une catégorie"""
    id: str
    name: str
    entity_category: str
    description: Optional[str]
    parent_category_id: Optional[str]
    hierarchy_level: int
    ecosystem_domain_id: str
    pole_id: str
    is_base_template: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CategoryUpdate(BaseModel):
    """Schéma pour mettre à jour une catégorie"""
    name: Optional[str] = Field(None, description="Nouveau nom")
    description: Optional[str] = Field(None, description="Nouvelle description")
    is_active: Optional[bool] = Field(None, description="Activer/désactiver")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Fournisseurs IT & Cloud",
                "description": "Fournisseurs de services IT et cloud"
            }
        }


class CategoryTreeNode(BaseModel):
    """Schéma pour l'arbre hiérarchique des catégories"""
    id: str
    name: str
    entity_category: str
    hierarchy_level: int
    children: list["CategoryTreeNode"] = []

    class Config:
        from_attributes = True