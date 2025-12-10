#!/usr/bin/env python3
"""
Script pour générer les embeddings sur les données existantes
"""

import sys
import os
import time
from datetime import datetime

# Ajouter le répertoire courant au path pour les imports absolus
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Imports absolus
from src.database import get_db
from src.models.audit import Framework, Requirement
from sqlalchemy import text

def test_imports():
    """Tester que les imports fonctionnent"""
    try:
        from src.services.embedding_service import EmbeddingService, RequirementEmbeddingService
        print("✅ Imports réussis")
        
        # Tester l'initialisation du service
        service = EmbeddingService()
        print("✅ Service d'embedding initialisé")
        
        return True
    except Exception as e:
        print(f"❌ Erreur d'import: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def get_frameworks_stats():
    """Récupérer les stats des frameworks"""
    db = next(get_db())
    try:
        result = db.execute(text("""
            SELECT 
                f.id,
                f.code,
                f.name,
                f.language,
                COUNT(r.id) as requirement_count,
                COUNT(re.id) as embedding_count
            FROM framework f
            LEFT JOIN requirement r ON f.id = r.framework_id
            LEFT JOIN requirement_embeddings re ON r.id = re.requirement_id
            WHERE f.is_active = true
            GROUP BY f.id, f.code, f.name, f.language
            ORDER BY f.created_at
        """))
        
        frameworks = []
        for row in result:
            frameworks.append({
                'id': str(row.id),
                'code': row.code,
                'name': row.name,
                'language': row.language,
                'requirements': row.requirement_count,
                'embeddings': row.embedding_count
            })
        
        return frameworks
    finally:
        db.close()

def generate_framework_embeddings(framework_id):
    """Générer les embeddings pour un framework"""
    from src.services.embedding_service import RequirementEmbeddingService
    
    db = next(get_db())
    try:
        service = RequirementEmbeddingService(db)
        return service.generate_requirement_embeddings(framework_id)
    finally:
        db.close()

def test_similarity():
    """Tester la recherche par similarité"""
    from src.services.embedding_service import RequirementEmbeddingService
    
    db = next(get_db())
    try:
        service = RequirementEmbeddingService(db)
        
        # Test avec une requête simple
        print("\n🔍 Test de similarité avec 'politique sécurité':")
        results = service.find_similar_requirements(
            query_text="politique sécurité",
            limit=3
        )
        
        if results:
            for i, result in enumerate(results, 1):
                print(f"  {i}. {result['official_code']} - {result['title'][:60]}...")
                print(f"     Similarité: {result['similarity_score']:.3f}")
        else:
            print("  Aucun résultat trouvé")
            
    except Exception as e:
        print(f"❌ Erreur test similarité: {str(e)}")
    finally:
        db.close()

def main():
    print("🚀 Génération d'embeddings CyberGuard Pro")
    print("=" * 50)
    
    # Test des imports d'abord
    if not test_imports():
        print("❌ Échec des imports - Arrêt du script")
        return
    
    # Récupérer les stats initiales
    print("\n📊 État de la base de données:")
    frameworks = get_frameworks_stats()
    
    if not frameworks:
        print("❌ Aucun framework trouvé")
        return
    
    total_requirements = sum(f['requirements'] for f in frameworks)
    total_embeddings = sum(f['embeddings'] for f in frameworks)
    
    print(f"Frameworks: {len(frameworks)}")
    print(f"Requirements: {total_requirements}")
    print(f"Embeddings existants: {total_embeddings}")
    
    for fw in frameworks:
        status = "✅" if fw['embeddings'] == fw['requirements'] else "⚠️"
        print(f"  {status} {fw['code']}: {fw['embeddings']}/{fw['requirements']} ({fw['language']})")
    
    # Génération
    print(f"\n🔄 Génération en cours...")
    start_time = time.time()
    
    total_generated = 0
    total_errors = 0
    
    for fw in frameworks:
        print(f"\n📖 {fw['code']} ({fw['name']})...")
        
        try:
            result = generate_framework_embeddings(fw['id'])
            
            if 'error' in result:
                print(f"   ❌ {result['error']}")
                total_errors += 1
            else:
                generated = result.get('embeddings_generated', 0)
                errors = result.get('errors', 0)
                
                print(f"   ✅ Généré: {generated}")
                if errors > 0:
                    print(f"   ⚠️ Erreurs: {errors}")
                
                total_generated += generated
                total_errors += errors
                
        except Exception as e:
            print(f"   ❌ Exception: {str(e)}")
            total_errors += 1
    
    # Résultats finaux
    duration = time.time() - start_time
    print(f"\n📋 Résultats:")
    print(f"✅ Embeddings générés: {total_generated}")
    print(f"❌ Erreurs: {total_errors}")
    print(f"⏱️ Durée: {duration:.2f}s")
    
    if total_generated > 0:
        print(f"📊 Moyenne: {duration/total_generated:.3f}s par embedding")
        
        # Test de similarité
        test_similarity()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ Interruption utilisateur")
    except Exception as e:
        print(f"\n❌ Erreur critique: {str(e)}")
        import traceback
        traceback.print_exc()