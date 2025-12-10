"""add_is_platform_owner_to_organizations

Revision ID: 0121555e5b5f
Revises: 1a10ff06de34
Create Date: 2025-11-05 13:51:31.989547

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0121555e5b5f'
down_revision: Union[str, None] = '1a10ff06de34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter la colonne is_platform_owner
    op.add_column('organizations',
        sa.Column('is_platform_owner', sa.Boolean(), nullable=False, server_default='false')
    )

    # Mettre à jour l'organisation "Administration Plateforme" pour qu'elle soit marquée comme plateforme
    op.execute("""
        UPDATE organizations
        SET is_platform_owner = true
        WHERE name = 'Administration Plateforme'
    """)


def downgrade() -> None:
    # Supprimer la colonne is_platform_owner
    op.drop_column('organizations', 'is_platform_owner')
