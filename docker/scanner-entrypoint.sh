#!/bin/bash
# ============================================================================
# SCANNER WORKER ENTRYPOINT
# ============================================================================
# Script d'entrée pour le container scanner-worker
# Vérifie les dépendances et lance le worker Celery

set -e

echo "🔍 CyberGuard AI - Scanner Worker"
echo "=================================="

# ============================================================================
# VÉRIFICATIONS PRÉ-DÉMARRAGE
# ============================================================================

# Vérifier nmap
echo "📡 Vérification nmap..."
if command -v nmap &> /dev/null; then
    NMAP_VERSION=$(nmap --version | head -n 1)
    echo "✅ $NMAP_VERSION"
else
    echo "❌ nmap non installé!"
    exit 1
fi

# Vérifier sslyze
echo "🔐 Vérification sslyze..."
if python -c "import sslyze; print(f'sslyze version {sslyze.__version__}')" 2>/dev/null; then
    echo "✅ sslyze disponible"
else
    echo "⚠️ sslyze non disponible (installation en cours...)"
    pip install sslyze --quiet
fi

# Vérifier connexion Redis
echo "📦 Vérification Redis..."
REDIS_HOST=${REDIS_HOST:-redis}
REDIS_PORT=${REDIS_PORT:-6379}

for i in {1..30}; do
    if nc -z $REDIS_HOST $REDIS_PORT 2>/dev/null; then
        echo "✅ Redis accessible sur $REDIS_HOST:$REDIS_PORT"
        break
    fi
    echo "⏳ Attente Redis... ($i/30)"
    sleep 2
done

if ! nc -z $REDIS_HOST $REDIS_PORT 2>/dev/null; then
    echo "❌ Redis non accessible après 60s"
    exit 1
fi

# Vérifier connexion PostgreSQL
echo "🐘 Vérification PostgreSQL..."
DB_HOST=${DB_HOST:-db}
DB_PORT=${DB_PORT:-5432}

for i in {1..30}; do
    if nc -z $DB_HOST $DB_PORT 2>/dev/null; then
        echo "✅ PostgreSQL accessible sur $DB_HOST:$DB_PORT"
        break
    fi
    echo "⏳ Attente PostgreSQL... ($i/30)"
    sleep 2
done

if ! nc -z $DB_HOST $DB_PORT 2>/dev/null; then
    echo "❌ PostgreSQL non accessible après 60s"
    exit 1
fi

# ============================================================================
# CONFIGURATION CELERY
# ============================================================================

CELERY_CONCURRENCY=${SCANNER_CONCURRENCY:-2}
CELERY_LOGLEVEL=${LOG_LEVEL:-INFO}
CELERY_QUEUE=${SCANNER_QUEUE:-external_scan}

echo ""
echo "⚙️ Configuration Celery Worker:"
echo "   Queue: $CELERY_QUEUE"
echo "   Concurrency: $CELERY_CONCURRENCY"
echo "   Log Level: $CELERY_LOGLEVEL"
echo ""

# ============================================================================
# DÉMARRAGE WORKER
# ============================================================================

echo "🚀 Démarrage du Scanner Worker..."
echo ""

exec celery -A src.tasks.celery_app worker \
    --queues=$CELERY_QUEUE \
    --concurrency=$CELERY_CONCURRENCY \
    --loglevel=$CELERY_LOGLEVEL \
    --hostname=scanner@%h \
    --prefetch-multiplier=1 \
    --task-events \
    "$@"
