# ============================================================================
#  Zapret Manager v2 — консольный установщик (для разработчиков и автоматизации).
#
#  Обычным пользователям: двойной клик по Installer.vbs (GUI с видео).
#
#  Запуск: powershell -ExecutionPolicy Bypass -File tools\Setup.ps1
#
#  Параметры:
#    -Uninstall      удалить приложение и ярлыки
#    -NoLaunch       поставить, но не запускать
#    -CheckOnly      только проверить (ничего не меняет)
#    -Rebuild        пересобрать exe из исходников (нужен Rust)
#    -NoVideo        не открывать обучающее видео
#    -Silent         тихо: без видео и вопросов
#    -ZapretRoot     путь к папке zapret вручную
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
if (((Split-Path -Leaf $here) -eq "tools") -and (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $here) "src-tauri"))) {
    $root = Split-Path -Parent $here
} else {
    $root = $here
}
$appName = "Zapret Manager"
$exeName = "zapret-manager.exe"
$installDir = Join-Path $env:LOCALAPPDATA "Zapret Manager"
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
    if ($ZapretRoot -and (Test-ZapretFolder $ZapretRoot)) { return $ZapretRoot }
    
    # Проверяем все возможные пути установки для config.json
    $configSearchPaths = @(
        (Join-Path $env:LOCALAPPDATA "Zapret Manager"),
        (Join-Path $env:LOCALAPPDATA "ZapretManager"),
        (Join-Path $env:LOCALAPPDATA "zapret-manager")
    )
    
    foreach ($d in $configSearchPaths) {
        $c = Join-Path $d "data\config.json"
        if (Test-Path -LiteralPath $c) {
            try {
                $z = (Get-Content -LiteralPath $c -Raw | ConvertFrom-Json).zapret_root
                if (Test-ZapretFolder $z) { return $z }
            } catch {}
        }
    }
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

function Get-CurrentVersion {
    $vFile = Join-Path $root "version.txt"
    if (Test-Path -LiteralPath $vFile) {
        return (Get-Content -LiteralPath $vFile -Raw).Trim()
    }
    return "0.0.0"
}

function Get-InstalledVersion($exePath) {
    try {
        $vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($exePath)
        if ($vi.ProductVersion) { return $vi.ProductVersion }
        if ($vi.FileVersion) { return $vi.FileVersion }
    } catch {}
    try {
        $dataDir = Join-Path (Split-Path -Parent $exePath) "data"
        $vFile = Join-Path $dataDir "version.txt"
        if (Test-Path -LiteralPath $vFile) {
            return (Get-Content -LiteralPath $vFile -Raw).Trim()
        }
    } catch {}
    return "0.0.0"
}

function Test-VersionOutdated($exePath) {
    $current = Get-CurrentVersion
    $installed = Get-InstalledVersion $exePath
    try {
        if ([version]$installed -lt [version]$current) { return $true }
    } catch {}
    return $false
}

function Find-ManagerExe {
    $dev = Join-Path $root "src-tauri\target\release\$exeName"
    if (Test-Path -LiteralPath $dev) {
        return @{ Path = $dev; Kind = "dev-build" }
    }
    
    # Локальный NSIS-бандл (свежесобранный) — приоритет над GitHub
    $setup = Get-ChildItem (Join-Path $root "src-tauri\target\release\bundle\nsis\*-setup.exe") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($setup) {
        return @{ Path = $setup.FullName; Kind = "nsis-bundle" }
    }
    
    # Проверяем все возможные пути установки NSIS
    $installedPaths = @(
        (Join-Path $env:LOCALAPPDATA "Zapret Manager\$exeName"),
        (Join-Path $env:LOCALAPPDATA "ZapretManager\$exeName"),
        (Join-Path $env:LOCALAPPDATA "zapret-manager\$exeName"),
        (Join-Path ${env:ProgramFiles} "Zapret Manager\$exeName"),
        (Join-Path ${env:ProgramFiles(x86)} "Zapret Manager\$exeName")
    )
    
    foreach ($instPath in $installedPaths) {
        if (Test-Path -LiteralPath $instPath) {
            if (Test-VersionOutdated $instPath) {
                return @{ Path = $instPath; Kind = "outdated" }
            }
            return @{ Path = $instPath; Kind = "installed" }
        }
    }
    
    return $null
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

function Get-AppReleaseGH {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/PROPANE3/zapret-manager/releases/latest" `
        -Headers @{ "User-Agent" = "ZapretManager-Setup"; "Accept" = "application/vnd.github+json" }
    $asset = $rel.assets | Where-Object { $_.name -like "*-setup.exe" } | Select-Object -First 1
    if (!$asset) { throw "в релизе на GitHub нет setup.exe" }
    return @{ Tag = [string]$rel.tag_name; Url = [string]$asset.browser_download_url; Name = [string]$asset.name }
}

# ================= удаление =================
if ($Uninstall) {
    Write-Host "=== $appName — удаление ===" -ForegroundColor Cyan
    Stop-App
    if (Test-Path -LiteralPath $installDir) {
        Remove-Item -LiteralPath $installDir -Recurse -Force
        Write-Ok "Папка удалена: $installDir"
    }
    foreach ($lnk in @((Join-Path $deskDir "$appName.lnk"), (Join-Path $progDir "$appName.lnk"))) {
        if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force; Write-Ok "Ярлык удалён" }
    }
    Write-Host "Готово. Папка zapret и служба не тронуты." -ForegroundColor Green
    exit 0
}

# ================= проверка без изменений =================
if ($CheckOnly) {
    Write-Host "=== $appName — проверка ===" -ForegroundColor Cyan
    $currentVer = Get-CurrentVersion
    Write-Host "Актуальная версия: $currentVer" -ForegroundColor White
    $wv = Test-WebView2
    if ($wv) { Write-Ok "WebView2: $wv" } else { Write-Warn "WebView2: нет" }
    $vc = Test-VcRedist
    if ($vc) { Write-Ok "VC++ Redist x64: $vc" } else { Write-Warn "VC++ Redist: нет" }
    $m = Find-ManagerExe
    if ($m) {
        $instVer = Get-InstalledVersion $m.Path
        if ($m.Kind -eq "outdated") {
            Write-Warn "Приложение: устаревшая версия $instVer (нужно обновление)"
        } else {
            Write-Ok "Приложение: $($m.Kind) — версия $instVer"
        }
        Write-Host "  Путь: $($m.Path)" -ForegroundColor Gray
    } else { Write-Warn "Приложение: не найдено (скачается с GitHub)" }
    $z = Find-Zapret
    if ($z) { Write-Ok "zapret: $z" } else { Write-Warn "zapret: не найден (скачается)" }
    exit 0
}

# ================= установка =================
Write-Host "=== $appName — установка ===" -ForegroundColor Cyan
$currentVer = Get-CurrentVersion
Write-Host "Актуальная версия: $currentVer" -ForegroundColor White

$videoProc = $null
if (!$NoVideo -and !$Silent) {
    $vid = Join-Path $root "assets\wizard\install_wizards.mp4"
    if (Test-Path -LiteralPath $vid) {
        try { $videoProc = Start-Process -FilePath $vid -PassThru -ErrorAction SilentlyContinue } catch {}
        if ($videoProc) { Write-Inf "Видео запущено" }
    }
}

# [1/5] зависимости
Write-Host "[1/5] Зависимости..." -ForegroundColor Cyan
if (!(Test-WebView2)) {
    $code = Install-Dependency "WebView2" "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "/silent /install"
    if ($code -eq 0) { Write-Ok "WebView2 установлен" } else { Write-Warn "WebView2: код $code" }
} else { Write-Ok "WebView2 уже стоит" }
if (!(Test-VcRedist)) {
    $code = Install-Dependency "VC++ Redist" "https://aka.ms/vs/17/release/vc_redist.x64.exe" "/install /quiet /norestart"
    if ($code -eq 0 -or $code -eq 3010) { Write-Ok "VC++ Redist установлен" } else { Write-Warn "VC++: код $code" }
} else { Write-Ok "VC++ Redist уже стоит" }

# [2/5] программа
Write-Host "[2/5] Программа..." -ForegroundColor Cyan
if ($Rebuild) {
    Write-Inf "Пересборка из исходников..."
    $env:PATH += ";$HOME\.cargo\bin"
    if (!(Get-Command cargo -ErrorAction SilentlyContinue)) { Write-Err "Нет Rust (https://rustup.rs)"; exit 1 }
    $keyFile = Join-Path $HOME ".tauri\zapret-manager.key"
    if (Test-Path -LiteralPath $keyFile) { $env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -LiteralPath $keyFile -Raw }
    $pwFile = Join-Path $HOME ".tauri\zapret-manager.pw.txt"
    if (Test-Path -LiteralPath $pwFile) { $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = Get-Content -LiteralPath $pwFile -Raw }
    Push-Location (Join-Path $root "src-tauri")
    try {
        if (!(Get-Command cargo-tauri -ErrorAction SilentlyContinue)) {
            Write-Inf "Ставлю tauri-cli..."
            & cargo install tauri-cli --locked
            if ($LASTEXITCODE -ne 0) { throw "tauri-cli не встал" }
        }
        & cargo tauri build
        if ($LASTEXITCODE -ne 0) { throw "сборка упала" }
    } finally { Pop-Location }
    Write-Ok "Собрано"
}

$m = Find-ManagerExe
$needDownload = $false

if (!$m) {
    Write-Inf "Программа не найдена — скачаю с GitHub"
    $needDownload = $true
} elseif ($m.Kind -eq "outdated") {
    $instVer = Get-InstalledVersion $m.Path
    Write-Inf "Найдена устаревшая версия $instVer — обновлю до $currentVer"
    $needDownload = $true
} elseif ($m.Kind -eq "dev-build") {
    Write-Ok "Dev-сборка найдена"
} elseif ($m.Kind -eq "nsis-bundle") {
    Write-Ok "NSIS-пакет найден"
} else {
    Write-Ok "Программа уже установлена (актуальная версия)"
}

if ($needDownload) {
    Write-Inf "Проверяю GitHub..."
    try {
        $arel = Get-AppReleaseGH
        $ghVer = ($arel.Tag -replace '^v', '').Trim()
        Write-Host "Версия на GitHub: $ghVer" -ForegroundColor Gray
        
        # Проверяем, что версия на GitHub действительно новее
        try {
            if ([version]$ghVer -lt [version]$currentVer) {
                Write-Warn "На GitHub версия $ghVer старее локальной $currentVer"
                Write-Warn "Необходимо собрать проект локально или опубликовать новый релиз"
                if ($m.Kind -eq "outdated") {
                    Write-Inf "Использую установленную версию"
                    $needDownload = $false
                }
            }
        } catch {}
        
        if ($needDownload) {
            Write-Inf "Скачиваю $($arel.Tag)..."
            $asetup = Join-Path $env:TEMP $arel.Name
            Invoke-WebRequest -Uri $arel.Url -OutFile $asetup -UseBasicParsing
            $m = @{ Path = $asetup; Kind = "dl-setup" }
        }
    } catch {
        Write-Warn "Не удалось проверить GitHub: $($_.Exception.Message)"
        if ($m.Kind -eq "outdated") {
            Write-Inf "Использую установленную версию"
            $needDownload = $false
        }
    }
}

if ($m.Kind -eq "nsis-bundle" -or $m.Kind -eq "dl-setup") {
    Write-Inf "Устанавливаю из NSIS-пакета..."
    Stop-App
    $p = Start-Process -FilePath $m.Path -ArgumentList "/S" -Wait -PassThru
    
    # Ищем exe в нескольких возможных местах (Tauri NSIS может ставить в разные пути)
    $possiblePaths = @(
        (Join-Path $env:LOCALAPPDATA "Zapret Manager\$exeName"),
        (Join-Path $env:LOCALAPPDATA "ZapretManager\$exeName"),
        (Join-Path $env:LOCALAPPDATA "zapret-manager\$exeName"),
        (Join-Path ${env:ProgramFiles} "Zapret Manager\$exeName"),
        (Join-Path ${env:ProgramFiles(x86)} "Zapret Manager\$exeName")
    )
    
    $installed = $null
    foreach ($testPath in $possiblePaths) {
        if (Test-Path -LiteralPath $testPath) {
            $installed = $testPath
            break
        }
    }
    
    if (!$installed) {
        # Финальная попытка — ищем рекурсивно в LocalAppData
        $found = Get-ChildItem -Path $env:LOCALAPPDATA -Filter $exeName -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -like "*zapret*" } |
            Select-Object -First 1
        if ($found) {
            $installed = $found.FullName
        }
    }
    
    if (!$installed) {
        Write-Err "NSIS завершился (код $($p.ExitCode)), но exe не найден"
        exit 1
    }
    
    if ($m.Kind -eq "dl-setup") { Remove-Item -LiteralPath $m.Path -Force -ErrorAction SilentlyContinue }
    Write-Ok "Программа установлена: $installed"
} elseif ($m.Kind -eq "dev-build") {
    Write-Inf "Копирую dev-сборку..."
    Stop-App
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    Copy-Item -LiteralPath $m.Path -Destination (Join-Path $installDir $exeName) -Force
    $installed = Join-Path $installDir $exeName
    Write-Ok "Dev-сборка скопирована"
} else {
    $installed = $m.Path
    Write-Ok "Использую существующую установку"
}

# ассеты
$srcAssets = Join-Path $root "assets"
if (Test-Path -LiteralPath $srcAssets) {
    Write-Inf "Копирую ресурсы..."
    $dstAssets = Join-Path (Split-Path -Parent $installed) "assets"
    New-Item -ItemType Directory -Path $dstAssets -Force | Out-Null
    Copy-Item -Path (Join-Path $srcAssets "*") -Destination $dstAssets -Recurse -Force
    Write-Ok "Ресурсы скопированы"
}

# UAC-манифест
try {
    $mt = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName "x64\mt.exe" } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    $mf = Join-Path $root "src-tauri\app.manifest"
    if ($mt -and (Test-Path -LiteralPath $mf)) {
        & $mt -nologo -manifest $mf "-outputresource:$installed;#1" | Out-Null
        Write-Ok "UAC-манифест встроен"
    } else {
        Write-Warn "Нет mt.exe/манифеста: UAC не вшит"
    }
} catch {
    Write-Warn "Не вшил UAC-манифест"
}

# [3/5] zapret
Write-Host "[3/5] zapret..." -ForegroundColor Cyan
$zpath = Find-Zapret
if ($zpath) {
    Write-Ok "Найден: $zpath"
} else {
    Write-Inf "Не найден — качаю свежий релиз..."
    $rel = Get-ZapretRelease
    $safeTag = ($rel.Tag -replace '[^\w.\-]', '_').Trim('_')
    if (!$safeTag) { $safeTag = Get-Date -Format "yyyyMMdd" }
    $dest = Join-Path $deskDir "zapret-discord-youtube-$safeTag"
    if (Test-ZapretFolder $dest) {
        $zpath = $dest
        Write-Ok "Уже скачан"
    } else {
        $zip = Join-Path $env:TEMP ("zapret_" + $safeTag + ".zip")
        Write-Inf "Качаю $($rel.Tag) ..."
        Invoke-WebRequest -Uri $rel.Url -OutFile $zip -UseBasicParsing
        $tmpDir = Join-Path $env:TEMP ("zapret_" + [IO.Path]::GetRandomFileName())
        New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
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

# [4/5] конфиг
Write-Host "[4/5] Конфиг..." -ForegroundColor Cyan
$cfgPath = Write-ManagerConfig $installed $zpath
Write-Ok "zapret прописан"

# [5/5] ярлыки
Write-Host "[5/5] Ярлыки..." -ForegroundColor Cyan
$workDir = Split-Path -Parent $installed
New-Shortcut (Join-Path $deskDir "$appName.lnk") $installed $workDir
New-Shortcut (Join-Path $progDir "$appName.lnk") $installed $workDir
Write-Ok "Рабочий стол + меню Пуск"

# запуск
if ($NoLaunch) { Write-Ok "Готово (без запуска)"; exit 0 }
Write-Host "Запуск..." -ForegroundColor Cyan
Start-Process -FilePath $installed
Write-Host "Готово! Приложение запущено." -ForegroundColor Green
if ($videoProc -and !$videoProc.HasExited) {
    Write-Inf "Досмотрите видео до конца."
}
