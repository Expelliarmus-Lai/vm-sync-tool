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

Copy-Item -LiteralPath (Join-Path $Root "docs\USER_GUIDE.md") -Destination (Join-Path $Root "dist\VM Sync\README.md") -Force
Copy-Item -LiteralPath (Join-Path $Root "config.example.json") -Destination (Join-Path $Root "dist\VM Sync\config.example.json") -Force
$RuntimeConfig = Join-Path $Root "dist\VM Sync\config.json"
if (Test-Path $RuntimeConfig) {
    Remove-Item -LiteralPath $RuntimeConfig -Force
}

Write-Host ""
Write-Host "Build complete:"
Write-Host (Join-Path $Root "dist\VM Sync")
