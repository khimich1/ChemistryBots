#!/usr/bin/env python3
"""
Тестовый скрипт для проверки логики доступа к групповому тарифу
"""

import sys
import os

# Добавляем путь к govr_bot
current_dir = os.path.dirname(os.path.abspath(__file__))
govr_path = os.path.join(current_dir, "govr_bot")
sys.path.append(govr_path)

def test_group_access():
    """Тестирует логику доступа к групповому тарифу"""
    
    print("🧪 Тестирование логики доступа к групповому тарифу")
    print("=" * 60)
    
    try:
        from bot.services.teacher_access import (
            is_student_approved_by_teacher,
            can_access_group_tariff,
            get_group_access_status
        )
        
        # Тестируем разных учеников
        test_users = [
            {"id": 1001, "name": "Иван Петров", "plan": "free"},
            {"id": 1002, "name": "Мария Сидорова", "plan": "group"},
            {"id": 1003, "name": "Алексей Кузнецов", "plan": "self"},
            {"id": 999999, "name": "Неизвестный ученик", "plan": "free"},
        ]
        
        for user in test_users:
            user_id = user["id"]
            user_name = user["name"]
            user_plan = user["plan"]
            
            print(f"\n👤 Тестируем: {user_name} (ID: {user_id}, План: {user_plan})")
            print("-" * 50)
            
            # Проверяем одобрение преподавателем
            is_approved = is_student_approved_by_teacher(user_id)
            print(f"✅ Одобрен преподавателем: {'Да' if is_approved else 'Нет'}")
            
            # Проверяем доступ к групповому тарифу
            can_access = can_access_group_tariff(user_id)
            print(f"🔓 Может получить доступ к групповому тарифу: {'Да' if can_access else 'Нет'}")
            
            # Получаем полный статус
            status = get_group_access_status(user_id)
            print(f"📊 Статус доступа:")
            print(f"   - Имеет групповой план: {'Да' if status['has_group_plan'] else 'Нет'}")
            print(f"   - Одобрен преподавателем: {'Да' if status['is_approved'] else 'Нет'}")
            print(f"   - Текущий план: {status['current_plan']}")
            print(f"   - Может получить доступ: {'Да' if status['can_access'] else 'Нет'}")
        
        print("\n" + "=" * 60)
        print("🎯 Демонстрация добавления ученика в группу:")
        print("-" * 50)
        
        # Добавляем тестового ученика в группу
        test_user_id = 1001  # Иван Петров
        
        # Импортируем функции из prepod_bot
        prepod_path = os.path.join(current_dir, "prepod_bot")
        sys.path.append(prepod_path)
        
        from services.groups import add_student_to_group, remove_student_from_group
        
        print(f"👤 Добавляем {test_users[0]['name']} в группу...")
        add_student_to_group(test_user_id)
        
        # Проверяем статус после добавления
        is_approved = is_student_approved_by_teacher(test_user_id)
        status = get_group_access_status(test_user_id)
        
        print(f"✅ После добавления в группу:")
        print(f"   - Одобрен преподавателем: {'Да' if is_approved else 'Нет'}")
        print(f"   - Может получить доступ: {'Да' if status['can_access'] else 'Нет'}")
        
        # Удаляем из группы
        print(f"🔄 Удаляем из группы...")
        remove_student_from_group(test_user_id)
        
        # Проверяем статус после удаления
        is_approved = is_student_approved_by_teacher(test_user_id)
        status = get_group_access_status(test_user_id)
        
        print(f"❌ После удаления из группы:")
        print(f"   - Одобрен преподавателем: {'Да' if is_approved else 'Нет'}")
        print(f"   - Может получить доступ: {'Да' if status['can_access'] else 'Нет'}")
        
        print("\n" + "=" * 60)
        print("✅ Тест завершен успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_group_access()
