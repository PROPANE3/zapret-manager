# ============================================================================
#  Zapret Manager v2 — движок консольной установки (для разработчиков).
#
#  Обычным пользователям нужен Installer.bat в корне проекта (окно с видео).
#  Этот скрипт живёт в tools/ и используется как фолбэк GUI-установщика,
#  а также для автоматизации и диагностики.
#
#  Запуск: powershell -ExecutionPolicy Bypass -File tools\Setup.ps1
#          powershell -ExecutionPolicy Bypass -File tools\Setup.ps1 -CheckOnly
#
#  Что делает (по шагам, всё сам):
#    [1/6] Проверяет WebView2 и VC++ Redist (доставляет при отсутствии)
#    [2/6] Находит готовый zapret-manager.exe (сборка в проекте, NSIS-пакеты
#          или уже установленная копия) и ставит его
#    [3/6] Находит папку zapret-discord-youtube (или качает свежий релиз)
#    [4/6] Прописывает zapret_root в config.json — приложение сразу готово
#    [5/6] Создаёт ярлыки (рабочий стол + меню Пуск)
#    [6/6] Запускает приложение (первый запрос UAC — это нормально)
#
#  Параметры:
#    -Uninstall      удалить приложение и ярлыки (zapret и служба не трогаются)
#    -NoLaunch       поставить, но не запускать
#    -CheckOnly      только проверить и показать план (ничего не меняет)
#    -Rebuild        пересобрать exe из исходников перед установкой (нужен Rust)
#    -NoVideo        не открывать обучающее видео во время установки
#    -Silent         тихо: без видео и лишних вопросов
#    -ZapretRoot     путь к папке zapret вручную, например:
#                    tools\Setup.ps1 -ZapretRoot "C:\zapret"
# ============================================================================
param(
    [switch]$Uninstall,
    [switch]$NoLaunch,
    [switch]$CheckOnly,
    [switch]$Rebuild,
    [switch]$NoVideo,
    [switch]$Silent,
    [string]$ZapretRoot = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
# скрипт живёт в tools/ — корень проекта на уровень выше
if (((Split-Path -Leaf $here) -eq "tools") -and (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $here) "src-tauri"))) {
    $root = Split-Path -Parent $here
} else {
    $root = $here
}
$appName = "Zapret Manager v2"
$exeName = "zapret-manager.exe"
$portableDir = Join-Path $env:LOCALAPPDATA "ZapretManager"
$nsisDir = Join-Path $env:LOCALAPPDATA "Zapret Manager"
$deskDir = [Environment]::GetFolderPath("Desktop")
$progDir = [Environment]::GetFolderPath("Programs")
$wvGuid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

function Write-Ok($t) { Write-Host "[OK] $t" -ForegroundColor Green }
function Write-Inf($t) { Write-Host "[..] $t" -ForegroundColor Gray }
function Write-Warn($t) { Write-Host "[!!] $t" -ForegroundColor Yellow }
function Write-Err($t) { Write-Host "[ОШИБКА] $t" -ForegroundColor Red }

function Stop-App {
    Get-Process -Name "zapret-manager" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

function New-Shortcut($path, $target, $workDir) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $s.TargetPath = $target
    $s.WorkingDirectory = $workDir
    $s.IconLocation = "$target,0"
    $s.Description = "$appName — обход DPI"
    $s.Save()
}

# ---------- проверки зависимостей (только чтение) ----------

function Test-WebView2 {
    foreach ($p in @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$wvGuid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$wvGuid",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$wvGuid")) {
        $v = (Get-ItemProperty -LiteralPath $p -ErrorAction SilentlyContinue).pv
        if ($v) { return $v }
    }
    return $null
}

function Test-VcRedist {
    try {
        $vc = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -ErrorAction SilentlyContinue
        # Version бывает вида "v14.51.36247.00" — букву отрезаем перед сравнением
        $ver = ([string]$vc.Version -replace '^[^0-9]*', '')
        if ($vc -and $vc.Installed -eq 1 -and ([version]$ver -ge [version]"14.30")) { return $vc.Version }
    } catch {}
    return $null
}

function Test-ZapretFolder($path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return $false }
    if (!(Test-Path -LiteralPath $path -PathType Container)) { return $false }
    if (!(Test-Path -LiteralPath (Join-Path $path "service.bat"))) { return $false }
    if (!(Test-Path -LiteralPath (Join-Path $path "bin"))) { return $false }
    return $true
}

function Find-Zapret {
    # 1. явный параметр
    if ($ZapretRoot -and (Test-ZapretFolder $ZapretRoot)) { return $ZapretRoot }
    # 2. уже прописан в существующих config.json
    foreach ($d in @($portableDir, $nsisDir)) {
        $c = Join-Path $d "data\config.json"
        if (Test-Path -LiteralPath $c) {
            try {
                $z = (Get-Content -LiteralPath $c -Raw | ConvertFrom-Json).zapret_root
                if (Test-ZapretFolder $z) { return $z }
            } catch {}
        }
    }
    # 3. соседние папки: рабочий стол, рядом с проектом, корни дисков
    $cands = @()
    $cands += Get-ChildItem -LiteralPath $deskDir -Directory -Filter "zapret-discord-youtube-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | ForEach-Object { $_.FullName }
    $cands += Join-Path $deskDir "zapret-discord-youtube-main"
    $cands += Join-Path (Split-Path -Parent $root) "zapret-discord-youtube-main"
    $cands += @("C:\zapret", "D:\zapret")
    foreach ($c in $cands) {
        if (Test-ZapretFolder $c) { return $c }
    }
    return $null
}

function Find-ManagerExe {
    $dev = Join-Path $root "src-tauri\target\release\$exeName"
    if (Test-Path -LiteralPath $dev) {
        return @{ Path = $dev; Kind = "dev-build" }
    }
    foreach ($p in @((Join-Path $nsisDir $exeName), (Join-Path $portableDir $exeName))) {
        if (Test-Path -LiteralPath $p) {
            return @{ Path = $p; Kind = "installed" }
        }
    }
    $setup = Get-ChildItem (Join-Path $root "src-tauri\target\release\bundle\nsis\*-setup.exe") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($setup) {
        return @{ Path = $setup.FullName; Kind = "nsis-bundle" }
    }
    return $null
}

function Test-FrontendNewer($exePath) {
    try {
        $exeTime = (Get-Item -LiteralPath $exePath).LastWriteTime
        $fresh = Get-ChildItem -LiteralPath (Join-Path $root "frontend") -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $wiz = Get-ChildItem -LiteralPath (Join-Path $root "assets\wizard") -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        foreach ($f in @($fresh, $wiz)) {
            if ($f -and ($f.LastWriteTime -gt $exeTime)) { return $true }
        }
    } catch {}
    return $false
}

function Write-ManagerConfig($installedExe, $zapretPath) {
    $dataDir = Join-Path (Split-Path -Parent $installedExe) "data"
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    $cfgPath = Join-Path $dataDir "config.json"
    $cfg = @{}
    if (Test-Path -LiteralPath $cfgPath) {
        try {
            (Get-Content -LiteralPath $cfgPath -Raw | ConvertFrom-Json).PSObject.Properties |
                ForEach-Object { $cfg[$_.Name] = $_.Value }
        } catch {}
    }
    $cfg["zapret_root"] = $zapretPath
    ($cfg | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $cfgPath -Encoding UTF8
    return $cfgPath
}

function Install-Dependency($name, $url, $args) {
    $tmp = Join-Path $env:TEMP ("zm_" + [IO.Path]::GetRandomFileName() + ".exe")
    Write-Inf "Качаю $name ..."
    Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    Write-Inf "Ставлю $name (тихо) ..."
    $p = Start-Process -FilePath $tmp -ArgumentList $args -Wait -PassThru
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    return $p.ExitCode
}

function Get-ZapretRelease {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest" `
        -Headers @{ "User-Agent" = "ZapretManager-Setup"; "Accept" = "application/vnd.github+json" }
    $tag = [string]$rel.tag_name
    $asset = $rel.assets | Where-Object { $_.name -like "zapret-discord-youtube-*.zip" } | Select-Object -First 1
    if (!$asset) { throw "в релизе нет zip-архива" }
    return @{ Tag = $tag; Url = [string]$asset.browser_download_url }
}

# ================= удаление =================
if ($Uninstall) {
    Write-Host "=== $appName — удаление ===" -ForegroundColor Cyan
    Stop-App
    foreach ($d in @($portableDir, $nsisDir)) {
        if (Test-Path -LiteralPath $d) {
            Remove-Item -LiteralPath $d -Recurse -Force
            Write-Ok "Папка удалена: $d"
        }
    }
    foreach ($lnk in @((Join-Path $deskDir "$appName.lnk"), (Join-Path $progDir "$appName.lnk"))) {
        if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force; Write-Ok "Ярлык удалён" }
    }
    Write-Host "Готово. Папка zapret и служба zapret не тронуты." -ForegroundColor Green
    exit 0
}

# ================= проверка без изменений =================
if ($CheckOnly) {
    Write-Host "=== $appName — проверка (ничего не меняю) ===" -ForegroundColor Cyan
    $wv = Test-WebView2
    if ($wv) { Write-Ok "WebView2: $wv" } else { Write-Warn "WebView2: нет (установщик доставит)" }
    $vc = Test-VcRedist
    if ($vc) { Write-Ok "VC++ Redist x64: $vc" } else { Write-Warn "VC++ Redist: нет (установщик доставит)" }
    $m = Find-ManagerExe
    if ($m) {
        Write-Ok "Приложение: $($m.Kind) — $($m.Path)"
        if (($m.Kind -eq "dev-build") -and (Test-FrontendNewer $m.Path)) {
            Write-Warn "frontend новее exe — совет: tools\Setup.ps1 -Rebuild"
        }
    } else { Write-Warn "Приложение: exe не найден (нужна сборка или релиз)" }
    $z = Find-Zapret
    if ($z) { Write-Ok "zapret: $z" } else { Write-Warn "zapret: не найден (установщик скачает свежий релиз)" }
    $vid = Join-Path $root "assets\wizard\install_wizards.mp4"
    if (Test-Path -LiteralPath $vid) { Write-Ok "Видео мастера: есть" } else { Write-Warn "Видео мастера: нет" }
    $ad = Join-Path $portableDir "assets"
    if (Test-Path -LiteralPath (Join-Path $ad "funny")) { Write-Ok "Ассеты funny: есть" } else { Write-Warn "Ассеты funny: нет (установщик докинет)" }
    if (Test-Path -LiteralPath (Join-Path $ad "packs\vsd_pack.zip")) { Write-Ok "Архивы тем: есть" } else { Write-Warn "Архивы тем: нет (установщик докинет)" }
    exit 0
}

# ================= установка =================
Write-Host "=== $appName — установка в 1 клик ===" -ForegroundColor Cyan
Write-Inf "Всё сделаю сам: зависимости, программа, zapret, ярлыки, запуск."

# Видео параллельно с установкой (как в мастере приложения)
$videoProc = $null
if (!$NoVideo -and !$Silent) {
    $vid = Join-Path $root "assets\wizard\install_wizards.mp4"
    if (Test-Path -LiteralPath $vid) {
        try { $videoProc = Start-Process -FilePath $vid -PassThru -ErrorAction SilentlyContinue } catch {}
        if ($videoProc) { Write-Inf "Включил обучающее видео — смотрите, пока ставится." }
    }
}

# [1/6] зависимости
Write-Host "[1/6] Зависимости..." -ForegroundColor Cyan
if (!(Test-WebView2)) {
    $code = Install-Dependency "WebView2" "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "/silent /install"
    if ($code -eq 0) { Write-Ok "WebView2 установлен" } else { Write-Warn "WebView2: код $code, приложение всё равно попробует запуститься" }
} else { Write-Ok "WebView2 уже стоит" }
if (!(Test-VcRedist)) {
    $code = Install-Dependency "VC++ Redist" "https://aka.ms/vs/17/release/vc_redist.x64.exe" "/install /quiet /norestart"
    if ($code -eq 0 -or $code -eq 3010) { Write-Ok "VC++ Redist установлен" } else { Write-Warn "VC++: код $code" }
} else { Write-Ok "VC++ Redist уже стоит" }

# [2/6] программа
Write-Host "[2/6] Программа..." -ForegroundColor Cyan
if ($Rebuild) {
    Write-Inf "Пересобираю из исходников (несколько минут)..."
    $env:PATH += ";$HOME\.cargo\bin"
    if (!(Get-Command cargo -ErrorAction SilentlyContinue)) { Write-Err "Нет Rust (https://rustup.rs). Уберите флаг -Rebuild."; exit 1 }
    Push-Location (Join-Path $root "src-tauri")
    try {
        if (!(Get-Command cargo-tauri -ErrorAction SilentlyContinue)) {
            Write-Inf "Ставлю Tauri CLI (один раз, долго)..."
            & cargo install tauri-cli --locked
            if ($LASTEXITCODE -ne 0) { throw "tauri-cli не встал" }
        }
        & cargo tauri build
        if ($LASTEXITCODE -ne 0) { throw "сборка упала" }
    } finally { Pop-Location }
    Write-Ok "Собрано"
}
$m = Find-ManagerExe
if (!$m) {
    Write-Err "Не нашёл zapret-manager.exe: нет ни сборки (src-tauri\target\release), ни NSIS-пакета, ни установленной копии."
    Write-Err "Соберите проект (tools\Setup.ps1 -Rebuild) или положите рядом готовый setup.exe."
    exit 1
}
if ($m.Kind -eq "nsis-bundle") {
    Write-Inf "Ставлю из NSIS-пакета (тихо): $(Split-Path -Leaf $m.Path)"
    $p = Start-Process -FilePath $m.Path -ArgumentList "/S" -Wait -PassThru
    $installed = Join-Path $nsisDir $exeName
    if (!(Test-Path -LiteralPath $installed)) { Write-Err "NSIS завершился с кодом $($p.ExitCode), но exe не появился."; exit 1 }
    Write-Ok "Поставлено: $installed"
} elseif ($m.Kind -eq "dev-build") {
    if (Test-FrontendNewer $m.Path) {
        Write-Warn "frontend новее exe — интерфейс может быть старым. В следующий раз: tools\Setup.ps1 -Rebuild"
    }
    Write-Inf "Копирую в $portableDir ..."
    Stop-App
    New-Item -ItemType Directory -Path $portableDir -Force | Out-Null
    Copy-Item -LiteralPath $m.Path -Destination (Join-Path $portableDir $exeName) -Force
    $installed = Join-Path $portableDir $exeName
    Write-Ok "Поставлено: $installed"
} else {
    $installed = $m.Path
    Write-Ok "Уже стоит, использую: $installed"
}
# Ассеты рядом с exe: funny, секретные архивы, музыка, видео мастера
$srcAssets = Join-Path $root "assets"
if (Test-Path -LiteralPath $srcAssets) {
    Write-Inf "Копирую картинки, архивы и музыку..."
    $dstAssets = Join-Path (Split-Path -Parent $installed) "assets"
    New-Item -ItemType Directory -Path $dstAssets -Force | Out-Null
    Copy-Item -Path (Join-Path $srcAssets "*") -Destination $dstAssets -Recurse -Force
    Write-Ok "Ассеты на месте"
}
# UAC-манифест: --no-bundle сборки его не штампуют (только beforeBundleCommand),
# а без requireAdministrator служба не ставится (sc -> FAILED 5).
try {
    $mt = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName "x64\mt.exe" } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    $mf = Join-Path $root "src-tauri\app.manifest"
    if ($mt -and (Test-Path -LiteralPath $mf)) {
        & $mt -nologo -manifest $mf "-outputresource:$installed;#1" | Out-Null
        $chk = Join-Path $env:TEMP "zm-manifest-check.xml"
        & $mt -nologo "-inputresource:$installed;#1" "-out:$chk" | Out-Null
        if ((Get-Content -LiteralPath $chk -Raw -ErrorAction SilentlyContinue) -match "requireAdministrator") {
            Write-Ok "UAC-манифест вшит (запуск будет с запросом прав)"
        } else {
            Write-Warn "Манифест не вшился: проверьте вручную"
        }
        Remove-Item -LiteralPath $chk -Force -ErrorAction SilentlyContinue
    } else {
        Write-Warn "Нет mt.exe/манифеста: UAC не вшит, служба без прав не встанет"
    }
} catch {
    Write-Warn "Не вшил UAC-манифест"
}

# [3/6] zapret
Write-Host "[3/6] Папка zapret..." -ForegroundColor Cyan
$zpath = Find-Zapret
if ($zpath) {
    Write-Ok "Нашёл: $zpath"
} else {
    Write-Inf "Локально нет — качаю свежий релиз Flowseal..."
    $rel = Get-ZapretRelease
    $safeTag = ($rel.Tag -replace '[^\w.\-]', '_').Trim('_')
    if (!$safeTag) { $safeTag = Get-Date -Format "yyyyMMdd" }
    $dest = Join-Path $deskDir "zapret-discord-youtube-$safeTag"
    if (Test-ZapretFolder $dest) {
        $zpath = $dest
        Write-Ok "Уже скачан: $zpath"
    } else {
        $zip = Join-Path $env:TEMP ("zapret_" + $safeTag + ".zip")
        Write-Inf "Качаю $($rel.Tag) ..."
        Invoke-WebRequest -Uri $rel.Url -OutFile $zip -UseBasicParsing
        $tmpDir = Join-Path $env:TEMP ("zapret_" + [IO.Path]::GetRandomFileName())
        New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
        Write-Inf "Распаковываю..."
        Expand-Archive -LiteralPath $zip -DestinationPath $tmpDir -Force
        $inner = Get-ChildItem -LiteralPath $tmpDir -Directory | Select-Object -First 1
        if ($inner -and (Test-Path -LiteralPath (Join-Path $inner.FullName "service.bat"))) { $srcDir = $inner.FullName }
        else { $srcDir = $tmpDir }
        if (!(Test-Path -LiteralPath (Join-Path $srcDir "service.bat"))) { throw "в архиве нет service.bat" }
        if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
        Move-Item -LiteralPath $srcDir -Destination $dest
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
        $zpath = $dest
        Write-Ok "Скачан: $zpath"
    }
}

# [4/6] конфиг — приложение сразу готово к работе
Write-Host "[4/6] Настройка..." -ForegroundColor Cyan
$cfgPath = Write-ManagerConfig $installed $zpath
Write-Ok "Папка zapret прописана: $cfgPath"

# [5/6] ярлыки
Write-Host "[5/6] Ярлыки..." -ForegroundColor Cyan
$workDir = Split-Path -Parent $installed
New-Shortcut (Join-Path $deskDir "$appName.lnk") $installed $workDir
New-Shortcut (Join-Path $progDir "$appName.lnk") $installed $workDir
Write-Ok "Рабочий стол + меню Пуск"

# [6/6] запуск
if ($NoLaunch) { Write-Ok "Готово без запуска (флаг -NoLaunch)"; exit 0 }
Write-Host "[6/6] Запуск..." -ForegroundColor Cyan
Write-Inf "Сейчас появится запрос прав администратора — соглашайтесь (нужен для WinDivert)."
Start-Process -FilePath $installed
Write-Host "Готово! Приложение запущено и уже знает, где zapret. Дальше — кнопка проверки или Мастер установки." -ForegroundColor Green
if ($videoProc -and !$videoProc.HasExited) {
    Write-Inf "Досмотрите обучающее видео до конца — там всё показано."
}
