@echo off
:: HACHI AI - Force Shutdown & RAM Cleanup Script
:: Performs an instant "End Task" on Ollama and closes Hachi.
:: (Also called by the in-app "shutdown" command.)
:: ============================================================

cd /d "%~dp0"

echo.
echo ===================================================
echo   HACHI - Shutting Down ^& Cleaning System RAM
echo ===================================================
echo.

echo [*] Force stopping all Ollama AI background processes...
taskkill /F /T /IM "ollama.exe" >nul 2>&1
taskkill /F /T /IM "ollama_llama_server.exe" >nul 2>&1
taskkill /F /T /IM "Ollama app.exe" >nul 2>&1
:: Fallback via PowerShell process name
powershell -c "Get-Process -Name *ollama* -ErrorAction SilentlyContinue | Stop-Process -Force" >nul 2>&1

echo [OK] Ollama background tasks terminated. RAM freed!
echo.

echo [*] Closing Hachi Python Application...
:: Use WMI (Win32_Process) to access CommandLine property (Get-Process does not expose it).
powershell -c "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*hachi_app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
:: Broad fallback: kill any python process referencing hachi (catches venv python too)
powershell -c "Get-WmiObject Win32_Process | Where-Object { $_.Name -like '*python*' -and $_.CommandLine -like '*hachi*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo [OK] Hachi completely shut down.

echo [*] Cleaning up leftover TTS temp files...
del /q "%TEMP%\hachi_*.mp3" >nul 2>&1
echo [OK] Temp files cleared.

timeout /t 2 /nobreak >nul
