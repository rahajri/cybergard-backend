"""
API endpoints pour l'activation de compte avec Keycloak
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr, validator
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging
import re

from src.database import get_db
from src.services.keycloak_service import get_keycloak_service
from src.services.email_service import send_activation_confirmation_email
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["activation"])


# ============================================================================
# MODÈLES PYDANTIC
# ============================================================================

class ActivateAccountRequest(BaseModel):
    """Requête d'activation de compte"""
    token: str
    password: str

    @validator('password')
    def validate_password(cls, v):
        """
        Valide la complexité du mot de passe
        - Minimum 12 caractères
        - Au moins une majuscule
        - Au moins une minuscule
        - Au moins un chiffre
        - Au moins un caractère spécial
        """
        if len(v) < 12:
            raise ValueError('Le mot de passe doit contenir au moins 12 caractères')

        if not re.search(r'[A-Z]', v):
            raise ValueError('Le mot de passe doit contenir au moins une lettre majuscule')

        if not re.search(r'[a-z]', v):
            raise ValueError('Le mot de passe doit contenir au moins une lettre minuscule')

        if not re.search(r'[0-9]', v):
            raise ValueError('Le mot de passe doit contenir au moins un chiffre')

        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]', v):
            raise ValueError('Le mot de passe doit contenir au moins un caractère spécial')

        return v


class ActivateAccountResponse(BaseModel):
    """Réponse après activation"""
    success: bool
    message: str
    email: str


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/activate", response_model=ActivateAccountResponse)
async def activate_account(
    request: ActivateAccountRequest,
    db: Session = Depends(get_db)
):
    """
    Active un compte utilisateur en définissant son mot de passe dans Keycloak

    Flow:
    1. Vérifier le token d'activation dans la BDD
    2. Récupérer l'utilisateur depuis la BDD
    3. Obtenir un token admin Keycloak
    4. Trouver ou créer l'utilisateur dans Keycloak par email
    5. Définir le mot de passe dans Keycloak
    6. Vérifier l'email dans Keycloak
    7. Activer l'utilisateur dans Keycloak
    8. Marquer l'utilisateur comme actif dans la BDD
    9. Invalider le token d'activation
    """
    try:
        logger.info(f"🔐 Tentative d'activation avec token: {request.token[:20]}...")

        # ========================================================================
        # 1. Vérifier le token d'activation dans la BDD
        # ========================================================================

        # Vérifier que le token existe et n'a pas expiré
        result = db.execute(
            text("""
                SELECT u.id, u.email, u.first_name, u.last_name, at.is_used, at.expires_at
                FROM users u
                JOIN activation_tokens at ON u.id = at.user_id
                WHERE at.token = :token
            """),
            {"token": request.token}
        ).first()

        if not result:
            logger.warning("❌ Token d'activation invalide")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token d'activation invalide ou expiré"
            )

        user_id, email, first_name, last_name, is_used, expires_at = result

        # Vérifier si le token a déjà été utilisé
        if is_used:
            logger.warning(f"❌ Token déjà utilisé pour {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ce lien d'activation a déjà été utilisé"
            )

        # Vérifier si le token a expiré (si expires_at est défini)
        if expires_at:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            if expires_at.replace(tzinfo=timezone.utc) < now:
                logger.warning(f"❌ Token expiré pour {email}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ce lien d'activation a expiré. Veuillez demander un nouveau lien."
                )

        logger.info(f"✅ Token valide pour l'utilisateur: {email}")

        # ========================================================================
        # 2. Interagir avec Keycloak
        # ========================================================================

        keycloak_service = get_keycloak_service()

        # 3. Obtenir un token admin
        admin_token = await keycloak_service.get_admin_token()
        if not admin_token:
            logger.error("❌ Impossible d'obtenir un token admin Keycloak")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors de la communication avec le service d'authentification"
            )

        logger.info("✅ Token admin Keycloak obtenu")

        # 4. Trouver ou créer l'utilisateur dans Keycloak
        keycloak_user = await keycloak_service.get_user_by_email(admin_token, email)

        if not keycloak_user:
            # L'utilisateur n'existe pas dans Keycloak, on le crée
            logger.info(f"👤 Utilisateur non trouvé dans Keycloak, création en cours: {email}")

            user_data = {
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": False,  # Désactivé par défaut, sera activé après définition du mot de passe
                "emailVerified": False,
                "username": email  # Utiliser l'email comme username
            }

            keycloak_user_id = await keycloak_service.create_user(
                admin_token=admin_token,
                user_data=user_data
            )

            if not keycloak_user_id:
                logger.error(f"❌ Échec de la création de l'utilisateur dans Keycloak: {email}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Erreur lors de la création du compte dans le système d'authentification"
                )

            logger.info(f"✅ Utilisateur créé dans Keycloak: {keycloak_user_id}")
        else:
            keycloak_user_id = keycloak_user["id"]
            logger.info(f"✅ Utilisateur trouvé dans Keycloak: {keycloak_user_id}")

        # 5. Définir le mot de passe
        password_set = await keycloak_service.set_user_password(
            admin_token=admin_token,
            user_id=keycloak_user_id,
            password=request.password,
            temporary=False
        )

        if not password_set:
            logger.error(f"❌ Échec de la définition du mot de passe pour {email}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors de la définition du mot de passe"
            )

        logger.info(f"✅ Mot de passe défini pour {email}")

        # 6. Vérifier l'email
        email_verified = await keycloak_service.verify_user_email(
            admin_token=admin_token,
            user_id=keycloak_user_id
        )

        if not email_verified:
            logger.warning(f"⚠️ Échec de la vérification de l'email pour {email}")
            # Ce n'est pas bloquant, on continue

        # 7. Activer l'utilisateur dans Keycloak
        user_enabled = await keycloak_service.enable_user(
            admin_token=admin_token,
            user_id=keycloak_user_id
        )

        if not user_enabled:
            logger.error(f"❌ Échec de l'activation de l'utilisateur dans Keycloak: {email}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors de l'activation du compte"
            )

        logger.info(f"✅ Utilisateur activé dans Keycloak: {email}")

        # ========================================================================
        # 8. Mettre à jour la BDD locale
        # ========================================================================

        # Marquer l'utilisateur comme actif
        db.execute(
            text("""
                UPDATE users
                SET is_active = true, is_email_verified = true, updated_at = NOW()
                WHERE id = :user_id
            """),
            {"user_id": str(user_id)}
        )

        # 9. Invalider le token d'activation
        db.execute(
            text("""
                UPDATE activation_tokens
                SET is_used = true, used_at = NOW()
                WHERE token = :token
            """),
            {"token": request.token}
        )

        db.commit()

        logger.info(f"✅ ✅ ✅ Compte activé avec succès pour {email}")

        # ========================================================================
        # 10. Envoyer l'email de confirmation d'activation
        # ========================================================================
        try:
            # Récupérer le nom de l'organisation (tenant) de l'utilisateur
            org_result = db.execute(
                text("""
                    SELECT t.name
                    FROM users u
                    JOIN tenant t ON u.tenant_id = t.id
                    WHERE u.id = :user_id
                """),
                {"user_id": str(user_id)}
            ).first()

            organization_name = org_result[0] if org_result else "CYBERGARD AI"
            user_full_name = f"{first_name} {last_name}".strip() or email

            # URL de connexion
            frontend_url = settings.FRONTEND_URL if hasattr(settings, 'FRONTEND_URL') else "http://localhost:3000"
            login_url = f"{frontend_url}/login"

            # Envoyer l'email de confirmation
            send_activation_confirmation_email(
                to_email=email,
                user_name=user_full_name,
                login_url=login_url,
                organization_name=organization_name
            )

            logger.info(f"📧 Email de confirmation envoyé à {email}")

        except Exception as email_error:
            # L'échec de l'envoi d'email ne doit pas bloquer l'activation
            logger.warning(f"⚠️ Échec envoi email de confirmation à {email}: {email_error}")

        return ActivateAccountResponse(
            success=True,
            message="Votre compte a été activé avec succès ! Vous pouvez maintenant vous connecter.",
            email=email
        )

    except HTTPException:
        # Re-raise les HTTPExceptions
        raise

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Erreur inattendue lors de l'activation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Une erreur inattendue s'est produite lors de l'activation du compte"
        )
