@echo off
chcp 65001 > nul
cd /d "%~dp0"
:: Поиск pythonw: сначала локальный лаунчер zapret-manager.exe
:: (виден в диспетчере задач по поиску "zapret"), затем настоящий
:: python.org. Store-алиасы из WindowsApps пропускаем: под ними
:: таскбар принудительно показывает иконку Python вместо нашей.
set "PYW=%~dp0zapret-manager.exe"
if not exist "%PYW%" set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
if not exist "%PYW%" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if not exist "%PYW%" set "PYW=C:\Python314\pythonw.exe"
if not exist "%PYW%" set "PYW=C:\Python313\pythonw.exe"
if not exist "%PYW%" (
    set "PYW="
    for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do (
        echo %%P | findstr /I /C:"WindowsApps" >nul
        if errorlevel 1 if not defined PYW set "PYW=%%P"
    )
)
if not defined PYW set "PYW=pythonw.exe"
:: Проверка прав администратора. winws/WinDivert требуют админа.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Zapret Manager: запрашиваю права администратора...
    powershell -NoProfile -Command "Start-Process '%PYW%' -ArgumentList '\"%~dp0app.py\"' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)
start "" /min "%PYW%" "%~dp0app.py"
