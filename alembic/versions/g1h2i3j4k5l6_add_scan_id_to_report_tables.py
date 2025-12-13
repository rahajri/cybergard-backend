"""add_scan_id_to_report_tables

Revision ID: g1h2i3j4k5l6
Revises: f1a2b3c4d5e6
Create Date: 2024-12-03

Ajoute le support des rapports scanner :
- scan_id dans generated_report
- scan_id dans report_chart_cache
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = 'g1h2i3j4k5l6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ajouter scan_id à generated_report
    op.add_column(
        'generated_report',
        sa.Column(
            'scan_id',
            UUID(as_uuid=True),
            sa.ForeignKey('external_scan.id', ondelete='SET NULL'),
            nullable=True
        )
    )

    # Index sur scan_id pour performance
    op.create_index(
        'idx_generated_report_scan_id',
        'generated_report',
        ['scan_id']
    )

    # Ajouter scan_id à report_chart_cache
    op.add_column(
        'report_chart_cache',
        sa.Column(
            'scan_id',
            UUID(as_uuid=True),
            sa.ForeignKey('external_scan.id', ondelete='CASCADE'),
            nullable=True
        )
    )

    # Index sur scan_id dans cache
    op.create_index(
        'idx_report_chart_cache_scan_id',
        'report_chart_cache',
        ['scan_id']
    )


def downgrade() -> None:
    # Supprimer index et colonnes
    op.drop_index('idx_report_chart_cache_scan_id', 'report_chart_cache')
    op.drop_column('report_chart_cache', 'scan_id')

    op.drop_index('idx_generated_report_scan_id', 'generated_report')
    op.drop_column('generated_report', 'scan_id')
