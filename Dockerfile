# 使用Python 3.13作为基础镜像
FROM python:3.13-slim

# 设置构建参数
ARG VERSION=latest
ARG BUILD_DATE
ARG VCS_REF

# 设置标签
LABEL maintainer="BanhammerBot Team" \
      version="${VERSION}" \
      description="Telegram Banhammer Bot for spam detection and management"

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV VERSION=${VERSION}
ENV PYTHONPATH=/app/src

# 复制requirements.txt并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip

# 复制项目文件
COPY main.py .
COPY src/ ./src/
COPY scripts/ ./scripts/

# 创建必要的目录
RUN mkdir -p logs data

# 暴露端口（如果需要的话）
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sqlite3; sqlite3.connect('/app/data/banhammer_bot.db')" || exit 1

# 启动命令
CMD ["python", "main.py"]