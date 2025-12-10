from sqlalchemy import text
from src.database import SessionLocal

def find_choice_questions():
    """Trouve les questions à choix multiples dans la campagne"""
    db = SessionLocal()
    try:
        # D'abord voir tous les types de questions
        types_query = text("""
            SELECT
                q.response_type,
                COUNT(*) as cnt
            FROM question q
            JOIN questionnaire qn ON q.questionnaire_id = qn.id
            JOIN campaign c ON c.questionnaire_id = qn.id
            WHERE c.id = '7cbe1915-37cf-478c-ab40-bd63a319f0b2'
            GROUP BY q.response_type
        """)
        types_result = db.execute(types_query)
        print("Types de questions dans la campagne:")
        for row in types_result.fetchall():
            print(f"  {row.response_type}: {row.cnt}")
        print('='*80)

        query = text("""
            SELECT
                q.id,
                q.question_text,
                q.response_type
            FROM question q
            JOIN questionnaire qn ON q.questionnaire_id = qn.id
            JOIN campaign c ON c.questionnaire_id = qn.id
            WHERE c.id = '7cbe1915-37cf-478c-ab40-bd63a319f0b2'
            AND q.response_type ILIKE '%choice%'
            LIMIT 5
        """)
        result = db.execute(query)
        rows = result.fetchall()

        print(f'Questions a choix multiples trouvees: {len(rows)}')
        print('='*80)

        for row in rows:
            q_text = str(row.question_text) if row.question_text else 'N/A'
            print(f'ID: {row.id}')
            print(f'Question: {q_text[:80]}...' if len(q_text) > 80 else f'Question: {q_text}')
            print(f'Type: {row.response_type}')
            print('-'*40)
    finally:
        db.close()

def check_answers():
    db = SessionLocal()
    try:
        query = text("""
            SELECT
                qa.id,
                qa.compliance_status,
                qa.answer_value,
                qa.answered_at,
                q.question_text,
                q.response_type
            FROM question_answer qa
            JOIN question q ON qa.question_id = q.id
            WHERE qa.campaign_id = '7cbe1915-37cf-478c-ab40-bd63a319f0b2'
            ORDER BY qa.answered_at DESC
            LIMIT 20
        """)
        result = db.execute(query)
        rows = result.fetchall()

        print(f'Nombre de reponses trouvees: {len(rows)}')
        print('='*80)

        for row in rows:
            q_text = str(row.question_text) if row.question_text else 'N/A'
            print(f'Question: {q_text[:70]}...' if len(q_text) > 70 else f'Question: {q_text}')
            print(f'  response_type: {row.response_type}')
            print(f'  compliance_status: {row.compliance_status}')
            print(f'  answer_value: {row.answer_value}')
            print(f'  answered_at: {row.answered_at}')
            print('-'*40)
    finally:
        db.close()

def find_frozen_campaigns():
    """Trouve les campagnes gelées"""
    db = SessionLocal()
    try:
        query = text("""
            SELECT c.id, c.title, c.status,
                   COUNT(qa.id) as answer_count
            FROM campaign c
            LEFT JOIN question_answer qa ON qa.campaign_id = c.id
            WHERE c.status = 'frozen'
            GROUP BY c.id, c.title, c.status
        """)
        result = db.execute(query)
        rows = result.fetchall()

        print(f'Campagnes gelees: {len(rows)}')
        print('='*80)

        for row in rows:
            print(f'ID: {row.id}')
            print(f'Titre: {row.title}')
            print(f'Status: {row.status}')
            print(f'Reponses: {row.answer_count}')
            print('-'*40)
    finally:
        db.close()

def check_frozen_answers(campaign_id):
    """Verifie les reponses d'une campagne gelee"""
    db = SessionLocal()
    try:
        query = text("""
            SELECT
                qa.id,
                qa.compliance_status,
                qa.answer_value,
                q.question_text,
                q.response_type
            FROM question_answer qa
            JOIN question q ON qa.question_id = q.id
            WHERE qa.campaign_id = :campaign_id
            AND qa.is_current = true
            ORDER BY qa.answered_at DESC
        """)
        result = db.execute(query, {"campaign_id": campaign_id})
        rows = result.fetchall()

        print(f'Reponses dans la campagne: {len(rows)}')
        print('='*80)

        for row in rows:
            q_text = str(row.question_text)[:50] if row.question_text else 'N/A'
            print(f'ID: {row.id}')
            print(f'Question: {q_text}...')
            print(f'Type: {row.response_type}')
            print(f'compliance_status: {row.compliance_status}')
            print(f'answer_value: {row.answer_value}')
            print('-'*40)
    finally:
        db.close()

def check_report_jobs():
    """Vérifie les jobs de génération de rapports"""
    db = SessionLocal()
    try:
        query = text("""
            SELECT
                rj.id,
                rj.status,
                rj.current_step,
                rj.progress_percent,
                rj.error_message,
                gr.created_at,
                gr.title as report_title,
                gr.status as report_status,
                c.title as campaign_title
            FROM report_generation_job rj
            JOIN generated_report gr ON rj.report_id = gr.id
            JOIN campaign c ON gr.campaign_id = c.id
            ORDER BY gr.created_at DESC
            LIMIT 10
        """)
        result = db.execute(query)
        rows = result.fetchall()

        print(f'Jobs de generation: {len(rows)}')
        print('='*80)

        for row in rows:
            print(f'Job ID: {row.id}')
            print(f'  Status: {row.status}')
            print(f'  Step: {row.current_step}')
            print(f'  Progress: {row.progress_percent}%')
            print(f'  Report: {row.report_title} ({row.report_status})')
            print(f'  Campaign: {row.campaign_title}')
            if row.error_message:
                print(f'  ERROR: {row.error_message[:100]}...')
            print('-'*40)
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'find':
        find_choice_questions()
    elif len(sys.argv) > 1 and sys.argv[1] == 'frozen':
        find_frozen_campaigns()
    elif len(sys.argv) > 2 and sys.argv[1] == 'check':
        check_frozen_answers(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == 'jobs':
        check_report_jobs()
    else:
        check_answers()
