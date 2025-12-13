"""Add AI matrix analysis column to risk_project

Revision ID: q1r2s3t4u5v6
Revises: p1q2r3s4t5u6
Create Date: 2024-12-11

Stockage de l'analyse IA de la matrice des risques (AT5)
pour éviter de regénérer à chaque consultation.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'q1r2s3t4u5v6'
down_revision = 'p1q2r3s4t5u6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ajouter la colonne pour stocker l'analyse IA de la matrice AT5
    op.add_column(
        'risk_project',
        sa.Column('ai_matrix_analysis', sa.Text(), nullable=True,
                  comment='Analyse IA de la matrice des risques (AT5)')
    )

    # Ajouter la date de dernière analyse
    op.add_column(
        'risk_project',
        sa.Column('ai_matrix_analysis_at', sa.DateTime(), nullable=True,
                  comment='Date de dernière analyse IA de la matrice')
    )


def downgrade() -> None:
    op.drop_column('risk_project', 'ai_matrix_analysis_at')
    op.drop_column('risk_project', 'ai_matrix_analysis')
