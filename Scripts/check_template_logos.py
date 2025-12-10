"""Script pour vérifier les logos des templates."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    result = db.execute(text("""
        SELECT
            rt.id,
            rt.name,
            rt.default_logo,
            CASE WHEN rt.custom_logo IS NOT NULL THEN 'OUI (' || LENGTH(rt.custom_logo) || ' chars)' ELSE 'NON' END as has_custom_logo,
            rt.is_system,
            t.name as tenant_name,
            t.logo_url as tenant_logo_url
        FROM report_template rt
        LEFT JOIN tenant t ON rt.tenant_id = t.id
        ORDER BY rt.is_system DESC, rt.name
    """)).fetchall()

    print("=" * 100)
    print("ÉTAT DES LOGOS DANS LES TEMPLATES")
    print("=" * 100)
    print(f"{'NOM':<40} | {'DEFAULT_LOGO':<12} | {'CUSTOM_LOGO':<20} | {'TENANT LOGO':<20}")
    print("-" * 100)

    for row in result:
        tenant_logo = "OUI" if row.tenant_logo_url else "NON"
        print(f"{row.name[:38]:<40} | {row.default_logo or 'NULL':<12} | {row.has_custom_logo:<20} | {tenant_logo:<20}")

    print("-" * 100)
    print(f"Total: {len(result)} templates")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
