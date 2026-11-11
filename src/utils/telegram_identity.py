"""区分普通用户和 Telegram 代发身份。

关联讨论群里的频道自动转发、以频道身份发送的消息、匿名管理员，
Bot API 都会给一个伪造的 ``from``。这个 ``from`` 不是发帖的人，而且
在所有同类消息之间共用：

- ``777000``：Telegram 服务账号。频道帖自动转发到关联讨论群时都是它。
- ``1087968824``：GroupAnonymousBot。管理员匿名发言时都是它。
- ``136817688``：Channel_Bot。以频道身份发到群里时可能是它。

把其中任何一个写入或命中 ``user`` 黑名单，一条消息的判定会连带之后
所有频道或所有匿名管理员。``sender_chat`` / ``is_automatic_forward``
才是「这是某个聊天在发言」的信号；``forward_origin`` 只表示用户手动
转发，发送者仍是 ``from``。

已经写进库里的服务身份记录不在这里删除。读路径直接忽略，避免历史
误判继续命中；清库由运维手动处理。
"""

from typing import Optional

from telegram import Message, User
from telegram.constants import ChatID

# 与 python-telegram-bot 的 ChatID 一致：这些 from 只是兼容字段，不是群成员。
TELEGRAM_SERVICE_USER_ID = int(ChatID.SERVICE_CHAT)
GROUP_ANONYMOUS_BOT_ID = int(ChatID.ANONYMOUS_ADMIN)
CHANNEL_BOT_USER_ID = int(ChatID.FAKE_CHANNEL)

SERVICE_USER_IDS = frozenset(
    {
        TELEGRAM_SERVICE_USER_ID,
        GROUP_ANONYMOUS_BOT_ID,
        CHANNEL_BOT_USER_ID,
    }
)


def is_service_user_id(user_id: object) -> bool:
    """是否为不能当作普通用户拉黑的 Telegram 服务身份。"""
    return (
        isinstance(user_id, int) and not isinstance(user_id, bool) and user_id in SERVICE_USER_IDS
    )


def is_service_user_blacklist(blacklist_type: str, content: object) -> bool:
    """``user`` 黑名单内容是否指向服务身份。其他类型不受影响。"""
    if blacklist_type != "user" or isinstance(content, bool):
        return False
    if isinstance(content, int):
        return is_service_user_id(content)
    if not isinstance(content, str):
        return False
    text = content.strip()
    if not text.isdigit():
        return False
    return is_service_user_id(int(text))


def sent_on_behalf_of_chat(message: Message) -> bool:
    """消息是频道、匿名管理员或关联群自动转发，而不是某个用户本人。"""
    if getattr(message, "is_automatic_forward", None) is True:
        return True
    sender = getattr(message, "sender_chat", None)
    if sender is None:
        return False
    return isinstance(getattr(sender, "id", None), int) and not isinstance(
        getattr(sender, "id", None), bool
    )


def ordinary_user(message: Optional[Message]) -> Optional[User]:
    """返回可以写入或命中 user 黑名单的普通用户。

    没有可追责的个人时返回 None。手动转发（只有 forward_origin）仍算
    转发的那个人。
    """
    if message is None:
        return None
    user = message.from_user
    if user is None:
        return None
    if is_service_user_id(user.id) or sent_on_behalf_of_chat(message):
        return None
    return user
