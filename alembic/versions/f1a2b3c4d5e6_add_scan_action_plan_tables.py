"""Add scan_action_plan tables for ASM module

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2024-12-02 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===========================================================================
    # TABLE: scan_action_plan
    # Plan d'action généré à partir d'un scan externe
    # ===========================================================================
    op.create_table(
        'scan_action_plan',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scan_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('external_scan.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        # Statut du plan
        sa.Column('status', sa.String(20), default='DRAFT'),  # DRAFT, PUBLISHED, ARCHIVED
        # Compteurs
        sa.Column('total_items', sa.Integer(), default=0),
        sa.Column('critical_count', sa.Integer(), default=0),
        sa.Column('high_count', sa.Integer(), default=0),
        sa.Column('medium_count', sa.Integer(), default=0),
        sa.Column('low_count', sa.Integer(), default=0),
        sa.Column('validated_count', sa.Integer(), default=0),
        sa.Column('excluded_count', sa.Integer(), default=0),
        # Filtres utilisés pour la génération
        sa.Column('filters', postgresql.JSONB(), nullable=True),
        # Timestamps
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.Column('generated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('published_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    # Index pour scan_action_plan
    op.create_index('ix_scan_action_plan_scan', 'scan_action_plan', ['scan_id'])
    op.create_index('ix_scan_action_plan_status', 'scan_action_plan', ['status'])
    op.create_index('ix_scan_action_plan_tenant', 'scan_action_plan', ['tenant_id'])

    # ===========================================================================
    # TABLE: scan_action_plan_item
    # Items individuels du plan d'action (une action par vulnérabilité)
    # ===========================================================================
    op.create_table(
        'scan_action_plan_item',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('scan_action_plan.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vulnerability_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('external_service_vulnerability.id', ondelete='SET NULL'), nullable=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        # Informations de l'action
        sa.Column('code_action', sa.String(50), nullable=True),  # ACT_SCAN_XXXX
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        # Sévérité et priorité
        sa.Column('severity', sa.String(20), nullable=False),  # CRITICAL, HIGH, MEDIUM, LOW
        sa.Column('priority', sa.String(10), nullable=False),  # P1, P2, P3
        sa.Column('recommended_due_days', sa.Integer(), default=30),
        # Informations du service
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('service_name', sa.String(100), nullable=True),
        sa.Column('protocol', sa.String(20), nullable=True),
        # CVE et CVSS
        sa.Column('cve_ids', postgresql.JSONB(), nullable=True),
        sa.Column('cvss_score', sa.Float(), nullable=True),
        # Statut de l'item dans le plan
        sa.Column('status', sa.String(20), default='PENDING'),  # PENDING, VALIDATED, EXCLUDED
        sa.Column('included', sa.Boolean(), default=True),
        # Lien vers action publiée
        sa.Column('published_action_id', postgresql.UUID(as_uuid=True), nullable=True),
        # Assignation optionnelle
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('entity_name', sa.String(255), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    # Index pour scan_action_plan_item
    op.create_index('ix_scan_action_plan_item_plan', 'scan_action_plan_item', ['plan_id'])
    op.create_index('ix_scan_action_plan_item_vuln', 'scan_action_plan_item', ['vulnerability_id'])
    op.create_index('ix_scan_action_plan_item_severity', 'scan_action_plan_item', ['severity'])
    op.create_index('ix_scan_action_plan_item_status', 'scan_action_plan_item', ['status'])

    # ===========================================================================
    # Ajouter colonne code_scan à external_scan si elle n'existe pas
    # ===========================================================================
    # Note: Cette colonne peut déjà exister, utiliser try/except
    try:
        op.add_column('external_scan', sa.Column('code_scan', sa.String(50), nullable=True))
        op.create_index('ix_external_scan_code', 'external_scan', ['code_scan'])
    except Exception:
        pass  # La colonne existe déjà


def downgrade() -> None:
    # Supprimer les tables dans l'ordre inverse (dépendances)
    op.drop_table('scan_action_plan_item')
    op.drop_table('scan_action_plan')

    # Supprimer la colonne code_scan si elle a été ajoutée
    try:
        op.drop_index('ix_external_scan_code', 'external_scan')
        op.drop_column('external_scan', 'code_scan')
    except Exception:
        pass
