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
echo Запускайте приложение двойным кликом по ярлыку.
pause
