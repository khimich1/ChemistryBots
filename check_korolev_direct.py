#!/usr/bin/env python3
"""
Прямая проверка Алексея Королева в базе данных
"""

import sqlite3
import os

def check_korolev_direct():
    """Прямая проверка Алексея Королева"""
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    shared_db = os.path.join(current_dir, "shared", "test_answers.db")
    
    korolev_id = 399462447
    
    print("👤 Прямая проверка Алексея Королева")
    print("=" * 50)
    print(f"📁 База: {shared_db}")
    
    try:
        with sqlite3.connect(shared_db) as conn:
            cur = conn.cursor()
            
            # Проверяем в user_profiles
            cur.execute("SELECT user_id, username, full_name FROM user_profiles WHERE user_id = ?", (korolev_id,))
            profile = cur.fetchone()
            
            if profile:
                print(f"✅ Найден в user_profiles: {profile}")
            else:
                print("❌ Не найден в user_profiles")
            
            # Проверяем в user_plans
            cur.execute("SELECT user_id, plan_code FROM user_plans WHERE user_id = ?", (korolev_id,))
            plan = cur.fetchone()
            
            if plan:
                print(f"✅ Найден в user_plans: {plan}")
            else:
                print("❌ Не найден в user_plans")
            
            # Проверяем в teacher_groups
            cur.execute("SELECT user_id FROM teacher_groups WHERE user_id = ?", (korolev_id,))
            group = cur.fetchone()
            
            if group:
                print(f"✅ Найден в teacher_groups: {group}")
            else:
                print("❌ Не найден в teacher_groups")
            
            print("\n📊 Итоговый статус:")
            if profile and plan and group:
                print("✅ Алексей Королев имеет все необходимые записи!")
                print("   - Есть в user_profiles")
                print("   - Есть тариф в user_plans")
                print("   - Одобрен преподавателем в teacher_groups")
            else:
                print("❌ Алексей Королев не имеет всех необходимых записей")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    check_korolev_direct()
