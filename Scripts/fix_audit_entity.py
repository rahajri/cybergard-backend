"""Script pour corriger l'audit sans entity_id."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    campaign_id = '7cbe1915-37cf-478c-ab40-bd63a319f0b2'
    report_entity_id = 'cbdebd92-e22a-4911-8da7-7cf665336b9b'

    # 1. Vérifier l'audit sans entity_id
    audit = db.execute(text("""
        SELECT a.id, a.entity_id, a.questionnaire_id
        FROM audit a
        JOIN question_answer qa ON qa.audit_id = a.id
        WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
        LIMIT 1
    """), {"campaign_id": campaign_id}).fetchone()

    print(f"🔍 AUDIT trouvé:")
    print(f"   ID: {audit.id}")
    print(f"   entity_id actuel: {audit.entity_id}")
    print(f"   questionnaire_id: {audit.questionnaire_id}")

    # 2. Vérifier l'entité du rapport
    entity = db.execute(text("""
        SELECT id, name FROM ecosystem_entity WHERE id = CAST(:entity_id AS uuid)
    """), {"entity_id": report_entity_id}).fetchone()

    print(f"\n📋 ENTITÉ du rapport:")
    print(f"   ID: {entity.id}")
    print(f"   Nom: {entity.name}")

    # 3. Vérifier le scope de la campagne
    scope = db.execute(text("""
        SELECT cs.entity_ids
        FROM campaign c
        JOIN campaign_scope cs ON c.scope_id = cs.id
        WHERE c.id = CAST(:campaign_id AS uuid)
    """), {"campaign_id": campaign_id}).fetchone()

    print(f"\n🎯 SCOPE de la campagne:")
    print(f"   entity_ids: {scope.entity_ids if scope else 'NULL'}")

    # 4. Proposer la correction
    if audit.entity_id is None:
        print(f"\n⚠️  L'AUDIT n'a pas d'entity_id!")
        print(f"   → On peut le corriger en assignant l'entity_id = {report_entity_id}")

        confirm = input("\n🔧 Voulez-vous corriger l'audit ? (oui/non): ")
        if confirm.lower() == 'oui':
            db.execute(text("""
                UPDATE audit SET entity_id = CAST(:entity_id AS uuid)
                WHERE id = CAST(:audit_id AS uuid)
            """), {"entity_id": report_entity_id, "audit_id": str(audit.id)})
            db.commit()
            print(f"✅ Audit corrigé ! entity_id = {report_entity_id}")
        else:
            print("❌ Correction annulée")
    else:
        print(f"\n✅ L'audit a déjà un entity_id: {audit.entity_id}")
        if str(audit.entity_id) != report_entity_id:
            print(f"   ⚠️ MAIS il ne correspond pas à l'entité du rapport!")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
