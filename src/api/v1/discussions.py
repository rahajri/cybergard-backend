# backend/src/api/v1/discussions.py
"""
API endpoints pour le module Discussions (Conversations et Messages)

Endpoints:
- GET /discussions: Liste des conversations de l'utilisateur
- POST /discussions: Créer une nouvelle conversation
- GET /discussions/{id}: Détails d'une conversation avec messages
- POST /discussions/{id}/messages: Envoyer un message
- PATCH /discussions/{id}/read: Marquer comme lu
- DELETE /discussions/{id}: Soft delete (admin tenant uniquement)
- GET /discussions/notifications/unread: Notifications non lues
- PATCH /discussions/notifications/{id}/read: Marquer notification comme lue
"""

from fastapi import APIRouter, Depends, HTTPException, status as http_status, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from uuid import UUID
import logging
import json
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from src.database import get_db
from src.dependencies_keycloak import get_current_user_keycloak
from src.services.email_service import send_discussion_new_message_email
import os
from src.schemas.discussion import (
    ConversationType,
    ConversationCreate,
    ConversationCreateDirect,
    ConversationResponse,
    ConversationListResponse,
    ConversationDetailResponse,
    MessageCreate,
    MessageResponse,
    ParticipantResponse,
    ConversationNotificationResponse,
    UnreadNotificationsResponse,
    MarkAsReadRequest,
    AddParticipantsRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discussions", tags=["Discussions"])


# ============================================================================
# HELPERS
# ============================================================================

def get_user_info_from_token(current_user: dict, db: Session) -> dict:
    """
    Récupère les informations utilisateur depuis le token Keycloak.
    Gère les Magic Links et les utilisateurs internes.

    Returns:
        dict avec: user_id, user_type, email, tenant_id, first_name, last_name
    """
    user_email = current_user.get("email") if isinstance(current_user, dict) else current_user.email

    # Pour les utilisateurs Magic Link
    if user_email and user_email.endswith("@temp.cybergard.local"):
        username = user_email.split("@")[0]
        parts = username.split("-")
        if len(parts) >= 6:
            campaign_id_from_email = "-".join(parts[1:-1])
            email_hash = parts[-1]

            # Récupérer tous les emails de la campagne
            import hashlib
            real_email_query = text("""
                SELECT user_email FROM audit_tokens
                WHERE campaign_id = :campaign_id AND revoked = false
            """)
            all_emails = db.execute(real_email_query, {"campaign_id": campaign_id_from_email}).fetchall()

            real_email = user_email
            for row in all_emails:
                candidate_email = row.user_email
                candidate_hash = hashlib.sha256(candidate_email.encode()).hexdigest()[:8]
                if candidate_hash == email_hash:
                    real_email = candidate_email
                    break

            user_email = real_email

    # Chercher d'abord dans users (utilisateurs internes)
    user_query = text("""
        SELECT u.id, u.email, u.first_name, u.last_name, u.tenant_id
        FROM users u
        WHERE u.email = :email AND u.is_active = true
        LIMIT 1
    """)
    user_result = db.execute(user_query, {"email": user_email}).fetchone()

    if user_result:
        return {
            "user_id": user_result.id,
            "user_type": "user",
            "email": user_result.email,
            "tenant_id": user_result.tenant_id,
            "first_name": user_result.first_name,
            "last_name": user_result.last_name
        }

    # Sinon chercher dans entity_member
    member_query = text("""
        SELECT em.id, em.email, em.first_name, em.last_name, ee.tenant_id
        FROM entity_member em
        JOIN ecosystem_entity ee ON em.entity_id = ee.id
        WHERE em.email = :email AND em.is_active = true
        LIMIT 1
    """)
    member_result = db.execute(member_query, {"email": user_email}).fetchone()

    if member_result:
        return {
            "user_id": member_result.id,
            "user_type": "entity_member",
            "email": member_result.email,
            "tenant_id": member_result.tenant_id,
            "first_name": member_result.first_name,
            "last_name": member_result.last_name
        }

    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail="Utilisateur non trouvé"
    )


def get_conversation_participants(db: Session, conversation_id: UUID) -> List[ParticipantResponse]:
    """Récupère les participants d'une conversation avec leurs infos"""
    query = text("""
        SELECT
            cp.user_id,
            cp.user_type,
            cp.joined_at,
            cp.last_read_at,
            COALESCE(u.first_name, em.first_name) as first_name,
            COALESCE(u.last_name, em.last_name) as last_name,
            COALESCE(u.email, em.email) as email
        FROM conversation_participant cp
        LEFT JOIN users u ON cp.user_type = 'user' AND cp.user_id = u.id
        LEFT JOIN entity_member em ON cp.user_type = 'entity_member' AND cp.user_id = em.id
        WHERE cp.conversation_id = CAST(:conversation_id AS uuid)
    """)
    results = db.execute(query, {"conversation_id": str(conversation_id)}).fetchall()

    return [
        ParticipantResponse(
            user_id=row.user_id,
            user_type=row.user_type,
            first_name=row.first_name,
            last_name=row.last_name,
            email=row.email,
            joined_at=row.joined_at,
            last_read_at=row.last_read_at
        )
        for row in results
    ]


def get_last_message(db: Session, conversation_id: UUID) -> Optional[MessageResponse]:
    """Récupère le dernier message d'une conversation"""
    query = text("""
        SELECT
            m.id, m.conversation_id, m.author_id, m.author_type,
            m.body, m.attachments, m.is_system, m.metadata, m.created_at,
            COALESCE(u.first_name, em.first_name) as author_first_name,
            COALESCE(u.last_name, em.last_name) as author_last_name,
            COALESCE(u.email, em.email) as author_email
        FROM message m
        LEFT JOIN users u ON m.author_type = 'user' AND m.author_id = u.id
        LEFT JOIN entity_member em ON m.author_type = 'entity_member' AND m.author_id = em.id
        WHERE m.conversation_id = CAST(:conversation_id AS uuid)
        ORDER BY m.created_at DESC
        LIMIT 1
    """)
    row = db.execute(query, {"conversation_id": str(conversation_id)}).fetchone()

    if not row:
        return None

    return MessageResponse(
        id=row.id,
        conversation_id=row.conversation_id,
        author_id=row.author_id,
        author_type=row.author_type,
        author_first_name=row.author_first_name,
        author_last_name=row.author_last_name,
        author_email=row.author_email,
        body=row.body,
        attachments=row.attachments or [],
        is_system=row.is_system,
        metadata=row.metadata or {},
        created_at=row.created_at
    )


def get_unread_count(db: Session, conversation_id: UUID, user_id: UUID) -> int:
    """Compte les messages non lus pour un utilisateur"""
    query = text("""
        SELECT COUNT(*) as count
        FROM message m
        JOIN conversation_participant cp ON cp.conversation_id = m.conversation_id
        WHERE m.conversation_id = CAST(:conversation_id AS uuid)
          AND cp.user_id = CAST(:user_id AS uuid)
          AND (cp.last_read_at IS NULL OR m.created_at > cp.last_read_at)
          AND (m.author_id IS NULL OR m.author_id != CAST(:user_id AS uuid))
    """)
    result = db.execute(query, {
        "conversation_id": str(conversation_id),
        "user_id": str(user_id)
    }).fetchone()

    return result.count if result else 0


# ============================================================================
# ENDPOINTS - CONVERSATIONS
# ============================================================================

@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    type: Optional[ConversationType] = Query(None, description="Filtrer par type"),
    campaign_id: Optional[UUID] = Query(None, description="Filtrer par campagne"),
    unread_only: bool = Query(False, description="Uniquement les non lus"),
    search: Optional[str] = Query(None, description="Recherche dans le titre"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Liste les conversations de l'utilisateur connecté.
    Triées par date du dernier message (plus récent en premier).
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])
        tenant_id = str(user_info["tenant_id"])

        # Construction de la requête
        base_query = """
            SELECT DISTINCT c.id, c.type, c.title, c.object_id, c.campaign_id,
                   c.tenant_id, c.created_by, c.created_by_type,
                   c.created_at, c.updated_at, c.deleted_at,
                   (SELECT MAX(m.created_at) FROM message m WHERE m.conversation_id = c.id) as last_message_at
            FROM conversation c
            JOIN conversation_participant cp ON cp.conversation_id = c.id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND cp.user_id = CAST(:user_id AS uuid)
              AND c.deleted_at IS NULL
        """

        params = {"tenant_id": tenant_id, "user_id": user_id}

        # Filtres optionnels
        if type:
            base_query += " AND c.type = :type"
            params["type"] = type.value

        if campaign_id:
            base_query += " AND c.campaign_id = CAST(:campaign_id AS uuid)"
            params["campaign_id"] = str(campaign_id)

        if search:
            base_query += " AND c.title ILIKE :search"
            params["search"] = f"%{search}%"

        # Comptage total
        count_query = f"SELECT COUNT(*) FROM ({base_query}) as filtered"
        total = db.execute(text(count_query), params).scalar()

        # Requête avec pagination et tri
        base_query += " ORDER BY last_message_at DESC NULLS LAST LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset

        results = db.execute(text(base_query), params).fetchall()

        # Construction des réponses
        items = []
        for row in results:
            participants = get_conversation_participants(db, row.id)
            last_message = get_last_message(db, row.id)
            unread_count = get_unread_count(db, row.id, user_info["user_id"])

            # Si filtre unread_only et pas de messages non lus, skip
            if unread_only and unread_count == 0:
                continue

            items.append(ConversationResponse(
                id=row.id,
                type=row.type,
                title=row.title,
                object_id=row.object_id,
                campaign_id=row.campaign_id,
                tenant_id=row.tenant_id,
                created_by=row.created_by,
                created_by_type=row.created_by_type,
                created_at=row.created_at,
                updated_at=row.updated_at,
                deleted_at=row.deleted_at,
                participants=participants,
                last_message=last_message,
                unread_count=unread_count
            ))

        return ConversationListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            has_more=(offset + limit) < total
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la liste des conversations: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("", response_model=ConversationResponse, status_code=http_status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreateDirect,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Crée une nouvelle conversation directe (DIRECT_MESSAGE).
    Pour les conversations contextuelles (ACTION, QUESTION, RIGHTS),
    utiliser les endpoints spécifiques.
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])
        tenant_id = str(user_info["tenant_id"])

        # Vérifier que tous les participants sont du même tenant
        participant_ids = [str(p) for p in data.participant_ids]

        # Inclure le créateur dans les participants
        if user_id not in participant_ids:
            participant_ids.append(user_id)

        # Créer la conversation
        insert_conv = text("""
            INSERT INTO conversation (type, title, tenant_id, created_by, created_by_type, created_at, updated_at)
            VALUES ('DIRECT_MESSAGE', :title, CAST(:tenant_id AS uuid), CAST(:created_by AS uuid), :created_by_type, NOW(), NOW())
            RETURNING id, type, title, object_id, campaign_id, tenant_id, created_by, created_by_type, created_at, updated_at, deleted_at
        """)
        conv_result = db.execute(insert_conv, {
            "title": data.title,
            "tenant_id": tenant_id,
            "created_by": user_id,
            "created_by_type": user_info["user_type"]
        }).fetchone()
        db.flush()

        conversation_id = str(conv_result.id)

        # Ajouter les participants
        for p_id in participant_ids:
            # Déterminer le type de participant
            user_check = db.execute(text("SELECT id FROM users WHERE id = CAST(:id AS uuid)"), {"id": p_id}).fetchone()
            p_type = "user" if user_check else "entity_member"

            insert_participant = text("""
                INSERT INTO conversation_participant (conversation_id, user_id, user_type, joined_at)
                VALUES (CAST(:conv_id AS uuid), CAST(:user_id AS uuid), :user_type, NOW())
            """)
            db.execute(insert_participant, {
                "conv_id": conversation_id,
                "user_id": p_id,
                "user_type": p_type
            })

        # Créer le message initial si fourni
        if data.initial_message:
            insert_msg = text("""
                INSERT INTO message (conversation_id, author_id, author_type, body, attachments, is_system, metadata, created_at)
                VALUES (CAST(:conv_id AS uuid), CAST(:author_id AS uuid), :author_type, :body, '[]'::jsonb, false, '{}'::jsonb, NOW())
            """)
            db.execute(insert_msg, {
                "conv_id": conversation_id,
                "author_id": user_id,
                "author_type": user_info["user_type"],
                "body": data.initial_message
            })

            # Créer les notifications pour les autres participants
            for p_id in participant_ids:
                if p_id != user_id:
                    user_check = db.execute(text("SELECT id FROM users WHERE id = CAST(:id AS uuid)"), {"id": p_id}).fetchone()
                    p_type = "user" if user_check else "entity_member"

                    insert_notif = text("""
                        INSERT INTO conversation_notification
                        (user_id, user_type, conversation_id, notification_type, is_read, created_at)
                        VALUES (CAST(:user_id AS uuid), :user_type, CAST(:conv_id AS uuid), 'DISCUSSION_NEW_MESSAGE', false, NOW())
                    """)
                    db.execute(insert_notif, {
                        "user_id": p_id,
                        "user_type": p_type,
                        "conv_id": conversation_id
                    })

        db.commit()

        # Récupérer la conversation complète
        participants = get_conversation_participants(db, conv_result.id)
        last_message = get_last_message(db, conv_result.id)

        return ConversationResponse(
            id=conv_result.id,
            type=conv_result.type,
            title=conv_result.title,
            object_id=conv_result.object_id,
            campaign_id=conv_result.campaign_id,
            tenant_id=conv_result.tenant_id,
            created_by=conv_result.created_by,
            created_by_type=conv_result.created_by_type,
            created_at=conv_result.created_at,
            updated_at=conv_result.updated_at,
            deleted_at=conv_result.deleted_at,
            participants=participants,
            last_message=last_message,
            unread_count=0
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la création de conversation: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=100, description="Nombre de messages"),
    offset: int = Query(0, ge=0, description="Offset pour pagination des messages"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Récupère les détails d'une conversation avec ses messages.
    L'utilisateur doit être participant de la conversation.
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])

        # Vérifier que l'utilisateur est participant
        participant_check = text("""
            SELECT 1 FROM conversation_participant
            WHERE conversation_id = CAST(:conv_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
        """)
        if not db.execute(participant_check, {"conv_id": str(conversation_id), "user_id": user_id}).fetchone():
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Vous n'êtes pas participant de cette conversation"
            )

        # Récupérer la conversation
        conv_query = text("""
            SELECT id, type, title, object_id, campaign_id, tenant_id,
                   created_by, created_by_type, created_at, updated_at, deleted_at
            FROM conversation
            WHERE id = CAST(:conv_id AS uuid) AND deleted_at IS NULL
        """)
        conv = db.execute(conv_query, {"conv_id": str(conversation_id)}).fetchone()

        if not conv:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Conversation non trouvée"
            )

        # Récupérer les participants
        participants = get_conversation_participants(db, conversation_id)

        # Récupérer les messages
        messages_query = text("""
            SELECT
                m.id, m.conversation_id, m.author_id, m.author_type,
                m.body, m.attachments, m.is_system, m.metadata, m.created_at,
                COALESCE(u.first_name, em.first_name) as author_first_name,
                COALESCE(u.last_name, em.last_name) as author_last_name,
                COALESCE(u.email, em.email) as author_email
            FROM message m
            LEFT JOIN users u ON m.author_type = 'user' AND m.author_id = u.id
            LEFT JOIN entity_member em ON m.author_type = 'entity_member' AND m.author_id = em.id
            WHERE m.conversation_id = CAST(:conv_id AS uuid)
            ORDER BY m.created_at ASC
            LIMIT :limit OFFSET :offset
        """)
        messages_results = db.execute(messages_query, {
            "conv_id": str(conversation_id),
            "limit": limit,
            "offset": offset
        }).fetchall()

        messages = [
            MessageResponse(
                id=row.id,
                conversation_id=row.conversation_id,
                author_id=row.author_id,
                author_type=row.author_type,
                author_first_name=row.author_first_name,
                author_last_name=row.author_last_name,
                author_email=row.author_email,
                body=row.body,
                attachments=row.attachments or [],
                is_system=row.is_system,
                metadata=row.metadata or {},
                created_at=row.created_at
            )
            for row in messages_results
        ]

        # Compter le total des messages
        count_query = text("""
            SELECT COUNT(*) FROM message WHERE conversation_id = CAST(:conv_id AS uuid)
        """)
        messages_total = db.execute(count_query, {"conv_id": str(conversation_id)}).scalar()

        # Mettre à jour last_read_at
        update_read = text("""
            UPDATE conversation_participant
            SET last_read_at = NOW()
            WHERE conversation_id = CAST(:conv_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
        """)
        db.execute(update_read, {"conv_id": str(conversation_id), "user_id": user_id})
        db.commit()

        return ConversationDetailResponse(
            id=conv.id,
            type=conv.type,
            title=conv.title,
            object_id=conv.object_id,
            campaign_id=conv.campaign_id,
            tenant_id=conv.tenant_id,
            created_by=conv.created_by,
            created_by_type=conv.created_by_type,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            deleted_at=conv.deleted_at,
            participants=participants,
            last_message=messages[-1] if messages else None,
            unread_count=0,  # Vient d'être lu
            messages=messages,
            messages_total=messages_total
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de conversation: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ============================================================================
# ENDPOINTS - MESSAGES
# ============================================================================

@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=http_status.HTTP_201_CREATED)
async def create_message(
    conversation_id: UUID,
    data: MessageCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Envoie un message dans une conversation.
    L'utilisateur doit être participant de la conversation.
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])

        # Vérifier que l'utilisateur est participant
        participant_check = text("""
            SELECT 1 FROM conversation_participant
            WHERE conversation_id = CAST(:conv_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
        """)
        if not db.execute(participant_check, {"conv_id": str(conversation_id), "user_id": user_id}).fetchone():
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Vous n'êtes pas participant de cette conversation"
            )

        # Vérifier que la conversation existe et n'est pas supprimée
        conv_check = text("""
            SELECT id FROM conversation
            WHERE id = CAST(:conv_id AS uuid) AND deleted_at IS NULL
        """)
        if not db.execute(conv_check, {"conv_id": str(conversation_id)}).fetchone():
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Conversation non trouvée"
            )

        # Créer le message
        attachments_json = json.dumps([a.dict() for a in data.attachments]) if data.attachments else '[]'

        insert_msg = text("""
            INSERT INTO message (conversation_id, author_id, author_type, body, attachments, is_system, metadata, created_at)
            VALUES (CAST(:conv_id AS uuid), CAST(:author_id AS uuid), :author_type, :body, CAST(:attachments AS jsonb), false, '{}'::jsonb, NOW())
            RETURNING id, conversation_id, author_id, author_type, body, attachments, is_system, metadata, created_at
        """)
        msg = db.execute(insert_msg, {
            "conv_id": str(conversation_id),
            "author_id": user_id,
            "author_type": user_info["user_type"],
            "body": data.body,
            "attachments": attachments_json
        }).fetchone()

        # Mettre à jour updated_at de la conversation
        update_conv = text("""
            UPDATE conversation SET updated_at = NOW() WHERE id = CAST(:conv_id AS uuid)
        """)
        db.execute(update_conv, {"conv_id": str(conversation_id)})

        # Récupérer les informations de la conversation pour les emails
        conv_info_query = text("""
            SELECT c.title, c.type, c.campaign_id,
                   COALESCE(camp.title, '') as campaign_name
            FROM conversation c
            LEFT JOIN campaign camp ON c.campaign_id = camp.id
            WHERE c.id = CAST(:conv_id AS uuid)
        """)
        conv_info = db.execute(conv_info_query, {"conv_id": str(conversation_id)}).fetchone()
        conversation_title = conv_info.title or "Discussion"
        conversation_type = conv_info.type if conv_info else "DIRECT_MESSAGE"
        campaign_name = conv_info.campaign_name if conv_info and conv_info.campaign_name else None

        # Créer les notifications pour les autres participants
        participants_query = text("""
            SELECT cp.user_id, cp.user_type,
                   CASE
                       WHEN cp.user_type = 'user' THEN u.email
                       WHEN cp.user_type = 'entity_member' THEN em.email
                   END as email,
                   CASE
                       WHEN cp.user_type = 'user' THEN CONCAT(u.first_name, ' ', u.last_name)
                       WHEN cp.user_type = 'entity_member' THEN CONCAT(em.first_name, ' ', em.last_name)
                   END as full_name
            FROM conversation_participant cp
            LEFT JOIN users u ON cp.user_type = 'user' AND cp.user_id = u.id
            LEFT JOIN entity_member em ON cp.user_type = 'entity_member' AND cp.user_id = em.id
            WHERE cp.conversation_id = CAST(:conv_id AS uuid)
              AND cp.user_id != CAST(:author_id AS uuid)
        """)
        other_participants = db.execute(participants_query, {
            "conv_id": str(conversation_id),
            "author_id": user_id
        }).fetchall()

        # Préparer l'URL de la conversation
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        conversation_url = f"{frontend_url}/client/discussions/{conversation_id}"

        # Nom complet de l'auteur
        sender_name = f"{user_info['first_name']} {user_info['last_name']}"

        # Aperçu du message (max 200 caractères)
        message_preview = data.body[:200] + "..." if len(data.body) > 200 else data.body

        for p in other_participants:
            # Créer la notification en base
            insert_notif = text("""
                INSERT INTO conversation_notification
                (user_id, user_type, conversation_id, message_id, notification_type, is_read, created_at)
                VALUES (CAST(:user_id AS uuid), :user_type, CAST(:conv_id AS uuid), CAST(:msg_id AS uuid), 'DISCUSSION_NEW_MESSAGE', false, NOW())
            """)
            db.execute(insert_notif, {
                "user_id": str(p.user_id),
                "user_type": p.user_type,
                "conv_id": str(conversation_id),
                "msg_id": str(msg.id)
            })

            # Envoyer l'email de notification (en background pour ne pas bloquer)
            if p.email:
                try:
                    send_discussion_new_message_email(
                        to_email=p.email,
                        recipient_name=p.full_name or "Utilisateur",
                        sender_name=sender_name,
                        conversation_title=conversation_title,
                        conversation_type=conversation_type,
                        message_preview=message_preview,
                        conversation_url=conversation_url,
                        campaign_name=campaign_name
                    )
                    logger.info(f"📧 Email notification envoyé à {p.email} pour nouveau message")
                except Exception as email_error:
                    # Ne pas bloquer si l'email échoue, juste logger
                    logger.warning(f"⚠️ Échec envoi email à {p.email}: {email_error}")

        db.commit()

        return MessageResponse(
            id=msg.id,
            conversation_id=msg.conversation_id,
            author_id=msg.author_id,
            author_type=msg.author_type,
            author_first_name=user_info["first_name"],
            author_last_name=user_info["last_name"],
            author_email=user_info["email"],
            body=msg.body,
            attachments=msg.attachments or [],
            is_system=msg.is_system,
            metadata=msg.metadata or {},
            created_at=msg.created_at
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la création du message: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ============================================================================
# ENDPOINTS - NOTIFICATIONS
# ============================================================================

@router.get("/notifications/unread", response_model=UnreadNotificationsResponse)
async def get_unread_notifications(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Récupère les notifications non lues de l'utilisateur pour les discussions.
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])

        query = text("""
            SELECT
                cn.id, cn.user_id, cn.user_type, cn.conversation_id, cn.message_id,
                cn.notification_type, cn.is_read, cn.read_at, cn.created_at,
                c.title as conversation_title, c.type as conversation_type,
                m.body as message_body,
                COALESCE(u.first_name || ' ' || u.last_name, em.first_name || ' ' || em.last_name) as author_name
            FROM conversation_notification cn
            JOIN conversation c ON cn.conversation_id = c.id
            LEFT JOIN message m ON cn.message_id = m.id
            LEFT JOIN users u ON m.author_type = 'user' AND m.author_id = u.id
            LEFT JOIN entity_member em ON m.author_type = 'entity_member' AND m.author_id = em.id
            WHERE cn.user_id = CAST(:user_id AS uuid)
              AND cn.is_read = false
            ORDER BY cn.created_at DESC
            LIMIT 50
        """)
        results = db.execute(query, {"user_id": user_id}).fetchall()

        notifications = [
            ConversationNotificationResponse(
                id=row.id,
                user_id=row.user_id,
                user_type=row.user_type,
                conversation_id=row.conversation_id,
                message_id=row.message_id,
                notification_type=row.notification_type,
                is_read=row.is_read,
                read_at=row.read_at,
                created_at=row.created_at,
                conversation_title=row.conversation_title,
                conversation_type=row.conversation_type,
                message_preview=row.message_body[:100] if row.message_body else None,
                author_name=row.author_name
            )
            for row in results
        ]

        return UnreadNotificationsResponse(
            total_unread=len(notifications),
            notifications=notifications
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des notifications: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.patch("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Marque une notification comme lue.
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])

        # Vérifier que la notification appartient à l'utilisateur
        check_query = text("""
            SELECT id FROM conversation_notification
            WHERE id = CAST(:notif_id AS uuid) AND user_id = CAST(:user_id AS uuid)
        """)
        if not db.execute(check_query, {"notif_id": str(notification_id), "user_id": user_id}).fetchone():
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Notification non trouvée"
            )

        # Marquer comme lue
        update_query = text("""
            UPDATE conversation_notification
            SET is_read = true, read_at = NOW()
            WHERE id = CAST(:notif_id AS uuid)
        """)
        db.execute(update_query, {"notif_id": str(notification_id)})
        db.commit()

        return {"success": True, "message": "Notification marquée comme lue"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors du marquage de notification: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ============================================================================
# ENDPOINTS - SUPPRESSION
# ============================================================================

@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Soft delete d'une conversation (admin tenant uniquement).
    Les messages ne sont PAS supprimés (audit trail).
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])

        # Vérifier que l'utilisateur est admin ou créateur
        # TODO: Ajouter vérification rôle admin tenant via Keycloak

        # Vérifier que la conversation existe
        conv_check = text("""
            SELECT id, created_by FROM conversation
            WHERE id = CAST(:conv_id AS uuid) AND deleted_at IS NULL
        """)
        conv = db.execute(conv_check, {"conv_id": str(conversation_id)}).fetchone()

        if not conv:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Conversation non trouvée"
            )

        # Pour l'instant, seul le créateur peut supprimer
        if str(conv.created_by) != user_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Seul le créateur peut supprimer cette conversation"
            )

        # Soft delete
        delete_query = text("""
            UPDATE conversation
            SET deleted_at = NOW(), deleted_by = CAST(:user_id AS uuid)
            WHERE id = CAST(:conv_id AS uuid)
        """)
        db.execute(delete_query, {"conv_id": str(conversation_id), "user_id": user_id})

        # Notifier les participants
        participants_query = text("""
            SELECT user_id, user_type FROM conversation_participant
            WHERE conversation_id = CAST(:conv_id AS uuid)
              AND user_id != CAST(:user_id AS uuid)
        """)
        participants = db.execute(participants_query, {
            "conv_id": str(conversation_id),
            "user_id": user_id
        }).fetchall()

        for p in participants:
            insert_notif = text("""
                INSERT INTO conversation_notification
                (user_id, user_type, conversation_id, notification_type, is_read, created_at)
                VALUES (CAST(:user_id AS uuid), :user_type, CAST(:conv_id AS uuid), 'DISCUSSION_DELETED', false, NOW())
            """)
            db.execute(insert_notif, {
                "user_id": str(p.user_id),
                "user_type": p.user_type,
                "conv_id": str(conversation_id)
            })

        db.commit()

        return {"success": True, "message": "Conversation supprimée"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la suppression de conversation: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ============================================================================
# ENDPOINTS - PARTICIPANTS (OPTIONNEL)
# ============================================================================

@router.get("/{conversation_id}/participants", response_model=List[ParticipantResponse])
async def get_participants(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Liste les participants d'une conversation.
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])

        # Vérifier que l'utilisateur est participant
        participant_check = text("""
            SELECT 1 FROM conversation_participant
            WHERE conversation_id = CAST(:conv_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
        """)
        if not db.execute(participant_check, {"conv_id": str(conversation_id), "user_id": user_id}).fetchone():
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Vous n'êtes pas participant de cette conversation"
            )

        return get_conversation_participants(db, conversation_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des participants: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/members/search", response_model=List[ParticipantResponse])
async def search_members(
    q: str = Query(..., min_length=2, description="Recherche par nom ou email"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Recherche des membres du tenant pour créer une conversation.
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        tenant_id = str(user_info["tenant_id"])
        user_id = str(user_info["user_id"])

        # Rechercher dans users et entity_member
        query = text("""
            SELECT id, 'user' as user_type, first_name, last_name, email
            FROM users
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_active = true
              AND id != CAST(:user_id AS uuid)
              AND (
                  first_name ILIKE :search
                  OR last_name ILIKE :search
                  OR email ILIKE :search
                  OR CONCAT(first_name, ' ', last_name) ILIKE :search
              )
            UNION ALL
            SELECT em.id, 'entity_member' as user_type, em.first_name, em.last_name, em.email
            FROM entity_member em
            JOIN ecosystem_entity ee ON em.entity_id = ee.id
            WHERE ee.tenant_id = CAST(:tenant_id AS uuid)
              AND em.is_active = true
              AND em.id != CAST(:user_id AS uuid)
              AND (
                  em.first_name ILIKE :search
                  OR em.last_name ILIKE :search
                  OR em.email ILIKE :search
                  OR CONCAT(em.first_name, ' ', em.last_name) ILIKE :search
              )
            ORDER BY first_name, last_name
            LIMIT :limit
        """)
        results = db.execute(query, {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "search": f"%{q}%",
            "limit": limit
        }).fetchall()

        return [
            ParticipantResponse(
                user_id=row.id,
                user_type=row.user_type,
                first_name=row.first_name,
                last_name=row.last_name,
                email=row.email
            )
            for row in results
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la recherche de membres: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ============================================================================
# ENDPOINTS - DEMANDE DE DROITS (RIGHTS)
# ============================================================================

class RightsRequestCreate(BaseModel):
    """Schéma pour créer une demande de droits"""
    permission_code: str = Field(..., description="Code de la permission demandée")
    action_name: str = Field(..., description="Nom lisible de l'action")
    message: Optional[str] = Field(None, max_length=2000, description="Message optionnel")


class RightsRequestResponse(BaseModel):
    """Réponse après création d'une demande de droits"""
    success: bool
    conversation_id: UUID
    message: str


@router.post("/rights-request", response_model=RightsRequestResponse, status_code=http_status.HTTP_201_CREATED)
async def create_rights_request(
    data: RightsRequestCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Crée une demande de droits (conversation de type RIGHTS).

    - Crée automatiquement une conversation avec les admins du tenant
    - Envoie une notification + email aux admins
    - Le lien dans l'email redirige vers la gestion des permissions
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        user_id = str(user_info["user_id"])
        tenant_id = str(user_info["tenant_id"])
        user_name = f"{user_info['first_name']} {user_info['last_name']}"
        user_email = user_info["email"]

        # Récupérer les admins du tenant (rôle ADMIN ou SUPER_ADMIN)
        admin_query = text("""
            SELECT DISTINCT u.id, u.email, u.first_name, u.last_name
            FROM users u
            JOIN user_role ur ON ur.user_id = u.id
            JOIN role r ON r.id = ur.role_id
            WHERE u.tenant_id = CAST(:tenant_id AS uuid)
              AND u.is_active = true
              AND r.code IN ('ADMIN', 'SUPER_ADMIN')
        """)
        admins = db.execute(admin_query, {"tenant_id": tenant_id}).fetchall()

        if not admins:
            logger.warning(f"⚠️ Aucun admin trouvé pour le tenant {tenant_id}")
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Aucun administrateur trouvé pour traiter votre demande"
            )

        # Titre de la conversation
        title = f"Demande de droits: {data.action_name}"

        # Message initial formaté
        initial_message = f"""🔐 **Demande de droits**

**Utilisateur:** {user_name} ({user_email})
**Permission demandée:** {data.permission_code}
**Action:** {data.action_name}

"""
        if data.message:
            initial_message += f"**Message:**\n{data.message}"
        else:
            initial_message += "L'utilisateur souhaite obtenir cette permission."

        # Créer la conversation de type RIGHTS
        insert_conv = text("""
            INSERT INTO conversation (type, title, tenant_id, created_by, created_by_type, created_at, updated_at)
            VALUES ('RIGHTS', :title, CAST(:tenant_id AS uuid), CAST(:created_by AS uuid), :created_by_type, NOW(), NOW())
            RETURNING id, type, title, object_id, campaign_id, tenant_id, created_by, created_by_type, created_at, updated_at, deleted_at
        """)
        conv_result = db.execute(insert_conv, {
            "title": title,
            "tenant_id": tenant_id,
            "created_by": user_id,
            "created_by_type": user_info["user_type"]
        }).fetchone()
        db.flush()

        conversation_id = str(conv_result.id)

        # Ajouter le demandeur comme participant
        insert_participant = text("""
            INSERT INTO conversation_participant (conversation_id, user_id, user_type, joined_at)
            VALUES (CAST(:conv_id AS uuid), CAST(:user_id AS uuid), :user_type, NOW())
        """)
        db.execute(insert_participant, {
            "conv_id": conversation_id,
            "user_id": user_id,
            "user_type": user_info["user_type"]
        })

        # Ajouter les admins comme participants
        admin_ids = []
        for admin in admins:
            if str(admin.id) != user_id:  # Ne pas ajouter le demandeur s'il est admin
                db.execute(insert_participant, {
                    "conv_id": conversation_id,
                    "user_id": str(admin.id),
                    "user_type": "user"
                })
                admin_ids.append(admin)

        # Créer le message initial
        insert_msg = text("""
            INSERT INTO message (conversation_id, author_id, author_type, body, attachments, is_system, metadata, created_at)
            VALUES (CAST(:conv_id AS uuid), CAST(:author_id AS uuid), :author_type, :body, '[]'::jsonb, false, :metadata, NOW())
            RETURNING id
        """)
        metadata = json.dumps({
            "permission_code": data.permission_code,
            "action_name": data.action_name,
            "requester_email": user_email
        })
        msg_result = db.execute(insert_msg, {
            "conv_id": conversation_id,
            "author_id": user_id,
            "author_type": user_info["user_type"],
            "body": initial_message,
            "metadata": metadata
        }).fetchone()

        # Créer les notifications et envoyer les emails aux admins
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

        # Trouver le rôle de l'utilisateur pour créer le lien direct
        user_role_query = text("""
            SELECT r.id, r.name
            FROM role r
            JOIN user_role ur ON ur.role_id = r.id
            WHERE ur.user_id = CAST(:user_id AS uuid)
            LIMIT 1
        """)
        user_role_result = db.execute(user_role_query, {"user_id": user_id}).fetchone()

        # Lien vers la page de gestion des rôles/permissions
        if user_role_result:
            permission_url = f"{frontend_url}/client/administration/roles/{user_role_result.id}"
        else:
            permission_url = f"{frontend_url}/client/administration/roles"

        conversation_url = f"{frontend_url}/client/discussions"

        for admin in admin_ids:
            # Notification en base
            insert_notif = text("""
                INSERT INTO conversation_notification
                (user_id, user_type, conversation_id, message_id, notification_type, is_read, created_at)
                VALUES (CAST(:user_id AS uuid), 'user', CAST(:conv_id AS uuid), CAST(:msg_id AS uuid), 'DISCUSSION_NEW_MESSAGE', false, NOW())
            """)
            db.execute(insert_notif, {
                "user_id": str(admin.id),
                "conv_id": conversation_id,
                "msg_id": str(msg_result.id)
            })

            # Email à l'admin avec lien direct vers la permission
            if admin.email:
                try:
                    from src.services.email_service import send_rights_request_email
                    send_rights_request_email(
                        to_email=admin.email,
                        admin_name=f"{admin.first_name} {admin.last_name}",
                        requester_name=user_name,
                        requester_email=user_email,
                        permission_code=data.permission_code,
                        action_name=data.action_name,
                        message=data.message,
                        permission_url=permission_url,
                        conversation_url=conversation_url
                    )
                    logger.info(f"📧 Email demande de droits envoyé à {admin.email}")
                except Exception as email_error:
                    logger.warning(f"⚠️ Échec envoi email demande de droits à {admin.email}: {email_error}")

        db.commit()

        logger.info(f"✅ Demande de droits créée: {data.permission_code} par {user_email}")

        return RightsRequestResponse(
            success=True,
            conversation_id=conv_result.id,
            message="Votre demande a été envoyée aux administrateurs"
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la création de demande de droits: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


class RightsRequestAction(BaseModel):
    """Schéma pour accepter/refuser une demande de droits"""
    action: str = Field(..., pattern="^(accept|reject)$", description="Action: 'accept' ou 'reject'")
    message: Optional[str] = Field(None, max_length=500, description="Message optionnel")


class RightsRequestActionResponse(BaseModel):
    """Réponse après action sur une demande de droits"""
    success: bool
    action: str
    message: str
    permissions_granted: Optional[List[str]] = None


@router.post("/{conversation_id}/rights-action", response_model=RightsRequestActionResponse)
async def process_rights_request(
    conversation_id: UUID,
    data: RightsRequestAction,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Accepte ou refuse une demande de droits.

    - Seuls les admins peuvent traiter les demandes
    - Si acceptée, les permissions sont ajoutées au rôle de l'utilisateur
    - Une notification est envoyée au demandeur
    """
    try:
        user_info = get_user_info_from_token(current_user, db)
        admin_id = str(user_info["user_id"])
        admin_name = f"{user_info['first_name']} {user_info['last_name']}"
        tenant_id = str(user_info["tenant_id"])

        # Vérifier que l'utilisateur est admin
        admin_check = text("""
            SELECT 1 FROM user_role ur
            JOIN role r ON r.id = ur.role_id
            WHERE ur.user_id = CAST(:user_id AS uuid)
              AND r.code IN ('ADMIN', 'SUPER_ADMIN')
        """)
        is_admin = db.execute(admin_check, {"user_id": admin_id}).fetchone()

        if not is_admin:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Seuls les administrateurs peuvent traiter les demandes de droits"
            )

        # Récupérer la conversation et vérifier que c'est une demande de droits
        conv_query = text("""
            SELECT c.id, c.type, c.created_by, c.created_by_type, c.tenant_id
            FROM conversation c
            WHERE c.id = CAST(:conv_id AS uuid)
              AND c.type = 'RIGHTS'
              AND c.deleted_at IS NULL
        """)
        conv = db.execute(conv_query, {"conv_id": str(conversation_id)}).fetchone()

        if not conv:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Conversation de demande de droits non trouvée"
            )

        # Récupérer le premier message avec les métadonnées de la demande
        msg_query = text("""
            SELECT m.id, m.author_id, m.author_type, m.metadata
            FROM message m
            WHERE m.conversation_id = CAST(:conv_id AS uuid)
            ORDER BY m.created_at ASC
            LIMIT 1
        """)
        first_msg = db.execute(msg_query, {"conv_id": str(conversation_id)}).fetchone()

        if not first_msg or not first_msg.metadata:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Métadonnées de la demande introuvables"
            )

        metadata = first_msg.metadata
        requester_id = str(conv.created_by)
        requester_type = conv.created_by_type
        permission_codes = metadata.get("permission_code", "").split(", ")
        requester_email = metadata.get("requester_email", "")

        # Récupérer les infos du demandeur
        if requester_type == "user":
            requester_query = text("""
                SELECT first_name, last_name, email FROM users
                WHERE id = CAST(:user_id AS uuid)
            """)
        else:
            requester_query = text("""
                SELECT first_name, last_name, email FROM entity_member
                WHERE id = CAST(:user_id AS uuid)
            """)
        requester_info = db.execute(requester_query, {"user_id": requester_id}).fetchone()
        requester_name = f"{requester_info.first_name} {requester_info.last_name}" if requester_info else "Utilisateur"

        permissions_granted = []

        if data.action == "accept":
            # Récupérer le rôle de l'utilisateur
            user_role_query = text("""
                SELECT r.id, r.code, r.name
                FROM role r
                JOIN user_role ur ON ur.role_id = r.id
                WHERE ur.user_id = CAST(:user_id AS uuid)
                ORDER BY r.created_at ASC
                LIMIT 1
            """)
            user_role = db.execute(user_role_query, {"user_id": requester_id}).fetchone()

            if not user_role:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="L'utilisateur n'a pas de rôle assigné"
                )

            # Récupérer les IDs des permissions demandées
            for perm_code in permission_codes:
                perm_code = perm_code.strip()
                if not perm_code:
                    continue

                perm_query = text("""
                    SELECT id FROM permission WHERE code = :code
                """)
                perm = db.execute(perm_query, {"code": perm_code}).fetchone()

                if perm:
                    # Vérifier si la permission n'est pas déjà attribuée
                    existing_check = text("""
                        SELECT 1 FROM role_permission
                        WHERE role_id = CAST(:role_id AS uuid)
                          AND permission_id = CAST(:perm_id AS uuid)
                    """)
                    existing = db.execute(existing_check, {
                        "role_id": str(user_role.id),
                        "perm_id": str(perm.id)
                    }).fetchone()

                    if not existing:
                        # Ajouter la permission au rôle
                        insert_perm = text("""
                            INSERT INTO role_permission (role_id, permission_id)
                            VALUES (CAST(:role_id AS uuid), CAST(:perm_id AS uuid))
                        """)
                        db.execute(insert_perm, {
                            "role_id": str(user_role.id),
                            "perm_id": str(perm.id)
                        })
                        permissions_granted.append(perm_code)
                        logger.info(f"✅ Permission {perm_code} ajoutée au rôle {user_role.name}")

            # Message système dans la conversation
            system_msg = f"✅ **Demande acceptée** par {admin_name}\n\n"
            if permissions_granted:
                system_msg += f"Permissions accordées: {', '.join(permissions_granted)}\n"
            if data.message:
                system_msg += f"\n{data.message}"

        else:  # reject
            system_msg = f"❌ **Demande refusée** par {admin_name}"
            if data.message:
                system_msg += f"\n\n{data.message}"

        # Ajouter le message système
        insert_sys_msg = text("""
            INSERT INTO message (conversation_id, author_id, author_type, body, attachments, is_system, metadata, created_at)
            VALUES (CAST(:conv_id AS uuid), CAST(:author_id AS uuid), :author_type, :body, '[]'::jsonb, true, :metadata, NOW())
            RETURNING id
        """)
        sys_msg_result = db.execute(insert_sys_msg, {
            "conv_id": str(conversation_id),
            "author_id": admin_id,
            "author_type": "user",
            "body": system_msg,
            "metadata": json.dumps({
                "action": data.action,
                "admin_id": admin_id,
                "permissions_granted": permissions_granted
            })
        }).fetchone()

        # Mettre à jour la conversation
        update_conv = text("""
            UPDATE conversation SET updated_at = NOW() WHERE id = CAST(:conv_id AS uuid)
        """)
        db.execute(update_conv, {"conv_id": str(conversation_id)})

        # Notification au demandeur
        insert_notif = text("""
            INSERT INTO conversation_notification
            (user_id, user_type, conversation_id, message_id, notification_type, is_read, created_at)
            VALUES (CAST(:user_id AS uuid), :user_type, CAST(:conv_id AS uuid), CAST(:msg_id AS uuid), 'ACCESS_REQUEST_UPDATED', false, NOW())
        """)
        db.execute(insert_notif, {
            "user_id": requester_id,
            "user_type": requester_type,
            "conv_id": str(conversation_id),
            "msg_id": str(sys_msg_result.id)
        })

        # Envoyer email au demandeur
        if requester_info and requester_info.email:
            frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
            conversation_url = f"{frontend_url}/client/discussions"

            try:
                from src.services.email_service import send_rights_decision_email
                send_rights_decision_email(
                    to_email=requester_info.email,
                    requester_name=requester_name,
                    admin_name=admin_name,
                    action=data.action,
                    permissions=permissions_granted if data.action == "accept" else permission_codes,
                    message=data.message,
                    conversation_url=conversation_url
                )
                logger.info(f"📧 Email décision droits envoyé à {requester_info.email}")
            except Exception as email_error:
                logger.warning(f"⚠️ Échec envoi email décision à {requester_info.email}: {email_error}")

        db.commit()

        action_text = "acceptée" if data.action == "accept" else "refusée"
        logger.info(f"✅ Demande de droits {action_text} par {admin_name} pour {requester_email}")

        return RightsRequestActionResponse(
            success=True,
            action=data.action,
            message=f"Demande {action_text} avec succès",
            permissions_granted=permissions_granted if data.action == "accept" else None
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors du traitement de la demande de droits: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
