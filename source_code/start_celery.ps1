# Celery 启动脚本 (Windows / 开发环境)
# 用法：
#   .\start_celery.ps1 worker    # 启动 Worker
#   .\start_celery.ps1 beat      # 启动 Beat
#   .\start_celery.ps1 all       # 启动 Worker + Beat
#   .\start_celery.ps1 status    # 检查状态
#   .\start_celery.ps1 stop      # 停止所有

param(
    [Parameter(Position=0)]
    [string]$Action = "all"
)

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$LogDir = Join-Path $ProjectDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Start-Worker {
    Write-Host "[Celery] Starting Worker..." -ForegroundColor Cyan
    $env:PYTHONUNBUFFERED = "1"
    Start-Process -FilePath "celery" `
        -ArgumentList "-A","backend.core.celery_app","worker","--loglevel=info","--concurrency=4","-P","solo","-Q","scheduled,trade,ai,backtest,default" `
        -NoNewWindow `
        -RedirectStandardOutput "$LogDir\celery_worker.log" `
        -RedirectStandardError "$LogDir\celery_worker_error.log"
    Write-Host "[Celery] Worker started (logs: logs\celery_worker.log)" -ForegroundColor Green
}

function Start-Beat {
    Write-Host "[Celery] Starting Beat..." -ForegroundColor Cyan
    $env:PYTHONUNBUFFERED = "1"
    Start-Process -FilePath "celery" `
        -ArgumentList "-A","backend.core.celery_app","beat","--loglevel=info","--schedule=$LogDir\celerybeat-schedule" `
        -NoNewWindow `
        -RedirectStandardOutput "$LogDir\celery_beat.log" `
        -RedirectStandardError "$LogDir\celery_beat_error.log"
    Write-Host "[Celery] Beat started (logs: logs\celery_beat.log)" -ForegroundColor Green
}

function Stop-Celery {
    Write-Host "[Celery] Stopping all Celery processes..." -ForegroundColor Yellow
    Get-Process -Name "celery" -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "[Celery] All stopped." -ForegroundColor Green
}

function Show-Status {
    $procs = Get-Process -Name "celery" -ErrorAction SilentlyContinue
    if ($procs) {
        Write-Host "[Celery] Running processes:" -ForegroundColor Green
        $procs | Format-Table Id, CPU, WorkingSet, StartTime -AutoSize
    } else {
        Write-Host "[Celery] No running processes." -ForegroundColor Yellow
    }
}

switch ($Action.ToLower()) {
    "worker" { Start-Worker }
    "beat"   { Start-Beat }
    "all"    { Start-Worker; Start-Beat }
    "stop"   { Stop-Celery }
    "status" { Show-Status }
    default  { Write-Host "Usage: .\start_celery.ps1 [worker|beat|all|stop|status]" }
}
