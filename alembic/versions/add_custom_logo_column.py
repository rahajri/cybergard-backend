"""Add custom_logo column to report_template

Revision ID: add_custom_logo_001
Revises:
Create Date: 2024-11-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_custom_logo_001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Ajouter la colonne custom_logo
    op.add_column('report_template',
        sa.Column('custom_logo', sa.Text(), nullable=True)
    )


def downgrade():
    # Supprimer la colonne custom_logo
    op.drop_column('report_template', 'custom_logo')
