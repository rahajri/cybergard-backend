#!/bin/bash
# Script de démarrage du backend avec logs en temps réel

echo "🚀 Démarrage du backend CyberGuard Pro..."
echo "📍 Port: 8000"
echo "📊 Logs: Temps réel activé"
echo ""

# Se placer dans le répertoire backend
cd "$(dirname "$0")"

# Charger les variables d'environnement
if [ -f .env ]; then
    echo "✅ Chargement du fichier .env"
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "⚠️  Fichier .env non trouvé"
fi

# Lancer uvicorn avec logs en temps réel
# -u : unbuffered (force l'affichage immédiat)
# --log-level info : niveau de log détaillé
echo "🔄 Lancement d'uvicorn..."
echo ""

python -u -m uvicorn src.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --log-level info \
    --access-log
