"""Script pour déboguer le flux du logo dans le rapport."""
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
        print(f"Template ID: {report.template_id}")
        print(f"{'='*80}")

        # Récupérer les infos du template
        template = db.execute(text("""
            SELECT
                id, name, default_logo,
                LENGTH(custom_logo) as custom_logo_length,
                CASE WHEN custom_logo IS NOT NULL AND custom_logo != '' THEN 'OUI' ELSE 'NON' END as has_custom_logo,
                LEFT(custom_logo, 100) as custom_logo_preview,
                structure
            FROM report_template
            WHERE id = :template_id
        """), {"template_id": str(report.template_id)}).fetchone()

        if template:
            print(f"\n📋 TEMPLATE: {template.name}")
            print(f"   default_logo: {template.default_logo}")
            print(f"   has_custom_logo: {template.has_custom_logo}")
            print(f"   custom_logo_length: {template.custom_logo_length} chars")
            print(f"   custom_logo_preview: {template.custom_logo_preview[:80]}..." if template.custom_logo_preview else "   custom_logo_preview: NULL")

            # Analyser la structure pour trouver la config du widget cover
            if template.structure:
                structure = template.structure if isinstance(template.structure, list) else json.loads(template.structure)
                print(f"\n📊 STRUCTURE DU TEMPLATE ({len(structure)} widgets):")
                for widget in structure:
                    widget_type = widget.get('widget_type', 'unknown')
                    print(f"   - {widget_type}")
                    if widget_type == 'cover':
                        config = widget.get('config', {})
                        print(f"     └── logo_source: {config.get('logo_source', 'NON DÉFINI (défaut: tenant)')}")
                        print(f"     └── title: {config.get('title', 'N/A')}")

        # Collecter les données comme le fait le processeur
        service = ReportService(db)
        if report.report_scope == 'consolidated':
            data = service.collect_consolidated_data(report.campaign_id)
        else:
            data = service.collect_entity_data(report.campaign_id, report.entity_id)

        print(f"\n🖼️  LOGOS DANS DATA (avant injection template):")
        logos = data.get('logos', {})
        print(f"   tenant_logo_url: {'OUI' if logos.get('tenant_logo_url') else 'NON'}")
        if logos.get('tenant_logo_url'):
            preview = str(logos.get('tenant_logo_url'))[:80]
            print(f"   └── preview: {preview}...")
        print(f"   custom_logo: {'OUI' if logos.get('custom_logo') else 'NON'}")
        print(f"   entity_logo_url: {'OUI' if logos.get('entity_logo_url') else 'NON'}")

        # Simuler l'injection du logo comme dans report_job_processor.py
        print(f"\n🔧 SIMULATION INJECTION LOGO:")
        print(f"   Condition: template.default_logo == 'CUSTOM' → {template.default_logo == 'CUSTOM'}")
        print(f"   Condition: template.custom_logo non vide → {bool(template.custom_logo_length and template.custom_logo_length > 0)}")

        if template.default_logo == 'CUSTOM' and template.custom_logo_length and template.custom_logo_length > 0:
            print(f"   ✅ INJECTION DEVRAIT SE FAIRE!")
            # Récupérer le vrai custom_logo
            custom_logo = db.execute(text("""
                SELECT custom_logo FROM report_template WHERE id = :id
            """), {"id": str(template.id)}).scalar()
            if custom_logo:
                print(f"   Logo à injecter: {custom_logo[:80]}...")
        else:
            print(f"   ❌ INJECTION NE SE FERA PAS - conditions non remplies")
            if template.default_logo != 'CUSTOM':
                print(f"      → default_logo est '{template.default_logo}' au lieu de 'CUSTOM'")
            if not template.custom_logo_length or template.custom_logo_length == 0:
                print(f"      → custom_logo est vide ou NULL")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
