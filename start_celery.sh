#!/bin/bash
# Celery 启动脚本 (Linux)
# 用法：
#   ./start_celery.sh worker    # 启动 Worker
#   ./start_celery.sh beat      # 启动 Beat
#   ./start_celery.sh all       # 启动 Worker + Beat
#   ./start_celery.sh stop      # 停止所有
#   ./start_celery.sh status    # 检查状态

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

export PYTHONUNBUFFERED=1

case "$1" in
    worker)
        echo "[Celery] Starting Worker..."
        celery -A backend.core.celery_app worker \
            --loglevel=info \
            --concurrency=4 \
            --pool=prefork \
            -Q scheduled,trade,ai,backtest,default \
            > "$LOG_DIR/celery_worker.log" 2>&1 &
        echo "[Celery] Worker PID=$! (logs: logs/celery_worker.log)"
        ;;

    beat)
        echo "[Celery] Starting Beat..."
        celery -A backend.core.celery_app beat \
            --loglevel=info \
            --schedule="$LOG_DIR/celerybeat-schedule" \
            > "$LOG_DIR/celery_beat.log" 2>&1 &
        echo "[Celery] Beat PID=$! (logs: logs/celery_beat.log)"
        ;;

    all)
        echo "[Celery] Starting Worker + Beat..."
        celery -A backend.core.celery_app worker \
            --loglevel=info \
            --concurrency=4 \
            --pool=prefork \
            -Q scheduled,trade,ai,backtest,default \
            > "$LOG_DIR/celery_worker.log" 2>&1 &
        echo "[Celery] Worker PID=$!"
        celery -A backend.core.celery_app beat \
            --loglevel=info \
            --schedule="$LOG_DIR/celerybeat-schedule" \
            > "$LOG_DIR/celery_beat.log" 2>&1 &
        echo "[Celery] Beat PID=$!"
        ;;

    stop)
        echo "[Celery] Stopping all Celery processes..."
        pkill -f "celery.*backend.core.celery_app" 2>/dev/null || true
        echo "[Celery] All stopped."
        ;;

    status)
        ps aux | grep "[c]elery.*backend.core.celery_app" || echo "[Celery] No running processes."
        ;;

    *)
        echo "Usage: $0 {worker|beat|all|stop|status}"
        exit 1
        ;;
esac
