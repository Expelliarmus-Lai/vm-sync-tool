Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$ReleaseVersion = if ($env:VM_SYNC_VERSION) { $env:VM_SYNC_VERSION } else { "v1.3.0" }
$ReleaseZip = Join-Path $Root ("dist\VM-Sync-{0}.zip" -f $ReleaseVersion)

Write-Host "== VM Sync release build =="
Write-Host "Project: $Root"
Write-Host "Version: $ReleaseVersion"

python -m PyInstaller --clean --noconfirm "VM Sync.spec"

$Exe = Join-Path $Root "dist\VM Sync\VM Sync.exe"
if (-not (Test-Path $Exe)) {
    throw "Build failed: $Exe was not created."
}

$ReleaseDir = Join-Path $Root "dist\VM Sync"
$ReadmeCn = Join-Path $ReleaseDir "README.md"
$ReadmeEn = Join-Path $ReleaseDir "README.en.md"

Copy-Item -LiteralPath (Join-Path $Root "docs\USER_GUIDE.md") -Destination $ReadmeCn -Force
Copy-Item -LiteralPath (Join-Path $Root "docs\USER_GUIDE.en.md") -Destination $ReadmeEn -Force
Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination (Join-Path $ReleaseDir "LICENSE") -Force
Copy-Item -LiteralPath (Join-Path $Root "CHANGELOG.md") -Destination (Join-Path $ReleaseDir "CHANGELOG.md") -Force
Copy-Item -LiteralPath (Join-Path $Root "CHANGELOG.en.md") -Destination (Join-Path $ReleaseDir "CHANGELOG.en.md") -Force

$ReadmeCnText = Get-Content -LiteralPath $ReadmeCn -Raw -Encoding UTF8
$ReadmeCnText = $ReadmeCnText.Replace("(USER_GUIDE.md)", "(README.md)").Replace("(USER_GUIDE.en.md)", "(README.en.md)")
Set-Content -LiteralPath $ReadmeCn -Value $ReadmeCnText -Encoding UTF8

$ReadmeEnText = Get-Content -LiteralPath $ReadmeEn -Raw -Encoding UTF8
$ReadmeEnText = $ReadmeEnText.Replace("(USER_GUIDE.md)", "(README.md)").Replace("(USER_GUIDE.en.md)", "(README.en.md)")
Set-Content -LiteralPath $ReadmeEn -Value $ReadmeEnText -Encoding UTF8

Copy-Item -LiteralPath (Join-Path $Root "config.example.json") -Destination (Join-Path $Root "dist\VM Sync\config.example.json") -Force
$RuntimeConfig = Join-Path $Root "dist\VM Sync\config.json"
if (Test-Path $RuntimeConfig) {
    Remove-Item -LiteralPath $RuntimeConfig -Force
}

if (Test-Path $ReleaseZip) {
    Remove-Item -LiteralPath $ReleaseZip -Force
}
Compress-Archive -LiteralPath $ReleaseDir -DestinationPath $ReleaseZip -Force
$ReleaseHash = Get-FileHash -LiteralPath $ReleaseZip -Algorithm SHA256

Write-Host ""
Write-Host "Build complete:"
Write-Host (Join-Path $Root "dist\VM Sync")
Write-Host $ReleaseZip
Write-Host ("SHA256: {0}" -f $ReleaseHash.Hash.ToLowerInvariant())
