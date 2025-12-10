"""
Script pour ajouter des IDs stables aux widgets des templates.

Les widgets AI n'ont actuellement pas d'ID, ce qui cause des problèmes
de correspondance entre frontend et backend lors de la génération de rapports.
"""

import sys
import os
import uuid
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
conn_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def add_widget_ids():
    """Ajoute des IDs uniques à tous les widgets des templates."""
    conn = psycopg2.connect(conn_url)
    cur = conn.cursor()

    try:
        # Récupérer tous les templates
        cur.execute("SELECT id, name, structure FROM report_template")
        templates = cur.fetchall()

        print("=" * 60)
        print("AJOUT DES IDS AUX WIDGETS")
        print("=" * 60)

        updated_count = 0

        for template_id, name, structure in templates:
            if not structure:
                continue

            widgets = structure if isinstance(structure, list) else []
            modified = False

            for i, widget in enumerate(widgets):
                # Ajouter un ID si absent
                if not widget.get('id'):
                    widget['id'] = f"widget-{str(uuid.uuid4())[:8]}"
                    modified = True

            if modified:
                # Mettre à jour le template
                cur.execute(
                    "UPDATE report_template SET structure = %s WHERE id = %s",
                    (Json(widgets), template_id)
                )
                updated_count += 1
                print("Updated: %s" % name)

                # Afficher les widgets AI avec leurs nouveaux IDs
                ai_widgets = [w for w in widgets if w.get('widget_type') in ('ai_summary', 'summary')]
                for aw in ai_widgets:
                    print("  - %s: id=%s" % (aw.get('config', {}).get('title', '?'), aw.get('id')))

        conn.commit()
        print("")
        print("=" * 60)
        print("TERMINE: %d templates mis a jour" % updated_count)
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print("ERREUR: %s" % e)
        import traceback
        traceback.print_exc()
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    add_widget_ids()
