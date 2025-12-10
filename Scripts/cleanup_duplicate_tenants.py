"""Script pour supprimer les tenants AHAJRI en double et leurs templates."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print("=" * 70)
print("NETTOYAGE DES TENANTS EN DOUBLE")
print("=" * 70)
print()

# Tenants à supprimer (identifiés par le diagnostic)
TENANTS_TO_DELETE = [
    "41660602-352e-4baa-a1c1-9b7683bb1b69",
    "706c6447-ce19-4972-bffa-e5c20eef188e",
    "36b25f80-138c-4d2d-9e8a-4883b9eac6d6",
]

# Tenant à garder
TENANT_TO_KEEP = "e628c959-d81b-417d-bbb9-0e861053ec30"

try:
    # 1. Supprimer les templates des tenants à supprimer
    print("[1] Suppression des templates des tenants vides...")
    for tenant_id in TENANTS_TO_DELETE:
        result = db.execute(text("""
            DELETE FROM report_template
            WHERE tenant_id = CAST(:tid AS uuid)
        """), {"tid": tenant_id})
        print(f"    - Tenant {tenant_id[:8]}... : {result.rowcount} templates supprimés")

    # 2. Supprimer les tenants vides
    print()
    print("[2] Suppression des tenants vides...")
    for tenant_id in TENANTS_TO_DELETE:
        result = db.execute(text("""
            DELETE FROM tenant
            WHERE id = CAST(:tid AS uuid)
        """), {"tid": tenant_id})
        print(f"    - Tenant {tenant_id[:8]}... : supprimé")

    # 3. Vérifier que le bon tenant a ses templates
    print()
    print("[3] Vérification du tenant AHAJRI restant...")
    templates = db.execute(text("""
        SELECT id, name, report_scope
        FROM report_template
        WHERE tenant_id = CAST(:tid AS uuid)
        ORDER BY report_scope
    """), {"tid": TENANT_TO_KEEP}).fetchall()

    print(f"    Tenant: {TENANT_TO_KEEP}")
    print(f"    Templates: {len(templates)}")
    for t in templates:
        print(f"      - {t[1]} ({t[2]})")

    # Commit
    db.commit()

    print()
    print("=" * 70)
    print("[SUCCESS] Nettoyage terminé !")
    print("=" * 70)

except Exception as e:
    db.rollback()
    print(f"[ERROR] {str(e)}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
