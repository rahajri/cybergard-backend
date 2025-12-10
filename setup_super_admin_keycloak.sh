#!/bin/bash
set -e

KEYCLOAK_URL="http://localhost:8080"
REALM="cyberguard"
ADMIN_USER="admin"
ADMIN_PASS="admin"
USER_EMAIL="admin@cybergard.fr"
USER_FIRST_NAME="Super"
USER_LAST_NAME="Admin"
USER_PASSWORD="Cybergard2025!"

echo "=========================================="
echo "CRÉATION SUPER ADMIN DANS KEYCLOAK"
echo "=========================================="
echo ""

# 1. Obtenir le token admin
echo "🔐 1. Obtenir le token admin Keycloak..."
TOKEN_RESPONSE=$(curl -s -X POST "$KEYCLOAK_URL/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$ADMIN_USER" \
  -d "password=$ADMIN_PASS" \
  -d "grant_type=password" \
  -d "client_id=admin-cli")

ACCESS_TOKEN=$(echo $TOKEN_RESPONSE | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

if [ -z "$ACCESS_TOKEN" ]; then
  echo "❌ Impossible d'obtenir le token admin"
  echo "Response: $TOKEN_RESPONSE"
  exit 1
fi

echo "✅ Token admin obtenu"
echo ""

# 2. Vérifier si l'utilisateur existe déjà
echo "🔍 2. Vérifier si l'utilisateur $USER_EMAIL existe..."
USERS_RESPONSE=$(curl -s -X GET "$KEYCLOAK_URL/admin/realms/$REALM/users?email=$USER_EMAIL" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

USER_ID=$(echo $USERS_RESPONSE | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$USER_ID" ]; then
  echo "📝 Utilisateur n'existe pas, création..."
  
  # Créer l'utilisateur
  CREATE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$KEYCLOAK_URL/admin/realms/$REALM/users" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"username\": \"$USER_EMAIL\",
      \"email\": \"$USER_EMAIL\",
      \"firstName\": \"$USER_FIRST_NAME\",
      \"lastName\": \"$USER_LAST_NAME\",
      \"enabled\": true,
      \"emailVerified\": true,
      \"credentials\": [{
        \"type\": \"password\",
        \"value\": \"$USER_PASSWORD\",
        \"temporary\": false
      }]
    }")
  
  HTTP_CODE=$(echo "$CREATE_RESPONSE" | tail -n1)
  
  if [ "$HTTP_CODE" = "201" ]; then
    echo "✅ Utilisateur créé avec succès"
    
    # Récupérer l'ID du nouvel utilisateur
    sleep 1
    USERS_RESPONSE=$(curl -s -X GET "$KEYCLOAK_URL/admin/realms/$REALM/users?email=$USER_EMAIL" \
      -H "Authorization: Bearer $ACCESS_TOKEN")
    USER_ID=$(echo $USERS_RESPONSE | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
  else
    echo "❌ Erreur lors de la création de l'utilisateur (HTTP $HTTP_CODE)"
    echo "$CREATE_RESPONSE"
    exit 1
  fi
else
  echo "✅ Utilisateur existe déjà: $USER_ID"
  
  # Mettre à jour le mot de passe si nécessaire
  echo "🔄 Mise à jour du mot de passe..."
  curl -s -X PUT "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/reset-password" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"type\": \"password\",
      \"value\": \"$USER_PASSWORD\",
      \"temporary\": false
    }"
  echo "✅ Mot de passe mis à jour"
fi

echo "User ID: $USER_ID"
echo ""

# 3. Créer ou récupérer le rôle super_admin
echo "🔍 3. Vérifier/créer le rôle 'super_admin'..."
ROLE_RESPONSE=$(curl -s -X GET "$KEYCLOAK_URL/admin/realms/$REALM/roles/super_admin" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

ROLE_ID=$(echo $ROLE_RESPONSE | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$ROLE_ID" ]; then
  echo "📝 Création du rôle 'super_admin'..."
  
  curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/roles" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "super_admin",
      "description": "Super Administrator - Full platform access",
      "composite": false,
      "clientRole": false
    }'
  
  echo "✅ Rôle 'super_admin' créé"
  
  # Récupérer à nouveau l'ID
  sleep 1
  ROLE_RESPONSE=$(curl -s -X GET "$KEYCLOAK_URL/admin/realms/$REALM/roles/super_admin" \
    -H "Authorization: Bearer $ACCESS_TOKEN")
  ROLE_ID=$(echo $ROLE_RESPONSE | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
fi

ROLE_NAME=$(echo $ROLE_RESPONSE | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
echo "✅ Rôle trouvé: $ROLE_NAME (ID: $ROLE_ID)"
echo ""

# 4. Assigner le rôle à l'utilisateur
echo "👤 4. Assigner le rôle 'super_admin' à $USER_EMAIL..."
curl -s -X POST "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/role-mappings/realm" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "[{
    \"id\": \"$ROLE_ID\",
    \"name\": \"super_admin\"
  }]"

echo "✅ Rôle assigné avec succès!"
echo ""

# 5. Vérification finale
echo "🔍 5. Vérification des rôles assignés..."
ASSIGNED_ROLES=$(curl -s -X GET "$KEYCLOAK_URL/admin/realms/$REALM/users/$USER_ID/role-mappings/realm" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

echo "Rôles de l'utilisateur $USER_EMAIL:"
echo "$ASSIGNED_ROLES" | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | sed 's/^/  - /'

echo ""
echo "=========================================="
echo "✅ CONFIGURATION TERMINÉE!"
echo "=========================================="
echo ""
echo "Informations de connexion:"
echo "  Email: $USER_EMAIL"
echo "  Mot de passe: $USER_PASSWORD"
echo "  Rôle: super_admin"
echo ""
echo "Vous pouvez maintenant vous connecter à l'application."
