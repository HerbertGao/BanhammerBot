#!/bin/bash

# BanhammerBot 部署脚本
set -e

# 配置变量
IMAGE_NAME="ghcr.io/herbertgao/banhammerbot"
CONTAINER_NAME="banhammer-bot"
DATA_DIR="/opt/banhammer"
LOG_DIR="/opt/banhammer/logs"
VERSION="${VERSION:-latest}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查Docker是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
}

# 创建必要的目录
create_directories() {
    log_info "创建必要的目录..."
    sudo mkdir -p "$DATA_DIR"
    sudo mkdir -p "$LOG_DIR"
    sudo chown -R $USER:$USER "$DATA_DIR"
    sudo chown -R $USER:$USER "$LOG_DIR"
}

# 停止并删除旧容器
cleanup_old_container() {
    log_info "清理旧容器..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
}

# 拉取最新镜像
pull_image() {
    log_info "拉取镜像: $IMAGE_NAME:$VERSION"
    docker pull "$IMAGE_NAME:$VERSION"
    docker pull "$IMAGE_NAME:latest"
}

# 运行新容器
run_container() {
    log_info "启动新容器..."
    
    # 检查 .env 文件是否存在
    if [ ! -f ".env" ]; then
        log_error ".env 文件不存在，请先创建并配置 .env 文件"
        log_info "可以运行: cp env.example .env"
        exit 1
    fi
    
    docker run -d \
        --name "$CONTAINER_NAME" \
        --restart unless-stopped \
        --env-file .env \
        -v "$DATA_DIR:/app/data" \
        -v "$LOG_DIR:/app/logs" \
        -p 8080:8080 \
        "$IMAGE_NAME:$VERSION"
}

# 检查容器状态
check_container() {
    log_info "检查容器状态..."
    sleep 5
    if docker ps | grep -q "$CONTAINER_NAME"; then
        log_info "容器启动成功！"
        docker logs "$CONTAINER_NAME" --tail 20
    else
        log_error "容器启动失败！"
        docker logs "$CONTAINER_NAME" || true
        exit 1
    fi
}

# 清理未使用的镜像
cleanup_images() {
    log_info "清理未使用的镜像..."
    docker image prune -f
}

# 主函数
main() {
    log_info "开始部署 BanhammerBot (版本: $VERSION)..."
    
    # 检查 .env 文件
    if [ ! -f ".env" ]; then
        log_error ".env 文件不存在，请先创建并配置 .env 文件"
        log_info "可以运行: cp env.example .env"
        exit 1
    fi
    
    # 检查必要的环境变量是否在 .env 文件中
    if ! grep -q "^BOT_TOKEN=" .env; then
        log_error ".env 文件中缺少 BOT_TOKEN 配置"
        exit 1
    fi
    
    check_docker
    create_directories
    cleanup_old_container
    pull_image
    run_container
    check_container
    cleanup_images
    
    log_info "部署完成！"
    log_info "容器名称: $CONTAINER_NAME"
    log_info "镜像版本: $VERSION"
    log_info "数据目录: $DATA_DIR"
    log_info "日志目录: $LOG_DIR"
    log_info "端口: 8080"
    log_info "环境变量文件: .env"
}

# 显示帮助信息
show_help() {
    echo "使用方法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -h, --help     显示此帮助信息"
    echo "  -v, --version  显示版本信息"
    echo ""
    echo "环境变量配置:"
    echo "  1. 复制环境变量模板: cp env.example .env"
    echo "  2. 编辑 .env 文件，填入必要的配置"
    echo "  3. 运行部署脚本: $0"
    echo ""
    echo ".env 文件中的变量:"
    echo "  BOT_TOKEN      必需，Telegram Bot Token"
    echo "  LOG_LEVEL      可选，日志级别 (默认: INFO)"
    echo "  DATABASE_URL   可选，数据库URL (默认: sqlite:///data/banhammer_bot.db)"
    echo "  ADMIN_USER_IDS 可选，管理员用户ID列表"
    echo ""
    echo "脚本环境变量:"
    echo "  VERSION        可选，镜像版本 (默认: latest)"
    echo ""
    echo "示例:"
    echo "  VERSION=v1.0.0 $0"
}

# 处理命令行参数
case "$1" in
    -h|--help)
        show_help
        exit 0
        ;;
    -v|--version)
        echo "BanhammerBot 部署脚本 v1.0.0"
        exit 0
        ;;
    *)
        main
        ;;
esac 