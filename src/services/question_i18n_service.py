"""
Service pour gérer les traductions des questions (QuestionI18n)
"""
from typing import List, Optional, Dict
from uuid import UUID
from sqlalchemy.orm import Session
import logging

from src.models.question_i18n import QuestionI18n

logger = logging.getLogger(__name__)


class QuestionI18nService:
    """Service pour gérer les traductions des questions"""

    @staticmethod
    def create_translation(
        db: Session,
        question_id: UUID,
        language_code: str,
        question_text: str,
        help_text: Optional[str] = None,
        commit: bool = False
    ) -> QuestionI18n:
        """
        Crée une traduction pour une question.

        Args:
            db: Session de base de données
            question_id: ID de la question
            language_code: Code langue (ex: 'fr', 'en', 'es')
            question_text: Texte de la question traduit
            help_text: Texte d'aide traduit (optionnel)
            commit: Si True, commit immédiatement

        Returns:
            QuestionI18n créé ou mis à jour
        """
        # Vérifier si traduction existe déjà
        existing = db.query(QuestionI18n).filter(
            QuestionI18n.question_id == question_id,
            QuestionI18n.language_code == language_code
        ).first()

        if existing:
            # Mettre à jour
            existing.question_text = question_text
            if help_text is not None:
                existing.help_text = help_text
            translation = existing
            logger.info(f"✅ [QUESTION_I18N] Traduction mise à jour: {question_id} ({language_code})")
        else:
            # Créer
            translation = QuestionI18n(
                question_id=question_id,
                language_code=language_code,
                question_text=question_text,
                help_text=help_text
            )
            db.add(translation)
            logger.info(f"✅ [QUESTION_I18N] Traduction créée: {question_id} ({language_code})")

        if commit:
            db.commit()
            db.refresh(translation)
        else:
            db.flush()

        return translation

    @staticmethod
    def get_translation(
        db: Session,
        question_id: UUID,
        language_code: str
    ) -> Optional[QuestionI18n]:
        """
        Récupère la traduction d'une question pour une langue.

        Args:
            db: Session de base de données
            question_id: ID de la question
            language_code: Code langue

        Returns:
            QuestionI18n ou None si non trouvée
        """
        return db.query(QuestionI18n).filter(
            QuestionI18n.question_id == question_id,
            QuestionI18n.language_code == language_code
        ).first()

    @staticmethod
    def get_all_translations(
        db: Session,
        question_id: UUID
    ) -> List[QuestionI18n]:
        """
        Récupère toutes les traductions d'une question.

        Args:
            db: Session de base de données
            question_id: ID de la question

        Returns:
            Liste des QuestionI18n
        """
        return db.query(QuestionI18n).filter(
            QuestionI18n.question_id == question_id
        ).all()

    @staticmethod
    def delete_translation(
        db: Session,
        question_id: UUID,
        language_code: str,
        commit: bool = False
    ) -> bool:
        """
        Supprime une traduction.

        Args:
            db: Session de base de données
            question_id: ID de la question
            language_code: Code langue
            commit: Si True, commit immédiatement

        Returns:
            True si supprimée, False sinon
        """
        deleted = db.query(QuestionI18n).filter(
            QuestionI18n.question_id == question_id,
            QuestionI18n.language_code == language_code
        ).delete()

        if commit:
            db.commit()
        else:
            db.flush()

        if deleted:
            logger.info(f"🗑️ [QUESTION_I18N] Traduction supprimée: {question_id} ({language_code})")
            return True
        else:
            logger.warning(f"⚠️ [QUESTION_I18N] Traduction non trouvée: {question_id} ({language_code})")
            return False

    @staticmethod
    def get_question_text(
        db: Session,
        question_id: UUID,
        language_code: str,
        fallback_text: Optional[str] = None
    ) -> str:
        """
        Récupère le texte traduit d'une question avec fallback.

        Args:
            db: Session de base de données
            question_id: ID de la question
            language_code: Code langue demandée
            fallback_text: Texte de fallback si traduction non trouvée

        Returns:
            Texte traduit ou fallback
        """
        translation = QuestionI18nService.get_translation(db, question_id, language_code)

        if translation:
            return translation.question_text
        else:
            logger.debug(f"[QUESTION_I18N] Pas de traduction {language_code} pour question {question_id} - fallback utilisé")
            return fallback_text or ""

    @staticmethod
    def create_translations_batch(
        db: Session,
        question_id: UUID,
        translations: Dict[str, Dict[str, str]],
        commit: bool = False
    ) -> List[QuestionI18n]:
        """
        Crée plusieurs traductions pour une question en une fois.

        Args:
            db: Session de base de données
            question_id: ID de la question
            translations: Dict avec structure:
                {
                    "en": {"question_text": "...", "help_text": "..."},
                    "es": {"question_text": "...", "help_text": "..."},
                }
            commit: Si True, commit immédiatement

        Returns:
            Liste des QuestionI18n créés
        """
        created = []

        for lang_code, texts in translations.items():
            translation = QuestionI18nService.create_translation(
                db=db,
                question_id=question_id,
                language_code=lang_code,
                question_text=texts.get("question_text", ""),
                help_text=texts.get("help_text"),
                commit=False  # On commit à la fin
            )
            created.append(translation)

        if commit:
            db.commit()

        logger.info(f"✅ [QUESTION_I18N] {len(created)} traductions créées pour question {question_id}")
        return created
