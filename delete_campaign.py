"""
Script pour supprimer la campagne ISO 27001 et toutes ses données
"""
from src.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

CAMPAIGN_ID = 'e954e93c-3964-4aa1-a50a-e965974a5511'
TENANT_ID = 'e628c959-d81b-417d-bbb9-0e861053ec30'

print("=" * 80)
print("SUPPRESSION DE LA CAMPAGNE ISO 27001")
print("=" * 80)
print()

try:
    # 1. Récupérer les IDs des audits
    print("[1/6] Récupération des audits de la campagne...")
    audits = db.execute(text("""
        SELECT id FROM audit
        WHERE name LIKE :pattern
        AND tenant_id = :tenant_id
    """), {'pattern': '%ISO 27001%', 'tenant_id': TENANT_ID}).fetchall()

    audit_ids = [str(a[0]) for a in audits]
    print(f"      {len(audit_ids)} audits trouvés")

    if len(audit_ids) > 0:
        # 2. Supprimer les documents
        print("[2/6] Suppression des documents...")
        total_docs = 0
        for audit_id in audit_ids:
            result = db.execute(text("""
                DELETE FROM answer_attachment
                WHERE audit_id = :audit_id
            """), {'audit_id': audit_id})
            total_docs += result.rowcount
        print(f"      {total_docs} documents supprimés")

        # 3. Supprimer les réponses
        print("[3/6] Suppression des réponses...")
        total_answers = 0
        for audit_id in audit_ids:
            result = db.execute(text("""
                DELETE FROM question_answer
                WHERE audit_id = :audit_id
            """), {'audit_id': audit_id})
            total_answers += result.rowcount
        print(f"      {total_answers} réponses supprimées")

        # 4. Supprimer les audits
        print("[4/6] Suppression des audits...")
        total_audits = 0
        for audit_id in audit_ids:
            result = db.execute(text("""
                DELETE FROM audit
                WHERE id = :audit_id
            """), {'audit_id': audit_id})
            total_audits += result.rowcount
        print(f"      {total_audits} audits supprimés")

    # 5. Supprimer les utilisateurs de campagne
    print("[5/6] Suppression des utilisateurs de campagne...")
    result = db.execute(text("""
        DELETE FROM campaign_user
        WHERE campaign_id = :campaign_id
    """), {'campaign_id': CAMPAIGN_ID})
    print(f"      {result.rowcount} liens utilisateurs supprimés")

    # 6. Supprimer le périmètre
    print("[6/6] Suppression du périmètre de campagne...")
    result = db.execute(text("""
        DELETE FROM campaign_scope
        WHERE campaign_id = :campaign_id
    """), {'campaign_id': CAMPAIGN_ID})
    print(f"      {result.rowcount} entités de périmètre supprimées")

    # 7. Supprimer la campagne
    print("[7/7] Suppression de la campagne...")
    result = db.execute(text("""
        DELETE FROM campaign
        WHERE id = :campaign_id
    """), {'campaign_id': CAMPAIGN_ID})
    print(f"      {result.rowcount} campagne supprimée")

    # Commit
    db.commit()

    print()
    print("=" * 80)
    print("[OK] Campagne et toutes les données associées supprimées avec succès")
    print("=" * 80)

except Exception as e:
    print(f"[ERROR] {e}")
    db.rollback()
    import traceback
    traceback.print_exc()

finally:
    db.close()
