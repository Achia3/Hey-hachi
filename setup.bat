@echo off
REM HACHI AI Setup Script for Windows
REM This script installs all dependencies and prepares the environment

echo.
echo ============================================
echo   HACHI - AI Voice Assistant Setup
echo ============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from python.org
    pause
    exit /b 1
)

echo [✓] Python detected
python --version
echo.

REM Install pip requirements
echo [*] Installing required packages...
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo ERROR: Failed to install requirements
    pause
    exit /b 1
)

echo [✓] All packages installed successfully
echo.

REM Check Ollama
echo [*] Checking Ollama installation...
where ollama >nul 2>&1

if %errorlevel% neq 0 (
    echo WARNING: Ollama not found in PATH
    echo Please ensure Ollama is installed and running
    echo Download from: https://ollama.ai
    echo.
)

echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo Next steps:
echo 1. Make sure Ollama is running: ollama serve
echo 2. Run: python hachi_gui.py
echo.
pause
