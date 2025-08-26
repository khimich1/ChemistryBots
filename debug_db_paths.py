#!/usr/bin/env python3
"""
Скрипт для отладки путей к базам данных
"""

import os
import sys

def debug_db_paths():
    """Отлаживает пути к базам данных"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("🔍 Отладка путей к базам данных")
    print("=" * 50)
    
    # Добавляем путь к govr_bot
    govr_path = os.path.join(current_dir, "govr_bot")
    sys.path.append(govr_path)
    
    try:
        from bot.services.answer_db import DB_FILE
        print(f"📁 DB_FILE из answer_db.py: {DB_FILE}")
        print(f"📁 Существует: {'✅' if os.path.exists(DB_FILE) else '❌'}")
        
        # Проверяем содержимое этой базы
        import sqlite3
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            
            # Проверяем таблицу user_plans
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_plans'")
            if cur.fetchone():
                print("✅ Таблица user_plans существует в DB_FILE")
                
                # Проверяем Смирнова Романа
                cur.execute("SELECT plan_code FROM user_plans WHERE user_id = ?", (727117860,))
                row = cur.fetchone()
                if row:
                    print(f"📊 Смирнов Роман в DB_FILE: план {row[0]}")
                else:
                    print("❌ Смирнов Роман не найден в DB_FILE")
            else:
                print("❌ Таблица user_plans не существует в DB_FILE")
                
    except Exception as e:
        print(f"❌ Ошибка при проверке DB_FILE: {e}")
    
    # Проверяем govr_bot базу напрямую
    govr_db = os.path.join(current_dir, "govr_bot", "bot", "services", "answers.db")
    print(f"\n📁 Прямой путь к govr_bot: {govr_db}")
    print(f"📁 Существует: {'✅' if os.path.exists(govr_db) else '❌'}")
    
    try:
        with sqlite3.connect(govr_db) as conn:
            cur = conn.cursor()
            
            # Проверяем таблицу user_plans
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_plans'")
            if cur.fetchone():
                print("✅ Таблица user_plans существует в govr_bot")
                
                # Проверяем Смирнова Романа
                cur.execute("SELECT plan_code FROM user_plans WHERE user_id = ?", (727117860,))
                row = cur.fetchone()
                if row:
                    print(f"📊 Смирнов Роман в govr_bot: план {row[0]}")
                else:
                    print("❌ Смирнов Роман не найден в govr_bot")
            else:
                print("❌ Таблица user_plans не существует в govr_bot")
                
    except Exception as e:
        print(f"❌ Ошибка при проверке govr_bot: {e}")

if __name__ == "__main__":
    debug_db_paths()
