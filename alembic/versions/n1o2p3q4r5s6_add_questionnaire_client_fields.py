"""Add parent_questionnaire_id and owner_org_id to questionnaire table

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2024-12-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'n1o2p3q4r5s6'
down_revision: Union[str, None] = 'm1n2o3p4q5r6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add parent_questionnaire_id column (self-referencing FK)
    op.add_column('questionnaire', sa.Column('parent_questionnaire_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Add owner_org_id column (FK to organization)
    op.add_column('questionnaire', sa.Column('owner_org_id', postgresql.UUID(as_uuid=True), nullable=True))

    # Add foreign key constraints
    op.create_foreign_key(
        'fk_questionnaire_parent_questionnaire',
        'questionnaire', 'questionnaire',
        ['parent_questionnaire_id'], ['id'],
        ondelete='SET NULL'
    )

    op.create_foreign_key(
        'fk_questionnaire_owner_org',
        'questionnaire', 'organization',
        ['owner_org_id'], ['id'],
        ondelete='CASCADE'
    )

    # Add index for faster lookups
    op.create_index('ix_questionnaire_owner_org_id', 'questionnaire', ['owner_org_id'])
    op.create_index('ix_questionnaire_parent_questionnaire_id', 'questionnaire', ['parent_questionnaire_id'])


def downgrade() -> None:
    # Remove indexes
    op.drop_index('ix_questionnaire_parent_questionnaire_id', table_name='questionnaire')
    op.drop_index('ix_questionnaire_owner_org_id', table_name='questionnaire')

    # Remove foreign key constraints
    op.drop_constraint('fk_questionnaire_owner_org', 'questionnaire', type_='foreignkey')
    op.drop_constraint('fk_questionnaire_parent_questionnaire', 'questionnaire', type_='foreignkey')

    # Remove columns
    op.drop_column('questionnaire', 'owner_org_id')
    op.drop_column('questionnaire', 'parent_questionnaire_id')
