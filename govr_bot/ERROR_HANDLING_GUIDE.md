# 🚨 Руководство по исправлению `except Exception:`

## ✅ Что уже исправлено:

### 1. Система логирования
- ✅ `utils_pkg_new/logger.py` - структурированное логирование
- ✅ `utils_pkg_new/error_handler.py` - декораторы для безопасной обработки
- ✅ `main.py` - подключение логирования

### 2. Критические файлы
- ✅ `middlewares/subscription_gate.py` - обработка Telegram API
- ✅ `services/answer_db.py` - операции с базой данных
- ✅ `handlers/billing.py` - платежи и уведомления

## 🔧 Что нужно исправить дальше:

### Приоритет 1 (Критично) - исправить в течение недели:

#### `handlers/topics.py` (29 мест с `except Exception:`)
```python
# ❌ ПЛОХО
try:
    # код
except Exception:
    pass

# ✅ ХОРОШО
try:
    # код
except (ValueError, TypeError) as e:
    log_error(e, f"Data error in topic handler for user {user_id}", user_id=user_id)
    await message.answer("Ошибка данных. Попробуйте еще раз.")
except sqlite3.OperationalError as e:
    log_error(e, f"Database error in topic handler for user {user_id}", user_id=user_id)
    await message.answer("Ошибка базы данных. Попробуйте позже.")
except Exception as e:
    log_error(e, f"Unexpected error in topic handler for user {user_id}", user_id=user_id)
    await message.answer("Произошла ошибка. Попробуйте позже.")
```

#### `handlers/tests.py` (22 места с `except Exception:`)
```python
# ❌ ПЛОХО
try:
    # код
except Exception:
    pass

# ✅ ХОРОШО
try:
    # код
except (ValueError, TypeError) as e:
    log_error(e, f"Data error in test handler for user {user_id}", user_id=user_id)
    await message.answer("Ошибка данных. Попробуйте еще раз.")
except sqlite3.OperationalError as e:
    log_error(e, f"Database error in test handler for user {user_id}", user_id=user_id)
    await message.answer("Ошибка базы данных. Попробуйте позже.")
except Exception as e:
    log_error(e, f"Unexpected error in test handler for user {user_id}", user_id=user_id)
    await message.answer("Произошла ошибка. Попробуйте позже.")
```

#### `handlers/flashcards.py` (14 мест с `except Exception:`)
```python
# ❌ ПЛОХО
try:
    # код
except Exception:
    pass

# ✅ ХОРОШО
try:
    # код
except (ValueError, TypeError) as e:
    log_error(e, f"Data error in flashcards handler for user {user_id}", user_id=user_id)
    await message.answer("Ошибка данных. Попробуйте еще раз.")
except sqlite3.OperationalError as e:
    log_error(e, f"Database error in flashcards handler for user {user_id}", user_id=user_id)
    await message.answer("Ошибка базы данных. Попробуйте позже.")
except Exception as e:
    log_error(e, f"Unexpected error in flashcards handler for user {user_id}", user_id=user_id)
    await message.answer("Произошла ошибка. Попробуйте позже.")
```

### Приоритет 2 (Важно) - исправить в течение месяца:

#### `utils.py` (13 мест с `except Exception:`)
```python
# ❌ ПЛОХО
try:
    # код
except Exception:
    pass

# ✅ ХОРОШО
try:
    # код
except (ValueError, TypeError) as e:
    log_error(e, f"Data error in utils function", user_id=user_id)
    return default_value
except Exception as e:
    log_error(e, f"Unexpected error in utils function", user_id=user_id)
    return default_value
```

#### `services/pdf_generator.py` (6 мест с `except Exception:`)
```python
# ❌ ПЛОХО
try:
    # код
except Exception:
    pass

# ✅ ХОРОШО
try:
    # код
except (ValueError, TypeError) as e:
    log_error(e, f"Data error in PDF generator for user {user_id}", user_id=user_id)
    return None
except Exception as e:
    log_error(e, f"Unexpected error in PDF generator for user {user_id}", user_id=user_id)
    return None
```

#### `services/test_sql.py` (4 места с `except Exception:`)
```python
# ❌ ПЛОХО
try:
    # код
except Exception:
    pass

# ✅ ХОРОШО
try:
    # код
except sqlite3.OperationalError as e:
    log_error(e, f"Database operational error in test_sql", user_id=user_id)
    return None
except sqlite3.Error as e:
    log_error(e, f"SQLite error in test_sql", user_id=user_id)
    return None
except Exception as e:
    log_error(e, f"Unexpected error in test_sql", user_id=user_id)
    return None
```

## 🛠️ Как использовать декораторы:

### Для обычных функций:
```python
from bot.utils_pkg_new.error_handler import safe_execute

@safe_execute(error_message="Не удалось получить статистику", default_return=(0, 0))
def get_user_stats(user_id: int) -> tuple[int, int]:
    # Ваш код здесь
    pass
```

### Для Telegram API:
```python
from bot.utils_pkg_new.error_handler import safe_telegram_execute

@safe_telegram_execute(fallback_message="Не удалось отправить сообщение")
async def send_message_to_user(user_id: int, text: str):
    # Telegram API код здесь
    pass
```

### Для операций с БД:
```python
from bot.utils_pkg_new.error_handler import safe_database_operation

@safe_database_operation("get_user_profile")
def get_user_profile(user_id: int):
    # Операции с БД здесь
    pass
```

## 📋 Чек-лист исправления:

### Для каждого файла:
1. ✅ Добавить импорт: `from bot.utils_pkg_new.logger import log_error`
2. ✅ Найти все `except Exception:`
3. ✅ Заменить на конкретные исключения
4. ✅ Добавить логирование ошибок
5. ✅ Добавить fallback сообщения для пользователя
6. ✅ Протестировать изменения

### Типы исключений для разных операций:

#### База данных:
- `sqlite3.OperationalError` - таблицы нет, проблемы с БД
- `sqlite3.Error` - другие ошибки SQLite
- `sqlite3.IntegrityError` - проблемы с целостностью данных

#### Telegram API:
- `TelegramForbiddenError` - пользователь заблокировал бота
- `TelegramBadRequest` - неправильный запрос
- `TelegramAPIError` - проблемы с API

#### Пользовательский ввод:
- `ValueError` - неправильный формат данных
- `TypeError` - неправильный тип данных
- `UnicodeDecodeError` - проблемы с кодировкой

#### Общие:
- `AttributeError` - отсутствует атрибут
- `IndexError` - неправильный индекс
- `KeyError` - неправильный ключ словаря

## 🎯 Результат после исправления:

✅ **Безопасность:** Видите все ошибки, включая атаки  
✅ **Отладка:** Понимаете, что именно сломалось  
✅ **Надежность:** Бот не падает от неожиданных ошибок  
✅ **Мониторинг:** Логи показывают реальные проблемы  
✅ **Пользователи:** Получают понятные сообщения об ошибках  

## 📞 Если нужна помощь:

1. Создайте issue в репозитории
2. Приложите логи из `logs/errors.log`
3. Опишите, что происходило при ошибке
4. Укажите ID пользователя из логов
