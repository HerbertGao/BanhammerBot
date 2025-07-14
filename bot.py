from datetime import datetime

from telegram import Update, Message
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import Config
from database.models import DatabaseManager
from handlers.blacklist_handler import BlacklistHandler
from handlers.spam_detector import SpamDetector
from utils.logger import logger


class BanhammerBot:
    """Banhammer Bot 主类"""

    def __init__(self):
        """初始化Bot"""
        self.token = Config.BOT_TOKEN
        self.db = DatabaseManager()
        self.application = None

        if not self.token:
            raise ValueError("BOT_TOKEN 未设置，请在 .env 文件中配置")

    def start(self):
        """启动 Bot"""
        logger.info("正在启动 Banhammer Bot...")

        # 创建应用
        self.application = Application.builder().token(self.token).build()

        # 注册处理器
        self._register_handlers(self.application)

        logger.info("Banhammer Bot 启动成功！")

        # 简单启动
        try:
            self.application.run_polling()
        except Exception as e:
            logger.error(f"Bot 运行出错: {e}")
            raise

    def stop(self):
        """停止 Bot"""
        if self.application:
            self.application.stop()
            self.application.shutdown()
            logger.info("Banhammer Bot 已停止")

    def _register_handlers(self, application: Application):
        """注册消息处理器"""
        # 黑名单处理器
        blacklist_handler = BlacklistHandler()

        # 注册命令处理器
        application.add_handler(CommandHandler("start", self._handle_start))
        application.add_handler(CommandHandler("help", self._handle_help))
        application.add_handler(CommandHandler("admin", self._handle_admin))
        application.add_handler(CommandHandler("spam", blacklist_handler.handle_spam_report))
        application.add_handler(CommandHandler("global", blacklist_handler.handle_global_command))
        application.add_handler(CommandHandler("log_channel", blacklist_handler.handle_log_channel_command))
        application.add_handler(CommandHandler("cleanup", blacklist_handler.handle_cleanup_command))
        application.add_handler(CommandHandler("private_help", self._handle_private_help))

        # 注册群组消息处理器
        application.add_handler(MessageHandler(
            filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
            self._handle_message
        ))

        # 注册群组贴纸处理器
        application.add_handler(MessageHandler(
            filters.Sticker.ALL & filters.ChatType.GROUPS,
            self._handle_message
        ))

        # 注册群组GIF处理器
        application.add_handler(MessageHandler(
            filters.ANIMATION & filters.ChatType.GROUPS,
            self._handle_message
        ))

        # 注册群组内联Bot处理器
        application.add_handler(MessageHandler(
            filters.ViaBot() & filters.ChatType.GROUPS,
            self._handle_message
        ))

        # 注册私聊转发消息处理器 - 直接添加黑名单
        application.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & filters.FORWARDED,
            blacklist_handler.handle_private_forward
        ))

        # 错误处理器
        application.add_error_handler(self._error_handler)

        logger.info("处理器注册完成")

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        message = update.message
        if not message:
            return

        # 检查是否为私聊
        if message.chat.type == 'private':
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
                "• 自动检测并删除垃圾消息\n"
                "• 黑名单管理（链接、贴纸、GIF、Bot、文字）\n"
                "• 文字消息举报计数（3次自动加入黑名单）\n"
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
            chat_id=message.chat.id,
            text=welcome_text,
            parse_mode=ParseMode.HTML
        )

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /help 命令"""
        message = update.message
        if not message:
            return

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
            "⚡ <b>自动检测:</b>\n"
            "• 垃圾链接\n"
            "• 禁止词汇\n"
            "• 大写比例过高\n"
            "• 重复字符\n"
            "• 黑名单贴纸（精确到单个贴纸）\n"
            "• 黑名单GIF\n"
            "• 黑名单内联Bot\n"
            "• 文字消息黑名单\n\n"
            "📝 <b>文字消息黑名单:</b>\n"
            "• 同一发送者的同一消息被举报3次后自动加入黑名单\n"
            "• 支持通用黑名单贡献和共享\n"
            "• 自动删除和封禁违规用户\n\n"
            "🛡️ <b>保护措施:</b>\n"
            "• 自动删除违规消息\n"
            "• 自动封禁违规用户\n"
            "• 操作记录到指定频道\n\n"
            "🆕 <b>贴纸识别升级:</b>\n"
            "• 使用file_unique_id精确识别单个贴纸\n"
            "• 比set_name更可靠，不会出现空值问题\n"
            "• 支持所有类型的贴纸（包括单个贴纸）"
        )

        await context.bot.send_message(
            chat_id=message.chat.id,
            text=help_text,
            parse_mode=ParseMode.HTML
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
                admin_text = "👮 <b>群组管理员:</b>\n\n" + "\n".join([f"• {admin}" for admin in admin_list])
            else:
                admin_text = "❌ 无法获取管理员列表"

            await context.bot.send_message(
                chat_id=message.chat.id,
                text=admin_text,
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            logger.error(f"获取管理员列表失败: {e}")
            await context.bot.send_message(
                chat_id=message.chat.id,
                text="❌ 获取管理员列表失败"
            )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理普通消息"""
        message = update.message
        if not message:
            return

        # 创建黑名单处理器实例
        blacklist_handler = BlacklistHandler()

        # 检查黑名单
        if await blacklist_handler.check_blacklist(message, context):
            return

        # 检查垃圾消息
        spam_detector = SpamDetector()
        if spam_detector.detect_spam(message)[0]:
            await self._handle_spam_message(message, context)

    async def _handle_spam_message(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """处理垃圾消息"""
        user = message.from_user
        chat = message.chat

        logger.warning(f"检测到垃圾消息 - 用户: {user.username}, 群组: {chat.title}")

        # 删除消息
        try:
            await message.delete()
            logger.info(f"已删除垃圾消息: {message.message_id}")
        except Exception as e:
            logger.error(f"删除垃圾消息失败: {e}")

        # 封禁用户
        if Config.BLACKLIST_CONFIG['auto_ban_on_spam']:
            try:
                await context.bot.ban_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    until_date=Config.BLACKLIST_CONFIG['ban_duration'] if Config.BLACKLIST_CONFIG[
                                                                              'ban_duration'] > 0 else None
                )

                # 记录封禁
                ban_id = self.db.add_ban_record(
                    chat_id=chat.id,
                    user_id=user.id,
                    reason="发送垃圾消息",
                    banned_by=context.bot.id
                )

                # 记录操作
                self.db.add_action_log(
                    chat_id=chat.id,
                    action_type='ban',
                    user_id=user.id,
                    target_content="垃圾消息",
                    reason="自动检测为垃圾消息"
                )

                logger.info(f"已封禁垃圾消息发送者: {user.username} (ID: {user.id})")

                # 记录到频道
                if Config.BLACKLIST_CONFIG['log_actions']:
                    await self._log_to_channel(context, chat, user, 'ban', "垃圾消息", "自动检测为垃圾消息")

            except Exception as e:
                logger.error(f"封禁垃圾消息发送者失败: {e}")

    async def _log_to_channel(self, context: ContextTypes.DEFAULT_TYPE, chat, user, action_type: str,
                              content: str, reason: str):
        """记录操作到群组指定的频道"""
        try:
            # 处理chat为None的情况（如私聊转发）
            if chat is None:
                chat_info = "私聊"
                source_chat_id = None
            else:
                chat_info = chat.title
                source_chat_id = chat.id
            
            # 获取群组的记录频道ID
            log_channel_id = None
            if source_chat_id:
                log_channel_id = self.db.get_group_log_channel(source_chat_id)
            
            # 如果没有设置记录频道，则不记录
            if not log_channel_id:
                logger.info(f"群组 {source_chat_id} 未设置记录频道，跳过记录")
                return
            
            log_text = (
                f"🔔 <b>操作记录</b>\n\n"
                f"<b>来源群组:</b> {chat_info}\n"
                f"<b>用户:</b> {user.username or user.first_name}\n"
                f"<b>操作:</b> {action_type}\n"
                f"<b>内容:</b> {content}\n"
                f"<b>原因:</b> {reason}\n"
                f"<b>时间:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            await context.bot.send_message(
                chat_id=log_channel_id,
                text=log_text,
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            logger.error(f"记录到频道失败: {e}")

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """错误处理器"""
        logger.error(f"处理更新时发生错误: {context.error}")
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
            "2. 长按该消息，选择\"转发\"\n"
            "3. 选择Bot作为转发目标\n"
            "4. Bot会自动识别消息类型并添加到黑名单\n\n"
            "✅ <b>支持的消息类型:</b>\n"
            "• 链接消息 - 自动提取链接\n"
            "• 贴纸 - 使用file_unique_id精确识别\n"
            "• GIF动画 - 使用file_id识别\n"
            "• 内联Bot消息 - 识别Bot用户名\n"
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
            chat_id=message.chat.id,
            text=help_text,
            parse_mode=ParseMode.HTML
        )


def main():
    try:
        bot = BanhammerBot()
        bot.start()
    except Exception as e:
        logger.error(f"启动 Bot 失败: {e}")
        raise


if __name__ == "__main__":
    main()
