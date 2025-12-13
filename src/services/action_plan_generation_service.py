"""
Service de génération de plans d'action IA (EN MÉMOIRE UNIQUEMENT).

Pattern identique à la génération de questions:
- Service génère les données en mémoire
- Retourne JSON au frontend via SSE
- Frontend affiche l'interface de validation
- Utilisateur valide/modifie
- Frontend appelle /publish pour sauvegarder en DB

Version: 2.0 - Refactorisation complète
Date: 2025-01-23
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
import httpx
from pathlib import Path
from src.services.clients.deepseek_http_client import DeepSeekHttpClient

logger = logging.getLogger(__name__)


class ActionPlanGenerationService:
    """
    Service de génération de plans d'action EN MÉMOIRE.

    Workflow (5 phases):
    1. Préparation données (extraction depuis DB)
    2. Analyse IA des réponses (conformité/risque)
    3. Génération IA du plan (actions structurées)
    4. Post-traitement & assignation (mapping utilisateurs)
    5. [FRONTEND] Validation & publication (MANUEL)

    Pattern: Génère TOUT en mémoire, retourne Dict JSON.
    """

    def __init__(self, ollama_base_url: str = "http://localhost:11434", model: str = "deepseek-v3.1:671b-cloud"):
        """
        Initialise le service.

        Args:
            ollama_base_url: URL de base d'Ollama pour les appels IA
            model: Nom du modèle DeepSeek à utiliser
        """
        self.ollama_base_url = ollama_base_url
        self.model = model
        self.client = httpx.AsyncClient(timeout=120.0)

        # Charger les prompts depuis les fichiers
        self.prompts_dir = Path(__file__).parent.parent / "prompts" / "action_plan"
        self.system_prompt = self._load_prompt("00_system_prompt.txt")
        self.analysis_prompt = self._load_prompt("02_analysis_prompt.txt")
        self.action_plan_prompt = self._load_prompt("03_action_plan_prompt.txt")

        # Initialiser le client DeepSeek HTTP avec Ollama
        # IMPORTANT: max_tokens augmenté à 16384 pour éviter les JSON tronqués
        self.deepseek = DeepSeekHttpClient(
            base_url=ollama_base_url,
            model=model,
            temperature=0.6,
            max_tokens=16384,  # Doublé pour éviter la troncature des réponses JSON longues
            max_retries=3,
            system_prompt=self.system_prompt
        )

        # RGPD: Mapping entity_id -> {label anonyme, vrai nom}
        # Permet d'anonymiser avant envoi IA et remettre vrais noms au retour
        self.entity_mapping = {}

    def _load_prompt(self, filename: str) -> str:
        """Charge un prompt depuis un fichier."""
        prompt_path = self.prompts_dir / filename
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()
                logger.info(f"✅ Prompt chargé: {filename}")
                return content
        except FileNotFoundError:
            logger.error(f"❌ Fichier prompt introuvable: {prompt_path}")
            raise
        except Exception as e:
            logger.error(f"❌ Erreur chargement prompt {filename}: {e}")
            raise

    async def _safe_json_parse(self, response_text: str, phase_name: str) -> Dict[str, Any]:
        """
        Parse le JSON de manière robuste avec tentative de réparation.

        Args:
            response_text: Texte brut de la réponse IA
            phase_name: Nom de la phase (pour logging)

        Returns:
            Dict parsé

        Raises:
            Exception si impossible de parser même après réparation
        """
        # Détecter si la réponse semble tronquée (indicateurs communs)
        is_likely_truncated = (
            response_text.rstrip().endswith((',', '"', ':', '[', '{')) or
            response_text.count('{') > response_text.count('}') or
            response_text.count('[') > response_text.count(']')
        )

        if is_likely_truncated:
            logger.warning(f"⚠️ JSON potentiellement tronqué détecté en Phase {phase_name}")
            logger.warning(f"   - Derniers 100 caractères: ...{response_text[-100:]}")
            logger.warning(f"   - {{ count: {response_text.count('{')}, }} count: {response_text.count('}')}")

        try:
            # Tentative 1: Parse direct
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ JSON invalide en Phase {phase_name}, tentative de réparation...")
            logger.debug(f"Réponse brute: {response_text[:1000]}")

        # Tentative 2: Nettoyage basique et retry
        try:
            cleaned = response_text.strip()
            # Enlever les blocs markdown si présents (```json ... ``` ou ```json ... sans fermeture)
            if cleaned.startswith("```"):
                # Supprimer le premier ```json ou ```
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]  # len("```json") = 7
                else:
                    cleaned = cleaned[3:]  # len("```") = 3
                # Supprimer le ``` de fin s'il existe
                if "```" in cleaned:
                    cleaned = cleaned.split("```")[0]
            cleaned = cleaned.strip()

            logger.debug(f"🧹 JSON nettoyé (premiers 200 chars): {cleaned[:200]}")
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Tentative 3: Utiliser json-repair library
        try:
            from json_repair import repair_json
            logger.info("🔧 Utilisation de json-repair...")

            # Nettoyer les backticks markdown avant repair
            text_to_repair = response_text.strip()
            if text_to_repair.startswith("```"):
                if text_to_repair.startswith("```json"):
                    text_to_repair = text_to_repair[7:]
                else:
                    text_to_repair = text_to_repair[3:]
                if "```" in text_to_repair:
                    text_to_repair = text_to_repair.split("```")[0]
                text_to_repair = text_to_repair.strip()

            repaired = repair_json(text_to_repair)
            result = json.loads(repaired)
            logger.info(f"✅ JSON réparé avec succès pour Phase {phase_name}")

            # Vérifier la qualité des données réparées
            if phase_name == "2-Consolidation":
                nc_list = result.get("consolidated_nonconformities", [])
                incomplete_count = sum(1 for nc in nc_list if not nc.get("consolidated_description") or not nc.get("root_cause"))
                if incomplete_count > 0:
                    logger.warning(f"⚠️ JSON réparé mais {incomplete_count}/{len(nc_list)} NCs ont des champs vides (troncature probable)")
            elif phase_name == "3-Actions":
                actions = result.get("actions", [])
                incomplete_count = sum(1 for a in actions if not a.get("description") or len(a.get("description", "")) < 50)
                if incomplete_count > 0:
                    logger.warning(f"⚠️ JSON réparé mais {incomplete_count}/{len(actions)} actions ont des descriptions incomplètes (troncature probable)")

            return result
        except Exception as repair_error:
            logger.error(f"❌ Échec réparation JSON: {repair_error}")
            logger.error(f"Réponse complète: {response_text[:2000]}")
            raise Exception(
                f"IA a retourné du texte non-JSON en Phase {phase_name}. "
                f"Preview: {response_text[:500]}"
            )

    async def generate_action_plan(
        self,
        campaign_id: UUID,
        db: Session,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Génère un plan d'action complet EN MÉMOIRE (4 phases IA).

        IMPORTANT: Aucune écriture en base de données.
        Retourne un dictionnaire JSON prêt pour affichage frontend.

        Args:
            campaign_id: ID de la campagne
            db: Session database (lecture seule)
            progress_callback: Fonction callback pour envoyer progression SSE

        Returns:
            Dict contenant:
            {
                "action_plan_summary": {
                    "title": str,
                    "overall_risk_level": "faible|moyen|élevé|critique",
                    "total_actions": int,
                    "global_justification": str
                },
                "actions": [
                    {
                        "local_id": "ACT-1",
                        "title": str,
                        "description": str,
                        "objective": str,
                        "deliverables": [str],
                        "severity": "critical|major|minor|info",
                        "priority": "P1|P2|P3",
                        "recommended_due_days": int,
                        "suggested_role": str,
                        "source_questions": [str],
                        "referential_controls": [str],
                        "justification": {
                            "why_action": str,
                            "why_severity": str,
                            "why_priority": str,
                            "why_role": str,
                            "why_due_days": str
                        }
                    }
                ],
                "statistics": {
                    "total": int,
                    "critical_count": int,
                    "major_count": int,
                    "minor_count": int,
                    "info_count": int,
                    "overall_risk_level": str
                },
                "metadata": {
                    "campaign_id": str,
                    "generated_at": str,
                    "dominant_language": str
                }
            }
        """
        logger.info(f"🚀 Démarrage génération plan d'action pour campagne {campaign_id}")

        try:
            # PHASE 1: Préparation des données
            if progress_callback:
                await progress_callback("phase1_started", {"message": "Extraction des réponses..."})

            analyzed_responses = await self.phase1_prepare_data(campaign_id, db, progress_callback)

            if progress_callback:
                await progress_callback("phase1_completed", {
                    "questions_analyzed": len(analyzed_responses),
                    "message": f"✅ {len(analyzed_responses)} réponses extraites"
                })

            logger.info(f"✅ Phase 1 : {len(analyzed_responses)} réponses analysées")

            # PHASE 2: Analyse IA (conformité/risque)
            if progress_callback:
                await progress_callback("phase2_started", {"message": "Analyse IA des conformités..."})

            nonconformities = await self.phase2_analyze_conformity(
                analyzed_responses, campaign_id, db, progress_callback
            )

            if progress_callback:
                await progress_callback("phase2_completed", {
                    "non_conformities_found": len(nonconformities),
                    "message": f"✅ {len(nonconformities)} non-conformités détectées"
                })

            logger.info(f"✅ Phase 2 : {len(nonconformities)} NC détectées")

            # PHASE 3: Génération IA du plan
            if progress_callback:
                await progress_callback("phase3_started", {"message": "Génération des actions..."})

            action_plan_data = await self.phase3_generate_actions(
                nonconformities, campaign_id, db, progress_callback
            )

            if progress_callback:
                await progress_callback("phase3_completed", {
                    "actions_generated": len(action_plan_data.get("actions", [])),
                    "message": f"✅ {len(action_plan_data.get('actions', []))} actions générées"
                })

            logger.info(f"✅ Phase 3 : {len(action_plan_data.get('actions', []))} actions générées")

            # PHASE 4: Post-traitement & assignation
            if progress_callback:
                await progress_callback("phase4_started", {"message": "Assignation automatique..."})

            final_plan = await self.phase4_assign_users(
                action_plan_data, campaign_id, db, progress_callback
            )

            if progress_callback:
                await progress_callback("phase4_completed", {
                    "actions_assigned": len(final_plan.get("actions", [])),
                    "message": "✅ Assignation terminée"
                })

            logger.info(f"✅ Phase 4 : {len(final_plan.get('actions', []))} actions assignées")

            # PHASE 5: Préparation de la validation (PAS de sauvegarde DB)
            if progress_callback:
                await progress_callback("phase5_started", {"message": "Préparation de la validation..."})

            # RGPD: Remettre les vrais noms d'entités (dé-anonymisation)
            logger.info("🔓 RGPD: Remapping des noms réels d'entités...")
            for action in final_plan.get("actions", []):
                entity_id = action.get("entity_id")
                if entity_id and entity_id in self.entity_mapping:
                    action["entity_name"] = self.entity_mapping[entity_id]["real_name"]
                    logger.debug(f"🔓 Action {action.get('local_id')}: {self.entity_mapping[entity_id]['label']} → {action['entity_name']}")

            # Ajouter métadonnées finales (sans ID car pas encore sauvegardé)
            final_plan["metadata"] = {
                "campaign_id": str(campaign_id),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "dominant_language": "fr",  # TODO: détecter depuis les réponses
                "status": "READY_FOR_VALIDATION"  # Pas encore en DB
            }

            if progress_callback:
                await progress_callback("phase5_completed", {
                    "message": "✅ Prêt pour validation"
                })

            logger.info(f"🎉 Plan d'action généré avec succès : {len(final_plan.get('actions', []))} actions")
            return final_plan

        except Exception as e:
            logger.error(f"❌ Erreur lors de la génération : {str(e)}", exc_info=True)
            if progress_callback:
                await progress_callback("error", {"message": str(e)})
            raise

    # ==================== PHASE 1: PRÉPARATION DES DONNÉES ====================

    async def phase1_prepare_data(
        self,
        campaign_id: UUID,
        db: Session,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Phase 1 : Collecte de toutes les réponses du questionnaire.

        Returns:
            Liste des réponses avec métadonnées (question, contrôle, domaine, etc.)
        """
        logger.info("📋 Phase 1 : Préparation des données...")

        # Requête pour récupérer toutes les réponses avec contexte
        # IMPORTANT: Inclut entity_id et entity_name pour permettre à l'IA de générer
        # des actions spécifiques par entité (évite la sur-consolidation)
        # FIX: Utilise a.entity_id directement au lieu de la jointure via organization
        query = text("""
            SELECT
                qr.id as response_id,
                qr.question_id,
                qr.answer_value,
                qr.comment,
                q.question_text,
                q.response_type,
                req.id as requirement_id,
                req.official_code as requirement_code,
                req.title as requirement_title,
                req.requirement_text,
                d.title as domain_name,
                d.code as domain_code,
                ee.id as entity_id,
                ee.name as entity_name,
                a.id as audit_id,
                COUNT(DISTINCT aa.id) as attachments_count,
                STRING_AGG(DISTINCT aa.original_filename, ', ') as attachment_filenames,
                STRING_AGG(DISTINCT aa.attachment_type, ', ') as attachment_types
            FROM question_answer qr
            JOIN question q ON qr.question_id = q.id
            JOIN audit a ON qr.audit_id = a.id
            JOIN ecosystem_entity ee ON a.entity_id = ee.id
            JOIN campaign c ON qr.campaign_id = c.id
            JOIN campaign_scope cs ON c.scope_id = cs.id
            LEFT JOIN requirement req ON q.requirement_id = req.id
            LEFT JOIN domain d ON req.domain_id = d.id
            LEFT JOIN answer_attachment aa ON qr.id = aa.answer_id
                AND aa.virus_scan_status = 'clean'
                AND aa.is_active = true
            WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
              AND qr.is_current = true
              AND ee.id = ANY(cs.entity_ids)
            GROUP BY qr.id, qr.question_id, qr.answer_value, qr.comment,
                     q.question_text, q.response_type, req.id,
                     req.official_code, req.title, req.requirement_text,
                     d.title, d.code, ee.id, ee.name, a.id
            ORDER BY ee.name, d.title, req.official_code
        """)

        result = db.execute(query, {"campaign_id": str(campaign_id)})
        rows = result.fetchall()

        # RGPD: Créer un mapping entity_id -> label anonyme (Entité 1, Entité 2, ...)
        # Réinitialiser le mapping pour cette génération
        self.entity_mapping = {}
        entity_counter = 1

        analyzed = []
        total = len(rows)

        for idx, row in enumerate(rows):
            # Créer label anonyme si première fois qu'on voit cette entité
            entity_id_str = str(row.entity_id)
            if entity_id_str not in self.entity_mapping:
                self.entity_mapping[entity_id_str] = {
                    "label": f"Entité {entity_counter}",
                    "real_name": row.entity_name
                }
                entity_counter += 1
                logger.info(f"🔒 RGPD: Anonymisation {row.entity_name} → {self.entity_mapping[entity_id_str]['label']}")

            analyzed.append({
                "response_id": str(row.response_id),
                "question_id": str(row.question_id),
                "question_text": row.question_text,
                "response_type": row.response_type,
                "answer_value": row.answer_value,
                "comment": row.comment or "",
                "requirement_id": str(row.requirement_id) if row.requirement_id else None,
                "requirement_code": row.requirement_code,
                "requirement_title": row.requirement_title,
                "requirement_text": row.requirement_text,
                "domain_name": row.domain_name,
                "domain_code": row.domain_code,
                "entity_id": entity_id_str,
                "entity_name": self.entity_mapping[entity_id_str]["label"],  # Label anonyme pour l'IA
                "audit_id": str(row.audit_id),
                "attachments_count": row.attachments_count or 0,  # Nombre de preuves fournies
                "attachment_filenames": row.attachment_filenames or "",  # Noms des fichiers (evidence)
                "attachment_types": row.attachment_types or "",  # Types des pièces jointes
            })

            # Envoyer progression tous les 10 items
            if progress_callback and (idx + 1) % 10 == 0:
                await progress_callback("phase1_progress", {
                    "questions_analyzed": idx + 1,
                    "total_questions": total
                })

        # Log des entités trouvées pour debug
        unique_entities = set((r["entity_id"], r["entity_name"]) for r in analyzed)
        logger.info(f"📊 Phase 1: {len(analyzed)} réponses de {len(unique_entities)} entités distinctes")
        for entity_id, entity_label in unique_entities:
            entity_responses = [r for r in analyzed if r["entity_id"] == entity_id]
            real_name = self.entity_mapping.get(entity_id, {}).get("real_name", "?")
            logger.info(f"   - {entity_label} ({real_name}): {len(entity_responses)} réponses")

        return analyzed

    # ==================== PHASE 2: ANALYSE IA ====================

    async def phase2_analyze_conformity(
        self,
        analyzed_responses: List[Dict[str, Any]],
        campaign_id: UUID,
        db: Session,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Phase 2 : Analyse IA de TOUTES les réponses avec CONSOLIDATION.

        Deux étapes:
        1. Détection simple des NC via parsing JSON
        2. Appel IA pour CONSOLIDATION (grouper NCs similaires, calculer risques)

        Returns:
            Liste consolidée de non-conformités avec scores de risque
        """
        logger.info(f"🤖 Phase 2 : Analyse IA de {len(analyzed_responses)} questions...")

        # ÉTAPE 1: Détection simple des NCs (parsing JSON)
        raw_nonconformities = []

        for response in analyzed_responses:
            answer_value = response.get("answer_value", {})

            # Si answer_value est une string JSON, la parser
            if isinstance(answer_value, str):
                try:
                    answer_value = json.loads(answer_value)
                except:
                    answer_value = {}

            # Déterminer la conformité selon le type de réponse
            is_non_conforme = False
            is_partiel = False
            value_str = ""

            if isinstance(answer_value, dict):
                # Réponse booléenne
                if "bool" in answer_value:
                    bool_val = answer_value["bool"]
                    if bool_val is False:
                        is_non_conforme = True
                        value_str = "Non"
                    else:
                        value_str = "Oui"

                # Réponse à choix multiples
                elif "choice" in answer_value:
                    choice = str(answer_value["choice"]).lower()
                    if choice in ["non", "no", "non conforme", "non-conforme"]:
                        is_non_conforme = True
                        value_str = answer_value["choice"]
                    elif choice in ["partiellement", "partiel", "partial", "en cours"]:
                        is_partiel = True
                        value_str = answer_value["choice"]
                    else:
                        value_str = answer_value["choice"]

                # Réponse numérique (seuil bas = risque)
                elif "number" in answer_value:
                    num_val = answer_value.get("number", 0)
                    value_str = str(num_val)
                    if num_val < 3:
                        is_partiel = True

                # Réponse fichiers manquants
                elif "files" in answer_value:
                    files = answer_value.get("files", [])
                    if len(files) == 0:
                        is_partiel = True
                        value_str = "Aucun fichier fourni"

            # Ajouter aux NCs brutes si détecté
            if is_non_conforme or is_partiel:
                raw_nonconformities.append({
                    **response,
                    "detected_value": value_str,
                    "is_critical": is_non_conforme
                })

        logger.info(f"🔍 Détection brute : {len(raw_nonconformities)} NC sur {len(analyzed_responses)} réponses")

        # Log répartition des NCs par entité
        nc_by_entity = {}
        for nc in raw_nonconformities:
            entity_name = nc.get("entity_name", "?")
            entity_id = nc.get("entity_id", "?")
            key = f"{entity_name} ({entity_id})"
            nc_by_entity[key] = nc_by_entity.get(key, 0) + 1
        logger.info(f"📊 Répartition NCs brutes par entité:")
        for entity, count in nc_by_entity.items():
            logger.info(f"   - {entity}: {count} NC")

        # ÉTAPE 2: Consolidation IA (si NCs détectées)
        if len(raw_nonconformities) == 0:
            logger.info("✅ Aucune NC détectée, fin de Phase 2")
            return []

        logger.info("=" * 80)
        logger.info("🚀 DÉBUT CONSOLIDATION IA (PHASE 2 - PASSE 1)")
        logger.info("=" * 80)

        try:
            # TRAITEMENT PAR BATCHES pour éviter la troncature JSON
            # Le modèle cloud a une limite de génération - on traite par lots de 10 NCs
            BATCH_SIZE = 10
            all_consolidated = []
            total_batches = (len(raw_nonconformities) + BATCH_SIZE - 1) // BATCH_SIZE

            for batch_idx in range(total_batches):
                start_idx = batch_idx * BATCH_SIZE
                end_idx = min(start_idx + BATCH_SIZE, len(raw_nonconformities))
                batch_ncs = raw_nonconformities[start_idx:end_idx]

                logger.info(f"📦 Batch {batch_idx + 1}/{total_batches}: NCs {start_idx + 1} à {end_idx}")

                # Préparer les NCs du batch en JSON
                nc_json_data = []
                for nc in batch_ncs:
                    nc_json_data.append({
                        "question_id": nc.get("question_id"),
                        "question_text": nc.get("question_text", ""),
                        "requirement_code": nc.get("requirement_code", "N/A"),
                        "requirement_title": nc.get("requirement_title", ""),
                        "domain_name": nc.get("domain_name", ""),
                        "entity_id": nc.get("entity_id", ""),
                        "entity_name": nc.get("entity_name", ""),
                        "detected_value": nc.get("detected_value", ""),
                        "comment": nc.get("comment", ""),
                        "attachments_count": nc.get("attachments_count", 0),
                        "attachment_filenames": nc.get("attachment_filenames", ""),
                        "attachment_types": nc.get("attachment_types", "")
                    })

                nc_json_str = json.dumps(nc_json_data, indent=2, ensure_ascii=False)

                logger.info(f"🔍 DEBUG Batch {batch_idx + 1}: Envoi de {len(nc_json_data)} NCs")

                user_prompt = self.analysis_prompt.replace("{{total_responses}}", str(len(analyzed_responses)))
                user_prompt = user_prompt.replace("{{nc_count}}", str(len(batch_ncs)))
                user_prompt = user_prompt.replace("{{campaign_id}}", str(campaign_id))
                user_prompt = user_prompt.replace("{{nonconformities_json}}", nc_json_str)

                logger.info(f"📤 Envoi à Ollama DeepSeek (Batch {batch_idx + 1}):")
                logger.info(f"   - Modèle: {self.deepseek.model}")
                logger.info(f"   - Température: {self.deepseek.temperature}")
                logger.info(f"   - Max tokens: {self.deepseek.max_tokens}")
                logger.info(f"   - NCs dans ce batch: {len(batch_ncs)}")
                logger.info(f"🤖 Appel Ollama DeepSeek pour consolidation batch {batch_idx + 1}...")

                # Appel Ollama DeepSeek avec retry logic
                response_text = await self.deepseek.call_with_retry(
                    user_prompt=user_prompt,
                    system_prompt=self.system_prompt
                )

                # Parser la réponse JSON avec réparation si nécessaire
                response = await self._safe_json_parse(response_text, f"2-Consolidation-Batch{batch_idx + 1}")

                batch_consolidated = response.get("consolidated_nonconformities", [])
                logger.info(f"✅ Batch {batch_idx + 1}: {len(batch_ncs)} NC → {len(batch_consolidated)} clusters")

                all_consolidated.extend(batch_consolidated)

                # Callback de progression
                if progress_callback:
                    await progress_callback("phase2_batch_progress", {
                        "batch": batch_idx + 1,
                        "total_batches": total_batches,
                        "batch_nc_count": len(batch_ncs),
                        "batch_consolidated_count": len(batch_consolidated)
                    })

            logger.info(f"✅ CONSOLIDATION TERMINÉE: {len(raw_nonconformities)} NC → {len(all_consolidated)} clusters total")
            logger.info("=" * 80)

            # Enrichir chaque NC consolidée avec les métadonnées originales
            # ET compléter les champs manquants si le JSON était tronqué
            for nc in all_consolidated:
                # Retrouver les questions sources
                source_ids = nc.get("source_question_ids", [])
                source_responses = [r for r in raw_nonconformities if r["question_id"] in source_ids]

                # Ajouter métadonnées du premier source
                if source_responses:
                    first_source = source_responses[0]
                    nc["requirement_code"] = first_source.get("requirement_code")
                    nc["requirement_title"] = first_source.get("requirement_title")
                    nc["domain_name"] = first_source.get("domain_name")
                    nc["domain_code"] = first_source.get("domain_code")
                    nc["entity_id"] = first_source.get("entity_id")
                    nc["entity_name"] = first_source.get("entity_name")

                    # Si champs IA sont vides (JSON tronqué), utiliser les données brutes comme fallback
                    if not nc.get("consolidated_description"):
                        nc["consolidated_description"] = f"Non-conformité détectée: {first_source.get('question_text', '')[:200]}"
                        logger.warning(f"⚠️ consolidated_description manquant pour NC, fallback sur question_text")

                    if not nc.get("root_cause"):
                        nc["root_cause"] = f"Réponse: {first_source.get('detected_value', 'Non conforme')}. Commentaire: {first_source.get('comment', 'N/A')[:150]}"
                        logger.warning(f"⚠️ root_cause manquant pour NC, fallback sur comment")

                    if not nc.get("current_situation"):
                        nc["current_situation"] = f"Question: {first_source.get('question_text', '')[:150]}. Réponse: {first_source.get('detected_value', 'NC')}"

                    if not nc.get("gap_description"):
                        nc["gap_description"] = f"Écart constaté sur l'exigence {nc.get('requirement_code', 'N/A')}"

                    # S'assurer que risk_score existe
                    if not nc.get("risk_score") or nc.get("risk_score") == 0:
                        # Calculer un score basique basé sur is_critical
                        nc["risk_score"] = 16 if first_source.get("is_critical") else 9
                        nc["impact"] = 4 if first_source.get("is_critical") else 3
                        nc["probability"] = 4 if first_source.get("is_critical") else 3

            if progress_callback:
                await progress_callback("phase2_progress", {
                    "raw_nc_count": len(raw_nonconformities),
                    "consolidated_count": len(all_consolidated)
                })

            return all_consolidated

        except Exception as e:
            logger.error(f"❌ Erreur consolidation IA Phase 2 : {str(e)}", exc_info=True)
            # PAS DE FALLBACK - Remonter l'erreur
            raise Exception(f"Échec de la consolidation IA des non-conformités: {str(e)}")

    # ==================== PHASE 3: GÉNÉRATION ACTIONS IA ====================

    async def phase3_generate_actions(
        self,
        nonconformities: List[Dict[str, Any]],
        campaign_id: UUID,
        db: Session,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Phase 3 : Génération IA du plan d'action structuré avec DEEPSEEK.

        L'IA génère des actions correctives SMART avec justifications complètes.

        Returns:
            Dict avec action_plan_summary + actions
        """
        logger.info(f"🤖 Phase 3 : Génération IA du plan d'action ({len(nonconformities)} NC)...")

        # Si aucune NC, retourner plan vide
        if len(nonconformities) == 0:
            logger.info("✅ Aucune action à générer")
            return {
                "action_plan_summary": {
                    "title": f"Plan d'actions - Campagne {campaign_id}",
                    "overall_risk_level": "faible",
                    "total_actions": 0,
                    "global_justification": "Aucune non-conformité détectée. Organisation en conformité totale."
                },
                "actions": [],
                "statistics": {
                    "total": 0,
                    "critical_count": 0,
                    "major_count": 0,
                    "minor_count": 0,
                    "info_count": 0,
                    "overall_risk_level": "faible"
                }
            }

        logger.info("=" * 80)
        logger.info("🚀 DÉBUT GÉNÉRATION ACTIONS (PHASE 3 - PASSE 2)")
        logger.info("=" * 80)

        try:
            # TRAITEMENT PAR BATCHES pour éviter la troncature JSON
            # Le modèle cloud a une limite de génération - on traite par lots de 10 NCs
            BATCH_SIZE = 10
            all_actions = []
            total_batches = (len(nonconformities) + BATCH_SIZE - 1) // BATCH_SIZE
            action_plan_summary = {}

            for batch_idx in range(total_batches):
                start_idx = batch_idx * BATCH_SIZE
                end_idx = min(start_idx + BATCH_SIZE, len(nonconformities))
                batch_ncs = nonconformities[start_idx:end_idx]

                logger.info(f"📦 Batch {batch_idx + 1}/{total_batches}: NCs {start_idx + 1} à {end_idx}")

                # Préparer le contexte des NC consolidées pour l'IA
                nc_context = []
                for nc in batch_ncs:
                    nc_context.append({
                        "requirement_code": nc.get("requirement_code", "N/A"),
                        "requirement_title": nc.get("requirement_title", ""),
                        "entity_id": nc.get("entity_id", ""),  # ✅ OBLIGATOIRE - Identifiant entité
                        "entity_name": nc.get("entity_name", ""),  # ✅ OBLIGATOIRE - Nom anonymisé (Entité 1, 2, 3)
                        "consolidated_description": nc.get("consolidated_description", ""),
                        "risk_score": nc.get("risk_score", 0),
                        "impact": nc.get("impact", 0),
                        "probability": nc.get("probability", 0),
                        "source_question_ids": nc.get("source_question_ids", []),
                        "domain_name": nc.get("domain_name", ""),
                        "root_cause": nc.get("root_cause", ""),  # ✅ Cause racine identifiée en Phase 2
                        "current_situation": nc.get("current_situation", ""),  # ✅ État actuel constaté
                        "gap_description": nc.get("gap_description", "")  # ✅ Description précise de l'écart
                    })

                nc_json_str = json.dumps(nc_context, indent=2, ensure_ascii=False)

                # 🔍 DEBUG: Afficher le contexte envoyé à l'IA (premières itérations seulement)
                if batch_idx == 0:
                    logger.info(f"🔍 DEBUG Phase 3: Contexte NC envoyé à l'IA:")
                    logger.info(f"🔍 DEBUG Phase 3: Nombre de NCs dans ce batch: {len(nc_context)}")
                    for idx, nc in enumerate(nc_context[:3]):  # Afficher les 3 premières
                        logger.info(f"🔍 DEBUG Phase 3: NC {idx+1}:")
                        logger.info(f"   - entity_id: {nc.get('entity_id')}")
                        logger.info(f"   - entity_name: {nc.get('entity_name')}")
                        logger.info(f"   - requirement_code: {nc.get('requirement_code')}")
                        logger.info(f"   - requirement_title: {nc.get('requirement_title')}")
                        logger.info(f"   - consolidated_description: {nc.get('consolidated_description')[:100] if nc.get('consolidated_description') else 'VIDE'}...")
                        logger.info(f"   - risk_score: {nc.get('risk_score')}")
                        logger.info(f"   - source_question_ids: {nc.get('source_question_ids')}")

                # Préparer le prompt
                user_prompt = self.action_plan_prompt.replace("{{nc_count}}", str(len(batch_ncs)))
                user_prompt = user_prompt.replace("{{nc_json}}", nc_json_str)

                logger.info(f"📤 Envoi à Ollama DeepSeek (Batch {batch_idx + 1}):")
                logger.info(f"   - Modèle: {self.deepseek.model}")
                logger.info(f"   - Température: {self.deepseek.temperature}")
                logger.info(f"   - Max tokens: {self.deepseek.max_tokens}")
                logger.info(f"   - NCs dans ce batch: {len(batch_ncs)}")
                logger.info(f"🤖 Appel Ollama DeepSeek pour génération d'actions correctives batch {batch_idx + 1}...")

                # Appel Ollama DeepSeek avec retry logic
                response_text = await self.deepseek.call_with_retry(
                    user_prompt=user_prompt,
                    system_prompt=self.system_prompt
                )

                # Parser la réponse JSON avec réparation si nécessaire
                response = await self._safe_json_parse(response_text, f"3-Actions-Batch{batch_idx + 1}")

                # Extraire les données générées
                if batch_idx == 0:
                    # Premier batch: récupérer le summary global
                    action_plan_summary = response.get("action_plan_summary", {})

                batch_actions = response.get("actions", [])
                logger.info(f"✅ Batch {batch_idx + 1}: {len(batch_ncs)} NC → {len(batch_actions)} actions")

                all_actions.extend(batch_actions)

                # Callback de progression
                if progress_callback:
                    await progress_callback("phase3_batch_progress", {
                        "batch": batch_idx + 1,
                        "total_batches": total_batches,
                        "batch_nc_count": len(batch_ncs),
                        "batch_actions_count": len(batch_actions)
                    })

            # Utiliser all_actions comme actions finales
            actions = all_actions

            logger.info(f"✅ GÉNÉRATION TERMINÉE: {len(actions)} actions créées depuis {len(nonconformities)} NC (en {total_batches} batches)")
            logger.info("=" * 80)

            # Enrichir chaque action avec les source_questions réelles
            for idx, action in enumerate(actions):
                # Mapper les clusters_ids aux source_question_ids
                cluster_ids = action.get("source_clusters", [])
                all_source_questions = []

                logger.info(f"🔍 Action {idx+1}: source_clusters = {cluster_ids}")
                logger.info(f"🔍 Action {idx+1}: Nombre de NCs disponibles = {len(nonconformities)}")

                for cluster_id in cluster_ids:
                    # Retrouver la NC correspondante
                    matching_nc = next((nc for nc in nonconformities if nc.get("requirement_code") == cluster_id), None)
                    if matching_nc:
                        nc_questions = matching_nc.get("source_question_ids", [])
                        all_source_questions.extend(nc_questions)
                        logger.info(f"   ✅ Cluster '{cluster_id}' → {len(nc_questions)} questions: {nc_questions}")
                    else:
                        logger.warning(f"   ⚠️ Cluster '{cluster_id}' introuvable dans les NCs")
                        logger.warning(f"   📋 NCs disponibles: {[nc.get('requirement_code') for nc in nonconformities]}")

                action["source_questions"] = all_source_questions
                action["local_id"] = f"ACT-{idx + 1}"

                logger.info(f"✅ Action {idx+1} '{action.get('title', '')[:50]}...': {len(all_source_questions)} source_questions")
                logger.info(f"📋 source_questions final: {all_source_questions}")

                # Fallback si certains champs manquent
                if not action.get("severity"):
                    action["severity"] = "minor"
                if not action.get("priority"):
                    action["priority"] = "P2"
                if not action.get("recommended_due_days"):
                    action["recommended_due_days"] = 60
                if not action.get("suggested_role"):
                    action["suggested_role"] = "RSSI"

            # Calculer statistiques
            stats = self._calculate_statistics(actions)

            # Construire résultat final
            result = {
                "action_plan_summary": {
                    "title": action_plan_summary.get("title", f"Plan d'actions - Campagne {campaign_id}"),
                    "overall_risk_level": action_plan_summary.get("overall_risk_level", stats["overall_risk_level"]),
                    "total_actions": len(actions),
                    "global_justification": action_plan_summary.get("global_justification", f"{len(nonconformities)} non-conformités consolidées en {len(actions)} actions correctives.")
                },
                "actions": actions,
                "statistics": stats
            }

            if progress_callback:
                await progress_callback("phase3_progress", {
                    "nc_count": len(nonconformities),
                    "actions_generated": len(actions)
                })

            return result

        except Exception as e:
            logger.error(f"❌ Erreur génération IA Phase 3 : {str(e)}", exc_info=True)
            # PAS DE FALLBACK - Remonter l'erreur
            raise Exception(f"Échec de la génération IA du plan d'action: {str(e)}")

    # ==================== PHASE 4: POST-TRAITEMENT & ASSIGNATION ====================

    async def phase4_assign_users(
        self,
        action_plan_data: Dict[str, Any],
        campaign_id: UUID,
        db: Session,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Phase 4 : Assignation automatique des responsables.

        Logique d'assignation :
        1. Tenter d'assigner à un utilisateur avec le rôle correspondant dans le tenant
        2. Fallback : Assigner à un auditeur de la campagne
        3. Si aucun mapping trouvé : laisser non assigné

        Returns:
            Dict avec actions assignées (champ assigned_user_id ajouté)
        """
        logger.info(f"👥 Phase 4 : Assignation automatique...")

        # Récupérer le tenant_id de la campagne
        campaign_query = text("""
            SELECT c.tenant_id
            FROM campaign c
            WHERE c.id = CAST(:campaign_id AS uuid)
        """)
        campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)})
        campaign_row = campaign_result.mappings().first()

        if not campaign_row:
            logger.warning(f"⚠️ Campagne {campaign_id} introuvable pour assignation")
            return action_plan_data

        tenant_id = campaign_row.tenant_id

        # Mapping des rôles suggérés vers les rôles système
        role_mapping = {
            "RSSI": ["RSSI", "RSSI externe"],
            "DSI": ["Administrateur (Tenant)", "Chef de projet"],
            "DPO": ["Directeur de conformité / DPO", "DPO externe"],
            "Directeur général": ["Administrateur (Tenant)"],
            "Responsable RH": ["Administrateur (Tenant)"],
            "Chef de projet": ["Chef de projet"],
            "Auditeur": ["Auditeur"]
        }

        actions = action_plan_data.get("actions", [])
        assigned_count = 0

        for idx, action in enumerate(actions):
            suggested_role = action.get("suggested_role", "")

            assigned_user_id = None

            # Étape 1 : Chercher un utilisateur avec le rôle correspondant
            matched_roles = role_mapping.get(suggested_role, [suggested_role])

            user_query = text("""
                SELECT DISTINCT u.id
                FROM users u
                JOIN user_role ur ON u.id = ur.user_id
                JOIN role r ON ur.role_id = r.id
                WHERE u.tenant_id = CAST(:tenant_id AS uuid)
                  AND r.name = ANY(:role_names)
                  AND u.is_active = true
                LIMIT 1
            """)

            result = db.execute(user_query, {
                "tenant_id": str(tenant_id),
                "role_names": matched_roles
            })
            user_row = result.first()

            if user_row:
                assigned_user_id = str(user_row[0])
                assigned_count += 1
                logger.debug(f"✅ Action {idx+1} assignée à {assigned_user_id} (rôle: {suggested_role})")
            else:
                # Étape 2 : Fallback vers un auditeur de la campagne
                auditor_query = text("""
                    SELECT u.id
                    FROM users u
                    JOIN campaign_user cu ON u.id = cu.user_id
                    WHERE cu.campaign_id = CAST(:campaign_id AS uuid)
                      AND cu.role = 'auditor'
                      AND cu.is_active = true
                    LIMIT 1
                """)

                result = db.execute(auditor_query, {"campaign_id": str(campaign_id)})
                auditor_row = result.first()

                if auditor_row:
                    assigned_user_id = str(auditor_row[0])
                    assigned_count += 1
                    logger.debug(f"✅ Action {idx+1} assignée à auditeur (fallback)")

            # Mettre à jour l'action avec l'assignation
            action["assigned_user_id"] = assigned_user_id

            # Envoyer progression tous les 3 items
            if progress_callback and (idx + 1) % 3 == 0:
                await progress_callback("phase4_progress", {
                    "actions_assigned": assigned_count,
                    "actions_generated": len(actions)
                })

        logger.info(f"✅ Phase 4 : {assigned_count}/{len(actions)} actions assignées")

        return action_plan_data

    # ==================== UTILITAIRES ====================

    def _calculate_statistics(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calcule les statistiques sur les actions."""
        severity_counts = {
            "critical": 0,
            "major": 0,
            "minor": 0,
            "info": 0
        }

        for action in actions:
            severity = action.get("severity", "minor")
            if severity in severity_counts:
                severity_counts[severity] += 1

        # Déterminer niveau de risque global
        if severity_counts["critical"] > 0:
            overall_risk = "critique"
        elif severity_counts["major"] > 2:
            overall_risk = "élevé"
        elif severity_counts["major"] > 0 or severity_counts["minor"] > 5:
            overall_risk = "moyen"
        else:
            overall_risk = "faible"

        return {
            "total": len(actions),
            "critical_count": severity_counts["critical"],
            "major_count": severity_counts["major"],
            "minor_count": severity_counts["minor"],
            "info_count": severity_counts["info"],
            "overall_risk_level": overall_risk
        }
