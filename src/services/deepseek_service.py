"""
Service d'appel à DeepSeek pour génération de contenu IA.

Utilisé pour :
- Génération de questions d'audit
- Analyse de conformité
- Génération de plans d'action
"""

import httpx
import json
import logging
from typing import Dict, Any, Optional
import os

logger = logging.getLogger(__name__)


class DeepSeekService:
    """Service pour appels API DeepSeek."""

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat")

        if not self.api_key:
            logger.warning("⚠️ DEEPSEEK_API_KEY not configured - using fallback mode")

    async def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4000
    ) -> str:
        """
        Appel à DeepSeek Chat Completion API.

        Args:
            system_prompt: Prompt système (rôle, instructions)
            user_prompt: Prompt utilisateur (tâche spécifique)
            temperature: Créativité (0-1, défaut 0.7)
            max_tokens: Tokens max en réponse

        Returns:
            Réponse de l'IA (string)

        Raises:
            Exception si erreur API
        """
        if not self.api_key:
            raise ValueError("DeepSeek API key not configured")

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                logger.info(f"🤖 Appel DeepSeek ({self.model})...")
                logger.info(f"📝 System prompt length: {len(system_prompt)} chars")
                logger.info(f"📝 User prompt length: {len(user_prompt)} chars")
                logger.debug(f"📄 System prompt preview: {system_prompt[:200]}...")
                logger.debug(f"📄 User prompt preview: {user_prompt[:500]}...")

                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"}
                    }
                )

                response.raise_for_status()
                data = response.json()

                content = data["choices"][0]["message"]["content"]

                # Log usage
                usage = data.get("usage", {})
                logger.info(
                    f"✅ DeepSeek response received "
                    f"(tokens: {usage.get('total_tokens', 0)}, "
                    f"cost: ~${usage.get('total_tokens', 0) * 0.00001:.4f})"
                )
                logger.info(f"📊 Response length: {len(content)} chars")
                logger.debug(f"📄 Response preview: {content[:500]}...")

                return content

            except httpx.HTTPStatusError as e:
                logger.error(f"❌ DeepSeek API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"❌ DeepSeek call failed: {str(e)}")
                raise

    async def chat_completion_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4000
    ) -> Dict[str, Any]:
        """
        Appel DeepSeek avec parsing JSON automatique.

        Returns:
            Dict parsé depuis la réponse JSON

        Raises:
            ValueError si réponse n'est pas un JSON valide
        """
        response_text = await self.chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens
        )

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON from DeepSeek: {response_text[:500]}")
            raise ValueError(f"DeepSeek returned invalid JSON: {str(e)}")
