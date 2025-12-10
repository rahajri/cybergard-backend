"""Add CVE columns to published_action table

Adds cve_ids, cvss_score, cve_source_url and scan_action_plan_item_id columns
to support CVE tracking for actions generated from scanner vulnerabilities.

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2024-12-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'j1k2l3m4n5o6'
down_revision = 'i1j2k3l4m5n6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add CVE columns to published_action table."""

    # Add cve_ids column (array of strings for CVE identifiers)
    op.add_column(
        'published_action',
        sa.Column('cve_ids', postgresql.ARRAY(sa.String()), nullable=True, default=[])
    )

    # Add cvss_score column (float for CVSS score 0.0-10.0)
    op.add_column(
        'published_action',
        sa.Column('cvss_score', sa.Float(), nullable=True)
    )

    # Add cve_source_url column (link to NVD or other CVE source)
    op.add_column(
        'published_action',
        sa.Column('cve_source_url', sa.String(500), nullable=True)
    )

    # Add scan_action_plan_item_id column (FK to scan_action_plan_item)
    op.add_column(
        'published_action',
        sa.Column(
            'scan_action_plan_item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('scan_action_plan_item.id', ondelete='SET NULL'),
            nullable=True
        )
    )

    # Create index on cve_ids for faster lookups
    op.create_index(
        'ix_published_action_cve_ids',
        'published_action',
        ['cve_ids'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    """Remove CVE columns from published_action table."""

    # Drop index first
    op.drop_index('ix_published_action_cve_ids', table_name='published_action')

    # Drop columns
    op.drop_column('published_action', 'scan_action_plan_item_id')
    op.drop_column('published_action', 'cve_source_url')
    op.drop_column('published_action', 'cvss_score')
    op.drop_column('published_action', 'cve_ids')
