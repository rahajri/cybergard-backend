"""Script pour afficher les IDs des templates."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print("=" * 70)
print("TEMPLATES DISPONIBLES")
print("=" * 70)
print()

# Templates avec tenant
templates = db.execute(text("""
    SELECT rt.id, rt.name, rt.report_scope, rt.is_system, t.name as tenant_name
    FROM report_template rt
    LEFT JOIN tenant t ON rt.tenant_id = t.id
    ORDER BY t.name NULLS FIRST, rt.report_scope
""")).fetchall()

print(f"{'ID':<40} {'Tenant':<15} {'Scope':<15} {'Nom'}")
print("-" * 100)

for t in templates:
    tenant = t[4] if t[4] else "(Système)"
    system = "[SYS]" if t[3] else ""
    print(f"{t[0]}  {tenant:<15} {t[2]:<15} {t[1]} {system}")

db.close()
