"""
Script de migration vers l'architecture avec options réutilisables

Ce script :
1. Crée les tables option et option_i18n
2. Insère les options système de base
3. Modifie la table question_option pour ajouter option_id et custom_value
4. Migre les données existantes de option_value vers option_id/custom_value
5. Supprime la colonne option_value

Usage:
    python scripts/migrate_to_reusable_options.py
"""
import sys
import os
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.config import settings
from src.services.option_service import OptionService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_to_reusable_options():
    """Migre vers l'architecture avec options réutilisables"""

    # Créer la connexion
    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        logger.info("🚀 Démarrage de la migration vers options réutilisables")
        logger.info("=" * 70)

        # ==============================================================================
        # ÉTAPE 1 : Créer la table option
        # ==============================================================================
        logger.info("\n📋 ÉTAPE 1/7 : Création de la table 'option'...")

        db.execute(text("""
            CREATE TABLE IF NOT EXISTS option (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                value_key VARCHAR(100) UNIQUE NOT NULL,
                default_value VARCHAR(255) NOT NULL,
                category VARCHAR(50),
                is_system BOOLEAN DEFAULT false,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """))

        db.execute(text("CREATE INDEX IF NOT EXISTS idx_option_value_key ON option(value_key);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_option_default_value ON option(default_value);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_option_category ON option(category);"))

        db.commit()
        logger.info("✅ Table 'option' créée")

        # ==============================================================================
        # ÉTAPE 2 : Créer la table option_i18n
        # ==============================================================================
        logger.info("\n📋 ÉTAPE 2/7 : Création de la table 'option_i18n'...")

        db.execute(text("""
            CREATE TABLE IF NOT EXISTS option_i18n (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                option_id UUID NOT NULL REFERENCES option(id) ON DELETE CASCADE,
                language_code VARCHAR(5) NOT NULL,
                translated_value VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(option_id, language_code)
            );
        """))

        db.execute(text("CREATE INDEX IF NOT EXISTS idx_option_i18n_option_id ON option_i18n(option_id);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_option_i18n_lang ON option_i18n(language_code);"))

        db.commit()
        logger.info("✅ Table 'option_i18n' créée")

        # ==============================================================================
        # ÉTAPE 3 : Insérer les options système
        # ==============================================================================
        logger.info("\n📋 ÉTAPE 3/7 : Insertion des options système...")

        created_options = OptionService.create_system_options(db, commit=True)
        logger.info(f"✅ {len(created_options)} options système créées")

        # ==============================================================================
        # ÉTAPE 4 : Modifier la table question_option
        # ==============================================================================
        logger.info("\n📋 ÉTAPE 4/7 : Modification de la table 'question_option'...")

        # Vérifier si option_value existe
        result = db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'question_option' AND column_name = 'option_value'
        """))
        has_option_value = result.fetchone() is not None

        if not has_option_value:
            logger.info("⚠️ Colonne 'option_value' n'existe pas - skip migration données")
            # Ajouter directement les nouvelles colonnes
            db.execute(text("""
                ALTER TABLE question_option
                ADD COLUMN IF NOT EXISTS option_id UUID REFERENCES option(id) ON DELETE CASCADE,
                ADD COLUMN IF NOT EXISTS custom_value VARCHAR(255);
            """))
        else:
            # Ajouter les nouvelles colonnes
            db.execute(text("""
                ALTER TABLE question_option
                ADD COLUMN IF NOT EXISTS option_id UUID REFERENCES option(id) ON DELETE CASCADE,
                ADD COLUMN IF NOT EXISTS custom_value VARCHAR(255);
            """))

        db.execute(text("CREATE INDEX IF NOT EXISTS idx_question_option_option_id ON question_option(option_id);"))
        db.commit()
        logger.info("✅ Colonnes 'option_id' et 'custom_value' ajoutées")

        # ==============================================================================
        # ÉTAPE 5 : Migrer les données existantes
        # ==============================================================================
        if has_option_value:
            logger.info("\n📋 ÉTAPE 5/7 : Migration des données existantes...")

            # Récupérer toutes les question_option avec option_value
            result = db.execute(text("""
                SELECT id, option_value
                FROM question_option
                WHERE option_value IS NOT NULL
                  AND option_value != ''
                  AND option_id IS NULL
                  AND custom_value IS NULL
            """))

            rows = result.fetchall()
            logger.info(f"📊 Trouvé {len(rows)} lignes à migrer")

            migrated_reusable = 0
            migrated_custom = 0
            errors = 0

            for row in rows:
                qo_id = row[0]
                option_value = row[1]

                try:
                    # Chercher si l'option existe dans la table option
                    existing_option = db.execute(text("""
                        SELECT id FROM option WHERE default_value ILIKE :value LIMIT 1
                    """), {"value": option_value}).fetchone()

                    if existing_option:
                        # Option réutilisable trouvée
                        db.execute(text("""
                            UPDATE question_option
                            SET option_id = :option_id
                            WHERE id = :qo_id
                        """), {"option_id": existing_option[0], "qo_id": qo_id})
                        migrated_reusable += 1
                    else:
                        # Option custom
                        db.execute(text("""
                            UPDATE question_option
                            SET custom_value = :value
                            WHERE id = :qo_id
                        """), {"value": option_value, "qo_id": qo_id})
                        migrated_custom += 1

                except Exception as e:
                    logger.error(f"❌ Erreur migration de {qo_id}: {e}")
                    errors += 1

            db.commit()
            logger.info(f"✅ Migration terminée:")
            logger.info(f"   - Options réutilisables: {migrated_reusable}")
            logger.info(f"   - Options custom: {migrated_custom}")
            logger.info(f"   - Erreurs: {errors}")

        else:
            logger.info("\n⏭️ ÉTAPE 5/7 : Skip migration (pas de colonne option_value)")

        # ==============================================================================
        # ÉTAPE 6 : Ajouter la contrainte CHECK
        # ==============================================================================
        logger.info("\n📋 ÉTAPE 6/7 : Ajout de la contrainte CHECK...")

        # Supprimer si existe
        db.execute(text("""
            ALTER TABLE question_option
            DROP CONSTRAINT IF EXISTS chk_option_or_custom;
        """))

        # Ajouter la contrainte
        db.execute(text("""
            ALTER TABLE question_option
            ADD CONSTRAINT chk_option_or_custom
            CHECK (
                (option_id IS NOT NULL AND custom_value IS NULL) OR
                (option_id IS NULL AND custom_value IS NOT NULL)
            );
        """))

        db.commit()
        logger.info("✅ Contrainte CHECK ajoutée")

        # ==============================================================================
        # ÉTAPE 7 : Supprimer l'ancienne colonne option_value
        # ==============================================================================
        if has_option_value:
            logger.info("\n📋 ÉTAPE 7/7 : Suppression de la colonne 'option_value'...")

            db.execute(text("ALTER TABLE question_option DROP COLUMN IF EXISTS option_value;"))
            db.commit()
            logger.info("✅ Colonne 'option_value' supprimée")
        else:
            logger.info("\n⏭️ ÉTAPE 7/7 : Skip suppression (colonne n'existe pas)")

        # ==============================================================================
        # VÉRIFICATIONS FINALES
        # ==============================================================================
        logger.info("\n" + "=" * 70)
        logger.info("🔍 VÉRIFICATIONS FINALES")
        logger.info("=" * 70)

        # Compter les options dans la table option
        count_options = db.execute(text("SELECT COUNT(*) FROM option;")).scalar()
        logger.info(f"✅ Options dans table 'option': {count_options}")

        # Compter les question_option avec option_id
        count_reusable = db.execute(text("""
            SELECT COUNT(*) FROM question_option WHERE option_id IS NOT NULL;
        """)).scalar()
        logger.info(f"✅ QuestionOption avec option réutilisable: {count_reusable}")

        # Compter les question_option avec custom_value
        count_custom = db.execute(text("""
            SELECT COUNT(*) FROM question_option WHERE custom_value IS NOT NULL;
        """)).scalar()
        logger.info(f"✅ QuestionOption avec option custom: {count_custom}")

        # Compter les question_option invalides (ni l'un ni l'autre)
        count_invalid = db.execute(text("""
            SELECT COUNT(*) FROM question_option
            WHERE option_id IS NULL AND custom_value IS NULL;
        """)).scalar()

        if count_invalid > 0:
            logger.warning(f"⚠️ {count_invalid} QuestionOption sans option (invalide!)")
        else:
            logger.info(f"✅ Aucune QuestionOption invalide")

        logger.info("=" * 70)
        logger.info("✅ Migration terminée avec succès!")
        logger.info("=" * 70)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la migration: {e}")
        import traceback
        traceback.print_exc()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    migrate_to_reusable_options()
    logger.info("\n✅ Script terminé")
