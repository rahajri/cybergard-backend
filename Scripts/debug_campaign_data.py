"""Script pour déboguer les données de la campagne et des audits."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.database import SessionLocal

db = SessionLocal()
try:
    # Trouver le dernier rapport généré
    report = db.execute(text("""
        SELECT
            gr.id,
            gr.title,
            gr.template_id,
            gr.campaign_id,
            gr.entity_id,
            gr.report_scope,
            c.title as campaign_title
        FROM generated_report gr
        LEFT JOIN campaign c ON gr.campaign_id = c.id
        ORDER BY gr.generated_at DESC
        LIMIT 1
    """)).fetchone()

    if not report:
        print("Aucun rapport trouvé")
    else:
        print(f"\n{'='*80}")
        print(f"RAPPORT: {report.title}")
        print(f"Campaign ID: {report.campaign_id}")
        print(f"Entity ID: {report.entity_id}")
        print(f"Scope: {report.report_scope}")
        print(f"{'='*80}")

        campaign_id = str(report.campaign_id)
        entity_id = str(report.entity_id) if report.entity_id else None

        # 1. Vérifier les question_answer pour cette campagne
        qa_count = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN audit_id IS NOT NULL THEN 1 END) as with_audit,
                COUNT(CASE WHEN is_current = true THEN 1 END) as is_current
            FROM question_answer
            WHERE campaign_id = CAST(:campaign_id AS uuid)
        """), {"campaign_id": campaign_id}).fetchone()

        print(f"\n📊 QUESTION_ANSWER pour cette campagne:")
        print(f"   Total: {qa_count.total}")
        print(f"   Avec audit_id: {qa_count.with_audit}")
        print(f"   is_current=true: {qa_count.is_current}")

        # 2. Vérifier les audits liés aux question_answer de cette campagne
        audits = db.execute(text("""
            SELECT
                a.id,
                a.entity_id,
                ee.name as entity_name,
                COUNT(qa.id) as qa_count
            FROM audit a
            LEFT JOIN ecosystem_entity ee ON a.entity_id = ee.id
            LEFT JOIN question_answer qa ON qa.audit_id = a.id AND qa.is_current = true
            WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
            GROUP BY a.id, a.entity_id, ee.name
        """), {"campaign_id": campaign_id}).fetchall()

        print(f"\n📋 AUDITS liés à cette campagne ({len(audits)} trouvés):")
        for a in audits:
            print(f"   - Audit {str(a.id)[:8]}... | Entity: {a.entity_name or 'NULL'} | QA: {a.qa_count}")

        # 3. Si entity_id fourni, vérifier les données pour cette entité
        if entity_id:
            # Vérifier si l'audit existe pour cette entité
            audit_for_entity = db.execute(text("""
                SELECT a.id, COUNT(qa.id) as qa_count
                FROM audit a
                LEFT JOIN question_answer qa ON qa.audit_id = a.id AND qa.is_current = true
                WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                  AND a.entity_id = CAST(:entity_id AS uuid)
                GROUP BY a.id
            """), {"campaign_id": campaign_id, "entity_id": entity_id}).fetchone()

            print(f"\n🔍 AUDIT pour l'entité du rapport ({entity_id[:8]}...):")
            if audit_for_entity:
                print(f"   ✅ Audit trouvé: {str(audit_for_entity.id)[:8]}... avec {audit_for_entity.qa_count} réponses")
            else:
                print(f"   ❌ AUCUN AUDIT trouvé pour cette entité!")

            # Vérifier les réponses directement liées à cette entité via audit
            qa_for_entity = db.execute(text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN qa.answer_value IS NOT NULL THEN 1 END) as answered,
                    COUNT(CASE WHEN qa.compliance_status = 'compliant' THEN 1 END) as compliant,
                    COUNT(CASE WHEN qa.compliance_status LIKE 'non_compliant%' THEN 1 END) as nc
                FROM question_answer qa
                JOIN audit a ON qa.audit_id = a.id
                WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                  AND qa.is_current = true
                  AND a.entity_id = CAST(:entity_id AS uuid)
            """), {"campaign_id": campaign_id, "entity_id": entity_id}).fetchone()

            print(f"\n📈 RÉPONSES pour cette entité (via audit.entity_id):")
            print(f"   Total: {qa_for_entity.total}")
            print(f"   Answered: {qa_for_entity.answered}")
            print(f"   Compliant: {qa_for_entity.compliant}")
            print(f"   NC: {qa_for_entity.nc}")

        # 4. Vérifier la structure des question_answer (colonnes audit_id et entity_id)
        print(f"\n🔧 STRUCTURE question_answer:")
        sample = db.execute(text("""
            SELECT
                qa.id,
                qa.campaign_id,
                qa.audit_id,
                qa.question_id,
                qa.is_current,
                qa.compliance_status,
                LEFT(qa.answer_value::text, 50) as answer_preview
            FROM question_answer qa
            WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
              AND qa.is_current = true
            LIMIT 5
        """), {"campaign_id": campaign_id}).fetchall()

        for s in sample:
            print(f"   QA {str(s.id)[:8]}... | audit_id: {str(s.audit_id)[:8] if s.audit_id else 'NULL'} | status: {s.compliance_status} | answer: {s.answer_preview}")

        # 5. Vérifier les données legacy (compliance_status dérivé de answer_value)
        legacy_check = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN compliance_status IS NOT NULL THEN 1 END) as with_status,
                COUNT(CASE WHEN compliance_status IS NULL AND answer_value IS NOT NULL THEN 1 END) as legacy_needs_derive
            FROM question_answer
            WHERE campaign_id = CAST(:campaign_id AS uuid)
              AND is_current = true
        """), {"campaign_id": campaign_id}).fetchone()

        print(f"\n📊 DONNÉES LEGACY:")
        print(f"   Total réponses: {legacy_check.total}")
        print(f"   Avec compliance_status: {legacy_check.with_status}")
        print(f"   Legacy (status à dériver): {legacy_check.legacy_needs_derive}")

except Exception as e:
    print(f"ERREUR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
