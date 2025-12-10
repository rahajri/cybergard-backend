"""
Script pour synchroniser les rôles de la base de données vers Keycloak
et assigner le rôle admin à l'utilisateur rachid.ahajri@vision-agile.fr
"""
import os
import sys
import requests

sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
os.environ['DATABASE_URL'] = 'postgresql://postgres:postgres@localhost:5432/audit_platform'

from sqlalchemy import create_engine, text

# Configuration Keycloak
KEYCLOAK_URL = "http://localhost:8080"
KEYCLOAK_REALM = "cyberguard"
KEYCLOAK_ADMIN_USER = "admin"
KEYCLOAK_ADMIN_PASSWORD = "admin"


def get_admin_token():
    """Obtenir un token admin Keycloak"""
    url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    data = {
        "client_id": "admin-cli",
        "username": KEYCLOAK_ADMIN_USER,
        "password": KEYCLOAK_ADMIN_PASSWORD,
        "grant_type": "password"
    }

    response = requests.post(url, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print(f"Erreur authentification Keycloak: {response.status_code}")
        print(response.text)
        return None


def get_keycloak_roles(token):
    """Récupérer les rôles existants dans Keycloak"""
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/roles"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return {role["name"].lower(): role for role in response.json()}
    return {}


def create_keycloak_role(token, role_name, description=""):
    """Créer un rôle dans Keycloak"""
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/roles"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    data = {
        "name": role_name.lower(),
        "description": description
    }

    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 201


def get_keycloak_user(token, email):
    """Récupérer un utilisateur Keycloak par email"""
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"email": email}

    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        users = response.json()
        if users:
            return users[0]
    return None


def assign_role_to_user(token, user_id, role_name):
    """Assigner un rôle à un utilisateur Keycloak"""
    # D'abord, récupérer le rôle
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/roles/{role_name.lower()}"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"  Rôle {role_name} non trouvé dans Keycloak")
        return False

    role = response.json()

    # Assigner le rôle à l'utilisateur
    url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/role-mappings/realm"
    response = requests.post(url, headers={**headers, "Content-Type": "application/json"}, json=[role])

    return response.status_code == 204


def main():
    engine = create_engine(os.environ['DATABASE_URL'])

    print("=" * 70, flush=True)
    print("SYNCHRONISATION DES RÔLES VERS KEYCLOAK", flush=True)
    print("=" * 70, flush=True)

    # 1. Obtenir un token admin
    print("\n1. Connexion à Keycloak...", flush=True)
    token = get_admin_token()
    if not token:
        print("ERREUR: Impossible de se connecter à Keycloak", flush=True)
        return
    print("   ✅ Connecté à Keycloak", flush=True)

    # 2. Récupérer les rôles existants dans Keycloak
    print("\n2. Rôles existants dans Keycloak:", flush=True)
    kc_roles = get_keycloak_roles(token)
    for role_name in sorted(kc_roles.keys()):
        print(f"   - {role_name}", flush=True)

    # 3. Récupérer les rôles de la base de données
    print("\n3. Rôles dans la base de données:", flush=True)
    with engine.connect() as conn:
        db_roles = conn.execute(text("""
            SELECT code, name, description FROM role ORDER BY code
        """)).fetchall()

        for role in db_roles:
            print(f"   - {role.code}: {role.name}", flush=True)

    # 4. Créer les rôles manquants dans Keycloak
    print("\n4. Création des rôles manquants dans Keycloak:", flush=True)
    created = 0
    for role in db_roles:
        role_code_lower = role.code.lower()
        if role_code_lower not in kc_roles:
            print(f"   + Création de '{role_code_lower}'...", flush=True)
            if create_keycloak_role(token, role.code, role.description or role.name):
                print(f"     ✅ Créé", flush=True)
                created += 1
            else:
                print(f"     ❌ Échec", flush=True)
        else:
            print(f"   - '{role_code_lower}' existe déjà", flush=True)

    print(f"\n   Total créé: {created} rôles", flush=True)

    # 5. Assigner le rôle admin à rachid.ahajri@vision-agile.fr
    print("\n5. Assignation du rôle admin à l'utilisateur:", flush=True)
    user_email = "rachid.ahajri@vision-agile.fr"

    kc_user = get_keycloak_user(token, user_email)
    if kc_user:
        print(f"   Utilisateur trouvé: {kc_user['id']}", flush=True)

        if assign_role_to_user(token, kc_user['id'], 'admin'):
            print(f"   ✅ Rôle 'admin' assigné à {user_email}", flush=True)
        else:
            print(f"   ❌ Échec de l'assignation du rôle", flush=True)
    else:
        print(f"   ❌ Utilisateur {user_email} non trouvé dans Keycloak", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("TERMINÉ!", flush=True)
    print("=" * 70, flush=True)
    print("\nReconnectez-vous pour que les nouveaux rôles soient pris en compte.", flush=True)


if __name__ == "__main__":
    main()
