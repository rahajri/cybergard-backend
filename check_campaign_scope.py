import sys
sys.path.insert(0, r'c:\Users\rachi\Documents\Mes Sites\AI CYBER\backend')

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Trouver la campagne ISO 27001
    campaign_query = text("""
        SELECT id, title, scope_id, status
        FROM campaign
        WHERE title LIKE '%ISO 27001%'
        LIMIT 1
    """)
    campaign = conn.execute(campaign_query).fetchone()

    if not campaign:
        print("Campaign ISO 27001 not found")
        exit(1)

    print(f"=== CAMPAGNE ===")
    print(f"ID: {campaign.id}")
    print(f"Title: {campaign.title}")
    print(f"Scope ID: {campaign.scope_id}")
    print(f"Status: {campaign.status}\n")

    if campaign.scope_id:
        # Vérifier le scope
        scope_query = text("""
            SELECT id, name, entity_ids, auditor_ids
            FROM campaign_scope
            WHERE id = :scope_id
        """)
        scope = conn.execute(scope_query, {"scope_id": str(campaign.scope_id)}).fetchone()

        if scope:
            print(f"=== SCOPE ===")
            print(f"ID: {scope.id}")
            print(f"Name: {scope.name}")
            print(f"Entity IDs: {scope.entity_ids}")
            print(f"Auditor IDs: {scope.auditor_ids}\n")

            if scope.auditor_ids and len(scope.auditor_ids) > 0:
                print(f"Le scope contient {len(scope.auditor_ids)} auditeur(s)")
            else:
                print("PROBLEME: Le scope ne contient AUCUN auditeur!")
        else:
            print(f"PROBLEME: Scope {campaign.scope_id} introuvable!")
    else:
        print("PROBLEME: La campagne n'a PAS de scope_id défini!")
