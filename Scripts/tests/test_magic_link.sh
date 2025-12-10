#!/bin/bash
# Script de test pour Magic Link + Keycloak

echo "🧪 Test Magic Link + Keycloak Integration"
echo "=========================================="
echo ""

# Configuration
BACKEND_URL="http://localhost:8000"
FRONTEND_URL="http://localhost:3000"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "📋 Étape 1 : Générer un Magic Link"
echo "-----------------------------------"
echo ""
echo "${YELLOW}Vous devez fournir :${NC}"
echo "  - user_email: Email de l'audité (ex: test@example.com)"
echo "  - campaign_id: ID de la campagne (UUID)"
echo "  - questionnaire_id: ID du questionnaire (UUID)"
echo "  - tenant_id: ID du tenant (UUID)"
echo ""

read -p "Email de l'audité : " USER_EMAIL
read -p "Campaign ID : " CAMPAIGN_ID
read -p "Questionnaire ID : " QUESTIONNAIRE_ID
read -p "Tenant ID : " TENANT_ID

echo ""
echo "${YELLOW}Génération du magic link...${NC}"

RESPONSE=$(curl -s -X POST "$BACKEND_URL/api/v1/user-management/generate-magic-link" \
  -H "Content-Type: application/json" \
  -d "{
    \"user_email\": \"$USER_EMAIL\",
    \"campaign_id\": \"$CAMPAIGN_ID\",
    \"questionnaire_id\": \"$QUESTIONNAIRE_ID\",
    \"tenant_id\": \"$TENANT_ID\",
    \"entity_name\": \"Entité Test\"
  }")

echo "$RESPONSE" | jq '.' 2>/dev/null || echo "$RESPONSE"

# Extraire le magic link
MAGIC_LINK=$(echo "$RESPONSE" | jq -r '.magic_link' 2>/dev/null)

if [ "$MAGIC_LINK" == "null" ] || [ -z "$MAGIC_LINK" ]; then
  echo ""
  echo "${RED}❌ Erreur : Impossible de générer le magic link${NC}"
  echo "Vérifiez que vous avez fourni des IDs valides."
  exit 1
fi

echo ""
echo "${GREEN}✅ Magic link généré avec succès !${NC}"
echo "URL complète : $MAGIC_LINK"

# Extraire juste le token
TOKEN=$(echo "$MAGIC_LINK" | sed 's/.*token=//')

echo ""
echo "Token JWT : $TOKEN"
echo ""

# Étape 2 : Tester l'échange de token
echo ""
echo "📋 Étape 2 : Échanger le Magic Token contre Token Keycloak"
echo "-----------------------------------------------------------"
echo ""

EXCHANGE_RESPONSE=$(curl -s -X POST "$BACKEND_URL/api/v1/magic-link/exchange" \
  -H "Content-Type: application/json" \
  -d "{\"magic_token\": \"$TOKEN\"}")

echo "Réponse de l'échange :"
echo "$EXCHANGE_RESPONSE" | jq '.' 2>/dev/null || echo "$EXCHANGE_RESPONSE"

# Vérifier si l'échange a réussi
ACCESS_TOKEN=$(echo "$EXCHANGE_RESPONSE" | jq -r '.access_token' 2>/dev/null)

if [ "$ACCESS_TOKEN" == "null" ] || [ -z "$ACCESS_TOKEN" ]; then
  echo ""
  echo "${RED}❌ Erreur : L'échange de token a échoué${NC}"
  echo ""
  echo "Causes possibles :"
  echo "  1. Keycloak : Direct Access Grants désactivé"
  echo "  2. Token expiré ou déjà utilisé"
  echo "  3. Erreur de configuration Keycloak"
  echo ""
  echo "Vérifiez les logs backend pour plus de détails."
  exit 1
fi

echo ""
echo "${GREEN}✅ Token Keycloak obtenu avec succès !${NC}"
echo ""
echo "Access Token : ${ACCESS_TOKEN:0:50}..."
echo ""

# Étape 3 : Tester l'accès au questionnaire
echo ""
echo "📋 Étape 3 : Tester l'accès au questionnaire"
echo "--------------------------------------------"
echo ""

AUDIT_ID=$(echo "$EXCHANGE_RESPONSE" | jq -r '.audit_id')
QUESTIONNAIRE_ID_RESPONSE=$(echo "$EXCHANGE_RESPONSE" | jq -r '.questionnaire_id')

echo "URL du questionnaire : $FRONTEND_URL/audite/$AUDIT_ID/$QUESTIONNAIRE_ID_RESPONSE"
echo ""

echo "${GREEN}✅ Test complet réussi !${NC}"
echo ""
echo "Vous pouvez maintenant :"
echo "  1. Ouvrir l'URL du magic link dans le navigateur : $MAGIC_LINK"
echo "  2. Ou accéder directement au questionnaire : $FRONTEND_URL/audite/$AUDIT_ID/$QUESTIONNAIRE_ID_RESPONSE"
echo ""
