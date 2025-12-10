"""
Script de test pour l'intégration Redis
"""

import asyncio
import sys
import os

# Fix encoding pour Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Ajoute le chemin du backend au PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils.redis_manager import redis_manager
from src.config import settings


async def test_redis_connection():
    """Test de connexion à Redis"""
    print("=" * 60)
    print("TEST 1: Connexion à Redis")
    print("=" * 60)

    redis_manager.connect()

    if redis_manager.is_connected:
        print("✅ Redis connecté avec succès!")
        print(f"   - Host: {settings.redis_host}")
        print(f"   - Port: {settings.redis_port}")
        print(f"   - DB: {settings.redis_db}")
    else:
        print("❌ Impossible de se connecter à Redis")
        return False

    return True


async def test_cache_operations():
    """Test des opérations de cache"""
    print("\n" + "=" * 60)
    print("TEST 2: Opérations de cache")
    print("=" * 60)

    # Test SET
    print("\n1. Test SET...")
    success = redis_manager.set("test:key", {"message": "Hello Redis!"}, ttl=60)
    if success:
        print("   ✅ SET réussi")
    else:
        print("   ❌ SET échoué")
        return False

    # Test GET
    print("\n2. Test GET...")
    value = redis_manager.get("test:key")
    if value and value.get("message") == "Hello Redis!":
        print(f"   ✅ GET réussi: {value}")
    else:
        print(f"   ❌ GET échoué: {value}")
        return False

    # Test EXISTS
    print("\n3. Test EXISTS...")
    exists = redis_manager.exists("test:key")
    if exists:
        print("   ✅ EXISTS réussi")
    else:
        print("   ❌ EXISTS échoué")
        return False

    # Test TTL
    print("\n4. Test GET_TTL...")
    ttl = redis_manager.get_ttl("test:key")
    if ttl and ttl > 0:
        print(f"   ✅ GET_TTL réussi: {ttl}s restantes")
    else:
        print(f"   ❌ GET_TTL échoué: {ttl}")

    # Test DELETE
    print("\n5. Test DELETE...")
    deleted = redis_manager.delete("test:key")
    if deleted:
        print("   ✅ DELETE réussi")
    else:
        print("   ❌ DELETE échoué")
        return False

    return True


async def test_rate_limiting():
    """Test du rate limiting"""
    print("\n" + "=" * 60)
    print("TEST 3: Rate Limiting")
    print("=" * 60)

    identifier = "test_user_123"
    max_requests = 5
    window = 10

    print(f"\nConfiguration: {max_requests} requêtes max en {window}s")

    # Fait plusieurs requêtes
    for i in range(max_requests + 2):
        allowed, remaining = redis_manager.check_rate_limit(
            identifier=identifier,
            max_requests=max_requests,
            window=window
        )

        status = "✅ Autorisée" if allowed else "❌ Bloquée"
        print(f"   Requête {i+1}: {status} (restantes: {remaining})")

    # Nettoie
    redis_manager.reset_rate_limit(identifier)
    print("\n   ✅ Rate limit réinitialisé")

    return True


async def test_ai_cache():
    """Test du cache IA"""
    print("\n" + "=" * 60)
    print("TEST 4: Cache IA")
    print("=" * 60)

    model = "deepseek-test"
    prompt_hash = "abc123def456"
    result = {"points_de_controle": ["PC1", "PC2", "PC3"]}

    # Mise en cache
    print("\n1. Test CACHE_AI_RESULT...")
    success = redis_manager.cache_ai_result(model, prompt_hash, result, ttl=300)
    if success:
        print("   ✅ Résultat IA mis en cache")
    else:
        print("   ❌ Échec mise en cache IA")
        return False

    # Récupération du cache
    print("\n2. Test GET_CACHED_AI_RESULT...")
    cached = redis_manager.get_cached_ai_result(model, prompt_hash)
    if cached and cached == result:
        print(f"   ✅ Résultat récupéré: {cached}")
    else:
        print(f"   ❌ Récupération échouée: {cached}")
        return False

    # Effacement du cache
    print("\n3. Test CLEAR_AI_CACHE...")
    deleted = redis_manager.clear_ai_cache(model)
    if deleted >= 1:
        print(f"   ✅ Cache IA effacé ({deleted} clés)")
    else:
        print(f"   ⚠️ Aucune clé effacée: {deleted}")

    return True


async def test_session_management():
    """Test de la gestion des sessions"""
    print("\n" + "=" * 60)
    print("TEST 5: Gestion des Sessions")
    print("=" * 60)

    session_id = "session_test_123"
    session_data = {
        "user_id": "user_456",
        "username": "test_user",
        "role": "admin"
    }

    # Créer une session
    print("\n1. Test SET_SESSION...")
    success = redis_manager.set_session(session_id, session_data, ttl=600)
    if success:
        print("   ✅ Session créée")
    else:
        print("   ❌ Échec création session")
        return False

    # Récupérer la session
    print("\n2. Test GET_SESSION...")
    session = redis_manager.get_session(session_id)
    if session and session.get("user_id") == "user_456":
        print(f"   ✅ Session récupérée: {session}")
    else:
        print(f"   ❌ Récupération session échouée: {session}")
        return False

    # Supprimer la session
    print("\n3. Test DELETE_SESSION...")
    deleted = redis_manager.delete_session(session_id)
    if deleted:
        print("   ✅ Session supprimée")
    else:
        print("   ❌ Échec suppression session")
        return False

    return True


async def test_stats():
    """Test des statistiques Redis"""
    print("\n" + "=" * 60)
    print("TEST 6: Statistiques Redis")
    print("=" * 60)

    stats = redis_manager.get_stats()

    if stats.get("status") == "connected":
        print("\n✅ Statistiques Redis:")
        print(f"   - Version: {stats.get('version')}")
        print(f"   - Uptime: {stats.get('uptime_seconds')}s")
        print(f"   - Clients connectés: {stats.get('connected_clients')}")
        print(f"   - Mémoire utilisée: {stats.get('used_memory_human')}")
        print(f"   - Commandes traitées: {stats.get('total_commands')}")
        return True
    else:
        print(f"\n❌ Erreur récupération stats: {stats}")
        return False


async def run_all_tests():
    """Exécute tous les tests"""
    print("\n" + "=" * 60)
    print("🧪 TESTS D'INTÉGRATION REDIS - AI CYBER")
    print("=" * 60)

    results = []

    # Test 1: Connexion
    results.append(("Connexion", await test_redis_connection()))

    if not results[-1][1]:
        print("\n❌ ÉCHEC: Impossible de se connecter à Redis")
        print("Vérifiez que Redis est démarré:")
        print("  cd backend && docker-compose up -d redis")
        return

    # Test 2: Cache operations
    results.append(("Cache Operations", await test_cache_operations()))

    # Test 3: Rate limiting
    results.append(("Rate Limiting", await test_rate_limiting()))

    # Test 4: AI Cache
    results.append(("AI Cache", await test_ai_cache()))

    # Test 5: Sessions
    results.append(("Session Management", await test_session_management()))

    # Test 6: Stats
    results.append(("Statistiques", await test_stats()))

    # Résumé
    print("\n" + "=" * 60)
    print("📊 RÉSUMÉ DES TESTS")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status} - {name}")

    print(f"\n   Total: {passed}/{total} tests réussis")

    if passed == total:
        print("\n🎉 TOUS LES TESTS SONT PASSÉS!")
    else:
        print(f"\n⚠️ {total - passed} test(s) échoué(s)")

    # Nettoyage
    print("\n" + "=" * 60)
    print("🧹 Nettoyage...")
    print("=" * 60)
    redis_manager.disconnect()
    print("✅ Connexion Redis fermée")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
