"""
Endpoints de monitoring et gestion Redis
"""

from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any, Optional

from src.utils.redis_manager import redis_manager

router = APIRouter()


@router.get("/redis/health", tags=["Monitoring"])
async def redis_health():
    """
    Vérifie l'état de santé de Redis

    Returns:
        État de connexion Redis
    """
    if redis_manager.is_connected:
        return {
            "status": "healthy",
            "connected": True,
            "message": "Redis est opérationnel"
        }
    else:
        return {
            "status": "degraded",
            "connected": False,
            "message": "Redis non disponible - Mode dégradé actif"
        }


@router.get("/redis/stats", tags=["Monitoring"])
async def redis_stats():
    """
    Récupère les statistiques Redis

    Returns:
        Statistiques détaillées de Redis
    """
    if not redis_manager.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis non disponible"
        )

    stats = redis_manager.get_stats()

    return {
        "redis": stats,
        "timestamp": stats.get("uptime_seconds", 0)
    }


@router.delete("/redis/cache", tags=["Monitoring"])
async def clear_cache(pattern: str = "*"):
    """
    Efface le cache Redis

    Args:
        pattern: Pattern des clés à supprimer (défaut: "*" = tout)

    Returns:
        Nombre de clés supprimées
    """
    if not redis_manager.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis non disponible"
        )

    # Sécurité: limite les patterns autorisés
    allowed_patterns = ["cache:*", "ai:*", "session:*", "rate_limit:*", "*"]
    if pattern not in allowed_patterns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pattern non autorisé. Utilisez: {', '.join(allowed_patterns)}"
        )

    deleted = redis_manager.delete_pattern(pattern)

    return {
        "message": f"Cache effacé avec succès",
        "pattern": pattern,
        "keys_deleted": deleted
    }


@router.delete("/redis/cache/ai", tags=["Monitoring"])
async def clear_ai_cache(model: Optional[str] = None):
    """
    Efface le cache des résultats IA

    Args:
        model: Modèle spécifique (optionnel)

    Returns:
        Nombre de clés supprimées
    """
    if not redis_manager.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis non disponible"
        )

    deleted = redis_manager.clear_ai_cache(model)

    return {
        "message": f"Cache IA effacé avec succès",
        "model": model or "tous",
        "keys_deleted": deleted
    }


@router.get("/redis/keys", tags=["Monitoring"])
async def list_keys(pattern: str = "*", limit: int = 100):
    """
    Liste les clés Redis correspondant au pattern

    Args:
        pattern: Pattern de recherche
        limit: Nombre maximum de clés à retourner

    Returns:
        Liste des clés trouvées
    """
    if not redis_manager.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis non disponible"
        )

    try:
        client = redis_manager.client
        if not client:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Client Redis non disponible"
            )

        keys = client.keys(pattern)[:limit]

        # Récupère les TTL pour chaque clé
        keys_with_ttl = []
        for key in keys:
            ttl = redis_manager.get_ttl(key)
            keys_with_ttl.append({
                "key": key,
                "ttl": ttl,
                "type": client.type(key) if hasattr(client, 'type') else "unknown"
            })

        return {
            "pattern": pattern,
            "count": len(keys_with_ttl),
            "total_matching": len(client.keys(pattern)),
            "limit": limit,
            "keys": keys_with_ttl
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des clés: {str(e)}"
        )
