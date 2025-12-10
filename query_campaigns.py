import sys
sys.path.insert(0, r'c:\Users\rachi\Documents\Mes Sites\AI CYBER\backend')

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Find campaigns with our entities
    query = text("""
        SELECT
            c.id as campaign_id,
            c.title,
            c.scope_id,
            c.status,
            cs.name as scope_name,
            cs.entity_ids
        FROM campaign c
        LEFT JOIN campaign_scope cs ON c.scope_id = cs.id
        WHERE cs.entity_ids && ARRAY['1754cab1-c444-4a32-88d7-12faeb035115'::uuid, 'cbdebd92-e22a-4911-8da7-7cf665336b9b'::uuid]
        ORDER BY c.created_at DESC
        LIMIT 5
    """)

    result = conn.execute(query)
    rows = result.fetchall()

    print('=== CAMPAIGNS WITH FRANCE IA OR C2M SYSTEM ===')
    for row in rows:
        print(f'Campaign ID: {row.campaign_id}')
        print(f'  Title: {row.title}')
        print(f'  Status: {row.status}')
        print(f'  Scope ID: {row.scope_id}')
        print(f'  Scope Name: {row.scope_name}')
        print(f'  Entity IDs in scope: {row.entity_ids}')
        print()
