"""modify_category_unique_constraint_to_use_parent

Revision ID: 16b669b9b3a4
Revises: 561dbb129df7
Create Date: 2025-11-14 18:19:19.103820

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16b669b9b3a4'
down_revision: Union[str, None] = '561dbb129df7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Modifie la contrainte d'unicité des catégories pour permettre les doublons contextuels.

    Avant: UNIQUE (pole_id, name, client_organization_id)
    Après: UNIQUE (parent_category_id, name, client_organization_id)

    Cela permet d'avoir:
    - FOURNISSEURS → MAROC
    - CLIENTS → MAROC

    Tout en empêchant les vrais doublons (même parent + même nom + même org)
    """
    # 1. Supprimer l'ancienne contrainte basée sur pole_id
    op.drop_constraint(
        'unique_category_per_pole_client',
        'categories',
        type_='unique'
    )

    # 2. Créer la nouvelle contrainte basée sur parent_category_id
    op.create_unique_constraint(
        'unique_category_per_parent_client',
        'categories',
        ['parent_category_id', 'name', 'client_organization_id']
    )


def downgrade() -> None:
    """
    Rollback: Restaurer l'ancienne contrainte basée sur pole_id
    """
    # 1. Supprimer la nouvelle contrainte
    op.drop_constraint(
        'unique_category_per_parent_client',
        'categories',
        type_='unique'
    )

    # 2. Recréer l'ancienne contrainte
    op.create_unique_constraint(
        'unique_category_per_pole_client',
        'categories',
        ['pole_id', 'name', 'client_organization_id']
    )
