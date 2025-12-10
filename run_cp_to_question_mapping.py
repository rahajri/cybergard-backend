"""
Script pour lancer le mapping automatique Control Point → Questions via IA

Basé sur le document mapping.md :
- Mappe les nouveaux PCs (non couverts) vers des questions existantes
- Utilise l'IA pour identifier les questions qui couvrent chaque PC
- Ne crée PAS de nouvelles questions, uniquement des liens
- Ne modifie JAMAIS les mappings existants

Usage:
    python run_cp_to_question_mapping.py [--questionnaire-id UUID] [--limit N] [--test]
"""

import asyncio
import os
import sys
import argparse
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Ajouter le chemin du backend au PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.services.control_point_question_mapping_service import ControlPointQuestionMappingService

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
    parser = argparse.ArgumentParser(description="Mapping automatique Control Points → Questions via IA")
    parser.add_argument('--questionnaire-id', type=str, help='UUID du questionnaire à traiter (optionnel)')
    parser.add_argument('--limit', type=int, help='Limiter le nombre de PCs (pour tests)')
    parser.add_argument('--test', action='store_true', help='Mode test: traiter seulement 5 PCs')

    args = parser.parse_args()

    # Mode test
    if args.test:
        args.limit = 5
        logger.info("🧪 MODE TEST: Traitement de 5 PCs seulement")

    # Créer la session DB
    engine = create_engine(db_url)
    db = Session(engine)

    try:
        # Créer le service
        service = ControlPointQuestionMappingService(db, deepseek_api_key)

        logger.info("=" * 80)
        logger.info("🤖 MAPPING AUTOMATIQUE CONTROL POINTS → QUESTIONS")
        logger.info("=" * 80)

        if args.questionnaire_id:
            logger.info(f"📋 Questionnaire: {args.questionnaire_id}")

        if args.limit:
            logger.info(f"⚠️  Limite: {args.limit} PCs")

        logger.info("")

        # Confirmation
        if not args.test:
            response = input("⚠️  Cette opération va appeler l'API DeepSeek. Continuer ? (oui/non): ")
            if response.lower() != 'oui':
                logger.info("❌ Opération annulée")
                return

        # Lancer le mapping
        stats = await service.map_control_points_to_questions(
            questionnaire_id=args.questionnaire_id,
            limit=args.limit
        )

        # Afficher les résultats
        logger.info("\n" + "=" * 80)
        logger.info("📊 RÉSULTATS DU MAPPING")
        logger.info("=" * 80)
        logger.info(f"✅ Questionnaires analysés: {stats['questionnaires_analyzed']}")
        logger.info(f"🔗 Nouveaux mappings créés: {stats['total_mappings_created']}")
        logger.info(f"📋 PCs restant non couverts: {stats['total_pcs_uncovered']}")
        logger.info(f"🤖 Appels IA: {stats['ai_calls']}")
        logger.info(f"❌ Erreurs: {stats['errors']}")

        if stats['total_mappings_created'] > 0:
            ratio = (stats['total_mappings_created'] / (stats['total_mappings_created'] + stats['total_pcs_uncovered'])) * 100
            logger.info(f"📈 Taux de couverture: {ratio:.1f}%")

        logger.info("\n✅ Mapping terminé avec succès!")

    except Exception as e:
        logger.error(f"\n❌ Erreur: {e}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
