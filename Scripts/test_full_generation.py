"""Script pour tester la génération complète du rapport comme le fait le vrai processeur."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal
from src.services.report_service import ReportService
from src.services.widget_renderer import WidgetRenderer
import json
import logging

# Activer le logging pour voir les messages
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SessionLocal()
try:
    campaign_id = 'dcdb2976-1b43-4fda-8816-f71058b63ae5'
    entity_id = 'cbdebd92-e22a-4911-8da7-7cf665336b9b'

    print("="*80)
    print("TEST GÉNÉRATION COMPLÈTE (COMME LE VRAI PROCESSEUR)")
    print("="*80)

    # 1. Récupérer le template (comme report_job_processor)
    template = db.execute(text("""
        SELECT
            id, name, default_logo, custom_logo,
            color_scheme, fonts, structure
        FROM report_template
        WHERE name LIKE '%AHAJRI%'
        LIMIT 1
    """)).fetchone()

    print(f"\n📄 Template: {template.name}")
    print(f"   default_logo: '{template.default_logo}'")
    print(f"   custom_logo: {'présent' if template.custom_logo else 'absent'}")

    # 2. Collecter les données (comme report_job_processor)
    print("\n📊 Collecte des données...")
    service = ReportService(db)
    data = service.collect_entity_data(campaign_id, entity_id)

    print(f"   logos AVANT injection: {list(data.get('logos', {}).keys())}")

    # 3. Appliquer le logo personnalisé (EXACTEMENT comme report_job_processor ligne 110-122)
    logger.info(f"🔍 Template logo check: default_logo='{template.default_logo}', custom_logo={'présent' if template.custom_logo else 'absent'}")
    if template.default_logo == 'CUSTOM' and template.custom_logo:
        if 'logos' not in data:
            data['logos'] = {}
        data['logos']['tenant_logo_url'] = template.custom_logo
        data['logos']['entity_logo_url'] = template.custom_logo
        data['logos']['organization_logo_url'] = template.custom_logo
        data['logos']['custom_logo'] = template.custom_logo
        logger.info(f"✅ Logo personnalisé appliqué depuis le template (toutes sources, {len(template.custom_logo)} chars)")

    print(f"   logos APRÈS injection: {list(data.get('logos', {}).keys())}")

    # Vérifier que les logos sont bien là
    for key in ['tenant_logo_url', 'entity_logo_url', 'organization_logo_url', 'custom_logo']:
        val = data.get('logos', {}).get(key)
        if val and len(val) > 100:
            print(f"   ✅ {key}: [DATA URI - {len(val)} chars]")
        else:
            print(f"   ❌ {key}: {val or 'ABSENT'}")

    # 4. Créer le renderer (comme _generate_simple_html)
    color_scheme = template.color_scheme or {
        'primary': '#8B5CF6',
        'secondary': '#3B82F6',
        'text': '#1F2937',
        'background': '#FFFFFF'
    }
    if isinstance(color_scheme, str):
        color_scheme = json.loads(color_scheme)

    fonts = template.fonts or {
        'title': {'family': 'Helvetica, Arial, sans-serif', 'size': 24, 'weight': 'bold'},
        'heading1': {'family': 'Helvetica, Arial, sans-serif', 'size': 18, 'weight': 'bold'},
        'body': {'family': 'Helvetica, Arial, sans-serif', 'size': 10, 'weight': 'normal'}
    }
    if isinstance(fonts, str):
        fonts = json.loads(fonts)

    renderer = WidgetRenderer(color_scheme, fonts)

    # 5. Récupérer la structure
    structure = template.structure or []
    if isinstance(structure, str):
        structure = json.loads(structure)

    # 6. Générer HTML pour chaque widget
    print("\n🎨 GÉNÉRATION DES WIDGETS:")
    widgets_html = []
    for widget in sorted(structure, key=lambda w: w.get('position', 0)):
        widget_type = widget.get('widget_type', '')
        config = widget.get('config', {})

        try:
            html = renderer.render_widget(widget_type, config, data)
            widgets_html.append(html)

            if widget_type == 'cover':
                if 'data:image' in html:
                    print(f"   ✅ cover: LOGO DATA URI PRÉSENT!")
                elif 'Logo Client' in html:
                    print(f"   ❌ cover: Placeholder 'Logo Client' - PAS DE LOGO")
                else:
                    print(f"   ⚠️ cover: Ni logo ni placeholder")

            elif widget_type == 'benchmark':
                print(f"   ✅ benchmark: widget généré")

        except Exception as e:
            print(f"   ❌ {widget_type}: ERREUR - {e}")

    # 7. Sauvegarder le HTML complet
    print("\n📝 ASSEMBLAGE HTML FINAL:")
    primary_color = color_scheme.get('primary', '#8B5CF6')

    full_html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{ size: A4; margin: 15mm; }}
            body {{
                font-family: {fonts['body']['family']};
                font-size: {fonts['body']['size']}px;
                line-height: 1.6;
                color: {color_scheme['text']};
                margin: 0;
                padding: 0;
                background: {color_scheme['background']};
            }}
            .page-break {{ page-break-after: always; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
            th {{ background: {primary_color}; color: white; font-weight: 600; }}
        </style>
    </head>
    <body>
        {''.join(widgets_html)}
    </body>
    </html>
    """

    # Vérifier présence logo dans HTML final
    if 'data:image' in full_html:
        print("   ✅ LOGO DATA URI PRÉSENT dans le HTML final!")
    else:
        print("   ❌ LOGO ABSENT du HTML final!")

    output_path = Path(__file__).parent / "test_full_report.html"
    output_path.write_text(full_html, encoding='utf-8')
    print(f"\n📁 HTML sauvegardé: {output_path}")
    print(f"   Taille: {len(full_html)} bytes")

    # 8. Test WeasyPrint
    print("\n🖨️ TEST WEASYPRINT:")
    try:
        from weasyprint import HTML, CSS

        additional_css = CSS(string="""
            @page { size: A4; margin: 15mm; }
            * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
        """)

        html_doc = HTML(string=full_html)
        pdf_bytes = html_doc.write_pdf(stylesheets=[additional_css])

        pdf_path = Path(__file__).parent / "test_full_report.pdf"
        pdf_path.write_bytes(pdf_bytes)
        print(f"   ✅ PDF généré: {pdf_path} ({len(pdf_bytes)} bytes)")
        print("   → Ouvrez ce PDF pour vérifier si le logo apparaît!")

    except ImportError:
        print("   ⚠️ WeasyPrint non installé")
    except Exception as e:
        print(f"   ❌ Erreur WeasyPrint: {e}")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
