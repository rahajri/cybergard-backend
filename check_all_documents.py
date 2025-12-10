"""
Vérifier TOUS les documents dans la base de données
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text

# Fix encoding for Windows console
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Database URL
db_url = 'postgresql://postgres:postgres@localhost:5432/audit_platform'

engine = create_engine(db_url)

with engine.connect() as conn:
    print('\n=== TOUS LES DOCUMENTS (ACTIFS ET INACTIFS) ===\n')

    # Compter TOUS les answer_attachment (même inactifs ou soft-deleted)
    query = text('''
        SELECT
            COUNT(*) FILTER (WHERE is_active = true AND deleted_at IS NULL) as actifs,
            COUNT(*) FILTER (WHERE is_active = false) as inactifs,
            COUNT(*) FILTER (WHERE deleted_at IS NOT NULL) as soft_deleted,
            COUNT(*) as total
        FROM answer_attachment
    ''')
    result = conn.execute(query).fetchone()
    print(f'Documents actifs: {result.actifs}')
    print(f'Documents inactifs: {result.inactifs}')
    print(f'Documents soft-deleted: {result.soft_deleted}')
    print(f'Total documents (table): {result.total}\n')

    # Voir les derniers documents (même supprimés)
    query = text('''
        SELECT
            id,
            original_filename,
            file_size,
            uploaded_at,
            audit_id,
            is_active,
            deleted_at
        FROM answer_attachment
        ORDER BY uploaded_at DESC
        LIMIT 10
    ''')
    docs = conn.execute(query).fetchall()

    if len(docs) > 0:
        print('=== 10 DERNIERS DOCUMENTS (même supprimés) ===\n')
        for doc in docs:
            status = 'ACTIF' if doc.is_active and doc.deleted_at is None else 'SUPPRIME' if doc.deleted_at else 'INACTIF'
            print(f'{status}: {doc.original_filename}')
            print(f'  Audit ID: {doc.audit_id}')
            print(f'  Date: {doc.uploaded_at}')
            print(f'  Deleted at: {doc.deleted_at}')
            print()
    else:
        print('Aucun document dans la table answer_attachment (table vide)')
