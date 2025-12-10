# backend/src/tasks/__init__.py
"""
Module des tâches asynchrones Celery.

Ce module contient:
- celery_app: Configuration de l'application Celery
- external_scan_tasks: Tâches pour le scan externe
"""

from .celery_app import celery_app

__all__ = ["celery_app"]
