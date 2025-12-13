"""Add is_selected column to AT1 tables (risk_business_value, risk_asset, risk_feared_event)

Revision ID: k1l2m3n4o5p6
Revises: j1k2l3m4n5o6
Create Date: 2024-12-07

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'k1l2m3n4o5p6'
down_revision = 'j1k2l3m4n5o6'
branch_labels = None
depends_on = None


def upgrade():
    """Ajoute la colonne is_selected aux tables AT1 pour persister les sélections utilisateur."""

    # risk_business_value - Valeurs métier (default false - non sélectionné)
    op.add_column('risk_business_value', sa.Column('is_selected', sa.Boolean(), nullable=False, server_default='false'))

    # risk_asset - Biens supports (default false - non sélectionné)
    op.add_column('risk_asset', sa.Column('is_selected', sa.Boolean(), nullable=False, server_default='false'))

    # risk_feared_event - Événements redoutés (default false - non sélectionné)
    op.add_column('risk_feared_event', sa.Column('is_selected', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    """Supprime les colonnes is_selected."""

    op.drop_column('risk_feared_event', 'is_selected')
    op.drop_column('risk_asset', 'is_selected')
    op.drop_column('risk_business_value', 'is_selected')
