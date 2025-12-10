"""
Script de test pour vérifier les données de rapport après correction des compliance_status.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

# IDs de la campagne FRANCE IA
CAMPAIGN_ID = "5c61c9b6-3444-451c-a81d-b68c4f0e43f2"
ENTITY_ID = "1754cab1-c444-4a32-88d7-12faeb035115"

def test_compliance_status_values():
    """Vérifier les valeurs de compliance_status dans la base."""
    with engine.connect() as conn:
        query = text("""
            SELECT DISTINCT compliance_status, COUNT(*) as count
            FROM question_answer qa
            JOIN audit a ON qa.audit_id = a.id
            WHERE a.entity_id = CAST(:entity_id AS uuid)
            GROUP BY compliance_status
            ORDER BY count DESC
        """)
        result = conn.execute(query, {"entity_id": ENTITY_ID}).fetchall()

        print("\n=== VALEURS DE COMPLIANCE_STATUS ===")
        for row in result:
            print(f"  {row.compliance_status or 'NULL'}: {row.count}")

def test_score_query():
    """Test de la requête de score avec valeurs anglaises."""
    with engine.connect() as conn:
        query = text("""
            SELECT
                COUNT(DISTINCT qr.id) as total_questions,
                COUNT(DISTINCT CASE WHEN qr.compliance_status = 'compliant' THEN qr.id END) as conformes,
                COUNT(DISTINCT CASE WHEN qr.compliance_status IN ('non_compliant', 'partial') THEN qr.id END) as nc_count
            FROM question_answer qr
            JOIN audit a ON qr.audit_id = a.id
            WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
              AND a.entity_id = CAST(:entity_id AS uuid)
        """)
        result = conn.execute(query, {
            "campaign_id": CAMPAIGN_ID,
            "entity_id": ENTITY_ID
        }).fetchone()

        total = result.total_questions or 0
        conformes = result.conformes or 0
        nc_count = result.nc_count or 0
        score = round((conformes / total * 100), 1) if total > 0 else 0

        print("\n=== TEST REQUÊTE SCORE (CORRIGÉE) ===")
        print(f"  Total questions: {total}")
        print(f"  Conformes: {conformes}")
        print(f"  Non-conformes/Partiels: {nc_count}")
        print(f"  Score calculé: {score}%")

def test_domain_query():
    """Test de la requête par domaines."""
    with engine.connect() as conn:
        query = text("""
            SELECT
                COALESCE(d.code_officiel, d.code) as name,
                COUNT(DISTINCT qr.id) as questions,
                COUNT(DISTINCT CASE WHEN qr.compliance_status = 'compliant' THEN qr.id END) as conformes,
                COUNT(DISTINCT CASE WHEN qr.compliance_status IN ('non_compliant', 'partial') THEN qr.id END) as nc_count
            FROM domain d
            JOIN requirement r ON r.domain_id = d.id
            JOIN question q ON q.requirement_id = r.id
            JOIN question_answer qr ON qr.question_id = q.id
            JOIN audit a ON qr.audit_id = a.id
            WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
              AND a.entity_id = CAST(:entity_id AS uuid)
            GROUP BY d.id, COALESCE(d.code_officiel, d.code)
            ORDER BY d.code
        """)
        results = conn.execute(query, {
            "campaign_id": CAMPAIGN_ID,
            "entity_id": ENTITY_ID
        }).fetchall()

        print("\n=== ANALYSE PAR DOMAINES (CORRIGÉE) ===")
        for d in results:
            rate = round((d.conformes / d.questions * 100), 1) if d.questions > 0 else 0
            print(f"  {d.name}: {rate}% ({d.conformes}/{d.questions} conformes, {d.nc_count} NC)")

def test_campaign_info():
    """Test des informations de campagne."""
    with engine.connect() as conn:
        query = text("""
            SELECT
                c.title as campaign_title,
                c.description as campaign_description,
                c.launch_date as start_date,
                c.due_date as end_date,
                f.name as framework_name,
                f.code as framework_code,
                q.name as questionnaire_name
            FROM campaign c
            LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
            LEFT JOIN framework f ON q.framework_id = f.id
            WHERE c.id = CAST(:campaign_id AS uuid)
        """)
        result = conn.execute(query, {"campaign_id": CAMPAIGN_ID}).fetchone()

        print("\n=== INFORMATIONS CAMPAGNE ===")
        print(f"  Titre: {result.campaign_title}")
        print(f"  Description: {result.campaign_description or 'N/A'}")
        print(f"  Framework: {result.framework_name or 'N/A'} ({result.framework_code or 'N/A'})")
        print(f"  Questionnaire: {result.questionnaire_name or 'N/A'}")
        print(f"  Dates: {result.start_date} - {result.end_date}")

def test_entity_info():
    """Test des informations de l'entité."""
    with engine.connect() as conn:
        query = text("""
            SELECT
                ee.name,
                ee.stakeholder_type,
                ee.city,
                ee.country_code,
                ee.description as entity_description,
                cat.name as category_name
            FROM ecosystem_entity ee
            LEFT JOIN categories cat ON ee.category_id = cat.id
            WHERE ee.id = CAST(:entity_id AS uuid)
        """)
        result = conn.execute(query, {"entity_id": ENTITY_ID}).fetchone()

        print("\n=== INFORMATIONS ENTITÉ ===")
        print(f"  Nom: {result.name}")
        print(f"  Type: {result.stakeholder_type or 'N/A'}")
        print(f"  Localisation: {result.city or 'N/A'}, {result.country_code or 'N/A'}")
        print(f"  Description: {result.entity_description or 'N/A'}")
        print(f"  Catégorie: {result.category_name or 'N/A'}")

if __name__ == "__main__":
    print("=" * 60)
    print("TEST DES DONNÉES RAPPORT APRÈS CORRECTION")
    print("=" * 60)

    test_compliance_status_values()
    test_campaign_info()
    test_entity_info()
    test_score_query()
    test_domain_query()

    print("\n" + "=" * 60)
    print("✅ Tests terminés!")
    print("=" * 60)
