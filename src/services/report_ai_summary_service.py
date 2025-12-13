"""
Service de génération de résumés IA pour les rapports d'audit.

Génère des résumés exécutifs en utilisant DeepSeek/Ollama avec différents
tons adaptés aux publics cibles (Direction, RSSI, Auditeurs).
"""

from typing import Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
import httpx
import os
import logging

logger = logging.getLogger(__name__)


class ReportAISummaryService:
    """Génère des résumés IA pour les rapports d'audit."""

    # ========================================================================
    # PROMPT SYSTÈME (Base commune) - FORMAT JSON OBLIGATOIRE
    # ========================================================================
    SYSTEM_PROMPT = """Tu es un expert senior en cybersécurité et conformité ISO 27001 avec 15 ans d'expérience en audit.

MISSION : Analyser les résultats d'un audit de cybersécurité et générer un résumé exécutif professionnel.

⚠️ INSTRUCTION CRITIQUE - FORMAT JSON OBLIGATOIRE :
Tu dois TOUJOURS répondre avec un objet JSON valide contenant le résumé.
Format de réponse OBLIGATOIRE :
{
  "summary": "Le contenu complet du résumé ici..."
}

RÈGLES ABSOLUES :
- Maximum 400 mots dans le résumé
- Français formel et professionnel
- Chiffres précis (pourcentages, nombres exacts)
- Pas de formules de politesse ni d'introduction générique
- Pas de jargon technique excessif sauf si ton "technical"
- Ton factuel, direct et orienté décision
- Structure claire avec sections visuellement distinctes
- Utiliser les emojis ✅ ⚠️ 🔴 🎯 📅 pour la lisibilité

FORMAT DU RÉSUMÉ (dans le champ "summary") :
- Texte structuré prêt à être inséré dans un PDF
- Pas de markdown (pas de ** ou ## ou ```)
- Listes à puces avec le caractère •
- Sections séparées par \\n\\n (double saut de ligne)
"""

    # ========================================================================
    # PROMPTS PAR TON - RAPPORT CONSOLIDÉ
    # ========================================================================
    CONSOLIDATED_PROMPTS = {
        "executive": """
CONTEXTE : Rapport consolidé multi-organismes pour Direction générale / CODIR

PUBLIC CIBLE : PDG, DAF, membres du comité de direction
Ils veulent : Vue stratégique, risques business, ROI, décisions à prendre

STRUCTURE OBLIGATOIRE :

VUE D'ENSEMBLE (2-3 phrases)
Résumer la portée de l'audit et le niveau de maturité global de l'écosystème.
Mentionner le nombre d'organismes, le taux de conformité moyen, et le positionnement.

✅ POINTS FORTS (3-4 bullets)
Identifier les domaines où les investissements portent leurs fruits.
Focus sur ce qui fonctionne et protège l'entreprise.

⚠️ RISQUES STRATÉGIQUES (3-4 bullets)
Identifier les risques business majeurs (pas techniques).
Formuler en termes d'impact : "Exposition à...", "Risque de...", "Vulnérabilité face à..."

🎯 RECOMMANDATIONS PRIORITAIRES (3 actions max)
Actions concrètes avec estimation budgétaire et timeline.
Format : [Action] ([Trimestre], [Budget estimé])
""",

        "technical": """
CONTEXTE : Rapport consolidé multi-organismes pour équipes techniques

PUBLIC CIBLE : RSSI, DSI, Responsables sécurité, Équipes IT
Ils veulent : Détails techniques, mesures concrètes, indicateurs précis, plan d'action opérationnel

STRUCTURE OBLIGATOIRE :

SYNTHÈSE TECHNIQUE (2-3 phrases)
Périmètre technique évalué, nombre de contrôles, score de maturité selon échelle 1-5.

✅ CONFORMITÉS TECHNIQUES (4-5 bullets)
Contrôles bien implémentés avec niveau de détail technique.
Mentionner les outils, configurations, processus en place.

🔴 NON-CONFORMITÉS TECHNIQUES (4-5 bullets)
Gaps identifiés avec précision technique.
Format : [Domaine] : [Problème technique précis]

🎯 PLAN D'ACTION TECHNIQUE (4-5 actions)
Mesures techniques prioritaires avec effort estimé.
Format : [Action technique] ([Durée estimée])

📊 INDICATEURS CLÉS À SUIVRE
Métriques techniques à suivre.
""",

        "detailed": """
CONTEXTE : Rapport consolidé multi-organismes pour experts conformité

PUBLIC CIBLE : Auditeurs, Consultants GRC, Experts conformité, Juristes
Ils veulent : Analyse méthodologique, détails par clause ISO, observations qualitatives, recommandations normatives

STRUCTURE OBLIGATOIRE :

CONTEXTE D'AUDIT (3-4 phrases)
Méthodologie appliquée, périmètre, échantillonnage, référentiels croisés, limitations.

📊 RÉSULTATS PAR CLAUSE ISO 27001 (tableau ou liste)
Analyse statistique par annexe A avec variance inter-organismes.

🔍 OBSERVATIONS MÉTHODOLOGIQUES (3-4 bullets)
Qualité des preuves, cohérence des réponses, points d'attention audit.

📋 ANALYSE DES ÉCARTS (par criticité)
Écarts critiques, majeurs, mineurs avec références normatives.

🎯 RECOMMANDATIONS NORMATIVES
Actions classées par horizon temporel avec référence aux clauses ISO.
"""
    }

    # ========================================================================
    # PROMPTS PAR TON - RAPPORT INDIVIDUEL
    # ========================================================================
    INDIVIDUAL_PROMPTS = {
        "executive": """
CONTEXTE : Rapport individuel pour Direction de l'organisme audité

PUBLIC CIBLE : Direction générale de l'organisme audité
Ils veulent : Où ils en sont, comment ils se comparent, quoi faire en priorité

STRUCTURE OBLIGATOIRE :

POSITIONNEMENT (2-3 phrases)
Score global, niveau de maturité, position vs pairs et vs secteur.
Évolution par rapport à l'audit précédent si disponible.

✅ ATOUTS À CAPITALISER (3-4 bullets)
Ce qui fonctionne bien et doit être maintenu/valorisé.

⚠️ AXES D'AMÉLIORATION PRIORITAIRES (3-4 bullets)
Domaines nécessitant investissement, formulés en termes business.

🎯 FEUILLE DE ROUTE (3-4 étapes)
Plan d'action séquencé avec jalons clairs.

💰 INVESTISSEMENT RECOMMANDÉ
Estimation budgétaire globale et ROI attendu.
""",

        "technical": """
CONTEXTE : Rapport individuel pour équipe technique de l'organisme

PUBLIC CIBLE : DSI, RSSI, Équipe IT de l'organisme audité
Ils veulent : Détails techniques précis, quoi corriger comment

STRUCTURE OBLIGATOIRE :

ÉTAT DES LIEUX TECHNIQUE (2-3 phrases)
Score par domaine technique, points de contrôle évalués, niveau CMMI/maturité.

✅ CONTRÔLES CONFORMES (5-6 bullets)
Mesures techniques en place et efficaces.
Mentionner outils, configurations, versions.

🔴 ÉCARTS TECHNIQUES À CORRIGER (5-6 bullets)
Non-conformités avec détail technique précis.
Format : [Contrôle] : [État actuel] → [État cible]

🎯 PLAN DE REMÉDIATION TECHNIQUE (5-6 actions)
Actions techniques ordonnées par priorité et dépendance.
Format : [Action] | Effort : [J/H] | Prérequis : [X]

📊 MÉTRIQUES CIBLES
KPIs techniques à atteindre.
""",

        "detailed": """
CONTEXTE : Rapport individuel détaillé pour responsable conformité

PUBLIC CIBLE : Responsable conformité, DPO, Consultant GRC de l'organisme
Ils veulent : Analyse exhaustive, mapping normatif, plan de certification

STRUCTURE OBLIGATOIRE :

ANALYSE DE MATURITÉ (3-4 phrases)
Positionnement sur échelle de maturité (Initial/Répétable/Défini/Géré/Optimisé).
Benchmark détaillé par domaine vs référentiel et vs pairs.

📊 CARTOGRAPHIE CONFORMITÉ
Analyse détaillée par domaine ISO avec taux et tendance.

🔍 ANALYSE DES PREUVES
Qualité et complétude de la documentation fournie.
Écarts entre déclaratif et preuves.

📋 REGISTRE DES ÉCARTS
Liste exhaustive classée par criticité avec référence normative.

🎯 TRAJECTOIRE DE CERTIFICATION
Roadmap détaillée vers certification ISO 27001 si applicable.
Jalons, prérequis, effort estimé.

📅 PLAN D'ACTION DÉTAILLÉ
Actions par trimestre avec responsable suggéré et livrables.
"""
    }

    def __init__(self, db: Session):
        self.db = db
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        # Utilise OLLAMA_MODEL_ADVANCED car OLLAMA_MODEL peut être GLM qui ne fonctionne pas bien
        self.model = os.getenv("OLLAMA_MODEL_ADVANCED", "deepseek-v3.1:671b-cloud")
        logger.info(f"🤖 ReportAISummaryService initialisé avec modèle: {self.model}")

    # ========================================================================
    # MÉTHODES PUBLIQUES
    # ========================================================================

    async def generate_campaign_summary(
        self,
        campaign_id: UUID,
        tenant_id: UUID,
        tone: str = "executive",
        language: str = "fr"
    ) -> Dict[str, Any]:
        """
        Génère un résumé consolidé pour une campagne entière.

        Args:
            campaign_id: ID de la campagne
            tenant_id: ID du tenant
            tone: executive, technical, detailed
            language: fr, en

        Returns:
            Dict avec executive_summary, key_findings, top_recommendations, statistics
        """
        logger.info(f"🤖 Génération résumé campagne {campaign_id} - Ton: {tone}")

        # 1. Collecter les données
        campaign_data = self._collect_campaign_data(campaign_id, tenant_id)

        # 2. Construire le prompt
        system_prompt = self.SYSTEM_PROMPT + self.CONSOLIDATED_PROMPTS.get(tone, self.CONSOLIDATED_PROMPTS["executive"])
        user_prompt = self._build_consolidated_prompt(campaign_data)

        # 3. Appeler DeepSeek
        summary_text = await self._call_deepseek(system_prompt, user_prompt)

        # 4. Structurer la réponse
        return {
            "executive_summary": summary_text,
            "key_findings": campaign_data.get("key_findings", []),
            "top_recommendations": campaign_data.get("top_actions", []),
            "statistics": campaign_data.get("stats", {}),
            "tone": tone,
            "generated_at": datetime.utcnow().isoformat()
        }

    async def generate_entity_summary(
        self,
        campaign_id: UUID,
        entity_id: UUID,
        tenant_id: UUID,
        tone: str = "executive",
        language: str = "fr"
    ) -> Dict[str, Any]:
        """
        Génère un résumé individuel pour une entité spécifique.

        Args:
            campaign_id: ID de la campagne
            entity_id: ID de l'entité
            tenant_id: ID du tenant
            tone: executive, technical, detailed
            language: fr, en

        Returns:
            Dict avec executive_summary, benchmarking, recommendations
        """
        logger.info(f"🤖 Génération résumé entité {entity_id} - Ton: {tone}")

        # 1. Collecter les données de l'entité
        entity_data = self._collect_entity_data(campaign_id, entity_id, tenant_id)

        # 2. Construire le prompt
        system_prompt = self.SYSTEM_PROMPT + self.INDIVIDUAL_PROMPTS.get(tone, self.INDIVIDUAL_PROMPTS["executive"])
        user_prompt = self._build_individual_prompt(entity_data)

        # 3. Appeler DeepSeek
        summary_text = await self._call_deepseek(system_prompt, user_prompt)

        # 4. Structurer la réponse
        return {
            "executive_summary": summary_text,
            "entity_name": entity_data.get("entity", {}).get("name", "N/A"),
            "benchmarking": entity_data.get("benchmarking", {}),
            "recommendations": entity_data.get("recommendations", []),
            "tone": tone,
            "generated_at": datetime.utcnow().isoformat()
        }

    # ========================================================================
    # MÉTHODES PUBLIQUES SYNCHRONES (pour appels depuis contexte non-async)
    # ========================================================================

    def generate_campaign_summary_sync(
        self,
        campaign_id: UUID,
        tenant_id: UUID,
        tone: str = "executive",
        language: str = "fr"
    ) -> Dict[str, Any]:
        """
        Version synchrone de generate_campaign_summary.
        À utiliser depuis un contexte non-async (ex: job processor).
        """
        logger.info(f"🤖 [SYNC] Génération résumé campagne {campaign_id} - Ton: {tone}")

        # 1. Collecter les données
        campaign_data = self._collect_campaign_data(campaign_id, tenant_id)

        # 2. Construire le prompt
        system_prompt = self.SYSTEM_PROMPT + self.CONSOLIDATED_PROMPTS.get(tone, self.CONSOLIDATED_PROMPTS["executive"])
        user_prompt = self._build_consolidated_prompt(campaign_data)

        # 3. Appeler DeepSeek (version sync)
        summary_text = self._call_deepseek_sync(system_prompt, user_prompt)

        # 4. Structurer la réponse
        return {
            "executive_summary": summary_text,
            "key_findings": campaign_data.get("key_findings", []),
            "top_recommendations": campaign_data.get("top_actions", []),
            "statistics": campaign_data.get("stats", {}),
            "tone": tone,
            "generated_at": datetime.utcnow().isoformat()
        }

    def generate_entity_summary_sync(
        self,
        campaign_id: UUID,
        entity_id: UUID,
        tenant_id: UUID,
        tone: str = "executive",
        language: str = "fr"
    ) -> Dict[str, Any]:
        """
        Version synchrone de generate_entity_summary.
        À utiliser depuis un contexte non-async (ex: job processor).
        """
        logger.info(f"🤖 [SYNC] Génération résumé entité {entity_id} - Ton: {tone}")

        # 1. Collecter les données de l'entité
        entity_data = self._collect_entity_data(campaign_id, entity_id, tenant_id)

        # 2. Construire le prompt
        system_prompt = self.SYSTEM_PROMPT + self.INDIVIDUAL_PROMPTS.get(tone, self.INDIVIDUAL_PROMPTS["executive"])
        user_prompt = self._build_individual_prompt(entity_data)

        # 3. Appeler DeepSeek (version sync)
        summary_text = self._call_deepseek_sync(system_prompt, user_prompt)

        # 4. Structurer la réponse
        return {
            "executive_summary": summary_text,
            "entity_name": entity_data.get("entity", {}).get("name", "N/A"),
            "benchmarking": entity_data.get("benchmarking", {}),
            "recommendations": entity_data.get("recommendations", []),
            "tone": tone,
            "generated_at": datetime.utcnow().isoformat()
        }

    # ========================================================================
    # COLLECTE DE DONNÉES
    # ========================================================================

    def _collect_campaign_data(self, campaign_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Collecte les données consolidées de la campagne."""
        try:
            # Informations campagne
            # Note: la table campaign utilise launch_date/due_date (pas start_date/end_date)
            campaign_query = text("""
                SELECT c.title, c.launch_date, c.due_date, f.name as framework_name
                FROM campaign c
                LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
                LEFT JOIN framework f ON q.framework_id = f.id
                WHERE c.id = CAST(:campaign_id AS uuid)
            """)
            campaign_result = self.db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()

            # Statistiques globales
            # NOTE: compliance_status utilise les valeurs anglaises: 'compliant', 'non_compliant', 'partial'
            stats_query = text("""
                SELECT
                    COUNT(DISTINCT qr.id) as total_questions,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status = 'compliant' THEN qr.id END) as conformes,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status IN ('non_compliant', 'partial') THEN qr.id END) as nc_count
                FROM question_answer qr
                JOIN audit a ON qr.audit_id = a.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
            """)
            stats_result = self.db.execute(stats_query, {"campaign_id": str(campaign_id)}).fetchone()

            total_questions = stats_result.total_questions or 0
            conformes = stats_result.conformes or 0
            conformity_rate = round((conformes / total_questions * 100), 1) if total_questions > 0 else 0

            # Entités
            entities_query = text("""
                SELECT
                    ee.id, ee.name, ee.stakeholder_type,
                    COUNT(DISTINCT qr.id) as questions,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status = 'compliant' THEN qr.id END) as conformes
                FROM ecosystem_entity ee
                JOIN audit a ON a.entity_id = ee.id
                JOIN question_answer qr ON qr.audit_id = a.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                GROUP BY ee.id, ee.name, ee.stakeholder_type
            """)
            entities_results = self.db.execute(entities_query, {"campaign_id": str(campaign_id)}).fetchall()

            entities_summary = []
            for e in entities_results:
                score = round((e.conformes / e.questions * 100), 1) if e.questions > 0 else 0
                entities_summary.append({
                    "name": e.name,
                    "type": e.stakeholder_type or "N/A",
                    "score": score,
                    "level": self._get_maturity_level(score)
                })

            # Domaines
            domains_query = text("""
                SELECT
                    COALESCE(d.code_officiel, d.code) as name,
                    COUNT(DISTINCT qr.id) as questions,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status = 'compliant' THEN qr.id END) as conformes
                FROM domain d
                JOIN requirement r ON r.domain_id = d.id
                JOIN question q ON q.requirement_id = r.id
                JOIN question_answer qr ON qr.question_id = q.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                GROUP BY d.id, COALESCE(d.code_officiel, d.code)
                ORDER BY d.code
            """)
            domains_results = self.db.execute(domains_query, {"campaign_id": str(campaign_id)}).fetchall()

            domain_analysis = []
            for d in domains_results:
                rate = round((d.conformes / d.questions * 100), 1) if d.questions > 0 else 0
                domain_analysis.append({
                    "name": d.name,
                    "conformity_rate": rate
                })

            # NC critiques
            nc_query = text("""
                SELECT
                    ee.name as entity_name,
                    COALESCE(d.code_officiel, d.code) as domain_name,
                    q.question_text
                FROM question_answer qr
                JOIN audit a ON qr.audit_id = a.id
                JOIN ecosystem_entity ee ON a.entity_id = ee.id
                JOIN question q ON qr.question_id = q.id
                JOIN requirement r ON q.requirement_id = r.id
                JOIN domain d ON r.domain_id = d.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                  AND qr.compliance_status = 'non_compliant'
                LIMIT 10
            """)
            nc_results = self.db.execute(nc_query, {"campaign_id": str(campaign_id)}).fetchall()

            critical_nc = [
                {"entity_name": nc.entity_name, "domain": nc.domain_name, "control_point": nc.question_text[:80]}
                for nc in nc_results
            ]

            # Statistiques des preuves (attachments)
            attachments_query = text("""
                SELECT
                    COUNT(DISTINCT att.id) as total_attachments,
                    COUNT(DISTINCT CASE WHEN att.virus_scan_status = 'clean' THEN att.id END) as clean_files,
                    COUNT(DISTINCT att.answer_id) as answers_with_evidence,
                    COALESCE(SUM(att.file_size), 0) as total_size_bytes,
                    array_agg(DISTINCT att.attachment_type) FILTER (WHERE att.attachment_type IS NOT NULL) as attachment_types
                FROM answer_attachment att
                JOIN question_answer qr ON att.answer_id = qr.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                  AND att.is_active = true
                  AND att.deleted_at IS NULL
            """)
            attachments_result = self.db.execute(attachments_query, {"campaign_id": str(campaign_id)}).fetchone()

            evidence_stats = {
                "total_attachments": attachments_result.total_attachments or 0,
                "clean_files": attachments_result.clean_files or 0,
                "answers_with_evidence": attachments_result.answers_with_evidence or 0,
                "total_size_mb": round((attachments_result.total_size_bytes or 0) / (1024 * 1024), 2),
                "attachment_types": attachments_result.attachment_types or [],
                "evidence_coverage_rate": round((attachments_result.answers_with_evidence or 0) / total_questions * 100, 1) if total_questions > 0 else 0
            }

            return {
                "campaign": {
                    "title": campaign_result.title if campaign_result else "N/A",
                    "framework_name": campaign_result.framework_name if campaign_result else "N/A"
                },
                "stats": {
                    "total_questions": total_questions,
                    "conformity_rate": conformity_rate,
                    "entities_count": len(entities_summary),
                    "nc_critical": len([e for e in entities_summary if e["score"] < 50]),
                    "nc_major": len([e for e in entities_summary if 50 <= e["score"] < 70])
                },
                "entities_summary": entities_summary,
                "domain_analysis": domain_analysis,
                "critical_nc": critical_nc,
                "evidence_stats": evidence_stats,
                "key_findings": self._extract_key_findings(domain_analysis),
                "top_actions": self._get_top_actions(critical_nc)
            }

        except Exception as e:
            logger.error(f"❌ Erreur collecte données campagne: {e}")
            # Rollback pour éviter que l'erreur ne bloque les transactions suivantes
            try:
                self.db.rollback()
            except Exception:
                pass
            return {
                "campaign": {"title": "N/A", "framework_name": "N/A"},
                "stats": {"total_questions": 0, "conformity_rate": 0},
                "entities_summary": [],
                "domain_analysis": [],
                "critical_nc": []
            }

    def _collect_entity_data(self, campaign_id: UUID, entity_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Collecte les données d'une entité spécifique pour rapport INDIVIDUEL."""
        try:
            logger.info(f"🔍 DEBUG _collect_entity_data - campaign_id={campaign_id}, entity_id={entity_id}, tenant_id={tenant_id}")

            # ================================================================
            # 1. INFORMATIONS DE LA CAMPAGNE (contexte essentiel)
            # ================================================================
            campaign_query = text("""
                SELECT
                    c.title as campaign_title,
                    c.description as campaign_description,
                    c.launch_date as start_date,
                    c.due_date as end_date,
                    f.name as framework_name,
                    f.code as framework_code,
                    f.version as framework_version,
                    f.description as framework_description,
                    q.name as questionnaire_name
                FROM campaign c
                LEFT JOIN questionnaire q ON c.questionnaire_id = q.id
                LEFT JOIN framework f ON q.framework_id = f.id
                WHERE c.id = CAST(:campaign_id AS uuid)
            """)
            campaign_result = self.db.execute(campaign_query, {"campaign_id": str(campaign_id)}).fetchone()
            logger.info(f"🔍 DEBUG campaign_result: {campaign_result}")

            # ================================================================
            # 2. INFORMATIONS ENRICHIES DE L'ENTITÉ
            # ================================================================
            entity_query = text("""
                SELECT
                    ee.name,
                    ee.stakeholder_type,
                    ee.city,
                    ee.country_code,
                    ee.description as entity_description,
                    ee.entity_category as sector,
                    ee.legal_name as employee_count,
                    ee.annual_revenue,
                    cat.name as category_name,
                    cat.entity_category
                FROM ecosystem_entity ee
                LEFT JOIN categories cat ON ee.category_id = cat.id
                WHERE ee.id = CAST(:entity_id AS uuid)
            """)
            entity_result = self.db.execute(entity_query, {"entity_id": str(entity_id)}).fetchone()
            logger.info(f"🔍 DEBUG entity_result: {entity_result}")
            logger.info(f"🔍 DEBUG entity_name: {entity_result.name if entity_result else 'NONE'}")

            # Score de l'entité
            # NOTE: compliance_status utilise les valeurs anglaises: 'compliant', 'non_compliant', 'partial'
            score_query = text("""
                SELECT
                    COUNT(DISTINCT qr.id) as total_questions,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status = 'compliant' THEN qr.id END) as conformes,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status IN ('non_compliant', 'partial') THEN qr.id END) as nc_count
                FROM question_answer qr
                JOIN audit a ON qr.audit_id = a.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                  AND a.entity_id = CAST(:entity_id AS uuid)
            """)
            score_result = self.db.execute(score_query, {
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id)
            }).fetchone()

            total = score_result.total_questions or 0
            conformes = score_result.conformes or 0
            global_score = round((conformes / total * 100), 1) if total > 0 else 0
            logger.info(f"🔍 DEBUG score: total={total}, conformes={conformes}, global_score={global_score}%")

            # Benchmarking vs autres entités
            benchmark_query = text("""
                SELECT
                    a.entity_id,
                    COUNT(DISTINCT qr.id) as questions,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status = 'compliant' THEN qr.id END) as conformes
                FROM question_answer qr
                JOIN audit a ON qr.audit_id = a.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                GROUP BY a.entity_id
            """)
            benchmark_results = self.db.execute(benchmark_query, {"campaign_id": str(campaign_id)}).fetchall()

            all_scores = []
            for b in benchmark_results:
                score = round((b.conformes / b.questions * 100), 1) if b.questions > 0 else 0
                all_scores.append({"entity_id": str(b.entity_id), "score": score})

            all_scores.sort(key=lambda x: x["score"], reverse=True)
            position = next((i + 1 for i, s in enumerate(all_scores) if s["entity_id"] == str(entity_id)), 0)
            avg_score = round(sum(s["score"] for s in all_scores) / len(all_scores), 1) if all_scores else 0

            # Domaines de l'entité
            domains_query = text("""
                SELECT
                    COALESCE(d.code_officiel, d.code) as name,
                    COUNT(DISTINCT qr.id) as questions,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status = 'compliant' THEN qr.id END) as conformes,
                    COUNT(DISTINCT CASE WHEN qr.compliance_status IN ('non_compliant', 'partial') THEN qr.id END) as nc_count
                FROM domain d
                JOIN requirement r ON r.domain_id = d.id
                JOIN question q ON q.requirement_id = r.id
                JOIN question_answer qr ON qr.question_id = q.id
                JOIN audit a ON qr.audit_id = a.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                  AND a.entity_id = CAST(:entity_id AS uuid)
                GROUP BY d.id, COALESCE(d.code_officiel, d.code)
                ORDER BY d.code
            """)
            domains_results = self.db.execute(domains_query, {
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id)
            }).fetchall()

            domain_analysis = []
            strengths = []
            for d in domains_results:
                rate = round((d.conformes / d.questions * 100), 1) if d.questions > 0 else 0
                domain_analysis.append({
                    "name": d.name,
                    "conformity_rate": rate,
                    "nc": d.nc_count
                })
                if rate >= 80:
                    strengths.append({"title": d.name, "score": rate})

            # ================================================================
            # NON-CONFORMITÉS DÉTAILLÉES (avec commentaires et recommandations)
            # ================================================================
            # Colonnes vérifiées: domain(title, code, code_officiel), requirement(official_code, title),
            # question(question_text), control_point(implementation_guidance)
            nc_query = text("""
                SELECT
                    COALESCE(d.code_officiel, d.code) as domain_name,
                    d.title as domain_full_name,
                    r.official_code as requirement_code,
                    r.title as requirement_title,
                    q.question_text,
                    qr.comment as auditor_comment,
                    qr.compliance_status,
                    cp.implementation_guidance as control_recommendation
                FROM question_answer qr
                JOIN audit a ON qr.audit_id = a.id
                JOIN question q ON qr.question_id = q.id
                LEFT JOIN requirement r ON q.requirement_id = r.id
                LEFT JOIN domain d ON r.domain_id = d.id
                LEFT JOIN control_point cp ON q.control_point_id = cp.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                  AND a.entity_id = CAST(:entity_id AS uuid)
                  AND qr.compliance_status IN ('non_compliant', 'partial')
                ORDER BY d.code, r.official_code
            """)
            nc_results = self.db.execute(nc_query, {
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id)
            }).fetchall()

            # Séparer NC totales et partielles
            nc_total = [nc for nc in nc_results if nc.compliance_status == 'non_compliant']
            nc_partiel = [nc for nc in nc_results if nc.compliance_status == 'partial']

            non_conformities = {
                "critical": [
                    {
                        "domain": nc.domain_name,
                        "domain_full": nc.domain_full_name,
                        "requirement": nc.requirement_code,
                        "control_point": nc.question_text,
                        "auditor_comment": nc.auditor_comment or "Aucun commentaire",
                        "recommendation": nc.control_recommendation or "À définir"
                    }
                    for nc in nc_total[:10]  # Top 10 NC totales
                ],
                "major": [
                    {
                        "domain": nc.domain_name,
                        "control_point": nc.question_text[:100],
                        "status": "Partiel",
                        "auditor_comment": nc.auditor_comment or ""
                    }
                    for nc in nc_partiel[:10]  # Top 10 NC partielles
                ],
                "total_nc": len(nc_total),
                "total_partial": len(nc_partiel)
            }

            # Statistiques des preuves (attachments) pour cette entité
            entity_attachments_query = text("""
                SELECT
                    COUNT(DISTINCT att.id) as total_attachments,
                    COUNT(DISTINCT CASE WHEN att.virus_scan_status = 'clean' THEN att.id END) as clean_files,
                    COUNT(DISTINCT att.answer_id) as answers_with_evidence,
                    COALESCE(SUM(att.file_size), 0) as total_size_bytes,
                    array_agg(DISTINCT att.attachment_type) FILTER (WHERE att.attachment_type IS NOT NULL) as attachment_types,
                    array_agg(DISTINCT att.original_filename) FILTER (WHERE att.original_filename IS NOT NULL) as filenames
                FROM answer_attachment att
                JOIN question_answer qr ON att.answer_id = qr.id
                JOIN audit a ON qr.audit_id = a.id
                WHERE qr.campaign_id = CAST(:campaign_id AS uuid)
                  AND a.entity_id = CAST(:entity_id AS uuid)
                  AND att.is_active = true
                  AND att.deleted_at IS NULL
            """)
            entity_attachments_result = self.db.execute(entity_attachments_query, {
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id)
            }).fetchone()

            evidence_stats = {
                "total_attachments": entity_attachments_result.total_attachments or 0,
                "clean_files": entity_attachments_result.clean_files or 0,
                "answers_with_evidence": entity_attachments_result.answers_with_evidence or 0,
                "total_size_mb": round((entity_attachments_result.total_size_bytes or 0) / (1024 * 1024), 2),
                "attachment_types": entity_attachments_result.attachment_types or [],
                "sample_filenames": (entity_attachments_result.filenames or [])[:10],  # Limiter à 10 exemples
                "evidence_coverage_rate": round((entity_attachments_result.answers_with_evidence or 0) / total * 100, 1) if total > 0 else 0
            }

            # Fallback: utiliser le nom du questionnaire si pas de framework
            framework_name = "N/A"
            if campaign_result:
                if campaign_result.framework_name:
                    framework_name = campaign_result.framework_name
                elif campaign_result.questionnaire_name:
                    framework_name = campaign_result.questionnaire_name

            return {
                # ✅ NOUVEAU: Contexte de la campagne
                "campaign": {
                    "title": campaign_result.campaign_title if campaign_result else "N/A",
                    "description": campaign_result.campaign_description if campaign_result else "",
                    "framework_name": framework_name,
                    "framework_code": campaign_result.framework_code if campaign_result and campaign_result.framework_code else "",
                    "framework_version": campaign_result.framework_version if campaign_result and campaign_result.framework_version else "",
                    "framework_description": campaign_result.framework_description if campaign_result and campaign_result.framework_description else "",
                    "questionnaire_name": campaign_result.questionnaire_name if campaign_result and campaign_result.questionnaire_name else "",
                    "start_date": str(campaign_result.start_date) if campaign_result and campaign_result.start_date else "N/A",
                    "end_date": str(campaign_result.end_date) if campaign_result and campaign_result.end_date else "N/A"
                },
                # ✅ ENRICHI: Informations détaillées de l'entité
                "entity": {
                    "name": entity_result.name if entity_result else "N/A",
                    "type": entity_result.stakeholder_type if entity_result else "N/A",
                    "city": entity_result.city if entity_result else "N/A",
                    "country": entity_result.country_code if entity_result else "N/A",
                    "description": getattr(entity_result, 'entity_description', None) or "",
                    "sector": getattr(entity_result, 'sector', None) or "Non spécifié",
                    "employee_count": getattr(entity_result, 'employee_count', None) or "Non spécifié",
                    "category": getattr(entity_result, 'category_name', None) or "Non catégorisé",
                    "entity_category": getattr(entity_result, 'entity_category', None) or ""
                },
                "score": {
                    "global_score": global_score,
                    "maturity_level": self._get_maturity_level(global_score),
                    "total_questions": total,
                    "conformes": conformes,
                    "nc_count": score_result.nc_count or 0
                },
                "benchmarking": {
                    "entity_score": global_score,
                    "average_score": avg_score,
                    "position": position,
                    "total_entities": len(all_scores),
                    "performance_vs_average": round(global_score - avg_score, 1)
                },
                "domain_analysis": domain_analysis,
                "non_conformities": non_conformities,
                "evidence_stats": evidence_stats,
                "strengths": strengths,
                "recommendations": self._generate_recommendations(domain_analysis, non_conformities)
            }

        except Exception as e:
            logger.error(f"❌ Erreur collecte données entité: {e}")
            # Rollback pour éviter que l'erreur ne bloque les transactions suivantes
            try:
                self.db.rollback()
            except Exception:
                pass
            return {
                "entity": {"name": "N/A"},
                "score": {"global_score": 0},
                "benchmarking": {},
                "domain_analysis": [],
                "non_conformities": {"critical": [], "major": []}
            }

    # ========================================================================
    # CONSTRUCTION DES PROMPTS
    # ========================================================================

    def _build_consolidated_prompt(self, data: Dict[str, Any]) -> str:
        """Construit le prompt utilisateur pour rapport consolidé."""
        entities_text = "\n".join([
            f"{i+1}. {e['name']} ({e['type']})\n   - Score : {e['score']}%\n   - Niveau : {e['level']}"
            for i, e in enumerate(data.get("entities_summary", []))
        ])

        domains_text = "\n".join([
            f"- {d['name']} : {d['conformity_rate']}%"
            for d in data.get("domain_analysis", [])
        ])

        nc_text = "\n".join([
            f"{i+1}. [{nc['entity_name']}] {nc['control_point']}"
            for i, nc in enumerate(data.get("critical_nc", []))
        ])

        # Statistiques des preuves
        evidence = data.get("evidence_stats", {})
        evidence_types = ", ".join(evidence.get("attachment_types", [])) if evidence.get("attachment_types") else "Aucun"

        return f"""
DONNÉES DE L'AUDIT CONSOLIDÉ :

📊 CAMPAGNE
- Titre : {data['campaign']['title']}
- Date : {datetime.now().strftime('%d/%m/%Y')}
- Référentiel : {data['campaign']['framework_name']}

📈 STATISTIQUES GLOBALES
- Organismes audités : {data['stats']['entities_count']}
- Taux de conformité moyen : {data['stats']['conformity_rate']}%
- NC critiques : {data['stats']['nc_critical']}
- NC majeures : {data['stats']['nc_major']}

📎 PREUVES DOCUMENTAIRES
- Total pièces jointes : {evidence.get('total_attachments', 0)}
- Fichiers vérifiés (clean) : {evidence.get('clean_files', 0)}
- Questions avec preuves : {evidence.get('answers_with_evidence', 0)}
- Taux de couverture : {evidence.get('evidence_coverage_rate', 0)}%
- Volume total : {evidence.get('total_size_mb', 0)} MB
- Types de documents : {evidence_types}

🏢 PERFORMANCE PAR ORGANISME
{entities_text}

📊 ANALYSE PAR DOMAINE (moyenne écosystème)
{domains_text}

🔴 TOP NC CRITIQUES
{nc_text}

---

GÉNÈRE LE RÉSUMÉ EXÉCUTIF EN RESPECTANT STRICTEMENT :
- La structure obligatoire du ton demandé
- Maximum 400 mots
- Chiffres exacts tirés des données ci-dessus
- Mentionner la qualité et couverture des preuves documentaires

⚠️ RÉPONDS UNIQUEMENT AVEC UN JSON VALIDE AU FORMAT:
{
  "summary": "TON RÉSUMÉ COMPLET ICI (avec sections VUE D'ENSEMBLE, POINTS FORTS, RISQUES, etc.)"
}
"""

    def _build_individual_prompt(self, data: Dict[str, Any]) -> str:
        """Construit le prompt utilisateur pour rapport INDIVIDUEL personnalisé."""

        # ================================================================
        # EXTRACTION DES DONNÉES ENRICHIES
        # ================================================================
        campaign = data.get("campaign", {})
        entity = data.get("entity", {})
        score = data.get("score", {})
        bench = data.get("benchmarking", {})
        evidence = data.get("evidence_stats", {})
        nc = data.get("non_conformities", {})

        # Analyse par domaine
        domains_text = "\n".join([
            f"  • {d['name']} : {d['conformity_rate']}% de conformité ({d['nc']} non-conformités)"
            for d in data.get("domain_analysis", [])
        ]) or "  Aucune donnée par domaine"

        # NC critiques avec détails enrichis
        nc_critical_list = nc.get("critical", [])
        nc_critical_text = "\n".join([
            f"  {i+1}. [{item.get('domain', 'N/A')}] {item.get('control_point', '')[:150]}\n"
            f"     → Commentaire auditeur : {item.get('auditor_comment', 'Aucun')[:100]}\n"
            f"     → Recommandation : {item.get('recommendation', 'À définir')[:100]}"
            for i, item in enumerate(nc_critical_list[:6])
        ]) or "  Aucune non-conformité critique"

        # NC partielles
        nc_partial_list = nc.get("major", [])
        nc_partial_text = "\n".join([
            f"  • [{item.get('domain', 'N/A')}] {item.get('control_point', '')[:100]}"
            for item in nc_partial_list[:5]
        ]) or "  Aucune conformité partielle"

        # Points forts
        strengths_text = "\n".join([
            f"  • {s['title']} ({s['score']}% de conformité)"
            for s in data.get("strengths", [])
        ]) or "  Aucun domaine à plus de 80% de conformité"

        # Statistiques preuves
        evidence_types = ", ".join(evidence.get("attachment_types", [])) if evidence.get("attachment_types") else "Aucun type spécifié"
        sample_files = evidence.get("sample_filenames", [])
        sample_files_text = "\n".join([f"    - {f}" for f in sample_files[:5]]) if sample_files else "    Aucune preuve documentaire fournie"

        # ================================================================
        # CONSTRUCTION DU PROMPT ENRICHI
        # ================================================================
        return f"""
══════════════════════════════════════════════════════════════════════
                    RAPPORT D'AUDIT INDIVIDUEL
                    DONNÉES POUR ANALYSE IA
══════════════════════════════════════════════════════════════════════

📋 CONTEXTE DE LA CAMPAGNE D'AUDIT
────────────────────────────────────────────────────────────────────
• Campagne : {campaign.get('title', 'N/A')}
• Description : {campaign.get('description', 'Non renseignée')[:200]}
• Référentiel : {campaign.get('framework_name', 'N/A')} ({campaign.get('framework_code', '')})
• Version : {campaign.get('framework_version', 'N/A')}
• Période : du {campaign.get('start_date', 'N/A')} au {campaign.get('end_date', 'N/A')}

🏢 ORGANISME AUDITÉ : {entity.get('name', 'N/A')}
────────────────────────────────────────────────────────────────────
• Nom complet : {entity.get('name', 'N/A')}
• Type d'organisation : {entity.get('type', 'N/A')}
• Catégorie : {entity.get('category', 'Non catégorisé')} ({entity.get('entity_category', '')})
• Localisation : {entity.get('city', 'N/A')}, {entity.get('country', 'N/A')}
• Secteur d'activité : {entity.get('sector', 'Non spécifié')}
• Effectifs : {entity.get('employee_count', 'Non spécifié')}
• Description : {entity.get('description', 'Non renseignée')[:200]}

⚠️ IMPORTANT : Ce rapport concerne UNIQUEMENT l'organisme "{entity.get('name', 'N/A')}".
Toutes les analyses et recommandations doivent être spécifiques à cette entité.

🎯 RÉSULTATS DE L'ÉVALUATION
────────────────────────────────────────────────────────────────────
• Score de conformité global : {score.get('global_score', 0)}%
• Niveau de maturité : {score.get('maturity_level', 'N/A')}
• Points de contrôle évalués : {score.get('total_questions', 0)}
• Conformes : {score.get('conformes', 0)}
• Non conformes : {nc.get('total_nc', score.get('nc_count', 0))}
• Partiellement conformes : {nc.get('total_partial', 0)}

📈 POSITIONNEMENT (Benchmarking)
────────────────────────────────────────────────────────────────────
• Score de {entity.get('name', 'N/A')} : {bench.get('entity_score', 0)}%
• Moyenne des {bench.get('total_entities', 0)} entités auditées : {bench.get('average_score', 0)}%
• Position : {bench.get('position', 0)}ème sur {bench.get('total_entities', 0)} entités
• Écart par rapport à la moyenne : {'+' if bench.get('performance_vs_average', 0) >= 0 else ''}{bench.get('performance_vs_average', 0)}%

📊 ANALYSE DÉTAILLÉE PAR DOMAINE
────────────────────────────────────────────────────────────────────
{domains_text}

🔴 NON-CONFORMITÉS IDENTIFIÉES ({nc.get('total_nc', 0)} totales)
────────────────────────────────────────────────────────────────────
{nc_critical_text}

⚠️ CONFORMITÉS PARTIELLES ({nc.get('total_partial', 0)} contrôles)
────────────────────────────────────────────────────────────────────
{nc_partial_text}

✅ POINTS FORTS (Domaines >= 80% conformité)
────────────────────────────────────────────────────────────────────
{strengths_text}

📎 PREUVES DOCUMENTAIRES FOURNIES PAR {entity.get('name', 'N/A')}
────────────────────────────────────────────────────────────────────
• Nombre total de pièces jointes : {evidence.get('total_attachments', 0)}
• Fichiers validés (sans virus) : {evidence.get('clean_files', 0)}
• Questions avec preuves : {evidence.get('answers_with_evidence', 0)} / {score.get('total_questions', 0)}
• Taux de couverture documentaire : {evidence.get('evidence_coverage_rate', 0)}%
• Volume total : {evidence.get('total_size_mb', 0)} MB
• Types de documents : {evidence_types}
• Exemples de fichiers fournis :
{sample_files_text}

══════════════════════════════════════════════════════════════════════
                    INSTRUCTIONS DE GÉNÉRATION
══════════════════════════════════════════════════════════════════════

GÉNÈRE UN RÉSUMÉ EXÉCUTIF PERSONNALISÉ pour {entity.get('name', 'N/A')} en respectant :

1. PERSONNALISATION OBLIGATOIRE :
   - Mentionner systématiquement le nom "{entity.get('name', 'N/A')}" dans l'analyse
   - Adapter les recommandations au contexte de l'organisme
   - Faire référence aux données spécifiques ci-dessus

2. STRUCTURE À RESPECTER (selon le ton demandé) :
   - Utiliser les sections obligatoires du ton (executive/technical/detailed)
   - Maximum 500 mots

3. CHIFFRES À UTILISER :
   - Score : {score.get('global_score', 0)}%
   - Niveau : {score.get('maturity_level', 'N/A')}
   - NC : {nc.get('total_nc', 0)} non-conformités
   - Preuves : {evidence.get('evidence_coverage_rate', 0)}% de couverture

4. FOCUS SUR LES ÉCARTS :
   - Analyser les domaines les plus faibles
   - Proposer des actions concrètes pour {entity.get('name', 'N/A')}

⚠️ RÉPONDS UNIQUEMENT AVEC UN JSON VALIDE AU FORMAT:
{{
  "summary": "TON RÉSUMÉ COMPLET ICI PERSONNALISÉ POUR {entity.get('name', 'N/A')}"
}}
"""

    # ========================================================================
    # APPEL IA
    # ========================================================================

    def _extract_content_from_response(self, result: Dict[str, Any]) -> str:
        """
        Extrait le contenu de la réponse Ollama/OpenAI-like.
        Gère plusieurs formats de réponse possibles.

        Pour GLM-4.6 en mode "thinking":
        - "thinking" = raisonnement interne du modèle
        - "content" = réponse finale formatée (ce qu'on veut)

        IMPORTANT: Si content est vide, on utilise thinking comme fallback car
        GLM-4.6 peut parfois mettre le résumé complet dans thinking au lieu de content.
        """
        # Format Ollama /api/chat: {"message": {"content": "...", "thinking": "..."}}
        message = result.get("message", {})

        # Log détaillé pour debug
        msg_keys = list(message.keys()) if isinstance(message, dict) else []
        content_len = len(message.get("content", "")) if isinstance(message, dict) else 0
        thinking_len = len(message.get("thinking", "")) if isinstance(message, dict) else 0
        logger.info(f"🔍 Message keys: {msg_keys}, content: {content_len} chars, thinking: {thinking_len} chars")

        content = message.get("content", "")

        # Si content est vide mais thinking existe, utiliser thinking comme fallback
        # GLM-4.6 met parfois tout dans thinking de manière incohérente
        if not content and "thinking" in message:
            thinking_content = message.get("thinking", "")
            if thinking_content:
                # Marqueurs qui indiquent un résumé formaté (pas du raisonnement)
                summary_markers = [
                    "VUE D'ENSEMBLE", "POINTS FORTS", "RISQUES", "RECOMMANDATIONS",
                    "SYNTHÈSE", "CONFORMITÉ", "NON-CONFORMITÉ", "PLAN D'ACTION",
                    "POSITIONNEMENT", "ATOUTS", "AXES D'AMÉLIORATION", "FEUILLE DE ROUTE",
                    "ÉTAT DES LIEUX", "CONTRÔLES CONFORMES", "ÉCARTS TECHNIQUES",
                    "CONTEXTE D'AUDIT", "OBSERVATIONS", "ANALYSE DES ÉCARTS"
                ]
                is_formatted_summary = any(marker in thinking_content.upper() for marker in summary_markers)

                # Marqueurs qui indiquent du raisonnement (à éviter)
                reasoning_markers = [
                    "LET ME", "I NEED TO", "I WILL", "FIRST,", "STEP 1",
                    "**DECONSTRUCT", "ANALYZE THE", "UNDERSTAND THE"
                ]
                is_reasoning = any(marker in thinking_content.upper() for marker in reasoning_markers)

                if is_formatted_summary and not is_reasoning:
                    logger.info(f"🧠 Résumé formaté trouvé dans 'thinking' ({len(thinking_content)} chars)")
                    content = thinking_content
                elif is_reasoning:
                    logger.warning(f"⚠️ 'thinking' contient du raisonnement EN ANGLAIS, pas un résumé ({len(thinking_content)} chars)")
                    logger.info(f"   Preview thinking: {thinking_content[:300]}...")
                    # Ne pas utiliser le raisonnement, laisser content vide
                else:
                    # Ni résumé formaté ni raisonnement clair - utiliser quand même comme fallback
                    logger.warning(f"⚠️ 'thinking' contenu non classifié, utilisation comme fallback ({len(thinking_content)} chars)")
                    content = thinking_content

        # Fallback: certains modèles retournent directement {"content": "..."}
        if not content and "content" in result:
            content = result.get("content", "")

        # Fallback: format OpenAI {"choices": [{"message": {"content": "..."}}]}
        if not content and "choices" in result:
            choices = result.get("choices", [])
            if choices and "message" in choices[0]:
                choice_message = choices[0]["message"]
                content = choice_message.get("content", "")
                # Vérifier aussi "thinking" dans le format OpenAI
                if not content and "thinking" in choice_message:
                    content = choice_message.get("thinking", "")

        # Fallback: format {"response": "..."} (certains modèles Ollama)
        if not content and "response" in result:
            content = result.get("response", "")

        return content

    async def _call_deepseek(self, system_prompt: str, user_prompt: str) -> str:
        """
        Appel à DeepSeek via Ollama (version async).

        Utilise format: "json" pour forcer GLM-4.6 à mettre la réponse dans content.
        """
        try:
            # Timeout élevé pour laisser le modèle travailler
            async with httpx.AsyncClient(timeout=180) as client:
                logger.info(f"🚀 Appel Ollama {self.model} avec format=json...")

                response = await client.post(
                    f"{self.ollama_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "format": "json",  # ⚠️ CRUCIAL: Force le contenu dans "content"
                        "stream": False,
                        "keep_alive": "5m",
                        "options": {
                            "temperature": 0.3,
                            "num_predict": 4000,  # Augmenté pour résumés longs
                            "top_p": 0.9,
                            "repeat_penalty": 1.1
                        }
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"🔍 Réponse Ollama (clés): {list(result.keys())}")

                    # Avec format=json, le contenu est TOUJOURS dans message.content
                    content = self._extract_content_from_response(result)

                    # Parser le JSON pour extraire le résumé
                    summary = self._parse_json_summary(content)

                    if summary:
                        logger.info(f"✅ Résumé IA généré ({len(summary)} chars)")
                    else:
                        logger.warning(f"⚠️ Résumé vide après parsing JSON")

                    return summary
                else:
                    logger.error(f"❌ Erreur Ollama: {response.status_code} - {response.text[:500]}")
                    return self._generate_fallback_summary(user_prompt)

        except Exception as e:
            logger.error(f"❌ Erreur appel DeepSeek: {e}")
            return self._generate_fallback_summary(user_prompt)

    def _call_deepseek_sync(self, system_prompt: str, user_prompt: str) -> str:
        """
        Appel à DeepSeek via Ollama (version synchrone pour contexte non-async).

        Utilise format: "json" pour forcer GLM-4.6 à mettre la réponse dans content.
        """
        try:
            # Timeout élevé pour laisser le modèle travailler
            with httpx.Client(timeout=180) as client:
                logger.info(f"🚀 [SYNC] Appel Ollama {self.model} avec format=json...")

                response = client.post(
                    f"{self.ollama_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "format": "json",  # ⚠️ CRUCIAL: Force le contenu dans "content"
                        "stream": False,
                        "keep_alive": "5m",
                        "options": {
                            "temperature": 0.3,
                            "num_predict": 4000,  # Augmenté pour résumés longs
                            "top_p": 0.9,
                            "repeat_penalty": 1.1
                        }
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"🔍 Réponse Ollama sync (clés): {list(result.keys())}")

                    # Log détaillé de la structure message
                    message = result.get("message", {})
                    logger.info(f"🔍 Message keys: {list(message.keys()) if isinstance(message, dict) else 'N/A'}")
                    content_len = len(message.get('content', '')) if isinstance(message, dict) else 0
                    logger.info(f"🔍 content length: {content_len}")

                    # Afficher les 500 premiers caractères de content
                    if message.get("content"):
                        logger.info(f"📝 CONTENT (500 chars): {message.get('content', '')[:500]}")

                    # Avec format=json, le contenu est TOUJOURS dans message.content
                    content = self._extract_content_from_response(result)

                    # Parser le JSON pour extraire le résumé
                    summary = self._parse_json_summary(content)

                    if summary:
                        logger.info(f"✅ Résumé IA généré (sync) ({len(summary)} chars)")
                        logger.info(f"📄 RÉSUMÉ FINAL (500 chars): {summary[:500]}")
                    else:
                        logger.warning(f"⚠️ Résumé vide après parsing JSON (sync)")

                    return summary
                else:
                    logger.error(f"❌ Erreur Ollama: {response.status_code} - {response.text[:500]}")
                    return self._generate_fallback_summary(user_prompt)

        except Exception as e:
            logger.error(f"❌ Erreur appel DeepSeek (sync): {e}")
            return self._generate_fallback_summary(user_prompt)

    def _parse_json_summary(self, content: str) -> str:
        """
        Parse le JSON retourné par l'IA et extrait le résumé.

        Le modèle doit retourner: {"summary": "..."}

        Gère plusieurs cas:
        - JSON valide avec clé "summary"
        - JSON avec autres clés (fallback sur première valeur string longue)
        - Texte brut (fallback si pas JSON valide)
        """
        import json

        if not content:
            logger.warning("⚠️ Contenu vide reçu pour parsing JSON")
            return ""

        # Nettoyer le contenu (enlever backticks markdown si présents)
        cleaned = content.strip()
        if cleaned.startswith("```"):
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            else:
                cleaned = cleaned[3:]
            if "```" in cleaned:
                cleaned = cleaned.split("```")[0]
            cleaned = cleaned.strip()

        try:
            # Tenter de parser le JSON
            data = json.loads(cleaned)

            # Cas 1: Clé "summary" directe
            if isinstance(data, dict) and "summary" in data:
                summary = data["summary"]
                logger.info(f"✅ JSON parsé avec succès - clé 'summary' trouvée ({len(summary)} chars)")
                return summary

            # Cas 2: Chercher une clé contenant "summary" ou "résumé"
            if isinstance(data, dict):
                for key in data:
                    if "summary" in key.lower() or "résumé" in key.lower() or "resume" in key.lower():
                        summary = data[key]
                        if isinstance(summary, str) and len(summary) > 50:
                            logger.info(f"✅ JSON parsé - clé '{key}' utilisée ({len(summary)} chars)")
                            return summary

                # Cas 3: Fallback sur première valeur string longue
                for key, value in data.items():
                    if isinstance(value, str) and len(value) > 100:
                        logger.warning(f"⚠️ Fallback: utilisation de la clé '{key}' ({len(value)} chars)")
                        return value

            # Cas 4: Si c'est une string directe
            if isinstance(data, str) and len(data) > 50:
                logger.info(f"✅ JSON était une string directe ({len(data)} chars)")
                return data

            logger.warning(f"⚠️ Structure JSON inattendue: {str(data)[:200]}")
            return str(data) if data else ""

        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ JSON invalide, utilisation du contenu brut: {e}")
            # Si le contenu ressemble à un résumé (pas du raisonnement en anglais)
            summary_markers = ["VUE D'ENSEMBLE", "POINTS FORTS", "SYNTHÈSE", "POSITIONNEMENT"]
            reasoning_markers = ["LET ME", "I NEED TO", "STEP 1", "FIRST,"]

            is_summary = any(marker in cleaned.upper() for marker in summary_markers)
            is_reasoning = any(marker in cleaned.upper() for marker in reasoning_markers)

            if is_summary and not is_reasoning:
                logger.info(f"📝 Contenu brut utilisé comme résumé ({len(cleaned)} chars)")
                return cleaned
            elif is_reasoning:
                logger.warning(f"⚠️ Contenu rejeté (raisonnement en anglais)")
                return ""
            else:
                # Utiliser quand même si assez long
                if len(cleaned) > 200:
                    logger.info(f"📝 Contenu brut utilisé (fallback) ({len(cleaned)} chars)")
                    return cleaned
                return ""

    def _generate_fallback_summary(self, user_prompt: str) -> str:
        """Génère un résumé basique en cas d'erreur IA."""
        return """VUE D'ENSEMBLE
Le résumé IA n'a pas pu être généré automatiquement. Veuillez consulter les données détaillées du rapport pour une analyse complète.

⚠️ NOTE
Ce résumé a été généré en mode dégradé. Pour un résumé complet, vérifiez la connexion au service IA (Ollama/DeepSeek).
"""

    # ========================================================================
    # UTILITAIRES
    # ========================================================================

    def _get_maturity_level(self, score: float) -> str:
        """Détermine le niveau de maturité selon le score."""
        if score >= 90:
            return "Optimisé"
        elif score >= 75:
            return "Géré"
        elif score >= 60:
            return "Défini"
        elif score >= 40:
            return "Répétable"
        else:
            return "Initial"

    def _extract_key_findings(self, domain_analysis: List[Dict]) -> List[str]:
        """Extrait les constats clés des domaines."""
        findings = []
        for d in domain_analysis:
            if d["conformity_rate"] >= 80:
                findings.append(f"Point fort : {d['name']} ({d['conformity_rate']}%)")
            elif d["conformity_rate"] < 50:
                findings.append(f"Point d'attention : {d['name']} ({d['conformity_rate']}%)")
        return findings[:5]

    def _get_top_actions(self, critical_nc: List[Dict]) -> List[str]:
        """Génère les actions prioritaires."""
        actions = []
        domains_seen = set()
        for nc in critical_nc:
            domain = nc.get("domain", "")
            if domain and domain not in domains_seen:
                actions.append(f"Remédiation {domain}")
                domains_seen.add(domain)
            if len(actions) >= 3:
                break
        return actions

    def _generate_recommendations(self, domain_analysis: List[Dict], non_conformities: Dict) -> List[Dict]:
        """Génère des recommandations basées sur l'analyse."""
        recommendations = []

        # Recommandations par domaine faible
        for d in sorted(domain_analysis, key=lambda x: x["conformity_rate"]):
            if d["conformity_rate"] < 60:
                recommendations.append({
                    "domain": d["name"],
                    "priority": "high" if d["conformity_rate"] < 40 else "medium",
                    "action": f"Améliorer la conformité du domaine {d['name']}"
                })
            if len(recommendations) >= 5:
                break

        return recommendations
