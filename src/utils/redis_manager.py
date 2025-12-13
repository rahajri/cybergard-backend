"""
Redis Cache Manager pour AI CYBER
Gestion centralisée du cache, sessions et rate limiting
"""

import json
import logging
from typing import Any, Optional, Union
from datetime import datetime, date, timedelta
from decimal import Decimal
from uuid import UUID
from functools import wraps

import redis
from redis import Redis
from redis.exceptions import RedisError, ConnectionError

from src.config import settings

logger = logging.getLogger(__name__)


# ========================================================================
# JSON ENCODER PERSONNALISÉ
# ========================================================================

class RedisJSONEncoder(json.JSONEncoder):
    """
    Encodeur JSON personnalisé pour gérer les types Python/SQLAlchemy/Pydantic
    """
    def default(self, obj):
        # UUID → string
        if isinstance(obj, UUID):
            return str(obj)

        # datetime/date → ISO string
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()

        # Decimal → float
        if isinstance(obj, Decimal):
            return float(obj)

        # bytes → string
        if isinstance(obj, bytes):
            return obj.decode('utf-8')

        # Enum → valeur
        if hasattr(obj, 'value'):
            return obj.value

        # Pydantic models → dict (via model_dump())
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()

        # SQLAlchemy models → dict (via __dict__)
        if hasattr(obj, '__dict__') and hasattr(obj, '__table__'):
            # Objet SQLAlchemy
            data = {}
            for column in obj.__table__.columns:
                value = getattr(obj, column.name, None)
                # Récursion pour les types complexes
                if isinstance(value, (UUID, datetime, date, Decimal)):
                    value = self.default(value)
                data[column.name] = value
            return data

        # Fallback sur l'encodeur par défaut
        return super().default(obj)


class RedisManager:
    """
    Gestionnaire Redis pour cache, sessions et rate limiting
    """

    def __init__(self):
        self._client: Optional[Redis] = None
        self._connected = False

    def connect(self) -> None:
        """Établit la connexion Redis"""
        try:
            self._client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                decode_responses=True,
                socket_timeout=settings.redis_socket_timeout,
                socket_connect_timeout=settings.redis_socket_connect_timeout,
                max_connections=settings.redis_max_connections,
                health_check_interval=30,
                retry_on_timeout=True,
            )
            # Test de connexion
            self._client.ping()
            self._connected = True
            logger.info(f"✅ Redis connecté: {settings.redis_host}:{settings.redis_port}")
        except ConnectionError as e:
            logger.warning(f"⚠️ Redis non disponible: {e}. Mode dégradé activé.")
            self._connected = False
        except Exception as e:
            logger.error(f"❌ Erreur Redis: {e}")
            self._connected = False

    def disconnect(self) -> None:
        """Ferme la connexion Redis"""
        if self._client:
            try:
                self._client.close()
                logger.info("Redis déconnecté")
            except Exception as e:
                logger.error(f"Erreur lors de la déconnexion Redis: {e}")
        self._connected = False

    @property
    def client(self) -> Optional[Redis]:
        """Retourne le client Redis si connecté"""
        return self._client if self._connected else None

    @property
    def is_connected(self) -> bool:
        """Vérifie si Redis est connecté"""
        if not self._connected or not self._client:
            return False
        try:
            self._client.ping()
            return True
        except:
            self._connected = False
            return False

    # ========================================================================
    # CACHE OPERATIONS
    # ========================================================================

    def get(self, key: str) -> Optional[Any]:
        """
        Récupère une valeur du cache

        Args:
            key: Clé du cache

        Returns:
            Valeur désérialisée ou None
        """
        if not self.is_connected:
            return None

        try:
            value = self._client.get(key)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
        except RedisError as e:
            logger.warning(f"Erreur lecture cache {key}: {e}")
            return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Stocke une valeur dans le cache

        Args:
            key: Clé du cache
            value: Valeur à stocker
            ttl: Durée de vie en secondes (None = utilise default)

        Returns:
            True si succès, False sinon
        """
        if not self.is_connected:
            return False

        try:
            ttl = ttl or settings.redis_cache_ttl

            # Sérialisation JSON pour types complexes avec encodeur personnalisé
            if not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False, cls=RedisJSONEncoder)

            self._client.setex(key, ttl, value)
            return True
        except (RedisError, TypeError, ValueError) as e:
            logger.warning(f"Erreur écriture cache {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """
        Supprime une clé du cache

        Args:
            key: Clé à supprimer

        Returns:
            True si supprimé, False sinon
        """
        if not self.is_connected:
            return False

        try:
            self._client.delete(key)
            return True
        except RedisError as e:
            logger.warning(f"Erreur suppression cache {key}: {e}")
            return False

    def delete_pattern(self, pattern: str) -> int:
        """
        Supprime toutes les clés correspondant au pattern

        Args:
            pattern: Pattern Redis (ex: "user:*", "cache:ollama:*")

        Returns:
            Nombre de clés supprimées
        """
        if not self.is_connected:
            return 0

        try:
            keys = self._client.keys(pattern)
            if keys:
                return self._client.delete(*keys)
            return 0
        except RedisError as e:
            logger.warning(f"Erreur suppression pattern {pattern}: {e}")
            return 0

    def exists(self, key: str) -> bool:
        """
        Vérifie si une clé existe

        Args:
            key: Clé à vérifier

        Returns:
            True si existe, False sinon
        """
        if not self.is_connected:
            return False

        try:
            return bool(self._client.exists(key))
        except RedisError as e:
            logger.warning(f"Erreur vérification existence {key}: {e}")
            return False

    def get_ttl(self, key: str) -> Optional[int]:
        """
        Récupère le TTL d'une clé

        Args:
            key: Clé

        Returns:
            TTL en secondes, -1 si pas d'expiration, -2 si clé inexistante
        """
        if not self.is_connected:
            return None

        try:
            return self._client.ttl(key)
        except RedisError as e:
            logger.warning(f"Erreur récupération TTL {key}: {e}")
            return None

    # ========================================================================
    # RATE LIMITING
    # ========================================================================

    def check_rate_limit(
        self,
        identifier: str,
        max_requests: int = 100,
        window: int = 60
    ) -> tuple[bool, int]:
        """
        Vérifie si le rate limit est dépassé

        Args:
            identifier: Identifiant unique (user_id, IP, etc.)
            max_requests: Nombre max de requêtes
            window: Fenêtre de temps en secondes

        Returns:
            (allowed: bool, remaining: int)
        """
        if not self.is_connected:
            return True, max_requests  # Mode dégradé: autorise

        try:
            key = f"rate_limit:{identifier}"

            # Incrémente le compteur
            current = self._client.incr(key)

            # Définit l'expiration si première requête
            if current == 1:
                self._client.expire(key, window)

            # Vérifie la limite
            allowed = current <= max_requests
            remaining = max(0, max_requests - current)

            return allowed, remaining
        except RedisError as e:
            logger.warning(f"Erreur rate limiting {identifier}: {e}")
            return True, max_requests  # Mode dégradé

    def reset_rate_limit(self, identifier: str) -> bool:
        """
        Réinitialise le compteur de rate limit

        Args:
            identifier: Identifiant unique

        Returns:
            True si réussi
        """
        return self.delete(f"rate_limit:{identifier}")

    # ========================================================================
    # SESSIONS
    # ========================================================================

    def set_session(
        self,
        session_id: str,
        data: dict,
        ttl: Optional[int] = None
    ) -> bool:
        """
        Stocke des données de session

        Args:
            session_id: ID de session
            data: Données de session
            ttl: Durée de vie (None = utilise SESSION_TTL)

        Returns:
            True si succès
        """
        ttl = ttl or settings.redis_session_ttl
        return self.set(f"session:{session_id}", data, ttl)

    def get_session(self, session_id: str) -> Optional[dict]:
        """
        Récupère les données de session

        Args:
            session_id: ID de session

        Returns:
            Données de session ou None
        """
        return self.get(f"session:{session_id}")

    def delete_session(self, session_id: str) -> bool:
        """
        Supprime une session

        Args:
            session_id: ID de session

        Returns:
            True si supprimé
        """
        return self.delete(f"session:{session_id}")

    # ========================================================================
    # CACHE HELPERS
    # ========================================================================

    def cache_ai_result(
        self,
        model: str,
        prompt_hash: str,
        result: Any,
        ttl: int = 3600
    ) -> bool:
        """
        Cache un résultat d'IA

        Args:
            model: Nom du modèle (ex: "deepseek-v3.1")
            prompt_hash: Hash du prompt
            result: Résultat à cacher
            ttl: Durée de vie en secondes

        Returns:
            True si succès
        """
        key = f"ai:{model}:{prompt_hash}"
        return self.set(key, result, ttl)

    def get_cached_ai_result(
        self,
        model: str,
        prompt_hash: str
    ) -> Optional[Any]:
        """
        Récupère un résultat d'IA du cache

        Args:
            model: Nom du modèle
            prompt_hash: Hash du prompt

        Returns:
            Résultat caché ou None
        """
        key = f"ai:{model}:{prompt_hash}"
        return self.get(key)

    def clear_ai_cache(self, model: Optional[str] = None) -> int:
        """
        Efface le cache IA

        Args:
            model: Modèle spécifique ou None pour tout effacer

        Returns:
            Nombre de clés supprimées
        """
        pattern = f"ai:{model}:*" if model else "ai:*"
        return self.delete_pattern(pattern)

    # ========================================================================
    # STATISTICS
    # ========================================================================

    def get_stats(self) -> dict:
        """
        Récupère les statistiques Redis

        Returns:
            Dictionnaire de statistiques
        """
        if not self.is_connected:
            return {"status": "disconnected"}

        try:
            info = self._client.info()
            return {
                "status": "connected",
                "version": info.get("redis_version"),
                "uptime_seconds": info.get("uptime_in_seconds"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "total_commands": info.get("total_commands_processed"),
                "keyspace": info.get("db0", {}),
            }
        except RedisError as e:
            logger.error(f"Erreur récupération stats: {e}")
            return {"status": "error", "error": str(e)}


# Instance globale
redis_manager = RedisManager()


# ========================================================================
# DECORATOR POUR CACHE
# ========================================================================

def cache_result(
    ttl: int = 3600,
    key_prefix: str = "cache",
    include_args: bool = True,
    version_sensitive: bool = True
):
    """
    Décorateur pour cacher les résultats de fonction

    Args:
        ttl: Durée de vie du cache en secondes
        key_prefix: Préfixe pour la clé de cache
        include_args: Inclure les arguments dans la clé
        version_sensitive: Inclure un hash du code source (invalidation auto si code modifié)

    Usage:
        @cache_result(ttl=600, key_prefix="insee", version_sensitive=True)
        def get_company_info(siret: str):
            ...
    """
    def decorator(func):
        # ✅ Calcule le hash du code source de la fonction (une seule fois au démarrage)
        func_version = ""
        if version_sensitive:
            import inspect
            import hashlib
            try:
                source_code = inspect.getsource(func)
                func_version = hashlib.md5(source_code.encode()).hexdigest()[:8]
            except (OSError, TypeError):
                # Si impossible d'obtenir le code source, on utilise un hash du nom
                func_version = hashlib.md5(func.__name__.encode()).hexdigest()[:8]

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not redis_manager.is_connected:
                return await func(*args, **kwargs)

            # ✅ SÉCURITÉ: Extraire le tenant EFFECTIF pour isolation du cache
            # Priorité: client_organization_id (tenant actif dans l'UI) > tenant_id explicite > current_user.tenant_id
            tenant_id = None

            # 1. Chercher client_organization_id (tenant actif sélectionné dans l'UI)
            if 'client_organization_id' in kwargs and kwargs['client_organization_id']:
                tenant_id = str(kwargs['client_organization_id'])
            # 2. Chercher tenant_id explicite
            elif 'tenant_id' in kwargs and kwargs['tenant_id']:
                tenant_id = str(kwargs['tenant_id'])
            # 3. Fallback: utiliser le tenant de l'utilisateur connecté
            else:
                current_user = kwargs.get('current_user')
                if current_user and hasattr(current_user, 'tenant_id'):
                    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else 'no_tenant'

            # Génère la clé de cache avec version du code ET tenant_id
            if include_args:
                args_str = json.dumps([str(a) for a in args] + [f"{k}={v}" for k, v in kwargs.items()])
                tenant_part = f":tenant:{tenant_id}" if tenant_id else ""
                cache_key = f"{key_prefix}:{func.__name__}{tenant_part}:v{func_version}:{hash(args_str)}"
            else:
                tenant_part = f":tenant:{tenant_id}" if tenant_id else ""
                cache_key = f"{key_prefix}:{func.__name__}{tenant_part}:v{func_version}"

            # Vérifie le cache
            cached = redis_manager.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached

            # Exécute la fonction
            logger.debug(f"Cache MISS: {cache_key}")
            result = await func(*args, **kwargs)

            # Stocke dans le cache
            redis_manager.set(cache_key, result, ttl)

            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not redis_manager.is_connected:
                return func(*args, **kwargs)

            # ✅ SÉCURITÉ: Extraire le tenant EFFECTIF pour isolation du cache
            # Priorité: client_organization_id (tenant actif dans l'UI) > tenant_id explicite > current_user.tenant_id
            tenant_id = None

            # 1. Chercher client_organization_id (tenant actif sélectionné dans l'UI)
            if 'client_organization_id' in kwargs and kwargs['client_organization_id']:
                tenant_id = str(kwargs['client_organization_id'])
            # 2. Chercher tenant_id explicite
            elif 'tenant_id' in kwargs and kwargs['tenant_id']:
                tenant_id = str(kwargs['tenant_id'])
            # 3. Fallback: utiliser le tenant de l'utilisateur connecté
            else:
                current_user = kwargs.get('current_user')
                if current_user and hasattr(current_user, 'tenant_id'):
                    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else 'no_tenant'

            # Génère la clé de cache avec version du code ET tenant_id
            if include_args:
                args_str = json.dumps([str(a) for a in args] + [f"{k}={v}" for k, v in kwargs.items()])
                tenant_part = f":tenant:{tenant_id}" if tenant_id else ""
                cache_key = f"{key_prefix}:{func.__name__}{tenant_part}:v{func_version}:{hash(args_str)}"
            else:
                tenant_part = f":tenant:{tenant_id}" if tenant_id else ""
                cache_key = f"{key_prefix}:{func.__name__}{tenant_part}:v{func_version}"

            # Vérifie le cache
            cached = redis_manager.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached

            # Exécute la fonction
            logger.debug(f"Cache MISS: {cache_key}")
            result = func(*args, **kwargs)

            # Stocke dans le cache
            redis_manager.set(cache_key, result, ttl)

            return result

        # Détecte si la fonction est async
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ========================================================================
# HELPER FUNCTION - cache_get_or_set
# ========================================================================

def get_cache_key(func: callable, params: dict) -> str:
    """
    Génère une clé de cache unique basée sur la fonction et ses paramètres

    Args:
        func: La fonction à cacher
        params: Dictionnaire des paramètres

    Returns:
        Clé de cache unique

    Usage:
        key = get_cache_key(list_orgs, {"tenant_id": "123", "page": 1, "size": 10})
    """
    import hashlib
    import inspect

    # Hash du code source (version sensitivity)
    try:
        source_code = inspect.getsource(func)
        func_version = hashlib.md5(source_code.encode()).hexdigest()[:8]
    except (OSError, TypeError):
        func_version = hashlib.md5(func.__name__.encode()).hexdigest()[:8]

    # Hash des paramètres
    params_str = json.dumps(params, sort_keys=True, default=str)
    params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]

    return f"cache:{func.__name__}:v{func_version}:{params_hash}"


def cache_get_or_set(key: str, ttl: int, fetch: callable) -> Any:
    """
    Récupère la valeur du cache ou exécute la fonction fetch si absente

    Args:
        key: Clé de cache
        ttl: Durée de vie du cache en secondes
        fetch: Fonction à exécuter si cache MISS (callable sans arguments)

    Returns:
        Valeur cachée ou résultat de fetch()

    Usage:
        def list_orgs(tenant_id, page, size, search=None):
            params = {"tenant_id": tenant_id, "page": page, "size": size, "search": search or ""}
            key = get_cache_key(list_orgs, params)

            def fetch():
                base = db.query(Organization).filter_by(tenant_id=tenant_id)
                if search:
                    base = base.filter(Organization.name.ilike(f"%{search}%"))
                return [o.name for o in base.limit(size).offset((page-1)*size).all()]

            return cache_get_or_set(key, ttl=120, fetch=fetch)
    """
    if not redis_manager.is_connected:
        return fetch()

    # Vérifie le cache
    cached = redis_manager.get(key)
    if cached is not None:
        logger.debug(f"✅ Cache HIT: {key}")
        return cached

    # Exécute la fonction fetch
    logger.debug(f"⚠️ Cache MISS: {key}")
    result = fetch()

    # Stocke dans le cache
    redis_manager.set(key, result, ttl)
    logger.debug(f"💾 Résultat mis en cache: {key} (TTL={ttl}s)")

    return result
