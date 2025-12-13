"""
Question Generation Service (Orchestrator)

Service principal qui coordonne tous les modules pour générer des questions.

Architecture (Facade Pattern):
- Routage vers le bon générateur (framework vs control_points)
- Injection de dépendances (http_client, parser, etc.)
- Conversion dict → Pydantic
- Matching control points

Version: 1.0
Date: 2025-01-08
"""

import os
import logging
from typing import List
from sqlalchemy.orm import Session

# Imports des modules refactorisés
from .prompts.question_generation_prompts import PromptBuilder, PromptVersion
from .parsers.deepseek_response_parser import DeepSeekResponseParser
from .clients.deepseek_http_client import DeepSeekHttpClient
from .generators.framework_question_generator import FrameworkQuestionGenerator
from .generators.control_point_question_generator import ControlPointQuestionGenerator
from .converters.question_converter import QuestionConverter
from .control_point_matcher import ControlPointMatcher

# Imports des schémas
from ..schemas.questionnaire import QuestionGenerationRequest, GeneratedQuestion

logger = logging.getLogger(__name__)


class QuestionGenerationService:
    """
    Service orchestrateur pour la génération de questions.

    Responsabilités:
    1. Router vers le bon générateur (framework/control_points)
    2. Coordonner les dépendances (HTTP, parser, prompt)
    3. Convertir les questions (dict → Pydantic)
    4. Assigner les control points (mode framework)

    Pattern: Facade
    """

    def __init__(self, db_session: Session):
        """
        Initialise le service avec injection de dépendances.

        Args:
            db_session: Session SQLAlchemy
        """
        self.db = db_session

        # Configuration depuis variables d'environnement
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "deepseek-v3.1:671b-cloud")

        try:
            self.temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.6"))
        except ValueError:
            self.temperature = 0.6
            logger.warning("⚠️ DEEPSEEK_TEMPERATURE invalide, utilisation de 0.6")

        try:
            self.max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192"))
        except ValueError:
            self.max_tokens = 8192
            logger.warning("⚠️ DEEPSEEK_MAX_TOKENS invalide, utilisation de 8192")

        # Initialiser les dépendances
        self._init_dependencies()

    def _init_dependencies(self):
        """
        Initialise tous les modules (dependency injection).

        Modules créés:
        - prompt_builder: Construction prompts
        - parser: Parsing JSON
        - http_client: Appels IA
        - framework_generator: Mode framework
        - control_point_generator: Mode control_points
        - converter: Dict → Pydantic
        - matcher: Q ↔ CP matching
        """
        # 1. Prompt builder
        self.prompt_builder = PromptBuilder(version=PromptVersion.V1)

        # 2. Parser
        self.parser = DeepSeekResponseParser()

        # 3. HTTP Client
        self.http_client = DeepSeekHttpClient(
            base_url=self.ollama_url,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_retries=3,
            system_prompt=self.prompt_builder.get_system_prompt()
        )

        # 4. Generators
        self.framework_generator = FrameworkQuestionGenerator(
            db_session=self.db,
            http_client=self.http_client,
            parser=self.parser,
            prompt_builder=self.prompt_builder,
            batch_size=10
        )

        self.control_point_generator = ControlPointQuestionGenerator(
            db_session=self.db,
            http_client=self.http_client,
            parser=self.parser,
            prompt_builder=self.prompt_builder,
            batch_size=10
        )

        # 5. Converter
        self.converter = QuestionConverter()

        # 6. Matcher
        self.matcher = ControlPointMatcher(
            db_session=self.db,
            use_semantic=False  # Désactivé par défaut
        )

        logger.info("✅ QuestionGenerationService initialisé")

    async def generate_questions(
        self,
        request: QuestionGenerationRequest,
        progress_callback = None  # Callback pour progression SSE
    ) -> List[GeneratedQuestion]:
        """
        Point d'entrée principal appelé par l'API.

        Workflow:
        1. Router vers le générateur approprié
        2. Générer questions brutes (dict)
        3. Assigner control points (si mode framework)
        4. Convertir en GeneratedQuestion (Pydantic)

        Args:
            request: Requête de génération
            progress_callback: Fonction async pour progression SSE

        Returns:
            Liste de GeneratedQuestion

        Raises:
            ValueError: Si mode invalide
        """
        mode = request.mode
        logger.info(f"[QGen] Mode={mode}")

        # 1. Router et générer
        if mode == "framework":
            questions_raw = await self._generate_for_framework(request, progress_callback)
        elif mode == "control_points":
            questions_raw = await self._generate_for_control_points(request, progress_callback)
        else:
            raise ValueError("mode must be 'framework' or 'control_points'")

        # 2. Convertir en Pydantic
        generated_questions = self._convert_to_pydantic(questions_raw)

        logger.info(f"🎉 Total: {len(generated_questions)} questions générées")
        return generated_questions

    async def _generate_for_framework(
        self,
        request: QuestionGenerationRequest,
        progress_callback = None
    ) -> List[dict]:
        """
        Génère des questions pour un framework.

        Workflow:
        1. Générer via FrameworkGenerator
        2. Assigner control points via Matcher
        3. Aplatir la structure

        Args:
            request: Requête
            progress_callback: Callback pour progression SSE

        Returns:
            Liste de questions (dict)
        """
        # 1. Générer
        questions_raw = await self.framework_generator.generate(
            framework_id=request.framework_id,
            language=request.language or "fr",
            progress_callback=progress_callback
        )

        # 2. Aplatir structure items → questions
        flat_questions = []
        for item in questions_raw:
            if isinstance(item, dict) and "questions" in item:
                # Structure: {"anchor_id": "...", "questions": [...]}
                anchor_id = item.get("anchor_id", "unknown")
                for q in item.get("questions", []):
                    if q:  # Ignorer None
                        # Ajouter requirement_ids si manquant
                        if "requirement_ids" not in q and anchor_id != "unknown":
                            q["requirement_ids"] = [anchor_id]
                        elif "requirement_ids" not in q:
                            q["requirement_ids"] = []
                        flat_questions.append(q)
            elif isinstance(item, dict):
                # Déjà une question plate
                flat_questions.append(item)

        # 3. Assigner control points
        enriched = await self.matcher.assign_control_points(
            questions=flat_questions
        )

        return enriched

    async def _generate_for_control_points(
        self,
        request: QuestionGenerationRequest,
        progress_callback = None
    ) -> List[dict]:
        """
        Génère des questions pour des control points.

        Args:
            request: Requête

        Returns:
            Liste de questions (dict)
        """
        questions_raw = await self.control_point_generator.generate(
            control_point_ids=request.control_point_ids or [],
            language=request.language or "fr"
        )

        # Aplatir structure si nécessaire
        flat_questions = []
        for item in questions_raw:
            if isinstance(item, dict) and "questions" in item:
                anchor_id = item.get("anchor_id")
                for q in item.get("questions", []):
                    if q:
                        # Ajouter control_point_id si manquant
                        if "control_point_id" not in q and anchor_id:
                            q["control_point_id"] = anchor_id
                        flat_questions.append(q)
            elif isinstance(item, dict):
                flat_questions.append(item)

        return flat_questions

    def _convert_to_pydantic(
        self,
        questions_raw: List[dict]
    ) -> List[GeneratedQuestion]:
        """
        Convertit les questions brutes en objets Pydantic.

        Args:
            questions_raw: Questions dict

        Returns:
            Liste de GeneratedQuestion
        """
        out: List[GeneratedQuestion] = []

        for q in questions_raw:
            # Extraire requirement_ids
            requirement_ids = q.get("requirement_ids", [])
            if not isinstance(requirement_ids, list):
                requirement_ids = [requirement_ids] if requirement_ids else []

            # Extraire control_point_id
            control_point_id = q.get("control_point_id")

            try:
                generated_q = self.converter.to_generated_question(
                    q=q,
                    requirement_ids=requirement_ids,
                    control_point_id=control_point_id
                )
                out.append(generated_q)
            except Exception as e:
                logger.error(f"❌ Erreur conversion question: {e}")
                logger.debug(f"Question problématique: {q}")
                continue

        return out

    async def health_check(self) -> dict:
        """
        Vérifie la disponibilité du service.

        Returns:
            Statut du service
        """
        try:
            # Vérifier HTTP client
            client_status = await self.http_client.health_check()

            return {
                "status": "ok" if client_status["available"] else "degraded",
                "ollama": client_status,
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
