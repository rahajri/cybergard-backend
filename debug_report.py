"""Debug report data collection"""
from sqlalchemy import text
from src.database import SessionLocal

CAMPAIGN_ID = 'dcdb2976-1b43-4fda-8816-f71058b63ae5'
ENTITY_ID = '1754cab1-c444-4a32-88d7-12faeb035115'  # FRANCE IA

db = SessionLocal()

# 0. Structure de audit
print("="*60)
print("0. Colonnes de la table audit")
result = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'audit'"))
cols = [r[0] for r in result.fetchall()]
print(f"  {cols}")

# 1. Vérifier les réponses avec compliance_status
print("\n" + "="*60)
print("1. Réponses avec compliance_status")
result = db.execute(text("""
    SELECT compliance_status, COUNT(*)
    FROM question_answer
    WHERE campaign_id = :campaign_id AND is_current = true
    GROUP BY compliance_status
"""), {"campaign_id": CAMPAIGN_ID})
for row in result.fetchall():
    print(f"  {row[0]}: {row[1]}")

# 2. Vérifier les audits
print("\n" + "="*60)
print("2. Audits (via question_answer.audit_id)")
result = db.execute(text("""
    SELECT DISTINCT qa.audit_id
    FROM question_answer qa
    WHERE qa.campaign_id = :campaign_id AND qa.is_current = true
"""), {"campaign_id": CAMPAIGN_ID})
audit_ids = [r[0] for r in result.fetchall()]
print(f"  audit_ids: {audit_ids}")

# 3. Vérifier audit.target_org_id pour ces audit_ids
print("\n" + "="*60)
print("3. Audit target_org_id")
if audit_ids:
    for aid in audit_ids:
        result = db.execute(text("""
            SELECT a.id, a.target_org_id, ee.name
            FROM audit a
            LEFT JOIN ecosystem_entity ee ON a.target_org_id = ee.id
            WHERE a.id = :audit_id
        """), {"audit_id": str(aid)})
        row = result.fetchone()
        if row:
            print(f"  audit {row.id}: target_org_id={row.target_org_id}, entity={row.name}")
        else:
            print(f"  audit {aid}: NOT FOUND")

# 4. Vérifier la jointure complète
print("\n" + "="*60)
print("4. Test jointure avec entity_id spécifique")
result = db.execute(text("""
    SELECT COUNT(*) as cnt
    FROM question_answer qa
    JOIN audit a ON qa.audit_id = a.id
    WHERE qa.campaign_id = :campaign_id
      AND qa.is_current = true
      AND a.target_org_id = CAST(:entity_id AS uuid)
"""), {"campaign_id": CAMPAIGN_ID, "entity_id": ENTITY_ID})
row = result.fetchone()
print(f"  Réponses pour entity {ENTITY_ID}: {row.cnt}")

# 5. Vérifier les entités du campaign_scope
print("\n" + "="*60)
print("5. Entités dans campaign_scope")
result = db.execute(text("""
    SELECT cs.entity_ids, ee.id, ee.name
    FROM campaign_scope cs
    JOIN campaign c ON c.scope_id = cs.id
    CROSS JOIN LATERAL unnest(cs.entity_ids) AS eid(id)
    JOIN ecosystem_entity ee ON ee.id = eid.id
    WHERE c.id = :campaign_id
"""), {"campaign_id": CAMPAIGN_ID})
for row in result.fetchall():
    print(f"  Entity: {row.name} ({row.id})")

db.close()
