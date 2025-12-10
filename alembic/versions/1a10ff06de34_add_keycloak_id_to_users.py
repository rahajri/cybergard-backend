"""add_keycloak_id_to_users

Revision ID: 1a10ff06de34
Revises: f48e687278ce
Create Date: 2025-11-04 14:24:01.428450

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a10ff06de34'
down_revision: Union[str, None] = 'f48e687278ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter la colonne keycloak_id à la table users
    op.add_column('users', sa.Column('keycloak_id', sa.String(length=255), nullable=True))

    # Créer un index unique sur keycloak_id
    op.create_index('ix_users_keycloak_id', 'users', ['keycloak_id'], unique=True)


def downgrade() -> None:
    # Supprimer l'index
    op.drop_index('ix_users_keycloak_id', table_name='users')

    # Supprimer la colonne
    op.drop_column('users', 'keycloak_id')
