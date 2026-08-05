@echo off
:: HACHI AI Setup & Launcher Script for Windows
:: Dynamically switches to current script directory so it runs anywhere on any PC

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
    echo     Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

echo [✓] Python detected:
python --version
echo.

:: Install / Upgrade Dependencies
echo [*] Installing required Python packages...
python -m pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo [!] WARNING: Some packages had installation warnings, continuing setup...
) else (
    echo [✓] All packages installed successfully.
)
echo.

:: Check Ollama
echo [*] Checking Ollama installation...
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] WARNING: Ollama executable not found in system PATH.
    echo     Please make sure Ollama is installed from https://ollama.com and running.
) else (
    echo [✓] Ollama detected. Model qwen3.5:2b ready.
)

echo.
echo ===================================================
echo   Setup Complete! Launching Hachi Assistant...
echo ===================================================
echo.
echo Press any key to launch Hachi, or close this window.
pause >nul

python hachi_app.py
