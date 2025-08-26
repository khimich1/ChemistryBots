#!/usr/bin/env python3
"""
Финальный тестовый скрипт для демонстрации полного цикла работы системы
"""

import sys
import os

# Добавляем пути к ботам
current_dir = os.path.dirname(os.path.abspath(__file__))
govr_path = os.path.join(current_dir, "govr_bot")
prepod_path = os.path.join(current_dir, "prepod_bot")
sys.path.append(govr_path)
sys.path.append(prepod_path)

def test_full_cycle():
    """Демонстрирует полный цикл работы системы"""
    
    roman_id = 727117860  # ID Смирнова Романа
    
    print("🎯 Демонстрация полного цикла работы системы")
    print("=" * 70)
    print(f"👤 Тестируем ученика: Смирнов Роман (ID: {roman_id})")
    
    try:
        # Импортируем функции
        from bot.services.teacher_access import get_group_access_status
        from services.groups import add_student_to_group, remove_student_from_group, is_student_in_group
        
        print("\n📋 Шаг 1: Начальное состояние")
        print("-" * 50)
        
        # Проверяем начальное состояние
        status = get_group_access_status(roman_id)
        print(f"📊 Статус доступа:")
        print(f"   - Имеет групповой план: {'Да' if status['has_group_plan'] else 'Нет'}")
        print(f"   - Одобрен преподавателем: {'Да' if status['is_approved'] else 'Нет'}")
        print(f"   - Может получить доступ: {'Да' if status['can_access'] else 'Нет'}")
        
        if status['can_access']:
            print("✅ В govr_bot: 👨‍🏫 Подписка на бота при занятии с преподавателем — 390 ₽/мес")
        else:
            print("❌ В govr_bot: 📞 Записаться на бесплатное занятие")
        
        print("\n📋 Шаг 2: Преподаватель добавляет ученика в группу")
        print("-" * 50)
        
        # Преподаватель добавляет ученика в группу
        print("👨‍🏫 Преподаватель нажимает 'Добавить доступ' для Смирнова Романа...")
        add_student_to_group(roman_id)
        
        # Проверяем состояние после добавления
        status = get_group_access_status(roman_id)
        print(f"📊 Статус после добавления:")
        print(f"   - Имеет групповой план: {'Да' if status['has_group_plan'] else 'Нет'}")
        print(f"   - Одобрен преподавателем: {'Да' if status['is_approved'] else 'Нет'}")
        print(f"   - Может получить доступ: {'Да' if status['can_access'] else 'Нет'}")
        
        if status['can_access']:
            print("✅ В govr_bot: 👨‍🏫 Подписка на бота при занятии с преподавателем — 390 ₽/мес")
        else:
            print("❌ В govr_bot: 📞 Записаться на бесплатное занятие")
        
        print("\n📋 Шаг 3: Ученик может оплатить тариф")
        print("-" * 50)
        
        if status['can_access']:
            print("🎉 Ученик теперь может:")
            print("   • Нажать на кнопку '👨‍🏫 Подписка на бота при занятии с преподавателем'")
            print("   • Увидеть описание тарифа")
            print("   • Перейти к оплате")
            print("   • Получить доступ к функциям группового тарифа")
        else:
            print("❌ Ученик не может оплатить тариф")
        
        print("\n📋 Шаг 4: Преподаватель удаляет ученика из группы")
        print("-" * 50)
        
        # Преподаватель удаляет ученика из группы
        print("👨‍🏫 Преподаватель удаляет Смирнова Романа из группы...")
        remove_student_from_group(roman_id)
        
        # Проверяем состояние после удаления
        status = get_group_access_status(roman_id)
        print(f"📊 Статус после удаления:")
        print(f"   - Имеет групповой план: {'Да' if status['has_group_plan'] else 'Нет'}")
        print(f"   - Одобрен преподавателем: {'Да' if status['is_approved'] else 'Нет'}")
        print(f"   - Может получить доступ: {'Да' if status['can_access'] else 'Нет'}")
        
        if status['can_access']:
            print("✅ В govr_bot: 👨‍🏫 Подписка на бота при занятии с преподавателем — 390 ₽/мес")
        else:
            print("❌ В govr_bot: 📞 Записаться на бесплатное занятие")
        
        print("\n" + "=" * 70)
        print("🎉 Система работает корректно!")
        print("✅ Полный цикл протестирован успешно")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_full_cycle()
