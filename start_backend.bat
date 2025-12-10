@echo off
REM Script de démarrage du backend avec logs en temps réel (Windows)

echo ==============================================
echo 🚀 Démarrage du backend CyberGuard Pro
echo ==============================================
echo 📍 Port: 8000
echo 📊 Logs: Temps réel activé
echo ==============================================
echo.

cd /d "%~dp0"

REM Lancer uvicorn avec logs en temps réel
REM -u : unbuffered (force l'affichage immédiat)
REM --log-level info : niveau de log détaillé
echo 🔄 Lancement d'uvicorn...
echo.

python -u -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload --log-level info --access-log
