"""
Schémas Pydantic pour les Organizations
"""
from pydantic import BaseModel, Field, EmailStr, field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional, Literal
import re


class OrganizationBase(BaseModel):
    """Schéma de base pour une organization"""
    name: str = Field(..., min_length=1, max_length=255, description="Nom de l'organisation")
    domain: Optional[str] = Field(None, max_length=100, description="Domaine web")
    subscription_type: Literal["starter", "professional", "enterprise"] = Field("starter", description="Type d'abonnement")
    email: Optional[str] = Field(None, description="Email de contact")  # ✅ Changé de EmailStr à str
    phone: Optional[str] = Field(None, max_length=50, description="Téléphone")
    country_code: str = Field("FR", max_length=2, description="Code pays ISO")

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        """Validateur d'email personnalisé qui accepte les domaines .local pour le développement"""
        if v is None:
            return v

        # Pattern email basique qui accepte .local et autres domaines de développement
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        # Pattern pour accepter aussi .local
        local_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.local$'

        if re.match(email_pattern, v) or re.match(local_pattern, v):
            return v

        raise ValueError(f"Email invalide: {v}")

    
    # ✅ Champs mappés (sector -> activity, enterprise_category -> category)
    sector: Optional[str] = Field(None, max_length=100, description="Secteur d'activité (legacy)")
    activity: Optional[str] = Field(None, max_length=255, description="Activité (libellé NAF)")
    enterprise_category: Optional[str] = Field(None, description="Catégorie (legacy)")
    category: Optional[str] = Field(None, description="Catégorie INSEE (MIC, PME, ETI, GE)")
    
    workforce: Optional[int] = Field(None, ge=0, description="Nombre d'employés")
    siret: Optional[str] = Field(None, max_length=20, description="Numéro SIRET")
    naf: Optional[str] = Field(None, max_length=10, description="Code NAF")
    naf_title: Optional[str] = Field(None, max_length=255, description="Libellé NAF")
    max_suppliers: int = Field(10, ge=1, description="Nombre maximum de fournisseurs")
    max_auditors: int = Field(5, ge=1, description="Nombre maximum d'auditeurs")


class OrganizationCreate(OrganizationBase):
    """Schéma pour créer une organization"""
    # 🔒 SÉCURITÉ : tenant_id est RETIRÉ du payload public
    # Il sera forcé côté serveur depuis current_user.tenant_id
    is_active: bool = Field(True, description="Statut actif")

    # ✅ AJOUT : Tous les champs INSEE possibles (optionnels)
    siren: Optional[str] = Field(None, description="Numéro SIREN (9 chiffres)")
    ape_code: Optional[str] = Field(None, description="Code APE")
    denomination: Optional[str] = Field(None, description="Dénomination officielle")
    activite_principale: Optional[str] = Field(None, description="Activité principale")
    code_naf: Optional[str] = Field(None, description="Code NAF")
    libelle_naf: Optional[str] = Field(None, description="Libellé NAF complet")
    forme_juridique: Optional[str] = Field(None, description="Forme juridique")
    adresse: Optional[str] = Field(None, description="Adresse complète")
    address_line1: Optional[str] = Field(None, description="Ligne d'adresse 1")
    code_postal: Optional[str] = Field(None, description="Code postal")
    postal_code: Optional[str] = Field(None, description="Code postal (alias)")
    commune: Optional[str] = Field(None, description="Commune")
    city: Optional[str] = Field(None, description="Ville (alias)")
    date_creation: Optional[str] = Field(None, description="Date de création de l'entreprise")
    tranche_effectif: Optional[str] = Field(None, description="Tranche d'effectif INSEE")
    etat_administratif: Optional[str] = Field(None, description="État administratif (Actif/Cessé)")

    class Config:
        # 🔒 SÉCURITÉ : Changé de "allow" à "forbid" pour empêcher l'injection de champs arbitraires
        extra = "forbid"


class OrganizationUpdate(BaseModel):
    """Schéma pour mettre à jour une organization"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    domain: Optional[str] = Field(None, max_length=100)
    subscription_type: Optional[Literal["starter", "professional", "enterprise"]] = None
    email: Optional[str] = None  # ✅ Changé de EmailStr à str
    phone: Optional[str] = Field(None, max_length=50)
    country_code: Optional[str] = Field(None, max_length=2)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        """Validateur d'email personnalisé qui accepte les domaines .local pour le développement"""
        if v is None:
            return v

        # Pattern email basique qui accepte .local et autres domaines de développement
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        # Pattern pour accepter aussi .local
        local_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.local$'

        if re.match(email_pattern, v) or re.match(local_pattern, v):
            return v

        raise ValueError(f"Email invalide: {v}")

    sector: Optional[str] = Field(None, max_length=100)
    enterprise_category: Optional[str] = None
    workforce: Optional[int] = Field(None, ge=0)
    siret: Optional[str] = Field(None, max_length=20)
    naf: Optional[str] = Field(None, max_length=10)
    naf_title: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None
    max_suppliers: Optional[int] = Field(None, ge=1)
    max_auditors: Optional[int] = Field(None, ge=1)


class OrganizationResponse(OrganizationBase):
    """Schéma de réponse pour une organization"""
    id: UUID
    tenant_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    # ✅ AJOUT : Retourner les données INSEE dans la réponse
    insee_data: Optional[dict] = Field(None, description="Données INSEE enrichies (JSONB)")
    
    # Statistiques calculées (optionnelles)
    total_users: Optional[int] = Field(None, description="Nombre total d'utilisateurs")
    total_audits: Optional[int] = Field(None, description="Nombre total d'audits")
    
    class Config:
        from_attributes = True


class OrganizationListResponse(BaseModel):
    """Schéma de réponse pour une liste d'organizations"""
    items: list[OrganizationResponse]
    total: int
    skip: int
    limit: int


class OrganizationStats(BaseModel):
    """Statistiques globales des organizations"""
    total_clients: int
    active_clients: int
    inactive_clients: int
    total_users: int
    subscription_breakdown: dict[str, int]  # starter: 5, professional: 3, enterprise: 2
    
    
class TenantCreateData(BaseModel):
    """Données pour créer un tenant associé"""
    name: str = Field(..., description="Nom du tenant (généralement identique à l'organisation)")
    is_active: bool = Field(True)
    subscription_type: Literal["starter", "professional", "enterprise"] = Field("starter")
    max_users: int = Field(5, ge=1)
    max_organizations: int = Field(1, ge=1)