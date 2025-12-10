# backend/src/schemas/discussion.py
"""
Schémas Pydantic pour le module Discussions (Conversations et Messages)
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime
from enum import Enum


class ConversationType(str, Enum):
    """Types de conversations supportés"""
    RIGHTS = "RIGHTS"
    ACTION = "ACTION"
    QUESTION = "QUESTION"
    DIRECT_MESSAGE = "DIRECT_MESSAGE"


# ============================================================================
# PARTICIPANTS
# ============================================================================

class ParticipantBase(BaseModel):
    """Base pour les participants"""
    user_id: UUID
    user_type: str = "entity_member"  # 'user' ou 'entity_member'


class ParticipantCreate(ParticipantBase):
    """Création d'un participant"""
    pass


class ParticipantResponse(ParticipantBase):
    """Réponse participant avec infos supplémentaires"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    joined_at: Optional[datetime] = None
    last_read_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================================
# MESSAGES
# ============================================================================

class AttachmentSchema(BaseModel):
    """Schéma pour une pièce jointe"""
    id: Optional[str] = None
    name: str
    url: Optional[str] = None
    type: Optional[str] = None
    size: Optional[int] = None


class MessageBase(BaseModel):
    """Base pour les messages"""
    body: str = Field(..., min_length=1, max_length=10000)
    attachments: List[AttachmentSchema] = Field(default_factory=list)


class MessageCreate(MessageBase):
    """Création d'un message"""
    pass


class MessageResponse(BaseModel):
    """Réponse message complète"""
    id: UUID
    conversation_id: UUID
    author_id: Optional[UUID] = None
    author_type: Optional[str] = None
    author_first_name: Optional[str] = None
    author_last_name: Optional[str] = None
    author_email: Optional[str] = None
    body: str
    attachments: List[AttachmentSchema] = Field(default_factory=list)
    is_system: bool = False
    metadata: dict = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# CONVERSATIONS
# ============================================================================

class ConversationBase(BaseModel):
    """Base pour les conversations"""
    type: ConversationType
    title: Optional[str] = Field(None, max_length=255)
    object_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None


class ConversationCreate(ConversationBase):
    """Création d'une conversation"""
    participant_ids: List[UUID] = Field(..., min_items=1)
    initial_message: Optional[str] = Field(None, max_length=10000)


class ConversationCreateDirect(BaseModel):
    """Création d'une conversation directe (DIRECT_MESSAGE)"""
    title: Optional[str] = Field(None, max_length=255)
    participant_ids: List[UUID] = Field(..., min_items=1)
    initial_message: Optional[str] = Field(None, max_length=10000)


class ConversationCreateContextual(BaseModel):
    """Création d'une conversation contextuelle (ACTION, QUESTION, RIGHTS)"""
    type: ConversationType
    object_id: UUID
    campaign_id: Optional[UUID] = None
    participant_ids: Optional[List[UUID]] = None  # Auto-déterminé si non fourni
    initial_message: Optional[str] = Field(None, max_length=10000)


class ConversationResponse(BaseModel):
    """Réponse conversation complète"""
    id: UUID
    type: ConversationType
    title: Optional[str] = None
    object_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    tenant_id: UUID
    created_by: UUID
    created_by_type: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    # Informations enrichies
    participants: List[ParticipantResponse] = Field(default_factory=list)
    last_message: Optional[MessageResponse] = None
    unread_count: int = 0

    # Infos contextuelles (pour QUESTION, ACTION, RIGHTS)
    object_title: Optional[str] = None
    object_status: Optional[str] = None

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    """Liste paginée de conversations"""
    items: List[ConversationResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class ConversationDetailResponse(ConversationResponse):
    """Détails complets d'une conversation avec messages"""
    messages: List[MessageResponse] = Field(default_factory=list)
    messages_total: int = 0


# ============================================================================
# FILTRES
# ============================================================================

class ConversationFilter(BaseModel):
    """Filtres pour la liste des conversations"""
    type: Optional[ConversationType] = None
    campaign_id: Optional[UUID] = None
    object_id: Optional[UUID] = None
    search: Optional[str] = None
    unread_only: bool = False


# ============================================================================
# NOTIFICATIONS
# ============================================================================

class NotificationType(str, Enum):
    """Types de notifications pour les discussions"""
    DISCUSSION_NEW_MESSAGE = "DISCUSSION_NEW_MESSAGE"
    DISCUSSION_SYSTEM_MESSAGE = "DISCUSSION_SYSTEM_MESSAGE"
    DISCUSSION_DELETED = "DISCUSSION_DELETED"
    ACCESS_REQUEST_UPDATED = "ACCESS_REQUEST_UPDATED"
    ACTION_NEW_MESSAGE = "ACTION_NEW_MESSAGE"
    QUESTION_NEW_MESSAGE = "QUESTION_NEW_MESSAGE"


class ConversationNotificationResponse(BaseModel):
    """Notification de conversation"""
    id: UUID
    user_id: UUID
    user_type: str
    conversation_id: UUID
    message_id: Optional[UUID] = None
    notification_type: str
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime

    # Informations enrichies
    conversation_title: Optional[str] = None
    conversation_type: Optional[ConversationType] = None
    message_preview: Optional[str] = None
    author_name: Optional[str] = None

    class Config:
        from_attributes = True


class UnreadNotificationsResponse(BaseModel):
    """Réponse pour les notifications non lues"""
    total_unread: int
    notifications: List[ConversationNotificationResponse]


# ============================================================================
# ACTIONS SPÉCIALES
# ============================================================================

class MarkAsReadRequest(BaseModel):
    """Marquer des messages comme lus"""
    message_ids: Optional[List[UUID]] = None  # Si None, marque tous comme lus
    up_to_message_id: Optional[UUID] = None  # Marque jusqu'à ce message


class AddParticipantsRequest(BaseModel):
    """Ajouter des participants à une conversation"""
    participant_ids: List[UUID] = Field(..., min_items=1)


class DeleteConversationRequest(BaseModel):
    """Suppression (soft delete) d'une conversation"""
    reason: Optional[str] = Field(None, max_length=500)
