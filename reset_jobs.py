"""
Script pour réinitialiser les jobs de rapport bloqués.
"""
from sqlalchemy import text
from src.database import SessionLocal

def reset_stuck_jobs():
    db = SessionLocal()
    try:
        # Réinitialiser les jobs en processing ou queued
        print("Réinitialisation des jobs bloqués...")

        result = db.execute(text("""
            UPDATE report_generation_job
            SET status = 'queued',
                current_step = NULL,
                current_step_number = 0,
                progress_percent = 0,
                error_message = NULL,
                started_at = NULL,
                completed_at = NULL
            WHERE status IN ('processing', 'queued')
            RETURNING id, status
        """))

        updated = result.fetchall()
        db.commit()

        print(f"Jobs réinitialisés: {len(updated)}")
        for row in updated:
            print(f"  - {row.id}")

        # Vérifier l'état final
        result = db.execute(text("""
            SELECT rj.id, rj.status, gr.title
            FROM report_generation_job rj
            JOIN generated_report gr ON rj.report_id = gr.id
            ORDER BY gr.created_at DESC
            LIMIT 5
        """))

        print("\nÉtat actuel des jobs:")
        for row in result.fetchall():
            print(f"  {row.title}: {row.status}")

    finally:
        db.close()

if __name__ == "__main__":
    reset_stuck_jobs()
