@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo Создание ярлыка Zapret Manager на рабочем столе...
for /f "delims=" %%D in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESK=%%D"
if not defined DESK (
    echo Не удалось найти рабочий стол
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESK%\Zapret Manager.lnk');$s.TargetPath='%~dp0run.bat';$s.WorkingDirectory='%~dp0';$s.IconLocation='%~dp0assets\icon.ico,0';$s.Description='Zapret Manager';$s.Save()"
echo.
echo Готово: "%DESK%\Zapret Manager.lnk"
echo.
echo Лаунчер zapret-manager.exe (процесс будет виден в диспетчере задач)...
set "SRCW="
for %%C in (
    "%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
    "C:\Python314\pythonw.exe"
    "C:\Python313\pythonw.exe"
) do if not defined SRCW if exist %%C set "SRCW=%%~C"
if not defined SRCW (
    echo Не найден настоящий python.org, только Store — пропускаю лаунчер.
    echo Запускайте приложение двойным кликом по ярлыку.
    pause
    exit /b 0
)
for %%I in ("%SRCW%") do set "SRCDIR=%%~dpI"
set "SRCDIR=%SRCDIR:~0,-1%"
copy /Y "%SRCW%" "%~dp0zapret-manager.exe" >nul
if errorlevel 1 (
    echo Не удалось скопировать лаунчер.
    pause
    exit /b 1
)
for %%D in ("%SRCDIR%\python3*.dll") do copy /Y "%%D" "%~dp0" >nul
for %%D in ("%SRCDIR%\vcruntime*.dll") do copy /Y "%%D" "%~dp0" >nul
> "%~dp0pyvenv.cfg" echo home = %SRCDIR%
>> "%~dp0pyvenv.cfg" echo include-system-site-packages = true
echo Лаунчер готов: "%~dp0zapret-manager.exe"
echo Запускайте приложение двойным кликом по ярлыку.
pause
