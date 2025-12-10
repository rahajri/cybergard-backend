"""Script pour trouver les campagnes et entités."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Trouver les campagnes
    result = conn.execute(text("SELECT id, title FROM campaign ORDER BY created_at DESC LIMIT 10")).fetchall()
    print("=== CAMPAGNES ===")
    for r in result:
        print(f"  {r.id} - {r.title}")

    # Trouver l'entité FRANCE IA
    result2 = conn.execute(text("SELECT id, name FROM ecosystem_entity WHERE name ILIKE '%france%' OR name ILIKE '%ia%'")).fetchall()
    print("\n=== ENTITÉS (FRANCE/IA) ===")
    for r in result2:
        print(f"  {r.id} - {r.name}")

    # Trouver les audits liés à FRANCE IA
    result3 = conn.execute(text("""
        SELECT a.id as audit_id, a.campaign_id, c.title as campaign_title, ee.name as entity_name
        FROM audit a
        JOIN campaign c ON a.campaign_id = c.id
        JOIN ecosystem_entity ee ON a.entity_id = ee.id
        WHERE ee.name ILIKE '%france%' OR ee.name ILIKE '%ia%'
        LIMIT 10
    """)).fetchall()
    print("\n=== AUDITS FRANCE IA ===")
    for r in result3:
        print(f"  Campaign: {r.campaign_id}")
        print(f"    Title: {r.campaign_title}")
        print(f"    Entity: {r.entity_name}")
        print()
