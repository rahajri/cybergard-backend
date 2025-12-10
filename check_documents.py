from src.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print('=== Verification entity_document ===')
entity_docs = db.execute(text('SELECT COUNT(*) FROM entity_document')).fetchone()
print(f'Total entity_document: {entity_docs[0]}')

print('\n=== Verification question_answer (total) ===')
qa_total = db.execute(text('SELECT COUNT(*) FROM question_answer')).fetchone()
print(f'Total question_answer: {qa_total[0]}')

print('\n=== Verification audits lies a la campagne ISO 27001 ===')
audits = db.execute(text("SELECT id, name FROM audit WHERE name LIKE '%ISO 27001%' LIMIT 3")).fetchall()
print(f'Audits trouves: {len(audits)}')
for a in audits:
    print(f'  - {a[1]} (ID: {a[0]})')

if audits:
    audit_id = audits[0][0]
    print(f'\n=== Verification reponses pour audit {audit_id} ===')
    qa_count = db.execute(text('SELECT COUNT(*) FROM question_answer WHERE audit_id = :aid'), {'aid': audit_id}).fetchone()
    print(f'Reponses dans cet audit: {qa_count[0]}')

    if qa_count[0] > 0:
        print('\n=== Verification answer_attachment pour cet audit ===')
        att_count = db.execute(text('SELECT COUNT(*) FROM answer_attachment WHERE audit_id = :aid'), {'aid': audit_id}).fetchone()
        print(f'Documents dans cet audit: {att_count[0]}')

        print('\n=== Exemples de reponses (5 premieres) ===')
        answers = db.execute(text('SELECT id, question_id, value FROM question_answer WHERE audit_id = :aid LIMIT 5'), {'aid': audit_id}).fetchall()
        for ans in answers:
            print(f'  Answer ID: {ans[0]}, Question ID: {ans[1]}, Value: {ans[2][:50] if ans[2] else "NULL"}...')

db.close()
