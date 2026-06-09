$ErrorActionPreference = "Stop"

$Project = "C:\Users\sudon\Desktop\cowork\project\mail-handoff-lite-20260601-1745"
$Outputs = Join-Path $Project "outputs"
$Scripts = Join-Path $Project "scripts"
$Destination = Join-Path $Outputs "ml-taxonomy-benchmark-20260602"

Set-Location $Project
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

python (Join-Path $Scripts "run-ml-taxonomy-benchmark.py") `
  --knowledge-db (Join-Path $Outputs "knowledge-db.json") `
  --preallocation (Join-Path $Outputs "ml-preallocation.csv") `
  --pilot-script (Join-Path $Scripts "run-ml-taxonomy-pilot.py") `
  --output-dir $Destination `
  --k-min 4 `
  --k-max 16 `
  --bootstrap 48 `
  --group-folds 5 `
  --blrt-bootstrap 12 `
  --seed 20260602
