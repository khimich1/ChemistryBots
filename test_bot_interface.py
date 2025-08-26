#!/usr/bin/env python3
"""
Тестовый скрипт для демонстрации интерфейса бота
"""

import sys
import os

# Добавляем путь к prepod_bot
current_dir = os.path.dirname(os.path.abspath(__file__))
prepod_path = os.path.join(current_dir, "prepod_bot")
sys.path.append(prepod_path)

def test_bot_interface():
    """Демонстрирует интерфейс бота"""
    
    print("🤖 Демонстрация интерфейса бота")
    print("=" * 50)
    
    try:
        from services.groups import (
            get_all_students_with_plans,
            add_student_to_group,
            remove_student_from_group,
            is_student_in_group
        )
        
        # Получаем список учеников
        students = get_all_students_with_plans()
        
        print(f"📊 Всего учеников: {len(students)}")
        print("\n📋 Список учеников (как в боте):")
        print("-" * 80)
        
        # Показываем первых 10 учеников
        for i, student in enumerate(students[:10], 1):
            user_id = student["user_id"]
            label = student["label"]
            plan_name = student["plan_name"]
            is_added = is_student_in_group(user_id)
            
            # Статус как в боте
            status = "✅ Добавлен доступ" if is_added else "➕ Добавить доступ"
            
            print(f"{i:2d}. {label} - {plan_name} - {status}")
        
        if len(students) > 10:
            print(f"... и еще {len(students) - 10} учеников")
        
        print("\n" + "=" * 50)
        print("🎯 Демонстрация добавления ученика в группу:")
        print("-" * 50)
        
        # Добавляем тестового ученика
        test_user_id = 1001  # Иван Петров
        test_student = next((s for s in students if s["user_id"] == test_user_id), None)
        
        if test_student:
            print(f"👤 Добавляем: {test_student['label']} - {test_student['plan_name']}")
            add_student_to_group(test_user_id)
            
            # Показываем обновленный статус
            is_added = is_student_in_group(test_user_id)
            status = "✅ Добавлен доступ" if is_added else "➕ Добавить доступ"
            print(f"📝 Новый статус: {test_student['label']} - {test_student['plan_name']} - {status}")
            
            # Удаляем обратно
            remove_student_from_group(test_user_id)
            print("🔄 Удалили из группы")
        
        print("\n" + "=" * 50)
        print("✅ Демонстрация завершена!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_bot_interface()
