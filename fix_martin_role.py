"""
Script pour créer le rôle 'auditeur' dans Keycloak et l'assigner à martin.ducept@gmail.com
"""
import asyncio
import os
from dotenv import load_dotenv
from src.services.keycloak_service import KeycloakService

load_dotenv()

async def main():
    # Initialiser le service Keycloak avec les variables d'environnement
    keycloak = KeycloakService(
        server_url=os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080"),
        realm=os.getenv("KEYCLOAK_REALM", "cyberguard"),
        client_id=os.getenv("KEYCLOAK_CLIENT_ID", "cyberguard-frontend"),
        client_secret=os.getenv("KEYCLOAK_CLIENT_SECRET"),
        admin_username=os.getenv("KEYCLOAK_ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin")
    )

    # 1. Obtenir un token admin
    print("Obtention du token admin...")
    admin_token = await keycloak.get_admin_token()

    if not admin_token:
        print("❌ Impossible d'obtenir le token admin")
        return

    print("✅ Token admin obtenu")

    # 2. Créer le rôle 'auditeur' dans Keycloak (realm role)
    print("\n📝 Création du rôle 'auditeur' dans Keycloak...")

    import httpx

    try:
        async with httpx.AsyncClient() as client:
            # Vérifier si le rôle existe déjà
            check_response = await client.get(
                f"{keycloak.admin_url}/roles/auditeur",
                headers={"Authorization": f"Bearer {admin_token}"}
            )

            if check_response.status_code == 200:
                print("✅ Le rôle 'auditeur' existe déjà")
            else:
                # Créer le rôle
                create_response = await client.post(
                    f"{keycloak.admin_url}/roles",
                    headers={
                        "Authorization": f"Bearer {admin_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "name": "auditeur",
                        "description": "Auditeur - peut créer et gérer des campagnes d'audit"
                    }
                )
                create_response.raise_for_status()
                print("✅ Rôle 'auditeur' créé")

    except Exception as e:
        print(f"⚠️  Erreur lors de la création du rôle: {e}")

    # 3. Récupérer l'utilisateur martin.ducept@gmail.com depuis Keycloak
    print("\n📝 Recherche de l'utilisateur martin.ducept@gmail.com...")

    try:
        async with httpx.AsyncClient() as client:
            search_response = await client.get(
                f"{keycloak.admin_url}/users",
                headers={"Authorization": f"Bearer {admin_token}"},
                params={"email": "martin.ducept@gmail.com"}
            )
            search_response.raise_for_status()
            users = search_response.json()

            if not users:
                print("❌ Utilisateur non trouvé dans Keycloak")
                return

            user_id = users[0]["id"]
            print(f"✅ Utilisateur trouvé (ID: {user_id})")

    except Exception as e:
        print(f"❌ Erreur lors de la recherche de l'utilisateur: {e}")
        return

    # 4. Assigner le rôle à l'utilisateur
    print("\n📝 Assignation du rôle 'auditeur' à l'utilisateur...")

    success = await keycloak.assign_role_to_user(
        admin_token=admin_token,
        user_id=user_id,
        role_name="auditeur"
    )

    if success:
        print("✅ Rôle assigné avec succès!")
        print("\n🎉 TERMINÉ - Déconnectez-vous et reconnectez-vous pour que le rôle prenne effet")
    else:
        print("❌ Échec de l'assignation du rôle")

if __name__ == "__main__":
    asyncio.run(main())
