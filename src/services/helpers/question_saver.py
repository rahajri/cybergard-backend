"""
Helper pour sauvegarder les questions avec leurs options
"""
from typing import Dict, Any, List
from uuid import UUID
from sqlalchemy.orm import Session
import logging

from src.models import Question
from src.services.question_option_service import QuestionOptionService

logger = logging.getLogger(__name__)


def save_question_with_options(
    db: Session,
    question_data: Dict[str, Any],
    commit: bool = False
) -> Question:
    """
    Sauvegarde une question ET ses options dans question_option.

    Args:
        db: Session de base de données
        question_data: Dictionnaire contenant les données de la question
        commit: Si True, commit la transaction

    Returns:
        Question créée

    Example:
        question_data = {
            "questionnaire_id": uuid,
            "question_text": "Quelle est...",
            "response_type": "single_choice",
            "options": ["Oui", "Non", "NSP"],  # <- Géré séparément
            "help_text": "...",
            ...
        }
    """
    # Extraire les options du dict (pour ne pas les passer au modèle Question)
    options = question_data.pop("options", None)

    # Créer la question (sans options)
    question = Question(**question_data)
    db.add(question)
    db.flush()  # Pour obtenir l'ID de la question

    # Créer les options dans question_option si nécessaire
    if options and isinstance(options, list) and len(options) > 0:
        # Vérifier que le type nécessite des options
        if question.response_type in ["single_choice", "multiple_choice"]:
            QuestionOptionService.create_options_for_question(
                db=db,
                question_id=question.id,
                options=options,
                replace_existing=True
            )
            logger.info(f"✅ [QUESTION_SAVER] Question {question.id} créée avec {len(options)} options")
        else:
            logger.warning(f"⚠️ [QUESTION_SAVER] Options fournies pour type '{question.response_type}' qui ne les nécessite pas (ignorées)")
    elif question.response_type in ["single_choice", "multiple_choice"]:
        logger.warning(f"⚠️ [QUESTION_SAVER] Question de type '{question.response_type}' sans options!")

    if commit:
        db.commit()
        db.refresh(question)

    return question


def save_questions_batch(
    db: Session,
    questions_data: List[Dict[str, Any]],
    commit: bool = True
) -> List[Question]:
    """
    Sauvegarde un lot de questions avec leurs options.

    Args:
        db: Session de base de données
        questions_data: Liste de dictionnaires de questions
        commit: Si True, commit la transaction à la fin

    Returns:
        Liste des Questions créées
    """
    questions = []

    for q_data in questions_data:
        try:
            question = save_question_with_options(db, q_data, commit=False)
            questions.append(question)
        except Exception as e:
            logger.error(f"❌ [QUESTION_SAVER] Erreur lors de la sauvegarde de la question: {e}")
            logger.debug(f"Données: {q_data}")
            # Continuer avec les autres questions
            continue

    if commit:
        try:
            db.commit()
            logger.info(f"✅ [QUESTION_SAVER] {len(questions)} questions sauvegardées avec succès")
        except Exception as e:
            db.rollback()
            logger.error(f"❌ [QUESTION_SAVER] Erreur lors du commit: {e}")
            raise

    return questions
