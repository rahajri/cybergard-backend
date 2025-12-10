"""
API endpoints pour la gestion des périmètres de campagnes (campaign_scope)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging

from src.database import get_db
from src.utils.redis_manager import cache_result
from src.dependencies_keycloak import get_current_user_keycloak, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaign-scopes", tags=["Campaign Scopes"])


# ============================================================================
# SCHEMAS
# ============================================================================

from pydantic import BaseModel, Field

class CampaignScopeCreate(BaseModel):
    """Schéma pour la création d'un périmètre de campagne"""
    name: str = Field(..., min_length=1, max_length=255, description="Nom du périmètre")
    description: Optional[str] = Field(None, description="Description du périmètre")
    entity_ids: List[UUID] = Field(..., min_items=1, description="Liste des IDs des entités incluses")
    auditor_ids: List[UUID] = Field(..., min_items=1, description="Liste des IDs des auditeurs assignés")
    is_active: bool = Field(True, description="Périmètre actif ou non")


class CampaignScopeResponse(BaseModel):
    """Schéma de réponse pour un périmètre de campagne"""
    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str]
    entity_ids: List[UUID]
    auditor_ids: List[UUID]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID]

    # Champs calculés
    entities_count: int = 0
    auditors_count: int = 0

    class Config:
        from_attributes = True


class CampaignScopeListResponse(BaseModel):
    """Schéma de réponse pour la liste des périmètres"""
    items: List[CampaignScopeResponse]
    total: int
    skip: int = 0
    limit: int = 100


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("", response_model=CampaignScopeListResponse)
@cache_result(ttl=600, key_prefix="campaign_scopes_list")  # Cache 10min
async def list_campaign_scopes(
    is_active: Optional[bool] = Query(None, description="Filtrer par statut actif/inactif"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    Liste tous les périmètres de campagne avec filtres et pagination
    """
    try:
        # Build WHERE clause
        where_clauses = []
        params = {"limit": limit, "skip": skip}

        if is_active is not None:
            where_clauses.append("is_active = :is_active")
            params["is_active"] = is_active

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # Query
        query = text(f"""
            SELECT
                id,
                tenant_id,
                name,
                description,
                entity_ids,
                auditor_ids,
                is_active,
                created_at,
                updated_at,
                created_by
            FROM campaign_scope
            {where_sql}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :skip
        """)

        result = db.execute(query, params)
        scopes_data = result.fetchall()

        # Convert to dict
        scopes = []
        for row in scopes_data:
            scopes.append({
                "id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "name": row.name,
                "description": row.description,
                "entity_ids": [str(eid) for eid in row.entity_ids] if row.entity_ids else [],
                "auditor_ids": [str(aid) for aid in row.auditor_ids] if row.auditor_ids else [],
                "is_active": row.is_active,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "created_by": str(row.created_by) if row.created_by else None,
                "entities_count": len(row.entity_ids) if row.entity_ids else 0,
                "auditors_count": len(row.auditor_ids) if row.auditor_ids else 0,
            })

        # Count total
        count_query = text(f"""
            SELECT COUNT(*)
            FROM campaign_scope
            {where_sql}
        """)

        count_params = {}
        if is_active is not None:
            count_params["is_active"] = is_active

        total = db.execute(count_query, count_params).scalar()

        logger.info(f"✅ {len(scopes)} périmètre(s) de campagne récupéré(s)")

        return {
            "items": scopes,
            "total": total or 0,
            "skip": skip,
            "limit": limit
        }

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des périmètres: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des périmètres: {str(e)}"
        )


@router.get("/{scope_id}", response_model=CampaignScopeResponse)
@cache_result(ttl=600, key_prefix="campaign_scope_detail")  # Cache 10min
async def get_campaign_scope(
    scope_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Récupère les détails d'un périmètre de campagne
    """
    try:
        query = text("""
            SELECT
                id,
                tenant_id,
                name,
                description,
                entity_ids,
                auditor_ids,
                is_active,
                created_at,
                updated_at,
                created_by
            FROM campaign_scope
            WHERE id = :scope_id
        """)

        result = db.execute(query, {"scope_id": str(scope_id)}).fetchone()

        if not result:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Périmètre {scope_id} introuvable"
            )

        return {
            "id": str(result.id),
            "tenant_id": str(result.tenant_id),
            "name": result.name,
            "description": result.description,
            "entity_ids": [str(eid) for eid in result.entity_ids] if result.entity_ids else [],
            "auditor_ids": [str(aid) for aid in result.auditor_ids] if result.auditor_ids else [],
            "is_active": result.is_active,
            "created_at": result.created_at,
            "updated_at": result.updated_at,
            "created_by": str(result.created_by) if result.created_by else None,
            "entities_count": len(result.entity_ids) if result.entity_ids else 0,
            "auditors_count": len(result.auditor_ids) if result.auditor_ids else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du périmètre: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération du périmètre: {str(e)}"
        )


@router.post("", response_model=CampaignScopeResponse, status_code=http_status.HTTP_201_CREATED)
async def create_campaign_scope(
    scope: CampaignScopeCreate,
    current_user = Depends(require_permission("CAMPAIGN_READ")),
    db: Session = Depends(get_db)
):
    """
    Crée un nouveau périmètre de campagne réutilisable
    """
    try:
        # Récupérer le tenant_id et user_id de l'utilisateur connecté
        if not current_user.tenant_id:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Utilisateur sans tenant. Impossible de créer un périmètre."
            )

        tenant_id = str(current_user.tenant_id)
        created_by = str(current_user.id)

        # Convertir les UUIDs en strings pour PostgreSQL
        entity_ids_str = [str(eid) for eid in scope.entity_ids]
        auditor_ids_str = [str(aid) for aid in scope.auditor_ids]

        # Créer le scope
        insert_query = text("""
            INSERT INTO campaign_scope (
                tenant_id,
                name,
                description,
                entity_ids,
                auditor_ids,
                is_active,
                created_by,
                created_at,
                updated_at
            ) VALUES (
                :tenant_id,
                :name,
                :description,
                CAST(:entity_ids AS uuid[]),
                CAST(:auditor_ids AS uuid[]),
                :is_active,
                :created_by,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            RETURNING id
        """)

        params = {
            "tenant_id": tenant_id,
            "name": scope.name,
            "description": scope.description,
            "entity_ids": entity_ids_str,
            "auditor_ids": auditor_ids_str,
            "is_active": scope.is_active,
            "created_by": created_by,
        }

        result = db.execute(insert_query, params)
        scope_id = result.fetchone().id
        db.commit()

        logger.info(f"✅ Périmètre créé: {scope_id} - {scope.name}")

        # Invalider le cache
        from src.utils.redis_manager import redis_manager
        if redis_manager.is_connected:
            redis_manager.delete_pattern("campaign_scopes_list:*")
            logger.info(f"🔄 Cache invalidé pour campaign_scopes_list")

        # Récupérer le scope créé
        return await get_campaign_scope(scope_id, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la création du périmètre: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création du périmètre: {str(e)}"
        )


@router.patch("/{scope_id}", response_model=CampaignScopeResponse)
async def update_campaign_scope(
    scope_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    entity_ids: Optional[List[UUID]] = None,
    auditor_ids: Optional[List[UUID]] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    Met à jour un périmètre de campagne
    """
    try:
        # Vérifier que le scope existe
        check_query = text("SELECT id FROM campaign_scope WHERE id = :scope_id")
        if not db.execute(check_query, {"scope_id": str(scope_id)}).fetchone():
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Périmètre {scope_id} introuvable"
            )

        # Construire la requête de mise à jour
        updates = []
        params = {"scope_id": str(scope_id)}

        if name is not None:
            updates.append("name = :name")
            params["name"] = name

        if description is not None:
            updates.append("description = :description")
            params["description"] = description

        if entity_ids is not None:
            updates.append("entity_ids = :entity_ids")
            params["entity_ids"] = [str(eid) for eid in entity_ids]

        if auditor_ids is not None:
            updates.append("auditor_ids = :auditor_ids")
            params["auditor_ids"] = [str(aid) for aid in auditor_ids]

        if is_active is not None:
            updates.append("is_active = :is_active")
            params["is_active"] = is_active

        if not updates:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Aucune modification fournie"
            )

        updates.append("updated_at = CURRENT_TIMESTAMP")

        update_query = text(f"""
            UPDATE campaign_scope
            SET {", ".join(updates)}
            WHERE id = :scope_id
        """)

        db.execute(update_query, params)
        db.commit()

        logger.info(f"✅ Périmètre mis à jour: {scope_id}")

        # Invalider le cache
        from src.utils.redis_manager import redis_manager
        if redis_manager.is_connected:
            redis_manager.delete_pattern("campaign_scopes_list:*")
            redis_manager.delete_pattern(f"campaign_scope_detail:{scope_id}:*")
            logger.info(f"🔄 Cache invalidé pour campaign_scope {scope_id}")

        # Récupérer le scope mis à jour
        return await get_campaign_scope(scope_id, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la mise à jour du périmètre: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour du périmètre: {str(e)}"
        )


@router.delete("/{scope_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_campaign_scope(
    scope_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Supprime un périmètre de campagne
    """
    try:
        # Vérifier si le scope est utilisé par des campagnes
        check_usage = text("""
            SELECT COUNT(*) as count
            FROM campaign
            WHERE scope_id = :scope_id
        """)

        usage_count = db.execute(check_usage, {"scope_id": str(scope_id)}).fetchone().count

        if usage_count > 0:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Ce périmètre est utilisé par {usage_count} campagne(s). Impossible de le supprimer."
            )

        # Supprimer le scope
        delete_query = text("""
            DELETE FROM campaign_scope
            WHERE id = :scope_id
        """)

        result = db.execute(delete_query, {"scope_id": str(scope_id)})

        if result.rowcount == 0:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Périmètre {scope_id} introuvable"
            )

        db.commit()

        logger.info(f"✅ Périmètre supprimé: {scope_id}")

        # Invalider le cache
        from src.utils.redis_manager import redis_manager
        if redis_manager.is_connected:
            redis_manager.delete_pattern("campaign_scopes_list:*")
            redis_manager.delete_pattern(f"campaign_scope_detail:{scope_id}:*")
            logger.info(f"🔄 Cache invalidé pour campaign_scope {scope_id}")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la suppression du périmètre: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression du périmètre: {str(e)}"
        )
