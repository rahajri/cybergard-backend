"""Add entity_id and entity_name columns only

Revision ID: 63a29fdf2d66
Revises: b10a4d350c01
Create Date: 2025-11-24 01:29:04.043270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '63a29fdf2d66'
down_revision: Union[str, None] = '78abba06bc5b'  # Changed to skip failed migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add entity_id and entity_name columns to action_plan_item table
    op.add_column('action_plan_item', sa.Column('entity_id', sa.UUID(), nullable=True))
    op.add_column('action_plan_item', sa.Column('entity_name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    # Remove entity_id and entity_name columns from action_plan_item table
    op.drop_column('action_plan_item', 'entity_name')
    op.drop_column('action_plan_item', 'entity_id')
