"""
List all tables in the database
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text

# Database URL
db_url = 'postgresql://postgres:postgres@localhost:5432/audit_platform'

engine = create_engine(db_url)

with engine.connect() as conn:
    # List all tables
    query = text('''
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name LIKE '%magic%'
        OR table_name LIKE '%token%'
        ORDER BY table_name
    ''')

    results = conn.execute(query).fetchall()

    print('\n=== TABLES CONTENANT "MAGIC" OU "TOKEN" ===\n')
    for row in results:
        print(f'  - {row.table_name}')

    if not results:
        print('  Aucune table trouvee.\n')
        print('=== TOUTES LES TABLES ===\n')

        query_all = text('''
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        ''')

        results_all = conn.execute(query_all).fetchall()
        for row in results_all:
            print(f'  - {row.table_name}')
