@echo off
rem Zapret Manager v2 — установщик с окном. Двойной клик — терминала не будет,
rem откроется окно установки с обучающим видео внутри.
title Zapret Manager v2 — установщик
cd /d "%~dp0"
start "" wscript.exe //nologo "%~dp0Installer.vbs"
exit
