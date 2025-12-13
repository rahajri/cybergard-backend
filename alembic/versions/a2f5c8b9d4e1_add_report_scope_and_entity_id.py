"""add_report_scope_and_entity_id

Revision ID: a2f5c8b9d4e1
Revises: 51462ba64e63
Create Date: 2025-11-25 10:00:00.000000

Migration pour supporter les deux types de rapports :
- CONSOLIDÉ (multi-organismes) : report_scope='consolidated', entity_id=NULL
- INDIVIDUEL (mono-organisme) : report_scope='entity', entity_id=UUID

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2f5c8b9d4e1'
down_revision: Union[str, None] = '51462ba64e63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================
    # 1. Ajouter report_scope à generated_report
    # ============================================
    op.add_column(
        'generated_report',
        sa.Column(
            'report_scope',
            sa.String(50),
            nullable=False,
            server_default='consolidated'  # Défaut pour rétrocompatibilité
        )
    )

    # ============================================
    # 2. Ajouter entity_id à generated_report
    # ============================================
    op.add_column(
        'generated_report',
        sa.Column(
            'entity_id',
            sa.UUID(),
            nullable=True
        )
    )

    # Foreign key vers ecosystem_entity
    op.create_foreign_key(
        'fk_generated_report_entity',
        'generated_report',
        'ecosystem_entity',
        ['entity_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # ============================================
    # 3. Ajouter report_scope à report_template
    # ============================================
    op.add_column(
        'report_template',
        sa.Column(
            'report_scope',
            sa.String(50),
            nullable=False,
            server_default='consolidated'  # Défaut pour templates existants
        )
    )

    # ============================================
    # 4. Créer les index
    # ============================================
    op.create_index(
        'idx_generated_report_scope',
        'generated_report',
        ['report_scope']
    )

    op.create_index(
        'idx_generated_report_entity',
        'generated_report',
        ['entity_id']
    )

    op.create_index(
        'idx_report_template_scope',
        'report_template',
        ['report_scope']
    )

    # ============================================
    # 5. Ajouter CHECK constraint pour cohérence
    # ============================================
    # entity_id DOIT être NULL si scope='consolidated'
    # entity_id DOIT être NOT NULL si scope='entity'
    op.execute("""
        ALTER TABLE generated_report
        ADD CONSTRAINT chk_report_scope_entity_consistency
        CHECK (
            (report_scope = 'consolidated' AND entity_id IS NULL)
            OR
            (report_scope = 'entity' AND entity_id IS NOT NULL)
        )
    """)

    # ============================================
    # 6. Ajouter entity_id à report_chart_cache
    # ============================================
    op.add_column(
        'report_chart_cache',
        sa.Column(
            'entity_id',
            sa.UUID(),
            nullable=True
        )
    )

    op.create_foreign_key(
        'fk_report_chart_cache_entity',
        'report_chart_cache',
        'ecosystem_entity',
        ['entity_id'],
        ['id'],
        ondelete='CASCADE'
    )

    op.create_index(
        'idx_chart_cache_entity',
        'report_chart_cache',
        ['entity_id']
    )


def downgrade() -> None:
    # Supprimer dans l'ordre inverse

    # report_chart_cache
    op.drop_index('idx_chart_cache_entity', table_name='report_chart_cache')
    op.drop_constraint('fk_report_chart_cache_entity', 'report_chart_cache', type_='foreignkey')
    op.drop_column('report_chart_cache', 'entity_id')

    # CHECK constraint
    op.execute("""
        ALTER TABLE generated_report
        DROP CONSTRAINT IF EXISTS chk_report_scope_entity_consistency
    """)

    # Indexes
    op.drop_index('idx_report_template_scope', table_name='report_template')
    op.drop_index('idx_generated_report_entity', table_name='generated_report')
    op.drop_index('idx_generated_report_scope', table_name='generated_report')

    # report_template
    op.drop_column('report_template', 'report_scope')

    # generated_report
    op.drop_constraint('fk_generated_report_entity', 'generated_report', type_='foreignkey')
    op.drop_column('generated_report', 'entity_id')
    op.drop_column('generated_report', 'report_scope')
