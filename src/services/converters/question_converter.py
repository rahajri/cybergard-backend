"""
Question Converter

Convertit les questions brutes (dict) en objets Pydantic GeneratedQuestion.

Gère:
- Mapping types de réponses
- Validation règles métier
- Extraction evidence_types selon difficulté
- Estimation temps de réponse
- Conversion upload_conditions

Version: 1.0
Date: 2025-01-08
"""

import logging
from typing import Dict, Any, Optional, List
from uuid import uuid4

logger = logging.getLogger(__name__)


class QuestionConverter:
    """
    Convertit dict → Pydantic GeneratedQuestion avec validation et enrichissement.

    Règles métier appliquées:
    - Validation selon response_type
    - Evidence types selon difficulté (low/medium/high/critical)
    - Temps estimé selon complexité
    - Extraction chapter depuis codes officiels
    """

    @staticmethod
    def to_generated_question(
        q: Dict[str, Any],
        requirement_ids: Optional[List[str]] = None,
        control_point_id: Optional[str] = None,
    ):
        """
        Transforme un dict normalisé en GeneratedQuestion Pydantic.

        Args:
            q: Question brute (dict)
            requirement_ids: IDs des exigences liées
            control_point_id: ID du control point lié

        Returns:
            GeneratedQuestion

        Raises:
            ValueError: Si text manquant
        """
        from ...schemas.questionnaire import GeneratedQuestion

        text = q.get("text") or q.get("question_text", "")
        if not text:
            raise ValueError("Question text requis")

        # Mapper le type de réponse
        typ = q.get("type") or q.get("response_type", "open")
        mapped_type = QuestionConverter._map_response_type(typ)

        # Normaliser difficulty
        difficulty = QuestionConverter._normalize_difficulty(q)

        # Construire l'objet
        return GeneratedQuestion(
            id=str(uuid4()),
            text=text.strip(),
            type=mapped_type,
            options=q.get("options"),
            control_point_id=control_point_id,
            requirement_ids=requirement_ids or [],
            difficulty=difficulty,
            ai_confidence=q.get("ai_confidence"),
            rationale=q.get("rationale"),
            help_text=q.get("help_text"),  # ✅ Aide contextuelle pour l'audité (DISTINCT de rationale)
            tags=q.get("tags", []),
            is_mandatory=q.get("is_mandatory", False),
            upload_conditions=q.get("upload_conditions"),
            # ✅ Extraction des métadonnées supplémentaires (ajouté lors du refactoring)
            question_code=q.get("question_code"),
            chapter=q.get("chapter"),
            evidence_types=q.get("evidence_types", []),
            estimated_time_minutes=q.get("estimated_time_minutes"),
        )

    @staticmethod
    def _map_response_type(typ: str) -> str:
        """
        Mappe les types de réponses vers les types standards.

        Supporte les alias:
        - yes_no → boolean
        - yesno → boolean
        - bool → boolean
        - text/textarea → open
        - likert → rating

        Args:
            typ: Type original

        Returns:
            Type normalisé
        """
        type_mapping = {
            # Valeurs standards
            "boolean": "boolean",
            "single_choice": "single_choice",
            "multiple_choice": "multiple_choice",
            "open": "open",
            "rating": "rating",
            "number": "number",
            "date": "date",
            # Alias fréquents
            "yes_no": "boolean",
            "yesno": "boolean",
            "bool": "boolean",
            "text": "open",
            "textarea": "open",
            "text_open": "open",
            "likert": "rating",
            "single": "single_choice",  # ✅ Alias IA
            "multiple": "multiple_choice",  # ✅ Alias IA
            "multi_choice": "multiple_choice",  # ✅ AJOUTÉ : Erreur FK
            "multi": "multiple_choice",  # ✅ Alias IA
        }

        normalized = typ.lower().strip() if typ else "open"
        return type_mapping.get(normalized, "open")

    @staticmethod
    def _normalize_difficulty(q: Dict[str, Any]) -> str:
        """
        Normalise le niveau de difficulté.

        Supporte:
        - difficulty, difficulty_level, criticality_level
        - Mapping: easy→low, hard→high, critical→high

        Args:
            q: Question dict

        Returns:
            Difficulté normalisée (low/medium/high)
        """
        # Extraire depuis plusieurs champs possibles
        raw = (
            q.get("difficulty")
            or q.get("difficulty_level")
            or q.get("criticality_level")
            or "medium"
        )

        # Normaliser
        normalized = str(raw).lower().strip()

        # Mapping
        difficulty_map = {
            "easy": "low",
            "basic": "low",
            "low": "low",
            "medium": "medium",
            "moderate": "medium",
            "hard": "high",
            "high": "high",
            "critical": "high",
        }

        return difficulty_map.get(normalized, "medium")

    @staticmethod
    def build_validation_rules(question_data: Dict) -> Dict:
        """
        Construit les règles de validation selon le type de réponse.

        Args:
            question_data: Question dict

        Returns:
            Dictionnaire de règles
        """
        q_type = question_data.get("type", "text")
        difficulty = question_data.get("difficulty", "medium")

        rules = {}

        if q_type in ["yes_no", "boolean"]:
            rules = {
                "requires_comment_if_no": True,
                "requires_evidence_if_no": difficulty in ["hard", "high", "critical"]
            }

        elif q_type == "single_choice":
            rules = {
                "requires_selection": True,
                "allow_other": False
            }

        elif q_type == "multiple_choice":
            rules = {
                "min_selections": 1,
                "max_selections": 10,
                "allow_other": True
            }

        elif q_type == "rating":
            rules = {
                "min": 1,
                "max": 5,
                "scale_labels": [
                    "Non implémenté",
                    "Incomplet",
                    "Partiel",
                    "Complet",
                    "Optimisé"
                ],
                "requires_comment_if_low": True,
                "low_threshold": 3
            }

        elif q_type == "number":
            rules = {
                "min": 0,
                "max": 100,
                "type": "integer",
                "unit": "%"
            }

        elif q_type == "date":
            rules = {
                "format": "YYYY-MM-DD",
                "min_date": "2020-01-01",
                "allow_future": False
            }

        elif q_type in ["open", "text", "textarea"]:
            rules = {
                "min_length": 10,
                "max_length": 500,
                "multiline": True
            }

        return rules

    @staticmethod
    def build_evidence_types(difficulty: str) -> List[str]:
        """
        Détermine les types de preuves selon la difficulté.

        Args:
            difficulty: Niveau de difficulté

        Returns:
            Liste des types de preuves attendues
        """
        difficulty = difficulty.lower().strip()

        if difficulty in ["hard", "high", "critical"]:
            return ["document", "screenshot", "policy", "procedure", "audit_report"]
        elif difficulty == "medium":
            return ["document", "screenshot", "policy"]
        elif difficulty in ["easy", "low", "basic"]:
            return ["document", "screenshot"]
        else:
            return ["document"]

    @staticmethod
    def estimate_time(question_data: Dict) -> int:
        """
        Estime le temps de réponse en minutes.

        Facteurs:
        - Difficulté (low/medium/high)
        - Type de réponse (boolean rapide, open long)
        - Upload requis (+3-5 min)

        Args:
            question_data: Question dict

        Returns:
            Temps estimé en minutes
        """
        difficulty = question_data.get("difficulty", "medium")
        q_type = question_data.get("type", "text")
        has_upload = question_data.get("upload_conditions") is not None

        # Base selon difficulté
        time_map = {
            "easy": 3,
            "low": 3,
            "basic": 3,
            "medium": 5,
            "moderate": 5,
            "hard": 10,
            "high": 10,
            "critical": 15
        }

        base_time = time_map.get(difficulty, 5)

        # Ajustement selon type
        if q_type in ["yes_no", "boolean"]:
            base_time = min(base_time, 5)  # Max 5 min pour boolean
        elif q_type in ["single_choice", "rating"]:
            base_time = min(base_time + 1, 8)
        elif q_type in ["open", "textarea"]:
            base_time += 3  # Texte libre prend plus de temps

        # Ajout pour upload
        if has_upload:
            base_time += 5

        return base_time

    @staticmethod
    def extract_chapter(official_code: Optional[str]) -> Optional[str]:
        """
        Extrait le chapitre depuis un code officiel.

        Exemples:
        - "A.5.1.1" → "A.5"
        - "A.6.2.1" → "A.6"
        - "5.1.2" → "5.1"
        - None → None

        Args:
            official_code: Code officiel ISO/NIST

        Returns:
            Chapitre extrait ou None
        """
        if not official_code:
            return None

        code = str(official_code).strip()

        # Pattern: A.5.1.1 → extraire A.5
        if "." in code:
            parts = code.split(".")
            if len(parts) >= 2:
                return f"{parts[0]}.{parts[1]}"

        return None
