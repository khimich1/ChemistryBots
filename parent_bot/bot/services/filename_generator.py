#!/usr/bin/env python3
"""
Общий модуль для генерации имен файлов PDF отчетов.
Используется в govr_bot, parent_bot и prepod_bot.
"""

import sqlite3
import os
import re
from datetime import datetime
from typing import Optional


def get_user_display_name(user_id: int, full_name: Optional[str], username: Optional[str]) -> str:
    """
    Получает отображаемое имя пользователя с приоритетом:
    1. База данных (user_profiles)
    2. full_name из Telegram
    3. username из Telegram
    """
    # Путь к базе данных
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "test_answers.db")
    
    try:
        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()
            # 1) user_profiles
            c.execute(
                "SELECT COALESCE(NULLIF(TRIM(full_name), ''), NULL) FROM user_profiles WHERE user_id=?",
                (user_id,)
            )
            row = c.fetchone()
            if row and row[0]:
                return row[0]
            
            # 2) test_answers (последний ответ с непустым full_name)
            c.execute(
                """
                SELECT full_name
                FROM test_answers
                WHERE user_id=? AND TRIM(COALESCE(full_name, ''))!=''
                ORDER BY answer_time DESC, id DESC
                LIMIT 1
                """,
                (user_id,)
            )
            row = c.fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    
    # 3) full_name из Telegram
    if full_name and full_name.strip():
        return full_name.strip()
    
    # 4) username из Telegram
    if username and username.strip():
        return username.strip()
    
    # 5) Fallback
    return "Ученик"


def generate_filename(display_name: str) -> str:
    """
    Генерирует имя файла в формате: Имя_Фамилия_ДД.ММ.ГГГГ.pdf
    Убирает специальные символы и заменяет пробелы на подчеркивания.
    """
    if not display_name:
        display_name = "Ученик"
    
    # Убираем специальные символы и эмодзи
    clean_name = re.sub(r'[^\w\sа-яёА-ЯЁ]', '', display_name)
    
    # Заменяем пробелы на подчеркивания
    clean_name = clean_name.replace(' ', '_')
    
    # Получаем текущую дату
    current_date = datetime.now().strftime("%d.%m.%Y")
    
    # Формируем имя файла
    filename = f"{clean_name}_{current_date}.pdf"
    
    return filename


def get_filename_for_user(user_id: int, full_name: Optional[str] = None, username: Optional[str] = None) -> str:
    """
    Получает имя файла для пользователя, используя все доступные источники имени.
    """
    display_name = get_user_display_name(user_id, full_name, username)
    return generate_filename(display_name)
