# backend/src/api/v1/external_scan.py
"""
Endpoints API pour le module Scan Externe (ASM).

Routes:
- /external-targets: Gestion des cibles
- /external-scans: Gestion des scans
- /external-scanner/dashboard: Statistiques

Toutes les routes sont sécurisées par tenant.

Note: Le worker Celery doit être démarré via Docker (docker-compose.scanner.yml)
"""

import json
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database import get_db
from src.dependencies_keycloak import require_permission
from src.models.audit import User
from src.schemas.external_scan import (
    # Request schemas
    ExternalTargetCreate,
    ExternalTargetUpdate,
    ScanLaunchRequest,
    VulnerabilityMarkRemediated,
    # Response schemas
    ExternalTargetResponse,
    ExternalTargetListResponse,
    ExternalScanResponse,
    ExternalScanListResponse,
    ScanLaunchResponse,
    VulnerabilityResponse,
    VulnerabilityListResponse,
    ScanDetailResponse,
    DashboardResponse,
    ExposureStats,
    TopVulnerableTarget,
    ScanSummary,
    # Enums
    ScanExecutionStatus,
    ScanStatus,
)

# Import conditionnel de Celery (disponible uniquement dans le container scanner)
# Si Celery n'est pas disponible, utiliser Redis directement
try:
    from src.tasks.external_scan_tasks import scan_external_target_task
    CELERY_AVAILABLE = True
except ImportError:
    scan_external_target_task = None
    CELERY_AVAILABLE = False

# Fonction pour envoyer une tâche via Redis sans dépendre de Celery
import json
import os
import redis

def send_celery_task_via_redis(task_name: str, args: list, kwargs: dict = None) -> str:
    """
    Envoie une tâche Celery via Redis directement.
    Utilisé quand le package Celery n'est pas installé dans l'API.

    Returns:
        task_id: ID de la tâche générée
    """
    redis_url = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://cyberguard_redis:6379/1"))

    # Parser l'URL Redis
    if redis_url.startswith("redis://"):
        parts = redis_url.replace("redis://", "").split("/")
        host_port = parts[0].split(":")
        host = host_port[0]
        port = int(host_port[1]) if len(host_port) > 1 else 6379
        db = int(parts[1]) if len(parts) > 1 else 0
    else:
        host = "cyberguard_redis"
        port = 6379
        db = 1

    r = redis.Redis(host=host, port=port, db=db)

    task_id = str(uuid.uuid4())

    # Format du message Celery
    message = {
        "body": json.dumps([args, kwargs or {}, {"callbacks": None, "errbacks": None, "chain": None, "chord": None}]),
        "content-encoding": "utf-8",
        "content-type": "application/json",
        "headers": {
            "lang": "py",
            "task": task_name,
            "id": task_id,
            "root_id": task_id,
            "parent_id": None,
            "group": None,
            "meth": None,
            "shadow": None,
            "eta": None,
            "expires": None,
            "retries": 0,
            "timelimit": [None, None],
            "argsrepr": repr(args),
            "kwargsrepr": repr(kwargs or {}),
            "origin": "api@cybergard"
        },
        "properties": {
            "correlation_id": task_id,
            "reply_to": "",
            "delivery_mode": 2,
            "delivery_info": {
                "exchange": "external_scan",
                "routing_key": "scan.external"
            },
            "priority": 0,
            "body_encoding": "base64",
            "delivery_tag": task_id
        }
    }

    # Publier dans la queue
    r.lpush("external_scan", json.dumps(message))

    logger.info(f"📤 Tâche envoyée via Redis: {task_name} (id={task_id})")

    return task_id

logger = logging.getLogger(__name__)

# Import du service IA pour les justifications Scanner
from src.services.scan_ai_justification_service import ScanAIJustificationService

router = APIRouter(prefix="/external-scanner", tags=["External Scanner"])


# ==============================================================================
# TARGETS ENDPOINTS
# ==============================================================================

@router.post("/targets", response_model=ExternalTargetResponse, status_code=status.HTTP_201_CREATED)
async def create_target(
    target: ExternalTargetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_WRITE"))
):
    """
    Crée une nouvelle cible externe.

    Args:
        target: Données de la cible
        db: Session DB
        current_user: Utilisateur connecté

    Returns:
        La cible créée
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None
    user_id = str(current_user.id) if current_user.id else None

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID requis")

    # Vérifier si la cible existe déjà
    check_query = text("""
        SELECT id FROM external_target
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        AND value = :value
        AND deleted_at IS NULL
    """)
    existing = db.execute(check_query, {
        "tenant_id": tenant_id,
        "value": target.value.lower()
    }).fetchone()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"La cible '{target.value}' existe déjà"
        )

    # Créer la cible
    target_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    insert_query = text("""
        INSERT INTO external_target (
            id, tenant_id, type, value, label, description,
            scan_frequency, is_active, last_scan_status,
            entity_id, created_by, created_at, updated_at
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:tenant_id AS uuid),
            :type,
            :value,
            :label,
            :description,
            :scan_frequency,
            :is_active,
            'NEVER',
            CAST(:entity_id AS uuid),
            CAST(:created_by AS uuid),
            :created_at,
            :updated_at
        )
        RETURNING *
    """)

    db.execute(insert_query, {
        "id": target_id,
        "tenant_id": tenant_id,
        "type": target.type.value,
        "value": target.value.lower(),
        "label": target.label,
        "description": target.description,
        "scan_frequency": target.scan_frequency.value,
        "is_active": target.is_active,
        "entity_id": str(target.entity_id) if target.entity_id else None,
        "created_by": user_id,
        "created_at": now,
        "updated_at": now
    })
    db.commit()

    # Récupérer avec le JOIN pour entity_name
    select_query = text("""
        SELECT et.*, ee.name as entity_name
        FROM external_target et
        LEFT JOIN ecosystem_entity ee ON et.entity_id = ee.id
        WHERE et.id = CAST(:target_id AS uuid)
    """)
    row = db.execute(select_query, {"target_id": target_id}).fetchone()
    logger.info(f"✅ Cible créée: {target.value} (id={target_id})")

    return _row_to_target_response(row)


@router.get("/targets", response_model=ExternalTargetListResponse)
async def list_targets(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ")),
    type: Optional[str] = Query(None, description="Filtrer par type"),
    is_active: Optional[bool] = Query(None, description="Filtrer par statut actif"),
    search: Optional[str] = Query(None, description="Recherche dans value/label"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Liste les cibles externes du tenant."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Construire la requête
    where_clauses = ["et.tenant_id = CAST(:tenant_id AS uuid)", "et.deleted_at IS NULL"]
    params = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

    if type:
        where_clauses.append("et.type = :type")
        params["type"] = type

    if is_active is not None:
        where_clauses.append("et.is_active = :is_active")
        params["is_active"] = is_active

    if search:
        where_clauses.append("(et.value ILIKE :search OR et.label ILIKE :search)")
        params["search"] = f"%{search}%"

    where_sql = " AND ".join(where_clauses)

    # Compter le total
    count_query = text(f"SELECT COUNT(*) FROM external_target et WHERE {where_sql}")
    total = db.execute(count_query, params).scalar()

    # Récupérer les items avec le nom de l'entité
    query = text(f"""
        SELECT et.*, ee.name as entity_name
        FROM external_target et
        LEFT JOIN ecosystem_entity ee ON et.entity_id = ee.id
        WHERE {where_sql}
        ORDER BY et.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = db.execute(query, params).fetchall()

    return ExternalTargetListResponse(
        items=[_row_to_target_response(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/targets/{target_id}", response_model=ExternalTargetResponse)
async def get_target(
    target_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ"))
):
    """Récupère une cible par son ID."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    query = text("""
        SELECT et.*, ee.name as entity_name
        FROM external_target et
        LEFT JOIN ecosystem_entity ee ON et.entity_id = ee.id
        WHERE et.id = CAST(:target_id AS uuid)
        AND et.tenant_id = CAST(:tenant_id AS uuid)
        AND et.deleted_at IS NULL
    """)
    row = db.execute(query, {
        "target_id": target_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Cible non trouvée")

    return _row_to_target_response(row)


@router.patch("/targets/{target_id}", response_model=ExternalTargetResponse)
async def update_target(
    target_id: str,
    update: ExternalTargetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_WRITE"))
):
    """Met à jour une cible."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Vérifier que la cible existe
    check_query = text("""
        SELECT id FROM external_target
        WHERE id = CAST(:target_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
        AND deleted_at IS NULL
    """)
    existing = db.execute(check_query, {
        "target_id": target_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Cible non trouvée")

    # Construire la mise à jour
    update_fields = []
    params = {"target_id": target_id, "tenant_id": tenant_id}

    if update.label is not None:
        update_fields.append("label = :label")
        params["label"] = update.label

    if update.description is not None:
        update_fields.append("description = :description")
        params["description"] = update.description

    if update.scan_frequency is not None:
        update_fields.append("scan_frequency = :scan_frequency")
        params["scan_frequency"] = update.scan_frequency.value

    if update.is_active is not None:
        update_fields.append("is_active = :is_active")
        params["is_active"] = update.is_active

    # entity_id peut être défini explicitement à None pour dissocier
    if hasattr(update, 'entity_id') and update.entity_id is not None:
        update_fields.append("entity_id = CAST(:entity_id AS uuid)")
        params["entity_id"] = str(update.entity_id)

    if not update_fields:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")

    update_fields.append("updated_at = NOW()")
    update_sql = ", ".join(update_fields)

    # D'abord faire le UPDATE
    update_query = text(f"""
        UPDATE external_target
        SET {update_sql}
        WHERE id = CAST(:target_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
    """)
    db.execute(update_query, params)
    db.commit()

    # Ensuite récupérer avec le JOIN pour entity_name
    select_query = text("""
        SELECT et.*, ee.name as entity_name
        FROM external_target et
        LEFT JOIN ecosystem_entity ee ON et.entity_id = ee.id
        WHERE et.id = CAST(:target_id AS uuid)
        AND et.tenant_id = CAST(:tenant_id AS uuid)
    """)
    row = db.execute(select_query, {"target_id": target_id, "tenant_id": tenant_id}).fetchone()

    return _row_to_target_response(row)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_DELETE"))
):
    """Supprime une cible (soft delete)."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    query = text("""
        UPDATE external_target
        SET deleted_at = NOW()
        WHERE id = CAST(:target_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
        AND deleted_at IS NULL
    """)
    result = db.execute(query, {
        "target_id": target_id,
        "tenant_id": tenant_id
    })
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Cible non trouvée")

    logger.info(f"🗑️ Cible supprimée: {target_id}")


# ==============================================================================
# SCANS ENDPOINTS
# ==============================================================================

@router.post("/targets/{target_id}/scan", response_model=ScanLaunchResponse)
async def launch_scan(
    target_id: str,
    request: ScanLaunchRequest = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_EXECUTE"))
):
    """
    Lance un scan sur une cible.

    Le scan est exécuté de manière asynchrone via Celery.
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None
    user_id = str(current_user.id) if current_user.id else None

    # Vérifier que la cible existe
    target_query = text("""
        SELECT id, value, type FROM external_target
        WHERE id = CAST(:target_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
        AND deleted_at IS NULL
        AND is_active = true
    """)
    target = db.execute(target_query, {
        "target_id": target_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not target:
        raise HTTPException(status_code=404, detail="Cible non trouvée ou inactive")

    # Vérifier qu'il n'y a pas de scan en cours
    running_query = text("""
        SELECT id FROM external_scan
        WHERE external_target_id = CAST(:target_id AS uuid)
        AND status IN ('PENDING', 'RUNNING')
    """)
    running = db.execute(running_query, {"target_id": target_id}).fetchone()

    if running:
        raise HTTPException(
            status_code=400,
            detail="Un scan est déjà en cours pour cette cible"
        )

    # Créer l'entrée de scan avec l'entity_id de la target
    scan_id = str(uuid.uuid4())

    # Récupérer l'entity_id de la target (peut être null pour scan interne)
    target_entity_id = target.entity_id if hasattr(target, 'entity_id') else None

    insert_query = text("""
        INSERT INTO external_scan (
            id, external_target_id, tenant_id, entity_id,
            status, triggered_by, trigger_type, created_at
        ) VALUES (
            CAST(:scan_id AS uuid),
            CAST(:target_id AS uuid),
            CAST(:tenant_id AS uuid),
            CAST(:entity_id AS uuid),
            'PENDING',
            CAST(:triggered_by AS uuid),
            'manual',
            NOW()
        )
    """)
    db.execute(insert_query, {
        "scan_id": scan_id,
        "target_id": target_id,
        "tenant_id": tenant_id,
        "entity_id": str(target_entity_id) if target_entity_id else None,
        "triggered_by": user_id
    })
    db.commit()

    # Lancer la tâche Celery (ou via Redis si Celery n'est pas disponible)
    if CELERY_AVAILABLE:
        task = scan_external_target_task.delay(
            target_id=target_id,
            scan_id=scan_id,
            triggered_by=user_id
        )
        task_id = task.id
        logger.info(f"🚀 Scan lancé via Celery: target={target_id}, scan={scan_id}, task={task_id}")
    else:
        # Utiliser Redis directement pour envoyer la tâche
        task_id = send_celery_task_via_redis(
            task_name="src.tasks.external_scan_tasks.scan_external_target_task",
            args=[],
            kwargs={
                "target_id": target_id,
                "scan_id": scan_id,
                "triggered_by": user_id
            }
        )
        logger.info(f"🚀 Scan lancé via Redis: target={target_id}, scan={scan_id}, task={task_id}")

    return ScanLaunchResponse(
        scan_id=uuid.UUID(scan_id),
        target_id=uuid.UUID(target_id),
        status=ScanExecutionStatus.PENDING,
        message=f"Scan lancé pour {target.value}",
        task_id=task_id
    )


@router.get("/scans", response_model=ExternalScanListResponse)
async def list_scans(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ")),
    target_id: Optional[str] = Query(None, description="Filtrer par cible"),
    status: Optional[str] = Query(None, description="Filtrer par statut"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Liste les scans du tenant."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Clauses WHERE pour la requête simple (count)
    where_clauses = ["tenant_id = CAST(:tenant_id AS uuid)"]
    # Clauses WHERE pour la requête JOIN (avec alias es.)
    where_clauses_aliased = ["es.tenant_id = CAST(:tenant_id AS uuid)"]
    params = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

    if target_id:
        where_clauses.append("external_target_id = CAST(:target_id AS uuid)")
        where_clauses_aliased.append("es.external_target_id = CAST(:target_id AS uuid)")
        params["target_id"] = target_id

    if status:
        where_clauses.append("status = :status")
        where_clauses_aliased.append("es.status = :status")
        params["status"] = status

    where_sql = " AND ".join(where_clauses)
    where_sql_aliased = " AND ".join(where_clauses_aliased)

    # Compter
    count_query = text(f"SELECT COUNT(*) FROM external_scan WHERE {where_sql}")
    total = db.execute(count_query, params).scalar()

    # Récupérer avec les infos de la cible et de l'entité (JOIN)
    # COALESCE pour récupérer l'entity_id depuis la target si le scan n'en a pas
    query = text(f"""
        SELECT
            es.*,
            et.value as target_value,
            et.type as target_type,
            et.label as target_label,
            COALESCE(es.entity_id, et.entity_id) as effective_entity_id,
            COALESCE(ee_scan.name, ee_target.name) as entity_name
        FROM external_scan es
        LEFT JOIN external_target et ON es.external_target_id = et.id
        LEFT JOIN ecosystem_entity ee_scan ON es.entity_id = ee_scan.id
        LEFT JOIN ecosystem_entity ee_target ON et.entity_id = ee_target.id
        WHERE {where_sql_aliased}
        ORDER BY es.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = db.execute(query, params).fetchall()

    from src.schemas.external_scan import TargetInfo

    # Transformer les résultats pour inclure les infos de la cible et de l'entité
    items = []
    for row in rows:
        scan_response = _row_to_scan_response(row)
        # Ajouter les infos de la cible si disponibles
        if hasattr(row, 'target_value') and row.target_value:
            scan_response.target = TargetInfo(
                value=row.target_value,
                type=row.target_type,
                label=row.target_label
            )
        # Ajouter les infos de l'entité (utilise effective_entity_id qui fait le COALESCE)
        if hasattr(row, 'effective_entity_id') and row.effective_entity_id:
            scan_response.entity_id = row.effective_entity_id
        if hasattr(row, 'entity_name') and row.entity_name:
            scan_response.entity_name = row.entity_name
        items.append(scan_response)

    return ExternalScanListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/scans/{scan_id}", response_model=ExternalScanResponse)
async def get_scan(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ"))
):
    """Récupère un scan par son ID."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # COALESCE pour récupérer l'entity_id depuis la target si le scan n'en a pas
    query = text("""
        SELECT es.*,
               COALESCE(es.entity_id, et.entity_id) as effective_entity_id,
               COALESCE(ee_scan.name, ee_target.name) as entity_name
        FROM external_scan es
        LEFT JOIN external_target et ON es.external_target_id = et.id
        LEFT JOIN ecosystem_entity ee_scan ON es.entity_id = ee_scan.id
        LEFT JOIN ecosystem_entity ee_target ON et.entity_id = ee_target.id
        WHERE es.id = CAST(:scan_id AS uuid)
        AND es.tenant_id = CAST(:tenant_id AS uuid)
    """)
    row = db.execute(query, {
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Scan non trouvé")

    response = _row_to_scan_response(row)
    # Utiliser effective_entity_id pour les scans existants qui n'avaient pas l'entity_id
    if hasattr(row, 'effective_entity_id') and row.effective_entity_id:
        response.entity_id = row.effective_entity_id
    return response


@router.get("/scans/{scan_id}/detail", response_model=ScanDetailResponse)
async def get_scan_detail(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ"))
):
    """Récupère le détail complet d'un scan avec vulnérabilités."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Récupérer le scan
    scan_query = text("""
        SELECT * FROM external_scan
        WHERE id = CAST(:scan_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
    """)
    scan_row = db.execute(scan_query, {
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not scan_row:
        raise HTTPException(status_code=404, detail="Scan non trouvé")

    # Récupérer la cible
    target_query = text("""
        SELECT * FROM external_target
        WHERE id = CAST(:target_id AS uuid)
    """)
    target_row = db.execute(target_query, {
        "target_id": str(scan_row.external_target_id)
    }).fetchone()

    # Récupérer les vulnérabilités
    vuln_query = text("""
        SELECT * FROM external_service_vulnerability
        WHERE external_scan_id = CAST(:scan_id AS uuid)
        ORDER BY
            CASE severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3
                WHEN 'LOW' THEN 4
                ELSE 5
            END
    """)
    vuln_rows = db.execute(vuln_query, {"scan_id": scan_id}).fetchall()

    # Parser scan_data si disponible
    scan_data = None
    if hasattr(scan_row, 'scan_data') and scan_row.scan_data:
        scan_data = scan_row.scan_data

    # Parser les services depuis scan_data
    services = []
    if scan_data and 'services' in scan_data:
        for svc in scan_data['services']:
            services.append({
                "port": svc.get("port", 0),
                "protocol": svc.get("protocol", "tcp"),
                "service_name": svc.get("service_name", "unknown"),
                "service_version": svc.get("service_version"),
                "service_product": svc.get("service_product"),
                "service_banner": svc.get("service_banner"),
                "cpe": svc.get("cpe"),
                "is_risky": svc.get("port", 0) in [21, 23, 139, 445, 1433, 3389, 5900],
                "vulnerabilities_count": 0
            })

    return ScanDetailResponse(
        scan=_row_to_scan_response(scan_row),
        target=_row_to_target_response(target_row),
        services=services,
        vulnerabilities=[_row_to_vuln_response(row) for row in vuln_rows],
        summary=_parse_summary(scan_row.summary) if scan_row.summary else None,
        scan_data=scan_data
    )


# ==============================================================================
# VULNERABILITIES ENDPOINTS
# ==============================================================================

@router.get("/scans/{scan_id}/vulnerabilities", response_model=VulnerabilityListResponse)
async def list_vulnerabilities(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ")),
    severity: Optional[str] = Query(None, description="Filtrer par sévérité"),
    vuln_type: Optional[str] = Query(None, description="Filtrer par type"),
    is_remediated: Optional[bool] = Query(None, description="Filtrer par remédiation"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Liste les vulnérabilités d'un scan."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Vérifier accès au scan
    scan_check = text("""
        SELECT id FROM external_scan
        WHERE id = CAST(:scan_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
    """)
    if not db.execute(scan_check, {"scan_id": scan_id, "tenant_id": tenant_id}).fetchone():
        raise HTTPException(status_code=404, detail="Scan non trouvé")

    where_clauses = ["external_scan_id = CAST(:scan_id AS uuid)"]
    params = {"scan_id": scan_id, "limit": limit, "offset": offset}

    if severity:
        where_clauses.append("severity = :severity")
        params["severity"] = severity

    if vuln_type:
        where_clauses.append("vulnerability_type = :vuln_type")
        params["vuln_type"] = vuln_type

    if is_remediated is not None:
        where_clauses.append("is_remediated = :is_remediated")
        params["is_remediated"] = is_remediated

    where_sql = " AND ".join(where_clauses)

    # Compter
    count_query = text(f"SELECT COUNT(*) FROM external_service_vulnerability WHERE {where_sql}")
    total = db.execute(count_query, params).scalar()

    # Compter par sévérité
    severity_query = text(f"""
        SELECT severity, COUNT(*) as count
        FROM external_service_vulnerability
        WHERE external_scan_id = CAST(:scan_id AS uuid)
        GROUP BY severity
    """)
    severity_counts = {row.severity: row.count for row in db.execute(severity_query, {"scan_id": scan_id})}

    # Récupérer
    query = text(f"""
        SELECT * FROM external_service_vulnerability
        WHERE {where_sql}
        ORDER BY
            CASE severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3
                WHEN 'LOW' THEN 4
                ELSE 5
            END,
            created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = db.execute(query, params).fetchall()

    return VulnerabilityListResponse(
        items=[_row_to_vuln_response(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        by_severity=severity_counts
    )


@router.patch("/vulnerabilities/{vuln_id}/remediate", response_model=VulnerabilityResponse)
async def mark_remediated(
    vuln_id: str,
    request: VulnerabilityMarkRemediated,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_WRITE"))
):
    """Marque une vulnérabilité comme remédiée."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None
    user_id = str(current_user.id) if current_user.id else None

    query = text("""
        UPDATE external_service_vulnerability
        SET is_remediated = :is_remediated,
            remediated_at = CASE WHEN :is_remediated THEN NOW() ELSE NULL END,
            remediated_by = CASE WHEN :is_remediated THEN CAST(:user_id AS uuid) ELSE NULL END
        WHERE id = CAST(:vuln_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
        RETURNING *
    """)
    row = db.execute(query, {
        "vuln_id": vuln_id,
        "tenant_id": tenant_id,
        "is_remediated": request.is_remediated,
        "user_id": user_id
    }).fetchone()
    db.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Vulnérabilité non trouvée")

    return _row_to_vuln_response(row)


# ==============================================================================
# REPORT ENDPOINT
# ==============================================================================

@router.post("/scans/{scan_id}/report")
async def generate_report(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_REPORT"))
):
    """
    Génère un rapport IA pour un scan.

    Le rapport inclut:
    - Résumé exécutif
    - Analyse des risques
    - Recommandations priorisées
    - Plan d'action
    """
    from src.services.external_scanner.report_generator import generate_scan_report

    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Récupérer le scan
    scan_query = text("""
        SELECT * FROM external_scan
        WHERE id = CAST(:scan_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
        AND status = 'SUCCESS'
    """)
    scan_row = db.execute(scan_query, {
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not scan_row:
        raise HTTPException(
            status_code=404,
            detail="Scan non trouvé ou non terminé avec succès"
        )

    # Récupérer la cible
    target_query = text("""
        SELECT * FROM external_target
        WHERE id = CAST(:target_id AS uuid)
    """)
    target_row = db.execute(target_query, {
        "target_id": str(scan_row.external_target_id)
    }).fetchone()

    # Récupérer les vulnérabilités
    vuln_query = text("""
        SELECT * FROM external_service_vulnerability
        WHERE external_scan_id = CAST(:scan_id AS uuid)
        ORDER BY
            CASE severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3
                WHEN 'LOW' THEN 4
                ELSE 5
            END
    """)
    vuln_rows = db.execute(vuln_query, {"scan_id": scan_id}).fetchall()

    # Convertir en dictionnaires
    scan_data = {
        "id": str(scan_row.id),
        "summary": scan_row.summary or {},
        "finished_at": scan_row.finished_at
    }

    target_data = {
        "value": target_row.value,
        "type": target_row.type
    }

    vulnerabilities = [
        {
            "title": row.title,
            "severity": row.severity,
            "vulnerability_type": row.vulnerability_type,
            "port": row.port,
            "protocol": row.protocol,
            "service_name": row.service_name,
            "service_version": row.service_version,
            "description": row.description,
            "recommendation": row.recommendation,
            "cve_ids": row.cve_ids or [],
            "cvss_score": row.cvss_score
        }
        for row in vuln_rows
    ]

    services = []  # Les services sont dérivés des vulnérabilités

    # Générer le rapport
    try:
        report = await generate_scan_report(
            scan_data=scan_data,
            target_data=target_data,
            vulnerabilities=vulnerabilities,
            services=services
        )

        # Marquer le scan comme ayant un rapport
        update_query = text("""
            UPDATE external_scan
            SET report_generated = true
            WHERE id = CAST(:scan_id AS uuid)
        """)
        db.execute(update_query, {"scan_id": scan_id})
        db.commit()

        logger.info(f"📄 Rapport généré pour scan {scan_id}")

        return {
            "title": report.title,
            "executive_summary": report.executive_summary,
            "risk_analysis": report.risk_analysis,
            "findings": report.findings,
            "recommendations": report.recommendations,
            "action_plan": report.action_plan,
            "conclusion": report.conclusion,
            "generated_at": report.generated_at.isoformat(),
            "model_used": report.model_used
        }

    except Exception as e:
        logger.error(f"❌ Erreur génération rapport: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la génération du rapport: {str(e)}"
        )


# ==============================================================================
# DASHBOARD ENDPOINT
# ==============================================================================

@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ"))
):
    """Récupère les statistiques du dashboard scanner."""
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Stats cibles
    targets_query = text("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN last_scan_status != 'NEVER' THEN 1 END) as scanned,
            COUNT(CASE WHEN last_scan_status = 'NEVER' THEN 1 END) as never_scanned,
            AVG(CASE WHEN last_exposure_score IS NOT NULL THEN last_exposure_score END) as avg_score
        FROM external_target
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        AND deleted_at IS NULL
    """)
    targets_stats = db.execute(targets_query, {"tenant_id": tenant_id}).fetchone()

    # Stats scans
    scans_query = text("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN created_at > NOW() - INTERVAL '30 days' THEN 1 END) as last_30_days
        FROM external_scan
        WHERE tenant_id = CAST(:tenant_id AS uuid)
    """)
    scans_stats = db.execute(scans_query, {"tenant_id": tenant_id}).fetchone()

    # Stats vulnérabilités
    vulns_query = text("""
        SELECT
            COUNT(CASE WHEN severity = 'CRITICAL' THEN 1 END) as critical,
            COUNT(CASE WHEN severity = 'HIGH' THEN 1 END) as high,
            COUNT(CASE WHEN severity = 'MEDIUM' THEN 1 END) as medium,
            COUNT(CASE WHEN severity = 'LOW' THEN 1 END) as low
        FROM external_service_vulnerability
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        AND is_remediated = false
    """)
    vulns_stats = db.execute(vulns_query, {"tenant_id": tenant_id}).fetchone()

    # Top cibles vulnérables
    top_targets_query = text("""
        SELECT
            et.id, et.value, et.type, et.last_exposure_score, et.last_scan_at,
            COUNT(CASE WHEN esv.severity = 'CRITICAL' THEN 1 END) as critical_count,
            COUNT(CASE WHEN esv.severity = 'HIGH' THEN 1 END) as high_count
        FROM external_target et
        LEFT JOIN external_scan es ON es.external_target_id = et.id
            AND es.status = 'SUCCESS'
        LEFT JOIN external_service_vulnerability esv ON esv.external_scan_id = es.id
            AND esv.is_remediated = false
        WHERE et.tenant_id = CAST(:tenant_id AS uuid)
        AND et.deleted_at IS NULL
        AND et.last_exposure_score IS NOT NULL
        GROUP BY et.id, et.value, et.type, et.last_exposure_score, et.last_scan_at
        ORDER BY et.last_exposure_score DESC
        LIMIT 5
    """)
    top_targets = db.execute(top_targets_query, {"tenant_id": tenant_id}).fetchall()

    # Scans récents
    recent_scans_query = text("""
        SELECT * FROM external_scan
        WHERE tenant_id = CAST(:tenant_id AS uuid)
        ORDER BY created_at DESC
        LIMIT 5
    """)
    recent_scans = db.execute(recent_scans_query, {"tenant_id": tenant_id}).fetchall()

    return DashboardResponse(
        stats=ExposureStats(
            total_targets=targets_stats.total or 0,
            targets_scanned=targets_stats.scanned or 0,
            targets_never_scanned=targets_stats.never_scanned or 0,
            total_scans=scans_stats.total or 0,
            scans_last_30_days=scans_stats.last_30_days or 0,
            average_exposure_score=float(targets_stats.avg_score or 0),
            critical_vulnerabilities=vulns_stats.critical or 0,
            high_vulnerabilities=vulns_stats.high or 0,
            medium_vulnerabilities=vulns_stats.medium or 0,
            low_vulnerabilities=vulns_stats.low or 0
        ),
        top_vulnerable_targets=[
            TopVulnerableTarget(
                target_id=row.id,
                target_value=row.value,
                target_type=row.type,
                exposure_score=row.last_exposure_score or 0,
                critical_count=row.critical_count or 0,
                high_count=row.high_count or 0,
                last_scan_at=row.last_scan_at
            )
            for row in top_targets
        ],
        recent_scans=[_row_to_scan_response(row) for row in recent_scans]
    )


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _row_to_target_response(row) -> ExternalTargetResponse:
    """Convertit une row SQL en ExternalTargetResponse."""
    return ExternalTargetResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        type=row.type,
        value=row.value,
        label=row.label,
        description=row.description,
        scan_frequency=row.scan_frequency,
        is_active=row.is_active,
        last_scan_at=row.last_scan_at,
        last_scan_status=row.last_scan_status or ScanStatus.NEVER,
        last_exposure_score=row.last_exposure_score,
        entity_id=row.entity_id if hasattr(row, 'entity_id') and row.entity_id else None,
        entity_name=row.entity_name if hasattr(row, 'entity_name') else None,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at
    )


def _row_to_scan_response(row) -> ExternalScanResponse:
    """Convertit une row SQL en ExternalScanResponse."""
    return ExternalScanResponse(
        id=row.id,
        external_target_id=row.external_target_id,
        tenant_id=row.tenant_id,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_message=row.error_message,
        summary=_parse_summary(row.summary) if row.summary else None,
        report_generated=row.report_generated or False,
        report_id=row.report_id,
        triggered_by=row.triggered_by,
        trigger_type=row.trigger_type or "manual",
        created_at=row.created_at,
        entity_id=row.entity_id if hasattr(row, 'entity_id') and row.entity_id else None,
        entity_name=row.entity_name if hasattr(row, 'entity_name') and row.entity_name else None
    )


def _row_to_vuln_response(row) -> VulnerabilityResponse:
    """Convertit une row SQL en VulnerabilityResponse."""
    return VulnerabilityResponse(
        id=row.id,
        external_scan_id=row.external_scan_id,
        tenant_id=row.tenant_id,
        port=row.port,
        protocol=row.protocol,
        service_name=row.service_name,
        service_version=row.service_version,
        service_banner=row.service_banner,
        vulnerability_type=row.vulnerability_type,
        severity=row.severity,
        cve_ids=row.cve_ids if isinstance(row.cve_ids, list) else [],
        cvss_score=row.cvss_score,
        cvss_vector=row.cvss_vector,
        title=row.title,
        description=row.description,
        recommendation=row.recommendation,
        references=row.references if isinstance(row.references, list) else [],
        is_remediated=row.is_remediated or False,
        remediated_at=row.remediated_at,
        remediated_by=row.remediated_by,
        created_at=row.created_at
    )


def _parse_summary(summary_data) -> Optional[ScanSummary]:
    """Parse le JSON summary en ScanSummary."""
    if not summary_data:
        return None

    if isinstance(summary_data, dict):
        return ScanSummary(
            nb_services_exposed=summary_data.get("nb_services_exposed", 0),
            nb_vuln_critical=summary_data.get("nb_vuln_critical", 0),
            nb_vuln_high=summary_data.get("nb_vuln_high", 0),
            nb_vuln_medium=summary_data.get("nb_vuln_medium", 0),
            nb_vuln_low=summary_data.get("nb_vuln_low", 0),
            nb_vuln_info=summary_data.get("nb_vuln_info", 0),
            nb_vuln_total=summary_data.get("nb_vuln_total", 0),
            exposure_score=summary_data.get("exposure_score", 0),
            risk_level=summary_data.get("risk_level"),
            tls_grade=summary_data.get("tls_grade"),
            ports_scanned=summary_data.get("ports_scanned", 0),
            scan_duration_seconds=summary_data.get("scan_duration_seconds", 0)
        )

    return None


# ==============================================================================
# ACTION PLAN GENERATION FROM SCAN
# ==============================================================================

from pydantic import BaseModel
from typing import List
from datetime import timedelta


class ActionCustomization(BaseModel):
    """Personnalisation d'une action par l'utilisateur."""
    vulnerability_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    objective: Optional[str] = None
    deliverables: Optional[str] = None
    severity: Optional[str] = None
    priority: Optional[str] = None
    recommended_due_days: Optional[int] = None
    suggested_role: Optional[str] = None
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None


class ScanActionPlanRequest(BaseModel):
    """Paramètres pour générer un plan d'action depuis un scan."""
    severity_filter: List[str] = ["CRITICAL", "HIGH", "MEDIUM"]  # Sévérités à inclure
    include_remediated: bool = False  # Inclure les vulnérabilités déjà remédiées
    entity_id: Optional[str] = None  # Entité de l'écosystème à lier (optionnel)
    customizations: Optional[List[ActionCustomization]] = None  # Personnalisations utilisateur


class ScanActionItemResponse(BaseModel):
    """Item du plan d'action généré depuis un scan."""
    id: str
    vulnerability_id: Optional[str] = None
    code_action: Optional[str] = None
    title: str
    description: str
    recommendation: Optional[str] = None
    severity: str
    priority: str
    recommended_due_days: int
    port: Optional[int] = None
    service_name: Optional[str] = None
    cve_ids: List[str] = []
    cvss_score: Optional[float] = None
    status: str
    included: bool
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    # Justifications IA générées automatiquement
    ai_justifications: Optional[Dict[str, str]] = None


class ScanActionPlanDetailResponse(BaseModel):
    """Réponse détaillée du plan d'action."""
    id: str
    scan_id: str
    code_scan: str
    status: str
    target_value: Optional[str] = None
    target_type: Optional[str] = None
    exposure_score: Optional[int] = None
    total_items: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    validated_count: int
    excluded_count: int
    items: List[ScanActionItemResponse]
    generated_at: Optional[str] = None
    published_at: Optional[str] = None


class PublishScanActionsResponse(BaseModel):
    """Réponse de publication des actions."""
    success: bool
    message: str
    published_count: int
    code_scan: str
    action_codes: List[str]


class UpdateScanActionItemRequest(BaseModel):
    """Mise à jour d'un item du plan d'action."""
    included: Optional[bool] = None
    status: Optional[str] = None  # VALIDATED, EXCLUDED
    entity_id: Optional[str] = None


@router.post("/scans/{scan_id}/action-plan", response_model=ScanActionPlanDetailResponse)
async def generate_scan_action_plan(
    scan_id: str,
    request: ScanActionPlanRequest = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_REPORT"))
):
    """
    Génère un plan d'action depuis les vulnérabilités d'un scan.

    Crée un enregistrement dans scan_action_plan avec les items correspondants.
    Le plan est en statut DRAFT et peut être édité avant publication.

    Args:
        scan_id: ID du scan
        request: Filtres (sévérités, inclure remédiées, entité)

    Returns:
        Plan d'action détaillé avec liste des items
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None
    user_id = str(current_user.id) if current_user.id else None

    if request is None:
        request = ScanActionPlanRequest()

    # Vérifier si un plan existe déjà
    existing_plan_query = text("""
        SELECT id, status FROM scan_action_plan
        WHERE scan_id = CAST(:scan_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
    """)
    existing_plan = db.execute(existing_plan_query, {
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if existing_plan:
        if existing_plan.status == "PUBLISHED":
            raise HTTPException(
                status_code=400,
                detail="Un plan d'action a déjà été publié pour ce scan"
            )
        # Retourner le plan existant
        return await get_scan_action_plan(scan_id, db, current_user)

    # Récupérer le scan avec la cible ET l'entité associée au scan
    scan_query = text("""
        SELECT es.id, es.code_scan, es.status, es.summary,
               et.value as target_value, et.type as target_type,
               es.entity_id as scan_entity_id,
               ee.name as scan_entity_name
        FROM external_scan es
        JOIN external_target et ON et.id = es.external_target_id
        LEFT JOIN ecosystem_entity ee ON es.entity_id = ee.id
        WHERE es.id = CAST(:scan_id AS uuid)
        AND es.tenant_id = CAST(:tenant_id AS uuid)
    """)
    scan_row = db.execute(scan_query, {
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not scan_row:
        raise HTTPException(status_code=404, detail="Scan non trouvé")

    if scan_row.status != "SUCCESS":
        raise HTTPException(
            status_code=400,
            detail="Le scan doit être terminé avec succès pour générer un plan d'action"
        )

    code_scan = scan_row.code_scan or f"SCAN_{scan_id[:8].upper()}"
    exposure_score = scan_row.summary.get("exposure_score") if scan_row.summary else None

    # Récupérer l'entité : priorité à request.entity_id, sinon utiliser l'entité du scan
    entity_id = request.entity_id if request.entity_id else (str(scan_row.scan_entity_id) if scan_row.scan_entity_id else None)
    entity_name = None

    if entity_id:
        # Si c'est l'entité du scan, on a déjà le nom
        if scan_row.scan_entity_id and str(scan_row.scan_entity_id) == entity_id:
            entity_name = scan_row.scan_entity_name
        else:
            # Sinon récupérer le nom de l'entité spécifiée dans la request
            entity_query = text("""
                SELECT name FROM ecosystem_entity
                WHERE id = CAST(:entity_id AS uuid)
                AND tenant_id = CAST(:tenant_id AS uuid)
            """)
            entity_result = db.execute(entity_query, {
                "entity_id": entity_id,
                "tenant_id": tenant_id
            }).fetchone()
            if entity_result:
                entity_name = entity_result.name

    # Construire la requête des vulnérabilités
    severity_placeholders = ", ".join([f":sev_{i}" for i in range(len(request.severity_filter))])
    severity_params = {f"sev_{i}": sev for i, sev in enumerate(request.severity_filter)}

    remediated_clause = "" if request.include_remediated else "AND is_remediated = false"

    vuln_query = text(f"""
        SELECT * FROM external_service_vulnerability
        WHERE external_scan_id = CAST(:scan_id AS uuid)
        AND severity IN ({severity_placeholders})
        {remediated_clause}
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

    vuln_rows = db.execute(vuln_query, {"scan_id": scan_id, **severity_params}).fetchall()

    # Créer le plan d'action
    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

    insert_plan_query = text("""
        INSERT INTO scan_action_plan (
            id, scan_id, tenant_id, code_scan, status,
            target_value, target_type, exposure_score,
            total_items, critical_count, high_count, medium_count, low_count,
            generated_at, generated_by, created_at, updated_at
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:scan_id AS uuid),
            CAST(:tenant_id AS uuid),
            :code_scan,
            'DRAFT',
            :target_value,
            :target_type,
            :exposure_score,
            :total_items,
            :critical_count,
            :high_count,
            :medium_count,
            :low_count,
            :generated_at,
            CAST(:generated_by AS uuid),
            :created_at,
            :updated_at
        )
    """)

    # Compter par sévérité
    for vuln in vuln_rows:
        if vuln.severity in severity_counts:
            severity_counts[vuln.severity] += 1

    db.execute(insert_plan_query, {
        "id": plan_id,
        "scan_id": scan_id,
        "tenant_id": tenant_id,
        "code_scan": code_scan,
        "target_value": scan_row.target_value,
        "target_type": scan_row.target_type,
        "exposure_score": exposure_score,
        "total_items": len(vuln_rows),
        "critical_count": severity_counts["CRITICAL"],
        "high_count": severity_counts["HIGH"],
        "medium_count": severity_counts["MEDIUM"],
        "low_count": severity_counts["LOW"],
        "generated_at": now,
        "generated_by": user_id,
        "created_at": now,
        "updated_at": now
    })

    # Créer un dictionnaire des customizations par vulnerability_id
    customizations_map = {}
    if request.customizations:
        for custom in request.customizations:
            customizations_map[custom.vulnerability_id] = custom

    # ========================================================================
    # GÉNÉRATION DES JUSTIFICATIONS IA
    # ========================================================================
    # Préparer les données pour l'IA (anonymisées automatiquement par le service)
    ai_justifications_map: Dict[int, Dict[str, str]] = {}

    if vuln_rows:
        try:
            logger.info(f"🤖 Génération des justifications IA pour {len(vuln_rows)} vulnérabilités...")

            # Préparer les données de vulnérabilités pour l'IA
            vulns_for_ai: List[Dict[str, Any]] = []
            for idx, vuln in enumerate(vuln_rows):
                # Déterminer priorité et délai pour le contexte IA
                custom = customizations_map.get(str(vuln.id))

                if custom and custom.priority:
                    priority = custom.priority
                elif vuln.severity == "CRITICAL":
                    priority = "P1"
                elif vuln.severity == "HIGH":
                    priority = "P1"
                elif vuln.severity == "MEDIUM":
                    priority = "P2"
                else:
                    priority = "P3"

                if custom and custom.recommended_due_days:
                    due_days = custom.recommended_due_days
                elif vuln.severity == "CRITICAL":
                    due_days = 7
                elif vuln.severity == "HIGH":
                    due_days = 14
                elif vuln.severity == "MEDIUM":
                    due_days = 30
                else:
                    due_days = 90

                vulns_for_ai.append({
                    "title": vuln.title,
                    "description": vuln.description or "",
                    "recommendation": vuln.recommendation or "",
                    "severity": vuln.severity,
                    "cvss_score": vuln.cvss_score,
                    "cve_ids": vuln.cve_ids if isinstance(vuln.cve_ids, list) else [],
                    "port": vuln.port,
                    "protocol": vuln.protocol,
                    "service_name": vuln.service_name,
                    "priority": priority,
                    "recommended_due_days": due_days
                })

            # Appeler le service IA (await direct car endpoint async)
            ai_service = ScanAIJustificationService()
            logger.info(f"🤖 Appel du service IA avec {len(vulns_for_ai)} vulnérabilités...")
            logger.info(f"🤖 Première vulnérabilité: {vulns_for_ai[0] if vulns_for_ai else 'aucune'}")

            ai_results = await ai_service.generate_batch_justifications(vulns_for_ai)

            logger.info(f"🤖 Résultats IA reçus: {len(ai_results) if ai_results else 0} justifications")
            if ai_results:
                logger.info(f"🤖 Première justification: {ai_results[0] if ai_results else 'aucune'}")

            # Mapper les résultats par index
            for idx, justifications in enumerate(ai_results):
                ai_justifications_map[idx] = justifications

            logger.info(f"✅ Justifications IA générées pour {len(ai_justifications_map)} vulnérabilités")

        except Exception as e:
            logger.error(f"❌ Erreur lors de la génération des justifications IA: {e}")
            logger.error(f"❌ Traceback complet: {traceback.format_exc()}")
            # Continuer sans justifications IA en cas d'erreur
            ai_justifications_map = {}

    # ========================================================================
    # CRÉATION DES ITEMS
    # ========================================================================
    items = []
    for idx, vuln in enumerate(vuln_rows):
        vuln_id_str = str(vuln.id)

        # Vérifier si une customization existe pour cette vulnérabilité
        custom = customizations_map.get(vuln_id_str)

        # Déterminer la priorité (utiliser customization si disponible)
        if custom and custom.priority:
            priority = custom.priority
        elif vuln.severity == "CRITICAL":
            priority = "P1"
        elif vuln.severity == "HIGH":
            priority = "P1"
        elif vuln.severity == "MEDIUM":
            priority = "P2"
        else:
            priority = "P3"

        # Déterminer les jours recommandés
        if custom and custom.recommended_due_days:
            due_days = custom.recommended_due_days
        elif vuln.severity == "CRITICAL":
            due_days = 7
        elif vuln.severity == "HIGH":
            due_days = 14
        elif vuln.severity == "MEDIUM":
            due_days = 30
        else:
            due_days = 90

        # Appliquer les customizations si disponibles
        item_title = (custom.title if custom and custom.title else vuln.title)
        item_description = (custom.description if custom and custom.description else (vuln.description or "Corriger cette vulnérabilité"))
        item_severity = (custom.severity if custom and custom.severity else vuln.severity)
        item_suggested_role = (custom.suggested_role if custom and custom.suggested_role else ("Administrateur Système" if vuln.port else "Responsable Sécurité"))
        item_entity_id = (custom.entity_id if custom and custom.entity_id else entity_id)
        item_entity_name = (custom.entity_name if custom and custom.entity_name else entity_name)
        item_assigned_user_id = (custom.assigned_user_id if custom and custom.assigned_user_id else None)

        item_id = str(uuid.uuid4())
        code_action = f"ACT_{code_scan}_{idx+1:03d}"

        # Récupérer les justifications IA pour cet item
        item_ai_justifications = ai_justifications_map.get(idx, None)

        insert_item_query = text("""
            INSERT INTO scan_action_plan_item (
                id, scan_action_plan_id, vulnerability_id, tenant_id,
                code_action, status, order_index, included,
                title, description, recommendation,
                port, protocol, service_name, service_version,
                cve_ids, cvss_score,
                severity, priority, recommended_due_days,
                suggested_role, assigned_user_id, entity_id, entity_name,
                ai_justifications,
                created_at, updated_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:plan_id AS uuid),
                CAST(:vulnerability_id AS uuid),
                CAST(:tenant_id AS uuid),
                :code_action,
                'PROPOSED',
                :order_index,
                true,
                :title,
                :description,
                :recommendation,
                :port,
                :protocol,
                :service_name,
                :service_version,
                :cve_ids,
                :cvss_score,
                :severity,
                :priority,
                :recommended_due_days,
                :suggested_role,
                CAST(:assigned_user_id AS uuid),
                CAST(:entity_id AS uuid),
                :entity_name,
                :ai_justifications,
                :created_at,
                :updated_at
            )
        """)

        db.execute(insert_item_query, {
            "id": item_id,
            "plan_id": plan_id,
            "vulnerability_id": vuln_id_str,
            "tenant_id": tenant_id,
            "code_action": code_action,
            "order_index": idx,
            "title": item_title,
            "description": item_description,
            "recommendation": vuln.recommendation,
            "port": vuln.port,
            "protocol": vuln.protocol,
            "service_name": vuln.service_name,
            "service_version": vuln.service_version,
            "cve_ids": json.dumps(vuln.cve_ids if isinstance(vuln.cve_ids, list) else []),
            "cvss_score": vuln.cvss_score,
            "severity": item_severity,
            "priority": priority,
            "recommended_due_days": due_days,
            "suggested_role": item_suggested_role,
            "assigned_user_id": item_assigned_user_id,
            "entity_id": item_entity_id,
            "entity_name": item_entity_name,
            "ai_justifications": json.dumps(item_ai_justifications) if item_ai_justifications else None,
            "created_at": now,
            "updated_at": now
        })

        items.append(ScanActionItemResponse(
            id=item_id,
            vulnerability_id=vuln_id_str,
            code_action=code_action,
            title=item_title,
            description=item_description,
            recommendation=vuln.recommendation,
            severity=item_severity,
            priority=priority,
            recommended_due_days=due_days,
            port=vuln.port,
            service_name=vuln.service_name,
            cve_ids=vuln.cve_ids if isinstance(vuln.cve_ids, list) else [],
            cvss_score=vuln.cvss_score,
            status="PROPOSED",
            included=True,
            entity_id=item_entity_id,
            entity_name=item_entity_name,
            ai_justifications=item_ai_justifications
        ))

    db.commit()

    logger.info(f"📋 Plan d'action créé pour scan {scan_id}: {len(items)} items")

    return ScanActionPlanDetailResponse(
        id=plan_id,
        scan_id=scan_id,
        code_scan=code_scan,
        status="DRAFT",
        target_value=scan_row.target_value,
        target_type=scan_row.target_type,
        exposure_score=exposure_score,
        total_items=len(items),
        critical_count=severity_counts["CRITICAL"],
        high_count=severity_counts["HIGH"],
        medium_count=severity_counts["MEDIUM"],
        low_count=severity_counts["LOW"],
        validated_count=0,
        excluded_count=0,
        items=items,
        generated_at=now.isoformat()
    )


@router.get("/scans/{scan_id}/action-plan", response_model=ScanActionPlanDetailResponse)
async def get_scan_action_plan(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ"))
):
    """
    Récupère le plan d'action d'un scan.

    Returns:
        Plan d'action détaillé avec tous les items
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Récupérer le plan
    plan_query = text("""
        SELECT * FROM scan_action_plan
        WHERE scan_id = CAST(:scan_id AS uuid)
        AND tenant_id = CAST(:tenant_id AS uuid)
    """)
    plan_row = db.execute(plan_query, {
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not plan_row:
        raise HTTPException(status_code=404, detail="Plan d'action non trouvé pour ce scan")

    # Récupérer les items
    items_query = text("""
        SELECT * FROM scan_action_plan_item
        WHERE scan_action_plan_id = CAST(:plan_id AS uuid)
        ORDER BY order_index
    """)
    items_rows = db.execute(items_query, {"plan_id": str(plan_row.id)}).fetchall()

    items = [
        ScanActionItemResponse(
            id=str(row.id),
            vulnerability_id=str(row.vulnerability_id) if row.vulnerability_id else None,
            code_action=row.code_action,
            title=row.title,
            description=row.description,
            recommendation=row.recommendation,
            severity=row.severity,
            priority=row.priority,
            recommended_due_days=row.recommended_due_days,
            port=row.port,
            service_name=row.service_name,
            cve_ids=row.cve_ids if isinstance(row.cve_ids, list) else [],
            cvss_score=row.cvss_score,
            status=row.status,
            included=row.included,
            entity_id=str(row.entity_id) if row.entity_id else None,
            entity_name=row.entity_name,
            ai_justifications=row.ai_justifications if hasattr(row, 'ai_justifications') else None
        )
        for row in items_rows
    ]

    return ScanActionPlanDetailResponse(
        id=str(plan_row.id),
        scan_id=str(plan_row.scan_id),
        code_scan=plan_row.code_scan,
        status=plan_row.status,
        target_value=plan_row.target_value,
        target_type=plan_row.target_type,
        exposure_score=plan_row.exposure_score,
        total_items=plan_row.total_items,
        critical_count=plan_row.critical_count,
        high_count=plan_row.high_count,
        medium_count=plan_row.medium_count,
        low_count=plan_row.low_count,
        validated_count=plan_row.validated_count,
        excluded_count=plan_row.excluded_count,
        items=items,
        generated_at=plan_row.generated_at.isoformat() if plan_row.generated_at else None,
        published_at=plan_row.published_at.isoformat() if plan_row.published_at else None
    )


@router.patch("/scans/{scan_id}/action-plan/items/{item_id}")
async def update_scan_action_plan_item(
    scan_id: str,
    item_id: str,
    request: UpdateScanActionItemRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_WRITE"))
):
    """
    Met à jour un item du plan d'action (validation/exclusion).
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    # Vérifier que l'item existe et appartient au scan
    check_query = text("""
        SELECT sapi.id, sap.status as plan_status
        FROM scan_action_plan_item sapi
        JOIN scan_action_plan sap ON sap.id = sapi.scan_action_plan_id
        WHERE sapi.id = CAST(:item_id AS uuid)
        AND sap.scan_id = CAST(:scan_id AS uuid)
        AND sapi.tenant_id = CAST(:tenant_id AS uuid)
    """)
    item = db.execute(check_query, {
        "item_id": item_id,
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not item:
        raise HTTPException(status_code=404, detail="Item non trouvé")

    if item.plan_status == "PUBLISHED":
        raise HTTPException(status_code=400, detail="Le plan est déjà publié")

    # Construire la mise à jour
    updates = ["updated_at = NOW()"]
    params = {"item_id": item_id}

    if request.included is not None:
        updates.append("included = :included")
        params["included"] = request.included

    if request.status:
        updates.append("status = :status")
        params["status"] = request.status

    if request.entity_id is not None:
        updates.append("entity_id = CAST(:entity_id AS uuid)")
        params["entity_id"] = request.entity_id if request.entity_id else None

        # Récupérer le nom de l'entité
        if request.entity_id:
            entity_query = text("""
                SELECT name FROM ecosystem_entity
                WHERE id = CAST(:entity_id AS uuid)
            """)
            entity_result = db.execute(entity_query, {"entity_id": request.entity_id}).fetchone()
            updates.append("entity_name = :entity_name")
            params["entity_name"] = entity_result.name if entity_result else None

    update_query = text(f"""
        UPDATE scan_action_plan_item
        SET {", ".join(updates)}
        WHERE id = CAST(:item_id AS uuid)
        RETURNING *
    """)

    result = db.execute(update_query, params).fetchone()
    db.commit()

    return {"success": True, "message": "Item mis à jour"}


@router.post("/scans/{scan_id}/publish-actions", response_model=PublishScanActionsResponse)
async def publish_scan_actions(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_WRITE"))
):
    """
    Publie les items validés du plan d'action vers le module Actions.

    Publie tous les items avec status='VALIDATED' ou 'PROPOSED' et included=true
    depuis la table scan_action_plan_item vers published_action.

    Returns:
        Résultat de la publication avec codes d'action générés
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None
    user_id = str(current_user.id) if current_user.id else None

    # Récupérer le plan d'action
    plan_query = text("""
        SELECT sap.*, es.code_scan
        FROM scan_action_plan sap
        JOIN external_scan es ON es.id = sap.scan_id
        WHERE sap.scan_id = CAST(:scan_id AS uuid)
        AND sap.tenant_id = CAST(:tenant_id AS uuid)
    """)
    plan_row = db.execute(plan_query, {
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not plan_row:
        raise HTTPException(
            status_code=404,
            detail="Plan d'action non trouvé. Générez d'abord un plan avec POST /scans/{id}/action-plan"
        )

    if plan_row.status == "PUBLISHED":
        raise HTTPException(
            status_code=400,
            detail="Ce plan d'action a déjà été publié"
        )

    code_scan = plan_row.code_scan or f"SCAN_{scan_id[:8].upper()}"

    # Récupérer les items à publier (included=true et non exclus)
    items_query = text("""
        SELECT * FROM scan_action_plan_item
        WHERE scan_action_plan_id = CAST(:plan_id AS uuid)
        AND included = true
        AND status != 'EXCLUDED'
        ORDER BY order_index
    """)
    items = db.execute(items_query, {"plan_id": str(plan_row.id)}).fetchall()

    if not items:
        raise HTTPException(
            status_code=400,
            detail="Aucun item à publier. Validez au moins un item du plan."
        )

    now = datetime.now(timezone.utc)
    published_count = 0
    action_codes = []

    for item in items:
        # Ignorer si déjà publié
        if item.created_action_id:
            action_codes.append(item.code_action)
            continue

        # Créer l'action publiée
        action_id = str(uuid.uuid4())
        due_date = now + timedelta(days=item.recommended_due_days)

        # Construire le titre
        title = f"[{code_scan}] {item.title}"
        if item.port:
            title += f" (Port {item.port})"

        # Préparer les CVE et le lien source NVD
        cve_ids_list = item.cve_ids if isinstance(item.cve_ids, list) else []
        # Générer le lien NVD pour le premier CVE s'il existe
        cve_source_url = None
        if cve_ids_list and len(cve_ids_list) > 0:
            first_cve = cve_ids_list[0]
            cve_source_url = f"https://nvd.nist.gov/vuln/detail/{first_cve}"

        insert_query = text("""
            INSERT INTO published_action (
                id, source_type, scan_id, scan_action_plan_item_id,
                tenant_id, code_action,
                title, description, objective, deliverables,
                severity, priority, status,
                suggested_role, assigned_user_id, entity_id, entity_name,
                due_date, recommended_due_days,
                source_question_ids, control_point_ids,
                cve_ids, cvss_score, cve_source_url,
                ai_justifications,
                published_at, published_by, created_at, updated_at
            ) VALUES (
                CAST(:id AS uuid),
                'scan',
                CAST(:scan_id AS uuid),
                CAST(:item_id AS uuid),
                CAST(:tenant_id AS uuid),
                :code_action,
                :title,
                :description,
                :objective,
                :deliverables,
                :severity,
                :priority,
                'pending',
                :suggested_role,
                CAST(:assigned_user_id AS uuid),
                CAST(:entity_id AS uuid),
                :entity_name,
                :due_date,
                :recommended_due_days,
                ARRAY[]::uuid[],
                ARRAY[]::uuid[],
                :cve_ids,
                :cvss_score,
                :cve_source_url,
                :ai_justifications,
                :published_at,
                CAST(:published_by AS uuid),
                :created_at,
                :updated_at
            )
        """)

        db.execute(insert_query, {
            "id": action_id,
            "scan_id": scan_id,
            "item_id": str(item.id),
            "tenant_id": tenant_id,
            "code_action": item.code_action,
            "title": title,
            "description": item.description,
            "objective": item.recommendation or f"Corriger la vulnérabilité {item.title}",
            "deliverables": "Preuve de correction (capture d'écran, rapport de scan de validation)",
            "severity": item.severity.lower() if item.severity else "medium",
            "priority": item.priority,
            "suggested_role": item.suggested_role or "Responsable Sécurité",
            "assigned_user_id": str(item.assigned_user_id) if item.assigned_user_id else None,
            "entity_id": str(item.entity_id) if item.entity_id else None,
            "entity_name": item.entity_name,
            "due_date": due_date,
            "recommended_due_days": item.recommended_due_days,
            "cve_ids": cve_ids_list if cve_ids_list else None,
            "cvss_score": item.cvss_score,
            "cve_source_url": cve_source_url,
            # Copier les justifications IA générées depuis scan_action_plan_item
            "ai_justifications": json.dumps(item.ai_justifications) if hasattr(item, 'ai_justifications') and item.ai_justifications else None,
            "published_at": now,
            "published_by": user_id,
            "created_at": now,
            "updated_at": now
        })

        # Mettre à jour l'item avec l'ID de l'action créée
        update_item_query = text("""
            UPDATE scan_action_plan_item
            SET created_action_id = CAST(:action_id AS uuid),
                status = 'PUBLISHED',
                updated_at = NOW()
            WHERE id = CAST(:item_id AS uuid)
        """)
        db.execute(update_item_query, {
            "action_id": action_id,
            "item_id": str(item.id)
        })

        action_codes.append(item.code_action)
        published_count += 1

    # Mettre à jour le statut du plan
    update_plan_query = text("""
        UPDATE scan_action_plan
        SET status = 'PUBLISHED',
            published_at = :now,
            published_by = CAST(:user_id AS uuid),
            updated_at = :now
        WHERE id = CAST(:plan_id AS uuid)
    """)
    db.execute(update_plan_query, {
        "plan_id": str(plan_row.id),
        "now": now,
        "user_id": user_id
    })

    db.commit()

    logger.info(f"✅ {published_count} actions publiées depuis plan {plan_row.id} ({code_scan})")

    return PublishScanActionsResponse(
        success=True,
        message=f"{published_count} action(s) publiée(s) avec succès vers le module Actions",
        published_count=published_count,
        code_scan=code_scan,
        action_codes=action_codes
    )


class UnpublishScanActionsResponse(BaseModel):
    """Réponse de dépublication des actions."""
    success: bool
    message: str
    deleted_count: int
    code_scan: str


@router.post("/scans/{scan_id}/unpublish-actions", response_model=UnpublishScanActionsResponse)
async def unpublish_scan_actions(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_WRITE"))
):
    """
    Dépublie les actions d'un plan et supprime les published_action associées.

    Remet le plan en statut DRAFT pour permettre une nouvelle génération.
    Supprime les actions de la table published_action.

    Returns:
        Résultat de la dépublication avec nombre d'actions supprimées
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None
    user_id = str(current_user.id) if current_user.id else None

    # Récupérer le plan d'action
    plan_query = text("""
        SELECT sap.*, es.code_scan
        FROM scan_action_plan sap
        JOIN external_scan es ON es.id = sap.scan_id
        WHERE sap.scan_id = CAST(:scan_id AS uuid)
        AND sap.tenant_id = CAST(:tenant_id AS uuid)
    """)
    plan_row = db.execute(plan_query, {
        "scan_id": scan_id,
        "tenant_id": tenant_id
    }).fetchone()

    if not plan_row:
        raise HTTPException(
            status_code=404,
            detail="Plan d'action non trouvé pour ce scan"
        )

    if plan_row.status != "PUBLISHED":
        raise HTTPException(
            status_code=400,
            detail="Ce plan d'action n'est pas publié"
        )

    code_scan = plan_row.code_scan or f"SCAN_{scan_id[:8].upper()}"

    # Supprimer les published_action liées à ce plan
    delete_actions_query = text("""
        DELETE FROM published_action
        WHERE scan_action_plan_item_id IN (
            SELECT id FROM scan_action_plan_item
            WHERE scan_action_plan_id = CAST(:plan_id AS uuid)
        )
        AND tenant_id = CAST(:tenant_id AS uuid)
    """)
    result = db.execute(delete_actions_query, {
        "plan_id": str(plan_row.id),
        "tenant_id": tenant_id
    })
    deleted_count = result.rowcount

    # Réinitialiser les items du plan (supprimer created_action_id, remettre status à PROPOSED)
    reset_items_query = text("""
        UPDATE scan_action_plan_item
        SET created_action_id = NULL,
            status = 'PROPOSED',
            updated_at = NOW()
        WHERE scan_action_plan_id = CAST(:plan_id AS uuid)
    """)
    db.execute(reset_items_query, {"plan_id": str(plan_row.id)})

    # Supprimer le plan pour permettre une nouvelle génération
    delete_items_query = text("""
        DELETE FROM scan_action_plan_item
        WHERE scan_action_plan_id = CAST(:plan_id AS uuid)
    """)
    db.execute(delete_items_query, {"plan_id": str(plan_row.id)})

    delete_plan_query = text("""
        DELETE FROM scan_action_plan
        WHERE id = CAST(:plan_id AS uuid)
    """)
    db.execute(delete_plan_query, {"plan_id": str(plan_row.id)})

    db.commit()

    logger.info(f"🗑️ Plan {plan_row.id} dépublié: {deleted_count} actions supprimées")

    return UnpublishScanActionsResponse(
        success=True,
        message=f"{deleted_count} action(s) supprimée(s). Vous pouvez maintenant générer un nouveau plan.",
        deleted_count=deleted_count,
        code_scan=code_scan
    )


# ==============================================================================
# ECOSYSTEM VIEW - VUE ÉCOSYSTÈME
# ==============================================================================

class EntityScanDataResponse(BaseModel):
    """Données de scan agrégées par entité pour la vue écosystème."""
    entity_id: str
    entity_name: str
    entity_type: str  # 'internal' ou 'external' basé sur stakeholder_type
    targets_count: int
    scans_count: int
    average_cvss: float
    total_vulnerabilities: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    grade: str  # A, B, C, D, E
    last_scan_at: Optional[str] = None


class EcosystemStatsResponse(BaseModel):
    """Statistiques globales de l'écosystème."""
    total_entities: int
    total_targets: int
    total_vulnerabilities: int
    average_grade: str
    median_cvss: float
    median_cve_count: float
    entities_by_grade: dict


class EcosystemResponse(BaseModel):
    """Réponse complète de la vue écosystème."""
    entities: List[EntityScanDataResponse]
    stats: EcosystemStatsResponse


def _calculate_grade(cvss: float) -> str:
    """
    Calcule la note A-E basée sur le score CVSS moyen pondéré.
    A: 0-1.9, B: 2-3.9, C: 4-5.9, D: 6-7.9, E: 8-10
    """
    if cvss < 2:
        return 'A'
    if cvss < 4:
        return 'B'
    if cvss < 6:
        return 'C'
    if cvss < 8:
        return 'D'
    return 'E'


def _calculate_weighted_cvss(critical: int, high: int, medium: int, low: int) -> float:
    """
    Calcule le score CVSS moyen pondéré selon les coefficients du CDC:
    - Critique (9-10): coefficient 10
    - Élevée (7-8.9): coefficient 7
    - Moyenne (4-6.9): coefficient 4
    - Faible (0.1-3.9): coefficient 1
    """
    # Scores CVSS moyens par sévérité
    critical_score = 9.5  # Moyenne de 9-10
    high_score = 8.0      # Moyenne de 7-8.9
    medium_score = 5.5    # Moyenne de 4-6.9
    low_score = 2.0       # Moyenne de 0.1-3.9

    # Coefficients de pondération
    critical_weight = 10
    high_weight = 7
    medium_weight = 4
    low_weight = 1

    total_weighted = (
        critical * critical_score * critical_weight +
        high * high_score * high_weight +
        medium * medium_score * medium_weight +
        low * low_score * low_weight
    )

    total_weight = (
        critical * critical_weight +
        high * high_weight +
        medium * medium_weight +
        low * low_weight
    )

    if total_weight == 0:
        return 0.0

    return round(total_weighted / total_weight, 2)


@router.get("/ecosystem", response_model=EcosystemResponse)
async def get_ecosystem_view(
    entity_type: Optional[str] = Query(None, description="Filtrer par type: internal, external"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("SCANNER_READ"))
):
    """
    Récupère la vue écosystème avec les données agrégées par entité.

    Retourne pour chaque entité ayant des cibles scannées:
    - Nombre de cibles et scans
    - Score CVSS moyen pondéré
    - Nombre de vulnérabilités par sévérité
    - Note de sécurité (A-E)
    - Date du dernier scan

    Également les statistiques globales:
    - Médianes pour le graphique en nuage de points
    - Distribution par note
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else None

    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID requis")

    # Requête pour agréger les données par entité
    # On récupère les entités qui ont des cibles avec des scans
    query = text("""
        WITH entity_vulns AS (
            -- Agrégation des vulnérabilités par entité
            SELECT
                ee.id as entity_id,
                ee.name as entity_name,
                ee.stakeholder_type,
                COUNT(DISTINCT et.id) as targets_count,
                COUNT(DISTINCT es.id) as scans_count,
                COUNT(CASE WHEN esv.severity = 'CRITICAL' AND esv.is_remediated = false THEN 1 END) as critical_count,
                COUNT(CASE WHEN esv.severity = 'HIGH' AND esv.is_remediated = false THEN 1 END) as high_count,
                COUNT(CASE WHEN esv.severity = 'MEDIUM' AND esv.is_remediated = false THEN 1 END) as medium_count,
                COUNT(CASE WHEN esv.severity = 'LOW' AND esv.is_remediated = false THEN 1 END) as low_count,
                COUNT(CASE WHEN esv.is_remediated = false THEN 1 END) as total_vulns,
                MAX(es.finished_at) as last_scan_at
            FROM ecosystem_entity ee
            JOIN external_target et ON et.entity_id = ee.id AND et.deleted_at IS NULL
            LEFT JOIN external_scan es ON es.external_target_id = et.id AND es.status = 'SUCCESS'
            LEFT JOIN external_service_vulnerability esv ON esv.external_scan_id = es.id
            WHERE ee.tenant_id = CAST(:tenant_id AS uuid)
            AND ee.is_active = true
            GROUP BY ee.id, ee.name, ee.stakeholder_type
            HAVING COUNT(DISTINCT et.id) > 0
        )
        SELECT
            entity_id,
            entity_name,
            stakeholder_type,
            targets_count,
            scans_count,
            critical_count,
            high_count,
            medium_count,
            low_count,
            total_vulns,
            last_scan_at
        FROM entity_vulns
        ORDER BY
            -- Prioriser les entités avec le plus de vulnérabilités critiques
            critical_count DESC,
            high_count DESC,
            total_vulns DESC,
            entity_name
    """)

    rows = db.execute(query, {"tenant_id": tenant_id}).fetchall()

    entities = []
    cvss_scores = []
    cve_counts = []
    grades_count = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'E': 0}

    for row in rows:
        # Déterminer le type (internal si CLIENT sinon external)
        is_internal = row.stakeholder_type in ('CLIENT', 'INTERNAL', None)
        entity_type_value = 'internal' if is_internal else 'external'

        # Filtrer par type si demandé
        if entity_type and entity_type != entity_type_value:
            continue

        # Calculer le CVSS pondéré
        weighted_cvss = _calculate_weighted_cvss(
            row.critical_count or 0,
            row.high_count or 0,
            row.medium_count or 0,
            row.low_count or 0
        )

        # Calculer la note
        grade = _calculate_grade(weighted_cvss)
        grades_count[grade] += 1

        # Stocker pour calcul des médianes
        cvss_scores.append(weighted_cvss)
        cve_counts.append(row.total_vulns or 0)

        entities.append(EntityScanDataResponse(
            entity_id=str(row.entity_id),
            entity_name=row.entity_name,
            entity_type=entity_type_value,
            targets_count=row.targets_count or 0,
            scans_count=row.scans_count or 0,
            average_cvss=weighted_cvss,
            total_vulnerabilities=row.total_vulns or 0,
            critical_count=row.critical_count or 0,
            high_count=row.high_count or 0,
            medium_count=row.medium_count or 0,
            low_count=row.low_count or 0,
            grade=grade,
            last_scan_at=row.last_scan_at.isoformat() if row.last_scan_at else None
        ))

    # Calculer les médianes pour le graphique en nuage de points
    def median(lst):
        if not lst:
            return 0.0
        sorted_lst = sorted(lst)
        n = len(sorted_lst)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_lst[mid - 1] + sorted_lst[mid]) / 2
        return sorted_lst[mid]

    median_cvss = median(cvss_scores)
    median_cve = median(cve_counts)

    # Calculer la note moyenne
    total_grade_score = sum({
        'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5
    }[e.grade] for e in entities)
    avg_grade_score = total_grade_score / len(entities) if entities else 0
    if avg_grade_score < 1.5:
        avg_grade = 'A'
    elif avg_grade_score < 2.5:
        avg_grade = 'B'
    elif avg_grade_score < 3.5:
        avg_grade = 'C'
    elif avg_grade_score < 4.5:
        avg_grade = 'D'
    else:
        avg_grade = 'E'

    stats = EcosystemStatsResponse(
        total_entities=len(entities),
        total_targets=sum(e.targets_count for e in entities),
        total_vulnerabilities=sum(e.total_vulnerabilities for e in entities),
        average_grade=avg_grade,
        median_cvss=round(median_cvss, 2),
        median_cve_count=round(median_cve, 1),
        entities_by_grade=grades_count
    )

    logger.info(f"📊 Vue écosystème: {len(entities)} entités, médiane CVSS={median_cvss:.2f}, médiane CVE={median_cve:.1f}")

    return EcosystemResponse(
        entities=entities,
        stats=stats
    )
