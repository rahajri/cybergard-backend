"""
Endpoints d'authentification via Keycloak
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from src.database import get_db
from src.services.keycloak_service import get_keycloak_service, KeycloakService
from src.dependencies_keycloak import get_current_user_keycloak
from src.models.audit import User

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/keycloak", tags=["Keycloak Authentication"])


# ============================================================================
# SCHÉMAS PYDANTIC
# ============================================================================

class TokenExchangeRequest(BaseModel):
    """Schéma pour l'échange de code contre des tokens"""
    code: str
    redirect_uri: str = "http://localhost:3000/auth/callback"


class RefreshTokenRequest(BaseModel):
    """Schéma pour le rafraîchissement du token"""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Schéma pour la déconnexion"""
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    """Schéma pour le changement de mot de passe"""
    current_password: str
    new_password: str


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/login-url")
async def get_login_url(
    redirect_uri: str = "http://localhost:3000/auth/callback",
    keycloak: KeycloakService = Depends(get_keycloak_service)
):
    """
    Retourne l'URL de connexion Keycloak

    Le frontend doit rediriger l'utilisateur vers cette URL pour se connecter.

    Query params:
        redirect_uri: URI de redirection après connexion (doit être configurée dans Keycloak)

    Returns:
        URL de connexion Keycloak avec les paramètres appropriés
    """
    auth_url = (
        f"{keycloak.realm_url}/protocol/openid-connect/auth"
        f"?client_id={keycloak.client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=openid profile email"
        # PKCE pour plus de sécurité (optionnel mais recommandé)
        f"&code_challenge_method=S256"
    )

    return {
        "auth_url": auth_url,
        "realm": keycloak.realm,
        "client_id": keycloak.client_id
    }


@router.post("/token")
async def exchange_code_for_token(
    request: TokenExchangeRequest,
    response: Response,
    db: Session = Depends(get_db),
    keycloak: KeycloakService = Depends(get_keycloak_service)
):
    """
    Échange un code d'autorisation contre des tokens

    Le frontend appelle cet endpoint après que l'utilisateur se soit connecté
    et ait été redirigé avec un code.

    Body:
        code: Code d'autorisation reçu de Keycloak
        redirect_uri: URI de redirection (doit correspondre à celle utilisée pour la connexion)

    Returns:
        Tokens d'accès et de rafraîchissement + informations utilisateur
    """
    try:
        # 1. Échanger le code contre des tokens
        token_data = await keycloak.exchange_code_for_token(
            code=request.code,
            redirect_uri=request.redirect_uri
        )

        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]

        # 2. Valider le token et extraire les informations
        token_payload = await keycloak.verify_token(access_token)
        user_claims = keycloak.extract_user_claims(token_payload)

        # 3. Synchroniser l'utilisateur dans la base de données locale
        from sqlalchemy import select

        email = user_claims.get("email")
        keycloak_id = user_claims.get("keycloak_id")

        # Chercher l'utilisateur existant
        user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if user:
            # Mettre à jour le keycloak_id si nécessaire
            if not hasattr(user, 'keycloak_id') or user.keycloak_id != keycloak_id:
                try:
                    user.keycloak_id = keycloak_id
                    db.commit()
                except Exception:
                    db.rollback()
        else:
            # Créer un nouvel utilisateur
            from src.dependencies_keycloak import _create_user_from_keycloak
            user = await _create_user_from_keycloak(db, user_claims)

        # 4. Définir un cookie HTTP-only pour le refresh token (recommandé pour la sécurité)
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=False,  # True en production avec HTTPS
            samesite="lax",
            max_age=30 * 24 * 60 * 60  # 30 jours
        )

        logger.info(f"✅ Authentification Keycloak réussie: {email}")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": token_data.get("expires_in", 1800),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "firstName": user.first_name,
                "lastName": user.last_name,
                "emailVerified": user_claims.get("email_verified", False),
                "roles": user_claims.get("roles", []),
                "tenantId": user_claims.get("tenant_id"),
                "organizationId": user_claims.get("organization_id"),
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'échange du code: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'authentification: {str(e)}"
        )


@router.post("/refresh")
async def refresh_token(
    request: RefreshTokenRequest,
    response: Response,
    keycloak: KeycloakService = Depends(get_keycloak_service)
):
    """
    Rafraîchit un token d'accès expiré

    Body:
        refresh_token: Token de rafraîchissement

    Returns:
        Nouveaux tokens d'accès et de rafraîchissement
    """
    try:
        token_data = await keycloak.refresh_access_token(request.refresh_token)

        # Mettre à jour le cookie
        response.set_cookie(
            key="refresh_token",
            value=token_data["refresh_token"],
            httponly=True,
            secure=False,  # True en production
            samesite="lax",
            max_age=30 * 24 * 60 * 60
        )

        return {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "token_type": "bearer",
            "expires_in": token_data.get("expires_in", 1800)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors du rafraîchissement: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors du rafraîchissement du token"
        )


@router.post("/logout")
async def logout(
    request: LogoutRequest,
    response: Response,
    keycloak: KeycloakService = Depends(get_keycloak_service)
):
    """
    Déconnecte un utilisateur en révoquant son refresh token

    Body:
        refresh_token: Token de rafraîchissement à révoquer

    Returns:
        Confirmation de déconnexion
    """
    try:
        await keycloak.logout(request.refresh_token)

        # Supprimer le cookie
        response.delete_cookie(key="refresh_token")

        return {"message": "Déconnexion réussie"}

    except Exception as e:
        logger.error(f"❌ Erreur lors de la déconnexion: {e}")
        # Même en cas d'erreur, on supprime le cookie côté client
        response.delete_cookie(key="refresh_token")
        return {"message": "Déconnexion effectuée (avec avertissement)"}


@router.get("/me")
async def get_current_user_info(
    current_user = Depends(get_current_user_keycloak),
    db: Session = Depends(get_db)
):
    """
    Retourne les informations de l'utilisateur actuellement connecté

    Headers:
        Authorization: Bearer <token>

    Returns:
        Informations détaillées de l'utilisateur
    """
    from src.models.organization import Organization
    from sqlalchemy import text

    # Si c'est un utilisateur Magic Link (dict), retourner les claims directement
    if isinstance(current_user, dict):
        logger.info(f"🔗 Utilisateur Magic Link temporaire: {current_user.get('email')}")
        return {
            "id": None,
            "email": current_user.get("email"),
            "first_name": current_user.get("first_name", ""),
            "last_name": current_user.get("last_name", ""),
            "role": "audited",  # Rôle spécial pour les utilisateurs Magic Link
            "organization": None,
            "is_magic_link": True
        }

    # Récupérer l'organisation si elle existe
    organization = None
    if current_user.default_org_id:
        organization = db.get(Organization, current_user.default_org_id)

        # ✅ VÉRIFIER SI L'ORGANISATION EST ACTIVE
        if organization and not organization.is_active:
            logger.warning(f"❌ Tentative de connexion refusée - Organisation désactivée: {organization.name} ({organization.id})")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "organization_inactive",
                    "message": "Votre organisation a été désactivée. Veuillez contacter l'administrateur de la plateforme pour plus d'informations.",
                    "organization_name": organization.name
                }
            )

    # Mapping des rôles base de données vers les rôles frontend
    # IMPORTANT: Ce mapping doit être cohérent avec le frontend pour la redirection
    ROLE_MAPPING = {
        'PLATFORM_ADMIN': 'platform_admin',
        'SUPER_ADMIN': 'platform_admin',  # ✅ SUPER_ADMIN = admin de la plateforme
        'RSSI': 'client',
        'RSSI_EXTERNE': 'client',
        'DIR_CONFORMITE_DPO': 'client',
        'DPO_EXTERNE': 'client',
        'CHEF_PROJET': 'client',
        'AUDITEUR': 'auditor',
        'AUDITE_RESP': 'client',
        'AUDITE_CONTRIB': 'client',
    }

    # Récupérer le rôle de l'utilisateur depuis la table user_role
    # Utilise la relation ORM `current_user.roles` qui est déjà chargée (lazy="selectin")
    role = None
    db_role = None

    if current_user.roles and len(current_user.roles) > 0:
        # Prendre le premier rôle (en pratique, un utilisateur a généralement un seul rôle principal)
        db_role = current_user.roles[0].code  # Ex: "AUDITEUR", "SUPER_ADMIN", etc.
        # Mapper le rôle pour le frontend
        role = ROLE_MAPPING.get(db_role, 'client')
        logger.info(f"✅ Rôle récupéré depuis user_role: {db_role} → mappé vers: {role}")
    else:
        logger.warning(f"⚠️ Aucun rôle trouvé dans user_role pour {current_user.email}")

        # Fallback: Vérifier l'ancienne table user_organization_role (rétrocompatibilité)
        if current_user.default_org_id:
            role_result = db.execute(
                text("""
                    SELECT role, is_active
                    FROM user_organization_role
                    WHERE user_id = :user_id AND organization_id = :org_id
                """),
                {"user_id": str(current_user.id), "org_id": str(current_user.default_org_id)}
            ).first()

            if role_result and role_result[1]:  # Si le rôle existe et est actif
                db_role = role_result[0]
                role = ROLE_MAPPING.get(db_role, 'client')
                logger.info(f"✅ Rôle récupéré depuis user_organization_role (fallback): {db_role} → mappé vers: {role}")
            else:
                role = "client"  # Rôle par défaut
                logger.warning(f"⚠️ Aucun rôle trouvé, utilisation du rôle par défaut: {role}")
        else:
            role = "client"  # Rôle par défaut
            logger.warning(f"⚠️ Utilisateur {current_user.email} sans organisation, utilisation du rôle par défaut: {role}")

    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "firstName": current_user.first_name,
        "lastName": current_user.last_name,
        "role": role if role else "client",  # Retourner le rôle exact depuis la BDD
        "roles": [r.code for r in current_user.roles] if current_user.roles else [],  # Liste complète des rôles
        "emailVerified": current_user.email_verified if hasattr(current_user, 'email_verified') else False,
        "isActive": current_user.is_active,
        "tenantId": str(current_user.tenant_id) if current_user.tenant_id else None,
        "organizationId": str(current_user.default_org_id) if current_user.default_org_id else None,
        "organizationName": organization.name if organization else None,
        "keycloakId": current_user.keycloak_id if hasattr(current_user, 'keycloak_id') else None,
    }


@router.get("/me/permissions")
async def get_current_user_permissions(
    current_user = Depends(get_current_user_keycloak),
    db: Session = Depends(get_db)
):
    """
    Retourne les permissions de l'utilisateur actuellement connecté.

    Ce endpoint permet au frontend de :
    - Afficher/masquer des éléments UI selon les droits
    - Désactiver des boutons si l'utilisateur n'a pas la permission
    - Adapter l'interface sans re-déployer

    Architecture 3 couches :
    - La matrice de droits est gérée dans l'UI RBAC (DB)
    - Synchronisée vers Keycloak
    - Le token contient les permissions, le code ne décide pas

    Returns:
        Liste des permissions de l'utilisateur groupées par module
    """
    from sqlalchemy import text
    from src.dependencies_keycloak import SUPERUSER_ROLES

    # Si c'est un utilisateur Magic Link (dict), retourner permissions limitées
    if isinstance(current_user, dict):
        return {
            "permissions": ["AUDIT_READ", "QUESTIONNAIRE_READ"],
            "modules": {
                "audit": ["read"],
                "questionnaire": ["read"]
            },
            "is_super_admin": False,
            "is_magic_link": True
        }

    # Récupérer les rôles de l'utilisateur
    user_roles = [role.code for role in current_user.roles] if current_user.roles else []
    is_super_admin = any(role in SUPERUSER_ROLES for role in user_roles)

    logger.info(f"🔐 /me/permissions appelé pour {current_user.email} (ID: {current_user.id})")
    logger.info(f"   Rôles ORM: {user_roles}, is_super_admin: {is_super_admin}")

    # Les super-admins ont toutes les permissions
    if is_super_admin:
        all_perms_query = text("""
            SELECT code, module, action FROM permission ORDER BY module, action
        """)
        result = db.execute(all_perms_query).fetchall()

        permissions = [row.code for row in result]
        modules = {}
        for row in result:
            if row.module:
                if row.module not in modules:
                    modules[row.module] = []
                if row.action and row.action not in modules[row.module]:
                    modules[row.module].append(row.action)

        return {
            "permissions": permissions,
            "modules": modules,
            "is_super_admin": True,
            "is_magic_link": False,
            "roles": user_roles
        }

    # Pour les autres utilisateurs, récupérer via role_permission
    permission_query = text("""
        SELECT DISTINCT p.code, p.module, p.action
        FROM role_permission rp
        JOIN role r ON rp.role_id = r.id
        JOIN permission p ON rp.permission_id = p.id
        JOIN user_role ur ON ur.role_id = r.id
        WHERE ur.user_id = :user_id
        ORDER BY p.module, p.action
    """)

    logger.info(f"🔍 Récupération permissions pour user_id={current_user.id}, email={current_user.email}")
    result = db.execute(permission_query, {"user_id": str(current_user.id)}).fetchall()
    logger.info(f"📋 Permissions trouvées: {len(result)} - {[row.code for row in result]}")

    permissions = [row.code for row in result]
    modules = {}
    for row in result:
        if row.module:
            if row.module not in modules:
                modules[row.module] = []
            if row.action and row.action not in modules[row.module]:
                modules[row.module].append(row.action)

    return {
        "permissions": permissions,
        "modules": modules,
        "is_super_admin": False,
        "is_magic_link": False,
        "roles": user_roles
    }


@router.get("/config")
async def get_keycloak_config(
    keycloak: KeycloakService = Depends(get_keycloak_service)
):
    """
    Retourne la configuration publique de Keycloak pour le frontend

    Cette configuration est nécessaire pour que le frontend puisse
    initialiser le client Keycloak.

    Returns:
        Configuration Keycloak (URL, realm, client ID)
    """
    return {
        "url": keycloak.server_url,
        "realm": keycloak.realm,
        "clientId": keycloak.client_id,
        "authUrl": f"{keycloak.realm_url}/protocol/openid-connect/auth",
        "tokenUrl": f"{keycloak.realm_url}/protocol/openid-connect/token",
        "logoutUrl": f"{keycloak.realm_url}/protocol/openid-connect/logout",
    }


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user_keycloak),
    keycloak: KeycloakService = Depends(get_keycloak_service)
):
    """
    Change le mot de passe de l'utilisateur connecté via Keycloak

    Body:
        current_password: Mot de passe actuel
        new_password: Nouveau mot de passe

    Returns:
        Confirmation du changement

    Raises:
        HTTPException: Si le mot de passe actuel est incorrect ou si une erreur survient
    """
    try:
        # 1. Vérifier que l'utilisateur a un keycloak_id
        if not hasattr(current_user, 'keycloak_id') or not current_user.keycloak_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Utilisateur non lié à Keycloak"
            )

        # 2. Vérifier le mot de passe actuel en tentant de se connecter avec
        try:
            token_data = await keycloak.get_token_password(
                username=current_user.email,
                password=request.current_password
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Mot de passe actuel incorrect"
            )

        # 3. Obtenir un token admin pour changer le mot de passe
        admin_token = await keycloak.get_admin_token()

        # 4. Changer le mot de passe dans Keycloak
        success = await keycloak.set_user_password(
            admin_token=admin_token,
            user_id=current_user.keycloak_id,
            password=request.new_password,
            temporary=False  # Mot de passe permanent
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors du changement de mot de passe"
            )

        logger.info(f"✅ Mot de passe changé pour: {current_user.email}")

        return {
            "message": "Mot de passe changé avec succès",
            "success": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur lors du changement de mot de passe: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du changement de mot de passe: {str(e)}"
        )
