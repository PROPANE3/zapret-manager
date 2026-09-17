' Zapret Manager v2 — скрытый запуск установщика (без терминала).
' Двойной клик по Installer.bat вызывает этот файл.
Option Explicit
Dim fso, dir, sh
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("Wscript.Shell")
sh.Run "powershell.exe -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & fso.BuildPath(dir, "Installer.ps1") & """", 0, False
