"""
Script pour mettre à jour les compliance_status de la campagne gelée
avec des valeurs cohérentes basées sur les réponses.
"""
from sqlalchemy import text
from src.database import SessionLocal

CAMPAIGN_ID = 'dcdb2976-1b43-4fda-8816-f71058b63ae5'

def update_compliance_status():
    db = SessionLocal()
    try:
        # 1. Mettre à jour les réponses single_choice avec Oui/Non/Partiellement
        print("Mise à jour des single_choice avec Oui...")
        db.execute(text("""
            UPDATE question_answer
            SET compliance_status = 'compliant'
            WHERE campaign_id = :campaign_id
            AND is_current = true
            AND compliance_status IS NULL
            AND answer_value->>'choice' ILIKE 'oui'
        """), {"campaign_id": CAMPAIGN_ID})

        print("Mise à jour des single_choice avec Non...")
        db.execute(text("""
            UPDATE question_answer
            SET compliance_status = 'non_compliant_major'
            WHERE campaign_id = :campaign_id
            AND is_current = true
            AND compliance_status IS NULL
            AND answer_value->>'choice' ILIKE 'non'
        """), {"campaign_id": CAMPAIGN_ID})

        print("Mise à jour des single_choice avec Partiellement...")
        db.execute(text("""
            UPDATE question_answer
            SET compliance_status = 'non_compliant_minor'
            WHERE campaign_id = :campaign_id
            AND is_current = true
            AND compliance_status IS NULL
            AND (answer_value->>'choice' ILIKE 'partiellement'
                 OR answer_value->>'choice' ILIKE 'partiel')
        """), {"campaign_id": CAMPAIGN_ID})

        print("Mise à jour des single_choice avec N/A...")
        db.execute(text("""
            UPDATE question_answer
            SET compliance_status = 'not_applicable'
            WHERE campaign_id = :campaign_id
            AND is_current = true
            AND compliance_status IS NULL
            AND (answer_value->>'choice' ILIKE 'n/a'
                 OR answer_value->>'choice' ILIKE 'na'
                 OR answer_value->>'choice' ILIKE 'non applicable')
        """), {"campaign_id": CAMPAIGN_ID})

        # 2. Mettre à jour les boolean (True = compliant, False = non_compliant)
        print("Mise à jour des boolean True...")
        db.execute(text("""
            UPDATE question_answer
            SET compliance_status = 'compliant'
            WHERE campaign_id = :campaign_id
            AND is_current = true
            AND compliance_status IS NULL
            AND (answer_value->>'bool')::boolean = true
        """), {"campaign_id": CAMPAIGN_ID})

        print("Mise à jour des boolean False...")
        db.execute(text("""
            UPDATE question_answer
            SET compliance_status = 'non_compliant_major'
            WHERE campaign_id = :campaign_id
            AND is_current = true
            AND compliance_status IS NULL
            AND (answer_value->>'bool')::boolean = false
        """), {"campaign_id": CAMPAIGN_ID})

        db.commit()
        print("=" * 60)
        print("Mise à jour terminée!")

        # Vérifier les résultats
        result = db.execute(text("""
            SELECT compliance_status, COUNT(*) as cnt
            FROM question_answer
            WHERE campaign_id = :campaign_id
            AND is_current = true
            GROUP BY compliance_status
            ORDER BY compliance_status
        """), {"campaign_id": CAMPAIGN_ID})

        print("\nRépartition des compliance_status:")
        for row in result.fetchall():
            print(f"  {row.compliance_status or 'NULL'}: {row.cnt}")

    finally:
        db.close()

if __name__ == "__main__":
    update_compliance_status()
