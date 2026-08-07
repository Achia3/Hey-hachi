@echo off
:: ============================================================
:: HACHI AI - Smart 1-Click Launcher
:: Finds Ollama automatically, starts it, then runs Hachi.
:: Uses PowerShell for health checks (no curl dependency).
:: ============================================================
setlocal EnableExtensions
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
where ollama >nul 2>&1
if %errorlevel% equ 0 (
    set "OLLAMA_EXE=ollama"
    goto :found_ollama
)
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    goto :found_ollama
)
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
call :check_ollama >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Ollama engine is already running.
    goto :ensure_model
)

echo [*] Starting Ollama engine in background...
start "OllamaServer" /min "%OLLAMA_EXE%" serve

:: Poll up to 15 seconds for Ollama to become ready
set "attempts=0"
:wait_loop
timeout /t 1 /nobreak >nul
call :check_ollama >nul 2>&1
if %errorlevel% equ 0 goto :ollama_ready
set /a attempts+=1
if %attempts% lss 15 goto :wait_loop
echo [WARNING] Ollama is taking a while. Hachi will keep retrying internally.
goto :launch_hachi

:ollama_ready
echo [OK] Ollama engine is ready.

:: ── Step 4: Ensure Ollama Model is Ready ───────────────────────
:ensure_model
echo [*] Checking config.json for configured model...
for /f "tokens=*" %%i in ('powershell -NoProfile -Command "(Get-Content config.json -ErrorAction SilentlyContinue | ConvertFrom-Json).model_name"') do set "MODEL_NAME=%%i"
if "%MODEL_NAME%"=="" set "MODEL_NAME=qwen2.5:3b"
echo [*] Ensuring model: %MODEL_NAME% (pulling if missing)...
"%OLLAMA_EXE%" pull %MODEL_NAME%

:: ── Step 5: Launch Hachi ─────────────────────────────────────
:launch_hachi
echo.
echo [*] Starting Hachi...
echo     Close this window or tell Hachi "turn off" to stop.
echo.
python hachi_app.py

:: ── Step 6: Cleanup prompt (matches the README promise) ─────
echo.
echo [*] Hachi exited.
set "STOPOLLAMA="
set /p "STOPOLLAMA=Free up RAM by stopping Ollama? (Y/N): "
if /i "%STOPOLLAMA%"=="Y" (
    echo [*] Stopping Ollama and cleaning up...
    call stop.bat
) else (
    echo [OK] Leaving Ollama running in the background.
)
pause
exit /b 0

:: ── Helper: returns 0 if Ollama API is up, else 1 ────────────
:check_ollama
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
exit /b %errorlevel%
