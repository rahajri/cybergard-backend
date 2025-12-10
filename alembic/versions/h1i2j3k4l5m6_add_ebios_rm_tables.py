"""Add EBIOS RM tables

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2024-12-04

Module EBIOS RM - Analyse de risques selon méthodologie ANSSI
- 5 ateliers officiels (AT1 → AT5)
- Matrice des risques 4×4
- Génération IA assistée
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'h1i2j3k4l5m6'
down_revision = 'a2f5c8b9d4e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===========================================================================
    # TABLE: risk_project
    # Projets EBIOS RM (équivalent d'une campagne)
    # ===========================================================================
    op.create_table(
        'risk_project',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('method', sa.String(50), nullable=False, server_default='EBIOS_RM'),
        sa.Column('status', sa.String(50), nullable=False, server_default='DRAFT'),  # DRAFT, IN_PROGRESS, FROZEN, ARCHIVED
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        # Périmètre (organismes/entités concernés)
        sa.Column('scope_entity_ids', postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        # Pilotes et contributeurs
        sa.Column('pilot_user_ids', postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column('contributor_user_ids', postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        # IA - Contexte initial du mini-chat
        sa.Column('ai_initial_context', postgresql.JSONB(), nullable=True),
        # Dates de gel
        sa.Column('frozen_at', sa.DateTime(), nullable=True),
        sa.Column('frozen_by', postgresql.UUID(as_uuid=True), nullable=True),
        # Audit
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    op.create_index('ix_risk_project_tenant', 'risk_project', ['tenant_id'])
    op.create_index('ix_risk_project_status', 'risk_project', ['status'])

    # ===========================================================================
    # TABLE: risk_workshop
    # Ateliers EBIOS (AT1 à AT5)
    # ===========================================================================
    op.create_table(
        'risk_workshop',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(10), nullable=False),  # AT1, AT2, AT3, AT4, AT5
        sa.Column('status', sa.String(50), nullable=False, server_default='NOT_STARTED'),  # NOT_STARTED, IN_PROGRESS, COMPLETED
        sa.Column('completion_percent', sa.Integer(), nullable=True, server_default='0'),
        # Historique des interactions IA
        sa.Column('ai_raw_input', postgresql.JSONB(), nullable=True),
        sa.Column('ai_raw_output', postgresql.JSONB(), nullable=True),
        sa.Column('ai_last_generation_at', sa.DateTime(), nullable=True),
        # Audit
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.create_index('ix_risk_workshop_project', 'risk_workshop', ['project_id'])
    op.create_index('ix_risk_workshop_type', 'risk_workshop', ['type'])
    op.create_unique_constraint('uq_risk_workshop_project_type', 'risk_workshop', ['project_id', 'type'])

    # ===========================================================================
    # TABLE: risk_business_value
    # Atelier 1 - Valeurs métier
    # ===========================================================================
    op.create_table(
        'risk_business_value',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('criticality', sa.Integer(), nullable=False, server_default='2'),  # 1-4
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        # Source IA ou manuel
        sa.Column('source', sa.String(20), nullable=True, server_default='MANUAL'),  # MANUAL, AI
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    op.create_index('ix_risk_business_value_project', 'risk_business_value', ['project_id'])

    # ===========================================================================
    # TABLE: risk_asset
    # Atelier 1 - Biens supports
    # ===========================================================================
    op.create_table(
        'risk_asset',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('type', sa.String(100), nullable=True),  # Serveur, Application, Réseau, Données, Personnel...
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('criticality', sa.Integer(), nullable=False, server_default='2'),  # 1-4
        # Lien optionnel avec organisme du périmètre
        sa.Column('linked_organism_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('source', sa.String(20), nullable=True, server_default='MANUAL'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    op.create_index('ix_risk_asset_project', 'risk_asset', ['project_id'])

    # ===========================================================================
    # TABLE: risk_feared_event
    # Atelier 1 - Événements redoutés
    # ===========================================================================
    op.create_table(
        'risk_feared_event',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # Dimension de sécurité (CIA)
        sa.Column('dimension', sa.String(50), nullable=True),  # CONFIDENTIALITY, INTEGRITY, AVAILABILITY
        sa.Column('severity', sa.Integer(), nullable=False, server_default='2'),  # 1-4 (Gravité)
        sa.Column('justification', sa.Text(), nullable=True),
        # Liens avec valeur métier et bien support
        sa.Column('linked_business_value_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_business_value.id', ondelete='SET NULL'), nullable=True),
        sa.Column('linked_asset_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_asset.id', ondelete='SET NULL'), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('source', sa.String(20), nullable=True, server_default='MANUAL'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    op.create_index('ix_risk_feared_event_project', 'risk_feared_event', ['project_id'])

    # ===========================================================================
    # TABLE: risk_source
    # Atelier 2 - Sources de risques
    # ===========================================================================
    op.create_table(
        'risk_source',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('relevance', sa.Integer(), nullable=False, server_default='2'),  # 1-4 (Pertinence)
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('is_selected', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('source', sa.String(20), nullable=True, server_default='MANUAL'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    op.create_index('ix_risk_source_project', 'risk_source', ['project_id'])

    # ===========================================================================
    # TABLE: risk_source_objective
    # Atelier 2 - Objectifs des sources de risques
    # ===========================================================================
    op.create_table(
        'risk_source_objective',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('source_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_source.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_selected', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.create_index('ix_risk_source_objective_source', 'risk_source_objective', ['source_id'])

    # ===========================================================================
    # TABLE: risk_strategic_scenario
    # Atelier 3 - Scénarios stratégiques
    # ===========================================================================
    op.create_table(
        'risk_strategic_scenario',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),  # SS01, SS02...
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # Chemin d'attaque (parties prenantes traversées)
        sa.Column('attack_path', postgresql.JSONB(), nullable=True),
        # Lien avec événement redouté
        sa.Column('feared_event_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_feared_event.id', ondelete='SET NULL'), nullable=True),
        # Lien avec source de risque
        sa.Column('risk_source_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_source.id', ondelete='SET NULL'), nullable=True),
        # Évaluation
        sa.Column('severity', sa.Integer(), nullable=True),  # 1-4 (héritée de l'événement redouté)
        sa.Column('likelihood_raw', sa.Integer(), nullable=True),  # 1-4 (Vraisemblance brute)
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('source', sa.String(20), nullable=True, server_default='MANUAL'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    op.create_index('ix_risk_strategic_scenario_project', 'risk_strategic_scenario', ['project_id'])
    op.create_unique_constraint('uq_risk_strategic_scenario_code', 'risk_strategic_scenario', ['project_id', 'code'])

    # ===========================================================================
    # TABLE: risk_operational_scenario
    # Atelier 4 - Scénarios opérationnels
    # ===========================================================================
    op.create_table(
        'risk_operational_scenario',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('strategic_scenario_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_strategic_scenario.id', ondelete='CASCADE'), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),  # SO01, SO02...
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        # Évaluation
        sa.Column('likelihood', sa.Integer(), nullable=True),  # 1-4 (Vraisemblance)
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('source', sa.String(20), nullable=True, server_default='MANUAL'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    op.create_index('ix_risk_operational_scenario_strategic', 'risk_operational_scenario', ['strategic_scenario_id'])

    # ===========================================================================
    # TABLE: risk_operational_step
    # Atelier 4 - Étapes techniques d'un scénario opérationnel
    # ===========================================================================
    op.create_table(
        'risk_operational_step',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('operational_scenario_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_operational_scenario.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('action', sa.String(255), nullable=False),
        sa.Column('technique', sa.String(255), nullable=True),  # MITRE ATT&CK technique
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
    )

    op.create_index('ix_risk_operational_step_scenario', 'risk_operational_step', ['operational_scenario_id'])

    # ===========================================================================
    # TABLE: risk_risk
    # Atelier 5 - Risques calculés
    # ===========================================================================
    op.create_table(
        'risk_risk',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),  # R01, R02...
        sa.Column('label', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # Évaluation brute
        sa.Column('severity', sa.Integer(), nullable=False),  # 1-4 (Gravité)
        sa.Column('likelihood', sa.Integer(), nullable=False),  # 1-4 (Vraisemblance)
        sa.Column('score', sa.Integer(), nullable=False),  # severity × likelihood (1-16)
        sa.Column('criticality_level', sa.String(20), nullable=False),  # LOW, MODERATE, HIGH, CRITICAL
        sa.Column('justification', sa.Text(), nullable=True),
        # Liens avec scénarios
        sa.Column('strategic_scenario_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_strategic_scenario.id', ondelete='SET NULL'), nullable=True),
        sa.Column('operational_scenario_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_operational_scenario.id', ondelete='SET NULL'), nullable=True),
        sa.Column('feared_event_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_feared_event.id', ondelete='SET NULL'), nullable=True),
        # Évaluation résiduelle (après traitement)
        sa.Column('residual_severity', sa.Integer(), nullable=True),  # 1-4
        sa.Column('residual_likelihood', sa.Integer(), nullable=True),  # 1-4
        sa.Column('residual_score', sa.Integer(), nullable=True),  # 1-16
        sa.Column('residual_justification', sa.Text(), nullable=True),
        # Traitement du risque
        sa.Column('treatment_strategy', sa.String(50), nullable=True),  # REDUCE, ACCEPT, TRANSFER, AVOID
        sa.Column('treatment_status', sa.String(50), nullable=True, server_default='PENDING'),
        sa.Column('order_index', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('source', sa.String(20), nullable=True, server_default='AI'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    op.create_index('ix_risk_risk_project', 'risk_risk', ['project_id'])
    op.create_index('ix_risk_risk_criticality', 'risk_risk', ['criticality_level'])
    op.create_unique_constraint('uq_risk_risk_code', 'risk_risk', ['project_id', 'code'])

    # ===========================================================================
    # TABLE: risk_action_link
    # Lien entre risques et actions
    # ===========================================================================
    op.create_table(
        'risk_action_link',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('risk_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_risk.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action_id', postgresql.UUID(as_uuid=True), nullable=False),  # FK vers table action existante
        sa.Column('code_action', sa.String(50), nullable=False),  # ACT_RISK_<RefCamp>_<XXX>
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_index('ix_risk_action_link_risk', 'risk_action_link', ['risk_id'])
    op.create_index('ix_risk_action_link_action', 'risk_action_link', ['action_id'])
    op.create_unique_constraint('uq_risk_action_link', 'risk_action_link', ['risk_id', 'action_id'])

    # ===========================================================================
    # TABLE: risk_matrix_snapshot
    # Snapshot de la matrice des risques lors du gel
    # ===========================================================================
    op.create_table(
        'risk_matrix_snapshot',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('risk_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('snapshot_date', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('snapshot_type', sa.String(20), nullable=False, server_default='FREEZE'),  # FREEZE, MANUAL
        # Matrice complète en JSON
        sa.Column('matrix_raw', postgresql.JSONB(), nullable=False),
        # Statistiques au moment du snapshot
        sa.Column('stats', postgresql.JSONB(), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_index('ix_risk_matrix_snapshot_project', 'risk_matrix_snapshot', ['project_id'])


def downgrade() -> None:
    # Supprimer les tables dans l'ordre inverse (dépendances FK)
    op.drop_table('risk_matrix_snapshot')
    op.drop_table('risk_action_link')
    op.drop_table('risk_risk')
    op.drop_table('risk_operational_step')
    op.drop_table('risk_operational_scenario')
    op.drop_table('risk_strategic_scenario')
    op.drop_table('risk_source_objective')
    op.drop_table('risk_source')
    op.drop_table('risk_feared_event')
    op.drop_table('risk_asset')
    op.drop_table('risk_business_value')
    op.drop_table('risk_workshop')
    op.drop_table('risk_project')
