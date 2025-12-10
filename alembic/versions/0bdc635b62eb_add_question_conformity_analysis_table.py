"""add_question_conformity_analysis_table

Revision ID: 0bdc635b62eb
Revises: 2f97233ff7cb
Create Date: 2025-11-23 02:16:40.197901

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0bdc635b62eb'
down_revision: Union[str, None] = '2f97233ff7cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Créer la table question_conformity_analysis
    op.create_table(
        'question_conformity_analysis',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('question_answer_id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('action_plan_id', sa.UUID(), nullable=True),

        # Résultats Phase 2
        sa.Column('conformite', sa.String(50), nullable=False, comment='conforme | partiel | non_conforme | non_applicable'),
        sa.Column('risque', sa.String(50), nullable=False, comment='faible | moyen | élevé | critique'),
        sa.Column('action_requise', sa.Boolean(), nullable=False, default=False),
        sa.Column('justification', sa.Text(), nullable=False),

        # Résultats Phase 2.5 (re-validation)
        sa.Column('revalidated_conformite', sa.String(50), nullable=True),
        sa.Column('revalidated_risque', sa.String(50), nullable=True),
        sa.Column('revalidated_action_requise', sa.Boolean(), nullable=True),
        sa.Column('revalidated_justification', sa.Text(), nullable=True),

        # Résultats consolidés
        sa.Column('final_conformite', sa.String(50), nullable=False),
        sa.Column('final_risque', sa.String(50), nullable=False),
        sa.Column('final_action_requise', sa.Boolean(), nullable=False),

        # Métadonnées
        sa.Column('analysis_phase', sa.Integer(), nullable=False, default=2, comment='2 = Phase 2, 25 = Phase 2.5'),
        sa.Column('analysis_method', sa.String(50), nullable=False, default='ai', comment='ai | fallback_rules | manual'),
        sa.Column('ai_model', sa.String(100), nullable=True),

        # Révision manuelle
        sa.Column('manually_reviewed', sa.Boolean(), default=False),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_comment', sa.Text(), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),

        # Contraintes
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['question_answer_id'], ['question_answer.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaign.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['action_plan_id'], ['action_plan.id'], ondelete='CASCADE'),
    )

    # Index pour améliorer les performances
    op.create_index('ix_qca_question_answer_id', 'question_conformity_analysis', ['question_answer_id'])
    op.create_index('ix_qca_campaign_id', 'question_conformity_analysis', ['campaign_id'])
    op.create_index('ix_qca_action_plan_id', 'question_conformity_analysis', ['action_plan_id'])
    op.create_index('ix_qca_action_requise', 'question_conformity_analysis', ['final_action_requise'])


def downgrade() -> None:
    # Supprimer les index
    op.drop_index('ix_qca_action_requise', table_name='question_conformity_analysis')
    op.drop_index('ix_qca_action_plan_id', table_name='question_conformity_analysis')
    op.drop_index('ix_qca_campaign_id', table_name='question_conformity_analysis')
    op.drop_index('ix_qca_question_answer_id', table_name='question_conformity_analysis')

    # Supprimer la table
    op.drop_table('question_conformity_analysis')
