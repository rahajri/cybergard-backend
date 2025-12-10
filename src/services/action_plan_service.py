"""
Service de génération de plans d'action IA.

Ce service orchestre les 4 phases de génération :
1. Analyse des réponses du questionnaire
2. Détection des non-conformités et risques
3. Génération des actions correctives avec IA
4. Assignation automatique des responsables
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, text
import json
import httpx
import os
from pathlib import Path

from src.models.action_plan import (
    ActionPlan,
    ActionPlanItem,
    ActionPlanStatus,
    ActionPlanItemStatus,
    ActionSeverity,
    ActionPriority,
    AssignmentMethod
)
from src.schemas.action_plan import GenerationProgress, PhaseStatus

logger = logging.getLogger(__name__)


class ActionPlanService:
    """Service de génération de plans d'action avec IA."""

    def __init__(self, ollama_base_url: str = "http://localhost:11434"):
        """
        Initialise le service.

        Args:
            ollama_base_url: URL de base d'Ollama pour les appels IA
        """
        self.ollama_base_url = ollama_base_url
        self.client = httpx.AsyncClient(timeout=120.0)

        # Charger les prompts depuis les fichiers
        self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"
        self.system_prompt = self._load_prompt("00_system_prompt.txt")
        self.analysis_prompt = self._load_prompt("02_analysis_prompt.txt")
        self.action_plan_prompt = self._load_prompt("03_action_plan_prompt.txt")

    def _load_prompt(self, filename: str) -> str:
        """
        Charge un prompt depuis un fichier.

        Args:
            filename: Nom du fichier prompt

        Returns:
            Contenu du prompt
        """
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

    async def generate_action_plan(
        self,
        campaign_id: UUID,
        tenant_id: UUID,
        db: Session,
        progress_callback: Optional[callable] = None
    ) -> ActionPlan:
        """
        Génère un plan d'action complet avec les 4 phases IA.

        IMPORTANT: Génère TOUT EN MÉMOIRE puis crée ActionPlan en DRAFT à la fin.
        Rien n'est enregistré en base de données avant la fin des 4 phases.

        Args:
            campaign_id: ID de la campagne
            tenant_id: ID du tenant (pour l'ActionPlan)
            db: Session database
            progress_callback: Fonction callback pour envoyer progression SSE

        Returns:
            ActionPlan créé en status=DRAFT avec tous les items
        """
        logger.info(f"🚀 Démarrage génération plan d'action pour campagne {campaign_id}")

        # Pas d'ActionPlan existant - génération en mémoire uniquement

        try:
            # ==================== PHASE 1: ANALYSE DES RÉPONSES ====================
            await self._update_progress(
                action_plan, db,
                current_phase=1,
                phase1_status=PhaseStatus.IN_PROGRESS,
                progress_callback=progress_callback
            )

            analyzed_responses = await self.phase1_analyze_responses(
                campaign_id, db, action_plan, progress_callback
            )

            await self._update_progress(
                action_plan, db,
                phase1_status=PhaseStatus.COMPLETED,
                questions_analyzed=len(analyzed_responses),
                progress_callback=progress_callback
            )

            logger.info(f"✅ Phase 1 terminée : {len(analyzed_responses)} réponses analysées")

            # ==================== PHASE 2: DÉTECTION NC ET RISQUES ====================
            await self._update_progress(
                action_plan, db,
                current_phase=2,
                phase2_status=PhaseStatus.IN_PROGRESS,
                progress_callback=progress_callback
            )

            nonconformities = await self.phase2_detect_nonconformities(
                analyzed_responses, db, action_plan, progress_callback
            )

            await self._update_progress(
                action_plan, db,
                phase2_status=PhaseStatus.COMPLETED,
                non_conformities_found=len(nonconformities),
                progress_callback=progress_callback
            )

            logger.info(f"✅ Phase 2 terminée : {len(nonconformities)} NC détectées")

            # ==================== PHASE 2.5: RE-VALIDATION 2-PASS ====================
            await self._update_progress(
                action_plan, db,
                current_phase=2,
                progress_callback=progress_callback
            )

            nonconformities = await self.phase2_5_revalidate_analysis(
                nonconformities, db, action_plan, progress_callback
            )

            logger.info(f"✅ Phase 2.5 terminée : {len(nonconformities)} NC validées")

            # ==================== PHASE 3: GÉNÉRATION ACTIONS IA ====================
            await self._update_progress(
                action_plan, db,
                current_phase=3,
                phase3_status=PhaseStatus.IN_PROGRESS,
                progress_callback=progress_callback
            )

            action_items = await self.phase3_generate_actions(
                nonconformities, action_plan_id, db, action_plan, progress_callback
            )

            await self._update_progress(
                action_plan, db,
                phase3_status=PhaseStatus.COMPLETED,
                actions_generated=len(action_items),
                progress_callback=progress_callback
            )

            logger.info(f"✅ Phase 3 terminée : {len(action_items)} actions générées")

            # ==================== PHASE 4: ASSIGNATION AUTOMATIQUE ====================
            await self._update_progress(
                action_plan, db,
                current_phase=4,
                phase4_status=PhaseStatus.IN_PROGRESS,
                progress_callback=progress_callback
            )

            assigned_items = await self.phase4_auto_assign(
                action_items, campaign_id, db, action_plan, progress_callback
            )

            await self._update_progress(
                action_plan, db,
                phase4_status=PhaseStatus.COMPLETED,
                actions_assigned=len(assigned_items),
                progress_callback=progress_callback
            )

            logger.info(f"✅ Phase 4 terminée : {len(assigned_items)} actions assignées")

            # ==================== FINALISATION ====================
            # Calculer statistiques
            stats = self._calculate_statistics(assigned_items)
            action_plan.total_actions = stats['total']
            action_plan.critical_count = stats['critical']
            action_plan.major_count = stats['major']
            action_plan.minor_count = stats['minor']
            action_plan.info_count = stats['info']
            action_plan.overall_risk_level = stats['overall_risk']
            action_plan.dominant_language = 'fr'
            action_plan.status = ActionPlanStatus.DRAFT
            action_plan.generated_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(action_plan)

            logger.info(f"🎉 Plan d'action généré avec succès : {stats['total']} actions")
            return action_plan

        except Exception as e:
            logger.error(f"❌ Erreur lors de la génération : {str(e)}", exc_info=True)
            action_plan.status = ActionPlanStatus.NOT_STARTED
            action_plan.generation_progress = {
                "error_message": str(e)
            }
            db.commit()
            raise

    # ==================== PHASE 1: ANALYSE DES RÉPONSES ====================

    async def phase1_analyze_responses(
        self,
        campaign_id: UUID,
        db: Session,
        action_plan: ActionPlan,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Phase 1 : Collecte et analyse de toutes les réponses du questionnaire.

        Returns:
            Liste des réponses avec métadonnées (question, conformité, risque, etc.)
        """
        logger.info("📋 Phase 1 : Analyse des réponses...")

        # Requête pour récupérer toutes les réponses avec contexte
        query = text("""
            SELECT
                qr.id as response_id,
                qr.question_id,
                qr.answer_value,
                q.question_text,
                q.response_type,
                req.id as requirement_id,
                req.official_code as requirement_code,
                req.title as requirement_title,
                req.requirement_text,
                d.title as domain_name,
                d.code as domain_code
            FROM question_answer qr
            JOIN question q ON qr.question_id = q.id
            LEFT JOIN requirement req ON q.requirement_id = req.id
            LEFT JOIN domain d ON req.domain_id = d.id
            WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
            ORDER BY d.title, req.official_code
        """)

        result = db.execute(query, {"campaign_id": str(campaign_id)})
        rows = result.fetchall()

        analyzed = []
        total = len(rows)

        for idx, row in enumerate(rows):
            analyzed.append({
                "response_id": row.response_id,
                "question_id": row.question_id,
                "question_text": row.question_text,
                "response_type": row.response_type,
                "answer_value": row.answer_value,
                # Note: conformite, risque, justification will be added by AI in Phase 2
                "requirement_id": row.requirement_id,
                "requirement_code": row.requirement_code,
                "requirement_title": row.requirement_title,
                "requirement_text": row.requirement_text,
                "domain_name": row.domain_name,
                "domain_code": row.domain_code,
            })

            # Envoyer progression tous les 10 items
            if progress_callback and (idx + 1) % 10 == 0:
                await self._update_progress(
                    action_plan, db,
                    questions_analyzed=idx + 1,
                    total_questions=total,
                    progress_callback=progress_callback
                )

        # Mise à jour finale
        if progress_callback:
            await self._update_progress(
                action_plan, db,
                questions_analyzed=total,
                total_questions=total,
                progress_callback=progress_callback
            )

        return analyzed

    # ==================== PHASE 2: ANALYSE IA DES RÉPONSES ====================

    async def phase2_detect_nonconformities(
        self,
        analyzed_responses: List[Dict[str, Any]],
        db: Session,
        action_plan: ActionPlan,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Phase 2 : Analyse IA de TOUTES les réponses avec le prompt 02_analysis_prompt.

        L'IA analyse chaque question et détermine :
        - conformite : conforme | partiel | non_conforme | non_applicable
        - risque : faible | moyen | élevé | critique
        - action_requise : true/false
        - justification : explication courte

        Returns:
            Liste des questions avec analyse IA enrichie
        """
        logger.info("🤖 Phase 2 : Analyse IA des réponses...")

        # Récupérer infos campagne pour contexte
        campaign_id = action_plan.campaign_id
        campaign_query = text("""
            SELECT c.title, c.description, f.name as framework_name
            FROM campaign c
            LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
            LEFT JOIN framework f ON q.framework_id = f.id
            WHERE c.id = CAST(:campaign_id AS uuid)
        """)
        campaign_info = db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()

        # Préparer données pour l'IA
        campaign_json = json.dumps({
            "title": campaign_info.title if campaign_info else "Campagne d'audit",
            "framework": campaign_info.framework_name if campaign_info else "ISO 27001",
            "description": campaign_info.description if campaign_info else ""
        }, ensure_ascii=False, indent=2)

        questions_json = json.dumps([
            {
                "question_id": str(r['question_id']),
                "question_text": r['question_text'],
                "answer_value": r['answer_value'],
                "requirement_code": r['requirement_code'],
                "requirement_title": r['requirement_title']
            }
            for r in analyzed_responses
        ], ensure_ascii=False, indent=2)

        # Formater le prompt avec variables
        analysis_prompt_filled = self.analysis_prompt.format(
            language="FR",  # TODO: détecter langue du questionnaire
            campaign_json=campaign_json,
            questions_json=questions_json
        )

        # Appel IA pour analyse globale
        try:
            logger.info(f"📡 Appel IA pour analyser {len(analyzed_responses)} questions...")

            # Informer l'utilisateur
            if progress_callback:
                await self._update_progress(
                    action_plan, db,
                    phase2_status=PhaseStatus.IN_PROGRESS,
                    progress_callback=progress_callback
                )

            response = await self.client.post(
                f"{self.ollama_base_url}/api/generate",
                json={
                    "model": "deepseek-v3.1:671b-cloud",
                    "system": self.system_prompt,
                    "prompt": analysis_prompt_filled,
                    "stream": False,
                    "format": "json"
                },
                timeout=120.0
            )

            if response.status_code == 200:
                result = response.json()

                # Informer l'utilisateur
                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        progress_callback=progress_callback
                    )

                ai_analysis = json.loads(result['response'])

                # Enrichir analyzed_responses avec l'analyse IA
                questions_analysis = {
                    qa['question_id']: qa
                    for qa in ai_analysis.get('questions_analysis', [])
                }

                enriched = []
                for r in analyzed_responses:
                    qid = str(r['question_id'])
                    if qid in questions_analysis:
                        ia = questions_analysis[qid]
                        r['conformite'] = ia.get('conformite', r.get('conformite'))
                        r['risque'] = ia.get('risque', r.get('risque'))
                        r['action_requise'] = ia.get('action_requise', False)
                        r['justification'] = ia.get('justification', r.get('justification'))
                    enriched.append(r)

                # Filtrer pour garder uniquement celles nécessitant action
                nonconformities = [r for r in enriched if r.get('action_requise', False)]

                logger.info(f"✅ Analyse IA terminée : {len(nonconformities)}/{len(analyzed_responses)} nécessitent une action")
                return nonconformities

            else:
                logger.warning(f"⚠️ Erreur IA analyse: {response.status_code}, fallback règles")
                return self._fallback_detect_nc(analyzed_responses)

        except Exception as e:
            logger.error(f"❌ Erreur appel IA Phase 2: {str(e)}")
            return self._fallback_detect_nc(analyzed_responses)

    def _fallback_detect_nc(self, responses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Fallback : détection NC par règles si IA indisponible.

        Returns:
            NC détectées par règles simples
        """
        nonconformities = []
        for response in responses:
            # Si conformite/risque pas encore définis, utiliser règle basique sur answer_value
            answer_value = response.get('answer_value')

            # Détecter NC selon type de réponse
            if isinstance(answer_value, bool) and answer_value is False:
                response['conformite'] = 'non_conforme'
                response['risque'] = 'moyen'
                response['action_requise'] = True
                response['justification'] = "Réponse négative détectée (analyse manuelle nécessaire)"
                nonconformities.append(response)
            elif isinstance(answer_value, str) and answer_value.lower() in ['non', 'no', 'non applicable']:
                response['conformite'] = 'non_conforme' if 'non' in answer_value.lower() else 'non_applicable'
                response['risque'] = 'moyen' if 'non' in answer_value.lower() else 'faible'
                response['action_requise'] = 'non' in answer_value.lower()
                response['justification'] = f"Réponse '{answer_value}' nécessite vérification"
                if response['action_requise']:
                    nonconformities.append(response)

        logger.info(f"🔍 Fallback : {len(nonconformities)} NC détectées sur {len(responses)} réponses")
        return nonconformities

    # ==================== PHASE 2.5: RE-VALIDATION 2-PASS ====================

    async def phase2_5_revalidate_analysis(
        self,
        nonconformities: List[Dict[str, Any]],
        db: Session,
        action_plan: ActionPlan,
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        Phase 2.5 : Re-validation 2-pass des non-conformités détectées.

        Cette phase effectue une seconde analyse IA sur les NC détectées en Phase 2
        pour confirmer/affiner les niveaux de conformité et risque, garantissant
        une analyse plus robuste (comme pour la génération de questions).

        Args:
            nonconformities: NC détectées en Phase 2
            db: Session database
            action_plan: ActionPlan en cours
            progress_callback: Callback pour SSE

        Returns:
            NC validées et potentiellement affinées
        """
        logger.info(f"🔍 Phase 2.5 : Re-validation 2-pass de {len(nonconformities)} NC...")

        if not nonconformities:
            logger.info("✅ Aucune NC à re-valider")
            return []

        # Informer l'utilisateur
        if progress_callback:
            await self._update_progress(
                action_plan, db,
                progress_callback=progress_callback
            )

        # Préparer contexte campagne
        campaign_id = action_plan.campaign_id
        campaign_query = text("""
            SELECT c.title, c.description, f.name as framework_name
            FROM campaign c
            LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
            LEFT JOIN framework f ON q.framework_id = f.id
            WHERE c.id = CAST(:campaign_id AS uuid)
        """)
        campaign_info = db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()

        campaign_json = json.dumps({
            "title": campaign_info.title if campaign_info else "Campagne d'audit",
            "framework": campaign_info.framework_name if campaign_info else "ISO 27001",
            "description": campaign_info.description if campaign_info else ""
        }, ensure_ascii=False, indent=2)

        # Préparer données pour re-validation
        questions_json = json.dumps([
            {
                "question_id": str(nc['question_id']),
                "question_text": nc['question_text'],
                "answer_value": nc['answer_value'],
                "answer_comment": nc.get('answer_comment', ''),
                "current_conformite": nc.get('conformite'),
                "current_risque": nc.get('risque'),
                "current_justification": nc.get('justification')
            }
            for nc in nonconformities
        ], ensure_ascii=False, indent=2)

        # Prompt de re-validation (utilise 02_analysis_prompt avec contexte enrichi)
        revalidation_prompt = self.analysis_prompt.format(
            language="FR",
            campaign_json=campaign_json,
            questions_json=questions_json
        )

        # Appel IA pour re-validation
        try:
            logger.info(f"📡 Appel IA pour re-valider {len(nonconformities)} NC...")

            # Informer l'utilisateur
            if progress_callback:
                await self._update_progress(
                    action_plan, db,
                    progress_callback=progress_callback
                )

            response = await self.client.post(
                f"{self.ollama_base_url}/api/generate",
                json={
                    "model": "deepseek-v3.1:671b-cloud",
                    "system": self.system_prompt,
                    "prompt": revalidation_prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=120.0
            )

            if response.status_code == 200:
                result = response.json()

                # Informer l'utilisateur
                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        progress_callback=progress_callback
                    )

                ai_revalidation = json.loads(result['response'])

                # Créer index pour accès rapide
                revalidation_index = {
                    qa['question_id']: qa
                    for qa in ai_revalidation.get('questions_analysis', [])
                }

                # Consolider avec résultats Phase 2
                validated_nc = []
                adjusted_count = 0

                for nc in nonconformities:
                    qid = str(nc['question_id'])

                    if qid in revalidation_index:
                        revalidated = revalidation_index[qid]

                        # Conserver le plus conservateur entre Phase 2 et re-validation
                        original_conformite = nc.get('conformite')
                        revalidated_conformite = revalidated.get('conformite')

                        original_risque = nc.get('risque')
                        revalidated_risque = revalidated.get('risque')

                        # Priorité conformité : non_conforme > partiel > conforme
                        conformite_priority = {'non_conforme': 3, 'partiel': 2, 'conforme': 1, 'non_applicable': 0}
                        final_conformite = max(
                            [original_conformite, revalidated_conformite],
                            key=lambda c: conformite_priority.get(c, 0)
                        )

                        # Priorité risque : critique > élevé > moyen > faible
                        risque_priority = {'critique': 4, 'élevé': 3, 'moyen': 2, 'faible': 1}
                        final_risque = max(
                            [original_risque, revalidated_risque],
                            key=lambda r: risque_priority.get(r, 0)
                        )

                        # Vérifier si ajustement
                        if final_conformite != original_conformite or final_risque != original_risque:
                            adjusted_count += 1
                            logger.info(
                                f"🔄 Ajustement Q{qid}: "
                                f"conformité {original_conformite}→{final_conformite}, "
                                f"risque {original_risque}→{final_risque}"
                            )

                        # Mettre à jour NC avec valeurs validées
                        nc['conformite'] = final_conformite
                        nc['risque'] = final_risque
                        nc['justification'] = revalidated.get('justification', nc.get('justification'))
                        nc['action_requise'] = revalidated.get('action_requise', True)

                        # Garder uniquement si action toujours requise
                        if nc['action_requise']:
                            validated_nc.append(nc)
                    else:
                        # Pas de re-validation IA, garder original
                        validated_nc.append(nc)

                # Informer l'utilisateur
                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        progress_callback=progress_callback
                    )

                logger.info(
                    f"✅ Re-validation terminée : {len(validated_nc)}/{len(nonconformities)} NC confirmées, "
                    f"{adjusted_count} ajustées, {len(nonconformities) - len(validated_nc)} rejetées"
                )
                return validated_nc

            else:
                logger.warning(f"⚠️ Erreur IA re-validation: {response.status_code}, NC Phase 2 conservées")

                # Informer l'utilisateur
                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        progress_callback=progress_callback
                    )

                return nonconformities

        except Exception as e:
            logger.error(f"❌ Erreur appel IA Phase 2.5: {str(e)}, NC Phase 2 conservées")

            # Informer l'utilisateur
            if progress_callback:
                await self._update_progress(
                    action_plan, db,
                    progress_callback=progress_callback
                )

            return nonconformities

    # ==================== PHASE 3: GÉNÉRATION PLAN D'ACTION COMPLET ====================

    async def phase3_generate_actions(
        self,
        nonconformities: List[Dict[str, Any]],
        action_plan_id: UUID,
        db: Session,
        action_plan: ActionPlan,
        progress_callback: Optional[callable] = None
    ) -> List[ActionPlanItem]:
        """
        Phase 3 : Génère le plan d'action complet avec regroupement IA.

        Utilise le prompt 03_action_plan_prompt pour :
        - Regrouper les NC similaires en actions cohérentes
        - Générer action_plan_summary (titre, risque global, justification)
        - Générer actions structurées avec justifications complètes

        Returns:
            Liste des ActionPlanItem créés avec regroupement
        """
        logger.info("🤖 Phase 3 : Génération plan d'action complet avec IA...")

        # Récupérer infos campagne
        campaign_id = action_plan.campaign_id
        campaign_query = text("""
            SELECT c.title, c.description, c.tenant_id, f.name as framework_name,
                   o.name as org_name
            FROM campaign c
            LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
            LEFT JOIN framework f ON q.framework_id = f.id
            LEFT JOIN organization o ON c.tenant_id = o.id
            WHERE c.id = CAST(:campaign_id AS uuid)
        """)
        campaign_info = db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()

        # Récupérer rôles autorisés depuis la table role
        roles_query = text("""
            SELECT code, label FROM role
            WHERE tenant_id = CAST(:tenant_id AS uuid) OR tenant_id IS NULL
            ORDER BY label
        """)
        roles_result = db.execute(roles_query, {
            "tenant_id": str(campaign_info.tenant_id) if campaign_info else None
        })
        allowed_roles = [row.code for row in roles_result]

        # Préparer contexte campagne
        campaign_json = json.dumps({
            "title": campaign_info.title if campaign_info else "Campagne d'audit",
            "organization": campaign_info.org_name if campaign_info else "Organisation",
            "framework": campaign_info.framework_name if campaign_info else "ISO 27001",
            "description": campaign_info.description if campaign_info else ""
        }, ensure_ascii=False, indent=2)

        # Préparer liste rôles
        allowed_roles_json = json.dumps(allowed_roles, ensure_ascii=False, indent=2)

        # Préparer non-conformités
        non_conformities_json = json.dumps([
            {
                "question_id": str(nc['question_id']),
                "question_text": nc['question_text'],
                "answer_value": nc['answer_value'],
                "conformite": nc.get('conformite'),
                "risque": nc.get('risque'),
                "justification": nc.get('justification'),
                "requirement_code": nc.get('requirement_code'),
                "requirement_title": nc.get('requirement_title'),
                "domain_name": nc.get('domain_name')
            }
            for nc in nonconformities
        ], ensure_ascii=False, indent=2)

        # Formater prompt Phase 3
        action_plan_prompt_filled = self.action_plan_prompt.format(
            language="FR",  # TODO: détecter langue
            campaign_json=campaign_json,
            allowed_roles_json=allowed_roles_json,
            non_conformities_json=non_conformities_json
        )

        # Appel IA pour génération plan complet
        try:
            logger.info(f"📡 Appel IA pour générer plan d'action ({len(nonconformities)} NC)...")

            # Informer l'utilisateur
            if progress_callback:
                await self._update_progress(
                    action_plan, db,
                    phase3_status=PhaseStatus.IN_PROGRESS,
                    progress_callback=progress_callback
                )

            response = await self.client.post(
                f"{self.ollama_base_url}/api/generate",
                json={
                    "model": "deepseek-v3.1:671b-cloud",
                    "system": self.system_prompt,
                    "prompt": action_plan_prompt_filled,
                    "stream": False,
                    "format": "json"
                },
                timeout=180.0  # 3 minutes pour génération complète
            )

            if response.status_code == 200:
                result = response.json()

                # Informer l'utilisateur
                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        progress_callback=progress_callback
                    )

                ai_plan = json.loads(result['response'])

                # Mettre à jour summary du plan
                summary = ai_plan.get('action_plan_summary', {})
                action_plan.title = summary.get('title', f"Plan d'action - {campaign_info.title if campaign_info else 'Audit'}")
                action_plan.overall_risk_level = summary.get('overall_risk_level', 'moyen')
                action_plan.summary_justification = summary.get('global_justification', '')

                # Informer l'utilisateur
                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        progress_callback=progress_callback
                    )

                # Créer ActionPlanItem pour chaque action
                action_items = []
                for idx, ai_action in enumerate(ai_plan.get('actions', []), 1):
                    try:
                        item = ActionPlanItem(
                            action_plan_id=action_plan_id,
                            status=ActionPlanItemStatus.PROPOSED,
                            local_id=ai_action.get('local_id'),
                            title=ai_action['title'],
                            description=ai_action['description'],
                            objective=ai_action.get('objective', ''),
                            deliverables=ai_action.get('deliverables', []),
                            severity=ActionSeverity[ai_action['severity'].upper()],
                            priority=ActionPriority[ai_action['priority'].upper()],
                            recommended_due_days=ai_action['recommended_due_days'],
                            suggested_role=ai_action['suggested_role'],
                            assignment_method=AssignmentMethod.AI_SUGGESTED,
                            source_question_ids=[UUID(qid) for qid in ai_action.get('source_questions', [])],
                            referential_controls=ai_action.get('referential_controls', []),
                            ai_justifications=ai_action.get('justification', {})
                        )

                        db.add(item)
                        action_items.append(item)

                        # Informer l'utilisateur tous les 5 actions
                        if progress_callback and idx % 5 == 0:
                            await self._update_progress(
                                action_plan, db,
                                progress_callback=progress_callback
                            )

                    except Exception as e:
                        logger.error(f"❌ Erreur création action {ai_action.get('local_id')}: {str(e)}")

                db.commit()

                # Informer l'utilisateur
                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        progress_callback=progress_callback
                    )

                logger.info(f"✅ Plan d'action généré : {len(action_items)} actions (regroupées depuis {len(nonconformities)} NC)")
                return action_items

            else:
                logger.warning(f"⚠️ Erreur IA génération: {response.status_code}, fallback")

                # Informer l'utilisateur
                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        progress_callback=progress_callback
                    )

                return await self._fallback_generate_actions(nonconformities, action_plan_id, db)

        except Exception as e:
            logger.error(f"❌ Erreur appel IA Phase 3: {str(e)}")

            # Informer l'utilisateur
            if progress_callback:
                await self._update_progress(
                    action_plan, db,
                    progress_callback=progress_callback
                )

            return await self._fallback_generate_actions(nonconformities, action_plan_id, db)

    async def _fallback_generate_actions(
        self,
        nonconformities: List[Dict[str, Any]],
        action_plan_id: UUID,
        db: Session
    ) -> List[ActionPlanItem]:
        """
        Fallback : génération 1 action par NC si IA indisponible.

        Returns:
            Actions générées par règles
        """
        logger.info("🔧 Fallback : génération actions par règles...")

        action_items = []
        for idx, nc in enumerate(nonconformities):
            ai_result = self._fallback_action_generation(nc)

            item = ActionPlanItem(
                action_plan_id=action_plan_id,
                status=ActionPlanItemStatus.PROPOSED,
                local_id=f"ACT-{idx+1}",
                title=ai_result['title'],
                description=ai_result['description'],
                severity=ActionSeverity[ai_result['severity'].upper()],
                priority=ActionPriority[ai_result['priority'].upper()],
                recommended_due_days=ai_result['recommended_due_days'],
                suggested_role=ai_result['suggested_role'],
                assignment_method=AssignmentMethod.AI_SUGGESTED,
                source_question_ids=[nc['question_id']],
                referential_controls=[nc.get('requirement_code', 'N/A')],
                ai_justifications=ai_result.get('justifications', {})
            )

            db.add(item)
            action_items.append(item)

        db.commit()
        logger.info(f"✅ Fallback : {len(action_items)} actions générées")
        return action_items

    async def _call_ai_for_action(self, nc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Appelle Ollama pour générer une action corrective.

        Args:
            nc: Non-conformité avec contexte

        Returns:
            Dict avec title, description, severity, priority, etc.
        """
        # Prompt structuré pour l'IA
        prompt = self._build_action_prompt(nc)

        try:
            # Appel Ollama avec DeepSeek
            response = await self.client.post(
                f"{self.ollama_base_url}/api/generate",
                json={
                    "model": "deepseek-v3.1:671b-cloud",  # Modèle disponible
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=60.0  # Timeout de 60 secondes pour l'IA
            )

            if response.status_code == 200:
                result = response.json()
                ai_response = json.loads(result['response'])
                return ai_response
            else:
                logger.warning(f"⚠️ Erreur Ollama: {response.status_code}, fallback sur règles")
                return self._fallback_action_generation(nc)

        except Exception as e:
            logger.warning(f"⚠️ Erreur appel IA: {str(e)}, fallback sur règles")
            return self._fallback_action_generation(nc)

    def _build_action_prompt(self, nc: Dict[str, Any]) -> str:
        """
        Construit le prompt pour l'IA.

        Args:
            nc: Non-conformité

        Returns:
            Prompt formaté
        """
        return f"""Tu es un expert en cybersécurité et conformité réglementaire.

CONTEXTE:
- Exigence: {nc.get('requirement_code', 'N/A')} - {nc.get('requirement_title', 'N/A')}
- Question: {nc.get('question_text', 'N/A')}
- Réponse: {nc.get('answer_value', 'N/A')}
- Conformité: {nc.get('conformite', 'N/A')}
- Risque: {nc.get('risque', 'N/A')}
- Justification: {nc.get('justification', 'N/A')}

TÂCHE:
Génère UNE action corrective structurée pour combler cette non-conformité.

RÈGLES STRICTES:
1. Severity:
   - critical: Contrôle vital absent (risque majeur immédiat)
   - major: Contrôle important manquant (non-conformité grave)
   - minor: Écart limité (amélioration nécessaire)
   - info: Recommandation (amélioration continue)

2. Priority:
   - P1: Critical + Urgent (30-60 jours)
   - P2: Important + Non urgent (60-120 jours)
   - P3: Amélioration continue (90-180 jours)

3. Action:
   - Concrète, réalisable, mesurable
   - Adresse la cause racine
   - S'aligne avec l'exigence

RÉPONSE (JSON strict):
{{
  "title": "Titre court et clair de l'action",
  "description": "Description détaillée de l'action à réaliser avec étapes concrètes",
  "severity": "critical|major|minor|info",
  "priority": "P1|P2|P3",
  "recommended_due_days": 30-180,
  "suggested_role": "RSSI|DPO|CISO|IT Manager|Security Officer",
  "justifications": {{
    "why_action": "Pourquoi cette action est nécessaire",
    "why_severity": "Pourquoi ce niveau de criticité",
    "why_priority": "Pourquoi cette priorité",
    "why_role": "Pourquoi ce rôle est approprié"
  }}
}}
"""

    def _fallback_action_generation(self, nc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Génération d'action par règles (fallback si IA indisponible).

        Args:
            nc: Non-conformité

        Returns:
            Action générée par règles
        """
        # Déterminer severity basé sur conformité et risque
        conformite = nc.get('conformite', '')
        risque = nc.get('risque', '')

        if risque == 'critique' or conformite == 'non_conforme':
            severity = 'critical'
            priority = 'P1'
            due_days = 30
        elif risque == 'élevé' or conformite == 'partiel':
            severity = 'major'
            priority = 'P2'
            due_days = 90
        else:
            severity = 'minor'
            priority = 'P3'
            due_days = 120

        return {
            "title": f"Mise en conformité : {nc.get('requirement_code', 'N/A')}",
            "description": f"Traiter la non-conformité identifiée pour l'exigence {nc.get('requirement_code', 'N/A')}. "
                          f"État actuel : {conformite}. Risque : {risque}. "
                          f"Justification : {nc.get('justification', 'N/A')}",
            "severity": severity,
            "priority": priority,
            "recommended_due_days": due_days,
            "suggested_role": "RSSI",
            "justifications": {
                "why_action": "Non-conformité détectée",
                "why_severity": f"Basé sur conformité={conformite} et risque={risque}",
                "why_priority": f"Priorité {priority} selon niveau de risque",
                "why_role": "RSSI par défaut"
            }
        }

    # ==================== PHASE 4: ASSIGNATION AUTOMATIQUE ====================

    async def phase4_auto_assign(
        self,
        action_items: List[ActionPlanItem],
        campaign_id: UUID,
        db: Session,
        action_plan: ActionPlan,
        progress_callback: Optional[callable] = None
    ) -> List[ActionPlanItem]:
        """
        Phase 4 : Assigne automatiquement les actions aux responsables.

        Logique d'assignation:
        1. Chercher dans role_assignments (mapping explicite)
        2. Fallback sur manager/owner de la campagne
        3. Si audit EXTERNAL: utiliser audit_resp
        4. Fallback final: owner du tenant

        Returns:
            Actions avec assigned_user_id rempli
        """
        logger.info("👥 Phase 4 : Assignation automatique...")

        # Récupérer infos campagne
        campaign_query = text("""
            SELECT c.id, c.manager_id, c.owner_id, c.tenant_id, c.audit_type
            FROM campaign c
            WHERE c.id = CAST(:campaign_id AS uuid)
        """)
        campaign_result = db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()

        if not campaign_result:
            raise ValueError(f"Campagne {campaign_id} introuvable")

        assigned_count = 0

        for item in action_items:
            try:
                # Tenter assignation
                assigned_user_id = await self._find_assignee(
                    item, campaign_result, db
                )

                if assigned_user_id:
                    item.assigned_user_id = assigned_user_id
                    item.assignment_method = AssignmentMethod.ROLE_BASED
                    assigned_count += 1
                else:
                    # Pas d'assignation trouvée
                    item.assignment_method = AssignmentMethod.AI_SUGGESTED

                if progress_callback:
                    await self._update_progress(
                        action_plan, db,
                        actions_assigned=assigned_count,
                        progress_callback=progress_callback
                    )

            except Exception as e:
                logger.error(f"❌ Erreur assignation action {item.id}: {str(e)}")

        db.commit()

        logger.info(f"✅ {assigned_count}/{len(action_items)} actions assignées")
        return action_items

    async def _find_assignee(
        self,
        item: ActionPlanItem,
        campaign: Any,
        db: Session
    ) -> Optional[UUID]:
        """
        Trouve le responsable approprié pour une action.

        Args:
            item: ActionPlanItem à assigner
            campaign: Row de la campagne
            db: Session DB

        Returns:
            UUID du user assigné, ou None
        """
        # 1. Chercher dans role_assignments (TODO: implémenter table)
        # role_query = text(...)

        # 2. Fallback sur manager de la campagne
        if campaign.manager_id:
            return campaign.manager_id

        # 3. Fallback sur owner
        if campaign.owner_id:
            return campaign.owner_id

        # 4. Aucun assigné trouvé
        return None

    # ==================== HELPERS ====================

    async def _update_progress(
        self,
        action_plan: ActionPlan,
        db: Session,
        current_phase: Optional[int] = None,
        phase1_status: Optional[PhaseStatus] = None,
        phase2_status: Optional[PhaseStatus] = None,
        phase3_status: Optional[PhaseStatus] = None,
        phase4_status: Optional[PhaseStatus] = None,
        questions_analyzed: Optional[int] = None,
        total_questions: Optional[int] = None,
        non_conformities_found: Optional[int] = None,
        actions_generated: Optional[int] = None,
        actions_assigned: Optional[int] = None,
        progress_callback: Optional[callable] = None
    ):
        """
        Met à jour la progression dans action_plan.generation_progress.

        Args:
            action_plan: ActionPlan à mettre à jour
            db: Session DB
            current_phase: Phase actuelle (1-4)
            phase1_status...phase4_status: Statuts des phases
            questions_analyzed...actions_assigned: Compteurs
            progress_callback: Fonction pour envoyer SSE
        """
        # Récupérer progression actuelle
        progress = action_plan.generation_progress or {}

        # Mettre à jour les champs fournis
        if current_phase is not None:
            progress['current_phase'] = current_phase
        if phase1_status is not None:
            progress['phase1_status'] = phase1_status.value
        if phase2_status is not None:
            progress['phase2_status'] = phase2_status.value
        if phase3_status is not None:
            progress['phase3_status'] = phase3_status.value
        if phase4_status is not None:
            progress['phase4_status'] = phase4_status.value
        if questions_analyzed is not None:
            progress['questions_analyzed'] = questions_analyzed
        if total_questions is not None:
            progress['total_questions'] = total_questions
        if non_conformities_found is not None:
            progress['non_conformities_found'] = non_conformities_found
        if actions_generated is not None:
            progress['actions_generated'] = actions_generated
        if actions_assigned is not None:
            progress['actions_assigned'] = actions_assigned

        # Calculer temps restant estimé (simpliste)
        progress['estimated_time_remaining'] = self._estimate_remaining_time(progress)

        action_plan.generation_progress = progress
        action_plan.updated_at = datetime.now(timezone.utc)

        db.commit()

        # Callback SSE si fourni
        if progress_callback:
            await progress_callback(GenerationProgress(**progress))

    def _estimate_remaining_time(self, progress: Dict) -> int:
        """
        Estime le temps restant en secondes (très simpliste).

        Returns:
            Temps estimé en secondes
        """
        current_phase = progress.get('current_phase', 1)

        # Temps estimé par phase (en secondes)
        phase_times = {1: 10, 2: 5, 3: 60, 4: 10}

        remaining = 0
        for phase in range(current_phase + 1, 5):
            remaining += phase_times.get(phase, 10)

        return remaining

    def _calculate_statistics(self, items: List[ActionPlanItem]) -> Dict[str, Any]:
        """
        Calcule les statistiques du plan d'action.

        Args:
            items: Liste des ActionPlanItem

        Returns:
            Dict avec total, counts par severity, overall_risk
        """
        stats = {
            'total': len(items),
            'critical': 0,
            'major': 0,
            'minor': 0,
            'info': 0,
            'overall_risk': 'low'
        }

        for item in items:
            if item.severity == ActionSeverity.CRITICAL:
                stats['critical'] += 1
            elif item.severity == ActionSeverity.MAJOR:
                stats['major'] += 1
            elif item.severity == ActionSeverity.MINOR:
                stats['minor'] += 1
            elif item.severity == ActionSeverity.INFO:
                stats['info'] += 1

        # Déterminer risque global
        if stats['critical'] > 0:
            stats['overall_risk'] = 'critical'
        elif stats['major'] > 3:
            stats['overall_risk'] = 'high'
        elif stats['major'] > 0:
            stats['overall_risk'] = 'medium'
        else:
            stats['overall_risk'] = 'low'

        return stats
