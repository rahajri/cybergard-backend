#!/bin/bash

# ============================================================================
# Exemple d'utilisation de l'API pour créer des catégories hiérarchiques
# ============================================================================
# Démonstration : Créer MAROC sous différents parents (FOURNISSEURS et CLIENTS)
# ============================================================================

API_URL="http://localhost:8000/api/v1/hierarchy"
CLIENT_ORG_ID="bf787e86-7df2-4a0d-b24f-88fe54a618dd"

echo "========================================="
echo "Test API - Création de catégories"
echo "========================================="
echo ""

# ============================================================================
# Test 1 : Récupérer les catégories parentes (Fournisseurs, Clients)
# ============================================================================
echo "1. Récupération des catégories parentes..."
curl -s -X GET "$API_URL/categories?stakeholder_type=external" | jq '.[] | select(.name == "Fournisseurs" or .name == "Clients") | {id, name}'

echo ""
echo "========================================="

# ============================================================================
# Test 2 : Créer FOURNISSEURS → MAROC
# ============================================================================
echo "2. Création de FOURNISSEURS → MAROC..."

FOURNISSEURS_ID="5871341e-bc83-4f47-8cbf-f938658203eb"

curl -s -X POST "$API_URL/categories" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"MAROC\",
    \"entity_category\": \"geographic\",
    \"description\": \"Fournisseurs basés au Maroc\",
    \"parent_category_id\": \"$FOURNISSEURS_ID\",
    \"client_organization_id\": \"$CLIENT_ORG_ID\",
    \"stakeholder_type\": \"external\"
  }" | jq '.'

echo ""
echo "✅ FOURNISSEURS → MAROC créé"
echo "========================================="

# ============================================================================
# Test 3 : Créer CLIENTS → MAROC
# ============================================================================
echo "3. Création de CLIENTS → MAROC..."

CLIENTS_ID="45953373-3ada-433f-b9cc-9de500b60d09"

curl -s -X POST "$API_URL/categories" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"MAROC\",
    \"entity_category\": \"geographic\",
    \"description\": \"Clients basés au Maroc\",
    \"parent_category_id\": \"$CLIENTS_ID\",
    \"client_organization_id\": \"$CLIENT_ORG_ID\",
    \"stakeholder_type\": \"external\"
  }" | jq '.'

echo ""
echo "✅ CLIENTS → MAROC créé"
echo "========================================="

# ============================================================================
# Test 4 : Vérifier la hiérarchie complète
# ============================================================================
echo "4. Vérification de l'arbre hiérarchique..."

curl -s -X GET "$API_URL/tree" | jq '.tree[] | select(.name == "Externe") | .children[] | select(.name == "Fournisseurs" or .name == "Clients")'

echo ""
echo "========================================="
echo "✅ Tests terminés avec succès !"
echo "========================================="
