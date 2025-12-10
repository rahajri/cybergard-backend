"""Script pour lister tous les rapports générés avec leurs données."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    result = db.execute(text("""
        SELECT
            gr.id,
            gr.title,
            gr.report_scope,
            gr.status,
            gr.generated_at,
            c.title as campaign_title,
            rt.name as template_name,
            rt.default_logo,
            CASE WHEN rt.custom_logo IS NOT NULL THEN 'OUI' ELSE 'NON' END as has_custom_logo,
            (SELECT COUNT(*) FROM question_answer qa
             JOIN audit a ON qa.audit_id = a.id
             WHERE a.campaign_id = gr.campaign_id AND qa.is_current = true) as response_count
        FROM generated_report gr
        LEFT JOIN campaign c ON gr.campaign_id = c.id
        LEFT JOIN report_template rt ON gr.template_id = rt.id
        ORDER BY gr.generated_at DESC
        LIMIT 10
    """)).fetchall()

    print("=" * 140)
    print("RAPPORTS GÉNÉRÉS (10 derniers)")
    print("=" * 140)
    print(f"{'TITRE':<40} | {'CAMPAGNE':<25} | {'SCOPE':<12} | {'RÉPONSES':<10} | {'LOGO':<10} | {'CUSTOM':<6}")
    print("-" * 140)

    for r in result:
        title = (r.title or 'N/A')[:38]
        campaign = (r.campaign_title or 'N/A')[:23]
        scope = r.report_scope or 'N/A'
        responses = r.response_count or 0
        logo = r.default_logo or 'NULL'
        custom = r.has_custom_logo or 'NON'

        print(f"{title:<40} | {campaign:<25} | {scope:<12} | {responses:<10} | {logo:<10} | {custom:<6}")

    print("-" * 140)

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
