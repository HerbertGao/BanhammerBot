import asyncio
import hashlib
import re
from typing import Dict, Optional, Tuple

from telegram import Chat, Message, Update, User
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import Config
from database.models import DatabaseManager
from utils.logger import logger
from utils.rate_limiter import rate_limiter


class BlacklistHandler:
    """黑名单处理器"""

    def __init__(self, db: Optional[DatabaseManager] = None):
        """初始化黑名单处理器

        Args:
            db: DatabaseManager实例，如果未提供则创建新实例（用于向后兼容）
        """
        self.db = db if db is not None else DatabaseManager()
        self.config = Config.BLACKLIST_CONFIG
        self.rate_limit_config = Config.RATE_LIMIT_CONFIG
        self.background_tasks: list = []  # 跟踪后台任务，用于清理

    async def handle_spam_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /spam 举报命令"""
        message = update.message

        if not message:
            return

        # 检查消息发送者是否存在（频道消息的from_user为None）
        if not message.from_user:
            logger.warning("跳过处理：消息发送者为空（可能是频道消息）")
            return

        if not message.reply_to_message:
            await self._send_error_message(message, context, "请回复要举报的消息")
            return

        # 检查权限
        if not await self._is_admin_or_creator(message):
            await self._send_error_message(message, context, "只有管理员可以使用此命令")
            return

        # 速率限制检查
        if self.rate_limit_config["enabled"]:
            spam_report_config = self.rate_limit_config["spam_report"]
            if rate_limiter.is_rate_limited(
                message.from_user.id,
                "spam_report",
                spam_report_config["max_calls"],
                spam_report_config["window_seconds"],
            ):
                remaining = rate_limiter.get_remaining_time(
                    message.from_user.id, "spam_report", spam_report_config["window_seconds"]
                )
                await self._send_error_message(
                    message,
                    context,
                    f"操作过于频繁，请在 {remaining} 秒后再试",
                )
                return

        target_message = message.reply_to_message
        blacklist_type, content = self._extract_blacklist_content(target_message)

        if not blacklist_type or not content:
            await self._send_error_message(message, context, "无法识别此消息类型")
            return

        # 获取群组设置
        group_settings = self.db.get_group_settings(message.chat.id)

        # 如果是文字消息，需要特殊处理举报计数
        if blacklist_type == "text":
            await self._handle_text_spam_report(
                message, context, target_message, content, group_settings
            )
            return

        # 添加到群组黑名单
        success = self.db.add_to_blacklist(
            chat_id=message.chat.id,
            blacklist_type=blacklist_type,
            content=content,
            created_by=message.from_user.id,
        )

        # 如果群组启用了贡献到通用黑名单，也添加到通用黑名单
        global_success = False
        if group_settings["contribute_to_global"]:
            global_success = self.db.add_to_global_blacklist(
                blacklist_type=blacklist_type, content=content, contributed_by=message.chat.id
            )

        if success:
            # 删除被举报的消息
            try:
                await target_message.delete()
                logger.info(f"已删除被举报的消息: {target_message.message_id}")
            except Exception as e:
                logger.error(f"删除被举报消息失败: {e}", exc_info=True)

            # 封禁发送者（检查target_message.from_user是否存在）
            if target_message.from_user:
                try:
                    await context.bot.ban_chat_member(
                        chat_id=message.chat.id,
                        user_id=target_message.from_user.id,
                        until_date=(
                            Config.BLACKLIST_CONFIG["ban_duration"]
                            if Config.BLACKLIST_CONFIG["ban_duration"] > 0
                            else None
                        ),
                    )

                    # 记录封禁
                    ban_id = self.db.add_ban_record(
                        chat_id=message.chat.id,
                        user_id=target_message.from_user.id,
                        reason=f"发送垃圾内容被举报 - 类型: {blacklist_type}",
                        banned_by=message.from_user.id,
                    )

                    logger.info(
                        f"[SPAM_REPORT] 已封禁发送者 | "
                        f"user_id={target_message.from_user.id} "
                        f"username={target_message.from_user.username} "
                        f"chat_id={message.chat.id} "
                        f"blacklist_type={blacklist_type} "
                        f"reporter_id={message.from_user.id}"
                    )

                except Exception as e:
                    logger.error(f"封禁发送者失败: {e}", exc_info=True)
            else:
                logger.warning(f"无法封禁发送者：消息发送者为空（可能是频道消息）")

            # 记录操作
            self.db.add_action_log(
                chat_id=message.chat.id,
                action_type="spam_report",
                user_id=message.from_user.id,
                target_content=content,
                reason=f"举报为垃圾消息 - 类型: {blacklist_type}",
            )

            # 如果贡献到通用黑名单成功，记录贡献日志
            if global_success:
                self.db.add_action_log(
                    chat_id=message.chat.id,
                    action_type="global_contribution",
                    user_id=message.from_user.id,
                    target_content=content,
                    reason=f"贡献到通用黑名单 - 类型: {blacklist_type}",
                )

            # 发送确认消息
            confirm_text = f"已添加到黑名单并处理\n类型: {blacklist_type}\n内容: {content}\n已删除消息并封禁发送者"
            if global_success:
                confirm_text += "\n✅ 已贡献到通用黑名单"

            sent_message = await self._send_success_message(message, context, confirm_text)

            # 延迟后删除确认消息和/spam命令（后台任务，不阻塞日志记录）
            # 先清理已完成的任务，防止内存泄漏
            self._cleanup_completed_tasks()
            task = asyncio.create_task(self._auto_delete_messages([sent_message, message]))
            self.background_tasks.append(task)

            # 记录到频道
            if Config.BLACKLIST_CONFIG["log_actions"]:
                await self._log_to_channel(
                    context,
                    message.chat,
                    message.from_user,
                    "spam_report",
                    content,
                    f"举报为垃圾消息 - 类型: {blacklist_type}",
                )
        else:
            await self._send_error_message(message, context, "添加到黑名单失败")

    def _extract_blacklist_content(self, message: Message) -> Tuple[Optional[str], Optional[str]]:
        """提取黑名单内容"""
        # 检查内联Bot（优先级最高，因为代表消息来源）
        if message.via_bot:
            bot_id = message.via_bot.id
            logger.debug(f"检测到内联Bot: {message.via_bot}, id: {bot_id}")
            # 只有当id存在时才返回bot类型
            if bot_id:
                logger.info(f"提取到内联Bot黑名单内容: {bot_id}")
                return "bot", str(bot_id)  # 转换为字符串以保持一致性
            else:
                logger.warning(f"内联Bot存在但id为空: {message.via_bot}")

        # 检查链接
        if message.text and self._is_only_link(message.text):
            return "link", self._extract_link(message.text)

        # 检查贴纸 - 使用file_unique_id进行精确识别
        if message.sticker:
            file_unique_id = message.sticker.file_unique_id
            # file_unique_id总是存在且唯一，更可靠
            if file_unique_id:
                return "sticker", file_unique_id

        # 检查GIF动画
        if message.animation:
            return "gif", message.animation.file_id

        # 检查普通文字消息
        if message.text and not self._is_only_link(message.text):
            return "text", self._generate_message_hash(message.text)

        return None, None

    def _generate_message_hash(self, text: str) -> str:
        """生成消息内容的哈希值"""
        # 清理文本（移除多余空格，转换为小写）
        clean_text = " ".join(text.strip().lower().split())
        # 生成SHA256哈希
        return hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

    def _is_only_link(self, text: str) -> bool:
        """检查消息是否只包含链接"""
        # 移除空白字符
        clean_text = text.strip()

        # 匹配链接模式
        link_patterns = [
            r"^https?://[^\s]+$",
            r"^www\.[^\s]+$",
            r"^t\.me/[^\s]+$",
            r"^@[a-zA-Z0-9_]+$",
        ]

        for pattern in link_patterns:
            if re.match(pattern, clean_text, re.IGNORECASE):
                return True

        return False

    def _extract_link(self, text: str) -> str:
        """提取链接"""
        # 匹配各种链接格式
        url_patterns = [r"https?://[^\s]+", r"www\.[^\s]+", r"t\.me/[^\s]+", r"@[a-zA-Z0-9_]+"]

        for pattern in url_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)

        return text.strip()

    async def _handle_text_spam_report(
        self,
        message: Message,
        context: ContextTypes.DEFAULT_TYPE,
        target_message: Message,
        message_hash: str,
        group_settings: Dict,
    ):
        """处理文字消息的举报"""
        # 检查目标消息发送者是否存在
        if not target_message.from_user:
            logger.warning("跳过处理文字消息举报：目标消息发送者为空（可能是频道消息）")
            await self._send_error_message(message, context, "无法举报此消息：发送者信息不可用")
            return

        # 增加举报计数
        report_info = self.db.increment_text_report_count(
            chat_id=message.chat.id, user_id=target_message.from_user.id, message_hash=message_hash
        )

        # 记录操作
        self.db.add_action_log(
            chat_id=message.chat.id,
            action_type="text_spam_report",
            user_id=message.from_user.id,
            target_content=f"文字消息 (举报次数: {report_info['report_count']})",
            reason=f"举报文字消息为垃圾内容",
        )

        # 删除被举报的消息
        try:
            await target_message.delete()
            logger.info(f"已删除被举报的文字消息: {target_message.message_id}")
        except Exception as e:
            logger.error(f"删除被举报文字消息失败: {e}", exc_info=True)

        # 如果举报次数达到阈值，自动加入黑名单
        if report_info["should_add_to_blacklist"]:
            # 添加到群组黑名单
            success = self.db.add_to_blacklist(
                chat_id=message.chat.id,
                blacklist_type="text",
                content=message_hash,
                created_by=message.from_user.id,
            )

            # 如果群组启用了贡献到通用黑名单，也添加到通用黑名单
            global_success = False
            if group_settings["contribute_to_global"]:
                global_success = self.db.add_to_global_blacklist(
                    blacklist_type="text", content=message_hash, contributed_by=message.chat.id
                )

            # 封禁发送者
            try:
                await context.bot.ban_chat_member(
                    chat_id=message.chat.id,
                    user_id=target_message.from_user.id,
                    until_date=(
                        Config.BLACKLIST_CONFIG["ban_duration"]
                        if Config.BLACKLIST_CONFIG["ban_duration"] > 0
                        else None
                    ),
                )

                # 记录封禁
                ban_id = self.db.add_ban_record(
                    chat_id=message.chat.id,
                    user_id=target_message.from_user.id,
                    reason=f"文字消息被举报{self.db.text_spam_threshold}次以上，自动加入黑名单",
                    banned_by=message.from_user.id,
                )

                logger.info(
                    f"已封禁文字消息发送者: {target_message.from_user.username} (ID: {target_message.from_user.id})"
                )

            except Exception as e:
                logger.error(f"封禁文字消息发送者失败: {e}", exc_info=True)

            # 如果贡献到通用黑名单成功，记录贡献日志
            if global_success:
                self.db.add_action_log(
                    chat_id=message.chat.id,
                    action_type="global_contribution",
                    user_id=message.from_user.id,
                    target_content=message_hash,
                    reason="贡献文字消息到通用黑名单",
                )

            # 发送确认消息
            confirm_text = (
                f"文字消息举报处理完成\n"
                f"举报次数: {report_info['report_count']}/{self.db.text_spam_threshold}\n"
                f"✅ 已达到{self.db.text_spam_threshold}次，已自动加入黑名单\n"
                f"已删除消息并封禁发送者"
            )
            if global_success:
                confirm_text += "\n✅ 已贡献到通用黑名单"
        else:
            # 发送确认消息
            confirm_text = (
                f"文字消息举报已记录\n"
                f"举报次数: {report_info['report_count']}/{self.db.text_spam_threshold}\n"
                f"已删除消息"
            )

        sent_message = await self._send_success_message(message, context, confirm_text)

        # 延迟后删除确认消息和/spam命令（后台任务，不阻塞日志记录）
        # 先清理已完成的任务，防止内存泄漏
        self._cleanup_completed_tasks()
        task = asyncio.create_task(self._auto_delete_messages([sent_message, message]))
        self.background_tasks.append(task)

        # 记录到频道
        if Config.BLACKLIST_CONFIG["log_actions"]:
            action_type = (
                "text_spam_blacklist"
                if report_info["should_add_to_blacklist"]
                else "text_spam_report"
            )
            reason = f"文字消息被举报{report_info['report_count']}次" + (
                "，已加入黑名单" if report_info["should_add_to_blacklist"] else ""
            )
            await self._log_to_channel(
                context,
                message.chat,
                message.from_user,
                action_type,
                f"文字消息 (举报次数: {report_info['report_count']})",
                reason,
            )

    async def check_blacklist(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """检查消息是否在黑名单中"""
        if not message:
            return False

        # 获取群组设置
        group_settings = self.db.get_group_settings(message.chat.id)

        # 检查群组黑名单
        if await self._check_group_blacklist(message, context):
            return True

        # 检查通用黑名单（如果启用）
        if group_settings["use_global_blacklist"]:
            if await self._check_global_blacklist(message, context):
                return True

        return False

    async def _check_group_blacklist(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """检查群组黑名单"""
        # 检查内联Bot（优先级最高，因为代表消息来源）
        if message.via_bot:
            bot_id = str(message.via_bot.id)  # 转换为字符串以保持一致性
            if bot_id and self.db.check_blacklist(message.chat.id, "bot", bot_id):
                await self._handle_blacklist_violation(message, context, "bot", bot_id, "group")
                return True

        # 检查链接 - 只检查纯链接消息
        if message.text and self._is_only_link(message.text):
            link = self._extract_link(message.text)
            if link and self.db.check_blacklist(message.chat.id, "link", link):
                await self._handle_blacklist_violation(message, context, "link", link, "group")
                return True

        # 检查贴纸 - 使用file_unique_id进行精确识别
        if message.sticker:
            file_unique_id = message.sticker.file_unique_id
            if file_unique_id and self.db.check_blacklist(
                message.chat.id, "sticker", file_unique_id
            ):
                await self._handle_blacklist_violation(
                    message, context, "sticker", file_unique_id, "group"
                )
                return True

        # 检查GIF动画
        if message.animation:
            file_id = message.animation.file_id
            if file_id and self.db.check_blacklist(message.chat.id, "gif", file_id):
                await self._handle_blacklist_violation(message, context, "gif", file_id, "group")
                return True

        # 检查文字消息
        if message.text and not self._is_only_link(message.text):
            message_hash = self._generate_message_hash(message.text)
            if self.db.check_blacklist(message.chat.id, "text", message_hash):
                await self._handle_blacklist_violation(
                    message, context, "text", message_hash, "group"
                )
                return True

        return False

    async def _check_global_blacklist(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """检查通用黑名单"""
        # 检查内联Bot（优先级最高，因为代表消息来源）
        if message.via_bot:
            bot_id = str(message.via_bot.id)  # 转换为字符串以保持一致性
            if bot_id and self.db.check_global_blacklist("bot", bot_id):
                self.db.increment_global_blacklist_usage("bot", bot_id)
                await self._handle_blacklist_violation(message, context, "bot", bot_id, "global")
                return True

        # 检查链接 - 只检查纯链接消息
        if message.text and self._is_only_link(message.text):
            link = self._extract_link(message.text)
            if link and self.db.check_global_blacklist("link", link):
                self.db.increment_global_blacklist_usage("link", link)
                await self._handle_blacklist_violation(message, context, "link", link, "global")
                return True

        # 检查贴纸 - 使用file_unique_id进行精确识别
        if message.sticker:
            file_unique_id = message.sticker.file_unique_id
            if file_unique_id and self.db.check_global_blacklist("sticker", file_unique_id):
                self.db.increment_global_blacklist_usage("sticker", file_unique_id)
                await self._handle_blacklist_violation(
                    message, context, "sticker", file_unique_id, "global"
                )
                return True

        # 检查GIF动画
        if message.animation:
            file_id = message.animation.file_id
            if file_id and self.db.check_global_blacklist("gif", file_id):
                self.db.increment_global_blacklist_usage("gif", file_id)
                await self._handle_blacklist_violation(message, context, "gif", file_id, "global")
                return True

        # 检查文字消息
        if message.text and not self._is_only_link(message.text):
            message_hash = self._generate_message_hash(message.text)
            if self.db.check_global_blacklist("text", message_hash):
                self.db.increment_global_blacklist_usage("text", message_hash)
                await self._handle_blacklist_violation(
                    message, context, "text", message_hash, "global"
                )
                return True

        return False

    async def _handle_blacklist_violation(
        self,
        message: Message,
        context: ContextTypes.DEFAULT_TYPE,
        violation_type: str,
        content: str,
        source: str = "group",
    ):
        """处理黑名单违规"""
        # 检查消息发送者是否存在（频道消息的from_user为None）
        if not message.from_user:
            logger.warning("跳过黑名单违规处理：消息发送者为空（可能是频道消息）")
            # 仍然删除违规消息，即使无法封禁发送者
            try:
                await message.delete()
                logger.info(f"已删除违规消息: {message.message_id}")
            except Exception as e:
                logger.error(f"删除消息失败: {e}", exc_info=True)
            return

        user = message.from_user
        chat = message.chat

        source_text = "通用黑名单" if source == "global" else "群组黑名单"
        logger.warning(
            f"[BLACKLIST_VIOLATION] 检测到{source_text}违规 | "
            f"user_id={user.id} "
            f"username={user.username} "
            f"chat_id={chat.id} "
            f"violation_type={violation_type} "
            f"source={source} "
            f"content={content[:50] + '...' if len(content) > 50 else content}"
        )

        # 删除消息
        try:
            await message.delete()
            logger.info(f"已删除违规消息: {message.message_id}")
        except Exception as e:
            logger.error(f"删除消息失败: {e}", exc_info=True)

        # 封禁用户
        if Config.BLACKLIST_CONFIG["auto_ban_on_blacklist"]:
            try:
                await context.bot.ban_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    until_date=(
                        Config.BLACKLIST_CONFIG["ban_duration"]
                        if Config.BLACKLIST_CONFIG["ban_duration"] > 0
                        else None
                    ),
                )

                # 记录封禁
                ban_id = self.db.add_ban_record(
                    chat_id=chat.id,
                    user_id=user.id,
                    reason=f"发送{source_text}内容 - 类型: {violation_type}",
                    banned_by=context.bot.id,
                )

                # 记录操作
                self.db.add_action_log(
                    chat_id=chat.id,
                    action_type="ban",
                    user_id=user.id,
                    target_content=content,
                    reason=f"发送{source_text}内容 - 类型: {violation_type}",
                )

                logger.info(
                    f"[BLACKLIST_DETECT] 已封禁用户 | "
                    f"user_id={user.id} "
                    f"username={user.username} "
                    f"chat_id={chat.id} "
                    f"violation_type={violation_type} "
                    f"source={source}"
                )

                # 记录到频道
                if Config.BLACKLIST_CONFIG["log_actions"]:
                    await self._log_to_channel(
                        context,
                        chat,
                        user,
                        "ban",
                        content,
                        f"发送{source_text}内容 - 类型: {violation_type}",
                    )

            except Exception as e:
                logger.error(f"封禁用户失败: {e}", exc_info=True)

    async def handle_unban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /unban 命令"""
        message = update.message

        if not message:
            return

        # 检查权限
        if not await self._is_admin_or_creator(message):
            await self._send_error_message(message, context, "只有管理员可以使用此命令")
            return

        # 解析用户ID
        args = message.text.split()
        if len(args) < 2:
            await self._send_error_message(message, context, "请提供用户ID: /unban <user_id>")
            return

        try:
            user_id = int(args[1])
            # Telegram用户ID必须是正整数
            if user_id <= 0:
                await self._send_error_message(message, context, "用户ID必须是正整数")
                return
            # Telegram用户ID的最大值约为2^63-1，但实际使用中远小于此值
            # 这里设置一个合理的上限（10^12）来防止无意义的大数
            if user_id > 10**12:
                await self._send_error_message(message, context, "用户ID超出有效范围")
                return
        except ValueError:
            await self._send_error_message(message, context, "无效的用户ID格式")
            return

        # 解除封禁
        success = self.db.unban_user(
            chat_id=message.chat.id, user_id=user_id, unbanned_by=message.from_user.id
        )

        if success:
            try:
                await context.bot.unban_chat_member(
                    chat_id=message.chat.id, user_id=user_id, only_if_banned=True
                )

                # 记录操作
                self.db.add_action_log(
                    chat_id=message.chat.id,
                    action_type="unban",
                    user_id=message.from_user.id,
                    target_content=str(user_id),
                    reason="管理员解除封禁",
                )

                await self._send_success_message(message, context, f"已解除用户 {user_id} 的封禁")

                # 记录到频道
                if Config.BLACKLIST_CONFIG["log_actions"]:
                    await self._log_to_channel(
                        context,
                        message.chat,
                        message.from_user,
                        "unban",
                        str(user_id),
                        "管理员解除封禁",
                    )

            except Exception as e:
                logger.error(f"解除封禁失败: {e}", exc_info=True)
                await self._send_error_message(message, context, "解除封禁失败")
        else:
            await self._send_error_message(message, context, "用户未被封禁或解除失败")

    async def handle_blacklist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /blacklist 命令"""
        message = update.message

        if not message:
            return

        # 检查权限
        if not await self._is_admin_or_creator(message):
            await self._send_error_message(message, context, "只有管理员可以查看黑名单")
            return

        # 获取黑名单
        blacklist = self.db.get_blacklist(message.chat.id)

        if not blacklist:
            await self._send_success_message(message, context, "当前群组没有黑名单项")
            return

        # 格式化黑名单
        blacklist_text = "<b>📋 群组黑名单</b>\n\n"
        for i, item in enumerate(blacklist, 1):
            blacklist_text += f"{i}. <b>类型</b>: {item['type']}\n"
            blacklist_text += f"   <b>内容</b>: {item['content']}\n"
            blacklist_text += f"   <b>添加时间</b>: {item['created_at']}\n\n"

        await context.bot.send_message(
            chat_id=message.chat.id, text=blacklist_text, parse_mode=ParseMode.HTML
        )

    async def handle_global_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /global 命令"""
        message = update.message

        if not message:
            return

        # 检查权限
        if not await self._is_admin_or_creator(message):
            await self._send_error_message(message, context, "只有管理员可以使用此命令")
            return

        args = message.text.split()
        if len(args) < 2:
            await self._send_global_help(message, context)
            return

        command = args[1].lower()

        if command in ["y", "yes", "加入", "开启"]:
            # 加入通用黑名单（开启贡献和使用）
            await self._join_global_blacklist(message, context)
        elif command in ["n", "no", "退出", "关闭"]:
            # 退出通用黑名单（关闭贡献和使用）
            await self._exit_global_blacklist(message, context)
        elif command == "confirm":
            # 确认退出
            await self._confirm_exit_contribution(message, context)
        elif command == "status":
            # 显示当前设置
            await self._show_global_status(message, context)
        elif command == "stats":
            # 显示通用黑名单统计
            await self._show_global_stats(message, context)
        else:
            await self._send_global_help(message, context)

    async def handle_log_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /log_channel 命令"""
        message = update.message

        if not message:
            return

        # 检查权限
        if not await self._is_admin_or_creator(message):
            await self._send_error_message(message, context, "只有管理员可以使用此命令")
            return

        # 解析参数
        args = message.text.split()

        if len(args) == 1:
            # 显示当前设置
            await self._show_log_channel_status(message, context)
        elif len(args) == 2:
            if args[1].lower() == "clear":
                # 清除记录频道设置
                await self._clear_log_channel(message, context)
            else:
                # 设置记录频道
                await self._set_log_channel(message, context, args[1])
        else:
            await self._send_error_message(message, context, "用法: /log_channel [频道ID|clear]")

    async def _send_global_help(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """发送通用黑名单帮助信息"""
        help_text = (
            "<b>🌐 通用黑名单管理</b>\n\n"
            "<b>可用命令:</b>\n"
            "/global Y - 加入通用黑名单（开启贡献和使用）\n"
            "/global N - 退出通用黑名单（关闭贡献和使用）\n"
            "/global confirm - 确认退出（删除贡献数据）\n"
            "/global status - 显示当前设置\n"
            "/global stats - 显示通用黑名单统计\n\n"
            "<b>功能说明:</b>\n"
            "• 加入：开启贡献和使用通用黑名单\n"
            "• 退出：关闭贡献和使用，删除贡献数据\n"
            "• 贡献：群组的举报会帮助其他群组\n"
            "• 使用：检测其他群组贡献的内容"
        )

        await context.bot.send_message(
            chat_id=message.chat.id, text=help_text, parse_mode=ParseMode.HTML
        )
    async def _join_global_blacklist(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """加入通用黑名单（开启贡献和使用）"""
        current_settings = self.db.get_group_settings(message.chat.id)

        if current_settings["contribute_to_global"] and current_settings["use_global_blacklist"]:
            await self._send_error_message(message, context, "群组已加入通用黑名单")
            return

        # 开启贡献和使用功能
        success = self.db.update_group_settings(
            chat_id=message.chat.id, contribute_to_global=True, use_global_blacklist=True
        )

        if success:
            await self._send_success_message(
                message,
                context,
                "✅ 已成功加入通用黑名单\n\n🔗 贡献模式：开启\n🔍 使用模式：开启\n\n现在群组可以贡献和使用通用黑名单数据",
            )
        else:
            await self._send_error_message(message, context, "加入通用黑名单失败")

    async def _exit_global_blacklist(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """退出通用黑名单（关闭贡献和使用）"""
        current_settings = self.db.get_group_settings(message.chat.id)

        if (
            not current_settings["contribute_to_global"]
            and not current_settings["use_global_blacklist"]
        ):
            await self._send_error_message(message, context, "群组未加入通用黑名单")
            return

        # 获取当前贡献的数据数量
        contribution_count = self.db.get_group_contribution_count(message.chat.id)

        if contribution_count > 0:
            # 询问用户是否确认删除贡献的数据
            confirm_text = (
                f"⚠️ <b>确认退出通用黑名单</b>\n\n"
                f"当前群组已贡献 <b>{contribution_count}</b> 条数据到通用黑名单\n"
                f"退出后将删除所有贡献的数据，其他群组将无法使用这些数据\n\n"
                f"是否确认退出？\n"
                f"回复 <code>/global confirm</code> 来确认操作"
            )

            await context.bot.send_message(
                chat_id=message.chat.id,
                text=confirm_text,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.message_id,
            )
            return

        # 直接退出（没有贡献数据）
        success = self.db.update_group_settings(
            chat_id=message.chat.id, contribute_to_global=False, use_global_blacklist=False
        )

        if success:
            await self._send_success_message(
                message, context, "✅ 已成功退出通用黑名单\n\n🔗 贡献模式：关闭\n🔍 使用模式：关闭"
            )
        else:
            await self._send_error_message(message, context, "退出通用黑名单失败")

    async def _confirm_exit_contribution(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ):
        """确认退出贡献"""
        current_settings = self.db.get_group_settings(message.chat.id)

        if current_settings["contribute_to_global"]:
            # 删除贡献的数据
            removed_count = self.db.get_group_contribution_count(message.chat.id)

            success = self.db.update_group_settings(
                chat_id=message.chat.id, contribute_to_global=False, use_global_blacklist=False
            )

            if success:
                self.db.remove_group_contributions(message.chat.id)
                await self._send_success_message(
                    message,
                    context,
                    f"✅ 已确认退出通用黑名单\n\n🔗 贡献模式：关闭\n🔍 使用模式：关闭\n🗑️ 已删除 {removed_count} 条贡献的数据",
                )
            else:
                await self._send_error_message(message, context, "退出失败")
        else:
            await self._send_error_message(message, context, "当前未开启贡献功能")

    async def _show_global_status(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """显示当前设置状态"""
        settings = self.db.get_group_settings(message.chat.id)
        contribution_count = self.db.get_group_contribution_count(message.chat.id)

        status_text = (
            "<b>🌐 群组通用黑名单设置</b>\n\n"
            f"<b>贡献到通用黑名单:</b> {'✅ 开启' if settings['contribute_to_global'] else '❌ 关闭'}\n"
            f"<b>使用通用黑名单:</b> {'✅ 开启' if settings['use_global_blacklist'] else '❌ 关闭'}\n"
            f"<b>已贡献数据:</b> {contribution_count} 条\n\n"
            "<b>说明:</b>\n"
            "• 贡献模式：举报的内容会帮助其他群组\n"
            "• 使用模式：会检测其他群组贡献的内容\n"
            "• 退出贡献：会删除该群组贡献的所有数据"
        )

        await context.bot.send_message(
            chat_id=message.chat.id, text=status_text, parse_mode=ParseMode.HTML
        )

    async def _show_global_stats(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """显示通用黑名单统计"""
        stats = self.db.get_global_blacklist_stats()

        stats_text = (
            "<b>📊 通用黑名单统计</b>\n\n"
            f"<b>总项目数:</b> {stats['total_count']}\n"
            f"<b>总使用次数:</b> {stats['total_usage']}\n\n"
            "<b>按类型统计:</b>\n"
        )

        for blacklist_type, count in stats["type_stats"].items():
            type_name = {"link": "链接", "sticker": "贴纸", "gif": "GIF", "bot": "Bot"}.get(
                blacklist_type, blacklist_type
            )
            stats_text += f"• {type_name}: {count}个\n"

        if not stats["type_stats"]:
            stats_text += "暂无数据"

        await context.bot.send_message(
            chat_id=message.chat.id, text=stats_text, parse_mode=ParseMode.HTML
        )

    async def handle_cleanup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /cleanup 命令 - 清理无效黑名单项"""
        message = update.message

        if not message:
            return

        # 检查权限
        if not await self._is_admin_or_creator(message):
            await self._send_error_message(message, context, "只有管理员可以使用此命令")
            return

        # 执行清理
        cleanup_result = self.db.cleanup_invalid_blacklist_items()

        # 检查Sticker黑名单迁移状态
        migration_info = self.db.migrate_sticker_blacklist_to_file_unique_id()

        # 发送清理结果
        cleanup_text = (
            f"🧹 <b>黑名单清理完成</b>\n\n"
            f"<b>清理结果:</b>\n"
            f"• 群组黑名单: {cleanup_result['group_blacklist']} 项\n"
            f"• 通用黑名单: {cleanup_result['global_blacklist']} 项\n\n"
            f"<b>Sticker黑名单状态:</b>\n"
            f"• 群组Sticker项: {migration_info['group_stickers']} 个\n"
            f"• 通用Sticker项: {migration_info['global_stickers']} 个\n\n"
            f"<b>重要提示:</b>\n"
            f"系统已升级为使用file_unique_id识别贴纸\n"
            f"旧的set_name黑名单项需要手动重新添加\n"
            f"建议重新举报需要屏蔽的贴纸"
        )

        await context.bot.send_message(
            chat_id=message.chat.id, text=cleanup_text, parse_mode=ParseMode.HTML
        )

    async def handle_private_forward(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理私聊转发消息 - 直接添加黑名单"""
        message = update.message

        if not message:
            return

        # Debug日志：记录收到的消息内容和所有关键字段
        if getattr(Config, "LOG_LEVEL", "").upper() == "DEBUG":
            logger.debug(f"收到私聊消息: {message}")
            logger.debug(f"message.text: {getattr(message, 'text', None)}")
            logger.debug(f"message.sticker: {getattr(message, 'sticker', None)}")
            logger.debug(f"message.animation: {getattr(message, 'animation', None)}")
            logger.debug(f"message.via_bot: {getattr(message, 'via_bot', None)}")
            logger.debug(f"message.forward_from: {getattr(message, 'forward_from', None)}")
            logger.debug(
                f"message.forward_from_chat: {getattr(message, 'forward_from_chat', None)}"
            )
            logger.debug(f"message.forward_origin: {getattr(message, 'forward_origin', None)}")
            logger.debug(f"message.from_user: {getattr(message, 'from_user', None)}")
            logger.debug(f"message.chat: {getattr(message, 'chat', None)}")

        # 判断是否为转发消息（支持forward_from、forward_from_chat和forward_origin）
        is_forward = (
            hasattr(message, "forward_from")
            and message.forward_from is not None
            or hasattr(message, "forward_from_chat")
            and message.forward_from_chat is not None
            or hasattr(message, "forward_origin")
            and message.forward_origin is not None
        )

        if not is_forward:
            await self._send_private_error_message(
                message, context, "请转发消息给Bot，不能直接发送或复制粘贴。"
            )
            return

        # 检查用户是否为Bot的管理员
        if not await self._is_bot_admin(message.from_user.id, context):
            await self._send_private_error_message(
                message, context, "您没有权限使用此功能。只有Bot的管理员才能直接添加黑名单。"
            )
            return

        # 速率限制检查
        if self.rate_limit_config["enabled"]:
            forward_config = self.rate_limit_config["private_forward"]
            if rate_limiter.is_rate_limited(
                message.from_user.id,
                "private_forward",
                forward_config["max_calls"],
                forward_config["window_seconds"],
            ):
                remaining = rate_limiter.get_remaining_time(
                    message.from_user.id, "private_forward", forward_config["window_seconds"]
                )
                await self._send_private_error_message(
                    message,
                    context,
                    f"操作过于频繁，请在 {remaining} 秒后再试",
                )
                return

        # 提取黑名单内容
        blacklist_type, content = self._extract_blacklist_content(message)

        if not blacklist_type or not content:
            await self._send_private_error_message(
                message,
                context,
                "无法识别此消息类型。支持的类型：链接、贴纸、GIF、内联Bot、文字消息。",
            )
            return

        # 获取所有启用了通用黑名单贡献的群组
        contributing_groups = self.db.get_contributing_groups()

        # 添加到所有贡献群组的黑名单
        success_count = 0
        failed_count = 0

        if Config.PRIVATE_FORWARD_CONFIG["auto_add_to_contributing_groups"]:
            for group_id in contributing_groups:
                success = self.db.add_to_blacklist(
                    chat_id=group_id,
                    blacklist_type=blacklist_type,
                    content=content,
                    created_by=message.from_user.id,
                )
                if success:
                    success_count += 1
                else:
                    failed_count += 1

        # 添加到通用黑名单
        global_success = False
        if Config.PRIVATE_FORWARD_CONFIG["auto_add_to_global"]:
            global_success = self.db.add_to_global_blacklist(
                blacklist_type=blacklist_type, content=content, contributed_by=message.from_user.id
            )

        # 记录操作
        self.db.add_action_log(
            chat_id=message.from_user.id,  # 使用用户ID作为chat_id
            action_type="private_forward_blacklist",
            user_id=message.from_user.id,
            target_content=content,
            reason=f"私聊转发添加黑名单 - 类型: {blacklist_type}",
        )

        # 发送确认消息
        type_names = {
            "link": "链接",
            "sticker": "贴纸",
            "gif": "GIF",
            "bot": "内联Bot",
            "text": "文字消息",
        }

        type_name = type_names.get(blacklist_type, blacklist_type)

        confirm_text = (
            f"✅ <b>黑名单添加成功</b>\n\n"
            f"<b>类型:</b> {type_name}\n"
            f"<b>内容:</b> {content[:50]}{'...' if len(content) > 50 else ''}\n\n"
            f"<b>添加结果:</b>\n"
        )

        if Config.PRIVATE_FORWARD_CONFIG["auto_add_to_contributing_groups"]:
            confirm_text += f"• 群组黑名单: {success_count} 个群组成功\n"

        if Config.PRIVATE_FORWARD_CONFIG["auto_add_to_global"]:
            confirm_text += f"• 通用黑名单: {'✅ 成功' if global_success else '❌ 失败'}\n"

        confirm_text += f"\n<b>说明:</b>\n"

        if Config.PRIVATE_FORWARD_CONFIG["auto_add_to_contributing_groups"]:
            confirm_text += f"此内容已添加到所有启用了通用黑名单贡献的群组中。\n"

        if Config.PRIVATE_FORWARD_CONFIG["auto_add_to_global"]:
            confirm_text += f"此内容已添加到通用黑名单中。"

        await context.bot.send_message(
            chat_id=message.chat.id, text=confirm_text, parse_mode=ParseMode.HTML
        )

        # 记录到频道
        if Config.BLACKLIST_CONFIG["log_actions"]:
            await self._log_to_channel(
                context,
                None,
                message.from_user,
                "private_forward_blacklist",
                content,
                f"私聊转发添加黑名单 - 类型: {blacklist_type}",
            )

        logger.info(
            f"私聊转发添加黑名单成功 - 用户: {message.from_user.username}, 类型: {blacklist_type}, 内容: {content}"
        )

    async def _is_admin_or_creator(self, message: Message) -> bool:
        """检查用户是否为管理员或群主"""
        try:
            chat_member = await message.chat.get_member(message.from_user.id)
            return chat_member.status in ["administrator", "creator"]
        except Exception as e:
            logger.error(f"检查用户权限失败: {e}", exc_info=True)
            return False

    async def _send_success_message(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, text: str
    ):
        """发送成功消息"""
        try:
            sent_message = await context.bot.send_message(
                chat_id=message.chat.id, text=f"✅ {text}", reply_to_message_id=message.message_id
            )
            return sent_message

        except Exception as e:
            # 如果回复失败，尝试发送普通消息
            logger.warning(f"回复消息失败，发送普通消息: {e}")
            try:
                sent_message = await context.bot.send_message(
                    chat_id=message.chat.id, text=f"✅ {text}"
                )
                return sent_message

            except Exception as e2:
                logger.error(f"发送普通消息也失败: {e2}", exc_info=True)
                return None

    async def _send_error_message(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, text: str
    ):
        """发送错误消息"""
        try:
            await context.bot.send_message(
                chat_id=message.chat.id, text=f"❌ {text}", reply_to_message_id=message.message_id
            )
        except Exception as e:
            # 如果回复失败，尝试发送普通消息
            logger.warning(f"回复消息失败，发送普通消息: {e}")
            await context.bot.send_message(chat_id=message.chat.id, text=f"❌ {text}")

    async def _auto_delete_messages(self, messages: list, delay: int = None):
        """延迟后自动删除消息

        Args:
            messages: 要删除的消息列表
            delay: 延迟时间(秒)，默认使用配置中的值
        """
        import asyncio

        if delay is None:
            delay = Config.BLACKLIST_CONFIG["auto_delete_confirmation_delay"]

        await asyncio.sleep(delay)

        for msg in messages:
            if msg is None:
                continue
            try:
                await msg.delete()
                logger.info(f"已自动删除消息: {msg.message_id}")
            except Exception as e:
                logger.error(f"自动删除消息失败: {e}", exc_info=True)

    async def _log_to_channel(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat: Chat,
        user: User,
        action_type: str,
        content: str,
        reason: str,
    ):
        """记录操作到群组指定的频道"""
        try:
            from datetime import datetime

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
                f"<b>来源群组</b>: {chat_info} (<code>{source_chat_id}</code>)\n"
                f"<b>用户</b>: {user.mention_html()} (<code>{user.id}</code>)\n"
                f"<b>操作</b>: {action_type}\n"
                f"<b>内容</b>: {content}\n"
                f"<b>原因</b>: {reason}\n"
                f"<b>时间</b>: {current_time}"
            )

            await context.bot.send_message(
                chat_id=log_channel_id, text=log_text, parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"记录到频道失败: {e}", exc_info=True)

    async def _is_bot_admin(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """检查用户是否为Bot的管理员（通过检查是否在Bot的群组中）"""
        try:
            # 检查是否启用了私聊转发功能
            if not Config.PRIVATE_FORWARD_CONFIG["enabled"]:
                return False

            # 检查用户是否在管理员列表中
            admin_user_ids = Config.PRIVATE_FORWARD_CONFIG["admin_user_ids"]

            # 安全检查：如果未配置管理员列表，拒绝所有请求
            if not admin_user_ids:
                logger.error(
                    f"安全警告：ADMIN_USER_IDS 未配置，拒绝用户 {user_id} 的私聊转发请求。"
                    f"请在环境变量中设置 ADMIN_USER_IDS。"
                )
                return False

            # 检查用户是否在白名单中
            if user_id in admin_user_ids:
                return True

            return False

        except Exception as e:
            logger.error(f"检查Bot管理员权限失败: {e}", exc_info=True)
            return False

    async def _send_private_error_message(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, text: str
    ):
        """发送私聊错误消息"""
        try:
            await context.bot.send_message(
                chat_id=message.chat.id, text=f"❌ {text}", parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"发送私聊错误消息失败: {e}", exc_info=True)

    async def _show_log_channel_status(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """显示记录频道状态"""
        try:
            current_channel = self.db.get_group_log_channel(message.chat.id)

            if current_channel:
                status_text = (
                    f"📋 <b>记录频道设置</b>\n\n"
                    f"<b>当前记录频道:</b> <code>{current_channel}</code>\n"
                    f"<b>状态:</b> ✅ 已设置\n\n"
                    f"<b>说明:</b>\n"
                    f"• 所有操作记录将发送到此频道\n"
                    f"• 记录包含来源群组信息\n"
                    f"• 不同群组可以使用相同的记录频道\n\n"
                    f"<b>命令:</b>\n"
                    f"• /log_channel clear - 清除记录频道\n"
                    f"• /log_channel &lt;频道ID&gt; - 设置记录频道"
                )
            else:
                status_text = (
                    f"📋 <b>记录频道设置</b>\n\n"
                    f"<b>当前记录频道:</b> 未设置\n"
                    f"<b>状态:</b> ❌ 未设置\n\n"
                    f"<b>说明:</b>\n"
                    f"• 未设置记录频道时，操作不会记录到频道\n"
                    f"• 记录包含来源群组信息\n"
                    f"• 不同群组可以使用相同的记录频道\n\n"
                    f"<b>命令:</b>\n"
                    f"• /log_channel &lt;频道ID&gt; - 设置记录频道"
                )

            await context.bot.send_message(
                chat_id=message.chat.id, text=status_text, parse_mode=ParseMode.HTML
            )

        except Exception as e:
            logger.error(f"显示记录频道状态失败: {e}", exc_info=True)
            await self._send_error_message(message, context, "获取记录频道状态失败")

    async def _set_log_channel(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, channel_id_str: str
    ):
        """设置记录频道"""
        try:
            # 解析频道ID
            try:
                channel_id = int(channel_id_str)
                # Telegram频道ID通常是负数（-100开头的13位数字）
                # 群组ID是负数，频道ID也是负数
                if channel_id >= 0:
                    await self._send_error_message(
                        message, context, "频道ID应该是负数（例如：-1001234567890）"
                    )
                    return
                # 合理的范围检查
                if channel_id < -10**15 or channel_id > -1:
                    await self._send_error_message(message, context, "频道ID超出有效范围")
                    return
            except ValueError:
                await self._send_error_message(message, context, "无效的频道ID格式，请输入数字")
                return

            # 验证频道是否存在且Bot有权限
            try:
                chat = await context.bot.get_chat(channel_id)
                if chat.type != "channel":
                    await self._send_error_message(
                        message, context, "指定的ID不是频道，请提供正确的频道ID"
                    )
                    return

                # 检查Bot是否有发送消息的权限
                bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
                if bot_member.status not in ["administrator", "creator"]:
                    await self._send_error_message(
                        message, context, "Bot需要是频道的管理员才能发送消息"
                    )
                    return

            except Exception as e:
                logger.error(f"验证频道失败: {e}", exc_info=True)
                await self._send_error_message(
                    message, context, "无法访问指定的频道，请检查频道ID和Bot权限"
                )
                return

            # 设置记录频道
            success = self.db.set_group_log_channel(message.chat.id, channel_id)

            if success:
                # 发送测试消息
                try:
                    from datetime import datetime

                    test_message = await context.bot.send_message(
                        chat_id=channel_id,
                        text=f"✅ 记录频道设置成功\n\n群组: {message.chat.title}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    )

                    # 5秒后删除测试消息
                    import asyncio

                    await asyncio.sleep(5)
                    await test_message.delete()

                except Exception as e:
                    logger.error(f"发送测试消息失败: {e}", exc_info=True)

                await self._send_success_message(
                    message, context, f"记录频道设置成功\n频道: {chat.title}\n频道ID: {channel_id}"
                )

                logger.info(f"群组 {message.chat.id} 设置记录频道: {channel_id}")
            else:
                await self._send_error_message(message, context, "设置记录频道失败")

        except Exception as e:
            logger.error(f"设置记录频道失败: {e}", exc_info=True)
            await self._send_error_message(message, context, "设置记录频道失败")

    async def _clear_log_channel(self, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """清除记录频道设置"""
        try:
            success = self.db.set_group_log_channel(message.chat.id, None)

            if success:
                await self._send_success_message(message, context, "记录频道设置已清除")
                logger.info(f"群组 {message.chat.id} 清除记录频道设置")
            else:
                await self._send_error_message(message, context, "清除记录频道设置失败")

        except Exception as e:
            logger.error(f"清除记录频道设置失败: {e}", exc_info=True)
            await self._send_error_message(message, context, "清除记录频道设置失败")

    def _cleanup_completed_tasks(self):
        """清理已完成的后台任务（不等待）

        在正常运行时调用，移除已完成的任务以防止内存泄漏
        """
        if not self.background_tasks:
            return

        initial_count = len(self.background_tasks)
        self.background_tasks = [task for task in self.background_tasks if not task.done()]
        cleaned_count = initial_count - len(self.background_tasks)

        if cleaned_count > 0:
            logger.debug(f"清理了 {cleaned_count} 个已完成的后台任务，剩余 {len(self.background_tasks)} 个")

    async def cleanup_background_tasks(self):
        """等待所有后台任务完成

        在Bot停止时调用，确保所有后台任务（如延迟删除消息）完成执行
        """
        if not self.background_tasks:
            logger.debug("没有待处理的后台任务")
            return

        logger.info(f"等待 {len(self.background_tasks)} 个后台任务完成...")

        # 清理已完成的任务
        self.background_tasks = [task for task in self.background_tasks if not task.done()]

        if self.background_tasks:
            # 等待所有未完成的任务，最多等待10秒
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.background_tasks, return_exceptions=True),
                    timeout=10.0
                )
                logger.info("所有后台任务已完成")
            except asyncio.TimeoutError:
                logger.warning(f"部分后台任务未在超时时间内完成，取消 {len(self.background_tasks)} 个任务")
                for task in self.background_tasks:
                    if not task.done():
                        task.cancel()
            except Exception as e:
                logger.error(f"等待后台任务完成时出错: {e}", exc_info=True)
            finally:
                self.background_tasks.clear()
