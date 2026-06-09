param(
  [int]$Port = 8090,
  [string]$ProjectRoot = "C:\Users\sudon\Desktop\cowork\project\mail-handoff-lite-20260601-1745",
  [string]$Page = "policyfit/index.html"
)

$ErrorActionPreference = "Stop"

$OutputDir = Join-Path $ProjectRoot "outputs"
$TargetUrl = "http://localhost:$Port/$Page"

if (-not (Test-Path -LiteralPath $OutputDir -PathType Container)) {
  throw "Output directory not found: $OutputDir"
}

$IndexPath = Join-Path $OutputDir $Page
if (-not (Test-Path -LiteralPath $IndexPath -PathType Leaf)) {
  throw "Page not found: $IndexPath"
}

Write-Host "Project: $ProjectRoot"
Write-Host "Serving: $OutputDir"
Write-Host "URL: $TargetUrl"

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
  if ($proc -and $proc.CommandLine -like "*http.server $Port*") {
    Write-Host "Stopping existing Python http.server on port $Port (PID $($listener.OwningProcess))"
    Stop-Process -Id $listener.OwningProcess -Force
  } elseif ($listener.OwningProcess) {
    throw "Port $Port is already used by PID $($listener.OwningProcess). Stop it first or run with another -Port."
  }
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  $python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $python) {
  throw "Python was not found in PATH."
}

$arguments = "-m http.server $Port --directory outputs"
Start-Process -FilePath $python.Source -ArgumentList $arguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden

Start-Sleep -Milliseconds 700
Start-Process $TargetUrl
Write-Host "Opened $TargetUrl"
