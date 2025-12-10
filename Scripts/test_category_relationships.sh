#!/bin/bash
# Script de test pour les endpoints de relations de catégories

BASE_URL="http://localhost:8000"
API_URL="$BASE_URL/api/v1"

echo "========================================="
echo "Test des endpoints Category Relationships"
echo "========================================="

# Variables de test (à remplacer avec des IDs réels)
CATEGORY_ID_1="replace-with-real-uuid"  # Ex: FOURNISSEURS
CATEGORY_ID_2="replace-with-real-uuid"  # Ex: MAROC

# Token Keycloak (à obtenir via login)
# Pour obtenir un token, il faut d'abord se connecter via le frontend
# ou utiliser l'endpoint /api/v1/auth/login

echo ""
echo "1. Test GET /categories/{category_id}/parents"
echo "----------------------------------------"
curl -X GET "$API_URL/hierarchy/categories/$CATEGORY_ID_2/parents" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json"

echo ""
echo ""
echo "2. Test GET /categories/{category_id}/contexts"
echo "----------------------------------------"
curl -X GET "$API_URL/hierarchy/categories/$CATEGORY_ID_2/contexts" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json"

echo ""
echo ""
echo "3. Test POST /categories/relationships (créer une nouvelle relation)"
echo "----------------------------------------"
curl -X POST "$API_URL/hierarchy/categories/relationships" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "parent_category_id": "'"$CATEGORY_ID_1"'",
    "child_category_id": "'"$CATEGORY_ID_2"'",
    "is_primary": false
  }'

echo ""
echo ""
echo "4. Test PATCH /categories/relationships/{relationship_id}/promote"
echo "----------------------------------------"
RELATIONSHIP_ID="replace-with-relationship-id"
curl -X PATCH "$API_URL/hierarchy/categories/relationships/$RELATIONSHIP_ID/promote" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json"

echo ""
echo ""
echo "5. Test DELETE /categories/relationships/{relationship_id}"
echo "----------------------------------------"
curl -X DELETE "$API_URL/hierarchy/categories/relationships/$RELATIONSHIP_ID" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json"

echo ""
echo ""
echo "========================================="
echo "Tests terminés"
echo "========================================="
