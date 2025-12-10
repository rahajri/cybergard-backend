"""
Control Point Matcher

Matching intelligent question ↔ point de contrôle avec scoring.

Stratégies:
1. Lexical scoring (rapide): Keywords + Jaccard similarity
2. Semantic scoring (optionnel): Embeddings + cosine similarity

Version: 1.0
Date: 2025-01-08
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class ControlPointMatcher:
    """
    Matcher pour assigner automatiquement des control points aux questions.

    Workflow:
    1. Charger les CP liés aux exigences (via requirement_control_point)
    2. Pour chaque question, scorer tous les CP candidats
    3. Assigner le meilleur CP (score > seuil)
    """

    def __init__(self, db_session: Session, use_semantic: bool = False):
        """
        Initialise le matcher.

        Args:
            db_session: Session SQLAlchemy
            use_semantic: Activer scoring sémantique (embeddings)
        """
        self.db = db_session
        self.use_semantic = use_semantic
        self.embedding_service = None

        if use_semantic:
            try:
                from .embedding_service import EmbeddingService
                self.embedding_service = EmbeddingService()
                logger.info("✅ Semantic matching activé")
            except ImportError:
                logger.warning("⚠️ EmbeddingService non disponible, mode lexical uniquement")
                self.use_semantic = False

    async def assign_control_points(
        self,
        questions: List[Dict[str, Any]],
        requirement_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Enrichit les questions avec control_point_id.

        Stratégie:
        1. Collecter requirement_ids depuis les questions
        2. Charger CP liés via requirement_control_point
        3. Scorer et assigner meilleur CP par question

        Args:
            questions: Liste de questions (dict)
            requirement_ids: IDs additionnels à considérer

        Returns:
            Questions enrichies avec control_point_id
        """
        if not questions:
            return questions

        # 1. Collecter requirement_ids valides
        req_ids = self._collect_requirement_ids(questions, requirement_ids)

        if not req_ids:
            logger.warning("⚠️ Aucun requirement_id valide, skip matching")
            return questions

        # 2. Charger CP liés
        cp_by_req = self._fetch_control_points_for_requirements(list(req_ids))

        logger.info(f"📊 {len(cp_by_req)} requirements → CPs chargés")

        # 3. Assigner meilleur CP par question
        out: List[Dict[str, Any]] = []
        for q in questions:
            if q.get("control_point_id"):
                # Déjà assigné
                out.append(q)
                continue

            q_text = (q.get("text") or q.get("question_text") or "").strip()
            if not q_text:
                out.append(q)
                continue

            # Collecter candidats depuis requirements
            candidates = self._get_candidate_control_points(
                q, cp_by_req
            )

            if not candidates:
                out.append(q)
                continue

            # Scorer et sélectionner meilleur
            best_cp, best_score = await self._rank_control_points(
                q_text, candidates
            )

            if best_cp and best_score > 0.1:  # Seuil minimal
                q["control_point_id"] = str(best_cp["id"])
                logger.debug(
                    f"✅ Q: {q_text[:50]}... → CP: {best_cp.get('name', 'N/A')} "
                    f"(score: {best_score:.2f})"
                )
            else:
                logger.debug(f"⚠️ Aucun CP pertinent pour: {q_text[:50]}...")

            out.append(q)

        matched_count = sum(1 for q in out if q.get("control_point_id"))
        logger.info(f"✅ {matched_count}/{len(out)} questions matchées à un CP")

        return out

    def _collect_requirement_ids(
        self,
        questions: List[Dict[str, Any]],
        additional_ids: Optional[List[str]] = None
    ) -> set:
        """
        Collecte et valide les requirement_ids.

        Args:
            questions: Questions sources
            additional_ids: IDs additionnels

        Returns:
            Set d'IDs valides (format UUID)
        """
        import uuid as uuid_lib

        req_ids = set()

        # Depuis questions
        for q in questions:
            for rid in q.get("requirement_ids", []) or []:
                rid_s = str(rid).strip()
                if self._is_valid_uuid(rid_s):
                    req_ids.add(rid_s)

        # Additionnels
        if additional_ids:
            for rid in additional_ids:
                rid_s = str(rid).strip()
                if self._is_valid_uuid(rid_s):
                    req_ids.add(rid_s)

        return req_ids

    @staticmethod
    def _is_valid_uuid(s: str) -> bool:
        """
        Valide un UUID.

        Args:
            s: String à valider

        Returns:
            True si UUID valide
        """
        import uuid as uuid_lib

        if not s or len(s) != 36 or s.count('-') != 4:
            return False

        try:
            uuid_lib.UUID(s)
            return True
        except (ValueError, AttributeError):
            return False

    def _fetch_control_points_for_requirements(
        self,
        requirement_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Charge les control points liés aux exigences.

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
                    cp.description as cp_description,
                    cp.category as cp_category,
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
        cp_map: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            req_id = str(row["requirement_id"])
            if req_id not in cp_map:
                cp_map[req_id] = []

            cp_map[req_id].append({
                "id": row["cp_id"],
                "code": row["cp_code"],
                "name": row["cp_name"],
                "description": row["cp_description"] or "",
                "category": row["cp_category"],
                "criticality_level": row["criticality_level"] or "MEDIUM"
            })

        return cp_map

    def _get_candidate_control_points(
        self,
        question: Dict[str, Any],
        cp_by_req: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Collecte les CP candidats depuis les requirement_ids de la question.

        Args:
            question: Question dict
            cp_by_req: Mapping requirement → CPs

        Returns:
            Liste unique de CP candidats
        """
        candidates: List[Dict[str, Any]] = []

        for rid in question.get("requirement_ids", []) or []:
            rid_s = str(rid).strip()
            candidates.extend(cp_by_req.get(rid_s, []))

        # Dédupliquer par id
        seen = set()
        unique = []
        for cp in candidates:
            cid = cp.get("id")
            if cid and cid not in seen:
                seen.add(cid)
                unique.append(cp)

        return unique

    async def _rank_control_points(
        self,
        question_text: str,
        candidates: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], float]:
        """
        Classe les CP candidats par score de pertinence.

        Stratégies:
        1. Lexical scoring (toujours actif)
        2. Semantic scoring (si activé)

        Args:
            question_text: Texte de la question
            candidates: Liste de CP candidats

        Returns:
            Tuple (meilleur_cp, score)
        """
        if not candidates:
            return None, -1.0

        q = question_text.lower().strip()
        if not q:
            return candidates[0], 0.0

        # Mode sémantique
        if self.use_semantic and self.embedding_service:
            return await self._semantic_ranking(question_text, candidates)

        # Mode lexical (fallback)
        return self._lexical_ranking(q, candidates)

    def _lexical_ranking(
        self,
        question_text: str,
        candidates: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], float]:
        """
        Scoring lexical rapide.

        Méthode:
        - Keywords matching (auth, backup, log, etc.)
        - Jaccard similarity sur mots

        Args:
            question_text: Question (lowercase)
            candidates: CP candidats

        Returns:
            Tuple (meilleur_cp, score)
        """
        def lexical_score(cp: Dict[str, Any]) -> float:
            """Calcule le score lexical"""
            cp_text = f"{cp.get('name', '')} {cp.get('description', '')}".lower()
            score = 0.0

            # Keywords matching
            keywords = [
                "auth", "mfa", "pwd", "password", "backup", "sauvegarde",
                "journal", "log", "incident", "patch", "vpn", "firewall",
                "antivirus", "chiffrement", "encrypt", "access", "accès",
                "contrôle", "audit", "sécurité", "security"
            ]

            for term in keywords:
                if term in question_text and term in cp_text:
                    score += 1.0

            # Jaccard similarity
            q_words = set(question_text.split())
            cp_words = set(cp_text.split())

            if q_words and cp_words:
                intersection = len(q_words & cp_words)
                union = len(q_words | cp_words)
                jaccard = intersection / max(1, union)
                score += jaccard * 5.0  # Poids Jaccard

            return score

        # Trier par score décroissant
        ranked = sorted(candidates, key=lexical_score, reverse=True)
        best = ranked[0]
        best_score = lexical_score(best)

        return best, best_score

    async def _semantic_ranking(
        self,
        question_text: str,
        candidates: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], float]:
        """
        Scoring sémantique via embeddings.

        Méthode:
        - Générer embedding de la question
        - Générer embeddings des CP
        - Calculer cosine similarity
        - Retourner meilleur match

        Args:
            question_text: Question
            candidates: CP candidats

        Returns:
            Tuple (meilleur_cp, score)
        """
        if not self.embedding_service:
            return self._lexical_ranking(question_text.lower(), candidates)

        try:
            # Embedding de la question
            q_embedding = await self.embedding_service.generate_embedding(question_text)

            best_cp = None
            best_score = -1.0

            for cp in candidates:
                cp_text = f"{cp.get('name', '')} {cp.get('description', '')}"

                # Embedding du CP
                cp_embedding = await self.embedding_service.generate_embedding(cp_text)

                # Similarité cosine
                similarity = self.embedding_service.compute_similarity(
                    q_embedding, cp_embedding
                )

                if similarity > best_score:
                    best_cp = cp
                    best_score = similarity

            return best_cp, best_score

        except Exception as e:
            logger.warning(f"⚠️ Semantic ranking failed: {e}, fallback lexical")
            return self._lexical_ranking(question_text.lower(), candidates)
