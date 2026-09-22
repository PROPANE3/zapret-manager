<#
  Zapret Manager v2 — установщик с окном (без терминала).
  Запуск: двойной клик по Installer.vbs (терминала не будет вообще).

  Что делает:
  - Проверяет зависимости (WebView2, VC++ Redist)
  - Скачивает актуальную версию с GitHub (всегда свежую!)
  - Устанавливает zapret-discord-youtube
  - Настраивает конфиг, создаёт ярлыки
  - Запускает приложение
#>
param([switch]$Silent)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ([Threading.Thread]::CurrentThread.ApartmentState -ne "STA") {
    $arg = '-NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    if ($Silent) { $arg += " -Silent" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $arg
    exit 0
}

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$AppName = "Zapret Manager"
$ExeName = "zapret-manager.exe"
$InstallDir = Join-Path $env:LOCALAPPDATA "Zapret Manager"
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
    Start-Process -FilePath "powershell.exe" -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Root "tools\Setup.ps1") + '"')
    exit 0
}

$Xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Zapret Manager — установка" Width="760" Height="700"
        WindowStartupLocation="CenterScreen" ResizeMode="CanMinimize"
        Background="#0D0D0D" WindowStyle="SingleBorderWindow">
  <Window.Resources>
    <Style x:Key="BtnPrimary" TargetType="Button">
      <Setter Property="Background" Value="#E63946"/>
      <Setter Property="Foreground" Value="White"/>
      <Setter Property="FontWeight" Value="Bold"/>
      <Setter Property="FontSize" Value="14"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="6" Padding="0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#FF4D5A"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#C1121F"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Bd" Property="Background" Value="#555"/>
                <Setter Property="Foreground" Value="#999"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="BtnSecondary" TargetType="Button">
      <Setter Property="Background" Value="#2A2A2E"/>
      <Setter Property="Foreground" Value="#F1FAEE"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}" CornerRadius="6" Padding="0">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#3A3A40"/>
              </Trigger>
              <Trigger Property="IsPressed" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#1A1A1E"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="Bd" Property="Background" Value="#1A1A1E"/>
                <Setter Property="Foreground" Value="#555"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>
  <Grid Margin="20">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="340"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock Name="Title" Text="Zapret Manager"
                 FontSize="26" FontWeight="Bold" Foreground="#F1FAEE"/>
      <TextBlock Text="Установка в один клик — всё автоматически"
                 FontSize="13" Foreground="#6C6C70" Margin="0,4,0,0"/>
    </StackPanel>
    <Border Grid.Row="1" CornerRadius="12" Background="#1A1A1E" ClipToBounds="True" Margin="0,0,0,12"
            BorderBrush="#2A2A2E" BorderThickness="1">
      <Grid>
        <Image Name="Cover" Stretch="UniformToFill" Opacity="0.9"/>
        <MediaElement Name="Video" LoadedBehavior="Manual" UnloadedBehavior="Manual"
                      Stretch="Uniform" Volume="0.8" Visibility="Collapsed"/>
      </Grid>
    </Border>
    <TextBlock Grid.Row="2" Name="Status"
               Text="Нажмите «Установить» — зависимости, программа, zapret, ярлыки — всё само."
               Foreground="#A8DADC" FontSize="13" TextWrapping="Wrap" Margin="0,0,0,8"/>
    <Grid Grid.Row="3" Margin="0,0,0,10">
      <ProgressBar Name="Bar" Height="6" Minimum="0" Maximum="100" Value="0"
                   Background="#1A1A1E" Foreground="#E63946" BorderThickness="0"/>
    </Grid>
    <Border Grid.Row="4" CornerRadius="8" Background="#111114" Margin="0,0,0,10"
            BorderBrush="#2A2A2E" BorderThickness="1">
      <TextBox Name="Log" IsReadOnly="True" VerticalScrollBarVisibility="Auto"
               FontFamily="Cascadia Code, Consolas" FontSize="11.5"
               Background="Transparent" Foreground="#A8DADC"
               BorderThickness="0" Padding="10,8" TextWrapping="Wrap"/>
    </Border>
    <StackPanel Grid.Row="5" Orientation="Horizontal" HorizontalAlignment="Right">
      <Button Name="InstallBtn" Content="Установить" Width="140" Height="40"
              Margin="0,0,8,0" Style="{StaticResource BtnPrimary}"/>
      <Button Name="OpenBtn" Content="Открыть приложение" Width="170" Height="40"
              Margin="0,0,8,0" IsEnabled="False" Style="{StaticResource BtnSecondary}"/>
      <Button Name="CloseBtn" Content="Закрыть" Width="100" Height="40"
              Style="{StaticResource BtnSecondary}"/>
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
function Add-Log($t) { $LogBox.AppendText("  $t`r`n"); $LogBox.ScrollToEnd(); Pump-UI }

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
    if ($Silent) { $Window.Close(); return }
    
    # Автозакрытие через 5 секунд
    $timer = New-Object System.Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromSeconds(5)
    $timer.Add_Tick({
        param($s, $e)
        $s.Stop()
        $Window.Close()
    })
    $timer.Start()
    $Status.Text = "$text (окно закроется автоматически через 5 сек...)"
    Pump-UI
}

$Video.add_MediaEnded({
    param($s, $e)
    if ($script:installDone) {
        $script:videoDone = $true
        try { $s.Stop() } catch {}
        Show-Done "Готово! Можете открыть приложение."
    } else {
        try { $s.Position = [TimeSpan]::Zero; $s.Play() } catch {}
    }
})
$Video.add_MediaFailed({
    $script:videoDone = $true
    try { $Video.Visibility = "Collapsed" } catch {}
    Add-Log "Видео не воспроизвелось — продолжаю без него."
    if ($script:installDone) { Show-Done "Готово! Можете открыть приложение." }
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

function Get-CurrentVersion {
    $vFile = Join-Path $Root "version.txt"
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
    $dev = Join-Path $Root "src-tauri\target\release\$ExeName"
    if (Test-Path -LiteralPath $dev) {
        return @{ Path = $dev; Kind = "dev-build" }
    }
    
    # Локальный NSIS-бандл (свежесобранный) — приоритет над GitHub
    $setup = Get-ChildItem (Join-Path $Root "src-tauri\target\release\bundle\nsis\*-setup.exe") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($setup) {
        return @{ Path = $setup.FullName; Kind = "nsis-bundle" }
    }
    
    # Проверяем все возможные пути установки NSIS
    $installedPaths = @(
        (Join-Path $env:LOCALAPPDATA "Zapret Manager\$ExeName"),
        (Join-Path $env:LOCALAPPDATA "ZapretManager\$ExeName"),
        (Join-Path $env:LOCALAPPDATA "zapret-manager\$ExeName"),
        (Join-Path ${env:ProgramFiles} "Zapret Manager\$ExeName"),
        (Join-Path ${env:ProgramFiles(x86)} "Zapret Manager\$ExeName")
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

function Get-AppRelease {
    $wr = New-Object Net.WebClient
    $wr.Headers.Add("User-Agent", "ZapretManager-Installer")
    $wr.Headers.Add("Accept", "application/vnd.github+json")
    try {
        $json = $wr.DownloadString("https://api.github.com/repos/PROPANE3/zapret-manager/releases/latest")
    } finally { $wr.Dispose() }
    $rel = $json | ConvertFrom-Json
    $asset = $rel.assets | Where-Object { $_.name -like "*-setup.exe" } | Select-Object -First 1
    if (!$asset) { throw "в релизе на GitHub нет setup.exe" }
    return @{ Tag = [string]$rel.tag_name; Url = [string]$asset.browser_download_url; Name = [string]$asset.name }
}

function Install-All {
    $InstallBtn.IsEnabled = $false
    $script:installDone = $false
    $script:videoDone = !$script:hasVideo
    try {
        if ($script:hasVideo) {
            try {
                $Video.Visibility = "Visible"
                $Video.Position = [TimeSpan]::Zero
                $Video.Play()
            } catch {}
            Add-Log "Видео запущено."
        }

        $currentVer = Get-CurrentVersion
        Add-Log "Актуальная версия: $currentVer"

        # [1/5] зависимости
        Set-Status "[1/5] Проверка зависимостей..."; Set-Prog 5
        if (!(Test-WebView2)) {
            Add-Log "WebView2 нет — устанавливаю..."
            $tmp = Join-Path $env:TEMP "zm_webview2.exe"
            Get-File "https://go.microsoft.com/fwlink/p/?LinkId=2124703" $tmp "Качаю WebView2"
            $p = Start-Process -FilePath $tmp -ArgumentList "/silent /install" -Wait -PassThru
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
            Add-Log "WebView2 установлен (код $($p.ExitCode))"
        } else { Add-Log "WebView2 OK" }
        if (!(Test-VcRedist)) {
            Add-Log "VC++ Redist нет — устанавливаю..."
            $tmp = Join-Path $env:TEMP "zm_vc.exe"
            Get-File "https://aka.ms/vs/17/release/vc_redist.x64.exe" $tmp "Качаю VC++ Redist"
            $p = Start-Process -FilePath $tmp -ArgumentList "/install /quiet /norestart" -Wait -PassThru
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
            Add-Log "VC++ Redist установлен (код $($p.ExitCode))"
        } else { Add-Log "VC++ Redist OK" }

        # [2/5] программа
        Set-Status "[2/5] Установка программы..."; Set-Prog 25
        $m = Find-ManagerExe
        $needDownload = $false

        if (!$m) {
            Add-Log "Программа не найдена — скачаю с GitHub"
            $needDownload = $true
        } elseif ($m.Kind -eq "outdated") {
            $instVer = Get-InstalledVersion $m.Path
            Add-Log "Найдена устаревшая версия $instVer — обновлю до $currentVer"
            $needDownload = $true
        } elseif ($m.Kind -eq "dev-build") {
            Add-Log "Найдена dev-сборка, использую её"
        } elseif ($m.Kind -eq "nsis-bundle") {
            Add-Log "Найден NSIS-пакет, использую его"
        } else {
            Add-Log "Программа уже установлена (актуальная версия)"
        }

        if ($needDownload) {
            Set-Status "[2/5] Проверка GitHub..."
            Add-Log "Проверяю GitHub..."
            try {
                $arel = Get-AppRelease
                $ghVer = ($arel.Tag -replace '^v', '').Trim()
                Add-Log "Версия на GitHub: $ghVer"
                
                # Проверяем, что версия на GitHub действительно новее
                try {
                    if ([version]$ghVer -lt [version]$currentVer) {
                        Add-Log "ВНИМАНИЕ: На GitHub версия $ghVer старее локальной $currentVer"
                        Add-Log "Необходимо собрать проект локально или опубликовать новый релиз"
                        # Если есть установленная версия, используем её вместо скачивания
                        if ($m.Kind -eq "outdated") {
                            Add-Log "Использую установленную версию (обновите позже)"
                            $needDownload = $false
                        }
                    }
                } catch {}
                
                if ($needDownload) {
                    Set-Status "[2/5] Скачивание актуальной версии с GitHub..."
                    $asetup = Join-Path $env:TEMP $arel.Name
                    Get-File $arel.Url $asetup "Качаю $($arel.Name)"
                    $m = @{ Path = $asetup; Kind = "dl-setup" }
                }
            } catch {
                Add-Log "Не удалось проверить GitHub: $($_.Exception.Message)"
                if ($m.Kind -eq "outdated") {
                    Add-Log "Использую установленную версию"
                    $needDownload = $false
                }
            }
        }

        if ($m.Kind -eq "nsis-bundle" -or $m.Kind -eq "dl-setup") {
            Add-Log "Устанавливаю из NSIS-пакета..."
            Stop-App
            $p = Start-Process -FilePath $m.Path -ArgumentList "/S" -Wait -PassThru
            
            # Ищем exe в нескольких возможных местах (Tauri NSIS может ставить в разные пути)
            $possiblePaths = @(
                (Join-Path $env:LOCALAPPDATA "Zapret Manager\$ExeName"),
                (Join-Path $env:LOCALAPPDATA "ZapretManager\$ExeName"),
                (Join-Path $env:LOCALAPPDATA "zapret-manager\$ExeName"),
                (Join-Path ${env:ProgramFiles} "Zapret Manager\$ExeName"),
                (Join-Path ${env:ProgramFiles(x86)} "Zapret Manager\$ExeName")
            )
            
            $script:installedExe = $null
            foreach ($testPath in $possiblePaths) {
                if (Test-Path -LiteralPath $testPath) {
                    $script:installedExe = $testPath
                    break
                }
            }
            
            if (!$script:installedExe) {
                # Финальная попытка — ищем рекурсивно в LocalAppData
                $found = Get-ChildItem -Path $env:LOCALAPPDATA -Filter $ExeName -Recurse -ErrorAction SilentlyContinue |
                    Where-Object { $_.DirectoryName -like "*zapret*" } |
                    Select-Object -First 1
                if ($found) {
                    $script:installedExe = $found.FullName
                }
            }
            
            if (!$script:installedExe) {
                throw "NSIS-установщик завершился (код $($p.ExitCode)), но exe не найден. Проверьте, куда установилась программа."
            }
            
            if ($m.Kind -eq "dl-setup") { Remove-Item -LiteralPath $m.Path -Force -ErrorAction SilentlyContinue }
            Add-Log "Программа установлена: $script:installedExe"
        } elseif ($m.Kind -eq "dev-build") {
            Stop-App
            New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
            Copy-Item -LiteralPath $m.Path -Destination (Join-Path $InstallDir $ExeName) -Force
            $script:installedExe = Join-Path $InstallDir $ExeName
            Add-Log "Dev-сборка скопирована"
        } else {
            $script:installedExe = $m.Path
            Add-Log "Использую существующую установку"
        }

        # ассеты
        $srcAssets = Join-Path $Root "assets"
        if (Test-Path -LiteralPath $srcAssets) {
            Set-Status "[2/5] Копирование ресурсов..."
            $dstAssets = Join-Path (Split-Path -Parent $script:installedExe) "assets"
            New-Item -ItemType Directory -Path $dstAssets -Force | Out-Null
            Copy-Item -Path (Join-Path $srcAssets "*") -Destination $dstAssets -Recurse -Force
            Add-Log "Ресурсы скопированы"
        }

        # UAC-манифест
        try {
            $mt = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { Join-Path $_.FullName "x64\mt.exe" } |
                Where-Object { Test-Path -LiteralPath $_ } |
                Select-Object -First 1
            $mf = Join-Path $Root "src-tauri\app.manifest"
            if ($mt -and (Test-Path -LiteralPath $mf)) {
                Set-Status "[2/5] Встраивание UAC-манифеста..."
                & $mt -nologo -manifest $mf ("-outputresource:" + $script:installedExe + ";#1") | Out-Null
                Add-Log "UAC-манифест встроен"
            }
        } catch {
            Add-Log "Не удалось вшить UAC-манифест: $($_.Exception.Message)"
        }

        # [3/5] zapret
        Set-Status "[3/5] Настройка zapret..."; Set-Prog 55
        $zpath = Find-Zapret
        if (!$zpath) {
            Add-Log "zapret не найден — скачаю свежий релиз..."
            $rel = Get-ZapretRelease
            $safeTag = ($rel.Tag -replace '[^\w.\-]', '_').Trim('_')
            if (!$safeTag) { $safeTag = Get-Date -Format "yyyyMMdd" }
            $dest = Join-Path $DeskDir "zapret-discord-youtube-$safeTag"
            if (!(Test-ZapretFolder $dest)) {
                $zip = Join-Path $env:TEMP ("zapret_" + $safeTag + ".zip")
                Get-File $rel.Url $zip "Качаю zapret $($rel.Tag)"
                $tmpDir = Join-Path $env:TEMP ("zapret_" + [IO.Path]::GetRandomFileName())
                New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
                Set-Status "Распаковка zapret..."
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
            Add-Log "zapret скачан: $zpath"
        } else {
            Add-Log "zapret найден: $zpath"
        }

        # [4/5] конфиг
        Set-Status "[4/5] Настройка конфигурации..."; Set-Prog 78
        $cfgPath = Write-ManagerConfig $script:installedExe $zpath
        Add-Log "Конфиг записан"

        # [5/5] ярлыки
        Set-Status "[5/5] Создание ярлыков..."; Set-Prog 90
        $workDir = Split-Path -Parent $script:installedExe
        New-Shortcut (Join-Path $DeskDir "$AppName.lnk") $script:installedExe $workDir
        New-Shortcut (Join-Path $ProgDir "$AppName.lnk") $script:installedExe $workDir
        Add-Log "Ярлыки созданы (рабочий стол + меню Пуск)"

        # запуск
        Set-Prog 95
        $script:installDone = $true
        try {
            Start-Process -FilePath $script:installedExe
            Add-Log "Приложение запущено!"
        } catch {
            Add-Log "Не удалось запустить автоматически — откройте кнопкой ниже"
        }

        try {
            if ($script:hasVideo -and $Video.NaturalDuration.HasTimeSpan -and ($Video.Position -ge $Video.NaturalDuration.TimeSpan)) {
                $script:videoDone = $true
            }
        } catch {}
        if ($script:videoDone -or !$script:hasVideo) {
            Show-Done "Установка завершена! Приложение запущено."
        } else {
            Set-Status "Установка завершена! Досмотрите видео до конца."
            try { $Video.Play() } catch {}
            $InstallBtn.IsEnabled = $false
            if ($script:installedExe) { $OpenBtn.Tag = $script:installedExe; $OpenBtn.IsEnabled = $true }
        }
    } catch {
        $msg = $_.Exception.Message
        Set-Status "Ошибка: $msg"
        Add-Log "ОШИБКА: $msg"
        $InstallBtn.IsEnabled = $true
    }
}

$InstallBtn.add_Click({ Install-All })
$OpenBtn.add_Click({
    param($s, $e)
    if ($s.Tag -and (Test-Path -LiteralPath $s.Tag)) {
        Add-Log "Запускаю приложение..."
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
