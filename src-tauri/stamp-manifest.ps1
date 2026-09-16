# Stamps UAC manifest (requireAdministrator) into the built exe.
# Runs via beforeBundleCommand before packaging.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $root "target\release\zapret-manager.exe"
$manifest = Join-Path $root "app.manifest"
if (!(Test-Path $exe)) { Write-Error "[stamp] no exe: $exe"; exit 1 }
if (!(Test-Path $manifest)) { Write-Error "[stamp] no manifest: $manifest"; exit 1 }
$mt = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Directory -ErrorAction SilentlyContinue |
  Sort-Object Name -Descending |
  ForEach-Object { Join-Path $_.FullName "x64\mt.exe" } |
  Where-Object { Test-Path $_ } |
  Select-Object -First 1
if (!$mt) { Write-Error "[stamp] mt.exe not found (Windows SDK required)"; exit 1 }
& $mt -nologo -manifest $manifest "-outputresource:$exe;#1"
if ($LASTEXITCODE -ne 0) { Write-Error "[stamp] mt stamp failed"; exit 1 }
$tmp = Join-Path $env:TEMP "zm-manifest-check.xml"
& $mt -nologo "-inputresource:$exe;#1" "-out:$tmp" | Out-Null
if ((Get-Content $tmp -Raw) -notmatch "requireAdministrator") {
  Write-Error "[stamp] VERIFY FAILED: requireAdministrator missing"; exit 1
}
Write-Host "[stamp] OK: requireAdministrator embedded"
