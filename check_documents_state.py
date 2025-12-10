"""
Vérifier l'état actuel des documents dans la base de données
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
    print('\n=== VERIFICATION DES DOCUMENTS ===\n')

    # 1. Compter tous les answer_attachment actifs
    query = text('''
        SELECT COUNT(*) as total
        FROM answer_attachment
        WHERE is_active = true AND deleted_at IS NULL
    ''')
    result = conn.execute(query).fetchone()
    print(f'✅ Total documents actifs dans answer_attachment: {result.total}\n')

    # 2. Voir quelques exemples de documents
    if result.total > 0:
        query = text('''
            SELECT
                aa.id,
                aa.original_filename,
                aa.file_size,
                aa.uploaded_at,
                aa.audit_id,
                u.email as uploaded_by_email
            FROM answer_attachment aa
            LEFT JOIN users u ON aa.uploaded_by = u.id
            WHERE aa.is_active = true AND aa.deleted_at IS NULL
            ORDER BY aa.uploaded_at DESC
            LIMIT 5
        ''')
        docs = conn.execute(query).fetchall()
        print('📄 Exemples de documents (5 derniers):')
        for doc in docs:
            print(f'  - {doc.original_filename} ({doc.file_size} bytes)')
            print(f'    Audit ID: {doc.audit_id}')
            print(f'    Uploadé par: {doc.uploaded_by_email}')
            print(f'    Date: {doc.uploaded_at}')
            print()

    # 3. Vérifier la structure audit_tokens
    print('=== STRUCTURE AUDIT_TOKENS ===\n')
    query = text('''
        SELECT
            at.id,
            at.campaign_id,
            at.user_email,
            at.questionnaire_id,
            c.title as campaign_title
        FROM audit_tokens at
        LEFT JOIN campaign c ON at.campaign_id = c.id
        WHERE at.revoked = false
        LIMIT 5
    ''')
    tokens = conn.execute(query).fetchall()
    print(f'✅ Audit tokens actifs: {len(tokens)}\n')
    for token in tokens:
        print(f'  Campaign: {token.campaign_title} (ID: {token.campaign_id})')
        print(f'  Email: {token.user_email}')
        print(f'  Questionnaire ID: {token.questionnaire_id}')
        print()

    # 4. Vérifier les audits liés aux questionnaires des tokens
    print('=== AUDITS LIES AUX CAMPAIGNS (via audit_tokens) ===\n')
    query = text('''
        SELECT DISTINCT
            at.campaign_id,
            c.title as campaign_title,
            a.id as audit_id,
            a.name as audit_name,
            a.questionnaire_id
        FROM audit_tokens at
        INNER JOIN campaign c ON at.campaign_id = c.id
        INNER JOIN audit a ON a.questionnaire_id = at.questionnaire_id
        WHERE at.revoked = false
        LIMIT 10
    ''')
    audits = conn.execute(query).fetchall()
    print(f'✅ Audits liés aux campaigns: {len(audits)}\n')
    for audit in audits:
        print(f'  Campaign: {audit.campaign_title}')
        print(f'  Audit: {audit.audit_name} (ID: {audit.audit_id})')
        print(f'  Questionnaire ID: {audit.questionnaire_id}')
        print()

    # 5. Vérifier combien de documents sont liés à ces audits
    if len(audits) > 0:
        print('=== DOCUMENTS LIES AUX AUDITS DES CAMPAIGNS ===\n')
        audit_ids = [str(audit.audit_id) for audit in audits]
        query = text(f'''
            SELECT
                aa.audit_id,
                a.name as audit_name,
                COUNT(*) as doc_count
            FROM answer_attachment aa
            INNER JOIN audit a ON aa.audit_id = a.id
            WHERE aa.is_active = true
              AND aa.deleted_at IS NULL
              AND aa.audit_id IN ({','.join([f"'{aid}'" for aid in audit_ids])})
            GROUP BY aa.audit_id, a.name
        ''')
        doc_counts = conn.execute(query).fetchall()
        total_docs = sum(dc.doc_count for dc in doc_counts)
        print(f'✅ Total documents dans les audits de campaigns: {total_docs}\n')
        for dc in doc_counts:
            print(f'  Audit: {dc.audit_name}')
            print(f'  Documents: {dc.doc_count}')
            print()
