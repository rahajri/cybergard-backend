"""
API endpoints pour le module EBIOS RM

Analyse de risques selon méthodologie ANSSI avec 5 ateliers:
- AT1: Cadrage et socle de sécurité
- AT2: Sources de risques
- AT3: Scénarios stratégiques
- AT4: Scénarios opérationnels
- AT5: Traitement des risques

Toutes les routes sont sécurisées par tenant et permissions RBAC.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database import get_db
from src.dependencies_keycloak import require_permission
from src.models.audit import User
from src.schemas.ebios import (
    # Project schemas
    RiskProjectCreate,
    RiskProjectUpdate,
    RiskProjectResponse,
    RiskProjectListResponse,
    # Workshop schemas
    WorkshopResponse,
    # AT1 schemas
    BusinessValueCreate,
    BusinessValueUpdate,
    BusinessValueResponse,
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    FearedEventCreate,
    FearedEventUpdate,
    FearedEventResponse,
    AT1Response,
    # AT2 schemas
    RiskSourceCreate,
    RiskSourceUpdate,
    RiskSourceResponse,
    RiskSourceObjectiveCreate,
    RiskSourceObjectiveResponse,
    AT2Response,
    # AT3 schemas
    StrategicScenarioCreate,
    StrategicScenarioUpdate,
    StrategicScenarioResponse,
    AT3Response,
    # AT4 schemas
    OperationalScenarioCreate,
    OperationalScenarioUpdate,
    OperationalScenarioResponse,
    OperationalStepCreate,
    OperationalStepResponse,
    AT4Response,
    # AT5 schemas
    RiskResponse,
    RiskUpdateResidual,
    MatrixResponse,
    MatrixCell,
    AT5Response,
    # Other schemas
    AIGenerateRequest,
    AIGenerateResponse,
    FreezeRequest,
    FreezeResponse,
    ActionLinkCreate,
    ActionLinkResponse,
    # AI Chat schemas
    AIChatRequest,
    AIChatResponse,
    # Enums
    ProjectStatus,
    WorkshopType,
    WorkshopStatus,
    CriticalityLevel,
)
import httpx
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk", tags=["EBIOS RM"])


# ==============================================================================
# LIMITES EBIOS RM - Règles fonctionnelles
# ==============================================================================

# Limites maximales (blocage dur)
MAX_BUSINESS_VALUES = 15
MAX_ASSETS = 20
MAX_FEARED_EVENTS = 15
MAX_RISK_SOURCES = 15

# Plages recommandées (min, max)
RECOMMENDED_BUSINESS_VALUES = (5, 10)
RECOMMENDED_ASSETS = (8, 15)
RECOMMENDED_FEARED_EVENTS = (5, 10)
RECOMMENDED_RISK_SOURCES = (5, 12)

# Codes d'avertissement et d'erreur
WARNING_CODES = {
    "business_values": "BUSINESS_VALUE_OVER_RECOMMENDED",
    "assets": "ASSET_OVER_RECOMMENDED",
    "feared_events": "FEARED_EVENT_OVER_RECOMMENDED",
    "risk_sources": "RISK_SOURCE_OVER_RECOMMENDED"
}

ERROR_CODES = {
    "business_values": "BUSINESS_VALUE_LIMIT_REACHED",
    "assets": "ASSET_LIMIT_REACHED",
    "feared_events": "FEARED_EVENT_LIMIT_REACHED",
    "risk_sources": "RISK_SOURCE_LIMIT_REACHED"
}


def get_element_limits(element_type: str) -> dict:
    """
    Retourne les limites pour un type d'élément donné.

    Returns:
        Dict avec max_hard, recommended_min, recommended_max
    """
    limits = {
        "business_values": {
            "max_hard": MAX_BUSINESS_VALUES,
            "recommended_min": RECOMMENDED_BUSINESS_VALUES[0],
            "recommended_max": RECOMMENDED_BUSINESS_VALUES[1],
            "label_singular": "valeur métier",
            "label_plural": "valeurs métier"
        },
        "assets": {
            "max_hard": MAX_ASSETS,
            "recommended_min": RECOMMENDED_ASSETS[0],
            "recommended_max": RECOMMENDED_ASSETS[1],
            "label_singular": "bien support",
            "label_plural": "biens supports"
        },
        "feared_events": {
            "max_hard": MAX_FEARED_EVENTS,
            "recommended_min": RECOMMENDED_FEARED_EVENTS[0],
            "recommended_max": RECOMMENDED_FEARED_EVENTS[1],
            "label_singular": "événement redouté",
            "label_plural": "événements redoutés"
        },
        "risk_sources": {
            "max_hard": MAX_RISK_SOURCES,
            "recommended_min": RECOMMENDED_RISK_SOURCES[0],
            "recommended_max": RECOMMENDED_RISK_SOURCES[1],
            "label_singular": "source de risque",
            "label_plural": "sources de risques"
        }
    }
    return limits.get(element_type, {})


def check_element_count(current_count: int, element_type: str) -> dict:
    """
    Vérifie si le nombre d'éléments est dans les limites.

    Returns:
        Dict avec:
        - can_add: bool - Si on peut ajouter un élément
        - warning: dict | None - Avertissement si dépassement recommandé
        - error: dict | None - Erreur si limite atteinte
    """
    limits = get_element_limits(element_type)
    if not limits:
        return {"can_add": True, "warning": None, "error": None}

    max_hard = limits["max_hard"]
    rec_max = limits["recommended_max"]
    rec_min = limits["recommended_min"]
    label_plural = limits["label_plural"]

    result = {"can_add": True, "warning": None, "error": None}

    # Blocage dur si limite max atteinte
    if current_count >= max_hard:
        result["can_add"] = False
        result["error"] = {
            "code": ERROR_CODES.get(element_type, "LIMIT_REACHED"),
            "message": f"Limite atteinte : pour garantir une analyse lisible, le nombre de {label_plural} est limité à {max_hard}. Supprimez ou fusionnez certains éléments avant d'en ajouter de nouveaux."
        }
    # Avertissement soft si au-dessus de la recommandation
    elif current_count >= rec_max:
        result["warning"] = {
            "code": WARNING_CODES.get(element_type, "OVER_RECOMMENDED"),
            "message": f"Vous avez défini {current_count} {label_plural}. Au-delà de {rec_max}, l'analyse peut devenir difficile à exploiter. Vous pouvez continuer, mais pensez à regrouper ou fusionner les éléments proches.",
            "recommended_range": f"{rec_min}-{rec_max}"
        }

    return result


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def calculate_criticality_level(score: int) -> str:
    """Calcule le niveau de criticité à partir du score"""
    if score <= 4:
        return CriticalityLevel.LOW.value
    elif score <= 8:
        return CriticalityLevel.MODERATE.value
    elif score <= 12:
        return CriticalityLevel.HIGH.value
    else:
        return CriticalityLevel.CRITICAL.value


def get_matrix_color(score: int) -> str:
    """Retourne la couleur CSS pour un score de risque"""
    if score <= 4:
        return "#22c55e"  # green-500
    elif score <= 8:
        return "#eab308"  # yellow-500
    elif score <= 12:
        return "#f97316"  # orange-500
    else:
        return "#ef4444"  # red-500


def parse_ai_messages_for_at1(ai_context: dict) -> dict:
    """
    Parse les messages de l'IA pour extraire les éléments de l'Atelier 1.

    Retourne un dict avec:
    - business_values: Liste de {label, description, criticality}
    - assets: Liste de {label, type, description, criticality}
    - feared_events: Liste de {label, description, severity, dimension}
    """
    result = {
        "business_values": [],
        "assets": [],
        "feared_events": []
    }

    if not ai_context or "messages" not in ai_context:
        return result

    # Concaténer toutes les réponses de l'assistant
    assistant_text = ""
    for msg in ai_context.get("messages", []):
        if msg.get("role") == "assistant":
            assistant_text += "\n\n" + msg.get("content", "")

    if not assistant_text:
        return result

    # Patterns pour détecter les sections
    # On cherche les listes à puces ou numérotées après les titres de section

    # ========== VALEURS MÉTIER ==========
    # Cherche "Valeurs métier" suivi de listes
    vm_pattern = r"(?:Valeurs?\s*m[ée]tier[^:]*:|valeurs?\s*m[ée]tier[^:]*:)(.*?)(?=(?:Biens?\s*supports?|Événements?\s*redout|Sources?\s*de\s*risques?|$))"
    vm_match = re.search(vm_pattern, assistant_text, re.IGNORECASE | re.DOTALL)

    if vm_match:
        vm_section = vm_match.group(1)
        # Extraire les éléments (puces • ou - ou numéros)
        items = re.findall(r'[•\-]\s*([^\n•\-]+)|^\d+\.\s*([^\n]+)', vm_section, re.MULTILINE)
        for item in items:
            text = (item[0] or item[1]).strip()
            if text and len(text) > 3:
                # Nettoyer et extraire la criticité si présente
                criticality = 3  # Par défaut: moyen-élevé
                crit_match = re.search(r'\((?:Criticité|Gravité)\s*:\s*(\d)/4\)', text, re.IGNORECASE)
                if crit_match:
                    criticality = int(crit_match.group(1))
                    text = re.sub(r'\s*\((?:Criticité|Gravité)\s*:\s*\d/4\)', '', text).strip()

                result["business_values"].append({
                    "label": text[:255],
                    "description": None,
                    "criticality": criticality
                })

    # ========== BIENS SUPPORTS ==========
    bs_pattern = r"(?:Biens?\s*supports?[^:]*:|biens?\s*supports?[^:]*:)(.*?)(?=(?:Événements?\s*redout|Sources?\s*de\s*risques?|Valeurs?\s*m[ée]tier|$))"
    bs_match = re.search(bs_pattern, assistant_text, re.IGNORECASE | re.DOTALL)

    if bs_match:
        bs_section = bs_match.group(1)
        items = re.findall(r'[•\-]\s*([^\n•\-]+)|^\d+\.\s*([^\n]+)', bs_section, re.MULTILINE)
        for item in items:
            text = (item[0] or item[1]).strip()
            if text and len(text) > 3:
                criticality = 3
                crit_match = re.search(r'\((?:Criticité|Gravité)\s*:\s*(\d)/4\)', text, re.IGNORECASE)
                if crit_match:
                    criticality = int(crit_match.group(1))
                    text = re.sub(r'\s*\((?:Criticité|Gravité)\s*:\s*\d/4\)', '', text).strip()

                # Déterminer le type (SI, Réseau, Application, etc.)
                asset_type = "SYSTEM"  # Par défaut
                text_lower = text.lower()
                if any(k in text_lower for k in ["serveur", "server", "infrastructure", "datacenter"]):
                    asset_type = "INFRASTRUCTURE"
                elif any(k in text_lower for k in ["application", "logiciel", "software", "erp", "crm"]):
                    asset_type = "APPLICATION"
                elif any(k in text_lower for k in ["réseau", "network", "firewall", "vpn", "routeur"]):
                    asset_type = "NETWORK"
                elif any(k in text_lower for k in ["données", "data", "base de données", "database"]):
                    asset_type = "DATA"
                elif any(k in text_lower for k in ["personnel", "équipe", "utilisateur", "admin"]):
                    asset_type = "HUMAN"

                result["assets"].append({
                    "label": text[:255],
                    "type": asset_type,
                    "description": None,
                    "criticality": criticality
                })

    # ========== ÉVÉNEMENTS REDOUTÉS ==========
    er_pattern = r"(?:Événements?\s*redout[ée]s?[^:]*:|événements?\s*redout[ée]s?[^:]*:)(.*?)(?=(?:Sources?\s*de\s*risques?|Recommandations?|En\s*résumé|Conclusion|$))"
    er_match = re.search(er_pattern, assistant_text, re.IGNORECASE | re.DOTALL)

    if er_match:
        er_section = er_match.group(1)
        items = re.findall(r'[•\-]\s*([^\n•\-]+)|^\d+\.\s*([^\n]+)', er_section, re.MULTILINE)
        for item in items:
            text = (item[0] or item[1]).strip()
            if text and len(text) > 3:
                severity = 3  # Par défaut
                sev_match = re.search(r'\((?:Gravité|Sévérité)\s*:\s*(\d)/4\)', text, re.IGNORECASE)
                if sev_match:
                    severity = int(sev_match.group(1))
                    text = re.sub(r'\s*\((?:Gravité|Sévérité)\s*:\s*\d/4\)', '', text).strip()

                # Déterminer la dimension de sécurité (C, I, A)
                dimension = "AVAILABILITY"  # Par défaut
                text_lower = text.lower()
                if any(k in text_lower for k in ["confidentialité", "fuite", "vol de données", "divulgation", "accès non autorisé"]):
                    dimension = "CONFIDENTIALITY"
                elif any(k in text_lower for k in ["intégrité", "modification", "altération", "corruption", "falsification"]):
                    dimension = "INTEGRITY"
                elif any(k in text_lower for k in ["disponibilité", "indisponibilité", "interruption", "déni de service", "panne"]):
                    dimension = "AVAILABILITY"

                result["feared_events"].append({
                    "label": text[:255],
                    "description": None,
                    "severity": severity,
                    "dimension": dimension
                })

    # ========== LIMITER AUX RECOMMANDATIONS EBIOS RM ==========
    # Appliquer les limites pour éviter de surcharger l'analyse
    # On prend les N premiers éléments (le plus souvent les plus pertinents car listés en premier)
    max_bv = RECOMMENDED_BUSINESS_VALUES[1]  # 10
    max_assets = RECOMMENDED_ASSETS[1]  # 15
    max_fe = RECOMMENDED_FEARED_EVENTS[1]  # 10

    if len(result["business_values"]) > max_bv:
        logger.info(f"⚠️ Limitation des valeurs métier: {len(result['business_values'])} → {max_bv}")
        result["business_values"] = result["business_values"][:max_bv]

    if len(result["assets"]) > max_assets:
        logger.info(f"⚠️ Limitation des biens supports: {len(result['assets'])} → {max_assets}")
        result["assets"] = result["assets"][:max_assets]

    if len(result["feared_events"]) > max_fe:
        logger.info(f"⚠️ Limitation des événements redoutés: {len(result['feared_events'])} → {max_fe}")
        result["feared_events"] = result["feared_events"][:max_fe]

    logger.info(f"📊 Parsing IA: {len(result['business_values'])} valeurs métier, "
                f"{len(result['assets'])} biens supports, {len(result['feared_events'])} événements redoutés")

    return result


def get_next_code(db: Session, table: str, prefix: str, project_id: str) -> str:
    """
    Génère le prochain code pour une table donnée (VM01, BS02, SR03, etc.)
    """
    result = db.execute(text(f"""
        SELECT MAX(CAST(SUBSTRING(code FROM 3) AS INTEGER)) as max_num
        FROM {table}
        WHERE project_id = CAST(:project_id AS uuid) AND code LIKE :prefix
    """), {"project_id": project_id, "prefix": f"{prefix}%"}).fetchone()

    next_num = (result.max_num or 0) + 1 if result else 1
    return f"{prefix}{next_num:02d}"


def populate_at1_from_ai(db: Session, project_id: str, ai_data: dict) -> None:
    """
    Insère les données extraites de l'IA dans les tables AT1.
    """
    # Insérer les valeurs métier
    for idx, bv in enumerate(ai_data.get("business_values", []), 1):
        try:
            code = f"VM{idx:02d}"
            insert_query = text("""
                INSERT INTO risk_business_value (id, project_id, code, label, description, criticality, order_index, source, created_at)
                VALUES (CAST(:id AS uuid), CAST(:project_id AS uuid), :code, :label, :description, :criticality, :order_index, 'AI', NOW())
            """)
            db.execute(insert_query, {
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "code": code,
                "label": bv["label"],
                "description": bv.get("description"),
                "criticality": bv.get("criticality", 3),
                "order_index": idx
            })
        except Exception as e:
            logger.warning(f"⚠️ Erreur insertion valeur métier: {e}")

    # Insérer les biens supports
    for idx, asset in enumerate(ai_data.get("assets", []), 1):
        try:
            code = f"BS{idx:02d}"
            insert_query = text("""
                INSERT INTO risk_asset (id, project_id, code, label, type, description, criticality, order_index, source, created_at)
                VALUES (CAST(:id AS uuid), CAST(:project_id AS uuid), :code, :label, :type, :description, :criticality, :order_index, 'AI', NOW())
            """)
            db.execute(insert_query, {
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "code": code,
                "label": asset["label"],
                "type": asset.get("type", "SYSTEM"),
                "description": asset.get("description"),
                "criticality": asset.get("criticality", 3),
                "order_index": idx
            })
        except Exception as e:
            logger.warning(f"⚠️ Erreur insertion bien support: {e}")

    # Insérer les événements redoutés
    for idx, fe in enumerate(ai_data.get("feared_events", []), 1):
        try:
            code = f"ER{idx:02d}"
            insert_query = text("""
                INSERT INTO risk_feared_event (id, project_id, code, label, description, dimension, severity, order_index, source, created_at)
                VALUES (CAST(:id AS uuid), CAST(:project_id AS uuid), :code, :label, :description, :dimension, :severity, :order_index, 'AI', NOW())
            """)
            db.execute(insert_query, {
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "code": code,
                "label": fe["label"],
                "description": fe.get("description"),
                "dimension": fe.get("dimension", "AVAILABILITY"),
                "severity": fe.get("severity", 3),
                "order_index": idx
            })
        except Exception as e:
            logger.warning(f"⚠️ Erreur insertion événement redouté: {e}")

    db.commit()
    logger.info(f"✅ AT1 pré-rempli pour projet {project_id}")


def ensure_workshops_exist(db: Session, project_id: UUID) -> None:
    """Crée les 5 ateliers s'ils n'existent pas déjà"""
    for workshop_type in ["AT1", "AT2", "AT3", "AT4", "AT5"]:
        check_query = text("""
            SELECT id FROM risk_workshop
            WHERE project_id = CAST(:project_id AS uuid) AND type = :type
        """)
        result = db.execute(check_query, {
            "project_id": str(project_id),
            "type": workshop_type
        }).fetchone()

        if not result:
            insert_query = text("""
                INSERT INTO risk_workshop (id, project_id, type, status, completion_percent, created_at)
                VALUES (CAST(:id AS uuid), CAST(:project_id AS uuid), :type, 'NOT_STARTED', 0, NOW())
            """)
            db.execute(insert_query, {
                "id": str(uuid.uuid4()),
                "project_id": str(project_id),
                "type": workshop_type
            })
    db.commit()


# ==============================================================================
# HELPER: UPDATE WORKSHOP PROGRESS
# ==============================================================================

def update_workshop_progress(db: Session, project_id: str, workshop_type: str = None):
    """
    Met à jour le pourcentage de complétion d'un ou plusieurs ateliers.

    Logique de calcul:
    - AT1: 33% valeurs métier + 33% événements redoutés + 34% biens supports (si > 0)
    - AT2: 100% si au moins 1 source de risque
    - AT3: 100% si au moins 1 scénario stratégique
    - AT4: 100% si au moins 1 scénario opérationnel
    - AT5: % de scénarios évalués (avec gravité ET vraisemblance) ou 100% si snapshot existe
    """
    try:
        # Compter les éléments pour chaque atelier
        counts_query = text("""
            SELECT
                (SELECT COUNT(*) FROM risk_business_value WHERE project_id = CAST(:project_id AS uuid)) as business_values,
                (SELECT COUNT(*) FROM risk_feared_event WHERE project_id = CAST(:project_id AS uuid)) as feared_events,
                (SELECT COUNT(*) FROM risk_asset WHERE project_id = CAST(:project_id AS uuid)) as assets,
                (SELECT COUNT(*) FROM risk_source WHERE project_id = CAST(:project_id AS uuid)) as risk_sources,
                (SELECT COUNT(*) FROM risk_strategic_scenario WHERE project_id = CAST(:project_id AS uuid)) as strategic_scenarios,
                (SELECT COUNT(*) FROM risk_operational_scenario WHERE project_id = CAST(:project_id AS uuid)) as operational_scenarios,
                (SELECT COUNT(*) FROM risk_matrix_snapshot WHERE project_id = CAST(:project_id AS uuid)) as matrix_snapshots,
                (SELECT COUNT(*) FROM risk_strategic_scenario WHERE project_id = CAST(:project_id AS uuid) AND severity IS NOT NULL AND likelihood_raw IS NOT NULL) as evaluated_strategic,
                (SELECT COUNT(*) FROM risk_operational_scenario WHERE project_id = CAST(:project_id AS uuid) AND severity IS NOT NULL AND likelihood IS NOT NULL) as evaluated_operational
        """)

        counts = db.execute(counts_query, {"project_id": str(project_id)}).fetchone()

        # Calculer les progressions
        progressions = {}

        # AT1: Valeurs métier (33%) + Événements redoutés (33%) + Biens supports (34%)
        at1_progress = 0
        if counts.business_values > 0:
            at1_progress += 33
        if counts.feared_events > 0:
            at1_progress += 33
        if counts.assets > 0:
            at1_progress += 34
        progressions['AT1'] = at1_progress

        # AT2: 100% si sources de risques
        progressions['AT2'] = 100 if counts.risk_sources > 0 else 0

        # AT3: 100% si scénarios stratégiques
        progressions['AT3'] = 100 if counts.strategic_scenarios > 0 else 0

        # AT4: 100% si scénarios opérationnels
        progressions['AT4'] = 100 if counts.operational_scenarios > 0 else 0

        # AT5: Basé sur les scénarios évalués (avec gravité et vraisemblance)
        # 100% si tous les scénarios stratégiques ET opérationnels sont évalués
        # ou si un snapshot existe
        if counts.matrix_snapshots > 0:
            progressions['AT5'] = 100
        elif counts.strategic_scenarios > 0 or counts.operational_scenarios > 0:
            # Calculer le pourcentage de scénarios évalués
            total_scenarios = counts.strategic_scenarios + counts.operational_scenarios
            evaluated_scenarios = counts.evaluated_strategic + counts.evaluated_operational
            if total_scenarios > 0:
                progressions['AT5'] = int((evaluated_scenarios / total_scenarios) * 100)
            else:
                progressions['AT5'] = 0
        else:
            progressions['AT5'] = 0

        # Mettre à jour les workshops
        if workshop_type:
            # Mettre à jour un seul atelier
            workshops_to_update = [workshop_type]
        else:
            # Mettre à jour tous les ateliers
            workshops_to_update = ['AT1', 'AT2', 'AT3', 'AT4', 'AT5']

        for ws_type in workshops_to_update:
            progress = progressions.get(ws_type, 0)
            status_val = 'NOT_STARTED'
            if progress > 0 and progress < 100:
                status_val = 'IN_PROGRESS'
            elif progress >= 100:
                status_val = 'COMPLETED'

            update_query = text("""
                UPDATE risk_workshop
                SET completion_percent = :progress,
                    status = :status,
                    updated_at = NOW()
                WHERE project_id = CAST(:project_id AS uuid)
                  AND type = :type
            """)

            db.execute(update_query, {
                "project_id": str(project_id),
                "type": ws_type,
                "progress": progress,
                "status": status_val
            })

        db.commit()
        logger.info(f"✅ Progression mise à jour pour projet {project_id}: {progressions}")

    except Exception as e:
        logger.error(f"❌ Erreur mise à jour progression: {e}")
        db.rollback()


# ==============================================================================
# PROJECT ENDPOINTS
# ==============================================================================

@router.post("/projects", response_model=RiskProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: RiskProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_CREATE"))
):
    """
    Crée un nouveau projet EBIOS RM.

    Permissions requises: EBIOS_CREATE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    project_id = str(uuid.uuid4())

    try:
        # Insérer le projet
        insert_query = text("""
            INSERT INTO risk_project (
                id, tenant_id, label, description, method, status,
                start_date, end_date, scope_entity_ids, pilot_user_ids,
                contributor_user_ids, ai_initial_context, created_by, created_at
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:tenant_id AS uuid),
                :label,
                :description,
                'EBIOS_RM',
                'DRAFT',
                :start_date,
                :end_date,
                CAST(:scope_entity_ids AS uuid[]),
                CAST(:pilot_user_ids AS uuid[]),
                CAST(:contributor_user_ids AS uuid[]),
                CAST(:ai_initial_context AS jsonb),
                CAST(:created_by AS uuid),
                NOW()
            )
            RETURNING *
        """)

        result = db.execute(insert_query, {
            "id": project_id,
            "tenant_id": str(current_user.tenant_id),
            "label": project.label,
            "description": project.description,
            "start_date": project.start_date,
            "end_date": project.end_date,
            "scope_entity_ids": [str(e) for e in project.scope_entity_ids] if project.scope_entity_ids else None,
            "pilot_user_ids": [str(u) for u in project.pilot_user_ids] if project.pilot_user_ids else None,
            "contributor_user_ids": [str(u) for u in project.contributor_user_ids] if project.contributor_user_ids else None,
            "ai_initial_context": json.dumps(project.ai_initial_context) if project.ai_initial_context else None,
            "created_by": str(current_user.id)
        })

        row = result.fetchone()
        db.commit()

        # Créer les 5 ateliers
        ensure_workshops_exist(db, UUID(project_id))

        # Si des messages IA ont été échangés, pré-remplir l'Atelier 1
        if project.ai_initial_context:
            try:
                ai_data = parse_ai_messages_for_at1(project.ai_initial_context)
                if ai_data["business_values"] or ai_data["assets"] or ai_data["feared_events"]:
                    populate_at1_from_ai(db, project_id, ai_data)
                    logger.info(f"🤖 AT1 pré-rempli avec données IA pour projet {project_id}")
            except Exception as ai_err:
                logger.warning(f"⚠️ Erreur parsing/insertion IA (non bloquant): {ai_err}")

        logger.info(f"✅ Projet EBIOS créé: {project_id} par {current_user.email}")

        return RiskProjectResponse(
            id=UUID(project_id),
            tenant_id=current_user.tenant_id,
            label=project.label,
            description=project.description,
            method="EBIOS_RM",
            status=ProjectStatus.DRAFT,
            start_date=project.start_date,
            end_date=project.end_date,
            scope_entity_ids=project.scope_entity_ids,
            pilot_user_ids=project.pilot_user_ids,
            contributor_user_ids=project.contributor_user_ids,
            ai_initial_context=project.ai_initial_context,
            created_by=current_user.id,
            created_at=datetime.now(),
            progress_percent=0,
            workshops_status={
                "AT1": "NOT_STARTED",
                "AT2": "NOT_STARTED",
                "AT3": "NOT_STARTED",
                "AT4": "NOT_STARTED",
                "AT5": "NOT_STARTED"
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur création projet EBIOS: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création: {str(e)}"
        )


@router.get("/projects", response_model=RiskProjectListResponse)
async def list_projects(
    status_filter: Optional[str] = Query(None, alias="status", description="Filtrer par statut"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_READ"))
):
    """
    Liste tous les projets EBIOS RM du tenant.

    Permissions requises: EBIOS_READ
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    try:
        # Construire la requête avec filtres
        status_clause = "AND rp.status = :status" if status_filter else ""

        # D'abord, récupérer les IDs des projets pour recalculer leurs progressions
        ids_query = text(f"""
            SELECT rp.id FROM risk_project rp
            WHERE rp.tenant_id = CAST(:tenant_id AS uuid)
              AND rp.deleted_at IS NULL
              {status_clause}
        """)
        ids_params = {"tenant_id": str(current_user.tenant_id)}
        if status_filter:
            ids_params["status"] = status_filter

        project_ids = [str(row.id) for row in db.execute(ids_query, ids_params).fetchall()]

        # Recalculer les progressions pour tous les projets
        for pid in project_ids:
            update_workshop_progress(db, pid)

        query = text(f"""
            SELECT
                rp.*,
                -- Calculer la progression globale
                COALESCE(
                    (SELECT AVG(completion_percent) FROM risk_workshop WHERE project_id = rp.id),
                    0
                ) as progress_percent
            FROM risk_project rp
            WHERE rp.tenant_id = CAST(:tenant_id AS uuid)
              AND rp.deleted_at IS NULL
              {status_clause}
            ORDER BY rp.created_at DESC
            LIMIT :limit OFFSET :skip
        """)

        params = {
            "tenant_id": str(current_user.tenant_id),
            "limit": limit,
            "skip": skip
        }
        if status_filter:
            params["status"] = status_filter

        result = db.execute(query, params)
        rows = result.fetchall()

        # Compte total
        count_query = text(f"""
            SELECT COUNT(*) FROM risk_project rp
            WHERE rp.tenant_id = CAST(:tenant_id AS uuid)
              AND rp.deleted_at IS NULL
              {status_clause}
        """)
        count_params = {"tenant_id": str(current_user.tenant_id)}
        if status_filter:
            count_params["status"] = status_filter

        total = db.execute(count_query, count_params).scalar()

        # Transformer en réponses avec workshops_progress
        items = []
        for row in rows:
            # Récupérer la progression de chaque atelier
            workshops_query = text("""
                SELECT type, completion_percent FROM risk_workshop
                WHERE project_id = CAST(:project_id AS uuid)
            """)
            workshops_result = db.execute(workshops_query, {"project_id": str(row.id)})
            workshops_progress = {r.type: r.completion_percent or 0 for r in workshops_result.fetchall()}

            items.append(RiskProjectResponse(
                id=row.id,
                tenant_id=row.tenant_id,
                label=row.label,
                description=row.description,
                method=row.method,
                status=ProjectStatus(row.status),
                start_date=row.start_date,
                end_date=row.end_date,
                scope_entity_ids=row.scope_entity_ids,
                pilot_user_ids=row.pilot_user_ids,
                contributor_user_ids=row.contributor_user_ids,
                frozen_at=row.frozen_at,
                frozen_by=row.frozen_by,
                created_by=row.created_by,
                created_at=row.created_at,
                updated_at=row.updated_at,
                progress_percent=int(row.progress_percent) if row.progress_percent else 0,
                workshops_progress=workshops_progress
            ))

        return RiskProjectListResponse(
            items=items,
            total=total,
            skip=skip,
            limit=limit
        )

    except Exception as e:
        logger.error(f"❌ Erreur liste projets EBIOS: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )


@router.get("/projects/{project_id}", response_model=RiskProjectResponse)
async def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_READ"))
):
    """
    Récupère les détails d'un projet EBIOS RM.

    Permissions requises: EBIOS_READ
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Recalculer la progression avant de récupérer le projet
    update_workshop_progress(db, str(project_id))

    query = text("""
        SELECT rp.*,
            (SELECT AVG(completion_percent) FROM risk_workshop WHERE project_id = rp.id) as progress_percent
        FROM risk_project rp
        WHERE rp.id = CAST(:project_id AS uuid)
          AND rp.tenant_id = CAST(:tenant_id AS uuid)
          AND rp.deleted_at IS NULL
    """)

    result = db.execute(query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    })
    row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet non trouvé"
        )

    # Récupérer le statut et progression des ateliers
    workshops_query = text("""
        SELECT type, status, completion_percent FROM risk_workshop
        WHERE project_id = CAST(:project_id AS uuid)
        ORDER BY type
    """)
    workshops_result = db.execute(workshops_query, {"project_id": str(project_id)})
    workshops_rows = workshops_result.fetchall()
    workshops_status = {r.type: r.status for r in workshops_rows}
    workshops_progress = {r.type: r.completion_percent or 0 for r in workshops_rows}

    # Parser ai_initial_context si c'est une string JSON
    ai_context = row.ai_initial_context
    if isinstance(ai_context, str):
        try:
            ai_context = json.loads(ai_context)
        except json.JSONDecodeError:
            ai_context = None

    return RiskProjectResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        label=row.label,
        description=row.description,
        method=row.method,
        status=ProjectStatus(row.status),
        start_date=row.start_date,
        end_date=row.end_date,
        scope_entity_ids=row.scope_entity_ids,
        pilot_user_ids=row.pilot_user_ids,
        contributor_user_ids=row.contributor_user_ids,
        ai_initial_context=ai_context,
        frozen_at=row.frozen_at,
        frozen_by=row.frozen_by,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        progress_percent=int(row.progress_percent) if row.progress_percent else 0,
        workshops_status=workshops_status,
        workshops_progress=workshops_progress
    )


@router.post("/projects/{project_id}/populate-at1")
async def populate_at1_from_ai_context(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Re-parse le contexte IA du projet et remplit l'Atelier 1.

    Utile pour les projets créés avant l'implémentation du parsing automatique,
    ou pour re-générer les données AT1 à partir des échanges IA.

    Permissions requises: EBIOS_UPDATE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Récupérer le projet avec son contexte IA
    query = text("""
        SELECT id, status, ai_initial_context
        FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    row = db.execute(query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet non trouvé"
        )

    if row.status == "FROZEN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de modifier un projet figé"
        )

    if not row.ai_initial_context:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun contexte IA disponible pour ce projet"
        )

    # Parser le contexte IA (peut être string JSON ou dict)
    ai_context = row.ai_initial_context
    if isinstance(ai_context, str):
        try:
            ai_context = json.loads(ai_context)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contexte IA invalide (format JSON incorrect)"
            )

    # Parser les messages IA
    ai_data = parse_ai_messages_for_at1(ai_context)

    if not ai_data["business_values"] and not ai_data["assets"] and not ai_data["feared_events"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune donnée exploitable trouvée dans les échanges IA. "
                   "Assurez-vous que l'IA a généré des valeurs métier, biens supports ou événements redoutés."
        )

    # Compter les éléments existants pour éviter les doublons
    count_query = text("""
        SELECT
            (SELECT COUNT(*) FROM risk_business_value WHERE project_id = CAST(:project_id AS uuid)) as bv_count,
            (SELECT COUNT(*) FROM risk_asset WHERE project_id = CAST(:project_id AS uuid)) as asset_count,
            (SELECT COUNT(*) FROM risk_feared_event WHERE project_id = CAST(:project_id AS uuid)) as fe_count
    """)
    counts = db.execute(count_query, {"project_id": str(project_id)}).fetchone()

    # Insérer les données
    populate_at1_from_ai(db, str(project_id), ai_data)

    # Mettre à jour le statut de l'atelier AT1 si des données ont été ajoutées
    if ai_data["business_values"] or ai_data["assets"] or ai_data["feared_events"]:
        update_workshop = text("""
            UPDATE risk_workshop
            SET status = 'IN_PROGRESS', updated_at = NOW()
            WHERE project_id = CAST(:project_id AS uuid) AND type = 'AT1'
        """)
        db.execute(update_workshop, {"project_id": str(project_id)})
        db.commit()

    logger.info(f"🤖 AT1 peuplé pour projet {project_id} par {current_user.email}")

    return {
        "success": True,
        "message": "Atelier 1 pré-rempli avec succès",
        "data": {
            "business_values_added": len(ai_data["business_values"]),
            "assets_added": len(ai_data["assets"]),
            "feared_events_added": len(ai_data["feared_events"]),
            "previous_counts": {
                "business_values": counts.bv_count if counts else 0,
                "assets": counts.asset_count if counts else 0,
                "feared_events": counts.fe_count if counts else 0
            }
        }
    }


@router.put("/projects/{project_id}", response_model=RiskProjectResponse)
async def update_project(
    project_id: UUID,
    project_update: RiskProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Met à jour un projet EBIOS RM.

    Permissions requises: EBIOS_UPDATE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier que le projet existe et n'est pas gelé
    check_query = text("""
        SELECT id, status FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    check_result = db.execute(check_query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not check_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet non trouvé"
        )

    if check_result.status == "FROZEN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossible de modifier un projet figé"
        )

    # Construire la mise à jour dynamique
    update_fields = []
    params = {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }

    if project_update.label is not None:
        update_fields.append("label = :label")
        params["label"] = project_update.label

    if project_update.description is not None:
        update_fields.append("description = :description")
        params["description"] = project_update.description

    if project_update.status is not None:
        update_fields.append("status = :status")
        params["status"] = project_update.status.value

    if project_update.start_date is not None:
        update_fields.append("start_date = :start_date")
        params["start_date"] = project_update.start_date

    if project_update.end_date is not None:
        update_fields.append("end_date = :end_date")
        params["end_date"] = project_update.end_date

    if project_update.scope_entity_ids is not None:
        update_fields.append("scope_entity_ids = CAST(:scope_entity_ids AS uuid[])")
        params["scope_entity_ids"] = [str(e) for e in project_update.scope_entity_ids]

    if project_update.pilot_user_ids is not None:
        update_fields.append("pilot_user_ids = CAST(:pilot_user_ids AS uuid[])")
        params["pilot_user_ids"] = [str(u) for u in project_update.pilot_user_ids]

    if project_update.contributor_user_ids is not None:
        update_fields.append("contributor_user_ids = CAST(:contributor_user_ids AS uuid[])")
        params["contributor_user_ids"] = [str(u) for u in project_update.contributor_user_ids]

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune mise à jour fournie"
        )

    update_fields.append("updated_at = NOW()")

    update_query = text(f"""
        UPDATE risk_project
        SET {", ".join(update_fields)}
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
        RETURNING *
    """)

    try:
        result = db.execute(update_query, params)
        row = result.fetchone()
        db.commit()

        logger.info(f"✅ Projet EBIOS mis à jour: {project_id}")

        return await get_project(project_id, db, current_user)

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur mise à jour projet: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour: {str(e)}"
        )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_DELETE"))
):
    """
    Supprime un projet EBIOS RM (soft delete).

    Permissions requises: EBIOS_DELETE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier que le projet existe
    check_query = text("""
        SELECT id FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    check_result = db.execute(check_query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not check_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet non trouvé"
        )

    # Soft delete
    delete_query = text("""
        UPDATE risk_project
        SET deleted_at = NOW(), updated_at = NOW()
        WHERE id = CAST(:project_id AS uuid)
    """)

    try:
        db.execute(delete_query, {"project_id": str(project_id)})
        db.commit()
        logger.info(f"🗑️ Projet EBIOS supprimé: {project_id}")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur suppression projet: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )


# ==============================================================================
# FREEZE ENDPOINT
# ==============================================================================

@router.post("/projects/{project_id}/freeze", response_model=FreezeResponse)
async def freeze_project(
    project_id: UUID,
    request: FreezeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_FREEZE"))
):
    """
    Fige une analyse EBIOS RM. Cette action est irréversible.

    - Calcule tous les scores de risques
    - Génère un snapshot de la matrice
    - Verrouille les ateliers en lecture seule

    Permissions requises: EBIOS_FREEZE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation requise pour figer l'analyse"
        )

    # Vérifier le projet
    project_query = text("""
        SELECT rp.*,
            (SELECT COUNT(*) FROM risk_workshop WHERE project_id = rp.id AND status = 'COMPLETED') as completed_workshops
        FROM risk_project rp
        WHERE rp.id = CAST(:project_id AS uuid)
          AND rp.tenant_id = CAST(:tenant_id AS uuid)
          AND rp.deleted_at IS NULL
    """)
    project = db.execute(project_query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet non trouvé"
        )

    if project.status == "FROZEN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le projet est déjà figé"
        )

    # Vérifier que tous les ateliers sont complétés (optionnel)
    # if project.completed_workshops < 5:
    #     raise HTTPException(
    #         status_code=status.HTTP_400_BAD_REQUEST,
    #         detail="Tous les ateliers doivent être complétés avant le gel"
    #     )

    try:
        now = datetime.now()
        snapshot_id = str(uuid.uuid4())

        # 1. Récupérer tous les risques
        risks_query = text("""
            SELECT * FROM risk_risk
            WHERE project_id = CAST(:project_id AS uuid)
              AND deleted_at IS NULL
        """)
        risks = db.execute(risks_query, {"project_id": str(project_id)}).fetchall()

        # 2. Construire la matrice
        matrix_data = {
            "cells": [],
            "risks": [],
            "stats": {
                "total_risks": len(risks),
                "by_criticality": {
                    "LOW": 0,
                    "MODERATE": 0,
                    "HIGH": 0,
                    "CRITICAL": 0
                }
            }
        }

        for risk in risks:
            risk_data = {
                "id": str(risk.id),
                "code": risk.code,
                "label": risk.label,
                "severity": risk.severity,
                "likelihood": risk.likelihood,
                "score": risk.score,
                "criticality_level": risk.criticality_level
            }
            matrix_data["risks"].append(risk_data)
            matrix_data["stats"]["by_criticality"][risk.criticality_level] += 1

        # 3. Sauvegarder le snapshot
        snapshot_query = text("""
            INSERT INTO risk_matrix_snapshot (
                id, project_id, snapshot_date, snapshot_type,
                matrix_raw, stats, created_by, created_at
            )
            VALUES (
                CAST(:id AS uuid),
                CAST(:project_id AS uuid),
                :snapshot_date,
                'FREEZE',
                CAST(:matrix_raw AS jsonb),
                CAST(:stats AS jsonb),
                CAST(:created_by AS uuid),
                NOW()
            )
        """)
        db.execute(snapshot_query, {
            "id": snapshot_id,
            "project_id": str(project_id),
            "snapshot_date": now,
            "matrix_raw": str(matrix_data).replace("'", '"'),
            "stats": str(matrix_data["stats"]).replace("'", '"'),
            "created_by": str(current_user.id)
        })

        # 4. Figer le projet
        freeze_query = text("""
            UPDATE risk_project
            SET status = 'FROZEN',
                frozen_at = :frozen_at,
                frozen_by = CAST(:frozen_by AS uuid),
                updated_at = NOW()
            WHERE id = CAST(:project_id AS uuid)
        """)
        db.execute(freeze_query, {
            "project_id": str(project_id),
            "frozen_at": now,
            "frozen_by": str(current_user.id)
        })

        # 5. Marquer tous les ateliers comme complétés
        complete_workshops_query = text("""
            UPDATE risk_workshop
            SET status = 'COMPLETED',
                completion_percent = 100,
                completed_at = NOW(),
                completed_by = CAST(:user_id AS uuid),
                updated_at = NOW()
            WHERE project_id = CAST(:project_id AS uuid)
        """)
        db.execute(complete_workshops_query, {
            "project_id": str(project_id),
            "user_id": str(current_user.id)
        })

        db.commit()

        logger.info(f"🔒 Projet EBIOS figé: {project_id} par {current_user.email}")

        return FreezeResponse(
            success=True,
            message="Analyse EBIOS RM figée avec succès",
            frozen_at=now,
            matrix_snapshot_id=UUID(snapshot_id),
            risks_count=len(risks),
            stats=matrix_data["stats"]
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur gel projet: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du gel: {str(e)}"
        )


# ==============================================================================
# ATELIER 1 - CADRAGE
# ==============================================================================

@router.get("/projects/{project_id}/workshop/at1", response_model=AT1Response)
async def get_workshop_at1(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_READ"))
):
    """
    Récupère l'atelier 1 (Cadrage) avec ses données.

    Permissions requises: EBIOS_READ
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier le projet
    project_check = text("""
        SELECT id FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    if not db.execute(project_check, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")

    # Assurer que les ateliers existent
    ensure_workshops_exist(db, project_id)

    # Workshop
    workshop_query = text("""
        SELECT * FROM risk_workshop
        WHERE project_id = CAST(:project_id AS uuid) AND type = 'AT1'
    """)
    workshop_row = db.execute(workshop_query, {"project_id": str(project_id)}).fetchone()

    # Business values
    bv_query = text("""
        SELECT * FROM risk_business_value
        WHERE project_id = CAST(:project_id AS uuid) AND deleted_at IS NULL
        ORDER BY order_index, created_at
    """)
    business_values = [
        BusinessValueResponse(
            id=r.id, project_id=r.project_id, label=r.label, description=r.description,
            criticality=r.criticality, order_index=r.order_index, source=r.source,
            is_selected=r.is_selected,
            created_at=r.created_at, updated_at=r.updated_at
        )
        for r in db.execute(bv_query, {"project_id": str(project_id)}).fetchall()
    ]

    # Assets
    assets_query = text("""
        SELECT * FROM risk_asset
        WHERE project_id = CAST(:project_id AS uuid) AND deleted_at IS NULL
        ORDER BY order_index, created_at
    """)
    assets = [
        AssetResponse(
            id=r.id, project_id=r.project_id, label=r.label, type=r.type,
            description=r.description, criticality=r.criticality,
            linked_organism_id=r.linked_organism_id, order_index=r.order_index,
            source=r.source, is_selected=r.is_selected,
            created_at=r.created_at, updated_at=r.updated_at
        )
        for r in db.execute(assets_query, {"project_id": str(project_id)}).fetchall()
    ]

    # Feared events
    fe_query = text("""
        SELECT fe.*, bv.label as bv_label, a.label as asset_label
        FROM risk_feared_event fe
        LEFT JOIN risk_business_value bv ON fe.linked_business_value_id = bv.id
        LEFT JOIN risk_asset a ON fe.linked_asset_id = a.id
        WHERE fe.project_id = CAST(:project_id AS uuid) AND fe.deleted_at IS NULL
        ORDER BY fe.order_index, fe.created_at
    """)
    feared_events = [
        FearedEventResponse(
            id=r.id, project_id=r.project_id, label=r.label, description=r.description,
            dimension=r.dimension, severity=r.severity, justification=r.justification,
            linked_business_value_id=r.linked_business_value_id, linked_asset_id=r.linked_asset_id,
            order_index=r.order_index, source=r.source, is_selected=r.is_selected,
            created_at=r.created_at, updated_at=r.updated_at,
            business_value_label=r.bv_label, asset_label=r.asset_label
        )
        for r in db.execute(fe_query, {"project_id": str(project_id)}).fetchall()
    ]

    return AT1Response(
        workshop=WorkshopResponse(
            id=workshop_row.id, project_id=workshop_row.project_id,
            type=WorkshopType(workshop_row.type), status=WorkshopStatus(workshop_row.status),
            completion_percent=workshop_row.completion_percent,
            ai_last_generation_at=workshop_row.ai_last_generation_at,
            completed_at=workshop_row.completed_at, completed_by=workshop_row.completed_by,
            created_at=workshop_row.created_at, updated_at=workshop_row.updated_at
        ),
        business_values=business_values,
        assets=assets,
        feared_events=feared_events
    )


@router.post("/projects/{project_id}/workshop/at1/business-values", response_model=BusinessValueResponse, status_code=status.HTTP_201_CREATED)
async def create_business_value(
    project_id: UUID,
    item: BusinessValueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Ajoute une valeur métier à l'atelier 1.

    Permissions requises: EBIOS_UPDATE

    Retourne un warning si le nombre dépasse la recommandation (10),
    ou une erreur 400 si la limite dure (15) est atteinte.
    """
    if not current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans tenant")

    # Vérifier projet et non gelé
    check = text("""
        SELECT status FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    result = db.execute(check, {"project_id": str(project_id), "tenant_id": str(current_user.tenant_id)}).fetchone()

    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")
    if result.status == "FROZEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Projet figé")

    # Compter les éléments existants et vérifier les limites
    count_query = text("""
        SELECT COUNT(*) FROM risk_business_value
        WHERE project_id = CAST(:project_id AS uuid) AND deleted_at IS NULL
    """)
    current_count = db.execute(count_query, {"project_id": str(project_id)}).scalar() or 0

    limit_check = check_element_count(current_count, "business_values")
    if not limit_check["can_add"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=limit_check["error"]["message"]
        )

    item_id = str(uuid.uuid4())
    # Générer le code automatiquement
    code = get_next_code(db, "risk_business_value", "VM", str(project_id))

    insert_query = text("""
        INSERT INTO risk_business_value (id, project_id, code, label, description, criticality, order_index, source, created_at)
        VALUES (CAST(:id AS uuid), CAST(:project_id AS uuid), :code, :label, :description, :criticality, :order_index, 'MANUAL', NOW())
        RETURNING *
    """)

    try:
        row = db.execute(insert_query, {
            "id": item_id,
            "project_id": str(project_id),
            "code": code,
            "label": item.label,
            "description": item.description,
            "criticality": item.criticality,
            "order_index": current_count + 1
        }).fetchone()
        db.commit()

        # Préparer la réponse avec warning éventuel
        new_count = current_count + 1
        new_limit_check = check_element_count(new_count, "business_values")

        response = {
            "success": True,
            "count": new_count,
            "data": BusinessValueResponse(
                id=row.id, project_id=row.project_id, label=row.label, description=row.description,
                criticality=row.criticality, order_index=row.order_index or 0, source=row.source,
                created_at=row.created_at, updated_at=row.updated_at
            )
        }

        if new_limit_check["warning"]:
            response["warning"] = new_limit_check["warning"]

        return response
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/projects/{project_id}/workshop/at1/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    project_id: UUID,
    item: AssetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Ajoute un bien support à l'atelier 1.

    Permissions requises: EBIOS_UPDATE

    Retourne un warning si le nombre dépasse la recommandation (15),
    ou une erreur 400 si la limite dure (20) est atteinte.
    """
    if not current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans tenant")

    check = text("""
        SELECT status FROM risk_project
        WHERE id = CAST(:project_id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid) AND deleted_at IS NULL
    """)
    result = db.execute(check, {"project_id": str(project_id), "tenant_id": str(current_user.tenant_id)}).fetchone()

    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")
    if result.status == "FROZEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Projet figé")

    # Compter les éléments existants et vérifier les limites
    count_query = text("""
        SELECT COUNT(*) FROM risk_asset
        WHERE project_id = CAST(:project_id AS uuid) AND deleted_at IS NULL
    """)
    current_count = db.execute(count_query, {"project_id": str(project_id)}).scalar() or 0

    limit_check = check_element_count(current_count, "assets")
    if not limit_check["can_add"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=limit_check["error"]["message"]
        )

    item_id = str(uuid.uuid4())
    # Générer le code automatiquement
    code = get_next_code(db, "risk_asset", "BS", str(project_id))

    insert_query = text("""
        INSERT INTO risk_asset (id, project_id, code, label, type, description, criticality, linked_organism_id, order_index, source, created_at)
        VALUES (CAST(:id AS uuid), CAST(:project_id AS uuid), :code, :label, :type, :description, :criticality,
                CAST(:linked_organism_id AS uuid), :order_index, 'MANUAL', NOW())
        RETURNING *
    """)

    try:
        row = db.execute(insert_query, {
            "id": item_id,
            "project_id": str(project_id),
            "code": code,
            "label": item.label,
            "type": item.type,
            "description": item.description,
            "criticality": item.criticality,
            "linked_organism_id": str(item.linked_organism_id) if item.linked_organism_id else None,
            "order_index": current_count + 1
        }).fetchone()
        db.commit()

        # Préparer la réponse avec warning éventuel
        new_count = current_count + 1
        new_limit_check = check_element_count(new_count, "assets")

        response = {
            "success": True,
            "count": new_count,
            "data": AssetResponse(
                id=row.id, project_id=row.project_id, label=row.label, type=row.type,
                description=row.description, criticality=row.criticality,
                linked_organism_id=row.linked_organism_id, order_index=row.order_index or 0,
                source=row.source, created_at=row.created_at, updated_at=row.updated_at
            )
        }

        if new_limit_check["warning"]:
            response["warning"] = new_limit_check["warning"]

        return response
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/projects/{project_id}/workshop/at1/feared-events", response_model=FearedEventResponse, status_code=status.HTTP_201_CREATED)
async def create_feared_event(
    project_id: UUID,
    item: FearedEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Ajoute un événement redouté à l'atelier 1.

    Permissions requises: EBIOS_UPDATE

    Retourne un warning si le nombre dépasse la recommandation (10),
    ou une erreur 400 si la limite dure (15) est atteinte.
    """
    if not current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans tenant")

    check = text("""
        SELECT status FROM risk_project
        WHERE id = CAST(:project_id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid) AND deleted_at IS NULL
    """)
    result = db.execute(check, {"project_id": str(project_id), "tenant_id": str(current_user.tenant_id)}).fetchone()

    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")
    if result.status == "FROZEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Projet figé")

    # Compter les éléments existants et vérifier les limites
    count_query = text("""
        SELECT COUNT(*) FROM risk_feared_event
        WHERE project_id = CAST(:project_id AS uuid) AND deleted_at IS NULL
    """)
    current_count = db.execute(count_query, {"project_id": str(project_id)}).scalar() or 0

    limit_check = check_element_count(current_count, "feared_events")
    if not limit_check["can_add"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=limit_check["error"]["message"]
        )

    item_id = str(uuid.uuid4())
    # Générer le code automatiquement
    code = get_next_code(db, "risk_feared_event", "ER", str(project_id))

    insert_query = text("""
        INSERT INTO risk_feared_event (
            id, project_id, code, label, description, dimension, severity, justification,
            linked_business_value_id, linked_asset_id, order_index, source, created_at
        )
        VALUES (
            CAST(:id AS uuid), CAST(:project_id AS uuid), :code, :label, :description, :dimension, :severity, :justification,
            CAST(:linked_business_value_id AS uuid), CAST(:linked_asset_id AS uuid), :order_index, 'MANUAL', NOW()
        )
        RETURNING *
    """)

    try:
        row = db.execute(insert_query, {
            "id": item_id,
            "project_id": str(project_id),
            "code": code,
            "label": item.label,
            "description": item.description,
            "dimension": item.dimension.value if item.dimension else None,
            "severity": item.severity,
            "justification": item.justification,
            "linked_business_value_id": str(item.linked_business_value_id) if item.linked_business_value_id else None,
            "linked_asset_id": str(item.linked_asset_id) if item.linked_asset_id else None,
            "order_index": current_count + 1
        }).fetchone()
        db.commit()

        # Préparer la réponse avec warning éventuel
        new_count = current_count + 1
        new_limit_check = check_element_count(new_count, "feared_events")

        response = {
            "success": True,
            "count": new_count,
            "data": FearedEventResponse(
                id=row.id, project_id=row.project_id, label=row.label, description=row.description,
                dimension=row.dimension, severity=row.severity, justification=row.justification,
                linked_business_value_id=row.linked_business_value_id, linked_asset_id=row.linked_asset_id,
                order_index=row.order_index or 0, source=row.source, created_at=row.created_at, updated_at=row.updated_at
            )
        }

        if new_limit_check["warning"]:
            response["warning"] = new_limit_check["warning"]

        return response
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ==============================================================================
# ATELIER 1 - TOGGLE SELECTION (is_selected)
# ==============================================================================

class ToggleSelectionRequest(BaseModel):
    """Requête pour basculer la sélection d'un élément AT1"""
    element_type: str = Field(..., description="Type d'élément: business_value, asset, feared_event")
    element_id: UUID = Field(..., description="ID de l'élément")
    is_selected: bool = Field(..., description="Nouvelle valeur de sélection")


class ToggleSelectionResponse(BaseModel):
    """Réponse pour le toggle de sélection"""
    success: bool
    element_type: str
    element_id: UUID
    is_selected: bool


@router.patch("/projects/{project_id}/workshop/at1/toggle-selection", response_model=ToggleSelectionResponse)
async def toggle_at1_selection(
    project_id: UUID,
    request: ToggleSelectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Bascule la sélection (is_selected) d'un élément de l'atelier 1.

    Permet de sélectionner/désélectionner les valeurs métier, biens supports
    ou événements redoutés pour la génération de l'atelier 2.

    Permissions requises: EBIOS_UPDATE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier le projet
    project_check = text("""
        SELECT id, status FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    project_row = db.execute(project_check, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not project_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")

    if project_row.status == 'FROZEN':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Projet figé - modifications interdites")

    # Mapper le type d'élément vers la table
    table_mapping = {
        "business_value": "risk_business_value",
        "asset": "risk_asset",
        "feared_event": "risk_feared_event"
    }

    if request.element_type not in table_mapping:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Type d'élément invalide: {request.element_type}. Valeurs acceptées: business_value, asset, feared_event"
        )

    table_name = table_mapping[request.element_type]

    # Vérifier que l'élément existe et appartient au projet
    check_query = text(f"""
        SELECT id FROM {table_name}
        WHERE id = CAST(:element_id AS uuid)
          AND project_id = CAST(:project_id AS uuid)
          AND deleted_at IS NULL
    """)
    if not db.execute(check_query, {
        "element_id": str(request.element_id),
        "project_id": str(project_id)
    }).fetchone():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Élément {request.element_type} non trouvé"
        )

    # Mettre à jour is_selected
    update_query = text(f"""
        UPDATE {table_name}
        SET is_selected = :is_selected, updated_at = NOW()
        WHERE id = CAST(:element_id AS uuid)
          AND project_id = CAST(:project_id AS uuid)
    """)
    db.execute(update_query, {
        "element_id": str(request.element_id),
        "project_id": str(project_id),
        "is_selected": request.is_selected
    })
    db.commit()

    logger.info(f"✅ Toggle AT1 selection: {request.element_type} {request.element_id} -> is_selected={request.is_selected}")

    return ToggleSelectionResponse(
        success=True,
        element_type=request.element_type,
        element_id=request.element_id,
        is_selected=request.is_selected
    )


# ==============================================================================
# ATELIER 2 - SOURCES DE RISQUES (GET)
# ==============================================================================

@router.get("/projects/{project_id}/workshop/at2", response_model=AT2Response)
async def get_workshop_at2(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_READ"))
):
    """
    Récupère l'atelier 2 (Sources de risques) avec ses données.

    Permissions requises: EBIOS_READ
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier le projet
    project_check = text("""
        SELECT id FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    if not db.execute(project_check, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")

    # Assurer que les ateliers existent
    ensure_workshops_exist(db, project_id)

    # Workshop AT2
    workshop_query = text("""
        SELECT * FROM risk_workshop
        WHERE project_id = CAST(:project_id AS uuid) AND type = 'AT2'
    """)
    workshop_row = db.execute(workshop_query, {"project_id": str(project_id)}).fetchone()

    # Sources de risques
    sources_query = text("""
        SELECT * FROM risk_source
        WHERE project_id = CAST(:project_id AS uuid) AND deleted_at IS NULL
        ORDER BY order_index, created_at
    """)
    source_rows = db.execute(sources_query, {"project_id": str(project_id)}).fetchall()

    # Pour chaque source, récupérer les objectifs
    risk_sources = []
    for source_row in source_rows:
        objectives_query = text("""
            SELECT * FROM risk_source_objective
            WHERE source_id = CAST(:source_id AS uuid)
            ORDER BY order_index, created_at
        """)
        objective_rows = db.execute(objectives_query, {"source_id": str(source_row.id)}).fetchall()

        objectives = [
            RiskSourceObjectiveResponse(
                id=obj.id,
                source_id=obj.source_id,
                label=obj.label,
                description=obj.description,
                is_selected=obj.is_selected if hasattr(obj, 'is_selected') else True,
                order_index=obj.order_index if hasattr(obj, 'order_index') else 0,
                created_at=obj.created_at,
                updated_at=obj.updated_at if hasattr(obj, 'updated_at') else None
            )
            for obj in objective_rows
        ]

        risk_sources.append(
            RiskSourceResponse(
                id=source_row.id,
                project_id=source_row.project_id,
                label=source_row.label,
                description=source_row.description,
                relevance=source_row.relevance if hasattr(source_row, 'relevance') else 3,
                justification=source_row.justification if hasattr(source_row, 'justification') else None,
                is_selected=source_row.is_selected if hasattr(source_row, 'is_selected') else True,
                order_index=source_row.order_index if hasattr(source_row, 'order_index') else 0,
                source=source_row.source if hasattr(source_row, 'source') else 'MANUAL',
                objectives=objectives,
                created_at=source_row.created_at,
                updated_at=source_row.updated_at if hasattr(source_row, 'updated_at') else None
            )
        )

    return AT2Response(
        workshop=WorkshopResponse(
            id=workshop_row.id,
            project_id=workshop_row.project_id,
            type=WorkshopType(workshop_row.type),
            status=WorkshopStatus(workshop_row.status),
            completion_percent=workshop_row.completion_percent,
            ai_last_generation_at=workshop_row.ai_last_generation_at,
            completed_at=workshop_row.completed_at,
            completed_by=workshop_row.completed_by,
            created_at=workshop_row.created_at,
            updated_at=workshop_row.updated_at
        ),
        risk_sources=risk_sources
    )


# ==============================================================================
# GENERATE AT2 FROM AT1 SELECTION
# ==============================================================================

class GenerateAT2Request(BaseModel):
    """Schéma pour la génération de l'Atelier 2 depuis AT1"""
    business_value_ids: List[str] = []
    asset_ids: List[str] = []
    feared_event_ids: List[str] = []


@router.post("/projects/{project_id}/generate-at2")
async def generate_at2_from_at1(
    project_id: UUID,
    request: GenerateAT2Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Génère l'Atelier 2 (Sources de risques) à partir des éléments sélectionnés de l'Atelier 1.

    Utilise l'IA pour proposer des sources de risques pertinentes basées sur :
    - Les valeurs métier sélectionnées
    - Les biens supports sélectionnés
    - Les événements redoutés sélectionnés

    Permissions requises: EBIOS_UPDATE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier le projet et qu'il n'est pas figé
    check = text("""
        SELECT id, status, label FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    project = db.execute(check, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")
    if project.status == "FROZEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Projet figé")

    # Vérifier qu'au moins un élément est sélectionné
    total_selected = len(request.business_value_ids) + len(request.asset_ids) + len(request.feared_event_ids)
    if total_selected == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Veuillez sélectionner au moins un élément de l'Atelier 1"
        )

    # Récupérer les éléments sélectionnés
    selected_items = {
        "business_values": [],
        "assets": [],
        "feared_events": []
    }

    # Business values
    if request.business_value_ids:
        bv_query = text("""
            SELECT id, label, description, criticality FROM risk_business_value
            WHERE project_id = CAST(:project_id AS uuid)
              AND id = ANY(CAST(:ids AS uuid[]))
              AND deleted_at IS NULL
        """)
        bv_rows = db.execute(bv_query, {
            "project_id": str(project_id),
            "ids": request.business_value_ids
        }).fetchall()
        selected_items["business_values"] = [
            {"label": r.label, "description": r.description, "criticality": r.criticality}
            for r in bv_rows
        ]

    # Assets
    if request.asset_ids:
        asset_query = text("""
            SELECT id, label, type, description, criticality FROM risk_asset
            WHERE project_id = CAST(:project_id AS uuid)
              AND id = ANY(CAST(:ids AS uuid[]))
              AND deleted_at IS NULL
        """)
        asset_rows = db.execute(asset_query, {
            "project_id": str(project_id),
            "ids": request.asset_ids
        }).fetchall()
        selected_items["assets"] = [
            {"label": r.label, "type": r.type, "description": r.description, "criticality": r.criticality}
            for r in asset_rows
        ]

    # Feared events
    if request.feared_event_ids:
        fe_query = text("""
            SELECT id, label, description, severity, dimension FROM risk_feared_event
            WHERE project_id = CAST(:project_id AS uuid)
              AND id = ANY(CAST(:ids AS uuid[]))
              AND deleted_at IS NULL
        """)
        fe_rows = db.execute(fe_query, {
            "project_id": str(project_id),
            "ids": request.feared_event_ids
        }).fetchall()
        selected_items["feared_events"] = [
            {"label": r.label, "description": r.description, "severity": r.severity, "dimension": r.dimension}
            for r in fe_rows
        ]

    logger.info(f"🔄 Génération AT2 pour projet {project_id}: "
                f"{len(selected_items['business_values'])} valeurs, "
                f"{len(selected_items['assets'])} biens, "
                f"{len(selected_items['feared_events'])} événements")

    # Générer les sources de risques via IA
    risk_sources = await generate_risk_sources_with_ai(
        project_label=project.label,
        selected_items=selected_items
    )

    # Insérer les sources de risques dans la base
    sources_created = 0
    objectives_created = 0

    for idx, source in enumerate(risk_sources, 1):
        source_id = str(uuid.uuid4())
        code = f"SR{idx:02d}"
        try:
            insert_source = text("""
                INSERT INTO risk_source (
                    id, project_id, code, label, description, relevance,
                    justification, is_selected, order_index, source, created_at
                )
                VALUES (
                    CAST(:id AS uuid), CAST(:project_id AS uuid), :code, :label, :description, :relevance,
                    :justification, true, :order_index, 'AI', NOW()
                )
                RETURNING id
            """)
            db.execute(insert_source, {
                "id": source_id,
                "project_id": str(project_id),
                "code": code,
                "label": source.get("label", "Source de risque"),
                "description": source.get("description"),
                "relevance": source.get("relevance", 3),
                "justification": source.get("justification"),
                "order_index": idx
            })
            sources_created += 1

            # Insérer les objectifs associés
            for obj in source.get("objectives", []):
                obj_id = str(uuid.uuid4())
                insert_obj = text("""
                    INSERT INTO risk_source_objective (
                        id, source_id, label, description, is_selected, created_at
                    )
                    VALUES (
                        CAST(:id AS uuid), CAST(:source_id AS uuid), :label, :description, true, NOW()
                    )
                """)
                db.execute(insert_obj, {
                    "id": obj_id,
                    "source_id": source_id,
                    "label": obj.get("label", "Objectif"),
                    "description": obj.get("description")
                })
                objectives_created += 1

        except Exception as e:
            logger.warning(f"⚠️ Erreur insertion source de risque: {e}")

    # Mettre à jour le statut de l'atelier AT2
    update_workshop = text("""
        UPDATE risk_workshop
        SET status = 'IN_PROGRESS', updated_at = NOW()
        WHERE project_id = CAST(:project_id AS uuid) AND type = 'AT2'
    """)
    db.execute(update_workshop, {"project_id": str(project_id)})

    db.commit()

    logger.info(f"✅ AT2 généré: {sources_created} sources, {objectives_created} objectifs")

    return {
        "success": True,
        "message": f"Atelier 2 généré avec succès",
        "risk_sources_created": sources_created,
        "objectives_created": objectives_created,
        "selected_elements": {
            "business_values": len(selected_items["business_values"]),
            "assets": len(selected_items["assets"]),
            "feared_events": len(selected_items["feared_events"])
        }
    }


async def generate_risk_sources_with_ai(project_label: str, selected_items: dict) -> List[dict]:
    """
    Utilise l'IA pour générer des sources de risques pertinentes.

    Retourne une liste de dictionnaires avec:
    - label: Nom de la source de risque
    - description: Description détaillée
    - relevance: Pertinence (1-4)
    - justification: Justification de la pertinence
    - objectives: Liste des objectifs [{label, description}]
    """
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")

    # Construire le prompt
    bv_list = "\n".join([f"- {bv['label']} (Criticité: {bv['criticality']}/4)" for bv in selected_items.get("business_values", [])])
    asset_list = "\n".join([f"- {a['label']} ({a['type']})" for a in selected_items.get("assets", [])])
    fe_list = "\n".join([f"- {fe['label']} (Gravité: {fe['severity']}/4, {fe['dimension']})" for fe in selected_items.get("feared_events", [])])

    prompt = f"""Tu es un expert en analyse de risques EBIOS RM. Génère des sources de risques pour l'Atelier 2.

CONTEXTE DU PROJET: {project_label}

ÉLÉMENTS DE L'ATELIER 1 SÉLECTIONNÉS:

Valeurs métier:
{bv_list or "Aucune sélectionnée"}

Biens supports:
{asset_list or "Aucun sélectionné"}

Événements redoutés:
{fe_list or "Aucun sélectionné"}

CONTRAINTES EBIOS RM:
- Ne génère pas plus de 10-12 sources de risques (recommandé: 5-12, maximum absolu: 15)
- Si plusieurs sources se recoupent, fusionne-les en catégories plus générales
- Retourne une liste courte et synthétique, pas exhaustive

INSTRUCTIONS:
1. Génère 5 à 10 sources de risques pertinentes (attaquants potentiels, menaces)
2. Pour chaque source, définis 2-3 objectifs (motivations)
3. Évalue la pertinence de 1 (faible) à 4 (critique)
4. Regroupe les sources similaires plutôt que de les lister séparément

RÉPONDS EN JSON STRICT (sans markdown, sans ```):
[
  {{
    "label": "Nom de la source de risque",
    "description": "Description détaillée",
    "relevance": 3,
    "justification": "Pourquoi cette source est pertinente",
    "objectives": [
      {{"label": "Objectif 1", "description": "Description de l'objectif"}},
      {{"label": "Objectif 2", "description": "Description de l'objectif"}}
    ]
  }}
]

Génère uniquement le JSON, sans texte avant ou après."""

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": 8192,
                        "num_predict": 4096
                    }
                }
            )

            if response.status_code != 200:
                logger.error(f"❌ Ollama error: {response.status_code}")
                return get_default_risk_sources()

            data = response.json()
            ai_response = data.get("response", "")

            # Parser le JSON de la réponse
            # Nettoyer la réponse (enlever markdown si présent)
            cleaned = ai_response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
                cleaned = cleaned.rstrip("`").strip()

            # Trouver le JSON array dans la réponse
            json_match = re.search(r'\[[\s\S]*\]', cleaned)
            if json_match:
                cleaned = json_match.group(0)

            try:
                risk_sources = json.loads(cleaned)
                if isinstance(risk_sources, list) and len(risk_sources) > 0:
                    logger.info(f"✅ IA a généré {len(risk_sources)} sources de risques")
                    return risk_sources
            except json.JSONDecodeError as je:
                logger.warning(f"⚠️ Erreur parsing JSON IA: {je}")

    except httpx.TimeoutException:
        logger.warning("⚠️ Timeout IA pour génération AT2")
    except httpx.ConnectError:
        logger.warning("⚠️ Impossible de contacter Ollama")
    except Exception as e:
        logger.error(f"❌ Erreur génération AT2 IA: {e}")

    # Fallback: sources par défaut
    return get_default_risk_sources()


def get_default_risk_sources() -> List[dict]:
    """
    Retourne des sources de risques par défaut si l'IA n'est pas disponible.
    """
    return [
        {
            "label": "Cybercriminels opportunistes",
            "description": "Attaquants motivés par le gain financier, utilisant des techniques automatisées",
            "relevance": 3,
            "justification": "Menace courante pour toute organisation connectée",
            "objectives": [
                {"label": "Gain financier", "description": "Rançon, vol de données monnayables"},
                {"label": "Revente de données", "description": "Commercialisation d'accès ou de données volées"}
            ]
        },
        {
            "label": "Attaquants ciblés (APT)",
            "description": "Groupes organisés avec des moyens importants et une persistance élevée",
            "relevance": 2,
            "justification": "Risque selon le secteur d'activité et les données détenues",
            "objectives": [
                {"label": "Espionnage industriel", "description": "Vol de propriété intellectuelle"},
                {"label": "Sabotage", "description": "Perturbation des opérations"}
            ]
        },
        {
            "label": "Personnel interne malveillant",
            "description": "Employés ou prestataires avec accès légitime agissant de manière malveillante",
            "relevance": 2,
            "justification": "Menace interne difficile à détecter",
            "objectives": [
                {"label": "Vengeance", "description": "Actions suite à un litige ou mécontentement"},
                {"label": "Profit personnel", "description": "Vente d'informations à des concurrents"}
            ]
        }
    ]


# ==============================================================================
# CRUD SOURCES DE RISQUES (AT2)
# ==============================================================================

class RiskSourceObjectiveCreate(BaseModel):
    """Schéma pour créer un objectif de source de risque"""
    label: str
    description: Optional[str] = None


class RiskSourceCreate(BaseModel):
    """Schéma pour créer une source de risque manuellement"""
    reference: str  # Ex: SR01
    label: str  # Titre de la source
    description: Optional[str] = None  # Description courte
    justification: str  # Justification obligatoire
    relevance: int = 3  # 1-4 (Faible, Modéré, Élevé, Très élevé)
    objectives: List[RiskSourceObjectiveCreate] = []
    is_selected: bool = True  # Retenue par défaut


@router.post("/projects/{project_id}/risk-sources")
async def create_risk_source(
    project_id: UUID,
    request: RiskSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Crée une nouvelle source de risque manuellement.

    Cette API permet d'ajouter une source de risque sans passer par la génération IA.

    Permissions requises: EBIOS_UPDATE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier le projet et qu'il n'est pas figé
    project_check = text("""
        SELECT id, status FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    project = db.execute(project_check, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")
    if project.status == "FROZEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Projet figé, impossible d'ajouter des sources")

    # Vérifier l'unicité de la référence
    ref_check = text("""
        SELECT id FROM risk_source
        WHERE project_id = CAST(:project_id AS uuid)
          AND UPPER(label) = UPPER(:reference)
          AND deleted_at IS NULL
    """)
    existing = db.execute(ref_check, {
        "project_id": str(project_id),
        "reference": request.reference
    }).fetchone()

    # Note: On ne vérifie pas la référence car elle n'est pas stockée comme champ séparé
    # La référence est juste un identifiant visuel (SR01, SR02...)

    # Compter les sources existantes pour l'ordre
    count_query = text("""
        SELECT COUNT(*) FROM risk_source
        WHERE project_id = CAST(:project_id AS uuid)
          AND deleted_at IS NULL
    """)
    count_result = db.execute(count_query, {"project_id": str(project_id)}).scalar()
    order_index = count_result + 1

    # Vérifier limite EBIOS (max 15 sources)
    if count_result >= 15:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limite atteinte : maximum 15 sources de risques par projet"
        )

    # Validation de la pertinence
    if request.relevance < 1 or request.relevance > 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La pertinence doit être entre 1 et 4"
        )

    # Validation des objectifs
    if len(request.objectives) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Au moins un objectif est requis"
        )
    if len(request.objectives) > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 5 objectifs par source"
        )

    # Créer la source de risque
    source_id = str(uuid.uuid4())
    # Générer le code automatiquement
    code = get_next_code(db, "risk_source", "SR", str(project_id))

    insert_source = text("""
        INSERT INTO risk_source (
            id, project_id, code, label, description, relevance, justification,
            is_selected, source, order_index, created_at, updated_at
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:project_id AS uuid),
            :code,
            :label,
            :description,
            :relevance,
            :justification,
            :is_selected,
            'MANUAL',
            :order_index,
            NOW(),
            NOW()
        )
        RETURNING id
    """)

    db.execute(insert_source, {
        "id": source_id,
        "project_id": str(project_id),
        "code": code,
        "label": request.label,
        "description": request.description,
        "relevance": request.relevance,
        "justification": request.justification,
        "is_selected": request.is_selected,
        "order_index": order_index
    })

    # Créer les objectifs
    objectives_created = []
    for idx, obj in enumerate(request.objectives):
        obj_id = str(uuid.uuid4())
        insert_obj = text("""
            INSERT INTO risk_source_objective (
                id, source_id, label, description, is_selected, order_index, created_at, updated_at
            ) VALUES (
                CAST(:id AS uuid),
                CAST(:source_id AS uuid),
                :label,
                :description,
                true,
                :order_index,
                NOW(),
                NOW()
            )
            RETURNING id
        """)
        db.execute(insert_obj, {
            "id": obj_id,
            "source_id": source_id,
            "label": obj.label,
            "description": obj.description,
            "order_index": idx + 1
        })
        objectives_created.append({
            "id": obj_id,
            "label": obj.label,
            "description": obj.description
        })

    # Mettre à jour le statut du workshop AT2 si besoin
    update_workshop = text("""
        UPDATE risk_workshop
        SET status = 'IN_PROGRESS', updated_at = NOW()
        WHERE project_id = CAST(:project_id AS uuid)
          AND type = 'AT2'
          AND status = 'NOT_STARTED'
    """)
    db.execute(update_workshop, {"project_id": str(project_id)})

    db.commit()

    logger.info(f"✅ Source de risque créée manuellement: {request.label} (projet: {project_id})")

    return {
        "success": True,
        "message": "Source de risque créée avec succès",
        "source": {
            "id": source_id,
            "label": request.label,
            "description": request.description,
            "relevance": request.relevance,
            "justification": request.justification,
            "is_selected": request.is_selected,
            "source": "MANUAL",
            "order_index": order_index,
            "objectives": objectives_created
        }
    }


@router.delete("/projects/{project_id}/risk-sources/{source_id}")
async def delete_risk_source(
    project_id: UUID,
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Supprime une source de risque (soft delete).

    Permissions requises: EBIOS_UPDATE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier le projet et qu'il n'est pas figé
    project_check = text("""
        SELECT rp.id, rp.status FROM risk_project rp
        JOIN risk_source rs ON rs.project_id = rp.id
        WHERE rp.id = CAST(:project_id AS uuid)
          AND rp.tenant_id = CAST(:tenant_id AS uuid)
          AND rs.id = CAST(:source_id AS uuid)
          AND rp.deleted_at IS NULL
          AND rs.deleted_at IS NULL
    """)
    result = db.execute(project_check, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id),
        "source_id": str(source_id)
    }).fetchone()

    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source non trouvée")
    if result.status == "FROZEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Projet figé, impossible de supprimer")

    # Soft delete de la source
    delete_source = text("""
        UPDATE risk_source
        SET deleted_at = NOW()
        WHERE id = CAST(:source_id AS uuid)
    """)
    db.execute(delete_source, {"source_id": str(source_id)})

    db.commit()

    logger.info(f"🗑️ Source de risque supprimée: {source_id}")

    return {"success": True, "message": "Source de risque supprimée"}


# ==============================================================================
# ATELIER 5 - MATRICE DES RISQUES
# ==============================================================================

@router.get("/projects/{project_id}/matrix", response_model=MatrixResponse)
async def get_risk_matrix(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_READ"))
):
    """
    Récupère la matrice des risques 4×4.

    - Si le projet est figé: affiche la matrice avec les risques
    - Si le projet n'est pas figé: matrice vide avec message

    Permissions requises: EBIOS_READ
    """
    if not current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans tenant")

    # Vérifier le projet
    project_query = text("""
        SELECT id, status, frozen_at FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    project = db.execute(project_query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet non trouvé")

    is_frozen = project.status == "FROZEN"

    # Si non figé, retourner une matrice vide
    if not is_frozen:
        return MatrixResponse(
            project_id=project_id,
            is_frozen=False,
            frozen_at=None,
            cells=[],
            stats={"message": "La matrice sera calculée lorsque l'analyse sera figée."}
        )

    # Si figé, récupérer les risques
    risks_query = text("""
        SELECT r.*,
            ss.code as strategic_code,
            os.code as operational_code,
            fe.label as feared_event_label
        FROM risk_risk r
        LEFT JOIN risk_strategic_scenario ss ON r.strategic_scenario_id = ss.id
        LEFT JOIN risk_operational_scenario os ON r.operational_scenario_id = os.id
        LEFT JOIN risk_feared_event fe ON r.feared_event_id = fe.id
        WHERE r.project_id = CAST(:project_id AS uuid)
          AND r.deleted_at IS NULL
        ORDER BY r.score DESC
    """)
    risks = db.execute(risks_query, {"project_id": str(project_id)}).fetchall()

    # Construire les cellules de la matrice
    cells_map = {}
    for sev in range(1, 5):
        for lik in range(1, 5):
            score = sev * lik
            key = f"{sev}_{lik}"
            cells_map[key] = MatrixCell(
                severity=sev,
                likelihood=lik,
                score=score,
                risks=[],
                color=get_matrix_color(score)
            )

    # Placer les risques dans les cellules
    stats = {"total": 0, "LOW": 0, "MODERATE": 0, "HIGH": 0, "CRITICAL": 0}

    for r in risks:
        key = f"{r.severity}_{r.likelihood}"
        if key in cells_map:
            risk_response = RiskResponse(
                id=r.id, project_id=r.project_id, code=r.code, label=r.label,
                description=r.description, severity=r.severity, likelihood=r.likelihood,
                score=r.score, criticality_level=CriticalityLevel(r.criticality_level),
                justification=r.justification, strategic_scenario_id=r.strategic_scenario_id,
                operational_scenario_id=r.operational_scenario_id, feared_event_id=r.feared_event_id,
                residual_severity=r.residual_severity, residual_likelihood=r.residual_likelihood,
                residual_score=r.residual_score, residual_justification=r.residual_justification,
                treatment_strategy=r.treatment_strategy, treatment_status=r.treatment_status,
                order_index=r.order_index or 0, source=r.source,
                created_at=r.created_at, updated_at=r.updated_at,
                strategic_scenario_code=r.strategic_code,
                operational_scenario_code=r.operational_code,
                feared_event_label=r.feared_event_label,
                linked_actions_count=0
            )
            cells_map[key].risks.append(risk_response)
            stats["total"] += 1
            stats[r.criticality_level] += 1

    return MatrixResponse(
        project_id=project_id,
        is_frozen=True,
        frozen_at=project.frozen_at,
        cells=list(cells_map.values()),
        stats=stats
    )


# ==============================================================================
# RISQUE RÉSIDUEL (modifiable même après gel)
# ==============================================================================

@router.put("/projects/{project_id}/risks/{risk_id}/residual", response_model=RiskResponse)
async def update_residual_risk(
    project_id: UUID,
    risk_id: UUID,
    update: RiskUpdateResidual,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_UPDATE"))
):
    """
    Met à jour le risque résiduel. Possible même après gel de l'analyse.

    Permissions requises: EBIOS_UPDATE
    """
    if not current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans tenant")

    # Vérifier le risque existe
    check = text("""
        SELECT r.id FROM risk_risk r
        JOIN risk_project rp ON r.project_id = rp.id
        WHERE r.id = CAST(:risk_id AS uuid)
          AND r.project_id = CAST(:project_id AS uuid)
          AND rp.tenant_id = CAST(:tenant_id AS uuid)
          AND r.deleted_at IS NULL
    """)
    if not db.execute(check, {
        "risk_id": str(risk_id),
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risque non trouvé")

    # Calculer le score résiduel
    residual_score = None
    if update.residual_severity and update.residual_likelihood:
        residual_score = update.residual_severity * update.residual_likelihood

    update_query = text("""
        UPDATE risk_risk
        SET residual_severity = :residual_severity,
            residual_likelihood = :residual_likelihood,
            residual_score = :residual_score,
            residual_justification = :residual_justification,
            treatment_strategy = :treatment_strategy,
            updated_at = NOW()
        WHERE id = CAST(:risk_id AS uuid)
        RETURNING *
    """)

    try:
        row = db.execute(update_query, {
            "risk_id": str(risk_id),
            "residual_severity": update.residual_severity,
            "residual_likelihood": update.residual_likelihood,
            "residual_score": residual_score,
            "residual_justification": update.residual_justification,
            "treatment_strategy": update.treatment_strategy.value if update.treatment_strategy else None
        }).fetchone()
        db.commit()

        return RiskResponse(
            id=row.id, project_id=row.project_id, code=row.code, label=row.label,
            description=row.description, severity=row.severity, likelihood=row.likelihood,
            score=row.score, criticality_level=CriticalityLevel(row.criticality_level),
            justification=row.justification, strategic_scenario_id=row.strategic_scenario_id,
            operational_scenario_id=row.operational_scenario_id, feared_event_id=row.feared_event_id,
            residual_severity=row.residual_severity, residual_likelihood=row.residual_likelihood,
            residual_score=row.residual_score, residual_justification=row.residual_justification,
            treatment_strategy=row.treatment_strategy, treatment_status=row.treatment_status,
            order_index=row.order_index or 0, source=row.source,
            created_at=row.created_at, updated_at=row.updated_at,
            linked_actions_count=0
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ==============================================================================
# AI CHAT ENDPOINT
# ==============================================================================

EBIOS_SYSTEM_PROMPT = """Tu es un expert en analyse de risques selon la méthodologie EBIOS RM de l'ANSSI.

Tu aides les utilisateurs à initialiser leur analyse de risques en identifiant :
• Les valeurs métier (données, processus, services critiques)
• Les biens supports (systèmes, applications, infrastructures)
• Les événements redoutés (incidents de sécurité potentiels)
• Les sources de risques (attaquants, menaces)

CONTRAINTES EBIOS RM À RESPECTER STRICTEMENT :
Pour garder une analyse lisible et exploitable, tu dois LIMITER tes propositions :
• 5 à 10 valeurs métier maximum (ne pas dépasser 8)
• 8 à 15 biens supports maximum (ne pas dépasser 10)
• 5 à 10 événements redoutés maximum (ne pas dépasser 8)
• 5 à 12 sources de risques maximum (ne pas dépasser 10)

IMPORTANT : Si plusieurs éléments se recoupent, regroupe-les en catégories plus générales.
Retourne des listes COURTES et SYNTHÉTIQUES, pas exhaustives.

RÈGLES DE FORMATAGE STRICTES :
1. Utilise TOUJOURS des sauts de ligne pour séparer les paragraphes
2. Pour les titres de section, mets-les sur une ligne seule suivie d'un saut de ligne
3. Pour les listes, utilise "• " (puce) ou des numéros "1. " au début de chaque élément
4. Chaque élément de liste doit être sur SA PROPRE LIGNE
5. Ajoute une ligne vide entre les sections

EXEMPLE DE FORMAT ATTENDU :

Valeurs métier identifiées :

• Continuité des services clients
• Protection des données personnelles
• Réputation de l'organisation

Événements redoutés :

1. Fuite de données sensibles (Gravité: 4/4)
2. Indisponibilité du système (Gravité: 3/4)
3. Compromission des accès (Gravité: 3/4)

Pour les événements redoutés, indique TOUJOURS la gravité entre 1 et 4.

Sois structuré, professionnel et synthétique. Privilégie la qualité à la quantité."""


@router.post("/ai/chat", response_model=AIChatResponse)
async def ai_chat(
    request: AIChatRequest,
    current_user: User = Depends(require_permission("risk_project:read"))
):
    """
    Chat avec l'IA pour l'initialisation EBIOS RM.

    Utilise le modèle Ollama configuré (glm-4.6:cloud par défaut).
    """
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")

    logger.info(f"🤖 [EBIOS AI Chat] User: {current_user.email}, Model: {ollama_model}")

    # Construire les messages pour Ollama
    messages = [{"role": "system", "content": EBIOS_SYSTEM_PROMPT}]

    # Ajouter le contexte du projet si fourni
    if request.context:
        messages.append({
            "role": "user",
            "content": f"Contexte du projet : {request.context}"
        })
        messages.append({
            "role": "assistant",
            "content": "J'ai bien pris en compte le contexte. Comment puis-je vous aider ?"
        })

    # Ajouter l'historique des messages
    if request.history:
        for msg in request.history:
            messages.append({"role": msg.role, "content": msg.content})

    # Ajouter le nouveau message
    messages.append({"role": "user", "content": request.message})

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minutes timeout
            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": ollama_model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": 16384,      # Contexte plus large
                        "num_predict": 8192    # Réponse plus longue (jusqu'à ~6000 mots)
                    }
                }
            )

            if response.status_code != 200:
                logger.error(f"❌ Ollama error: {response.status_code} - {response.text}")
                return AIChatResponse(
                    success=False,
                    response="",
                    error=f"Erreur Ollama: {response.status_code}"
                )

            data = response.json()
            ai_response = data.get("message", {}).get("content", "")

            logger.info(f"✅ [EBIOS AI Chat] Response received ({len(ai_response)} chars)")

            return AIChatResponse(
                success=True,
                response=ai_response
            )

    except httpx.TimeoutException:
        logger.error("❌ Ollama timeout")
        return AIChatResponse(
            success=False,
            response="",
            error="Timeout: L'IA met trop de temps à répondre"
        )
    except httpx.ConnectError:
        logger.error("❌ Cannot connect to Ollama")
        return AIChatResponse(
            success=False,
            response="",
            error="Impossible de se connecter au serveur IA (Ollama)"
        )
    except Exception as e:
        logger.error(f"❌ AI Chat error: {e}")
        return AIChatResponse(
            success=False,
            response="",
            error=str(e)
        )


# ==================== AI RISK SOURCE SUGGESTION ====================

class RiskSourceSuggestionRequest(BaseModel):
    """Requête pour générer une suggestion de source de risque via IA."""
    context: str  # Description brève de la menace (ex: "employé mécontent")
    project_context: Optional[str] = None  # Contexte additionnel du projet


class RiskSourceSuggestion(BaseModel):
    """Suggestion de source de risque générée par l'IA."""
    label: str  # Titre de la source (ex: "Employé mécontent ou malveillant")
    description: str  # Description courte
    justification: str  # Justification détaillée
    relevance: int  # Niveau de pertinence 1-4
    objectives: List[dict]  # Liste d'objectifs {label, description}


class RiskSourceSuggestionResponse(BaseModel):
    """Réponse de suggestion de source de risque."""
    success: bool
    suggestion: Optional[RiskSourceSuggestion] = None
    error: Optional[str] = None


RISK_SOURCE_SUGGESTION_PROMPT = """Tu es un expert en cybersécurité spécialisé dans la méthodologie EBIOS Risk Manager (EBIOS RM).

Ta tâche est de générer une source de risque structurée et exploitable pour l'Atelier 2 (AT2) d'EBIOS RM.

RÈGLES IMPORTANTES :
1. Le TITRE doit être le NOM de l'acteur menaçant (pas une phrase)
   - Exemples corrects : "Employé mécontent", "Cybercriminels opportunistes", "État hostile (APT)", "Prestataire négligent"
   - Exemples incorrects : "Source de risque liée à...", "Menace potentielle de..."

2. La DESCRIPTION doit être courte (1-2 phrases) et caractériser l'acteur

3. La JUSTIFICATION doit expliquer pourquoi cette source est pertinente pour l'organisation

4. Les OBJECTIFS VISÉS doivent être entre 1 et 5, choisis parmi les motivations typiques EBIOS :
   - Gain financier
   - Revente de données
   - Espionnage industriel
   - Espionnage étatique
   - Déstabilisation
   - Sabotage
   - Hacktivisme
   - Vengeance
   - Fraude interne
   - Vol de propriété intellectuelle

5. Le NIVEAU DE PERTINENCE doit être entre 1 et 4 :
   - 1 = Faible
   - 2 = Modéré
   - 3 = Élevé
   - 4 = Très élevé

Tu dois répondre UNIQUEMENT avec un JSON valide au format suivant (pas de texte avant ou après) :
{
  "label": "Nom de l'acteur menaçant",
  "description": "Description courte de l'acteur",
  "justification": "Pourquoi cette source est pertinente",
  "relevance": 3,
  "objectives": [
    {"label": "Objectif 1", "description": "Description de l'objectif"},
    {"label": "Objectif 2", "description": "Description de l'objectif"}
  ]
}"""


@router.post("/ai/suggest-risk-source", response_model=RiskSourceSuggestionResponse)
async def suggest_risk_source(
    request: RiskSourceSuggestionRequest,
    current_user: User = Depends(require_permission("risk_project:read"))
):
    """
    Génère une suggestion de source de risque via l'IA basée sur le contexte fourni.

    L'IA analyse le contexte (ex: "employé mécontent") et génère une source de risque
    structurée et exploitable pour EBIOS RM AT2.
    """
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")

    logger.info(f"🤖 [EBIOS AI Suggest Risk Source] User: {current_user.email}, Context: {request.context[:50]}...")

    # Construire le prompt utilisateur
    user_prompt = f"""Génère une source de risque EBIOS RM basée sur ce contexte :

Contexte de la menace : {request.context}
"""

    if request.project_context:
        user_prompt += f"\nContexte du projet : {request.project_context}"

    user_prompt += "\n\nRéponds UNIQUEMENT avec le JSON structuré, sans texte additionnel."

    messages = [
        {"role": "system", "content": RISK_SOURCE_SUGGESTION_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": ollama_model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": 8192,
                        "num_predict": 4096  # Augmenté pour éviter les réponses tronquées
                    }
                }
            )

            if response.status_code != 200:
                logger.error(f"❌ Ollama error: {response.status_code} - {response.text}")
                return RiskSourceSuggestionResponse(
                    success=False,
                    error=f"Erreur Ollama: {response.status_code}"
                )

            data = response.json()
            ai_response = data.get("message", {}).get("content", "")

            logger.info(f"✅ [EBIOS AI Suggest] Raw response ({len(ai_response)} chars): {ai_response[:300]}...")

            # Parser le JSON de la réponse
            try:
                # Nettoyer la réponse (enlever les backticks markdown si présents)
                cleaned_response = ai_response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.startswith("```"):
                    cleaned_response = cleaned_response[3:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                cleaned_response = cleaned_response.strip()

                # Vérifier si le JSON semble complet (se termine par })
                if not cleaned_response.rstrip().endswith("}"):
                    logger.error(f"❌ JSON response appears truncated: ...{cleaned_response[-100:]}")
                    return RiskSourceSuggestionResponse(
                        success=False,
                        error="La réponse de l'IA a été tronquée. Veuillez réessayer avec une description plus courte."
                    )

                suggestion_data = json.loads(cleaned_response)

                # Valider et normaliser les données
                suggestion = RiskSourceSuggestion(
                    label=suggestion_data.get("label", "Source de risque"),
                    description=suggestion_data.get("description", ""),
                    justification=suggestion_data.get("justification", ""),
                    relevance=max(1, min(4, int(suggestion_data.get("relevance", 3)))),
                    objectives=suggestion_data.get("objectives", [])[:5]  # Max 5 objectifs
                )

                logger.info(f"✅ [EBIOS AI Suggest] Parsed suggestion: {suggestion.label}")

                return RiskSourceSuggestionResponse(
                    success=True,
                    suggestion=suggestion
                )

            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse AI response as JSON: {e}")
                logger.error(f"Raw response: {ai_response}")
                return RiskSourceSuggestionResponse(
                    success=False,
                    error="L'IA n'a pas retourné un format JSON valide. Veuillez réessayer."
                )

    except httpx.TimeoutException:
        logger.error("❌ Ollama timeout for risk source suggestion")
        return RiskSourceSuggestionResponse(
            success=False,
            error="Timeout: L'IA met trop de temps à répondre"
        )
    except httpx.ConnectError:
        logger.error("❌ Cannot connect to Ollama for risk source suggestion")
        return RiskSourceSuggestionResponse(
            success=False,
            error="Impossible de se connecter au serveur IA"
        )
    except Exception as e:
        logger.error(f"❌ AI Risk Source Suggestion error: {e}")
        return RiskSourceSuggestionResponse(
            success=False,
            error=str(e)
        )


# ==================== ATELIER 3 - SCÉNARIOS STRATÉGIQUES ====================

class StrategicScenarioAsset(BaseModel):
    """Bien support lié à un scénario stratégique."""
    id: str
    code: str
    label: str


class StrategicScenarioResponse(BaseModel):
    """Réponse d'un scénario stratégique."""
    id: str
    code: str
    title: str
    description: Optional[str]
    risk_source_id: Optional[str]
    risk_source_code: Optional[str]
    risk_source_label: Optional[str]
    feared_event_id: Optional[str]
    feared_event_code: Optional[str]
    feared_event_label: Optional[str]
    assets: List[StrategicScenarioAsset]
    severity: Optional[int]  # 1-4
    likelihood: Optional[int]  # 1-4
    justification: Optional[str]
    source: str  # 'MANUAL' ou 'AI'
    created_at: str
    # Champs de calcul du risque stratégique
    risk_score: Optional[int] = 0  # Gravité × Vraisemblance (1-16)
    risk_level: Optional[str] = "FAIBLE"  # FAIBLE, MODERE, ELEVE, CRITIQUE
    matrix_x: Optional[int] = 0  # Position X dans la matrice (Vraisemblance 1-4)
    matrix_y: Optional[int] = 0  # Position Y dans la matrice (Gravité 1-4)


class AT3WorkshopResponse(BaseModel):
    """Réponse de l'atelier 3."""
    strategic_scenarios: List[StrategicScenarioResponse]
    total_count: int
    can_generate: bool  # Si AT1 et AT2 sont complets
    generation_blocked_reason: Optional[str]


class GenerateAT3Response(BaseModel):
    """Réponse de génération AT3."""
    success: bool
    scenarios_created: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


# ==================== CALCUL DU RISQUE STRATÉGIQUE ====================

def compute_risk_level(score: int) -> str:
    """Détermine le niveau de risque en fonction du score (G × V)."""
    if score >= 12:
        return "CRITIQUE"
    elif score >= 8:
        return "ELEVE"
    elif score >= 4:
        return "MODERE"
    else:
        return "FAIBLE"


def calculate_strategic_risk(severity: int, likelihood: int) -> dict:
    """
    Calcule le score de risque stratégique et les coordonnées pour la matrice.

    Args:
        severity: Gravité (1-4)
        likelihood: Vraisemblance (1-4)

    Returns:
        dict avec risk_score, risk_level, matrix_x, matrix_y
    """
    g = max(1, min(4, severity or 1))  # Clamp entre 1 et 4
    v = max(1, min(4, likelihood or 1))

    risk_score = g * v
    risk_level = compute_risk_level(risk_score)

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "matrix_x": v,  # Axe X = Vraisemblance
        "matrix_y": g   # Axe Y = Gravité
    }


# Prompt pour la génération AT3
AT3_GENERATION_PROMPT = """Tu es un expert EBIOS RM. Tu dois générer des SCÉNARIOS STRATÉGIQUES (AT3) à partir des éléments AT1 et AT2 fournis ci-dessous.

OBJECTIF :
Identifier les scénarios dans lesquels une source de risque (acteur menaçant) exploite un bien support ou une dépendance pour atteindre une finalité correspondant à un événement redouté.

CONTRAINTES :
- Générer un nombre de scénarios proportionnel aux données fournies (voir instruction spécifique dans le message utilisateur).
- Chaque source de risque DOIT apparaître dans au moins un scénario si elle est pertinente.
- Chaque scénario doit être concis, clair et basé uniquement sur les données fournies.
- Ne pas inventer de nouveaux événements redoutés ni de biens supports.
- Une même source de risque peut apparaître dans plusieurs scénarios si elle cible différents biens supports ou événements redoutés.
- Faire correspondre logiquement :
    * une source de risque →
    * un ou plusieurs biens supports exposés →
    * un événement redouté (finalité)
- Évaluer :
    * la gravité (1=Faible, 2=Modérée, 3=Importante, 4=Critique)
    * la vraisemblance (1=Faible, 2=Modérée, 3=Élevée)
- IMPORTANT : Utiliser EXACTEMENT les codes fournis (SR01, BS01, ER01, etc.)

FORMAT DE SORTIE STRICT JSON (pas de texte avant ou après) :
[
  {
    "code": "SS01",
    "titre": "Titre court décrivant le scénario",
    "source_risque_code": "SR01",
    "biens_supports_codes": ["BS01", "BS03"],
    "evenement_redoute_code": "ER02",
    "description": "Description narrative du scénario d'attaque.",
    "gravite": 4,
    "vraisemblance": 2
  }
]"""


@router.get("/projects/{project_id}/workshop/at3", response_model=AT3WorkshopResponse)
async def get_workshop_at3(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:read"))
):
    """
    Récupère les données de l'Atelier 3 (Scénarios stratégiques).
    """
    # Vérifier accès au projet
    project_check = db.execute(
        text("SELECT id, tenant_id FROM risk_project WHERE id = :id AND deleted_at IS NULL"),
        {"id": str(project_id)}
    ).fetchone()

    if not project_check:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    # Vérifier si AT1 et AT2 sont complétés
    at1_complete = True
    at2_complete = True
    blocked_reason = None

    # Vérifier AT1 - au moins 1 valeur métier, 1 bien support, 1 événement redouté
    at1_counts = db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM risk_business_value WHERE project_id = :project_id AND deleted_at IS NULL) as bv_count,
            (SELECT COUNT(*) FROM risk_asset WHERE project_id = :project_id AND deleted_at IS NULL) as asset_count,
            (SELECT COUNT(*) FROM risk_feared_event WHERE project_id = :project_id AND deleted_at IS NULL) as fe_count
    """), {"project_id": str(project_id)}).fetchone()

    if at1_counts.bv_count == 0:
        at1_complete = False
        blocked_reason = "Aucune valeur métier définie dans AT1"
    elif at1_counts.asset_count == 0:
        at1_complete = False
        blocked_reason = "Aucun bien support défini dans AT1"
    elif at1_counts.fe_count == 0:
        at1_complete = False
        blocked_reason = "Aucun événement redouté défini dans AT1"

    # Vérifier AT2 - au moins 1 source de risque retenue
    at2_count = db.execute(text("""
        SELECT COUNT(*) as count FROM risk_source
        WHERE project_id = :project_id AND deleted_at IS NULL AND is_selected = true
    """), {"project_id": str(project_id)}).fetchone()

    if at2_count.count == 0:
        at2_complete = False
        blocked_reason = "Aucune source de risque retenue dans AT2"

    # Vérifier limite sources
    if at2_count.count > 15:
        blocked_reason = "Trop de sources de risques (max 15)"

    can_generate = at1_complete and at2_complete and blocked_reason is None

    # Récupérer les scénarios stratégiques existants
    scenarios_query = db.execute(text("""
        SELECT
            ss.id,
            ss.code,
            ss.title,
            ss.description,
            ss.risk_source_id,
            rs.code as risk_source_code,
            rs.label as risk_source_label,
            ss.feared_event_id,
            fe.code as feared_event_code,
            fe.label as feared_event_label,
            ss.severity,
            ss.likelihood_raw as likelihood,
            ss.justification,
            ss.source,
            ss.created_at,
            ss.risk_score,
            ss.risk_level,
            ss.matrix_x,
            ss.matrix_y
        FROM risk_strategic_scenario ss
        LEFT JOIN risk_source rs ON ss.risk_source_id = rs.id
        LEFT JOIN risk_feared_event fe ON ss.feared_event_id = fe.id
        WHERE ss.project_id = :project_id AND ss.deleted_at IS NULL
        ORDER BY ss.order_index, ss.code
    """), {"project_id": str(project_id)})

    scenarios = []
    for row in scenarios_query:
        # Récupérer les biens supports liés
        assets_query = db.execute(text("""
            SELECT a.id, a.code, a.label
            FROM risk_strategic_scenario_asset ssa
            JOIN risk_asset a ON ssa.asset_id = a.id
            WHERE ssa.scenario_id = :scenario_id
            ORDER BY a.order_index, a.id
        """), {"scenario_id": str(row.id)})

        assets = [
            StrategicScenarioAsset(id=str(a.id), code=a.code, label=a.label)
            for a in assets_query
        ]

        scenarios.append(StrategicScenarioResponse(
            id=str(row.id),
            code=row.code,
            title=row.title,
            description=row.description,
            risk_source_id=str(row.risk_source_id) if row.risk_source_id else None,
            risk_source_code=row.risk_source_code,
            risk_source_label=row.risk_source_label,
            feared_event_id=str(row.feared_event_id) if row.feared_event_id else None,
            feared_event_code=row.feared_event_code,
            feared_event_label=row.feared_event_label,
            assets=assets,
            severity=row.severity,
            likelihood=row.likelihood,
            justification=row.justification,
            source=row.source or 'MANUAL',
            created_at=row.created_at.isoformat() if row.created_at else "",
            risk_score=row.risk_score or 0,
            risk_level=row.risk_level or "FAIBLE",
            matrix_x=row.matrix_x or 0,
            matrix_y=row.matrix_y or 0
        ))

    return AT3WorkshopResponse(
        strategic_scenarios=scenarios,
        total_count=len(scenarios),
        can_generate=can_generate,
        generation_blocked_reason=blocked_reason
    )


@router.post("/projects/{project_id}/generate-at3", response_model=GenerateAT3Response)
async def generate_at3_scenarios(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:write"))
):
    """
    Génère les scénarios stratégiques (AT3) via l'IA.

    Prérequis:
    - AT1 complété (valeurs métier, biens supports, événements redoutés)
    - AT2 complété (au moins 1 source de risque retenue)
    """
    logger.info(f"🎯 [AT3] Génération des scénarios stratégiques pour projet {project_id}")

    # Vérifier accès au projet
    project = db.execute(
        text("SELECT id, label, status, tenant_id FROM risk_project WHERE id = :id AND deleted_at IS NULL"),
        {"id": str(project_id)}
    ).fetchone()

    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    if project.status == 'FROZEN':
        raise HTTPException(status_code=400, detail="Le projet est figé, impossible de générer")

    # Récupérer les données AT1 avec les codes stockés en base
    business_values = db.execute(text("""
        SELECT id, code, label, description
        FROM risk_business_value
        WHERE project_id = :project_id AND deleted_at IS NULL
        ORDER BY order_index, id
    """), {"project_id": str(project_id)}).fetchall()

    assets = db.execute(text("""
        SELECT id, code, label, description
        FROM risk_asset
        WHERE project_id = :project_id AND deleted_at IS NULL
        ORDER BY order_index, id
    """), {"project_id": str(project_id)}).fetchall()

    feared_events = db.execute(text("""
        SELECT id, code, label, description, severity
        FROM risk_feared_event
        WHERE project_id = :project_id AND deleted_at IS NULL
        ORDER BY order_index, id
    """), {"project_id": str(project_id)}).fetchall()

    # Récupérer les données AT2 (sources retenues uniquement)
    risk_sources = db.execute(text("""
        SELECT id, code, label, description, relevance
        FROM risk_source
        WHERE project_id = :project_id AND deleted_at IS NULL AND is_selected = true
        ORDER BY order_index, id
    """), {"project_id": str(project_id)}).fetchall()

    # Vérifications
    if not business_values:
        raise HTTPException(status_code=400, detail="Aucune valeur métier définie dans AT1")
    if not assets:
        raise HTTPException(status_code=400, detail="Aucun bien support défini dans AT1")
    if not feared_events:
        raise HTTPException(status_code=400, detail="Aucun événement redouté défini dans AT1")
    if not risk_sources:
        raise HTTPException(status_code=400, detail="Aucune source de risque retenue dans AT2")
    if len(risk_sources) > 15:
        raise HTTPException(status_code=400, detail="Trop de sources de risques (max 15)")

    # Construire le contexte pour l'IA
    bv_text = "\n".join([f"- {bv.code}: {bv.label}" + (f" - {bv.description}" if bv.description else "") for bv in business_values])
    assets_text = "\n".join([f"- {a.code}: {a.label}" + (f" - {a.description}" if a.description else "") for a in assets])
    fe_text = "\n".join([f"- {fe.code}: {fe.label} (Gravité: {fe.severity}/4)" + (f" - {fe.description}" if fe.description else "") for fe in feared_events])
    rs_text = "\n".join([f"- {rs.code}: {rs.label} (Pertinence: {rs.relevance}/4)" + (f" - {rs.description}" if rs.description else "") for rs in risk_sources])

    # Calculer le nombre de scénarios à générer en fonction des données
    # Règle : au minimum autant de scénarios que de sources de risques, avec un max raisonnable
    num_sources = len(risk_sources)
    num_feared_events = len(feared_events)
    # Minimum : nombre de sources, Maximum : sources × 2 ou 20 max
    min_scenarios = max(num_sources, 4)
    max_scenarios = min(num_sources * 2, 20)

    user_prompt = f"""Génère les scénarios stratégiques EBIOS RM basés sur ces données :

DONNÉES AT1 :
Valeurs métier :
{bv_text}

Biens supports :
{assets_text}

Événements redoutés :
{fe_text}

DONNÉES AT2 :
Sources de risques retenues ({num_sources} sources) :
{rs_text}

INSTRUCTION IMPORTANTE SUR LE NOMBRE DE SCÉNARIOS :
- Tu as {num_sources} sources de risques et {num_feared_events} événements redoutés.
- Génère entre {min_scenarios} et {max_scenarios} scénarios stratégiques.
- CHAQUE source de risque doit apparaître dans AU MOINS un scénario.
- Si une source de risque peut viser plusieurs événements redoutés différents, crée plusieurs scénarios distincts pour cette source.

Génère maintenant les scénarios stratégiques au format JSON strict."""

    # Appeler l'IA
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")

    logger.info(f"🤖 [AT3] Appel IA avec {num_sources} sources, {len(assets)} biens, {num_feared_events} événements → génération de {min_scenarios}-{max_scenarios} scénarios")

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": ollama_model,
                    "messages": [
                        {"role": "system", "content": AT3_GENERATION_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": 16384,
                        "num_predict": 8192
                    }
                }
            )

            if response.status_code != 200:
                logger.error(f"❌ Ollama error: {response.status_code}")
                raise HTTPException(status_code=500, detail="Erreur du serveur IA")

            data = response.json()
            ai_response = data.get("message", {}).get("content", "")

            logger.info(f"✅ [AT3] Réponse IA reçue ({len(ai_response)} chars)")

            # Parser le JSON
            cleaned_response = ai_response.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            if cleaned_response.startswith("```"):
                cleaned_response = cleaned_response[3:]
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            cleaned_response = cleaned_response.strip()

            try:
                scenarios_data = json.loads(cleaned_response)
            except json.JSONDecodeError as e:
                logger.error(f"❌ [AT3] JSON invalide: {e}")
                logger.error(f"Réponse brute: {ai_response[:500]}")
                raise HTTPException(status_code=500, detail="L'IA n'a pas retourné un format JSON valide")

            if not isinstance(scenarios_data, list):
                scenarios_data = [scenarios_data]

            # Créer les scénarios en base
            # Récupérer le prochain numéro de code disponible
            max_code_result = db.execute(text("""
                SELECT MAX(CAST(SUBSTRING(code FROM 3) AS INTEGER)) as max_num
                FROM risk_strategic_scenario
                WHERE project_id = :project_id AND code LIKE 'SS%'
            """), {"project_id": str(project_id)}).fetchone()
            next_code_num = (max_code_result.max_num or 0) + 1 if max_code_result else 1

            # Compter les scénarios existants pour order_index
            existing_count = db.execute(text("""
                SELECT COUNT(*) FROM risk_strategic_scenario
                WHERE project_id = :project_id AND deleted_at IS NULL
            """), {"project_id": str(project_id)}).scalar() or 0

            # Créer un mapping des codes vers IDs
            assets_map = {a.code: str(a.id) for a in assets}
            rs_map = {rs.code: str(rs.id) for rs in risk_sources}
            fe_map = {fe.code: str(fe.id) for fe in feared_events}

            scenarios_created = 0
            for i, scenario in enumerate(scenarios_data[:max_scenarios]):  # Max dynamique basé sur les sources
                # Toujours générer un code unique, ignorer celui de l'IA
                scenario_code = f"SS{str(next_code_num + i).zfill(2)}"

                # Trouver les IDs correspondants
                source_code = scenario.get("source_risque_code", "")
                source_id = rs_map.get(source_code)

                fe_code = scenario.get("evenement_redoute_code", "")
                fe_id = fe_map.get(fe_code)

                asset_codes = scenario.get("biens_supports_codes", [])

                # Calculer le risque stratégique
                severity_val = scenario.get("gravite", 3)
                likelihood_val = scenario.get("vraisemblance", 2)
                risk_data = calculate_strategic_risk(severity_val, likelihood_val)

                # Insérer le scénario avec les données de risque
                scenario_id = str(uuid.uuid4())
                db.execute(text("""
                    INSERT INTO risk_strategic_scenario (
                        id, project_id, code, title, description,
                        risk_source_id, feared_event_id,
                        severity, likelihood_raw, source, order_index,
                        risk_score, risk_level, matrix_x, matrix_y, created_at
                    ) VALUES (
                        :id, :project_id, :code, :title, :description,
                        CAST(:risk_source_id AS uuid), CAST(:feared_event_id AS uuid),
                        :severity, :likelihood, 'AI', :order_index,
                        :risk_score, :risk_level, :matrix_x, :matrix_y, NOW()
                    )
                """), {
                    "id": scenario_id,
                    "project_id": str(project_id),
                    "code": scenario_code,
                    "title": scenario.get("titre", "Scénario stratégique"),
                    "description": scenario.get("description", ""),
                    "risk_source_id": source_id,
                    "feared_event_id": fe_id,
                    "severity": severity_val,
                    "likelihood": likelihood_val,
                    "order_index": existing_count + i,
                    "risk_score": risk_data["risk_score"],
                    "risk_level": risk_data["risk_level"],
                    "matrix_x": risk_data["matrix_x"],
                    "matrix_y": risk_data["matrix_y"]
                })

                # Lier les biens supports
                for asset_code in asset_codes:
                    asset_id = assets_map.get(asset_code)
                    if asset_id:
                        db.execute(text("""
                            INSERT INTO risk_strategic_scenario_asset (scenario_id, asset_id)
                            VALUES (CAST(:scenario_id AS uuid), CAST(:asset_id AS uuid))
                            ON CONFLICT DO NOTHING
                        """), {"scenario_id": scenario_id, "asset_id": asset_id})

                scenarios_created += 1

            db.commit()

            logger.info(f"✅ [AT3] {scenarios_created} scénarios stratégiques créés")

            return GenerateAT3Response(
                success=True,
                scenarios_created=scenarios_created,
                message=f"{scenarios_created} scénarios stratégiques générés avec succès"
            )

    except httpx.TimeoutException:
        logger.error("❌ [AT3] Timeout IA")
        raise HTTPException(status_code=504, detail="Timeout: L'IA met trop de temps à répondre")
    except httpx.ConnectError:
        logger.error("❌ [AT3] Connexion IA impossible")
        raise HTTPException(status_code=503, detail="Impossible de se connecter au serveur IA")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AT3] Erreur: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_id}/strategic-scenarios/{scenario_id}")
async def delete_strategic_scenario(
    project_id: UUID,
    scenario_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:write"))
):
    """Supprime un scénario stratégique (hard delete)."""

    # Vérifier que le scénario appartient au projet
    scenario = db.execute(text("""
        SELECT ss.id, rp.status FROM risk_strategic_scenario ss
        JOIN risk_project rp ON ss.project_id = rp.id
        WHERE ss.id = :scenario_id AND ss.project_id = :project_id AND ss.deleted_at IS NULL
    """), {"scenario_id": str(scenario_id), "project_id": str(project_id)}).fetchone()

    if not scenario:
        raise HTTPException(status_code=404, detail="Scénario non trouvé")

    if scenario.status == 'FROZEN':
        raise HTTPException(status_code=400, detail="Le projet est figé")

    # Supprimer d'abord les liens avec les biens supports
    db.execute(text("""
        DELETE FROM risk_strategic_scenario_asset WHERE scenario_id = :id
    """), {"id": str(scenario_id)})

    # Hard delete du scénario
    db.execute(text("""
        DELETE FROM risk_strategic_scenario WHERE id = :id
    """), {"id": str(scenario_id)})

    db.commit()

    return {"success": True, "message": "Scénario supprimé"}


# ==================== ATELIER 4 - SCÉNARIOS OPÉRATIONNELS ====================

# Modèles Pydantic pour AT4

class OperationalStepResponse(BaseModel):
    """Une étape d'un scénario opérationnel."""
    id: str
    order_index: int
    action: str
    technique: Optional[str]
    description: Optional[str]


class OperationalScenarioAsset(BaseModel):
    """Un bien support lié à un scénario opérationnel."""
    id: str
    code: str
    label: str


class OperationalScenarioResponse(BaseModel):
    """Réponse d'un scénario opérationnel."""
    id: str
    code: str
    title: str
    description: Optional[str]
    # Liens vers le scénario stratégique parent
    strategic_scenario_id: str
    strategic_scenario_code: Optional[str]
    strategic_scenario_title: Optional[str]
    # Source de risque (héritée ou définie)
    risk_source_id: Optional[str]
    risk_source_code: Optional[str]
    risk_source_label: Optional[str]
    # Événement redouté
    feared_event_id: Optional[str]
    feared_event_code: Optional[str]
    feared_event_label: Optional[str]
    # Biens supports ciblés
    assets: List[OperationalScenarioAsset]
    # Étapes de la chaîne d'attaque
    steps: List[OperationalStepResponse]
    # Évaluation du risque opérationnel
    severity: Optional[int]  # 1-4
    likelihood: Optional[int]  # 1-4
    risk_score: int  # G × V
    risk_level: str  # FAIBLE, MODERE, ELEVE, CRITIQUE
    matrix_x: int  # Vraisemblance (1-4)
    matrix_y: int  # Gravité (1-4)
    # Métadonnées
    justification: Optional[str]
    source: str  # 'AI' | 'MANUAL'
    created_at: str


class AT4WorkshopResponse(BaseModel):
    """Réponse de l'atelier 4."""
    operational_scenarios: List[OperationalScenarioResponse]
    total_count: int
    can_generate: bool
    generation_blocked_reason: Optional[str]


class GenerateAT4Request(BaseModel):
    """Requête de génération AT4."""
    strategic_scenario_ids: Optional[List[str]] = None  # None = tous les SS
    max_per_ss: int = 2  # 1 à 3 SO par SS


class GenerateAT4Response(BaseModel):
    """Réponse de génération AT4."""
    success: bool
    scenarios_created: int = 0
    message: Optional[str] = None
    error: Optional[str] = None


# Prompt pour la génération AT4
# NOTE: Les accolades {{ et }} sont échappées pour .format()
AT4_GENERATION_PROMPT = """Tu es un expert en analyse de risques selon la méthode EBIOS RM (ANSSI).
Ta tâche est de transformer des scénarios stratégiques (AT3) en scénarios opérationnels (AT4).

OBJECTIF :
Pour chaque scénario stratégique, générer {max_per_ss} scénario(s) opérationnel(s) qui décrivent concrètement comment l'attaque se déroule.

CONTRAINTES :
- Génère exactement {max_per_ss} scénario(s) opérationnel(s) par scénario stratégique.
- Réutilise EXACTEMENT les codes des éléments fournis (SS, SR, ER).
- La description doit être concise (2-3 phrases max).
- Réponds UNIQUEMENT avec le JSON, sans texte avant ni après.

FORMAT JSON STRICT :
{{
  "operational_scenarios": [
    {{
      "strategic_scenario_code": "SS01",
      "code": "SO01",
      "title": "Titre court",
      "description": "Description concise de l'attaque.",
      "risk_source_code": "SR01",
      "feared_event_code": "ER01",
      "severity": 4,
      "likelihood": 3
    }}
  ]
}}"""


@router.get("/projects/{project_id}/workshop/at4", response_model=AT4WorkshopResponse)
async def get_workshop_at4(
    project_id: UUID,
    strategic_scenario_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:read"))
):
    """
    Récupère les données de l'Atelier 4 (Scénarios opérationnels).
    Optionnel: filtrer par scénario stratégique.
    """
    # Vérifier accès au projet
    project_check = db.execute(
        text("SELECT id, tenant_id FROM risk_project WHERE id = :id AND deleted_at IS NULL"),
        {"id": str(project_id)}
    ).fetchone()

    if not project_check:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    # Vérifier si AT3 a des scénarios stratégiques
    ss_count = db.execute(text("""
        SELECT COUNT(*) FROM risk_strategic_scenario
        WHERE project_id = :project_id AND deleted_at IS NULL
    """), {"project_id": str(project_id)}).scalar()

    can_generate = ss_count > 0
    blocked_reason = None if can_generate else "Aucun scénario stratégique dans AT3"

    # Construire la requête de base
    base_query = """
        SELECT
            os.id,
            os.code,
            os.title,
            os.description,
            os.strategic_scenario_id,
            ss.code as strategic_scenario_code,
            ss.title as strategic_scenario_title,
            os.risk_source_id,
            rs.code as risk_source_code,
            rs.label as risk_source_label,
            os.feared_event_id,
            fe.code as feared_event_code,
            fe.label as feared_event_label,
            os.severity,
            os.likelihood,
            os.risk_score,
            os.risk_level,
            os.matrix_x,
            os.matrix_y,
            os.justification,
            os.source,
            os.created_at
        FROM risk_operational_scenario os
        JOIN risk_strategic_scenario ss ON os.strategic_scenario_id = ss.id
        LEFT JOIN risk_source rs ON os.risk_source_id = rs.id
        LEFT JOIN risk_feared_event fe ON os.feared_event_id = fe.id
        WHERE os.project_id = :project_id AND os.deleted_at IS NULL
    """

    params = {"project_id": str(project_id)}

    if strategic_scenario_id:
        base_query += " AND os.strategic_scenario_id = :ss_id"
        params["ss_id"] = str(strategic_scenario_id)

    base_query += " ORDER BY os.order_index, os.code"

    scenarios_query = db.execute(text(base_query), params)

    scenarios = []
    for row in scenarios_query:
        # Récupérer les biens supports liés
        assets_query = db.execute(text("""
            SELECT a.id, a.code, a.label
            FROM risk_operational_scenario_asset osa
            JOIN risk_asset a ON osa.asset_id = a.id
            WHERE osa.scenario_id = :scenario_id
            ORDER BY a.order_index, a.id
        """), {"scenario_id": str(row.id)})

        assets = [
            OperationalScenarioAsset(id=str(a.id), code=a.code, label=a.label)
            for a in assets_query
        ]

        # Récupérer les étapes
        steps_query = db.execute(text("""
            SELECT id, order_index, action, technique, description
            FROM risk_operational_step
            WHERE operational_scenario_id = :scenario_id
            ORDER BY order_index
        """), {"scenario_id": str(row.id)})

        steps = [
            OperationalStepResponse(
                id=str(s.id),
                order_index=s.order_index,
                action=s.action,
                technique=s.technique,
                description=s.description
            )
            for s in steps_query
        ]

        scenarios.append(OperationalScenarioResponse(
            id=str(row.id),
            code=row.code,
            title=row.title or "",
            description=row.description,
            strategic_scenario_id=str(row.strategic_scenario_id),
            strategic_scenario_code=row.strategic_scenario_code,
            strategic_scenario_title=row.strategic_scenario_title,
            risk_source_id=str(row.risk_source_id) if row.risk_source_id else None,
            risk_source_code=row.risk_source_code,
            risk_source_label=row.risk_source_label,
            feared_event_id=str(row.feared_event_id) if row.feared_event_id else None,
            feared_event_code=row.feared_event_code,
            feared_event_label=row.feared_event_label,
            assets=assets,
            steps=steps,
            severity=row.severity,
            likelihood=row.likelihood,
            risk_score=row.risk_score or 0,
            risk_level=row.risk_level or "FAIBLE",
            matrix_x=row.matrix_x or 0,
            matrix_y=row.matrix_y or 0,
            justification=row.justification,
            source=row.source or 'MANUAL',
            created_at=row.created_at.isoformat() if row.created_at else ""
        ))

    return AT4WorkshopResponse(
        operational_scenarios=scenarios,
        total_count=len(scenarios),
        can_generate=can_generate,
        generation_blocked_reason=blocked_reason
    )


@router.post("/projects/{project_id}/generate-at4", response_model=GenerateAT4Response)
async def generate_at4_scenarios(
    project_id: UUID,
    request: GenerateAT4Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:write"))
):
    """
    Génère les scénarios opérationnels (AT4) via l'IA à partir des scénarios stratégiques (AT3).
    """
    logger.info(f"🎯 [AT4] Génération des scénarios opérationnels pour projet {project_id}")

    # Vérifier accès au projet
    project = db.execute(
        text("SELECT id, label, status, tenant_id FROM risk_project WHERE id = :id AND deleted_at IS NULL"),
        {"id": str(project_id)}
    ).fetchone()

    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    if project.status == 'FROZEN':
        raise HTTPException(status_code=400, detail="Le projet est figé, impossible de générer")

    # Récupérer les scénarios stratégiques à traiter
    ss_query = """
        SELECT
            ss.id, ss.code, ss.title, ss.description,
            ss.risk_source_id, rs.code as rs_code, rs.label as rs_label,
            ss.feared_event_id, fe.code as fe_code, fe.label as fe_label,
            ss.severity, ss.likelihood_raw
        FROM risk_strategic_scenario ss
        LEFT JOIN risk_source rs ON ss.risk_source_id = rs.id
        LEFT JOIN risk_feared_event fe ON ss.feared_event_id = fe.id
        WHERE ss.project_id = :project_id AND ss.deleted_at IS NULL
    """
    params = {"project_id": str(project_id)}

    if request.strategic_scenario_ids:
        ss_query += " AND ss.id = ANY(CAST(:ss_ids AS uuid[]))"
        params["ss_ids"] = [str(sid) for sid in request.strategic_scenario_ids]

    ss_query += " ORDER BY ss.order_index, ss.code"

    strategic_scenarios = db.execute(text(ss_query), params).fetchall()

    if not strategic_scenarios:
        raise HTTPException(status_code=400, detail="Aucun scénario stratégique trouvé")

    # Récupérer les biens supports pour chaque SS
    ss_with_assets = []
    for ss in strategic_scenarios:
        assets = db.execute(text("""
            SELECT a.id, a.code, a.label
            FROM risk_strategic_scenario_asset ssa
            JOIN risk_asset a ON ssa.asset_id = a.id
            WHERE ssa.scenario_id = :ss_id
        """), {"ss_id": str(ss.id)}).fetchall()

        ss_with_assets.append({
            "id": str(ss.id),
            "code": ss.code,
            "title": ss.title,
            "description": ss.description,
            "risk_source_code": ss.rs_code,
            "risk_source_label": ss.rs_label,
            "feared_event_code": ss.fe_code,
            "feared_event_label": ss.fe_label,
            "severity": ss.severity,
            "likelihood": ss.likelihood_raw,
            "assets": [{"code": a.code, "label": a.label} for a in assets]
        })

    # Récupérer tous les biens supports du projet pour référence
    all_assets = db.execute(text("""
        SELECT id, code, label FROM risk_asset
        WHERE project_id = :project_id AND deleted_at IS NULL
    """), {"project_id": str(project_id)}).fetchall()

    assets_map = {a.code: str(a.id) for a in all_assets}

    max_per_ss = min(max(1, request.max_per_ss), 3)  # Entre 1 et 3

    # Appeler l'IA
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")

    # Limiter le nombre de SS par batch pour éviter les prompts trop longs
    MAX_SS_PER_BATCH = 10
    total_ss = len(strategic_scenarios)

    if total_ss > MAX_SS_PER_BATCH:
        logger.info(f"📊 [AT4] {total_ss} scénarios stratégiques - traitement par lots de {MAX_SS_PER_BATCH}")
        # Sélectionner les premiers SS ou les SS spécifiés
        ss_with_assets = ss_with_assets[:MAX_SS_PER_BATCH]
        logger.info(f"🔄 [AT4] Traitement du lot 1: {len(ss_with_assets)} SS")

    # Reconstruire le prompt avec moins de SS
    ss_text = ""
    for ss in ss_with_assets:
        assets_str = ", ".join([f"{a['code']} ({a['label']})" for a in ss["assets"]]) or "Non définis"
        ss_text += f"""
Scénario {ss['code']} : {ss['title']}
- Source de risque : {ss['risk_source_code']} - {ss['risk_source_label']}
- Événement redouté : {ss['feared_event_code']} - {ss['feared_event_label']}
- Biens supports : {assets_str}
- Gravité : {ss['severity']}/4 | Vraisemblance : {ss['likelihood']}/4
"""

    user_prompt_trimmed = f"""Génère {max_per_ss} scénario(s) opérationnel(s) par scénario stratégique.

SCÉNARIOS STRATÉGIQUES :
{ss_text}

Réponds uniquement avec le JSON valide."""

    logger.info(f"🤖 [AT4] Appel IA avec {len(ss_with_assets)} scénarios stratégiques, max {max_per_ss} SO par SS")
    logger.info(f"📏 [AT4] Taille du prompt: {len(user_prompt_trimmed)} chars")

    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            logger.info(f"🌐 [AT4] Envoi requête à {ollama_url}/api/chat avec modèle {ollama_model}")

            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": ollama_model,
                    "messages": [
                        {"role": "system", "content": AT4_GENERATION_PROMPT.format(max_per_ss=max_per_ss)},
                        {"role": "user", "content": user_prompt_trimmed}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": 16384,
                        "num_predict": 8000
                    }
                }
            )

            logger.info(f"📨 [AT4] Réponse Ollama reçue: status={response.status_code}")

            if response.status_code != 200:
                logger.error(f"❌ Ollama error: {response.status_code} - {response.text[:500]}")
                raise HTTPException(status_code=500, detail=f"Erreur du serveur IA: {response.status_code}")

            data = response.json()
            ai_response = data.get("message", {}).get("content", "")

            if not ai_response:
                logger.error(f"❌ [AT4] Réponse IA vide. Data: {str(data)[:500]}")
                raise HTTPException(status_code=500, detail="L'IA a retourné une réponse vide")

            logger.info(f"✅ [AT4] Réponse IA reçue ({len(ai_response)} chars)")
            logger.debug(f"🔍 [AT4] Début réponse: {ai_response[:200]}")

            # Parser le JSON - nettoyage amélioré
            cleaned_response = ai_response.strip()

            # Supprimer les blocs de code markdown
            if "```json" in cleaned_response:
                start_idx = cleaned_response.find("```json") + 7
                end_idx = cleaned_response.rfind("```")
                if end_idx > start_idx:
                    cleaned_response = cleaned_response[start_idx:end_idx].strip()
            elif "```" in cleaned_response:
                start_idx = cleaned_response.find("```") + 3
                end_idx = cleaned_response.rfind("```")
                if end_idx > start_idx:
                    cleaned_response = cleaned_response[start_idx:end_idx].strip()

            # Si la réponse ne commence pas par {, essayer de trouver le JSON
            if not cleaned_response.startswith("{"):
                json_start = cleaned_response.find("{")
                if json_start != -1:
                    # Trouver l'accolade fermante correspondante
                    bracket_count = 0
                    json_end = -1
                    for i, char in enumerate(cleaned_response[json_start:], json_start):
                        if char == "{":
                            bracket_count += 1
                        elif char == "}":
                            bracket_count -= 1
                            if bracket_count == 0:
                                json_end = i + 1
                                break
                    if json_end != -1:
                        cleaned_response = cleaned_response[json_start:json_end]
                        logger.info(f"🔧 [AT4] JSON extrait de la position {json_start} à {json_end}")

            logger.info(f"📝 [AT4] JSON nettoyé: {cleaned_response[:200]}...")

            try:
                scenarios_data = json.loads(cleaned_response)
            except json.JSONDecodeError as e:
                logger.error(f"❌ [AT4] JSON invalide: {e}")
                logger.error(f"Réponse nettoyée (500 premiers chars): {cleaned_response[:500]}")
                logger.error(f"Réponse brute (500 premiers chars): {ai_response[:500]}")
                raise HTTPException(status_code=500, detail=f"L'IA n'a pas retourné un format JSON valide: {str(e)}")

            # Extraire la liste des scénarios
            if isinstance(scenarios_data, dict) and "operational_scenarios" in scenarios_data:
                scenarios_list = scenarios_data["operational_scenarios"]
            elif isinstance(scenarios_data, list):
                scenarios_list = scenarios_data
            else:
                scenarios_list = [scenarios_data]

            # Créer un mapping des codes SS vers IDs
            ss_code_to_id = {ss["code"]: ss["id"] for ss in ss_with_assets}
            # Mapping alternatif: par titre pour fallback
            ss_title_to_id = {ss["title"].strip().lower(): ss["id"] for ss in ss_with_assets if ss.get("title")}

            logger.info(f"🗺️ [AT4] Mapping SS codes: {list(ss_code_to_id.keys())}")
            logger.info(f"📋 [AT4] Scénarios générés par IA: {len(scenarios_list)}")

            # Récupérer le prochain numéro de code SO
            max_code_result = db.execute(text("""
                SELECT MAX(CAST(SUBSTRING(code FROM 3) AS INTEGER)) as max_num
                FROM risk_operational_scenario
                WHERE project_id = :project_id AND code LIKE 'SO%'
            """), {"project_id": str(project_id)}).fetchone()
            next_code_num = (max_code_result.max_num or 0) + 1 if max_code_result else 1

            # Compter les SO existants pour order_index
            existing_count = db.execute(text("""
                SELECT COUNT(*) FROM risk_operational_scenario
                WHERE project_id = :project_id AND deleted_at IS NULL
            """), {"project_id": str(project_id)}).scalar() or 0

            # Créer un mapping des sources de risques et événements redoutés
            rs_map = {}
            for ss in ss_with_assets:
                if ss["risk_source_code"]:
                    rs_result = db.execute(text("""
                        SELECT id FROM risk_source WHERE code = :code AND project_id = :project_id
                    """), {"code": ss["risk_source_code"], "project_id": str(project_id)}).fetchone()
                    if rs_result:
                        rs_map[ss["risk_source_code"]] = str(rs_result.id)

            fe_map = {}
            for ss in ss_with_assets:
                if ss["feared_event_code"]:
                    fe_result = db.execute(text("""
                        SELECT id FROM risk_feared_event WHERE code = :code AND project_id = :project_id
                    """), {"code": ss["feared_event_code"], "project_id": str(project_id)}).fetchone()
                    if fe_result:
                        fe_map[ss["feared_event_code"]] = str(fe_result.id)

            scenarios_created = 0
            scenarios_skipped = 0
            for i, scenario in enumerate(scenarios_list):
                # Générer un code unique
                scenario_code = f"SO{str(next_code_num + i).zfill(2)}"

                # Trouver l'ID du scénario stratégique parent
                ss_code = scenario.get("strategic_scenario_code", "")
                ss_id = ss_code_to_id.get(ss_code)

                # Fallback: essayer par titre si le code ne matche pas
                if not ss_id:
                    ss_title = scenario.get("strategic_scenario_title", "").strip().lower()
                    ss_id = ss_title_to_id.get(ss_title)
                    if ss_id:
                        logger.info(f"🔄 [AT4] SS code {ss_code} non trouvé, mais titre '{ss_title}' matché")

                # Fallback 2: prendre le premier SS disponible si un seul SS dans la requête
                if not ss_id and len(ss_with_assets) == 1:
                    ss_id = ss_with_assets[0]["id"]
                    logger.info(f"🔄 [AT4] Fallback: utilisation du seul SS disponible")

                # Fallback 3: essayer de matcher par index (SO01 → SS01, etc.)
                if not ss_id:
                    # Extraire le numéro du code SO généré par l'IA
                    so_code = scenario.get("code", "")
                    if so_code.startswith("SO") and len(so_code) >= 4:
                        try:
                            so_num = int(so_code[2:])
                            # Chercher le SS correspondant dans la liste
                            for ss in ss_with_assets:
                                if ss["code"].startswith("SS"):
                                    try:
                                        ss_num = int(ss["code"][2:])
                                        if ss_num == so_num or (so_num > 0 and so_num <= len(ss_with_assets)):
                                            ss_id = ss_with_assets[min(so_num - 1, len(ss_with_assets) - 1)]["id"]
                                            logger.info(f"🔄 [AT4] Fallback index: SO{so_num} → SS index {min(so_num - 1, len(ss_with_assets) - 1)}")
                                            break
                                    except (ValueError, IndexError):
                                        pass
                        except ValueError:
                            pass

                if not ss_id:
                    logger.warning(f"⚠️ [AT4] SS code '{ss_code}' non trouvé dans mapping {list(ss_code_to_id.keys())}, ignoré")
                    scenarios_skipped += 1
                    continue

                # Calculer le risque opérationnel
                severity_val = scenario.get("severity", 3)
                likelihood_val = scenario.get("likelihood", 2)
                risk_data = calculate_strategic_risk(severity_val, likelihood_val)

                # IDs des éléments liés
                rs_code = scenario.get("risk_source_code", "")
                rs_id = rs_map.get(rs_code)

                fe_code = scenario.get("feared_event_code", "")
                fe_id = fe_map.get(fe_code)

                # Insérer le scénario opérationnel
                scenario_id = str(uuid.uuid4())
                db.execute(text("""
                    INSERT INTO risk_operational_scenario (
                        id, project_id, code, title, description,
                        strategic_scenario_id, risk_source_id, feared_event_id,
                        severity, likelihood, risk_score, risk_level, matrix_x, matrix_y,
                        justification, source, order_index, created_at
                    ) VALUES (
                        :id, :project_id, :code, :title, :description,
                        CAST(:ss_id AS uuid), CAST(:rs_id AS uuid), CAST(:fe_id AS uuid),
                        :severity, :likelihood, :risk_score, :risk_level, :matrix_x, :matrix_y,
                        :justification, 'AI', :order_index, NOW()
                    )
                """), {
                    "id": scenario_id,
                    "project_id": str(project_id),
                    "code": scenario_code,
                    "title": scenario.get("title", "Scénario opérationnel"),
                    "description": scenario.get("description", ""),
                    "ss_id": ss_id,
                    "rs_id": rs_id,
                    "fe_id": fe_id,
                    "severity": severity_val,
                    "likelihood": likelihood_val,
                    "risk_score": risk_data["risk_score"],
                    "risk_level": risk_data["risk_level"],
                    "matrix_x": risk_data["matrix_x"],
                    "matrix_y": risk_data["matrix_y"],
                    "justification": scenario.get("justification", ""),
                    "order_index": existing_count + i
                })

                # Lier les biens supports
                asset_codes = scenario.get("asset_codes", [])
                for asset_code in asset_codes:
                    asset_id = assets_map.get(asset_code)
                    if asset_id:
                        db.execute(text("""
                            INSERT INTO risk_operational_scenario_asset (id, scenario_id, asset_id)
                            VALUES (gen_random_uuid(), CAST(:scenario_id AS uuid), CAST(:asset_id AS uuid))
                            ON CONFLICT DO NOTHING
                        """), {"scenario_id": scenario_id, "asset_id": asset_id})

                # Créer les étapes
                steps = scenario.get("steps", [])
                for step in steps:
                    db.execute(text("""
                        INSERT INTO risk_operational_step (
                            id, operational_scenario_id, order_index, action, technique, description, created_at
                        ) VALUES (
                            gen_random_uuid(), CAST(:scenario_id AS uuid), :order_index, :action, :technique, :description, NOW()
                        )
                    """), {
                        "scenario_id": scenario_id,
                        "order_index": step.get("order_index", 1),
                        "action": step.get("action", "Étape"),
                        "technique": step.get("technique", ""),
                        "description": step.get("description", "")
                    })

                scenarios_created += 1

            db.commit()

            logger.info(f"✅ [AT4] {scenarios_created} scénarios opérationnels créés, {scenarios_skipped} ignorés")

            message = f"{scenarios_created} scénarios opérationnels générés avec succès"
            if scenarios_skipped > 0:
                message += f" ({scenarios_skipped} ignorés car codes SS non trouvés)"
            if total_ss > MAX_SS_PER_BATCH:
                message += f". Note: {len(ss_with_assets)}/{total_ss} SS traités (lot 1). Relancez pour traiter les suivants."

            return GenerateAT4Response(
                success=True,
                scenarios_created=scenarios_created,
                message=message
            )

    except httpx.TimeoutException:
        logger.error("❌ [AT4] Timeout IA")
        raise HTTPException(status_code=504, detail="Timeout: L'IA met trop de temps à répondre")
    except httpx.ConnectError:
        logger.error("❌ [AT4] Connexion IA impossible")
        raise HTTPException(status_code=503, detail="Impossible de se connecter au serveur IA")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AT4] Erreur: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_id}/operational-scenarios/{scenario_id}")
async def delete_operational_scenario(
    project_id: UUID,
    scenario_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:write"))
):
    """Supprime un scénario opérationnel (hard delete)."""

    # Vérifier que le scénario appartient au projet
    scenario = db.execute(text("""
        SELECT os.id, rp.status FROM risk_operational_scenario os
        JOIN risk_project rp ON os.project_id = rp.id
        WHERE os.id = :scenario_id AND os.project_id = :project_id AND os.deleted_at IS NULL
    """), {"scenario_id": str(scenario_id), "project_id": str(project_id)}).fetchone()

    if not scenario:
        raise HTTPException(status_code=404, detail="Scénario opérationnel non trouvé")

    if scenario.status == 'FROZEN':
        raise HTTPException(status_code=400, detail="Le projet est figé")

    # Supprimer les étapes
    db.execute(text("""
        DELETE FROM risk_operational_step WHERE operational_scenario_id = :id
    """), {"id": str(scenario_id)})

    # Supprimer les liens avec les biens supports
    db.execute(text("""
        DELETE FROM risk_operational_scenario_asset WHERE scenario_id = :id
    """), {"id": str(scenario_id)})

    # Hard delete du scénario
    db.execute(text("""
        DELETE FROM risk_operational_scenario WHERE id = :id
    """), {"id": str(scenario_id)})

    db.commit()

    return {"success": True, "message": "Scénario opérationnel supprimé"}


# ===========================================================================
# AT5 - MATRICE DES RISQUES
# ===========================================================================

class MatrixCell(BaseModel):
    """Cellule de la matrice de risques."""
    severity: int  # 1-4 (axe Y)
    likelihood: int  # 1-4 (axe X)
    scenario_count: int
    max_risk_band: str  # FAIBLE, MODERE, IMPORTANT, CRITIQUE
    scenario_ids: List[str]


class MatrixScenario(BaseModel):
    """Scénario pour affichage dans la matrice."""
    id: str
    code: str
    title: str
    type: str  # 'strategic' ou 'operational'
    risk_source_code: Optional[str] = None
    risk_source_label: Optional[str] = None
    feared_event_code: Optional[str] = None
    feared_event_label: Optional[str] = None
    severity: int
    likelihood: int
    risk_score: int
    risk_level: str
    assets: List[str] = []


class AT5WorkshopResponse(BaseModel):
    """Réponse de l'atelier AT5 - Matrice des risques."""
    project_id: str
    project_name: str
    can_build: bool
    blocked_reason: Optional[str] = None
    matrix: List[MatrixCell]
    scenarios: List[MatrixScenario]
    stats: dict
    # Analyse IA existante (si déjà générée)
    ai_analysis: Optional[str] = None
    ai_analysis_at: Optional[str] = None


class AT5AnalysisRequest(BaseModel):
    """Requête d'analyse IA de la matrice."""
    view_type: str = "operational"  # 'strategic', 'operational', 'combined'


class AT5AnalysisResponse(BaseModel):
    """Réponse d'analyse IA de la matrice."""
    success: bool
    analysis: Optional[str] = None
    error: Optional[str] = None


def build_risk_matrix(scenarios: List[dict]) -> tuple[List[dict], dict]:
    """
    Construit la matrice 4x4 à partir des scénarios.
    Retourne (cells, stats).
    """
    # Initialiser la matrice 4x4
    matrix_data = {}
    for g in range(1, 5):
        for v in range(1, 5):
            matrix_data[(g, v)] = {
                "severity": g,
                "likelihood": v,
                "scenario_count": 0,
                "max_risk_band": "FAIBLE",
                "scenario_ids": []
            }

    # Remplir avec les scénarios
    risk_counts = {"FAIBLE": 0, "MODERE": 0, "IMPORTANT": 0, "CRITIQUE": 0}

    for s in scenarios:
        g = min(max(1, s.get("severity", 1)), 4)
        v = min(max(1, s.get("likelihood", 1)), 4)
        cell = matrix_data[(g, v)]
        cell["scenario_count"] += 1
        cell["scenario_ids"].append(s["id"])

        # Mettre à jour le max risk band
        risk_level = s.get("risk_level", "FAIBLE")
        risk_counts[risk_level] = risk_counts.get(risk_level, 0) + 1

        band_order = {"FAIBLE": 1, "MODERE": 2, "IMPORTANT": 3, "CRITIQUE": 4}
        if band_order.get(risk_level, 1) > band_order.get(cell["max_risk_band"], 1):
            cell["max_risk_band"] = risk_level

    cells = list(matrix_data.values())

    stats = {
        "total_scenarios": len(scenarios),
        "by_risk_level": risk_counts,
        "critical_count": risk_counts.get("CRITIQUE", 0),
        "important_count": risk_counts.get("IMPORTANT", 0),
        "cells_with_scenarios": sum(1 for c in cells if c["scenario_count"] > 0)
    }

    return cells, stats


@router.get("/projects/{project_id}/workshop/at5", response_model=AT5WorkshopResponse)
async def get_workshop_at5(
    project_id: UUID,
    view_type: str = "operational",  # 'strategic', 'operational', 'combined'
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:read"))
):
    """
    Récupère les données de l'Atelier 5 (Matrice des risques).

    - view_type: 'strategic' (SS), 'operational' (SO), 'combined' (SS+SO)
    """
    logger.info(f"📊 [AT5] Récupération matrice pour projet {project_id}, vue: {view_type}")

    # Vérifier accès au projet et récupérer l'analyse IA existante
    project = db.execute(
        text("""
            SELECT id, label, status, tenant_id, ai_matrix_analysis, ai_matrix_analysis_at
            FROM risk_project WHERE id = :id AND deleted_at IS NULL
        """),
        {"id": str(project_id)}
    ).fetchone()

    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    # Extraire l'analyse IA existante
    existing_analysis = getattr(project, 'ai_matrix_analysis', None)
    existing_analysis_at = getattr(project, 'ai_matrix_analysis_at', None)

    scenarios = []

    # Récupérer les scénarios selon le type de vue
    if view_type in ["strategic", "combined"]:
        ss_query = """
            SELECT
                ss.id, ss.code, ss.title,
                rs.code as rs_code, rs.label as rs_label,
                fe.code as fe_code, fe.label as fe_label,
                ss.severity, ss.likelihood_raw as likelihood,
                ss.risk_score, ss.risk_level
            FROM risk_strategic_scenario ss
            LEFT JOIN risk_source rs ON ss.risk_source_id = rs.id
            LEFT JOIN risk_feared_event fe ON ss.feared_event_id = fe.id
            WHERE ss.project_id = :project_id AND ss.deleted_at IS NULL
            ORDER BY ss.risk_score DESC, ss.code
        """
        ss_results = db.execute(text(ss_query), {"project_id": str(project_id)}).fetchall()

        for ss in ss_results:
            # Récupérer les assets liés
            assets = db.execute(text("""
                SELECT a.code FROM risk_strategic_scenario_asset ssa
                JOIN risk_asset a ON ssa.asset_id = a.id
                WHERE ssa.scenario_id = :ss_id
            """), {"ss_id": str(ss.id)}).fetchall()

            scenarios.append({
                "id": str(ss.id),
                "code": ss.code,
                "title": ss.title,
                "type": "strategic",
                "risk_source_code": ss.rs_code,
                "risk_source_label": ss.rs_label,
                "feared_event_code": ss.fe_code,
                "feared_event_label": ss.fe_label,
                "severity": ss.severity or 1,
                "likelihood": ss.likelihood or 1,
                "risk_score": ss.risk_score or 1,
                "risk_level": ss.risk_level or "FAIBLE",
                "assets": [a.code for a in assets]
            })

    if view_type in ["operational", "combined"]:
        so_query = """
            SELECT
                os.id, os.code, os.title,
                rs.code as rs_code, rs.label as rs_label,
                fe.code as fe_code, fe.label as fe_label,
                os.severity, os.likelihood,
                os.risk_score, os.risk_level
            FROM risk_operational_scenario os
            LEFT JOIN risk_source rs ON os.risk_source_id = rs.id
            LEFT JOIN risk_feared_event fe ON os.feared_event_id = fe.id
            WHERE os.project_id = :project_id AND os.deleted_at IS NULL
            ORDER BY os.risk_score DESC, os.code
        """
        so_results = db.execute(text(so_query), {"project_id": str(project_id)}).fetchall()

        for so in so_results:
            # Récupérer les assets liés
            assets = db.execute(text("""
                SELECT a.code FROM risk_operational_scenario_asset soa
                JOIN risk_asset a ON soa.asset_id = a.id
                WHERE soa.scenario_id = :so_id
            """), {"so_id": str(so.id)}).fetchall()

            scenarios.append({
                "id": str(so.id),
                "code": so.code,
                "title": so.title,
                "type": "operational",
                "risk_source_code": so.rs_code,
                "risk_source_label": so.rs_label,
                "feared_event_code": so.fe_code,
                "feared_event_label": so.fe_label,
                "severity": so.severity or 1,
                "likelihood": so.likelihood or 1,
                "risk_score": so.risk_score or 1,
                "risk_level": so.risk_level or "FAIBLE",
                "assets": [a.code for a in assets]
            })

    # Vérifier si on peut construire la matrice
    can_build = len(scenarios) > 0
    blocked_reason = None
    if not can_build:
        if view_type == "strategic":
            blocked_reason = "Aucun scénario stratégique (AT3) n'a été créé"
        elif view_type == "operational":
            blocked_reason = "Aucun scénario opérationnel (AT4) n'a été créé"
        else:
            blocked_reason = "Aucun scénario n'a été créé (AT3/AT4)"

    # Construire la matrice
    matrix_cells, stats = build_risk_matrix(scenarios)

    logger.info(f"✅ [AT5] Matrice construite: {stats['total_scenarios']} scénarios, {stats['cells_with_scenarios']} cellules actives")

    return AT5WorkshopResponse(
        project_id=str(project_id),
        project_name=project.label,
        can_build=can_build,
        blocked_reason=blocked_reason,
        matrix=matrix_cells,
        scenarios=scenarios,
        stats=stats,
        ai_analysis=existing_analysis,
        ai_analysis_at=existing_analysis_at.isoformat() if existing_analysis_at else None
    )


# Prompt IA pour l'analyse de la matrice
AT5_ANALYSIS_PROMPT = """Tu es un expert en analyse de risques EBIOS RM.
Tu DOIS respecter la structure, les règles de classification, les formules et les résultats fournis par l'application Cybergard AI.

Ton rôle :
- analyser les scénarios produits dans AT3 (stratégiques) et AT4 (opérationnels)
- vérifier la cohérence Gravité (G), Vraisemblance (V), Risque (R = G × V)
- classer correctement les scénarios dans la matrice 4×4
- identifier les risques les plus critiques
- produire une analyse synthétique et priorisée pour l'utilisateur

Tu ne dois JAMAIS modifier les données brutes (G, V, score).
Tu peux uniquement commenter, analyser et formuler des recommandations.

BANDES DE RISQUE:
- Score 1-3 : FAIBLE (vert)
- Score 4-7 : MODÉRÉ (jaune)
- Score 8-11 : IMPORTANT (orange)
- Score 12-16 : CRITIQUE (rouge)

FORMAT DE RÉPONSE (en français, structuré en markdown):
1. **Synthèse générale** - Vue d'ensemble du niveau de risque
2. **Top scénarios critiques** - Les 5 scénarios les plus risqués avec leurs scores
3. **Tendances observées** - Sources de risque dominantes, assets les plus ciblés, événements récurrents
4. **Zones chaudes** - Cellules de la matrice les plus chargées
5. **Priorités d'atténuation** - Court/moyen/long terme
6. **Recommandations structurelles** - Mesures de fond à considérer"""


@router.post("/projects/{project_id}/at5/analyze", response_model=AT5AnalysisResponse)
async def analyze_risk_matrix_with_ai(
    project_id: UUID,
    request: AT5AnalysisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:read"))
):
    """
    Analyse la matrice des risques avec l'IA et génère des recommandations.
    """
    logger.info(f"🤖 [AT5] Analyse IA de la matrice pour projet {project_id}")

    # Récupérer les données AT5
    at5_response = await get_workshop_at5(project_id, request.view_type, db, current_user)

    if not at5_response.can_build:
        return AT5AnalysisResponse(
            success=False,
            error=at5_response.blocked_reason or "Impossible d'analyser une matrice vide"
        )

    # Préparer les données pour l'IA
    scenarios_text = ""
    for s in at5_response.scenarios[:30]:  # Limiter à 30 scénarios
        assets_str = ", ".join(s.assets) if s.assets else "Non définis"
        scenarios_text += f"""
- {s.code} ({s.type}): {s.title}
  Source: {s.risk_source_code} | Event: {s.feared_event_code}
  G={s.severity}, V={s.likelihood}, R={s.risk_score} ({s.risk_level})
  Assets: {assets_str}
"""

    matrix_text = ""
    for cell in at5_response.matrix:
        if cell.scenario_count > 0:
            matrix_text += f"- Case G={cell.severity}, V={cell.likelihood}: {cell.scenario_count} scénarios ({cell.max_risk_band})\n"

    stats = at5_response.stats

    user_prompt = f"""Voici les données de la matrice de risques EBIOS RM à analyser:

=== STATISTIQUES ===
- Total scénarios: {stats['total_scenarios']}
- Critiques: {stats['critical_count']}
- Importants: {stats['important_count']}
- Cellules actives: {stats['cells_with_scenarios']}

=== SCÉNARIOS ===
{scenarios_text}

=== MATRICE (cellules non vides) ===
{matrix_text}

Analyse cette matrice et fournis tes recommandations en français."""

    # Appeler l'IA
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": ollama_model,
                    "messages": [
                        {"role": "system", "content": AT5_ANALYSIS_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": 16384,
                        "num_predict": 4000
                    }
                }
            )

            if response.status_code != 200:
                logger.error(f"❌ [AT5] Erreur Ollama: {response.status_code}")
                return AT5AnalysisResponse(
                    success=False,
                    error="Erreur lors de l'appel à l'IA"
                )

            data = response.json()
            ai_response = data.get("message", {}).get("content", "")

            if not ai_response:
                return AT5AnalysisResponse(
                    success=False,
                    error="L'IA n'a pas retourné de réponse"
                )

            logger.info(f"✅ [AT5] Analyse IA générée ({len(ai_response)} chars)")

            # Sauvegarder l'analyse en base de données
            try:
                db.execute(text("""
                    UPDATE risk_project
                    SET ai_matrix_analysis = :analysis,
                        ai_matrix_analysis_at = NOW()
                    WHERE id = :project_id
                """), {
                    "analysis": ai_response,
                    "project_id": str(project_id)
                })
                db.commit()
                logger.info(f"💾 [AT5] Analyse sauvegardée en BDD pour projet {project_id}")
            except Exception as save_err:
                logger.warning(f"⚠️ [AT5] Erreur sauvegarde analyse: {save_err}")
                # Ne pas bloquer le retour même si la sauvegarde échoue

            return AT5AnalysisResponse(
                success=True,
                analysis=ai_response
            )

    except httpx.TimeoutException:
        logger.error("❌ [AT5] Timeout IA")
        return AT5AnalysisResponse(
            success=False,
            error="Timeout: L'IA met trop de temps à répondre"
        )
    except Exception as e:
        logger.error(f"❌ [AT5] Erreur: {e}")
        return AT5AnalysisResponse(
            success=False,
            error=str(e)
        )


# ==============================================================================
# AT6 - GÉNÉRATION DU PLAN D'ACTIONS
# ==============================================================================

AT6_GENERATION_PROMPT = """Tu es un expert en cybersécurité et en analyse de risques EBIOS RM.

À partir des données du projet (valeurs métier, biens supports, sources de risques AT2, scénarios stratégiques AT3, scénarios opérationnels AT4, matrice AT5), génère un PLAN D'ACTIONS COMPLET (AT6) structuré.

RÈGLES:
- Créer des actions uniquement pour les risques dont le score ≥ 8
- Proposer entre 2 et 6 actions par scénario important ou critique
- Chaque action doit être alignée sur les bonnes pratiques cyber (ISO 27001, NIST CSF, CIS)
- Pas d'actions génériques vagues — toujours contextualisées
- Les actions doivent être complémentaires, pas redondantes

CATÉGORIES D'ACTIONS:
- Préventive: durcissement, MFA, segmentation, bastion, EDR, sauvegardes, anti-phishing
- Détective: supervision, journalisation, SIEM, alertes, monitoring
- Corrective: playbooks, plans de reprise, remédiation
- Pilotage: gouvernance, procédures, politique SSI, sensibilisation

Pour chaque action, produis un objet JSON avec les champs suivants:
- action_id: identifiant unique format "ACT_RISK_<RefScenario>_<Index>" (ex: ACT_RISK_SS01_02)
- titre: court et actionnable
- description: détaillée
- objectif: "Réduire la vraisemblance", "Réduire la gravité" ou "Réduire la vraisemblance et la gravité"
- categorie: "Préventive", "Détective", "Corrective" ou "Pilotage"
- priorite: "Critique", "Haute", "Modérée", "Faible"
- effort: "Faible", "Moyen", "Élevé"
- cout_estime: "Faible", "Moyen", "Élevé"
- justification: raisonnement cyber expliquant pourquoi cette action
- sources_couvertes: ["SRxx"] - codes des sources de risques traitées
- biens_supports: ["BSxx"] - codes des biens supports protégés
- scenarios_couverts: ["SSxx", "SOxx"] - codes des scénarios couverts
- risque_initial: score du scénario avant action (ex: 12)
- risque_cible: score visé après action (ex: 6)
- responsable_suggere: rôle recommandé (ex: "RSSI", "DSI", "Équipe Réseau")
- delai_recommande: horizon de mise en œuvre (ex: "3 mois", "6 mois")
- statut_initial: "À faire"
- references_normatives: ["ISO27001 A.x.x", "NIST PR.AC-1"] - références ISO/NIST pertinentes

FORMAT DE SORTIE STRICT JSON (pas de texte avant ou après):
{{
  "actions": [
    {{
      "action_id": "ACT_RISK_SS01_01",
      "titre": "Déploiement de l'authentification multifacteur (MFA)",
      "description": "Imposer l'authentification multifacteur sur tous les accès distants et comptes privilégiés",
      "objectif": "Réduire la vraisemblance",
      "categorie": "Préventive",
      "priorite": "Critique",
      "effort": "Moyen",
      "cout_estime": "Moyen",
      "justification": "L'accès initial du scénario SS01 est obtenu par vol de credentials. Le MFA réduit fortement ce vecteur.",
      "sources_couvertes": ["SR10"],
      "biens_supports": ["BS01", "BS07"],
      "scenarios_couverts": ["SS01", "SO01"],
      "risque_initial": 12,
      "risque_cible": 6,
      "responsable_suggere": "RSSI",
      "delai_recommande": "3 mois",
      "statut_initial": "À faire",
      "references_normatives": ["ISO27001 A.9.2.3", "NIST PR.AC-1"]
    }}
  ]
}}"""


class GenerateActionPlanResponse(BaseModel):
    """Réponse de la génération du plan d'actions"""
    success: bool
    actions_created: int = 0
    message: str = ""
    error: Optional[str] = None


@router.post("/projects/{project_id}/generate-action-plan", response_model=GenerateActionPlanResponse)
async def generate_action_plan(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("risk_project:update"))
):
    """
    Génère le plan d'actions (AT6) avec l'IA à partir des scénarios AT3/AT4 et de la matrice AT5.

    L'IA analyse les risques significatifs (score ≥ 8) et génère des actions
    classées en 4 catégories EBIOS: Préventive, Détection, Organisation, Fournisseurs.
    """
    logger.info(f"🤖 [AT6] Génération du plan d'actions pour projet {project_id}")

    try:
        # 1. Récupérer les scénarios stratégiques AT3
        at3_query = text("""
            SELECT ss.id, ss.code, ss.title, ss.severity, ss.likelihood_raw as likelihood,
                   ss.risk_score, ss.risk_level,
                   rs.code as source_code, fe.code as feared_event_code
            FROM risk_strategic_scenario ss
            LEFT JOIN risk_source rs ON ss.risk_source_id = rs.id
            LEFT JOIN risk_feared_event fe ON ss.feared_event_id = fe.id
            WHERE ss.project_id = CAST(:project_id AS uuid)
              AND ss.deleted_at IS NULL
        """)
        at3_rows = db.execute(at3_query, {"project_id": str(project_id)}).fetchall()

        # 2. Récupérer les scénarios opérationnels AT4
        at4_query = text("""
            SELECT os.id, os.code, os.title, os.severity, os.likelihood,
                   os.risk_score, os.risk_level,
                   ss.code as strategic_code,
                   rs.code as source_code
            FROM risk_operational_scenario os
            LEFT JOIN risk_strategic_scenario ss ON os.strategic_scenario_id = ss.id
            LEFT JOIN risk_source rs ON os.risk_source_id = rs.id
            WHERE os.project_id = CAST(:project_id AS uuid)
              AND os.deleted_at IS NULL
        """)
        at4_rows = db.execute(at4_query, {"project_id": str(project_id)}).fetchall()

        # 3. Récupérer les biens supports
        assets_query = text("""
            SELECT id, code, label, type, criticality FROM risk_asset
            WHERE project_id = CAST(:project_id AS uuid)
              AND deleted_at IS NULL
        """)
        assets = db.execute(assets_query, {"project_id": str(project_id)}).fetchall()
        assets_dict = {a.code: {"label": a.label, "type": a.type, "criticality": a.criticality} for a in assets if a.code}

        # 4. Récupérer les sources de risques
        sources_query = text("""
            SELECT id, code, label, relevance, is_selected FROM risk_source
            WHERE project_id = CAST(:project_id AS uuid)
              AND deleted_at IS NULL
              AND is_selected = true
        """)
        sources = db.execute(sources_query, {"project_id": str(project_id)}).fetchall()
        sources_dict = {s.code: {"label": s.label, "relevance": s.relevance} for s in sources if s.code}

        # 5. Construire le contexte pour l'IA
        scenarios_text = "=== SCÉNARIOS STRATÉGIQUES (AT3) ===\n"
        for row in at3_rows:
            score = row.risk_score or ((row.severity or 1) * (row.likelihood or 1))
            risk_level = row.risk_level or ("CRITIQUE" if score >= 12 else "IMPORTANT" if score >= 8 else "MODÉRÉ" if score >= 4 else "FAIBLE")
            scenarios_text += f"""
- {row.code}: {row.title}
  Gravité: {row.severity}, Vraisemblance: {row.likelihood}, Score: {score} ({risk_level})
  Source: {row.source_code or 'N/A'}, Événement redouté: {row.feared_event_code or 'N/A'}
"""

        scenarios_text += "\n=== SCÉNARIOS OPÉRATIONNELS (AT4) ===\n"
        for row in at4_rows:
            score = row.risk_score or ((row.severity or 1) * (row.likelihood or 1))
            risk_level = row.risk_level or ("CRITIQUE" if score >= 12 else "IMPORTANT" if score >= 8 else "MODÉRÉ" if score >= 4 else "FAIBLE")
            scenarios_text += f"""
- {row.code}: {row.title}
  Gravité: {row.severity}, Vraisemblance: {row.likelihood}, Score: {score} ({risk_level})
  Scénario stratégique: {row.strategic_code or 'N/A'}, Source: {row.source_code or 'N/A'}
"""

        assets_text = "\n=== BIENS SUPPORTS ===\n"
        for code, info in assets_dict.items():
            criticality_label = ["Faible", "Moyenne", "Haute", "Critique"][min(info.get("criticality", 2) - 1, 3)]
            assets_text += f"- {code}: {info.get('label', 'N/A')} (Type: {info.get('type') or 'N/A'}, Criticité: {criticality_label})\n"

        sources_text = "\n=== SOURCES DE RISQUES ===\n"
        for code, info in sources_dict.items():
            relevance_label = ["Faible", "Moyenne", "Haute", "Critique"][min(info.get("relevance", 2) - 1, 3)]
            sources_text += f"- {code}: {info.get('label', 'N/A')} (Pertinence: {relevance_label})\n"

        user_prompt = f"""Voici les données du projet EBIOS RM pour générer le plan d'actions:

{scenarios_text}
{assets_text}
{sources_text}

Génère le plan d'actions en JSON pour tous les scénarios avec un score ≥ 8.
"""

        # 6. Appeler l'IA
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_MODEL", "glm-4.6:cloud")

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": ollama_model,
                    "messages": [
                        {"role": "system", "content": AT6_GENERATION_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_ctx": 16384,
                        "num_predict": 8000
                    }
                }
            )

            if response.status_code != 200:
                logger.error(f"❌ [AT6] Erreur Ollama: {response.status_code}")
                return GenerateActionPlanResponse(
                    success=False,
                    error="Erreur lors de l'appel à l'IA"
                )

            data = response.json()
            ai_response = data.get("message", {}).get("content", "")

            if not ai_response:
                return GenerateActionPlanResponse(
                    success=False,
                    error="L'IA n'a pas retourné de réponse"
                )

        # 7. Parser le JSON généré avec nettoyage robuste
        import re

        def repair_json(json_str: str) -> str:
            """Répare les erreurs courantes dans le JSON généré par l'IA."""
            repaired = json_str

            # 1. Enlever les virgules en trop avant ] ou }
            repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)

            # 2. Enlever les virgules en trop après [ ou {
            repaired = re.sub(r'([{\[])\s*,', r'\1', repaired)

            # 3. Ajouter les virgules manquantes entre objets } {
            repaired = re.sub(r'\}(\s*)\{', r'},\1{', repaired)

            # 4. Ajouter les virgules manquantes entre ] et "
            repaired = re.sub(r'\](\s*)"', r'],\1"', repaired)

            # 5. Corriger les doubles virgules
            repaired = re.sub(r',\s*,', ',', repaired)

            # 6. Corriger les guillemets non échappés dans les valeurs
            # Trouver les valeurs de string et échapper les guillemets internes
            def escape_inner_quotes(match):
                key = match.group(1)
                value = match.group(2)
                # Échapper les guillemets non échappés dans la valeur
                escaped_value = re.sub(r'(?<!\\)"(?!,|\s*}|\s*])', r'\"', value)
                return f'"{key}": "{escaped_value}"'

            # Pattern pour trouver "key": "value" avec potentiels guillemets non échappés
            # (simplifié, ne gère pas tous les cas)

            # 7. S'assurer que le JSON est bien fermé
            open_braces = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')

            if open_braces > 0:
                repaired += '}' * open_braces
            if open_brackets > 0:
                repaired += ']' * open_brackets

            # 8. Enlever le texte après le dernier } ou ] valide
            # Trouver la dernière fermeture valide
            last_brace = repaired.rfind('}')
            last_bracket = repaired.rfind(']')
            last_close = max(last_brace, last_bracket)
            if last_close > 0 and last_close < len(repaired) - 1:
                repaired = repaired[:last_close + 1]

            return repaired

        def clean_and_parse_json(raw_response: str) -> dict:
            """Nettoie et parse le JSON de l'IA de manière robuste."""
            cleaned = raw_response.strip()

            # Enlever les balises markdown
            if "```" in cleaned:
                # Extraire le contenu entre les balises
                match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned)
                if match:
                    cleaned = match.group(1).strip()
                else:
                    cleaned = re.sub(r'```(?:json)?', '', cleaned).strip()

            # Chercher le JSON object principal
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if not json_match:
                # Essayer de trouver juste un array d'actions
                array_match = re.search(r'\[[\s\S]*\]', cleaned)
                if array_match:
                    try:
                        return {"actions": json.loads(repair_json(array_match.group()))}
                    except:
                        pass
                raise ValueError("Pas de JSON trouvé")

            json_str = json_match.group()

            # Tentative 1: Parser directement
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.debug(f"Tentative 1 échouée: {e}")

            # Tentative 2: Réparer puis parser
            repaired = repair_json(json_str)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as e:
                logger.debug(f"Tentative 2 (repair) échouée: {e}")

            # Tentative 3: Extraire les actions une par une avec regex
            actions = []
            # Pattern plus permissif pour capturer les objets action
            action_blocks = re.split(r'\},\s*\{', json_str)
            for i, block in enumerate(action_blocks):
                # Reconstruire l'objet
                if not block.startswith('{'):
                    block = '{' + block
                if not block.endswith('}'):
                    block = block + '}'

                try:
                    action = json.loads(repair_json(block))
                    if "code_action" in action or "titre" in action or "title" in action:
                        actions.append(action)
                except:
                    pass

            if actions:
                logger.info(f"📋 [AT6] Récupéré {len(actions)} actions via extraction individuelle")
                return {"actions": actions}

            raise ValueError("Impossible de parser le JSON après nettoyage")

        try:
            actions_data = clean_and_parse_json(ai_response)
            actions_list = actions_data.get("actions", [])
            logger.info(f"📋 [AT6] JSON parsé avec succès: {len(actions_list)} actions trouvées")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"❌ [AT6] Erreur parsing JSON: {e}")
            logger.debug(f"Réponse IA brute (premiers 1000 chars): {ai_response[:1000]}")
            return GenerateActionPlanResponse(
                success=False,
                error=f"Erreur de parsing JSON: {str(e)}"
            )

        # 8. Insérer les actions en base (table risk_action_link ou nouvelle table)
        # Pour l'instant, on stocke dans risk_workshop.ai_raw_output
        update_query = text("""
            UPDATE risk_workshop
            SET ai_raw_output = CAST(:actions_json AS jsonb),
                ai_last_generation_at = NOW(),
                updated_at = NOW()
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        db.execute(update_query, {
            "project_id": str(project_id),
            "actions_json": json.dumps({"actions": actions_list})
        })
        db.commit()

        logger.info(f"✅ [AT6] Plan d'actions généré: {len(actions_list)} actions")

        return GenerateActionPlanResponse(
            success=True,
            actions_created=len(actions_list),
            message=f"Plan d'actions généré avec succès: {len(actions_list)} actions créées"
        )

    except httpx.TimeoutException:
        logger.error("❌ [AT6] Timeout IA")
        return GenerateActionPlanResponse(
            success=False,
            error="Timeout: L'IA met trop de temps à répondre"
        )
    except Exception as e:
        logger.error(f"❌ [AT6] Erreur: {e}")
        db.rollback()
        return GenerateActionPlanResponse(
            success=False,
            error=str(e)
        )


# ============================================================================
# AT6 - RÉCUPÉRER LES ACTIONS GÉNÉRÉES
# ============================================================================

class ActionItem(BaseModel):
    """Modèle pour une action du plan d'actions."""
    code_action: Optional[str] = None
    titre: Optional[str] = None
    title: Optional[str] = None  # Alias anglais
    description: Optional[str] = None
    categorie: Optional[str] = None
    category: Optional[str] = None  # Alias anglais
    priorite: Optional[str] = None
    priority: Optional[str] = None  # Alias anglais
    objectif: Optional[str] = None
    objective: Optional[str] = None  # Alias anglais
    justification: Optional[str] = None
    effort: Optional[str] = None
    sources_couvertes: Optional[List[str]] = []
    biens_supports: Optional[List[str]] = []


class GetActionsResponse(BaseModel):
    """Réponse pour la récupération des actions."""
    success: bool
    actions: List[dict] = []
    total: int = 0
    generated_at: Optional[str] = None
    message: str = ""


@router.get("/projects/{project_id}/actions", response_model=GetActionsResponse)
async def get_project_actions(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("risk_project:read"))
):
    """
    Récupère les actions générées pour un projet EBIOS RM.
    Les actions sont stockées dans risk_workshop.ai_raw_output pour AT5.
    """
    try:
        # Récupérer les actions depuis risk_workshop AT5
        query = text("""
            SELECT ai_raw_output, ai_last_generation_at
            FROM risk_workshop
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        result = db.execute(query, {"project_id": str(project_id)}).fetchone()

        if not result or not result.ai_raw_output:
            return GetActionsResponse(
                success=True,
                actions=[],
                total=0,
                message="Aucune action générée. Utilisez le bouton 'Générer le plan d'actions' dans AT5."
            )

        ai_output = result.ai_raw_output
        actions_list = ai_output.get("actions", []) if isinstance(ai_output, dict) else []

        # Normaliser les actions (s'assurer que tous les champs existent)
        # Mapping des priorités IA vers format P1/P2/P3 (cohérent avec module Campagnes)
        def normalize_priority(raw_priority: str) -> str:
            """Convertit les priorités textuelles en format P1/P2/P3."""
            p = (raw_priority or "").lower().strip()
            if p in ("critique", "critical", "p1", "très haute", "urgente"):
                return "P1"
            elif p in ("haute", "high", "important", "p2", "élevée"):
                return "P2"
            elif p in ("modérée", "moderate", "medium", "normale", "p3", "moyenne"):
                return "P3"
            elif p in ("faible", "low", "basse"):
                return "P3"  # Faible → P3 (normal)
            return "P3"  # Défaut

        # Mapping des statuts vers format Campagnes
        def normalize_status(raw_status: str, assigned_user_id: str = None) -> str:
            """
            Convertit les statuts textuels en format Campagnes.
            Règle : Si pas assigné → toujours 'pending'
            """
            # Si pas assigné, toujours pending
            if not assigned_user_id:
                return "pending"

            s = (raw_status or "").lower().strip()
            if s in ("en cours", "in_progress", "in progress", "démarré", "started"):
                return "in_progress"
            elif s in ("terminé", "completed", "done", "fini", "achevé"):
                return "completed"
            elif s in ("bloqué", "blocked", "en attente", "suspendu"):
                return "blocked"
            elif s in ("non retenue", "cancelled", "rejeté", "annulé"):
                return "cancelled"
            return "pending"  # Défaut : En attente

        normalized_actions = []
        for i, action in enumerate(actions_list):
            # Gérer les deux formats possibles de code action
            code = action.get("action_id") or action.get("code_action") or f"ACT_{i+1:03d}"

            # Extraire les scénarios couverts
            scenarios = action.get("scenarios_couverts") or action.get("scenario_code")
            if isinstance(scenarios, str):
                scenarios = [scenarios]
            elif not scenarios:
                scenarios = []

            # Récupérer l'ID utilisateur assigné et le type d'assignation
            assigned_user_id = action.get("assigned_user_id") or None
            assignment_type = action.get("assignment_type") or None  # 'internal' ou 'external'
            assigned_entity_id = action.get("assigned_entity_id") or None  # ID de l'organisme (pour mode externe)

            # Récupérer le nom de l'organisme assigné (pour mode externe)
            assigned_entity_name = None
            if assigned_entity_id and assignment_type == 'external':
                entity_query = text("""
                    SELECT name FROM ecosystem_entity WHERE id = CAST(:entity_id AS uuid)
                """)
                entity_result = db.execute(entity_query, {"entity_id": assigned_entity_id}).fetchone()
                if entity_result and entity_result.name:
                    assigned_entity_name = entity_result.name

            # Récupérer le nom de l'utilisateur assigné
            # Si pas stocké dans le JSON, le récupérer depuis la bonne table selon assignment_type
            assigned_user_name = action.get("assigned_user_name") or None
            if assigned_user_id and not assigned_user_name:
                if assignment_type == 'external':
                    # Chercher dans entity_member (externe)
                    member_query = text("""
                        SELECT CONCAT(first_name, ' ', last_name) as full_name
                        FROM entity_member WHERE id = CAST(:user_id AS uuid)
                    """)
                    member_result = db.execute(member_query, {"user_id": assigned_user_id}).fetchone()
                    if member_result and member_result.full_name:
                        assigned_user_name = member_result.full_name
                else:
                    # Par défaut ou 'internal': chercher dans users (interne)
                    user_query = text("""
                        SELECT CONCAT(first_name, ' ', last_name) as full_name
                        FROM users WHERE id = CAST(:user_id AS uuid)
                    """)
                    user_result = db.execute(user_query, {"user_id": assigned_user_id}).fetchone()
                    if user_result and user_result.full_name:
                        assigned_user_name = user_result.full_name

            normalized = {
                "id": i + 1,
                "code_action": code,
                "titre": action.get("titre") or action.get("title") or "Action sans titre",
                "description": action.get("description") or "",
                "categorie": action.get("categorie") or action.get("category") or "Non catégorisé",
                "priorite": normalize_priority(action.get("priorite") or action.get("priority") or "Modérée"),
                "objectif": action.get("objectif") or action.get("objective") or "",
                "justification": action.get("justification") or "",
                "effort": action.get("effort") or "Moyen",
                "cout_estime": action.get("cout_estime") or action.get("cost") or "Moyen",
                "sources_couvertes": action.get("sources_couvertes") or action.get("sources") or [],
                "biens_supports": action.get("biens_supports") or action.get("assets") or [],
                "scenarios_couverts": scenarios,
                "risque_initial": action.get("risque_initial") or None,
                "risque_cible": action.get("risque_cible") or None,
                "responsable_suggere": action.get("responsable_suggere") or action.get("responsable") or "",
                "assignment_type": assignment_type,  # 'internal' ou 'external'
                "assigned_entity_id": assigned_entity_id,  # ID de l'organisme (pour mode externe)
                "assigned_entity_name": assigned_entity_name,  # Nom de l'organisme (pour affichage)
                "assigned_user_id": assigned_user_id,
                "assigned_user_name": assigned_user_name,
                "delai_recommande": action.get("delai_recommande") or action.get("echeance") or "",
                "due_date": action.get("due_date") or None,
                "statut": normalize_status(
                    action.get("statut_initial") or action.get("statut") or action.get("status"),
                    assigned_user_id
                ),
                "references_normatives": action.get("references_normatives") or action.get("references") or [],
                "source": action.get("source") or "AI"  # AI ou MANUAL
            }
            normalized_actions.append(normalized)

        generated_at = None
        if result.ai_last_generation_at:
            generated_at = result.ai_last_generation_at.isoformat()

        return GetActionsResponse(
            success=True,
            actions=normalized_actions,
            total=len(normalized_actions),
            generated_at=generated_at,
            message=f"{len(normalized_actions)} actions disponibles"
        )

    except Exception as e:
        logger.error(f"❌ Erreur récupération actions: {e}")
        return GetActionsResponse(
            success=False,
            actions=[],
            total=0,
            message=f"Erreur: {str(e)}"
        )


# ==================== AT6 - CRUD ACTIONS ====================

class UpdateActionRequest(BaseModel):
    """Requête de mise à jour d'une action EBIOS."""
    id: int
    code_action: str
    titre: str
    description: str
    categorie: str
    priorite: str  # P1, P2, P3
    objectif: Optional[str] = ""
    justification: Optional[str] = ""
    effort: Optional[str] = "Moyen"
    cout_estime: Optional[str] = ""
    sources_couvertes: Optional[List[str]] = []
    biens_supports: Optional[List[str]] = []
    scenarios_couverts: Optional[List[str]] = []
    risque_initial: Optional[int] = None
    risque_cible: Optional[int] = None
    responsable_suggere: Optional[str] = ""
    assignment_type: Optional[str] = None  # 'internal' ou 'external'
    assigned_entity_id: Optional[str] = None  # ID de l'organisme (pour mode externe)
    assigned_user_id: Optional[str] = None
    delai_recommande: Optional[str] = ""
    due_date: Optional[str] = None
    statut: str = "pending"  # pending, in_progress, completed, blocked
    references_normatives: Optional[List[str]] = []


class ActionResponse(BaseModel):
    """Réponse standard pour les opérations sur les actions."""
    success: bool
    message: str
    action: Optional[dict] = None


@router.put("/projects/{project_id}/actions/{action_id}", response_model=ActionResponse)
async def update_project_action(
    project_id: UUID,
    action_id: int,
    action_data: UpdateActionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("risk_project:write"))
):
    """
    Met à jour une action dans le plan d'actions EBIOS.
    Les actions sont stockées dans risk_workshop.ai_raw_output pour AT5.
    """
    try:
        # Récupérer le workshop AT5
        query = text("""
            SELECT id, ai_raw_output
            FROM risk_workshop
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        result = db.execute(query, {"project_id": str(project_id)}).fetchone()

        if not result or not result.ai_raw_output:
            return ActionResponse(
                success=False,
                message="Aucun plan d'actions trouvé pour ce projet."
            )

        ai_output = result.ai_raw_output
        actions_list = ai_output.get("actions", []) if isinstance(ai_output, dict) else []

        # Trouver l'action à mettre à jour par son index (id - 1)
        action_index = action_id - 1
        if action_index < 0 or action_index >= len(actions_list):
            return ActionResponse(
                success=False,
                message=f"Action {action_id} non trouvée."
            )

        # Récupérer le nom de l'utilisateur assigné si un ID est fourni
        # Utiliser assignment_type pour savoir dans quelle table chercher
        assigned_user_name = None
        assignment_type = action_data.assignment_type  # 'internal' ou 'external'

        if action_data.assigned_user_id:
            if assignment_type == 'external':
                # Chercher dans entity_member (membres d'entités externes)
                member_query = text("""
                    SELECT CONCAT(first_name, ' ', last_name) as full_name
                    FROM entity_member
                    WHERE id = CAST(:user_id AS uuid)
                """)
                member_result = db.execute(member_query, {"user_id": action_data.assigned_user_id}).fetchone()
                if member_result and member_result.full_name:
                    assigned_user_name = member_result.full_name
            else:
                # Par défaut ou 'internal': chercher dans users (utilisateurs internes)
                user_query = text("""
                    SELECT CONCAT(first_name, ' ', last_name) as full_name
                    FROM users
                    WHERE id = CAST(:user_id AS uuid)
                """)
                user_result = db.execute(user_query, {"user_id": action_data.assigned_user_id}).fetchone()
                if user_result and user_result.full_name:
                    assigned_user_name = user_result.full_name

        # Mettre à jour l'action
        updated_action = {
            "action_id": action_data.code_action,
            "code_action": action_data.code_action,
            "titre": action_data.titre,
            "title": action_data.titre,
            "description": action_data.description,
            "categorie": action_data.categorie,
            "category": action_data.categorie,
            "priorite": action_data.priorite,
            "priority": action_data.priorite,
            "objectif": action_data.objectif,
            "objective": action_data.objectif,
            "justification": action_data.justification,
            "effort": action_data.effort,
            "cout_estime": action_data.cout_estime,
            "cost": action_data.cout_estime,
            "sources_couvertes": action_data.sources_couvertes,
            "sources": action_data.sources_couvertes,
            "biens_supports": action_data.biens_supports,
            "assets": action_data.biens_supports,
            "scenarios_couverts": action_data.scenarios_couverts,
            "risque_initial": action_data.risque_initial,
            "risque_cible": action_data.risque_cible,
            "responsable_suggere": action_data.responsable_suggere,
            "responsable": action_data.responsable_suggere,
            "assignment_type": assignment_type,  # 'internal' ou 'external'
            "assigned_entity_id": action_data.assigned_entity_id,  # ID de l'organisme (pour mode externe)
            "assigned_user_id": action_data.assigned_user_id,
            "assigned_user_name": assigned_user_name,
            "delai_recommande": action_data.delai_recommande,
            "echeance": action_data.delai_recommande,
            "due_date": action_data.due_date,
            "statut": action_data.statut,
            "status": action_data.statut,
            "references_normatives": action_data.references_normatives,
            "references": action_data.references_normatives,
            "source": actions_list[action_index].get("source", "AI")  # Conserver la source originale
        }

        # Remplacer l'action dans la liste
        actions_list[action_index] = updated_action

        # Mettre à jour le JSON dans la base
        ai_output["actions"] = actions_list

        update_query = text("""
            UPDATE risk_workshop
            SET ai_raw_output = CAST(:ai_output AS jsonb),
                updated_at = NOW()
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        db.execute(update_query, {
            "project_id": str(project_id),
            "ai_output": json.dumps(ai_output)
        })
        db.commit()

        logger.info(f"✅ Action {action_id} mise à jour pour le projet {project_id}")

        return ActionResponse(
            success=True,
            message="Action mise à jour avec succès.",
            action=updated_action
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur mise à jour action: {e}")
        return ActionResponse(
            success=False,
            message=f"Erreur: {str(e)}"
        )


@router.delete("/projects/{project_id}/actions/{action_id}", response_model=ActionResponse)
async def delete_project_action(
    project_id: UUID,
    action_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("risk_project:write"))
):
    """
    Supprime une action du plan d'actions EBIOS.
    """
    try:
        # Récupérer le workshop AT5
        query = text("""
            SELECT id, ai_raw_output
            FROM risk_workshop
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        result = db.execute(query, {"project_id": str(project_id)}).fetchone()

        if not result or not result.ai_raw_output:
            return ActionResponse(
                success=False,
                message="Aucun plan d'actions trouvé pour ce projet."
            )

        ai_output = result.ai_raw_output
        actions_list = ai_output.get("actions", []) if isinstance(ai_output, dict) else []

        # Trouver l'action à supprimer par son index (id - 1)
        action_index = action_id - 1
        if action_index < 0 or action_index >= len(actions_list):
            return ActionResponse(
                success=False,
                message=f"Action {action_id} non trouvée."
            )

        # Supprimer l'action de la liste
        deleted_action = actions_list.pop(action_index)

        # Mettre à jour le JSON dans la base
        ai_output["actions"] = actions_list

        update_query = text("""
            UPDATE risk_workshop
            SET ai_raw_output = CAST(:ai_output AS jsonb),
                updated_at = NOW()
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        db.execute(update_query, {
            "project_id": str(project_id),
            "ai_output": json.dumps(ai_output)
        })
        db.commit()

        logger.info(f"✅ Action {action_id} supprimée du projet {project_id}")

        return ActionResponse(
            success=True,
            message="Action supprimée avec succès.",
            action=deleted_action
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur suppression action: {e}")
        return ActionResponse(
            success=False,
            message=f"Erreur: {str(e)}"
        )


class CreateActionRequest(BaseModel):
    """Requête de création d'une action EBIOS manuelle."""
    code_action: Optional[str] = None  # Généré automatiquement si non fourni
    titre: str
    description: str
    categorie: str
    priorite: str = "P3"  # P1, P2, P3
    objectif: Optional[str] = ""
    justification: Optional[str] = ""
    effort: Optional[str] = "Moyen"
    cout_estime: Optional[str] = ""
    sources_couvertes: Optional[List[str]] = []
    biens_supports: Optional[List[str]] = []
    scenarios_couverts: Optional[List[str]] = []
    risque_initial: Optional[int] = None
    risque_cible: Optional[int] = None
    responsable_suggere: Optional[str] = ""
    assigned_user_id: Optional[str] = None
    assignment_type: Optional[str] = None  # 'internal' ou 'external' - détermine quelle table utiliser
    assigned_entity_id: Optional[str] = None  # ID de l'organisme (pour mode externe)
    delai_recommande: Optional[str] = ""
    due_date: Optional[str] = None
    statut: str = "pending"
    references_normatives: Optional[List[str]] = []


@router.post("/projects/{project_id}/actions", response_model=ActionResponse)
async def create_project_action(
    project_id: UUID,
    action_data: CreateActionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("risk_project:write"))
):
    """
    Crée une nouvelle action manuelle dans le plan d'actions EBIOS.
    """
    try:
        # Récupérer le workshop AT5
        query = text("""
            SELECT id, ai_raw_output
            FROM risk_workshop
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        result = db.execute(query, {"project_id": str(project_id)}).fetchone()

        # Si pas de workshop AT5, en créer un avec une structure vide
        if not result:
            create_query = text("""
                INSERT INTO risk_workshop (id, project_id, type, status, progress, data, ai_raw_output, created_at, updated_at)
                VALUES (gen_random_uuid(), CAST(:project_id AS uuid), 'AT5', 'IN_PROGRESS', 0, '{}'::jsonb, '{"actions": []}'::jsonb, NOW(), NOW())
                RETURNING id, ai_raw_output
            """)
            result = db.execute(create_query, {"project_id": str(project_id)}).fetchone()
            db.commit()

        ai_output = result.ai_raw_output or {"actions": []}
        actions_list = ai_output.get("actions", []) if isinstance(ai_output, dict) else []

        # Générer un code action si non fourni
        code_action = action_data.code_action
        if not code_action:
            # Trouver le prochain numéro disponible
            max_num = 0
            for action in actions_list:
                code = action.get("code_action") or action.get("action_id") or ""
                if code.startswith("ACT_MAN_"):
                    try:
                        num = int(code.replace("ACT_MAN_", ""))
                        max_num = max(max_num, num)
                    except ValueError:
                        pass
            code_action = f"ACT_MAN_{max_num + 1:03d}"

        # Récupérer le nom de l'utilisateur assigné si un ID est fourni
        # Utiliser assignment_type pour savoir dans quelle table chercher
        assigned_user_name = None
        assignment_type = action_data.assignment_type  # 'internal' ou 'external'

        if action_data.assigned_user_id:
            if assignment_type == 'external':
                # Campagne externe → chercher dans entity_member (membres d'entités externes)
                member_query = text("""
                    SELECT CONCAT(first_name, ' ', last_name) as full_name
                    FROM entity_member
                    WHERE id = CAST(:user_id AS uuid)
                """)
                member_result = db.execute(member_query, {"user_id": action_data.assigned_user_id}).fetchone()
                if member_result and member_result.full_name:
                    assigned_user_name = member_result.full_name
            else:
                # Par défaut ou 'internal': chercher dans users (utilisateurs internes du tenant)
                user_query = text("""
                    SELECT CONCAT(first_name, ' ', last_name) as full_name
                    FROM users
                    WHERE id = CAST(:user_id AS uuid)
                """)
                user_result = db.execute(user_query, {"user_id": action_data.assigned_user_id}).fetchone()
                if user_result and user_result.full_name:
                    assigned_user_name = user_result.full_name

        # Créer la nouvelle action
        new_action = {
            "action_id": code_action,
            "code_action": code_action,
            "titre": action_data.titre,
            "title": action_data.titre,
            "description": action_data.description,
            "categorie": action_data.categorie,
            "category": action_data.categorie,
            "priorite": action_data.priorite,
            "priority": action_data.priorite,
            "objectif": action_data.objectif,
            "objective": action_data.objectif,
            "justification": action_data.justification,
            "effort": action_data.effort,
            "cout_estime": action_data.cout_estime,
            "cost": action_data.cout_estime,
            "sources_couvertes": action_data.sources_couvertes,
            "sources": action_data.sources_couvertes,
            "biens_supports": action_data.biens_supports,
            "assets": action_data.biens_supports,
            "scenarios_couverts": action_data.scenarios_couverts,
            "risque_initial": action_data.risque_initial,
            "risque_cible": action_data.risque_cible,
            "responsable_suggere": action_data.responsable_suggere,
            "responsable": action_data.responsable_suggere,
            "assigned_user_id": action_data.assigned_user_id,
            "assigned_user_name": assigned_user_name,
            "assignment_type": assignment_type,  # 'internal' ou 'external'
            "assigned_entity_id": action_data.assigned_entity_id,  # ID de l'organisme (pour mode externe)
            "delai_recommande": action_data.delai_recommande,
            "echeance": action_data.delai_recommande,
            "due_date": action_data.due_date,
            "statut": action_data.statut,
            "status": action_data.statut,
            "references_normatives": action_data.references_normatives,
            "references": action_data.references_normatives,
            "source": "MANUAL"  # Action créée manuellement
        }

        # Ajouter l'action à la liste
        actions_list.append(new_action)

        # Mettre à jour le JSON dans la base
        ai_output["actions"] = actions_list

        update_query = text("""
            UPDATE risk_workshop
            SET ai_raw_output = CAST(:ai_output AS jsonb),
                updated_at = NOW()
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        db.execute(update_query, {
            "project_id": str(project_id),
            "ai_output": json.dumps(ai_output)
        })
        db.commit()

        logger.info(f"✅ Action {code_action} créée pour le projet {project_id}")

        return ActionResponse(
            success=True,
            message="Action créée avec succès.",
            action=new_action
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur création action: {e}")
        return ActionResponse(
            success=False,
            message=f"Erreur: {str(e)}"
        )


# ==================== SCOPE ENTITIES & MEMBERS ====================

class ScopeEntityMember(BaseModel):
    """Membre d'une entité du scope."""
    id: str
    first_name: str
    last_name: str
    email: str
    role: Optional[str] = None


class ScopeEntity(BaseModel):
    """Entité du scope avec ses membres."""
    id: str
    name: str
    stakeholder_type: str  # 'internal' | 'external'
    entity_category: Optional[str] = None  # Catégorie de l'organisme (ex: MAROC, ESPAGNE)
    parent_category: Optional[str] = None  # Catégorie parente (ex: Fournisseurs, Clients)
    members: List[ScopeEntityMember] = []


class ScopeEntitiesResponse(BaseModel):
    """Réponse avec les entités du scope et leurs membres."""
    success: bool
    entities: List[ScopeEntity] = []
    internal_users: List[ScopeEntityMember] = []  # Utilisateurs internes (table users)
    message: str = ""


@router.get("/projects/{project_id}/scope-entities", response_model=ScopeEntitiesResponse)
async def get_project_scope_entities(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("risk_project:read"))
):
    """
    Récupère les organismes du périmètre d'une étude EBIOS avec leurs membres.

    Retourne :
    - internal_users : Utilisateurs de la table 'users' (pour assignation interne)
    - entities : Liste des organismes du scope avec leurs membres (entity_member)
    """
    try:
        # 1. Récupérer le projet et son scope_entity_ids
        project_query = text("""
            SELECT scope_entity_ids, tenant_id
            FROM risk_project
            WHERE id = CAST(:project_id AS uuid)
              AND deleted_at IS NULL
        """)
        project_result = db.execute(project_query, {"project_id": str(project_id)}).fetchone()

        if not project_result:
            return ScopeEntitiesResponse(
                success=False,
                message="Projet EBIOS non trouvé."
            )

        scope_entity_ids = project_result.scope_entity_ids or []
        tenant_id = project_result.tenant_id

        # 2. Récupérer les utilisateurs internes (table users du tenant)
        internal_users_query = text("""
            SELECT id, first_name, last_name, email
            FROM users
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_active = true
            ORDER BY first_name, last_name
        """)
        internal_users_result = db.execute(internal_users_query, {"tenant_id": str(tenant_id)}).fetchall()

        internal_users = [
            ScopeEntityMember(
                id=str(row.id),
                first_name=row.first_name or "",
                last_name=row.last_name or "",
                email=row.email or "",
                role="user"  # Rôle par défaut pour les utilisateurs internes
            )
            for row in internal_users_result
        ]

        # 3. Récupérer les entités du scope avec leurs membres
        entities = []

        if scope_entity_ids:
            # Récupérer les détails des entités avec leur catégorie ET catégorie parente
            entities_query = text("""
                SELECT e.id, e.name, e.stakeholder_type,
                       COALESCE(c.name, e.entity_category) as category_name,
                       pc.name as parent_category_name
                FROM ecosystem_entity e
                LEFT JOIN categories c ON e.category_id = c.id
                LEFT JOIN categories pc ON c.parent_category_id = pc.id
                WHERE e.id = ANY(CAST(:entity_ids AS uuid[]))
                  AND e.is_active = true
                ORDER BY e.name
            """)
            entities_result = db.execute(entities_query, {
                "entity_ids": [str(eid) for eid in scope_entity_ids]
            }).fetchall()

            for entity_row in entities_result:
                # Récupérer les membres de chaque entité
                members_query = text("""
                    SELECT id, first_name, last_name, email, roles
                    FROM entity_member
                    WHERE entity_id = CAST(:entity_id AS uuid)
                      AND is_active = true
                    ORDER BY first_name, last_name
                """)
                members_result = db.execute(members_query, {
                    "entity_id": str(entity_row.id)
                }).fetchall()

                members = []
                for member_row in members_result:
                    # Extraire le premier rôle du JSON
                    roles = member_row.roles or []
                    role_str = ""
                    if isinstance(roles, list) and len(roles) > 0:
                        role_str = roles[0]
                    elif isinstance(roles, dict):
                        role_str = list(roles.keys())[0] if roles else ""

                    members.append(ScopeEntityMember(
                        id=str(member_row.id),
                        first_name=member_row.first_name or "",
                        last_name=member_row.last_name or "",
                        email=member_row.email or "",
                        role=role_str
                    ))

                # Déterminer la catégorie parente:
                # - Si l'entité a une catégorie parente, on l'utilise
                # - Sinon, la catégorie elle-même est la catégorie principale
                parent_cat = entity_row.parent_category_name
                cat_name = entity_row.category_name

                entities.append(ScopeEntity(
                    id=str(entity_row.id),
                    name=entity_row.name or "Sans nom",
                    stakeholder_type=entity_row.stakeholder_type or "external",
                    entity_category=cat_name,  # Catégorie directe (ex: MAROC, Fournisseurs)
                    parent_category=parent_cat,  # Catégorie parente si existe (ex: Fournisseurs)
                    members=members
                ))

        return ScopeEntitiesResponse(
            success=True,
            entities=entities,
            internal_users=internal_users,
            message=f"{len(internal_users)} utilisateurs internes, {len(entities)} organismes dans le scope"
        )

    except Exception as e:
        logger.error(f"❌ Erreur récupération scope entities: {e}")
        return ScopeEntitiesResponse(
            success=False,
            message=f"Erreur: {str(e)}"
        )


# ==============================================================================
# GÉNÉRATION DE RAPPORT EBIOS RM
# ==============================================================================

class ReportPrerequisitesResponse(BaseModel):
    """Réponse de vérification des prérequis pour la génération du rapport."""
    hasStrategicScenarios: bool = False
    hasOperationalScenarios: bool = False
    hasActions: bool = False
    hasTemplate: bool = True
    strategicCount: int = 0
    operationalCount: int = 0
    actionsCount: int = 0
    templateName: str = "Template EBIOS RM par défaut"


class ReportGenerationRequest(BaseModel):
    """Requête de génération de rapport EBIOS RM."""
    report_type: str = Field(default="consolidated", description="Type: consolidated, individual, both")
    include_strategic_scenarios: bool = Field(default=True)
    include_operational_scenarios: bool = Field(default=True)
    only_critical_scenarios: bool = Field(default=False)
    include_actions: bool = Field(default=True)
    include_actions_summary: bool = Field(default=True)
    include_actions_detail: bool = Field(default=True)
    format: str = Field(default="pdf", description="Format: pdf ou docx")
    use_ai: bool = Field(default=True, description="Utiliser l'IA pour les synthèses")
    ai_tone: str = Field(default="executive", description="Ton: executive, technical, detailed")


class ReportGenerationResponse(BaseModel):
    """Réponse de génération de rapport."""
    success: bool
    message: str
    report_id: Optional[str] = None
    title: Optional[str] = None
    download_url: Optional[str] = None
    file_path: Optional[str] = None


@router.get(
    "/projects/{project_id}/report/prerequisites",
    response_model=ReportPrerequisitesResponse,
    summary="Vérifier les prérequis pour la génération du rapport"
)
async def check_report_prerequisites(
    project_id: UUID,
    current_user: User = Depends(require_permission("RISK_PROJECTS_READ")),
    db: Session = Depends(get_db)
):
    """
    Vérifie les prérequis pour la génération du rapport EBIOS RM.

    Conditions requises:
    - Au moins 1 scénario (stratégique OU opérationnel)
    - Au moins 1 action dans le plan
    - Template de rapport configuré (toujours vrai avec template par défaut)
    """
    try:
        from src.services.ebios_report_service import EbiosReportService

        service = EbiosReportService(db, current_user.tenant_id)
        prerequisites = await service.check_prerequisites(project_id)

        return ReportPrerequisitesResponse(**prerequisites)

    except Exception as e:
        logger.error(f"❌ Erreur vérification prérequis rapport: {e}")
        # Retourner des valeurs par défaut en cas d'erreur
        return ReportPrerequisitesResponse()


@router.post(
    "/projects/{project_id}/report/generate",
    response_model=ReportGenerationResponse,
    summary="Générer le rapport EBIOS RM"
)
async def generate_report(
    project_id: UUID,
    request: ReportGenerationRequest,
    current_user: User = Depends(require_permission("RISK_PROJECTS_READ")),
    db: Session = Depends(get_db)
):
    """
    Génère un rapport EBIOS RM au format PDF ou DOCX.

    Le rapport inclut:
    - Résumé exécutif (généré par IA si activé)
    - AT1: Cadrage et socle de sécurité
    - AT2: Sources de risques
    - AT3: Scénarios stratégiques
    - AT4: Scénarios opérationnels
    - AT5: Matrice des risques
    - AT6: Plan de traitement des risques
    """
    try:
        from src.services.ebios_report_service import EbiosReportService
        import tempfile
        import os as os_module

        logger.info(f"📄 Génération rapport EBIOS pour projet {project_id}")

        # Vérifier que le projet existe
        project_query = text("""
            SELECT id, label, status FROM risk_project
            WHERE id = CAST(:project_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
        """)
        project_result = db.execute(project_query, {
            "project_id": str(project_id),
            "tenant_id": str(current_user.tenant_id)
        })
        project = project_result.fetchone()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Projet EBIOS non trouvé"
            )

        # Initialiser le service
        service = EbiosReportService(db, current_user.tenant_id)

        # Vérifier les prérequis
        prerequisites = await service.check_prerequisites(project_id)

        has_scenarios = prerequisites['hasStrategicScenarios'] or prerequisites['hasOperationalScenarios']
        if not has_scenarios:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Au moins un scénario (stratégique ou opérationnel) est requis"
            )

        if not prerequisites['hasActions']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Au moins une action est requise dans le plan de traitement"
            )

        # Collecter les données
        logger.info("📊 Collecte des données AT1-AT6...")
        data = await service.collect_project_data(project_id)

        # Générer les synthèses IA si demandé
        ai_summaries = {}
        if request.use_ai:
            logger.info("🤖 Génération des synthèses IA...")
            try:
                ai_summaries['executive_summary'] = await service.generate_ai_summary(
                    'executive_summary', data, request.ai_tone
                )
                ai_summaries['at1_summary'] = await service.generate_ai_summary(
                    'at1_summary', data, request.ai_tone
                )
                ai_summaries['at2_summary'] = await service.generate_ai_summary(
                    'at2_summary', data, request.ai_tone
                )
                ai_summaries['risk_analysis'] = await service.generate_ai_summary(
                    'risk_analysis', data, request.ai_tone
                )
            except Exception as e:
                logger.warning(f"⚠️ Erreur génération IA (ignorée): {e}")

        # Options de génération
        options = {
            'include_at1': True,
            'include_strategic_scenarios': request.include_strategic_scenarios,
            'include_operational_scenarios': request.include_operational_scenarios,
            'only_critical': request.only_critical_scenarios,
            'include_actions': request.include_actions,
            'include_actions_summary': request.include_actions_summary,
            'include_actions_detail': request.include_actions_detail,
        }

        # Générer le HTML - Utiliser le template depuis la BDD si disponible
        logger.info("📝 Génération du HTML...")
        # Essayer d'abord avec le template EBIOS de la BDD
        html_content = service.generate_html_from_template(data, ai_summaries)
        if not html_content:
            # Fallback vers la méthode manuelle
            html_content = service.generate_html_report(data, options, ai_summaries)

        # Convertir en PDF avec xhtml2pdf
        if request.format == 'pdf':
            logger.info("📄 Conversion en PDF...")
            try:
                from xhtml2pdf import pisa
                from io import BytesIO

                # Créer le fichier PDF dans un dossier temporaire
                reports_dir = os_module.path.join(tempfile.gettempdir(), 'ebios_reports')
                os_module.makedirs(reports_dir, exist_ok=True)

                # Nom du fichier
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                safe_name = "".join(c for c in project.label if c.isalnum() or c in (' ', '-', '_')).strip()
                filename = f"EBIOS_RM_{safe_name}_{timestamp}.pdf"
                file_path = os_module.path.join(reports_dir, filename)

                # Générer le PDF avec xhtml2pdf
                with open(file_path, "wb") as pdf_file:
                    pisa_status = pisa.CreatePDF(
                        html_content,
                        dest=pdf_file,
                        encoding='utf-8'
                    )

                if pisa_status.err:
                    logger.error(f"Erreur xhtml2pdf: {pisa_status.err}")
                    raise Exception("Erreur lors de la conversion HTML vers PDF")

                logger.info(f"✅ PDF généré: {file_path}")

                # Enregistrer le rapport dans la table generated_report
                report_id = uuid.uuid4()
                report_title = f"Rapport EBIOS RM - {project.label}"
                now = datetime.now()

                # Calculer la taille du fichier
                file_size = os_module.path.getsize(file_path)

                # Insérer dans generated_report avec report_data pour stocker ai_summaries
                insert_report_query = text("""
                    INSERT INTO generated_report (
                        id, tenant_id, risk_project_id, title, description,
                        status, generation_mode, report_scope,
                        file_path, file_name, file_size_bytes, file_mime_type,
                        generated_by, generated_at, created_at, updated_at,
                        is_latest, version, report_data
                    ) VALUES (
                        CAST(:id AS uuid),
                        CAST(:tenant_id AS uuid),
                        CAST(:risk_project_id AS uuid),
                        :title,
                        :description,
                        'final',
                        'final',
                        :report_scope,
                        :file_path,
                        :file_name,
                        :file_size,
                        'application/pdf',
                        CAST(:generated_by AS uuid),
                        :generated_at,
                        :created_at,
                        :updated_at,
                        true,
                        1,
                        CAST(:report_data AS jsonb)
                    )
                """)

                # Déterminer le scope selon le type de rapport demandé
                report_scope = 'ebios_consolidated' if request.report_type in ['consolidated', 'both'] else 'ebios_individual'

                # Préparer report_data avec les ai_summaries pour la preview
                report_data_json = json.dumps({
                    "ai_summaries": ai_summaries,
                    "generation_options": {
                        "use_ai": request.use_ai,
                        "ai_tone": request.ai_tone,
                        "report_type": request.report_type
                    }
                })

                db.execute(insert_report_query, {
                    "id": str(report_id),
                    "tenant_id": str(current_user.tenant_id),
                    "risk_project_id": str(project_id),
                    "title": report_title,
                    "description": f"Rapport EBIOS RM généré le {now.strftime('%d/%m/%Y à %H:%M')}",
                    "report_scope": report_scope,
                    "file_path": file_path,
                    "file_name": filename,
                    "file_size": file_size,
                    "generated_by": str(current_user.id),
                    "generated_at": now,
                    "created_at": now,
                    "updated_at": now,
                    "report_data": report_data_json
                })
                db.commit()

                logger.info(f"✅ Rapport enregistré en base: {report_id}")

                return ReportGenerationResponse(
                    success=True,
                    message="Rapport EBIOS RM généré avec succès",
                    report_id=str(report_id),
                    title=report_title,
                    file_path=file_path,
                    download_url=f"/api/v1/risk/reports/download/{filename}"
                )

            except ImportError:
                logger.error("xhtml2pdf non installé")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Erreur: xhtml2pdf non installé. Installez-le avec: pip install xhtml2pdf"
                )
            except Exception as e:
                logger.error(f"Erreur génération PDF: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erreur lors de la génération du PDF: {str(e)}"
                )

        else:
            # Format DOCX - À implémenter
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Le format DOCX n'est pas encore supporté. Utilisez PDF."
            )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"❌ Erreur génération rapport: {e}\n{error_trace}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération du rapport: {str(e)}"
        )


@router.get(
    "/reports/download/{filename}",
    summary="Télécharger un rapport EBIOS RM"
)
async def download_report(
    filename: str,
    current_user: User = Depends(require_permission("RISK_PROJECTS_READ"))
):
    """
    Télécharge un rapport EBIOS RM généré.
    """
    try:
        import tempfile
        import os as os_module
        from fastapi.responses import FileResponse

        # Vérifier que le fichier existe
        reports_dir = os_module.path.join(tempfile.gettempdir(), 'ebios_reports')
        file_path = os_module.path.join(reports_dir, filename)

        if not os_module.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rapport non trouvé ou expiré"
            )

        # Vérifier que c'est bien un fichier dans le bon dossier (sécurité)
        if not os_module.path.abspath(file_path).startswith(os_module.path.abspath(reports_dir)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé"
            )

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type='application/pdf'
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement rapport: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du téléchargement: {str(e)}"
        )


# ============================================================================
# Rapports EBIOS RM - Liste et gestion
# ============================================================================

class EbiosGeneratedReportResponse(BaseModel):
    """Réponse pour un rapport EBIOS généré."""
    id: str
    title: str
    description: Optional[str] = None
    report_scope: str
    status: str
    file_name: Optional[str] = None
    file_size_bytes: Optional[int] = None
    generated_at: Optional[datetime] = None
    generated_by_name: Optional[str] = None
    download_url: str

    class Config:
        from_attributes = True


class EbiosReportsListResponse(BaseModel):
    """Liste des rapports EBIOS générés."""
    items: List[EbiosGeneratedReportResponse]
    total: int


@router.get(
    "/projects/{project_id}/reports",
    response_model=EbiosReportsListResponse,
    summary="Liste les rapports générés pour un projet EBIOS"
)
async def list_project_reports(
    project_id: UUID,
    current_user: User = Depends(require_permission("RISK_PROJECTS_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère la liste des rapports générés pour un projet EBIOS RM.
    """
    try:
        # Vérifier que le projet existe et appartient au tenant
        project_check = text("""
            SELECT id FROM risk_project
            WHERE id = CAST(:project_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
        """)
        project_result = db.execute(project_check, {
            "project_id": str(project_id),
            "tenant_id": str(current_user.tenant_id)
        })
        if not project_result.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Projet EBIOS non trouvé"
            )

        # Récupérer les rapports du projet
        reports_query = text("""
            SELECT
                gr.id,
                gr.title,
                gr.description,
                gr.report_scope,
                gr.status,
                gr.file_name,
                gr.file_size_bytes,
                gr.generated_at,
                CONCAT(u.first_name, ' ', u.last_name) as generated_by_name
            FROM generated_report gr
            LEFT JOIN users u ON gr.generated_by = u.id
            WHERE gr.risk_project_id = CAST(:project_id AS uuid)
              AND gr.tenant_id = CAST(:tenant_id AS uuid)
            ORDER BY gr.generated_at DESC
        """)

        result = db.execute(reports_query, {
            "project_id": str(project_id),
            "tenant_id": str(current_user.tenant_id)
        })

        reports = []
        for row in result:
            reports.append(EbiosGeneratedReportResponse(
                id=str(row.id),
                title=row.title,
                description=row.description,
                report_scope=row.report_scope,
                status=row.status,
                file_name=row.file_name,
                file_size_bytes=row.file_size_bytes,
                generated_at=row.generated_at,
                generated_by_name=row.generated_by_name,
                download_url=f"/api/v1/risk/reports/{row.id}/download"
            ))

        return EbiosReportsListResponse(
            items=reports,
            total=len(reports)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur liste rapports EBIOS: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des rapports: {str(e)}"
        )


@router.get(
    "/reports/{report_id}/preview-html",
    summary="Prévisualiser un rapport EBIOS RM en HTML"
)
async def preview_ebios_report_html(
    report_id: UUID,
    current_user: User = Depends(require_permission("RISK_PROJECTS_READ")),
    db: Session = Depends(get_db)
):
    """
    Génère et retourne l'aperçu HTML d'un rapport EBIOS RM.

    Cette route régénère le HTML à partir des données actuelles du projet,
    permettant de visualiser le rendu avant téléchargement du PDF.

    Returns:
        HTML content du rapport
    """
    try:
        from fastapi.responses import HTMLResponse
        from src.services.ebios_report_service import EbiosReportService

        logger.info(f"📄 Preview HTML rapport EBIOS: {report_id}")

        # 1. Récupérer le rapport et son risk_project_id + report_data (contient ai_contents)
        report_query = text("""
            SELECT id, risk_project_id, tenant_id, title, report_scope, report_data
            FROM generated_report
            WHERE id = CAST(:report_id AS uuid)
        """)
        result = db.execute(report_query, {"report_id": str(report_id)})
        report = result.fetchone()

        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rapport non trouvé"
            )

        # Vérifier que l'utilisateur a accès (même tenant)
        if str(report.tenant_id) != str(current_user.tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé à ce rapport"
            )

        # 2. Vérifier que c'est bien un rapport EBIOS (a un risk_project_id)
        if not report.risk_project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ce rapport n'est pas un rapport EBIOS RM"
            )

        project_id = report.risk_project_id

        # 3. Vérifier que le projet existe toujours
        project_query = text("""
            SELECT id, label FROM risk_project
            WHERE id = CAST(:project_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
        """)
        project_result = db.execute(project_query, {
            "project_id": str(project_id),
            "tenant_id": str(current_user.tenant_id)
        })
        project = project_result.fetchone()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Projet EBIOS associé non trouvé"
            )

        # 4. Initialiser le service et collecter les données
        service = EbiosReportService(db, current_user.tenant_id)
        data = await service.collect_project_data(project_id)

        # 5. Déterminer le scope du rapport (consolidated par défaut pour EBIOS)
        # Le scope 'consolidated' génère le rapport complet
        # Le scope 'individual' génère une fiche par scénario
        report_scope = report.report_scope or 'consolidated'
        logger.info(f"📋 Preview avec scope: {report_scope}")

        # 5b. Charger les ai_contents depuis report_data si disponible
        # Ces contenus ont été générés lors de la création du rapport
        report_data = report.report_data or {}
        if isinstance(report_data, str):
            import json
            report_data = json.loads(report_data)

        ai_contents = report_data.get('ai_contents', {})
        ai_summaries_stored = report_data.get('ai_summaries', {})

        # Vérifier si les ai_summaries ont du contenu réel (pas juste des clés vides)
        has_real_content = any(
            ai_summaries_stored.get(key, '').strip()
            for key in ['executive_summary', 'at1_summary', 'at2_summary', 'risk_analysis']
        )

        if ai_contents:
            logger.info(f"📋 Preview: ai_contents chargés depuis report_data: {list(ai_contents.keys())}")
            # Injecter les ai_contents dans data pour le renderer
            data['ai_contents'] = ai_contents
        else:
            logger.info(f"📋 Preview: aucun ai_contents trouvé")

        # Utiliser les ai_summaries stockés s'ils ont du contenu réel
        ai_summaries = {}
        if has_real_content:
            ai_summaries = ai_summaries_stored
            logger.info(f"📋 Preview: ai_summaries chargés: {list(ai_summaries.keys())}")
        else:
            logger.info(f"📋 Preview: ai_summaries vides, tentative de régénération...")
            # Tenter de régénérer les résumés IA
            generation_options = report_data.get('generation_options', {})
            use_ai = generation_options.get('use_ai', True)
            ai_tone = generation_options.get('ai_tone', 'executive')

            if use_ai:
                try:
                    ai_summaries['executive_summary'] = await service.generate_ai_summary(
                        'executive_summary', data, ai_tone
                    )
                    ai_summaries['at1_summary'] = await service.generate_ai_summary(
                        'at1_summary', data, ai_tone
                    )
                    ai_summaries['at2_summary'] = await service.generate_ai_summary(
                        'at2_summary', data, ai_tone
                    )
                    ai_summaries['risk_analysis'] = await service.generate_ai_summary(
                        'risk_analysis', data, ai_tone
                    )
                    logger.info(f"✅ Preview: ai_summaries régénérés: {[k for k, v in ai_summaries.items() if v]}")
                except Exception as e:
                    logger.warning(f"⚠️ Preview: échec régénération IA: {e}")

        # 6. Générer le HTML avec les contenus IA stockés
        html_content = service.generate_html_from_template(data, ai_summaries, report_scope)
        if not html_content:
            # Fallback vers la méthode manuelle
            options = {
                'include_at1': True,
                'include_strategic_scenarios': True,
                'include_operational_scenarios': True,
                'only_critical': False,
                'include_actions': True,
                'include_actions_summary': True,
                'include_actions_detail': True,
            }
            html_content = service.generate_html_report(data, options, ai_summaries)

        if not html_content:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors de la génération de l'aperçu HTML"
            )

        logger.info(f"✅ Preview HTML généré pour rapport EBIOS: {report_id}")

        return HTMLResponse(content=html_content, media_type="text/html")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur preview rapport EBIOS: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération de l'aperçu: {str(e)}"
        )


@router.get(
    "/reports/{report_id}/download",
    summary="Télécharger un rapport EBIOS RM par ID"
)
async def download_report_by_id(
    report_id: UUID,
    current_user: User = Depends(require_permission("RISK_PROJECTS_READ")),
    db: Session = Depends(get_db)
):
    """
    Télécharge un rapport EBIOS RM par son ID.
    Met à jour le compteur de téléchargement.
    """
    try:
        import tempfile
        import os as os_module
        from fastapi.responses import FileResponse

        # Récupérer les informations du rapport
        report_query = text("""
            SELECT file_path, file_name, tenant_id
            FROM generated_report
            WHERE id = CAST(:report_id AS uuid)
        """)
        result = db.execute(report_query, {"report_id": str(report_id)})
        report = result.fetchone()

        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rapport non trouvé"
            )

        # Vérifier que l'utilisateur a accès (même tenant)
        if str(report.tenant_id) != str(current_user.tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé à ce rapport"
            )

        file_path = report.file_path
        file_name = report.file_name

        # Vérifier que le fichier existe
        if not file_path or not os_module.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fichier du rapport non trouvé ou expiré"
            )

        # Mettre à jour le compteur de téléchargement
        update_query = text("""
            UPDATE generated_report
            SET downloaded_count = COALESCE(downloaded_count, 0) + 1,
                last_downloaded_at = :now
            WHERE id = CAST(:report_id AS uuid)
        """)
        db.execute(update_query, {
            "report_id": str(report_id),
            "now": datetime.now()
        })
        db.commit()

        return FileResponse(
            path=file_path,
            filename=file_name or f"rapport_ebios_{report_id}.pdf",
            media_type='application/pdf'
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement rapport par ID: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du téléchargement: {str(e)}"
        )


@router.delete(
    "/reports/{report_id}",
    summary="Supprimer un rapport EBIOS RM"
)
async def delete_ebios_report(
    report_id: UUID,
    current_user: User = Depends(require_permission("RISK_PROJECTS_DELETE")),
    db: Session = Depends(get_db)
):
    """
    Supprime un rapport EBIOS RM.
    """
    try:
        import os as os_module

        # Récupérer les informations du rapport
        report_query = text("""
            SELECT id, file_path, tenant_id
            FROM generated_report
            WHERE id = CAST(:report_id AS uuid)
        """)
        result = db.execute(report_query, {"report_id": str(report_id)})
        report = result.fetchone()

        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rapport non trouvé"
            )

        # Vérifier que l'utilisateur a accès (même tenant)
        if str(report.tenant_id) != str(current_user.tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé à ce rapport"
            )

        # Supprimer le fichier physique si il existe
        if report.file_path and os_module.path.exists(report.file_path):
            try:
                os_module.remove(report.file_path)
                logger.info(f"🗑️ Fichier supprimé: {report.file_path}")
            except Exception as e:
                logger.warning(f"⚠️ Impossible de supprimer le fichier: {e}")

        # Supprimer l'entrée en base
        delete_query = text("""
            DELETE FROM generated_report
            WHERE id = CAST(:report_id AS uuid)
        """)
        db.execute(delete_query, {"report_id": str(report_id)})
        db.commit()

        logger.info(f"✅ Rapport {report_id} supprimé")

        return {"success": True, "message": "Rapport supprimé avec succès"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur suppression rapport: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )


# ==============================================================================
# UNFREEZE / PUBLISH / UNPUBLISH ACTIONS
# ==============================================================================

class UnfreezeRequest(BaseModel):
    confirm: bool = False


class UnfreezeResponse(BaseModel):
    success: bool
    message: str


class PublishActionsRequest(BaseModel):
    confirm: bool = False


class PublishActionsResponse(BaseModel):
    success: bool
    message: str
    actions_count: int = 0
    published_at: Optional[datetime] = None


@router.post("/projects/{project_id}/unfreeze", response_model=UnfreezeResponse)
async def unfreeze_project(
    project_id: UUID,
    request: UnfreezeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_FREEZE"))
):
    """
    Dégèle une analyse EBIOS RM et supprime les actions publiées.

    - Remet le projet en mode édition (DRAFT)
    - Supprime toutes les actions publiées dans le module Actions
    - Permet de modifier à nouveau les ateliers

    Permissions requises: EBIOS_FREEZE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation requise pour dégeler l'analyse"
        )

    # Vérifier le projet
    project_query = text("""
        SELECT id, status, frozen_at, actions_published_at
        FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    project = db.execute(project_query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet non trouvé"
        )

    if project.status != "FROZEN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le projet n'est pas figé"
        )

    try:
        # 1. Supprimer les actions publiées pour ce projet EBIOS
        delete_actions_query = text("""
            DELETE FROM published_action
            WHERE risk_project_id = CAST(:project_id AS uuid)
              AND source_type = 'ebios'
        """)
        result = db.execute(delete_actions_query, {"project_id": str(project_id)})
        deleted_count = result.rowcount

        # 2. Remettre le projet en mode DRAFT
        unfreeze_query = text("""
            UPDATE risk_project
            SET status = 'DRAFT',
                frozen_at = NULL,
                frozen_by = NULL,
                actions_published_at = NULL,
                actions_published_by = NULL,
                updated_at = NOW()
            WHERE id = CAST(:project_id AS uuid)
        """)
        db.execute(unfreeze_query, {"project_id": str(project_id)})

        db.commit()

        logger.info(f"🔓 Projet EBIOS dégélé: {project_id} par {current_user.email} ({deleted_count} actions supprimées)")

        return UnfreezeResponse(
            success=True,
            message=f"Analyse EBIOS RM dégélée avec succès. {deleted_count} action(s) supprimée(s) du module Actions."
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur dégel projet: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du dégel: {str(e)}"
        )


@router.post("/projects/{project_id}/publish-actions", response_model=PublishActionsResponse)
async def publish_actions(
    project_id: UUID,
    request: PublishActionsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_FREEZE"))
):
    """
    Publie les actions EBIOS vers le module Actions pour suivi.

    - Le projet doit être figé (FROZEN)
    - Copie toutes les actions du plan AT6 vers published_action
    - Permet le suivi et l'assignation des actions

    Permissions requises: EBIOS_FREEZE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation requise pour publier les actions"
        )

    # Vérifier le projet
    project_query = text("""
        SELECT id, label, status, frozen_at, actions_published_at
        FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    project = db.execute(project_query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet non trouvé"
        )

    if project.status != "FROZEN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le projet doit être figé avant de publier les actions"
        )

    if project.actions_published_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Les actions ont déjà été publiées. Dégélez d'abord pour republier."
        )

    try:
        # 1. Récupérer les actions depuis ai_raw_output du workshop AT5
        workshop_query = text("""
            SELECT ai_raw_output FROM risk_workshop
            WHERE project_id = CAST(:project_id AS uuid)
              AND type = 'AT5'
        """)
        workshop = db.execute(workshop_query, {"project_id": str(project_id)}).fetchone()

        actions = []
        if workshop and workshop.ai_raw_output:
            ai_data = workshop.ai_raw_output
            if isinstance(ai_data, str):
                import json
                ai_data = json.loads(ai_data)
            actions = ai_data.get('actions', [])

        if not actions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Aucune action à publier. Générez d'abord le plan d'actions (AT6)."
            )

        # 2. Insérer les actions dans published_action
        now = datetime.now()
        published_count = 0

        for action in actions:
            action_id = str(uuid.uuid4())

            # Mapper la priorité
            priority_map = {
                "Critique": "P1",
                "Haute": "P2",
                "Moyenne": "P3",
                "Basse": "P4"
            }
            priority = priority_map.get(action.get('priorite', 'Moyenne'), 'P3')

            # Mapper le délai recommandé vers due_date approximatif
            delai = action.get('delai_recommande', '')
            recommended_days = 90  # Par défaut 3 mois
            if '1 mois' in delai.lower():
                recommended_days = 30
            elif '3 mois' in delai.lower():
                recommended_days = 90
            elif '6 mois' in delai.lower():
                recommended_days = 180
            elif '12 mois' in delai.lower() or '1 an' in delai.lower():
                recommended_days = 365

            insert_query = text("""
                INSERT INTO published_action (
                    id, tenant_id, risk_project_id, source_type,
                    code_action, title, description, objective,
                    severity, priority, status,
                    suggested_role, assignment_method,
                    recommended_due_days,
                    source_question_ids, control_point_ids,
                    ai_justifications,
                    published_at, published_by,
                    created_at, updated_at
                ) VALUES (
                    CAST(:id AS uuid),
                    CAST(:tenant_id AS uuid),
                    CAST(:project_id AS uuid),
                    'ebios',
                    :code_action,
                    :title,
                    :description,
                    :objective,
                    :severity,
                    :priority,
                    'pending',
                    :suggested_role,
                    'unassigned',
                    :recommended_days,
                    ARRAY[]::uuid[],
                    ARRAY[]::uuid[],
                    CAST(:ai_justifications AS jsonb),
                    :published_at,
                    CAST(:published_by AS uuid),
                    NOW(),
                    NOW()
                )
            """)

            db.execute(insert_query, {
                "id": action_id,
                "tenant_id": str(current_user.tenant_id),
                "project_id": str(project_id),
                "code_action": action.get('action_id', f"ACT_EBIOS_{published_count + 1:03d}"),
                "title": action.get('titre', 'Action sans titre'),
                "description": action.get('description', ''),
                "objective": action.get('objectif', ''),
                "severity": action.get('priorite', 'Moyenne'),
                "priority": priority,
                "suggested_role": action.get('responsable_suggere', 'Non défini'),
                "recommended_days": recommended_days,
                "ai_justifications": json.dumps({
                    "justification": action.get('justification', ''),
                    "scenarios_couverts": action.get('scenarios_couverts', []),
                    "sources_couvertes": action.get('sources_couvertes', []),
                    "biens_supports": action.get('biens_supports', []),
                    "references_normatives": action.get('references_normatives', []),
                    "risque_initial": action.get('risque_initial'),
                    "risque_cible": action.get('risque_cible'),
                    "effort": action.get('effort', ''),
                    "cout_estime": action.get('cout_estime', '')
                }),
                "published_at": now,
                "published_by": str(current_user.id)
            })
            published_count += 1

        # 3. Marquer le projet comme publié
        update_project_query = text("""
            UPDATE risk_project
            SET actions_published_at = :published_at,
                actions_published_by = CAST(:published_by AS uuid),
                updated_at = NOW()
            WHERE id = CAST(:project_id AS uuid)
        """)
        db.execute(update_project_query, {
            "project_id": str(project_id),
            "published_at": now,
            "published_by": str(current_user.id)
        })

        db.commit()

        logger.info(f"📤 {published_count} actions EBIOS publiées pour projet {project_id} par {current_user.email}")

        return PublishActionsResponse(
            success=True,
            message=f"{published_count} action(s) publiée(s) dans le module Actions.",
            actions_count=published_count,
            published_at=now
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur publication actions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la publication: {str(e)}"
        )


@router.delete("/projects/{project_id}/unpublish-actions", response_model=UnfreezeResponse)
async def unpublish_actions(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("EBIOS_FREEZE"))
):
    """
    Dépublie les actions EBIOS du module Actions.

    - Supprime toutes les actions publiées pour ce projet
    - Le projet reste figé mais les actions ne sont plus suivies

    Permissions requises: EBIOS_FREEZE
    """
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur sans tenant"
        )

    # Vérifier le projet
    project_query = text("""
        SELECT id, status, actions_published_at
        FROM risk_project
        WHERE id = CAST(:project_id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND deleted_at IS NULL
    """)
    project = db.execute(project_query, {
        "project_id": str(project_id),
        "tenant_id": str(current_user.tenant_id)
    }).fetchone()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet non trouvé"
        )

    if not project.actions_published_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune action n'a été publiée pour ce projet"
        )

    try:
        # 1. Supprimer les actions publiées
        delete_query = text("""
            DELETE FROM published_action
            WHERE risk_project_id = CAST(:project_id AS uuid)
              AND source_type = 'ebios'
        """)
        result = db.execute(delete_query, {"project_id": str(project_id)})
        deleted_count = result.rowcount

        # 2. Mettre à jour le projet
        update_query = text("""
            UPDATE risk_project
            SET actions_published_at = NULL,
                actions_published_by = NULL,
                updated_at = NOW()
            WHERE id = CAST(:project_id AS uuid)
        """)
        db.execute(update_query, {"project_id": str(project_id)})

        db.commit()

        logger.info(f"🗑️ {deleted_count} actions EBIOS dépubliées pour projet {project_id} par {current_user.email}")

        return UnfreezeResponse(
            success=True,
            message=f"{deleted_count} action(s) supprimée(s) du module Actions."
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur dépublication actions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la dépublication: {str(e)}"
        )
