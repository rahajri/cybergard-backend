"""
Script pour ajouter la colonne custom_logo à la table report_template.

Usage (depuis le dossier backend):
    python scripts/add_custom_logo_column.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal


def add_custom_logo_column():
    """Ajoute la colonne custom_logo si elle n'existe pas."""

    print("=" * 60)
    print("AJOUT DE LA COLONNE custom_logo")
    print("=" * 60)

    db = SessionLocal()
    try:
        # Vérifier si la colonne existe déjà
        check_query = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'report_template'
            AND column_name = 'custom_logo'
        """)

        result = db.execute(check_query).fetchone()

        if result:
            print("\n✓ La colonne 'custom_logo' existe déjà.")
            return

        # Ajouter la colonne
        print("\n→ Ajout de la colonne 'custom_logo'...")

        alter_query = text("""
            ALTER TABLE report_template
            ADD COLUMN custom_logo TEXT NULL
        """)

        db.execute(alter_query)
        db.commit()

        print("✓ Colonne 'custom_logo' ajoutée avec succès!")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Erreur: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    add_custom_logo_column()
