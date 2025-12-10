"""
Check contributor in database
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
import os

# Database URL
db_url = 'postgresql://postgres:postgres@localhost:5432/audit_platform'

engine = create_engine(db_url)

with engine.connect() as conn:
    # Rechercher le contributeur
    query = text('''
        SELECT
            em.id,
            em.email,
            em.first_name,
            em.last_name,
            em.roles,
            em.entity_id,
            ee.name as entity_name,
            em.created_at
        FROM entity_member em
        LEFT JOIN ecosystem_entity ee ON em.entity_id = ee.id
        WHERE em.email LIKE '%contrib%'
        ORDER BY em.created_at DESC
    ''')

    results = conn.execute(query).fetchall()

    print('\n=== CONTRIBUTEURS DANS LA BASE ===\n')
    for row in results:
        print(f'ID: {row.id}')
        print(f'Email: {row.email}')
        print(f'Nom: {row.first_name} {row.last_name}')
        print(f'Roles: {row.roles}')
        print(f'Entite: {row.entity_name} ({row.entity_id})')
        print(f'Cree le: {row.created_at}')
        print('-' * 60)

    print(f'\nTotal: {len(results)} contributeur(s)\n')
