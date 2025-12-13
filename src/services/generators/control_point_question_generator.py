"""
Control Point Question Generator

Génère des questions d'audit depuis des points de contrôle personnalisés.
Similaire au générateur framework mais optimisé pour les control points.

Workflow:
1. Charger control points
2. Découper en batches
3. Générer via IA
4. Parser et normaliser

Version: 1.0
Date: 2025-01-08
"""

import logging
from typing import List, Dict, Any
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class ControlPointQuestionGenerator:
    """
    Générateur de questions depuis points de contrôle personnalisés.

    Dépendances injectées:
    - http_client: DeepSeekHttpClient
    - parser: DeepSeekResponseParser
    - prompt_builder: PromptBuilder
    """

    def __init__(
        self,
        db_session: Session,
        http_client,
        parser,
        prompt_builder,
        batch_size: int = 10
    ):
        """
        Initialise le générateur.

        Args:
            db_session: Session SQLAlchemy
            http_client: Client HTTP pour IA
            parser: Parser de réponses JSON
            prompt_builder: Constructeur de prompts
            batch_size: Taille des lots
        """
        self.db = db_session
        self.http_client = http_client
        self.parser = parser
        self.prompt_builder = prompt_builder
        self.batch_size = batch_size

    async def generate(
        self,
        control_point_ids: List[str],
        language: str = "fr"
    ) -> List[Dict[str, Any]]:
        """
        Génère des questions pour une liste de control points.

        Args:
            control_point_ids: Liste des IDs de control points
            language: Langue des questions

        Returns:
            Liste de questions brutes (format dict)

        Raises:
            ValueError: Si aucun control point trouvé
        """
        # 1. Charger control points
        control_points = self._load_control_points(control_point_ids)

        if not control_points:
            logger.warning(
                f"⚠️ Aucun control point trouvé pour IDs: {control_point_ids}"
            )
            return []

        logger.info(f"📋 {len(control_points)} control points chargés")

        # 2. Préparer items avec métadonnées
        items = []
        for cp in control_points:
            items.append({
                "anchor_id": str(cp.id),
                "control_code": cp.code,
                "code": cp.code,
                "title": cp.name,
                "description": (cp.description or "")[:600],
                "domain": getattr(cp, "category", None) or getattr(cp, "control_family", None),
                "subdomain": getattr(cp, "subcategory", None),
                "criticality_level": getattr(cp, "criticality_level", "MEDIUM"),
                "official_code": getattr(cp, "code", None),
            })

        # 3. Générer par batches
        all_questions = await self._generate_batches(items, language)

        logger.info(f"✅ {len(all_questions)} questions générées au total")
        return all_questions

    async def _generate_batches(
        self,
        items: List[Dict[str, Any]],
        language: str
    ) -> List[Dict[str, Any]]:
        """
        Génère des questions par lots.

        Args:
            items: Liste d'items (control points avec métadonnées)
            language: Langue

        Returns:
            Liste de toutes les questions générées
        """
        all_questions: List[Dict[str, Any]] = []

        # Découper en batches
        batches = list(self._chunks(items, self.batch_size))
        logger.info(f"📦 {len(batches)} batches de {self.batch_size} max")

        for idx, batch in enumerate(batches, 1):
            logger.info(f"🔄 Batch {idx}/{len(batches)} ({len(batch)} items)")

            try:
                # Construire le prompt
                prompt = self.prompt_builder.build_user_prompt_for_control_points(
                    control_points=batch,
                    framework_name="Custom Control Points"
                )

                logger.debug(f"📝 Prompt: {len(prompt)} chars")

                # Appeler l'IA
                response = await self.http_client.call_with_retry(prompt)

                # Parser la réponse
                parsed = self.parser.parse(response)

                if parsed:
                    # Enrichir et normaliser
                    enriched = self.parser.coerce_and_enrich_questions(parsed)
                    all_questions.extend(enriched)
                    logger.info(f"✅ Batch {idx}: {len(enriched)} questions")
                else:
                    logger.warning(f"⚠️ Batch {idx}: aucune question parsée")

            except Exception as e:
                logger.error(f"❌ Batch {idx} échoué: {e}")
                continue

        return all_questions

    def _load_control_points(self, cp_ids: List[str]):
        """
        Charge les control points depuis la DB.

        Args:
            cp_ids: Liste des IDs

        Returns:
            Liste de control points

        Raises:
            ValueError: Si aucun ID fourni
        """
        if not cp_ids:
            raise ValueError("control_point_ids requis")

        rows = self.db.execute(
            text(
                """
                SELECT
                    id, code, name, description,
                    category, subcategory, control_family,
                    criticality_level
                FROM control_point
                WHERE id::text = ANY(:ids)
                AND is_active = true
                ORDER BY criticality_level DESC, code
                """
            ),
            {"ids": cp_ids},
        ).mappings().all()

        # Wrapper pour accès attributs
        class ControlPointWrapper:
            def __init__(self, row):
                self.id = row["id"]
                self.code = row["code"]
                self.name = row["name"]
                self.description = row["description"]
                self.category = row["category"]
                self.subcategory = row["subcategory"]
                self.control_family = row["control_family"]
                self.criticality_level = row["criticality_level"] or "MEDIUM"

        return [ControlPointWrapper(r) for r in rows]

    @staticmethod
    def _chunks(items: List, size: int):
        """
        Découpe une liste en chunks.

        Args:
            items: Liste à découper
            size: Taille des chunks

        Yields:
            Chunks de taille size
        """
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def ensure_minimum_questions(
        self,
        questions: List[Dict[str, Any]],
        control_points: List[Dict[str, Any]],
        min_count: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Garantit un nombre minimum de questions.

        Args:
            questions: Questions générées
            control_points: Control points sources
            min_count: Minimum requis

        Returns:
            Liste avec au moins min_count questions
        """
        if len(questions) >= min_count:
            return questions

        needed = min_count - len(questions)
        logger.info(
            f"⚠️ Seulement {len(questions)} questions, "
            f"fallback pour {needed} questions"
        )

        # Générer templates
        templates = self._generate_template_questions(control_points[:needed])

        # Fusionner sans doublons
        def normalize_text(s: str) -> str:
            return " ".join((s or "").strip().lower().split())

        seen = set()
        out = []

        for q in questions:
            text = normalize_text(q.get("text", ""))
            if text and text not in seen:
                seen.add(text)
                out.append(q)

        for q in templates:
            text = normalize_text(q.get("text", ""))
            if text and text not in seen:
                seen.add(text)
                out.append(q)

        return out[:max(min_count, len(out))]

    def _generate_template_questions(
        self,
        control_points: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Génère des questions templates depuis les control points.

        Args:
            control_points: Control points sources

        Returns:
            Liste de questions templates
        """
        templates = []

        for cp in control_points:
            title = (cp.get("title") or cp.get("name") or "").strip()
            domain = cp.get("domain") or cp.get("category")
            cp_id = cp.get("anchor_id") or cp.get("id")
            short = title[:60] if title else "contrôle"

            templates.extend([
                {
                    "id": str(uuid4()),
                    "text": f"Le contrôle « {short} » est-il implémenté ?",
                    "type": "yes_no",
                    "options": [],
                    "help_text": "Vérifier l'existence d'une procédure ou mesure technique.",
                    "difficulty": "low",
                    "domain": domain,
                    "control_point_id": cp_id,
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": ["contrôle", "implémentation"]
                },
                {
                    "id": str(uuid4()),
                    "text": f"Quand le contrôle « {short} » a-t-il été vérifié pour la dernière fois ?",
                    "type": "date",
                    "options": [],
                    "help_text": "Date du dernier audit ou revue de conformité.",
                    "difficulty": "medium",
                    "domain": domain,
                    "control_point_id": cp_id,
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": ["audit", "revue"]
                },
            ])

        return templates
