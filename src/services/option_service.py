"""
Service pour gérer les options réutilisables
"""
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from uuid import UUID
import re
import logging

from src.models.option import Option, OptionI18n

logger = logging.getLogger(__name__)


class OptionService:
    """Service pour la gestion des options réutilisables"""

    @staticmethod
    def slugify(text: str) -> str:
        """
        Convertit un texte en slug (clé technique)

        Examples:
            "Oui" → "oui"
            "Quotidienne" → "quotidienne"
            "Pas du tout" → "pas_du_tout"
        """
        text = text.lower().strip()
        # Remplacer les espaces par underscores
        text = re.sub(r'\s+', '_', text)
        # Garder seulement alphanumérique et underscores
        text = re.sub(r'[^a-z0-9_]', '', text)
        return text

    @staticmethod
    def get_or_create_option(
        db: Session,
        value: str,
        category: Optional[str] = None,
        commit: bool = False
    ) -> Option:
        """
        Récupère une option existante ou en crée une nouvelle

        Args:
            db: Session SQLAlchemy
            value: Valeur de l'option (ex: "Oui", "Quotidienne")
            category: Catégorie optionnelle (ex: "yes_no", "frequency")
            commit: Si True, commit immédiatement

        Returns:
            Option: Option existante ou nouvellement créée
        """
        # Chercher par default_value (insensible à la casse)
        option = db.query(Option).filter(
            Option.default_value.ilike(value.strip())
        ).first()

        if option:
            logger.debug(f"✅ [OPTION_SERVICE] Option existante réutilisée: '{value}'")
            return option

        # Créer nouvelle option
        value_key = OptionService.slugify(value)

        # Vérifier que la clé n'existe pas déjà
        existing_key = db.query(Option).filter(Option.value_key == value_key).first()
        if existing_key:
            # Si la clé existe mais pas la valeur, ajouter un suffixe
            counter = 1
            while db.query(Option).filter(Option.value_key == f"{value_key}_{counter}").first():
                counter += 1
            value_key = f"{value_key}_{counter}"

        option = Option(
            value_key=value_key,
            default_value=value.strip(),
            category=category,
            is_system=False
        )
        db.add(option)

        if commit:
            db.commit()
            db.refresh(option)
        else:
            db.flush()

        logger.info(f"✅ [OPTION_SERVICE] Nouvelle option créée: '{value}' (key={value_key}, category={category})")
        return option

    @staticmethod
    def get_all_options(
        db: Session,
        category: Optional[str] = None,
        language: str = "fr",
        active_only: bool = True
    ) -> List[Dict]:
        """
        Liste toutes les options disponibles

        Args:
            db: Session SQLAlchemy
            category: Filtrer par catégorie (optional)
            language: Code langue pour traductions
            active_only: Si True, seulement les options actives

        Returns:
            List[Dict]: Liste des options avec traductions
        """
        query = db.query(Option)

        if category:
            query = query.filter(Option.category == category)

        options = query.order_by(Option.category, Option.default_value).all()

        # Enrichir avec traductions
        result = []
        for opt in options:
            translation = db.query(OptionI18n).filter(
                OptionI18n.option_id == opt.id,
                OptionI18n.language_code == language
            ).first()

            result.append({
                "id": str(opt.id),
                "value_key": opt.value_key,
                "value": translation.translated_value if translation else opt.default_value,
                "default_value": opt.default_value,
                "category": opt.category,
                "is_system": opt.is_system
            })

        logger.debug(f"[OPTION_SERVICE] Récupéré {len(result)} options (category={category}, lang={language})")
        return result

    @staticmethod
    def create_translation(
        db: Session,
        option_id: UUID,
        language_code: str,
        translated_value: str,
        commit: bool = False
    ) -> OptionI18n:
        """
        Crée une traduction pour une option

        Args:
            db: Session SQLAlchemy
            option_id: ID de l'option
            language_code: Code langue ('fr', 'en', 'es', etc.)
            translated_value: Valeur traduite
            commit: Si True, commit immédiatement

        Returns:
            OptionI18n: Traduction créée
        """
        # Vérifier si traduction existe déjà
        existing = db.query(OptionI18n).filter(
            OptionI18n.option_id == option_id,
            OptionI18n.language_code == language_code
        ).first()

        if existing:
            # Mettre à jour
            existing.translated_value = translated_value.strip()
            translation = existing
            logger.info(f"✅ [OPTION_SERVICE] Traduction mise à jour: {option_id} ({language_code})")
        else:
            # Créer
            translation = OptionI18n(
                option_id=option_id,
                language_code=language_code,
                translated_value=translated_value.strip()
            )
            db.add(translation)
            logger.info(f"✅ [OPTION_SERVICE] Traduction créée: {option_id} ({language_code})")

        if commit:
            db.commit()
            db.refresh(translation)
        else:
            db.flush()

        return translation

    @staticmethod
    def create_system_options(db: Session, commit: bool = True) -> List[Option]:
        """
        Crée les options système de base

        Args:
            db: Session SQLAlchemy
            commit: Si True, commit les changements

        Returns:
            List[Option]: Options créées
        """
        system_options = [
            # Oui/Non/NSP
            ("yes", "Oui", "yes_no", True),
            ("no", "Non", "yes_no", True),
            ("partial", "Partiellement", "yes_no", True),
            ("unknown", "NSP", "yes_no", True),
            ("not_applicable", "N/A", "yes_no", True),

            # Fréquences
            ("daily", "Quotidienne", "frequency", True),
            ("weekly", "Hebdomadaire", "frequency", True),
            ("monthly", "Mensuelle", "frequency", True),
            ("quarterly", "Trimestrielle", "frequency", True),
            ("yearly", "Annuelle", "frequency", True),
            ("none", "Aucune", "frequency", True),

            # Niveaux de conformité
            ("full", "Totalement conforme", "compliance", True),
            ("high", "Largement conforme", "compliance", True),
            ("medium", "Partiellement conforme", "compliance", True),
            ("low", "Faiblement conforme", "compliance", True),
            ("non_compliant", "Non conforme", "compliance", True),
        ]

        created = []
        for value_key, default_value, category, is_system in system_options:
            # Vérifier si existe déjà
            existing = db.query(Option).filter(Option.value_key == value_key).first()
            if existing:
                logger.debug(f"[OPTION_SERVICE] Option système déjà existante: {value_key}")
                continue

            option = Option(
                value_key=value_key,
                default_value=default_value,
                category=category,
                is_system=is_system
            )
            db.add(option)
            created.append(option)
            logger.info(f"✅ [OPTION_SERVICE] Option système créée: {value_key} = {default_value}")

        if commit:
            db.commit()

        logger.info(f"✅ [OPTION_SERVICE] {len(created)} options système créées")
        return created

    @staticmethod
    def get_option_by_value(
        db: Session,
        value: str,
        category: Optional[str] = None
    ) -> Optional[Option]:
        """
        Recherche une option par sa valeur (insensible à la casse)

        Args:
            db: Session SQLAlchemy
            value: Valeur à rechercher
            category: Filtrer par catégorie (optional)

        Returns:
            Option ou None
        """
        query = db.query(Option).filter(
            Option.default_value.ilike(value.strip())
        )

        if category:
            query = query.filter(Option.category == category)

        return query.first()
