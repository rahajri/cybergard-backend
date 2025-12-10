"""Script pour déboguer les actions du plan d'action."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    campaign_id = 'dcdb2976-1b43-4fda-8816-f71058b63ae5'
    entity_id = 'cbdebd92-e22a-4911-8da7-7cf665336b9b'

    print("="*80)
    print("DEBUG PLAN D'ACTION")
    print("="*80)

    # 1. Vérifier s'il existe un ActionPlan pour cette campagne
    action_plan = db.execute(text("""
        SELECT id, campaign_id, status, created_at
        FROM action_plan
        WHERE campaign_id = CAST(:campaign_id AS uuid)
    """), {"campaign_id": campaign_id}).fetchall()

    print(f"\n📋 ACTION_PLAN pour cette campagne:")
    if action_plan:
        for ap in action_plan:
            print(f"   - ID: {ap.id}")
            print(f"     Status: {ap.status}")
            print(f"     Created: {ap.created_at}")
    else:
        print("   ❌ AUCUN plan d'action trouvé!")

    # 2. Vérifier les ActionPlanItem
    items = db.execute(text("""
        SELECT api.id, api.title, api.severity, api.priority, api.entity_id, api.included
        FROM action_plan_item api
        JOIN action_plan ap ON api.action_plan_id = ap.id
        WHERE ap.campaign_id = CAST(:campaign_id AS uuid)
        LIMIT 10
    """), {"campaign_id": campaign_id}).fetchall()

    print(f"\n📝 ACTION_PLAN_ITEM ({len(items)} trouvés):")
    for item in items:
        print(f"   - {item.title[:50]}...")
        print(f"     Severity: {item.severity} | Priority: {item.priority}")
        print(f"     Entity: {item.entity_id or 'Global'} | Included: {item.included}")

    # 3. Vérifier si le problème est le status
    published_plan = db.execute(text("""
        SELECT id, status FROM action_plan
        WHERE campaign_id = CAST(:campaign_id AS uuid)
          AND status = 'PUBLISHED'
    """), {"campaign_id": campaign_id}).fetchone()

    print(f"\n🔍 PLAN PUBLIÉ:")
    if published_plan:
        print(f"   ✅ Plan publié trouvé: {published_plan.id}")
    else:
        print("   ❌ AUCUN plan avec status='PUBLISHED'")
        print("   → C'est probablement la cause du problème!")

    # 4. Vérifier les status disponibles
    statuses = db.execute(text("""
        SELECT DISTINCT status FROM action_plan
        WHERE campaign_id = CAST(:campaign_id AS uuid)
    """), {"campaign_id": campaign_id}).fetchall()

    print(f"\n📊 STATUS des plans d'action:")
    for s in statuses:
        print(f"   - {s.status}")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
