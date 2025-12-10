"""
Script de migration pour calculer et remplir le compliance_status des question_answer existants.

Ce script analyse toutes les réponses de la table question_answer et calcule le compliance_status
en fonction de :
- answer_value (oui/non/partiel/na)
- compliance_level de la question (critical/major/minor)

Logique :
- answer = 'non' + compliance_level = 'critical' ou 'major' => 'non_compliant_major'
- answer = 'non' + compliance_level = 'minor' => 'non_compliant_minor'
- answer = 'partiel' => 'partially_compliant'
- answer = 'oui' => 'compliant'
- answer = 'na' => 'not_applicable'
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
import sys

# Ajouter le répertoire parent au path pour importer les modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

def main():
    print("=" * 80)
    print("MIGRATION : Calcul du compliance_status pour question_answer")
    print("=" * 80)
    print()

    # Connexion à la base
    engine = create_engine(os.getenv('DATABASE_URL'))
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # 1. Statistiques avant migration
        print("STATISTIQUES AVANT MIGRATION")
        print("-" * 80)

        stats_before = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN compliance_status IS NULL THEN 1 END) as null_count,
                COUNT(CASE WHEN compliance_status = 'compliant' THEN 1 END) as compliant,
                COUNT(CASE WHEN compliance_status = 'non_compliant_major' THEN 1 END) as nc_major,
                COUNT(CASE WHEN compliance_status = 'non_compliant_minor' THEN 1 END) as nc_minor,
                COUNT(CASE WHEN compliance_status = 'partially_compliant' THEN 1 END) as partial,
                COUNT(CASE WHEN compliance_status = 'not_applicable' THEN 1 END) as na
            FROM question_answer
        """)).fetchone()

        print(f"Total reponses : {stats_before[0]}")
        print(f"  - compliance_status NULL : {stats_before[1]}")
        print(f"  - Conformes : {stats_before[2]}")
        print(f"  - NC Majeures : {stats_before[3]}")
        print(f"  - NC Mineures : {stats_before[4]}")
        print(f"  - Partiellement conformes : {stats_before[5]}")
        print(f"  - Non applicables : {stats_before[6]}")
        print()

        # 2. Mise à jour du compliance_status
        print("CALCUL ET MISE A JOUR DU COMPLIANCE_STATUS")
        print("-" * 80)

        # Mise à jour en fonction de answer_value->>'choice' et risk_level
        update_query = text("""
            UPDATE question_answer qa
            SET compliance_status =
                CASE
                    -- Non conforme (choice = 'Non')
                    WHEN LOWER(qa.answer_value->>'choice') = 'non' THEN
                        CASE
                            -- High ou Critical => NC Majeure
                            WHEN LOWER(r.risk_level) IN ('high', 'critical', 'major') THEN 'non_compliant_major'
                            -- Medium => NC Majeure aussi (défaut conservateur)
                            WHEN LOWER(r.risk_level) IN ('medium', 'moderate') THEN 'non_compliant_major'
                            -- Low ou Minor => NC Mineure
                            WHEN LOWER(r.risk_level) IN ('low', 'minor') THEN 'non_compliant_minor'
                            ELSE 'non_compliant_major'  -- Par défaut conservateur
                        END
                    -- Partiellement conforme => Non-conformité mineure (approche conservatrice)
                    WHEN LOWER(qa.answer_value->>'choice') = 'partiellement' THEN 'non_compliant_minor'
                    -- Conforme
                    WHEN LOWER(qa.answer_value->>'choice') = 'oui' THEN 'compliant'
                    -- Non applicable
                    WHEN LOWER(qa.answer_value->>'choice') IN ('na', 'n/a', 'non applicable') THEN 'not_applicable'
                    -- Par défaut : NULL (pas de réponse de conformité)
                    ELSE NULL
                END
            FROM question q
            JOIN requirement r ON q.requirement_id = r.id
            WHERE qa.question_id = q.id
              AND qa.compliance_status IS NULL  -- Seulement les rows avec NULL
              AND qa.answer_value ? 'choice'    -- Seulement les réponses avec un choice
        """)

        result = db.execute(update_query)
        db.commit()

        print(f"[OK] {result.rowcount} lignes mises a jour")
        print()

        # 3. Statistiques après migration
        print("STATISTIQUES APRES MIGRATION")
        print("-" * 80)

        stats_after = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN compliance_status IS NULL THEN 1 END) as null_count,
                COUNT(CASE WHEN compliance_status = 'compliant' THEN 1 END) as compliant,
                COUNT(CASE WHEN compliance_status = 'non_compliant_major' THEN 1 END) as nc_major,
                COUNT(CASE WHEN compliance_status = 'non_compliant_minor' THEN 1 END) as nc_minor,
                COUNT(CASE WHEN compliance_status = 'partially_compliant' THEN 1 END) as partial,
                COUNT(CASE WHEN compliance_status = 'not_applicable' THEN 1 END) as na
            FROM question_answer
        """)).fetchone()

        print(f"Total reponses : {stats_after[0]}")
        print(f"  - compliance_status NULL : {stats_after[1]}")
        print(f"  - Conformes : {stats_after[2]}")
        print(f"  - NC Majeures : {stats_after[3]}")
        print(f"  - NC Mineures : {stats_after[4]}")
        print(f"  - Partiellement conformes : {stats_after[5]}")
        print(f"  - Non applicables : {stats_after[6]}")
        print()

        # 4. Détails par campagne
        print("DETAILS PAR CAMPAGNE")
        print("-" * 80)

        campaigns_stats = db.execute(text("""
            SELECT
                c.id,
                c.title,
                COUNT(qa.id) as total_answers,
                COUNT(CASE WHEN qa.compliance_status = 'non_compliant_major' THEN 1 END) as nc_major,
                COUNT(CASE WHEN qa.compliance_status = 'non_compliant_minor' THEN 1 END) as nc_minor,
                COUNT(CASE WHEN qa.compliance_status = 'compliant' THEN 1 END) as compliant
            FROM campaign c
            LEFT JOIN question_answer qa ON qa.campaign_id = c.id
            WHERE qa.id IS NOT NULL
            GROUP BY c.id, c.title
            ORDER BY c.title
        """)).fetchall()

        for camp in campaigns_stats:
            print(f"\n{camp[1]} (ID: {camp[0]})")
            print(f"  Total reponses : {camp[2]}")
            print(f"  NC Majeures : {camp[3]}")
            print(f"  NC Mineures : {camp[4]}")
            print(f"  Conformes : {camp[5]}")

        print()
        print("=" * 80)
        print("[OK] MIGRATION TERMINEE AVEC SUCCES")
        print("=" * 80)

    except Exception as e:
        print(f"\n[ERREUR] : {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
