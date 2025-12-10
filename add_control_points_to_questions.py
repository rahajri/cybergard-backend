"""
Script pour ajouter des control points supplémentaires aux questions

Usage:
    python add_control_points_to_questions.py
"""

from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_control_points():
    """
    Ajouter des control points supplémentaires aux questions

    Modifiez les exemples ci-dessous selon vos besoins
    """

    load_dotenv()
    db_url = os.getenv('DATABASE_URL')

    if not db_url:
        raise ValueError("DATABASE_URL non trouvée dans .env")

    engine = create_engine(db_url)

    with engine.begin() as conn:
        logger.info("📝 Ajout de control points supplémentaires...")

        # EXEMPLE 1: Ajouter un control point spécifique à UNE question
        # Décommentez et modifiez selon vos besoins
        """
        conn.execute(text('''
            INSERT INTO question_control_point (question_id, control_point_id)
            VALUES (
                CAST(:question_id AS uuid),
                CAST(:control_point_id AS uuid)
            )
            ON CONFLICT (question_id, control_point_id) DO NOTHING
        '''), {
            'question_id': 'UUID-DE-LA-QUESTION',
            'control_point_id': 'UUID-DU-CONTROL-POINT'
        })
        logger.info("✅ Control point ajouté à la question")
        """

        # EXEMPLE 2: Ajouter le même control point à PLUSIEURS questions
        # Décommentez et modifiez selon vos besoins
        """
        question_ids = [
            'uuid-question-1',
            'uuid-question-2',
            'uuid-question-3'
        ]
        control_point_id = 'uuid-control-point'

        for qid in question_ids:
            conn.execute(text('''
                INSERT INTO question_control_point (question_id, control_point_id)
                VALUES (
                    CAST(:question_id AS uuid),
                    CAST(:control_point_id AS uuid)
                )
                ON CONFLICT (question_id, control_point_id) DO NOTHING
            '''), {
                'question_id': qid,
                'control_point_id': control_point_id
            })

        logger.info(f"✅ Control point ajouté à {len(question_ids)} questions")
        """

        # EXEMPLE 3: Ajouter tous les control points d'un référentiel à certaines questions
        # Décommentez et modifiez selon vos besoins
        """
        conn.execute(text('''
            INSERT INTO question_control_point (question_id, control_point_id)
            SELECT
                q.id as question_id,
                cp.id as control_point_id
            FROM question q
            CROSS JOIN control_point cp
            WHERE q.questionnaire_id = CAST(:questionnaire_id AS uuid)
              AND cp.referential_id = CAST(:referential_id AS uuid)
              AND q.question_text ILIKE :pattern
            ON CONFLICT (question_id, control_point_id) DO NOTHING
        '''), {
            'questionnaire_id': 'uuid-questionnaire',
            'referential_id': 'uuid-referential',
            'pattern': '%mot-clé%'  # Ex: '%sécurité%'
        })

        logger.info("✅ Control points ajoutés aux questions matchant le pattern")
        """

        # Afficher le nombre total de liens
        result = conn.execute(text("""
            SELECT COUNT(*) FROM question_control_point
        """)).fetchone()

        logger.info(f"\n📊 Total liens dans question_control_point: {result[0]}")

        # Afficher les questions avec plusieurs control points
        result2 = conn.execute(text("""
            SELECT
                q.id,
                q.question_text,
                COUNT(qcp.control_point_id) as nb_control_points
            FROM question q
            JOIN question_control_point qcp ON q.id = qcp.question_id
            GROUP BY q.id, q.question_text
            HAVING COUNT(qcp.control_point_id) > 1
            ORDER BY nb_control_points DESC
            LIMIT 10
        """)).fetchall()

        if result2:
            logger.info(f"\n📋 Questions avec plusieurs control points:")
            for row in result2:
                logger.info(f"   {row[1][:60]}... → {row[2]} control points")
        else:
            logger.info("\n⚠️  Aucune question n'a plusieurs control points pour le moment")
            logger.info("   Décommentez et modifiez les exemples ci-dessus pour en ajouter")

if __name__ == "__main__":
    try:
        add_control_points()
        logger.info("\n✅ Terminé!")
    except Exception as e:
        logger.error(f"\n❌ Erreur: {e}", exc_info=True)
        raise
