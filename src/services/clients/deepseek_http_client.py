"""
DeepSeek HTTP Client

Client HTTP robuste pour Ollama/DeepSeek avec:
- Support multi-endpoints (Ollama /api/chat + OpenAI /v1/chat/completions)
- Retry logic avec backoff exponentiel
- Timeouts progressifs
- Gestion erreurs 5xx/502 Bad Gateway
- Health check

Version: 1.0
Date: 2025-01-08
"""

import asyncio
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class DeepSeekHttpClient:
    """
    Client HTTP pour DeepSeek/Ollama avec retry logic et multi-endpoint support.

    Supporte:
    - Ollama native API: /api/chat
    - OpenAI-compatible API: /v1/chat/completions
    - Retry avec backoff exponentiel
    - Timeouts progressifs (120s → 240s → 360s)
    - Gestion erreurs HTTP (5xx, timeouts)
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.6,
        max_tokens: int = 8192,
        max_retries: int = 3,
        system_prompt: Optional[str] = None
    ):
        """
        Initialise le client HTTP.

        Args:
            base_url: URL de base (ex: "http://localhost:11434")
            model: Nom du modèle (ex: "deepseek-v3.1:671b-cloud")
            temperature: Température de génération (0.0-1.0)
            max_tokens: Nombre maximum de tokens générés
            max_retries: Nombre max de tentatives
            system_prompt: Prompt système par défaut
        """
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.system_prompt = system_prompt

        # Endpoints à tenter (dans l'ordre)
        self.endpoints = [
            f"{self.base_url}/api/chat",           # Ollama native
            f"{self.base_url}/v1/chat/completions", # OpenAI-compatible
        ]

    async def call_with_retry(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Appelle le modèle avec retry logic.

        Args:
            user_prompt: Prompt utilisateur
            system_prompt: Prompt système (override l'instance si fourni)

        Returns:
            Réponse générée par le modèle

        Raises:
            RuntimeError: Si toutes les tentatives échouent
        """
        system = system_prompt or self.system_prompt or ""
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            for idx, endpoint in enumerate(self.endpoints):
                is_openai = endpoint.endswith("/v1/chat/completions")

                try:
                    # Timeout progressif (augmenté pour modèles cloud)
                    # Base: 180s, puis 360s, puis 540s
                    base_timeout = 180
                    timeout_seconds = base_timeout * attempt
                    timeout = httpx.Timeout(
                        connect=60.0,
                        read=float(timeout_seconds),
                        write=60.0,
                        pool=60.0
                    )

                    payload = self._build_payload(
                        user_prompt=user_prompt,
                        system_prompt=system,
                        is_openai=is_openai
                    )

                    logger.debug(
                        f"➡️ POST {endpoint} (try {attempt}/{self.max_retries})"
                    )

                    async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
                        r = await client.post(endpoint, json=payload)

                        # Gestion erreurs serveur
                        if r.status_code >= 500:
                            raise RuntimeError(
                                f"Upstream {r.status_code}: {r.text}"
                            )

                        # Si /api/chat absent, fallback OpenAI-like
                        if r.status_code == 404 and idx == 0:
                            logger.info(
                                "ℹ️ Endpoint /api/chat introuvable, "
                                "essai OpenAI-like..."
                            )
                            continue

                        r.raise_for_status()

                        data = r.json()
                        content = self._extract_content(data, is_openai)

                        if not content.strip():
                            raise RuntimeError("Réponse DeepSeek vide")

                        logger.debug(
                            f"✅ Réponse IA reçue ({len(content)} chars)"
                        )
                        return content

                except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                    last_error = e
                    logger.warning(
                        f"⏳ Timeout (tentative {attempt}) sur {endpoint}: {e}"
                    )

                except httpx.HTTPError as e:
                    last_error = e
                    code = getattr(e.response, "status_code", "N/A")
                    body = getattr(e.response, "text", "")
                    logger.error(
                        f"❌ HTTPError {code} sur {endpoint}: {body[:500]}"
                    )

                except Exception as e:
                    last_error = e
                    logger.error(
                        f"❌ Exception appel IA ({type(e).__name__}): {e}"
                    )

            # Backoff exponentiel entre les tentatives
            await asyncio.sleep(min(2 ** attempt, 10))

        raise RuntimeError(
            f"Échec appel DeepSeek après {self.max_retries} tentatives: "
            f"{last_error}"
        )

    def _build_payload(
        self,
        user_prompt: str,
        system_prompt: str,
        is_openai: bool
    ) -> Dict[str, Any]:
        """
        Construit le payload JSON selon le type d'endpoint.

        Args:
            user_prompt: Prompt utilisateur
            system_prompt: Prompt système
            is_openai: True si endpoint OpenAI-compatible

        Returns:
            Payload JSON
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if not is_openai:
            # Ollama /api/chat
            return {
                "model": self.model,
                "messages": messages,
                "format": "json",
                "stream": False,
                "keep_alive": "5m",
                "options": {
                    "temperature": self.temperature,
                    "top_p": 0.9,
                    "num_predict": self.max_tokens,
                    "repeat_penalty": 1.1,
                },
            }

        # OpenAI-compatible /v1/chat/completions
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": 0.9,
            "stream": False,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

    def _extract_content(
        self,
        response_json: Dict[str, Any],
        is_openai: bool
    ) -> str:
        """
        Extrait le contenu de la réponse selon le format.

        Args:
            response_json: Réponse JSON du serveur
            is_openai: True si format OpenAI

        Returns:
            Contenu généré
        """
        if not is_openai:
            # Ollama /api/chat -> {"message": {"content": "..."}}
            return response_json.get("message", {}).get("content", "")

        # OpenAI-like -> {"choices":[{"message":{"content":"..."}}]}
        choices = response_json.get("choices") or []
        if choices and "message" in choices[0]:
            return choices[0]["message"].get("content", "")

        # Fallback : certains serveurs renvoient directement "content"
        return response_json.get("content", "")

    async def health_check(self) -> Dict[str, Any]:
        """
        Vérifie la disponibilité du service.

        Returns:
            Statut du service
        """
        for endpoint in self.endpoints:
            try:
                # Tenter un appel minimal
                timeout = httpx.Timeout(connect=5.0, read=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    # Pour Ollama: GET /api/tags liste les modèles
                    health_url = f"{self.base_url}/api/tags"
                    r = await client.get(health_url)
                    r.raise_for_status()

                    return {
                        "status": "ok",
                        "endpoint": endpoint,
                        "model": self.model,
                        "available": True
                    }

            except Exception as e:
                logger.warning(f"Health check failed on {endpoint}: {e}")
                continue

        return {
            "status": "error",
            "endpoint": None,
            "model": self.model,
            "available": False,
            "error": "All endpoints unreachable"
        }
