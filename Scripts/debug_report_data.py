"""Script pour déboguer les données collectées pour un rapport."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal
from src.services.report_service import ReportService
import json

db = SessionLocal()
try:
    # Trouver le dernier rapport généré
    report = db.execute(text("""
        SELECT
            gr.id,
            gr.title,
            gr.template_id,
            gr.campaign_id,
            gr.entity_id,
            gr.report_scope,
            c.title as campaign_title
        FROM generated_report gr
        LEFT JOIN campaign c ON gr.campaign_id = c.id
        ORDER BY gr.generated_at DESC
        LIMIT 1
    """)).fetchone()

    if not report:
        print("Aucun rapport trouvé")
    else:
        print(f"\n{'='*80}")
        print(f"RAPPORT: {report.title}")
        print(f"Campaign: {report.campaign_title}")
        print(f"Scope: {report.report_scope}")
        print(f"Entity ID: {report.entity_id}")
        print(f"{'='*80}")

        # Collecter les données comme le fait le processeur
        service = ReportService(db)

        if report.report_scope == 'consolidated':
            print("\n📊 Mode CONSOLIDÉ - collect_consolidated_data()")
            data = service.collect_consolidated_data(report.campaign_id)
        else:
            print(f"\n📊 Mode ENTITY - collect_entity_data({report.entity_id})")
            data = service.collect_entity_data(report.campaign_id, report.entity_id)

        # Afficher les clés de premier niveau
        print(f"\n🔑 Clés disponibles dans data:")
        for key in data.keys():
            value = data[key]
            if isinstance(value, dict):
                print(f"  - {key}: dict avec {len(value)} clés: {list(value.keys())}")
            elif isinstance(value, list):
                print(f"  - {key}: list avec {len(value)} éléments")
            else:
                print(f"  - {key}: {type(value).__name__} = {value}")

        # Détails importants pour le KPI widget
        print(f"\n📈 DONNÉES POUR KPI WIDGET:")
        print(f"  data['scores'] = {data.get('scores', 'NON DÉFINI')}")
        print(f"  data['stats'] = {json.dumps(data.get('stats', {}), indent=4, default=str)}")

        # Vérifier les domaines
        domain_scores = data.get('domain_scores', [])
        print(f"\n📊 DOMAINES ({len(domain_scores)} trouvés):")
        for d in domain_scores[:5]:
            print(f"  - {d.get('name', '?')}: {d.get('score', 0)}%")
        if len(domain_scores) > 5:
            print(f"  ... et {len(domain_scores) - 5} autres")

        # Vérifier les logos
        logos = data.get('logos', {})
        print(f"\n🖼️  LOGOS:")
        print(f"  tenant_logo_url: {'OUI' if logos.get('tenant_logo_url') else 'NON'}")
        print(f"  custom_logo: {'OUI' if logos.get('custom_logo') else 'NON'}")
        print(f"  entity_logo_url: {'OUI' if logos.get('entity_logo_url') else 'NON'}")

        # Vérifier les NC
        nc_list = data.get('nc_list', [])
        nc_major = data.get('nc_major', [])
        nc_minor = data.get('nc_minor', [])
        print(f"\n⚠️  NON-CONFORMITÉS:")
        print(f"  nc_list: {len(nc_list)} éléments")
        print(f"  nc_major: {len(nc_major)} éléments")
        print(f"  nc_minor: {len(nc_minor)} éléments")

        # Calculer ce que le KPI widget devrait afficher
        print(f"\n🎯 CE QUE LE KPI WIDGET DEVRAIT AFFICHER:")
        stats = data.get('stats', {})
        scores = data.get('scores', {})

        # Score global
        global_score = scores.get('global', stats.get('compliance_rate', 0))
        print(f"  Score Global: {global_score}%")

        # Domaines
        total_domains = len(domain_scores) if domain_scores else stats.get('total_domains', 0)
        print(f"  Domaines: {total_domains}")

        # Questions
        total_questions = stats.get('total_questions', 0)
        print(f"  Questions: {total_questions}")

        # NC
        nc_count = stats.get('nc_major_count', 0) + stats.get('nc_minor_count', 0)
        print(f"  Non-Conformités: {nc_count}")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
