"""Cloudflare clef-flash 入群资料与首条消息广告检测。"""

from __future__ import annotations

from html import escape
from typing import Optional

from telegram import Chat, ChatMember, ChatMemberUpdated, Message, Update, User
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import ContextTypes

from config import Config
from database.models import DatabaseManager
from services.clef_client import ClefClient, ClefScore, clef_client
from utils.logger import logger

# 视为「新加入」的目标状态
_JOIN_NEW_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.RESTRICTED,
}
# 加入前的旧状态
_JOIN_OLD_STATUSES = {
    ChatMemberStatus.LEFT,
    ChatMemberStatus.BANNED,
}


def display_name(user: User) -> str:
    """拼接 first_name + last_name。"""
    parts = [p for p in (user.first_name, user.last_name) if p]
    return " ".join(parts).strip() or (user.username or str(user.id))


def build_join_state(nickname: str, bio: str) -> str:
    """入群评分 state。"""
    return "Telegram 入群资料：\n" f"昵称：{nickname or '（空）'}\n" f"简介：{bio or '（空）'}"


def build_message_state(nickname: str, bio: str, message_text: str) -> str:
    """首条消息评分 state。"""
    return (
        "Telegram 用户资料与消息：\n"
        f"昵称：{nickname or '（空）'}\n"
        f"简介：{bio or '（空）'}\n"
        f"消息：{message_text or '（空）'}"
    )


def is_join_transition(old_status: str, new_status: str) -> bool:
    """判断 ChatMember 更新是否为入群。"""
    return old_status in _JOIN_OLD_STATUSES and new_status in _JOIN_NEW_STATUSES


class ClefHandler:
    """clef-flash 入群 / 首条消息检测处理器。"""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        client: Optional[ClefClient] = None,
    ):
        self.db = db if db is not None else DatabaseManager()
        self.client = client if client is not None else clef_client

    @property
    def enabled(self) -> bool:
        return bool(Config.CLEF_ENABLED and self.client.is_configured())

    async def handle_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 chat_member 入群事件。"""
        if not self.enabled:
            return

        result = update.chat_member
        if not isinstance(result, ChatMemberUpdated):
            return

        old_status = result.old_chat_member.status
        new_status = result.new_chat_member.status
        if not is_join_transition(old_status, new_status):
            return

        user = result.new_chat_member.user
        chat = result.chat
        if not user or not chat:
            return

        if getattr(chat, "type", None) not in ("group", "supergroup"):
            return

        if user.is_bot:
            logger.debug(f"clef: 跳过机器人入群 user_id={user.id}")
            return

        # 跳过管理员/群主（防御性；通常不会从 left→administrator 走此分支）
        if new_status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return
        if await self._is_admin(chat.id, user.id, context):
            logger.debug(f"clef: 跳过管理员入群 user_id={user.id}")
            return

        # 必须先于 join_scored：命中封禁会写下该标记，Telegram 侧解封后再入群仍要踢
        if self.db.check_blacklist(chat.id, "user", str(user.id)):
            await self._ban_listed_user(context, chat.id, user.id)
            return

        if self.db.has_clef_join_scored(chat.id, user.id):
            logger.debug(f"clef: 入群已评过分 chat={chat.id} user={user.id}")
            return

        nickname = display_name(user)
        bio = await self._fetch_bio(user.id, context)
        state = build_join_state(nickname, bio)

        score = await self.client.score_profile(state)
        if score is None:
            return

        logger.info(
            f"[CLEF_JOIN] chat={chat.id} user={user.id} "
            f"is_ad={score.is_ad:.4f} risk={score.risk_score:.4f} nick={nickname!r}"
        )

        if not score.should_auto_kick():
            self.db.mark_clef_join_scored(chat.id, user.id)
            return

        # 尝试删除入群服务消息（chat_member 更新通常没有 message）
        service_message = update.effective_message
        if service_message is not None:
            try:
                await service_message.delete()
            except Exception as e:
                logger.debug(f"clef: 删除入群服务消息失败: {e}")

        if await self._ban_user(
            context=context,
            chat=chat,
            user=user,
            score=score,
            content=f"昵称={nickname}; 简介={(bio or '')[:80]}",
            reason=(
                f"clef-flash 入群检测命中 "
                f"(is_ad={score.is_ad:.3f}, risk={score.risk_score:.2f})"
            ),
            action_type="clef_join_ban",
        ):
            self._mark_both_scored(chat.id, user.id)

    async def check_first_message(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """检查群组首条文本/说明消息。

        Returns:
            True 表示已处理（命中并封禁），调用方应停止后续逻辑。
        """
        if not self.enabled:
            return False

        if not message or not message.from_user or not message.chat:
            return False

        user = message.from_user
        chat = message.chat

        if user.is_bot:
            return False

        # 仅文本或带 caption 的消息
        text = message.text or message.caption
        if not text or not str(text).strip():
            return False

        if await self._is_admin(chat.id, user.id, context):
            return False

        if self.db.has_clef_message_scored(chat.id, user.id):
            return False

        nickname = display_name(user)
        bio = await self._fetch_bio(user.id, context)
        state = build_message_state(nickname, bio, text.strip())

        score = await self.client.score_profile(state)
        if score is None:
            return False

        logger.info(
            f"[CLEF_MSG] chat={chat.id} user={user.id} "
            f"is_ad={score.is_ad:.4f} risk={score.risk_score:.4f}"
        )

        if not score.should_auto_kick():
            self.db.mark_clef_message_scored(chat.id, user.id)
            return False

        # 删除消息并封禁
        try:
            await message.delete()
            logger.info(f"clef: 已删除首条广告消息 message_id={message.message_id}")
        except Exception as e:
            logger.error(f"clef: 删除消息失败: {e}", exc_info=True)

        banned = await self._ban_user(
            context=context,
            chat=chat,
            user=user,
            score=score,
            content=text[:200],
            reason=(
                f"clef-flash 首条消息检测命中 "
                f"(is_ad={score.is_ad:.3f}, risk={score.risk_score:.2f})"
            ),
            action_type="clef_message_ban",
        )
        if banned:
            self._mark_both_scored(chat.id, user.id)
        return banned

    def _mark_both_scored(self, chat_id: int, user_id: int) -> None:
        """封禁已经做出，两条路径都不再打分，否则 /unban 后会被另一条路径立刻打回。"""
        self.db.mark_clef_join_scored(chat_id, user_id)
        self.db.mark_clef_message_scored(chat_id, user_id)

    async def _ban_listed_user(
        self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int
    ) -> None:
        """已在本群 user 黑名单的人再次入群时直接封禁，不再调用 clef。"""
        try:
            until = (
                Config.BLACKLIST_CONFIG["ban_duration"]
                if Config.BLACKLIST_CONFIG.get("ban_duration", 0) > 0
                else None
            )
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id, until_date=until)
        except Exception as e:
            logger.error(f"clef: 黑名单用户入群封禁失败 user={user_id}: {e}")

    async def _ban_user(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat: Chat,
        user: User,
        score: ClefScore,
        content: str,
        reason: str,
        action_type: str,
    ) -> bool:
        """封禁用户并写入本群 user 黑名单。封禁成功返回 True。

        用户 ID 只进当前群。通用黑名单没有逐条删除，写进去后其他群无法撤销误伤。
        """
        user_content = str(user.id)

        try:
            added = self.db.add_to_blacklist(
                chat_id=chat.id,
                blacklist_type="user",
                content=user_content,
                created_by=context.bot.id,
            )
            if added:
                logger.info(
                    f"[CLEF_BLACKLIST] 已加入群组黑名单 type=user "
                    f"chat={chat.id} user={user.id} is_ad={score.is_ad:.4f}"
                )
            else:
                logger.error(f"clef: 写入群组黑名单失败 user={user.id}")
        except Exception as e:
            logger.error(f"clef: 写入群组黑名单失败 user={user.id}: {e}", exc_info=True)

        try:
            until = (
                Config.BLACKLIST_CONFIG["ban_duration"]
                if Config.BLACKLIST_CONFIG.get("ban_duration", 0) > 0
                else None
            )
            await context.bot.ban_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                until_date=until,
            )
        except Exception as e:
            logger.error(f"clef: 封禁用户失败 user={user.id}: {e}", exc_info=True)
            return False

        self.db.add_ban_record(
            chat_id=chat.id,
            user_id=user.id,
            reason=reason,
            banned_by=context.bot.id,
        )
        self.db.add_action_log(
            chat_id=chat.id,
            action_type=action_type,
            user_id=user.id,
            target_content=content,
            reason=reason,
        )
        logger.info(
            f"[CLEF_BAN] action={action_type} chat={chat.id} user={user.id} "
            f"is_ad={score.is_ad:.4f} risk={score.risk_score:.4f}"
        )
        if Config.BLACKLIST_CONFIG.get("log_actions"):
            await self._log_to_channel(context, chat, user, action_type, content, reason)
        return True

    async def _log_to_channel(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat: Chat,
        user: User,
        action_type: str,
        content: str,
        reason: str,
    ) -> None:
        """写到群组配置的日志频道（与黑名单处理器风格一致）。"""
        try:
            from datetime import datetime

            log_channel_id = self.db.get_group_log_channel(chat.id)
            if not log_channel_id:
                return

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_text = (
                f"🔔 <b>操作记录</b>\n\n"
                f"<b>来源群组</b>: {escape(chat.title or '')} (<code>{chat.id}</code>)\n"
                f"<b>用户</b>: {user.mention_html()} (<code>{user.id}</code>)\n"
                f"<b>操作</b>: {escape(action_type)}\n"
                f"<b>内容</b>: {escape(content)}\n"
                f"<b>原因</b>: {escape(reason)}\n"
                f"<b>时间</b>: {current_time}"
            )
            await context.bot.send_message(
                chat_id=log_channel_id, text=log_text, parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"clef: 记录到频道失败: {e}", exc_info=True)

    async def _fetch_bio(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
        """尝试通过 get_chat 拉取用户简介；失败则空串。"""
        try:
            chat = await context.bot.get_chat(user_id)
            bio = getattr(chat, "bio", None) or ""
            return str(bio).strip()
        except Exception as e:
            logger.debug(f"clef: 无法获取用户简介 user={user_id}: {e}")
            return ""

    async def _is_admin(
        self, chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """检查是否为群管理员/群主。"""
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            return member.status in (
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
                "administrator",
                "creator",
            )
        except Exception as e:
            logger.debug(f"clef: 检查管理员失败: {e}")
            return False
