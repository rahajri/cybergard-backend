"""
Framework Question Generator

Génère des questions d'audit depuis des frameworks (ISO 27001, NIST, etc.) en utilisant
l'IA (DeepSeek) avec batching intelligent et fallback algorithmique.

Workflow:
1. Charger framework + exigences
2. Découper en batches (10 exigences/lot)
3. Générer via IA par lot
4. Parser et normaliser
5. Vérifier couverture minimale
6. Relancer pour exigences manquantes

Version: 1.0
Date: 2025-01-08
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class FrameworkQuestionGenerator:
    """
    Générateur de questions depuis frameworks de conformité.

    Dépendances injectées:
    - http_client: DeepSeekHttpClient pour appels IA
    - parser: DeepSeekResponseParser pour parsing JSON
    - prompt_builder: PromptBuilder pour construction prompts
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
            batch_size: Taille des lots (défaut: 10)
        """
        self.db = db_session
        self.http_client = http_client
        self.parser = parser
        self.prompt_builder = prompt_builder
        self.batch_size = batch_size

    async def generate(
        self,
        framework_id: str,
        language: str = "fr",
        progress_callback = None  # Callback pour progression SSE
    ) -> List[Dict[str, Any]]:
        """
        Génère des questions pour un framework donné.

        Args:
            framework_id: ID du framework
            language: Langue des questions (défaut: "fr")
            progress_callback: Fonction async(batch_idx, total_batches, status, data) pour SSE

        Returns:
            Liste de questions brutes (format dict)

        Raises:
            ValueError: Si framework inexistant
        """
        # 1. Charger framework + exigences
        framework, requirements = self._load_framework_and_requirements(framework_id)

        if not requirements:
            logger.warning(f"⚠️ Aucune exigence trouvée pour framework {framework_id}")
            return []

        logger.info(
            f"📋 Framework: {framework.name} - "
            f"{len(requirements)} exigences"
        )

        # 2. Charger criticités depuis control points
        requirement_ids = [str(r.id) for r in requirements]
        cp_map = self._fetch_control_points_for_requirements(requirement_ids)

        # 3. Préparer les items avec métadonnées
        items = []
        for r in requirements:
            # Récupérer la criticité du premier CP lié
            cps = cp_map.get(str(r.id), [])
            criticality = cps[0].get("criticality_level", "MEDIUM") if cps else "MEDIUM"

            items.append({
                "anchor_id": str(r.id),
                "requirement_code": r.official_code,
                "official_code": r.official_code,
                "title": r.title,
                "requirement_text": (r.requirement_text or "")[:600],
                "domain": getattr(r, "domain", None),
                "subdomain": getattr(r, "subdomain", None),
                "criticality_level": criticality,
            })

        # 4. Générer par batches
        all_questions = await self._generate_batches(items, language, progress_callback)

        # 5. Vérifier la couverture des exigences
        covered_req_ids = set()
        for q in all_questions:
            if isinstance(q, dict):
                req_ids = q.get("requirement_ids", [])
                if isinstance(req_ids, list):
                    covered_req_ids.update([str(rid) for rid in req_ids])

        all_req_ids = {str(r.id) for r in requirements}
        uncovered_req_ids = all_req_ids - covered_req_ids

        # 6. Deuxième passe IA si des exigences ne sont pas couvertes
        if uncovered_req_ids:
            logger.warning(
                f"⚠️ {len(uncovered_req_ids)} exigences non couvertes après première passe"
            )

            # Callback pour informer du démarrage de la deuxième passe
            if progress_callback:
                await progress_callback(0, 1, "second_pass_started", {
                    "missing_count": len(uncovered_req_ids),
                    "message": f"Deuxième passe IA pour {len(uncovered_req_ids)} exigences non couvertes..."
                })

            # Récupérer les items des exigences manquantes
            uncovered_items = [item for item in items if item.get("anchor_id") in uncovered_req_ids]

            if uncovered_items:
                try:
                    # Générer pour les exigences manquantes
                    logger.info(f"🔄 Deuxième passe pour {len(uncovered_items)} exigences manquantes")
                    second_pass_questions = await self._generate_second_pass(uncovered_items, language)

                    if second_pass_questions:
                        all_questions.extend(second_pass_questions)
                        logger.info(f"✅ Deuxième passe: {len(second_pass_questions)} questions supplémentaires")

                        # Callback pour informer de la fin de la deuxième passe
                        if progress_callback:
                            await progress_callback(0, 1, "second_pass_complete", {
                                "new_questions": len(second_pass_questions),
                                "total_questions": len(all_questions),
                                "message": f"Deuxième passe terminée: {len(second_pass_questions)} questions supplémentaires"
                            })

                except Exception as e:
                    logger.error(f"❌ Erreur deuxième passe IA: {e}")
                    # Callback pour informer de l'erreur
                    if progress_callback:
                        await progress_callback(0, 1, "second_pass_error", {
                            "error": str(e),
                            "message": f"Erreur deuxième passe: {len(uncovered_req_ids)} exigences non couvertes"
                        })

        logger.info(f"✅ {len(all_questions)} questions générées au total")
        return all_questions

    async def _generate_second_pass(
        self,
        uncovered_items: List[Dict[str, Any]],
        language: str = "fr"
    ) -> List[Dict[str, Any]]:
        """
        Deuxième passe IA pour les exigences non couvertes.
        Utilise un prompt spécifique pour garantir la couverture.

        Args:
            uncovered_items: Items des exigences non couvertes
            language: Langue

        Returns:
            Liste de questions supplémentaires
        """
        if not uncovered_items:
            return []

        logger.info(f"🔄 Deuxième passe: génération pour {len(uncovered_items)} exigences manquantes")

        all_second_pass_questions = []

        # Traiter par petits lots pour ne pas surcharger l'IA
        batches = list(self._chunks(uncovered_items, min(self.batch_size, 5)))

        for idx, batch in enumerate(batches, 1):
            try:
                # Construire un prompt spécifique pour les exigences manquantes
                reqs_text = ""
                for i, item in enumerate(batch, 1):
                    code = item.get("official_code", f"REQ-{i}")
                    title = item.get("title", "")
                    text = item.get("requirement_text", "")
                    req_id = item.get("anchor_id", "")
                    reqs_text += f"{i}. **{code}** (ID: {req_id})\n   Titre: {title}\n   Texte: {text[:400]}\n\n"

                second_pass_prompt = f"""Tu es un expert en cybersécurité et conformité.

⚠️ **MISSION CRITIQUE : COUVERTURE OBLIGATOIRE POUR EXIGENCES MANQUANTES**

Ces {len(batch)} exigences N'ONT PAS ÉTÉ COUVERTES lors de la première passe.
Tu DOIS ABSOLUMENT générer au moins 3 à 5 questions pour CHACUNE d'entre elles.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 EXIGENCES NON COUVERTES :

{reqs_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 **OBJECTIF** : Générer 3-5 questions pertinentes pour CHAQUE exigence ci-dessus.

📊 FORMAT JSON OBLIGATOIRE :

```json
[
  {{
    "text": "Question pertinente (verbe à l'infinitif ou forme interrogative)",
    "type": "yes_no|single_choice|multiple_choice|open|rating|number|date",
    "options": [],
    "help_text": "Aide contextuelle pour l'audité",
    "difficulty": "low|medium|high",
    "requirement_ids": ["ID_EXIGENCE_COUVERTE"],
    "ai_confidence": 0.7,
    "rationale": "Pourquoi cette question est importante",
    "tags": ["tag1", "tag2"]
  }}
]
```

⚠️ IMPORTANT :
- CHAQUE question DOIT avoir le requirement_id de l'exigence qu'elle couvre
- Les questions doivent vérifier la conformité de l'organisation à l'exigence
- Varier les types de questions (yes_no, open, single_choice, etc.)

Retourne UNIQUEMENT le JSON, sans texte supplémentaire."""

                # Appeler l'IA
                response = await self.http_client.call_with_retry(second_pass_prompt)

                # Parser la réponse
                parsed = self.parser.parse(response)

                if parsed:
                    enriched = self.parser.coerce_and_enrich_questions(parsed)
                    all_second_pass_questions.extend(enriched)
                    logger.info(f"✅ Deuxième passe batch {idx}/{len(batches)}: {len(enriched)} questions")

            except Exception as e:
                logger.error(f"❌ Erreur deuxième passe batch {idx}: {e}")
                continue

        return all_second_pass_questions

    async def _generate_batches(
        self,
        items: List[Dict[str, Any]],
        language: str,
        progress_callback = None  # Callback pour progression SSE
    ) -> List[Dict[str, Any]]:
        """
        Génère des questions par lots.

        Args:
            items: Liste d'items (exigences avec métadonnées)
            language: Langue

        Returns:
            Liste de toutes les questions générées
        """
        all_questions: List[Dict[str, Any]] = []

        # Découper en batches
        batches = list(self._chunks(items, self.batch_size))
        logger.info(f"📦 {len(batches)} batches de {self.batch_size} max")

        # Callback initial
        if progress_callback:
            await progress_callback(0, len(batches), "started", {
                "total_requirements": len(items),
                "total_batches": len(batches),
                "batch_size": self.batch_size
            })

        for idx, batch in enumerate(batches, 1):
            logger.info(f"🔄 Batch {idx}/{len(batches)} ({len(batch)} items)")

            # Callback avant traitement
            if progress_callback:
                await progress_callback(idx, len(batches), "processing", {
                    "batch_index": idx,
                    "batch_size": len(batch),
                    "current_questions": len(all_questions)
                })

            try:
                # Construire le prompt
                prompt = self.prompt_builder.build_user_prompt_for_requirements(
                    requirements=batch,
                    framework_name="ISO 27001"  # TODO: récupérer depuis DB
                )

                logger.debug(f"📝 Prompt: {len(prompt)} chars")

                # Appeler l'IA
                response = await self.http_client.call_with_retry(prompt)

                # Parser la réponse
                parsed = self.parser.parse(response)

                if parsed:
                    # Enrichir et normaliser
                    enriched = self.parser.coerce_and_enrich_questions(parsed)

                    # ✅ Enrichir avec official_code des requirements du batch
                    # Pour permettre l'extraction du chapter
                    for q in enriched:
                        if isinstance(q, dict) and "official_code" not in q:
                            # Associer à la première requirement du batch par défaut
                            # (idéalement l'IA devrait grouper, mais fallback ici)
                            if batch and len(batch) > 0:
                                q["official_code"] = batch[0].get("official_code")

                    all_questions.extend(enriched)
                    logger.info(f"✅ Batch {idx}: {len(enriched)} questions")

                    # Callback après succès
                    if progress_callback:
                        await progress_callback(idx, len(batches), "batch_complete", {
                            "batch_index": idx,
                            "new_questions": len(enriched),
                            "total_questions": len(all_questions),
                            "progress_percent": int((idx / len(batches)) * 100)
                        })
                else:
                    logger.warning(f"⚠️ Batch {idx}: aucune question parsée")

            except Exception as e:
                logger.error(f"❌ Batch {idx} échoué: {e}")
                continue

        return all_questions

    def _load_framework_and_requirements(self, framework_id: str):
        """
        Charge le framework et ses exigences depuis la DB.

        Args:
            framework_id: ID du framework

        Returns:
            Tuple (framework, requirements)

        Raises:
            ValueError: Si framework inexistant
        """
        from ...models import Framework

        if not framework_id:
            raise ValueError("framework_id requis")

        # Charger framework
        fw = self.db.query(Framework).filter_by(
            id=framework_id,
            is_active=True
        ).first()

        if not fw:
            raise ValueError(f"Framework {framework_id} non trouvé ou inactif")

        # Charger exigences
        reqs = self.db.execute(
            text(
                """
                SELECT id, official_code, title, requirement_text, domain_id,
                       NULL::text as domain, NULL::text as subdomain
                FROM requirement
                WHERE framework_id = :fid AND is_active = true
                ORDER BY official_code NULLS LAST, created_at
                """
            ),
            {"fid": str(fw.id)},
        ).mappings().all()

        # Wrapper pour accès attributs
        class RequirementWrapper:
            def __init__(self, row):
                self.id = row["id"]
                self.official_code = row["official_code"]
                self.title = row["title"]
                self.requirement_text = row["requirement_text"]
                self.domain = row["domain"]
                self.subdomain = row["subdomain"]

        requirements = [RequirementWrapper(r) for r in reqs]
        return fw, requirements

    def _fetch_control_points_for_requirements(
        self,
        requirement_ids: List[str]
    ) -> Dict[str, List[Dict]]:
        """
        Récupère les control points liés aux exigences.

        Args:
            requirement_ids: Liste des IDs d'exigences

        Returns:
            Mapping requirement_id → [control_points]
        """
        if not requirement_ids:
            return {}

        rows = self.db.execute(
            text(
                """
                SELECT
                    rcp.requirement_id,
                    cp.id as cp_id,
                    cp.code as cp_code,
                    cp.name as cp_name,
                    cp.criticality_level
                FROM requirement_control_point rcp
                JOIN control_point cp ON cp.id = rcp.control_point_id
                WHERE rcp.requirement_id::text = ANY(:req_ids)
                AND cp.is_active = true
                ORDER BY rcp.requirement_id, cp.criticality_level DESC
                """
            ),
            {"req_ids": requirement_ids},
        ).mappings().all()

        # Grouper par requirement_id
        cp_map: Dict[str, List[Dict]] = {}
        for row in rows:
            req_id = str(row["requirement_id"])
            if req_id not in cp_map:
                cp_map[req_id] = []

            cp_map[req_id].append({
                "id": row["cp_id"],
                "code": row["cp_code"],
                "name": row["cp_name"],
                "criticality_level": row["criticality_level"] or "MEDIUM"
            })

        return cp_map

    @staticmethod
    def _chunks(items: List, size: int):
        """
        Découpe une liste en chunks de taille size.

        Args:
            items: Liste à découper
            size: Taille des chunks

        Yields:
            Chunks de taille size
        """
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def _merge_unique_questions(
        self,
        q1: List[Dict[str, Any]],
        q2: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Fusionne deux listes de questions en supprimant les doublons.

        Critère: Texte normalisé (lowercase, espaces multiples supprimés)

        Args:
            q1: Première liste
            q2: Deuxième liste

        Returns:
            Liste fusionnée sans doublons
        """
        def normalize_text(s: str) -> str:
            """Normalise le texte pour comparaison"""
            return " ".join((s or "").strip().lower().split())

        seen = set()
        out = []

        for q in (q1 or []):
            text = normalize_text(q.get("text", ""))
            if text and text not in seen:
                seen.add(text)
                out.append(q)

        for q in (q2 or []):
            text = normalize_text(q.get("text", ""))
            if text and text not in seen:
                seen.add(text)
                out.append(q)

        return out

    def ensure_minimum_questions(
        self,
        questions: List[Dict[str, Any]],
        requirements: List[Dict[str, Any]],
        min_count: int = 8
    ) -> List[Dict[str, Any]]:
        """
        Garantit un nombre minimum de questions via fallback algorithmique.

        Si l'IA génère trop peu de questions, complète avec des templates
        standards dérivés des exigences.

        Args:
            questions: Questions générées par l'IA
            requirements: Exigences source
            min_count: Nombre minimum requis

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

        # Échantillonner les exigences
        sample = self._pick_requirement_sample(
            requirements,
            max_reqs=min(needed * 2, 12)
        )

        # Générer templates
        templates = self._generate_template_questions(sample)

        # Fusionner sans doublons
        completed = self._merge_unique_questions(questions, templates)

        return completed[:max(min_count, len(completed))]

    def _pick_requirement_sample(
        self,
        requirements: List[Dict[str, Any]],
        max_reqs: int = 16
    ) -> List[Dict[str, Any]]:
        """
        Échantillonne les exigences de manière déterministe.

        Stratégie: Répartition uniforme sur toute la liste

        Args:
            requirements: Liste complète
            max_reqs: Nombre max à retourner

        Returns:
            Échantillon représentatif
        """
        n = len(requirements)
        if n <= max_reqs:
            return list(requirements)

        step = max(1, n // max_reqs)
        sample = []
        idx = 0

        while len(sample) < max_reqs and idx < n:
            sample.append(requirements[idx])
            idx += step

        # Compléter avec la fin si nécessaire
        i = n - 1
        while len(sample) < max_reqs and i >= 0:
            if requirements[i] not in sample:
                sample.append(requirements[i])
            i -= 1

        return sample[:max_reqs]

    def _generate_template_questions(
        self,
        requirements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Génère des questions templates depuis les exigences.

        5 templates par exigence:
        - Existence de procédure
        - Date dernière revue
        - Éléments de preuve
        - Niveau de mise en œuvre
        - Nombre d'incidents

        Args:
            requirements: Exigences sources

        Returns:
            Liste de questions templates
        """
        templates = []

        for r in requirements:
            title = (r.get("title") or "").strip()
            domain = r.get("domain")
            req_id = r.get("anchor_id") or r.get("id")
            short = title[:60] if title else "exigence"

            templates.extend([
                {
                    "id": str(uuid4()),
                    "text": f"Disposez-vous d'une procédure formalisée pour « {short} » ?",
                    "type": "yes_no",
                    "options": [],
                    "help_text": "Procédure documentée, validée et diffusée.",
                    "difficulty": "low",
                    "domain": domain,
                    "requirement_ids": [req_id] if req_id else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": ["procédure", "documentation"]
                },
                {
                    "id": str(uuid4()),
                    "text": f"Quand la dernière revue liée à « {short} » a-t-elle été réalisée ?",
                    "type": "date",
                    "options": [],
                    "help_text": "Indiquez la date de la dernière revue ou audit interne.",
                    "difficulty": "medium",
                    "domain": domain,
                    "requirement_ids": [req_id] if req_id else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": ["revue", "audit"]
                },
                {
                    "id": str(uuid4()),
                    "text": f"Quels éléments de preuve pouvez-vous fournir concernant « {short} » ?",
                    "type": "open",
                    "options": [],
                    "help_text": "Ex: procédures, rapports, tickets, journaux.",
                    "difficulty": "medium",
                    "domain": domain,
                    "requirement_ids": [req_id] if req_id else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": ["preuve", "conformité"]
                },
                {
                    "id": str(uuid4()),
                    "text": f"Quel est le niveau de mise en œuvre actuel pour « {short} » ?",
                    "type": "single_choice",
                    "options": [
                        "Non démarré",
                        "En cours",
                        "Partiellement en place",
                        "Mis en œuvre",
                        "Optimisé"
                    ],
                    "help_text": "Auto-évaluation du niveau de maturité.",
                    "difficulty": "low",
                    "domain": domain,
                    "requirement_ids": [req_id] if req_id else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": ["maturité", "implémentation"]
                },
                {
                    "id": str(uuid4()),
                    "text": f"Indiquez le nombre d'incidents liés à « {short} » sur les 12 derniers mois.",
                    "type": "number",
                    "options": [],
                    "help_text": "Saisir une valeur entière (0 si aucun).",
                    "difficulty": "medium",
                    "domain": domain,
                    "requirement_ids": [req_id] if req_id else [],
                    "ai_confidence": 0.6,
                    "rationale": "",
                    "tags": ["incidents", "métriques"]
                },
            ])

        return templates
