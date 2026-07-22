#!/bin/bash
# ================================================================
# Seeed Tech Support Agent — 环境切换 + 启动辅助脚本
# 用法: ./switch-env.sh {test|prod|status|stop|logs}
#
# 不依赖 deploy.sh，独立可调用。两个环境的容器名/端口/卷
# 都已隔离，可同时运行在同一台机器上。
# ================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# 通用 compose 数组。test 只用主文件；prod 加 override 并指向 .env.production
COMPOSE_BASE=(docker compose)
COMPOSE_PROD=(docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production)

start_test() {
    log "启动测试环境 (端口 8000/8501/4173/6333)..."
    "${COMPOSE_BASE[@]}" --env-file .env.testing up -d
    sleep 5
    show_status_test
}

start_prod() {
    if [[ ! -f .env.production ]]; then
        err ".env.production 不存在，请先: cp .env.production.template .env.production 并填入真 key"
    fi
    log "启动生产环境 (端口 18000/18501/14173/16333)..."
    "${COMPOSE_PROD[@]}" up -d
    sleep 5
    show_status_prod
}

stop_all() {
    log "停止测试环境..."
    "${COMPOSE_BASE[@]}" down 2>/dev/null || warn "测试环境未运行"
    log "停止生产环境..."
    "${COMPOSE_PROD[@]}" down 2>/dev/null || warn "生产环境未运行"
    log "全部停止"
}

show_status_test() {
    echo ""
    log "测试环境状态:"
    "${COMPOSE_BASE[@]}" ps
    echo ""
    echo "访问地址 (测试):"
    echo "  Web UI  http://localhost:8501"
    echo "  API     http://localhost:8000/docs"
    echo "  SAG     http://localhost:4173"
    echo "  Qdrant  http://localhost:6333/dashboard"
}

show_status_prod() {
    echo ""
    log "生产环境状态:"
    "${COMPOSE_PROD[@]}" ps
    echo ""
    echo "访问地址 (生产):"
    echo "  Web UI  http://localhost:18501"
    echo "  API     http://localhost:18000/docs"
    echo "  SAG     http://localhost:14173"
    echo "  Qdrant  http://localhost:16333/dashboard"
}

logs() {
    case "${1:-test}" in
        test) "${COMPOSE_BASE[@]}" logs -f "${@:2}" ;;
        prod) "${COMPOSE_PROD[@]}" logs -f "${@:2}" ;;
        *)    err "用法: $0 logs {test|prod} [service]" ;;
    esac
}

case "${1:-}" in
    test)   start_test ;;
    prod)   start_prod ;;
    status) show_status_test; echo; show_status_prod ;;
    stop)   stop_all ;;
    logs)   shift; logs "$@" ;;
    *) cat <<USAGE
用法: $0 {test|prod|status|stop|logs [test|prod] [service]}

  test     启动测试环境
  prod     启动生产环境（需 .env.production）
  status   显示两个环境状态
  stop     停止两个环境
  logs     查看日志 (默认 test)
USAGE
        ;;
esac