; Zapret Manager Portable 2.0.5
; Один файл: приложение + zapret + авто-настройка (раскрывается в папку, без админа)
Unicode true

!include "MUI2.nsh"

Name "Zapret Manager Portable"
OutFile "Zapret-Manager-Portable-2.0.5.exe"
InstallDir "$DESKTOP\Zapret Manager Portable"
InstallDirRegKey HKCU "Software\ZapretManagerPortable" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
XPStyle on
CRCCheck on
ShowInstDetails nevershow

VIProductVersion "2.0.5.0"
VIAddVersionKey "ProductName" "Zapret Manager Portable"
VIAddVersionKey "FileDescription" "Zapret Manager Portable 2.0.5 — приложение + zapret в одном файле"
VIAddVersionKey "ProductVersion" "2.0.5"
VIAddVersionKey "CompanyName" "PROPANE3"

!define MUI_ABORTWARNING
!define MUI_ICON "..\..\src-tauri\icons\icon.ico"
!define MUI_UNICON "..\..\src-tauri\icons\icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "..\..\src-tauri\icons\wizard.bmp"
!define MUI_WELCOMEPAGE_TITLE "Zapret Manager Portable 2.0.5"
!define MUI_WELCOMEPAGE_TEXT "Zapret Manager — панель управления zapret для обхода DPI.$\r$\n$\r$\nПриложение полностью портативное: папку можно переносить на любой диск или флешку.$\r$\n$\r$\nНажмите Далее для распаковки."
!define MUI_FINISHPAGE_TITLE "Установка завершена"
!define MUI_FINISHPAGE_TEXT "Zapret Manager Portable установлен в:$\r$\n$\r$\n$INSTDIR$\r$\n$\r$\nПриложение полностью портативное: папку можно переносить на любой диск и даже на флешку."
!define MUI_FINISHPAGE_RUN "$INSTDIR\zapret-manager.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Запустить Zapret Manager"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "Russian"

Section "Установка"
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "stage\*"
  WriteRegStr HKCU "Software\ZapretManagerPortable" "InstallDir" "$INSTDIR"
  CreateShortcut "$DESKTOP\Zapret Manager Portable.lnk" "$INSTDIR\zapret-manager.exe"
SectionEnd