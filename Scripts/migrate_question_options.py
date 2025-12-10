"""
Script de migration pour transférer les options de questions
depuis le champ JSON 'options' vers la table 'question_option'.

Usage:
    python scripts/migrate_question_options.py
"""
import sys
import os
import json
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.config import settings
from src.models import QuestionOption
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_options():
    """Migre les options depuis le champ JSON vers question_option"""

    # Créer la connexion
    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # 1. Vérifier si la colonne 'options' existe dans la table question
        result = db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'question' AND column_name = 'options'
        """))

        has_options_column = result.fetchone() is not None

        if not has_options_column:
            logger.info("✅ Colonne 'options' n'existe pas dans la table question")
            logger.info("ℹ️ Rien à migrer - la table question_option est prête à être utilisée")
            return

        # 2. Récupérer toutes les questions avec des options
        logger.info("🔍 Recherche des questions avec options...")

        result = db.execute(text("""
            SELECT id, question_text, response_type, options
            FROM question
            WHERE options IS NOT NULL
              AND options != ''
              AND options != 'null'
              AND response_type IN ('single_choice', 'multiple_choice')
        """))

        questions_with_options = result.fetchall()
        logger.info(f"📊 Trouvé {len(questions_with_options)} questions avec options")

        # 3. Migrer chaque question
        migrated_count = 0
        error_count = 0

        for row in questions_with_options:
            question_id = row[0]
            question_text = row[1]
            response_type = row[2]
            options_json = row[3]

            try:
                # Parser le JSON des options
                if isinstance(options_json, str):
                    options = json.loads(options_json)
                else:
                    options = options_json

                if not isinstance(options, list):
                    logger.warning(f"⚠️ Options invalides pour question {question_id}: {options}")
                    error_count += 1
                    continue

                # Vérifier si des options existent déjà pour cette question
                existing = db.execute(text("""
                    SELECT COUNT(*) FROM question_option WHERE question_id = :qid
                """), {"qid": question_id}).scalar()

                if existing > 0:
                    logger.info(f"⏭️ Question {question_id} a déjà {existing} options - ignorée")
                    continue

                # Créer les options dans question_option
                for idx, option_value in enumerate(options):
                    if not option_value or not str(option_value).strip():
                        continue

                    db.execute(text("""
                        INSERT INTO question_option (id, question_id, option_value, sort_order, is_active)
                        VALUES (gen_random_uuid(), :qid, :value, :order, true)
                    """), {
                        "qid": question_id,
                        "value": str(option_value).strip(),
                        "order": idx
                    })

                migrated_count += 1
                logger.info(f"✅ Question {question_id} migrée ({len(options)} options)")

            except json.JSONDecodeError as e:
                logger.error(f"❌ Erreur JSON pour question {question_id}: {e}")
                error_count += 1
            except Exception as e:
                logger.error(f"❌ Erreur pour question {question_id}: {e}")
                error_count += 1

        # 4. Commit
        db.commit()

        # 5. Résumé
        logger.info("=" * 70)
        logger.info(f"✅ Migration terminée:")
        logger.info(f"   - Questions migrées: {migrated_count}")
        logger.info(f"   - Erreurs: {error_count}")
        logger.info(f"   - Total traité: {len(questions_with_options)}")
        logger.info("=" * 70)

        # 6. (Optionnel) Supprimer la colonne 'options' de la table question
        logger.info("")
        logger.info("⚠️ ATTENTION: Pour supprimer définitivement la colonne 'options', exécutez:")
        logger.info("   ALTER TABLE question DROP COLUMN IF EXISTS options;")
        logger.info("")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la migration: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("🚀 Démarrage de la migration des options de questions")
    migrate_options()
    logger.info("✅ Script terminé")
