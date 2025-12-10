"""
Script de traduction automatique des questions et options via IA
Utilise DeepSeek pour proposer des traductions en anglais

Usage:
    python scripts/translate_questions_ai.py --questions
    python scripts/translate_questions_ai.py --options
    python scripts/translate_questions_ai.py --all
    python scripts/translate_questions_ai.py --question-id <uuid>
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.config import settings
from src.models import Question, Option
from src.services.question_i18n_service import QuestionI18nService
from src.services.option_service import OptionService
import logging
import json
import argparse
from typing import Dict, List, Optional
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AITranslator:
    """Traducteur utilisant DeepSeek AI"""

    def __init__(self, api_key: str = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model
        self.base_url = "https://api.deepseek.com/v1"

        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY non définie")

    def translate_question(
        self,
        question_text: str,
        help_text: Optional[str] = None,
        context: str = "cybersecurity audit",
        target_language: str = "en"
    ) -> Dict[str, str]:
        """
        Traduit une question et son help_text via IA

        Args:
            question_text: Texte de la question en français
            help_text: Texte d'aide en français (optionnel)
            context: Contexte métier
            target_language: Langue cible (en, es, de, etc.)

        Returns:
            Dict avec question_text et help_text traduits
        """
        language_names = {
            "en": "English",
            "es": "Spanish",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese"
        }

        prompt = f"""You are a professional translator specialized in {context} terminology.

Translate the following French question into {language_names.get(target_language, target_language)}:

FRENCH QUESTION:
{question_text}
"""

        if help_text:
            prompt += f"""
FRENCH HELP TEXT:
{help_text}
"""

        prompt += f"""
INSTRUCTIONS:
- Translate accurately while preserving technical terminology
- Keep the same tone (formal/professional)
- Maintain any acronyms (ISO, GDPR, DPO, etc.)
- Return ONLY valid JSON with this structure:
{{
  "question_text": "translated question",
  "help_text": "translated help text or null"
}}

TRANSLATION:"""

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a professional translator. Always respond with valid JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.3,  # Basse température pour traductions précises
                "max_tokens": 500
            }

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()

            # Extraire le JSON de la réponse
            # Parfois l'IA ajoute du texte autour, on cherche le JSON
            start = content.find('{')
            end = content.rfind('}') + 1
            if start != -1 and end > start:
                json_str = content[start:end]
                translation = json.loads(json_str)
            else:
                raise ValueError("Pas de JSON trouvé dans la réponse")

            logger.info(f"✅ Traduction réussie: {question_text[:50]}... → {translation['question_text'][:50]}...")
            return translation

        except Exception as e:
            logger.error(f"❌ Erreur traduction IA: {e}")
            # Fallback : retourner texte original
            return {
                "question_text": question_text,
                "help_text": help_text
            }

    def translate_option(
        self,
        option_value: str,
        context: str = "cybersecurity audit",
        target_language: str = "en"
    ) -> str:
        """
        Traduit une option via IA

        Args:
            option_value: Valeur de l'option en français
            context: Contexte métier
            target_language: Langue cible

        Returns:
            Valeur traduite
        """
        language_names = {
            "en": "English",
            "es": "Spanish",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese"
        }

        prompt = f"""Translate this single word/phrase from French to {language_names.get(target_language, target_language)}:

"{option_value}"

Context: {context} questionnaire option

Return ONLY the translation, nothing else."""

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a translator. Return only the translated text, no explanation."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.2,
                "max_tokens": 50
            }

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()

            result = response.json()
            translated = result["choices"][0]["message"]["content"].strip()

            # Nettoyer les guillemets si présents
            translated = translated.strip('"').strip("'")

            logger.info(f"✅ Option traduite: {option_value} → {translated}")
            return translated

        except Exception as e:
            logger.error(f"❌ Erreur traduction option: {e}")
            return option_value


def translate_single_question(
    question_id: str,
    target_language: str = "en",
    preview: bool = False
):
    """Traduit une seule question"""
    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        from uuid import UUID
        question = db.query(Question).filter(Question.id == UUID(question_id)).first()

        if not question:
            logger.error(f"❌ Question {question_id} non trouvée")
            return

        logger.info(f"\n{'='*70}")
        logger.info(f"📝 Question ID: {question.id}")
        logger.info(f"   FR: {question.question_text}")
        if question.help_text:
            logger.info(f"   Help FR: {question.help_text[:100]}...")
        logger.info(f"{'='*70}\n")

        # Traduire via IA
        translator = AITranslator()
        translation = translator.translate_question(
            question_text=question.question_text,
            help_text=question.help_text,
            target_language=target_language
        )

        logger.info(f"\n✅ TRADUCTION PROPOSÉE ({target_language.upper()}):")
        logger.info(f"   Question: {translation['question_text']}")
        if translation.get('help_text'):
            logger.info(f"   Help: {translation['help_text'][:100]}...")

        if preview:
            logger.info("\n⏸️ MODE PREVIEW - Traduction non sauvegardée")
            return

        # Demander confirmation
        response = input("\n💾 Sauvegarder cette traduction ? (y/n): ")
        if response.lower() == 'y':
            QuestionI18nService.create_translation(
                db=db,
                question_id=question.id,
                language_code=target_language,
                question_text=translation['question_text'],
                help_text=translation.get('help_text'),
                commit=True
            )
            logger.info(f"✅ Traduction sauvegardée!")
        else:
            logger.info("❌ Traduction annulée")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def translate_all_questions(
    target_language: str = "en",
    auto_save: bool = False,
    limit: Optional[int] = None
):
    """Traduit toutes les questions"""
    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # Récupérer les questions sans traduction dans la langue cible
        query = db.execute(text(f"""
            SELECT q.id, q.question_text, q.help_text
            FROM question q
            LEFT JOIN question_i18n qi ON qi.question_id = q.id
                AND qi.language_code = :lang
            WHERE q.is_active = true
              AND qi.id IS NULL  -- Pas encore traduite
            ORDER BY q.created_at DESC
            {"LIMIT :limit" if limit else ""}
        """), {"lang": target_language, "limit": limit})

        questions = query.fetchall()
        total = len(questions)

        logger.info(f"🔍 {total} questions à traduire en {target_language.upper()}")

        if total == 0:
            logger.info("✅ Toutes les questions sont déjà traduites!")
            return

        translator = AITranslator()
        success_count = 0
        skip_count = 0

        for idx, row in enumerate(questions, 1):
            question_id, question_text, help_text = row

            logger.info(f"\n[{idx}/{total}] 📝 {question_text[:60]}...")

            # Traduire
            translation = translator.translate_question(
                question_text=question_text,
                help_text=help_text,
                target_language=target_language
            )

            logger.info(f"   → {translation['question_text'][:60]}...")

            # Sauvegarder ou demander confirmation
            should_save = auto_save

            if not auto_save:
                response = input(f"   💾 Sauvegarder ? (y/n/a=all): ")
                if response.lower() == 'a':
                    auto_save = True
                    should_save = True
                elif response.lower() == 'y':
                    should_save = True

            if should_save:
                QuestionI18nService.create_translation(
                    db=db,
                    question_id=question_id,
                    language_code=target_language,
                    question_text=translation['question_text'],
                    help_text=translation.get('help_text'),
                    commit=True
                )
                success_count += 1
                logger.info("   ✅ Sauvegardée")
            else:
                skip_count += 1
                logger.info("   ⏭️ Ignorée")

        logger.info(f"\n{'='*70}")
        logger.info(f"✅ RÉSUMÉ")
        logger.info(f"   Total: {total}")
        logger.info(f"   Sauvegardées: {success_count}")
        logger.info(f"   Ignorées: {skip_count}")
        logger.info(f"{'='*70}")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def translate_all_options(
    target_language: str = "en",
    auto_save: bool = False
):
    """Traduit toutes les options système"""
    engine = create_engine(settings.DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        # Récupérer les options système sans traduction
        query = db.execute(text(f"""
            SELECT o.id, o.value_key, o.default_value, o.category
            FROM option o
            LEFT JOIN option_i18n oi ON oi.option_id = o.id
                AND oi.language_code = :lang
            WHERE o.is_system = true
              AND oi.id IS NULL
            ORDER BY o.category, o.default_value
        """), {"lang": target_language})

        options = query.fetchall()
        total = len(options)

        logger.info(f"🔍 {total} options système à traduire en {target_language.upper()}")

        if total == 0:
            logger.info("✅ Toutes les options sont déjà traduites!")
            return

        translator = AITranslator()
        success_count = 0

        for idx, row in enumerate(options, 1):
            option_id, value_key, default_value, category = row

            logger.info(f"\n[{idx}/{total}] 📌 {value_key}: {default_value}")

            # Traduire
            translated_value = translator.translate_option(
                option_value=default_value,
                target_language=target_language
            )

            logger.info(f"   → {translated_value}")

            # Sauvegarder
            should_save = auto_save

            if not auto_save:
                response = input(f"   💾 Sauvegarder ? (y/n/a=all): ")
                if response.lower() == 'a':
                    auto_save = True
                    should_save = True
                elif response.lower() == 'y':
                    should_save = True

            if should_save:
                OptionService.create_translation(
                    db=db,
                    option_id=option_id,
                    language_code=target_language,
                    translated_value=translated_value,
                    commit=True
                )
                success_count += 1
                logger.info("   ✅ Sauvegardée")

        logger.info(f"\n{'='*70}")
        logger.info(f"✅ RÉSUMÉ")
        logger.info(f"   Total: {total}")
        logger.info(f"   Sauvegardées: {success_count}")
        logger.info(f"{'='*70}")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Traduction automatique via IA (DeepSeek)"
    )
    parser.add_argument(
        "--questions",
        action="store_true",
        help="Traduire toutes les questions"
    )
    parser.add_argument(
        "--options",
        action="store_true",
        help="Traduire toutes les options système"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Traduire questions ET options"
    )
    parser.add_argument(
        "--question-id",
        type=str,
        help="Traduire une seule question (UUID)"
    )
    parser.add_argument(
        "--language",
        type=str,
        default="en",
        help="Langue cible (en, es, de, it, pt)"
    )
    parser.add_argument(
        "--auto-save",
        action="store_true",
        help="Sauvegarder automatiquement sans confirmation"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Mode preview (ne sauvegarde pas)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limiter le nombre de questions à traduire"
    )

    args = parser.parse_args()

    # Vérifier que DEEPSEEK_API_KEY est définie
    if not os.getenv("DEEPSEEK_API_KEY"):
        logger.error("❌ DEEPSEEK_API_KEY non définie dans l'environnement")
        logger.info("   Ajouter dans .env: DEEPSEEK_API_KEY=sk-...")
        sys.exit(1)

    logger.info("🚀 Démarrage de la traduction IA")
    logger.info(f"   Langue cible: {args.language.upper()}")
    logger.info(f"   Auto-save: {args.auto_save}")
    logger.info("")

    if args.question_id:
        translate_single_question(
            question_id=args.question_id,
            target_language=args.language,
            preview=args.preview
        )
    elif args.all or args.options:
        logger.info("📌 Traduction des options système...")
        translate_all_options(
            target_language=args.language,
            auto_save=args.auto_save
        )

    if args.all or args.questions:
        logger.info("\n📝 Traduction des questions...")
        translate_all_questions(
            target_language=args.language,
            auto_save=args.auto_save,
            limit=args.limit
        )

    logger.info("\n✅ Script terminé")
