from typing import Optional
import aiogram
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


class TelegramGateway:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def ban_user(self, chat_id: int, user_id: int, delete_messages: bool = True) -> bool:
        """Забанить пользователя в чате"""
        try:
            await self.bot.ban_chat_member(
                chat_id=chat_id, user_id=user_id, revoke_messages=delete_messages
            )
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            print(f"Failed to ban user {user_id} in chat {chat_id}: {e}")
            return False

    async def restrict_user(self, chat_id: int, user_id: int) -> bool:
        """Ограничить пользователя (mute)"""
        try:
            await self.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=aiogram.types.ChatPermissions(
                    can_send_messages=False,
                    can_send_audios=False,
                    can_send_documents=False,
                    can_send_photos=False,
                    can_send_videos=False,
                    can_send_video_notes=False,
                    can_send_voice_notes=False,
                ),
            )
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            print(f"Failed to restrict user {user_id} in chat {chat_id}: {e}")
            return False

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        """Удалить сообщение"""
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            print(f"Failed to delete message {message_id} in chat {chat_id}: {e}")
            return False

    async def send_message(self, chat_id: int, text: str, reply_to: Optional[int] = None) -> bool:
        """Отправить сообщение"""
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, reply_to_message_id=reply_to)
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            print(f"Failed to send message to chat {chat_id}: {e}")
            return False
