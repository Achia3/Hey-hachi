@echo off
:: HACHI AI - Force Shutdown & RAM Cleanup Script
:: Performs an instant "End Task" on Ollama and closes Hachi

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
:: FIXED: Use WMI (Win32_Process) to access CommandLine property.
:: Get-Process does NOT expose CommandLine; Win32_Process/CIM_Process does.
powershell -c "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*hachi_app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
:: Broad fallback: kill any python process referencing hachi (catches venv python too)
powershell -c "Get-WmiObject Win32_Process | Where-Object { $_.Name -like '*python*' -and $_.CommandLine -like '*hachi*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo [OK] Hachi completely shut down.
timeout /t 2 /nobreak >nul
