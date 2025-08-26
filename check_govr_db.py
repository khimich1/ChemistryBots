#!/usr/bin/env python3
"""
Скрипт для проверки базы данных govr_bot
"""

import sqlite3
import os

def check_govr_db():
    """Проверяет базу данных govr_bot"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    govr_db = os.path.join(current_dir, "govr_bot", "bot", "services", "answers.db")
    
    print("🔍 Проверка базы данных govr_bot")
    print("=" * 50)
    print(f"📁 База данных: {govr_db}")
    print(f"📁 Существует: {'✅' if os.path.exists(govr_db) else '❌'}")
    
    if not os.path.exists(govr_db):
        print("❌ База данных не найдена!")
        return
    
    try:
        with sqlite3.connect(govr_db) as conn:
            cur = conn.cursor()
            
            # Проверяем таблицу user_plans
            print("\n📋 Таблица user_plans:")
            print("-" * 40)
            
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_plans'")
            if cur.fetchone():
                print("✅ Таблица user_plans существует")
                
                # Получаем все записи
                cur.execute("SELECT user_id, plan_code FROM user_plans")
                rows = cur.fetchall()
                
                print(f"📊 Всего записей: {len(rows)}")
                for user_id, plan_code in rows:
                    print(f"👤 ID: {user_id}, План: {plan_code}")
            else:
                print("❌ Таблица user_plans не существует")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    check_govr_db()
