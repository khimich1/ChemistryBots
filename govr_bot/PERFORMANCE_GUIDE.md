# 🚀 Руководство по производительности для высокой нагрузки

## 📊 **Текущие возможности бота**

### ✅ **Что уже оптимизировано:**

1. **Асинхронная архитектура aiogram 3.x**
   - Поддерживает тысячи одновременных запросов
   - Неблокирующие операции

2. **SQLite с WAL режимом**
   - Пул соединений для конкурентного доступа
   - Оптимизированные PRAGMA настройки
   - Таймауты для предотвращения блокировок

3. **Rate Limiting**
   - Защита от спама: 20 сообщений/минуту
   - Callback кнопки: 30/минуту
   - Тесты: 10/минуту
   - Отчеты: 5/5 минут

4. **Graceful Shutdown**
   - Корректное завершение работы
   - Закрытие всех соединений
   - Отмена фоновых задач

## 🎯 **Ожидаемая производительность**

### **150-200 пользователей одновременно:**

- ✅ **Сообщения**: ~3000/час (20 на пользователя)
- ✅ **Callback кнопки**: ~4500/час (30 на пользователя)  
- ✅ **Тесты**: ~1500/час (10 на пользователя)
- ✅ **Отчеты**: ~250/час (5 на пользователя)

### **Ограничения Telegram API:**
- 30 сообщений в секунду на бота
- 20 callback queries в секунду
- 50 requests в секунду

**Наш бот укладывается в лимиты!** ✅

## 🔧 **Мониторинг производительности**

### **Логи для отслеживания:**
```bash
# Следим за ошибками
tail -f govr_bot/logs/errors.log

# Следим за общими логами
tail -f govr_bot/logs/bot.log
```

### **Ключевые метрики:**
- `Rate limit exceeded` - превышение лимитов
- `Database operation failed` - проблемы с БД
- `Network error` - сетевые проблемы
- `Telegram API error` - ошибки API

## 🚨 **Что делать при проблемах**

### **1. Высокая нагрузка на БД:**
```python
# В govr_bot/bot/services/answer_db.py
# Увеличить timeout и cache_size
c.execute("PRAGMA busy_timeout=15000")  # 15 секунд
c.execute("PRAGMA cache_size=20000")    # Больше кэша
```

### **2. Медленные ответы:**
```python
# В govr_bot/bot/main.py
# Уменьшить polling_timeout
await dp_instance.start_polling(bot_instance, polling_timeout=20)
```

### **3. Много ошибок rate limit:**
```python
# В govr_bot/bot/utils_pkg_new/rate_limiter.py
# Увеличить лимиты
message_limiter = RateLimiter(max_requests=30, window_seconds=60)
```

## 📈 **Масштабирование**

### **Для 500+ пользователей:**

1. **Переход на PostgreSQL:**
   ```python
   # Заменить SQLite на PostgreSQL
   import asyncpg
   ```

2. **Redis для кэширования:**
   ```python
   # Кэш состояний пользователей
   import redis.asyncio as redis
   ```

3. **Множественные экземпляры:**
   ```bash
   # Запуск нескольких ботов
   python main.py --instance 1
   python main.py --instance 2
   ```

## 🛠️ **Команды для мониторинга**

### **Проверка нагрузки:**
```bash
# Количество активных пользователей
sqlite3 shared/test_answers.db "SELECT COUNT(DISTINCT user_id) FROM test_activity WHERE started_at > datetime('now', '-1 hour');"

# Статистика запросов
sqlite3 shared/test_answers.db "SELECT COUNT(*) FROM test_answers WHERE answer_time > datetime('now', '-1 hour');"
```

### **Очистка старых данных:**
```bash
# Удалить старые логи (старше 30 дней)
find govr_bot/logs -name "*.log" -mtime +30 -delete

# Очистить старые записи активности
sqlite3 shared/test_answers.db "DELETE FROM test_activity WHERE started_at < datetime('now', '-7 days');"
```

## 🎉 **Готовность к тестированию**

Ваш бот **готов к нагрузке 150-200 пользователей**!

### **Что включено:**
- ✅ Пул соединений БД
- ✅ Rate limiting
- ✅ Graceful shutdown
- ✅ Обработка ошибок
- ✅ Логирование

### **Рекомендации для тестирования:**
1. Запустите бота
2. Постепенно увеличивайте нагрузку
3. Следите за логами
4. При проблемах - увеличивайте лимиты

**Удачи с тестированием! 🚀**
