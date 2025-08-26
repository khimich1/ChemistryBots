#!/usr/bin/env python3
"""
Отладочный скрипт для проверки функции get_all_students
"""

import sys
import os

# Добавляем путь к prepod_bot
current_dir = os.path.dirname(os.path.abspath(__file__))
prepod_path = os.path.join(current_dir, "prepod_bot")
sys.path.append(prepod_path)

def debug_students():
    """Отлаживает функцию get_all_students"""
    
    print("🔍 Отладка функции get_all_students")
    print("=" * 50)
    
    try:
        from services.students import get_all_students
        
        # Получаем список учеников
        students = get_all_students()
        
        print(f"📊 get_all_students() вернула: {len(students)} учеников")
        print("\n📋 Список учеников из get_all_students():")
        print("-" * 80)
        
        for i, student in enumerate(students, 1):
            user_id = student["user_id"]
            label = student["label"]
            print(f"{i:2d}. {label} (ID: {user_id})")
        
        print("\n" + "=" * 50)
        
        # Теперь проверим функцию get_all_students_with_plans
        print("\n🔍 Отладка функции get_all_students_with_plans")
        print("=" * 50)
        
        from services.groups import get_all_students_with_plans
        
        students_with_plans = get_all_students_with_plans()
        
        print(f"📊 get_all_students_with_plans() вернула: {len(students_with_plans)} учеников")
        print("\n📋 Список учеников с тарифами:")
        print("-" * 80)
        
        for i, student in enumerate(students_with_plans, 1):
            user_id = student["user_id"]
            label = student["label"]
            plan_name = student["plan_name"]
            print(f"{i:2d}. {label} (ID: {user_id}) - {plan_name}")
        
        print("\n" + "=" * 50)
        print("✅ Отладка завершена!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_students()
