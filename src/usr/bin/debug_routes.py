#!/usr/bin/env python3
"""
Script de diagnostic pour vérifier les routes API
Usage: python debug_routes.py
"""

import requests
import json
import sys

def test_routes():
    """Teste toutes les routes questionnaires"""
    base_url = "http://localhost:8000"
    
    routes_to_test = [
        "/docs",  # Documentation FastAPI
        "/",      # Root
        "/health", # Health check
        "/api/v1/questionnaires",
        "/api/v1/questionnaires/stats", 
        "/api/v1/questionnaires/test/generation"
    ]
    
    print("🔍 Test des routes API...")
    print("=" * 60)
    
    for route in routes_to_test:
        try:
            url = f"{base_url}{route}"
            print(f"Testing: {url}")
            
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                print(f"✅ {route} - OK ({response.status_code})")
                
                # Afficher un aperçu de la réponse
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        print(f"   📄 Clés: {list(data.keys())}")
                    elif isinstance(data, list):
                        print(f"   📋 Liste de {len(data)} éléments")
                except:
                    print(f"   📄 Réponse: {response.text[:100]}...")
                        
            else:
                print(f"❌ {route} - Erreur {response.status_code}")
                if response.text:
                    print(f"   💬 Message: {response.text[:200]}")
                    
        except requests.exceptions.ConnectionError:
            print(f"🔌 {route} - Serveur non accessible")
            return False
        except Exception as e:
            print(f"💥 {route} - Erreur: {e}")
    
    print("=" * 60)
    return True

def test_openapi_docs():
    """Vérifie la documentation OpenAPI pour voir les routes disponibles"""
    try:
        response = requests.get("http://localhost:8000/openapi.json", timeout=5)
        if response.status_code == 200:
            openapi_spec = response.json()
            paths = openapi_spec.get("paths", {})
            
            print("\n📚 Routes disponibles dans OpenAPI:")
            print("-" * 40)
            for path, methods in paths.items():
                method_list = list(methods.keys())
                print(f"  {path} ({', '.join(method_list).upper()})")
            
            return True
        else:
            print("❌ Impossible de récupérer la spec OpenAPI")
            return False
    except Exception as e:
        print(f"❌ Erreur OpenAPI: {e}")
        return False

def main():
    print("🚀 Diagnostic des routes CyberGuard Pro API")
    print("=" * 60)
    
    # Test de connectivité de base
    if not test_routes():
        print("\n❌ Serveur non accessible. Vérifiez que le serveur est démarré:")
        print("   cd backend")
        print("   python -m uvicorn src.main:app --reload --port 8000")
        sys.exit(1)
    
    # Test de la documentation OpenAPI
    test_openapi_docs()
    
    print("\n📋 Actions recommandées si vous voyez des erreurs 404:")
    print("1. Vérifiez que votre main.py inclut correctement le router questionnaires")
    print("2. Vérifiez que le prefix des routes est correct")
    print("3. Redémarrez le serveur après modifications")
    print("4. Consultez /docs pour voir toutes les routes disponibles")
    
    print("\n🔧 Configuration recommandée dans main.py:")
    print("""
app.include_router(
    questionnaires_router,
    prefix="/api/v1",  # Le router questionnaires a déjà /questionnaires
    tags=["questionnaires"]
)
""")

if __name__ == "__main__":
    main()