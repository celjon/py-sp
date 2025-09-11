from typing import List, Optional, Dict, Any
import asyncpg
from datetime import datetime, timedelta, timezone
from ...domain.entity.message import Message, MessageRole
from ...lib.clients.postgres_client import PostgresClient

class MessageRepository:
    def __init__(self, db_client: PostgresClient):
        self.db = db_client

    async def save_message(self, message: Message) -> Message:
        """Сохранить сообщение в базе данных"""
        query = """
        INSERT INTO messages (user_id, chat_id, text, role, is_spam, spam_confidence, 
                             has_links, has_mentions, has_images, is_forward, emoji_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING id, created_at
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                message.user_id,
                message.chat_id, 
                message.text,
                message.role.value,
                message.is_spam,
                message.spam_confidence,
                message.has_links,
                message.has_mentions,
                message.has_images,
                message.is_forward,
                message.emoji_count
            )
            
            message.id = row['id']
            message.created_at = row['created_at']
            return message

    async def get_user_message_count(self, user_id: int, chat_id: int) -> int:
        """Получить количество сообщений пользователя в чате"""
        query = "SELECT COUNT(*) FROM messages WHERE user_id = $1 AND chat_id = $2"
        
        async with self.db.acquire() as conn:
            return await conn.fetchval(query, user_id, chat_id)

    async def get_recent_messages(self, user_id: int, chat_id: int, limit: int = 10) -> List[Message]:
        """Получить последние сообщения пользователя"""
        query = """
        SELECT * FROM messages 
        WHERE user_id = $1 AND chat_id = $2 
        ORDER BY created_at DESC 
        LIMIT $3
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, user_id, chat_id, limit)
            return [self._row_to_message(row) for row in rows]

    async def get_user_recent_messages(self, user_id: int, chat_id: int, hours: int = 24) -> List[Message]:
        """Получить сообщения пользователя за последние N часов"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = """
        SELECT * FROM messages 
        WHERE user_id = $1 AND chat_id = $2 AND created_at > $3
        ORDER BY created_at DESC
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, user_id, chat_id, since)
            return [self._row_to_message(row) for row in rows]

    async def mark_messages_deleted(self, message_ids: List[int]) -> None:
        """Отметить сообщения как удаленные"""
        if not message_ids:
            return
            
        query = "UPDATE messages SET deleted_at = NOW() WHERE id = ANY($1)"
        
        async with self.db.acquire() as conn:
            await conn.execute(query, message_ids)

    async def get_chat_stats(self, chat_id: int, hours: int = 24) -> Dict[str, Any]:
        """Получить статистику чата за указанный период"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Основная статистика сообщений
        messages_query = """
        SELECT 
            COUNT(*) as total_messages,
            COUNT(*) FILTER (WHERE is_spam = true) as spam_messages,
            COUNT(*) FILTER (WHERE is_spam = false) as clean_messages,
            COUNT(*) FILTER (WHERE deleted_at IS NOT NULL) as deleted_messages,
            COUNT(DISTINCT user_id) as active_users,
            AVG(spam_confidence) FILTER (WHERE spam_confidence IS NOT NULL) as avg_spam_confidence,
            MAX(created_at) as last_message_time
        FROM messages 
        WHERE chat_id = $1 AND created_at > $2
        """
        
        # Статистика по пользователям
        users_query = """
        SELECT 
            COUNT(DISTINCT user_id) FILTER (WHERE is_spam = true) as spam_users,
            COUNT(DISTINCT user_id) FILTER (WHERE is_spam = false) as clean_users
        FROM messages 
        WHERE chat_id = $1 AND created_at > $2
        """
        
        # Топ спам пользователей
        top_spammers_query = """
        SELECT 
            user_id,
            COUNT(*) as spam_count,
            AVG(spam_confidence) as avg_confidence
        FROM messages 
        WHERE chat_id = $1 AND created_at > $2 AND is_spam = true
        GROUP BY user_id
        ORDER BY spam_count DESC, avg_confidence DESC
        LIMIT 5
        """
        
        # Статистика по времени (по часам)
        hourly_stats_query = """
        SELECT 
            DATE_TRUNC('hour', created_at) as hour,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE is_spam = true) as spam
        FROM messages 
        WHERE chat_id = $1 AND created_at > $2
        GROUP BY DATE_TRUNC('hour', created_at)
        ORDER BY hour DESC
        LIMIT 24
        """
        
        async with self.db.acquire() as conn:
            # Выполняем все запросы
            messages_stats = await conn.fetchrow(messages_query, chat_id, since)
            users_stats = await conn.fetchrow(users_query, chat_id, since)
            top_spammers = await conn.fetch(top_spammers_query, chat_id, since)
            hourly_stats = await conn.fetch(hourly_stats_query, chat_id, since)
            
            # Обрабатываем результаты
            total_messages = messages_stats['total_messages'] or 0
            spam_messages = messages_stats['spam_messages'] or 0
            clean_messages = messages_stats['clean_messages'] or 0
            
            spam_percentage = (spam_messages / total_messages * 100) if total_messages > 0 else 0
            
            # Формируем ответ
            stats = {
                # Основные метрики
                'total_messages': total_messages,
                'spam_messages': spam_messages,
                'clean_messages': clean_messages,
                'deleted_messages': messages_stats['deleted_messages'] or 0,
                'spam_percentage': round(spam_percentage, 2),
                
                # Пользователи
                'active_users': messages_stats['active_users'] or 0,
                'spam_users': users_stats['spam_users'] or 0,
                'clean_users': users_stats['clean_users'] or 0,
                'banned_users': users_stats['spam_users'] or 0,  # Упрощение для совместимости
                
                # Качественные метрики
                'avg_spam_confidence': round(float(messages_stats['avg_spam_confidence'] or 0), 3),
                'last_message_time': messages_stats['last_message_time'],
                
                # Детализация
                'top_spammers': [
                    {
                        'user_id': row['user_id'],
                        'spam_count': row['spam_count'],
                        'avg_confidence': round(float(row['avg_confidence']), 3)
                    }
                    for row in top_spammers
                ],
                
                'hourly_distribution': [
                    {
                        'hour': row['hour'].isoformat() if row['hour'] else None,
                        'total': row['total'],
                        'spam': row['spam'],
                        'spam_rate': round((row['spam'] / row['total']) if row['total'] > 0 else 0.0, 3),
                        'spam_percentage': round((row['spam'] / row['total'] * 100) if row['total'] > 0 else 0, 1)
                    }
                    for row in hourly_stats
                ],
                
                # Метаданные
                'period_hours': hours,
                'period_start': since.isoformat(),
                'generated_at': datetime.now(timezone.utc).isoformat()
            }
            
            return stats

    async def get_global_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Получить глобальную статистику по всем чатам"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        query = """
        SELECT 
            COUNT(*) as total_messages,
            COUNT(*) FILTER (WHERE is_spam = true) as spam_messages,
            COUNT(DISTINCT chat_id) as active_chats,
            COUNT(DISTINCT user_id) as active_users,
            COUNT(DISTINCT user_id) FILTER (WHERE is_spam = true) as spam_users,
            AVG(spam_confidence) FILTER (WHERE spam_confidence IS NOT NULL) as avg_spam_confidence
        FROM messages 
        WHERE created_at > $1
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, since)
            
            total = row['total_messages'] or 0
            spam = row['spam_messages'] or 0
            
            return {
                'total_messages': total,
                'spam_messages': spam,
                'clean_messages': total - spam,
                'spam_percentage': round((spam / total * 100) if total > 0 else 0, 2),
                'active_chats': row['active_chats'] or 0,
                'active_users': row['active_users'] or 0,
                'spam_users': row['spam_users'] or 0,
                'avg_spam_confidence': round(float(row['avg_spam_confidence'] or 0), 3),
                'period_hours': hours,
                'generated_at': datetime.now(timezone.utc).isoformat()
            }

    async def get_user_stats(self, user_id: int, chat_id: Optional[int] = None, hours: int = 168) -> Dict[str, Any]:
        """Получить статистику конкретного пользователя"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Базовый запрос
        base_conditions = "user_id = $1 AND created_at > $2"
        params = [user_id, since]
        
        # Добавляем фильтр по чату если указан
        if chat_id is not None:
            base_conditions += " AND chat_id = $3"
            params.append(chat_id)
        
        query = f"""
        SELECT 
            COUNT(*) as total_messages,
            COUNT(*) FILTER (WHERE is_spam = true) as spam_messages,
            COUNT(*) FILTER (WHERE is_spam = false) as clean_messages,
            COUNT(DISTINCT chat_id) as active_chats,
            AVG(spam_confidence) FILTER (WHERE spam_confidence IS NOT NULL) as avg_spam_confidence,
            MAX(spam_confidence) as max_spam_confidence,
            MIN(created_at) as first_message,
            MAX(created_at) as last_message
        FROM messages 
        WHERE {base_conditions}
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            
            total = row['total_messages'] or 0
            spam = row['spam_messages'] or 0
            
            return {
                'user_id': user_id,
                'chat_id': chat_id,
                'total_messages': total,
                'spam_messages': spam,
                'clean_messages': row['clean_messages'] or 0,
                'spam_percentage': round((spam / total * 100) if total > 0 else 0, 2),
                'active_chats': row['active_chats'] or 0,
                'avg_spam_confidence': round(float(row['avg_spam_confidence'] or 0), 3),
                'max_spam_confidence': round(float(row['max_spam_confidence'] or 0), 3),
                'first_message': row['first_message'],
                'last_message': row['last_message'],
                'period_hours': hours,
                'is_suspicious': spam > 0 or float(row['avg_spam_confidence'] or 0) > 0.3,
                'generated_at': datetime.now(timezone.utc).isoformat()
            }

    async def search_messages(
        self, 
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
        text_pattern: Optional[str] = None,
        is_spam: Optional[bool] = None,
        min_confidence: Optional[float] = None,
        hours: Optional[int] = None,
        limit: int = 100
    ) -> List[Message]:
        """Поиск сообщений по различным критериям"""
        
        conditions = []
        params = []
        param_count = 0
        
        # Строим WHERE условия динамически
        if chat_id is not None:
            param_count += 1
            conditions.append(f"chat_id = ${param_count}")
            params.append(chat_id)
        
        if user_id is not None:
            param_count += 1
            conditions.append(f"user_id = ${param_count}")
            params.append(user_id)
        
        if text_pattern is not None:
            param_count += 1
            conditions.append(f"text ILIKE ${param_count}")
            params.append(f"%{text_pattern}%")
        
        if is_spam is not None:
            param_count += 1
            conditions.append(f"is_spam = ${param_count}")
            params.append(is_spam)
        
        if min_confidence is not None:
            param_count += 1
            conditions.append(f"spam_confidence >= ${param_count}")
            params.append(min_confidence)
        
        if hours is not None:
            param_count += 1
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            conditions.append(f"created_at > ${param_count}")
            params.append(since)
        
        # Добавляем лимит
        param_count += 1
        params.append(limit)
        
        # Собираем запрос
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"""
        SELECT * FROM messages 
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ${param_count}
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_message(row) for row in rows]

    def _row_to_message(self, row: asyncpg.Record) -> Message:
        """Преобразовать строку БД в объект Message"""
        return Message(
            id=row['id'],
            user_id=row['user_id'],
            chat_id=row['chat_id'],
            text=row['text'],
            role=MessageRole(row['role']),
            created_at=row['created_at'],
            is_spam=row['is_spam'],
            spam_confidence=row['spam_confidence'],
            has_links=row['has_links'],
            has_mentions=row['has_mentions'],
            has_images=row['has_images'],
            is_forward=row['is_forward'],
            emoji_count=row['emoji_count']
        )


