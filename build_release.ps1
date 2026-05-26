Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "== VM Sync release build =="
Write-Host "Project: $Root"

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

Write-Host ""
Write-Host "Build complete:"
Write-Host (Join-Path $Root "dist\VM Sync")
