"""add_is_category_column

Revision ID: f48e687278ce
Revises: 
Create Date: 2025-10-22 17:44:47.681126

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f48e687278ce'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('ecosystem_entity', 
        sa.Column('is_category', sa.Boolean(), nullable=False, server_default='false')
    )
    op.create_index('ix_ecosystem_entity_is_category', 'ecosystem_entity', ['is_category'])

def downgrade():
    op.drop_index('ix_ecosystem_entity_is_category', 'ecosystem_entity')
    op.drop_column('ecosystem_entity', 'is_category')