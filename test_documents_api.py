"""
Test de l'endpoint GET /campaigns/{campaign_id}/documents
"""
from src.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

campaign_id = 'e954e93c-3964-4aa1-a50a-e965974a5511'

# Récupérer la campagne
campaign = db.execute(
    text('SELECT title, tenant_id FROM campaign WHERE id = :id'),
    {'id': campaign_id}
).fetchone()

print(f"Campagne: {campaign[0]}")
print(f"Tenant ID: {campaign[1]}")
print()

# Requête exacte utilisée par l'endpoint
query = text("""
    WITH campaign_audits AS (
        SELECT DISTINCT a.id as audit_id, a.evaluated_org_id
        FROM audit a
        WHERE a.name LIKE '%' || :campaign_title || '%'
          AND a.tenant_id = :tenant_id
    )
    SELECT
        aa.id, aa.original_filename, aa.file_size,
        q.question_text as question_text, q.sort_order as question_order,
        ee.name as entity_name
    FROM answer_attachment aa
    INNER JOIN campaign_audits ca ON aa.audit_id = ca.audit_id
    INNER JOIN question_answer qa ON aa.answer_id = qa.id
    INNER JOIN question q ON qa.question_id = q.id
    LEFT JOIN ecosystem_entity ee ON ca.evaluated_org_id = ee.id
    WHERE aa.is_active = true AND aa.deleted_at IS NULL
    ORDER BY aa.uploaded_at DESC
    LIMIT 10
""")

result = db.execute(query, {
    'campaign_title': campaign[0],
    'tenant_id': campaign[1]
}).fetchall()

print(f"Documents trouves: {len(result)}")
print()

if len(result) == 0:
    print("[PROBLEME] Aucun document trouve!")
    print()
    print("Verification des audits...")
    audits = db.execute(
        text("SELECT id, name FROM audit WHERE name LIKE '%' || :title || '%' AND tenant_id = :tid"),
        {'title': campaign[0], 'tid': campaign[1]}
    ).fetchall()
    print(f"Audits trouvés: {len(audits)}")
    for audit in audits:
        print(f"  - {audit[1]}")

    print()
    print("Verification des documents dans ces audits...")
    for audit in audits:
        doc_count = db.execute(
            text("SELECT COUNT(*) FROM answer_attachment WHERE audit_id = :aid AND is_active = true"),
            {'aid': audit[0]}
        ).fetchone()[0]
        print(f"  - {audit[1]}: {doc_count} documents")
else:
    for r in result:
        print(f"  - {r[1]} ({r[2]} bytes)")
        print(f"    Question: Q{r[4]} - {r[3][:50]}...")
        print(f"    Entite: {r[5] or 'NULL'}")
        print()

db.close()
