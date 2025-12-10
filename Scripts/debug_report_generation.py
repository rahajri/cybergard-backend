"""Script pour déboguer le processus complet de génération de rapport."""
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
    print("DEBUG PROCESSUS DE GÉNÉRATION COMPLET")
    print("="*80)

    # 1. Récupérer le dernier rapport généré
    report = db.execute(text("""
        SELECT
            gr.id,
            gr.title,
            gr.template_id,
            gr.entity_id,
            rt.name as template_name,
            rt.default_logo,
            rt.custom_logo IS NOT NULL AND rt.custom_logo != '' as has_custom_logo,
            LENGTH(rt.custom_logo) as custom_logo_length
        FROM generated_report gr
        JOIN report_template rt ON gr.template_id = rt.id
        WHERE gr.campaign_id = CAST(:campaign_id AS uuid)
          AND gr.entity_id = CAST(:entity_id AS uuid)
        ORDER BY gr.generated_at DESC
        LIMIT 1
    """), {"campaign_id": campaign_id, "entity_id": entity_id}).fetchone()

    print(f"\n📄 DERNIER RAPPORT:")
    print(f"   Titre: {report.title}")
    print(f"   Template: {report.template_name}")
    print(f"   default_logo: '{report.default_logo}'")
    print(f"   has_custom_logo: {report.has_custom_logo}")
    print(f"   custom_logo_length: {report.custom_logo_length}")

    # 2. Vérifier la condition exacte du processor
    print(f"\n🔍 CONDITION DU PROCESSOR:")
    print(f"   template.default_logo == 'CUSTOM': {report.default_logo == 'CUSTOM'}")
    print(f"   template.custom_logo (bool): {report.has_custom_logo}")
    print(f"   => LOGO SERA INJECTÉ: {report.default_logo == 'CUSTOM' and report.has_custom_logo}")

    # 3. Collecter les données comme le fait le processor
    print(f"\n📊 COLLECTE DES DONNÉES:")
    service = ReportService(db)
    data = service.collect_entity_data(campaign_id, entity_id)

    print(f"   AVANT injection logo:")
    print(f"   - logos: {json.dumps(data.get('logos', {}), indent=4, default=str)}")

    # 4. Simuler l'injection du logo
    if report.default_logo == 'CUSTOM' and report.has_custom_logo:
        # Récupérer le vrai custom_logo
        template_data = db.execute(text("""
            SELECT custom_logo FROM report_template WHERE id = CAST(:template_id AS uuid)
        """), {"template_id": str(report.template_id)}).fetchone()

        if 'logos' not in data:
            data['logos'] = {}
        data['logos']['tenant_logo_url'] = template_data.custom_logo
        data['logos']['entity_logo_url'] = template_data.custom_logo
        data['logos']['organization_logo_url'] = template_data.custom_logo
        data['logos']['custom_logo'] = template_data.custom_logo
        print(f"\n   ✅ Logo injecté!")
    else:
        print(f"\n   ❌ Logo NON injecté - condition non remplie")

    print(f"\n   APRÈS injection logo:")
    logos_info = {}
    for key, val in data.get('logos', {}).items():
        if val and isinstance(val, str) and len(val) > 100:
            logos_info[key] = f"[DATA URI - {len(val)} chars]"
        else:
            logos_info[key] = val
    print(f"   - logos: {json.dumps(logos_info, indent=4, default=str)}")

    # 5. Vérifier le widget cover config
    print(f"\n🖼️ CONFIG DU WIDGET COVER:")
    structure = db.execute(text("""
        SELECT structure FROM report_template WHERE id = CAST(:template_id AS uuid)
    """), {"template_id": str(report.template_id)}).fetchone()

    if structure and structure.structure:
        widgets = json.loads(structure.structure) if isinstance(structure.structure, str) else structure.structure
        for w in widgets:
            if w.get('widget_type') == 'cover':
                config = w.get('config', {})
                print(f"   logo_source: {config.get('logo_source', 'non défini')}")
                logo_source = config.get('logo_source', 'tenant')
                logo_key = f"{logo_source}_logo_url"
                logo_value = data.get('logos', {}).get(logo_key)
                print(f"   Clé recherchée: {logo_key}")
                if logo_value and len(logo_value) > 100:
                    print(f"   Valeur trouvée: [DATA URI - {len(logo_value)} chars]")
                else:
                    print(f"   Valeur trouvée: {logo_value}")
                break
        else:
            print("   ❌ Widget cover non trouvé dans la structure!")

    # 6. Vérifier les stats pour KPI
    print(f"\n📈 DONNÉES POUR KPI WIDGET:")
    stats = data.get('stats', {})
    scores = data.get('scores', {})
    domain_scores = data.get('domain_scores', [])
    benchmarking = data.get('benchmarking', {})

    print(f"   stats.compliance_rate: {stats.get('compliance_rate', 'NON TROUVÉ')}")
    print(f"   stats.total_questions: {stats.get('total_questions', 'NON TROUVÉ')}")
    print(f"   stats.nc_major_count: {stats.get('nc_major_count', 'NON TROUVÉ')}")
    print(f"   stats.nc_minor_count: {stats.get('nc_minor_count', 'NON TROUVÉ')}")
    print(f"   scores.global: {scores.get('global', 'NON TROUVÉ')}")
    print(f"   len(domain_scores): {len(domain_scores)}")
    print(f"   benchmarking.entity_score: {benchmarking.get('entity_score', 'NON TROUVÉ')}")

    # 7. Vérifier le widget KPI config
    print(f"\n📊 CONFIG DU WIDGET KPI:")
    if structure and structure.structure:
        widgets = json.loads(structure.structure) if isinstance(structure.structure, str) else structure.structure
        for w in widgets:
            if w.get('widget_type') == 'kpi':
                config = w.get('config', {})
                print(f"   show_global_score: {config.get('show_global_score', True)}")
                print(f"   show_domains_count: {config.get('show_domains_count', True)}")
                print(f"   show_questions_count: {config.get('show_questions_count', True)}")
                print(f"   show_nc_count: {config.get('show_nc_count', True)}")
                break
        else:
            print("   ❌ Widget KPI non trouvé dans la structure!")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
