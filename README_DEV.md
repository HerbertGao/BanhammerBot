# BanhammerBot 开发指南

## 项目结构

```
BanhammerBot/
├── src/                    # 源代码目录
│   ├── bot.py             # Bot 主类
│   ├── config.py          # 配置管理
│   ├── database/          # 数据库模块
│   ├── handlers/          # 消息处理器
│   └── utils/             # 工具函数
├── tests/                  # 测试目录
├── scripts/               # 脚本目录
├── main.py                # 程序入口
├── requirements.txt       # 生产依赖
├── requirements-dev.txt   # 开发依赖
└── pyproject.toml         # 项目配置
```

## 开发环境设置

### 1. 克隆仓库

```bash
git clone https://github.com/HerbertGao/BanhammerBot
cd BanhammerBot
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate  # Windows
```

### 3. 安装依赖

```bash
# 安装生产依赖
pip install -r requirements.txt

# 安装开发依赖
pip install -r requirements-dev.txt
```

### 4. 配置环境变量

复制 `env.example` 到 `.env` 并填写配置：

```bash
cp env.example .env
```

编辑 `.env` 文件：
```
BOT_TOKEN=your_bot_token_here
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///data/banhammer_bot.db
ADMIN_USER_IDS=123456789,987654321
```

## 代码质量工具

### Black - 代码格式化

```bash
# 格式化所有代码
black src/ tests/

# 检查但不修改
black --check src/ tests/
```

### isort - 导入排序

```bash
# 排序导入
isort src/ tests/

# 检查但不修改
isort --check-only src/ tests/
```

### Flake8 - 代码检查

```bash
# 运行代码检查
flake8 src/ tests/
```

### Mypy - 类型检查

```bash
# 运行类型检查
mypy src/
```

## 测试

### 运行所有测试

```bash
pytest
```

### 运行特定测试文件

```bash
pytest tests/test_database.py
```

### 运行带覆盖率的测试

```bash
pytest --cov=src --cov-report=html
```

查看覆盖率报告：
```bash
open htmlcov/index.html  # Mac
# 或
start htmlcov/index.html  # Windows
```

## Pre-commit Hooks

### 安装 pre-commit hooks

```bash
pre-commit install
```

### 手动运行所有 hooks

```bash
pre-commit run --all-files
```

## 运行 Bot

### 开发模式

```bash
python main.py
```

### Docker 模式

```bash
# 构建镜像
docker build -t banhammer-bot .

# 运行容器
docker-compose up -d
```

## 提交代码

1. 确保代码格式化：
```bash
black src/ tests/
isort src/ tests/
```

2. 运行测试：
```bash
pytest
```

3. 运行代码检查：
```bash
flake8 src/ tests/
mypy src/
```

4. 提交：
```bash
git add .
git commit -m "feat: 添加新功能"
```

Pre-commit hooks 会自动运行检查。

## 常见问题

### 导入错误

如果遇到导入错误，确保：
1. 虚拟环境已激活
2. PYTHONPATH 包含 src 目录：
```bash
export PYTHONPATH="${PYTHONPATH}:${PWD}/src"
```

### 数据库问题

如果数据库有问题，可以删除并重新创建：
```bash
rm banhammer_bot.db
python main.py  # 会自动创建新数据库
```

## 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 代码风格

- 使用 Black 进行代码格式化（行长度：100）
- 使用 isort 排序导入
- 遵循 PEP 8 规范
- 添加类型提示
- 编写单元测试
