' Zapret Manager v2 - hidden launcher, no console window.
' Double-click this file to open the installer window.
Option Explicit
Dim fso, dir, sh
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("Wscript.Shell")
sh.Run "powershell.exe -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & fso.BuildPath(dir, "Installer.ps1") & """", 0, False
