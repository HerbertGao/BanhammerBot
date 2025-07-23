# Banhammer Bot 🤖

一个基于 [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 的自动化垃圾消息删除 Telegram Bot。

## 功能特性

- 🔍 **智能垃圾消息检测**
  - 禁止词汇检测
  - 链接数量限制
  - 大写字母比例检测
  - 重复字符检测
  - 消息长度检测

- 🛡️ **黑名单系统**
  - 支持链接黑名单（完整链接匹配）
  - 支持贴纸包黑名单
  - 支持GIF动画黑名单
  - 支持内联Bot黑名单（使用Bot ID识别）
  - 支持文字消息黑名单（举报3次自动加入）
  - 管理员举报机制（/spam 命令）

- 🚫 **自动封禁机制**
  - 检测到黑名单内容自动删除消息
  - 自动封禁发送黑名单内容的用户
  - 支持管理员解除封禁（/unban 命令）

- 📝 **操作记录**
  - 每个群组可设置独立的记录频道
  - 不同群组可以使用相同的记录频道
  - 记录包含来源群组信息
  - 详细的日志记录
  - 支持查看群组黑名单（/blacklist 命令）

- 👥 **管理员呼叫**
  - 支持 @admin 关键词检测（不区分大小写）
  - 自动列出群组管理员（排除机器人）
  - 支持 /admin 命令查看管理员列表

- 🌐 **通用黑名单系统**
  - 群组间黑名单数据共享
  - 支持贡献和使用通用黑名单
  - 可独立控制贡献和使用开关

- ⚙️ **灵活配置**
  - 可自定义检测规则
  - 可调整删除策略
  - 支持多种群组类型

## 安装和配置

### 1. 克隆项目

```bash
git clone https://github.com/HerbertGao/BanhammerBot
cd BanhammerBot
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

创建 `.env` 文件并配置以下内容：

```env
# Telegram Bot Token (从 @BotFather 获取)
BOT_TOKEN=your_bot_token_here

# 日志级别
LOG_LEVEL=INFO

# 数据库配置 (可选)
# 注意：在 Docker 环境中，数据库文件位于 /app/data 目录
DATABASE_URL=sqlite:///data/banhammer_bot.db

# 管理员用户ID列表 (用于私聊转发功能，多个ID用逗号分隔)
# 未配置时将无管理员可用
ADMIN_USER_IDS=123456789,987654321
```

### 4. 获取 Bot Token

1. 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 命令
3. 按照提示设置 Bot 名称和用户名
4. 复制获得的 Token 到 `.env` 文件中

### 5. 设置记录频道（可选）

1. 创建一个 Telegram 频道
2. 将 Bot 添加为频道管理员
3. 获取频道 ID（可以通过 @userinfobot 获取）
4. 在群组中使用 `/log_channel <频道ID>` 命令设置记录频道
5. 不同群组可以使用相同的记录频道
6. 使用 `/log_channel clear` 清除记录频道设置

### 6. 配置管理员权限（可选）

1. 获取您的 Telegram 用户 ID（可以通过 @userinfobot 获取）
2. 将您的用户 ID 添加到 `.env` 文件的 `ADMIN_USER_IDS` 中
3. 多个管理员 ID 用逗号分隔，例如：`ADMIN_USER_IDS=123456789,987654321`
4. 配置的管理员可以使用私聊转发功能
5. **未配置时将无管理员可用，所有用户都无法使用私聊转发功能**

### 7. 运行 Bot

#### 方式一：直接运行
```bash
python bot.py
```

#### 方式二：使用 Docker（推荐）
```bash
# 使用 Docker Compose（推荐）
# 确保已创建 .env 文件
cp env.example .env
# 编辑 .env 文件，填入必要的配置
docker-compose up -d

# 或使用 Docker 命令
docker pull ghcr.io/herbertgao/banhammerbot:latest
docker run -d \
  --name banhammer-bot \
  --restart unless-stopped \
  --env-file .env \
  -v /opt/banhammer/data:/app/data \
  -v /opt/banhammer/logs:/app/logs \
  ghcr.io/herbertgao/banhammerbot:latest
```

> 💡 **Docker 部署**: 详细的 Docker 部署说明请参考 [DOCKER.md](DOCKER.md)

## 配置说明

### 删除配置

```python
DELETE_CONFIG = {
    'auto_delete_spam': True,    # 自动删除垃圾消息
    'warn_before_delete': True,  # 删除前警告
    'warn_timeout': 30,          # 警告超时时间(秒)
    'delete_timeout': 60,        # 删除超时时间(秒)
}
```

## 使用命令

在群组中使用以下命令：

- `/help` - 显示帮助信息
- `/stats` - 显示统计信息
- `/config` - 显示当前配置
- `/spam` - 举报消息为垃圾消息（回复要举报的消息）
- `/blacklist` - 查看群组黑名单
- `/unban <user_id>` - 解除用户封禁
- `/admin` - 查看群组管理员列表
- `/global Y` - 加入通用黑名单系统
- `/global N` - 退出通用黑名单系统
- `/global status` - 查看通用黑名单状态
- `/global stats` - 查看通用黑名单统计
- `/log_channel` - 查看记录频道设置
- `/log_channel <频道ID>` - 设置记录频道
- `/log_channel clear` - 清除记录频道设置

## 权限说明

- **管理员和群主**：消息不会被检测，可以使用所有命令
- **普通用户**：消息会被自动检测和处理
- **Bot 权限**：需要删除消息和封禁用户权限
- **记录频道**：Bot 需要是频道管理员才能发送日志

## 项目结构

```
BanhammerBot/
├── bot.py                 # 主程序入口
├── config.py             # 配置文件
├── requirements.txt      # 依赖列表
├── .gitignore           # Git 忽略文件
├── README.md            # 项目说明
├── env.example          # 环境变量示例
├── utils/               # 工具模块
│   ├── __init__.py
│   └── logger.py        # 日志工具
├── database/            # 数据库模块
│   ├── __init__.py
│   └── models.py        # 数据库模型
└── handlers/            # 处理器模块
    ├── __init__.py
    ├── blacklist_handler.py # 黑名单处理器
    ├── admin_handler.py # 管理员处理器
    └── message_handler.py # 消息处理器
```

## 开发说明

### 自定义黑名单类型

在 `handlers/blacklist_handler.py` 中的 `_extract_blacklist_content` 方法中添加新的黑名单类型检测。

### 自定义处理逻辑

在 `handlers/message_handler.py` 中修改消息处理逻辑。

### 扩展命令

在 `handlers/message_handler.py` 中添加新的命令处理方法。

### 数据库操作

在 `database/models.py` 中添加新的数据库操作方法。

## 注意事项

1. **Bot 权限**：确保 Bot 在群组中有删除消息和封禁用户的权限
2. **管理员保护**：管理员和群主的消息不会被检测
3. **记录频道**：确保 Bot 是记录频道的管理员
4. **配置备份**：修改配置前请备份原始文件
5. **日志监控**：定期检查日志文件了解 Bot 运行状态
6. **数据库备份**：定期备份数据库文件

## 许可证

本项目采用 MIT 许可证。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 支持

如果遇到问题，请：

1. 查看日志文件 `logs/banhammer_bot.log`
2. 检查配置是否正确
3. 确认 Bot 权限设置
4. 提交 Issue 描述问题 