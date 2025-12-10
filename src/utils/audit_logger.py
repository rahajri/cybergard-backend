"""
Système d'audit logging pour les opérations sensibles
"""
from functools import wraps
from typing import Callable, Any
from fastapi import Request
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)


def audit_log(action: str, resource_type: str):
    """
    Décorateur pour logger les actions sensibles dans le système.

    Usage:
        @router.post("/organizations")
        @audit_log(action="CREATE_ORGANIZATION", resource_type="organization")
        async def create_organization(...):
            ...

    Args:
        action: Type d'action (CREATE_ORGANIZATION, UPDATE_ORGANIZATION, DELETE_ORGANIZATION, etc.)
        resource_type: Type de ressource (organization, user, tenant, etc.)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extraire les informations de contexte
            current_user = kwargs.get('current_user')
            db = kwargs.get('db')

            # Informations de base
            audit_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "action": action,
                "resource_type": resource_type,
                "user_email": current_user.email if current_user else "ANONYMOUS",
                "user_id": str(current_user.id) if current_user else None,
                "tenant_id": str(current_user.tenant_id) if current_user and current_user.tenant_id else None,
                "is_super_admin": current_user.is_super_admin() if current_user else False,
            }

            # Extraire l'ID de la ressource si présent
            resource_id = kwargs.get('organization_id') or kwargs.get('entity_id') or kwargs.get('user_id')
            if resource_id:
                audit_entry["resource_id"] = str(resource_id)

            # Extraire les données de la requête (pour CREATE/UPDATE)
            if 'organization' in kwargs:
                org_data = kwargs['organization']
                if hasattr(org_data, 'model_dump'):
                    audit_entry["request_data"] = {
                        "name": getattr(org_data, 'name', None),
                        "subscription_type": getattr(org_data, 'subscription_type', None),
                    }
            elif 'entity' in kwargs:
                entity_data = kwargs['entity']
                if hasattr(entity_data, 'model_dump'):
                    audit_entry["request_data"] = {
                        "name": getattr(entity_data, 'name', None),
                    }

            try:
                # Exécuter la fonction
                result = await func(*args, **kwargs)

                # Logger le succès
                audit_entry["status"] = "SUCCESS"
                if result and hasattr(result, 'id'):
                    audit_entry["resource_id"] = str(result.id)

                logger.info(f"🔍 AUDIT: {json.dumps(audit_entry, default=str)}")

                # TODO: Stocker dans une table audit_log en base de données
                # _store_audit_log(db, audit_entry)

                return result

            except Exception as e:
                # Logger l'échec
                audit_entry["status"] = "FAILURE"
                audit_entry["error"] = str(e)
                audit_entry["error_type"] = type(e).__name__

                logger.error(f"🔍 AUDIT (FAILED): {json.dumps(audit_entry, default=str)}")

                # TODO: Stocker l'échec aussi
                # _store_audit_log(db, audit_entry)

                raise

        return wrapper
    return decorator


def _store_audit_log(db, audit_entry: dict):
    """
    Stocke l'entrée d'audit dans la base de données.

    TODO: Implémenter avec une table audit_log:
    - id (UUID)
    - timestamp (DateTime)
    - action (String)
    - resource_type (String)
    - resource_id (UUID nullable)
    - user_id (UUID)
    - tenant_id (UUID nullable)
    - status (String: SUCCESS/FAILURE)
    - request_data (JSONB)
    - error (Text nullable)
    """
    pass
