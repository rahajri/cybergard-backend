"""
Describe audit_tokens table structure
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text

# Database URL
db_url = 'postgresql://postgres:postgres@localhost:5432/audit_platform'

engine = create_engine(db_url)

with engine.connect() as conn:
    # Get column names and types
    query = text('''
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'audit_tokens'
        ORDER BY ordinal_position
    ''')

    results = conn.execute(query).fetchall()

    print('\n=== STRUCTURE DE LA TABLE audit_tokens ===\n')
    for row in results:
        print(f'  {row.column_name:<30} {row.data_type}')
    print()
