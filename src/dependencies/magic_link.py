"""
Dépendances FastAPI pour la validation des liens magiques
"""
from fastapi import Depends, HTTPException, status, Cookie, Request, Query
from sqlalchemy.orm import Session
from typing import Optional, Dict
import logging

from src.database import get_db
from src.services.magic_link_service import validate_magic_token

logger = logging.getLogger(__name__)


async def get_magic_token_from_request(
    request: Request,
    token: Optional[str] = Query(None, description="Token JWT du lien magique"),
    audit_token: Optional[str] = Cookie(None, description="Token JWT stocké dans un cookie")
) -> str:
    """
    Récupère le token magic link depuis la requête (query param ou cookie)

    Priority:
    1. Token dans le query parameter (?token=xxx)
    2. Token dans le cookie (audit_token)

    Args:
        request: Requête FastAPI
        token: Token dans le query parameter
        audit_token: Token dans le cookie

    Returns:
        str: Le token JWT

    Raises:
        HTTPException: Si aucun token n'est trouvé
    """

    # 1. Priorité au token dans l'URL (premier accès via lien)
    if token:
        logger.debug(f"🔗 Token trouvé dans query param")
        return token

    # 2. Sinon, chercher dans le cookie (visites suivantes)
    if audit_token:
        logger.debug(f"🍪 Token trouvé dans cookie")
        return audit_token

    # 3. Aucun token trouvé
    logger.warning("❌ Aucun token magic link trouvé (ni query param, ni cookie)")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Accès refusé. Veuillez utiliser le lien d'invitation envoyé par email."
    )


async def validate_magic_link(
    request: Request,
    token: str = Depends(get_magic_token_from_request),
    db: Session = Depends(get_db)
) -> Dict:
    """
    Valide un token de lien magique et retourne le payload décodé

    Args:
        request: Requête FastAPI (pour récupérer IP et User-Agent)
        token: Token JWT à valider
        db: Session de base de données

    Returns:
        Dict: Payload du token (email, campaign_id, questionnaire_id, tenant_id, etc.)

    Raises:
        HTTPException: Si le token est invalide, expiré ou révoqué
    """

    try:
        # Récupérer l'IP et le User-Agent
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # Valider le token
        payload = validate_magic_token(
            db=db,
            token=token,
            ip_address=client_ip,
            user_agent=user_agent
        )

        logger.info(
            f"✅ Accès magic link autorisé: {payload['sub']} - "
            f"Campaign: {payload['campaign_id']}"
        )

        return payload

    except ValueError as e:
        # Erreurs de validation du token
        error_msg = str(e)

        if "expiré" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Votre lien d'invitation a expiré. Veuillez demander un nouveau lien."
            )
        elif "révoqué" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ce lien a été révoqué. Veuillez contacter l'administrateur."
            )
        elif "nombre maximal" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Vous avez dépassé le nombre maximal d'utilisations de ce lien. Veuillez contacter l'administrateur."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Lien invalide : {error_msg}"
            )

    except Exception as e:
        logger.error(f"❌ Erreur validation magic link: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la validation du lien d'accès"
        )


def get_audit_email(magic_link_payload: Dict = Depends(validate_magic_link)) -> str:
    """
    Récupère l'email de l'audité depuis le payload du magic link

    Args:
        magic_link_payload: Payload du token validé

    Returns:
        str: Email de l'audité
    """
    return magic_link_payload.get("sub")


def get_campaign_id(magic_link_payload: Dict = Depends(validate_magic_link)) -> str:
    """
    Récupère l'ID de la campagne depuis le payload du magic link

    Args:
        magic_link_payload: Payload du token validé

    Returns:
        str: ID de la campagne
    """
    return magic_link_payload.get("campaign_id")


def get_tenant_id(magic_link_payload: Dict = Depends(validate_magic_link)) -> str:
    """
    Récupère l'ID du tenant depuis le payload du magic link

    Args:
        magic_link_payload: Payload du token validé

    Returns:
        str: ID du tenant
    """
    return magic_link_payload.get("tenant_id")


# Exemple d'utilisation dans une route :
"""
from fastapi import APIRouter, Depends
from src.dependencies.magic_link import validate_magic_link, get_audit_email

router = APIRouter()

@router.get("/audit/form/{campaign_id}")
async def access_audit_form(
    campaign_id: str,
    magic_link_payload: Dict = Depends(validate_magic_link),
    audited_email: str = Depends(get_audit_email)
):
    # L'utilisateur est authentifié via le magic link
    # On peut maintenant charger le questionnaire et les réponses
    return {
        "message": f"Bienvenue {audited_email}",
        "campaign_id": campaign_id,
        "payload": magic_link_payload
    }
"""
