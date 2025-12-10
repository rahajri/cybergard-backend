"""add_category_relationships_table

Revision ID: 2f97233ff7cb
Revises: 16b669b9b3a4
Create Date: 2025-11-14 21:02:37.104495

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f97233ff7cb'
down_revision: Union[str, None] = '16b669b9b3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Créer la table category_relationships pour les relations many-to-many
    op.create_table(
        'category_relationships',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('parent_category_id', sa.UUID(), nullable=False),
        sa.Column('child_category_id', sa.UUID(), nullable=False),
        sa.Column('relationship_type', sa.String(50), server_default='hierarchical', nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['parent_category_id'], ['categories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['child_category_id'], ['categories.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('parent_category_id', 'child_category_id', name='unique_category_relationship')
    )

    # Créer des index pour optimiser les requêtes
    op.create_index('idx_category_rel_parent', 'category_relationships', ['parent_category_id'])
    op.create_index('idx_category_rel_child', 'category_relationships', ['child_category_id'])
    op.create_index('idx_category_rel_primary', 'category_relationships', ['is_primary'])

    # Migrer les relations existantes depuis parent_category_id
    # Toutes les catégories qui ont un parent_category_id doivent avoir une relation primaire
    op.execute("""
        INSERT INTO category_relationships (parent_category_id, child_category_id, is_primary, created_at)
        SELECT parent_category_id, id, true, created_at
        FROM categories
        WHERE parent_category_id IS NOT NULL
    """)


def downgrade() -> None:
    # Supprimer les index
    op.drop_index('idx_category_rel_primary', 'category_relationships')
    op.drop_index('idx_category_rel_child', 'category_relationships')
    op.drop_index('idx_category_rel_parent', 'category_relationships')

    # Supprimer la table
    op.drop_table('category_relationships')
