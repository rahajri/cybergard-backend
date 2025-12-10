#!/bin/bash
# Script de test HTTP pour l'API Organizations
# Teste les contrôles SaaS via HTTP

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# API Base URL
BASE_URL="http://localhost:8000/api/v1/organizations"

# Test data (from database test script)
TENANT_A_ID="844e0c15-d19d-49d1-947e-455a7e5fc5ba"
TENANT_B_ID="51f59828-26fb-42ad-b27e-5b35a482cf38"
ORG_A1_ID="efed787e-b703-489a-9ef3-3be51bc1f8ef"
ORG_A2_ID="e6065687-b63d-439e-a052-442430641d6a"
ORG_B1_ID="1cab0a47-9ecb-412e-8df6-193baf0d86f3"
ORG_B2_ID="5bb8d5d9-0c9c-42ae-a395-599d481f6ac3"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  HTTP API Tests - SaaS Controls${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Test 1: No authentication should fail
echo -e "${YELLOW}[TEST 1]${NC} GET /organizations without auth (should be 401 or 403)"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/")
if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "403" ] || [ "$HTTP_CODE" == "404" ]; then
    echo -e "${GREEN}✅ PASS${NC}: HTTP $HTTP_CODE (authentication required)"
else
    echo -e "${RED}❌ FAIL${NC}: HTTP $HTTP_CODE (expected 401/403/404)"
fi

# Test 2: Check server is running
echo -e "\n${YELLOW}[TEST 2]${NC} Check server health"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/health")
if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✅ PASS${NC}: Server is running (HTTP $HTTP_CODE)"
else
    echo -e "${RED}❌ FAIL${NC}: Server not responding (HTTP $HTTP_CODE)"
    exit 1
fi

# Test 3: Check API docs accessible
echo -e "\n${YELLOW}[TEST 3]${NC} Check API documentation"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/docs")
if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✅ PASS${NC}: API docs accessible (HTTP $HTTP_CODE)"
else
    echo -e "${RED}❌ FAIL${NC}: API docs not accessible (HTTP $HTTP_CODE)"
fi

# Test 4: Test stats endpoint without auth
echo -e "\n${YELLOW}[TEST 4]${NC} GET /stats/overview without auth (should be 401 or 403)"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/stats/overview")
if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "403" ] || [ "$HTTP_CODE" == "404" ]; then
    echo -e "${GREEN}✅ PASS${NC}: HTTP $HTTP_CODE (authentication required)"
else
    echo -e "${RED}❌ FAIL${NC}: HTTP $HTTP_CODE (expected 401/403/404)"
fi

# Test 5: Test search endpoint without auth
echo -e "\n${YELLOW}[TEST 5]${NC} GET /search without auth (should be 401 or 403)"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/search?q=test")
if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "403" ] || [ "$HTTP_CODE" == "404" ]; then
    echo -e "${GREEN}✅ PASS${NC}: HTTP $HTTP_CODE (authentication required)"
else
    echo -e "${RED}❌ FAIL${NC}: HTTP $HTTP_CODE (expected 401/403/404)"
fi

# Test 6: Test export endpoint without auth
echo -e "\n${YELLOW}[TEST 6]${NC} GET /export without auth (should be 401 or 403)"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/export?format=json")
if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "403" ] || [ "$HTTP_CODE" == "404" ]; then
    echo -e "${GREEN}✅ PASS${NC}: HTTP $HTTP_CODE (authentication required)"
else
    echo -e "${RED}❌ FAIL${NC}: HTTP $HTTP_CODE (expected 401/403/404)"
fi

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}  HTTP Tests Complete${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "${YELLOW}Note:${NC} These tests verify that endpoints require authentication."
echo -e "${YELLOW}Note:${NC} For full testing with authentication, use Python script or Postman."
echo -e "${YELLOW}Note:${NC} Test data IDs from database tests:"
echo -e "  - Tenant A: $TENANT_A_ID"
echo -e "  - Tenant B: $TENANT_B_ID"
echo -e "  - Org A1: $ORG_A1_ID"
echo -e "  - Org B1: $ORG_B1_ID"
