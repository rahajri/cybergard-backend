"""
Endpoint API pour la gestion administrative des Magic Links
Permet de réinitialiser, supprimer ou gérer les tokens pour les tests
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
import logging

from src.database import get_db
from src.models.audit_token import AuditToken
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class TokenResetRequest(BaseModel):
    """Requête pour réinitialiser un ou plusieurs tokens"""
    token_jti: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    reset_all: bool = False


class TokenUpdateRequest(BaseModel):
    """Requête pour modifier un token"""
    max_uses: Optional[int] = None
    used_count: Optional[int] = None
    revoked: Optional[bool] = None


class TokenStatsResponse(BaseModel):
    """Statistiques des tokens"""
    total_tokens: int
    active_tokens: int
    expired_tokens: int
    revoked_tokens: int
    fully_used_tokens: int
    total_uses: int


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset_token_usage(
    payload: TokenResetRequest,
    db: Session = Depends(get_db)
):
    """
    Réinitialise le compteur d'utilisations d'un ou plusieurs tokens.

    Utile pour les tests de développement.

    Args:
        payload: Configuration de réinitialisation
        - token_jti: Réinitialise un token spécifique
        - campaign_id: Réinitialise tous les tokens d'une campagne
        - reset_all: Réinitialise TOUS les tokens (dangereux!)

    Returns:
        Nombre de tokens réinitialisés
    """
    try:
        tokens_reset = 0

        if payload.token_jti:
            # Réinitialiser un token spécifique
            query = text("""
                UPDATE audit_tokens
                SET used_count = 0,
                    first_used_at = NULL,
                    last_used_at = NULL,
                    last_used_ip = NULL,
                    last_user_agent = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE token_jti = :token_jti
                RETURNING token_jti
            """)
            result = db.execute(query, {"token_jti": str(payload.token_jti)})
            tokens_reset = len(result.fetchall())
            db.commit()

            if tokens_reset == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Token {payload.token_jti} introuvable"
                )

            logger.info(f"✅ Token réinitialisé: {payload.token_jti}")

        elif payload.campaign_id:
            # Réinitialiser tous les tokens d'une campagne
            query = text("""
                UPDATE audit_tokens
                SET used_count = 0,
                    first_used_at = NULL,
                    last_used_at = NULL,
                    last_used_ip = NULL,
                    last_user_agent = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE campaign_id = :campaign_id
                RETURNING token_jti
            """)
            result = db.execute(query, {"campaign_id": str(payload.campaign_id)})
            tokens_reset = len(result.fetchall())
            db.commit()

            logger.info(f"✅ {tokens_reset} token(s) réinitialisé(s) pour la campagne {payload.campaign_id}")

        elif payload.reset_all:
            # Réinitialiser TOUS les tokens (à utiliser avec précaution)
            query = text("""
                UPDATE audit_tokens
                SET used_count = 0,
                    first_used_at = NULL,
                    last_used_at = NULL,
                    last_used_ip = NULL,
                    last_user_agent = NULL,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING token_jti
            """)
            result = db.execute(query)
            tokens_reset = len(result.fetchall())
            db.commit()

            logger.warning(f"⚠️ TOUS les tokens ont été réinitialisés ({tokens_reset})")

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vous devez spécifier token_jti, campaign_id ou reset_all=true"
            )

        return {
            "message": f"{tokens_reset} token(s) réinitialisé(s) avec succès",
            "tokens_reset": tokens_reset
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la réinitialisation des tokens: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la réinitialisation: {str(e)}"
        )


@router.patch("/{token_jti}", status_code=status.HTTP_200_OK)
async def update_token(
    token_jti: UUID,
    payload: TokenUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Met à jour les propriétés d'un token.

    Permet de :
    - Augmenter la limite d'utilisations (max_uses)
    - Modifier le compteur d'utilisations (used_count)
    - Révoquer ou dé-révoquer (revoked)

    Args:
        token_jti: ID du token à modifier
        payload: Nouvelles valeurs

    Returns:
        Token mis à jour
    """
    try:
        # Vérifier que le token existe
        token = db.execute(
            select(AuditToken).where(AuditToken.token_jti == token_jti)
        ).scalar_one_or_none()

        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Token {token_jti} introuvable"
            )

        # Construire la requête UPDATE dynamique
        updates = []
        params = {"token_jti": str(token_jti)}

        if payload.max_uses is not None:
            updates.append("max_uses = :max_uses")
            params["max_uses"] = payload.max_uses

        if payload.used_count is not None:
            updates.append("used_count = :used_count")
            params["used_count"] = payload.used_count

        if payload.revoked is not None:
            updates.append("revoked = :revoked")
            params["revoked"] = payload.revoked

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Aucune modification spécifiée"
            )

        updates.append("updated_at = CURRENT_TIMESTAMP")

        query = text(f"""
            UPDATE audit_tokens
            SET {', '.join(updates)}
            WHERE token_jti = :token_jti
            RETURNING token_jti, user_email, max_uses, used_count, revoked
        """)

        result = db.execute(query, params).fetchone()
        db.commit()

        logger.info(f"✅ Token {token_jti} mis à jour")

        return {
            "token_jti": str(result.token_jti),
            "user_email": result.user_email,
            "max_uses": result.max_uses,
            "used_count": result.used_count,
            "revoked": result.revoked
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la mise à jour du token: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour: {str(e)}"
        )


@router.delete("/{token_jti}", status_code=status.HTTP_200_OK)
async def delete_token(
    token_jti: UUID,
    db: Session = Depends(get_db)
):
    """
    Supprime définitivement un token de la base de données.

    ⚠️ Action irréversible !

    Args:
        token_jti: ID du token à supprimer

    Returns:
        Message de confirmation
    """
    try:
        query = text("""
            DELETE FROM audit_tokens
            WHERE token_jti = :token_jti
            RETURNING token_jti, user_email
        """)

        result = db.execute(query, {"token_jti": str(token_jti)}).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Token {token_jti} introuvable"
            )

        db.commit()

        logger.info(f"🗑️ Token supprimé: {token_jti} ({result.user_email})")

        return {
            "message": f"Token {token_jti} supprimé avec succès",
            "deleted_token": {
                "token_jti": str(result.token_jti),
                "user_email": result.user_email
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur lors de la suppression du token: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression: {str(e)}"
        )


@router.get("/list", status_code=status.HTTP_200_OK)
async def list_tokens(
    campaign_id: Optional[UUID] = Query(None, description="Filtrer par campagne"),
    user_email: Optional[str] = Query(None, description="Filtrer par email"),
    revoked: Optional[bool] = Query(None, description="Filtrer par statut révoqué"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Liste les tokens avec filtres optionnels.

    Utile pour diagnostiquer les problèmes d'accès.

    Args:
        campaign_id: Filtrer par campagne
        user_email: Filtrer par email utilisateur
        revoked: Filtrer par statut révoqué (true/false)
        limit: Nombre max de résultats
        offset: Décalage pour pagination

    Returns:
        Liste des tokens
    """
    try:
        # Construire la requête avec filtres
        conditions = ["1=1"]
        params = {"limit": limit, "offset": offset}

        if campaign_id:
            conditions.append("campaign_id = :campaign_id")
            params["campaign_id"] = str(campaign_id)

        if user_email:
            conditions.append("user_email ILIKE :user_email")
            params["user_email"] = f"%{user_email}%"

        if revoked is not None:
            conditions.append("revoked = :revoked")
            params["revoked"] = revoked

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT
                token_jti,
                user_email,
                campaign_id,
                questionnaire_id,
                expires_at,
                max_uses,
                used_count,
                revoked,
                first_used_at,
                last_used_at,
                last_used_ip,
                created_at
            FROM audit_tokens
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)

        result = db.execute(query, params)
        tokens = result.fetchall()

        # Compter le total
        count_query = text(f"""
            SELECT COUNT(*)
            FROM audit_tokens
            WHERE {where_clause}
        """)
        total = db.execute(count_query, {k: v for k, v in params.items() if k not in ['limit', 'offset']}).scalar()

        tokens_list = []
        for token in tokens:
            tokens_list.append({
                "token_jti": str(token.token_jti),
                "user_email": token.user_email,
                "campaign_id": str(token.campaign_id),
                "questionnaire_id": str(token.questionnaire_id) if token.questionnaire_id else None,
                "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                "max_uses": token.max_uses,
                "used_count": token.used_count,
                "revoked": token.revoked,
                "first_used_at": token.first_used_at.isoformat() if token.first_used_at else None,
                "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
                "last_used_ip": str(token.last_used_ip) if token.last_used_ip else None,
                "created_at": token.created_at.isoformat() if token.created_at else None,
                "is_valid": (
                    not token.revoked and
                    token.expires_at > datetime.now(timezone.utc) and
                    token.used_count < token.max_uses
                )
            })

        logger.info(f"📋 {len(tokens_list)} token(s) récupéré(s)")

        return {
            "items": tokens_list,
            "total": total,
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des tokens: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )


@router.get("/stats", response_model=TokenStatsResponse)
async def get_tokens_stats(
    campaign_id: Optional[UUID] = Query(None, description="Filtrer par campagne"),
    db: Session = Depends(get_db)
):
    """
    Récupère les statistiques globales des tokens.

    Args:
        campaign_id: Filtrer par campagne (optionnel)

    Returns:
        Statistiques des tokens
    """
    try:
        where_clause = "1=1"
        params = {}

        if campaign_id:
            where_clause = "campaign_id = :campaign_id"
            params["campaign_id"] = str(campaign_id)

        query = text(f"""
            SELECT
                COUNT(*) as total_tokens,
                COUNT(*) FILTER (
                    WHERE NOT revoked
                      AND expires_at > CURRENT_TIMESTAMP
                      AND used_count < max_uses
                ) as active_tokens,
                COUNT(*) FILTER (
                    WHERE expires_at <= CURRENT_TIMESTAMP
                      AND NOT revoked
                ) as expired_tokens,
                COUNT(*) FILTER (WHERE revoked = true) as revoked_tokens,
                COUNT(*) FILTER (WHERE used_count >= max_uses) as fully_used_tokens,
                COALESCE(SUM(used_count), 0) as total_uses
            FROM audit_tokens
            WHERE {where_clause}
        """)

        result = db.execute(query, params).fetchone()

        return TokenStatsResponse(
            total_tokens=result.total_tokens,
            active_tokens=result.active_tokens,
            expired_tokens=result.expired_tokens,
            revoked_tokens=result.revoked_tokens,
            fully_used_tokens=result.fully_used_tokens,
            total_uses=result.total_uses
        )

    except Exception as e:
        logger.error(f"❌ Erreur lors du calcul des stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du calcul des statistiques: {str(e)}"
        )
