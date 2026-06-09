$ErrorActionPreference = "Stop"

$Project = "C:\Users\sudon\Desktop\cowork\project\mail-handoff-lite-20260601-1745"
$Outputs = Join-Path $Project "outputs"
$Scripts = Join-Path $Project "scripts"
$Tests = Join-Path $Project "tests"
$Staging = Join-Path $Outputs "_claude-validation"

Set-Location $Project

Write-Host "`n[1/5] Python environment"
python --version
python -c "import importlib.util; names=['numpy','pandas','scipy','sklearn','statsmodels']; print({n: bool(importlib.util.find_spec(n)) for n in names})"

Write-Host "`n[2/5] Knowledge DB regression tests"
python -m unittest discover -s $Tests -p "test_*.py" -v

Write-Host "`n[3/5] Validate committed pre-allocation outputs"
python (Join-Path $Scripts "validate-ml-preallocation.py") `
  --knowledge-db (Join-Path $Outputs "knowledge-db.json") `
  --allocation-json (Join-Path $Outputs "ml-preallocation.json") `
  --allocation-csv (Join-Path $Outputs "ml-preallocation.csv")

Write-Host "`n[4/5] Rebuild pre-allocation into an isolated validation folder"
New-Item -ItemType Directory -Force -Path $Staging | Out-Null
python (Join-Path $Scripts "build-ml-preallocation.py") `
  --input (Join-Path $Outputs "knowledge-db.json") `
  --output-dir $Staging

python (Join-Path $Scripts "validate-ml-preallocation.py") `
  --knowledge-db (Join-Path $Outputs "knowledge-db.json") `
  --allocation-json (Join-Path $Staging "ml-preallocation.json") `
  --allocation-csv (Join-Path $Staging "ml-preallocation.csv")

Write-Host "`n[5/5] Compare reproducibility hashes"
Get-FileHash (Join-Path $Outputs "ml-preallocation.json"), (Join-Path $Staging "ml-preallocation.json") -Algorithm SHA256
Get-FileHash (Join-Path $Outputs "ml-preallocation.csv"), (Join-Path $Staging "ml-preallocation.csv") -Algorithm SHA256

Write-Host "`nValidation command bundle completed."
