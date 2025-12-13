"""
Schémas Pydantic pour la gestion des campagnes d'audit
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date
from uuid import UUID


class CampaignBase(BaseModel):
    """Schéma de base pour une campagne"""
    title: str = Field(..., min_length=1, max_length=255, description="Titre de la campagne")
    description: Optional[str] = Field(None, description="Description de la campagne")
    questionnaire_id: UUID = Field(..., description="ID du questionnaire associé")
    audit_type: str = Field("external", description="Type d'audit: internal (interne) ou external (externe)")
    recurrence_type: Optional[str] = Field(None, description="Type de récurrence: once, monthly, quarterly, yearly")
    recurrence_interval: int = Field(1, ge=1, description="Intervalle de récurrence")
    launch_date: Optional[date] = Field(None, description="Date de lancement")
    due_date: Optional[date] = Field(None, description="Date d'échéance")


class CampaignCreate(CampaignBase):
    """Schéma pour la création d'une campagne"""
    scope_id: Optional[UUID] = Field(None, description="ID du scope (périmètre)")
    recurrence_end_date: Optional[date] = Field(None, description="Date de fin de récurrence")


class CampaignUpdate(BaseModel):
    """Schéma pour la mise à jour d'une campagne"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(None, description="Status: draft, ongoing, late, frozen, completed, cancelled")
    launch_date: Optional[date] = None
    due_date: Optional[date] = None
    frozen_date: Optional[date] = None


class CampaignResponse(CampaignBase):
    """Schéma de réponse pour une campagne"""
    id: UUID
    tenant_id: UUID
    status: str
    scope_id: Optional[UUID] = None
    next_occurrence_date: Optional[date] = None
    recurrence_end_date: Optional[date] = None
    frozen_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None

    # Champs calculés
    questionnaire_name: Optional[str] = None
    questions_total: int = 0
    questions_answered: int = 0
    progress: int = 0

    # Champs pour l'édition (chargés depuis les relations)
    pilot_user_ids: Optional[List[UUID]] = None
    entity_ids: Optional[List[UUID]] = None
    auditor_ids: Optional[List[UUID]] = None
    campaign_type: Optional[str] = None  # 'internal' ou 'external'
    pole_ids: Optional[List[UUID]] = None
    category_ids: Optional[List[UUID]] = None

    class Config:
        from_attributes = True


class CampaignListResponse(BaseModel):
    """Schéma de réponse pour la liste des campagnes"""
    items: List[CampaignResponse]
    total: int
    skip: int = 0
    limit: int = 100


class CampaignStatsResponse(BaseModel):
    """Schéma de réponse pour les statistiques des campagnes"""
    total: int
    draft: int
    ongoing: int
    late: int
    frozen: int
    completed: int
    cancelled: int


class CampaignKPIs(BaseModel):
    """KPIs pour la page de détail de campagne"""
    global_progress: int = Field(0, description="Progression globale en %")
    total_questions: int = Field(0, description="Nombre total de questions")
    answered_questions: int = Field(0, description="Nombre de questions répondues")
    validated_questions: int = Field(0, description="Nombre de questions validées")
    entities_count: int = Field(0, description="Nombre d'organismes audités")
    entities_completed: int = Field(0, description="Nombre d'organismes ayant terminé")
    contributors_active: int = Field(0, description="Nombre de contributeurs actifs")
    contributors_total: int = Field(0, description="Nombre total de contributeurs")
    nc_major: int = Field(0, description="Nombre de non-conformités majeures")
    nc_minor: int = Field(0, description="Nombre de non-conformités mineures")
    documents_provided: int = Field(0, description="Nombre de documents fournis")
    documents_required: int = Field(0, description="Nombre de documents requis")
    days_elapsed: int = Field(0, description="Nombre de jours écoulés depuis le lancement")
    days_remaining: Optional[int] = Field(None, description="Nombre de jours restants avant échéance")


class StakeholderResponse(BaseModel):
    """Schéma pour un stakeholder de campagne"""
    id: UUID
    user_id: UUID
    first_name: str
    last_name: str
    email: str
    role: str = Field(..., description="Rôle: owner, manager, auditor, viewer")
    assigned_at: datetime

    class Config:
        from_attributes = True


class CampaignDetailsResponse(BaseModel):
    """Schéma de réponse complet pour les détails d'une campagne"""
    campaign: CampaignResponse
    kpis: CampaignKPIs
    stakeholders: List[StakeholderResponse]


# ============================================================================
# SCHÉMAS POUR ONGLET PROGRESSION
# ============================================================================

class EntityProgressResponse(BaseModel):
    """Progression d'un organisme dans la campagne"""
    entity_id: UUID
    entity_name: str
    invited_at: datetime
    progress_percent: int = Field(0, description="Pourcentage de progression (0-100)")
    questions_answered: int = Field(0, description="Nombre de questions répondues")
    questions_total: int = Field(0, description="Nombre total de questions assignées")
    last_activity: Optional[datetime] = Field(None, description="Date de dernière activité")
    is_inactive: bool = Field(False, description="True si aucune activité depuis 3+ jours")

    class Config:
        from_attributes = True


class ContributorProgressResponse(BaseModel):
    """Progression d'un contributeur dans la campagne"""
    user_id: UUID
    first_name: str
    last_name: str
    email: str
    entity_id: UUID
    entity_name: str
    progress_percent: int = Field(0, description="Pourcentage de progression (0-100)")
    questions_answered: int = Field(0, description="Nombre de questions répondues")
    questions_total: int = Field(0, description="Nombre total de questions assignées")
    is_active: bool = Field(True, description="True si activité dans les 7 derniers jours")
    last_activity: Optional[datetime] = Field(None, description="Date de dernière activité")

    class Config:
        from_attributes = True


class CampaignProgressResponse(BaseModel):
    """Données complètes de progression pour l'onglet Progression"""
    entities: List[EntityProgressResponse]
    contributors: List[ContributorProgressResponse]


# ============================================================================
# SCHÉMAS POUR ONGLET PÉRIMÈTRE
# ============================================================================

class EntityScopeResponse(BaseModel):
    """Informations sur un organisme du périmètre"""
    entity_id: UUID
    entity_name: str
    entity_type: Optional[str] = Field(None, description="Type: fournisseur, client, filiale, etc.")
    country: Optional[str] = Field(None, description="Pays")
    sector: Optional[str] = Field(None, description="Secteur d'activité")
    added_at: datetime = Field(..., description="Date d'ajout au périmètre")
    contributors_count: int = Field(0, description="Nombre de contributeurs assignés")
    last_audit_date: Optional[datetime] = Field(None, description="Date du dernier audit")
    last_audit_score: Optional[int] = Field(None, description="Score du dernier audit (0-100)")

    class Config:
        from_attributes = True


class CampaignScopeResponse(BaseModel):
    """Liste des organismes du périmètre pour l'onglet Périmètre"""
    entities: List[EntityScopeResponse]
    total_count: int = Field(..., description="Nombre total d'organismes")


# ============================================================================
# SCHÉMAS POUR COUVERTURE CROSS-RÉFÉRENTIELLE
# ============================================================================

class FrameworkCoverageResponse(BaseModel):
    """Couverture d'un framework par les Control Points de la campagne"""
    framework_code: str = Field(..., description="Code du framework (ex: 27002, PSSI)")
    framework_name: str = Field(..., description="Nom du framework")
    requirements_covered: int = Field(..., description="Nombre de requirements couverts")
    total_requirements: int = Field(..., description="Nombre total de requirements du framework")
    coverage_percentage: float = Field(..., description="Pourcentage de couverture (0-100)")

    class Config:
        from_attributes = True


class CampaignCrossReferentialResponse(BaseModel):
    """Couverture cross-référentielle pour une campagne"""
    campaign_id: UUID
    campaign_title: str
    base_framework_code: Optional[str] = Field(None, description="Code du framework de base de la campagne")
    base_framework_name: Optional[str] = Field(None, description="Nom du framework de base")
    total_requirements_in_campaign: int = Field(..., description="Nombre de requirements inclus dans le questionnaire")
    total_control_points: int = Field(..., description="Nombre de Control Points liés à la campagne")
    frameworks_coverage: List[FrameworkCoverageResponse] = Field(..., description="Liste des couvertures par framework")

    class Config:
        from_attributes = True


# ============================================================================
# SCHÉMAS POUR ONGLET DOCUMENTS
# ============================================================================

class DocumentResponse(BaseModel):
    """Informations sur un document uploadé"""
    id: UUID
    answer_id: UUID
    audit_id: UUID
    question_id: UUID
    question_text: str
    question_order: int

    # Métadonnées fichier
    filename: str = Field(..., description="Nom du fichier stocké")
    original_filename: str = Field(..., description="Nom original du fichier")
    file_size: int = Field(..., description="Taille en octets")
    file_size_mb: float = Field(..., description="Taille en MB")
    mime_type: str
    file_extension: Optional[str] = None

    # Catégorisation
    attachment_type: str = Field(..., description="Type: evidence, policy, report, certificate, etc.")
    description: Optional[str] = None

    # Sécurité
    virus_scan_status: str = Field(..., description="Status: pending, clean, infected, error, skipped")
    is_safe: bool = Field(..., description="True si le fichier est sûr à télécharger")

    # Upload
    uploaded_by: Optional[UUID] = None
    uploaded_by_name: Optional[str] = None
    uploaded_by_email: Optional[str] = None
    uploaded_at: datetime

    # Entité
    entity_id: Optional[UUID] = None
    entity_name: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentStats(BaseModel):
    """Statistiques globales des documents"""
    total_questions_requiring_docs: int = Field(0, description="Questions nécessitant des preuves")
    questions_with_docs: int = Field(0, description="Questions ayant au moins un document")
    total_documents: int = Field(0, description="Nombre total de documents uploadés")
    total_size_mb: float = Field(0, description="Taille totale en MB")
    by_type: dict = Field(default_factory=dict, description="Répartition par type de document")
    by_entity: dict = Field(default_factory=dict, description="Répartition par entité")


class CampaignDocumentsResponse(BaseModel):
    """Liste des documents pour l'onglet Documents"""
    stats: DocumentStats
    documents: List[DocumentResponse]
    total_count: int = Field(..., description="Nombre total de documents")


# ============================================================================
# SCHÉMAS POUR ACTIONS DE CAMPAGNE
# ============================================================================

class CampaignFreezeResponse(BaseModel):
    """Réponse après le gel d'une campagne"""
    success: bool = Field(True, description="True si l'opération a réussi")
    message: str = Field(..., description="Message de confirmation")
    campaign_id: UUID = Field(..., description="ID de la campagne figée")
    frozen_date: date = Field(..., description="Date de gel de la campagne")
    status: str = Field("frozen", description="Nouveau statut de la campagne")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Campagne figée avec succès",
                "campaign_id": "dcdb2976-1b43-4fda-8816-f71058b63ae5",
                "frozen_date": "2024-11-22",
                "status": "frozen"
            }
        }
