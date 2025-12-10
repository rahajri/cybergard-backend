#!/bin/bash

# Import CyberGuard Pro pour service audit_postgres
set -e

echo "Import CyberGuard Pro"
echo "Service: audit_postgres"
echo "======================"

# Chemins
BACKUP_FILE="../../backup2.sql"
COMPOSE_DIR="../"

# Vérifications
if [ ! -f "$BACKUP_FILE" ]; then
    echo "Erreur: backup2.sql non trouvé"
    exit 1
fi

if [ ! -f "${COMPOSE_DIR}docker-compose.yml" ]; then
    echo "Erreur: docker-compose.yml non trouvé"
    exit 1
fi

echo "Fichiers OK"

# Se placer dans le dossier backend
cd $COMPOSE_DIR

# Vérifier le fichier .env
if [ ! -f ".env" ]; then
    echo "Attention: fichier .env non trouvé"
    echo "Variables par défaut utilisées"
    export POSTGRES_DB="${POSTGRES_DB:-audit_platform}"
    export POSTGRES_USER="${POSTGRES_USER:-postgres}"
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
    export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
else
    echo "Fichier .env trouvé"
    source .env
fi

echo "Variables PostgreSQL:"
echo "  DB: ${POSTGRES_DB:-audit_platform}"
echo "  User: ${POSTGRES_USER:-postgres}"
echo "  Port: ${POSTGRES_PORT:-5432}"

# 1. Arrêt propre
echo ""
echo "1. Arrêt containers..."
docker-compose down -v 2>/dev/null || true

# 2. Nettoyage volume
echo "2. Nettoyage données PostgreSQL..."
docker volume rm backend_pg_data 2>/dev/null || true
docker volume rm $(basename $(pwd))_pg_data 2>/dev/null || true

# 3. Démarrage PostgreSQL
echo "3. Démarrage audit_postgres..."
docker-compose up -d audit_postgres

# 4. Attente PostgreSQL
echo "4. Attente PostgreSQL..."
max_attempts=30
attempt=1

while [ $attempt -le $max_attempts ]; do
    if docker exec audit_postgres pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-audit_platform} >/dev/null 2>&1; then
        echo "   PostgreSQL prêt (${attempt}/${max_attempts})"
        break
    fi
    
    if [ $attempt -eq $max_attempts ]; then
        echo "   Timeout après $max_attempts tentatives"
        echo "   Status container:"
        docker ps | grep audit_postgres
        echo "   Logs:"
        docker-compose logs audit_postgres | tail -15
        exit 1
    fi
    
    sleep 2
    attempt=$((attempt + 1))
    echo -n "."
done

# 5. Import backup
echo ""
echo "5. Import backup2.sql..."
if cat ../backup2.sql | docker exec -i audit_postgres psql -U ${POSTGRES_USER:-postgres} -d audit_platform; then
    echo "   Import réussi"
else
    echo "   Erreur import"
    echo "   Derniers logs:"
    docker-compose logs audit_postgres | tail -10
    exit 1
fi

# 6. Vérifications
echo "6. Vérifications..."
TABLES=$(docker exec audit_postgres psql -U ${POSTGRES_USER:-postgres} -d audit_platform -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' ')
FRAMEWORKS=$(docker exec audit_postgres psql -U ${POSTGRES_USER:-postgres} -d audit_platform -t -c "SELECT count(*) FROM framework;" 2>/dev/null | tr -d ' ')
REQUIREMENTS=$(docker exec audit_postgres psql -U ${POSTGRES_USER:-postgres} -d audit_platform -t -c "SELECT count(*) FROM requirement;" 2>/dev/null | tr -d ' ')

echo "   Tables: $TABLES"
echo "   Référentiels: $FRAMEWORKS"
echo "   Exigences: $REQUIREMENTS"

# 7. Démarrage autres services
echo "7. Démarrage autres services..."
docker-compose up -d

sleep 3

echo ""
echo "Import terminé avec succès"
echo "========================="
docker-compose ps
echo ""
echo "Connexion: docker exec -it audit_postgres psql -U ${POSTGRES_USER:-postgres} -d audit_platform"
