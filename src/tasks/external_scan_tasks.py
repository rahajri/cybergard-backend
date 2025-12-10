# backend/src/tasks/external_scan_tasks.py
"""
Tâches Celery pour le scan externe.

Tâches:
- scan_external_target_task: Exécute un scan complet sur une cible
- generate_scan_report_task: Génère un rapport IA pour un scan
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional

from celery import shared_task
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database import SessionLocal
from src.services.external_scanner.engine import ScanEngine, ScanConfig, ScanResult
from src.models.external_scan import (
    ExternalTarget,
    ExternalScan,
    ExternalServiceVulnerability,
    ScanExecutionStatus,
    ScanStatus,
    SeverityLevel,
    VulnerabilityType
)

logger = logging.getLogger(__name__)


def get_db_session() -> Session:
    """Crée une session de base de données."""
    return SessionLocal()


@shared_task(
    bind=True,
    name="src.tasks.external_scan_tasks.scan_external_target_task",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=600,
    time_limit=900
)
def scan_external_target_task(
    self,
    target_id: str,
    scan_id: str,
    triggered_by: Optional[str] = None
) -> dict:
    """
    Tâche Celery pour scanner une cible externe.

    Args:
        target_id: UUID de la cible (ExternalTarget.id)
        scan_id: UUID du scan (ExternalScan.id)
        triggered_by: UUID de l'utilisateur qui a déclenché le scan

    Returns:
        Dictionnaire avec le résumé du scan
    """
    logger.info(f"🚀 Démarrage tâche scan: target={target_id}, scan={scan_id}")

    db = get_db_session()

    try:
        # Récupérer la cible
        target_query = text("""
            SELECT id, tenant_id, type, value, label
            FROM external_target
            WHERE id = CAST(:target_id AS uuid)
            AND deleted_at IS NULL
        """)
        target_result = db.execute(
            target_query,
            {"target_id": target_id}
        ).fetchone()

        if not target_result:
            logger.error(f"❌ Cible non trouvée: {target_id}")
            _update_scan_status(db, scan_id, ScanExecutionStatus.ERROR, "Cible non trouvée")
            return {"error": "Cible non trouvée"}

        target_type = target_result.type
        target_value = target_result.value
        tenant_id = str(target_result.tenant_id)

        # Mettre à jour le statut du scan à RUNNING
        _update_scan_status(db, scan_id, ScanExecutionStatus.RUNNING)

        # Exécuter le scan de manière asynchrone
        logger.info(f"📡 Scan en cours: {target_type} -> {target_value}")

        # Créer une boucle d'événements pour exécuter le scan async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            config = ScanConfig(
                nmap_timeout=300,
                tls_timeout=60,
                enable_tls_audit=True,
                enable_cve_enrichment=True
            )
            engine = ScanEngine(config)

            scan_result: ScanResult = loop.run_until_complete(
                engine.run_scan(
                    target_type=target_type,
                    target_value=target_value,
                    target_id=UUID(target_id),
                    scan_id=UUID(scan_id)
                )
            )
        finally:
            loop.close()

        # Persister les résultats
        if scan_result.status == "SUCCESS":
            # Sauvegarder les vulnérabilités
            _save_vulnerabilities(
                db,
                scan_id=scan_id,
                tenant_id=tenant_id,
                vulnerabilities=scan_result.vulnerabilities
            )

            # Mettre à jour le résumé du scan
            summary = scan_result.summary
            summary["scan_duration_seconds"] = scan_result.scan_duration_seconds

            _update_scan_success(
                db,
                scan_id=scan_id,
                summary=summary,
                started_at=scan_result.started_at,
                finished_at=scan_result.finished_at,
                scan_data=scan_result.scan_data
            )

            # Mettre à jour la cible
            _update_target_after_scan(
                db,
                target_id=target_id,
                exposure_score=scan_result.exposure_score,
                scan_status=ScanStatus.SUCCESS
            )

            logger.info(
                f"✅ Scan terminé avec succès: score={scan_result.exposure_score}, "
                f"vulns={len(scan_result.vulnerabilities)}"
            )

            return {
                "status": "SUCCESS",
                "exposure_score": scan_result.exposure_score,
                "nb_vulnerabilities": len(scan_result.vulnerabilities),
                "nb_services": len(scan_result.services),
                "tls_grade": scan_result.tls_grade,
                "duration_seconds": scan_result.scan_duration_seconds
            }

        else:
            # Scan en erreur
            _update_scan_status(
                db,
                scan_id,
                ScanExecutionStatus.ERROR,
                scan_result.error_message
            )
            _update_target_after_scan(
                db,
                target_id=target_id,
                exposure_score=None,
                scan_status=ScanStatus.ERROR
            )

            logger.error(f"❌ Scan échoué: {scan_result.error_message}")

            return {
                "status": "ERROR",
                "error": scan_result.error_message
            }

    except Exception as e:
        logger.exception(f"❌ Erreur inattendue dans la tâche scan: {e}")

        # Mettre à jour le statut en erreur
        try:
            _update_scan_status(db, scan_id, ScanExecutionStatus.ERROR, str(e))
            _update_target_after_scan(db, target_id, None, ScanStatus.ERROR)
        except Exception:
            pass

        # Retry si possible
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)

        return {"status": "ERROR", "error": str(e)}

    finally:
        db.close()


@shared_task(
    bind=True,
    name="src.tasks.external_scan_tasks.generate_scan_report_task",
    max_retries=1,
    soft_time_limit=120,
    time_limit=180
)
def generate_scan_report_task(
    self,
    scan_id: str,
    tenant_id: str
) -> dict:
    """
    Tâche Celery pour générer un rapport IA pour un scan.

    Args:
        scan_id: UUID du scan
        tenant_id: UUID du tenant

    Returns:
        Dictionnaire avec l'ID du rapport généré
    """
    logger.info(f"📄 Génération rapport pour scan: {scan_id}")

    # TODO: Implémenter la génération de rapport IA
    # Cette tâche sera implémentée avec l'intégration Ollama

    return {
        "status": "NOT_IMPLEMENTED",
        "message": "La génération de rapport sera implémentée ultérieurement"
    }


# ==============================================================================
# FONCTIONS HELPER
# ==============================================================================

def _update_scan_status(
    db: Session,
    scan_id: str,
    status: ScanExecutionStatus,
    error_message: Optional[str] = None
):
    """Met à jour le statut d'un scan."""
    query = text("""
        UPDATE external_scan
        SET status = :status,
            error_message = :error_message,
            started_at = CASE
                WHEN :status = 'RUNNING' AND started_at IS NULL
                THEN NOW()
                ELSE started_at
            END
        WHERE id = CAST(:scan_id AS uuid)
    """)

    db.execute(query, {
        "scan_id": scan_id,
        "status": status.value,
        "error_message": error_message
    })
    db.commit()


def _make_json_serializable(obj):
    """
    Convertit récursivement un objet en structure JSON-sérialisable.
    Gère les cas de dataclasses, méthodes, datetime, etc.
    """
    import json
    from datetime import datetime, date
    from dataclasses import is_dataclass, asdict

    if obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    elif is_dataclass(obj) and not isinstance(obj, type):
        return _make_json_serializable(asdict(obj))
    elif callable(obj):
        # Si c'est une méthode/fonction, retourner None ou une valeur par défaut
        return None
    else:
        # Tenter la conversion en string
        try:
            return str(obj)
        except Exception:
            return None


def _update_scan_success(
    db: Session,
    scan_id: str,
    summary: dict,
    started_at: datetime,
    finished_at: datetime,
    scan_data: Optional[dict] = None
):
    """Met à jour un scan terminé avec succès."""
    import json

    # Nettoyer les données pour s'assurer qu'elles sont JSON-sérialisables
    clean_summary = _make_json_serializable(summary)
    clean_scan_data = _make_json_serializable(scan_data) if scan_data else None

    query = text("""
        UPDATE external_scan
        SET status = 'SUCCESS',
            summary = CAST(:summary AS jsonb),
            scan_data = CAST(:scan_data AS jsonb),
            started_at = :started_at,
            finished_at = :finished_at
        WHERE id = CAST(:scan_id AS uuid)
    """)

    db.execute(query, {
        "scan_id": scan_id,
        "summary": json.dumps(clean_summary),
        "scan_data": json.dumps(clean_scan_data) if clean_scan_data else None,
        "started_at": started_at,
        "finished_at": finished_at
    })
    db.commit()


def _update_target_after_scan(
    db: Session,
    target_id: str,
    exposure_score: Optional[int],
    scan_status: ScanStatus
):
    """Met à jour la cible après un scan."""
    query = text("""
        UPDATE external_target
        SET last_scan_at = NOW(),
            last_scan_status = :scan_status,
            last_exposure_score = :exposure_score,
            updated_at = NOW()
        WHERE id = CAST(:target_id AS uuid)
    """)

    db.execute(query, {
        "target_id": target_id,
        "scan_status": scan_status.value,
        "exposure_score": exposure_score
    })
    db.commit()


def _save_vulnerabilities(
    db: Session,
    scan_id: str,
    tenant_id: str,
    vulnerabilities: list[dict]
):
    """Sauvegarde les vulnérabilités détectées."""
    import json
    import uuid

    for vuln in vulnerabilities:
        vuln_id = str(uuid.uuid4())

        # Mapper le type de vulnérabilité
        vuln_type = vuln.get("vulnerability_type", "MISCONFIGURATION")
        if vuln_type not in [e.value for e in VulnerabilityType]:
            vuln_type = "MISCONFIGURATION"

        # Mapper la sévérité
        severity = vuln.get("severity", "INFO").upper()
        if severity not in [e.value for e in SeverityLevel]:
            severity = "INFO"

        query = text("""
            INSERT INTO external_service_vulnerability (
                id, external_scan_id, tenant_id,
                port, protocol, service_name, service_version, service_banner,
                vulnerability_type, severity,
                cve_ids, cvss_score, cvss_vector,
                title, description, recommendation,
                "references",
                created_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:scan_id AS uuid),
                CAST(:tenant_id AS uuid),
                :port, :protocol, :service_name, :service_version, :service_banner,
                :vuln_type, :severity,
                CAST(:cve_ids AS jsonb), :cvss_score, :cvss_vector,
                :title, :description, :recommendation,
                CAST(:refs AS jsonb),
                NOW()
            )
        """)

        db.execute(query, {
            "id": vuln_id,
            "scan_id": scan_id,
            "tenant_id": tenant_id,
            "port": vuln.get("port"),
            "protocol": vuln.get("protocol", "tcp"),
            "service_name": vuln.get("service_name"),
            "service_version": vuln.get("service_version"),
            "service_banner": vuln.get("service_banner"),
            "vuln_type": vuln_type,
            "severity": severity,
            "cve_ids": json.dumps(vuln.get("cve_ids", [])),
            "cvss_score": vuln.get("cvss_score"),
            "cvss_vector": vuln.get("cvss_vector"),
            "title": vuln.get("title", "Vulnérabilité détectée"),
            "description": vuln.get("description"),
            "recommendation": vuln.get("recommendation"),
            "refs": json.dumps(vuln.get("references", []))
        })

    db.commit()
    logger.info(f"💾 {len(vulnerabilities)} vulnérabilités sauvegardées")
