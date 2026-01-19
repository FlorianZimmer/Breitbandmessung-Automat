$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location ..

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

$repoRoot = (Get-Location).Path
$distPath = Join-Path $repoRoot "dist"
$tempRoot = Join-Path $env:TEMP "Breitbandmessung-Automat-pyinstaller"
$workPath = Join-Path $tempRoot "build"
$specPath = $tempRoot

# Avoid permission issues in OneDrive-synced folders by using a temp work/spec dir.
Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue | Out-Null
New-Item -ItemType Directory -Force -Path $workPath, $distPath, $specPath | Out-Null

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name "Breitbandmessung-Automat" `
  --workpath "$workPath" `
  --specpath "$specPath" `
  --distpath "$distPath" `
  --collect-submodules pywinauto `
  --collect-submodules comtypes `
  --collect-submodules win32com `
  breitbandmessung_automate_stateful.py

Write-Host "Built: dist\\Breitbandmessung-Automat.exe"
