"""add_report_tables

Revision ID: 51462ba64e63
Revises: 6c8ab8893574
Create Date: 2025-11-24 19:36:10.696544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '51462ba64e63'
down_revision: Union[str, None] = '6c8ab8893574'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Créer la table report_template
    op.create_table(
        'report_template',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('code', sa.String(50), nullable=True),
        sa.Column('template_type', sa.String(50), nullable=False, server_default='custom'),
        sa.Column('is_system', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('is_default', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('page_size', sa.String(20), nullable=True, server_default='A4'),
        sa.Column('orientation', sa.String(20), nullable=True, server_default='portrait'),
        sa.Column('margins', sa.JSON(), nullable=True),
        sa.Column('color_scheme', sa.JSON(), nullable=True),
        sa.Column('fonts', sa.JSON(), nullable=True),
        sa.Column('custom_css', sa.Text(), nullable=True),
        sa.Column('default_logo', sa.String(50), nullable=True, server_default='TENANT'),
        sa.Column('structure', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index('idx_report_template_tenant', 'report_template', ['tenant_id'])
    op.create_index('idx_report_template_type', 'report_template', ['template_type'])
    op.create_index('idx_report_template_system', 'report_template', ['is_system'])

    # Créer la table report_widget
    op.create_table(
        'report_widget',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('template_id', sa.UUID(), nullable=False),
        sa.Column('widget_type', sa.String(100), nullable=False),
        sa.Column('widget_key', sa.String(100), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('parent_widget_id', sa.UUID(), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('display_condition', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['template_id'], ['report_template.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_widget_id'], ['report_widget.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_report_widget_template', 'report_widget', ['template_id'])
    op.create_index('idx_report_widget_parent', 'report_widget', ['parent_widget_id'])
    op.create_index('idx_report_widget_position', 'report_widget', ['template_id', 'position'])

    # Créer la table generated_report
    op.create_table(
        'generated_report',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=True),
        sa.Column('audit_id', sa.UUID(), nullable=True),
        sa.Column('template_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('generation_mode', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('report_data', sa.JSON(), nullable=True),
        sa.Column('report_metadata', sa.JSON(), nullable=True),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('file_name', sa.String(255), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('file_mime_type', sa.String(100), nullable=True, server_default='application/pdf'),
        sa.Column('file_checksum', sa.String(64), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('generation_time_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details', sa.JSON(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('is_latest', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('previous_version_id', sa.UUID(), nullable=True),
        sa.Column('generated_by', sa.UUID(), nullable=True),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.Column('downloaded_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('last_downloaded_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaign.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['template_id'], ['report_template.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['previous_version_id'], ['generated_report.id']),
        sa.ForeignKeyConstraint(['generated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_generated_report_tenant', 'generated_report', ['tenant_id'])
    op.create_index('idx_generated_report_campaign', 'generated_report', ['campaign_id'])
    op.create_index('idx_generated_report_audit', 'generated_report', ['audit_id'])
    op.create_index('idx_generated_report_status', 'generated_report', ['status'])

    # Créer la table report_generation_job
    op.create_table(
        'report_generation_job',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='queued'),
        sa.Column('progress_percent', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('current_step', sa.String(100), nullable=True),
        sa.Column('total_steps', sa.Integer(), nullable=True),
        sa.Column('current_step_number', sa.Integer(), nullable=True),
        sa.Column('queued_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('worker_id', sa.String(100), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=True, server_default='3'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_stack', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['report_id'], ['generated_report.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_report_job_status', 'report_generation_job', ['status'])

    # Créer la table report_chart_cache
    op.create_table(
        'report_chart_cache',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=True),
        sa.Column('audit_id', sa.UUID(), nullable=True),
        sa.Column('chart_type', sa.String(100), nullable=False),
        sa.Column('chart_key', sa.String(255), nullable=False),
        sa.Column('chart_config', sa.JSON(), nullable=True),
        sa.Column('chart_data', sa.JSON(), nullable=False),
        sa.Column('image_data', sa.LargeBinary(), nullable=True),
        sa.Column('image_format', sa.String(10), nullable=True, server_default='png'),
        sa.Column('image_width', sa.Integer(), nullable=True),
        sa.Column('image_height', sa.Integer(), nullable=True),
        sa.Column('data_hash', sa.String(64), nullable=True),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaign.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_chart_cache_campaign', 'report_chart_cache', ['campaign_id'])
    op.create_index('idx_chart_cache_audit', 'report_chart_cache', ['audit_id'])
    op.create_index('idx_chart_cache_expires', 'report_chart_cache', ['expires_at'])


def downgrade() -> None:
    # Supprimer les tables dans l'ordre inverse (à cause des FK)
    op.drop_table('report_chart_cache')
    op.drop_table('report_generation_job')
    op.drop_table('generated_report')
    op.drop_table('report_widget')
    op.drop_table('report_template')
