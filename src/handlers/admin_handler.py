import re
from typing import List

from telegram import Message, Update, User
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from utils.logger import logger


class AdminHandler:
    """管理员处理器"""

    def __init__(self):
        pass

    async def handle_admin_call(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 @admin 呼叫"""
        message = update.message

        if not message or not message.text:
            return

        # 检查是否为群组消息
        if message.chat.type not in ["group", "supergroup"]:
            return

        # 检查消息是否包含 @admin
        if not self._contains_admin_call(message.text):
            return

        # 获取群组管理员列表
        admins = await self._get_chat_admins(message.chat.id, context)

        if not admins:
            await self._send_no_admins_message(message, context)
            return

        # 发送管理员列表
        await self._send_admin_list(message, context, admins)

    def _contains_admin_call(self, text: str) -> bool:
        """检查消息是否包含 @admin 呼叫"""
        # 不区分大小写的正则匹配
        pattern = r"@admin"
        return bool(re.search(pattern, text, re.IGNORECASE))

    async def _get_chat_admins(
        self, chat_id: int, context: ContextTypes.DEFAULT_TYPE
    ) -> List[User]:
        """获取群组管理员列表（排除机器人）"""
        try:
            admins = await context.bot.get_chat_administrators(chat_id)

            # 过滤掉机器人账号
            human_admins = []
            for admin in admins:
                if not admin.user.is_bot:
                    human_admins.append(admin.user)

            logger.info(f"群组 {chat_id} 的管理员数量: {len(human_admins)}")
            return human_admins

        except Exception as e:
            logger.error(f"获取群组管理员失败: {e}")
            return []

    async def _send_admin_list(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, admins: List[User]
    ):
        """发送管理员列表"""
        try:
            # 构建管理员列表消息
            admin_text = "👥 **群组管理员**\n\n"

            for i, admin in enumerate(admins, 1):
                # 获取用户显示名称
                display_name = admin.first_name
                if admin.last_name:
                    display_name += f" {admin.last_name}"

                # 构建用户信息
                user_info = f"{i}. {display_name}"
                if admin.username:
                    user_info += f" (@{admin.username})"

                admin_text += f"{user_info}\n"

            admin_text += f"\n📞 呼叫者: {message.from_user.mention_html()}"

            # 发送消息
            await context.bot.send_message(
                chat_id=message.chat.id,
                text=admin_text,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.message_id,
            )

            logger.info(f"已发送管理员列表给用户 {message.from_user.username}")

        except Exception as e:
            logger.error(f"发送管理员列表失败: {e}")

    async def _send_no_admins_message(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """发送无管理员消息"""
        try:
            no_admin_text = (
                "<b>❌ 无管理员</b>\n\n" "当前群组没有人类管理员。\n" "请联系群主添加管理员。"
            )

            await context.bot.send_message(
                chat_id=message.chat.id,
                text=no_admin_text,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.message_id,
            )

        except Exception as e:
            logger.error(f"发送无管理员消息失败: {e}")

    async def handle_admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /admin 命令"""
        message = update.message

        if not message:
            return

        # 检查是否为群组消息
        if message.chat.type not in ["group", "supergroup"]:
            await self._send_private_chat_message(message, context)
            return

        # 获取群组管理员列表
        admins = await self._get_chat_admins(message.chat.id, context)

        if not admins:
            await self._send_no_admins_message(message, context)
            return

        # 发送管理员列表
        await self._send_admin_list(message, context, admins)

    async def _send_private_chat_message(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ):
        """发送私聊消息"""
        try:
            private_text = (
                "<b>ℹ️ 使用说明</b>\n\n"
                "此命令只能在群组中使用。\n"
                "在群组中发送 <code>/admin</code> 或包含 <code>@admin</code> 的消息即可查看管理员列表。"
            )

            await context.bot.send_message(
                chat_id=message.chat.id, text=private_text, parse_mode=ParseMode.HTML
            )

        except Exception as e:
            logger.error(f"发送私聊消息失败: {e}")
