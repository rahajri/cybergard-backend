"""Script pour vérifier le template utilisé par un rapport."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    # Chercher les rapports récents et leur template
    result = db.execute(text("""
        SELECT
            gr.id as report_id,
            gr.title as report_title,
            gr.status,
            gr.generated_at,
            rt.id as template_id,
            rt.name as template_name,
            rt.code as template_code,
            rt.is_system,
            rt.default_logo,
            CASE WHEN rt.custom_logo IS NOT NULL THEN 'OUI' ELSE 'NON' END as has_custom_logo,
            c.title as campaign_title
        FROM generated_report gr
        LEFT JOIN report_template rt ON gr.template_id = rt.id
        LEFT JOIN campaign c ON gr.campaign_id = c.id
        ORDER BY gr.generated_at DESC
        LIMIT 10
    """)).fetchall()

    print("=" * 120)
    print("RAPPORTS GÉNÉRÉS ET LEURS TEMPLATES")
    print("=" * 120)
    print(f"{'RAPPORT':<30} | {'TEMPLATE':<35} | {'CODE':<20} | {'SYSTEM':<8} | {'DEF_LOGO':<10} | {'CUSTOM':<8}")
    print("-" * 120)

    for row in result:
        report_title = (row.report_title or 'N/A')[:28]
        template_name = (row.template_name or 'N/A')[:33]
        template_code = (row.template_code or 'N/A')[:18]
        is_system = 'OUI' if row.is_system else 'NON'
        default_logo = row.default_logo or 'NULL'
        has_custom = row.has_custom_logo

        print(f"{report_title:<30} | {template_name:<35} | {template_code:<20} | {is_system:<8} | {default_logo:<10} | {has_custom:<8}")

    print("-" * 120)

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
