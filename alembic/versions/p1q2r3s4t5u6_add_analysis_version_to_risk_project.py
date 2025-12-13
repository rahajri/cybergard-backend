"""Add analysis_version column to risk_project table

Revision ID: p1q2r3s4t5u6
Revises: o1p2q3r4s5t6
Create Date: 2024-12-10

Ajoute le champ analysis_version pour permettre la bascule
entre le mode legacy et le nouveau mode ebios_rm_v2 (ANSSI).

Valeurs possibles:
- 'legacy' : Comportement actuel conserve (defaut)
- 'ebios_rm_v2' : Nouveau pipeline IA conforme ANSSI
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'p1q2r3s4t5u6'
down_revision = 'o1p2q3r4s5t6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ajouter la colonne analysis_version avec valeur par defaut 'legacy'
    op.add_column(
        'risk_project',
        sa.Column(
            'analysis_version',
            sa.String(50),
            nullable=False,
            server_default='legacy'
        )
    )

    # Ajouter un index pour filtrer rapidement par version
    op.create_index(
        'ix_risk_project_analysis_version',
        'risk_project',
        ['analysis_version']
    )

    # Commentaire explicatif
    op.execute(
        "COMMENT ON COLUMN risk_project.analysis_version IS "
        "'Version du pipeline IA: legacy (existant) ou ebios_rm_v2 (conforme ANSSI)'"
    )


def downgrade() -> None:
    op.drop_index('ix_risk_project_analysis_version', table_name='risk_project')
    op.drop_column('risk_project', 'analysis_version')
