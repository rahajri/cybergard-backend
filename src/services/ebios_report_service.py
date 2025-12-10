"""
Service de génération de rapport EBIOS RM

Ce service gère la collecte des données des ateliers AT1-AT6
et la génération du rapport PDF via WeasyPrint.
"""

import json
import logging
import os
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Configuration Ollama - Utiliser le modèle avancé DeepSeek pour les résumés IA
# IMPORTANT: Le modèle GLM retourne des réponses vides, utiliser DeepSeek
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
# Priorité: OLLAMA_MODEL_ADVANCED > hardcoded deepseek (OLLAMA_MODEL peut être GLM qui ne fonctionne pas)
AI_MODEL = os.getenv("OLLAMA_MODEL_ADVANCED", "deepseek-v3.1:671b-cloud")


class EbiosReportService:
    """Service de génération de rapports EBIOS RM."""

    def __init__(self, db: Session, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id

    async def check_prerequisites(self, project_id: UUID) -> Dict[str, Any]:
        """
        Vérifie les prérequis pour la génération du rapport.

        Returns:
            Dict avec:
            - hasStrategicScenarios: bool
            - hasOperationalScenarios: bool
            - hasActions: bool
            - hasTemplate: bool
            - strategicCount: int
            - operationalCount: int
            - actionsCount: int
            - templateName: str
        """
        try:
            # Compter les scénarios stratégiques (AT3)
            # Note: risk_strategic_scenario n'a pas de tenant_id, filtrer via project_id suffit
            strategic_query = text("""
                SELECT COUNT(*) FROM risk_strategic_scenario
                WHERE project_id = CAST(:project_id AS uuid)
            """)
            strategic_result = self.db.execute(strategic_query, {
                "project_id": str(project_id)
            })
            strategic_count = strategic_result.scalar() or 0

            # Compter les scénarios opérationnels (AT4)
            # Note: risk_operational_scenario n'a pas de tenant_id, filtrer via project_id suffit
            operational_query = text("""
                SELECT COUNT(*) FROM risk_operational_scenario
                WHERE project_id = CAST(:project_id AS uuid)
            """)
            operational_result = self.db.execute(operational_query, {
                "project_id": str(project_id)
            })
            operational_count = operational_result.scalar() or 0

            # Compter les actions - depuis risk_workshop AT5 ai_raw_output
            actions_count = 0
            workshop_query = text("""
                SELECT ai_raw_output FROM risk_workshop
                WHERE project_id = CAST(:project_id AS uuid)
                  AND type = 'AT5'
            """)
            workshop_result = self.db.execute(workshop_query, {
                "project_id": str(project_id)
            })
            workshop_row = workshop_result.fetchone()

            if workshop_row and workshop_row.ai_raw_output:
                try:
                    ai_data = workshop_row.ai_raw_output
                    if isinstance(ai_data, str):
                        ai_data = json.loads(ai_data)
                    actions = ai_data.get('actions', [])
                    actions_count = len(actions)
                except (json.JSONDecodeError, AttributeError):
                    pass

            # Vérifier si un template EBIOS existe pour ce tenant
            template_query = text("""
                SELECT name FROM report_template
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND (name ILIKE '%ebios%' OR code ILIKE '%ebios%')
                LIMIT 1
            """)
            template_result = self.db.execute(template_query, {
                "tenant_id": str(self.tenant_id)
            })
            template_row = template_result.fetchone()

            # Si pas de template spécifique, utiliser le template par défaut
            template_name = template_row.name if template_row else "Template EBIOS RM par défaut"
            has_template = True  # On a toujours un template par défaut

            return {
                "hasStrategicScenarios": strategic_count > 0,
                "hasOperationalScenarios": operational_count > 0,
                "hasActions": actions_count > 0,
                "hasTemplate": has_template,
                "strategicCount": strategic_count,
                "operationalCount": operational_count,
                "actionsCount": actions_count,
                "templateName": template_name
            }

        except Exception as e:
            logger.error(f"Erreur vérification prérequis: {e}")
            raise

    async def collect_project_data(self, project_id: UUID) -> Dict[str, Any]:
        """
        Collecte toutes les données du projet EBIOS pour le rapport.

        Returns:
            Dict avec toutes les données AT1 à AT6
        """
        data = {
            "project": {},
            "at1": {},
            "at2": {},
            "at3": {},
            "at4": {},
            "at5": {},
            "at6": {}
        }

        # Données du projet
        # Note: risk_project n'a pas de organization_id, on récupère uniquement le tenant_name
        project_query = text("""
            SELECT rp.*, t.name as tenant_name
            FROM risk_project rp
            LEFT JOIN tenant t ON rp.tenant_id = t.id
            WHERE rp.id = CAST(:project_id AS uuid)
              AND rp.tenant_id = CAST(:tenant_id AS uuid)
        """)
        project_result = self.db.execute(project_query, {
            "project_id": str(project_id),
            "tenant_id": str(self.tenant_id)
        })
        project_row = project_result.fetchone()

        if project_row:
            data["project"] = {
                "id": str(project_row.id),
                "name": project_row.label,
                "description": project_row.description,
                "status": project_row.status,
                "created_at": str(project_row.created_at) if project_row.created_at else None,
                "tenant_name": project_row.tenant_name,
                "organization_name": project_row.tenant_name  # Utiliser tenant_name à la place
            }

        # AT1 - Valeurs métier
        data["at1"]["business_values"] = await self._collect_business_values(project_id)
        data["at1"]["assets"] = await self._collect_assets(project_id)
        data["at1"]["feared_events"] = await self._collect_feared_events(project_id)

        # AT2 - Sources de risque
        data["at2"]["risk_sources"] = await self._collect_risk_sources(project_id)

        # AT3 - Scénarios stratégiques
        data["at3"]["strategic_scenarios"] = await self._collect_strategic_scenarios(project_id)

        # AT4 - Scénarios opérationnels
        data["at4"]["operational_scenarios"] = await self._collect_operational_scenarios(project_id)

        # AT5 - Matrice des risques
        data["at5"]["matrix"] = await self._collect_risk_matrix(project_id)

        # AT6 - Actions
        data["at6"]["actions"] = await self._collect_actions(project_id)

        # Logos du tenant
        data["logos"] = self._get_logos_data()

        return data

    def _get_logos_data(self) -> Dict[str, Any]:
        """
        Récupère les URLs des logos pour le rapport EBIOS.

        Returns:
            Dict avec les URLs des logos (tenant, organization)
        """
        try:
            logos = {
                'tenant_logo_url': None,
                'organization_logo_url': None,
                'tenant_name': None,
                'organization_name': None,
                'custom_logo': None
            }

            # Récupérer le logo du tenant
            tenant_result = self.db.execute(text("""
                SELECT t.name, t.logo_url
                FROM tenant t
                WHERE t.id = CAST(:tenant_id AS uuid)
            """), {"tenant_id": str(self.tenant_id)}).fetchone()

            if tenant_result:
                logos['tenant_name'] = tenant_result.name
                logos['tenant_logo_url'] = tenant_result.logo_url
                # Le logo du tenant est aussi le custom_logo par défaut
                if tenant_result.logo_url:
                    logos['custom_logo'] = tenant_result.logo_url

            # Récupérer le logo de l'organization liée au tenant
            org_result = self.db.execute(text("""
                SELECT o.name, o.logo_url
                FROM organization o
                WHERE o.tenant_id = CAST(:tenant_id AS uuid)
                LIMIT 1
            """), {"tenant_id": str(self.tenant_id)}).fetchone()

            if org_result:
                logos['organization_name'] = org_result.name
                logos['organization_logo_url'] = org_result.logo_url
                # Si pas de logo tenant, utiliser celui de l'org
                if not logos['custom_logo'] and org_result.logo_url:
                    logos['custom_logo'] = org_result.logo_url

            logger.info(f"🖼️ Logos récupérés: tenant={bool(logos['tenant_logo_url'])}, org={bool(logos['organization_logo_url'])}")
            return logos

        except Exception as e:
            logger.error(f"Erreur récupération logos: {e}")
            return {
                'tenant_logo_url': None,
                'organization_logo_url': None,
                'tenant_name': None,
                'organization_name': None,
                'custom_logo': None
            }

    async def _collect_business_values(self, project_id: UUID) -> List[Dict]:
        """Collecte les valeurs métier (AT1)."""
        # Note: risk_business_value n'a pas de tenant_id, on filtre par project_id uniquement
        query = text("""
            SELECT * FROM risk_business_value
            WHERE project_id = CAST(:project_id AS uuid)
            ORDER BY code
        """)
        result = self.db.execute(query, {
            "project_id": str(project_id)
        })

        values = []
        for row in result:
            values.append({
                "code": row.code,
                "label": row.label,
                "description": row.description,
                "criticality": row.criticality,
                "is_selected": getattr(row, 'is_selected', False)
            })
        return values

    async def _collect_assets(self, project_id: UUID) -> List[Dict]:
        """Collecte les biens supports (AT1)."""
        # Note: risk_asset n'a pas de tenant_id, on filtre par project_id uniquement
        query = text("""
            SELECT * FROM risk_asset
            WHERE project_id = CAST(:project_id AS uuid)
            ORDER BY code
        """)
        result = self.db.execute(query, {
            "project_id": str(project_id)
        })

        assets = []
        for row in result:
            assets.append({
                "code": row.code,
                "label": row.label,
                "description": row.description,
                "asset_type": getattr(row, 'type', ''),  # Colonne s'appelle 'type' dans la DB
                "is_selected": getattr(row, 'is_selected', False)
            })
        return assets

    async def _collect_feared_events(self, project_id: UUID) -> List[Dict]:
        """Collecte les événements redoutés (AT1)."""
        # Note: risk_feared_event n'a pas de tenant_id, on filtre par project_id uniquement
        query = text("""
            SELECT * FROM risk_feared_event
            WHERE project_id = CAST(:project_id AS uuid)
            ORDER BY code
        """)
        result = self.db.execute(query, {
            "project_id": str(project_id)
        })

        events = []
        for row in result:
            events.append({
                "code": row.code,
                "label": row.label,
                "description": row.description,
                "dimension": getattr(row, 'dimension', ''),  # Dimension D/I/C/T
                "severity": row.severity,
                "is_selected": getattr(row, 'is_selected', False)
            })
        return events

    async def _collect_risk_sources(self, project_id: UUID) -> List[Dict]:
        """Collecte les sources de risque (AT2)."""
        # Note: risk_source n'a pas de tenant_id, on filtre par project_id uniquement
        # Note: risk_source_objective utilise 'source_id' comme FK et n'a pas de 'code'
        query = text("""
            SELECT rs.*,
                   (SELECT json_agg(json_build_object('label', o.label, 'description', o.description))
                    FROM risk_source_objective o
                    WHERE o.source_id = rs.id) as objectives
            FROM risk_source rs
            WHERE rs.project_id = CAST(:project_id AS uuid)
            ORDER BY rs.code
        """)
        result = self.db.execute(query, {
            "project_id": str(project_id)
        })

        sources = []
        for row in result:
            sources.append({
                "code": row.code,
                "label": row.label,
                "description": row.description,
                "relevance": getattr(row, 'relevance', 2),  # Pertinence dans la DB
                "is_selected": getattr(row, 'is_selected', False),
                "objectives": row.objectives or []
            })
        return sources

    async def _collect_strategic_scenarios(self, project_id: UUID) -> List[Dict]:
        """Collecte les scénarios stratégiques (AT3)."""
        query = text("""
            SELECT ss.*,
                   rs.code as risk_source_code, rs.label as risk_source_label,
                   fe.code as feared_event_code, fe.label as feared_event_label
            FROM risk_strategic_scenario ss
            LEFT JOIN risk_source rs ON ss.risk_source_id = rs.id
            LEFT JOIN risk_feared_event fe ON ss.feared_event_id = fe.id
            WHERE ss.project_id = CAST(:project_id AS uuid)
            ORDER BY ss.code
        """)
        result = self.db.execute(query, {
            "project_id": str(project_id)
        })

        scenarios = []
        for row in result:
            severity = row.severity or 1
            likelihood = getattr(row, 'likelihood_raw', 1) or 1  # Colonne s'appelle 'likelihood_raw'
            scenarios.append({
                "code": row.code,
                "title": row.title,
                "description": row.description,
                "severity": severity,
                "likelihood": likelihood,
                "risk_level": severity * likelihood,
                "risk_source": {
                    "code": row.risk_source_code,
                    "label": row.risk_source_label
                } if row.risk_source_code else None,
                "feared_event": {
                    "code": row.feared_event_code,
                    "label": row.feared_event_label
                } if row.feared_event_code else None
            })
        return scenarios

    async def _collect_operational_scenarios(self, project_id: UUID) -> List[Dict]:
        """Collecte les scénarios opérationnels (AT4)."""
        query = text("""
            SELECT os.*,
                   ss.code as strategic_code, ss.title as strategic_title
            FROM risk_operational_scenario os
            LEFT JOIN risk_strategic_scenario ss ON os.strategic_scenario_id = ss.id
            WHERE os.project_id = CAST(:project_id AS uuid)
            ORDER BY os.code
        """)
        result = self.db.execute(query, {
            "project_id": str(project_id)
        })

        scenarios = []
        for row in result:
            severity = getattr(row, 'severity', 1) or 1
            likelihood = getattr(row, 'likelihood', 1) or 1
            scenarios.append({
                "code": row.code,
                "title": row.title,
                "description": row.description,
                "severity": severity,
                "likelihood": likelihood,
                "risk_level": severity * likelihood,
                "strategic_scenario": {
                    "code": row.strategic_code,
                    "title": row.strategic_title
                } if getattr(row, 'strategic_code', None) else None
            })
        return scenarios

    async def _collect_risk_matrix(self, project_id: UUID) -> Dict:
        """Collecte la matrice des risques (AT5)."""
        # Récupérer les données du workshop AT5
        # Note: risk_workshop n'a pas de tenant_id, on filtre par project_id uniquement
        workshop_query = text("""
            SELECT ai_raw_output FROM risk_workshop
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        result = self.db.execute(workshop_query, {
            "project_id": str(project_id)
        })
        row = result.fetchone()

        matrix_data = {
            "cells": [],
            "scenarios": []
        }

        if row and row.ai_raw_output:
            try:
                ai_data = row.ai_raw_output
                if isinstance(ai_data, str):
                    ai_data = json.loads(ai_data)

                # Construire la matrice 5x5
                scenarios = []
                scenarios.extend(await self._collect_strategic_scenarios(project_id))
                scenarios.extend(await self._collect_operational_scenarios(project_id))

                matrix_data["scenarios"] = scenarios

                # Calculer les cellules de la matrice
                cells = {}
                for s in scenarios:
                    key = f"{s['severity']}_{s['likelihood']}"
                    if key not in cells:
                        cells[key] = []
                    cells[key].append(s['code'])

                matrix_data["cells"] = cells

            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning(f"Erreur parsing AT5 data: {e}")

        return matrix_data

    async def _collect_actions(self, project_id: UUID) -> List[Dict]:
        """Collecte les actions (AT6)."""
        # Les actions sont stockées dans ai_raw_output du workshop AT5
        # Note: risk_workshop n'a pas de tenant_id, on filtre par project_id uniquement
        workshop_query = text("""
            SELECT ai_raw_output FROM risk_workshop
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        result = self.db.execute(workshop_query, {
            "project_id": str(project_id)
        })
        row = result.fetchone()

        if row and row.ai_raw_output:
            try:
                ai_data = row.ai_raw_output
                if isinstance(ai_data, str):
                    ai_data = json.loads(ai_data)
                return ai_data.get('actions', [])
            except (json.JSONDecodeError, AttributeError):
                pass

        return []

    async def generate_ai_summary(
        self,
        section: str,
        data: Dict[str, Any],
        tone: str = 'executive'
    ) -> str:
        """
        Génère une synthèse IA pour une section du rapport.

        Args:
            section: Nom de la section (executive_summary, at1_summary, etc.)
            data: Données de la section
            tone: Ton du rapport (executive, technical, detailed)

        Returns:
            Texte généré par l'IA
        """
        # Prompts par section
        prompts = {
            "executive_summary": f"""Tu es un expert en analyse de risques EBIOS RM.
Génère un résumé exécutif (1-2 paragraphes) de l'analyse de risques suivante.
Ton: {"concis et orienté décision" if tone == 'executive' else "technique et détaillé" if tone == 'technical' else "exhaustif avec références méthodologiques"}

Projet: {data.get('project', {}).get('name', 'N/A')}
Nombre de scénarios stratégiques: {len(data.get('at3', {}).get('strategic_scenarios', []))}
Nombre de scénarios opérationnels: {len(data.get('at4', {}).get('operational_scenarios', []))}
Nombre d'actions: {len(data.get('at6', {}).get('actions', []))}

Génère uniquement le résumé, sans titre ni formatage markdown.""",

            "at1_summary": f"""Tu es un expert EBIOS RM.
Résume en 2-3 phrases le cadrage et socle de sécurité (AT1):
- Valeurs métier identifiées: {len(data.get('at1', {}).get('business_values', []))}
- Biens supports: {len(data.get('at1', {}).get('assets', []))}
- Événements redoutés: {len(data.get('at1', {}).get('feared_events', []))}

Génère uniquement le résumé textuel.""",

            "at2_summary": f"""Tu es un expert EBIOS RM.
Résume en 2-3 phrases les sources de risque identifiées (AT2):
Sources: {json.dumps([s.get('label') for s in data.get('at2', {}).get('risk_sources', [])[:5]], ensure_ascii=False)}

Génère uniquement le résumé textuel.""",

            "risk_analysis": f"""Tu es un expert EBIOS RM.
Analyse brièvement les niveaux de risque:
- Scénarios à risque critique (niveau >= 16): {len([s for s in data.get('at3', {}).get('strategic_scenarios', []) if s.get('risk_level', 0) >= 16])}
- Scénarios à risque important (niveau 9-15): {len([s for s in data.get('at3', {}).get('strategic_scenarios', []) if 9 <= s.get('risk_level', 0) < 16])}
- Scénarios à risque modéré (niveau < 9): {len([s for s in data.get('at3', {}).get('strategic_scenarios', []) if s.get('risk_level', 0) < 9])}

Génère 2-3 phrases d'analyse."""
        }

        prompt = prompts.get(section, f"Génère un résumé pour la section {section}.")

        try:
            logger.info(f"🤖 Génération IA EBIOS: model={AI_MODEL}, section={section}")
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": AI_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_predict": 500
                        }
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    generated_text = result.get("response", "").strip()
                    logger.info(f"✅ IA EBIOS {section}: {len(generated_text)} chars générés")
                    return generated_text
                else:
                    logger.warning(f"⚠️ Erreur IA EBIOS: {response.status_code} - {response.text[:200]}")
                    return ""

        except httpx.TimeoutException:
            logger.warning(f"⚠️ Timeout génération IA EBIOS pour {section}")
            return ""
        except Exception as e:
            logger.error(f"❌ Erreur génération IA EBIOS: {e}")
            return ""

    def get_ebios_template(self, report_scope: str = "consolidated"):
        """
        Récupère le template EBIOS depuis la base de données.

        Args:
            report_scope: Scope du rapport ('consolidated' ou 'individual')

        Returns:
            Tuple (template_data, structure) ou (None, None) si non trouvé
        """
        # Sélectionner le template selon le scope demandé
        # - CONSOLIDATED pour les rapports complets
        # - INDIVIDUAL pour les fiches scénarios
        if report_scope == "individual":
            # Chercher d'abord INDIVIDUAL puis CONSOLIDATED
            order_clause = "CASE WHEN code ILIKE '%INDIVIDUAL%' THEN 0 ELSE 1 END"
        else:
            # Chercher d'abord CONSOLIDATED puis INDIVIDUAL
            order_clause = "CASE WHEN code ILIKE '%CONSOLIDATED%' THEN 0 ELSE 1 END"

        query = text(f"""
            SELECT id, name, code, color_scheme, fonts, structure, custom_css,
                   default_logo, custom_logo
            FROM report_template
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND (code ILIKE '%ebios%' OR name ILIKE '%ebios%')
            ORDER BY
                {order_clause},
                is_default DESC,
                created_at DESC
            LIMIT 1
        """)
        result = self.db.execute(query, {"tenant_id": str(self.tenant_id)})
        row = result.fetchone()

        if row:
            logger.info(f"✅ Template EBIOS trouvé: {row.name} ({row.code})")
            structure = row.structure
            if isinstance(structure, str):
                structure = json.loads(structure)
            return {
                "id": str(row.id),
                "name": row.name,
                "code": row.code,
                "color_scheme": row.color_scheme or {},
                "fonts": row.fonts or {},
                "custom_css": row.custom_css or "",
                "default_logo": getattr(row, 'default_logo', 'TENANT'),
                "custom_logo": getattr(row, 'custom_logo', None)
            }, structure
        else:
            logger.warning("⚠️ Aucun template EBIOS trouvé, utilisation du template par défaut")
            return None, None

    def generate_html_from_template(
        self,
        data: Dict[str, Any],
        ai_summaries: Dict[str, str] = None,
        report_scope: str = "consolidated"
    ) -> str:
        """
        Génère le HTML du rapport EBIOS RM en utilisant le template depuis la BDD.

        Cette méthode utilise le WidgetRenderer pour rendre les widgets
        définis dans le template maître côté Admin.

        Args:
            data: Données collectées du projet (AT1-AT6)
            ai_summaries: Résumés générés par l'IA
            report_scope: Scope du rapport ('consolidated' ou 'individual')

        Returns:
            HTML du rapport
        """
        from .widget_renderer import WidgetRenderer

        ai_summaries = ai_summaries or {}

        # Récupérer le template EBIOS selon le scope
        template_info, structure = self.get_ebios_template(report_scope)
        logger.info(f"📋 Template sélectionné pour scope '{report_scope}': {template_info.get('name') if template_info else 'AUCUN'}")

        if not structure:
            # Fallback vers la méthode manuelle si pas de template
            logger.warning("⚠️ Pas de template EBIOS, fallback vers génération manuelle")
            return self.generate_html_report(data, {}, ai_summaries)

        # Préparer les couleurs et polices du template
        color_scheme = template_info.get('color_scheme', {
            'primary': '#dc2626',  # Rouge EBIOS
            'secondary': '#991b1b',
            'accent': '#f87171',
            'danger': '#dc2626',
            'warning': '#f59e0b',
            'success': '#22c55e',
            'text': '#1F2937',
            'background': '#FFFFFF'
        })

        fonts = template_info.get('fonts', {
            'title': {'family': 'Helvetica, Arial, sans-serif', 'size': 24, 'weight': 'bold'},
            'heading1': {'family': 'Helvetica, Arial, sans-serif', 'size': 18, 'weight': 'bold'},
            'heading2': {'family': 'Helvetica, Arial, sans-serif', 'size': 14, 'weight': 'bold'},
            'heading3': {'family': 'Helvetica, Arial, sans-serif', 'size': 12, 'weight': 'bold'},
            'body': {'family': 'Helvetica, Arial, sans-serif', 'size': 10, 'weight': 'normal'}
        })

        # Créer le renderer
        renderer = WidgetRenderer(color_scheme, fonts)

        # Gérer le logo du template (comme dans report_job_processor)
        default_logo = template_info.get('default_logo', 'TENANT')
        custom_logo = template_info.get('custom_logo')

        logger.info(f"🖼️ Template logo: default_logo='{default_logo}', custom_logo={'présent' if custom_logo else 'absent'}")

        if default_logo == 'CUSTOM' and custom_logo:
            # Logo personnalisé du template - appliquer à toutes les sources
            if 'logos' not in data:
                data['logos'] = {}
            data['logos']['tenant_logo_url'] = custom_logo
            data['logos']['entity_logo_url'] = custom_logo
            data['logos']['organization_logo_url'] = custom_logo
            data['logos']['custom_logo'] = custom_logo
            logger.info(f"✅ Logo personnalisé du template appliqué ({len(custom_logo)} chars)")
        elif default_logo == 'PLATFORM':
            # Logo plateforme
            if 'logos' not in data:
                data['logos'] = {}
            data['logos']['tenant_logo_url'] = '/logo-cyberguard.png'
            logger.info(f"✅ Logo plateforme appliqué")
        elif default_logo == 'NONE':
            # Pas de logo
            if 'logos' not in data:
                data['logos'] = {}
            data['logos']['tenant_logo_url'] = None
            logger.info(f"✅ Aucun logo configuré")
        # Si TENANT (défaut), le logo du tenant récupéré par _get_logos_data() reste

        # Préparer les données avec les ai_contents
        # Mapper les ai_summaries vers les sections attendues par les widgets
        ai_contents = {}
        for section, content in ai_summaries.items():
            if content:
                # Les widgets utilisent la section comme clé
                ai_contents[section] = {
                    "text": content,
                    "tone": "executive"
                }
        data['ai_contents'] = ai_contents
        data['ai_summary'] = {"text": ai_summaries.get('executive_summary', '')}

        logger.info(f"🎨 generate_html_from_template: ai_contents keys={list(ai_contents.keys())}")

        # Passer la structure du template dans data pour que render_toc puisse générer la TOC
        data['_template_structure'] = structure

        # Générer le HTML de chaque widget
        widgets_html = []
        prev_section_title = None  # Pour détecter doublons section + ai_summary
        rendered_ai_titles = set()  # Pour éviter doublons de widgets ai_summary

        for i, widget in enumerate(structure):
            widget_type = widget.get('widget_type', '')
            config = widget.get('config', {}).copy()

            # Ajouter l'ID du widget pour les widgets IA
            widget_id = widget.get('id') or widget.get('widget_key') or ''
            if widget_id:
                config['id'] = widget_id

            # Tracker le titre des sections pour éviter doublons
            if widget_type == 'section':
                prev_section_title = config.get('title', '')

            # Pour les widgets ai_summary, utiliser la section comme clé (id du widget)
            if widget_type in ['ai_summary', 'summary']:
                section = config.get('section', '')
                # TOUJOURS définir config['id'] = section pour que le renderer puisse trouver le contenu
                if section:
                    config['id'] = section
                logger.info(f"🤖 Widget IA #{i}: type={widget_type}, section={section}, id={config.get('id', 'NONE')}")

                # Éviter doublon de titre
                ai_title = config.get('title', 'Résumé Exécutif')
                ai_title_lower = ai_title.lower()

                # Cas 1: Section précédente avec même titre
                if prev_section_title and prev_section_title.lower() == ai_title_lower:
                    config['show_title'] = False
                    logger.info(f"🔄 Masquage titre doublon: '{ai_title}' (déjà dans section précédente)")
                # Cas 2: Widget ai_summary avec même titre déjà rendu
                elif ai_title_lower in rendered_ai_titles:
                    config['show_title'] = False
                    logger.info(f"🔄 Masquage titre doublon: '{ai_title}' (widget ai_summary déjà rendu)")

                # Enregistrer ce titre comme déjà rendu
                rendered_ai_titles.add(ai_title_lower)

                # Reset après utilisation
                prev_section_title = None
            else:
                # Reset si widget entre section et ai_summary
                if widget_type != 'section':
                    prev_section_title = None

            try:
                html = renderer.render_widget(widget_type, config, data)
                widgets_html.append(html)
            except Exception as e:
                logger.warning(f"Erreur rendu widget {widget_type}: {e}")
                widgets_html.append(f"<!-- Erreur widget {widget_type}: {e} -->")

        # Assembler le HTML final
        primary_color = color_scheme.get('primary', '#dc2626')
        custom_css = template_info.get('custom_css', '')

        html = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <style>
                @page {{
                    size: A4;
                    margin: 15mm;
                }}
                body {{
                    font-family: {fonts.get('body', {}).get('family', 'Helvetica, Arial, sans-serif')};
                    font-size: {fonts.get('body', {}).get('size', 10)}px;
                    line-height: 1.6;
                    color: {color_scheme.get('text', '#1F2937')};
                    margin: 0;
                    padding: 0;
                    background: {color_scheme.get('background', '#FFFFFF')};
                }}
                .page-break {{
                    page-break-after: always;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                th, td {{
                    padding: 8px 12px;
                    text-align: left;
                    border-bottom: 1px solid #e5e7eb;
                }}
                th {{
                    background: {primary_color};
                    color: white;
                    font-weight: 600;
                }}
                .risk-critical {{ background-color: #fecaca; color: #7f1d1d; }}
                .risk-high {{ background-color: #fed7aa; color: #9a3412; }}
                .risk-medium {{ background-color: #fef08a; color: #854d0e; }}
                .risk-low {{ background-color: #bbf7d0; color: #166534; }}
                {custom_css}
            </style>
        </head>
        <body>
            {''.join(widgets_html)}
        </body>
        </html>
        """

        logger.info(f"✅ HTML généré depuis template EBIOS ({len(widgets_html)} widgets)")
        return html

    def generate_html_report(
        self,
        data: Dict[str, Any],
        options: Dict[str, Any],
        ai_summaries: Dict[str, str] = None
    ) -> str:
        """
        Génère le HTML du rapport EBIOS RM.

        Args:
            data: Données collectées du projet
            options: Options de génération
            ai_summaries: Résumés générés par l'IA

        Returns:
            HTML du rapport
        """
        ai_summaries = ai_summaries or {}
        project = data.get('project', {})

        # Styles CSS compatibles xhtml2pdf
        css = """
        <style>
            @page {
                size: A4;
                margin: 2cm;
            }
            body {
                font-family: Helvetica, Arial, sans-serif;
                font-size: 10pt;
                line-height: 1.5;
                color: #333333;
            }
            .cover {
                text-align: center;
                padding-top: 150px;
                page-break-after: always;
            }
            .cover h1 {
                color: #dc2626;
                font-size: 24pt;
                margin-bottom: 30px;
            }
            .cover .project-name {
                font-size: 16pt;
                color: #666666;
                margin-bottom: 60px;
            }
            .cover .date {
                font-size: 11pt;
                color: #999999;
            }
            h1 {
                color: #dc2626;
                font-size: 18pt;
                border-bottom: 2px solid #dc2626;
                padding-bottom: 5px;
                margin-top: 30px;
            }
            h2 {
                color: #991b1b;
                font-size: 14pt;
                margin-top: 25px;
            }
            h3 {
                color: #7f1d1d;
                font-size: 12pt;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
            }
            th, td {
                border: 1px solid #dddddd;
                padding: 8px;
                text-align: left;
                font-size: 9pt;
            }
            th {
                background-color: #fee2e2;
                color: #991b1b;
                font-weight: bold;
            }
            .risk-critical { background-color: #fecaca; color: #7f1d1d; }
            .risk-high { background-color: #fed7aa; color: #9a3412; }
            .risk-medium { background-color: #fef08a; color: #854d0e; }
            .risk-low { background-color: #bbf7d0; color: #166534; }
            .summary-box {
                background-color: #f3f4f6;
                border-left: 4px solid #dc2626;
                padding: 15px;
                margin: 20px 0;
            }
            .action-card {
                border: 1px solid #e5e7eb;
                padding: 15px;
                margin: 15px 0;
                background-color: #fafafa;
            }
            .action-code {
                font-weight: bold;
                color: #dc2626;
            }
            .priority-P1 { color: #dc2626; font-weight: bold; }
            .priority-P2 { color: #f59e0b; font-weight: bold; }
            .priority-P3 { color: #3b82f6; font-weight: bold; }
            .page-break { page-break-before: always; }
            .text-center { text-align: center; }
            .matrix-cell {
                text-align: center;
                padding: 15px;
                font-weight: bold;
            }
        </style>
        """

        # Page de couverture
        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Rapport EBIOS RM - {project.get('name', 'Projet')}</title>
    {css}
</head>
<body>
    <div class="cover">
        <h1>Rapport d'Analyse de Risques<br/>EBIOS RM</h1>
        <div class="project-name">{project.get('name', 'Projet EBIOS')}</div>
        <div class="date">Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}</div>
        <div style="margin-top: 3cm; color: #666;">
            <p>{project.get('organization_name', '')}</p>
        </div>
    </div>
"""

        # Résumé exécutif
        if ai_summaries.get('executive_summary'):
            html += f"""
    <h1>Résumé Exécutif</h1>
    <div class="summary-box">
        {ai_summaries['executive_summary']}
    </div>
"""

        # AT1 - Cadrage
        at1 = data.get('at1', {})
        if options.get('include_at1', True):
            html += """
    <div class="page-break"></div>
    <h1>AT1 - Cadrage et Socle de Sécurité</h1>
"""
            if ai_summaries.get('at1_summary'):
                html += f"""
    <div class="summary-box">{ai_summaries['at1_summary']}</div>
"""

            # Valeurs métier
            business_values = at1.get('business_values', [])
            if business_values:
                html += """
    <h2>Valeurs Métier</h2>
    <table>
        <thead>
            <tr><th>Code</th><th>Libellé</th><th>Description</th><th>Criticité</th></tr>
        </thead>
        <tbody>
"""
                for bv in business_values:
                    crit_class = f"risk-{'critical' if bv.get('criticality') == 'CRITICAL' else 'high' if bv.get('criticality') == 'HIGH' else 'medium' if bv.get('criticality') == 'MEDIUM' else 'low'}"
                    html += f"""
            <tr>
                <td>{bv.get('code', '')}</td>
                <td>{bv.get('label', '')}</td>
                <td>{(bv.get('description', '') or '')[:100]}...</td>
                <td class="{crit_class}">{bv.get('criticality', 'N/A')}</td>
            </tr>
"""
                html += """
        </tbody>
    </table>
"""

            # Biens supports
            assets = at1.get('assets', [])
            if assets:
                html += """
    <h2>Biens Supports</h2>
    <table>
        <thead>
            <tr><th>Code</th><th>Libellé</th><th>Type</th><th>Description</th></tr>
        </thead>
        <tbody>
"""
                for asset in assets:
                    html += f"""
            <tr>
                <td>{asset.get('code', '')}</td>
                <td>{asset.get('label', '')}</td>
                <td>{asset.get('asset_type', '')}</td>
                <td>{(asset.get('description', '') or '')[:80]}...</td>
            </tr>
"""
                html += """
        </tbody>
    </table>
"""

            # Événements redoutés
            feared_events = at1.get('feared_events', [])
            if feared_events:
                html += """
    <h2>Événements Redoutés</h2>
    <table>
        <thead>
            <tr><th>Code</th><th>Libellé</th><th>Gravité</th></tr>
        </thead>
        <tbody>
"""
                for fe in feared_events:
                    sev = fe.get('severity', 1)
                    sev_class = f"risk-{'critical' if sev >= 4 else 'high' if sev >= 3 else 'medium' if sev >= 2 else 'low'}"
                    html += f"""
            <tr>
                <td>{fe.get('code', '')}</td>
                <td>{fe.get('label', '')}</td>
                <td class="{sev_class}">{sev}/4</td>
            </tr>
"""
                html += """
        </tbody>
    </table>
"""

        # AT2 - Sources de risque
        at2 = data.get('at2', {})
        risk_sources = at2.get('risk_sources', [])
        if risk_sources:
            html += """
    <div class="page-break"></div>
    <h1>AT2 - Sources de Risques</h1>
"""
            if ai_summaries.get('at2_summary'):
                html += f"""
    <div class="summary-box">{ai_summaries['at2_summary']}</div>
"""
            html += """
    <table>
        <thead>
            <tr><th>Code</th><th>Source</th><th>Description</th><th>Pertinence</th></tr>
        </thead>
        <tbody>
"""
            for rs in risk_sources:
                pert = rs.get('relevance', 2)
                pert_class = f"risk-{'critical' if pert >= 4 else 'high' if pert >= 3 else 'medium' if pert >= 2 else 'low'}"
                html += f"""
            <tr>
                <td>{rs.get('code', '')}</td>
                <td>{rs.get('label', '')}</td>
                <td>{(rs.get('description', '') or '')[:100]}...</td>
                <td class="{pert_class}">{pert}/4</td>
            </tr>
"""
            html += """
        </tbody>
    </table>
"""

        # AT3 - Scénarios stratégiques
        if options.get('include_strategic_scenarios', True):
            at3 = data.get('at3', {})
            strategic = at3.get('strategic_scenarios', [])
            if strategic:
                html += """
    <div class="page-break"></div>
    <h1>AT3 - Scénarios Stratégiques</h1>
    <table>
        <thead>
            <tr><th>Code</th><th>Titre</th><th>Source</th><th>Gravité</th><th>Vraisemblance</th><th>Niveau</th></tr>
        </thead>
        <tbody>
"""
                for ss in strategic:
                    level = ss.get('risk_level', 0)
                    level_class = f"risk-{'critical' if level >= 16 else 'high' if level >= 9 else 'medium' if level >= 4 else 'low'}"
                    html += f"""
            <tr>
                <td>{ss.get('code', '')}</td>
                <td>{ss.get('title', '')}</td>
                <td>{ss.get('risk_source', {}).get('code', 'N/A') if ss.get('risk_source') else 'N/A'}</td>
                <td>{ss.get('severity', 'N/A')}/4</td>
                <td>{ss.get('likelihood', 'N/A')}/4</td>
                <td class="{level_class}">{level}</td>
            </tr>
"""
                html += """
        </tbody>
    </table>
"""

        # AT4 - Scénarios opérationnels
        if options.get('include_operational_scenarios', True):
            at4 = data.get('at4', {})
            operational = at4.get('operational_scenarios', [])
            if operational:
                html += """
    <div class="page-break"></div>
    <h1>AT4 - Scénarios Opérationnels</h1>
    <table>
        <thead>
            <tr><th>Code</th><th>Titre</th><th>Scénario Stratégique</th><th>Gravité</th><th>Vraisemblance</th><th>Niveau</th></tr>
        </thead>
        <tbody>
"""
                for os in operational:
                    level = os.get('risk_level', 0)
                    level_class = f"risk-{'critical' if level >= 16 else 'high' if level >= 9 else 'medium' if level >= 4 else 'low'}"
                    html += f"""
            <tr>
                <td>{os.get('code', '')}</td>
                <td>{os.get('title', '')}</td>
                <td>{os.get('strategic_scenario', {}).get('code', 'N/A') if os.get('strategic_scenario') else 'N/A'}</td>
                <td>{os.get('severity', 'N/A')}/4</td>
                <td>{os.get('likelihood', 'N/A')}/4</td>
                <td class="{level_class}">{level}</td>
            </tr>
"""
                html += """
        </tbody>
    </table>
"""

        # AT5 - Matrice des risques
        html += """
    <div class="page-break"></div>
    <h1>AT5 - Matrice des Risques</h1>
    <p>Positionnement des scénarios selon leur niveau de risque (Gravité × Vraisemblance).</p>
"""
        # Collecter tous les scénarios
        all_scenarios = data.get('at3', {}).get('strategic_scenarios', []) + data.get('at4', {}).get('operational_scenarios', [])

        # Créer une grille 5x5 pour positionner les scénarios
        # matrix[severity][likelihood] = liste de codes
        matrix_grid = {}
        for sev in range(1, 6):
            matrix_grid[sev] = {}
            for lik in range(1, 6):
                matrix_grid[sev][lik] = []

        for s in all_scenarios:
            sev = min(max(int(s.get('severity', 1)), 1), 5)
            lik = min(max(int(s.get('likelihood', 1)), 1), 5)
            matrix_grid[sev][lik].append(s.get('code', '?'))

        # Compter par niveau de risque pour le résumé
        risk_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        for s in all_scenarios:
            level = s.get('risk_level', 0)
            if level >= 16:
                risk_counts['critical'] += 1
            elif level >= 9:
                risk_counts['high'] += 1
            elif level >= 4:
                risk_counts['medium'] += 1
            else:
                risk_counts['low'] += 1

        # Fonction pour déterminer la couleur de la cellule selon le niveau de risque
        def get_cell_color(severity: int, likelihood: int) -> str:
            level = severity * likelihood
            if level >= 16:
                return "#ffcdd2"  # Rouge clair - Critique
            elif level >= 9:
                return "#ffe0b2"  # Orange clair - Important
            elif level >= 4:
                return "#fff9c4"  # Jaune clair - Modéré
            else:
                return "#c8e6c9"  # Vert clair - Faible

        # Générer la matrice HTML 5x5
        html += """
    <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
        <thead>
            <tr>
                <th style="width: 80px; background: #f5f5f5; padding: 8px; border: 1px solid #ddd;">Gravité ↓<br/>Vraisemb. →</th>
                <th style="background: #f5f5f5; padding: 8px; border: 1px solid #ddd; text-align: center;">1<br/><small>Minime</small></th>
                <th style="background: #f5f5f5; padding: 8px; border: 1px solid #ddd; text-align: center;">2<br/><small>Significatif</small></th>
                <th style="background: #f5f5f5; padding: 8px; border: 1px solid #ddd; text-align: center;">3<br/><small>Fort</small></th>
                <th style="background: #f5f5f5; padding: 8px; border: 1px solid #ddd; text-align: center;">4<br/><small>Maximal</small></th>
            </tr>
        </thead>
        <tbody>
"""
        # Lignes de la matrice (gravité de 4 à 1, du haut vers le bas)
        severity_labels = {4: "Critique", 3: "Grave", 2: "Significatif", 1: "Négligeable"}
        for sev in range(4, 0, -1):
            html += f"""
            <tr>
                <td style="background: #f5f5f5; padding: 8px; border: 1px solid #ddd; font-weight: bold; text-align: center;">
                    {sev}<br/><small>{severity_labels.get(sev, '')}</small>
                </td>
"""
            for lik in range(1, 5):
                cell_color = get_cell_color(sev, lik)
                scenarios_in_cell = matrix_grid.get(sev, {}).get(lik, [])
                cell_content = "<br/>".join(scenarios_in_cell) if scenarios_in_cell else "-"
                html += f"""
                <td style="background: {cell_color}; padding: 8px; border: 1px solid #ddd; text-align: center; vertical-align: middle; min-height: 50px;">
                    {cell_content}
                </td>
"""
            html += """
            </tr>
"""
        html += """
        </tbody>
    </table>
"""
        # Légende et résumé
        html += f"""
    <h3>Synthèse des niveaux de risque</h3>
    <table style="width: 100%; margin-top: 10px;">
        <tr>
            <td style="background: #ffcdd2; padding: 12px; text-align: center; border: 1px solid #ddd;">
                <strong style="color: #c62828;">Critique</strong><br/>(niveau 16+)<br/><strong style="font-size: 18pt; color: #c62828;">{risk_counts['critical']}</strong>
            </td>
            <td style="background: #ffe0b2; padding: 12px; text-align: center; border: 1px solid #ddd;">
                <strong style="color: #e65100;">Important</strong><br/>(niveau 9-15)<br/><strong style="font-size: 18pt; color: #e65100;">{risk_counts['high']}</strong>
            </td>
            <td style="background: #fff9c4; padding: 12px; text-align: center; border: 1px solid #ddd;">
                <strong style="color: #f9a825;">Modéré</strong><br/>(niveau 4-8)<br/><strong style="font-size: 18pt; color: #f9a825;">{risk_counts['medium']}</strong>
            </td>
            <td style="background: #c8e6c9; padding: 12px; text-align: center; border: 1px solid #ddd;">
                <strong style="color: #2e7d32;">Faible</strong><br/>(niveau 1-3)<br/><strong style="font-size: 18pt; color: #2e7d32;">{risk_counts['low']}</strong>
            </td>
        </tr>
    </table>
"""
        if ai_summaries.get('risk_analysis'):
            html += f"""
    <div class="summary-box">{ai_summaries['risk_analysis']}</div>
"""

        # AT6 - Actions
        if options.get('include_actions', True):
            at6 = data.get('at6', {})
            actions = at6.get('actions', [])
            if actions:
                html += """
    <div class="page-break"></div>
    <h1>AT6 - Plan de Traitement des Risques</h1>
"""
                # Synthèse
                if options.get('include_actions_summary', True):
                    html += f"""
    <h2>Vue Synthétique</h2>
    <p>Total des actions: <strong>{len(actions)}</strong></p>
    <table>
        <thead>
            <tr><th>Code</th><th>Titre</th><th>Catégorie</th><th>Priorité</th><th>Statut</th></tr>
        </thead>
        <tbody>
"""
                    for action in actions:
                        prio = action.get('priorite', 'P2')
                        prio_class = f"priority-{prio}"
                        html += f"""
            <tr>
                <td>{action.get('code_action', '')}</td>
                <td>{action.get('titre', '')}</td>
                <td>{action.get('categorie', '')}</td>
                <td class="{prio_class}">{prio}</td>
                <td>{action.get('statut', 'pending')}</td>
            </tr>
"""
                    html += """
        </tbody>
    </table>
"""

                # Détail des actions
                if options.get('include_actions_detail', True):
                    html += """
    <h2>Fiches Actions Détaillées</h2>
"""
                    for action in actions:
                        prio = action.get('priorite', 'P2')
                        html += f"""
    <div class="action-card">
        <div class="action-header">
            <span class="action-code">{action.get('code_action', '')}</span>
            <span class="priority-{prio}">{prio}</span>
        </div>
        <h3>{action.get('titre', 'Sans titre')}</h3>
        <p><strong>Catégorie:</strong> {action.get('categorie', 'N/A')}</p>
        <p><strong>Description:</strong> {action.get('description', 'N/A')}</p>
        <p><strong>Responsable suggéré:</strong> {action.get('responsable_suggere', 'Non défini')}</p>
        <p><strong>Effort estimé:</strong> {action.get('effort', 'N/A')}</p>
        <p><strong>Échéance:</strong> {action.get('echeance', 'Non définie')}</p>
    </div>
"""

        # Pied de page
        html += f"""
    <div class="page-break"></div>
    <div style="text-align: center; padding: 2cm 0; color: #666;">
        <p>Rapport généré automatiquement par Cybergard AI</p>
        <p>Méthodologie EBIOS Risk Manager - ANSSI</p>
        <p>{datetime.now().strftime('%d/%m/%Y')}</p>
    </div>
</body>
</html>
"""
        return html
