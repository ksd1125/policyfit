# 정책핏 서버 시작 + 브라우저 자동 열기 (PowerShell)
#
# 사용법:
#   .\policyfit-start.ps1                  # 기본 (8090 포트)
#   .\policyfit-start.ps1 -Port 8091        # 다른 포트
#   .\policyfit-start.ps1 -NoOpen           # 브라우저 자동 열기 안 함
#   .\policyfit-start.ps1 -Stop             # 실행 중인 서버 중지
#
# 동작:
#   1. 같은 포트에 이미 떠있으면 → 그 서버를 재사용 (브라우저만 열기)
#   2. 안 떠있으면 → 새 서버 백그라운드로 시작 + 브라우저 열기

param(
    [int]$Port = 8090,
    [switch]$NoOpen,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'

# ── 프로젝트 루트 경로 (스크립트 위치 기준) ──
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputsDir = Join-Path $ProjectRoot 'outputs'
$AppUrl = "http://localhost:$Port/policyfit/index.html"

Write-Host "`n=== 정책핏 서버 ===" -ForegroundColor Cyan
Write-Host "프로젝트: $ProjectRoot"
Write-Host "URL: $AppUrl`n"

# ── 포트 점유 확인 ──
function Get-PortPid {
    param([int]$P)
    $line = netstat -ano | Select-String ":$P\s.*LISTENING"
    if ($line) {
        $parts = ($line -split '\s+') | Where-Object { $_ -ne '' }
        return [int]$parts[-1]
    }
    return $null
}

# ── --Stop 모드 ──
if ($Stop) {
    $existingPid = Get-PortPid -P $Port
    if ($existingPid) {
        Write-Host "포트 $Port 점유 프로세스(PID $existingPid) 종료..." -ForegroundColor Yellow
        Stop-Process -Id $existingPid -Force
        Write-Host "✓ 서버 중지 완료" -ForegroundColor Green
    } else {
        Write-Host "포트 $Port 에 실행 중인 서버 없음" -ForegroundColor Gray
    }
    exit 0
}

# ── 1) 이미 떠있는지 확인 ──
$existingPid = Get-PortPid -P $Port
if ($existingPid) {
    # 실제 연결되는지 한번 더 검증
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$Port" -TimeoutSec 2 -UseBasicParsing
        Write-Host "✓ 서버 이미 실행 중 (PID $existingPid) — 재사용" -ForegroundColor Green
    } catch {
        Write-Host "⚠ 포트 $Port 점유 중인데 응답 없음 — 종료 후 재시작" -ForegroundColor Yellow
        Stop-Process -Id $existingPid -Force
        Start-Sleep -Milliseconds 500
        $existingPid = $null
    }
}

# ── 2) 새 서버 시작 (필요 시) ──
if (-not $existingPid) {
    if (-not (Test-Path $OutputsDir)) {
        Write-Host "❌ outputs 디렉토리 없음: $OutputsDir" -ForegroundColor Red
        exit 1
    }

    Write-Host "서버 시작 (포트 $Port, outputs/ 제공)..." -ForegroundColor Cyan

    # 백그라운드 프로세스로 띄움 — Hidden 창
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'python'
    $psi.Arguments = "-m http.server $Port --directory `"$OutputsDir`""
    $psi.WorkingDirectory = $ProjectRoot
    $psi.WindowStyle = 'Hidden'
    $psi.UseShellExecute = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    Write-Host "✓ PID $($proc.Id) 시작됨" -ForegroundColor Green

    # 응답 대기 (최대 5초)
    $ready = $false
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $null = Invoke-WebRequest -Uri "http://localhost:$Port" -TimeoutSec 1 -UseBasicParsing
            $ready = $true
            break
        } catch {
            # 아직 응답 안 함, 재시도
        }
    }
    if ($ready) {
        Write-Host "✓ 서버 응답 확인" -ForegroundColor Green
    } else {
        Write-Host "⚠ 서버 응답 지연 — 브라우저에서 직접 새로고침 필요" -ForegroundColor Yellow
    }
}

# ── 3) 브라우저 자동 열기 ──
if (-not $NoOpen) {
    Write-Host "`n브라우저 열기: $AppUrl" -ForegroundColor Cyan
    Start-Process $AppUrl
}

Write-Host "`n--- 사용 가능한 페이지 ---" -ForegroundColor Gray
Write-Host "  앱   : http://localhost:$Port/policyfit/index.html"
Write-Host "  편집기: http://localhost:$Port/policyfit/editor.html"
Write-Host ""
Write-Host "서버 중지: .\policyfit-start.ps1 -Stop" -ForegroundColor Gray
