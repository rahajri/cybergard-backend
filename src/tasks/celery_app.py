# backend/src/tasks/celery_app.py
"""
Configuration de l'application Celery.

Celery est utilisé pour les tâches asynchrones:
- Scans externes (nmap, TLS, CVE)
- Génération de rapports
- Notifications
"""

import os
from celery import Celery

# Configuration Redis
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# Créer l'application Celery
celery_app = Celery(
    "cyberguard_scanner",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "src.tasks.external_scan_tasks",
    ]
)

# Configuration Celery
celery_app.conf.update(
    # Sérialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="Europe/Paris",
    enable_utc=True,

    # Queues
    task_default_queue="default",
    task_queues={
        "default": {
            "exchange": "default",
            "routing_key": "default",
        },
        "external_scan": {
            "exchange": "external_scan",
            "routing_key": "scan.external",
        },
        "report_generation": {
            "exchange": "report_generation",
            "routing_key": "report.generate",
        },
    },

    # Routes
    task_routes={
        "src.tasks.external_scan_tasks.scan_external_target_task": {
            "queue": "external_scan"
        },
        "src.tasks.external_scan_tasks.generate_scan_report_task": {
            "queue": "report_generation"
        },
    },

    # Timeouts et retries
    task_soft_time_limit=600,  # 10 minutes soft limit
    task_time_limit=900,  # 15 minutes hard limit
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Résultats
    result_expires=86400,  # 24 heures
    result_extended=True,

    # Worker
    worker_prefetch_multiplier=1,  # Un job à la fois pour les scans
    worker_concurrency=2,  # 2 workers par défaut

    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)


# Configuration pour les tests (mode eager)
def configure_for_testing():
    """Configure Celery pour les tests (exécution synchrone)."""
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )
