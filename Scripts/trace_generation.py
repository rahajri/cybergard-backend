"""Script pour tracer la génération de rapport en temps réel."""
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
    # Dernière génération pour C2M SYSTEM
    campaign_id = 'dcdb2976-1b43-4fda-8816-f71058b63ae5'
    entity_id = 'cbdebd92-e22a-4911-8da7-7cf665336b9b'

    print("="*80)
    print("TRACE COMPLÈTE DE LA GÉNÉRATION")
    print("="*80)

    # 1. Récupérer le template utilisé
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

    print(f"\n📄 TEMPLATE: {template.name}")
    print(f"   default_logo: '{template.default_logo}'")
    print(f"   custom_logo existe: {template.custom_logo is not None and len(template.custom_logo) > 0}")
    if template.custom_logo:
        print(f"   custom_logo length: {len(template.custom_logo)}")
        print(f"   custom_logo starts with: {template.custom_logo[:50]}...")

    # 2. Collecter les données
    print("\n📊 COLLECTE DES DONNÉES:")
    service = ReportService(db)
    data = service.collect_entity_data(campaign_id, entity_id)

    print(f"   logos AVANT injection: {list(data.get('logos', {}).keys())}")

    # 3. Simuler l'injection du logo comme report_job_processor
    if template.default_logo == 'CUSTOM' and template.custom_logo:
        if 'logos' not in data:
            data['logos'] = {}
        data['logos']['tenant_logo_url'] = template.custom_logo
        data['logos']['entity_logo_url'] = template.custom_logo
        data['logos']['organization_logo_url'] = template.custom_logo
        data['logos']['custom_logo'] = template.custom_logo
        print(f"   ✅ Logo injecté dans 4 clés")

    print(f"   logos APRÈS injection: {list(data.get('logos', {}).keys())}")
    for key, val in data.get('logos', {}).items():
        if val and isinstance(val, str):
            if len(val) > 100:
                print(f"   - {key}: [DATA URI - {len(val)} chars]")
            else:
                print(f"   - {key}: {val}")
        else:
            print(f"   - {key}: {val}")

    # 4. Récupérer la structure et le widget cover
    structure = json.loads(template.structure) if isinstance(template.structure, str) else template.structure

    print("\n🎨 WIDGETS DANS LA STRUCTURE:")
    for w in structure:
        print(f"   - {w.get('widget_type')} (pos: {w.get('position', 0)})")

    # 5. Trouver le widget cover et sa config
    print("\n🖼️ CONFIGURATION DU WIDGET COVER:")
    cover_widget = None
    for w in structure:
        if w.get('widget_type') == 'cover':
            cover_widget = w
            break

    if cover_widget:
        config = cover_widget.get('config', {})
        print(f"   title: {config.get('title')}")
        print(f"   subtitle: {config.get('subtitle')}")
        print(f"   logo_source: {config.get('logo_source', 'tenant')}")

        # 6. Simuler ce que fait render_cover
        logo_source = config.get("logo_source", "tenant")
        logos = data.get("logos", {})

        print(f"\n   📌 Logo resolution:")
        print(f"      logo_source = '{logo_source}'")

        logo_url = None
        if logo_source == "tenant":
            logo_url = logos.get("tenant_logo_url")
        elif logo_source == "organization":
            logo_url = logos.get("organization_logo_url")
        elif logo_source == "entity":
            logo_url = logos.get("entity_logo_url")

        if logo_url:
            print(f"      ✅ logo_url trouvé ({len(logo_url)} chars)")
            print(f"      Début: {logo_url[:80]}...")
        else:
            print(f"      ❌ logo_url = None - PROBLÈME ICI!")
            print(f"      Clés disponibles: {list(logos.keys())}")
            print(f"      Valeur tenant_logo_url: {logos.get('tenant_logo_url', 'ABSENT')[:50] if logos.get('tenant_logo_url') else 'ABSENT'}")

    else:
        print("   ❌ Widget cover non trouvé!")

    # 7. Créer renderer et générer HTML cover
    print("\n📝 GÉNÉRATION HTML DU COVER:")
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

    if cover_widget:
        html = renderer.render_cover(cover_widget.get('config', {}), data)

        # Vérifier le résultat
        if 'data:image' in html:
            print("   ✅ LOGO DATA URI PRÉSENT dans le HTML!")
        elif 'Logo Client' in html:
            print("   ❌ PLACEHOLDER 'Logo Client' présent - logo NON affiché")
        else:
            print("   ⚠️ Ni logo ni placeholder trouvé")

        # Sauvegarder pour inspection
        output = Path(__file__).parent / "trace_cover.html"
        output.write_text(html, encoding='utf-8')
        print(f"\n   📁 HTML sauvegardé: {output}")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
