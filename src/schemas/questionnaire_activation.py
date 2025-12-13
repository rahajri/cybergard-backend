"""
Schémas Pydantic pour la gestion des activations de questionnaires
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class QuestionnaireActivationCreate(BaseModel):
    """Requête pour activer un questionnaire"""
    inherit_to_children: bool = Field(
        default=True,
        description="Hériter l'activation aux organizations enfants"
    )


class QuestionnaireActivationResponse(BaseModel):
    """Réponse après activation"""
    id: str
    org_id: str
    org_name: str
    questionnaire_id: str
    questionnaire_name: str
    active: bool
    inherit_to_children: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class QuestionnaireWithActivation(BaseModel):
    """Questionnaire avec son statut d'activation pour une organization"""
    id: str
    name: str
    status: str
    question_count: int
    created_at: datetime
    is_activated: bool = Field(description="A déjà été activé (historique)")
    is_active: bool = Field(description="Est actuellement actif")
    inherit_to_children: bool
    activated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QuestionnaireActivationList(BaseModel):
    """Liste des questionnaires pour une organization"""
    org_id: str
    org_name: str
    questionnaires: List[QuestionnaireWithActivation]
    total_count: int


class OrganizationWithActivation(BaseModel):
    """Organization avec statut d'activation d'un questionnaire"""
    id: str
    name: str
    tenant_id: str
    tenant_name: str
    is_active: bool
    inherit_to_children: bool
    activated_at: datetime

    class Config:
        from_attributes = True
