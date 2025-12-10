"""Script pour diagnostiquer les tenants AHAJRI en double."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print("=" * 70)
print("DIAGNOSTIC DES TENANTS AHAJRI")
print("=" * 70)
print()

# 1. Lister tous les tenants AHAJRI
print("=== TENANTS AHAJRI ===")
tenants = db.execute(text("""
    SELECT id, name, is_active
    FROM tenant
    WHERE name LIKE '%AHAJRI%'
    ORDER BY name
""")).fetchall()

tenant_to_keep = None
tenants_to_delete = []

for t in tenants:
    tenant_id = t[0]
    print(f"ID: {tenant_id}")
    print(f"   Name: {t[1]}, Active: {t[2]}")

    # Compter les organisations liées
    orgs = db.execute(text("SELECT COUNT(*) FROM organization WHERE tenant_id = :tid"), {"tid": tenant_id}).scalar()
    print(f"   Organizations: {orgs}")

    # Compter les campagnes liées
    camps = db.execute(text("SELECT COUNT(*) FROM campaign WHERE tenant_id = :tid"), {"tid": tenant_id}).scalar()
    print(f"   Campaigns: {camps}")

    # Compter les users liés
    users = db.execute(text("SELECT COUNT(*) FROM users WHERE tenant_id = :tid"), {"tid": tenant_id}).scalar()
    print(f"   Users: {users}")

    # Compter les templates liés
    templates = db.execute(text("SELECT COUNT(*) FROM report_template WHERE tenant_id = :tid"), {"tid": tenant_id}).scalar()
    print(f"   Templates: {templates}")

    # Déterminer si c'est le bon tenant (celui avec des données)
    if orgs > 0 or camps > 0 or users > 0:
        tenant_to_keep = tenant_id
        print("   >>> CE TENANT A DES DONNEES - A GARDER")
    else:
        tenants_to_delete.append(tenant_id)
        print("   >>> Tenant vide - peut être supprimé")

    print()

print("=" * 70)
print("RESUME")
print("=" * 70)
print(f"Tenant à garder: {tenant_to_keep}")
print(f"Tenants à supprimer: {len(tenants_to_delete)}")
for tid in tenants_to_delete:
    print(f"   - {tid}")

db.close()
