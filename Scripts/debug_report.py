"""Script pour déboguer le rapport et son template."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    # Trouver le rapport FRANCE IA le plus récent
    report = db.execute(text("""
        SELECT
            gr.id,
            gr.title,
            gr.template_id,
            gr.status,
            gr.generated_at
        FROM generated_report gr
        WHERE gr.title LIKE '%FRANCE IA%'
        ORDER BY gr.generated_at DESC
        LIMIT 1
    """)).fetchone()

    if not report:
        print("Aucun rapport FRANCE IA trouvé")
    else:
        print(f"\n{'='*80}")
        print(f"RAPPORT: {report.title}")
        print(f"ID: {report.id}")
        print(f"Template ID: {report.template_id}")
        print(f"Status: {report.status}")
        print(f"Généré le: {report.generated_at}")

        # Récupérer le template utilisé
        template = db.execute(text("""
            SELECT
                id,
                name,
                code,
                is_system,
                default_logo,
                CASE WHEN custom_logo IS NOT NULL THEN LENGTH(custom_logo) ELSE 0 END as custom_logo_length,
                LEFT(custom_logo, 50) as custom_logo_preview
            FROM report_template
            WHERE id = CAST(:template_id AS uuid)
        """), {"template_id": str(report.template_id)}).fetchone()

        if template:
            print(f"\n{'='*80}")
            print(f"TEMPLATE UTILISÉ:")
            print(f"  Nom: {template.name}")
            print(f"  Code: {template.code}")
            print(f"  Système: {'OUI' if template.is_system else 'NON'}")
            print(f"  default_logo: {template.default_logo}")
            print(f"  custom_logo length: {template.custom_logo_length} chars")
            print(f"  custom_logo preview: {template.custom_logo_preview}...")

            if template.default_logo != 'CUSTOM':
                print(f"\n⚠️  PROBLÈME: default_logo n'est pas 'CUSTOM' mais '{template.default_logo}'")
            if template.custom_logo_length == 0:
                print(f"\n⚠️  PROBLÈME: custom_logo est vide!")
            if template.is_system:
                print(f"\n⚠️  PROBLÈME: Le rapport utilise un template SYSTÈME, pas le template personnalisé du client!")

    # Lister tous les templates du tenant pour comparaison
    print(f"\n{'='*80}")
    print(f"TOUS LES TEMPLATES DISPONIBLES:")
    templates = db.execute(text("""
        SELECT
            rt.name,
            rt.code,
            rt.is_system,
            rt.default_logo,
            CASE WHEN rt.custom_logo IS NOT NULL THEN 'OUI' ELSE 'NON' END as has_custom_logo,
            rt.report_scope
        FROM report_template rt
        ORDER BY rt.is_system, rt.name
    """)).fetchall()

    for t in templates:
        system_marker = "[SYSTEM]" if t.is_system else "[TENANT]"
        print(f"  {system_marker} {t.name} | scope={t.report_scope} | default_logo={t.default_logo} | custom_logo={t.has_custom_logo}")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
