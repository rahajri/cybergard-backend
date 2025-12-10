"""
Script pour lancer le mapping automatique Question → Control Points via IA

Usage:
    python run_ai_mapping.py [--questionnaire-id UUID] [--limit N] [--test]
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Ajouter le chemin du backend au PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.services.question_control_point_mapping_service_v2 import QuestionControlPointMappingServiceV2 as QuestionControlPointMappingService

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Point d'entrée principal"""

    load_dotenv()

    # Configuration
    db_url = os.getenv('DATABASE_URL')
    deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')

    if not db_url:
        raise ValueError("❌ DATABASE_URL non trouvée dans .env")

    if not deepseek_api_key:
        raise ValueError("❌ DEEPSEEK_API_KEY non trouvée dans .env")

    # Arguments
    import argparse
    parser = argparse.ArgumentParser(description="Mapping automatique Question → Control Points via IA")
    parser.add_argument('--questionnaire-id', type=str, help='UUID du questionnaire à traiter (optionnel)')
    parser.add_argument('--limit', type=int, help='Limiter le nombre de questions (pour tests)')
    parser.add_argument('--test', action='store_true', help='Mode test: traiter seulement 5 questions')

    args = parser.parse_args()

    # Mode test
    if args.test:
        args.limit = 5
        logger.info("🧪 MODE TEST: Traitement de 5 questions seulement")

    # Créer la session DB
    engine = create_engine(db_url)
    db = Session(engine)

    try:
        # Créer le service
        service = QuestionControlPointMappingService(db, deepseek_api_key)

        logger.info("=" * 80)
        logger.info("🤖 MAPPING AUTOMATIQUE QUESTION → CONTROL POINTS")
        logger.info("=" * 80)

        if args.questionnaire_id:
            logger.info(f"📋 Questionnaire: {args.questionnaire_id}")

        if args.limit:
            logger.info(f"⚠️  Limite: {args.limit} questions")

        logger.info("")

        # Confirmation
        if not args.test:
            response = input("⚠️  Cette opération va appeler l'API DeepSeek. Continuer ? (oui/non): ")
            if response.lower() != 'oui':
                logger.info("❌ Opération annulée")
                return

        # Lancer le mapping
        stats = await service.map_all_questions(
            questionnaire_id=args.questionnaire_id,
            limit=args.limit
        )

        # Afficher les résultats
        logger.info("\n" + "=" * 80)
        logger.info("📊 RÉSULTATS DU MAPPING")
        logger.info("=" * 80)
        logger.info(f"✅ Questions traitées: {stats['processed']}/{stats['total_questions']}")
        logger.info(f"🔗 Mappings créés: {stats['total_mappings_created']}")
        logger.info(f"📋 Questions avec plusieurs CPs: {stats['questions_with_multiple_cps']}")
        logger.info(f"❌ Erreurs: {stats['errors']}")

        if stats['questions_with_multiple_cps'] > 0:
            ratio = (stats['questions_with_multiple_cps'] / stats['processed'] * 100) if stats['processed'] > 0 else 0
            logger.info(f"📈 Ratio questions multi-CPs: {ratio:.1f}%")

        logger.info("\n✅ Mapping terminé avec succès!")

    except Exception as e:
        logger.error(f"\n❌ Erreur: {e}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
