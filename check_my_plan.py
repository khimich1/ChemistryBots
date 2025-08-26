#!/usr/bin/env python3
"""
Скрипт для проверки тарифа пользователя
Запуск: python check_my_plan.py
"""

import sqlite3
import os
from datetime import datetime

# Путь к базе данных
DB_FILE = "govr_bot/bot/services/answers.db"

def check_user_plan(user_id: int):
    """Проверяет тариф пользователя"""
    
    if not os.path.exists(DB_FILE):
        print(f"❌ База данных не найдена: {DB_FILE}")
        return
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            
            # Проверяем, есть ли таблица user_plans
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_plans'")
            if not c.fetchone():
                print("❌ Таблица user_plans не найдена")
                return
            
            # Получаем тариф пользователя
            c.execute("SELECT plan_code, started_at FROM user_plans WHERE user_id=?", (user_id,))
            row = c.fetchone()
            
            if row:
                plan_code, started_at = row
                print(f"✅ Пользователь {user_id}:")
                print(f"   Тариф: {plan_code}")
                print(f"   Активирован: {started_at}")
                
                # Показываем лимиты
                limits = get_plan_limits(plan_code)
                print(f"   Лимиты:")
                for key, value in limits.items():
                    print(f"     {key}: {value}")
            else:
                print(f"ℹ️ Пользователь {user_id} не найден в базе (используется бесплатный тариф)")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def get_plan_limits(plan_code: str) -> dict:
    """Возвращает лимиты для тарифа"""
    plan = plan_code.lower() if plan_code else "free"
    
    if plan in {"full", "group", "self"}:
        return {
            "Голосовые сообщения/день": 10,
            "Вопросы ИИ/день": 50,
            "Объяснения тестов/день": 200,
            "Подсказки тестов/день": 200,
            "Отчёты/месяц": 20,
        }
    elif plan == "organic":
        return {
            "Голосовые сообщения/день": 5,
            "Вопросы ИИ/день": 20,
            "Объяснения тестов/день": 100,
            "Подсказки тестов/день": 100,
            "Отчёты/месяц": 5,
        }
    elif plan == "elements":
        return {
            "Голосовые сообщения/день": 5,
            "Вопросы ИИ/день": 20,
            "Объяснения тестов/день": 100,
            "Подсказки тестов/день": 100,
            "Отчёты/месяц": 5,
        }
    else:  # free
        return {
            "Голосовые сообщения/день": 1,
            "Вопросы ИИ/день": 2,
            "Объяснения тестов/день": 3,
            "Подсказки тестов/день": 5,
            "Отчёты/месяц": 1,
        }

if __name__ == "__main__":
    print("🔍 Проверка тарифа пользователя")
    print("=" * 40)
    
    # Запрашиваем ID пользователя
    try:
        user_id = int(input("Введите ID пользователя (или нажми Enter для демо): ").strip())
    except ValueError:
        user_id = 123456789  # Демо ID
    
    check_user_plan(user_id)
    
    print("\n" + "=" * 40)
    print("💡 Подсказки:")
    print("• В боте нажми '💳 Тарифы и оплата' для просмотра")
    print("• ID пользователя можно узнать в @userinfobot")
    print("• По умолчанию все пользователи на бесплатном тарифе")
