$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location ..

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name "Breitbandmessung-Automat" `
  --collect-submodules pywinauto `
  --collect-submodules comtypes `
  --collect-submodules win32com `
  breitbandmessung_automate_stateful.py

Write-Host "Built: dist\\Breitbandmessung-Automat.exe"

