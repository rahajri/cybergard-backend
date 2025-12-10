"""
Rate Limiting Middleware avec Redis
"""

import logging
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.utils.redis_manager import redis_manager

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware de rate limiting basé sur Redis
    Limite le nombre de requêtes par IP/utilisateur
    """

    def __init__(
        self,
        app,
        max_requests: int = 100,
        window_seconds: int = 60,
        exclude_paths: list[str] = None
    ):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/openapi.json", "/redoc"]

    async def dispatch(self, request: Request, call_next):
        # Ignore les chemins exclus
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Si Redis n'est pas disponible, on laisse passer
        if not redis_manager.is_connected:
            return await call_next(request)

        # Identifiant unique (IP ou user_id si authentifié)
        client_id = self._get_client_identifier(request)

        # Vérifie le rate limit
        allowed, remaining = redis_manager.check_rate_limit(
            identifier=client_id,
            max_requests=self.max_requests,
            window=self.window_seconds
        )

        if not allowed:
            logger.warning(f"Rate limit dépassé pour {client_id}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Trop de requêtes",
                    "message": f"Limite de {self.max_requests} requêtes par {self.window_seconds}s dépassée",
                    "retry_after": self.window_seconds
                }
            )

        # Exécute la requête
        response = await call_next(request)

        # Ajoute les headers de rate limiting
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(self.window_seconds)

        return response

    def _get_client_identifier(self, request: Request) -> str:
        """
        Génère un identifiant unique pour le client

        Args:
            request: Requête FastAPI

        Returns:
            Identifiant unique (IP ou user_id)
        """
        # Si utilisateur authentifié, utilise son ID
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "id"):
            return f"user:{user.id}"

        # Sinon utilise l'IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"

        return f"ip:{ip}"


def create_rate_limiter(
    max_requests: int = 100,
    window_seconds: int = 60,
    exclude_paths: list[str] = None
):
    """
    Factory pour créer un middleware de rate limiting

    Args:
        max_requests: Nombre maximum de requêtes
        window_seconds: Fenêtre de temps en secondes
        exclude_paths: Chemins à exclure

    Returns:
        Middleware configuré
    """
    def middleware(app):
        return RateLimitMiddleware(
            app,
            max_requests=max_requests,
            window_seconds=window_seconds,
            exclude_paths=exclude_paths
        )
    return middleware
