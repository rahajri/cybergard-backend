"""
Service de mapping automatique Question → Control Points via IA (Version améliorée)

Cette version utilise :
1. Le requirement déjà lié à la question comme point de départ
2. Les control points du même référentiel/domaine
3. L'analyse sémantique pour identifier les CPs pertinents
"""

import json
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
import httpx

logger = logging.getLogger(__name__)


class QuestionControlPointMappingServiceV2:
    """Service amélioré pour mapper automatiquement questions et control points via IA"""

    def __init__(self, db: Session, deepseek_api_key: str):
        self.db = db
        self.api_key = deepseek_api_key
        self.api_url = "https://api.deepseek.com/v1/chat/completions"

    async def map_all_questions(
        self,
        questionnaire_id: Optional[str] = None,
        limit: Optional[int] = None,
        skip_existing: bool = True
    ) -> Dict[str, Any]:
        """
        Mapper toutes les questions avec une stratégie intelligente

        Args:
            questionnaire_id: UUID du questionnaire (optionnel)
            limit: Limite du nombre de questions (optionnel)
            skip_existing: Ignorer les questions qui ont déjà des mappings

        Returns:
            Statistiques du mapping
        """
        logger.info(f"🔄 Début du mapping intelligent Question → Control Points")

        # 1. Récupérer les questions avec leur contexte (requirement, domaine, etc.)
        questions = self._get_questions_with_context(questionnaire_id, limit, skip_existing)

        logger.info(f"📊 {len(questions)} questions à traiter")

        # 2. Statistiques
        stats = {
            "total_questions": len(questions),
            "processed": 0,
            "skipped_no_requirement": 0,
            "skipped_no_control_points": 0,
            "errors": 0,
            "total_mappings_created": 0,
            "questions_with_multiple_cps": 0,
            "ai_calls": 0
        }

        # 3. Traiter chaque question
        for idx, question in enumerate(questions, 1):
            question_id = str(question['id'])
            question_text = question['text']
            requirement_id = question.get('requirement_id')
            requirement_text = question.get('requirement_text', '')

            logger.info(f"\n[{idx}/{len(questions)}] Question: {question_text[:60]}...")

            # Si pas de requirement lié, on skip (impossible de déterminer le contexte)
            if not requirement_id:
                logger.warning(f"   ⚠️ Pas de requirement lié, skip")
                stats['skipped_no_requirement'] += 1
                continue

            try:
                # Étape 1: Récupérer les control points candidats (même référentiel que le requirement)
                candidate_cps = self._get_candidate_control_points(requirement_id)

                if not candidate_cps:
                    logger.warning(f"   ⚠️ Aucun control point candidat trouvé")
                    stats['skipped_no_control_points'] += 1
                    continue

                logger.info(f"   📋 {len(candidate_cps)} control points candidats")

                # Étape 2: Utiliser l'IA pour sélectionner les CPs vraiment pertinents
                selected_cp_ids = await self._select_relevant_control_points(
                    question_text=question_text,
                    requirement_text=requirement_text,
                    candidate_control_points=candidate_cps
                )

                stats['ai_calls'] += 1

                if selected_cp_ids:
                    # Étape 3: Insérer les mappings
                    inserted_count = self._insert_mappings(question_id, selected_cp_ids)

                    stats['processed'] += 1
                    stats['total_mappings_created'] += inserted_count

                    if len(selected_cp_ids) > 1:
                        stats['questions_with_multiple_cps'] += 1

                    logger.info(f"   ✅ {len(selected_cp_ids)} control points mappés")
                else:
                    logger.info(f"   ℹ️  Aucun CP supplémentaire identifié")
                    stats['processed'] += 1

            except Exception as e:
                logger.error(f"   ❌ Erreur: {e}")
                stats['errors'] += 1

        # 4. Afficher les résultats
        logger.info(f"\n✅ Mapping terminé:")
        logger.info(f"   - Questions traitées: {stats['processed']}/{stats['total_questions']}")
        logger.info(f"   - Questions skipped (pas de requirement): {stats['skipped_no_requirement']}")
        logger.info(f"   - Questions skipped (pas de CP candidat): {stats['skipped_no_control_points']}")
        logger.info(f"   - Mappings créés: {stats['total_mappings_created']}")
        logger.info(f"   - Questions avec plusieurs CPs: {stats['questions_with_multiple_cps']}")
        logger.info(f"   - Appels IA: {stats['ai_calls']}")
        logger.info(f"   - Erreurs: {stats['errors']}")

        return stats

    def _get_questions_with_context(
        self,
        questionnaire_id: Optional[str],
        limit: Optional[int],
        skip_existing: bool
    ) -> List[Dict[str, Any]]:
        """
        Récupérer les questions avec leur contexte complet
        (requirement, domaine, control points existants)
        """

        query_parts = ["""
            SELECT DISTINCT
                q.id,
                q.question_text,
                q.requirement_id,
                r.title as requirement_text,
                r.requirement_code,
                d.name as domain_name,
                rf.name as referential_name,
                rf.id as referential_id,
                (
                    SELECT COUNT(*)
                    FROM question_control_point qcp
                    WHERE qcp.question_id = q.id
                ) as existing_mappings_count
            FROM question q
            LEFT JOIN requirement r ON q.requirement_id = r.id
            LEFT JOIN domain d ON r.domain_id = d.id
            LEFT JOIN referential rf ON r.referential_id = rf.id
            WHERE q.is_active = true
        """]

        if questionnaire_id:
            query_parts.append(f"AND q.questionnaire_id = CAST('{questionnaire_id}' AS uuid)")

        if skip_existing:
            query_parts.append("""
                AND NOT EXISTS (
                    SELECT 1 FROM question_control_point qcp2
                    WHERE qcp2.question_id = q.id
                )
            """)

        query_parts.append("ORDER BY q.created_at")

        if limit:
            query_parts.append(f"LIMIT {limit}")

        query = text(" ".join(query_parts))
        results = self.db.execute(query).fetchall()

        return [
            {
                "id": row[0],
                "text": row[1],
                "requirement_id": row[2],
                "requirement_text": row[3],
                "requirement_code": row[4],
                "domain_name": row[5],
                "referential_name": row[6],
                "referential_id": row[7],
                "existing_mappings_count": row[8]
            }
            for row in results
        ]

    def _get_candidate_control_points(self, requirement_id: str) -> List[Dict[str, Any]]:
        """
        Récupérer les control points candidats basés sur le requirement

        Stratégie:
        1. Tous les CPs du même référentiel que le requirement
        2. Les CPs du même domaine en priorité
        """

        query = text("""
            SELECT DISTINCT
                cp.id,
                cp.control_id,
                cp.title,
                cp.description,
                cp.category,
                r.name as referential_name,
                d.name as domain_name,
                CASE
                    WHEN cp.domain_id = req.domain_id THEN 1  -- Même domaine = priorité haute
                    ELSE 2
                END as priority
            FROM control_point cp
            JOIN referential r ON cp.referential_id = r.id
            LEFT JOIN domain d ON cp.domain_id = d.id
            CROSS JOIN requirement req
            WHERE req.id = CAST(:requirement_id AS uuid)
              AND cp.referential_id = req.referential_id
              AND cp.is_active = true
            ORDER BY priority, cp.control_id
        """)

        results = self.db.execute(query, {"requirement_id": requirement_id}).fetchall()

        return [
            {
                "id": str(row[0]),
                "control_id": row[1],
                "title": row[2],
                "description": row[3] or "",
                "category": row[4] or "",
                "referential_name": row[5],
                "domain_name": row[6] or "",
                "priority": row[7]
            }
            for row in results
        ]

    async def _select_relevant_control_points(
        self,
        question_text: str,
        requirement_text: str,
        candidate_control_points: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Utiliser l'IA pour sélectionner les control points vraiment pertinents

        Args:
            question_text: Texte de la question
            requirement_text: Texte du requirement lié
            candidate_control_points: Liste des CPs candidats (déjà filtrés par référentiel)

        Returns:
            Liste des IDs de control points pertinents
        """

        # Limiter à 30 CPs max pour le prompt (éviter de dépasser les tokens)
        candidates = candidate_control_points[:30]

        # Préparer la liste des CPs pour le prompt
        cp_list = []
        for idx, cp in enumerate(candidates, 1):
            cp_list.append(
                f"{idx}. [{cp['control_id']}] {cp['title']}\n"
                f"   Description: {cp['description'][:150]}...\n"
                f"   Catégorie: {cp['category']}\n"
                f"   Domaine: {cp['domain_name']}"
            )

        cp_list_str = "\n\n".join(cp_list)

        prompt = f"""Tu es un expert en cybersécurité et conformité réglementaire.

CONTEXTE:
Requirement: {requirement_text}

QUESTION D'AUDIT:
"{question_text}"

CONTROL POINTS CANDIDATS (même référentiel):
{cp_list_str}

MISSION:
Identifie les control points qui sont DIRECTEMENT vérifiés par cette question d'audit.

CRITÈRES DE SÉLECTION:
1. La réponse à la question permet de vérifier la conformité du control point
2. Le control point est EXPLICITEMENT mentionné ou fortement impliqué dans la question
3. Il existe un lien logique clair entre la question et le contrôle

INSTRUCTIONS:
- Sélectionne entre 1 et 5 control points maximum
- Privilégie la PRÉCISION à la quantité (mieux vaut 1 CP très pertinent que 5 moyennement pertinents)
- Si aucun CP n'est vraiment pertinent, retourne une liste vide
- Retourne UNIQUEMENT les numéros des control points pertinents

FORMAT DE RÉPONSE (JSON uniquement):
{{
  "selected_indices": [1, 3, 5],
  "justification": "Brève explication (1 phrase par CP)"
}}

Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

        # Appel à l'API DeepSeek
        async with httpx.AsyncClient(timeout=45.0) as client:
            try:
                response = await client.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {
                                "role": "system",
                                "content": "Tu es un expert en cybersécurité et conformité. Tu réponds UNIQUEMENT en JSON valide, sans markdown."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.2,  # Très faible pour cohérence maximale
                        "max_tokens": 800
                    }
                )

                if response.status_code != 200:
                    logger.error(f"Erreur API DeepSeek: {response.status_code} - {response.text}")
                    return []

                result = response.json()
                ai_response = result["choices"][0]["message"]["content"]

                # Parser la réponse JSON
                try:
                    # Nettoyer la réponse
                    ai_response = ai_response.strip()
                    if ai_response.startswith("```json"):
                        ai_response = ai_response[7:]
                    if ai_response.startswith("```"):
                        ai_response = ai_response[3:]
                    if ai_response.endswith("```"):
                        ai_response = ai_response[:-3]

                    parsed = json.loads(ai_response.strip())
                    selected_indices = parsed.get("selected_indices", [])
                    justification = parsed.get("justification", "")

                    if justification:
                        logger.debug(f"      IA: {justification}")

                    # Convertir les indices en IDs
                    selected_ids = []
                    for idx in selected_indices:
                        if 1 <= idx <= len(candidates):
                            selected_ids.append(candidates[idx - 1]["id"])

                    return selected_ids

                except json.JSONDecodeError as e:
                    logger.error(f"Erreur parsing JSON IA: {e}")
                    logger.debug(f"Réponse IA: {ai_response}")
                    return []

            except httpx.TimeoutException:
                logger.error("Timeout API DeepSeek")
                return []
            except Exception as e:
                logger.error(f"Erreur appel API: {e}")
                return []

    def _insert_mappings(self, question_id: str, control_point_ids: List[str]) -> int:
        """Insérer les mappings dans la table question_control_point"""

        inserted = 0

        for cp_id in control_point_ids:
            try:
                self.db.execute(text("""
                    INSERT INTO question_control_point (question_id, control_point_id)
                    VALUES (CAST(:question_id AS uuid), CAST(:control_point_id AS uuid))
                    ON CONFLICT (question_id, control_point_id) DO NOTHING
                """), {
                    "question_id": question_id,
                    "control_point_id": cp_id
                })
                inserted += 1
            except Exception as e:
                logger.error(f"Erreur insertion mapping: {e}")

        self.db.commit()
        return inserted
