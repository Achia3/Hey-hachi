@echo off
:: HACHI AI - 1-Click Automated Launcher
:: Starts Ollama automatically in background and runs Hachi

cd /d "%~dp0"

echo.
echo ===================================================
echo   HACHI - Agentic AI Voice Assistant Launcher
echo ===================================================
echo.

:: Check Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found on PATH. Please install Python 3.10+ and try again.
    pause
    exit /b 1
)

:: Check if Ollama is already running by querying its API (more reliable than netstat)
:: netstat :11434 can match any process on that port, not just Ollama
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:11434 2>nul | findstr "200" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Starting Ollama engine in background...
    start /b ollama serve >nul 2>&1
    :: Wait for Ollama to be ready (up to 10 seconds)
    set "attempts=0"
    :wait_ollama
    timeout /t 1 /nobreak >nul
    curl -s -o nul -w "%%{http_code}" http://127.0.0.1:11434 2>nul | findstr "200" >nul 2>&1
    if %errorlevel% neq 0 (
        set /a attempts+=1
        if %attempts% lss 10 goto wait_ollama
        echo [WARNING] Ollama may not be fully ready. Hachi will retry on startup.
    ) else (
        echo [OK] Ollama engine is active.
    )
) else (
    echo [OK] Ollama engine is already active.
)

echo [*] Starting Hachi Desktop Application...
python hachi_app.py
