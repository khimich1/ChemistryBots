#!/usr/bin/env python3
"""
Скрипт для проверки тестовых учеников
"""

import sqlite3
import os

def check_test_students():
    """Проверяет тестовых учеников"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prepod_db = os.path.join(current_dir, "prepod_bot", "test_answers.db")
    
    print("🔍 Проверка тестовых учеников")
    print("=" * 50)
    
    # Тестовые ID учеников
    test_ids = [1001, 1002, 1003, 1004, 1005, 1006, 12345]
    
    try:
        with sqlite3.connect(prepod_db) as conn:
            cur = conn.cursor()
            
            for user_id in test_ids:
                print(f"\n👤 Проверка ученика ID: {user_id}")
                print("-" * 30)
                
                # Проверяем в user_profiles
                cur.execute("SELECT username, full_name, hide_reason FROM user_profiles WHERE user_id = ?", (user_id,))
                profile_row = cur.fetchone()
                
                if profile_row:
                    username, full_name, hide_reason = profile_row
                    print(f"✅ В user_profiles: {full_name} (@{username})")
                    if hide_reason:
                        print(f"⚠️  Скрыт: {hide_reason}")
                else:
                    print("❌ Не найден в user_profiles")
                
                # Проверяем в test_answers
                cur.execute("SELECT username, full_name FROM test_answers WHERE user_id = ? LIMIT 1", (user_id,))
                answers_row = cur.fetchone()
                
                if answers_row:
                    username, full_name = answers_row
                    print(f"✅ В test_answers: {full_name} (@{username})")
                else:
                    print("❌ Не найден в test_answers")
                
                # Проверяем функцию _is_hidden
                cur.execute("SELECT hide_reason FROM user_profiles WHERE user_id = ?", (user_id,))
                hide_row = cur.fetchone()
                is_hidden = bool(hide_row and hide_row[0])
                print(f"🔒 Скрыт: {'Да' if is_hidden else 'Нет'}")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    check_test_students()
