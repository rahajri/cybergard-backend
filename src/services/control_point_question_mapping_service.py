"""
Service de mapping automatique Control Point → Questions via IA

Ce service implémente le mapping décrit dans mapping.md :
- Cible: nouveaux PCs non couverts (sans aucun mapping vers une question)
- Réutilise uniquement des questions existantes
- Utilise la vue cross-référentiels pour les équivalences de PCs
- Ne modifie jamais les mappings existants
- Ne crée jamais de nouvelles questions

Architecture:
    Control Point (non couvert) → (AI mapping) → Questions existantes
"""

import json
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
import httpx

logger = logging.getLogger(__name__)


class ControlPointQuestionMappingService:
    """Service pour mapper automatiquement control points vers questions existantes via IA"""

    def __init__(self, db: Session, deepseek_api_key: str):
        self.db = db
        self.api_key = deepseek_api_key
        self.api_url = "https://api.deepseek.com/v1/chat/completions"

    async def map_control_points_to_questions(
        self,
        questionnaire_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Mapper les control points non couverts vers des questions existantes

        Args:
            questionnaire_id: UUID du questionnaire (si None = tous les questionnaires "modèles")
            limit: Limite du nombre de PCs à traiter (pour tests)

        Returns:
            Statistiques du mapping
        """
        logger.info(f"🔄 Début du mapping Control Points → Questions")

        # 1. Récupérer les questionnaires concernés
        questionnaires = self._get_target_questionnaires(questionnaire_id)
        logger.info(f"📊 {len(questionnaires)} questionnaire(s) à analyser")

        if not questionnaires:
            logger.warning("⚠️  Aucun questionnaire trouvé")
            return {
                "error": "No questionnaires found",
                "questionnaires_analyzed": 0,
                "total_mappings_created": 0,
                "total_pcs_uncovered": 0,
                "ai_calls": 0,
                "errors": 0
            }

        # 2. Statistiques globales
        stats = {
            "questionnaires_analyzed": 0,
            "total_mappings_created": 0,
            "total_pcs_uncovered": 0,
            "ai_calls": 0,
            "errors": 0,
            "details": []
        }

        # 3. Traiter chaque questionnaire
        for idx, questionnaire in enumerate(questionnaires, 1):
            q_id = questionnaire['id']
            q_name = questionnaire['name']

            logger.info(f"\n[{idx}/{len(questionnaires)}] Questionnaire: {q_name}")

            try:
                # Étape 1: Récupérer les PCs attendus pour ce questionnaire
                expected_pcs = self._get_expected_control_points(q_id)
                logger.info(f"   📋 {len(expected_pcs)} PCs attendus")

                # Étape 2: Récupérer les PCs déjà couverts
                covered_pcs = self._get_covered_control_points(q_id)
                logger.info(f"   ✅ {len(covered_pcs)} PCs déjà couverts")

                # Étape 3: Calculer les PCs à traiter
                pcs_to_process = [pc for pc in expected_pcs if str(pc['id']) not in covered_pcs]

                # Appliquer la limite si spécifiée
                if limit and len(pcs_to_process) > limit:
                    pcs_to_process = pcs_to_process[:limit]

                if not pcs_to_process:
                    logger.info(f"   ℹ️  Aucun PC à mapper (tous déjà couverts)")
                    continue

                logger.info(f"   🎯 {len(pcs_to_process)} PCs à mapper")

                # Étape 4: Récupérer toutes les questions du questionnaire
                questions = self._get_questionnaire_questions(q_id)
                logger.info(f"   ❓ {len(questions)} questions disponibles")

                if not questions:
                    logger.warning(f"   ⚠️  Aucune question trouvée, skip")
                    continue

                # Étape 5: Récupérer les équivalences cross-référentiels (optionnel)
                crossrefs = self._get_crossref_equivalences([pc['id'] for pc in pcs_to_process])

                # Étape 6: Appeler l'IA pour le mapping
                ai_mappings = await self._map_pcs_to_questions_ai(
                    questionnaire=questionnaire,
                    pcs_to_process=pcs_to_process,
                    questions=questions,
                    crossrefs=crossrefs
                )

                stats['ai_calls'] += 1

                # Étape 7: Créer les mappings
                mappings_created = 0
                pcs_uncovered = 0

                for mapping in ai_mappings:
                    pc_id = mapping.get('pc_id')
                    question_ids = mapping.get('matched_question_ids', [])

                    if not question_ids:
                        pcs_uncovered += 1
                        logger.debug(f"      ℹ️  PC {pc_id}: aucune question identifiée")
                        continue

                    # Insérer les mappings
                    for question_id in question_ids:
                        created = self._insert_mapping_if_not_exists(question_id, pc_id)
                        if created:
                            mappings_created += 1

                    logger.info(f"      ✅ PC {pc_id}: {len(question_ids)} question(s) mappée(s)")

                # Mettre à jour les stats
                stats['questionnaires_analyzed'] += 1
                stats['total_mappings_created'] += mappings_created
                stats['total_pcs_uncovered'] += pcs_uncovered

                stats['details'].append({
                    "questionnaire_id": q_id,
                    "questionnaire_name": q_name,
                    "pcs_processed": len(pcs_to_process),
                    "mappings_created": mappings_created,
                    "pcs_uncovered": pcs_uncovered
                })

                logger.info(f"   ✅ {mappings_created} nouveaux mappings créés")
                logger.info(f"   ⚠️  {pcs_uncovered} PCs restent non couverts")

            except Exception as e:
                logger.error(f"   ❌ Erreur: {e}", exc_info=True)
                stats['errors'] += 1

        # 4. Afficher les résultats
        logger.info(f"\n✅ Mapping terminé:")
        logger.info(f"   - Questionnaires analysés: {stats['questionnaires_analyzed']}")
        logger.info(f"   - Nouveaux mappings créés: {stats['total_mappings_created']}")
        logger.info(f"   - PCs non couverts: {stats['total_pcs_uncovered']}")
        logger.info(f"   - Appels IA: {stats['ai_calls']}")
        logger.info(f"   - Erreurs: {stats['errors']}")

        return stats

    def _get_target_questionnaires(self, questionnaire_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        Récupérer les questionnaires concernés

        Si questionnaire_id fourni: ce questionnaire uniquement
        Sinon: tous les questionnaires "modèles" (type = 'template')
        """

        if questionnaire_id:
            # Questionnaire spécifique
            query = text("""
                SELECT
                    q.id,
                    q.name,
                    r.id as referential_id,
                    r.code as referential_code,
                    r.name as referential_name
                FROM questionnaire q
                LEFT JOIN referential r ON q.referential_id = r.id
                WHERE q.id = CAST(:questionnaire_id AS uuid)
                  AND q.is_active = true
            """)
            results = self.db.execute(query, {"questionnaire_id": questionnaire_id}).fetchall()
        else:
            # Tous les questionnaires modèles
            # Note: On suppose qu'il y a une colonne "type" ou on prend tous les questionnaires actifs
            query = text("""
                SELECT DISTINCT
                    q.id,
                    q.name,
                    r.id as referential_id,
                    r.code as referential_code,
                    r.name as referential_name
                FROM questionnaire q
                LEFT JOIN referential r ON q.referential_id = r.id
                WHERE q.is_active = true
                ORDER BY q.name
            """)
            results = self.db.execute(query).fetchall()

        return [
            {
                "id": str(row[0]),
                "name": row[1],
                "referential_id": str(row[2]) if row[2] else None,
                "referential_code": row[3] or "",
                "referential_name": row[4] or ""
            }
            for row in results
        ]

    def _get_expected_control_points(self, questionnaire_id: str) -> List[Dict[str, Any]]:
        """
        Récupérer les PCs "attendus" pour ce questionnaire

        Basés sur le(s) référentiel(s) associé(s) au questionnaire
        """

        query = text("""
            SELECT DISTINCT
                cp.id,
                cp.control_id,
                cp.title,
                cp.description,
                cp.category,
                r.code as referential_code,
                r.name as referential_name
            FROM control_point cp
            JOIN referential r ON cp.referential_id = r.id
            JOIN questionnaire q ON q.referential_id = r.id
            WHERE q.id = CAST(:questionnaire_id AS uuid)
              AND cp.is_active = true
              AND r.is_active = true
            ORDER BY cp.control_id
        """)

        results = self.db.execute(query, {"questionnaire_id": questionnaire_id}).fetchall()

        return [
            {
                "id": str(row[0]),
                "control_id": row[1],
                "title": row[2],
                "description": row[3] or "",
                "category": row[4] or "",
                "referential_code": row[5],
                "referential_name": row[6]
            }
            for row in results
        ]

    def _get_covered_control_points(self, questionnaire_id: str) -> set:
        """
        Récupérer les IDs des PCs déjà couverts par des questions de ce questionnaire

        Un PC est "couvert" s'il existe au moins un mapping question ↔ PC
        pour une question de ce questionnaire
        """

        query = text("""
            SELECT DISTINCT qcp.control_point_id
            FROM question_control_point qcp
            JOIN question q ON qcp.question_id = q.id
            WHERE q.questionnaire_id = CAST(:questionnaire_id AS uuid)
              AND q.is_active = true
        """)

        results = self.db.execute(query, {"questionnaire_id": questionnaire_id}).fetchall()

        return {str(row[0]) for row in results}

    def _get_questionnaire_questions(self, questionnaire_id: str) -> List[Dict[str, Any]]:
        """Récupérer toutes les questions du questionnaire"""

        query = text("""
            SELECT
                q.id,
                q.question_text,
                q.help_text,
                r.code as source_referentiel,
                req.requirement_code as source_clause
            FROM question q
            LEFT JOIN requirement req ON q.requirement_id = req.id
            LEFT JOIN referential r ON req.referential_id = r.id
            WHERE q.questionnaire_id = CAST(:questionnaire_id AS uuid)
              AND q.is_active = true
            ORDER BY q.created_at
        """)

        results = self.db.execute(query, {"questionnaire_id": questionnaire_id}).fetchall()

        return [
            {
                "question_id": str(row[0]),
                "text": row[1],
                "help_text": row[2] or "",
                "source_referentiel": row[3] or "",
                "source_clause": row[4] or ""
            }
            for row in results
        ]

    def _get_crossref_equivalences(self, pc_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Récupérer les équivalences cross-référentiels pour enrichir le contexte IA

        Note: Cette fonction suppose l'existence d'une table control_point_requirement
        qui fait le lien entre control points de différents référentiels
        """

        if not pc_ids:
            return []

        # Pour l'instant, on retourne une liste vide
        # TODO: Implémenter si la table cross_referential_links existe
        return []

    async def _map_pcs_to_questions_ai(
        self,
        questionnaire: Dict[str, Any],
        pcs_to_process: List[Dict[str, Any]],
        questions: List[Dict[str, Any]],
        crossrefs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Utiliser l'IA pour mapper les PCs vers les questions

        Returns:
            Liste de mappings: [{"pc_id": "...", "matched_question_ids": [...], "comment": "..."}, ...]
        """

        # Construire le prompt selon mapping.md
        system_prompt = """Tu es un assistant expert en audit de cybersécurité et en gestion de référentiels.

Ton rôle :
- Pour chaque point de contrôle (PC), analyser s'il est déjà couvert par une ou plusieurs questions d'un questionnaire existant.
- Tu dois uniquement réutiliser des questions existantes, jamais en inventer de nouvelles.

Tes contraintes :
- Si une question ne couvre qu'une partie mineure du PC, tu peux la proposer mais précise-le dans le commentaire.
- Si aucune question ne couvre clairement le PC, tu renvoies une liste vide pour ce PC.
- Tu ne modifies pas le texte des questions et tu ne proposes pas de nouveaux textes.
- Tu dois être strict : il vaut mieux ne pas proposer de question que de faire un faux mapping.

Format de sortie OBLIGATOIRE :
Tu renvoies un JSON valide de la forme :

[
  {
    "pc_id": "ID_DU_PC",
    "matched_question_ids": ["ID_Q1", "ID_Q2"],
    "comment": "Texte court expliquant pourquoi ces questions couvrent ce PC."
  },
  ...
]

Rappels importants :
- "pc_id" doit être exactement l'identifiant fourni dans les données en entrée.
- "matched_question_ids" ne doit contenir que des identifiants de questions présents dans la liste fournie.
- Si aucun mapping pertinent n'existe pour un PC, renvoie :

{
  "pc_id": "ID_DU_PC",
  "matched_question_ids": [],
  "comment": "Aucune question existante ne couvre clairement ce point de contrôle."
}"""

        # Formater les PCs pour le prompt
        pcs_json = json.dumps([
            {
                "pc_id": pc['id'],
                "referentiel": pc['referential_code'],
                "clause": pc['control_id'],
                "title": pc['title'],
                "description": pc['description'],
                "category": pc.get('category', '')
            }
            for pc in pcs_to_process
        ], indent=2, ensure_ascii=False)

        # Formater les questions pour le prompt
        questions_json = json.dumps(questions, indent=2, ensure_ascii=False)

        # User prompt
        user_prompt = f"""Contexte :

Nous sommes dans une plateforme de gestion d'audits et de référentiels cybersécurité.
Nous voulons savoir si des points de contrôle nouvellement introduits sont déjà couverts par des questions existantes d'un questionnaire.

Données fournies :

1) Questionnaire (métadonnées simplifiées) :
- questionnaire_id : {questionnaire['id']}
- nom : {questionnaire['name']}
- référentiel principal : {questionnaire['referential_code']} - {questionnaire['referential_name']}

2) Liste des points de contrôle à analyser (JSON) :
{pcs_json}

3) Liste des questions du questionnaire (JSON) :
{questions_json}

Ta tâche :

Pour chaque point de contrôle dans la liste, décide s'il est déjà couvert par une ou plusieurs questions de la liste.

- Si oui : renvoie la liste des "question_id" correspondants.
- Si non : renvoie une liste vide.

Ne renvoie que le JSON final conforme au format demandé dans le system prompt.
Pas de texte supplémentaire autour, uniquement le JSON."""

        # Appel à l'API DeepSeek
        async with httpx.AsyncClient(timeout=60.0) as client:
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
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 4000
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

                    # Valider que c'est une liste
                    if not isinstance(parsed, list):
                        logger.error(f"Réponse IA n'est pas une liste: {parsed}")
                        return []

                    return parsed

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

    def _insert_mapping_if_not_exists(self, question_id: str, control_point_id: str) -> bool:
        """
        Insérer un mapping question ↔ control point s'il n'existe pas déjà

        Returns:
            True si le mapping a été créé, False s'il existait déjà
        """

        try:
            result = self.db.execute(text("""
                INSERT INTO question_control_point (question_id, control_point_id)
                VALUES (CAST(:question_id AS uuid), CAST(:control_point_id AS uuid))
                ON CONFLICT (question_id, control_point_id) DO NOTHING
                RETURNING id
            """), {
                "question_id": question_id,
                "control_point_id": control_point_id
            })

            self.db.commit()

            # Si la requête retourne un résultat, c'est qu'une ligne a été insérée
            return result.rowcount > 0

        except Exception as e:
            logger.error(f"Erreur insertion mapping: {e}")
            self.db.rollback()
            return False
