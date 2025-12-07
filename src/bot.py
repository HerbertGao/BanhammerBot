from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import Config
from database.models import DatabaseManager
from handlers.admin_handler import AdminHandler
from handlers.blacklist_handler import BlacklistHandler
from utils.logger import logger


class BanhammerBot:
    """Banhammer Bot 主类"""

    def __init__(self):
        """初始化Bot

        Raises:
            ValueError: 如果 BOT_TOKEN 未配置
            Exception: 如果数据库初始化失败
        """
        self.token = Config.BOT_TOKEN
        self.db = None
        self.blacklist_handler = None
        self.application = None

        if not self.token:
            raise ValueError("BOT_TOKEN 未设置，请在 .env 文件中配置")

        # 初始化数据库，捕获并记录错误
        try:
            self.db = DatabaseManager()
            logger.info("数据库初始化成功")
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}", exc_info=True)
            raise RuntimeError(f"无法初始化数据库: {e}") from e

        # 初始化黑名单处理器 - 共享数据库连接
        self.blacklist_handler = BlacklistHandler(db=self.db)

    def start(self):
        """启动 Bot"""
        logger.info("正在启动 Banhammer Bot...")

        # 创建应用
        self.application = Application.builder().token(self.token).build()

        # 注册处理器
        self._register_handlers(self.application)

        # 添加定期清理速率限制器的任务（每小时清理一次）
        if self.application.job_queue:
            self.application.job_queue.run_repeating(
                callback=self._cleanup_rate_limiter,
                interval=3600,  # 每小时执行一次
                first=3600,  # 启动后1小时开始第一次清理
            )
            logger.info("已启动速率限制器定期清理任务（每小时）")

        logger.info("Banhammer Bot 启动成功！")

        # 简单启动
        try:
            self.application.run_polling()
        except Exception as e:
            logger.error(f"Bot 运行出错: {e}")
            raise

    def stop(self):
        """停止 Bot 并清理资源"""
        import asyncio

        try:
            # 使用 asyncio.run() 执行异步清理操作
            asyncio.run(self._async_stop())
        except Exception as e:
            logger.error(f"停止 Bot 时出错: {e}", exc_info=True)
        finally:
            # 清理数据库连接
            if self.db:
                try:
                    self.db.close()
                    logger.debug("数据库连接已关闭")
                except Exception as e:
                    logger.error(f"关闭数据库时出错: {e}", exc_info=True)

    async def _async_stop(self):
        """异步停止 Bot（内部方法）"""
        if self.application:
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Banhammer Bot 已停止")

    def _register_handlers(self, application: Application):
        """注册消息处理器"""
        # 注册命令处理器
        application.add_handler(CommandHandler("start", self._handle_start))
        application.add_handler(CommandHandler("help", self._handle_help))
        application.add_handler(CommandHandler("admin", self._handle_admin))
        application.add_handler(CommandHandler("spam", self.blacklist_handler.handle_spam_report))
        application.add_handler(CommandHandler("unban", self.blacklist_handler.handle_unban_command))
        application.add_handler(
            CommandHandler("blacklist", self.blacklist_handler.handle_blacklist_command)
        )
        application.add_handler(CommandHandler("global", self.blacklist_handler.handle_global_command))
        application.add_handler(
            CommandHandler("log_channel", self.blacklist_handler.handle_log_channel_command)
        )
        application.add_handler(CommandHandler("cleanup", self.blacklist_handler.handle_cleanup_command))
        application.add_handler(CommandHandler("private_help", self._handle_private_help))

        # 注册群组消息处理器
        application.add_handler(
            MessageHandler(
                filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, self._handle_message
            )
        )

        # 注册群组贴纸处理器
        application.add_handler(
            MessageHandler(filters.Sticker.ALL & filters.ChatType.GROUPS, self._handle_message)
        )

        # 注册群组GIF处理器
        application.add_handler(
            MessageHandler(filters.ANIMATION & filters.ChatType.GROUPS, self._handle_message)
        )

        # 注册群组内联Bot处理器
        application.add_handler(
            MessageHandler(filters.ViaBot() & filters.ChatType.GROUPS, self._handle_message)
        )

        # 注册私聊转发消息处理器 - 直接添加黑名单
        application.add_handler(
            MessageHandler(
                filters.ChatType.PRIVATE & filters.FORWARDED,
                self.blacklist_handler.handle_private_forward,
            )
        )

        # 错误处理器
        application.add_error_handler(self._error_handler)

        logger.info("处理器注册完成")

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        message = update.message
        if not message:
            return

        # 获取阈值配置
        threshold = Config.BLACKLIST_CONFIG.get("text_spam_threshold", 3)

        # 检查是否为私聊
        if message.chat.type == "private":
            welcome_text = (
                "🤖 <b>Banhammer Bot</b>\n\n"
                "欢迎使用群组垃圾消息清理机器人！\n\n"
                "📋 <b>私聊功能:</b>\n"
                "• 转发消息给Bot可直接添加黑名单\n"
                "• 支持链接、贴纸、GIF、内联Bot、文字消息\n"
                "• 自动添加到所有贡献群组和通用黑名单\n\n"
                "📋 <b>使用方法:</b>\n"
                "1. 在群组中找到要屏蔽的消息\n"
                "2. 转发该消息给Bot\n"
                "3. Bot会自动识别并添加到黑名单\n\n"
                "🔧 <b>群组命令:</b>\n"
                "/help - 查看群组帮助信息\n"
                "/spam - 举报垃圾消息\n"
                "/global - 通用黑名单管理\n"
                "/admin - 呼叫管理员\n\n"
                "💡 在群组中使用 /help 查看详细帮助"
            )
        else:
            welcome_text = (
                "🤖 <b>Banhammer Bot</b>\n\n"
                "欢迎使用群组垃圾消息清理机器人！\n\n"
                "🔧 <b>主要功能:</b>\n"
                "• 黑名单管理（链接、贴纸、GIF、Bot、文字）\n"
                f"• 文字消息举报计数（{threshold}次自动加入黑名单）\n"
                "• 自动封禁违规用户\n"
                "• 通用黑名单共享系统\n"
                "• 管理员呼叫功能\n\n"
                "📋 <b>管理员命令:</b>\n"
                "/help - 查看帮助信息\n"
                "/spam - 举报垃圾消息\n"
                "/global - 通用黑名单管理\n"
                "/admin - 呼叫管理员\n\n"
                "💡 使用 /help 查看详细帮助"
            )

        await context.bot.send_message(
            chat_id=message.chat.id, text=welcome_text, parse_mode=ParseMode.HTML
        )

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /help 命令"""
        message = update.message
        if not message:
            return

        # 获取阈值配置
        threshold = Config.BLACKLIST_CONFIG.get("text_spam_threshold", 3)

        help_text = (
            "📋 <b>Banhammer Bot 帮助</b>\n\n"
            "🔧 <b>管理员命令:</b>\n"
            "/spam - 回复消息举报为垃圾内容\n"
            "/global Y - 加入通用黑名单\n"
            "/global N - 退出通用黑名单\n"
            "/global status - 查看当前设置\n"
            "/global stats - 查看通用黑名单统计\n"
            "/log_channel - 查看记录频道设置\n"
            "/log_channel &lt;频道ID&gt; - 设置记录频道\n"
            "/log_channel clear - 清除记录频道\n"
            "/cleanup - 清理无效黑名单项\n"
            "/admin - 呼叫管理员\n\n"
            "🌐 <b>通用黑名单功能:</b>\n"
            "• 加入：开启贡献和使用通用黑名单\n"
            "• 退出：关闭贡献和使用，删除贡献数据\n"
            "• 贡献：群组的举报会帮助其他群组\n"
            "• 使用：检测其他群组贡献的内容\n\n"
            "📋 <b>记录频道功能:</b>\n"
            "• 每个群组可以设置独立的记录频道\n"
            "• 不同群组可以使用相同的记录频道\n"
            "• 记录包含来源群组信息\n"
            "• 未设置时不会记录到频道\n\n"
            "⚡ <b>黑名单检测:</b>\n"
            "• 黑名单链接\n"
            "• 黑名单贴纸（精确到单个贴纸）\n"
            "• 黑名单GIF\n"
            "• 黑名单内联Bot（使用Bot ID）\n"
            "• 文字消息黑名单\n\n"
            "📝 <b>文字消息黑名单:</b>\n"
            f"• 同一发送者的同一消息被举报{threshold}次后自动加入黑名单\n"
            "• 支持通用黑名单贡献和共享\n"
            "• 自动删除和封禁违规用户\n\n"
            "🛡️ <b>保护措施:</b>\n"
            "• 自动删除违规消息\n"
            "• 自动封禁违规用户\n"
            "• 操作记录到指定频道\n\n"
            "🆕 <b>贴纸识别升级:</b>\n"
            "• 使用file_unique_id精确识别单个贴纸\n"
            "• 支持跨群组共享贴纸黑名单\n"
            "• 自动迁移旧版贴纸数据\n\n"
            "📱 <b>私聊转发功能:</b>\n"
            "• 转发消息给Bot可直接添加黑名单\n"
            "• 支持所有消息类型\n"
            "• 自动添加到所有贡献群组\n"
            "• 自动添加到通用黑名单"
        )

        await context.bot.send_message(
            chat_id=message.chat.id, text=help_text, parse_mode=ParseMode.HTML
        )

    async def _handle_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /admin 命令"""
        message = update.message
        if not message:
            return

        # 获取群组管理员列表
        try:
            admins = await context.bot.get_chat_administrators(message.chat.id)
            admin_list = []

            for admin in admins:
                if admin.user.username:
                    admin_list.append(f"@{admin.user.username}")
                else:
                    admin_list.append(f"{admin.user.first_name}")

            if admin_list:
                admin_text = "👮 <b>群组管理员:</b>\n\n" + "\n".join(
                    [f"• {admin}" for admin in admin_list]
                )
            else:
                admin_text = "❌ 无法获取管理员列表"

            await context.bot.send_message(
                chat_id=message.chat.id, text=admin_text, parse_mode=ParseMode.HTML
            )

        except Exception as e:
            logger.error(f"获取管理员列表失败: {e}")
            await context.bot.send_message(chat_id=message.chat.id, text="❌ 获取管理员列表失败")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理普通消息"""
        message = update.message
        if not message:
            return

        # 检查用户权限 - 管理员和群主的消息跳过检测
        if await self._is_admin_or_creator(message):
            logger.info(f"管理员消息，跳过检测: {message.from_user.username}")
            return

        # 使用共享的黑名单处理器实例检查黑名单
        if await self.blacklist_handler.check_blacklist(message, context):
            return

        # 检查 @admin 呼叫（仅文本消息）
        if message.text:
            admin_handler = AdminHandler()
            await admin_handler.handle_admin_call(update, context)

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """错误处理器"""
        logger.error(
            f"处理更新时发生错误 - Update: {update}, Error: {context.error}",
            exc_info=context.error
        )
        return None

    async def _handle_private_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理私聊 /private_help 命令"""
        message = update.message
        if not message:
            return

        help_text = (
            "📋 <b>私聊转发功能帮助</b>\n\n"
            "🔄 <b>功能说明:</b>\n"
            "通过私聊转发消息给Bot，可以直接将内容添加到黑名单中，无需在群组中使用命令。\n\n"
            "📋 <b>使用方法:</b>\n"
            "1. 在群组中找到要屏蔽的消息\n"
            '2. 长按该消息，选择"转发"\n'
            "3. 选择Bot作为转发目标\n"
            "4. Bot会自动识别消息类型并添加到黑名单\n\n"
            "✅ <b>支持的消息类型:</b>\n"
            "• 链接消息 - 自动提取链接\n"
            "• 贴纸 - 使用file_unique_id精确识别\n"
            "• GIF动画 - 使用file_id识别\n"
            "• 内联Bot消息 - 使用Bot ID识别\n"
            "• 文字消息 - 生成内容哈希\n\n"
            "🎯 <b>添加范围:</b>\n"
            "• 自动添加到所有启用了通用黑名单贡献的群组\n"
            "• 自动添加到通用黑名单\n"
            "• 支持跨群组共享\n\n"
            "🔄 <b>转发支持:</b>\n"
            "• 支持从群组转发消息\n"
            "• 支持从用户转发消息\n"
            "• 支持从频道转发消息\n\n"
            "🔒 <b>权限要求:</b>\n"
            "• 只有配置的管理员用户才能使用此功能\n"
            "• 需要在.env文件中配置ADMIN_USER_IDS\n\n"
            "📝 <b>注意事项:</b>\n"
            "• 只能转发消息，不能直接发送或复制粘贴\n"
            "• 操作会记录到日志频道\n"
            "• 建议谨慎使用，避免误操作"
        )

        await context.bot.send_message(
            chat_id=message.chat.id, text=help_text, parse_mode=ParseMode.HTML
        )

    async def _is_admin_or_creator(self, message: Message) -> bool:
        """检查用户是否为管理员或群主"""
        try:
            chat_member = await message.chat.get_member(message.from_user.id)
            return chat_member.status in ["administrator", "creator"]
        except Exception as e:
            logger.error(f"检查用户权限失败: {e}")
            return False

    async def _cleanup_rate_limiter(self, context: ContextTypes.DEFAULT_TYPE):
        """定期清理速率限制器的过期记录（后台任务）"""
        from utils.rate_limiter import rate_limiter

        try:
            rate_limiter.cleanup_expired(window_seconds=3600)
            logger.debug("速率限制器清理任务执行完成")
        except Exception as e:
            logger.error(f"清理速率限制器时出错: {e}", exc_info=True)


def main():
    try:
        bot = BanhammerBot()
        bot.start()
    except Exception as e:
        logger.error(f"启动 Bot 失败: {e}")
        raise


if __name__ == "__main__":
    main()
