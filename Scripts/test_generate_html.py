"""Script pour tester la génération HTML avec le code actuel."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal
from src.services.report_service import ReportService
from src.services.widget_renderer import WidgetRenderer
import json

db = SessionLocal()
try:
    # Campagne V1 et entité C2M SYSTEM
    campaign_id = 'dcdb2976-1b43-4fda-8816-f71058b63ae5'
    entity_id = 'cbdebd92-e22a-4911-8da7-7cf665336b9b'

    print("="*80)
    print("TEST GÉNÉRATION HTML AVEC CODE ACTUEL")
    print("="*80)

    # 1. Récupérer le template
    template = db.execute(text("""
        SELECT
            rt.id,
            rt.name,
            rt.default_logo,
            rt.custom_logo,
            rt.color_scheme,
            rt.fonts,
            rt.structure
        FROM report_template rt
        WHERE rt.name LIKE '%AHAJRI%'
        LIMIT 1
    """)).fetchone()

    print(f"\n📄 Template: {template.name}")

    # 2. Collecter les données
    service = ReportService(db)
    data = service.collect_entity_data(campaign_id, entity_id)

    # 3. Injecter le logo comme le fait report_job_processor
    if template.default_logo == 'CUSTOM' and template.custom_logo:
        if 'logos' not in data:
            data['logos'] = {}
        data['logos']['tenant_logo_url'] = template.custom_logo
        data['logos']['entity_logo_url'] = template.custom_logo
        data['logos']['organization_logo_url'] = template.custom_logo
        data['logos']['custom_logo'] = template.custom_logo
        print(f"✅ Logo injecté (taille: {len(template.custom_logo)} chars)")

    # 4. Créer le renderer
    color_scheme = json.loads(template.color_scheme) if isinstance(template.color_scheme, str) else (template.color_scheme or {
        'primary': '#8B5CF6',
        'secondary': '#3B82F6',
        'text': '#1F2937',
        'background': '#FFFFFF'
    })

    fonts = json.loads(template.fonts) if isinstance(template.fonts, str) else (template.fonts or {
        'title': {'family': 'Helvetica, Arial, sans-serif', 'size': 24, 'weight': 'bold'},
        'heading1': {'family': 'Helvetica, Arial, sans-serif', 'size': 18, 'weight': 'bold'},
        'body': {'family': 'Helvetica, Arial, sans-serif', 'size': 10, 'weight': 'normal'}
    })

    renderer = WidgetRenderer(color_scheme, fonts)

    # 5. Récupérer la structure
    structure = json.loads(template.structure) if isinstance(template.structure, str) else template.structure

    # 6. Générer HTML pour cover et kpi
    print(f"\n🎨 GÉNÉRATION DES WIDGETS:")

    for widget in sorted(structure, key=lambda w: w.get('position', 0)):
        widget_type = widget.get('widget_type', '')
        config = widget.get('config', {})

        if widget_type in ['cover', 'kpi']:
            print(f"\n--- Widget: {widget_type} ---")
            html = renderer.render_widget(widget_type, config, data)

            # Afficher un extrait
            if widget_type == 'cover':
                # Chercher si logo est présent
                if 'data:image' in html:
                    print("✅ LOGO PRÉSENT dans le HTML (data:image trouvé)")
                elif 'Logo Client' in html:
                    print("❌ LOGO ABSENT - placeholder 'Logo Client' affiché")
                else:
                    print("⚠️ Ni logo ni placeholder trouvé")

            elif widget_type == 'kpi':
                # Extraire les valeurs
                import re
                # Pattern pour trouver les valeurs KPI
                values = re.findall(r'font-size: 28px[^>]*>([^<]+)<', html)
                print(f"   Valeurs KPI trouvées: {values}")

                # Vérifier les valeurs attendues
                expected = ['23.6%', '5', '55', '4']
                for exp in expected:
                    if exp in html:
                        print(f"   ✅ '{exp}' trouvé")
                    else:
                        print(f"   ❌ '{exp}' NON trouvé")

    # 7. Sauvegarder le HTML complet pour inspection
    output_path = Path(__file__).parent / "test_output.html"

    full_html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: {fonts['body']['family']};
                margin: 20px;
            }}
        </style>
    </head>
    <body>
    """

    for widget in sorted(structure, key=lambda w: w.get('position', 0)):
        widget_type = widget.get('widget_type', '')
        config = widget.get('config', {})

        if widget_type in ['cover', 'kpi', 'domain_scores']:
            try:
                html = renderer.render_widget(widget_type, config, data)
                full_html += html + "\n<hr>\n"
            except Exception as e:
                full_html += f"<!-- Erreur {widget_type}: {e} -->\n"

    full_html += """
    </body>
    </html>
    """

    output_path.write_text(full_html, encoding='utf-8')
    print(f"\n📁 HTML généré sauvegardé: {output_path}")
    print("   → Ouvre ce fichier dans un navigateur pour voir le résultat")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
