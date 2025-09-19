from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from bot.services.answer_db import get_db_connection, get_user_full_name
from bot.handlers.admin import is_admin
from datetime import datetime
import sqlite3
import random

router = Router()

def init_giveaway_table():
    """Создает таблицу для участников розыгрыша"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS giveaway_participants (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                registered_at TEXT
            )
        ''')
        conn.commit()

# Инициализируем таблицу при импорте модуля
init_giveaway_table()

@router.message(Command("giveaway"))
async def register_for_giveaway(message: Message):
    """Регистрация в розыгрыше"""
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Получаем полное имя пользователя из базы
    full_name = get_user_full_name(user_id)
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Проверяем, не зарегистрирован ли уже пользователь
            c.execute("SELECT user_id FROM giveaway_participants WHERE user_id = ?", (user_id,))
            if c.fetchone():
                await message.answer(
                    "🎁 Ты уже зарегистрирован в розыгрыше!\n\n"
                    "Следи за новостями - скоро объявим победителей! 🏆"
                )
                return
            
            # Регистрируем пользователя
            c.execute('''
                INSERT INTO giveaway_participants (user_id, username, full_name, registered_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, full_name, datetime.now().isoformat()))
            conn.commit()
            
            # Подсчитываем общее количество участников
            c.execute("SELECT COUNT(*) FROM giveaway_participants")
            total_participants = c.fetchone()[0]
            
            await message.answer(
                "🎉 Поздравляем! Ты зарегистрирован в розыгрыше!\n\n"
                "🎁 <b>Призы:</b>\n"
                "• 20 таблиц Менделеева\n"
                "• 2 подписки 'Полный доступ'\n\n"
                f"👥 Участников: {total_participants}\n\n"
                "Следи за новостями - скоро объявим победителей! 🏆",
                parse_mode="HTML"
            )
            
    except Exception as e:
        await message.answer(
            "❌ Произошла ошибка при регистрации. Попробуй позже."
        )

@router.message(Command("giveaway_stats"))
async def giveaway_stats(message: Message):
    """Статистика розыгрыша (для админа)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет доступа к этой команде")
        return
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Общее количество участников
            c.execute("SELECT COUNT(*) FROM giveaway_participants")
            total_participants = c.fetchone()[0]
            
            # Участники за последние 24 часа
            c.execute('''
                SELECT COUNT(*) FROM giveaway_participants 
                WHERE registered_at > datetime('now', '-1 day')
            ''')
            recent_participants = c.fetchone()[0]
            
            # Последние 10 участников
            c.execute('''
                SELECT username, full_name, registered_at 
                FROM giveaway_participants 
                ORDER BY registered_at DESC 
                LIMIT 10
            ''')
            recent_users = c.fetchall()
            
            stats_text = f"""📊 <b>СТАТИСТИКА РОЗЫГРЫША</b>

👥 <b>Участники:</b>
• Всего зарегистрировано: {total_participants}
• За последние 24 часа: {recent_participants}

👤 <b>Последние участники:</b>"""
            
            for username, full_name, registered_at in recent_users:
                user_display = f"@{username}" if username else "без username"
                name_display = full_name if full_name else "без имени"
                date_display = registered_at[:16].replace('T', ' ')
                stats_text += f"\n• {user_display} ({name_display}) - {date_display}"
            
            await message.answer(stats_text, parse_mode="HTML")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@router.message(Command("giveaway_draw"))
async def conduct_giveaway(message: Message):
    """Проводит розыгрыш и отправляет сообщения победителям"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет доступа к этой команде")
        return
    
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Получаем всех участников
            c.execute("SELECT user_id, username, full_name FROM giveaway_participants")
            all_participants = c.fetchall()
            
            if len(all_participants) < 22:
                await message.answer(
                    f"❌ Недостаточно участников для розыгрыша!\n"
                    f"Зарегистрировано: {len(all_participants)}, нужно минимум 22"
                )
                return
            
            # Выбираем случайных победителей
            winners = random.sample(all_participants, 22)
            
            # 20 победителей таблицы Менделеева
            mendeleev_winners = winners[:20]
            
            # 2 победителя подписки
            subscription_winners = winners[20:22]
            
            # Отправляем сообщения победителям таблицы Менделеева
            mendeleev_success = 0
            for user_id, username, full_name in mendeleev_winners:
                try:
                    await message.bot.send_message(
                        user_id,
                        "🎉 <b>ПОЗДРАВЛЯЕМ!</b> 🎉\n\n"
                        "Ты выиграл таблицу Менделеева в нашем розыгрыше! 📊⚗️\n\n"
                        "Скоро с тобой свяжется администратор для получения приза.\n\n"
                        "Спасибо за участие! 🙏",
                        parse_mode="HTML"
                    )
                    mendeleev_success += 1
                except Exception:
                    pass
            
            # Отправляем сообщения победителям подписки
            subscription_success = 0
            for user_id, username, full_name in subscription_winners:
                try:
                    await message.bot.send_message(
                        user_id,
                        "🎉 <b>ПОЗДРАВЛЯЕМ!</b> 🎉\n\n"
                        "Ты выиграл подписку 'Полный доступ' в нашем розыгрыше! 🔥✨\n\n"
                        "Скоро с тобой свяжется администратор для активации подписки.\n\n"
                        "Спасибо за участие! 🙏",
                        parse_mode="HTML"
                    )
                    subscription_success += 1
                except Exception:
                    pass
            
            # Отчет админу
            report_text = f"""🎊 <b>РОЗЫГРЫШ ЗАВЕРШЕН!</b> 🎊

👥 <b>Участников:</b> {len(all_participants)}

🏆 <b>Победители таблицы Менделеева ({mendeleev_success}/20):</b>"""
            
            for user_id, username, full_name in mendeleev_winners:
                user_display = f"@{username}" if username else f"ID: {user_id}"
                name_display = f" ({full_name})" if full_name else ""
                report_text += f"\n• {user_display}{name_display}"
            
            report_text += f"\n\n🔥 <b>Победители подписки ({subscription_success}/2):</b>"
            
            for user_id, username, full_name in subscription_winners:
                user_display = f"@{username}" if username else f"ID: {user_id}"
                name_display = f" ({full_name})" if full_name else ""
                report_text += f"\n• {user_display}{name_display}"
            
            await message.answer(report_text, parse_mode="HTML")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка при проведении розыгрыша: {str(e)}")
