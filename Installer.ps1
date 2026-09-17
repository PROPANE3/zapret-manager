<#
  Zapret Manager v2 — установщик с окном (без терминала).
  Запуск: двойной клик по Installer.bat (терминала не будет вообще).

  Внутри окна: картинка мастера, обучающее видео install_wizards.mp4
  (играет ПРЯМО В ОКНЕ во время установки), шаги, прогресс и журнал.
  Если установка закончилась раньше ролика — окно ждёт конца видео.
  Если ролик кончился раньше — крутится заново до конца установки.
#>
param([switch]$Silent)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# WPF требует STA; пере founder запускаем себя же в STA, если попали в MTA
if ([Threading.Thread]::CurrentThread.ApartmentState -ne "STA") {
    $arg = '-NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    if ($Silent) { $arg += " -Silent" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $arg
    exit 0
}

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$AppName = "Zapret Manager v2"
$ExeName = "zapret-manager.exe"
$PortableDir = Join-Path $env:LOCALAPPDATA "ZapretManager"
$NsisDir = Join-Path $env:LOCALAPPDATA "Zapret Manager"
$DeskDir = [Environment]::GetFolderPath("Desktop")
$ProgDir = [Environment]::GetFolderPath("Programs")
$WvGuid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

$ImgPath = Join-Path $Root "assets\wizard\wizard.jpg"
if (!(Test-Path -LiteralPath $ImgPath)) { $ImgPath = Join-Path $Root "frontend\wizard.jpg" }
$VidPath = Join-Path $Root "assets\wizard\install_wizards.mp4"
if (!(Test-Path -LiteralPath $VidPath)) { $VidPath = Join-Path $Root "frontend\install_wizards.mp4" }

try {
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml
} catch {
    # Совсем без WPF (редкость) — откатываемся на консольный движок в tools/
    Start-Process -FilePath "powershell.exe" -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Root "tools\Setup.ps1") + '"')
    exit 0
}

$Xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Zapret Manager — установка" Width="740" Height="660"
        WindowStartupLocation="CenterScreen" ResizeMode="CanMinimize" Background="#0A0A0C">
  <Grid Margin="18">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="360"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <TextBlock Grid.Row="0" Name="Title" Text="Zapret Manager v2 — установка в 1 клик"
               FontSize="20" FontWeight="Bold" Foreground="#F3E9E9" Margin="0,0,0,10"/>
    <!-- одна медиа-зона в полный размер: сначала картинка, после «Установить» её перекрывает видео -->
    <Border Grid.Row="1" CornerRadius="10" Background="Black" ClipToBounds="True" Margin="0,0,0,10">
      <Grid>
        <Image Name="Cover" Stretch="UniformToFill"/>
        <MediaElement Name="Video" LoadedBehavior="Manual" UnloadedBehavior="Manual" Stretch="Uniform" Volume="0.8" Visibility="Collapsed"/>
      </Grid>
    </Border>
    <TextBlock Grid.Row="2" Name="Status" Text="Нажмите «Установить» — всё сделаю сам: зависимости, программа, zapret, ярлыки."
               Foreground="#9C8B8E" TextWrapping="Wrap" Margin="0,0,0,6"/>
    <ProgressBar Grid.Row="3" Name="Bar" Height="18" Minimum="0" Maximum="100" Value="0" Margin="0,0,0,10"/>
    <TextBox Grid.Row="4" Name="Log" IsReadOnly="True" VerticalScrollBarVisibility="Auto"
             FontFamily="Consolas" FontSize="12" Background="#141014" Foreground="#F3E9E9"
             BorderBrush="#3A1518" TextWrapping="Wrap" Margin="0,0,0,10"/>
    <StackPanel Grid.Row="5" Orientation="Horizontal" HorizontalAlignment="Right">
      <Button Name="InstallBtn" Content="Установить" Width="130" Height="34" Margin="0,0,8,0"
              Background="#C1121F" Foreground="White" FontWeight="Bold"/>
      <Button Name="OpenBtn" Content="Открыть приложение" Width="170" Height="34" Margin="0,0,8,0" IsEnabled="False"/>
      <Button Name="CloseBtn" Content="Закрыть" Width="100" Height="34"/>
    </StackPanel>
  </Grid>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader ([xml]$Xaml)
$Window = [Windows.Markup.XamlReader]::Load($reader)
$TitleEl = $Window.FindName("Title")
$Cover = $Window.FindName("Cover")
$Video = $Window.FindName("Video")
$Status = $Window.FindName("Status")
$Bar = $Window.FindName("Bar")
$LogBox = $Window.FindName("Log")
$InstallBtn = $Window.FindName("InstallBtn")
$OpenBtn = $Window.FindName("OpenBtn")
$CloseBtn = $Window.FindName("CloseBtn")

$script:installDone = $false
$script:videoDone = $false
$script:hasVideo = $false
$script:installedExe = ""

function Pump-UI {
    $frame = New-Object System.Windows.Threading.DispatcherFrame
    [System.Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvoke(
        [System.Windows.Threading.DispatcherPriority]::Background,
        [System.Windows.Threading.DispatcherOperationCallback]{
            param($f) ($f -as [System.Windows.Threading.DispatcherFrame]).Continue = $false; return $null
        }, $frame) | Out-Null
    [System.Windows.Threading.Dispatcher]::PushFrame($frame)
}
function Set-Status($t) { $Status.Text = $t; Pump-UI }
function Set-Prog($p) { $Bar.IsIndeterminate = $false; $Bar.Value = $p; Pump-UI }
function Add-Log($t) { $LogBox.AppendText($t + "`r`n"); $LogBox.ScrollToEnd(); Pump-UI }

try {
    $ico = Join-Path $Root "src-tauri\icons\icon.ico"
    if (Test-Path -LiteralPath $ico) { $Window.Icon = [Windows.Media.Imaging.BitmapFrame]::Create((New-Object Uri $ico)) }
} catch {}
try {
    if (Test-Path -LiteralPath $ImgPath) {
        $bmp = New-Object Windows.Media.Imaging.BitmapImage
        $bmp.BeginInit()
        $bmp.UriSource = (New-Object Uri $ImgPath)
        $bmp.CacheOption = [Windows.Media.Imaging.BitmapCacheOption]::OnLoad
        $bmp.EndInit()
        $Cover.Source = $bmp
    }
} catch {}
if (Test-Path -LiteralPath $VidPath) {
    try { $Video.Source = (New-Object Uri $VidPath); $script:hasVideo = $true } catch {}
}
if (!$script:hasVideo) { $script:videoDone = $true }

function Show-Done($text) {
    Set-Prog 100
    Set-Status $text
    $InstallBtn.IsEnabled = $false
    if ($script:installedExe -and (Test-Path -LiteralPath $script:installedExe)) {
        $OpenBtn.Tag = $script:installedExe
        $OpenBtn.IsEnabled = $true
    }
    if ($Silent) { $Window.Close() }
}

$Video.add_MediaEnded({
    param($s, $e)
    if ($script:installDone) {
        # установка уже готова — досмотрели до конца, можно завершать
        $script:videoDone = $true
        try { $s.Stop() } catch {}
        Show-Done "Готово! Видео досмотрено. Открывайте приложение кнопкой ниже."
    } else {
        # установка ещё идёт, а ролик кончился — крутим заново
        try { $s.Position = [TimeSpan]::Zero; $s.Play() } catch {}
    }
})
$Video.add_MediaFailed({
    $script:videoDone = $true
    try { $Video.Visibility = "Collapsed" } catch {}
    Add-Log "Видео не воспроизвелось на этом ПК — продолжаю без него."
    if ($script:installDone) { Show-Done "Готово! Открывайте приложение кнопкой ниже." }
})

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
    $s.Description = "$AppName — обход DPI"
    $s.Save()
}
function Test-WebView2 {
    foreach ($p in @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$WvGuid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$WvGuid",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$WvGuid")) {
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
    foreach ($d in @($PortableDir, $NsisDir)) {
        $c = Join-Path $d "data\config.json"
        if (Test-Path -LiteralPath $c) {
            try {
                $z = (Get-Content -LiteralPath $c -Raw | ConvertFrom-Json).zapret_root
                if (Test-ZapretFolder $z) { return $z }
            } catch {}
        }
    }
    $cands = @()
    $cands += Get-ChildItem -LiteralPath $DeskDir -Directory -Filter "zapret-discord-youtube-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | ForEach-Object { $_.FullName }
    $cands += Join-Path $DeskDir "zapret-discord-youtube-main"
    $cands += Join-Path (Split-Path -Parent $Root) "zapret-discord-youtube-main"
    $cands += @("C:\zapret", "D:\zapret")
    foreach ($c in $cands) {
        if (Test-ZapretFolder $c) { return $c }
    }
    return $null
}
function Find-ManagerExe {
    $dev = Join-Path $Root "src-tauri\target\release\$ExeName"
    if (Test-Path -LiteralPath $dev) { return @{ Path = $dev; Kind = "dev-build" } }
    foreach ($p in @((Join-Path $NsisDir $ExeName), (Join-Path $PortableDir $ExeName))) {
        if (Test-Path -LiteralPath $p) { return @{ Path = $p; Kind = "installed" } }
    }
    $setup = Get-ChildItem (Join-Path $Root "src-tauri\target\release\bundle\nsis\*-setup.exe") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($setup) { return @{ Path = $setup.FullName; Kind = "nsis-bundle" } }
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
# Скачивание с живым окном: WebClient + крутим диспетчер, видео играет дальше
function Get-File($url, $dest, $label) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Set-Status "$label ..."
    $Bar.IsIndeterminate = $true; Pump-UI
    try {
        $wc = New-Object Net.WebClient
        $wc.Headers.Add("User-Agent", "ZapretManager-Installer")
        $wc.DownloadFileAsync((New-Object Uri $url), $dest)
        while ($wc.IsBusy) { Pump-UI; Start-Sleep -Milliseconds 200 }
        $wc.Dispose()
    } finally { $Bar.IsIndeterminate = $false; Pump-UI }
    if (!(Test-Path -LiteralPath $dest) -or ((Get-Item -LiteralPath $dest).Length -eq 0)) {
        throw "не скачался файл ($label)"
    }
}
function Get-ZapretRelease {
    $wr = New-Object Net.WebClient
    $wr.Headers.Add("User-Agent", "ZapretManager-Installer")
    $wr.Headers.Add("Accept", "application/vnd.github+json")
    $json = $wr.DownloadString("https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest")
    $wr.Dispose()
    $rel = $json | ConvertFrom-Json
    $tag = [string]$rel.tag_name
    $asset = $rel.assets | Where-Object { $_.name -like "zapret-discord-youtube-*.zip" } | Select-Object -First 1
    if (!$asset) { throw "в релизе нет zip-архива" }
    return @{ Tag = $tag; Url = [string]$asset.browser_download_url }
}

function Install-All {
    $InstallBtn.IsEnabled = $false
    $script:installDone = $false
    $script:videoDone = !$script:hasVideo
    try {
        if ($script:hasVideo) {
            try {
                # видео перекрывает картинку прямо в окне установщика
                $Video.Visibility = "Visible"
                $Video.Position = [TimeSpan]::Zero
                $Video.Play()
            } catch {}
            Add-Log "Видео запущено внутри установщика."
        }
        # [1/6] зависимости
        Set-Status "[1/6] Зависимости..."; Set-Prog 5
        if (!(Test-WebView2)) {
            Add-Log "WebView2 нет — качаю и ставлю..."
            $tmp = Join-Path $env:TEMP "zm_webview2.exe"
            Get-File "https://go.microsoft.com/fwlink/p/?LinkId=2124703" $tmp "Качаю WebView2"
            $p = Start-Process -FilePath $tmp -ArgumentList "/silent /install" -Wait -PassThru
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
            Add-Log ("WebView2: код " + $p.ExitCode)
        } else { Add-Log "WebView2 уже стоит." }
        if (!(Test-VcRedist)) {
            Add-Log "VC++ Redist нет — качаю и ставлю..."
            $tmp = Join-Path $env:TEMP "zm_vc.exe"
            Get-File "https://aka.ms/vs/17/release/vc_redist.x64.exe" $tmp "Качаю VC++ Redist"
            $p = Start-Process -FilePath $tmp -ArgumentList "/install /quiet /norestart" -Wait -PassThru
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
            Add-Log ("VC++: код " + $p.ExitCode)
        } else { Add-Log "VC++ Redist уже стоит." }

        # [2/6] программа
        Set-Status "[2/6] Программа..."; Set-Prog 25
        $m = Find-ManagerExe
        if (!$m) { throw "нет zapret-manager.exe: соберите проект или положите рядом setup.exe" }
        if ($m.Kind -eq "nsis-bundle") {
            Add-Log "Ставлю из NSIS-пакета (тихо)..."
            $p = Start-Process -FilePath $m.Path -ArgumentList "/S" -Wait -PassThru
            $script:installedExe = Join-Path $NsisDir $ExeName
            if (!(Test-Path -LiteralPath $script:installedExe)) { throw "NSIS-установщик заверёшился с кодом $($p.ExitCode), но exe не появился" }
        } elseif ($m.Kind -eq "dev-build") {
            Stop-App
            New-Item -ItemType Directory -Path $PortableDir -Force | Out-Null
            Copy-Item -LiteralPath $m.Path -Destination (Join-Path $PortableDir $ExeName) -Force
            $script:installedExe = Join-Path $PortableDir $ExeName
        } else {
            $script:installedExe = $m.Path
            Add-Log ("Уже стоит: " + $script:installedExe)
        }
        Add-Log ("Программа: " + $script:installedExe)
        # ассеты рядом с exe: funny, секретные архивы, музыка, видео мастера
        $srcAssets = Join-Path $Root "assets"
        if (Test-Path -LiteralPath $srcAssets) {
            Set-Status "[2/6] Программа: копирую картинки, архивы и музыку..."
            $dstAssets = Join-Path (Split-Path -Parent $script:installedExe) "assets"
            New-Item -ItemType Directory -Path $dstAssets -Force | Out-Null
            Copy-Item -Path (Join-Path $srcAssets "*") -Destination $dstAssets -Recurse -Force
            Add-Log "Ассеты скопированы."
        }
        # UAC-манифест (иначе sc -> FAILED 5): штампуем установленную копию
        try {
            $mt = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { Join-Path $_.FullName "x64\mt.exe" } |
                Where-Object { Test-Path -LiteralPath $_ } |
                Select-Object -First 1
            $mf = Join-Path $Root "src-tauri\app.manifest"
            if ($mt -and (Test-Path -LiteralPath $mf)) {
                Set-Status "[2/6] Программа: вшиваю UAC-манифест..."
                & $mt -nologo -manifest $mf ("-outputresource:" + $script:installedExe + ";#1") | Out-Null
                $chk = Join-Path $env:TEMP "zm-manifest-check.xml"
                & $mt -nologo ("-inputresource:" + $script:installedExe + ";#1") ("-out:" + $chk) | Out-Null
                if ((Get-Content -LiteralPath $chk -Raw -ErrorAction SilentlyContinue) -match "requireAdministrator") {
                    Add-Log "UAC-манифест вшит."
                } else {
                    Add-Log "Манифест не вшился!"
                }
                Remove-Item -LiteralPath $chk -Force -ErrorAction SilentlyContinue
            } else {
                Add-Log "Нет mt.exe: UAC не вшит."
            }
        } catch {
            Add-Log ("Не вшил UAC: " + $_.Exception.Message)
        }

        # [3/6] zapret
        Set-Status "[3/6] Папка zapret..."; Set-Prog 50
        $zpath = Find-Zapret
        if (!$zpath) {
            Add-Log "Локально нет — качаю свежий релиз Flowseal..."
            $rel = Get-ZapretRelease
            $safeTag = ($rel.Tag -replace '[^\w.\-]', '_').Trim('_')
            if (!$safeTag) { $safeTag = Get-Date -Format "yyyyMMdd" }
            $dest = Join-Path $DeskDir "zapret-discord-youtube-$safeTag"
            if (!(Test-ZapretFolder $dest)) {
                $zip = Join-Path $env:TEMP ("zapret_" + $safeTag + ".zip")
                Get-File $rel.Url $zip ("Качаю zapret " + $rel.Tag)
                $tmpDir = Join-Path $env:TEMP ("zapret_" + [IO.Path]::GetRandomFileName())
                New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
                Set-Status "Распаковываю zapret..."
                Expand-Archive -LiteralPath $zip -DestinationPath $tmpDir -Force
                $inner = Get-ChildItem -LiteralPath $tmpDir -Directory | Select-Object -First 1
                if ($inner -and (Test-Path -LiteralPath (Join-Path $inner.FullName "service.bat"))) { $srcDir = $inner.FullName }
                else { $srcDir = $tmpDir }
                if (!(Test-Path -LiteralPath (Join-Path $srcDir "service.bat"))) { throw "в архиве нет service.bat" }
                if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
                Move-Item -LiteralPath $srcDir -Destination $dest
                Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
                Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
            }
            $zpath = $dest
        }
        Add-Log ("zapret: " + $zpath)

        # [4/6] конфиг
        Set-Status "[4/6] Настройка..."; Set-Prog 72
        $cfgPath = Write-ManagerConfig $script:installedExe $zpath
        Add-Log ("Конфиг: " + $cfgPath)

        # [5/6] ярлыки
        Set-Status "[5/6] Ярлыки..."; Set-Prog 85
        $workDir = Split-Path -Parent $script:installedExe
        New-Shortcut (Join-Path $DeskDir "$AppName.lnk") $script:installedExe $workDir
        New-Shortcut (Join-Path $ProgDir "$AppName.lnk") $script:installedExe $workDir
        Add-Log "Ярлыки: рабочий стол + меню Пуск."

        # [6/6] готово
        Set-Prog 95
        $script:installDone = $true
        try {
            if ($script:hasVideo -and $Video.NaturalDuration.HasTimeSpan -and ($Video.Position -ge $Video.NaturalDuration.TimeSpan)) {
                $script:videoDone = $true
            }
        } catch {}
        if ($script:videoDone -or !$script:hasVideo) {
            Show-Done "Готово! Приложение настроено и знает, где zapret. Открывайте кнопкой ниже."
        } else {
            Set-Status "Установка готова! Досмотрите видео до конца — окно само скажет «Готово»."
            Add-Log "Установка обогнала ролик: жду конца видео (так задумано)."
            try { $Video.Play() } catch {}
            $InstallBtn.IsEnabled = $false
            if ($script:installedExe) { $OpenBtn.Tag = $script:installedExe; $OpenBtn.IsEnabled = $true }
        }
    } catch {
        $msg = $_.Exception.Message
        Set-Status ("Ошибка: " + $msg)
        Add-Log ("ОШИБКА: " + $msg)
        $InstallBtn.IsEnabled = $true
    }
}

$InstallBtn.add_Click({ Install-All })
$OpenBtn.add_Click({
    param($s, $e)
    if ($s.Tag -and (Test-Path -LiteralPath $s.Tag)) {
        Add-Log "Запускаю приложение (запрос UAC — это нормально)..."
        Start-Process -FilePath $s.Tag
    }
})
$CloseBtn.add_Click({ $Window.Close() })
$Window.add_Closing({
    try { $Video.Stop(); $Video.Source = $null } catch {}
})

if ($Silent) {
    $Window.add_ContentRendered({ Start-Sleep -Milliseconds 400; Install-All })
}

$Window.ShowDialog() | Out-Null
