"""
Schémas Pydantic pour QuestionType

Gestion des types de questions (référentiel).
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class QuestionTypeBase(BaseModel):
    """Schéma de base pour QuestionType"""
    code: str = Field(..., min_length=1, max_length=30, description="Code technique du type")
    label: str = Field(..., min_length=1, max_length=100, description="Libellé affiché")
    description: Optional[str] = Field(None, description="Description détaillée du type")
    icon: Optional[str] = Field(None, max_length=50, description="Nom de l'icône")
    has_options: bool = Field(False, description="Nécessite des options de réponse")
    validation_schema: Optional[Dict[str, Any]] = Field(None, description="Schéma de validation JSON")
    display_order: int = Field(..., ge=1, description="Ordre d'affichage")
    is_active: bool = Field(True, description="Type activé ou désactivé")


class QuestionTypeCreate(QuestionTypeBase):
    """Schéma pour la création d'un type de question"""
    pass


class QuestionTypeUpdate(BaseModel):
    """Schéma pour la mise à jour d'un type de question"""
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    has_options: Optional[bool] = None
    validation_schema: Optional[Dict[str, Any]] = None
    display_order: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None


class QuestionTypeResponse(QuestionTypeBase):
    """Schéma pour la réponse API (lecture)"""
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class QuestionTypeListResponse(BaseModel):
    """Schéma pour la liste des types de questions"""
    question_types: list[QuestionTypeResponse]
    total: int = Field(..., description="Nombre total de types")


class QuestionTypePublic(BaseModel):
    """Schéma public simplifié pour le frontend"""
    code: str
    label: str
    icon: Optional[str] = None
    has_options: bool
    display_order: int

    class Config:
        from_attributes = True
