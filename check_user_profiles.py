#!/usr/bin/env python3
"""
Скрипт для проверки таблицы user_profiles
"""

import sqlite3
import os

def check_user_profiles():
    """Проверяет таблицу user_profiles"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prepod_db = os.path.join(current_dir, "prepod_bot", "test_answers.db")
    
    print("🔍 Проверка таблицы user_profiles")
    print("=" * 50)
    
    try:
        with sqlite3.connect(prepod_db) as conn:
            cur = conn.cursor()
            
            # Проверяем все записи в user_profiles
            print("\n📋 Все записи в user_profiles:")
            print("-" * 60)
            
            cur.execute("SELECT user_id, username, full_name, hide_reason FROM user_profiles")
            rows = cur.fetchall()
            
            if rows:
                for user_id, username, full_name, hide_reason in rows:
                    print(f"👤 ID: {user_id}, Username: {username}, Name: {full_name}, Hidden: {hide_reason}")
            else:
                print("❌ Таблица пуста")
            
            # Проверяем запрос с условием hide_reason
            print("\n📋 Запрос с условием hide_reason IS NULL OR hide_reason = '':")
            print("-" * 60)
            
            cur.execute("SELECT user_id, username, full_name FROM user_profiles WHERE hide_reason IS NULL OR hide_reason = ''")
            filtered_rows = cur.fetchall()
            
            if filtered_rows:
                for user_id, username, full_name in filtered_rows:
                    print(f"👤 ID: {user_id}, Username: {username}, Name: {full_name}")
            else:
                print("❌ Нет записей с пустым hide_reason")
            
            # Проверяем количество записей
            print(f"\n📊 Всего записей: {len(rows)}")
            print(f"📊 Записей без hide_reason: {len(filtered_rows)}")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    check_user_profiles()
