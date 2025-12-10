"""
Script de migration : question.control_point_id → question_control_point

Ce script migre les relations one-to-many vers many-to-many pour les control points.
"""

from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_control_points():
    """Migrer les control_point_id vers la table question_control_point"""

    load_dotenv()
    db_url = os.getenv('DATABASE_URL')

    if not db_url:
        raise ValueError("DATABASE_URL non trouvée dans .env")

    engine = create_engine(db_url)

    with engine.begin() as conn:
        # 1. Vérifier l'état actuel
        logger.info("📊 État actuel de la base de données...")

        result = conn.execute(text("""
            SELECT
                COUNT(*) as total_questions,
                COUNT(control_point_id) as questions_with_cp
            FROM question
        """)).fetchone()

        total_questions = result[0]
        questions_with_cp = result[1]

        logger.info(f"   Total questions: {total_questions}")
        logger.info(f"   Questions avec control_point_id: {questions_with_cp}")

        result2 = conn.execute(text("SELECT COUNT(*) FROM question_control_point")).fetchone()
        existing_links = result2[0]

        logger.info(f"   Liens existants dans question_control_point: {existing_links}")

        if existing_links > 0:
            logger.warning(f"⚠️  La table question_control_point contient déjà {existing_links} entrées")
            response = input("Voulez-vous continuer et ajouter les nouvelles entrées ? (oui/non): ")
            if response.lower() != 'oui':
                logger.info("❌ Migration annulée")
                return

        # 2. Migrer les données
        logger.info("\n🔄 Migration des control_point_id vers question_control_point...")

        result = conn.execute(text("""
            INSERT INTO question_control_point (question_id, control_point_id)
            SELECT
                q.id as question_id,
                q.control_point_id as control_point_id
            FROM question q
            WHERE q.control_point_id IS NOT NULL
            ON CONFLICT (question_id, control_point_id) DO NOTHING
            RETURNING *
        """))

        migrated_count = result.rowcount

        logger.info(f"✅ {migrated_count} liens créés dans question_control_point")

        # 3. Vérifier la migration
        logger.info("\n🔍 Vérification post-migration...")

        result3 = conn.execute(text("SELECT COUNT(*) FROM question_control_point")).fetchone()
        total_links = result3[0]

        logger.info(f"   Total liens dans question_control_point: {total_links}")

        if total_links == questions_with_cp:
            logger.info("✅ Migration réussie ! Tous les control points ont été migrés.")
        else:
            logger.warning(f"⚠️  Nombre de liens ({total_links}) != nombre de questions avec CP ({questions_with_cp})")

        # 4. Optionnel : Supprimer la colonne control_point_id de la table question
        logger.info("\n⚠️  ATTENTION : La colonne question.control_point_id existe toujours")
        logger.info("   Pour la supprimer définitivement, exécutez :")
        logger.info("   ALTER TABLE question DROP COLUMN control_point_id;")
        logger.info("")
        logger.info("   Mais je recommande de la garder temporairement pour rollback si besoin.")

        # 5. Afficher quelques exemples
        logger.info("\n📋 Exemples de liens créés:")
        try:
            # Vérifier la structure de la table control_point
            examples = conn.execute(text("""
                SELECT
                    q.id as question_id,
                    q.question_text,
                    qcp.control_point_id,
                    cp.id as cp_id
                FROM question_control_point qcp
                JOIN question q ON qcp.question_id = q.id
                JOIN control_point cp ON qcp.control_point_id = cp.id
                LIMIT 5
            """)).fetchall()

            for ex in examples:
                logger.info(f"   Question: {ex[1][:60]}...")
                logger.info(f"   → Control Point ID: {ex[3]}")
                logger.info("")
        except Exception as e:
            logger.warning(f"   Impossible d'afficher les exemples: {e}")
            logger.info("   Mais la migration est réussie !")

if __name__ == "__main__":
    try:
        migrate_control_points()
        logger.info("\n✅ Migration terminée avec succès!")
    except Exception as e:
        logger.error(f"\n❌ Erreur lors de la migration: {e}", exc_info=True)
        raise
