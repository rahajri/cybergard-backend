"""add_compliance_status_to_question_answer

Revision ID: 78abba06bc5b
Revises: 0bdc635b62eb
Create Date: 2025-11-23 23:49:22.670989

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78abba06bc5b'
down_revision: Union[str, None] = '0bdc635b62eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter le champ compliance_status à la table question_answer
    op.add_column(
        'question_answer',
        sa.Column('compliance_status', sa.String(50), nullable=True)
    )

    # Ajouter une contrainte de validation pour les valeurs possibles
    op.create_check_constraint(
        'chk_compliance_status',
        'question_answer',
        "compliance_status IN ('compliant', 'non_compliant_minor', 'non_compliant_major', 'not_applicable', 'pending')"
    )

    # Créer un index pour améliorer les performances des requêtes filtrant par compliance_status
    op.create_index(
        'ix_question_answer_compliance_status',
        'question_answer',
        ['compliance_status']
    )


def downgrade() -> None:
    # Supprimer l'index
    op.drop_index('ix_question_answer_compliance_status', table_name='question_answer')

    # Supprimer la contrainte
    op.drop_constraint('chk_compliance_status', 'question_answer', type_='check')

    # Supprimer la colonne
    op.drop_column('question_answer', 'compliance_status')
