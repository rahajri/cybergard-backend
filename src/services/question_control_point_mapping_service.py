"""
Service de mapping automatique Question → Control Points via IA

Ce service utilise l'IA pour analyser chaque question et identifier
tous les control points pertinents (relation many-to-many).
"""

import json
import logging
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session
import httpx

logger = logging.getLogger(__name__)


class QuestionControlPointMappingService:
    """Service pour mapper automatiquement questions et control points via IA"""

    def __init__(self, db: Session, deepseek_api_key: str):
        self.db = db
        self.api_key = deepseek_api_key
        self.api_url = "https://api.deepseek.com/v1/chat/completions"

    async def map_all_questions(self, questionnaire_id: str = None, limit: int = None) -> Dict[str, Any]:
        """
        Mapper toutes les questions d'un questionnaire (ou toutes les questions)

        Args:
            questionnaire_id: UUID du questionnaire (optionnel, si None = toutes les questions)
            limit: Limite du nombre de questions à traiter (optionnel, pour tests)

        Returns:
            Statistiques du mapping
        """
        logger.info(f"🔄 Début du mapping automatique Question → Control Points")

        # 1. Récupérer toutes les questions
        query_parts = ["SELECT id, question_text, questionnaire_id FROM question WHERE is_active = true"]

        if questionnaire_id:
            query_parts.append(f"AND questionnaire_id = CAST('{questionnaire_id}' AS uuid)")

        if limit:
            query_parts.append(f"LIMIT {limit}")

        query = text(" ".join(query_parts))
        questions = self.db.execute(query).fetchall()

        logger.info(f"📊 {len(questions)} questions à traiter")

        # 2. Récupérer tous les control points disponibles
        control_points = self._get_all_control_points()
        logger.info(f"📋 {len(control_points)} control points disponibles")

        # 3. Traiter chaque question
        stats = {
            "total_questions": len(questions),
            "processed": 0,
            "errors": 0,
            "total_mappings_created": 0,
            "questions_with_multiple_cps": 0
        }

        for idx, question in enumerate(questions, 1):
            question_id = str(question[0])
            question_text = question[1]

            logger.info(f"\n[{idx}/{len(questions)}] Question: {question_text[:60]}...")

            try:
                # Utiliser l'IA pour identifier les control points pertinents
                mapped_cp_ids = await self._map_question_to_control_points(
                    question_text=question_text,
                    available_control_points=control_points
                )

                if mapped_cp_ids:
                    # Insérer les mappings dans la BDD
                    inserted_count = self._insert_mappings(question_id, mapped_cp_ids)

                    stats["processed"] += 1
                    stats["total_mappings_created"] += inserted_count

                    if len(mapped_cp_ids) > 1:
                        stats["questions_with_multiple_cps"] += 1

                    logger.info(f"   ✅ {len(mapped_cp_ids)} control points mappés")
                else:
                    logger.warning(f"   ⚠️ Aucun control point identifié par l'IA")
                    stats["processed"] += 1

            except Exception as e:
                logger.error(f"   ❌ Erreur: {e}")
                stats["errors"] += 1

        logger.info(f"\n✅ Mapping terminé:")
        logger.info(f"   - Questions traitées: {stats['processed']}/{stats['total_questions']}")
        logger.info(f"   - Mappings créés: {stats['total_mappings_created']}")
        logger.info(f"   - Questions avec plusieurs CPs: {stats['questions_with_multiple_cps']}")
        logger.info(f"   - Erreurs: {stats['errors']}")

        return stats

    def _get_all_control_points(self) -> List[Dict[str, Any]]:
        """Récupérer tous les control points avec leurs métadonnées"""

        query = text("""
            SELECT
                cp.id,
                cp.control_id,
                cp.title,
                cp.description,
                r.name as referential_name,
                r.code as referential_code
            FROM control_point cp
            LEFT JOIN referential r ON cp.referential_id = r.id
            WHERE cp.is_active = true
            ORDER BY r.name, cp.control_id
        """)

        results = self.db.execute(query).fetchall()

        return [
            {
                "id": str(row[0]),
                "control_id": row[1],
                "title": row[2],
                "description": row[3] or "",
                "referential_name": row[4] or "",
                "referential_code": row[5] or ""
            }
            for row in results
        ]

    async def _map_question_to_control_points(
        self,
        question_text: str,
        available_control_points: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Utiliser l'IA pour identifier les control points pertinents pour une question

        Args:
            question_text: Texte de la question
            available_control_points: Liste de tous les CPs disponibles

        Returns:
            Liste des IDs de control points pertinents
        """

        # Préparer le prompt pour l'IA
        control_points_list = "\n".join([
            f"- ID: {cp['id']}\n  Code: {cp['control_id']}\n  Titre: {cp['title']}\n  Description: {cp['description'][:100]}...\n  Référentiel: {cp['referential_name']}"
            for cp in available_control_points[:50]  # Limiter à 50 pour ne pas dépasser les tokens
        ])

        prompt = f"""Tu es un expert en cybersécurité et en conformité.

MISSION: Identifier TOUS les control points (points de contrôle) pertinents pour la question d'audit suivante.

QUESTION D'AUDIT:
"{question_text}"

CONTROL POINTS DISPONIBLES:
{control_points_list}

INSTRUCTIONS:
1. Analyse la question et identifie TOUS les control points qui sont directement ou indirectement liés
2. Un control point est pertinent si la réponse à la question permet de vérifier sa conformité
3. Retourne UNIQUEMENT les IDs des control points pertinents (entre 1 et 5 maximum)
4. Si aucun control point n'est pertinent, retourne une liste vide

FORMAT DE RÉPONSE (JSON uniquement):
{{
  "control_point_ids": ["uuid-1", "uuid-2", ...],
  "justification": "Courte explication du choix"
}}

Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

        # Appel à l'API DeepSeek
        async with httpx.AsyncClient(timeout=30.0) as client:
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
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,  # Faible température pour plus de cohérence
                        "max_tokens": 500
                    }
                )

                if response.status_code != 200:
                    logger.error(f"Erreur API DeepSeek: {response.status_code} - {response.text}")
                    return []

                result = response.json()
                ai_response = result["choices"][0]["message"]["content"]

                # Parser la réponse JSON
                try:
                    # Nettoyer la réponse (enlever les markdown code blocks si présents)
                    ai_response = ai_response.strip()
                    if ai_response.startswith("```json"):
                        ai_response = ai_response[7:]
                    if ai_response.startswith("```"):
                        ai_response = ai_response[3:]
                    if ai_response.endswith("```"):
                        ai_response = ai_response[:-3]

                    parsed = json.loads(ai_response.strip())
                    control_point_ids = parsed.get("control_point_ids", [])
                    justification = parsed.get("justification", "")

                    logger.debug(f"      IA: {justification}")

                    # Valider que les IDs existent dans la liste
                    valid_ids = [
                        cp_id for cp_id in control_point_ids
                        if any(cp["id"] == cp_id for cp in available_control_points)
                    ]

                    return valid_ids

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
        """
        Insérer les mappings dans la table question_control_point

        Args:
            question_id: UUID de la question
            control_point_ids: Liste des UUIDs des control points

        Returns:
            Nombre de mappings créés
        """
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
