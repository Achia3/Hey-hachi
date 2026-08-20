@echo off
:: HACHI AI Setup & Launcher Script for Windows
:: Dynamically switches to current script directory so it runs anywhere on any PC.
:: Installs dependencies, verifies Ollama, then hands off to run.bat (which
:: starts Ollama + the app together).
:: ============================================================

cd /d "%~dp0"

echo.
echo ===================================================
echo   HACHI - Agentic AI Voice Assistant Setup
echo ===================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] ERROR: Python is not installed or not added to PATH.
    echo     Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
echo [OK] Python detected:
python --version
echo.

:: Check if pip is available
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] ERROR: pip is not available. Reinstall Python and tick "Add to PATH".
    pause
    exit /b 1
)

:: Install / Upgrade Dependencies
echo [*] Installing required Python packages...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [!] WARNING: Some packages had installation warnings, continuing setup...
) else (
    echo [OK] All packages installed successfully.
)
echo.

:: Check Ollama
echo [*] Checking Ollama installation...
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] WARNING: Ollama executable not found in system PATH.
    echo     Please install it from https://ollama.com
) else (
    echo [OK] Ollama detected.
    echo [*] Verifying model 'hachi-master'...
    ollama list | findstr /i "hachi-master" >nul 2>&1
    if %errorlevel% equ 0 (
        echo [OK] Model 'hachi-master' is installed and ready.
    ) else (
        if exist "gguf\v5\Modelfile" (
            echo [*] Registering 'hachi-master' from gguf\v5\Modelfile...
            pushd "%~dp0gguf\v5"
            ollama create hachi-master -f Modelfile
            popd
        ) else if exist "MODEL\Modelfile" (
            echo [*] Registering 'hachi-master' from MODEL\Modelfile...
            pushd "%~dp0MODEL"
            ollama create hachi-master -f Modelfile
            popd
        ) else (
            echo [*] Pulling fallback model qwen3.5:2b...
            ollama pull qwen3.5:2b
        )
    )
)
echo.

echo ===================================================
echo   Setup Complete!
echo ===================================================
echo.
echo To launch Hachi:  double-click  run.bat
echo   ^(starts Ollama in the background, then opens the app^)
echo.
set "LAUNCH="
set /p "LAUNCH=Launch Hachi now? (Y/N): "
if /i "%LAUNCH%"=="Y" call run.bat
echo.
pause
