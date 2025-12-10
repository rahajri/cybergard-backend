@echo off
echo ========================================
echo Arret de tous les processus Python
echo ========================================
echo.

taskkill /F /IM python.exe /T 2>nul

if %ERRORLEVEL% EQU 0 (
    echo ✓ Tous les processus Python ont ete arretes
) else (
    echo ℹ Aucun processus Python en cours d'execution
)

echo.
echo ========================================
echo Verification du port 8000...
echo ========================================
netstat -ano | findstr ":8000" | findstr "LISTENING"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ⚠ Il reste des processus sur le port 8000
    echo Voulez-vous les tuer? (O/N)
    set /p choice=
    if /i "%choice%"=="O" (
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
            echo Arret du processus %%a...
            taskkill /F /PID %%a 2>nul
        )
    )
) else (
    echo ✓ Le port 8000 est libre
)

echo.
echo ========================================
echo Termine!
echo ========================================
echo.
echo Vous pouvez maintenant demarrer le serveur avec:
echo   start_server.bat
echo.
pause
