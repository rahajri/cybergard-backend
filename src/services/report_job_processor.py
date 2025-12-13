"""
Service de traitement des jobs de génération de rapports.

Ce module traite les jobs de génération de rapports en mode synchrone
(peut être adapté pour Celery plus tard).
"""

from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from datetime import datetime, timezone
import logging
from pathlib import Path

from ..models.report import (
    ReportTemplate,
    GeneratedReport,
    ReportGenerationJob,
)
from ..schemas.report import JobStatus, ReportStatus, ReportScope, GenerationMode
from .report_service import ReportService
from .file_storage_service import FileStorageService
from .widget_renderer import WidgetRenderer
from .report_ai_summary_service import ReportAISummaryService

logger = logging.getLogger(__name__)

# Instance du service de stockage MinIO
_storage_service = None

def get_storage_service() -> FileStorageService:
    """Retourne une instance du service de stockage MinIO."""
    global _storage_service
    if _storage_service is None:
        _storage_service = FileStorageService()
    return _storage_service


class ReportJobProcessor:
    """
    Processeur de jobs de génération de rapports.

    Traite les jobs en file d'attente et génère les PDFs.
    """

    def __init__(self, db: Session):
        self.db = db
        self.report_service = ReportService(db)
        # Utiliser un chemin absolu pour éviter les problèmes de répertoire de travail
        # Le dossier storage/reports est toujours relatif au dossier backend
        backend_root = Path(__file__).resolve().parent.parent.parent  # backend/
        self.output_dir = backend_root / "storage" / "reports"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Dossier de sortie des rapports: {self.output_dir}")

    def process_job(self, job_id: UUID) -> bool:
        """
        Traite un job de génération de rapport.

        Args:
            job_id: ID du job à traiter

        Returns:
            True si succès, False sinon
        """
        job = None
        try:
            # 1. Récupérer le job
            job = self.db.execute(
                select(ReportGenerationJob).where(ReportGenerationJob.id == job_id)
            ).scalar_one_or_none()

            if not job:
                logger.error(f"❌ Job {job_id} non trouvé")
                return False

            logger.info(f"🔄 Début traitement job {job_id}")

            # 2. Marquer le job comme en cours
            job.status = JobStatus.PROCESSING.value
            job.started_at = datetime.now(timezone.utc)
            job.current_step = "Initialisation"
            job.current_step_number = 1
            job.progress_percent = 5
            self.db.commit()

            # 3. Récupérer le rapport associé
            report = self.db.execute(
                select(GeneratedReport).where(GeneratedReport.id == job.report_id)
            ).scalar_one_or_none()

            if not report:
                raise ValueError(f"Rapport {job.report_id} non trouvé")

            # 4. Récupérer le template
            template = self.db.execute(
                select(ReportTemplate).where(ReportTemplate.id == report.template_id)
            ).scalar_one_or_none()

            if not template:
                raise ValueError(f"Template {report.template_id} non trouvé")

            # 5. Collecter les données selon le scope
            self._update_job_progress(job, "Collecte des données", 2, 15)

            if report.report_scope == ReportScope.CONSOLIDATED.value:
                data = self.report_service.collect_consolidated_data(report.campaign_id)

                # IMPORTANT: Normaliser les données consolidées pour compatibilité avec les widgets
                # Les widgets attendent 'stats' et 'scores', pas 'global_stats'
                global_stats = data.get('global_stats', {})
                data['stats'] = {
                    'total_questions': global_stats.get('total_evaluations', 0),
                    'answered_questions': global_stats.get('total_evaluations', 0),
                    'compliance_rate': global_stats.get('avg_compliance_rate', 0),
                    'nc_major_count': global_stats.get('nc_critical', 0),
                    'nc_minor_count': global_stats.get('nc_minor', 0),
                    'nc_count': global_stats.get('total_nc', 0),
                    'total_domains': len(data.get('domain_comparison', [])),
                    'entities_count': global_stats.get('total_entities', 0),
                    'entities_audited': global_stats.get('entities_audited', 0),
                    'entities_at_risk': global_stats.get('entities_at_risk', 0),
                }
                data['scores'] = {
                    'global': global_stats.get('avg_compliance_rate', 0)
                }

                # Normaliser domain_scores depuis domain_comparison pour le radar
                if data.get('domain_comparison'):
                    domain_scores = []
                    for dc in data['domain_comparison']:
                        # Calculer la moyenne des scores par entité pour ce domaine
                        scores_by_entity = dc.get('scores_by_entity', {})
                        if scores_by_entity:
                            avg_score = sum(scores_by_entity.values()) / len(scores_by_entity)
                        else:
                            avg_score = 0
                        domain_scores.append({
                            'id': dc.get('domain_id'),
                            'name': dc.get('domain_name'),
                            'code': dc.get('domain_code'),
                            'score': round(avg_score, 1)
                        })
                    data['domain_scores'] = domain_scores

                # Normaliser les NC pour le tableau
                data['nc_major'] = data.get('nc_critical_all', [])
                data['nc_minor'] = []

                # Normaliser les actions
                data['actions'] = data.get('consolidated_actions', [])

                logger.info(f"✅ Données consolidées normalisées: stats={list(data['stats'].keys())}, scores={list(data['scores'].keys())}")

            elif report.report_scope == ReportScope.ENTITY.value:
                data = self.report_service.collect_entity_data(
                    report.campaign_id,
                    report.entity_id
                )

                # Normaliser nc_count pour les widgets
                stats = data.get('stats', {})
                stats['nc_count'] = stats.get('nc_major_count', 0) + stats.get('nc_minor_count', 0)
                data['stats'] = stats

                # Normaliser scores
                if 'scores' not in data:
                    data['scores'] = {'global': stats.get('compliance_rate', 0)}

                logger.info(f"✅ Données entity normalisées: stats={list(data.get('stats', {}).keys())}")

            elif report.report_scope == ReportScope.SCAN_INDIVIDUAL.value:
                # Rapport de scan individuel
                data = self.report_service.collect_scanner_data(report.scan_id)
            elif report.report_scope == ReportScope.SCAN_ECOSYSTEM.value:
                # Rapport écosystème scanner
                report_metadata = report.report_metadata or {}
                filter_entity_id = report_metadata.get('entity_id')
                data = self.report_service.collect_scan_ecosystem_data(
                    tenant_id=report.tenant_id,
                    filter_entity_id=filter_entity_id
                )

                # IMPORTANT: Normaliser les données pour compatibilité avec les templates/widgets
                # Les templates utilisent %ecosystem.xxx% avec des noms de variables standardisés
                ecosystem_data = data.get('ecosystem', {})
                total_vulns = ecosystem_data.get('total_vulnerabilities', {})

                # Ajouter les alias pour les variables du template
                ecosystem_data['entities_count'] = ecosystem_data.get('total_entities', 0)
                ecosystem_data['total_cves'] = total_vulns.get('total', 0)
                ecosystem_data['critical_cves'] = total_vulns.get('critical', 0)
                ecosystem_data['high_cves'] = total_vulns.get('high', 0)
                ecosystem_data['medium_cves'] = total_vulns.get('medium', 0)
                ecosystem_data['low_cves'] = total_vulns.get('low', 0)
                ecosystem_data['avg_cvss'] = ecosystem_data.get('avg_exposure_score', 0)
                ecosystem_data['services_count'] = ecosystem_data.get('total_services_exposed', 0)
                data['ecosystem'] = ecosystem_data

                # Créer ecosystem_comparison à partir de positioning_chart pour le widget scatter
                positioning = data.get('positioning_chart', {})
                if positioning and positioning.get('data'):
                    data['ecosystem_comparison'] = positioning.get('data', [])
                else:
                    # Fallback: créer les données depuis la liste des entités
                    entities_list = data.get('entities', [])
                    data['ecosystem_comparison'] = [
                        {
                            'entity_id': e.get('id'),
                            'entity_name': e.get('name'),
                            'total_cves': (e.get('vuln_critical', 0) + e.get('vuln_high', 0) +
                                          e.get('vuln_medium', 0) + e.get('vuln_low', 0)),
                            'cvss_avg': e.get('exposure_score', 0) / 10,  # Normaliser sur 10
                            'exposure_score': e.get('exposure_score', 0)
                        }
                        for e in entities_list
                    ]

                logger.info(f"✅ Données scan_ecosystem normalisées: ecosystem keys={list(data['ecosystem'].keys())}, ecosystem_comparison count={len(data.get('ecosystem_comparison', []))}")
            else:
                # Fallback: entity data
                data = self.report_service.collect_entity_data(
                    report.campaign_id,
                    report.entity_id
                )

            # 5b. Appliquer le logo personnalisé du template si configuré
            logger.info(f"🔍 Template logo check: default_logo='{template.default_logo}', custom_logo={'présent' if template.custom_logo else 'absent'}")
            if template.default_logo == 'CUSTOM' and template.custom_logo:
                # Le custom_logo est stocké en base64 data URI
                # Injecter dans TOUTES les sources possibles pour que le widget le trouve
                # (le widget peut être configuré pour utiliser tenant, entity, ou organization)
                if 'logos' not in data:
                    data['logos'] = {}
                data['logos']['tenant_logo_url'] = template.custom_logo
                data['logos']['entity_logo_url'] = template.custom_logo
                data['logos']['organization_logo_url'] = template.custom_logo
                data['logos']['custom_logo'] = template.custom_logo
                logger.info(f"✅ Logo personnalisé appliqué depuis le template (toutes sources, {len(template.custom_logo)} chars)")
            elif template.default_logo == 'PLATFORM':
                # Utiliser le logo de la plateforme
                if 'logos' not in data:
                    data['logos'] = {}
                data['logos']['tenant_logo_url'] = '/logo-cyberguard.png'
                logger.info(f"✅ Logo plateforme appliqué")
            elif template.default_logo == 'NONE':
                # Pas de logo
                if 'logos' not in data:
                    data['logos'] = {}
                data['logos']['tenant_logo_url'] = None
                logger.info(f"✅ Aucun logo configuré")
            # Si TENANT (défaut), on garde le logo du tenant déjà récupéré

            # 6. Ajouter les métadonnées du rapport
            data['report'] = {
                'id': str(report.id),
                'title': report.title,
                'description': report.description,
                'scope': report.report_scope,
                'generated_at': datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M'),
                'mode': report.generation_mode
            }

            # 6b. Générer les contenus IA si demandé
            self._update_job_progress(job, "Génération des contenus IA", 3, 25)

            # Récupérer les options depuis report_metadata (stockées lors de la création du rapport)
            report_metadata = report.report_metadata or {}
            job_options = report_metadata.get('options', {})
            include_ai_summary = job_options.get('include_ai_summary', True)
            ai_widget_configs = job_options.get('ai_widget_configs', [])

            logger.info(f"📋 Options rapport: include_ai_summary={include_ai_summary}, ai_widget_configs count={len(ai_widget_configs)}")

            if include_ai_summary:
                data = self._generate_ai_contents(
                    data=data,
                    report=report,
                    template=template,
                    ai_widget_configs=ai_widget_configs
                )

            # 7. Générer le HTML
            self._update_job_progress(job, "Génération du HTML", 4, 40)

            # Pour l'instant, générer un HTML simple
            html_content = self._generate_simple_html(data, template, report)

            # 8. Convertir en PDF
            self._update_job_progress(job, "Conversion en PDF", 4, 50)

            pdf_result = self._generate_pdf(html_content, report)

            # 9. Mettre à jour le rapport
            self._update_job_progress(job, "Finalisation", 5, 80)

            report.status = ReportStatus.DRAFT.value if report.generation_mode == GenerationMode.DRAFT.value else ReportStatus.FINAL.value
            report.file_path = pdf_result.get('file_path')
            report.file_name = pdf_result.get('file_name')
            report.file_size_bytes = pdf_result.get('file_size_bytes')
            report.file_checksum = pdf_result.get('file_checksum')
            report.page_count = pdf_result.get('page_count')
            report.generation_time_ms = pdf_result.get('generation_time_ms')
            report.generated_at = datetime.now(timezone.utc)

            # 9b. Sauvegarder les données générées (notamment ai_contents) pour le preview
            # Extraire uniquement les ai_contents pour éviter de stocker trop de données
            if data.get('ai_contents'):
                report_data = report.report_data or {}
                report_data['ai_contents'] = data.get('ai_contents', {})
                report.report_data = report_data
                logger.info(f"💾 ai_contents sauvegardé dans report_data: {list(data['ai_contents'].keys())}")

            # 10. Marquer le job comme terminé
            job.status = JobStatus.COMPLETED.value
            job.completed_at = datetime.now(timezone.utc)
            job.progress_percent = 100
            job.current_step = "Terminé"

            self.db.commit()

            logger.info(f"✅ Job {job_id} terminé avec succès - PDF: {report.file_name}")
            return True

        except Exception as e:
            logger.error(f"❌ Erreur traitement job {job_id}: {str(e)}", exc_info=True)

            # Marquer le job comme échoué
            if job:
                job.status = JobStatus.FAILED.value
                job.error_message = str(e)
                job.completed_at = datetime.now(timezone.utc)

                # Marquer le rapport comme erreur
                if job.report_id:
                    report = self.db.execute(
                        select(GeneratedReport).where(GeneratedReport.id == job.report_id)
                    ).scalar_one_or_none()
                    if report:
                        report.status = ReportStatus.ERROR.value
                        report.error_message = str(e)

                self.db.commit()

            return False

    def _update_job_progress(
        self,
        job: ReportGenerationJob,
        step_name: str,
        step_number: int,
        progress: int
    ):
        """Met à jour la progression du job."""
        job.current_step = step_name
        job.current_step_number = step_number
        job.progress_percent = progress
        self.db.commit()
        logger.info(f"📊 Job {job.id}: {step_name} ({progress}%)")

    def _generate_ai_contents(
        self,
        data: Dict[str, Any],
        report: GeneratedReport,
        template: ReportTemplate,
        ai_widget_configs: list
    ) -> Dict[str, Any]:
        """
        Génère les contenus IA pour les widgets ai_summary du template.

        Args:
            data: Données collectées du rapport
            report: Rapport en cours de génération
            template: Template utilisé
            ai_widget_configs: Configurations des widgets IA (depuis le frontend)
                [{"widget_id": "...", "use_ai": true/false, "manual_content": "...", "tone": "..."}]

        Returns:
            data enrichi avec les contenus IA générés
        """
        try:
            # Récupérer la structure du template
            structure = template.structure or []
            if isinstance(structure, str):
                import json
                structure = json.loads(structure)

            # Trouver les widgets de type ai_summary ou summary
            ai_widgets = [w for w in structure if w.get('widget_type') in ['ai_summary', 'summary']]

            if not ai_widgets:
                logger.info("ℹ️ Aucun widget IA dans le template")
                return data

            logger.info(f"🤖 {len(ai_widgets)} widget(s) IA à traiter")

            # Créer un dictionnaire des configs par widget_id pour accès rapide
            configs_by_id = {c.get('widget_id'): c for c in ai_widget_configs}

            # Initialiser le service IA
            ai_service = ReportAISummaryService(self.db)

            # Initialiser la structure pour stocker les contenus IA
            if 'ai_contents' not in data:
                data['ai_contents'] = {}

            for widget in ai_widgets:
                # Utiliser widget_key OU id comme identifiant unique
                widget_id = widget.get('id') or widget.get('widget_key') or ''
                widget_config = widget.get('config', {})
                widget_title = widget_config.get('title', 'Résumé IA')

                # Récupérer la config spécifique depuis le frontend (si fournie)
                user_config = configs_by_id.get(widget_id, {})

                # Déterminer si on utilise l'IA ou le contenu manuel
                use_ai = user_config.get('use_ai', widget_config.get('use_ai', True))
                manual_content = user_config.get('manual_content', widget_config.get('manual_content', ''))
                tone = user_config.get('tone', widget_config.get('tone', 'executive'))

                logger.info(f"📝 Widget '{widget_title}' (id={widget_id[:8] if widget_id else 'N/A'}): use_ai={use_ai}, tone={tone}")

                if not use_ai and manual_content.strip():
                    # Utiliser le contenu manuel
                    logger.info(f"  → Utilisation du contenu manuel ({len(manual_content)} chars)")
                    data['ai_contents'][widget_id] = {
                        'text': manual_content,
                        'source': 'manual',
                        'tone': tone
                    }
                elif use_ai:
                    # Générer via l'IA
                    try:
                        logger.info(f"  → Génération IA en cours (tone={tone})...")
                        logger.info(f"  🔍 DEBUG: report.campaign_id={report.campaign_id}, report.entity_id={report.entity_id}, report.tenant_id={report.tenant_id}")

                        # Utiliser les versions synchrones des méthodes
                        if report.report_scope == ReportScope.CONSOLIDATED.value:
                            ai_result = ai_service.generate_campaign_summary_sync(
                                campaign_id=report.campaign_id,
                                tenant_id=report.tenant_id,
                                tone=tone
                            )
                        else:
                            ai_result = ai_service.generate_entity_summary_sync(
                                campaign_id=report.campaign_id,
                                entity_id=report.entity_id,
                                tenant_id=report.tenant_id,
                                tone=tone
                            )

                        # Le résultat contient executive_summary
                        generated_text = ai_result.get('executive_summary', '')
                        if generated_text:
                            logger.info(f"  ✅ Contenu IA généré ({len(generated_text)} chars)")
                            data['ai_contents'][widget_id] = {
                                'text': generated_text,
                                'source': 'ai',
                                'tone': tone,
                                'model': 'deepseek'
                            }
                        else:
                            # Fallback si pas de contenu généré
                            logger.warning(f"  ⚠️ Contenu IA vide")
                            data['ai_contents'][widget_id] = {
                                'text': "[Résumé IA non disponible - contenu vide]",
                                'source': 'fallback',
                                'tone': tone
                            }

                    except Exception as e:
                        logger.error(f"  ❌ Erreur génération IA: {str(e)}")
                        data['ai_contents'][widget_id] = {
                            'text': f"[Erreur lors de la génération IA: {str(e)}]",
                            'source': 'error',
                            'tone': tone,
                            'error': str(e)
                        }
                else:
                    # Ni IA ni contenu manuel - placeholder
                    logger.info(f"  → Aucun contenu (IA désactivée, pas de contenu manuel)")
                    data['ai_contents'][widget_id] = {
                        'text': '',
                        'source': 'none',
                        'tone': tone
                    }

            # Stocker aussi un résumé global (pour compatibilité avec l'ancien format)
            # Utiliser le premier contenu IA généré
            for widget_id, content in data['ai_contents'].items():
                if content.get('source') in ['ai', 'manual'] and content.get('text'):
                    data['ai_summary'] = content
                    logger.info(f"📦 ai_summary global défini depuis widget_id={widget_id[:8]}, text len={len(content.get('text', ''))}")
                    break

            # Log final pour debug
            logger.info(f"📊 _generate_ai_contents terminé: ai_contents keys={list(data.get('ai_contents', {}).keys())}")
            logger.info(f"📊 _generate_ai_contents terminé: ai_summary présent={bool(data.get('ai_summary'))}, text len={len(data.get('ai_summary', {}).get('text', ''))}")

            return data

        except Exception as e:
            logger.error(f"❌ Erreur génération contenus IA: {str(e)}", exc_info=True)
            # Ne pas faire échouer tout le rapport si l'IA échoue
            return data

    def _generate_simple_html(
        self,
        data: Dict[str, Any],
        template: ReportTemplate,
        report: GeneratedReport
    ) -> str:
        """
        Génère le HTML du rapport en utilisant le WidgetRenderer.

        Utilise la structure du template pour rendre chaque widget.
        """
        # Récupérer les couleurs et polices du template
        color_scheme = template.color_scheme or {
            'primary': '#8B5CF6',
            'secondary': '#3B82F6',
            'accent': '#10B981',
            'danger': '#EF4444',
            'warning': '#F59E0B',
            'success': '#22C55E',
            'text': '#1F2937',
            'background': '#FFFFFF'
        }

        # IMPORTANT: xhtml2pdf ne supporte que les polices standard (Helvetica, Arial, Times, Courier)
        # Les polices comme "Noto Sans JP" ne sont pas rendues et causent des pages blanches
        # On force donc l'utilisation de polices compatibles
        XHTML2PDF_SAFE_FONT = 'Helvetica, Arial, sans-serif'

        fonts = template.fonts or {}
        # Forcer les polices compatibles xhtml2pdf
        fonts = {
            'title': {'family': XHTML2PDF_SAFE_FONT, 'size': fonts.get('title', {}).get('size', 24), 'weight': 'bold'},
            'heading1': {'family': XHTML2PDF_SAFE_FONT, 'size': fonts.get('heading1', {}).get('size', 18), 'weight': 'bold'},
            'heading2': {'family': XHTML2PDF_SAFE_FONT, 'size': fonts.get('heading2', {}).get('size', 14), 'weight': 'bold'},
            'heading3': {'family': XHTML2PDF_SAFE_FONT, 'size': fonts.get('heading3', {}).get('size', 12), 'weight': 'bold'},
            'body': {'family': XHTML2PDF_SAFE_FONT, 'size': fonts.get('body', {}).get('size', 10), 'weight': 'normal'}
        }

        logger.info(f"📝 Polices forcées pour xhtml2pdf: {XHTML2PDF_SAFE_FONT}")

        # Créer le renderer
        renderer = WidgetRenderer(color_scheme, fonts)

        # Récupérer la structure du template
        structure = template.structure or []
        if isinstance(structure, str):
            import json
            structure = json.loads(structure)

        # Log état des données IA avant rendu
        logger.info(f"🎨 _generate_simple_html: ai_contents keys={list(data.get('ai_contents', {}).keys())}")
        logger.info(f"🎨 _generate_simple_html: ai_summary présent={bool(data.get('ai_summary'))}, text len={len(data.get('ai_summary', {}).get('text', ''))}")

        # Passer la structure du template dans data pour que render_toc puisse générer la TOC
        data['_template_structure'] = structure

        # Générer le HTML de chaque widget
        widgets_html = []
        for widget in sorted(structure, key=lambda w: w.get('position', 0)):
            widget_type = widget.get('widget_type', '')
            config = widget.get('config', {}).copy()  # Copie pour ne pas modifier l'original

            # Ajouter l'ID du widget au config pour que render_widget puisse l'utiliser
            # (nécessaire pour les widgets IA qui doivent récupérer leur contenu dans data['ai_contents'])
            # Note: les templates utilisent 'widget_key' ou 'id' comme identifiant unique
            widget_id = widget.get('id') or widget.get('widget_key') or ''
            if widget_id:
                config['id'] = widget_id

            # Log spécial pour widgets ai_summary
            if widget_type in ['ai_summary', 'summary']:
                logger.info(f"🤖 Rendu widget IA: type={widget_type}, id={widget_id[:20] if widget_id else 'VIDE'}")

            try:
                html = renderer.render_widget(widget_type, config, data)
                widgets_html.append(html)
            except Exception as e:
                logger.warning(f"Erreur rendu widget {widget_type}: {e}")
                widgets_html.append(f"<!-- Erreur widget {widget_type}: {e} -->")

        # Assembler le HTML final
        primary_color = color_scheme.get('primary', '#8B5CF6')

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
                    font-family: {fonts['body']['family']};
                    font-size: {fonts['body']['size']}px;
                    line-height: 1.6;
                    color: {color_scheme['text']};
                    margin: 0;
                    padding: 0;
                    background: {color_scheme['background']};
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
            </style>
        </head>
        <body>
            {''.join(widgets_html)}
        </body>
        </html>
        """

        return html

    def _generate_consolidated_html(
        self,
        data: Dict[str, Any],
        template: ReportTemplate,
        report: GeneratedReport,
        primary_color: str
    ) -> str:
        """Génère le HTML pour un rapport consolidé."""
        campaign = data.get('campaign', {})
        global_stats = data.get('global_stats', {})
        entities = data.get('entities', [])
        entity_scores = data.get('entity_scores', [])
        nc_critical = data.get('nc_critical_all', [])

        # Calculer les stats
        total_entities = len(entities)
        avg_score = global_stats.get('avg_compliance_rate', 0)
        total_nc = global_stats.get('total_nc', 0)

        # Générer la liste des entités
        entities_html = ""
        for entity in entity_scores:
            risk_color = {
                'high': '#ef4444',
                'medium': '#f59e0b',
                'low': '#22c55e'
            }.get(entity.get('risk_level', 'low'), '#22c55e')

            entities_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{entity.get('name', 'N/A')}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center;">{entity.get('score', 0):.1f}%</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center;">{entity.get('nc_count', 0)}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center;">
                    <span style="padding: 4px 8px; border-radius: 4px; background-color: {risk_color}; color: white; font-size: 12px;">
                        {entity.get('risk_level', 'N/A').upper()}
                    </span>
                </td>
            </tr>
            """

        # Générer la liste des NC critiques
        nc_html = ""
        for nc in nc_critical[:10]:
            nc_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{nc.get('domain_code', 'N/A')}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{nc.get('question_text', 'N/A')[:100]}...</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center;">{nc.get('entity_count', 0)}</td>
            </tr>
            """

        html = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <style>
                @page {{
                    size: A4;
                    margin: 20mm;
                }}
                body {{
                    font-family: 'Helvetica', 'Arial', sans-serif;
                    line-height: 1.6;
                    color: #1f2937;
                    margin: 0;
                    padding: 0;
                }}
                .header {{
                    background-color: {primary_color};
                    color: white;
                    padding: 40px;
                    margin: -20mm -20mm 30px -20mm;
                }}
                .header h1 {{
                    margin: 0 0 10px 0;
                    font-size: 32px;
                }}
                .header p {{
                    margin: 0;
                }}
                .stats-grid {{
                    margin-bottom: 30px;
                }}
                .stat-card {{
                    background-color: #f9fafb;
                    padding: 20px;
                    text-align: center;
                    display: inline-block;
                    width: 22%;
                    margin-right: 2%;
                    vertical-align: top;
                }}
                .stat-value {{
                    font-size: 36px;
                    font-weight: bold;
                    color: {primary_color};
                }}
                .stat-label {{
                    font-size: 14px;
                    color: #6b7280;
                    margin-top: 5px;
                }}
                .section {{
                    margin-bottom: 30px;
                }}
                .section-title {{
                    font-size: 20px;
                    color: {primary_color};
                    border-bottom: 2px solid {primary_color};
                    padding-bottom: 10px;
                    margin-bottom: 20px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                th {{
                    background: #f3f4f6;
                    padding: 12px;
                    text-align: left;
                    font-weight: 600;
                }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid #e5e7eb;
                    font-size: 12px;
                    color: #9ca3af;
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🌐 {report.title}</h1>
                <p>Rapport consolidé - {campaign.get('name', 'Campagne')}</p>
                <p style="margin-top: 10px; font-size: 14px;">
                    Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}
                </p>
            </div>

            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value">{total_entities}</div>
                    <div class="stat-label">Organismes audités</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{avg_score:.1f}%</div>
                    <div class="stat-label">Score moyen</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{total_nc}</div>
                    <div class="stat-label">Non-conformités</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{global_stats.get('nc_critical', 0)}</div>
                    <div class="stat-label">NC Critiques</div>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">📊 Classement des Organismes</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Organisme</th>
                            <th style="text-align: center;">Score</th>
                            <th style="text-align: center;">NC</th>
                            <th style="text-align: center;">Risque</th>
                        </tr>
                    </thead>
                    <tbody>
                        {entities_html if entities_html else '<tr><td colspan="4" style="text-align: center; padding: 20px; color: #9ca3af;">Aucun organisme</td></tr>'}
                    </tbody>
                </table>
            </div>

            <div class="section" style="page-break-before: always;">
                <h2 class="section-title">🔴 Non-Conformités Critiques Transverses</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Domaine</th>
                            <th>Question</th>
                            <th style="text-align: center;">Entités concernées</th>
                        </tr>
                    </thead>
                    <tbody>
                        {nc_html if nc_html else '<tr><td colspan="3" style="text-align: center; padding: 20px; color: #9ca3af;">Aucune non-conformité critique</td></tr>'}
                    </tbody>
                </table>
            </div>

            <div class="footer">
                <p>Rapport généré par Cybergard AI - Plateforme d'Audit de Cybersécurité</p>
                <p>Ce document est confidentiel</p>
            </div>
        </body>
        </html>
        """

        return html

    def _generate_entity_html(
        self,
        data: Dict[str, Any],
        template: ReportTemplate,
        report: GeneratedReport,
        primary_color: str
    ) -> str:
        """Génère le HTML pour un rapport individuel."""
        campaign = data.get('campaign', {})
        entity = data.get('entity', {})
        stats = data.get('stats', {})
        domain_scores = data.get('domain_scores', [])
        nc_list = data.get('nc_list', [])
        actions_list = data.get('actions', [])
        benchmarking = data.get('benchmarking', {})
        strengths = data.get('strengths', [])
        improvements = data.get('improvements', [])

        # Générer les domaines
        domains_html = ""
        for domain in domain_scores:
            score = domain.get('score', 0)
            status_color = '#22c55e' if score >= 80 else ('#f59e0b' if score >= 50 else '#ef4444')
            domains_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{domain.get('name', 'N/A')}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td width="80%">
                                <div style="background-color: #e5e7eb; height: 8px;">
                                    <div style="width: {score}%; background-color: {status_color}; height: 8px;"></div>
                                </div>
                            </td>
                            <td width="20%" style="text-align: right; padding-left: 10px;">
                                <span style="font-weight: 600; color: {status_color};">{score:.1f}%</span>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            """

        # Générer les NC
        nc_html = ""
        for nc in nc_list:
            severity_color = '#ef4444' if nc.get('severity_class') == 'critical' else '#f59e0b'
            nc_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                    <span style="padding: 4px 8px; border-radius: 4px; background-color: {severity_color}; color: white; font-size: 12px;">
                        {nc.get('severity', 'N/A')}
                    </span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{nc.get('domain_name', 'N/A')}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">{nc.get('question_text', 'N/A')[:80]}...</td>
            </tr>
            """

        # Générer les Actions
        actions_html = ""
        for action in actions_list:
            # Couleurs par sévérité
            severity = action.get('severity', 'info')
            severity_colors = {
                'critical': '#ef4444',
                'major': '#f97316',
                'minor': '#f59e0b',
                'info': '#3b82f6'
            }
            severity_labels = {
                'critical': 'CRITIQUE',
                'major': 'MAJEUR',
                'minor': 'MINEUR',
                'info': 'INFO'
            }
            severity_color = severity_colors.get(severity, '#6b7280')
            severity_label = severity_labels.get(severity, severity.upper())

            # Couleurs par priorité
            priority = action.get('priority', 'P3')
            priority_colors = {
                'P1': '#ef4444',
                'P2': '#f59e0b',
                'P3': '#22c55e'
            }
            priority_color = priority_colors.get(priority, '#6b7280')

            actions_html += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                    <span style="padding: 4px 8px; border-radius: 4px; background-color: {severity_color}; color: white; font-size: 11px; font-weight: 600;">
                        {severity_label}
                    </span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                    <span style="padding: 4px 8px; border-radius: 4px; background-color: {priority_color}; color: white; font-size: 11px; font-weight: 600;">
                        {priority}
                    </span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; font-weight: 500;">{action.get('title', 'N/A')[:60]}...</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; font-size: 13px; color: #6b7280;">{action.get('suggested_role', 'N/A')}</td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center;">{action.get('recommended_due_days', 'N/A')} jours</td>
            </tr>
            """

        # Pré-calculer les valeurs complexes pour éviter les erreurs f-string
        strengths_display = ', '.join([s.get('domain', 'N/A') for s in strengths[:3]]) if strengths else 'Aucun domaine >= 80%'
        improvements_display = ', '.join([i.get('domain', 'N/A') for i in improvements[:3]]) if improvements else 'Tous les domaines >= 70%'
        benchmark_color = '#22c55e' if benchmarking.get('difference_vs_avg', 0) >= 0 else '#ef4444'
        benchmark_sign = '+' if benchmarking.get('difference_vs_avg', 0) >= 0 else ''
        benchmark_value = benchmarking.get('difference_vs_avg', 0)

        html = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <style>
                @page {{
                    size: A4;
                    margin: 20mm;
                }}
                body {{
                    font-family: 'Helvetica', 'Arial', sans-serif;
                    line-height: 1.6;
                    color: #1f2937;
                    margin: 0;
                    padding: 0;
                }}
                .header {{
                    background-color: {primary_color};
                    color: white;
                    padding: 40px;
                    margin: -20mm -20mm 30px -20mm;
                }}
                .header h1 {{
                    margin: 0 0 10px 0;
                    font-size: 28px;
                }}
                .header p {{
                    margin: 0;
                }}
                .score-hero {{
                    text-align: center;
                    padding: 30px;
                    background-color: #f3f4f6;
                    margin-bottom: 30px;
                }}
                .score-value {{
                    font-size: 72px;
                    font-weight: bold;
                    color: {primary_color};
                }}
                .maturity-badge {{
                    display: inline-block;
                    padding: 8px 16px;
                    background-color: {primary_color};
                    color: white;
                    margin-top: 10px;
                }}
                .benchmark-info {{
                    text-align: center;
                    margin-top: 20px;
                }}
                .benchmark-item {{
                    display: inline-block;
                    text-align: center;
                    margin: 0 15px;
                }}
                .benchmark-value {{
                    font-size: 24px;
                    font-weight: bold;
                }}
                .benchmark-label {{
                    font-size: 12px;
                    color: #6b7280;
                }}
                .section {{
                    margin-bottom: 30px;
                }}
                .section-title {{
                    font-size: 20px;
                    color: {primary_color};
                    border-bottom: 2px solid {primary_color};
                    padding-bottom: 10px;
                    margin-bottom: 20px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                th {{
                    background-color: #f3f4f6;
                    padding: 12px;
                    text-align: left;
                    font-weight: 600;
                }}
                .highlights {{
                    margin-bottom: 30px;
                }}
                .highlight-card {{
                    display: inline-block;
                    width: 48%;
                    padding: 20px;
                    vertical-align: top;
                    margin-right: 2%;
                }}
                .highlight-strengths {{
                    background-color: #dcfce7;
                    border: 1px solid #22c55e;
                }}
                .highlight-improvements {{
                    background-color: #fef3c7;
                    border: 1px solid #f59e0b;
                }}
                .highlight-title {{
                    font-weight: 600;
                    margin-bottom: 10px;
                }}
                .highlight-list {{
                    font-size: 14px;
                }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid #e5e7eb;
                    font-size: 12px;
                    color: #9ca3af;
                    text-align: center;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🏢 {report.title}</h1>
                <p><strong>{entity.get('name', 'Entité')}</strong></p>
                <p style="margin-top: 5px;">Campagne: {campaign.get('name', 'N/A')}</p>
                <p style="margin-top: 10px; font-size: 14px;">
                    Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}
                </p>
            </div>

            <div class="score-hero">
                <div class="score-value">{stats.get('compliance_rate', 0):.1f}%</div>
                <div>Score de conformité</div>
                <div class="maturity-badge">{stats.get('maturity_level', 'Non évalué')}</div>

                <div class="benchmark-info">
                    <div class="benchmark-item">
                        <div class="benchmark-value">{benchmarking.get('rank', 'N/A')}/{benchmarking.get('total_entities', 'N/A')}</div>
                        <div class="benchmark-label">Classement</div>
                    </div>
                    <div class="benchmark-item">
                        <div class="benchmark-value">{benchmarking.get('campaign_avg', 0):.1f}%</div>
                        <div class="benchmark-label">Moyenne campagne</div>
                    </div>
                    <div class="benchmark-item">
                        <div class="benchmark-value" style="color: {benchmark_color}">
                            {benchmark_sign}{benchmark_value:.1f}%
                        </div>
                        <div class="benchmark-label">vs moyenne</div>
                    </div>
                </div>
            </div>

            <div class="highlights">
                <div class="highlight-card highlight-strengths">
                    <div class="highlight-title">✅ Points forts</div>
                    <div class="highlight-list">
                        {strengths_display}
                    </div>
                </div>
                <div class="highlight-card highlight-improvements">
                    <div class="highlight-title">⚠️ Axes d'amélioration</div>
                    <div class="highlight-list">
                        {improvements_display}
                    </div>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">📊 Scores par Domaine</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Domaine</th>
                            <th>Score</th>
                        </tr>
                    </thead>
                    <tbody>
                        {domains_html if domains_html else '<tr><td colspan="2" style="text-align: center; padding: 20px; color: #9ca3af;">Aucun domaine évalué</td></tr>'}
                    </tbody>
                </table>
            </div>

            <div class="section" style="page-break-before: always;">
                <h2 class="section-title">🔴 Non-Conformités Identifiées ({len(nc_list)})</h2>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 100px;">Sévérité</th>
                            <th style="width: 150px;">Domaine</th>
                            <th>Question</th>
                        </tr>
                    </thead>
                    <tbody>
                        {nc_html if nc_html else '<tr><td colspan="3" style="text-align: center; padding: 20px; color: #22c55e;">Aucune non-conformité 🎉</td></tr>'}
                    </tbody>
                </table>
            </div>

            <div class="section" style="page-break-before: always;">
                <h2 class="section-title">📋 Plan d'Actions ({len(actions_list)})</h2>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 90px;">Sévérité</th>
                            <th style="width: 70px;">Priorité</th>
                            <th>Action</th>
                            <th style="width: 120px;">Responsable</th>
                            <th style="width: 80px; text-align: center;">Délai</th>
                        </tr>
                    </thead>
                    <tbody>
                        {actions_html if actions_html else '<tr><td colspan="5" style="text-align: center; padding: 20px; color: #9ca3af;">Aucune action définie</td></tr>'}
                    </tbody>
                </table>
            </div>

            <div class="footer">
                <p>Rapport généré par Cybergard AI - Plateforme d'Audit de Cybersécurité</p>
                <p>Ce document est confidentiel et destiné exclusivement à {entity.get('name', 'cette entité')}</p>
            </div>
        </body>
        </html>
        """

        return html

    def _generate_pdf(self, html_content: str, report: GeneratedReport) -> Dict[str, Any]:
        """
        Génère le fichier PDF à partir du HTML et le stocke dans MinIO.

        Utilise xhtml2pdf (compatible Windows/Linux, pas de dépendances GTK).
        IMPORTANT: xhtml2pdf ne supporte pas CSS3 (flexbox, gradients) - utiliser tables et couleurs solides.

        Le fichier est stocké dans MinIO dans le dossier Rapports de la campagne.
        """
        from datetime import datetime
        import hashlib
        from io import BytesIO

        start_time = datetime.now()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_bytes = None
        filename = None
        content_type = None

        # DEBUG: Sauvegarder le HTML pour inspection
        debug_html_path = self.output_dir / f"debug_{report.id}_{timestamp}.html"
        with open(debug_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"🔍 HTML debug sauvegardé: {debug_html_path} ({len(html_content)} chars)")

        # Méthode principale: xhtml2pdf (même approche que EBIOS)
        try:
            from xhtml2pdf import pisa

            filename = f"rapport_{report.id}_{timestamp}.pdf"
            content_type = "application/pdf"

            # Convertir HTML en PDF avec xhtml2pdf
            pdf_buffer = BytesIO()
            pisa_status = pisa.CreatePDF(
                html_content,
                dest=pdf_buffer,
                encoding='utf-8'
            )

            if pisa_status.err:
                logger.error(f"❌ Erreur xhtml2pdf: {pisa_status.err} erreur(s)")
                raise Exception(f"xhtml2pdf a rencontré {pisa_status.err} erreur(s)")

            pdf_bytes = pdf_buffer.getvalue()
            logger.info(f"✅ PDF généré avec xhtml2pdf: {filename} ({len(pdf_bytes)} bytes)")

        except ImportError:
            logger.warning("⚠️ xhtml2pdf non installé. Installation: pip install xhtml2pdf")
        except Exception as xhtml2pdf_error:
            logger.error(f"❌ Erreur xhtml2pdf: {xhtml2pdf_error}")

        # Fallback: générer en HTML si xhtml2pdf n'a pas fonctionné
        if pdf_bytes is None:
            logger.warning("⚠️ Génération PDF impossible, fallback vers HTML")
            filename = f"rapport_{report.id}_{timestamp}.html"
            content_type = "text/html"
            pdf_bytes = html_content.encode('utf-8')

        # Calculer les métadonnées
        file_checksum = hashlib.sha256(pdf_bytes).hexdigest()
        file_size = len(pdf_bytes)
        page_count = html_content.count('page-break') + 2

        # Sauvegarder localement en backup
        local_path = self.output_dir / filename
        with open(local_path, 'wb') as f:
            f.write(pdf_bytes)

        # Stocker dans MinIO (dossier Rapports de la campagne)
        try:
            storage = get_storage_service()

            # Déterminer le type de rapport pour le chemin MinIO
            report_type = "consolidated" if report.report_scope == ReportScope.CONSOLIDATED.value else "entity"

            # Version du rapport
            version = f"v{report.version}" if report.version else None

            # Upload vers MinIO
            file_stream = BytesIO(pdf_bytes)
            minio_path, minio_checksum, minio_size = storage.upload_report(
                file_data=file_stream,
                filename=filename,
                tenant_id=report.tenant_id,
                campaign_id=report.campaign_id,
                report_type=report_type,
                version=version,
                content_type=content_type,
                metadata={
                    "report-id": str(report.id),
                    "report-title": report.title,
                    "report-scope": report.report_scope,
                    "generation-mode": report.generation_mode,
                    "entity-id": str(report.entity_id) if report.entity_id else "",
                }
            )

            logger.info(f"✅ Rapport stocké dans MinIO: {minio_path}")

            # Utiliser le chemin MinIO comme chemin principal
            final_path = minio_path

        except Exception as e:
            logger.warning(f"⚠️ Erreur stockage MinIO, utilisation du chemin local: {e}")
            final_path = str(local_path)

        generation_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        return {
            'file_path': final_path,
            'file_name': filename,
            'file_size_bytes': file_size,
            'file_checksum': file_checksum,
            'page_count': page_count,
            'generation_time_ms': generation_time_ms
        }


def process_pending_jobs(db: Session, limit: int = 10) -> int:
    """
    Traite les jobs en attente.

    Args:
        db: Session de base de données
        limit: Nombre maximum de jobs à traiter

    Returns:
        Nombre de jobs traités avec succès
    """
    processor = ReportJobProcessor(db)

    # Récupérer les jobs en attente
    pending_jobs = db.execute(
        select(ReportGenerationJob)
        .where(ReportGenerationJob.status == JobStatus.QUEUED.value)
        .order_by(ReportGenerationJob.queued_at)
        .limit(limit)
    ).scalars().all()

    success_count = 0
    for job in pending_jobs:
        if processor.process_job(job.id):
            success_count += 1

    return success_count
