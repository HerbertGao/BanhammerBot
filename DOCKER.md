# BanhammerBot Docker 化指南

## 概述

本项目已完全 Docker 化，支持通过 Docker 和 Docker Compose 进行部署和管理。同时提供了完整的 GitHub Actions CI/CD 工作流。

## 文件结构

```
BanhammerBot/
├── Dockerfile.github-actions  # GitHub Actions Docker 镜像构建文件
├── .dockerignore             # Docker 构建忽略文件
├── docker-compose.yml        # Docker Compose 配置
├── scripts/
│   └── deploy.sh             # 部署脚本
├── .github/workflows/
│   ├── docker-build.yml      # Docker 构建和推送工作流
│   ├── deploy.yml            # 自动部署工作流
│   └── test.yml              # 测试和代码质量检查工作流
└── DOCKER.md                 # 本文档
```

## 快速开始

### 1. 使用 Docker Compose（推荐）

```bash
# 克隆项目
git clone <your-repo-url>
cd BanhammerBot

# 创建环境变量文件
cp env.example .env
# 编辑 .env 文件，填入必要的配置
# 注意：docker-compose.yml 会自动读取 .env 文件中的环境变量

# 启动服务（使用预构建的镜像）
docker-compose up -d

# 查看日志
docker-compose logs -f banhammer-bot

# 停止服务
docker-compose down
```

### 2. 使用 Docker 命令

```bash
# 拉取预构建镜像
docker pull ghcr.io/herbertgao/banhammerbot:latest

# 运行容器（使用 .env 文件）
docker run -d \
  --name banhammer-bot \
  --restart unless-stopped \
  --env-file .env \
  -v /opt/banhammer/data:/app/data \
  -v /opt/banhammer/logs:/app/logs \
  -p 8080:8080 \
  ghcr.io/herbertgao/banhammerbot:latest
```

### 3. 使用部署脚本

```bash
# 确保 .env 文件已配置
cp env.example .env
# 编辑 .env 文件，填入必要的配置

# 设置版本（可选）
export VERSION="v1.0.0"

# 运行部署脚本
./scripts/deploy.sh
```

### 4. 本地构建（开发环境）

如果需要本地构建镜像，可以使用：

```bash
# 构建镜像
docker build -f Dockerfile.github-actions -t banhammer-bot .

# 运行本地构建的镜像
docker run -d \
  --name banhammer-bot \
  --restart unless-stopped \
  --env-file .env \
  -v /opt/banhammer/data:/app/data \
  -v /opt/banhammer/logs:/app/logs \
  -p 8080:8080 \
  banhammer-bot
```

## 环境变量

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `BOT_TOKEN` | ✅ | - | Telegram Bot Token |
| `LOG_LEVEL` | ❌ | INFO | 日志级别 |
| `DATABASE_URL` | ❌ | sqlite:///data/banhammer_bot.db | 数据库连接URL（Docker环境） |
| `ADMIN_USER_IDS` | ❌ | - | 管理员用户ID列表（逗号分隔） |
| `VERSION` | ❌ | latest | 镜像版本 |

**注意**：所有环境变量都通过 `.env` 文件配置，Docker 容器会自动读取该文件。

## 数据持久化

### 目录结构
```
/opt/banhammer/
├── data/           # 数据库文件
└── logs/           # 日志文件
```

### 挂载配置
- **数据库**: `/opt/banhammer/data:/app/data`
- **日志**: `/opt/banhammer/logs:/app/logs`

## GitHub Actions CI/CD

### 工作流说明

#### 1. 测试和代码质量检查 (`test.yml`)
- **触发**: 推送到 main/master/develop 分支或 PR
- **功能**:
  - Python 代码测试
  - 代码质量检查 (flake8, black, isort)
  - Docker 镜像构建测试
  - 代码覆盖率报告

#### 2. Docker 构建和推送 (`docker-build.yml`)
- **触发**: 推送到 main/master 分支或手动触发
- **功能**:
  - 构建多平台 Docker 镜像 (linux/amd64, linux/arm64)
  - 推送到 GitHub Container Registry
  - 支持手动指定版本
  - 为每个架构生成单独的镜像标签
  - 安全扫描 (Trivy)

#### 3. 自动部署 (`deploy.yml`)
- **触发**: Docker 构建成功后
- **功能**:
  - 自动部署到生产服务器
  - 零停机部署
  - 健康检查

### 镜像标签格式

构建完成后，会生成以下镜像标签：

```
ghcr.io/your-username/banhammerbot:latest          # 最新版本
ghcr.io/your-username/banhammerbot:commit-sha      # 提交哈希
ghcr.io/your-username/banhammerbot-aarch64:latest  # ARM64 架构
ghcr.io/your-username/banhammerbot-amd64:latest    # AMD64 架构
```

### 手动触发构建

在 GitHub 仓库页面，可以手动触发构建并指定版本：

1. 进入 "Actions" 标签页
2. 选择 "Docker Image Build" 工作流
3. 点击 "Run workflow"
4. 输入版本号（如 v1.0.0）
5. 点击 "Run workflow"

### 配置 GitHub Secrets

在 GitHub 仓库设置中添加以下 Secrets：

#### 构建和推送
- `GITHUB_TOKEN` (自动提供)

#### 部署
- `HOST`: 服务器 IP 地址
- `USERNAME`: SSH 用户名
- `SSH_KEY`: SSH 私钥
- `PORT`: SSH 端口 (默认 22)
- `BOT_TOKEN`: Telegram Bot Token
- `LOG_LEVEL`: 日志级别
- `DATABASE_URL`: 数据库连接URL
- `ADMIN_USER_IDS`: 管理员用户ID列表

## 生产环境部署

### 1. 服务器准备

```bash
# 安装 Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 安装 Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 创建必要目录
sudo mkdir -p /opt/banhammer/{data,logs}
sudo chown -R $USER:$USER /opt/banhammer
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp env.example /opt/banhammer/.env

# 编辑环境变量文件
nano /opt/banhammer/.env

# 或直接创建环境变量文件
cat > /opt/banhammer/.env << EOF
BOT_TOKEN=your_bot_token_here
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///data/banhammer_bot.db
ADMIN_USER_IDS=123456789,987654321
VERSION=v1.0.0
EOF
```

### 3. 部署

```bash
# 使用 Docker Compose
cd /opt/banhammer
docker-compose up -d

# 或使用部署脚本
./scripts/deploy.sh
```

## 监控和维护

### 查看日志
```bash
# Docker Compose
docker-compose logs -f banhammer-bot

# Docker
docker logs -f banhammer-bot

# 直接查看日志文件
tail -f /opt/banhammer/logs/banhammer_bot.log
```

### 更新部署
```bash
# 拉取最新镜像
docker-compose pull

# 重启服务
docker-compose up -d

# 或使用部署脚本
VERSION=v1.1.0 ./scripts/deploy.sh
```

### 备份数据
```bash
# 备份数据库
cp /opt/banhammer/data/banhammer_bot.db /backup/banhammer_bot_$(date +%Y%m%d_%H%M%S).db

# 备份日志
tar -czf /backup/logs_$(date +%Y%m%d_%H%M%S).tar.gz /opt/banhammer/logs/
```

### 健康检查
```bash
# 检查容器状态
docker ps | grep banhammer-bot

# 检查健康状态
docker inspect banhammer-bot | grep Health -A 10

# 检查端口
netstat -tlnp | grep 8080
```

## 故障排除

### 常见问题

#### 1. 容器启动失败
```bash
# 查看详细日志
docker logs banhammer-bot

# 检查环境变量
docker exec banhammer-bot env | grep -E "(BOT_TOKEN|LOG_LEVEL|ADMIN_USER_IDS)"
```

#### 2. 权限问题
```bash
# 修复目录权限
sudo chown -R $USER:$USER /opt/banhammer
sudo chmod -R 755 /opt/banhammer
```

#### 3. 网络问题
```bash
# 检查端口占用
sudo netstat -tlnp | grep 8080

# 检查防火墙
sudo ufw status
```

#### 4. 磁盘空间不足
```bash
# 清理 Docker 资源
docker system prune -a

# 清理日志
sudo find /opt/banhammer/logs -name "*.log" -mtime +7 -delete
```

## 性能优化

### 1. 资源限制
```yaml
# docker-compose.yml
services:
  banhammer-bot:
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
        reservations:
          memory: 256M
          cpus: '0.25'
```

### 2. 日志轮转
```bash
# 配置 logrotate
sudo tee /etc/logrotate.d/banhammer << EOF
/opt/banhammer/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 644 $USER $USER
}
EOF
```

### 3. 数据库优化
```bash
# 定期清理数据库
docker exec banhammer-bot python -c "
from database.models import DatabaseManager
db = DatabaseManager()
db.cleanup_invalid_blacklist_items()
"
```

## 安全考虑

### 1. 网络安全
- 使用防火墙限制端口访问
- 配置 SSL/TLS 证书
- 定期更新系统和 Docker

### 2. 数据安全
- 定期备份数据
- 加密敏感信息
- 限制文件权限

### 3. 容器安全
- 使用非 root 用户运行容器
- 定期扫描镜像漏洞
- 限制容器权限

## 扩展功能

### 1. 添加 Redis 缓存（可选）

如果需要添加 Redis 缓存功能，可以在 docker-compose.yml 中添加：

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    container_name: banhammer-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - banhammer-network

volumes:
  redis-data:
```

### 2. 添加 Nginx 反向代理
```yaml
# docker-compose.yml
services:
  nginx:
    image: nginx:alpine
    container_name: banhammer-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - banhammer-bot
```

### 3. 添加监控
```yaml
# docker-compose.yml
services:
  prometheus:
    image: prom/prometheus
    container_name: banhammer-prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus

  grafana:
    image: grafana/grafana
    container_name: banhammer-grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
```

## 总结

通过 Docker 化，BanhammerBot 现在具备了：

- ✅ 一致的运行环境
- ✅ 简单的部署流程
- ✅ 自动化的 CI/CD
- ✅ 数据持久化
- ✅ 健康监控
- ✅ 安全扫描
- ✅ 多平台支持
- ✅ 易于扩展
- ✅ 版本管理
- ✅ 手动触发构建

使用 Docker 可以大大简化部署和维护工作，提高系统的可靠性和可维护性。 