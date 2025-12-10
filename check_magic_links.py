"""
Check magic links for contributors
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text

# Database URL
db_url = 'postgresql://postgres:postgres@localhost:5432/audit_platform'

engine = create_engine(db_url)

with engine.connect() as conn:
    # Rechercher les audit tokens pour contrib1@ac2m.ma
    query = text('''
        SELECT
            id,
            user_email,
            campaign_id,
            token_hash,
            created_at,
            expires_at,
            used_count,
            max_uses,
            revoked
        FROM audit_tokens
        WHERE user_email LIKE '%contrib%'
        ORDER BY created_at DESC
    ''')

    results = conn.execute(query).fetchall()

    print('\n=== MAGIC LINKS POUR CONTRIBUTEURS ===\n')
    if results:
        for row in results:
            print(f'ID: {row.id}')
            print(f'Email: {row.user_email}')
            print(f'Campagne ID: {row.campaign_id}')
            print(f'Token Hash: {row.token_hash[:50]}...')
            print(f'Cree le: {row.created_at}')
            print(f'Expire le: {row.expires_at}')
            print(f'Utilisations: {row.used_count}/{row.max_uses}')
            print(f'Revoque: {row.revoked}')
            print('-' * 60)
        print(f'\nTotal: {len(results)} magic link(s)\n')
    else:
        print('Aucun magic link trouve pour les contributeurs!\n')
        print('Cela explique pourquoi aucun email n\'a ete envoye.\n')
