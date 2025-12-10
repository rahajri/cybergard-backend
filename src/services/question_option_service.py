"""
Service pour gérer les options de questions (QuestionOption)
Architecture avec options réutilisables
"""
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
import logging

from src.models.question_option import QuestionOption
from src.services.option_service import OptionService

logger = logging.getLogger(__name__)


class QuestionOptionService:
    """Service pour gérer les options de questions"""

    @staticmethod
    def create_options_for_question(
        db: Session,
        question_id: UUID,
        options: List[str],
        replace_existing: bool = True,
        category: Optional[str] = None
    ) -> List[QuestionOption]:
        """
        Crée les options pour une question (réutilise les options existantes si possible).

        Args:
            db: Session de base de données
            question_id: ID de la question
            options: Liste des valeurs d'options (ex: ["Oui", "Non", "NSP"])
            replace_existing: Si True, supprime les options existantes avant création
            category: Catégorie pour les nouvelles options (ex: "yes_no", "frequency")

        Returns:
            Liste des QuestionOption créés
        """
        if not options or not isinstance(options, list):
            logger.warning(f"Options vides ou invalides pour question {question_id}")
            return []

        # Supprimer les options existantes si demandé
        if replace_existing:
            QuestionOptionService.delete_options_for_question(db, question_id)

        # Créer les nouvelles options
        created_options = []
        for idx, option_value in enumerate(options):
            if not option_value or not str(option_value).strip():
                logger.warning(f"Option vide ignorée à l'index {idx} pour question {question_id}")
                continue

            # ✅ NOUVEAU : Récupérer ou créer l'option réutilisable
            reusable_option = OptionService.get_or_create_option(
                db=db,
                value=str(option_value).strip(),
                category=category,
                commit=False
            )

            # Créer la liaison question_option
            question_option = QuestionOption(
                question_id=question_id,
                option_id=reusable_option.id,  # ✅ Référence vers option réutilisable
                custom_value=None,  # Pas custom
                sort_order=idx,
                is_active=True
            )
            db.add(question_option)
            created_options.append(question_option)

        db.flush()  # Flush pour obtenir les IDs sans commit
        logger.info(f"✅ [OPTION_SERVICE] {len(created_options)} options créées pour question {question_id}")

        return created_options

    @staticmethod
    def create_custom_option(
        db: Session,
        question_id: UUID,
        custom_value: str,
        sort_order: int = 0
    ) -> QuestionOption:
        """
        Crée une option custom (non réutilisable) pour une question.

        Args:
            db: Session de base de données
            question_id: ID de la question
            custom_value: Valeur custom unique à cette question
            sort_order: Ordre de tri

        Returns:
            QuestionOption créé
        """
        question_option = QuestionOption(
            question_id=question_id,
            option_id=None,  # Pas d'option réutilisable
            custom_value=custom_value.strip(),
            sort_order=sort_order,
            is_active=True
        )
        db.add(question_option)
        db.flush()

        logger.info(f"✅ [OPTION_SERVICE] Option custom créée pour question {question_id}: '{custom_value}'")
        return question_option

    @staticmethod
    def get_options_for_question(
        db: Session,
        question_id: UUID,
        active_only: bool = True
    ) -> List[QuestionOption]:
        """
        Récupère les options d'une question.

        Args:
            db: Session de base de données
            question_id: ID de la question
            active_only: Si True, retourne uniquement les options actives

        Returns:
            Liste des QuestionOption ordonnées par sort_order
        """
        query = db.query(QuestionOption).filter_by(question_id=question_id)

        if active_only:
            query = query.filter_by(is_active=True)

        return query.order_by(QuestionOption.sort_order).all()

    @staticmethod
    def delete_options_for_question(
        db: Session,
        question_id: UUID
    ) -> int:
        """
        Supprime toutes les options d'une question.

        Args:
            db: Session de base de données
            question_id: ID de la question

        Returns:
            Nombre d'options supprimées
        """
        count = db.query(QuestionOption).filter_by(question_id=question_id).delete()
        db.flush()
        logger.info(f"🗑️ [OPTION_SERVICE] {count} options supprimées pour question {question_id}")
        return count

    @staticmethod
    def update_option(
        db: Session,
        option_id: UUID,
        option_value: Optional[str] = None,
        sort_order: Optional[int] = None,
        is_active: Optional[bool] = None
    ) -> Optional[QuestionOption]:
        """
        Met à jour une option existante.

        Args:
            db: Session de base de données
            option_id: ID de l'option
            option_value: Nouvelle valeur (optionnel)
            sort_order: Nouvel ordre (optionnel)
            is_active: Nouveau statut actif (optionnel)

        Returns:
            QuestionOption mise à jour ou None si non trouvée
        """
        option = db.query(QuestionOption).filter_by(id=option_id).first()

        if not option:
            logger.warning(f"Option {option_id} non trouvée")
            return None

        if option_value is not None:
            option.option_value = option_value
        if sort_order is not None:
            option.sort_order = sort_order
        if is_active is not None:
            option.is_active = is_active

        db.flush()
        logger.info(f"✏️ [OPTION_SERVICE] Option {option_id} mise à jour")

        return option

    @staticmethod
    def get_options_as_list(
        db: Session,
        question_id: UUID,
        active_only: bool = True,
        language: str = "fr"
    ) -> List[str]:
        """
        Récupère les options d'une question sous forme de liste de chaînes.

        Args:
            db: Session de base de données
            question_id: ID de la question
            active_only: Si True, retourne uniquement les options actives
            language: Code langue pour traductions (ex: 'fr', 'en')

        Returns:
            Liste des valeurs d'options (ex: ["Oui", "Non", "NSP"])
        """
        options = QuestionOptionService.get_options_for_question(
            db, question_id, active_only
        )
        # ✅ MODIFIÉ : Utiliser get_value() qui gère réutilisables ET custom
        return [opt.get_value(language) for opt in options]
