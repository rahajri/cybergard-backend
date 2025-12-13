"""add_objective_and_deliverables_to_action_plan_item

Revision ID: 6c8ab8893574
Revises: 63a29fdf2d66
Create Date: 2025-11-24 16:41:20.730967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c8ab8893574'
down_revision: Union[str, None] = '63a29fdf2d66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter colonnes objective et deliverables à action_plan_item
    op.add_column('action_plan_item', sa.Column('objective', sa.Text(), nullable=True))
    op.add_column('action_plan_item', sa.Column('deliverables', sa.Text(), nullable=True))


def downgrade() -> None:
    # Supprimer les colonnes
    op.drop_column('action_plan_item', 'deliverables')
    op.drop_column('action_plan_item', 'objective')
