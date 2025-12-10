"""
Service de cache pour les résultats IA
Wrapper autour des services DeepSeek/Ollama avec mise en cache Redis
"""

import hashlib
import json
import logging
from typing import Any, Optional, Dict

from src.utils.redis_manager import redis_manager, cache_result

logger = logging.getLogger(__name__)


class CachedAIService:
    """
    Service de cache pour les résultats d'IA
    Encapsule les appels aux modèles IA avec mise en cache Redis
    """

    @staticmethod
    def generate_prompt_hash(
        prompt: str,
        model: str,
        temperature: float = None,
        max_tokens: int = None,
        **kwargs
    ) -> str:
        """
        Génère un hash unique pour un prompt et ses paramètres

        Args:
            prompt: Le prompt texte
            model: Nom du modèle
            temperature: Température
            max_tokens: Tokens max
            **kwargs: Autres paramètres

        Returns:
            Hash SHA256 tronqué
        """
        # Crée une clé unique basée sur tous les paramètres
        params = {
            "prompt": prompt,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs
        }

        # Trie les clés pour garantir la reproductibilité
        canonical = json.dumps(params, sort_keys=True, ensure_ascii=False)

        # Génère le hash
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    @staticmethod
    async def get_or_generate(
        prompt: str,
        model: str,
        generator_func,
        ttl: int = 3600,
        temperature: float = None,
        max_tokens: int = None,
        force_refresh: bool = False,
        **kwargs
    ) -> Any:
        """
        Récupère le résultat du cache ou génère avec l'IA

        Args:
            prompt: Le prompt
            model: Nom du modèle
            generator_func: Fonction de génération async
            ttl: Durée de vie du cache en secondes
            temperature: Température
            max_tokens: Tokens max
            force_refresh: Force la régénération
            **kwargs: Paramètres additionnels

        Returns:
            Résultat de l'IA (du cache ou nouvellement généré)
        """
        # Génère le hash du prompt
        prompt_hash = CachedAIService.generate_prompt_hash(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        # Vérifie le cache si pas de force refresh
        if not force_refresh and redis_manager.is_connected:
            cached = redis_manager.get_cached_ai_result(model, prompt_hash)
            if cached is not None:
                logger.info(f"✅ Cache HIT pour {model}:{prompt_hash[:8]}")
                return cached

        logger.info(f"⚠️ Cache MISS pour {model}:{prompt_hash[:8]} - Génération...")

        # Génère le résultat
        result = await generator_func(prompt, **kwargs)

        # Met en cache si Redis disponible
        if redis_manager.is_connected:
            success = redis_manager.cache_ai_result(
                model=model,
                prompt_hash=prompt_hash,
                result=result,
                ttl=ttl
            )
            if success:
                logger.info(f"💾 Résultat mis en cache: {model}:{prompt_hash[:8]}")
            else:
                logger.warning(f"⚠️ Échec mise en cache: {model}:{prompt_hash[:8]}")

        return result

    @staticmethod
    async def generate_control_points_cached(
        requirement_text: str,
        generator_service,
        model: str = "deepseek",
        ttl: int = 7200,  # 2 heures pour les points de contrôle
        **kwargs
    ) -> list:
        """
        Génère des points de contrôle avec cache

        Args:
            requirement_text: Texte de l'exigence
            generator_service: Service de génération
            model: Modèle utilisé
            ttl: TTL du cache
            **kwargs: Paramètres additionnels

        Returns:
            Liste des points de contrôle générés
        """
        async def generator(prompt, **gen_kwargs):
            # Appelle la méthode du service
            return await generator_service.generate_control_points(
                requirement_text=prompt,
                **gen_kwargs
            )

        return await CachedAIService.get_or_generate(
            prompt=requirement_text,
            model=model,
            generator_func=generator,
            ttl=ttl,
            **kwargs
        )

    @staticmethod
    async def generate_questions_cached(
        control_point_text: str,
        generator_service,
        model: str = "deepseek",
        ttl: int = 7200,  # 2 heures pour les questions
        **kwargs
    ) -> list:
        """
        Génère des questions avec cache

        Args:
            control_point_text: Texte du point de contrôle
            generator_service: Service de génération
            model: Modèle utilisé
            ttl: TTL du cache
            **kwargs: Paramètres additionnels

        Returns:
            Liste des questions générées
        """
        async def generator(prompt, **gen_kwargs):
            return await generator_service.generate_questions(
                control_point_text=prompt,
                **gen_kwargs
            )

        return await CachedAIService.get_or_generate(
            prompt=control_point_text,
            model=model,
            generator_func=generator,
            ttl=ttl,
            **kwargs
        )

    @staticmethod
    def invalidate_cache(
        model: Optional[str] = None,
        prompt_hash: Optional[str] = None
    ) -> int:
        """
        Invalide le cache IA

        Args:
            model: Modèle spécifique (None = tous)
            prompt_hash: Hash spécifique (None = tous pour le modèle)

        Returns:
            Nombre de clés supprimées
        """
        if not redis_manager.is_connected:
            logger.warning("Redis non connecté - impossible d'invalider le cache")
            return 0

        if prompt_hash and model:
            # Supprime une entrée spécifique
            key = f"ai:{model}:{prompt_hash}"
            success = redis_manager.delete(key)
            return 1 if success else 0
        elif model:
            # Supprime tout le cache d'un modèle
            return redis_manager.clear_ai_cache(model)
        else:
            # Supprime tout le cache IA
            return redis_manager.clear_ai_cache()

    @staticmethod
    def get_cache_stats(model: Optional[str] = None) -> Dict[str, Any]:
        """
        Récupère les statistiques du cache IA

        Args:
            model: Modèle spécifique

        Returns:
            Statistiques du cache
        """
        if not redis_manager.is_connected:
            return {
                "status": "disconnected",
                "message": "Redis non disponible"
            }

        try:
            pattern = f"ai:{model}:*" if model else "ai:*"
            client = redis_manager.client

            if not client:
                return {"status": "error", "message": "Client Redis non disponible"}

            keys = client.keys(pattern)

            return {
                "status": "ok",
                "model": model or "all",
                "total_cached_results": len(keys),
                "pattern": pattern
            }
        except Exception as e:
            logger.error(f"Erreur récupération stats cache: {e}")
            return {
                "status": "error",
                "message": str(e)
            }


# Instance globale
cached_ai_service = CachedAIService()
