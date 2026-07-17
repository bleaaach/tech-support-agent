#!/bin/bash
# ================================================================
# Tech Support Agent - 本地一键部署 (无需 Docker)
# 用法: ./deploy-local.sh {start|stop|restart|status|logs|setup}
# ================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.local/bin:$PATH"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[i]${NC} $1"; }

VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
UVICORN="$VENV_DIR/bin/uvicorn"
STREAMLIT="$VENV_DIR/bin/streamlit"
LOG_DIR="$SCRIPT_DIR/logs"
RUN_DIR="$SCRIPT_DIR/.run"

mkdir -p "$LOG_DIR" "$RUN_DIR"

check_uv() {
    command -v uv &>/dev/null || err "uv 未安装。运行: curl -LsSf https://astral.sh/uv/install.sh | sh"
    log "uv 已就绪 ($(uv --version))"
}

ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        log "创建虚拟环境 (Python 3.11)..."
        uv venv --python 3.11 "$VENV_DIR"
    fi
    log "venv: $VENV_DIR"
}

install_deps() {
    local REQ_LIGHT=/tmp/req-light.txt
    log "拆分依赖：轻量包用阿里云，torch 走 CPU 专用源..."

    grep -v "^sentence-transformers\|^torch\|^--extra-index" requirements.txt > "$REQ_LIGHT"

    log "[1/2] 装轻量包 (fastapi/streamlit/langchain...)"
    uv pip install --python "$PYTHON" -r "$REQ_LIGHT" \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com 2>&1 | tail -3

    log "[2/2] 装 CPU-only torch (避免拉 CUDA 工具链)"
    uv pip install --python "$PYTHON" \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        --index-strategy first-index \
        torch 2>&1 | tail -3

    log "[3/3] 装 sentence-transformers"
    uv pip install --python "$PYTHON" sentence-transformers==3.2.1 \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com 2>&1 | tail -3

    log "依赖装完"
}

do_setup() {
    check_uv
    ensure_venv
    install_deps
    log "✅ 初始化完成！运行 ./deploy-local.sh start 启动服务"
}

is_running() {
    local pidfile="$RUN_DIR/$1.pid"
    [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

start_one() {
    local name=$1 cmd=$2 logfile=$LOG_DIR/$1.log
    if is_running "$name"; then
        warn "$name 已在运行 (PID $(cat "$RUN_DIR/$1.pid"))"
        return
    fi
    info "启动 $name: $cmd"
    nohup $cmd > "$logfile" 2>&1 &
    echo $! > "$RUN_DIR/$1.pid"
    sleep 1
    if is_running "$name"; then
        log "$name 已启动 (PID $(cat "$RUN_DIR/$1.pid"))"
    else
        err "$name 启动失败，查看日志: tail -n 50 $logfile"
    fi
}

stop_one() {
    local name=$1
    if [ -f "$RUN_DIR/$name.pid" ]; then
        local pid=$(cat "$RUN_DIR/$name.pid")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
            log "$name 已停止"
        fi
        rm -f "$RUN_DIR/$name.pid"
    fi
}

do_start() {
    [ -d "$VENV_DIR" ] || err "请先运行 ./deploy-local.sh setup"
    [ -f .env ] || err ".env 文件不存在！请从 .env.example 复制并填入 OPENAI_API_KEY"

    set -a; source .env; set +a
    info "OPENAI_API_KEY: ${OPENAI_API_KEY:0:20}..."

    start_one fastapi "$UVICORN agent.main:app --host 0.0.0.0 --port 8000"
    start_one streamlit "$STREAMLIT run ui/app.py --server.port 8501 --server.address 0.0.0.0"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "服务已启动！"
    echo "  Web UI:   http://localhost:8501"
    echo "  API:      http://localhost:8000"
    echo "  API Docs: http://localhost:8000/docs"
    echo "  日志目录: $LOG_DIR"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

do_stop() {
    stop_one streamlit
    stop_one fastapi
    log "所有服务已停止"
}

do_status() {
    echo ""
    for svc in fastapi streamlit; do
        if is_running "$svc"; then
            echo -e "  $svc: ${GREEN}running${NC} (PID $(cat "$RUN_DIR/$svc.pid"))"
        else
            echo -e "  $svc: ${RED}stopped${NC}"
        fi
    done
    echo ""
}

do_logs() {
    local svc="${1:-}"
    if [ -z "$svc" ]; then
        tail -n 30 -f "$LOG_DIR"/*.log
    else
        tail -n 50 -f "$LOG_DIR/$svc.log"
    fi
}

case "${1:-}" in
    setup)   do_setup ;;
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; sleep 1; do_start ;;
    status)  do_status ;;
    logs)    shift; do_logs "$@" ;;
    *) cat <<USAGE
用法: $0 {setup|start|stop|restart|status|logs}

  setup   首次运行：创建 venv + 装依赖
  start   启动 FastAPI + Streamlit
  stop    停止所有服务
  restart 重启服务
  status  查看运行状态
  logs    查看日志 (可指定服务名: logs fastapi)
USAGE
    ;;
esac