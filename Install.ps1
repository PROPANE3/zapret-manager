# Быстрый установщик Zapret Manager v2: ставит, настраивает, запускает.
# Использование: двойной клик по Install.bat (или powershell -File Install.ps1).
#   Install.ps1 -Uninstall   — удалить установку и ярлыки
#   Install.ps1 -NoLaunch    — поставить, но не запускать
param([switch]$Uninstall, [switch]$NoLaunch)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = Join-Path $env:LOCALAPPDATA "ZapretManager"
$exeName = "zapret-manager.exe"
$deskDir = [Environment]::GetFolderPath("Desktop")
$progDir = [Environment]::GetFolderPath("Programs")

function Write-Ok($t) { Write-Host "[OK] $t" -ForegroundColor Green }
function Write-Inf($t) { Write-Host "[..] $t" -ForegroundColor Gray }

function New-Shortcut($path, $target, $workDir) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $s.TargetPath = $target
    $s.WorkingDirectory = $workDir
    $s.IconLocation = "$target,0"
    $s.Description = "Zapret Manager v2 — обход DPI"
    $s.Save()
    Write-Ok "Ярлык: $path"
}

function Stop-App {
    Get-Process -Name "zapret-manager" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

if ($Uninstall) {
    Write-Inf "Удаление..."
    Stop-App
    if (Test-Path $installDir) { Remove-Item $installDir -Recurse -Force; Write-Ok "Папка удалена" }
    foreach ($lnk in @((Join-Path $deskDir "Zapret Manager v2.lnk"), (Join-Path $progDir "Zapret Manager v2.lnk"))) {
        if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Ok "Ярлык удалён" }
    }
    Write-Host "Готово. Служба zapret и сам zapret не тронуты." -ForegroundColor Green
    exit 0
}

# 1. Готовый NSIS-установщик — самый короткий путь
$setup = Get-ChildItem (Join-Path $root "src-tauri\target\release\bundle\nsis\*-setup.exe") -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($setup) {
    Write-Inf "Нашёл установщик, запускаю: $($setup.Name)"
    Start-Process $setup.FullName
    Write-Host "Дальше — мастер установки. Потом запустите приложение из меню Пуск." -ForegroundColor Green
    exit 0
}

# 2. Иначе — portable: берём готовый exe или собираем
$exe = Join-Path $root "src-tauri\target\release\$exeName"
if (!(Test-Path $exe)) {
    Write-Inf "Готового exe нет, собираю (нужен Rust + Tauri CLI, это несколько минут)..."
    $env:PATH += ";$HOME\.cargo\bin"
    if (!(Get-Command cargo -ErrorAction SilentlyContinue)) {
        Write-Host "[ОШИБКА] Нет Rust. Поставьте с https://rustup.rs, потом запустите снова." -ForegroundColor Red
        exit 1
    }
    Push-Location (Join-Path $root "src-tauri")
    try {
        if (!(Get-Command "cargo-tauri" -ErrorAction SilentlyContinue)) {
            Write-Inf "Ставлю Tauri CLI (долго, один раз)..."
            & cargo install tauri-cli --locked
            if ($LASTEXITCODE -ne 0) { throw "tauri-cli не встал" }
        }
        & cargo tauri build --no-bundle
        if ($LASTEXITCODE -ne 0) { throw "сборка упала" }
    } finally { Pop-Location }
    if (!(Test-Path $exe)) { Write-Host "[ОШИБКА] exe так и не появился." -ForegroundColor Red; exit 1 }
}

# 3. Кладём в %LOCALAPPDATA%\ZapretManager (админ не нужен, он спросится при запуске самого приложения)
Write-Inf "Копирую в $installDir ..."
Stop-App
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Copy-Item $exe (Join-Path $installDir $exeName) -Force
Write-Ok "Приложение установлено"

# 4. Ярлыки: рабочий стол + меню Пуск
New-Shortcut (Join-Path $deskDir "Zapret Manager v2.lnk") (Join-Path $installDir $exeName) $installDir
New-Shortcut (Join-Path $progDir "Zapret Manager v2.lnk") (Join-Path $installDir $exeName) $installDir

# 5. Запуск (UAC спросит само приложение — это нормально, нужен WinDivert)
if ($NoLaunch) { Write-Ok "Поставлено без запуска (флаг -NoLaunch)"; exit 0 }
Write-Inf "Запускаю... сейчас появится запрос прав администратора — соглашайтесь."
Start-Process (Join-Path $installDir $exeName)
Write-Host "Готово! Папку zapret приложение найдёт само, дальше — кнопка проверки." -ForegroundColor Green
