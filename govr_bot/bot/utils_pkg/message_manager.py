from typing import Dict, List, Set
from collections import defaultdict

class MessageManager:
    """Менеджер для отслеживания и удаления сообщений пользователя"""
    
    def __init__(self):
        # user_id -> set of message_ids
        self.user_messages: Dict[int, Set[int]] = defaultdict(set)
    
    def add_message(self, user_id: int, message_id: int):
        """Добавляет ID сообщения для пользователя"""
        self.user_messages[user_id].add(message_id)
    
    def remove_message(self, user_id: int, message_id: int):
        """Удаляет ID сообщения из отслеживания"""
        if user_id in self.user_messages:
            self.user_messages[user_id].discard(message_id)
    
    async def delete_user_messages(self, bot, user_id: int, chat_id: int):
        """Удаляет все отслеживаемые сообщения пользователя"""
        if user_id not in self.user_messages:
            return
        
        message_ids = list(self.user_messages[user_id])
        self.user_messages[user_id].clear()
        
        # Удаляем сообщения пакетами по 10 штук
        for i in range(0, len(message_ids), 10):
            batch = message_ids[i:i+10]
            for msg_id in batch:
                try:
                    await bot.delete_message(chat_id, msg_id)
                except Exception:
                    # Игнорируем ошибки удаления (сообщение уже удалено или недоступно)
                    pass

# Глобальный экземпляр менеджера
message_manager = MessageManager()
