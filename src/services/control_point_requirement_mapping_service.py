"""
Service de mapping entre Requirements d'un Framework et Control Points globaux.

Architecture CORRECTE selon le schéma BDD réel:
    Framework → Requirement → requirement_control_point ← Control Point (globaux)

Ce service propose des mappings pour les requirements d'un framework vers les control points existants.
"""

import json
import logging
from typing import List, Dict, Any, Optional, Callable, Awaitable
from sqlalchemy import text
from sqlalchemy.orm import Session
import httpx

logger = logging.getLogger(__name__)


class ControlPointRequirementMappingService:
    """Service pour mapper les requirements d'un framework vers les control points."""

    def __init__(
        self,
        db: Session,
        api_key: str = None,
        use_ollama: bool = True,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "deepseek-v3.1:671b-cloud"
    ):
        self.db = db
        self.api_key = api_key
        self.use_ollama = use_ollama
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model

        # URL API selon le mode
        if use_ollama:
            self.api_url = f"{ollama_url}/api/chat"
            logger.info(f"🤖 Service IA: Ollama local ({ollama_model})")
        else:
            self.api_url = "https://api.deepseek.com/v1/chat/completions"
            logger.info(f"🤖 Service IA: DeepSeek Cloud")

    async def analyze_framework_for_proposals(
        self,
        framework_id: str,
        limit: Optional[int] = None,
        progress_callback: Optional[Callable[[dict], Awaitable[None]]] = None
    ) -> Dict[str, Any]:
        """
        Analyser un framework et proposer des mappings Requirements → Control Points

        Args:
            framework_id: UUID du framework source
            limit: Limite du nombre de requirements à analyser (pour tests)
            progress_callback: Callback async pour notifier la progression

        Returns:
            Dict avec:
                - framework_id: UUID du framework
                - framework_name: Nom du framework
                - total_requirements: Nombre total de requirements
                - unmapped_requirements: Nombre de requirements non mappés
                - proposed_mappings: Liste des propositions
                    - requirement_id: UUID du requirement
                    - requirement: Détails du requirement
                    - matched_control_points: Liste des CPs proposés
                    - justification: Explication de l'IA
                    - confidence: Score de confiance
        """

        # Helper pour notifier progression
        async def notify_progress(event_data: dict):
            if progress_callback:
                await progress_callback(event_data)

        logger.info(f"🔍 Analyse du framework pour propositions de mapping")
        logger.info(f"   Framework: {framework_id}")

        await notify_progress({
            "status": "initializing",
            "message": "Chargement des requirements..."
        })

        # 1. Récupérer les informations du framework
        logger.info(f"📋 Étape 1/5: Récupération informations framework {framework_id}")
        framework_info = self._get_framework_info(framework_id)
        if not framework_info:
            logger.error(f"❌ Framework {framework_id} non trouvé dans la base")
            raise ValueError(f"Framework {framework_id} non trouvé")
        logger.info(f"   ✅ Framework trouvé: {framework_info['name']} (code: {framework_info['code']})")

        # 2. Récupérer TOUS les requirements du framework
        logger.info(f"📋 Étape 2/5: Récupération requirements du framework")
        all_requirements = self._get_framework_requirements(framework_id, limit=None)
        logger.info(f"   ✅ {len(all_requirements)} requirements au total")

        # 3. Récupérer TOUS les requirements du framework (pour le cross-référentiel)
        logger.info(f"📋 Étape 3/5: Récupération de tous les requirements (cross-référentiel)")
        target_requirements = all_requirements if not limit else all_requirements[:limit]
        logger.info(f"   ✅ {len(target_requirements)} requirements cibles pour mapping")

        if not target_requirements:
            logger.info(f"   ℹ️  Aucun requirement dans ce framework, arrêt du processus")

            # Résumé final même si rien à faire
            logger.info(f"\n{'='*60}")
            logger.info(f"✅ ANALYSE TERMINÉE - Aucun requirement à analyser")
            logger.info(f"{'='*60}")
            logger.info(f"📊 Framework: {framework_info['name']}")
            logger.info(f"📊 Total requirements du framework: 0")
            logger.info(f"{'='*60}\n")

            return {
                "framework_id": framework_id,
                "framework_name": framework_info['name'],
                "total_requirements": 0,
                "unmapped_requirements": 0,
                "proposed_mappings": []
            }

        # 4. Récupérer les CPs NON ENCORE MAPPÉS à ce framework (cross-référentiel)
        logger.info(f"📋 Étape 4/5: Récupération control points NON mappés à ce framework")
        unmapped_control_points = self._get_unmapped_control_points_for_framework(framework_id, limit)
        logger.info(f"   ✅ {len(unmapped_control_points)} control points non encore mappés à ce framework")

        await notify_progress({
            "status": "loaded",
            "total_requirements": len(target_requirements),
            "total_control_points": len(unmapped_control_points)
        })

        if not unmapped_control_points:
            logger.info(f"   ℹ️  Aucun control point non mappé trouvé")

            # Résumé final - tous CPs déjà mappés
            logger.info(f"\n{'='*60}")
            logger.info(f"✅ ANALYSE TERMINÉE - Tous les CPs déjà mappés")
            logger.info(f"{'='*60}")
            logger.info(f"📊 Framework cible: {framework_info['name']}")
            logger.info(f"📊 Requirements cibles: {len(target_requirements)}")
            logger.info(f"✅ Tous les control points disponibles sont déjà mappés à ce framework")
            logger.info(f"{'='*60}\n")

            return {
                "framework_id": framework_id,
                "framework_name": framework_info['name'],
                "total_requirements": len(all_requirements),
                "unmapped_requirements": 0,
                "proposed_mappings": []
            }

        # 5. Analyser les CPs en batch et les mapper vers requirements (CROSS-RÉFÉRENTIEL)
        logger.info(f"📋 Étape 5/5: Analyse mapping par IA - CPs → Requirements (cross-référentiel)")
        proposed_mappings = []

        # Traiter par lots de 20 control points
        batch_size = 20
        batches = [unmapped_control_points[i:i+batch_size] for i in range(0, len(unmapped_control_points), batch_size)]
        total_batches = len(batches)
        logger.info(f"   📊 {len(unmapped_control_points)} control points divisés en {total_batches} batches de {batch_size}")

        for batch_index, cp_batch in enumerate(batches, 1):
            logger.info(f"\n🔄 Batch {batch_index}/{total_batches}: Analyse de {len(cp_batch)} control points")
            logger.debug(f"   Control Points codes: {[cp['code'] for cp in cp_batch]}")

            await notify_progress({
                "status": "processing",
                "batch_index": batch_index,
                "total_batches": total_batches
            })

            try:
                # Appel IA en BATCH - INVERSÉ: CPs → Requirements
                mappings_batch = await self._map_multiple_control_points_to_requirements(
                    control_points=cp_batch,
                    candidate_requirements=target_requirements
                )

                # Compter les résultats du batch (CROSS-REF: CPs → Requirements)
                batch_with_mappings = len([m for m in mappings_batch if m['matched_requirement_ids']])
                batch_without_mappings = len(mappings_batch) - batch_with_mappings

                logger.info(f"   ✅ Batch {batch_index} traité: {len(mappings_batch)} control points analysés")
                logger.info(f"      → {batch_with_mappings} avec mapping, {batch_without_mappings} sans mapping")

                await notify_progress({
                    "status": "batch_complete",
                    "batch_index": batch_index,
                    "total_batches": total_batches,
                    "mappings_count": batch_with_mappings
                })

                # Traiter les résultats (CROSS-REF: chaque CP mappé vers Requirements)
                logger.info(f"   📦 Traitement des {len(cp_batch)} control points du batch...")
                for mapping in mappings_batch:
                    cp_id = mapping['control_point_id']
                    matched_req_ids = mapping['matched_requirement_ids']
                    comment = mapping['comment']
                    no_match_reason = mapping.get('no_match_reason')

                    # Récupérer les détails du control point
                    cp = next((c for c in cp_batch if c['id'] == cp_id), None)
                    if not cp:
                        continue

                    # Si aucun mapping, créer quand même une entrée avec la raison
                    if not matched_req_ids:
                        if no_match_reason:
                            proposed_mappings.append({
                                "control_point_id": cp['id'],
                                "control_point": {
                                    "id": cp['id'],
                                    "code": cp['code'],
                                    "name": cp['name'],
                                    "description": cp['description'],
                                    "category": cp['category']
                                },
                                "matched_requirements": [],
                                "justification": comment,
                                "confidence": 0.0,
                                "no_match_reason": no_match_reason
                            })
                        continue

                    # Récupérer les détails des requirements
                    matched_reqs = [req for req in target_requirements if req['id'] in matched_req_ids]

                    # Calculer confidence
                    confidence = min(len(matched_reqs) / 3.0, 1.0)

                    proposed_mappings.append({
                        "control_point_id": cp['id'],
                        "control_point": {
                            "id": cp['id'],
                            "code": cp['code'],
                            "name": cp['name'],
                            "description": cp['description'],
                            "category": cp['category']
                        },
                        "matched_requirements": [
                            {
                                "id": req['id'],
                                "official_code": req['official_code'],
                                "title": req['title'],
                                "requirement_text": req['requirement_text'],
                                "domain_name": req.get('domain_name', '')
                            }
                            for req in matched_reqs
                        ],
                        "justification": comment,
                        "confidence": confidence,
                        "no_match_reason": None
                    })

                # Log fin de traitement du batch
                logger.info(f"   ✅ Batch {batch_index} terminé: {len(proposed_mappings)} propositions au total jusqu'ici\n")

            except Exception as e:
                logger.error(f"   ❌ Erreur analyse batch {batch_index}: {e}", exc_info=True)
                await notify_progress({
                    "status": "error",
                    "batch_index": batch_index,
                    "error": str(e)
                })

        # Résumé final détaillé (CROSS-RÉFÉRENTIEL)
        # Compter les CPs qui ont au moins un requirement mappé
        total_cps_with_mappings = len([m for m in proposed_mappings if m.get('matched_requirements')])

        # Compter le nombre total d'associations (un CP peut avoir plusieurs requirements)
        total_requirement_associations = sum(len(m.get('matched_requirements', [])) for m in proposed_mappings)

        # CPs NON mappés = ceux qui n'ont aucun requirement correspondant
        total_cps_without_mapping = len([m for m in proposed_mappings if not m.get('matched_requirements')])

        # Taux de couverture
        coverage_pct = (total_cps_with_mappings * 100 // len(unmapped_control_points)) if unmapped_control_points else 0

        logger.info(f"\n{'='*60}")
        logger.info(f"✅ ANALYSE CROSS-RÉFÉRENTIEL TERMINÉE")
        logger.info(f"{'='*60}")
        logger.info(f"📊 Framework CIBLE: {framework_info['name']}")
        logger.info(f"📊 Total requirements du framework cible: {len(target_requirements)}")
        logger.info(f"📊 Control Points SOURCE à mapper: {len(unmapped_control_points)}")
        logger.info(f"📊 Propositions générées: {len(proposed_mappings)}")
        logger.info(f"📊 CPs mappés avec succès: {total_cps_with_mappings}/{len(unmapped_control_points)} ({coverage_pct}%)")
        logger.info(f"📊 CPs SANS correspondance: {total_cps_without_mapping}")
        logger.info(f"📊 Total associations créées (CPs → Requirements): {total_requirement_associations}")

        # Afficher les CPs sans correspondance avec raisons
        if total_cps_without_mapping > 0:
            logger.info(f"\n⚠️  Control Points SANS correspondance:")
            for mapping in proposed_mappings:
                if not mapping.get('matched_requirements'):
                    cp_code = mapping['control_point']['code']
                    reason = mapping.get('no_match_reason', 'Raison non fournie')
                    logger.info(f"   - {cp_code}: {reason}")

        logger.info(f"{'='*60}\n")

        return {
            "framework_id": framework_id,
            "framework_name": framework_info['name'],
            "total_target_requirements": len(target_requirements),
            "total_source_control_points": len(unmapped_control_points),
            "control_points_mapped": total_cps_with_mappings,
            "control_points_without_match": total_cps_without_mapping,
            "total_associations": total_requirement_associations,
            "proposed_mappings": proposed_mappings
        }

    def _get_framework_info(self, framework_id: str) -> Optional[Dict[str, Any]]:
        """Récupérer les informations d'un framework"""

        query = text("""
            SELECT id, name, code, version
            FROM framework
            WHERE id = CAST(:framework_id AS uuid)
              AND is_active = true
            LIMIT 1
        """)

        result = self.db.execute(query, {"framework_id": framework_id}).fetchone()

        if not result:
            return None

        return {
            "id": str(result[0]),
            "name": result[1],
            "code": result[2],
            "version": result[3]
        }

    def _get_framework_requirements(
        self,
        framework_id: str,
        limit: Optional[int]
    ) -> List[Dict[str, Any]]:
        """Récupérer tous les requirements d'un framework"""

        query_parts = ["""
            SELECT
                r.id,
                r.official_code,
                r.title,
                r.requirement_text,
                d.title as domain_name
            FROM requirement r
            LEFT JOIN domain d ON r.domain_id = d.id
            WHERE r.framework_id = CAST(:framework_id AS uuid)
              AND r.is_active = true
            ORDER BY r.official_code
        """]

        if limit:
            query_parts.append(f"LIMIT {limit}")

        query = text(" ".join(query_parts))
        results = self.db.execute(query, {"framework_id": framework_id}).fetchall()

        return [
            {
                "id": str(row[0]),
                "official_code": row[1],
                "title": row[2] or "",
                "requirement_text": row[3] or "",
                "domain_name": row[4] or ""
            }
            for row in results
        ]

    def _get_unmapped_requirements(
        self,
        framework_id: str,
        limit: Optional[int]
    ) -> List[Dict[str, Any]]:
        """
        Récupérer les requirements qui n'ont PAS encore de mapping dans requirement_control_point
        """

        query_parts = ["""
            SELECT
                r.id,
                r.official_code,
                r.title,
                r.requirement_text,
                d.title as domain_name
            FROM requirement r
            LEFT JOIN domain d ON r.domain_id = d.id
            WHERE r.framework_id = CAST(:framework_id AS uuid)
              AND r.is_active = true
              AND NOT EXISTS (
                  SELECT 1 FROM requirement_control_point rcp
                  WHERE rcp.requirement_id = r.id
              )
            ORDER BY r.official_code
        """]

        if limit:
            query_parts.append(f"LIMIT {limit}")

        query = text(" ".join(query_parts))
        results = self.db.execute(query, {"framework_id": framework_id}).fetchall()

        return [
            {
                "id": str(row[0]),
                "official_code": row[1],
                "title": row[2] or "",
                "requirement_text": row[3] or "",
                "domain_name": row[4] or ""
            }
            for row in results
        ]

    def _get_all_control_points(self) -> List[Dict[str, Any]]:
        """Récupérer TOUS les control points globaux"""

        query = text("""
            SELECT
                id,
                code,
                name,
                description,
                category
            FROM control_point
            WHERE is_active = true
            ORDER BY code
        """)

        results = self.db.execute(query).fetchall()

        return [
            {
                "id": str(row[0]),
                "code": row[1],
                "name": row[2],
                "description": row[3] or "",
                "category": row[4] or ""
            }
            for row in results
        ]

    def _get_unmapped_control_points_for_framework(
        self,
        framework_id: str,
        limit: Optional[int]
    ) -> List[Dict[str, Any]]:
        """
        Récupérer les control points qui ne sont PAS encore mappés aux requirements de ce framework.

        Pour le cross-référentiel: on cherche les CPs qui n'ont pas encore de lien
        avec les requirements du framework cible.
        """

        query_parts = ["""
            SELECT
                cp.id,
                cp.code,
                cp.name,
                cp.description,
                cp.category
            FROM control_point cp
            WHERE cp.is_active = true
              AND NOT EXISTS (
                  SELECT 1
                  FROM requirement_control_point rcp
                  JOIN requirement r ON rcp.requirement_id = r.id
                  WHERE rcp.control_point_id = cp.id
                    AND r.framework_id = CAST(:framework_id AS uuid)
              )
            ORDER BY cp.code
        """]

        if limit:
            query_parts.append(f"LIMIT {limit}")

        query = text(" ".join(query_parts))
        results = self.db.execute(query, {"framework_id": framework_id}).fetchall()

        return [
            {
                "id": str(row[0]),
                "code": row[1],
                "name": row[2],
                "description": row[3] or "",
                "category": row[4] or ""
            }
            for row in results
        ]

    async def _map_multiple_control_points_to_requirements(
        self,
        control_points: List[Dict[str, Any]],
        candidate_requirements: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Mapper PLUSIEURS control points vers des requirements en un seul appel IA (batch)

        CROSS-RÉFÉRENTIEL: Pour chaque CP source, trouver les requirements cibles correspondants.

        Returns:
            Liste de mappings: [{"control_point_id": "...", "matched_requirement_ids": [...], "comment": "..."}]
        """
        logger.info(f"   🤖 Appel IA (cross-ref): {len(control_points)} CPs × {len(candidate_requirements)} requirements")

        # Limiter à 30 requirements pour le prompt
        req_candidates = candidate_requirements[:30]
        logger.debug(f"   📊 Requirements limités à {len(req_candidates)} pour le prompt")

        # Limiter à 20 CPs par appel
        cp_candidates = control_points[:20]
        logger.debug(f"   📊 CPs limités à {len(cp_candidates)} pour cet appel")

        # Préparer la liste des control points (SOURCE)
        cp_list = []
        for idx, cp in enumerate(cp_candidates, 1):
            cp_list.append(
                f"{idx}. CP_ID: {cp['id']}\n"
                f"   Code: {cp['code']}\n"
                f"   Nom: {cp['name']}\n"
                f"   Description: {cp['description'][:200]}...\n"
                f"   Catégorie: {cp['category']}"
            )

        cp_list_str = "\n\n".join(cp_list)

        # Préparer la liste des requirements (CIBLES)
        reqs_list = []
        for idx, req in enumerate(req_candidates, 1):
            text_preview = req['requirement_text'][:200] if req['requirement_text'] else req['title']
            reqs_list.append(
                f"{idx}. REQ_ID: {req['id']}\n"
                f"   Code: {req['official_code']}\n"
                f"   Titre: {req['title']}\n"
                f"   Texte: {text_preview}...\n"
                f"   Domaine: {req.get('domain_name', 'N/A')}"
            )

        reqs_list_str = "\n\n".join(reqs_list)

        prompt = f"""Tu es un expert en cybersécurité, en normalisation (ISO 27001, NIS2, RGPD, HDS, PCI-DSS, etc.) et en mapping cross-référentiel.

Ton rôle :
- Déterminer si des control points (CPs) d'un référentiel SOURCE correspondent à des requirements d'un référentiel CIBLE.
- Tu travailles sur le mapping CROSS-RÉFÉRENTIEL : Control Points → Requirements.

Les CPs et requirements peuvent être considérés comme correspondants lorsque :
- ils couvrent la même intention de contrôle,
- ils ont un objectif fonctionnel identique,
- ils visent le même domaine de sécurité (accès, journalisation, continuité, risques, gouvernance…).

Tu dois être strict mais pas trop restrictif :
- Tu peux proposer des correspondances même si le vocabulaire est différent, tant que l'intention est la même.
- Sélectionne entre 1 et 5 requirements maximum PAR control point.
- Privilégie la PRÉCISION (mieux vaut 1 REQ très pertinent que 5 moyennement pertinents).

CONTROL POINTS SOURCE À MAPPER:
{cp_list_str}

REQUIREMENTS CIBLES DISPONIBLES:
{reqs_list_str}

FORMAT DE RÉPONSE OBLIGATOIRE (JSON uniquement):
[
  {{
    "cp_id_source": "CP_ID exact tel que fourni",
    "matched_requirements": [
      {{
        "req_id": "REQ_ID",
        "relation": "equivalent | proche | partiel",
        "justification": "Justification courte (2-3 phrases, français, non technique)."
      }}
    ],
    "no_match_reason": null
  }},
  {{
    "cp_id_source": "AUTRE_CP_ID",
    "matched_requirements": [],
    "no_match_reason": "Raison explicative courte si aucun requirement ne correspond (1-2 phrases)."
  }}
]

Règles :
- Si aucun requirement ne correspond, renvoie: {{"cp_id_source": "ID", "matched_requirements": [], "no_match_reason": "Raison..."}}
- Pour "no_match_reason", explique POURQUOI aucun requirement ne correspond (trop spécifique, domaine non couvert, etc.)
- Renvoie TOUS les control points, même ceux sans mapping (liste vide + raison).
- Utilise les CP_ID et REQ_ID EXACTS fournis ci-dessus.
- Réponds UNIQUEMENT avec le JSON valide, sans texte avant ou après."""

        # Appel à l'API (Ollama ou DeepSeek)
        logger.info(f"   📡 Appel API IA (cross-ref, temperature: 0.2, max_tokens: 2000)")
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                # Préparer le payload selon le mode
                if self.use_ollama:
                    # Format Ollama
                    payload = {
                        "model": self.ollama_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": """Tu es un expert en cybersécurité et en mapping cross-référentiel.

Tu travailles sur le mapping Control Points (source) → Requirements (cible).

Tu dois produire pour chaque correspondance une justification claire :
- courte (2 à 3 phrases maximum),
- non technique,
- en français,
- expliquant simplement pourquoi cette correspondance a été proposée.

Tu réponds UNIQUEMENT en JSON valide."""
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "stream": False,
                        "options": {
                            "temperature": 0.2,
                            "num_ctx": 16384
                        }
                    }
                    headers = {"Content-Type": "application/json"}
                else:
                    # Format DeepSeek Cloud
                    payload = {
                        "model": "deepseek-chat",
                        "messages": [
                            {
                                "role": "system",
                                "content": """Tu es un expert en cybersécurité et en mapping cross-référentiel.

Tu travailles sur le mapping Control Points (source) → Requirements (cible).

Tu dois produire pour chaque correspondance une justification claire :
- courte (2 à 3 phrases maximum),
- non technique,
- en français,
- expliquant simplement pourquoi cette correspondance a été proposée.

Tu réponds UNIQUEMENT en JSON valide."""
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.2,
                        "max_tokens": 2000
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }

                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json=payload
                )

                if response.status_code != 200:
                    logger.error(f"   ❌ Erreur API IA: {response.status_code} - {response.text}")
                    return []

                logger.info(f"   ✅ Réponse API reçue (status: {response.status_code})")
                result = response.json()

                # Extraire la réponse selon le format
                if self.use_ollama:
                    ai_response = result["message"]["content"]
                else:
                    ai_response = result["choices"][0]["message"]["content"]

                logger.debug(f"   📝 Réponse IA (longueur: {len(ai_response)} chars)")

                # Parser la réponse
                logger.info(f"   🔍 Parsing de la réponse JSON")
                try:
                    ai_response = ai_response.strip()
                    if ai_response.startswith("```json"):
                        ai_response = ai_response[7:]
                        logger.debug(f"   ✂️  Suppression du wrapper ```json")
                    if ai_response.startswith("```"):
                        ai_response = ai_response[3:]
                        logger.debug(f"   ✂️  Suppression du wrapper ```")
                    if ai_response.endswith("```"):
                        ai_response = ai_response[:-3]
                        logger.debug(f"   ✂️  Suppression du wrapper ``` de fin")

                    parsed = json.loads(ai_response.strip())
                    logger.info(f"   ✅ JSON parsé: {len(parsed)} mappings CP reçus")

                    # Valider et nettoyer les résultats
                    validated_mappings = []
                    for mapping in parsed:
                        cp_id = mapping.get("cp_id_source")
                        matched_requirements = mapping.get("matched_requirements", [])
                        no_match_reason = mapping.get("no_match_reason")

                        # Vérifier que le cp_id existe
                        if not any(cp['id'] == cp_id for cp in cp_candidates):
                            logger.warning(f"CP_ID {cp_id} non trouvé dans la liste")
                            continue

                        # Extraire les requirement_ids
                        valid_req_ids = []
                        justifications = []
                        for match in matched_requirements:
                            req_id = match.get("req_id")
                            relation = match.get("relation", "")
                            justification = match.get("justification", "")

                            # Vérifier que le req_id existe
                            if any(req['id'] == req_id for req in req_candidates):
                                valid_req_ids.append(req_id)
                                if justification:
                                    justifications.append(f"[{relation}] {justification}")
                            else:
                                logger.warning(f"REQ_ID {req_id} non trouvé dans la liste")

                        # Construire le commentaire final
                        if justifications:
                            final_comment = " | ".join(justifications)
                        elif no_match_reason:
                            final_comment = f"❌ Aucun mapping: {no_match_reason}"
                        else:
                            final_comment = "Aucun requirement ne correspond."

                        validated_mappings.append({
                            "control_point_id": cp_id,
                            "matched_requirement_ids": valid_req_ids,
                            "comment": final_comment,
                            "no_match_reason": no_match_reason
                        })

                    # Logs de résultats
                    total_cps = len(cp_candidates)
                    total_mapped = sum(1 for m in validated_mappings if m['matched_requirement_ids'])
                    total_unmapped = total_cps - total_mapped
                    total_req_mappings = sum(len(m['matched_requirement_ids']) for m in validated_mappings)
                    logger.info(f"   📊 Résultats: {total_cps} control points analysés")
                    logger.info(f"      → {total_mapped}/{total_cps} CPs mappés ({total_mapped*100//total_cps if total_cps > 0 else 0}%)")
                    logger.info(f"      → {total_req_mappings} requirements associés au total")

                    # Détail des CPs non mappés avec raisons
                    if total_unmapped > 0:
                        unmapped_cps = [m for m in validated_mappings if not m['matched_requirement_ids']]
                        logger.warning(f"   ⚠️  {total_unmapped} control points SANS mapping:")
                        for m in unmapped_cps[:3]:  # Montrer max 3 exemples
                            cp = next((c for c in cp_candidates if c['id'] == m['control_point_id']), None)
                            if cp:
                                reason = m.get('no_match_reason', 'Raison non fournie')
                                logger.warning(f"      - {cp['code']}: {cp['name'][:50]}...")
                                if reason:
                                    logger.warning(f"        └─ Raison IA: {reason}")

                    return validated_mappings

                except json.JSONDecodeError as e:
                    logger.error(f"Erreur parsing JSON: {e}")
                    logger.error(f"Réponse IA: {ai_response[:500]}")
                    return []

            except Exception as e:
                logger.error(f"Erreur appel API: {e}")
                return []


