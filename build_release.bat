@echo off
chcp 65001 > nul
cd /d "%~dp0"
:: Сборка запечённого zip для пользователя: распаковал -> run.bat -> мастер.
:: Никаких install.bat руками: ярлык и лаунчер приложение создаст само.
for /f "tokens=3 delims= " %%V in ('findstr /R "^APP_VERSION *= *" app.py') do set "VER=%%V"
set "VER=%VER:"=%"
if not defined VER (
    echo Не нашёл APP_VERSION в app.py
    pause
    exit /b 1
)
echo %VER% > version.txt
set "NAME=ZapretManager-v%VER%"
set "DIST=%~dp0dist\%NAME%"
echo Сборка %NAME% ...
if exist "%DIST%" rmdir /S /Q "%DIST%"
mkdir "%DIST%" >nul 2>&1
mkdir "%DIST%\assets" >nul 2>&1
copy /Y app.py "%DIST%\" >nul
copy /Y run.bat "%DIST%\" >nul
copy /Y version.txt "%DIST%\" >nul
copy /Y requirements.txt "%DIST%\" >nul
copy /Y README.md "%DIST%\" >nul
copy /Y assets\icon.ico "%DIST%\assets\" >nul
copy /Y assets\icon.png "%DIST%\assets\" >nul
if exist "assets\funny option" mkdir "%DIST%\assets\funny option" >nul 2>&1
if exist "assets\funny option" copy /Y "assets\funny option\*" "%DIST%\assets\funny option\" >nul
:: Мусор в релиз не кладём: лаунчер/DLL/venv привязаны к чужому Python,
:: data/ — личные настройки и логи пользователя.
echo.
echo В релиз НЕ вошли (создадутся сами): zapret-manager.exe, *.dll,
echo pyvenv.cfg, data/, install.bat
echo.
powershell -NoProfile -Command "Compress-Archive -Path '%DIST%\*' -DestinationPath '%~dp0dist\%NAME%.zip' -Force"
if errorlevel 1 (
    echo Не удалось упаковать zip
    pause
    exit /b 1
)
echo.
echo Готово: dist\%NAME%.zip
echo Пользователю: распаковать -^> двойной клик run.bat -^> мастер за 3 шага.
pause
