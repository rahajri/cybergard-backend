@echo off
echo ========================================
echo Demarrage du serveur backend
echo ========================================
echo.
echo Tuez tous les processus Python existants...
taskkill /F /IM python.exe /T 2>nul

echo.
echo Attente de 2 secondes...
timeout /t 2 /nobreak >nul

echo.
echo Demarrage du serveur sur http://localhost:8000
echo Les logs s'afficheront ci-dessous...
echo Appuyez sur Ctrl+C pour arreter le serveur
echo ========================================
echo.

cd /d "%~dp0"
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

pause
