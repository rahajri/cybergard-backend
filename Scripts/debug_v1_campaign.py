"""Script pour déboguer la campagne ISO 27001 V1."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    campaign_id = 'dcdb2976-1b43-4fda-8816-f71058b63ae5'

    print("="*80)
    print("CAMPAGNE ISO 27001 V1")
    print("="*80)

    # 1. Vérifier les audits
    audits = db.execute(text("""
        SELECT a.id, a.entity_id, ee.name as entity_name, COUNT(qa.id) as qa_count
        FROM audit a
        LEFT JOIN ecosystem_entity ee ON a.entity_id = ee.id
        LEFT JOIN question_answer qa ON qa.audit_id = a.id AND qa.is_current = true
        WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
        GROUP BY a.id, a.entity_id, ee.name
    """), {"campaign_id": campaign_id}).fetchall()

    print(f"\n📋 AUDITS ({len(audits)} trouvés):")
    for a in audits:
        print(f"   - Audit {str(a.id)[:8]}... | Entity: {a.entity_name or 'NULL'} ({str(a.entity_id)[:8] if a.entity_id else 'NULL'}...) | QA: {a.qa_count}")

    # 2. Rapports générés
    reports = db.execute(text("""
        SELECT gr.id, gr.title, gr.entity_id, ee.name as entity_name,
               gr.template_id, rt.name as template_name,
               rt.default_logo,
               CASE WHEN rt.custom_logo IS NOT NULL AND rt.custom_logo != '' THEN 'OUI' ELSE 'NON' END as has_custom_logo,
               gr.generated_at
        FROM generated_report gr
        LEFT JOIN report_template rt ON gr.template_id = rt.id
        LEFT JOIN ecosystem_entity ee ON gr.entity_id = ee.id
        WHERE gr.campaign_id = CAST(:campaign_id AS uuid)
        ORDER BY gr.generated_at DESC
        LIMIT 5
    """), {"campaign_id": campaign_id}).fetchall()

    print(f"\n📄 RAPPORTS GÉNÉRÉS ({len(reports)} derniers):")
    for r in reports:
        print(f"   - {r.title[:40]}")
        print(f"     Entity: {r.entity_name or 'NULL'} ({str(r.entity_id)[:8] if r.entity_id else 'NULL'}...)")
        print(f"     Template: {r.template_name} | Logo: {r.default_logo} | Custom: {r.has_custom_logo}")
        print(f"     Généré: {r.generated_at}")
        print()

    # 3. Vérifier si entity_id des rapports correspond aux audits
    if reports and audits:
        report_entity = reports[0].entity_id
        audit_entities = [a.entity_id for a in audits if a.entity_id]

        print(f"\n🔍 CORRESPONDANCE:")
        print(f"   Entity du dernier rapport: {report_entity}")
        print(f"   Entities des audits: {audit_entities}")

        if report_entity in audit_entities:
            print(f"   ✅ MATCH - L'entity du rapport correspond à un audit")
        else:
            print(f"   ❌ PAS DE MATCH - L'entity du rapport ne correspond à aucun audit!")

    # 4. Stats des réponses
    stats = db.execute(text("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN compliance_status IS NOT NULL THEN 1 END) as with_status,
            COUNT(CASE WHEN compliance_status = 'compliant' THEN 1 END) as compliant,
            COUNT(CASE WHEN compliance_status LIKE 'non_compliant%' THEN 1 END) as nc
        FROM question_answer
        WHERE campaign_id = CAST(:campaign_id AS uuid)
          AND is_current = true
    """), {"campaign_id": campaign_id}).fetchone()

    print(f"\n📊 STATS DES RÉPONSES:")
    print(f"   Total: {stats.total}")
    print(f"   Avec compliance_status: {stats.with_status}")
    print(f"   Compliant: {stats.compliant}")
    print(f"   Non-Compliant: {stats.nc}")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
