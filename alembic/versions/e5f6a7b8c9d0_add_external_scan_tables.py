"""Add external scan tables (ASM module)

Revision ID: e5f6a7b8c9d0
Revises: d7f8c9e1a2b3
Create Date: 2024-12-01 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd7f8c9e1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===========================================================================
    # TABLE: external_target
    # Cibles externes à scanner (domaines, IPs, sous-domaines)
    # ===========================================================================
    op.create_table(
        'external_target',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('type', sa.String(50), nullable=False),  # DOMAIN, SUBDOMAIN, IP, IP_RANGE, EMAIL_DOMAIN
        sa.Column('value', sa.String(255), nullable=False),
        sa.Column('label', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scan_frequency', sa.String(20), default='MANUAL'),  # MANUAL, DAILY, WEEKLY, MONTHLY
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('last_scan_at', sa.DateTime(), nullable=True),
        sa.Column('last_scan_status', sa.String(20), default='NEVER'),  # NEVER, SUCCESS, ERROR
        sa.Column('last_exposure_score', sa.Integer(), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    # Index pour external_target
    op.create_index('ix_external_target_tenant_type', 'external_target', ['tenant_id', 'type'])
    op.create_index('ix_external_target_value', 'external_target', ['value'])

    # ===========================================================================
    # TABLE: external_scan
    # Historique des scans effectués
    # ===========================================================================
    op.create_table(
        'external_scan',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('external_target_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('external_target.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('status', sa.String(20), default='PENDING'),  # PENDING, RUNNING, SUCCESS, ERROR, CANCELLED
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('summary', postgresql.JSONB(), nullable=True),
        sa.Column('report_generated', sa.Boolean(), default=False),
        sa.Column('report_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('triggered_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('trigger_type', sa.String(50), default='manual'),  # manual, scheduled, api
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Index pour external_scan
    op.create_index('ix_external_scan_target', 'external_scan', ['external_target_id'])
    op.create_index('ix_external_scan_status', 'external_scan', ['status'])
    op.create_index('ix_external_scan_created', 'external_scan', ['created_at'])

    # ===========================================================================
    # TABLE: external_service_vulnerability
    # Vulnérabilités détectées lors d'un scan
    # ===========================================================================
    op.create_table(
        'external_service_vulnerability',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('external_scan_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('external_scan.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        # Informations du service
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('protocol', sa.String(20), nullable=True),  # tcp, udp
        sa.Column('service_name', sa.String(100), nullable=True),
        sa.Column('service_version', sa.String(100), nullable=True),
        sa.Column('service_banner', sa.Text(), nullable=True),
        # Type et sévérité
        sa.Column('vulnerability_type', sa.String(50), nullable=False),  # PORT_EXPOSED, SERVICE_VULN, TLS_WEAK, etc.
        sa.Column('severity', sa.String(20), nullable=False),  # CRITICAL, HIGH, MEDIUM, LOW, INFO
        # Détails CVE
        sa.Column('cve_ids', postgresql.JSONB(), nullable=True),
        sa.Column('cvss_score', sa.Float(), nullable=True),
        sa.Column('cvss_vector', sa.String(100), nullable=True),
        # Description et recommandation
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        # Références externes
        sa.Column('references', postgresql.JSONB(), nullable=True),
        # Statut de remédiation
        sa.Column('is_remediated', sa.Boolean(), default=False),
        sa.Column('remediated_at', sa.DateTime(), nullable=True),
        sa.Column('remediated_by', postgresql.UUID(as_uuid=True), nullable=True),
        # Métadonnées
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Index pour external_service_vulnerability
    op.create_index('ix_vuln_scan', 'external_service_vulnerability', ['external_scan_id'])
    op.create_index('ix_vuln_severity', 'external_service_vulnerability', ['severity'])
    op.create_index('ix_vuln_type', 'external_service_vulnerability', ['vulnerability_type'])

    # ===========================================================================
    # TABLE: external_email_exposure (V2 - OSINT)
    # Emails exposés dans des fuites de données
    # ===========================================================================
    op.create_table(
        'external_email_exposure',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('external_scan_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('external_scan.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        # Informations de l'email
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('breach_count', sa.Integer(), default=0),
        sa.Column('last_breach_date', sa.Date(), nullable=True),
        sa.Column('sources', postgresql.JSONB(), nullable=True),
        # Recommandation
        sa.Column('recommendation', sa.Text(), nullable=True),
        # Statut
        sa.Column('is_remediated', sa.Boolean(), default=False),
        sa.Column('remediated_at', sa.DateTime(), nullable=True),
        # Métadonnées
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Index pour external_email_exposure
    op.create_index('ix_email_scan', 'external_email_exposure', ['external_scan_id'])
    op.create_index('ix_email_address', 'external_email_exposure', ['email'])


def downgrade() -> None:
    # Supprimer les tables dans l'ordre inverse (dépendances)
    op.drop_table('external_email_exposure')
    op.drop_table('external_service_vulnerability')
    op.drop_table('external_scan')
    op.drop_table('external_target')
