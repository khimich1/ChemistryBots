#!/usr/bin/env python3
"""
Скрипт для добавления тарифа 'free' всем существующим пользователям
"""

import sqlite3
import os

def add_free_plans_to_all_users():
    """Добавляет тариф 'free' всем пользователям, у которых его нет"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Пути к базам данных
    shared_db = os.path.join(current_dir, "shared", "test_answers.db")
    
    print("👤 Добавление тарифа 'free' всем пользователям")
    print("=" * 60)
    print(f"📁 База shared: {shared_db}")
    print(f"📁 Существует: {'✅' if os.path.exists(shared_db) else '❌'}")
    
    if not os.path.exists(shared_db):
        print("❌ База данных не найдена!")
        return
    
    try:
        with sqlite3.connect(shared_db) as conn:
            cur = conn.cursor()
            
            # Создаем таблицу user_plans, если её нет
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_plans(
                    user_id INTEGER PRIMARY KEY,
                    plan_code TEXT,
                    started_at TEXT
                )
            """)
            
            # Получаем всех пользователей из user_profiles
            cur.execute("SELECT user_id, username, full_name FROM user_profiles")
            all_users = cur.fetchall()
            
            print(f"📊 Найдено пользователей в user_profiles: {len(all_users)}")
            
            # Получаем существующие записи в user_plans
            cur.execute("SELECT user_id FROM user_plans")
            existing_plans = {row[0] for row in cur.fetchall()}
            
            print(f"📊 Уже имеют тариф: {len(existing_plans)}")
            
            # Находим пользователей без тарифа
            users_without_plan = []
            for user_id, username, full_name in all_users:
                if user_id not in existing_plans:
                    users_without_plan.append({
                        'user_id': user_id,
                        'username': username,
                        'full_name': full_name
                    })
            
            print(f"📊 Нуждаются в тарифе 'free': {len(users_without_plan)}")
            
            if not users_without_plan:
                print("✅ Все пользователи уже имеют тариф!")
                return
            
            # Добавляем тариф 'free' всем нуждающимся
            added_count = 0
            for user in users_without_plan:
                cur.execute("""
                    INSERT OR REPLACE INTO user_plans (user_id, plan_code, started_at)
                    VALUES (?, ?, datetime('now'))
                """, (user['user_id'], 'free'))
                added_count += 1
            
            conn.commit()
            print(f"✅ Добавлен тариф 'free' для {added_count} пользователей")
            
            # Показываем список добавленных пользователей
            print("\n📋 Добавленные пользователи:")
            print("-" * 60)
            for user in users_without_plan[:10]:  # Показываем первых 10
                label = user['full_name'] or user['username'] or f"ID {user['user_id']}"
                print(f"👤 {label} (ID: {user['user_id']})")
            
            if len(users_without_plan) > 10:
                print(f"... и еще {len(users_without_plan) - 10} пользователей")
            
            print("\n" + "=" * 60)
            print("🏁 Операция завершена!")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    add_free_plans_to_all_users()
