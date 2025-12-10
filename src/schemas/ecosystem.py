# backend/src/schemas/ecosystem.py

from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class StakeholderType(str, Enum):
    """Type de partie prenante"""
    internal = "internal"
    external = "external"


class EntityCategory(str, Enum):
    """Catégorie d'entité externe"""
    client = "client"
    supplier = "supplier"
    subcontractor = "subcontractor"


# ============================================================================
# SCHÉMAS ENTITY
# ============================================================================

class EcosystemEntityCreate(BaseModel):
    """Schéma pour créer une entité dans l'écosystème"""
    
    # ========== OBLIGATOIRE ==========
    name: str = Field(..., min_length=1, max_length=200, description="Nom de l'organisme")
    client_organization_id: str = Field(..., max_length=100, description="ID de l'organisation cliente")

    
    # ========== IDENTIFICATION LÉGALE ==========
    legal_name: Optional[str] = Field(None, max_length=300, description="Raison sociale")
    trade_name: Optional[str] = Field(None, max_length=200, description="Nom commercial")
    short_name: Optional[str] = Field(None, max_length=100, description="Nom court")
    siret: Optional[str] = Field(None, max_length=14, description="Numéro SIRET")
    siren: Optional[str] = Field(None, max_length=9, description="Numéro SIREN")
    ape_code: Optional[str] = Field(None, max_length=10, description="Code APE/NAF")
    vat_number: Optional[str] = Field(None, max_length=50, description="Numéro de TVA")
    
    # ========== TYPE D'ORGANISME ==========
    stakeholder_type: Optional[str] = Field(None, description="Type: 'internal' ou 'external'")
    entity_category: Optional[str] = Field(None, description="Catégorie: 'client', 'supplier', 'subcontractor'")
    
    # ========== HIÉRARCHIE (NOUVEAUX CHAMPS CRITIQUES) ==========
    ecosystem_domain_id: Optional[UUID] = Field(None, description="ID du domaine écosystème")
    pole_id: Optional[UUID] = Field(None, description="ID du pôle (OBLIGATOIRE pour organismes internes)")
    category_id: Optional[UUID] = Field(None, description="ID de la catégorie (OBLIGATOIRE pour organismes externes)")
    short_code: Optional[str] = Field(None, max_length=50, description="Code court de l'organisme")
    parent_entity_id: Optional[UUID] = Field(None, description="ID de l'entité parente")
    hierarchy_level: Optional[int] = Field(None, ge=1, le=10, description="Niveau hiérarchique")
    
    # ========== ADRESSE ==========
    address_line1: Optional[str] = Field(None, max_length=200, description="Adresse ligne 1")
    address_line2: Optional[str] = Field(None, max_length=200, description="Adresse ligne 2")
    address_line3: Optional[str] = Field(None, max_length=200, description="Adresse ligne 3")
    postal_code: Optional[str] = Field(None, max_length=20, description="Code postal")
    city: Optional[str] = Field(None, max_length=100, description="Ville")
    region: Optional[str] = Field(None, max_length=100, description="Région")
    country_code: Optional[str] = Field("FR", max_length=2, description="Code pays ISO")
    
    # ========== CONTACT ==========
    main_email: Optional[str] = Field(None, max_length=200, description="Email principal")
    main_phone: Optional[str] = Field(None, max_length=50, description="Téléphone principal")
    website: Optional[str] = Field(None, max_length=500, description="Site web")
    
    # ========== INFORMATIONS COMPLÉMENTAIRES ==========
    description: Optional[str] = Field(None, description="Description de l'organisme")
    notes: Optional[str] = Field(None, description="Notes internes")
    sector: Optional[str] = Field(None, max_length=200, description="Secteur d'activité")
    size_category: Optional[str] = Field(None, max_length=50, description="Taille de l'entreprise")
    employee_count: Optional[int] = Field(None, ge=0, description="Nombre d'employés")
    annual_revenue: Optional[float] = Field(None, ge=0, description="Chiffre d'affaires annuel")
    currency_code: Optional[str] = Field("EUR", max_length=3, description="Code devise ISO")
    
    # ========== STATUT ==========
    status: Optional[str] = Field("pending", max_length=50, description="Statut de l'entité")
    is_active: bool = Field(False, description="Entité active")
    is_certified: Optional[bool] = Field(None, description="Entité certifiée")
    
    # ========== TENANT (Multi-organisation) ==========
    tenant_id: Optional[UUID] = Field(None, description="ID du tenant (sera résolu automatiquement)")
    
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "name": "Service Comptabilité",
                "client_organization_id": "bf787e86-7df2-4a0d-b24f-88fe54a618dd",
                "stakeholder_type": "internal",
                "pole_id": "a7f8ab96-1acb-4f01-a6d7-9cdee2ec2ce0",
                "short_code": "COMPTA",
                "description": "Service en charge de la comptabilité générale",
                "status": "pending",
                "is_active": False
            }
        }
    )


class EcosystemEntityUpdate(BaseModel):
    """Schéma pour mettre à jour une entité"""
    # Tous les champs optionnels
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    legal_name: Optional[str] = Field(None, max_length=300)
    trade_name: Optional[str] = Field(None, max_length=200)
    short_name: Optional[str] = Field(None, max_length=100)
    
    # Hiérarchie
    stakeholder_type: Optional[str] = None
    entity_category: Optional[str] = None
    pole_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    short_code: Optional[str] = Field(None, max_length=50)
    
    # Infos
    description: Optional[str] = None
    notes: Optional[str] = None
    
    # Adresse
    address_line1: Optional[str] = Field(None, max_length=200)
    postal_code: Optional[str] = Field(None, max_length=20)
    city: Optional[str] = Field(None, max_length=100)
    country_code: Optional[str] = Field(None, max_length=2)
    
    # Contact
    main_email: Optional[str] = Field(None, max_length=200)
    main_phone: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=500)
    
    # Statut
    status: Optional[str] = None
    is_active: Optional[bool] = None
    
    model_config = ConfigDict(from_attributes=True)


class EcosystemEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    # Existants
    id: UUID
    name: str
    client_organization_id: UUID
    stakeholder_type: str
    entity_category: Optional[str] = None
    pole_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    ecosystem_domain_id: Optional[UUID] = None
    short_code: Optional[str] = None
    description: Optional[str] = None
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    # ✅ AJOUTER CES CHAMPS MANQUANTS
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    short_name: Optional[str] = None
    siret: Optional[str] = None
    siren: Optional[str] = None
    ape_code: Optional[str] = None
    vat_number: Optional[str] = None
    registration_number: Optional[str] = None
    registration_country: Optional[str] = None
    
    # Adresse
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    address_line3: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country_code: Optional[str] = None
    
    # Autres
    notes: Optional[str] = None
    threat_level: Optional[str] = None
    annual_revenue: Optional[float] = None

    # ✅ Comptage des membres (calculé dynamiquement)
    member_count: Optional[int] = 0


class EcosystemEntityListResponse(BaseModel):
    """Réponse paginée pour la liste d'entités"""
    items: List[EcosystemEntityResponse]
    total: int
    skip: int
    limit: int


class CategoryCreateData(BaseModel):
    """Schéma pour créer une catégorie personnalisée"""
    name: str = Field(..., min_length=1, max_length=255)
    stakeholder_type: StakeholderType
    entity_category: str = Field(..., max_length=100)
    parent_entity_id: Optional[UUID] = None
    description: Optional[str] = None
    client_organization_id: str
    tenant_id: Optional[UUID] = None


# ============================================================================
# SCHÉMAS INSEE
# ============================================================================

class INSEEDataRequest(BaseModel):
    """Requête pour enrichir avec INSEE"""
    siret: str = Field(..., min_length=14, max_length=14, description="SIRET de 14 chiffres")


class INSEEDataResponse(BaseModel):
    """Réponse avec données INSEE"""
    siret: Optional[str] = None
    siren: Optional[str] = None
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    ape_code: Optional[str] = None
    address_line1: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    creation_date: Optional[str] = None
    enterprise_category: Optional[str] = None
    employee_count: Optional[int] = None
    raw_data: Optional[Dict[str, Any]] = Field(default_factory=dict)


# ============================================================================
# SCHÉMAS ENTITY MEMBER
# ============================================================================

class EntityMemberBase(BaseModel):
    """Schéma de base pour un membre d'entité"""
    user_id: Optional[UUID] = None  # NULL pour les contacts (audités externes)
    role: Optional[str] = Field(None, max_length=50)
    is_primary: bool = False


class EntityMemberCreate(EntityMemberBase):
    """Schéma pour créer un membre"""
    pass


class EntityMemberUpdate(BaseModel):
    """Schéma pour mettre à jour un membre"""
    role: Optional[str] = None
    is_primary: Optional[bool] = None
    is_active: Optional[bool] = None


class EntityMemberResponse(BaseModel):
    """Schéma de réponse pour un membre avec informations complètes"""
    id: UUID
    entity_id: UUID
    user_id: Optional[UUID] = None  # NULL pour les contacts (audités externes)
    roles: Optional[List[str]] = []

    # ✅ Informations utilisateur
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    # Autres champs
    job_title: Optional[str] = None
    department: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None

    # Flags
    is_active: bool
    can_be_assigned_audits: bool = True
    can_receive_notifications: bool = True

    # Dates
    joined_at: datetime
    left_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)




# ============================================================================
# SCHÉMAS RELATIONSHIP TYPE
# ============================================================================

class RelationshipTypeCreate(BaseModel):
    """Schéma pour créer un type de relation"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    direction: Optional[str] = Field(None, max_length=50)


class RelationshipTypeUpdate(BaseModel):
    """Schéma pour mettre à jour un type de relation"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    direction: Optional[str] = None
    is_active: Optional[bool] = None


class RelationshipTypeResponse(BaseModel):
    """Schéma de réponse pour un type de relation"""
    id: UUID
    name: str
    description: Optional[str] = None
    direction: Optional[str] = None
    is_active: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# SCHÉMAS BULK OPERATIONS
# ============================================================================

class BulkActivateRequest(BaseModel):
    """Requête pour activer plusieurs entités"""
    entity_ids: List[UUID] = Field(..., min_length=1, description="Liste des IDs à activer")


class BulkArchiveRequest(BaseModel):
    """Requête pour archiver plusieurs entités"""
    entity_ids: List[UUID] = Field(..., min_length=1, description="Liste des IDs à archiver")


class BulkOperationResponse(BaseModel):
    """Réponse pour opérations bulk"""
    success_count: int = Field(..., description="Nombre d'opérations réussies")
    failure_count: int = Field(default=0, description="Nombre d'échecs")
    failed_ids: List[UUID] = Field(default_factory=list, description="IDs ayant échoué")
    messages: List[str] = Field(default_factory=list, description="Messages d'erreur")


# ============================================================================
# STATISTIQUES
# ============================================================================

class EcosystemStats(BaseModel):
    """Statistiques de l'écosystème"""
    total: int = Field(..., description="Nombre total d'entités")
    active: int = Field(..., description="Nombre d'entités actives")
    pending: int = Field(..., description="Nombre d'entités en attente")
    inactive: int = Field(default=0, description="Nombre d'entités inactives")
    total_members: int = Field(..., description="Nombre total de membres")
    
    # Par type
    internal_count: int = Field(default=0, description="Entités internes")
    external_count: int = Field(default=0, description="Entités externes")
    
    # Par catégorie
    pole_count: int = Field(default=0)
    service_count: int = Field(default=0)
    client_count: int = Field(default=0)
    supplier_count: int = Field(default=0)
    subcontractor_count: int = Field(default=0)