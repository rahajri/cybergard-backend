"""
Security utilities shared across the backend (password hashing, activation tokens).
"""
from __future__ import annotations

import bcrypt
import logging
import secrets
from datetime import datetime


logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """
    Hash a password with bcrypt (72 bytes max).

    Args:
        password: plain text value.
    """
    if not password:
        raise ValueError("Le mot de passe ne peut pas être vide")

    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        logger.warning(
            "Password trop long (%s bytes), tronqué à 72 bytes pour compatibilité bcrypt",
            len(password_bytes),
        )
        password_bytes = password_bytes[:72]

    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the provided password matches the stored hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Erreur lors de la vérification du mot de passe: %s", exc)
        return False


def create_activation_token(identifier: str | None = None) -> str:
    """
    Generate a secure activation token (URL-safe) and log its creation.

    Args:
        identifier: optional email/user reference for debugging.
    """
    token = secrets.token_urlsafe(48)
    if identifier:
        logger.debug(
            "Token d'activation généré pour %s à %s",
            identifier,
            datetime.utcnow().isoformat(),
        )
    return token
