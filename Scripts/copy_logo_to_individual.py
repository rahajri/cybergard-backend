"""Script pour copier le logo du template Consolidé vers le template Individuel."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    # Récupérer le logo du template Consolidé AHAJRI
    source = db.execute(text("""
        SELECT custom_logo, default_logo
        FROM report_template
        WHERE name LIKE '%Consolidé%AHAJRI%'
        AND custom_logo IS NOT NULL
        LIMIT 1
    """)).fetchone()

    if not source or not source.custom_logo:
        print("❌ Aucun logo trouvé dans le template Consolidé AHAJRI")
    else:
        print(f"✅ Logo trouvé ({len(source.custom_logo)} chars)")

        # Mettre à jour le template Individuel AHAJRI
        result = db.execute(text("""
            UPDATE report_template
            SET custom_logo = :custom_logo,
                default_logo = 'CUSTOM'
            WHERE name LIKE '%Individuel%AHAJRI%'
            RETURNING id, name
        """), {"custom_logo": source.custom_logo})

        updated = result.fetchall()
        db.commit()

        if updated:
            for row in updated:
                print(f"✅ Template mis à jour: {row.name}")
        else:
            print("❌ Aucun template Individuel AHAJRI trouvé")

    # Vérification finale
    print("\n--- État final des templates AHAJRI ---")
    templates = db.execute(text("""
        SELECT name, default_logo,
               CASE WHEN custom_logo IS NOT NULL THEN 'OUI' ELSE 'NON' END as has_logo
        FROM report_template
        WHERE name LIKE '%AHAJRI%'
        ORDER BY name
    """)).fetchall()

    for t in templates:
        print(f"  {t.name}: default_logo={t.default_logo}, custom_logo={t.has_logo}")

except Exception as e:
    db.rollback()
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
