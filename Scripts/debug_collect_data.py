"""Script pour déboguer collect_entity_data sur la campagne V1."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal
from src.services.report_service import ReportService
import json

db = SessionLocal()
try:
    # Campagne V1 et entité C2M SYSTEM
    campaign_id = 'dcdb2976-1b43-4fda-8816-f71058b63ae5'
    entity_id = 'cbdebd92-e22a-4911-8da7-7cf665336b9b'

    print("="*80)
    print("DEBUG collect_entity_data")
    print(f"Campaign: {campaign_id}")
    print(f"Entity: {entity_id}")
    print("="*80)

    service = ReportService(db)
    data = service.collect_entity_data(campaign_id, entity_id)

    # Afficher les données collectées
    print(f"\n📊 STATS:")
    print(json.dumps(data.get('stats', {}), indent=2, default=str))

    print(f"\n🖼️ LOGOS:")
    print(json.dumps(data.get('logos', {}), indent=2, default=str))

    print(f"\n📈 DOMAIN_SCORES ({len(data.get('domain_scores', []))} domaines):")
    for d in data.get('domain_scores', [])[:3]:
        print(f"   - {d.get('name', 'N/A')}: {d.get('score', 0)}%")
    if len(data.get('domain_scores', [])) > 3:
        print(f"   ... et {len(data.get('domain_scores', [])) - 3} autres")

    print(f"\n📊 BENCHMARKING:")
    print(json.dumps(data.get('benchmarking', {}), indent=2, default=str))

    print(f"\n⚠️ NC_LIST ({len(data.get('nc_list', []))} éléments)")

    print(f"\n✅ STRENGTHS ({len(data.get('strengths', []))} éléments)")
    print(f"🔧 IMPROVEMENTS ({len(data.get('improvements', []))} éléments)")

    # Ce que le widget KPI devrait afficher
    print(f"\n" + "="*80)
    print("CE QUE LE KPI WIDGET DEVRAIT RECEVOIR:")
    print("="*80)

    stats = data.get('stats', {})
    scores = data.get('scores', {})
    domain_scores = data.get('domain_scores', [])
    benchmarking = data.get('benchmarking', {})

    global_score = scores.get('global', 0)
    if global_score == 0:
        global_score = stats.get('compliance_rate', 0)
    if global_score == 0:
        global_score = benchmarking.get('entity_score', 0)

    domains_count = len(domain_scores) if domain_scores else stats.get('total_domains', 0)
    questions_count = stats.get('total_questions', 0)
    nc_count = stats.get('nc_major_count', 0) + stats.get('nc_minor_count', 0)

    print(f"   Score Global: {global_score}%")
    print(f"   Domaines: {domains_count}")
    print(f"   Questions: {questions_count}")
    print(f"   NC: {nc_count}")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
