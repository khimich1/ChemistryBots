from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from bot.services.analytics import UserAnalytics
from bot.services.answer_db import get_db_connection
from datetime import datetime, timedelta
import sqlite3

router = Router()

# Список твоих ID (замени на свой)
ADMIN_IDS = [727117860]  # Замени на свой Telegram ID

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

@router.message(Command("stats"))
async def show_stats(message: Message):
    """Показывает общую статистику бота"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет доступа к этой команде")
        return
    
    try:
        # Получаем статистику
        total_users = UserAnalytics.get_total_users()
        active_week = UserAnalytics.get_active_users(7)
        active_month = UserAnalytics.get_active_users(30)
        new_week = UserAnalytics.get_new_users(7)
        new_month = UserAnalytics.get_new_users(30)
        
        # Статистика за сегодня
        today = datetime.now().strftime("%Y-%m-%d")
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM test_answers WHERE DATE(answer_time) = ?", (today,))
            tests_today = c.fetchone()[0]
            
            c.execute("SELECT COUNT(DISTINCT user_id) FROM test_answers WHERE DATE(answer_time) = ?", (today,))
            users_today = c.fetchone()[0]
        
        stats_text = f"""
📊 **СТАТИСТИКА БОТА**

👥 **Пользователи:**
• Всего: {total_users}
• Активных за неделю: {active_week}
• Активных за месяц: {active_month}
• Новых за неделю: {new_week}
• Новых за месяц: {new_month}

📅 **Сегодня ({today}):**
• Пользователей: {users_today}
• Тестов пройдено: {tests_today}

💡 **Команды:**
• `/stats` - общая статистика
• `/users` - список пользователей
• `/daily` - статистика по дням
• `/top` - топ пользователей
• `/help_admin` - все админские команды
        """
        
        await message.answer(stats_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении статистики: {str(e)}")

@router.message(Command("stats_clean"))
async def show_stats_clean(message: Message):
    """Показывает статистику бота без учёта активности админов"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет доступа к этой команде")
        return
    
    try:
        # Получаем статистику без админов
        stats = UserAnalytics.get_stats_exclude_admin()
        
        stats_text = f"""
📊 **СТАТИСТИКА БОТА (БЕЗ АДМИНОВ)**

👥 **Пользователи:**
• Всего: {stats['total_users']}
• Активных за неделю: {stats['active_week']}
• Активных за месяц: {stats['active_month']}
• Новых за неделю: {stats['new_week']}
• Новых за месяц: {stats['new_month']}

📅 **Сегодня:**
• Пользователей: {stats['users_today']}
• Тестов пройдено: {stats['tests_today']}

💡 **Эта статистика исключает твою активность как админа**
        """
        
        await message.answer(stats_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении статистики: {str(e)}")

@router.message(Command("users"))
async def show_users(message: Message):
    """Показывает список последних пользователей"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT user_id, username, full_name, created_at 
                FROM user_profiles 
                ORDER BY created_at DESC 
                LIMIT 20
            """)
            users = c.fetchall()
        
        if not users:
            await message.answer("👥 Пользователей пока нет")
            return
        
        users_text = "👥 **Последние 20 пользователей:**\n\n"
        for user in users:
            user_id, username, full_name, created_at = user
            name = full_name or username or f"ID: {user_id}"
            users_text += f"• {name} ({created_at})\n"
        
        await message.answer(users_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("daily"))
async def show_daily_stats(message: Message):
    """Показывает статистику по дням"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        daily_stats = UserAnalytics.get_daily_stats(7)  # За неделю
        
        stats_text = "📅 **Статистика за последние 7 дней:**\n\n"
        for day in daily_stats:
            stats_text += f"**{day['date']}:**\n"
            stats_text += f"• Новых: {day['new_users']}\n"
            stats_text += f"• Активных: {day['active_users']}\n"
            stats_text += f"• Тестов: {day['tests_count']}\n\n"
        
        await message.answer(stats_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("top"))
async def show_top_users(message: Message):
    """Показывает топ пользователей"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        top_users = UserAnalytics.get_top_users(10)
        
        if not top_users:
            await message.answer("👥 Пользователей пока нет")
            return
        
        top_text = "🏆 **Топ-10 активных пользователей:**\n\n"
        for i, user in enumerate(top_users, 1):
            name = user['full_name'] or user['username'] or f"ID: {user['user_id']}"
            top_text += f"{i}. {name}\n"
            top_text += f"   Тестов: {user['tests_count']}, Теория: {user['theory_count']}, Карточки: {user['cards_count']}\n"
            top_text += f"   Всего: {user['total_activity']}\n\n"
        
        await message.answer(top_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("user"))
async def show_user_info(message: Message):
    """Показывает информацию о конкретном пользователе"""
    if not is_admin(message.from_user.id):
        return
    
    # Парсим команду: /user 123456789
    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Используй: /user <ID пользователя>")
        return
    
    try:
        user_id = int(args[1])
        user_stats = UserAnalytics.get_user_activity_summary(user_id)
        
        if not user_stats:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        user_text = f"""
👤 **Информация о пользователе:**

🆔 ID: {user_stats['user_id']}
👤 Имя: {user_stats['full_name'] or 'Не указано'}
📱 Username: @{user_stats['username'] or 'Не указан'}
📅 Зарегистрирован: {user_stats['created_at']}
🕐 Последняя активность: {user_stats['last_activity'] or 'Нет данных'}

📊 **Активность:**
• Тестов пройдено: {user_stats['total_tests']}
• Тестов правильно: {user_stats['correct_tests']}
• Заданий теории: {user_stats['total_theory']}
• Заданий правильно: {user_stats['correct_theory']}
• Карточек изучено: {user_stats['total_cards']}

⏱️ **Длительность сессии: {user_stats['session_duration_minutes'] or 'Нет данных'} минут**
        """
        
        await message.answer(user_text, parse_mode="Markdown")
        
    except ValueError:
        await message.answer("❌ ID пользователя должен быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("plans"))
async def show_plans_stats(message: Message):
    """Показывает статистику по тарифам пользователей"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        plans_stats = UserAnalytics.get_user_plans_stats()
        
        if not plans_stats:
            await message.answer("📊 Статистика по тарифам недоступна")
            return
        
        plans_text = "💳 **Статистика по тарифам:**\n\n"
        total_users = sum(plans_stats.values())
        
        for plan, count in plans_stats.items():
            percentage = (count / total_users * 100) if total_users > 0 else 0
            plans_text += f"• {plan}: {count} ({percentage:.1f}%)\n"
        
        plans_text += f"\n👥 **Всего пользователей: {total_users}**"
        
        await message.answer(plans_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("sources"))
async def show_acquisition_stats(message: Message):
    """Показывает статистику по источникам пользователей"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        sources_stats = UserAnalytics.get_user_acquisition_stats()
        
        if not sources_stats:
            await message.answer("📊 Статистика по источникам недоступна")
            return
        
        sources_text = "🔗 **Источники пользователей (top-20):**\n\n"
        total_users = sum(sources_stats.values())
        
        for source, count in sources_stats.items():
            percentage = (count / total_users * 100) if total_users > 0 else 0
            sources_text += f"• {source}: {count} ({percentage:.1f}%)\n"
        
        sources_text += f"\n👥 **Всего пользователей: {total_users}**"
        
        await message.answer(sources_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("retention"))
async def show_retention_stats(message: Message):
    """Показывает статистику удержания пользователей"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        retention_stats = UserAnalytics.get_user_retention_stats(30)
        
        retention_text = f"""
📈 **Статистика удержания (за 30 дней):**

👥 **Пользователи:**
• Были активны месяц назад: {retention_stats['past_active']}
• Активны сейчас: {retention_stats['current_active']}

💚 **Удержание: {retention_stats['retention_rate']}%**

💡 **Интерпретация:**
• Выше 70% - отличное удержание
• 50-70% - хорошее удержание  
• 30-50% - среднее удержание
• Ниже 30% - нужны меры по удержанию
        """
        
        await message.answer(retention_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("retention_week"))
async def show_retention_stats_week(message: Message):
    """Показывает статистику удержания пользователей за последние 7 дней"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        retention_stats = UserAnalytics.get_user_retention_stats_7_days()
        
        retention_text = f"""
📈 **Статистика удержания (за 7 дней):**

👥 **Пользователи:**
• Были активны неделю назад: {retention_stats['week_ago_active']}
• Вернулись за неделю: {retention_stats['current_week_active']}
• Всего активных за неделю: {retention_stats['total_week_active']}

💚 **Удержание: {retention_stats['retention_rate']}%**
📈 **Рост: {retention_stats['growth_rate']}%**

💡 **Интерпретация:**
• Удержание показывает, сколько старых пользователей вернулись
• Рост показывает общее изменение активности
• Положительный рост = новые пользователи или возвращение неактивных
        """
        
        await message.answer(retention_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("patterns"))
async def show_learning_patterns(message: Message):
    """Показывает паттерны обучения пользователей"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        patterns = UserAnalytics.get_user_learning_patterns()
        
        # Время суток
        hourly_text = "🕐 **Активность по часам (за неделю):**\n"
        for hour in range(24):
            count = patterns['hourly_activity'].get(hour, 0)
            if count > 0:
                hourly_text += f"• {hour:02d}:00 - {count} действий\n"
        
        # Дни недели
        weekday_text = "\n📅 **Активность по дням недели (за месяц):**\n"
        for weekday, count in patterns['weekday_activity'].items():
            weekday_text += f"• {weekday}: {count} действий\n"
        
        await message.answer(hourly_text + weekday_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("performance"))
async def show_performance_stats(message: Message):
    """Показывает статистику успеваемости пользователей"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        performance = UserAnalytics.get_user_performance_stats()
        
        performance_text = f"""
📊 **Статистика успеваемости:**

🎯 **Средние баллы:**
• По тестам: {performance['avg_test_score']}% {'(оценка недоступна)' if not performance.get('test_scoring_available', True) else ''}
• По теории: {performance['avg_theory_score']}% {'(оценка недоступна)' if not performance.get('theory_scoring_available', True) else ''}

📝 **Всего ответов:**
• Тестов: {performance['total_test_answers']}
• Теории: {performance['total_theory_answers']}

🏆 **Распределение по уровням:**
        """
        
        for level, count in performance['performance_levels'].items():
            performance_text += f"• {level}: {count} пользователей\n"
        
        await message.answer(performance_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("engagement"))
async def show_engagement_metrics(message: Message):
    """Показывает метрики вовлечённости пользователей"""
    if not is_admin(message.from_user.id):
        return
    
    try:
        engagement = UserAnalytics.get_user_engagement_metrics()
        
        engagement_text = f"""
🔥 **Метрики вовлечённости (за сегодня):**

👥 **По уровню активности:**
• Высокая (10+ действий): {engagement['high_engagement']}
• Средняя (3-9 действий): {engagement['medium_engagement']}
• Низкая (1-2 действия): {engagement['low_engagement']}
• Неактивны: {engagement['inactive_today']}

💡 **Интерпретация:**
• Высокая вовлечённость = отличный продукт
• Средняя = нужно мотивировать
• Низкая = нужны новые функции
• Неактивны = нужна реактивация
        """
        
        await message.answer(engagement_text, parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("help_admin"))
async def show_admin_help(message: Message):
    """Показывает справку по админским командам"""
    if not is_admin(message.from_user.id):
        return
    
    help_text = """
🛠️ **СПРАВКА ПО АДМИНСКИМ КОМАНДАМ:**

📊 **Основная статистика:**
• `/stats` - общая статистика бота
• `/stats_clean` - статистика без учёта админов
• `/users` - последние 20 пользователей
• `/daily` - статистика по дням (за неделю)
• `/top` - топ-10 активных пользователей

👤 **Анализ пользователей:**
• `/user <ID>` - информация о конкретном пользователе
• `/plans` - статистика по тарифам
• `/sources` - источники пользователей (deep-links)
• `/retention` - удержание пользователей (за 30 дней)
• `/retention_week` - удержание пользователей (за 7 дней)

📈 **Детальная аналитика:**
• `/patterns` - паттерны обучения (время, дни недели)
• `/performance` - успеваемость пользователей
• `/engagement` - метрики вовлечённости

💡 **Полезные советы:**
• Используй `/stats` каждый день
• `/retention` покажет качество удержания
• `/patterns` поможет понять лучшее время для уведомлений
• `/engagement` покажет, кто нуждается в мотивации
        """
    
    await message.answer(help_text, parse_mode="Markdown")
