"""
Service de génération de rapports.

Ce module contient la logique métier pour :
- Déterminer le mode de génération (DRAFT vs FINAL)
- Collecter les données de campagne/audit
- Calculer les scores et métriques
- Générer les graphiques
- Résoudre les variables dynamiques
- Convertir HTML → PDF
"""

from typing import Dict, Any, Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func, text
from datetime import datetime, timezone
import logging
import hashlib
import json

from ..models.campaign import Campaign, CampaignScope
from ..models.ecosystem import EcosystemEntity
from ..models.audit import Question, QuestionAnswer, Requirement, Domain
from ..models.report import (
    ReportTemplate,
    GeneratedReport,
    ReportGenerationJob,
    ReportChartCache
)
from ..schemas.report import GenerationMode, ReportStatus, ReportScope

logger = logging.getLogger(__name__)


class ReportService:
    """Service de génération de rapports."""

    def __init__(self, db: Session):
        self.db = db

    # ========================================================================
    # DÉTERMINATION DU MODE DE GÉNÉRATION
    # ========================================================================

    def determine_generation_mode(self, campaign_id: UUID) -> GenerationMode:
        """
        Détermine si le rapport doit être généré en mode DRAFT ou FINAL.

        Mode FINAL si :
        - Campaign.status = 'completed' ou 'frozen'
        - Toutes les questions ont un compliance_status validé

        Mode DRAFT sinon.
        """
        try:
            # Récupérer la campagne
            campaign = self.db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            ).scalar_one_or_none()

            if not campaign:
                raise ValueError(f"Campagne {campaign_id} non trouvée")

            # Vérifier le statut de la campagne
            if campaign.status not in ['completed', 'frozen']:
                logger.info(f"📊 Mode DRAFT - Campagne status={campaign.status}")
                return GenerationMode.DRAFT

            # Vérifier les réponses
            pending_count_query = text("""
                SELECT COUNT(*)
                FROM question_answer
                WHERE campaign_id = CAST(:campaign_id AS uuid)
                  AND (compliance_status IS NULL OR compliance_status = 'pending')
            """)

            pending_count = self.db.execute(
                pending_count_query,
                {"campaign_id": str(campaign_id)}
            ).scalar()

            if pending_count and pending_count > 0:
                logger.info(f"📊 Mode DRAFT - {pending_count} réponses en attente de validation")
                return GenerationMode.DRAFT

            logger.info(f"📊 Mode FINAL - Campagne terminée et toutes les réponses validées")
            return GenerationMode.FINAL

        except Exception as e:
            logger.error(f"❌ Erreur lors de la détermination du mode: {str(e)}")
            # En cas d'erreur, mode DRAFT par défaut (plus sûr)
            return GenerationMode.DRAFT

    # ========================================================================
    # COLLECTE DES DONNÉES
    # ========================================================================

    def collect_campaign_data(self, campaign_id: UUID) -> Dict[str, Any]:
        """
        Collecte toutes les données nécessaires pour générer un rapport.

        Returns:
            Dict contenant :
            - campaign: Informations de la campagne
            - stats: Statistiques globales
            - domains: Scores par domaine
            - nc_major: Liste des NC majeures
            - nc_minor: Liste des NC mineures
            - actions: Liste des actions du plan d'action
        """
        try:
            data = {}

            # 1. Informations de campagne
            campaign = self.db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            ).scalar_one_or_none()

            if not campaign:
                raise ValueError(f"Campagne {campaign_id} non trouvée")

            data['campaign'] = {
                'id': str(campaign.id),
                'name': campaign.title,
                'title': campaign.title,
                'description': campaign.description,
                'status': campaign.status,
                'start_date': campaign.launch_date.strftime('%d/%m/%Y') if campaign.launch_date else None,
                'due_date': campaign.due_date.strftime('%d/%m/%Y') if campaign.due_date else None,
                'end_date': campaign.due_date.strftime('%d/%m/%Y') if campaign.due_date else None,  # Alias pour compatibilité templates
            }

            # 1b. Récupérer les logos (tenant, organization)
            logos_data = self._get_logos_data(campaign.tenant_id)
            data['logos'] = logos_data

            # 1c. Récupérer les infos du framework/questionnaire
            framework_data = self._get_framework_data(campaign.questionnaire_id)
            data['framework'] = framework_data

            # 2. Statistiques globales
            stats = self._calculate_statistics(campaign_id)
            data['stats'] = stats

            # 3. Scores par domaine
            domains = self._calculate_domain_scores(campaign_id)
            data['domains'] = domains

            # Ajouter le nombre de domaines aux stats
            stats['total_domains'] = len(domains)

            # 4. Calculer le score global (moyenne pondérée des domaines)
            if domains:
                total_score = sum(d['score'] for d in domains)
                data['scores'] = {
                    'global': round(total_score / len(domains), 1) if domains else 0
                }
            else:
                data['scores'] = {'global': 0}

            # 4. Non-conformités
            nc_major, nc_minor = self._get_non_conformities(campaign_id)
            data['nc_major'] = nc_major
            data['nc_minor'] = nc_minor

            # 5. Actions (si plan d'action publié)
            actions = self._get_actions(campaign_id)
            data['actions'] = actions

            logger.info(f"✅ Données collectées pour campagne {campaign_id}")
            return data

        except Exception as e:
            logger.error(f"❌ Erreur lors de la collecte des données: {str(e)}", exc_info=True)
            raise

    def _get_logos_data(self, tenant_id: UUID) -> Dict[str, Any]:
        """
        Récupère les URLs des logos pour le rapport.

        Args:
            tenant_id: ID du tenant

        Returns:
            Dict avec les URLs des logos (tenant, organization)
        """
        try:
            logos = {
                'tenant_logo_url': None,
                'organization_logo_url': None,
                'tenant_name': None,
                'organization_name': None
            }

            # Récupérer le logo du tenant
            tenant_result = self.db.execute(text("""
                SELECT t.name, t.logo_url
                FROM tenant t
                WHERE t.id = CAST(:tenant_id AS uuid)
            """), {"tenant_id": str(tenant_id)}).fetchone()

            if tenant_result:
                logos['tenant_name'] = tenant_result.name
                logos['tenant_logo_url'] = tenant_result.logo_url

            # Récupérer le logo de l'organization liée au tenant
            org_result = self.db.execute(text("""
                SELECT o.name, o.logo_url
                FROM organization o
                WHERE o.tenant_id = CAST(:tenant_id AS uuid)
                LIMIT 1
            """), {"tenant_id": str(tenant_id)}).fetchone()

            if org_result:
                logos['organization_name'] = org_result.name
                logos['organization_logo_url'] = org_result.logo_url

            return logos

        except Exception as e:
            logger.error(f"❌ Erreur récupération logos: {str(e)}")
            return {
                'tenant_logo_url': None,
                'organization_logo_url': None,
                'tenant_name': None,
                'organization_name': None
            }

    def _get_entity_logo(self, entity_id: UUID) -> Dict[str, Any]:
        """
        Récupère le logo d'une entité spécifique (ecosystem_entity).

        Args:
            entity_id: ID de l'entité

        Returns:
            Dict avec le nom et URL du logo de l'entité
        """
        try:
            result = self.db.execute(text("""
                SELECT ee.name, ee.logo_url
                FROM ecosystem_entity ee
                WHERE ee.id = CAST(:entity_id AS uuid)
            """), {"entity_id": str(entity_id)}).fetchone()

            if result:
                return {
                    'entity_name': result.name,
                    'entity_logo_url': result.logo_url
                }
            return {'entity_name': None, 'entity_logo_url': None}

        except Exception as e:
            logger.error(f"❌ Erreur récupération logo entité: {str(e)}")
            return {'entity_name': None, 'entity_logo_url': None}

    def _get_framework_data(self, questionnaire_id: UUID) -> Dict[str, Any]:
        """
        Récupère les informations du framework/référentiel lié au questionnaire.

        Args:
            questionnaire_id: ID du questionnaire

        Returns:
            Dict avec les infos du framework (name, code, version)
        """
        try:
            if not questionnaire_id:
                return {'name': 'N/A', 'code': 'N/A', 'version': 'N/A'}

            result = self.db.execute(text("""
                SELECT f.name, f.code, f.version
                FROM framework f
                JOIN questionnaire q ON q.framework_id = f.id
                WHERE q.id = CAST(:questionnaire_id AS uuid)
            """), {"questionnaire_id": str(questionnaire_id)}).fetchone()

            if result:
                return {
                    'name': result.name or 'N/A',
                    'code': result.code or 'N/A',
                    'version': result.version or '1.0'
                }
            return {'name': 'N/A', 'code': 'N/A', 'version': 'N/A'}

        except Exception as e:
            logger.error(f"❌ Erreur récupération framework: {str(e)}")
            return {'name': 'N/A', 'code': 'N/A', 'version': 'N/A'}

    def _calculate_statistics(self, campaign_id: UUID) -> Dict[str, Any]:
        """Calcule les statistiques globales de la campagne."""
        try:
            # Support données legacy: dériver compliance_status depuis answer_value->>'choice' si NULL
            stats_query = text("""
                WITH answers_with_status AS (
                    SELECT
                        qa.question_id,
                        qa.answer_value,
                        COALESCE(
                            qa.compliance_status,
                            CASE LOWER(qa.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa
                    WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                      AND qa.is_current = true
                )
                SELECT
                    COUNT(*) as total_questions,
                    COUNT(CASE WHEN aws.answer_value IS NOT NULL THEN 1 END) as answered_questions,
                    COUNT(CASE WHEN aws.effective_status = 'compliant' THEN 1 END) as compliant,
                    COUNT(CASE WHEN aws.effective_status = 'non_compliant_major' THEN 1 END) as nc_major,
                    COUNT(CASE WHEN aws.effective_status = 'non_compliant_minor' THEN 1 END) as nc_minor,
                    COUNT(CASE WHEN aws.effective_status = 'not_applicable' THEN 1 END) as not_applicable
                FROM question q
                LEFT JOIN answers_with_status aws ON aws.question_id = q.id
                WHERE q.questionnaire_id = (
                    SELECT questionnaire_id FROM campaign WHERE id = CAST(:campaign_id AS uuid)
                )
            """)

            result = self.db.execute(stats_query, {"campaign_id": str(campaign_id)}).fetchone()

            total = result.total_questions or 0
            answered = result.answered_questions or 0

            return {
                'total_questions': total,
                'answered_questions': answered,
                'pending_questions': total - answered,
                'compliance_rate': round((result.compliant / total * 100) if total > 0 else 0, 1),
                'nc_major_count': result.nc_major or 0,
                'nc_minor_count': result.nc_minor or 0,
                'compliant_count': result.compliant or 0,
                'not_applicable_count': result.not_applicable or 0
            }

        except Exception as e:
            logger.error(f"❌ Erreur calcul statistiques: {str(e)}")
            return {}

    def _calculate_domain_scores(self, campaign_id: UUID) -> List[Dict[str, Any]]:
        """Calcule les scores par domaine."""
        try:
            # Support données legacy: dériver compliance_status depuis answer_value->>'choice' si NULL
            domain_scores_query = text("""
                WITH answers_with_status AS (
                    SELECT
                        qa.id,
                        qa.question_id,
                        COALESCE(
                            qa.compliance_status,
                            CASE LOWER(qa.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa
                    WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                      AND qa.is_current = true
                )
                SELECT
                    d.id,
                    COALESCE(d.title, d.code_officiel, d.code) as name,
                    d.code,
                    COUNT(aws.id) as total_answered,
                    COUNT(CASE WHEN aws.effective_status = 'compliant' THEN 1 END) as compliant,
                    COUNT(CASE WHEN aws.effective_status = 'non_compliant_minor' THEN 1 END) as nc_minor,
                    COUNT(CASE WHEN aws.effective_status = 'non_compliant_major' THEN 1 END) as nc_major,
                    CASE
                        WHEN COUNT(aws.id) > 0 THEN
                            ROUND(
                                (COUNT(CASE WHEN aws.effective_status = 'compliant' THEN 1 END) * 100.0 +
                                 COUNT(CASE WHEN aws.effective_status = 'non_compliant_minor' THEN 1 END) * 50.0) /
                                COUNT(aws.id)
                            , 1)
                        ELSE 0
                    END as score
                FROM domain d
                JOIN requirement r ON r.domain_id = d.id
                JOIN question q ON q.requirement_id = r.id
                LEFT JOIN answers_with_status aws
                    ON aws.question_id = q.id
                    AND aws.effective_status IN ('compliant', 'non_compliant_minor', 'non_compliant_major')
                WHERE q.questionnaire_id = (
                    SELECT questionnaire_id FROM campaign WHERE id = CAST(:campaign_id AS uuid)
                )
                GROUP BY d.id, d.title, d.code_officiel, d.code
                ORDER BY d.code
            """)

            results = self.db.execute(domain_scores_query, {"campaign_id": str(campaign_id)}).fetchall()

            domains = []
            for row in results:
                domains.append({
                    'id': str(row.id),
                    'name': row.name,
                    'code': row.code,
                    'score': float(row.score),
                    'total_answered': row.total_answered,
                    'compliant': row.compliant,
                    'nc_minor': row.nc_minor,
                    'nc_major': row.nc_major
                })

            return domains

        except Exception as e:
            logger.error(f"❌ Erreur calcul scores domaines: {str(e)}")
            return []

    def _get_non_conformities(self, campaign_id: UUID) -> tuple[List[Dict], List[Dict]]:
        """Récupère les non-conformités majeures et mineures."""
        try:
            # Support données legacy: dériver compliance_status depuis answer_value->>'choice' si NULL
            nc_query = text("""
                WITH answers_with_status AS (
                    SELECT
                        qa.*,
                        COALESCE(
                            qa.compliance_status,
                            CASE LOWER(qa.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa
                    WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                      AND qa.is_current = true
                )
                SELECT
                    aws.id,
                    q.question_text,
                    q.question_code as question_code,
                    COALESCE(d.title, d.code_officiel, d.code) as domain_name,
                    d.code as domain_code,
                    aws.effective_status as compliance_status,
                    aws.answer_value,
                    r.risk_level
                FROM answers_with_status aws
                JOIN question q ON aws.question_id = q.id
                JOIN requirement r ON q.requirement_id = r.id
                JOIN domain d ON r.domain_id = d.id
                WHERE aws.effective_status IN ('non_compliant_major', 'non_compliant_minor')
                ORDER BY
                    CASE aws.effective_status
                        WHEN 'non_compliant_major' THEN 1
                        WHEN 'non_compliant_minor' THEN 2
                    END,
                    d.code,
                    q.question_code
            """)

            results = self.db.execute(nc_query, {"campaign_id": str(campaign_id)}).fetchall()

            nc_major = []
            nc_minor = []

            for row in results:
                nc_item = {
                    'id': str(row.id),
                    'question_text': row.question_text,
                    'question_code': row.question_code,
                    'domain_name': row.domain_name,
                    'domain_code': row.domain_code,
                    'risk_level': row.risk_level
                }

                if row.compliance_status == 'non_compliant_major':
                    nc_major.append(nc_item)
                else:
                    nc_minor.append(nc_item)

            return nc_major, nc_minor

        except Exception as e:
            logger.error(f"❌ Erreur récupération NC: {str(e)}")
            return [], []

    def _get_actions(self, campaign_id: UUID) -> List[Dict[str, Any]]:
        """Récupère les actions du plan d'action (si publié)."""
        try:
            # Vérifier si un plan d'action publié existe
            from ..models.action_plan import ActionPlan, ActionPlanItem

            action_plan = self.db.execute(
                select(ActionPlan).where(
                    and_(
                        ActionPlan.campaign_id == campaign_id,
                        ActionPlan.status == 'PUBLISHED'
                    )
                )
            ).scalar_one_or_none()

            if not action_plan:
                return []

            # Récupérer les actions
            actions_query = select(ActionPlanItem).where(
                and_(
                    ActionPlanItem.action_plan_id == action_plan.id,
                    ActionPlanItem.included == True
                )
            ).order_by(ActionPlanItem.order_index)

            actions = self.db.execute(actions_query).scalars().all()

            return [
                {
                    'id': str(action.id),
                    'title': action.title,
                    'description': action.description,
                    'severity': action.severity,
                    'priority': action.priority,
                    'recommended_due_days': action.recommended_due_days,
                    'suggested_role': action.suggested_role
                }
                for action in actions
            ]

        except Exception as e:
            logger.error(f"❌ Erreur récupération actions: {str(e)}")
            return []

    # ========================================================================
    # RÉSOLUTION DES VARIABLES
    # ========================================================================

    def resolve_variables(self, text: str, data: Dict[str, Any]) -> str:
        """
        Résout les variables dynamiques dans un texte.

        Variables supportées :
        - %campaign.name%
        - %campaign.start_date%
        - %stats.total_questions%
        - etc.
        """
        try:
            result = text

            # Variables de campagne
            if 'campaign' in data:
                for key, value in data['campaign'].items():
                    placeholder = f"%campaign.{key}%"
                    if value is not None:
                        result = result.replace(placeholder, str(value))

            # Variables de statistiques
            if 'stats' in data:
                for key, value in data['stats'].items():
                    placeholder = f"%stats.{key}%"
                    if value is not None:
                        result = result.replace(placeholder, str(value))

            # Variables système
            result = result.replace("%report.date%", datetime.now(timezone.utc).strftime('%d/%m/%Y'))
            result = result.replace("%report.time%", datetime.now(timezone.utc).strftime('%H:%M'))
            result = result.replace("%current_date%", datetime.now(timezone.utc).strftime('%d/%m/%Y'))

            return result

        except Exception as e:
            logger.error(f"❌ Erreur résolution variables: {str(e)}")
            return text

    # ========================================================================
    # GESTION DU CACHE DES GRAPHIQUES
    # ========================================================================

    def get_cached_chart(
        self,
        campaign_id: UUID,
        chart_type: str,
        chart_key: str,
        chart_data: Dict[str, Any]
    ) -> Optional[bytes]:
        """
        Récupère un graphique depuis le cache.

        Vérifie que :
        - Le cache existe
        - Le hash des données correspond
        - Le cache n'a pas expiré
        """
        try:
            # Calculer le hash des données
            data_hash = hashlib.sha256(
                json.dumps(chart_data, sort_keys=True).encode()
            ).hexdigest()

            # Chercher dans le cache
            cache_entry = self.db.execute(
                select(ReportChartCache).where(
                    and_(
                        ReportChartCache.campaign_id == campaign_id,
                        ReportChartCache.chart_key == chart_key,
                        ReportChartCache.data_hash == data_hash,
                        (ReportChartCache.expires_at.is_(None) |
                         (ReportChartCache.expires_at > datetime.now(timezone.utc)))
                    )
                )
            ).scalar_one_or_none()

            if cache_entry:
                logger.info(f"✅ Cache hit pour graphique {chart_key}")
                return cache_entry.image_data

            logger.info(f"⚠️ Cache miss pour graphique {chart_key}")
            return None

        except Exception as e:
            logger.error(f"❌ Erreur lecture cache: {str(e)}")
            return None

    def cache_chart(
        self,
        campaign_id: UUID,
        chart_type: str,
        chart_key: str,
        chart_data: Dict[str, Any],
        image_data: bytes,
        image_width: int,
        image_height: int,
        expires_hours: int = 24
    ):
        """Stocke un graphique dans le cache."""
        try:
            # Calculer le hash et l'expiration
            data_hash = hashlib.sha256(
                json.dumps(chart_data, sort_keys=True).encode()
            ).hexdigest()

            from datetime import timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)

            # Vérifier si une entrée existe déjà
            existing = self.db.execute(
                select(ReportChartCache).where(
                    and_(
                        ReportChartCache.campaign_id == campaign_id,
                        ReportChartCache.chart_key == chart_key
                    )
                )
            ).scalar_one_or_none()

            if existing:
                # Mettre à jour
                existing.chart_data = chart_data
                existing.image_data = image_data
                existing.image_width = image_width
                existing.image_height = image_height
                existing.data_hash = data_hash
                existing.generated_at = datetime.now(timezone.utc)
                existing.expires_at = expires_at
            else:
                # Créer nouveau
                cache_entry = ReportChartCache(
                    campaign_id=campaign_id,
                    chart_type=chart_type,
                    chart_key=chart_key,
                    chart_data=chart_data,
                    chart_config={},
                    image_data=image_data,
                    image_format='png',
                    image_width=image_width,
                    image_height=image_height,
                    data_hash=data_hash,
                    expires_at=expires_at
                )
                self.db.add(cache_entry)

            self.db.commit()
            logger.info(f"✅ Graphique {chart_key} mis en cache")

        except Exception as e:
            logger.error(f"❌ Erreur écriture cache: {str(e)}")
            self.db.rollback()

    # ========================================================================
    # RAPPORTS CONSOLIDÉS (Multi-Organismes / Vue Écosystème)
    # ========================================================================

    def collect_consolidated_data(self, campaign_id: UUID) -> Dict[str, Any]:
        """
        Collecte les données pour un rapport CONSOLIDÉ (multi-organismes).

        Contenu spécifique :
        - Stats comparatives entre organismes
        - NC critiques globales
        - Plan d'action consolidé
        - Benchmarking sectoriel
        - Analyse par entité avec scores

        Returns:
            Dict contenant les données de toutes les entités de la campagne.
        """
        try:
            logger.info(f"📊 Collecte données consolidées pour campagne {campaign_id}")

            data = {
                'report_type': 'consolidated',
                'campaign': None,
                'entities': [],
                'global_stats': {},
                'domain_comparison': [],
                'nc_critical_all': [],
                'entity_scores': [],
                'consolidated_actions': []
            }

            # 1. Informations de campagne
            campaign = self.db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            ).scalar_one_or_none()

            if not campaign:
                raise ValueError(f"Campagne {campaign_id} non trouvée")

            data['campaign'] = {
                'id': str(campaign.id),
                'name': campaign.title,
                'title': campaign.title,
                'description': campaign.description,
                'status': campaign.status,
                'start_date': campaign.launch_date.strftime('%d/%m/%Y') if campaign.launch_date else None,
                'due_date': campaign.due_date.strftime('%d/%m/%Y') if campaign.due_date else None,
            }

            # 2. Récupérer les entités de la campagne via le scope_id de la campagne
            campaign_scope = None
            if campaign.scope_id:
                campaign_scope = self.db.execute(
                    select(CampaignScope).where(CampaignScope.id == campaign.scope_id)
                ).scalar_one_or_none()

            if not campaign_scope or not campaign_scope.entity_ids:
                logger.warning(f"Aucune entité trouvée pour la campagne {campaign_id}")
                return data

            entity_ids = campaign_scope.entity_ids

            # 3. Récupérer les informations de chaque entité
            entities_data = []
            for entity_id in entity_ids:
                entity = self.db.execute(
                    select(EcosystemEntity).where(EcosystemEntity.id == entity_id)
                ).scalar_one_or_none()

                if entity:
                    entity_data = {
                        'id': str(entity.id),
                        'name': entity.name,
                        'code': entity.short_code,
                        'entity_type': entity.stakeholder_type,
                        'stats': self._calculate_entity_statistics(campaign_id, entity.id),
                        'domain_scores': self._calculate_entity_domain_scores(campaign_id, entity.id),
                        'risk_level': 'low'  # Calculé plus bas
                    }

                    # Calculer le niveau de risque
                    score = entity_data['stats'].get('compliance_rate', 0)
                    if score < 50:
                        entity_data['risk_level'] = 'high'
                    elif score < 70:
                        entity_data['risk_level'] = 'medium'
                    else:
                        entity_data['risk_level'] = 'low'

                    entities_data.append(entity_data)

            data['entities'] = entities_data

            # 4. Statistiques globales écosystème
            data['global_stats'] = self._calculate_global_statistics(campaign_id, entity_ids)

            # 5. Comparaison par domaine (radar multi-entités)
            data['domain_comparison'] = self._calculate_domain_comparison(campaign_id, entity_ids)

            # 6. Top NC critiques de tout l'écosystème
            data['nc_critical_all'] = self._get_top_critical_nc(campaign_id, entity_ids, limit=10)

            # 7. Classement des entités par score
            data['entity_scores'] = sorted(
                [{'id': e['id'], 'name': e['name'], 'score': e['stats'].get('compliance_rate', 0),
                  'nc_count': e['stats'].get('nc_major_count', 0) + e['stats'].get('nc_minor_count', 0),
                  'risk_level': e['risk_level']}
                 for e in entities_data],
                key=lambda x: x['score'],
                reverse=True
            )

            # 8. Actions consolidées (actions transverses)
            data['consolidated_actions'] = self._get_consolidated_actions(campaign_id, entity_ids)

            logger.info(f"✅ Données consolidées collectées: {len(entities_data)} entités")
            return data

        except Exception as e:
            logger.error(f"❌ Erreur collecte données consolidées: {str(e)}", exc_info=True)
            raise

    def _calculate_entity_statistics(self, campaign_id: UUID, entity_id: UUID) -> Dict[str, Any]:
        """Calcule les statistiques pour une entité spécifique."""
        try:
            # Note: question_answer n'a pas entity_id, on passe par audit.entity_id (FK vers ecosystem_entity)
            # Support données legacy: dériver compliance_status depuis answer_value->>'choice' si NULL
            stats_query = text("""
                WITH answers_with_status AS (
                    SELECT
                        qa.question_id,
                        qa.answer_value,
                        COALESCE(
                            qa.compliance_status,
                            CASE LOWER(qa.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa
                    JOIN audit a ON qa.audit_id = a.id
                    WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                      AND qa.is_current = true
                      AND a.entity_id = CAST(:entity_id AS uuid)
                )
                SELECT
                    COUNT(*) as total_questions,
                    COUNT(CASE WHEN aws.answer_value IS NOT NULL THEN 1 END) as answered_questions,
                    COUNT(CASE WHEN aws.effective_status = 'compliant' THEN 1 END) as compliant,
                    COUNT(CASE WHEN aws.effective_status = 'non_compliant_major' THEN 1 END) as nc_major,
                    COUNT(CASE WHEN aws.effective_status = 'non_compliant_minor' THEN 1 END) as nc_minor,
                    COUNT(CASE WHEN aws.effective_status = 'not_applicable' THEN 1 END) as not_applicable
                FROM question q
                LEFT JOIN answers_with_status aws ON aws.question_id = q.id
                WHERE q.questionnaire_id = (
                    SELECT questionnaire_id FROM campaign WHERE id = CAST(:campaign_id AS uuid)
                )
            """)

            result = self.db.execute(stats_query, {
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id)
            }).fetchone()

            total = result.total_questions or 0
            answered = result.answered_questions or 0
            compliant = result.compliant or 0

            # Calcul du taux de conformité
            applicable = total - (result.not_applicable or 0)
            compliance_rate = round((compliant / applicable * 100) if applicable > 0 else 0, 1)

            return {
                'total_questions': total,
                'answered_questions': answered,
                'compliance_rate': compliance_rate,
                'nc_major_count': result.nc_major or 0,
                'nc_minor_count': result.nc_minor or 0,
                'compliant_count': compliant,
                'not_applicable_count': result.not_applicable or 0
            }

        except Exception as e:
            logger.error(f"❌ Erreur calcul stats entité {entity_id}: {str(e)}")
            return {}

    def _calculate_entity_domain_scores(self, campaign_id: UUID, entity_id: UUID) -> List[Dict[str, Any]]:
        """Calcule les scores par domaine pour une entité."""
        try:
            # Note: question_answer n'a pas entity_id, on passe par audit.entity_id (FK vers ecosystem_entity)
            # On récupère TOUS les domaines du questionnaire, même sans réponses
            # On déduit compliance_status depuis answer_value->>'choice' si NULL (données legacy)
            domain_scores_query = text("""
                SELECT
                    d.id,
                    COALESCE(d.title, d.code_officiel, d.code) as name,
                    d.code,
                    COUNT(qa.id) as total_answered,
                    COUNT(CASE WHEN qa.effective_status = 'compliant' THEN 1 END) as compliant,
                    CASE
                        WHEN COUNT(qa.id) > 0 THEN
                            ROUND(
                                (COUNT(CASE WHEN qa.effective_status = 'compliant' THEN 1 END) * 100.0 +
                                 COUNT(CASE WHEN qa.effective_status = 'non_compliant_minor' THEN 1 END) * 50.0) /
                                COUNT(qa.id)
                            , 1)
                        ELSE 0
                    END as score
                FROM domain d
                JOIN requirement r ON r.domain_id = d.id
                JOIN question q ON q.requirement_id = r.id
                LEFT JOIN (
                    SELECT
                        qa_inner.*,
                        COALESCE(
                            qa_inner.compliance_status,
                            CASE LOWER(qa_inner.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa_inner
                    JOIN audit a ON qa_inner.audit_id = a.id
                    WHERE qa_inner.campaign_id = CAST(:campaign_id AS uuid)
                      AND qa_inner.is_current = true
                      AND a.entity_id = CAST(:entity_id AS uuid)
                ) qa ON qa.question_id = q.id
                    AND qa.effective_status IN ('compliant', 'non_compliant_minor', 'non_compliant_major')
                WHERE q.questionnaire_id = (
                    SELECT questionnaire_id FROM campaign WHERE id = CAST(:campaign_id AS uuid)
                )
                GROUP BY d.id, d.title, d.code_officiel, d.code
                ORDER BY d.code
            """)

            results = self.db.execute(domain_scores_query, {
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id)
            }).fetchall()

            return [
                {
                    'id': str(row.id),
                    'name': row.name,
                    'code': row.code,
                    'score': float(row.score)
                }
                for row in results
            ]

        except Exception as e:
            logger.error(f"❌ Erreur calcul domaines entité {entity_id}: {str(e)}")
            return []

    def _calculate_global_statistics(self, campaign_id: UUID, entity_ids: List[UUID]) -> Dict[str, Any]:
        """Calcule les statistiques globales pour toutes les entités."""
        try:
            entity_ids_str = [str(eid) for eid in entity_ids]

            # Note: question_answer n'a pas entity_id, on passe par audit.entity_id (FK vers ecosystem_entity)
            # Support données legacy: dériver compliance_status depuis answer_value->>'choice' si NULL
            global_stats_query = text("""
                WITH answers_with_status AS (
                    SELECT
                        qa.audit_id,
                        COALESCE(
                            qa.compliance_status,
                            CASE LOWER(qa.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa
                    WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                      AND qa.is_current = true
                )
                SELECT
                    COUNT(DISTINCT a.entity_id) as entities_audited,
                    COUNT(*) as total_answers,
                    COUNT(CASE WHEN aws.effective_status = 'compliant' THEN 1 END) as compliant,
                    COUNT(CASE WHEN aws.effective_status = 'non_compliant_major' THEN 1 END) as nc_major,
                    COUNT(CASE WHEN aws.effective_status = 'non_compliant_minor' THEN 1 END) as nc_minor,
                    AVG(CASE
                        WHEN aws.effective_status = 'compliant' THEN 100
                        WHEN aws.effective_status = 'non_compliant_minor' THEN 50
                        WHEN aws.effective_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END) as avg_compliance_rate
                FROM answers_with_status aws
                JOIN audit a ON aws.audit_id = a.id
                WHERE a.entity_id = ANY(CAST(:entity_ids AS uuid[]))
            """)

            result = self.db.execute(global_stats_query, {
                "campaign_id": str(campaign_id),
                "entity_ids": entity_ids_str
            }).fetchone()

            return {
                'total_entities': len(entity_ids),
                'entities_audited': result.entities_audited or 0,
                'total_evaluations': result.total_answers or 0,
                'total_nc': (result.nc_major or 0) + (result.nc_minor or 0),
                'nc_critical': result.nc_major or 0,
                'nc_minor': result.nc_minor or 0,
                'avg_compliance_rate': round(result.avg_compliance_rate or 0, 1),
                'entities_at_risk': sum(1 for eid in entity_ids if self._is_entity_at_risk(campaign_id, eid))
            }

        except Exception as e:
            logger.error(f"❌ Erreur calcul stats globales: {str(e)}")
            return {}

    def _is_entity_at_risk(self, campaign_id: UUID, entity_id: UUID) -> bool:
        """Vérifie si une entité est à risque (score < 70%)."""
        stats = self._calculate_entity_statistics(campaign_id, entity_id)
        return stats.get('compliance_rate', 0) < 70

    def _calculate_domain_comparison(self, campaign_id: UUID, entity_ids: List[UUID]) -> List[Dict[str, Any]]:
        """Calcule la comparaison des scores par domaine pour toutes les entités."""
        try:
            entity_ids_str = [str(eid) for eid in entity_ids]

            # Note: question_answer n'a pas entity_id, on passe par audit.entity_id (FK vers ecosystem_entity)
            # Support données legacy: dériver compliance_status depuis answer_value->>'choice' si NULL
            comparison_query = text("""
                WITH answers_with_status AS (
                    SELECT
                        qa.question_id,
                        qa.audit_id,
                        COALESCE(
                            qa.compliance_status,
                            CASE LOWER(qa.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa
                    WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                      AND qa.is_current = true
                )
                SELECT
                    d.id as domain_id,
                    COALESCE(d.title, d.code_officiel, d.code) as domain_name,
                    d.code as domain_code,
                    ee.id as entity_id,
                    ee.name as entity_name,
                    AVG(CASE
                        WHEN aws.effective_status = 'compliant' THEN 100
                        WHEN aws.effective_status = 'non_compliant_minor' THEN 50
                        WHEN aws.effective_status = 'non_compliant_major' THEN 0
                        ELSE NULL
                    END) as score
                FROM domain d
                JOIN requirement r ON r.domain_id = d.id
                JOIN question q ON q.requirement_id = r.id
                JOIN answers_with_status aws ON aws.question_id = q.id
                JOIN audit a ON aws.audit_id = a.id
                JOIN ecosystem_entity ee ON ee.id = a.entity_id
                WHERE a.entity_id = ANY(CAST(:entity_ids AS uuid[]))
                  AND aws.effective_status IN ('compliant', 'non_compliant_minor', 'non_compliant_major')
                GROUP BY d.id, d.title, d.code_officiel, d.code, ee.id, ee.name
                ORDER BY d.code, ee.name
            """)

            results = self.db.execute(comparison_query, {
                "campaign_id": str(campaign_id),
                "entity_ids": entity_ids_str
            }).fetchall()

            # Restructurer les données pour le graphique radar
            domains = {}
            for row in results:
                domain_code = row.domain_code
                if domain_code not in domains:
                    domains[domain_code] = {
                        'domain_id': str(row.domain_id),
                        'domain_name': row.domain_name,
                        'domain_code': domain_code,
                        'scores_by_entity': {}
                    }
                domains[domain_code]['scores_by_entity'][row.entity_name] = round(row.score or 0, 1)

            return list(domains.values())

        except Exception as e:
            logger.error(f"❌ Erreur comparaison domaines: {str(e)}")
            return []

    def _get_top_critical_nc(self, campaign_id: UUID, entity_ids: List[UUID], limit: int = 10) -> List[Dict[str, Any]]:
        """Récupère les top NC critiques de tout l'écosystème."""
        try:
            entity_ids_str = [str(eid) for eid in entity_ids]

            # Note: question_answer n'a pas entity_id, on passe par audit.entity_id (FK vers ecosystem_entity)
            # Support données legacy: dériver compliance_status depuis answer_value->>'choice' si NULL
            nc_query = text("""
                WITH answers_with_status AS (
                    SELECT
                        qa.question_id,
                        qa.audit_id,
                        COALESCE(
                            qa.compliance_status,
                            CASE LOWER(qa.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa
                    WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                      AND qa.is_current = true
                )
                SELECT
                    q.id as question_id,
                    q.question_text,
                    q.question_code as question_code,
                    COALESCE(d.title, d.code_officiel, d.code) as domain_name,
                    d.code as domain_code,
                    COUNT(DISTINCT a.entity_id) as entity_count,
                    STRING_AGG(DISTINCT ee.name, ', ') as affected_entities
                FROM question q
                JOIN requirement r ON q.requirement_id = r.id
                JOIN domain d ON r.domain_id = d.id
                JOIN answers_with_status aws ON aws.question_id = q.id
                JOIN audit a ON aws.audit_id = a.id
                JOIN ecosystem_entity ee ON ee.id = a.entity_id
                WHERE aws.effective_status = 'non_compliant_major'
                  AND a.entity_id = ANY(CAST(:entity_ids AS uuid[]))
                GROUP BY q.id, q.question_text, q.question_code, d.title, d.code_officiel, d.code
                ORDER BY entity_count DESC, d.code
                LIMIT :limit
            """)

            results = self.db.execute(nc_query, {
                "campaign_id": str(campaign_id),
                "entity_ids": entity_ids_str,
                "limit": limit
            }).fetchall()

            return [
                {
                    'question_id': str(row.question_id),
                    'question_text': row.question_text,
                    'question_code': row.question_code,
                    'domain_name': row.domain_name,
                    'domain_code': row.domain_code,
                    'entity_count': row.entity_count,
                    'affected_entities': row.affected_entities
                }
                for row in results
            ]

        except Exception as e:
            logger.error(f"❌ Erreur récupération NC critiques: {str(e)}")
            return []

    def _get_consolidated_actions(self, campaign_id: UUID, entity_ids: List[UUID]) -> List[Dict[str, Any]]:
        """Récupère les actions consolidées (transverses)."""
        try:
            from ..models.action_plan import ActionPlan, ActionPlanItem

            # Récupérer les plans d'action publiés pour les entités
            action_plans = self.db.execute(
                select(ActionPlan).where(
                    and_(
                        ActionPlan.campaign_id == campaign_id,
                        ActionPlan.status == 'PUBLISHED'
                    )
                )
            ).scalars().all()

            if not action_plans:
                return []

            # Agréger les actions par similarité
            actions_map = {}
            for plan in action_plans:
                actions = self.db.execute(
                    select(ActionPlanItem).where(
                        and_(
                            ActionPlanItem.action_plan_id == plan.id,
                            ActionPlanItem.included == True
                        )
                    )
                ).scalars().all()

                for action in actions:
                    key = action.title.lower().strip()
                    if key not in actions_map:
                        actions_map[key] = {
                            'title': action.title,
                            'description': action.description,
                            'severity': action.severity,
                            'priority': action.priority,
                            'entity_count': 0,
                            'entities': []
                        }
                    actions_map[key]['entity_count'] += 1
                    # Note: entity_id est sur ActionPlanItem, pas sur ActionPlan
                    if action.entity_id:
                        actions_map[key]['entities'].append(str(action.entity_id))

            # Trier par nombre d'entités concernées
            consolidated = sorted(
                actions_map.values(),
                key=lambda x: (-x['entity_count'], x.get('severity', 'LOW') == 'HIGH')
            )

            return consolidated[:20]  # Top 20 actions transverses

        except Exception as e:
            logger.error(f"❌ Erreur récupération actions consolidées: {str(e)}")
            return []

    # ========================================================================
    # RAPPORTS INDIVIDUELS (Mono-Organisme)
    # ========================================================================

    def collect_entity_data(self, campaign_id: UUID, entity_id: UUID) -> Dict[str, Any]:
        """
        Collecte les données pour un rapport INDIVIDUEL (mono-organisme).

        Contenu spécifique :
        - Score personnalisé de l'entité
        - Analyse par domaine
        - Plan d'action dédié
        - Comparaison vs pairs (benchmarking)
        - Points forts et axes d'amélioration

        Args:
            campaign_id: UUID de la campagne
            entity_id: UUID de l'entité

        Returns:
            Dict contenant les données spécifiques à l'entité.
        """
        try:
            logger.info(f"📊 Collecte données individuelles pour entité {entity_id}")

            data = {
                'report_type': 'entity',
                'campaign': None,
                'entity': None,
                'stats': {},
                'domain_scores': [],
                'nc_list': [],
                'strengths': [],
                'improvements': [],
                'actions': [],
                'benchmarking': {}
            }

            # 1. Informations de campagne
            campaign = self.db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            ).scalar_one_or_none()

            if not campaign:
                raise ValueError(f"Campagne {campaign_id} non trouvée")

            data['campaign'] = {
                'id': str(campaign.id),
                'name': campaign.title,
                'title': campaign.title,
                'description': campaign.description,
                'status': campaign.status,
                'start_date': campaign.launch_date.strftime('%d/%m/%Y') if campaign.launch_date else None,
                'due_date': campaign.due_date.strftime('%d/%m/%Y') if campaign.due_date else None,
            }

            # 2. Informations de l'entité
            entity = self.db.execute(
                select(EcosystemEntity).where(EcosystemEntity.id == entity_id)
            ).scalar_one_or_none()

            if not entity:
                raise ValueError(f"Entité {entity_id} non trouvée")

            data['entity'] = {
                'id': str(entity.id),
                'name': entity.name,
                'code': entity.short_code,
                'entity_type': entity.stakeholder_type,
                'description': entity.description,
                'logo_url': entity.logo_url if hasattr(entity, 'logo_url') else None
            }

            # 2b. Récupérer les logos (tenant, organization, entité)
            logos_data = self._get_logos_data(campaign.tenant_id)
            entity_logo = self._get_entity_logo(entity_id)
            logos_data.update(entity_logo)
            data['logos'] = logos_data

            # 3. Statistiques de l'entité
            data['stats'] = self._calculate_entity_statistics(campaign_id, entity_id)

            # Ajouter le niveau de maturité
            score = data['stats'].get('compliance_rate', 0)
            if score >= 90:
                data['stats']['maturity_level'] = 'Avancé'
            elif score >= 70:
                data['stats']['maturity_level'] = 'Intermédiaire'
            elif score >= 50:
                data['stats']['maturity_level'] = 'En développement'
            else:
                data['stats']['maturity_level'] = 'Initial'

            # 4. Scores par domaine
            data['domain_scores'] = self._calculate_entity_domain_scores(campaign_id, entity_id)

            # Ajouter les indicateurs de status par domaine
            for domain in data['domain_scores']:
                score = domain.get('score', 0)
                if score >= 80:
                    domain['status'] = 'compliant'
                    domain['status_icon'] = '✅'
                elif score >= 50:
                    domain['status'] = 'partial'
                    domain['status_icon'] = '⚠️'
                else:
                    domain['status'] = 'non_compliant'
                    domain['status_icon'] = '🔴'

            # 5. Liste des NC
            data['nc_list'] = self._get_entity_non_conformities(campaign_id, entity_id)

            # 6. Points forts (domaines >= 80%)
            data['strengths'] = [
                {'domain': d['name'], 'score': d['score']}
                for d in data['domain_scores']
                if d['score'] >= 80
            ]

            # 7. Axes d'amélioration (domaines < 70%)
            data['improvements'] = [
                {'domain': d['name'], 'score': d['score'], 'gap': 70 - d['score']}
                for d in data['domain_scores']
                if d['score'] < 70
            ]

            # 8. Actions dédiées
            data['actions'] = self._get_entity_actions(campaign_id, entity_id)

            # 9. Benchmarking vs pairs
            data['benchmarking'] = self._calculate_entity_benchmarking(campaign_id, entity_id)

            logger.info(f"✅ Données individuelles collectées pour {entity.name}")
            return data

        except Exception as e:
            logger.error(f"❌ Erreur collecte données individuelles: {str(e)}", exc_info=True)
            raise

    def _get_entity_non_conformities(self, campaign_id: UUID, entity_id: UUID) -> List[Dict[str, Any]]:
        """Récupère les NC pour une entité spécifique."""
        try:
            # Note: question_answer n'a pas entity_id, on passe par audit.entity_id (FK vers ecosystem_entity)
            # Support données legacy: dériver compliance_status depuis answer_value->>'choice' si NULL
            nc_query = text("""
                WITH answers_with_status AS (
                    SELECT
                        qa.*,
                        COALESCE(
                            qa.compliance_status,
                            CASE LOWER(qa.answer_value->>'choice')
                                WHEN 'oui' THEN 'compliant'
                                WHEN 'non' THEN 'non_compliant_major'
                                WHEN 'partiellement' THEN 'non_compliant_minor'
                                WHEN 'partiel' THEN 'non_compliant_minor'
                                WHEN 'na' THEN 'not_applicable'
                                WHEN 'n/a' THEN 'not_applicable'
                                WHEN 'non applicable' THEN 'not_applicable'
                                ELSE NULL
                            END
                        ) as effective_status
                    FROM question_answer qa
                    JOIN audit a ON qa.audit_id = a.id
                    WHERE qa.campaign_id = CAST(:campaign_id AS uuid)
                      AND a.entity_id = CAST(:entity_id AS uuid)
                      AND qa.is_current = true
                )
                SELECT
                    aws.id,
                    q.question_text,
                    q.question_code as question_code,
                    COALESCE(d.title, d.code_officiel, d.code) as domain_name,
                    d.code as domain_code,
                    aws.effective_status as compliance_status,
                    aws.answer_value,
                    aws.comment
                FROM answers_with_status aws
                JOIN question q ON aws.question_id = q.id
                JOIN requirement r ON q.requirement_id = r.id
                JOIN domain d ON r.domain_id = d.id
                WHERE aws.effective_status IN ('non_compliant_major', 'non_compliant_minor')
                ORDER BY
                    CASE aws.effective_status
                        WHEN 'non_compliant_major' THEN 1
                        WHEN 'non_compliant_minor' THEN 2
                    END,
                    d.code,
                    q.question_code
            """)

            results = self.db.execute(nc_query, {
                "campaign_id": str(campaign_id),
                "entity_id": str(entity_id)
            }).fetchall()

            nc_list = []
            for row in results:
                nc_list.append({
                    'id': str(row.id),
                    'question_text': row.question_text,
                    'question_code': row.question_code,
                    'domain_name': row.domain_name,
                    'domain_code': row.domain_code,
                    'severity': 'CRITIQUE' if row.compliance_status == 'non_compliant_major' else 'MINEURE',
                    'severity_class': 'critical' if row.compliance_status == 'non_compliant_major' else 'minor',
                    'comment': row.comment
                })

            return nc_list

        except Exception as e:
            logger.error(f"❌ Erreur récupération NC entité: {str(e)}")
            return []

    def _get_entity_actions(self, campaign_id: UUID, entity_id: UUID) -> List[Dict[str, Any]]:
        """Récupère les actions du plan d'action pour une entité."""
        try:
            from ..models.action_plan import ActionPlan, ActionPlanItem
            from sqlalchemy import or_

            # Note: ActionPlan n'a pas entity_id, c'est ActionPlanItem qui l'a
            # Chercher le plan d'action publié de la campagne
            action_plan = self.db.execute(
                select(ActionPlan).where(
                    and_(
                        ActionPlan.campaign_id == campaign_id,
                        ActionPlan.status == 'PUBLISHED'
                    )
                )
            ).scalar_one_or_none()

            if not action_plan:
                return []

            # Récupérer les actions pour cette entité spécifique
            # ActionPlanItem.entity_id peut être NULL (action globale) ou correspondre à l'entité
            actions = self.db.execute(
                select(ActionPlanItem).where(
                    and_(
                        ActionPlanItem.action_plan_id == action_plan.id,
                        ActionPlanItem.included == True,
                        or_(
                            ActionPlanItem.entity_id == entity_id,
                            ActionPlanItem.entity_id.is_(None)  # Actions globales
                        )
                    )
                ).order_by(ActionPlanItem.order_index)
            ).scalars().all()

            return [
                {
                    'id': str(action.id),
                    'title': action.title,
                    'description': action.description,
                    'severity': action.severity,
                    'priority': action.priority,
                    'priority_label': self._get_priority_label(action.priority),
                    'recommended_due_days': action.recommended_due_days,
                    'suggested_role': action.suggested_role,
                    'estimated_effort': self._estimate_effort(action.recommended_due_days)
                }
                for action in actions
            ]

        except Exception as e:
            logger.error(f"❌ Erreur récupération actions entité: {str(e)}")
            return []

    def _get_priority_label(self, priority: str) -> str:
        """Retourne le label de priorité."""
        labels = {
            'CRITICAL': 'Priorité Critique',
            'HIGH': 'Priorité Haute',
            'MEDIUM': 'Priorité Moyenne',
            'LOW': 'Priorité Basse'
        }
        return labels.get(priority, priority)

    def _estimate_effort(self, days: int) -> str:
        """Estime l'effort en fonction des jours."""
        if not days:
            return 'Non défini'
        if days <= 5:
            return 'Court (< 1 semaine)'
        elif days <= 20:
            return 'Moyen (1-4 semaines)'
        else:
            return 'Long (> 1 mois)'

    def _calculate_entity_benchmarking(self, campaign_id: UUID, entity_id: UUID) -> Dict[str, Any]:
        """Calcule le benchmarking de l'entité vs les pairs de la campagne."""
        try:
            # Récupérer le score de l'entité
            entity_stats = self._calculate_entity_statistics(campaign_id, entity_id)
            entity_score = entity_stats.get('compliance_rate', 0)

            # Récupérer toutes les entités de la campagne via le scope de la campagne
            campaign = self.db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            ).scalar_one_or_none()

            campaign_scope = None
            if campaign and campaign.scope_id:
                campaign_scope = self.db.execute(
                    select(CampaignScope).where(CampaignScope.id == campaign.scope_id)
                ).scalar_one_or_none()

            if not campaign_scope or not campaign_scope.entity_ids:
                return {
                    'entity_score': entity_score,
                    'campaign_avg': entity_score,
                    'rank': 1,
                    'total_entities': 1,
                    'percentile': 100
                }

            # Calculer les scores de toutes les entités
            all_scores = []
            for eid in campaign_scope.entity_ids:
                stats = self._calculate_entity_statistics(campaign_id, eid)
                all_scores.append({
                    'entity_id': str(eid),
                    'score': stats.get('compliance_rate', 0)
                })

            # Trier par score
            all_scores.sort(key=lambda x: x['score'], reverse=True)

            # Trouver le rang de l'entité
            rank = next(
                (i + 1 for i, s in enumerate(all_scores) if s['entity_id'] == str(entity_id)),
                len(all_scores)
            )

            # Calculer les statistiques
            scores_only = [s['score'] for s in all_scores]
            campaign_avg = sum(scores_only) / len(scores_only) if scores_only else 0

            return {
                'entity_score': entity_score,
                'campaign_avg': round(campaign_avg, 1),
                'campaign_max': max(scores_only) if scores_only else 0,
                'campaign_min': min(scores_only) if scores_only else 0,
                'rank': rank,
                'total_entities': len(all_scores),
                'percentile': round((len(all_scores) - rank + 1) / len(all_scores) * 100, 0),
                'difference_vs_avg': round(entity_score - campaign_avg, 1)
            }

        except Exception as e:
            logger.error(f"❌ Erreur calcul benchmarking: {str(e)}")
            return {}

    # ========================================================================
    # COLLECTE DES DONNÉES SCANNER
    # ========================================================================

    def collect_scanner_data(self, scan_id: UUID) -> Dict[str, Any]:
        """
        Collecte toutes les données nécessaires pour générer un rapport de scan individuel.

        Args:
            scan_id: ID du scan

        Returns:
            Dict contenant :
            - scan: Informations du scan
            - target: Informations de la cible
            - entity: Informations de l'entité liée
            - summary: Résumé (scores, compteurs)
            - vulnerabilities: Liste des vulnérabilités par sévérité
            - services: Liste des services détectés
            - tls: Analyse TLS détaillée
            - positioning_chart: Données pour le graphique de positionnement
        """
        try:
            data = {}

            # 1. Récupérer le scan
            scan_query = text("""
                SELECT
                    es.id,
                    es.code_scan,
                    es.tenant_id,
                    es.external_target_id,
                    es.entity_id,
                    es.status,
                    es.started_at,
                    es.finished_at,
                    es.summary,
                    es.scan_data,
                    es.created_at,
                    et.value as target_value,
                    et.label as target_label,
                    et.type as target_type,
                    et.description as target_description,
                    ee.id as entity_id,
                    ee.name as entity_name,
                    ee.logo_url as entity_logo_url
                FROM external_scan es
                JOIN external_target et ON es.external_target_id = et.id
                LEFT JOIN ecosystem_entity ee ON es.entity_id = ee.id
                WHERE es.id = CAST(:scan_id AS uuid)
            """)

            result = self.db.execute(scan_query, {"scan_id": str(scan_id)}).fetchone()

            if not result:
                raise ValueError(f"Scan {scan_id} non trouvé")

            # Informations du scan
            # IMPORTANT: Ajouter 'target' pour supporter la variable %scan.target% dans les templates
            data['scan'] = {
                'id': str(result.id),
                'code': result.code_scan,
                'status': result.status,
                'started_at': result.started_at.strftime('%d/%m/%Y %H:%M') if result.started_at else None,
                'finished_at': result.finished_at.strftime('%d/%m/%Y %H:%M') if result.finished_at else None,
                'created_at': result.created_at.strftime('%d/%m/%Y %H:%M') if result.created_at else None,
                # Alias pour %scan.target% dans les templates (cover page, etc.)
                'target': result.target_value,
                'target_value': result.target_value,
                'target_type': result.target_type,
                'entity_id': str(result.entity_id) if result.entity_id else None,
                'entity_name': result.entity_name,
            }

            # Informations de la cible
            data['target'] = {
                'id': str(result.external_target_id),
                'value': result.target_value,
                'label': result.target_label or result.target_value,
                'type': result.target_type,
                'description': result.target_description
            }

            # Informations de l'entité
            data['entity'] = {
                'id': str(result.entity_id) if result.entity_id else None,
                'name': result.entity_name or 'Non associé',
                'logo_url': result.entity_logo_url
            }

            # Logos (tenant)
            data['logos'] = self._get_logos_data(result.tenant_id)

            # 2. Résumé (depuis le champ JSON summary)
            summary = result.summary or {}
            data['summary'] = {
                'exposure_score': summary.get('exposure_score', 0),
                'tls_grade': summary.get('tls_grade', 'N/A'),
                'services_exposed': summary.get('nb_services_exposed', 0),
                'vuln_critical': summary.get('nb_vuln_critical', 0),
                'vuln_high': summary.get('nb_vuln_high', 0),
                'vuln_medium': summary.get('nb_vuln_medium', 0),
                'vuln_low': summary.get('nb_vuln_low', 0),
                'vuln_info': summary.get('nb_vuln_info', 0),
                'total_vulnerabilities': (
                    summary.get('nb_vuln_critical', 0) +
                    summary.get('nb_vuln_high', 0) +
                    summary.get('nb_vuln_medium', 0) +
                    summary.get('nb_vuln_low', 0)
                ),
                'scan_duration_seconds': summary.get('scan_duration_seconds', 0),
                'ports_scanned': summary.get('ports_scanned', 0),
                'infrastructure': summary.get('infrastructure', {})
            }

            # Score de risque (inverse du score d'exposition)
            exposure = data['summary']['exposure_score']
            data['summary']['risk_score'] = 100 - exposure if exposure else 0
            data['summary']['risk_level'] = self._get_risk_level(exposure)

            # 3. Vulnérabilités par sévérité
            vuln_query = text("""
                SELECT
                    id, port, protocol, service_name, service_version,
                    vulnerability_type, severity, cve_ids, cvss_score,
                    title, description, recommendation
                FROM external_service_vulnerability
                WHERE external_scan_id = CAST(:scan_id AS uuid)
                ORDER BY
                    CASE severity
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'HIGH' THEN 2
                        WHEN 'MEDIUM' THEN 3
                        WHEN 'LOW' THEN 4
                        ELSE 5
                    END,
                    cvss_score DESC NULLS LAST
            """)

            vulns = self.db.execute(vuln_query, {"scan_id": str(scan_id)}).fetchall()

            data['vulnerabilities'] = {
                'critical': [],
                'high': [],
                'medium': [],
                'low': [],
                'info': [],
                'all': []
            }

            for v in vulns:
                vuln_data = {
                    'id': str(v.id),
                    'port': v.port,
                    'protocol': v.protocol,
                    'service': v.service_name,
                    'version': v.service_version,
                    'type': v.vulnerability_type,
                    'severity': v.severity,
                    'cve_ids': v.cve_ids or [],
                    'cvss_score': v.cvss_score,
                    'title': v.title,
                    'description': v.description,
                    'recommendation': v.recommendation
                }
                data['vulnerabilities']['all'].append(vuln_data)
                if v.severity == 'CRITICAL':
                    data['vulnerabilities']['critical'].append(vuln_data)
                elif v.severity == 'HIGH':
                    data['vulnerabilities']['high'].append(vuln_data)
                elif v.severity == 'MEDIUM':
                    data['vulnerabilities']['medium'].append(vuln_data)
                elif v.severity == 'LOW':
                    data['vulnerabilities']['low'].append(vuln_data)
                else:
                    data['vulnerabilities']['info'].append(vuln_data)

            # 4. Services (depuis scan_data)
            scan_data = result.scan_data or {}
            data['services'] = scan_data.get('services', [])

            # 5. Détails TLS
            data['tls'] = scan_data.get('tls_details', {})

            # 6. Graphique de positionnement (position de cette entité uniquement)
            data['positioning_chart'] = self._get_entity_positioning(
                tenant_id=result.tenant_id,
                entity_id=result.entity_id,
                highlight_entity_id=result.entity_id
            )

            logger.info(f"✅ Données scanner collectées pour scan {scan_id}")
            return data

        except Exception as e:
            logger.error(f"❌ Erreur collecte données scanner: {str(e)}", exc_info=True)
            raise

    def collect_scan_ecosystem_data(self, tenant_id: UUID, filter_entity_id: UUID = None) -> Dict[str, Any]:
        """
        Collecte les données pour un rapport écosystème scanner.

        Args:
            tenant_id: ID du tenant
            filter_entity_id: Filtrer par entité (optionnel)

        Returns:
            Dict contenant :
            - ecosystem: Statistiques globales de l'écosystème
            - entities: Liste des entités avec leurs scores
            - top_vulnerabilities: Top vulnérabilités par sévérité
            - distribution: Distribution des grades
            - positioning_chart: Graphique avec toutes les entités
            - trends: Tendances (évolution des scores)
        """
        try:
            data = {}

            # Logos
            data['logos'] = self._get_logos_data(tenant_id)

            # 1. Statistiques globales de l'écosystème
            stats_query = text("""
                WITH latest_scans AS (
                    SELECT DISTINCT ON (es.entity_id)
                        es.id,
                        es.entity_id,
                        es.summary,
                        es.finished_at
                    FROM external_scan es
                    WHERE es.tenant_id = CAST(:tenant_id AS uuid)
                      AND es.status = 'SUCCESS'
                      AND es.entity_id IS NOT NULL
                    ORDER BY es.entity_id, es.finished_at DESC
                )
                SELECT
                    COUNT(DISTINCT ls.entity_id) as total_entities,
                    AVG((ls.summary->>'exposure_score')::numeric) as avg_exposure,
                    MIN((ls.summary->>'exposure_score')::numeric) as min_exposure,
                    MAX((ls.summary->>'exposure_score')::numeric) as max_exposure,
                    SUM((ls.summary->>'nb_vuln_critical')::int) as total_critical,
                    SUM((ls.summary->>'nb_vuln_high')::int) as total_high,
                    SUM((ls.summary->>'nb_vuln_medium')::int) as total_medium,
                    SUM((ls.summary->>'nb_vuln_low')::int) as total_low,
                    SUM((ls.summary->>'nb_services_exposed')::int) as total_services
                FROM latest_scans ls
            """)

            stats = self.db.execute(stats_query, {"tenant_id": str(tenant_id)}).fetchone()

            data['ecosystem'] = {
                'total_entities': stats.total_entities or 0,
                'avg_exposure_score': round(float(stats.avg_exposure or 0), 1),
                'min_exposure_score': round(float(stats.min_exposure or 0), 1),
                'max_exposure_score': round(float(stats.max_exposure or 0), 1),
                'total_vulnerabilities': {
                    'critical': stats.total_critical or 0,
                    'high': stats.total_high or 0,
                    'medium': stats.total_medium or 0,
                    'low': stats.total_low or 0,
                    'total': (stats.total_critical or 0) + (stats.total_high or 0) + (stats.total_medium or 0) + (stats.total_low or 0)
                },
                'total_services_exposed': stats.total_services or 0,
                'avg_risk_level': self._get_risk_level(float(stats.avg_exposure or 0)),
                'scan_date': datetime.now(timezone.utc).strftime('%d/%m/%Y')
            }

            # 2. Liste des entités avec leurs scores (dernier scan)
            entities_query = text("""
                WITH latest_scans AS (
                    SELECT DISTINCT ON (es.entity_id)
                        es.id as scan_id,
                        es.entity_id,
                        es.summary,
                        es.finished_at,
                        ee.name as entity_name,
                        ee.logo_url as entity_logo
                    FROM external_scan es
                    JOIN ecosystem_entity ee ON es.entity_id = ee.id
                    WHERE es.tenant_id = CAST(:tenant_id AS uuid)
                      AND es.status = 'SUCCESS'
                      AND es.entity_id IS NOT NULL
                    ORDER BY es.entity_id, es.finished_at DESC
                )
                SELECT
                    ls.scan_id,
                    ls.entity_id,
                    ls.entity_name,
                    ls.entity_logo,
                    ls.summary,
                    ls.finished_at
                FROM latest_scans ls
                ORDER BY (ls.summary->>'exposure_score')::numeric DESC
            """)

            entities = self.db.execute(entities_query, {"tenant_id": str(tenant_id)}).fetchall()

            data['entities'] = []
            for e in entities:
                summary = e.summary or {}
                exposure = summary.get('exposure_score', 0)
                data['entities'].append({
                    'id': str(e.entity_id),
                    'name': e.entity_name,
                    'logo_url': e.entity_logo,
                    'scan_id': str(e.scan_id),
                    'last_scan_date': e.finished_at.strftime('%d/%m/%Y') if e.finished_at else None,
                    'exposure_score': exposure,
                    'risk_level': self._get_risk_level(exposure),
                    'tls_grade': summary.get('tls_grade', 'N/A'),
                    'vuln_critical': summary.get('nb_vuln_critical', 0),
                    'vuln_high': summary.get('nb_vuln_high', 0),
                    'vuln_medium': summary.get('nb_vuln_medium', 0),
                    'vuln_low': summary.get('nb_vuln_low', 0),
                    'services_exposed': summary.get('nb_services_exposed', 0)
                })

            # 3. Top vulnérabilités
            top_vulns_query = text("""
                SELECT
                    v.title,
                    v.severity,
                    v.cvss_score,
                    v.cve_ids,
                    v.port,
                    v.service_name,
                    ee.name as entity_name,
                    COUNT(*) as occurrence_count
                FROM external_service_vulnerability v
                JOIN external_scan es ON v.external_scan_id = es.id
                LEFT JOIN ecosystem_entity ee ON es.entity_id = ee.id
                WHERE es.tenant_id = CAST(:tenant_id AS uuid)
                  AND v.severity IN ('CRITICAL', 'HIGH')
                GROUP BY v.title, v.severity, v.cvss_score, v.cve_ids, v.port, v.service_name, ee.name
                ORDER BY
                    CASE v.severity WHEN 'CRITICAL' THEN 1 ELSE 2 END,
                    v.cvss_score DESC NULLS LAST
                LIMIT 20
            """)

            top_vulns = self.db.execute(top_vulns_query, {"tenant_id": str(tenant_id)}).fetchall()

            data['top_vulnerabilities'] = [
                {
                    'title': v.title,
                    'severity': v.severity,
                    'cvss_score': v.cvss_score,
                    'cve_ids': v.cve_ids or [],
                    'port': v.port,
                    'service': v.service_name,
                    'entity': v.entity_name,
                    'occurrences': v.occurrence_count
                }
                for v in top_vulns
            ]

            # 4. Distribution des grades TLS
            grades_query = text("""
                WITH latest_scans AS (
                    SELECT DISTINCT ON (es.entity_id)
                        es.summary->>'tls_grade' as grade
                    FROM external_scan es
                    WHERE es.tenant_id = CAST(:tenant_id AS uuid)
                      AND es.status = 'SUCCESS'
                      AND es.entity_id IS NOT NULL
                    ORDER BY es.entity_id, es.finished_at DESC
                )
                SELECT
                    COALESCE(grade, 'N/A') as grade,
                    COUNT(*) as count
                FROM latest_scans
                GROUP BY grade
                ORDER BY grade
            """)

            grades = self.db.execute(grades_query, {"tenant_id": str(tenant_id)}).fetchall()

            data['distribution'] = {
                'tls_grades': {g.grade: g.count for g in grades}
            }

            # 5. Graphique de positionnement (toutes les entités)
            data['positioning_chart'] = self._get_entity_positioning(
                tenant_id=tenant_id,
                entity_id=None,  # Toutes les entités
                highlight_entity_id=filter_entity_id
            )

            # 6. Comparaison tableau (classement)
            data['comparison'] = sorted(
                data['entities'],
                key=lambda x: x['exposure_score'],
                reverse=True
            )

            logger.info(f"✅ Données écosystème scanner collectées pour tenant {tenant_id}")
            return data

        except Exception as e:
            logger.error(f"❌ Erreur collecte données écosystème scanner: {str(e)}", exc_info=True)
            raise

    def _get_risk_level(self, exposure_score: float) -> str:
        """
        Détermine le niveau de risque basé sur le score d'exposition.
        Score élevé = risque élevé (plus de vulnérabilités/exposition).
        """
        if exposure_score >= 80:
            return 'Critique'
        elif exposure_score >= 60:
            return 'Élevé'
        elif exposure_score >= 40:
            return 'Moyen'
        elif exposure_score >= 20:
            return 'Faible'
        else:
            return 'Excellent'

    def _get_entity_positioning(
        self,
        tenant_id: UUID,
        entity_id: UUID = None,
        highlight_entity_id: UUID = None
    ) -> Dict[str, Any]:
        """
        Génère les données pour le graphique de positionnement (nuage de points).

        Chaque point représente une entité avec :
        - X: Nombre de CVEs
        - Y: Score CVSS moyen
        - Taille: Score d'exposition

        Args:
            tenant_id: ID du tenant
            entity_id: Si fourni, n'inclut que cette entité
            highlight_entity_id: Entité à mettre en surbrillance

        Returns:
            Dict avec les données du graphique
        """
        try:
            # Requête pour récupérer les données de positionnement
            if entity_id:
                # Une seule entité
                query = text("""
                    WITH latest_scan AS (
                        SELECT
                            es.id,
                            es.entity_id,
                            es.summary,
                            ee.name as entity_name
                        FROM external_scan es
                        JOIN ecosystem_entity ee ON es.entity_id = ee.id
                        WHERE es.entity_id = CAST(:entity_id AS uuid)
                          AND es.status = 'SUCCESS'
                        ORDER BY es.finished_at DESC
                        LIMIT 1
                    ),
                    vuln_stats AS (
                        SELECT
                            ls.entity_id,
                            COUNT(v.id) as total_cves,
                            COALESCE(AVG(v.cvss_score), 0) as avg_cvss
                        FROM latest_scan ls
                        LEFT JOIN external_service_vulnerability v ON v.external_scan_id = ls.id
                        GROUP BY ls.entity_id
                    )
                    SELECT
                        ls.entity_id,
                        ls.entity_name,
                        (ls.summary->>'exposure_score')::numeric as exposure_score,
                        COALESCE(vs.total_cves, 0) as total_cves,
                        COALESCE(vs.avg_cvss, 0) as avg_cvss
                    FROM latest_scan ls
                    LEFT JOIN vuln_stats vs ON ls.entity_id = vs.entity_id
                """)
                params = {"entity_id": str(entity_id)}
            else:
                # Toutes les entités
                query = text("""
                    WITH latest_scans AS (
                        SELECT DISTINCT ON (es.entity_id)
                            es.id,
                            es.entity_id,
                            es.summary,
                            ee.name as entity_name
                        FROM external_scan es
                        JOIN ecosystem_entity ee ON es.entity_id = ee.id
                        WHERE es.tenant_id = CAST(:tenant_id AS uuid)
                          AND es.status = 'SUCCESS'
                          AND es.entity_id IS NOT NULL
                        ORDER BY es.entity_id, es.finished_at DESC
                    ),
                    vuln_stats AS (
                        SELECT
                            ls.entity_id,
                            COUNT(v.id) as total_cves,
                            COALESCE(AVG(v.cvss_score), 0) as avg_cvss
                        FROM latest_scans ls
                        LEFT JOIN external_service_vulnerability v ON v.external_scan_id = ls.id
                        GROUP BY ls.entity_id
                    )
                    SELECT
                        ls.entity_id,
                        ls.entity_name,
                        (ls.summary->>'exposure_score')::numeric as exposure_score,
                        COALESCE(vs.total_cves, 0) as total_cves,
                        COALESCE(vs.avg_cvss, 0) as avg_cvss
                    FROM latest_scans ls
                    LEFT JOIN vuln_stats vs ON ls.entity_id = vs.entity_id
                """)
                params = {"tenant_id": str(tenant_id)}

            results = self.db.execute(query, params).fetchall()

            points = []
            for r in results:
                points.append({
                    'entity_id': str(r.entity_id),
                    'entity_name': r.entity_name,
                    'x': int(r.total_cves or 0),  # Nombre de CVEs
                    'y': round(float(r.avg_cvss or 0), 1),  # CVSS moyen
                    'size': int(r.exposure_score or 50),  # Score d'exposition
                    'highlighted': str(r.entity_id) == str(highlight_entity_id) if highlight_entity_id else False
                })

            return {
                'type': 'scatter',
                'title': 'Positionnement Écosystème',
                'x_label': 'Nombre de CVEs',
                'y_label': 'Score CVSS Moyen',
                'data': points
            }

        except Exception as e:
            logger.error(f"❌ Erreur génération positionnement: {str(e)}")
            return {'type': 'scatter', 'data': []}
