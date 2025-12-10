"""
Script pour lister tous les templates en base de données.

Usage (depuis le dossier backend):
    python scripts/list_templates.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal


def list_templates():
    """Liste tous les templates en base."""

    print("=" * 90)
    print("TEMPLATES EN BASE DE DONNÉES")
    print("=" * 90)

    db = SessionLocal()
    try:
        query = text("""
            SELECT
                rt.id,
                rt.name,
                rt.code,
                rt.tenant_id,
                rt.is_system,
                rt.report_scope,
                t.name as tenant_name
            FROM report_template rt
            LEFT JOIN tenant t ON rt.tenant_id = t.id
            ORDER BY rt.is_system DESC, rt.name
        """)

        result = db.execute(query).fetchall()

        if not result:
            print("Aucun template trouvé.")
            return

        print(f"\n{'NOM':<45} | {'CODE':<25} | {'SCOPE':<12} | {'TYPE':<6} | {'TENANT'}")
        print("-" * 90)

        for r in result:
            name = r[1][:44] if len(r[1]) > 44 else r[1]
            code = (r[2] or "")[:24] if r[2] and len(r[2]) > 24 else (r[2] or "")
            scope = r[5] or ""
            type_str = "SYS" if r[4] else "CUSTOM"
            tenant = r[6] if r[6] else ("SYSTÈME" if r[3] is None else str(r[3])[:8])

            print(f"{name:<45} | {code:<25} | {scope:<12} | {type_str:<6} | {tenant}")

        print("-" * 90)
        print(f"\nTotal: {len(result)} template(s)")

        # Stats
        sys_count = sum(1 for r in result if r[4])
        custom_count = len(result) - sys_count
        print(f"  - Système: {sys_count}")
        print(f"  - Custom: {custom_count}")

    except Exception as e:
        print(f"[ERROR] Erreur: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    list_templates()
