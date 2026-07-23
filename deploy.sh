#!/bin/bash
# ================================================================
# Seeed Tech Support Agent — 一键部署脚本（分支策略版）
#
# 用法:
#   ./deploy.sh test      # develop 分支 → 测试环境
#   ./deploy.sh prod      # main 分支   → 生产环境
#   ./deploy.sh rebuild   # 重build 镜像（当前分支）
#   ./deploy.sh stop      # 停止当前环境
#   ./deploy.sh logs      # 查看日志
#   ./deploy.sh status    # 查看状态
#   ./deploy.sh switch    # 切换分支（不重启）
#
# 自动在对应分支上部署，测试和生产可同时运行（端口完全隔离）
# ================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 颜色 ──────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()  { echo -e "${BLUE}[STEP]${NC}  $1"; }

# ── 环境配置 ───────────────────────────────────────────────────
# 用关联数组（Bash 4+）保存各环境的元数据
declare -A ENV_CONFIG
ENV_CONFIG[test,branch]=develop
ENV_CONFIG[test,compose_files]="-f docker-compose.yml -f docker-compose.testing.yml"
ENV_CONFIG[test,env_file]=.env.testing
ENV_CONFIG[test,project]=techagent-testing
ENV_CONFIG[test,ports]="FastAPI:28000  Streamlit:28501  SAG:14174  Qdrant:26333  PG:25432"

ENV_CONFIG[prod,branch]=main
ENV_CONFIG[prod,compose_files]="-f docker-compose.yml -f docker-compose.prod.yml"
ENV_CONFIG[prod,env_file]=.env.production
ENV_CONFIG[prod,project]=tech-support-agent
ENV_CONFIG[prod,ports]="FastAPI:18000  Streamlit:18501  SAG:14173  Qdrant:16333  PG:15432"

# ── 前置检查 ───────────────────────────────────────────────────
check() {
    command -v docker &>/dev/null || err "Docker 未安装"
    docker info &>/dev/null || err "Docker 未运行"
    docker-compose version &>/dev/null || err "Docker Compose v2 未安装"
}

# ── 获取当前所在分支 ──────────────────────────────────────────
current_branch() {
    git rev-parse --abbrev-ref HEAD 2>/dev/null
}

# ── 获取当前激活的环境（通过运行的容器名判断）─────────────────
current_env() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'tech-agent-prod\|qdrant-prod'; then
        echo "prod"
    elif docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'tech-agent$'; then
        echo "test"
    else
        echo "none"
    fi
}

# ── 确认生产 key 已配置 ────────────────────────────────────────
check_prod_key() {
    if [[ ! -f .env.production ]]; then
        err ".env.production 不存在，请先:\n  cp .env.production.template .env.production\n  # 然后填入真实 API Key"
    fi
    # 简单检查是否有 placeholder
    if grep -q "your_prod_key_here\|CHANGE_ME\|placeholder" .env.production 2>/dev/null; then
        warn ".env.production 中仍有 placeholder key，请确认已填入真实值！"
    fi
}

# ── 自动 checkout 到目标分支 ──────────────────────────────────
checkout_branch() {
    local target_branch="$1"
    local current
    current=$(current_branch)

    if [[ "$current" == "$target_branch" ]]; then
        info "已是 $target_branch 分支，跳过切换"
        return 0
    fi

    step "切换分支: $current → $target_branch"
    git fetch origin "$target_branch" 2>/dev/null || true

    if git rev-parse --verify "$target_branch" &>/dev/null; then
        git checkout "$target_branch"
    else
        # develop 分支不存在，从当前分支创建
        warn "分支 $target_branch 不存在，以当前分支创建"
        git checkout -b "$target_branch"
    fi
    git pull origin "$target_branch" 2>/dev/null || true
}

# ── 启动环境 ───────────────────────────────────────────────────
do_start() {
    local env="$1"
    local branch="${ENV_CONFIG[${env},branch]}"
    local compose_files="${ENV_CONFIG[${env},compose_files]}"
    local env_file="${ENV_CONFIG[${env},env_file]}"
    local project="${ENV_CONFIG[${env},project]}"
    local ports="${ENV_CONFIG[${env},ports]}"

    check
    if [[ "$env" == "prod" ]]; then
        check_prod_key
    fi

    checkout_branch "$branch"

    step "停止旧容器（$env）..."
    # 先尝试以该环境的方式停止
    docker-compose -p "$project" $compose_files --env-file "$env_file" down 2>/dev/null || true

    step "构建 + 启动 $env 环境 ($branch)..."
    # --pull=always 确保拉取最新的 SAG 基础镜像
    docker-compose -p "$project" $compose_files --env-file "$env_file" build --pull tech-agent
    docker-compose -p "$project" $compose_files --env-file "$env_file" up -d

    step "等待服务就绪（30s）..."
    sleep 30

    info "健康检查:"
    docker-compose -p "$project" $compose_files ps 2>/dev/null

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "  ${GREEN}✓${NC} $env 环境部署完成！  分支: $branch"
    echo ""
    echo "  访问地址:"
    echo "  $ports" | sed 's/  /\n  /g'
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ── 重建镜像 ───────────────────────────────────────────────────
do_rebuild() {
    local current_env
    current_env=$(current_env)
    [[ "$current_env" == "none" ]] && current_env="test"

    local branch="${ENV_CONFIG[${current_env},branch]}"
    local compose_files="${ENV_CONFIG[${current_env},compose_files]}"
    local env_file="${ENV_CONFIG[${current_env},env_file]}"
    local project="${ENV_CONFIG[${current_env},project]}"

    check
    step "重新构建 tech-agent 镜像（无缓存，10-20分钟）..."
    docker-compose -p "$project" $compose_files --env-file "$env_file" build --pull --no-cache tech-agent

    step "重启服务..."
    docker-compose -p "$project" $compose_files --env-file "$env_file" up -d
    sleep 10

    info "部署完成"
    docker-compose -p "$project" $compose_files ps
}

# ── 停止 ───────────────────────────────────────────────────────
do_stop() {
    local env="${1:-$(current_env)}"
    [[ "$env" == "none" ]] && echo "没有检测到运行中的环境" && return 0

    local project="${ENV_CONFIG[${env},project]}"
    local compose_files="${ENV_CONFIG[${env},compose_files]}"
    local env_file="${ENV_CONFIG[${env},env_file]}"

    info "停止 $env 环境..."
    docker-compose -p "$project" $compose_files --env-file "$env_file" down 2>/dev/null || \
    docker-compose -p "$project" down 2>/dev/null || true
}

# ── 日志 ───────────────────────────────────────────────────────
do_logs() {
    local env="${1:-$(current_env)}"
    [[ "$env" == "none" ]] && env="test"

    local project="${ENV_CONFIG[${env},project]}"
    local compose_files="${ENV_CONFIG[${env},compose_files]}"
    local env_file="${ENV_CONFIG[${env},env_file]}"

    docker-compose -p "$project" $compose_files --env-file "$env_file" logs -f "${2:-}"
}

# ── 状态 ───────────────────────────────────────────────────────
do_status() {
    echo ""
    echo "当前分支: $(current_branch)"
    echo ""
    echo "━━━ 测试环境 (develop) ━━━"
    docker-compose -p techagent-testing -f docker-compose.yml -f docker-compose.testing.yml --env-file .env.testing ps 2>/dev/null || echo "  未运行"
    echo ""
    echo "━━━ 生产环境 (main) ━━━"
    docker-compose -p tech-support-agent -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production ps 2>/dev/null || echo "  未运行"
    echo ""
    echo "测试端口: FastAPI:28000  Streamlit:28501  SAG:14174  Qdrant:26333"
    echo "生产端口: FastAPI:18000  Streamlit:18501  SAG:14173  Qdrant:16333"
}

# ── 分支切换（不重启）─────────────────────────────────────────
do_switch() {
    local target_branch="$1"
    checkout_branch "$target_branch"
    info "已切换到 $target_branch，运行 './deploy.sh start' 部署"
}

# ── 主入口 ─────────────────────────────────────────────────────
case "${1:-}" in
    test)  do_start test ;;
    prod)  do_start prod ;;
    rebuild) do_rebuild ;;
    stop)
        if [[ "${2:-}" == "all" ]]; then
            do_stop test; do_stop prod
        else
            do_stop "${2:-}"
        fi
        ;;
    logs)  shift; do_logs "$@" ;;
    status) do_status ;;
    switch) do_switch "${2:-}" ;;
    -h|--help|help) cat <<EOF
用法: $0 <command>

环境命令:
  test           部署测试环境（develop 分支，端口 28xxx）
  prod           部署生产环境（main 分支，端口 18xxx）

运维命令:
  rebuild        重新构建当前环境的镜像（不切换分支）
  stop [env]     停止环境（test/prod，不指定则检测当前）
  stop all       停止所有环境
  logs [env]     查看日志（默认当前环境）
  status         查看两套环境状态
  switch <branch> 切换 git 分支（不重启容器）

示例:
  ./deploy.sh test      # 部署测试环境
  ./deploy.sh prod       # 部署生产环境
  ./deploy.sh logs prod  # 看生产日志
  ./deploy.sh stop prod  # 停生产
  ./deploy.sh switch develop  # 切到 develop 分支（不重启）
EOF
        ;;
    *)     "$0" help ;;
esac
