"""
Schémas Pydantic pour le module EBIOS RM

Analyse de risques selon méthodologie ANSSI avec 5 ateliers.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from uuid import UUID
from enum import Enum


# ==============================================================================
# ENUMS
# ==============================================================================

class ProjectStatus(str, Enum):
    """Statuts d'un projet EBIOS"""
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    FROZEN = "FROZEN"
    ARCHIVED = "ARCHIVED"


class WorkshopType(str, Enum):
    """Types d'ateliers EBIOS"""
    AT1 = "AT1"  # Cadrage et socle de sécurité
    AT2 = "AT2"  # Sources de risques
    AT3 = "AT3"  # Scénarios stratégiques
    AT4 = "AT4"  # Scénarios opérationnels
    AT5 = "AT5"  # Traitement des risques


class WorkshopStatus(str, Enum):
    """Statuts d'un atelier"""
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class CriticalityLevel(str, Enum):
    """Niveaux de criticité"""
    LOW = "LOW"          # Score 1-4
    MODERATE = "MODERATE"  # Score 5-8
    HIGH = "HIGH"        # Score 9-12
    CRITICAL = "CRITICAL"  # Score 13-16


class SecurityDimension(str, Enum):
    """Dimensions de sécurité (CIA)"""
    CONFIDENTIALITY = "CONFIDENTIALITY"
    INTEGRITY = "INTEGRITY"
    AVAILABILITY = "AVAILABILITY"


class TreatmentStrategy(str, Enum):
    """Stratégies de traitement des risques"""
    REDUCE = "REDUCE"
    ACCEPT = "ACCEPT"
    TRANSFER = "TRANSFER"
    AVOID = "AVOID"


class SourceType(str, Enum):
    """Source de création (manuel ou IA)"""
    MANUAL = "MANUAL"
    AI = "AI"


# ==============================================================================
# PROJECT SCHEMAS
# ==============================================================================

class RiskProjectBase(BaseModel):
    """Schéma de base pour un projet EBIOS"""
    label: str = Field(..., min_length=1, max_length=255, description="Nom du projet")
    description: Optional[str] = Field(None, description="Description du projet")
    start_date: Optional[date] = Field(None, description="Date de début")
    end_date: Optional[date] = Field(None, description="Date de fin")


class RiskProjectCreate(RiskProjectBase):
    """Schéma pour la création d'un projet EBIOS"""
    scope_entity_ids: Optional[List[UUID]] = Field(None, description="IDs des entités du périmètre")
    pilot_user_ids: Optional[List[UUID]] = Field(None, description="IDs des pilotes")
    contributor_user_ids: Optional[List[UUID]] = Field(None, description="IDs des contributeurs")
    ai_initial_context: Optional[Dict[str, Any]] = Field(None, description="Contexte IA initial")


class RiskProjectUpdate(BaseModel):
    """Schéma pour la mise à jour d'un projet EBIOS"""
    label: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    scope_entity_ids: Optional[List[UUID]] = None
    pilot_user_ids: Optional[List[UUID]] = None
    contributor_user_ids: Optional[List[UUID]] = None


class RiskProjectResponse(RiskProjectBase):
    """Schéma de réponse pour un projet EBIOS"""
    id: UUID
    tenant_id: UUID
    method: str = "EBIOS_RM"
    status: ProjectStatus
    scope_entity_ids: Optional[List[UUID]] = None
    pilot_user_ids: Optional[List[UUID]] = None
    contributor_user_ids: Optional[List[UUID]] = None
    ai_initial_context: Optional[Dict[str, Any]] = Field(None, description="Contexte IA initial (messages échangés lors de la création)")
    frozen_at: Optional[datetime] = None
    frozen_by: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Champs calculés
    progress_percent: Optional[int] = Field(0, description="Progression globale en %")
    workshops_status: Optional[Dict[str, str]] = Field(None, description="Statut de chaque atelier")
    workshops_progress: Optional[Dict[str, int]] = Field(None, description="Progression de chaque atelier en %")

    class Config:
        from_attributes = True


class RiskProjectListResponse(BaseModel):
    """Schéma de réponse pour la liste des projets EBIOS"""
    items: List[RiskProjectResponse]
    total: int
    skip: int = 0
    limit: int = 100


# ==============================================================================
# WORKSHOP SCHEMAS
# ==============================================================================

class WorkshopResponse(BaseModel):
    """Schéma de réponse pour un atelier"""
    id: UUID
    project_id: UUID
    type: WorkshopType
    status: WorkshopStatus
    completion_percent: int = 0
    ai_last_generation_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==============================================================================
# ATELIER 1 - CADRAGE
# ==============================================================================

class BusinessValueBase(BaseModel):
    """Schéma de base pour une valeur métier"""
    label: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    criticality: int = Field(2, ge=1, le=4, description="Niveau de criticité (1-4)")


class BusinessValueCreate(BusinessValueBase):
    """Schéma pour la création d'une valeur métier"""
    pass


class BusinessValueUpdate(BaseModel):
    """Schéma pour la mise à jour d'une valeur métier"""
    label: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    criticality: Optional[int] = Field(None, ge=1, le=4)


class BusinessValueResponse(BusinessValueBase):
    """Schéma de réponse pour une valeur métier"""
    id: UUID
    project_id: UUID
    order_index: int = 0
    source: SourceType = SourceType.MANUAL
    is_selected: bool = True  # Sélection pour génération AT2
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AssetBase(BaseModel):
    """Schéma de base pour un bien support"""
    label: str = Field(..., min_length=1, max_length=255)
    type: Optional[str] = Field(None, description="Type de bien (Serveur, Application, etc.)")
    description: Optional[str] = None
    criticality: int = Field(2, ge=1, le=4)
    linked_organism_id: Optional[UUID] = None


class AssetCreate(AssetBase):
    """Schéma pour la création d'un bien support"""
    pass


class AssetUpdate(BaseModel):
    """Schéma pour la mise à jour d'un bien support"""
    label: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[str] = None
    description: Optional[str] = None
    criticality: Optional[int] = Field(None, ge=1, le=4)
    linked_organism_id: Optional[UUID] = None


class AssetResponse(AssetBase):
    """Schéma de réponse pour un bien support"""
    id: UUID
    project_id: UUID
    order_index: int = 0
    source: SourceType = SourceType.MANUAL
    is_selected: bool = True  # Sélection pour génération AT2
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FearedEventBase(BaseModel):
    """Schéma de base pour un événement redouté"""
    label: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    dimension: Optional[SecurityDimension] = None
    severity: int = Field(2, ge=1, le=4, description="Gravité (1-4)")
    justification: Optional[str] = None
    linked_business_value_id: Optional[UUID] = None
    linked_asset_id: Optional[UUID] = None


class FearedEventCreate(FearedEventBase):
    """Schéma pour la création d'un événement redouté"""
    pass


class FearedEventUpdate(BaseModel):
    """Schéma pour la mise à jour d'un événement redouté"""
    label: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    dimension: Optional[SecurityDimension] = None
    severity: Optional[int] = Field(None, ge=1, le=4)
    justification: Optional[str] = None
    linked_business_value_id: Optional[UUID] = None
    linked_asset_id: Optional[UUID] = None


class FearedEventResponse(FearedEventBase):
    """Schéma de réponse pour un événement redouté"""
    id: UUID
    project_id: UUID
    order_index: int = 0
    source: SourceType = SourceType.MANUAL
    is_selected: bool = True  # Sélection pour génération AT2
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Champs enrichis
    business_value_label: Optional[str] = None
    asset_label: Optional[str] = None

    class Config:
        from_attributes = True


class AT1Response(BaseModel):
    """Schéma de réponse pour l'atelier 1 complet"""
    workshop: WorkshopResponse
    business_values: List[BusinessValueResponse]
    assets: List[AssetResponse]
    feared_events: List[FearedEventResponse]


# ==============================================================================
# ATELIER 2 - SOURCES DE RISQUES
# ==============================================================================

class RiskSourceObjectiveBase(BaseModel):
    """Schéma de base pour un objectif de source de risque"""
    label: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    is_selected: bool = True


class RiskSourceObjectiveCreate(RiskSourceObjectiveBase):
    """Schéma pour la création d'un objectif"""
    pass


class RiskSourceObjectiveResponse(RiskSourceObjectiveBase):
    """Schéma de réponse pour un objectif"""
    id: UUID
    source_id: UUID
    order_index: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RiskSourceBase(BaseModel):
    """Schéma de base pour une source de risque"""
    label: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    relevance: int = Field(2, ge=1, le=4, description="Pertinence (1-4)")
    justification: Optional[str] = None
    is_selected: bool = True


class RiskSourceCreate(RiskSourceBase):
    """Schéma pour la création d'une source de risque"""
    objectives: Optional[List[RiskSourceObjectiveCreate]] = None


class RiskSourceUpdate(BaseModel):
    """Schéma pour la mise à jour d'une source de risque"""
    label: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    relevance: Optional[int] = Field(None, ge=1, le=4)
    justification: Optional[str] = None
    is_selected: Optional[bool] = None


class RiskSourceResponse(RiskSourceBase):
    """Schéma de réponse pour une source de risque"""
    id: UUID
    project_id: UUID
    order_index: int = 0
    source: SourceType = SourceType.MANUAL
    objectives: List[RiskSourceObjectiveResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AT2Response(BaseModel):
    """Schéma de réponse pour l'atelier 2 complet"""
    workshop: WorkshopResponse
    risk_sources: List[RiskSourceResponse]


# ==============================================================================
# ATELIER 3 - SCÉNARIOS STRATÉGIQUES
# ==============================================================================

class StrategicScenarioBase(BaseModel):
    """Schéma de base pour un scénario stratégique"""
    code: str = Field(..., max_length=20, description="Code du scénario (SS01, SS02...)")
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    attack_path: Optional[Dict[str, Any]] = Field(None, description="Chemin d'attaque JSON")
    feared_event_id: Optional[UUID] = None
    risk_source_id: Optional[UUID] = None
    severity: Optional[int] = Field(None, ge=1, le=4)
    likelihood_raw: Optional[int] = Field(None, ge=1, le=4)
    justification: Optional[str] = None


class StrategicScenarioCreate(StrategicScenarioBase):
    """Schéma pour la création d'un scénario stratégique"""
    pass


class StrategicScenarioUpdate(BaseModel):
    """Schéma pour la mise à jour d'un scénario stratégique"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    attack_path: Optional[Dict[str, Any]] = None
    feared_event_id: Optional[UUID] = None
    risk_source_id: Optional[UUID] = None
    severity: Optional[int] = Field(None, ge=1, le=4)
    likelihood_raw: Optional[int] = Field(None, ge=1, le=4)
    justification: Optional[str] = None


class StrategicScenarioResponse(StrategicScenarioBase):
    """Schéma de réponse pour un scénario stratégique"""
    id: UUID
    project_id: UUID
    order_index: int = 0
    source: SourceType = SourceType.MANUAL
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Champs enrichis
    feared_event_label: Optional[str] = None
    risk_source_label: Optional[str] = None

    class Config:
        from_attributes = True


class AT3Response(BaseModel):
    """Schéma de réponse pour l'atelier 3 complet"""
    workshop: WorkshopResponse
    strategic_scenarios: List[StrategicScenarioResponse]


# ==============================================================================
# ATELIER 4 - SCÉNARIOS OPÉRATIONNELS
# ==============================================================================

class OperationalStepBase(BaseModel):
    """Schéma de base pour une étape opérationnelle"""
    order_index: int = Field(0, ge=0)
    action: str = Field(..., min_length=1, max_length=255)
    technique: Optional[str] = Field(None, max_length=255, description="Technique MITRE ATT&CK")
    description: Optional[str] = None


class OperationalStepCreate(OperationalStepBase):
    """Schéma pour la création d'une étape"""
    pass


class OperationalStepResponse(OperationalStepBase):
    """Schéma de réponse pour une étape"""
    id: UUID
    operational_scenario_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OperationalScenarioBase(BaseModel):
    """Schéma de base pour un scénario opérationnel"""
    code: str = Field(..., max_length=20, description="Code du scénario (SO01, SO02...)")
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    likelihood: Optional[int] = Field(None, ge=1, le=4)
    justification: Optional[str] = None


class OperationalScenarioCreate(OperationalScenarioBase):
    """Schéma pour la création d'un scénario opérationnel"""
    strategic_scenario_id: UUID
    steps: Optional[List[OperationalStepCreate]] = None


class OperationalScenarioUpdate(BaseModel):
    """Schéma pour la mise à jour d'un scénario opérationnel"""
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    likelihood: Optional[int] = Field(None, ge=1, le=4)
    justification: Optional[str] = None


class OperationalScenarioResponse(OperationalScenarioBase):
    """Schéma de réponse pour un scénario opérationnel"""
    id: UUID
    strategic_scenario_id: UUID
    order_index: int = 0
    source: SourceType = SourceType.MANUAL
    steps: List[OperationalStepResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Champs enrichis
    strategic_scenario_code: Optional[str] = None
    strategic_scenario_title: Optional[str] = None

    class Config:
        from_attributes = True


class AT4Response(BaseModel):
    """Schéma de réponse pour l'atelier 4 complet"""
    workshop: WorkshopResponse
    operational_scenarios: List[OperationalScenarioResponse]


# ==============================================================================
# ATELIER 5 - RISQUES ET MATRICE
# ==============================================================================

class RiskBase(BaseModel):
    """Schéma de base pour un risque"""
    code: str = Field(..., max_length=20, description="Code du risque (R01, R02...)")
    label: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    severity: int = Field(..., ge=1, le=4, description="Gravité (1-4)")
    likelihood: int = Field(..., ge=1, le=4, description="Vraisemblance (1-4)")
    justification: Optional[str] = None
    strategic_scenario_id: Optional[UUID] = None
    operational_scenario_id: Optional[UUID] = None
    feared_event_id: Optional[UUID] = None


class RiskCreate(RiskBase):
    """Schéma pour la création d'un risque"""
    pass


class RiskUpdateResidual(BaseModel):
    """Schéma pour la mise à jour du risque résiduel"""
    residual_severity: Optional[int] = Field(None, ge=1, le=4)
    residual_likelihood: Optional[int] = Field(None, ge=1, le=4)
    residual_justification: Optional[str] = None
    treatment_strategy: Optional[TreatmentStrategy] = None


class RiskResponse(RiskBase):
    """Schéma de réponse pour un risque"""
    id: UUID
    project_id: UUID
    score: int = Field(..., ge=1, le=16, description="Score brut = severity × likelihood")
    criticality_level: CriticalityLevel

    # Risque résiduel
    residual_severity: Optional[int] = None
    residual_likelihood: Optional[int] = None
    residual_score: Optional[int] = None
    residual_justification: Optional[str] = None
    treatment_strategy: Optional[TreatmentStrategy] = None
    treatment_status: Optional[str] = None

    order_index: int = 0
    source: SourceType = SourceType.AI
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Champs enrichis
    strategic_scenario_code: Optional[str] = None
    operational_scenario_code: Optional[str] = None
    feared_event_label: Optional[str] = None

    # Actions liées
    linked_actions_count: int = 0

    class Config:
        from_attributes = True


class MatrixCell(BaseModel):
    """Cellule de la matrice des risques"""
    severity: int = Field(..., ge=1, le=4)
    likelihood: int = Field(..., ge=1, le=4)
    score: int = Field(..., ge=1, le=16)
    risks: List[RiskResponse] = []
    color: str = Field(..., description="Couleur CSS de la cellule")


class MatrixResponse(BaseModel):
    """Schéma de réponse pour la matrice des risques"""
    project_id: UUID
    is_frozen: bool = False
    frozen_at: Optional[datetime] = None
    cells: List[MatrixCell] = []
    stats: Dict[str, Any] = Field(default_factory=dict)


class AT5Response(BaseModel):
    """Schéma de réponse pour l'atelier 5 complet"""
    workshop: WorkshopResponse
    risks: List[RiskResponse]
    matrix: Optional[MatrixResponse] = None


# ==============================================================================
# AI GENERATION SCHEMAS
# ==============================================================================

class AIGenerateRequest(BaseModel):
    """Schéma pour une demande de génération IA"""
    context: Optional[str] = Field(None, description="Contexte additionnel")
    regenerate: bool = Field(False, description="Régénérer même si déjà généré")


class AIGeneratedItem(BaseModel):
    """Schéma pour un élément généré par l'IA"""
    label: str
    description: Optional[str] = None
    criticality: Optional[int] = None
    severity: Optional[int] = None
    likelihood: Optional[int] = None
    justification: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0, le=1, description="Score de confiance")


class AIGenerateResponse(BaseModel):
    """Schéma de réponse pour une génération IA"""
    success: bool
    items_generated: int
    items: List[AIGeneratedItem]
    ai_raw_input: Optional[Dict[str, Any]] = None
    ai_raw_output: Optional[Dict[str, Any]] = None


# ==============================================================================
# FREEZE SCHEMA
# ==============================================================================

class FreezeRequest(BaseModel):
    """Schéma pour demander le gel d'une analyse"""
    confirm: bool = Field(True, description="Confirmation du gel")


class FreezeResponse(BaseModel):
    """Schéma de réponse pour le gel d'une analyse"""
    success: bool
    message: str
    frozen_at: datetime
    matrix_snapshot_id: UUID
    risks_count: int
    stats: Dict[str, Any]


# ==============================================================================
# ACTIONS LINK SCHEMAS
# ==============================================================================

class ActionLinkCreate(BaseModel):
    """Schéma pour lier une action à un risque"""
    action_id: UUID
    code_action: str = Field(..., max_length=50, description="Code de l'action ACT_RISK_XXX")


class ActionLinkResponse(BaseModel):
    """Schéma de réponse pour un lien risque-action"""
    id: UUID
    risk_id: UUID
    action_id: UUID
    code_action: str
    created_at: datetime

    class Config:
        from_attributes = True


# ==============================================================================
# AI CHAT SCHEMAS
# ==============================================================================

class AIChatMessage(BaseModel):
    """Message dans le chat IA"""
    role: str = Field(..., description="'user' ou 'assistant'")
    content: str = Field(..., description="Contenu du message")


class AIChatRequest(BaseModel):
    """Requête pour le chat IA EBIOS"""
    message: str = Field(..., min_length=1, description="Message de l'utilisateur")
    context: Optional[str] = Field(None, description="Contexte du projet (nom, description)")
    history: Optional[List[AIChatMessage]] = Field(default=[], description="Historique des messages")


class AIChatResponse(BaseModel):
    """Réponse du chat IA EBIOS"""
    success: bool
    response: str = Field(..., description="Réponse de l'IA")
    error: Optional[str] = None
