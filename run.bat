@echo off
:: ============================================================
:: HACHI AI - Smart 1-Click Launcher
:: Finds Ollama automatically, starts it, then runs Hachi.
:: ============================================================

cd /d "%~dp0"

echo.
echo ===================================================
echo   HACHI - Agentic AI Voice Assistant
echo ===================================================
echo.

:: ── Step 1: Verify Python ───────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found on PATH.
    echo         Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
echo [OK] Python found.

:: ── Step 2: Find Ollama (PATH first, then known install dirs) ──
set "OLLAMA_EXE="

:: Check if it's on PATH
where ollama >nul 2>&1
if %errorlevel% equ 0 (
    set "OLLAMA_EXE=ollama"
    goto :found_ollama
)

:: Check per-user install location (most common)
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    goto :found_ollama
)

:: Check system-wide install
if exist "C:\Program Files\Ollama\ollama.exe" (
    set "OLLAMA_EXE=C:\Program Files\Ollama\ollama.exe"
    goto :found_ollama
)

echo [ERROR] Ollama not found. Please install from https://ollama.com/download
pause
exit /b 1

:found_ollama
echo [OK] Ollama located.

:: ── Step 3: Check if Ollama is already running ──────────────
curl -s --max-time 2 http://127.0.0.1:11434/api/tags >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Ollama engine is already running.
    goto :launch_hachi
)

:: Start Ollama in a hidden background window
echo [*] Starting Ollama engine in background...
start "OllamaServer" /min "%OLLAMA_EXE%" serve

:: Poll up to 15 seconds for Ollama to become ready
set "attempts=0"
:wait_loop
timeout /t 1 /nobreak >nul
curl -s --max-time 1 http://127.0.0.1:11434/api/tags >nul 2>&1
if %errorlevel% equ 0 goto :ollama_ready
set /a attempts+=1
if %attempts% lss 15 goto :wait_loop
echo [WARNING] Ollama is taking a while. Hachi will keep retrying internally.
goto :launch_hachi

:ollama_ready
echo [OK] Ollama engine is ready.

:: ── Step 4: Launch Hachi ─────────────────────────────────────
:launch_hachi
echo.
echo [*] Starting Hachi...
echo     Close this window or tell Hachi "turn off" to stop.
echo.

python hachi_app.py

echo.
echo [*] Hachi exited.
pause
