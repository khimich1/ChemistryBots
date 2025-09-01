import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from .answer_db import get_db_connection, get_conn

class UserAnalytics:
    """Аналитика пользователей бота"""
    
    # Список ID администраторов (исключаем из статистики)
    ADMIN_IDS = [727117860]  # Замени на свой Telegram ID
    
    @staticmethod
    def get_total_users() -> int:
        """Общее количество пользователей"""
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(DISTINCT user_id) FROM user_profiles")
            return c.fetchone()[0]
    
    @staticmethod
    def get_active_users(days: int = 7) -> int:
        """Количество активных пользователей за последние N дней"""
        with get_db_connection() as conn:
            c = conn.cursor()
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            
            # Пользователи, которые что-то делали за последние N дней
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id FROM test_answers WHERE answer_time > ?
                    UNION
                    SELECT user_id FROM theory_task_answers WHERE created_at > ?
                    UNION
                    SELECT user_id FROM flashcards_practice_log WHERE created_at > ?
                )
            """, (cutoff_date, cutoff_date, cutoff_date))
            return c.fetchone()[0]
    
    @staticmethod
    def get_new_users(days: int = 7) -> int:
        """Количество новых пользователей за последние N дней"""
        with get_db_connection() as conn:
            c = conn.cursor()
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
                SELECT COUNT(*) FROM user_profiles 
                WHERE created_at > ?
            """, (cutoff_date,))
            return c.fetchone()[0]
    
    @staticmethod
    def get_user_session_duration(user_id: int) -> Optional[float]:
        """Длительность сессии пользователя в минутах"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Получаем первое и последнее действие пользователя
            c.execute("""
                SELECT MIN(answer_time), MAX(answer_time) 
                FROM test_answers 
                WHERE user_id = ?
            """, (user_id,))
            result = c.fetchone()
            
            if not result[0] or not result[1]:
                return None
                
            try:
                first_action = datetime.strptime(result[0], "%Y-%m-%d %H:%M:%S")
                last_action = datetime.strptime(result[1], "%Y-%m-%d %H:%M:%S")
                duration = (last_action - first_action).total_seconds() / 60
                return round(duration, 2)
            except ValueError:
                return None
    
    @staticmethod
    def get_user_activity_summary(user_id: int) -> Dict:
        """Полная сводка активности пользователя"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Основная информация
            c.execute("""
                SELECT username, full_name, created_at 
                FROM user_profiles 
                WHERE user_id = ?
            """, (user_id,))
            profile = c.fetchone()
            
            if not profile:
                return {}
            
            # Статистика тестов
            c.execute("""
                SELECT COUNT(*), SUM(is_correct) 
                FROM test_answers 
                WHERE user_id = ?
            """, (user_id,))
            test_stats = c.fetchone()
            
            # Статистика теории
            c.execute("""
                SELECT COUNT(*), SUM(is_correct) 
                FROM theory_task_answers 
                WHERE user_id = ?
            """, (user_id,))
            theory_stats = c.fetchone()
            
            # Статистика карточек
            c.execute("""
                SELECT COUNT(*) 
                FROM flashcards_practice_log 
                WHERE user_id = ?
            """, (user_id,))
            cards_count = c.fetchone()[0]
            
            # Время последней активности
            c.execute("""
                SELECT MAX(answer_time) FROM test_answers WHERE user_id = ?
                UNION
                SELECT MAX(created_at) FROM theory_task_answers WHERE user_id = ?
                UNION
                SELECT MAX(created_at) FROM flashcards_practice_log WHERE user_id = ?
            """, (user_id, user_id, user_id))
            last_activity = max([row[0] for row in c.fetchall() if row[0]])
            
            return {
                "user_id": user_id,
                "username": profile[0],
                "full_name": profile[1],
                "created_at": profile[2],
                "last_activity": last_activity,
                "total_tests": test_stats[0] or 0,
                "correct_tests": test_stats[1] or 0,
                "total_theory": theory_stats[0] or 0,
                "correct_theory": theory_stats[1] or 0,
                "total_cards": cards_count,
                "session_duration_minutes": UserAnalytics.get_user_session_duration(user_id)
            }
    
    @staticmethod
    def get_daily_stats(days: int = 30) -> List[Dict]:
        """Статистика по дням за последние N дней"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            stats = []
            for i in range(days):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                
                # Новые пользователи
                c.execute("""
                    SELECT COUNT(*) FROM user_profiles 
                    WHERE DATE(created_at) = ?
                """, (date,))
                new_users = c.fetchone()[0]
                
                # Активные пользователи
                c.execute("""
                    SELECT COUNT(DISTINCT user_id) FROM (
                        SELECT user_id FROM test_answers WHERE DATE(answer_time) = ?
                        UNION
                        SELECT user_id FROM theory_task_answers WHERE DATE(created_at) = ?
                        UNION
                        SELECT user_id FROM flashcards_practice_log WHERE DATE(created_at) = ?
                    )
                """, (date, date, date))
                active_users = c.fetchone()[0]
                
                # Количество тестов
                c.execute("""
                    SELECT COUNT(*) FROM test_answers 
                    WHERE DATE(answer_time) = ?
                """, (date,))
                tests_count = c.fetchone()[0]
                
                stats.append({
                    "date": date,
                    "new_users": new_users,
                    "active_users": active_users,
                    "tests_count": tests_count
                })
            
            return stats[::-1]  # От старых к новым
    
    @staticmethod
    def get_top_users(limit: int = 10) -> List[Dict]:
        """Топ пользователей по активности"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            c.execute("""
                SELECT 
                    u.user_id,
                    u.username,
                    u.full_name,
                    COUNT(t.id) as tests_count,
                    SUM(t.is_correct) as correct_tests,
                    COUNT(th.id) as theory_count,
                    SUM(th.is_correct) as correct_theory,
                    COUNT(f.id) as cards_count
                FROM user_profiles u
                LEFT JOIN test_answers t ON u.user_id = t.user_id
                LEFT JOIN theory_task_answers th ON u.user_id = th.user_id
                LEFT JOIN flashcards_practice_log f ON u.user_id = f.user_id
                GROUP BY u.user_id
                ORDER BY (tests_count + theory_count + cards_count) DESC
                LIMIT ?
            """, (limit,))
            
            results = []
            for row in c.fetchall():
                results.append({
                    "user_id": row[0],
                    "username": row[1],
                    "full_name": row[2],
                    "tests_count": row[3],
                    "correct_tests": row[4] or 0,
                    "theory_count": row[5],
                    "correct_theory": row[6] or 0,
                    "cards_count": row[7],
                    "total_activity": (row[3] or 0) + (row[5] or 0) + (row[7] or 0)
                })
            
            return results
    
    @staticmethod
    def get_user_plans_stats() -> Dict:
        """Статистика по тарифам пользователей"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Создаём таблицу если её нет
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_plans(
                    user_id INTEGER PRIMARY KEY,
                    plan_code TEXT,
                    started_at TEXT
                )
            """)
            
            c.execute("""
                SELECT 
                    plan_code,
                    COUNT(*) as user_count
                FROM user_plans 
                GROUP BY plan_code
                ORDER BY user_count DESC
            """)
            
            plans = {}
            total_plans = 0
            for row in c.fetchall():
                plan_code, count = row
                plans[plan_code or "FREE"] = count
                total_plans += count
            
            # Пользователи без тарифа
            c.execute("SELECT COUNT(*) FROM user_profiles")
            total_users = c.fetchone()[0]
            plans["FREE"] = plans.get("FREE", 0) + (total_users - total_plans)
            
            return plans
    
    @staticmethod
    def get_user_acquisition_stats() -> Dict:
        """Статистика по источникам пользователей (deep-links)"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            c.execute("""
                SELECT 
                    start_param,
                    COUNT(*) as user_count
                FROM acquisition 
                WHERE start_param IS NOT NULL AND start_param != ''
                GROUP BY start_param
                ORDER BY user_count DESC
                LIMIT 20
            """)
            
            sources = {}
            for row in c.fetchall():
                source, count = row
                sources[source] = count
            
            # Пользователи без источника
            c.execute("""
                SELECT COUNT(*) FROM acquisition 
                WHERE start_param IS NULL OR start_param = ''
            """)
            no_source = c.fetchone()[0]
            if no_source > 0:
                sources["Прямой переход"] = no_source
            
            return sources
    
    @staticmethod
    def get_user_retention_stats(days: int = 30) -> Dict:
        """Статистика удержания пользователей"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Пользователи, которые были активны в прошлом месяце
            past_month = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id FROM test_answers WHERE answer_time < ?
                    UNION
                    SELECT user_id FROM theory_task_answers WHERE created_at < ?
                    UNION
                    SELECT user_id FROM flashcards_practice_log WHERE created_at < ?
                )
            """, (past_month, past_month, past_month))
            past_active = c.fetchone()[0]
            
            # Из них активны сейчас
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id FROM test_answers WHERE answer_time >= ?
                    UNION
                    SELECT user_id FROM theory_task_answers WHERE created_at >= ?
                    UNION
                    SELECT user_id FROM flashcards_practice_log WHERE created_at >= ?
                )
            """, (past_month, past_month, past_month))
            current_active = c.fetchone()[0]
            
            retention_rate = (current_active / past_active * 100) if past_active > 0 else 0
            
            return {
                "past_active": past_active,
                "current_active": current_active,
                "retention_rate": round(retention_rate, 2)
            }
    
    @staticmethod
    def get_user_retention_stats_7_days() -> Dict:
        """Статистика удержания пользователей за последние 7 дней"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Пользователи, которые были активны неделю назад
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id FROM test_answers WHERE answer_time < ?
                    UNION
                    SELECT user_id FROM theory_task_answers WHERE created_at < ?
                    UNION
                    SELECT user_id FROM flashcards_practice_log WHERE created_at < ?
                )
            """, (week_ago, week_ago, week_ago))
            week_ago_active = c.fetchone()[0]
            
            # Из них активны за последние 7 дней
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id FROM test_answers WHERE answer_time >= ?
                    UNION
                    SELECT user_id FROM theory_task_answers WHERE created_at >= ?
                    UNION
                    SELECT user_id FROM flashcards_practice_log WHERE created_at >= ?
                )
            """, (week_ago, week_ago, week_ago))
            current_week_active = c.fetchone()[0]
            
            # Пользователи, активные только за последние 7 дней (новые или вернувшиеся)
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id FROM test_answers WHERE answer_time >= ?
                    UNION
                    SELECT user_id FROM theory_task_answers WHERE created_at >= ?
                    UNION
                    SELECT user_id FROM flashcards_practice_log WHERE created_at >= ?
                )
            """, (week_ago, week_ago, week_ago))
            total_week_active = c.fetchone()[0]
            
            # Вычисляем удержание
            retention_rate = (current_week_active / week_ago_active * 100) if week_ago_active > 0 else 0
            
            # Вычисляем рост
            growth_rate = ((total_week_active - week_ago_active) / week_ago_active * 100) if week_ago_active > 0 else 0
            
            return {
                "week_ago_active": week_ago_active,
                "current_week_active": current_week_active,
                "total_week_active": total_week_active,
                "retention_rate": round(retention_rate, 2),
                "growth_rate": round(growth_rate, 2)
            }
    
    @staticmethod
    def get_user_learning_patterns() -> Dict:
        """Анализ паттернов обучения пользователей"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Время суток активности
            c.execute("""
                SELECT 
                    strftime('%H', answer_time) as hour,
                    COUNT(*) as activity_count
                FROM test_answers 
                WHERE answer_time > date('now', '-7 days')
                GROUP BY hour
                ORDER BY hour
            """)
            
            hourly_activity = {}
            for row in c.fetchall():
                hour, count = row
                hourly_activity[int(hour)] = count
            
            # Дни недели активности
            c.execute("""
                SELECT 
                    strftime('%w', answer_time) as weekday,
                    COUNT(*) as activity_count
                FROM test_answers 
                WHERE answer_time > date('now', '-30 days')
                GROUP BY weekday
                ORDER BY weekday
            """)
            
            weekday_activity = {}
            weekdays = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
            for row in c.fetchall():
                weekday_num, count = row
                weekday_name = weekdays[int(weekday_num)]
                weekday_activity[weekday_name] = count
            
            return {
                "hourly_activity": hourly_activity,
                "weekday_activity": weekday_activity
            }
    
    @staticmethod
    def get_user_performance_stats() -> Dict:
        """Статистика успеваемости пользователей"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Проверяем, есть ли колонка is_correct в таблицах
            c.execute("PRAGMA table_info(test_answers)")
            test_columns = {row[1] for row in c.fetchall()}
            test_has_is_correct = 'is_correct' in test_columns
            
            c.execute("PRAGMA table_info(theory_task_answers)")
            theory_columns = {row[1] for row in c.fetchall()}
            theory_has_is_correct = 'is_correct' in theory_columns
            
            # Средний балл по тестам (если есть колонка is_correct)
            avg_test_score = 0
            total_test_answers = 0
            if test_has_is_correct:
                c.execute("""
                    SELECT 
                        AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) as avg_score,
                        COUNT(*) as total_answers
                    FROM test_answers
                """)
                
                test_stats = c.fetchone()
                avg_test_score = (test_stats[0] or 0) * 100
                total_test_answers = test_stats[1] or 0
            else:
                # Если колонки нет, считаем только количество ответов
                c.execute("SELECT COUNT(*) FROM test_answers")
                total_test_answers = c.fetchone()[0]
            
            # Средний балл по теории (если есть колонка is_correct)
            avg_theory_score = 0
            total_theory_answers = 0
            if theory_has_is_correct:
                c.execute("""
                    SELECT 
                        AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) as avg_score,
                        COUNT(*) as total_answers
                    FROM theory_task_answers
                """)
                
                theory_stats = c.fetchone()
                avg_theory_score = (theory_stats[0] or 0) * 100
                total_theory_answers = theory_stats[1] or 0
            else:
                # Если колонки нет, считаем только количество ответов
                c.execute("SELECT COUNT(*) FROM theory_task_answers")
                total_theory_answers = c.fetchone()[0]
            
            # Распределение по уровням успеваемости (только если есть колонка is_correct)
            performance_levels = {}
            if test_has_is_correct:
                c.execute("""
                    SELECT 
                        CASE 
                            WHEN AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) >= 0.8 THEN 'Отличники (80%+)'
                            WHEN AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) >= 0.6 THEN 'Хорошисты (60-79%)'
                            WHEN AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) >= 0.4 THEN 'Троечники (40-59%)'
                            ELSE 'Нужна помощь (<40%)'
                        END as level,
                        COUNT(*) as user_count
                    FROM (
                        SELECT user_id, AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) as avg_score
                        FROM test_answers 
                        GROUP BY user_id
                        HAVING COUNT(*) >= 5
                    )
                    GROUP BY level
                """)
                
                for row in c.fetchall():
                    level, count = row
                    performance_levels[level] = count
            else:
                performance_levels["Оценка недоступна"] = 0
            
            return {
                "avg_test_score": round(avg_test_score, 1),
                "avg_theory_score": round(avg_theory_score, 1),
                "total_test_answers": total_test_answers,
                "total_theory_answers": total_theory_answers,
                "performance_levels": performance_levels,
                "test_scoring_available": test_has_is_correct,
                "theory_scoring_available": theory_has_is_correct
            }
    
    @staticmethod
    def get_user_engagement_metrics() -> Dict:
        """Метрики вовлечённости пользователей"""
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Пользователи с высокой активностью (более 10 действий в день)
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id, COUNT(*) as daily_actions
                    FROM test_answers 
                    WHERE answer_time > date('now', '-1 day')
                    GROUP BY user_id
                    HAVING daily_actions >= 10
                )
            """)
            high_engagement = c.fetchone()[0]
            
            # Пользователи со средней активностью (3-9 действий в день)
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id, COUNT(*) as daily_actions
                    FROM test_answers 
                    WHERE answer_time > date('now', '-1 day')
                    GROUP BY user_id
                    HAVING daily_actions BETWEEN 3 AND 9
                )
            """)
            medium_engagement = c.fetchone()[0]
            
            # Пользователи с низкой активностью (1-2 действия в день)
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id, COUNT(*) as daily_actions
                    FROM test_answers 
                    WHERE answer_time > date('now', '-1 day')
                    GROUP BY user_id
                    HAVING daily_actions BETWEEN 1 AND 2
                )
            """)
            low_engagement = c.fetchone()[0]
            
            # Пользователи, которые не были активны сегодня
            c.execute("""
                SELECT COUNT(DISTINCT user_id) FROM user_profiles
                WHERE user_id NOT IN (
                    SELECT DISTINCT user_id FROM test_answers 
                    WHERE answer_time > date('now', '-1 day')
                    UNION
                    SELECT DISTINCT user_id FROM theory_task_answers 
                    WHERE created_at > date('now', '-1 day')
                    UNION
                    SELECT DISTINCT user_id FROM flashcards_practice_log 
                    WHERE created_at > date('now', '-1 day')
                )
            """)
            inactive_today = c.fetchone()[0]
            
            return {
                "high_engagement": high_engagement,
                "medium_engagement": medium_engagement,
                "low_engagement": low_engagement,
                "inactive_today": inactive_today
            }
    
    @staticmethod
    def get_stats_exclude_admin() -> Dict:
        """Полная статистика бота без учёта активности админов"""
        with get_db_connection() as conn:
            c = conn.cursor()
            admin_ids_str = ','.join(map(str, UserAnalytics.ADMIN_IDS))
            
            # Общее количество пользователей (без админов)
            c.execute(f"SELECT COUNT(DISTINCT user_id) FROM user_profiles WHERE user_id NOT IN ({admin_ids_str})")
            total_users = c.fetchone()[0]
            
            # Активные за неделю (без админов)
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute(f"""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id FROM test_answers WHERE answer_time > ? AND user_id NOT IN ({admin_ids_str})
                    UNION
                    SELECT user_id FROM theory_task_answers WHERE created_at > ? AND user_id NOT IN ({admin_ids_str})
                    UNION
                    SELECT user_id FROM flashcards_practice_log WHERE created_at > ? AND user_id NOT IN ({admin_ids_str})
                )
            """, (week_ago, week_ago, week_ago))
            active_week = c.fetchone()[0]
            
            # Активные за месяц (без админов)
            month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute(f"""
                SELECT COUNT(DISTINCT user_id) FROM (
                    SELECT user_id FROM test_answers WHERE answer_time > ? AND user_id NOT IN ({admin_ids_str})
                    UNION
                    SELECT user_id FROM theory_task_answers WHERE created_at > ? AND user_id NOT IN ({admin_ids_str})
                    UNION
                    SELECT user_id FROM flashcards_practice_log WHERE created_at > ? AND user_id NOT IN ({admin_ids_str})
                )
            """, (month_ago, month_ago, month_ago))
            active_month = c.fetchone()[0]
            
            # Новые за неделю (без админов)
            c.execute(f"""
                SELECT COUNT(*) FROM user_profiles 
                WHERE created_at > ? AND user_id NOT IN ({admin_ids_str})
            """, (week_ago,))
            new_week = c.fetchone()[0]
            
            # Новые за месяц (без админов)
            c.execute(f"""
                SELECT COUNT(*) FROM user_profiles 
                WHERE created_at > ? AND user_id NOT IN ({admin_ids_str})
            """, (month_ago,))
            new_month = c.fetchone()[0]
            
            # Статистика за сегодня (без админов)
            today = datetime.now().strftime("%Y-%m-%d")
            c.execute(f"""
                SELECT COUNT(*) FROM test_answers 
                WHERE DATE(answer_time) = ? AND user_id NOT IN ({admin_ids_str})
            """, (today,))
            tests_today = c.fetchone()[0]
            
            c.execute(f"""
                SELECT COUNT(DISTINCT user_id) FROM test_answers 
                WHERE DATE(answer_time) = ? AND user_id NOT IN ({admin_ids_str})
            """, (today,))
            users_today = c.fetchone()[0]
            
            return {
                "total_users": total_users,
                "active_week": active_week,
                "active_month": active_month,
                "new_week": new_week,
                "new_month": new_month,
                "tests_today": tests_today,
                "users_today": users_today
            }

# Функции для быстрого доступа
def get_user_count() -> int:
    """Быстрое получение количества пользователей"""
    return UserAnalytics.get_total_users()

def get_active_user_count(days: int = 7) -> int:
    """Быстрое получение количества активных пользователей"""
    return UserAnalytics.get_active_users(days)

def get_user_stats(user_id: int) -> Dict:
    """Быстрое получение статистики пользователя"""
    return UserAnalytics.get_user_activity_summary(user_id)
