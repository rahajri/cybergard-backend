"""add_is_platform_owner_to_organization

Revision ID: b6b0ed51a6cf
Revises: 0121555e5b5f
Create Date: 2025-11-05 18:57:45.751550

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6b0ed51a6cf'
down_revision: Union[str, None] = '0121555e5b5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter la colonne is_platform_owner dans la table organization (sans s)
    op.add_column('organization',
        sa.Column('is_platform_owner', sa.Boolean(), nullable=False, server_default='false')
    )

    # Mettre à jour l'organisation "Administration Plateforme" pour qu'elle soit marquée comme plateforme
    op.execute("""
        UPDATE organization
        SET is_platform_owner = true
        WHERE name = 'Administration Plateforme'
    """)


def downgrade() -> None:
    # Supprimer la colonne is_platform_owner
    op.drop_column('organization', 'is_platform_owner')
