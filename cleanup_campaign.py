import sys
sys.path.insert(0, r'c:\Users\rachi\Documents\Mes Sites\AI CYBER\backend')

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

CAMPAIGN_ID = '65f50723-dcf5-4c48-83c2-ace342c9ae72'

with engine.connect() as conn:
    print("=== SUPPRESSION DE LA CAMPAGNE ET LIENS ASSOCIES ===\n")

    # 1. Supprimer les tokens d'audit (magic links)
    delete_tokens = text("""
        DELETE FROM audit_tokens
        WHERE campaign_id = :campaign_id
    """)
    result = conn.execute(delete_tokens, {"campaign_id": CAMPAIGN_ID})
    print(f"[OK] {result.rowcount} token(s) d'audit supprimes")

    # 2. Supprimer les reponses aux questions des audits
    delete_answers = text("""
        DELETE FROM question_answer
        WHERE audit_id IN (
            SELECT id FROM audit WHERE name LIKE '%ISO 27001%'
        )
    """)
    result = conn.execute(delete_answers)
    print(f"[OK] {result.rowcount} reponse(s) aux questions supprimees")

    # 3. Supprimer les audits
    delete_audits = text("""
        DELETE FROM audit
        WHERE name LIKE '%ISO 27001%'
    """)
    result = conn.execute(delete_audits)
    print(f"[OK] {result.rowcount} audit(s) supprimes")

    # 4. Recuperer le scope_id de la campagne avant suppression
    get_scope = text("""
        SELECT scope_id FROM campaign WHERE id = :campaign_id
    """)
    scope_result = conn.execute(get_scope, {"campaign_id": CAMPAIGN_ID}).fetchone()
    old_scope_id = scope_result.scope_id if scope_result else None

    # 5. Supprimer la campagne
    delete_campaign = text("""
        DELETE FROM campaign WHERE id = :campaign_id
    """)
    result = conn.execute(delete_campaign, {"campaign_id": CAMPAIGN_ID})
    print(f"[OK] {result.rowcount} campagne(s) supprimee(s)")

    # 6. Supprimer tous les scopes (ancien et nouveaux)
    delete_scopes = text("""
        DELETE FROM campaign_scope
        WHERE id IN (
            :old_scope,
            '9ebe68c9-4d3b-49ef-88a8-552ace58c8c0',
            '606ba3a0-656a-470b-bbfd-045c1642c291',
            '8b289b6d-8e7b-4e69-bd21-9d47a1c53bd7'
        )
    """)
    result = conn.execute(delete_scopes, {"old_scope": str(old_scope_id) if old_scope_id else '00000000-0000-0000-0000-000000000000'})
    print(f"[OK] {result.rowcount} scope(s) supprime(s)")

    # 7. Nettoyer les doublons de membres (garder seulement dans C2M SYSTEM)
    delete_duplicate_members = text("""
        DELETE FROM entity_member
        WHERE entity_id = '1754cab1-c444-4a32-88d7-12faeb035115'
          AND email LIKE '%@c2m.ma'
    """)
    result = conn.execute(delete_duplicate_members)
    print(f"[OK] {result.rowcount} membre(s) en double supprimes (membres C2M dans FRANCE IA)")

    conn.commit()

    print("\n=== NETTOYAGE TERMINE ===")
    print("La base de donnees est propre, prete pour recreer la campagne correctement.")
