"""Schémas Pydantic pour la collaboration et les mentions"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


# ============================================================================
# SCHÉMAS POUR LES CONTRIBUTEURS
# ============================================================================

class CollaboratorAdd(BaseModel):
    """Schéma pour ajouter un contributeur existant à un audit"""
    collaborator_id: UUID = Field(..., description="ID du entity_member à ajouter comme contributeur")


class CollaboratorCreate(BaseModel):
    """Schéma pour créer un nouveau contributeur"""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., description="Email du contributeur")
    phone: Optional[str] = Field(None, description="Numéro de téléphone")


class CollaboratorResponse(BaseModel):
    """Schéma de réponse pour un contributeur"""
    id: UUID
    audit_id: Optional[UUID] = None  # Optionnel pour les contributeurs pas encore ajoutés
    invited_by: Optional[UUID] = None  # Optionnel pour les contributeurs pas encore ajoutés
    collaborator_id: UUID
    invited_at: Optional[datetime] = None  # Optionnel pour les contributeurs pas encore ajoutés
    is_active: bool

    # Informations sur le contributeur (chargées depuis entity_member)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================================================
# SCHÉMAS POUR LES COMMENTAIRES ET MENTIONS
# ============================================================================

class CommentCreate(BaseModel):
    """Schéma pour créer un commentaire"""
    question_id: UUID
    audit_id: UUID
    content: str = Field(..., min_length=1, max_length=5000)

    class Config:
        json_schema_extra = {
            "example": {
                "question_id": "123e4567-e89b-12d3-a456-426614174000",
                "audit_id": "123e4567-e89b-12d3-a456-426614174001",
                "content": "Bonjour @jean.dupont, pouvez-vous m'aider sur cette question ?"
            }
        }


class CommentUpdate(BaseModel):
    """Schéma pour mettre à jour un commentaire"""
    content: str = Field(..., min_length=1, max_length=5000)


class MentionResponse(BaseModel):
    """Schéma de réponse pour une mention"""
    id: UUID
    comment_id: UUID
    mentioned_user_id: UUID
    is_read: bool
    created_at: datetime

    # Informations sur l'utilisateur mentionné
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None

    # Informations complémentaires pour les notifications
    comment_content: Optional[str] = None
    comment_created_at: Optional[datetime] = None
    author_id: Optional[UUID] = None
    author_first_name: Optional[str] = None
    author_last_name: Optional[str] = None
    author_email: Optional[str] = None
    question_id: Optional[UUID] = None
    question_text: Optional[str] = None
    question_order: Optional[int] = None
    audit_id: Optional[UUID] = None
    questionnaire_id: Optional[UUID] = None

    # Type d'utilisateur pour distinction auditeur/audité
    user_type: Optional[str] = None  # 'auditor' ou 'entity_member'
    campaign_id: Optional[UUID] = None  # Pour les audités (Magic Link)

    class Config:
        from_attributes = True


class CommentResponse(BaseModel):
    """Schéma de réponse pour un commentaire"""
    id: UUID
    question_id: UUID
    audit_id: UUID
    author_id: UUID
    content: str
    created_at: datetime
    updated_at: datetime
    is_deleted: bool

    # Informations sur l'auteur
    author_first_name: Optional[str] = None
    author_last_name: Optional[str] = None
    author_email: Optional[str] = None

    # Liste des mentions dans ce commentaire
    mentions: List[MentionResponse] = []

    class Config:
        from_attributes = True


# ============================================================================
# SCHÉMAS POUR LES NOTIFICATIONS
# ============================================================================

class UnreadMentionsResponse(BaseModel):
    """Schéma de réponse pour les mentions non lues"""
    total_unread: int
    mentions: List[MentionResponse]
