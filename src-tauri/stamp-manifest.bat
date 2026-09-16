@echo off
rem Stamps UAC manifest (requireAdministrator) into the built exe.
rem Runs standalone and via beforeBundleCommand before packaging.
cd /d "%~dp0"
set "EXE=%~dp0target\release\zapret-manager.exe"
if not exist "%EXE%" (
    echo [stamp] no %EXE% - build first
    exit /b 1
)
set "MT="
for /f "delims=" %%D in ('dir /b /ad "C:\Program Files (x86)\Windows Kits\10\bin" 2^>nul') do (
    if exist "C:\Program Files (x86)\Windows Kits\10\bin\%%D\x64\mt.exe" set "MT=C:\Program Files (x86)\Windows Kits\10\bin\%%D\x64\mt.exe"
)
if not defined MT (
    echo [stamp] mt.exe not found (Windows SDK required)
    exit /b 1
)
"%MT%" -nologo -manifest "%~dp0app.manifest" -outputresource:"%EXE%;#1"
if errorlevel 1 (
    echo [stamp] mt failed
    exit /b 1
)
"%MT%" -nologo -inputresource:"%EXE%;#1" -out:"%TEMP%\zm-manifest-check.xml" >nul
findstr /C:"requireAdministrator" "%TEMP%\zm-manifest-check.xml" >nul
if errorlevel 1 (
    echo [stamp] VERIFY FAILED: requireAdministrator missing in exe
    exit /b 1
)
echo [stamp] OK: requireAdministrator embedded into %EXE%
