# Тост в Центр уведомлений Windows (без сторонних модулей, чистый WinRT).
# Вызов: powershell -File notify.ps1 -Title "..." -Text "..." -AppId "..." [-Icon "C:\...\icon.png"]
param(
    [string]$Title = "Zapret Manager",
    [string]$Text = "",
    [string]$AppId = "Flowseal.ZapretManager",
    [string]$Icon = ""
)

[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] > $null

function Esc([string]$s) {
    if ([string]::IsNullOrEmpty($s)) { return "" }
    return [System.Security.SecurityElement]::Escape($s)
}

$img = ""
if ($Icon -ne "" -and (Test-Path -LiteralPath $Icon)) {
    $uri = (New-Object System.Uri($Icon)).AbsoluteUri
    $img = "<image placement=`"appLogoOverride`" src=`"$uri`"/>"
}

$xmlText = "<toast><visual><binding template=`"ToastGeneric`">$img<text>$(Esc $Title)</text><text>$(Esc $Text)</text></binding></visual></toast>"
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($xmlText)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId).Show($toast)
