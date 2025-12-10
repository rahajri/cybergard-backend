"""Diagnostic approfondi de la configuration Keycloak"""
import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()

KEYCLOAK_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080")
REALM = os.getenv("KEYCLOAK_REALM_NAME", "cyberguard")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "cyberguard-backend")
CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

print("="*80)
print("DIAGNOSTIC APPROFONDI KEYCLOAK CLIENT")
print("="*80)

# Token admin
response = requests.post(
    f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
    data={
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": os.getenv("KEYCLOAK_ADMIN_USERNAME", "admin"),
        "password": os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin"),
    }
)
admin_token = response.json()["access_token"]

# Trouver le client
response = requests.get(
    f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients",
    headers={"Authorization": f"Bearer {admin_token}"}
)
clients = response.json()

client = None
for c in clients:
    if c.get("clientId") == CLIENT_ID:
        client = c
        break

client_uuid = client["id"]

# Recuperer la config COMPLETE
response = requests.get(
    f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{client_uuid}",
    headers={"Authorization": f"Bearer {admin_token}"}
)
client_config = response.json()

print("\nCONFIGURATION CLIENT COMPLETE:")
print("-"*80)
print(f"Client ID: {client_config.get('clientId')}")
print(f"UUID: {client_config.get('id')}")
print(f"Enabled: {client_config.get('enabled')}")
print(f"Protocol: {client_config.get('protocol')}")
print()

print("AUTHENTICATION SETTINGS:")
print(f"  publicClient: {client_config.get('publicClient')}")
print(f"  bearerOnly: {client_config.get('bearerOnly')}")
print(f"  clientAuthenticatorType: {client_config.get('clientAuthenticatorType')}")
print()

print("GRANT TYPES / FLOWS:")
print(f"  standardFlowEnabled: {client_config.get('standardFlowEnabled')}")
print(f"  implicitFlowEnabled: {client_config.get('implicitFlowEnabled')}")
print(f"  directAccessGrantsEnabled: {client_config.get('directAccessGrantsEnabled')}")  # <-- LE PLUS IMPORTANT
print(f"  serviceAccountsEnabled: {client_config.get('serviceAccountsEnabled')}")
print()

print("ACCESS SETTINGS:")
print(f"  rootUrl: {client_config.get('rootUrl')}")
print(f"  baseUrl: {client_config.get('baseUrl')}")
print(f"  redirectUris: {client_config.get('redirectUris')}")
print(f"  webOrigins: {client_config.get('webOrigins')}")
print()

print("CREDENTIALS:")
if client_config.get('publicClient'):
    print("  Type: PUBLIC CLIENT (pas de secret requis)")
else:
    print("  Type: CONFIDENTIAL CLIENT (secret requis)")

    # Essayer de recuperer le secret
    try:
        response = requests.get(
            f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{client_uuid}/client-secret",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        if response.status_code == 200:
            keycloak_secret = response.json().get("value")
            print(f"  Secret Keycloak: {keycloak_secret[:4]}...{keycloak_secret[-4:]}")
            print(f"  Secret .env:     {CLIENT_SECRET[:4]}...{CLIENT_SECRET[-4:]}")

            if keycloak_secret == CLIENT_SECRET:
                print("  [OK] Les secrets correspondent!")
            else:
                print("  [ERREUR] LES SECRETS NE CORRESPONDENT PAS!")
                print("\n  SOLUTION:")
                print(f"    1. Copier le secret Keycloak: {keycloak_secret}")
                print(f"    2. Mettre a jour .env: KEYCLOAK_CLIENT_SECRET={keycloak_secret}")
                print(f"    3. Redemarrer le backend")
        else:
            print(f"  [ATTENTION] Impossible de recuperer le secret: {response.status_code}")
    except Exception as e:
        print(f"  [ERREUR] {e}")

print()
print("ATTRIBUTES:")
for key, value in client_config.get('attributes', {}).items():
    if 'password' in key.lower() or 'grant' in key.lower() or 'flow' in key.lower():
        print(f"  {key}: {value}")

print()
print("="*80)
print("PROBLEMES POTENTIELS:")
print("="*80)

problems = []

if not client_config.get('enabled'):
    problems.append("- Client DESACTIVE!")

if not client_config.get('directAccessGrantsEnabled'):
    problems.append("- Direct Access Grants DESACTIVE!")

if client_config.get('bearerOnly'):
    problems.append("- Bearer Only = True (ne peut pas obtenir de tokens)")

if not client_config.get('publicClient') and not CLIENT_SECRET:
    problems.append("- Client confidentiel SANS secret dans .env")

if client_config.get('publicClient') and CLIENT_SECRET:
    problems.append("- Client public AVEC secret (incohérence)")

if problems:
    for p in problems:
        print(p)
else:
    print("Aucun probleme evident detecte dans la configuration")

print()
print("="*80)
print("RECOMMENDATION:")
print("="*80)

if not client_config.get('directAccessGrantsEnabled'):
    print("1. Direct Access Grants doit etre ACTIVE")
    print("   -> Reexecutez: python fix_keycloak_client.py")

if not client_config.get('publicClient'):
    print("2. Pour un client confidentiel, verifiez que le secret est correct")
    print("   -> Comparez le secret dans .env avec celui dans Keycloak")

if client_config.get('publicClient'):
    print("2. Pour un client public:")
    print("   -> Supprimez KEYCLOAK_CLIENT_SECRET du .env")
    print("   -> Redemarrez le backend")

print("\n3. Si tout est OK mais ca ne fonctionne toujours pas:")
print("   -> Il peut y avoir un cache Keycloak")
print("   -> Redemarrer Keycloak: docker-compose restart keycloak")

print("="*80)
