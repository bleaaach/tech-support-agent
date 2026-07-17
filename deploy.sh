#!/bin/bash
# ================================================================
# Seeed Tech Support Agent 一键部署脚本
# 用法: ./deploy.sh {start|stop|restart|rebuild|logs|status}
# ================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

check() {
    command -v docker &>/dev/null || err "Docker 未安装"
    docker info &>/dev/null || err "Docker 未运行"
    docker compose version &>/dev/null || err "Docker Compose v2 未安装（运行: apt install docker-compose-v2）"
}

do_rebuild() {
    check
    log "停止旧服务..."
    docker compose down --remove-orphans 2>/dev/null || true

    log "构建 tech-support-agent 镜像（使用阿里云 pip 镜像，10-20分钟）..."
    docker compose build --no-cache tech-agent

    log "SAG 镜像已有，跳过构建（确保 ../SAG 存在且已构建）"
    docker compose build sag 2>/dev/null || warn "SAG 构建失败，请手动确认 ../SAG"

    log "启动所有服务..."
    docker compose up -d

    log "等待服务就绪..."
    sleep 10

    log "健康检查..."
    for svc in qdrant postgres sag tech-agent; do
        status=$(docker inspect --format='{{.State.Health.Status}}' ${svc} 2>/dev/null || echo "no-healthcheck")
        running=$(docker inspect --format='{{.State.Running}}' ${svc} 2>/dev/null || echo "false")
        echo "  $svc: running=$running health=$status"
    done

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "部署完成！"
    echo "  Tech Support Web:  http://localhost:8501"
    echo "  Tech Support API: http://localhost:8000/docs"
    echo "  SAG Web UI:       http://localhost:5173"
    echo "  SAG API:          http://localhost:4173/api"
    echo "  Qdrant Dashboard: http://localhost:6333/dashboard"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

do_start() {
    check
    log "启动服务..."
    docker compose up -d
    sleep 5
    do_status
}

do_stop() {
    check
    docker compose down
    log "已停止"
}

do_restart() {
    check
    docker compose restart "$@"
    sleep 3
    do_status
}

do_status() {
    echo ""
    docker compose ps
    echo ""
    echo "访问地址："
    echo "  Web UI  http://localhost:8501"
    echo "  API     http://localhost:8000/docs"
    echo "  SAG     http://localhost:4173"
    echo "  Qdrant  http://localhost:6333"
}

do_logs() {
    docker compose logs -f "${@:--tail=50}"
}

case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) shift; do_restart "$@" ;;
    rebuild) do_rebuild ;;
    logs)    shift; do_logs "$@" ;;
    status)  do_status ;;
    *) cat <<USAGE
用法: $0 {start|stop|restart|rebuild|logs|status}

  start   启动服务（不重新构建）
  stop    停止所有服务
  restart [svc] 重启服务（默认全部）
  rebuild 重新构建并启动（修改代码后用这个）
  logs    查看日志
  status  查看服务状态
USAGE
    ;;
esac
