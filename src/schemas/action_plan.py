"""
Schémas Pydantic pour le module Plan d'Action IA
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from uuid import UUID
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class ActionPlanStatus(str, Enum):
    """Statuts possibles d'un plan d'action"""
    NOT_STARTED = "NOT_STARTED"
    GENERATING = "GENERATING"
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class ActionPlanItemStatus(str, Enum):
    """Statuts possibles d'un item de plan d'action"""
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    EXCLUDED = "EXCLUDED"
    PUBLISHED = "PUBLISHED"


class ActionSeverity(str, Enum):
    """Sévérité d'une action"""
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class ActionPriority(str, Enum):
    """Priorité d'une action"""
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class AssignmentMethod(str, Enum):
    """Méthode d'assignation d'une action"""
    DIRECT = "direct"
    FALLBACK_MANAGER = "fallback_manager"
    FALLBACK_OWNER = "fallback_owner"
    AUDIT_RESP = "audit_resp"
    MANUAL = "manual"
    UNASSIGNED = "unassigned"


class PhaseStatus(str, Enum):
    """Statut d'une phase de génération"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================================
# SCHÉMAS DE PROGRESSION (pour état GENERATING)
# ============================================================================

class GenerationProgress(BaseModel):
    """Progression de la génération (4 phases)"""
    current_phase: int = Field(..., description="Phase actuelle (1-4)")

    # Statuts des phases
    phase1_status: PhaseStatus = Field(PhaseStatus.PENDING, description="Statut phase 1 : Analyse des réponses")
    phase2_status: PhaseStatus = Field(PhaseStatus.PENDING, description="Statut phase 2 : Consolidation des écarts")
    phase3_status: PhaseStatus = Field(PhaseStatus.PENDING, description="Statut phase 3 : Génération des actions")
    phase4_status: PhaseStatus = Field(PhaseStatus.PENDING, description="Statut phase 4 : Assignation des responsables")

    # Métriques Phase 1
    questions_analyzed: int = Field(0, description="Nombre de questions analysées")
    total_questions: int = Field(0, description="Nombre total de questions")
    non_conformities_found: int = Field(0, description="Nombre de non-conformités identifiées")

    # Métriques Phase 3
    actions_generated: int = Field(0, description="Nombre d'actions générées")

    # Métriques Phase 4
    actions_assigned: int = Field(0, description="Nombre d'actions assignées")

    # Temps estimé restant (en secondes)
    estimated_time_remaining: Optional[int] = Field(None, description="Temps estimé restant en secondes")

    # Message d'erreur éventuel
    error_message: Optional[str] = Field(None, description="Message d'erreur si échec")


# ============================================================================
# SCHÉMAS POUR ACTION PLAN
# ============================================================================

class ActionPlanBase(BaseModel):
    """Schéma de base pour un plan d'action"""
    summary_title: Optional[str] = Field(None, max_length=500, description="Titre du plan d'action")
    overall_risk_level: Optional[str] = Field(None, max_length=50, description="Niveau de risque global")
    dominant_language: Optional[str] = Field(None, max_length=10, description="Langue dominante")


class ActionPlanResponse(ActionPlanBase):
    """Réponse complète pour un plan d'action"""
    id: UUID
    campaign_id: UUID
    tenant_id: UUID
    status: ActionPlanStatus

    # Statistiques
    total_actions: int
    critical_count: int
    major_count: int
    minor_count: int
    info_count: int

    # Progression (si GENERATING)
    generation_progress: Optional[GenerationProgress] = None

    # Dates
    generated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Auditeurs
    generated_by: Optional[UUID] = None
    published_by: Optional[UUID] = None

    class Config:
        from_attributes = True


class ActionPlanSummary(BaseModel):
    """Résumé léger d'un plan d'action (pour ligne récapitulative)"""
    id: UUID
    campaign_id: UUID
    status: ActionPlanStatus
    summary_title: Optional[str] = None
    overall_risk_level: Optional[str] = None

    total_actions: int
    critical_count: int
    major_count: int
    minor_count: int

    generated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ActionPlanGenerateRequest(BaseModel):
    """Requête pour générer un plan d'action"""
    campaign_id: UUID


class ActionPlanGenerateResponse(BaseModel):
    """Réponse après démarrage de la génération"""
    campaign_id: UUID
    action_plan_id: UUID
    status: ActionPlanStatus = Field(ActionPlanStatus.GENERATING)
    message: str = Field(..., description="Message de confirmation")

    class Config:
        json_schema_extra = {
            "example": {
                "campaign_id": "camp-123",
                "action_plan_id": "ap-001",
                "status": "GENERATING",
                "message": "Génération du plan d'action en cours"
            }
        }


# ============================================================================
# SCHÉMAS POUR ACTION PLAN ITEMS
# ============================================================================

class ActionPlanItemBase(BaseModel):
    """Schéma de base pour un item de plan d'action"""
    title: str = Field(..., min_length=1, max_length=500, description="Titre de l'action")
    description: str = Field(..., min_length=1, description="Description détaillée de l'action")
    objective: Optional[str] = Field(None, description="Objectif de l'action (HTML riche)")
    deliverables: Optional[str] = Field(None, description="Livrables attendus (HTML riche)")
    severity: ActionSeverity
    priority: ActionPriority
    recommended_due_days: int = Field(..., ge=1, le=365, description="Délai recommandé en jours")
    suggested_role: str = Field(..., max_length=100, description="Rôle suggéré")


class ActionPlanItemCreate(ActionPlanItemBase):
    """Schéma pour créer un item de plan d'action"""
    action_plan_id: UUID
    source_question_ids: List[UUID] = Field(default_factory=list)
    referential_controls: List[str] = Field(default_factory=list)
    ai_justifications: Optional[Dict[str, str]] = None


class ActionPlanItemUpdate(BaseModel):
    """Schéma pour mettre à jour un item (édition DRAFT)"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = Field(None, min_length=1)
    objective: Optional[str] = None
    deliverables: Optional[str] = None
    severity: Optional[ActionSeverity] = None
    priority: Optional[ActionPriority] = None
    recommended_due_days: Optional[int] = Field(None, ge=1, le=365)
    suggested_role: Optional[str] = Field(None, max_length=100)
    assigned_user_id: Optional[UUID] = None
    included: Optional[bool] = None


class AssignedUser(BaseModel):
    """Informations sur l'utilisateur assigné"""
    id: UUID
    first_name: str
    last_name: str
    email: str

    class Config:
        from_attributes = True


class ActionPlanItemResponse(ActionPlanItemBase):
    """Réponse complète pour un item de plan d'action"""
    id: UUID
    action_plan_id: UUID
    tenant_id: UUID
    status: ActionPlanItemStatus
    order_index: int
    included: bool

    # Assignation
    assigned_user_id: Optional[UUID] = None
    assigned_user: Optional[AssignedUser] = None
    assignment_method: AssignmentMethod

    # Sources et contrôles
    source_question_ids: List[UUID]
    referential_controls: List[str]

    # Justifications IA
    ai_justifications: Optional[Dict[str, str]] = None

    # Action créée (si PUBLISHED)
    created_action_id: Optional[UUID] = None

    # Dates
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ActionPlanItemsListResponse(BaseModel):
    """Liste des items d'un plan d'action"""
    items: List[ActionPlanItemResponse]
    total: int

    # Statistiques d'assignation
    assigned_count: int = Field(..., description="Nombre d'actions assignées")
    unassigned_count: int = Field(..., description="Nombre d'actions non assignées")


# ============================================================================
# SCHÉMAS POUR PUBLICATION
# ============================================================================

class ActionPlanPublishResponse(BaseModel):
    """Réponse après publication d'un plan d'action"""
    action_plan_id: UUID
    campaign_id: UUID
    published_at: datetime
    created_actions_count: int = Field(..., description="Nombre d'actions créées")
    message: str = Field(..., description="Message de confirmation")

    class Config:
        json_schema_extra = {
            "example": {
                "action_plan_id": "ap-001",
                "campaign_id": "camp-123",
                "published_at": "2025-11-23T09:30:00Z",
                "created_actions_count": 5,
                "message": "Plan d'action publié avec succès. 5 actions ont été créées."
            }
        }


# ============================================================================
# SCHÉMA POUR RÉCUPÉRATION PLAN (peut être null)
# ============================================================================

class ActionPlanGetResponse(BaseModel):
    """Réponse pour GET /action-plan (peut être null si pas de plan)"""
    action_plan: Optional[ActionPlanResponse] = Field(None, description="Plan d'action (null si inexistant)")
    campaign_status: Optional[str] = Field(None, description="Statut de la campagne (draft, ongoing, frozen, etc.)")
    can_generate: Optional[bool] = Field(None, description="Si true, la génération est autorisée (campagne figée)")
