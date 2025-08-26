#!/usr/bin/env python3
"""
Тестовый скрипт для проверки списка учеников с тарифами
"""

import sys
import os

# Добавляем путь к prepod_bot
current_dir = os.path.dirname(os.path.abspath(__file__))
prepod_path = os.path.join(current_dir, "prepod_bot")
sys.path.append(prepod_path)

def test_students_list():
    """Тестирует получение списка учеников"""
    
    print("🧪 Тестирование списка учеников")
    print("=" * 50)
    
    try:
        from services.groups import get_all_students_with_plans
        
        # Получаем список учеников
        students = get_all_students_with_plans()
        
        print(f"📊 Найдено учеников: {len(students)}")
        print("\n📋 Список учеников:")
        print("-" * 80)
        
        for i, student in enumerate(students, 1):
            user_id = student["user_id"]
            label = student["label"]
            plan_name = student["plan_name"]
            plan_code = student["plan_code"]
            
            print(f"{i:2d}. {label} (ID: {user_id}) - {plan_name} ({plan_code})")
        
        print("\n" + "=" * 50)
        print("✅ Тест завершен успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_students_list()
