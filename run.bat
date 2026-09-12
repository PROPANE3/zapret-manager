@echo off
chcp 65001 > nul
cd /d "%~dp0"
:: Проверка прав администратора. winws/WinDivert требуют админа.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Запрашиваю права администратора...
    powershell -NoProfile -Command "Start-Process 'pythonw.exe' -ArgumentList '\"%~dp0app.py\"' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)
start "" /min pythonw.exe "%~dp0app.py"
