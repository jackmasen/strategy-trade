#!/usr/bin/env bash
# =========================================================================
# 策略交易系统 · onepress 一键安装脚本（WordPress 式体验）
# 宝塔用户：
#   1) 上传 onepress zip → 解压到站点根（例如 /www/wwwroot/trade.xxx.com/）
#   2) 在站点根终端里执行：bash deploy/onepress-install.sh
#
# 脚本做的事：
#   - 检测 Python 3.10+（系统自带 / 宝塔 Python 管理器版本）
#   - 自动创建 .venv + 用清华镜像 pip install -r requirements.txt
#   - 用 nohup 后台启动 uvicorn（127.0.0.1:8000），日志写 logs/uvicorn.log
#   - 最后打印下一步：浏览器访问域名进入 /install 向导
# =========================================================================
set -euo pipefail

# -------------------------- 彩色输出 --------------------------
RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'; BLUE='\033[36m'; RESET='\033[0m'
info(){ echo -e "${BLUE}[INFO]${RESET} $*"; }
ok(){   echo -e "${GREEN}[ OK ]${RESET} $*"; }
warn(){ echo -e "${YELLOW}[WARN]${RESET} $*"; }
die(){  echo -e "${RED}[FAIL]${RESET} $*"; exit 1; }

# -------------------------- 进入项目根 --------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
cd "$PROJECT_ROOT"
info "项目根：$PROJECT_ROOT"

# -------------------------- 找 Python 3.10+ --------------------------
PY_BIN=""
for candidate in \
    python3.12 python3.11 python3.10 python3 \
    /www/server/panel/pyenv/bin/python3.12 \
    /www/server/panel/pyenv/bin/python3.11 \
    /www/server/panel/pyenv/bin/python3.10 \
    /usr/bin/python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c 'import sys;v=sys.version_info;print(v.major*100+v.minor)' 2>/dev/null || true)
        if [[ "$ver" -ge 310 ]]; then
            PY_BIN="$candidate"
            break
        fi
    fi
done
if [[ -z "$PY_BIN" ]]; then
    die "未找到 Python 3.10+。请在宝塔→软件商店安装「Python 项目管理器」→安装 Python 3.10/3.11/3.12 后再运行本脚本。"
fi
ok "Python 可执行文件：$PY_BIN（$($PY_BIN --version 2>&1)）"

# -------------------------- 准备 venv --------------------------
VENV_DIR="$PROJECT_ROOT/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
    info "创建 Python 虚拟环境 .venv ..."
    "$PY_BIN" -m venv "$VENV_DIR"
fi
PIP="$VENV_DIR/bin/pip"
PY="$VENV_DIR/bin/python"
[[ -x "$PIP" ]] || die "虚拟环境的 pip 不存在：$PIP"
[[ -x "$PY"  ]] || die "虚拟环境的 python 不存在：$PY"
ok "虚拟环境就绪：$VENV_DIR"

# -------------------------- pip install --------------------------
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
REQ="$PROJECT_ROOT/requirements.txt"
[[ -f "$REQ" ]] || die "找不到 requirements.txt，当前目录是否正确？（当前 PROJECT_ROOT=$PROJECT_ROOT）"
info "升级 pip（走清华镜像）..."
"$PIP" install --upgrade pip setuptools wheel -i "$MIRROR" || \
    warn "pip 升级失败，继续使用旧版本..."
info "安装依赖（requirements.txt），首次可能需要 3~8 分钟 ..."
if ! "$PIP" install -r "$REQ" -i "$MIRROR"; then
    warn "清华镜像安装失败，退回官方源重试..."
    "$PIP" install -r "$REQ"
fi
ok "依赖安装完成。"

# -------------------------- 建 logs 目录 / 旧进程清理 --------------------------
mkdir -p "$PROJECT_ROOT/logs"
LOG_FILE="$PROJECT_ROOT/logs/uvicorn.log"
PID_FILE="$PROJECT_ROOT/logs/uvicorn.pid"
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        warn "检测到旧 uvicorn 进程 PID=$OLD_PID 仍在运行，先停止 ..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
    fi
    rm -f "$PID_FILE"
fi

# -------------------------- 启动后端（nohup 后台） --------------------------
BACKEND_PORT="${BACKEND_PORT:-8000}"
BIND_HOST="127.0.0.1"  # 只监听回环，Nginx 反代过来（安全）
info "后台启动 uvicorn （bind=$BIND_HOST:$BACKEND_PORT，PID 写入 $PID_FILE）..."

# -------------------------- WordPress 式收尾 ①：把根下静态安装入口 index.html 移走 --------------------------
# 因为未安装时我们靠 Nginx 默认 index.html 展示安装向导；
# 现在 uvicorn 起来了，就应该让 FastAPI 的状态机接管 / 路由（未安装 307 跳 /install）。
# 所以把 zip 根那个 index.html（就是 _onepress_wordpress_entry.html）重命名为 .bak，
# 避免 Nginx 的 index 指令还在返回静态页、盖过后端 / 路由。
ENTRY_HTML="$PROJECT_ROOT/index.html"
ENTRY_HTML_BAK="$PROJECT_ROOT/index.html.onepress-entry.bak.$(date +%s)"
if [[ -f "$ENTRY_HTML" ]]; then
    # 避免误删用户真·前端 index.html：仅当这个 index.html 里含有我们的标识才备份
    if grep -q "onepress-wordpress-entry\|策略交易系统 · 一键安装向导" "$ENTRY_HTML" 2>/dev/null; then
        info "检测到 onepress 安装入口页 index.html，已重命名到 $ENTRY_HTML_BAK（避免覆盖后端 / 路由）"
        mv -f "$ENTRY_HTML" "$ENTRY_HTML_BAK" 2>/dev/null || true
    fi
fi

nohup "$PY" -m uvicorn main:app \
    --host "$BIND_HOST" \
    --port "$BACKEND_PORT" \
    --log-file "$LOG_FILE" \
    --log-level info \
    --workers 1 \
    > "$PROJECT_ROOT/logs/nohup.log" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
# 等几秒，确认进程存活 + /health 有返回
sleep 4
if ! kill -0 "$NEW_PID" 2>/dev/null; then
    die "uvicorn 启动后立刻退出，请查看日志：tail -n 100 $LOG_FILE"
fi
ok "uvicorn 进程：PID=$NEW_PID"

# 探活
set +e
for i in 1 2 3 4 5; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$BACKEND_PORT/health" || true)
    if [[ "$CODE" == "200" ]]; then
        ok "/health 探测返回 200。"
        break
    fi
    info "/health 尚未就绪（HTTP=$CODE），等 2s 重试($i/5) ..."
    sleep 2
done
set -e

# -------------------------- 完成总结 --------------------------
echo ""
echo "=========================================================================="
ok  "✅ onepress 一键安装脚本执行完成！下一步（就两步）："
echo ""
echo "  ① 打开你的域名 → 会自动跳到【${BLUE}/install${RESET}】向导 → 3 步完成安装"
echo "     （推荐第 1 次选 SQLite，不需要提前建库，点一下就跑完）"
echo ""
echo "  ② /install 第 ③ 步『方案 C』有一段 Nginx 反代片段，复制后："
echo "       宝塔 → 站点 → 设置 → 配置文件 → 在 server{ } 内粘贴这段 location 即可"
echo "       ⚠️ 只粘贴片段，不要替换整段 server{}（避免丢 SSL 证书路径）"
echo ""
echo "常用命令："
echo "  · 看后端日志：     ${BLUE}tail -f $LOG_FILE${RESET}"
echo "  · 看 uvicorn PID： ${BLUE}cat $PID_FILE${RESET}"
echo "  · 重启后端：       ${BLUE}bash deploy/onepress-install.sh${RESET}（脚本自带旧进程清理）"
echo "  · 手动停后端：     ${BLUE}kill \$(cat $PID_FILE) && rm -f $PID_FILE${RESET}"
echo "  · 重装向导：       ${BLUE}rm -f $PROJECT_ROOT/.installed && 浏览器再打开 /install${RESET}"
echo "=========================================================================="
