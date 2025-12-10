# backend/src/schemas/questionnaire.py
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any, Literal
from datetime import datetime
from enum import Enum

class SourceType(str, Enum):
    framework = "framework"
    control_points = "control_points"
    requirements = "requirements"

class QuestionnaireStatus(str, Enum):
    draft = "draft"
    published = "published"
    archived = "archived"

class QuestionnaireBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_type: SourceType
    source_framework_name: Optional[str] = None
    language: str = Field(default="fr", pattern="^[a-z]{2}$")
    status: QuestionnaireStatus = QuestionnaireStatus.draft
    ai_model: Optional[str] = None

class QuestionnaireCreate(QuestionnaireBase):
    source_framework_id: Optional[str] = None
    source_control_point_ids: Optional[List[str]] = None
    ai_params: Optional[Dict[str, Any]] = None
    created_by: str

class QuestionnaireUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[QuestionnaireStatus] = None
    language: Optional[str] = None

class QuestionnaireResponse(QuestionnaireBase):
    id: str
    questions_count: int = 0
    ai_generated_count: int = 0
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class QuestionnaireStats(BaseModel):
    total_questionnaires: int = 0
    published_questionnaires: int = 0
    total_questions: int = 0
    ai_generated_questions: int = 0
    by_source_type: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_language: Dict[str, int] = {}

class QuestionnaireListResponse(BaseModel):
    questionnaires: List[QuestionnaireResponse]

class DuplicationResponse(BaseModel):
    message: str
    new_questionnaire_name: Optional[str] = None

class DeletionResponse(BaseModel):
    message: str
    deleted_questions_count: int = 0

class QuestionGenerationRequest(BaseModel):
    mode: Literal["framework", "control_points"]
    framework_id: Optional[str] = None
    control_point_ids: Optional[List[str]] = None
    language: str = Field(default="fr", pattern=r"^[a-z]{2}$")
    ai_params: Dict[str, Any] = Field(default_factory=dict)

class UploadCondition(BaseModel):
    """Conditions pour upload de pièce jointe selon la réponse"""
    required_for_values: List[str] = Field(default_factory=list)  # ex: ["Oui", "Partiellement"]
    attachment_types: List[str] = Field(default_factory=lambda: ["evidence"])  # Types acceptés
    min_files: int = Field(default=1, ge=0)  # Nombre minimum de fichiers
    max_files: Optional[int] = Field(default=None, ge=1)  # Nombre maximum (None = illimité)
    accepts_links: bool = Field(default=True)  # Accepter des liens URL comme preuve
    help_text: Optional[str] = None  # Texte d'aide pour l'upload
    is_mandatory: bool = True  # Upload obligatoire ou optionnel

class GeneratedQuestion(BaseModel):
    id: Optional[str] = None                    # si tu en génères un
    text: str                                   # énoncé de la question
    type: Literal["single_choice","multiple_choice","open","rating","boolean","number","date"] = "open"
    options: Optional[List[str]] = None         # pour choix
    control_point_id: Optional[str] = None
    requirement_ids: List[str] = Field(default_factory=list)
    difficulty: Optional[str] = None            # ex: "easy" | "medium" | "hard"
    ai_confidence: Optional[float] = None
    rationale: Optional[str] = None
    help_text: Optional[str] = None             # Aide contextuelle pour l'audité (où trouver l'info, commandes, etc.)
    tags: List[str] = Field(default_factory=list)
    is_mandatory: bool = Field(default=False)   # Question obligatoire
    upload_conditions: Optional[UploadCondition] = None  # Conditions d'upload

    # ✅ Nouveaux champs pour enrichissement des questions
    question_code: Optional[str] = None         # Code standardisé (ex: "ISO27001-A5.1-Q1")
    chapter: Optional[str] = None               # Chapitre/section (ex: "A.5", "A.6")
    evidence_types: List[str] = Field(default_factory=list)  # Types de preuves suggérés
    estimated_time_minutes: Optional[int] = Field(default=None, ge=1, le=120)  # Temps estimé (1-120 min)