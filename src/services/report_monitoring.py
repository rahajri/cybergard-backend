"""
Service de monitoring et logging pour la génération de rapports.

Fournit :
- Métriques de performance (temps, taille, erreurs)
- Logging structuré avec contexte
- Alertes sur erreurs critiques
- Statistiques d'utilisation
"""

from typing import Dict, Any, Optional, List
from uuid import UUID
from datetime import datetime, timezone, timedelta
import logging
import time
from contextlib import contextmanager
import json
from dataclasses import dataclass, asdict
from enum import Enum

from sqlalchemy import select, func, and_, text
from sqlalchemy.orm import Session

from ..models.report import GeneratedReport, ReportGenerationJob


logger = logging.getLogger(__name__)


class ReportEventType(str, Enum):
    """Types d'événements de génération de rapport."""
    GENERATION_STARTED = "generation_started"
    DATA_COLLECTION_STARTED = "data_collection_started"
    DATA_COLLECTION_COMPLETED = "data_collection_completed"
    TEMPLATE_RENDERING_STARTED = "template_rendering_started"
    TEMPLATE_RENDERING_COMPLETED = "template_rendering_completed"
    PDF_GENERATION_STARTED = "pdf_generation_started"
    PDF_GENERATION_COMPLETED = "pdf_generation_completed"
    GENERATION_COMPLETED = "generation_completed"
    GENERATION_FAILED = "generation_failed"
    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_COMPLETED = "download_completed"


@dataclass
class ReportMetrics:
    """Métriques de génération d'un rapport."""

    campaign_id: str
    template_code: str
    template_type: str
    generation_mode: str

    # Timings (en secondes)
    data_collection_time: float = 0.0
    template_rendering_time: float = 0.0
    pdf_generation_time: float = 0.0
    total_generation_time: float = 0.0

    # Tailles
    data_size_bytes: int = 0
    html_size_bytes: int = 0
    pdf_size_bytes: int = 0

    # Compteurs
    widgets_rendered: int = 0
    charts_generated: int = 0
    pages_generated: int = 0

    # Résultat
    success: bool = False
    error_message: Optional[str] = None

    # Metadata
    timestamp: str = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour logging."""
        return asdict(self)

    def to_json(self) -> str:
        """Convertit en JSON."""
        return json.dumps(self.to_dict(), indent=2)


class ReportMonitor:
    """Service de monitoring pour génération de rapports."""

    def __init__(self, db: Session):
        self.db = db
        self.current_metrics: Optional[ReportMetrics] = None
        self._timers: Dict[str, float] = {}

    def start_generation(
        self,
        campaign_id: UUID,
        template_code: str,
        template_type: str,
        generation_mode: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> ReportMetrics:
        """
        Démarre le monitoring d'une génération.

        Returns:
            Instance de ReportMetrics pour tracking
        """
        self.current_metrics = ReportMetrics(
            campaign_id=str(campaign_id),
            template_code=template_code,
            template_type=template_type,
            generation_mode=generation_mode,
            user_id=user_id,
            tenant_id=tenant_id
        )

        self._log_event(
            ReportEventType.GENERATION_STARTED,
            {
                "campaign_id": str(campaign_id),
                "template_code": template_code,
                "mode": generation_mode
            }
        )

        self._start_timer("total")

        return self.current_metrics

    def complete_generation(
        self,
        success: bool = True,
        error_message: Optional[str] = None
    ):
        """Marque la génération comme terminée."""
        if not self.current_metrics:
            logger.warning("complete_generation called without active metrics")
            return

        self.current_metrics.total_generation_time = self._stop_timer("total")
        self.current_metrics.success = success
        self.current_metrics.error_message = error_message

        if success:
            self._log_event(
                ReportEventType.GENERATION_COMPLETED,
                self.current_metrics.to_dict()
            )

            # Log métriques de performance
            logger.info(
                f"Report generation completed",
                extra={
                    "campaign_id": self.current_metrics.campaign_id,
                    "total_time": self.current_metrics.total_generation_time,
                    "pdf_size": self.current_metrics.pdf_size_bytes,
                    "pages": self.current_metrics.pages_generated
                }
            )
        else:
            self._log_event(
                ReportEventType.GENERATION_FAILED,
                {
                    "campaign_id": self.current_metrics.campaign_id,
                    "error": error_message,
                    "metrics": self.current_metrics.to_dict()
                }
            )

            # Log erreur
            logger.error(
                f"Report generation failed: {error_message}",
                extra={"campaign_id": self.current_metrics.campaign_id}
            )

        # Persister les métriques
        self._save_metrics()

        # Reset
        self.current_metrics = None
        self._timers.clear()

    @contextmanager
    def track_phase(self, phase_name: str, event_start: ReportEventType, event_end: ReportEventType):
        """
        Context manager pour tracker une phase de génération.

        Usage:
            with monitor.track_phase("data_collection", ...):
                # ... code de collecte
        """
        self._log_event(event_start, {"phase": phase_name})
        self._start_timer(phase_name)

        try:
            yield
        finally:
            elapsed = self._stop_timer(phase_name)
            self._log_event(event_end, {"phase": phase_name, "elapsed_seconds": elapsed})

            # Mettre à jour les métriques
            if self.current_metrics:
                if phase_name == "data_collection":
                    self.current_metrics.data_collection_time = elapsed
                elif phase_name == "template_rendering":
                    self.current_metrics.template_rendering_time = elapsed
                elif phase_name == "pdf_generation":
                    self.current_metrics.pdf_generation_time = elapsed

    def record_data_size(self, data: Dict[str, Any]):
        """Enregistre la taille des données collectées."""
        if self.current_metrics:
            data_json = json.dumps(data)
            self.current_metrics.data_size_bytes = len(data_json.encode('utf-8'))

    def record_html_size(self, html: str):
        """Enregistre la taille du HTML généré."""
        if self.current_metrics:
            self.current_metrics.html_size_bytes = len(html.encode('utf-8'))

    def record_pdf_size(self, pdf_bytes: bytes):
        """Enregistre la taille du PDF généré."""
        if self.current_metrics:
            self.current_metrics.pdf_size_bytes = len(pdf_bytes)

    def record_widgets_count(self, count: int):
        """Enregistre le nombre de widgets rendus."""
        if self.current_metrics:
            self.current_metrics.widgets_rendered = count

    def record_charts_count(self, count: int):
        """Enregistre le nombre de graphiques générés."""
        if self.current_metrics:
            self.current_metrics.charts_generated = count

    def record_pages_count(self, count: int):
        """Enregistre le nombre de pages générées."""
        if self.current_metrics:
            self.current_metrics.pages_generated = count

    def _start_timer(self, name: str):
        """Démarre un timer."""
        self._timers[name] = time.time()

    def _stop_timer(self, name: str) -> float:
        """Arrête un timer et retourne le temps écoulé."""
        if name not in self._timers:
            logger.warning(f"Timer '{name}' not started")
            return 0.0

        elapsed = time.time() - self._timers[name]
        del self._timers[name]
        return elapsed

    def _log_event(self, event_type: ReportEventType, data: Dict[str, Any]):
        """Log un événement structuré."""
        logger.info(
            f"Report event: {event_type.value}",
            extra={
                "event_type": event_type.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **data
            }
        )

    def _save_metrics(self):
        """Sauvegarde les métriques dans un système de persistence."""
        if not self.current_metrics:
            return

        # TODO: Implémenter persistence des métriques
        # Options:
        # 1. Table metrics dans PostgreSQL
        # 2. Time-series DB (InfluxDB, TimescaleDB)
        # 3. Redis pour métriques récentes
        # 4. Fichier JSON pour historique

        # Pour l'instant: log JSON
        logger.info(
            "Report metrics",
            extra={"metrics": self.current_metrics.to_dict()}
        )


class ReportStatistics:
    """Service de statistiques d'utilisation des rapports."""

    def __init__(self, db: Session):
        self.db = db

    def get_generation_stats(
        self,
        tenant_id: Optional[UUID] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Statistiques de génération de rapports.

        Args:
            tenant_id: Filtrer par tenant (None = tous)
            days: Nombre de jours à analyser

        Returns:
            Dict avec statistiques
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Query de base
        query = select(
            func.count(GeneratedReport.id).label('total_reports'),
            func.count(
                func.distinct(GeneratedReport.campaign_id)
            ).label('unique_campaigns'),
            func.avg(GeneratedReport.file_size_bytes).label('avg_size'),
            func.sum(GeneratedReport.file_size_bytes).label('total_size'),
            func.avg(GeneratedReport.generation_time_ms).label('avg_time'),
            func.sum(GeneratedReport.downloaded_count).label('total_downloads')
        ).where(
            GeneratedReport.generated_at >= cutoff_date
        )

        if tenant_id:
            query = query.where(GeneratedReport.tenant_id == tenant_id)

        result = self.db.execute(query).fetchone()

        # Stats par mode de génération
        mode_stats_query = select(
            GeneratedReport.generation_mode,
            func.count(GeneratedReport.id).label('count')
        ).where(
            GeneratedReport.generated_at >= cutoff_date
        )

        if tenant_id:
            mode_stats_query = mode_stats_query.where(
                GeneratedReport.tenant_id == tenant_id
            )

        mode_stats_query = mode_stats_query.group_by(
            GeneratedReport.generation_mode
        )

        mode_results = self.db.execute(mode_stats_query).fetchall()

        # Stats par template
        template_stats_query = select(
            GeneratedReport.template_code,
            func.count(GeneratedReport.id).label('count')
        ).where(
            GeneratedReport.generated_at >= cutoff_date
        )

        if tenant_id:
            template_stats_query = template_stats_query.where(
                GeneratedReport.tenant_id == tenant_id
            )

        template_stats_query = template_stats_query.group_by(
            GeneratedReport.template_code
        ).order_by(func.count(GeneratedReport.id).desc()).limit(10)

        template_results = self.db.execute(template_stats_query).fetchall()

        return {
            'period_days': days,
            'total_reports': result.total_reports or 0,
            'unique_campaigns': result.unique_campaigns or 0,
            'avg_size_bytes': int(result.avg_size or 0),
            'total_size_bytes': int(result.total_size or 0),
            'avg_generation_time_ms': int(result.avg_time or 0),
            'total_downloads': result.total_downloads or 0,
            'by_mode': {
                row.generation_mode: row.count
                for row in mode_results
            },
            'top_templates': [
                {
                    'template_code': row.template_code,
                    'count': row.count
                }
                for row in template_results
            ]
        }

    def get_error_stats(
        self,
        tenant_id: Optional[UUID] = None,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Statistiques des erreurs de génération.

        Returns:
            Dict avec stats d'erreurs
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        query = select(
            func.count(ReportGenerationJob.id).label('total_jobs'),
            func.count(
                ReportGenerationJob.id
            ).filter(
                ReportGenerationJob.status == 'failed'
            ).label('failed_jobs'),
            func.count(
                ReportGenerationJob.id
            ).filter(
                ReportGenerationJob.status == 'completed'
            ).label('completed_jobs')
        ).where(
            ReportGenerationJob.created_at >= cutoff_date
        )

        if tenant_id:
            query = query.where(ReportGenerationJob.tenant_id == tenant_id)

        result = self.db.execute(query).fetchone()

        total = result.total_jobs or 0
        failed = result.failed_jobs or 0

        return {
            'period_days': days,
            'total_jobs': total,
            'completed_jobs': result.completed_jobs or 0,
            'failed_jobs': failed,
            'success_rate': round((total - failed) / total * 100, 1) if total > 0 else 0.0
        }

    def get_performance_trends(
        self,
        tenant_id: Optional[UUID] = None,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Tendances de performance jour par jour.

        Returns:
            Liste de stats par jour
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        # PostgreSQL: DATE_TRUNC pour grouper par jour
        query = text("""
            SELECT
                DATE_TRUNC('day', generated_at) as date,
                COUNT(*) as count,
                AVG(file_size_bytes) as avg_size,
                AVG(generation_time_ms) as avg_time,
                SUM(downloaded_count) as downloads
            FROM generated_report
            WHERE generated_at >= :cutoff_date
              AND (:tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid))
            GROUP BY DATE_TRUNC('day', generated_at)
            ORDER BY date DESC
        """)

        results = self.db.execute(
            query,
            {
                "cutoff_date": cutoff_date,
                "tenant_id": str(tenant_id) if tenant_id else None
            }
        ).fetchall()

        return [
            {
                'date': row.date.strftime('%Y-%m-%d'),
                'count': row.count,
                'avg_size_bytes': int(row.avg_size or 0),
                'avg_time_ms': int(row.avg_time or 0),
                'downloads': row.downloads or 0
            }
            for row in results
        ]


def log_report_access(
    campaign_id: UUID,
    report_id: UUID,
    user_id: str,
    action: str,
    tenant_id: Optional[UUID] = None
):
    """
    Log un accès à un rapport (génération, téléchargement, vue).

    Args:
        campaign_id: ID de la campagne
        report_id: ID du rapport
        user_id: ID de l'utilisateur
        action: Type d'action (generate, download, view)
        tenant_id: ID du tenant
    """
    logger.info(
        f"Report access: {action}",
        extra={
            "action": action,
            "campaign_id": str(campaign_id),
            "report_id": str(report_id),
            "user_id": user_id,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )
