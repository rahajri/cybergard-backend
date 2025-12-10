"""Add risk_project_id column to generated_report for EBIOS RM reports

Revision ID: l1m2n3o4p5q6
Revises: k1l2m3n4o5p6
Create Date: 2024-12-07

Cette migration ajoute le support des rapports EBIOS RM dans la table generated_report.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l1m2n3o4p5q6'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade():
    """Ajoute la colonne risk_project_id pour les rapports EBIOS RM."""

    # 1. Ajouter la colonne risk_project_id (FK vers risk_project)
    op.add_column('generated_report', sa.Column('risk_project_id', sa.UUID(), nullable=True))

    # 2. Créer un index pour les recherches
    op.create_index('idx_generated_report_risk_project', 'generated_report', ['risk_project_id'])

    # 3. Ajouter la FK vers risk_project
    op.create_foreign_key(
        'fk_generated_report_risk_project',
        'generated_report',
        'risk_project',
        ['risk_project_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # 4. Modifier la contrainte check pour accepter les nouveaux scopes EBIOS
    # D'abord supprimer l'ancienne contrainte
    op.drop_constraint('chk_report_scope_entity_consistency', 'generated_report')

    # Recréer avec les scopes EBIOS ajoutés
    op.create_check_constraint(
        'chk_report_scope_entity_consistency',
        'generated_report',
        """
        (report_scope = 'consolidated' AND entity_id IS NULL) OR
        (report_scope = 'entity' AND entity_id IS NOT NULL) OR
        (report_scope IN ('scan_individual', 'scan_ecosystem')) OR
        (report_scope IN ('ebios_consolidated', 'ebios_individual') AND risk_project_id IS NOT NULL)
        """
    )


def downgrade():
    """Supprime la colonne risk_project_id."""

    # 1. Supprimer la contrainte modifiée
    op.drop_constraint('chk_report_scope_entity_consistency', 'generated_report')

    # Recréer l'ancienne contrainte
    op.create_check_constraint(
        'chk_report_scope_entity_consistency',
        'generated_report',
        """
        (report_scope = 'consolidated' AND entity_id IS NULL) OR
        (report_scope = 'entity' AND entity_id IS NOT NULL) OR
        (report_scope IN ('scan_individual', 'scan_ecosystem'))
        """
    )

    # 2. Supprimer la FK
    op.drop_constraint('fk_generated_report_risk_project', 'generated_report', type_='foreignkey')

    # 3. Supprimer l'index
    op.drop_index('idx_generated_report_risk_project', table_name='generated_report')

    # 4. Supprimer la colonne
    op.drop_column('generated_report', 'risk_project_id')
