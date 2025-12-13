"""Add EBIOS RM permissions

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2024-12-04

Ajoute les permissions RBAC pour le module EBIOS RM
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from uuid import uuid4

# revision identifiers, used by Alembic.
revision = 'i1j2k3l4m5n6'
down_revision = 'h1i2j3k4l5m6'
branch_labels = None
depends_on = None


EBIOS_PERMISSIONS = [
    {
        "code": "EBIOS_READ",
        "name": "Consulter les analyses EBIOS",
        "description": "Permet de consulter les projets EBIOS RM et leurs ateliers",
        "module": "ebios",
        "action": "read"
    },
    {
        "code": "EBIOS_CREATE",
        "name": "Créer des analyses EBIOS",
        "description": "Permet de créer de nouveaux projets EBIOS RM",
        "module": "ebios",
        "action": "create"
    },
    {
        "code": "EBIOS_UPDATE",
        "name": "Modifier des analyses EBIOS",
        "description": "Permet de modifier les projets EBIOS RM et leurs ateliers",
        "module": "ebios",
        "action": "update"
    },
    {
        "code": "EBIOS_DELETE",
        "name": "Supprimer des analyses EBIOS",
        "description": "Permet de supprimer des projets EBIOS RM",
        "module": "ebios",
        "action": "delete"
    },
    {
        "code": "EBIOS_FREEZE",
        "name": "Figer une analyse EBIOS",
        "description": "Permet de figer une analyse EBIOS RM (action irréversible)",
        "module": "ebios",
        "action": "freeze"
    },
    {
        "code": "EBIOS_GENERATE",
        "name": "Générer via IA (EBIOS)",
        "description": "Permet d'utiliser l'IA pour générer du contenu EBIOS RM",
        "module": "ebios",
        "action": "generate"
    },
    {
        "code": "EBIOS_EXPORT",
        "name": "Exporter les analyses EBIOS",
        "description": "Permet d'exporter les rapports EBIOS RM",
        "module": "ebios",
        "action": "export"
    },
]


def upgrade() -> None:
    # Obtenir la connexion
    connection = op.get_bind()

    for perm in EBIOS_PERMISSIONS:
        # Vérifier si la permission existe déjà
        result = connection.execute(
            text("SELECT id FROM permission WHERE code = :code"),
            {"code": perm["code"]}
        )
        existing = result.fetchone()

        if not existing:
            # Insérer la nouvelle permission
            perm_id = str(uuid4())
            connection.execute(
                text("""
                    INSERT INTO permission (id, code, name, description, module, action, permission_type)
                    VALUES (:id, :code, :name, :description, :module, :action, 'general')
                """),
                {
                    "id": perm_id,
                    "code": perm["code"],
                    "name": perm["name"],
                    "description": perm["description"],
                    "module": perm["module"],
                    "action": perm["action"]
                }
            )
            print(f"  ✓ Permission créée: {perm['code']}")
        else:
            print(f"  - Permission existante: {perm['code']}")


def downgrade() -> None:
    # Obtenir la connexion
    connection = op.get_bind()

    # Supprimer les permissions EBIOS
    for perm in EBIOS_PERMISSIONS:
        connection.execute(
            text("DELETE FROM permission WHERE code = :code"),
            {"code": perm["code"]}
        )
        print(f"  ✗ Permission supprimée: {perm['code']}")
