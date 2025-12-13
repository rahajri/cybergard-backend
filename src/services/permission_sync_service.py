"""
Service de synchronisation des permissions vers Keycloak

Ce service synchronise la matrice de droits (role_permission en BDD) vers Keycloak.
Il crée/met à jour les client roles dans Keycloak pour chaque permission.

Architecture :
1. Matrice de droits (DB) = Référentiel fonctionnel
2. Keycloak = Source technique d'autorisation (tokens avec rôles)
3. Application = Simple consommateur des droits du token

Usage:
    from src.services.permission_sync_service import PermissionSyncService

    sync_service = PermissionSyncService(keycloak_service)
    await sync_service.sync_role_permissions(role_code="CHEF_PROJET")
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import UUID
import httpx

from sqlalchemy.orm import Session
from sqlalchemy import text

from src.services.keycloak_service import KeycloakService

logger = logging.getLogger(__name__)


class PermissionSyncService:
    """
    Service pour synchroniser les permissions de la BDD vers Keycloak.

    Les permissions sont converties en client roles Keycloak avec le format:
    - app.CAMPAIGN_READ
    - app.CAMPAIGN_CREATE
    - app.ORGANIZATION_UPDATE
    etc.
    """

    # Préfixe pour les permissions dans Keycloak
    PERMISSION_PREFIX = "app."

    def __init__(self, keycloak_service: KeycloakService):
        """
        Initialise le service de synchronisation.

        Args:
            keycloak_service: Instance du service Keycloak
        """
        self.keycloak = keycloak_service
        self.admin_url = keycloak_service.admin_url

    async def get_all_permissions_from_db(self, db: Session) -> List[Dict[str, Any]]:
        """
        Récupère toutes les permissions de la base de données.

        Returns:
            Liste des permissions avec code, name, module, action
        """
        query = text("""
            SELECT id, code, name, module, action, permission_type
            FROM permission
            ORDER BY module, action
        """)

        result = db.execute(query).fetchall()
        return [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "module": row.module,
                "action": row.action,
                "permission_type": row.permission_type
            }
            for row in result
        ]

    async def get_role_permissions_from_db(self, db: Session, role_code: str) -> List[str]:
        """
        Récupère les permissions d'un rôle depuis la BDD.

        Args:
            role_code: Code du rôle (ex: "CHEF_PROJET")

        Returns:
            Liste des codes de permission
        """
        query = text("""
            SELECT p.code
            FROM permission p
            JOIN role_permission rp ON p.id = rp.permission_id
            JOIN role r ON rp.role_id = r.id
            WHERE r.code = :role_code
        """)

        result = db.execute(query, {"role_code": role_code}).fetchall()
        return [row.code for row in result]

    async def create_client_role_if_not_exists(
        self,
        admin_token: str,
        client_id: str,
        role_name: str,
        role_description: str = ""
    ) -> bool:
        """
        Crée un client role dans Keycloak s'il n'existe pas.

        Args:
            admin_token: Token d'administration Keycloak
            client_id: ID du client Keycloak (UUID, pas le client_id string)
            role_name: Nom du rôle (ex: "app.CAMPAIGN_READ")
            role_description: Description du rôle

        Returns:
            True si créé ou existe déjà, False en cas d'erreur
        """
        try:
            async with httpx.AsyncClient() as client:
                # Vérifier si le rôle existe
                check_url = f"{self.admin_url}/clients/{client_id}/roles/{role_name}"
                check_response = await client.get(
                    check_url,
                    headers={"Authorization": f"Bearer {admin_token}"}
                )

                if check_response.status_code == 200:
                    logger.debug(f"✅ Client role existe déjà: {role_name}")
                    return True

                # Créer le rôle
                create_url = f"{self.admin_url}/clients/{client_id}/roles"
                create_response = await client.post(
                    create_url,
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "name": role_name,
                        "description": role_description
                    }
                )

                if create_response.status_code == 201:
                    logger.info(f"✅ Client role créé: {role_name}")
                    return True
                elif create_response.status_code == 409:
                    logger.debug(f"✅ Client role existe déjà (409): {role_name}")
                    return True
                else:
                    logger.error(f"❌ Erreur création client role {role_name}: {create_response.text}")
                    return False

        except Exception as e:
            logger.error(f"❌ Erreur création client role {role_name}: {e}")
            return False

    async def get_client_uuid(self, admin_token: str, client_id_str: str) -> Optional[str]:
        """
        Récupère l'UUID d'un client Keycloak depuis son client_id string.

        Args:
            admin_token: Token d'administration
            client_id_str: Client ID string (ex: "cyberguard-backend")

        Returns:
            UUID du client ou None
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.admin_url}/clients",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    params={"clientId": client_id_str}
                )

                if response.status_code == 200:
                    clients = response.json()
                    if clients:
                        return clients[0]["id"]

                logger.error(f"❌ Client non trouvé: {client_id_str}")
                return None

        except Exception as e:
            logger.error(f"❌ Erreur récupération client UUID: {e}")
            return None

    async def sync_all_permissions_to_keycloak(self, db: Session) -> Dict[str, Any]:
        """
        Synchronise toutes les permissions de la BDD vers Keycloak.
        Crée les client roles correspondants.

        Args:
            db: Session de base de données

        Returns:
            Résumé de la synchronisation
        """
        logger.info("🔄 Début synchronisation des permissions vers Keycloak")

        # 1. Obtenir le token admin
        admin_token = await self.keycloak.get_admin_token()
        if not admin_token:
            logger.error("❌ Impossible d'obtenir le token admin Keycloak")
            return {"success": False, "error": "Token admin non disponible"}

        # 2. Obtenir l'UUID du client
        client_uuid = await self.get_client_uuid(admin_token, self.keycloak.client_id)
        if not client_uuid:
            return {"success": False, "error": "Client Keycloak non trouvé"}

        # 3. Récupérer toutes les permissions de la BDD
        permissions = await self.get_all_permissions_from_db(db)

        # 4. Créer les client roles pour chaque permission
        created = 0
        failed = 0

        for perm in permissions:
            role_name = f"{self.PERMISSION_PREFIX}{perm['code']}"
            success = await self.create_client_role_if_not_exists(
                admin_token,
                client_uuid,
                role_name,
                perm["name"]
            )

            if success:
                created += 1
            else:
                failed += 1

        result = {
            "success": failed == 0,
            "total_permissions": len(permissions),
            "created_or_exists": created,
            "failed": failed
        }

        logger.info(f"✅ Synchronisation terminée: {result}")
        return result

    async def assign_permissions_to_user(
        self,
        admin_token: str,
        user_keycloak_id: str,
        permission_codes: List[str]
    ) -> bool:
        """
        Assigne des permissions (client roles) à un utilisateur dans Keycloak.

        Args:
            admin_token: Token d'administration
            user_keycloak_id: ID Keycloak de l'utilisateur
            permission_codes: Codes des permissions à assigner

        Returns:
            True si succès
        """
        try:
            # Obtenir l'UUID du client
            client_uuid = await self.get_client_uuid(admin_token, self.keycloak.client_id)
            if not client_uuid:
                return False

            async with httpx.AsyncClient() as client:
                # Récupérer les rôles à assigner
                roles_to_assign = []

                for perm_code in permission_codes:
                    role_name = f"{self.PERMISSION_PREFIX}{perm_code}"

                    # Récupérer le rôle
                    role_response = await client.get(
                        f"{self.admin_url}/clients/{client_uuid}/roles/{role_name}",
                        headers={"Authorization": f"Bearer {admin_token}"}
                    )

                    if role_response.status_code == 200:
                        roles_to_assign.append(role_response.json())
                    else:
                        logger.warning(f"⚠️ Rôle non trouvé dans Keycloak: {role_name}")

                if not roles_to_assign:
                    logger.warning("⚠️ Aucun rôle à assigner")
                    return True

                # Assigner les rôles à l'utilisateur
                assign_response = await client.post(
                    f"{self.admin_url}/users/{user_keycloak_id}/role-mappings/clients/{client_uuid}",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json=roles_to_assign
                )

                if assign_response.status_code in [200, 204]:
                    logger.info(f"✅ {len(roles_to_assign)} permissions assignées à l'utilisateur {user_keycloak_id}")
                    return True
                else:
                    logger.error(f"❌ Erreur assignation: {assign_response.text}")
                    return False

        except Exception as e:
            logger.error(f"❌ Erreur assignation permissions: {e}")
            return False

    async def sync_role_permissions_to_keycloak(
        self,
        db: Session,
        role_code: str
    ) -> Dict[str, Any]:
        """
        Synchronise les permissions d'un rôle vers Keycloak.

        Cette méthode :
        1. Récupère les permissions du rôle depuis la BDD
        2. Met à jour le rôle composite dans Keycloak avec ces permissions

        Args:
            db: Session de base de données
            role_code: Code du rôle à synchroniser

        Returns:
            Résumé de la synchronisation
        """
        logger.info(f"🔄 Synchronisation des permissions du rôle {role_code} vers Keycloak")

        # 1. Obtenir le token admin
        admin_token = await self.keycloak.get_admin_token()
        if not admin_token:
            return {"success": False, "error": "Token admin non disponible"}

        # 2. Récupérer les permissions du rôle depuis la BDD
        permission_codes = await self.get_role_permissions_from_db(db, role_code)
        logger.info(f"📋 Permissions du rôle {role_code}: {permission_codes}")

        # 3. S'assurer que toutes les permissions existent comme client roles
        client_uuid = await self.get_client_uuid(admin_token, self.keycloak.client_id)
        if not client_uuid:
            return {"success": False, "error": "Client Keycloak non trouvé"}

        for perm_code in permission_codes:
            role_name = f"{self.PERMISSION_PREFIX}{perm_code}"
            await self.create_client_role_if_not_exists(
                admin_token,
                client_uuid,
                role_name,
                f"Permission: {perm_code}"
            )

        # 4. Mettre à jour le realm role avec les client roles (composite role)
        # On utilise les realm roles pour mapper rôle métier -> permissions
        await self._update_composite_role(admin_token, client_uuid, role_code, permission_codes)

        return {
            "success": True,
            "role_code": role_code,
            "permissions_synced": len(permission_codes),
            "permission_codes": permission_codes
        }

    async def _update_composite_role(
        self,
        admin_token: str,
        client_uuid: str,
        role_code: str,
        permission_codes: List[str]
    ) -> bool:
        """
        Met à jour un realm role comme composite role avec les client roles de permission.

        Args:
            admin_token: Token admin
            client_uuid: UUID du client
            role_code: Code du rôle métier (sera converti en lowercase pour Keycloak)
            permission_codes: Codes des permissions à inclure

        Returns:
            True si succès
        """
        try:
            # Mapping des codes de rôle vers les noms Keycloak
            role_mapping = {
                "SUPER_ADMIN": "super_admin",
                "ADMIN": "admin",
                "CHEF_PROJET": "chef_projet",
                "RSSI": "rssi",
                "DIR_CONFORMITE_DPO": "dir_conformite_dpo",
                "DPO_EXTERNE": "dpo_externe",
                "RSSI_EXTERNE": "rssi_externe",
                "AUDITEUR": "auditeur",
                "AUDITE_RESP": "audite_resp",
                "AUDITE_CONTRIB": "audite_contrib",
            }

            keycloak_role_name = role_mapping.get(role_code, role_code.lower())

            async with httpx.AsyncClient() as client:
                # 1. Vérifier/créer le realm role
                realm_role_url = f"{self.admin_url}/roles/{keycloak_role_name}"
                check_response = await client.get(
                    realm_role_url,
                    headers={"Authorization": f"Bearer {admin_token}"}
                )

                if check_response.status_code != 200:
                    # Créer le realm role s'il n'existe pas
                    create_response = await client.post(
                        f"{self.admin_url}/roles",
                        headers={
                            "Authorization": f"Bearer {admin_token}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "name": keycloak_role_name,
                            "description": f"Rôle métier: {role_code}",
                            "composite": True
                        }
                    )

                    if create_response.status_code not in [201, 409]:
                        logger.error(f"❌ Erreur création realm role: {create_response.text}")
                        return False

                # 2. Récupérer les client roles pour les permissions
                client_roles = []
                for perm_code in permission_codes:
                    role_name = f"{self.PERMISSION_PREFIX}{perm_code}"
                    role_response = await client.get(
                        f"{self.admin_url}/clients/{client_uuid}/roles/{role_name}",
                        headers={"Authorization": f"Bearer {admin_token}"}
                    )

                    if role_response.status_code == 200:
                        client_roles.append(role_response.json())

                if not client_roles:
                    logger.info(f"⚠️ Aucun client role à associer au realm role {keycloak_role_name}")
                    return True

                # 3. Supprimer les anciens composites (client roles) du realm role
                # D'abord récupérer les composites existants
                existing_composites_response = await client.get(
                    f"{realm_role_url}/composites/clients/{client_uuid}",
                    headers={"Authorization": f"Bearer {admin_token}"}
                )

                if existing_composites_response.status_code == 200:
                    existing = existing_composites_response.json()
                    if existing:
                        # Supprimer les anciens
                        await client.delete(
                            f"{realm_role_url}/composites",
                            headers={
                                "Authorization": f"Bearer {admin_token}",
                                "Content-Type": "application/json"
                            },
                            json=existing
                        )

                # 4. Ajouter les nouveaux client roles comme composites
                add_response = await client.post(
                    f"{realm_role_url}/composites",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json=client_roles
                )

                if add_response.status_code in [200, 204]:
                    logger.info(f"✅ Realm role {keycloak_role_name} mis à jour avec {len(client_roles)} permissions")
                    return True
                else:
                    logger.error(f"❌ Erreur ajout composites: {add_response.text}")
                    return False

        except Exception as e:
            logger.error(f"❌ Erreur mise à jour composite role: {e}")
            return False


# ============================================================================
# Instance globale
# ============================================================================

_permission_sync_service: Optional[PermissionSyncService] = None


def init_permission_sync_service(keycloak_service: KeycloakService) -> PermissionSyncService:
    """
    Initialise le service de synchronisation des permissions.

    Args:
        keycloak_service: Instance du service Keycloak

    Returns:
        Instance de PermissionSyncService
    """
    global _permission_sync_service

    if _permission_sync_service is None:
        _permission_sync_service = PermissionSyncService(keycloak_service)
        logger.info("✅ PermissionSyncService initialisé")

    return _permission_sync_service


def get_permission_sync_service() -> PermissionSyncService:
    """
    Retourne l'instance globale du service de synchronisation.

    Returns:
        Instance de PermissionSyncService

    Raises:
        RuntimeError: Si le service n'est pas initialisé
    """
    if _permission_sync_service is None:
        raise RuntimeError(
            "PermissionSyncService non initialisé. "
            "Appelez init_permission_sync_service() au démarrage."
        )
    return _permission_sync_service
