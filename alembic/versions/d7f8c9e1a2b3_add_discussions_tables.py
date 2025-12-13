"""add_discussions_tables

Revision ID: d7f8c9e1a2b3
Revises: a2f5c8b9d4e1
Create Date: 2025-12-01 10:00:00.000000

Migration pour le module Discussions:
- conversation: Conversations/discussions entre utilisateurs
- message: Messages dans les conversations
- conversation_participant: Table d'association participants
- conversation_notification: Notifications pour les discussions
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = 'd7f8c9e1a2b3'
down_revision: Union[str, None] = 'a2f5c8b9d4e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Créer le type ENUM pour les types de conversation
    conversation_type_enum = sa.Enum(
        'RIGHTS', 'ACTION', 'QUESTION', 'DIRECT_MESSAGE',
        name='conversation_type_enum'
    )
    conversation_type_enum.create(op.get_bind(), checkfirst=True)

    # 2. Créer la table conversation
    op.create_table(
        'conversation',
        sa.Column('id', UUID(as_uuid=True), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('type', sa.Enum('RIGHTS', 'ACTION', 'QUESTION', 'DIRECT_MESSAGE', name='conversation_type_enum'), nullable=False),
        sa.Column('object_id', UUID(as_uuid=True), nullable=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
        sa.Column('campaign_id', UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('created_by', UUID(as_uuid=True), nullable=False),
        sa.Column('created_by_type', sa.String(50), nullable=False, server_default='entity_member'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_by', UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaign.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # Index pour conversation
    op.create_index('ix_conversation_tenant_id', 'conversation', ['tenant_id'])
    op.create_index('ix_conversation_type', 'conversation', ['type'])
    op.create_index('ix_conversation_object_id', 'conversation', ['object_id'])
    op.create_index('ix_conversation_campaign_id', 'conversation', ['campaign_id'])
    op.create_index('ix_conversation_tenant_type', 'conversation', ['tenant_id', 'type'])
    op.create_index('ix_conversation_type_object', 'conversation', ['type', 'object_id'])
    op.create_index('ix_conversation_created_at', 'conversation', ['created_at'])

    # 3. Créer la table message
    op.create_table(
        'message',
        sa.Column('id', UUID(as_uuid=True), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('author_id', UUID(as_uuid=True), nullable=True),  # NULL pour messages système
        sa.Column('author_type', sa.String(50), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('attachments', JSONB, nullable=False, server_default='[]'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('metadata', JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Index pour message
    op.create_index('ix_message_conversation_id', 'message', ['conversation_id'])
    op.create_index('ix_message_author_id', 'message', ['author_id'])
    op.create_index('ix_message_conversation_created', 'message', ['conversation_id', 'created_at'])
    op.create_index('ix_message_created_at', 'message', ['created_at'])

    # 4. Créer la table conversation_participant
    op.create_table(
        'conversation_participant',
        sa.Column('id', UUID(as_uuid=True), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_type', sa.String(50), nullable=False, server_default='entity_member'),
        sa.Column('joined_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('last_read_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Index pour conversation_participant
    op.create_index('ix_conv_participant_conversation', 'conversation_participant', ['conversation_id'])
    op.create_index('ix_conv_participant_user', 'conversation_participant', ['user_id'])
    op.create_index('ix_conv_participant_unique', 'conversation_participant', ['conversation_id', 'user_id'], unique=True)

    # 5. Créer la table conversation_notification
    op.create_table(
        'conversation_notification',
        sa.Column('id', UUID(as_uuid=True), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_type', sa.String(50), nullable=False, server_default='entity_member'),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', UUID(as_uuid=True), nullable=True),
        sa.Column('notification_type', sa.String(50), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['message.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Index pour conversation_notification
    op.create_index('ix_conv_notif_user_id', 'conversation_notification', ['user_id'])
    op.create_index('ix_conv_notif_user_unread', 'conversation_notification', ['user_id', 'is_read'])
    op.create_index('ix_conv_notif_conversation', 'conversation_notification', ['conversation_id'])
    op.create_index('ix_conv_notif_created_at', 'conversation_notification', ['created_at'])


def downgrade() -> None:
    # Supprimer les tables dans l'ordre inverse
    op.drop_table('conversation_notification')
    op.drop_table('conversation_participant')
    op.drop_table('message')
    op.drop_table('conversation')

    # Supprimer le type ENUM
    sa.Enum(name='conversation_type_enum').drop(op.get_bind(), checkfirst=True)
