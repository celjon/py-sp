# src/adapter/gateway/telegram_chat_gateway.py
"""
Gateway для работы с Telegram Chat API
Автоматическое определение владельца группы и администраторов
"""

import logging
from typing import Dict, Any, Optional, List
from aiogram import Bot
from aiogram.types import ChatMember, ChatMemberOwner, ChatMemberAdministrator, ChatMemberMember

logger = logging.getLogger(__name__)


class TelegramChatGateway:
    """Gateway для работы с Telegram Chat API"""

    def __init__(self, bot: Bot):
        self.bot = bot
        logger.info("📱 Telegram Chat Gateway инициализирован")

    async def get_chat_info(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получает информацию о чате"""
        try:
            chat = await self.bot.get_chat(chat_id)
            return {
                "id": chat.id,
                "type": chat.type,
                "title": chat.title,
                "username": chat.username,
                "description": chat.description,
            }
        except Exception as e:
            logger.error(f"Error getting chat info for {chat_id}: {e}")
            return None

    async def get_chat_administrators(self, chat_id: int) -> List[Dict[str, Any]]:
        """Получает список администраторов чата"""
        try:
            administrators = await self.bot.get_chat_administrators(chat_id)
            result = []
            
            for admin in administrators:
                admin_info = {
                    "user_id": admin.user.id,
                    "username": admin.user.username,
                    "first_name": admin.user.first_name,
                    "last_name": admin.user.last_name,
                    "status": admin.status,
                    "can_be_edited": getattr(admin, 'can_be_edited', False),
                    "can_manage_chat": getattr(admin, 'can_manage_chat', False),
                    "can_delete_messages": getattr(admin, 'can_delete_messages', False),
                    "can_manage_video_chats": getattr(admin, 'can_manage_video_chats', False),
                    "can_restrict_members": getattr(admin, 'can_restrict_members', False),
                    "can_promote_members": getattr(admin, 'can_promote_members', False),
                    "can_change_info": getattr(admin, 'can_change_info', False),
                    "can_invite_users": getattr(admin, 'can_invite_users', False),
                    "can_post_messages": getattr(admin, 'can_post_messages', False),
                    "can_edit_messages": getattr(admin, 'can_edit_messages', False),
                    "can_pin_messages": getattr(admin, 'can_pin_messages', False),
                }
                result.append(admin_info)
            
            logger.info(f"Found {len(result)} administrators in chat {chat_id}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting chat administrators for {chat_id}: {e}")
            return []

    async def get_chat_member(self, chat_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Получает информацию о конкретном участнике чата"""
        try:
            member = await self.bot.get_chat_member(chat_id, user_id)
            return {
                "user_id": member.user.id,
                "username": member.user.username,
                "first_name": member.user.first_name,
                "last_name": member.user.last_name,
                "status": member.status,
                "can_be_edited": getattr(member, 'can_be_edited', False),
                "can_manage_chat": getattr(member, 'can_manage_chat', False),
                "can_delete_messages": getattr(member, 'can_delete_messages', False),
                "can_manage_video_chats": getattr(member, 'can_manage_video_chats', False),
                "can_restrict_members": getattr(member, 'can_restrict_members', False),
                "can_promote_members": getattr(member, 'can_promote_members', False),
                "can_change_info": getattr(member, 'can_change_info', False),
                "can_invite_users": getattr(member, 'can_invite_users', False),
                "can_post_messages": getattr(member, 'can_post_messages', False),
                "can_edit_messages": getattr(member, 'can_edit_messages', False),
                "can_pin_messages": getattr(member, 'can_pin_messages', False),
            }
        except Exception as e:
            logger.error(f"Error getting chat member {user_id} from chat {chat_id}: {e}")
            return None

    async def get_chat_owner(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получает владельца чата (creator)"""
        try:
            administrators = await self.get_chat_administrators(chat_id)
            
            # Ищем владельца (статус 'creator')
            for admin in administrators:
                if admin["status"] == "creator":
                    logger.info(f"Found chat owner: {admin['user_id']} in chat {chat_id}")
                    return admin
            
            logger.warning(f"No owner found in chat {chat_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting chat owner for {chat_id}: {e}")
            return None

    async def is_user_admin(self, chat_id: int, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором чата"""
        try:
            member = await self.get_chat_member(chat_id, user_id)
            if not member:
                return False
            
            return member["status"] in ["creator", "administrator"]
            
        except Exception as e:
            logger.error(f"Error checking admin status for user {user_id} in chat {chat_id}: {e}")
            return False

    async def is_user_owner(self, chat_id: int, user_id: int) -> bool:
        """Проверяет, является ли пользователь владельцем чата"""
        try:
            member = await self.get_chat_member(chat_id, user_id)
            if not member:
                return False
            
            return member["status"] == "creator"
            
        except Exception as e:
            logger.error(f"Error checking owner status for user {user_id} in chat {chat_id}: {e}")
            return False

    async def can_bot_manage_chat(self, chat_id: int) -> bool:
        """Проверяет, может ли бот управлять чатом"""
        try:
            bot_member = await self.get_chat_member(chat_id, self.bot.id)
            if not bot_member:
                return False
            
            # Бот должен быть администратором с правами на удаление сообщений
            return (
                bot_member["status"] in ["creator", "administrator"] and
                bot_member["can_delete_messages"]
            )
            
        except Exception as e:
            logger.error(f"Error checking bot permissions in chat {chat_id}: {e}")
            return False

    async def get_bot_permissions(self, chat_id: int) -> Dict[str, bool]:
        """Получает права бота в чате"""
        try:
            bot_member = await self.get_chat_member(chat_id, self.bot.id)
            if not bot_member:
                return {}
            
            return {
                "can_manage_chat": bot_member.get("can_manage_chat", False),
                "can_delete_messages": bot_member.get("can_delete_messages", False),
                "can_manage_video_chats": bot_member.get("can_manage_video_chats", False),
                "can_restrict_members": bot_member.get("can_restrict_members", False),
                "can_promote_members": bot_member.get("can_promote_members", False),
                "can_change_info": bot_member.get("can_change_info", False),
                "can_invite_users": bot_member.get("can_invite_users", False),
                "can_post_messages": bot_member.get("can_post_messages", False),
                "can_edit_messages": bot_member.get("can_edit_messages", False),
                "can_pin_messages": bot_member.get("can_pin_messages", False),
            }
            
        except Exception as e:
            logger.error(f"Error getting bot permissions in chat {chat_id}: {e}")
            return {}

    async def get_chat_member_count(self, chat_id: int) -> Optional[int]:
        """Получает количество участников чата"""
        try:
            member_count = await self.bot.get_chat_member_count(chat_id)
            return member_count
        except Exception as e:
            logger.error(f"Error getting member count for chat {chat_id}: {e}")
            return None

    async def leave_chat(self, chat_id: int) -> bool:
        """Покидает чат"""
        try:
            await self.bot.leave_chat(chat_id)
            logger.info(f"Bot left chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Error leaving chat {chat_id}: {e}")
            return False
