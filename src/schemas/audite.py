"""Schémas Pydantic pour la vue audité"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


# ============================================================================
# SCHÉMAS DE RÉPONSE
# ============================================================================

class QuestionAnswerCreate(BaseModel):
    """Création d'une réponse (sauvegarde brouillon)"""
    question_id: UUID
    audit_id: UUID
    campaign_id: Optional[UUID] = None
    answer_value: Dict[str, Any]  # Format flexible: {"bool": true}, {"text": "..."}, etc.
    status: str = Field(default="draft")  # draft, submitted

    class Config:
        json_schema_extra = {
            "example": {
                "question_id": "123e4567-e89b-12d3-a456-426614174000",
                "audit_id": "123e4567-e89b-12d3-a456-426614174001",
                "answer_value": {"bool": True},
                "status": "draft"
            }
        }


class QuestionAnswerUpdate(BaseModel):
    """Mise à jour d'une réponse"""
    answer_value: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    comment: Optional[str] = None


class QuestionAnswerResponse(BaseModel):
    """Réponse complète"""
    id: UUID
    question_id: UUID
    audit_id: UUID
    answered_by: Optional[UUID]
    answer_value: Dict[str, Any]
    status: str
    version: int
    is_current: bool
    comment: Optional[str]
    answered_at: datetime
    submitted_at: Optional[datetime]
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# SCHÉMAS DE QUESTION (VUE AUDITÉ)
# ============================================================================

class QuestionOption(BaseModel):
    """Option pour les questions à choix"""
    label: str
    value: str


class QuestionForAuditeResponse(BaseModel):
    """Question avec contexte pour l'audité"""
    id: UUID
    question_text: str
    response_type: str
    is_required: bool
    help_text: Optional[str]
    options: Optional[List[QuestionOption]]  # Liste d'objets {label, value}
    upload_conditions: Optional[Dict[str, Any]]
    order_index: int

    # Réponse actuelle (si existe)
    current_answer: Optional[QuestionAnswerResponse] = None

    class Config:
        from_attributes = True


class DomainNode(BaseModel):
    """Noeud de l'arbre des domaines"""
    id: str  # ID du domaine ou requirement
    name: str
    type: str = Field(..., description="domain ou requirement")
    order_index: int
    children: List["DomainNode"] = []
    question_count: int = 0
    answered_count: int = 0
    has_mandatory_unanswered: bool = False


class QuestionnaireForAuditeResponse(BaseModel):
    """Questionnaire complet pour l'audité avec arbre de navigation"""
    id: UUID
    name: str
    audit_id: UUID  # ID de l'audit individuel (créé automatiquement pour les campagnes)
    campaign_id: Optional[UUID] = None  # ID de la campagne (pour tracking des réponses)
    user_role: Optional[str] = None  # audite_resp ou audite_contrib (pour contrôle d'accès frontend)

    # Arbre de navigation par domaines
    domain_tree: List[DomainNode]

    # Questions par domaine/requirement (pour navigation)
    questions_by_node: Dict[str, List[QuestionForAuditeResponse]]

    # Statistiques globales
    total_questions: int
    answered_questions: int
    mandatory_questions: int
    mandatory_answered: int
    progress_percentage: float
    can_submit: bool  # True si toutes les questions mandatory sont répondues
    is_submitted: bool = False  # True si l'audit a déjà été soumis

    class Config:
        from_attributes = True


# ============================================================================
# SCHÉMAS DE SOUMISSION
# ============================================================================

class SubmitAuditRequest(BaseModel):
    """Requête de soumission d'audit"""
    audit_id: UUID
    comment: Optional[str] = Field(None, description="Commentaire général de l'audité")


class SubmitAuditResponse(BaseModel):
    """Réponse après soumission"""
    success: bool
    message: str
    submitted_at: datetime
    total_answers: int
    audit_id: UUID


# ============================================================================
# SCHÉMAS DE PROGRESSION
# ============================================================================

class ProgressResponse(BaseModel):
    """Réponse de progression"""
    audit_id: UUID
    questionnaire_id: UUID
    total_questions: int
    answered_questions: int
    mandatory_questions: int
    mandatory_answered: int
    progress_percentage: float
    can_submit: bool
    last_updated: Optional[datetime]


# Permettre la référence circulaire pour DomainNode
DomainNode.model_rebuild()
