"""
Service d'intégration Keycloak pour CyberGuard Pro
Gère l'authentification, la validation des tokens et la synchronisation des utilisateurs
"""

import httpx
import jwt
from jwt import InvalidTokenError, ExpiredSignatureError, InvalidAudienceError, PyJWKClient
from jwt.exceptions import PyJWKClientError

import json
import base64
from urllib.request import urlopen

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from functools import lru_cache
import logging

from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from src.config import settings

logger = logging.getLogger(__name__)


# Fonction utilitaire pour décoder le base64url
def _b64url_decode(s: str) -> bytes:
    """Décode une chaîne base64url (utilisée dans les tokens JWT)"""
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


class KeycloakService:
    """Service pour interagir avec Keycloak"""
    def __init__(
        self,
        server_url: str,
        realm: str,
        client_id: str,
        client_secret: Optional[str] = None,
        admin_username: Optional[str] = None,
        admin_password: Optional[str] = None
    ):
        """
        Initialise le service Keycloak

        Args:
            server_url: URL du serveur Keycloak (ex: http://localhost:8080)
            realm: Nom du realm (ex: cyberguard)
            client_id: ID du client backend
            client_secret: Secret du client (optionnel pour clients publics)
            admin_username: Username admin pour admin-cli (optionnel)
            admin_password: Password admin pour admin-cli (optionnel)
        """
        self.server_url = server_url.rstrip('/')
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.admin_username = admin_username
        self.admin_password = admin_password

        # URLs importantes
        self.realm_url = f"{self.server_url}/realms/{self.realm}"
        self.admin_url = f"{self.server_url}/admin/realms/{self.realm}"
        self.token_url = f"{self.realm_url}/protocol/openid-connect/token"
        self.userinfo_url = f"{self.realm_url}/protocol/openid-connect/userinfo"
        self.jwks_url = f"{self.realm_url}/protocol/openid-connect/certs"
        self.logout_url = f"{self.realm_url}/protocol/openid-connect/logout"

        # Client pour valider les tokens JWT avec les clés publiques
        self.jwks_client = PyJWKClient(self.jwks_url)

        logger.info(f"✅ KeycloakService initialisé - Realm: {realm}, URL: {server_url}")

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Récupère les informations de l'utilisateur depuis Keycloak

        Args:
            access_token: Token d'accès valide

        Returns:
            Dictionnaire avec les informations de l'utilisateur
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de la récupération des infos utilisateur: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Impossible de récupérer les informations utilisateur"
            )

    async def exchange_code_for_token(
        self,
        code: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        grant_type: str = "authorization_code"
    ) -> Dict[str, Any]:
        """
        Échange un code d'autorisation contre des tokens OU obtient un token via password grant

        Args:
            code: Code d'autorisation reçu de Keycloak (pour grant_type=authorization_code)
            redirect_uri: URI de redirection (pour grant_type=authorization_code)
            username: Nom d'utilisateur (pour grant_type=password)
            password: Mot de passe (pour grant_type=password)
            grant_type: Type de grant ("authorization_code" ou "password")

        Returns:
            Dictionnaire contenant access_token, refresh_token, etc.
        """
        try:
            data = {
                "grant_type": grant_type,
                "client_id": self.client_id,
            }

            if grant_type == "authorization_code":
                if not code or not redirect_uri:
                    raise ValueError("code et redirect_uri sont requis pour authorization_code")
                data["code"] = code
                data["redirect_uri"] = redirect_uri

            elif grant_type == "password":
                if not username or not password:
                    raise ValueError("username et password sont requis pour password grant")
                data["username"] = username
                data["password"] = password

            if self.client_secret:
                data["client_secret"] = self.client_secret

            async with httpx.AsyncClient() as client:
                response = await client.post(self.token_url, data=data)
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            error_body = e.response.text if hasattr(e.response, 'text') else str(e)
            logger.error(f"❌ Erreur lors de l'obtention du token ({grant_type}): {e}")
            logger.error(f"   Status: {e.response.status_code}, Body: {error_body}")
            logger.error(f"   URL: {self.token_url}, Client: {self.client_id}")
            logger.error(f"   Username: {data.get('username', 'N/A')}")

            if e.response.status_code == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Identifiants invalides - {error_body}"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Erreur lors de l'authentification ({grant_type})"
            )
        except ValueError as e:
            logger.error(f"❌ Paramètres invalides: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Rafraîchit un token d'accès expiré

        Args:
            refresh_token: Token de rafraîchissement

        Returns:
            Nouveau access_token et refresh_token
        """
        try:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
            }

            if self.client_secret:
                data["client_secret"] = self.client_secret

            async with httpx.AsyncClient() as client:
                response = await client.post(self.token_url, data=data)
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors du rafraîchissement du token: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de rafraîchissement invalide"
            )

    async def logout(self, refresh_token: str) -> bool:
        """
        Déconnecte un utilisateur en révoquant son refresh token

        Args:
            refresh_token: Token de rafraîchissement à révoquer

        Returns:
            True si succès
        """
        try:
            data = {
                "client_id": self.client_id,
                "refresh_token": refresh_token,
            }

            if self.client_secret:
                data["client_secret"] = self.client_secret

            async with httpx.AsyncClient() as client:
                response = await client.post(self.logout_url, data=data)
                response.raise_for_status()
                logger.info("✅ Déconnexion réussie")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de la déconnexion: {e}")
            return False

    @staticmethod
    def _parse_unverified(token: str):
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Le token n'a pas le format JWT (3 segments).")
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        return header, payload

    async def verify_token(self, token: str) -> dict:
        # 0) Nettoyage éventuel
        if token.startswith("Bearer "):
            token = token[len("Bearer "):].strip()

        # 1) Inspection non vérifiée (log utile)
        try:
            hdr, pl = self._parse_unverified(token)
            kid = hdr.get("kid")
            alg = hdr.get("alg")
            iss = pl.get("iss")
            logger.debug(f"🔎 JWT header: alg={alg}, kid={kid}; iss={iss}")
        except Exception as e:
            logger.error(f"❌ Token illisible: {e}")
            raise HTTPException(status_code=401, detail="Token invalide")

        try:
            # 2) Si kid présent → voie standard
            if hdr.get("kid"):
                signing_key = self.jwks_client.get_signing_key_from_jwt(token)
                return jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    options={"verify_signature": True, "verify_exp": True, "verify_aud": False},
                    leeway=10  # Tolérance de 10 secondes pour les décalages d'horloge
                )

            # 3) Fallback si kid manquant → tester les clés de la JWKS
            # Récupère la JWKS et essaie chaque clé
            jwks_url = self.jwks_client.uri  # si dispo, sinon reconstruis à partir de ta config
            jwks = json.load(urlopen(jwks_url))
            keys = jwks.get("keys", [])
            if not keys:
                raise InvalidTokenError("Aucune clé dans la JWKS")

            last_err = None
            for jwk in keys:
                try:
                    key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
                    return jwt.decode(
                        token,
                        key,
                        algorithms=["RS256"],
                        options={"verify_signature": True, "verify_exp": True, "verify_aud": False},
                        leeway=10  # Tolérance de 10 secondes pour les décalages d'horloge
                    )
                except Exception as e:
                    last_err = e
                    continue

            # si aucune clé n'a marché
            raise InvalidTokenError(f"Impossible de vérifier le token sans kid (dernière erreur: {last_err})")

        except ExpiredSignatureError:
            logger.warning("❌ Token expiré")
            raise HTTPException(status_code=401, detail="Token expiré")
        except InvalidAudienceError:
            logger.warning("❌ Audience invalide")
            raise HTTPException(status_code=401, detail="Token invalide (audience)")
        except (InvalidTokenError, PyJWKClientError) as e:
            logger.error(f"❌ Erreur validation JWT: {e}")
            raise HTTPException(status_code=401, detail="Token invalide")
        except Exception as e:
            logger.error(f"❌ Erreur inattendue: {e}")
            raise HTTPException(status_code=500, detail="Erreur lors de la validation du token")


    def extract_user_claims(self, token_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extrait les informations utilisateur pertinentes du token

        Args:
            token_payload: Payload du token JWT décodé

        Returns:
            Dictionnaire avec les claims utilisateur normalisés
        """
        email = token_payload.get("email")

        # Pour les utilisateurs Magic Link, extraire le vrai email depuis les attributs
        if email and email.endswith("@temp.cybergard.local"):
            # Le vrai email est stocké dans les attributs du token
            real_email = token_payload.get("real_email")
            if isinstance(real_email, list) and len(real_email) > 0:
                email = real_email[0]
            elif real_email:
                email = real_email
            logger.debug(f"🔗 Magic Link: email Keycloak={token_payload.get('email')} → vrai email={email}")

        # Récupérer TOUS les rôles (realm + client)
        realm_roles = token_payload.get("realm_access", {}).get("roles", [])

        # Récupérer les client roles depuis resource_access
        client_roles = []
        resource_access = token_payload.get("resource_access", {})
        for client_id, client_data in resource_access.items():
            client_roles.extend(client_data.get("roles", []))

        # Combiner tous les rôles
        all_roles = list(set(realm_roles + client_roles))

        # Logger pour diagnostic
        logger.debug(f"🔑 Token roles - Realm: {realm_roles}, Client: {client_roles}, Combined: {all_roles}")

        return {
            "keycloak_id": token_payload.get("sub"),
            "email": email,
            "email_verified": token_payload.get("email_verified", False),
            "first_name": token_payload.get("given_name"),
            "last_name": token_payload.get("family_name"),
            "username": token_payload.get("preferred_username"),
            "roles": all_roles,  # Utiliser TOUS les rôles (realm + client)
            "tenant_id": token_payload.get("tenant_id"),
            "organization_id": token_payload.get("organization_id"),
            "groups": token_payload.get("groups", []),
        }

    async def create_user(
        self,
        admin_token: str,
        user_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        Crée un utilisateur dans Keycloak (nécessite un token admin)

        Args:
            admin_token: Token d'administration
            user_data: Données de l'utilisateur à créer

        Returns:
            ID de l'utilisateur créé ou None en cas d'erreur
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.admin_url}/users",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json=user_data
                )
                response.raise_for_status()

                # L'ID est dans le header Location
                location = response.headers.get("Location")
                if location:
                    user_id = location.split("/")[-1]
                    logger.info(f"✅ Utilisateur créé dans Keycloak: {user_id}")
                    return user_id

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de la création de l'utilisateur: {e}")
            logger.error(f"   Response: {e.response.text}")
            return None

    async def assign_role_to_user(
        self,
        admin_token: str,
        user_id: str,
        role_name: str
    ) -> bool:
        """
        Assigne un realm role à un utilisateur dans Keycloak.

        Args:
            admin_token: Token d'administration
            user_id: ID Keycloak de l'utilisateur
            role_name: Nom du rôle à assigner (ex: 'auditeur', 'super_admin')

        Returns:
            True si succès, False sinon
        """
        try:
            async with httpx.AsyncClient() as client:
                # 1. Récupérer le rôle par son nom
                role_response = await client.get(
                    f"{self.admin_url}/roles/{role_name}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                role_response.raise_for_status()
                role_data = role_response.json()

                # 2. Assigner le rôle à l'utilisateur
                assign_response = await client.post(
                    f"{self.admin_url}/users/{user_id}/role-mappings/realm",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json=[role_data]  # L'API attend un array de rôles
                )
                assign_response.raise_for_status()
                logger.info(f"✅ Rôle '{role_name}' assigné à l'utilisateur {user_id}")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de l'assignation du rôle '{role_name}': {e}")
            if e.response.status_code == 404:
                logger.error(f"   Le rôle '{role_name}' n'existe pas dans Keycloak")
            else:
                logger.error(f"   Response: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"❌ Erreur inattendue lors de l'assignation du rôle: {e}")
            return False

    async def update_user_attributes(
        self,
        admin_token: str,
        user_id: str,
        attributes: Dict[str, List[str]]
    ) -> bool:
        """
        Met à jour les attributs d'un utilisateur (tenant_id, organization_id, etc.)

        Args:
            admin_token: Token d'administration
            user_id: ID Keycloak de l'utilisateur
            attributes: Dictionnaire d'attributs (valeurs doivent être des listes)

        Returns:
            True si succès
        """
        try:
            async with httpx.AsyncClient() as client:
                # Récupérer l'utilisateur actuel
                get_response = await client.get(
                    f"{self.admin_url}/users/{user_id}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                get_response.raise_for_status()
                user = get_response.json()

                # Mettre à jour les attributs
                if "attributes" not in user:
                    user["attributes"] = {}

                user["attributes"].update(attributes)

                # Sauvegarder
                put_response = await client.put(
                    f"{self.admin_url}/users/{user_id}",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json=user
                )
                put_response.raise_for_status()
                logger.info(f"✅ Attributs mis à jour pour l'utilisateur {user_id}")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de la mise à jour des attributs: {e}")
            return False

    async def get_admin_token(self) -> Optional[str]:
        """
        Obtient un token d'administration via le service account ou admin credentials

        Returns:
            Token d'administration ou None
        """
        try:
            # Méthode 1: Utiliser les credentials admin (admin-cli) - Préféré
            if self.admin_username and self.admin_password:
                logger.info("🔑 Utilisation des credentials admin (admin-cli) pour obtenir le token")
                data = {
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": self.admin_username,
                    "password": self.admin_password,
                }

                # Utiliser le realm master pour l'authentification admin
                master_token_url = f"{self.server_url}/realms/master/protocol/openid-connect/token"

                async with httpx.AsyncClient() as client:
                    response = await client.post(master_token_url, data=data)
                    response.raise_for_status()
                    token_data = response.json()
                    logger.info("✅ Token admin obtenu avec succès via admin-cli")
                    return token_data["access_token"]

            # Méthode 2: Fallback sur client_credentials si pas de credentials admin
            elif self.client_secret:
                logger.info("🔑 Utilisation de client_credentials pour obtenir le token")
                data = {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }

                async with httpx.AsyncClient() as client:
                    response = await client.post(self.token_url, data=data)
                    response.raise_for_status()
                    token_data = response.json()
                    logger.info("✅ Token admin obtenu avec succès via client_credentials")
                    return token_data["access_token"]

            else:
                logger.error("❌ Ni credentials admin ni client secret disponibles")
                return None

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de l'obtention du token admin: {e.response.text if hasattr(e, 'response') else e}")
            return None
        except Exception as e:
            logger.error(f"❌ Erreur inattendue lors de l'obtention du token admin: {e}")
            return None

    async def get_user_by_email(
        self,
        admin_token: str,
        email: str
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère un utilisateur Keycloak par son email

        Args:
            admin_token: Token d'administration
            email: Email de l'utilisateur

        Returns:
            Données de l'utilisateur ou None
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.admin_url}/users",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    params={"email": email, "exact": "true"}
                )
                response.raise_for_status()
                users = response.json()

                if users and len(users) > 0:
                    logger.info(f"✅ Utilisateur trouvé: {email}")
                    return users[0]

                logger.warning(f"⚠️ Utilisateur non trouvé: {email}")
                return None

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de la recherche de l'utilisateur: {e}")
            return None

    async def set_user_password(
        self,
        admin_token: str,
        user_id: str,
        password: str,
        temporary: bool = False
    ) -> bool:
        """
        Définit le mot de passe d'un utilisateur

        Args:
            admin_token: Token d'administration
            user_id: ID Keycloak de l'utilisateur
            password: Nouveau mot de passe
            temporary: Si True, l'utilisateur devra changer son mot de passe à la prochaine connexion

        Returns:
            True si succès
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"{self.admin_url}/users/{user_id}/reset-password",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "type": "password",
                        "value": password,
                        "temporary": temporary
                    }
                )
                response.raise_for_status()
                logger.info(f"✅ Mot de passe défini pour l'utilisateur {user_id}")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de la définition du mot de passe: {e}")
            logger.error(f"   Response: {e.response.text}")
            return False

    async def verify_user_email(
        self,
        admin_token: str,
        user_id: str
    ) -> bool:
        """
        Marque l'email d'un utilisateur comme vérifié

        Args:
            admin_token: Token d'administration
            user_id: ID Keycloak de l'utilisateur

        Returns:
            True si succès
        """
        try:
            async with httpx.AsyncClient() as client:
                # Récupérer l'utilisateur actuel
                get_response = await client.get(
                    f"{self.admin_url}/users/{user_id}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                get_response.raise_for_status()
                user = get_response.json()

                # Mettre à jour emailVerified
                user["emailVerified"] = True

                # Sauvegarder
                put_response = await client.put(
                    f"{self.admin_url}/users/{user_id}",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json=user
                )
                put_response.raise_for_status()
                logger.info(f"✅ Email vérifié pour l'utilisateur {user_id}")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de la vérification de l'email: {e}")
            return False

    async def enable_user(
        self,
        admin_token: str,
        user_id: str
    ) -> bool:
        """
        Active un utilisateur dans Keycloak

        Args:
            admin_token: Token d'administration
            user_id: ID Keycloak de l'utilisateur

        Returns:
            True si succès
        """
        try:
            async with httpx.AsyncClient() as client:
                # Récupérer l'utilisateur actuel
                get_response = await client.get(
                    f"{self.admin_url}/users/{user_id}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )
                get_response.raise_for_status()
                user = get_response.json()

                # Activer l'utilisateur
                user["enabled"] = True

                # Sauvegarder
                put_response = await client.put(
                    f"{self.admin_url}/users/{user_id}",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json=user
                )
                put_response.raise_for_status()
                logger.info(f"✅ Utilisateur activé: {user_id}")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erreur lors de l'activation de l'utilisateur: {e}")
            return False


# ============================================================================
# INSTANCE GLOBALE DU SERVICE
# ============================================================================

_keycloak_service: Optional[KeycloakService] = None


def init_keycloak_service(force: bool = False) -> KeycloakService:
    """
    Initialise le service Keycloak avec la configuration depuis les settings

    Args:
        force: Force la réinitialisation même si le service existe déjà

    Returns:
        Instance de KeycloakService
    """
    global _keycloak_service

    if _keycloak_service is None or force:
        # Récupérer la configuration depuis les variables d'environnement
        # IMPORTANT: Utiliser les noms Python (snake_case), pas les alias (UPPER_CASE)
        keycloak_url = settings.keycloak_server_url
        keycloak_realm = settings.keycloak_realm_name
        client_id = settings.keycloak_client_id
        client_secret = settings.keycloak_client_secret
        admin_username = settings.keycloak_admin_username
        admin_password = settings.keycloak_admin_password

        logger.info(f"🔧 Initialisation KeycloakService (force={force})")
        logger.info(f"   - Server: {keycloak_url}")
        logger.info(f"   - Realm: {keycloak_realm}")
        logger.info(f"   - Client: {client_id}")
        logger.info(f"   - Admin user: {admin_username if admin_username else 'Non configuré'}")

        _keycloak_service = KeycloakService(
            server_url=keycloak_url,
            realm=keycloak_realm,
            client_id=client_id,
            client_secret=client_secret,
            admin_username=admin_username,
            admin_password=admin_password
        )

    return _keycloak_service


def get_keycloak_service() -> KeycloakService:
    """
    Retourne l'instance globale du service Keycloak

    Returns:
        Instance de KeycloakService

    Raises:
        RuntimeError: Si le service n'est pas initialisé
    """
    if _keycloak_service is None:
        raise RuntimeError(
            "KeycloakService non initialisé. "
            "Appelez init_keycloak_service() au démarrage de l'application."
        )
    return _keycloak_service
