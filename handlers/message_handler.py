import asyncio
from typing import Optional
from telegram import Update, Message, ChatMember
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from config import Config
from utils.logger import logger
from handlers.spam_detector import SpamDetector
from handlers.blacklist_handler import BlacklistHandler
from handlers.admin_handler import AdminHandler

class GroupMessageHandler:
    """消息处理器"""
    
    def __init__(self):
        self.spam_detector = SpamDetector()
        self.blacklist_handler = BlacklistHandler()
        self.admin_handler = AdminHandler()
        self.config = Config.DELETE_CONFIG
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理新消息"""
        message = update.message
        
        if not message:
            return
        
        # 检查是否为群组消息
        if message.chat.type not in ['group', 'supergroup']:
            return
        
        # 检查用户权限
        if await self._is_admin_or_creator(message):
            logger.info(f"管理员消息，跳过检测: {message.from_user.username}")
            return
        
        # 首先检查黑名单
        if await self.blacklist_handler.check_blacklist(message, context):
            return  # 黑名单处理已完成，无需继续
        
        # 检查 @admin 呼叫（仅文本消息）
        if message.text:
            await self.admin_handler.handle_admin_call(update, context)
        
        # 对所有消息类型进行垃圾检测
        is_spam, reason, details = self.spam_detector.detect_spam(message)
        
        if is_spam:
            await self._handle_spam_message(message, context, reason, details)
    
    async def _handle_spam_message(self, message: Message, context: ContextTypes.DEFAULT_TYPE, 
                                 reason: str, details: dict):
        """处理垃圾消息"""
        user = message.from_user
        chat = message.chat
        
        logger.warning(f"检测到垃圾消息 - 用户: {user.username}, 原因: {reason}, 详情: {details}")
        
        if self.config['auto_delete_spam']:
            if self.config['warn_before_delete']:
                # 先发送警告
                warning_msg = await self._send_warning(message, context, reason)
                
                # 等待一段时间后删除
                await asyncio.sleep(self.config['warn_timeout'])
                
                # 删除原消息和警告消息
                await self._delete_messages([message, warning_msg])
            else:
                # 直接删除
                await self._delete_messages([message])
    
    async def _send_warning(self, message: Message, context: ContextTypes.DEFAULT_TYPE, 
                           reason: str) -> Optional[Message]:
        """发送警告消息"""
        user = message.from_user
        warning_text = (
            f"⚠️ **垃圾消息警告**\n\n"
            f"用户: {user.mention_html()}\n"
            f"原因: {reason}\n\n"
            f"此消息将在 {self.config['warn_timeout']} 秒后自动删除。"
        )
        
        try:
            warning_msg = await context.bot.send_message(
                chat_id=message.chat.id,
                text=warning_text,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.message_id
            )
            return warning_msg
        except Exception as e:
            logger.error(f"发送警告消息失败: {e}")
            return None
    
    async def _delete_messages(self, messages: list):
        """删除消息列表"""
        for message in messages:
            if message:
                try:
                    await message.delete()
                    logger.info(f"成功删除消息: {message.message_id}")
                except Exception as e:
                    logger.error(f"删除消息失败: {e}")
    
    async def _is_admin_or_creator(self, message: Message) -> bool:
        """检查用户是否为管理员或群主"""
        try:
            chat_member = await message.chat.get_member(message.from_user.id)
            return chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
        except Exception as e:
            logger.error(f"检查用户权限失败: {e}")
            return False
    
    async def handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理命令"""
        message = update.message
        command = message.text.split()[0].lower()
        
        if command == '/help':
            await self._send_help(message, context)
        elif command == '/spam':
            await self.blacklist_handler.handle_spam_report(update, context)
        elif command == '/unban':
            await self.blacklist_handler.handle_unban_command(update, context)
        elif command == '/blacklist':
            await self.blacklist_handler.handle_blacklist_command(update, context)
        elif command == '/admin':
            await self.admin_handler.handle_admin_command(update, context)
    
    async def _send_help(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """发送帮助信息"""
        help_text = (
            "<b>🤖 Banhammer Bot 帮助</b>\n\n"
            "<b>可用命令:</b>\n"
            "/help - 显示此帮助信息\n"
            "/spam - 举报消息为垃圾消息（回复消息）\n"
            "/blacklist - 查看群组黑名单\n"
            "/unban &lt;user_id&gt; - 解除用户封禁\n"
            "/admin - 查看群组管理员列表\n\n"
            "<b>功能:</b>\n"
            "• 自动检测并删除垃圾消息\n"
            "• 黑名单系统（链接、贴纸、GIF、Bot）\n"
            "• 自动封禁违规用户\n"
            "• 操作记录到指定频道\n"
            "• @admin 呼叫管理员功能\n\n"
            "<b>权限:</b>\n"
            "管理员和群主的消息不会被检测。"
        )
        
        await context.bot.send_message(
            chat_id=message.chat.id,
            text=help_text,
            parse_mode=ParseMode.HTML
        ) 