# database.py
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
import json
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import List, Dict, Optional, Any
import os
from dotenv import load_dotenv

load_dotenv()

# Конфигурация PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")

# Пул подключений
try:
    pool = ThreadedConnectionPool(
        minconn=1,
        maxconn=10,
        dsn=DATABASE_URL
    )
    print("✅ Пул подключений к PostgreSQL создан")
except Exception as e:
    print(f"❌ Ошибка создания пула подключений: {e}")
    pool = None


@contextmanager
def get_db_connection():
    """Контекстный менеджер для подключения к БД"""
    conn = None
    try:
        if pool:
            conn = pool.getconn()
        else:
            conn = psycopg2.connect(DATABASE_URL)
        yield conn
    finally:
        if conn:
            if pool:
                pool.putconn(conn)
            else:
                conn.close()


class Database:
    """Класс для работы с базой данных PostgreSQL"""
    
    @staticmethod
    def init_database():
        """Инициализация базы данных"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    name TEXT,
                    birth_date TEXT,
                    age INTEGER,
                    registration_date TIMESTAMP,
                    last_activity TIMESTAMP,
                    messages_count INTEGER DEFAULT 0
                )
            ''')
            
            # Таблица для последнего расклада
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS last_spread (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    question TEXT,
                    cards TEXT,
                    positions TEXT,
                    spread_name TEXT,
                    spread_topic TEXT,
                    created_at TIMESTAMP
                )
            ''')
            
            # Таблица для временного хранения регистрационных данных
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS registration_temp (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    name TEXT,
                    birth_date TEXT,
                    messages TEXT,
                    updated_at TIMESTAMP
                )
            ''')
            
            # Таблица для истории сообщений (последние 20)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    role TEXT,
                    content TEXT,
                    created_at TIMESTAMP
                )
            ''')
            
            # Таблица для подписок на карту дня
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_card_subscriptions (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    subscribed_at TIMESTAMP,
                    last_sent_date DATE
                )
            ''')
            
            # Таблица для отслеживания предложений подписки
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS subscription_offers (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    last_offer_date TIMESTAMP,
                    offer_count INTEGER DEFAULT 0
                )
            ''')
            
            # Создаем индексы для оптимизации
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_spread_user_id ON last_spread(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_spread_created_at ON last_spread(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_history_user_id ON message_history(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_history_created_at ON message_history(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_registration_temp_user_id ON registration_temp(user_id)')
            
            conn.commit()
            print("✅ База данных PostgreSQL инициализирована")
    
    @staticmethod
    def register_user(user_id: int, username: str, first_name: str, last_name: str, 
                    name: str, birth_date: str):
        """Регистрация нового пользователя с датой рождения"""
        # Вычисляем возраст из даты рождения
        age = Database._calculate_age(birth_date)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users 
                (user_id, username, first_name, last_name, name, birth_date, age,
                registration_date, last_activity, messages_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    name = EXCLUDED.name,
                    birth_date = EXCLUDED.birth_date,
                    age = EXCLUDED.age,
                    last_activity = EXCLUDED.last_activity
            ''', (
                user_id, username, first_name, last_name, name, birth_date, age,
                datetime.now(), datetime.now(), 0
            ))
            cursor.execute('DELETE FROM registration_temp WHERE user_id = %s', (user_id,))
            conn.commit()
    
    @staticmethod
    def update_user_activity(user_id: int):
        """Обновляет время последней активности и счетчик сообщений"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET last_activity = %s, 
                    messages_count = messages_count + 1
                WHERE user_id = %s
            ''', (datetime.now(), user_id))
            conn.commit()
    
    @staticmethod
    def get_user_info(user_id: int) -> Optional[Dict]:
        """Получает информацию о пользователе"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    def save_temp_registration(user_id: int, name: Optional[str], birth_date: Optional[str], message: str):
        """Сохраняет временные данные регистрации"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute('SELECT messages FROM registration_temp WHERE user_id = %s', (user_id,))
            row = cursor.fetchone()
            
            messages = []
            if row:
                messages = json.loads(row['messages'])
            
            messages.append({
                'text': message,
                'timestamp': datetime.now().isoformat()
            })
            
            messages = messages[-5:]
            
            cursor.execute('''
                INSERT INTO registration_temp (user_id, name, birth_date, messages, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    birth_date = EXCLUDED.birth_date,
                    messages = EXCLUDED.messages,
                    updated_at = EXCLUDED.updated_at
            ''', (user_id, name, birth_date, json.dumps(messages), datetime.now()))
            conn.commit()
    
    @staticmethod
    def get_temp_registration(user_id: int) -> Optional[Dict]:
        """Получает временные данные регистрации"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT * FROM registration_temp WHERE user_id = %s', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    def clear_temp_registration(user_id: int):
        """Очищает временные данные регистрации"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM registration_temp WHERE user_id = %s', (user_id,))
            conn.commit()
    
    @staticmethod
    def save_last_spread(user_id: int, question: str, cards: List[int], 
                         positions: List[str], spread_name: str, spread_topic: str):
        """Сохраняет последний расклад пользователя"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO last_spread 
                (user_id, question, cards, positions, spread_name, spread_topic, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                user_id, question[:200], json.dumps(cards), 
                json.dumps(positions), spread_name, spread_topic, datetime.now()
            ))
            conn.commit()
    
    @staticmethod
    def get_last_spread(user_id: int) -> Optional[Dict]:
        """Получает последний расклад пользователя"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('''
                SELECT * FROM last_spread 
                WHERE user_id = %s 
                ORDER BY created_at DESC 
                LIMIT 1
            ''', (user_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                result['cards'] = json.loads(result['cards'])
                result['positions'] = json.loads(result['positions'])
                return result
            return None
    
    @staticmethod
    def save_message_to_history(user_id: int, role: str, content: str):
        """Сохраняет сообщение в историю"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO message_history (user_id, role, content, created_at)
                VALUES (%s, %s, %s, %s)
            ''', (user_id, role, content, datetime.now()))
            
            # Оставляем только последние 20 сообщений
            cursor.execute('''
                DELETE FROM message_history 
                WHERE user_id = %s AND id NOT IN (
                    SELECT id FROM message_history 
                    WHERE user_id = %s 
                    ORDER BY created_at DESC 
                    LIMIT 20
                )
            ''', (user_id, user_id))
            
            conn.commit()
    
    @staticmethod
    def get_message_history(user_id: int) -> List[Dict]:
        """Получает историю сообщений пользователя"""
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('''
                SELECT role, content FROM message_history 
                WHERE user_id = %s 
                ORDER BY created_at ASC
            ''', (user_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def clear_message_history(user_id: int):
        """Очищает историю сообщений пользователя"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM message_history WHERE user_id = %s', (user_id,))
            conn.commit()
    
    @staticmethod
    def cleanup_old_data(days: int = 30):
        """Очищает старые данные из БД"""
        threshold = datetime.now() - timedelta(days=days)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM message_history WHERE created_at < %s', (threshold,))
            cursor.execute('DELETE FROM last_spread WHERE created_at < %s', (threshold,))
            cursor.execute('DELETE FROM registration_temp WHERE updated_at < %s', (threshold,))
            conn.commit()
        
        print(f"🔄 Очистка данных старше {days} дней выполнена")

    @staticmethod
    def change_name(user_id: int, new_name: str):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET name = %s WHERE user_id = %s', (new_name, user_id))
            conn.commit()
        print(f'Имя пользователя user_id: {user_id} изменено на: {new_name}')

    @staticmethod
    def change_birth_date(user_id: int, new_birth_date: str):
        """Изменяет дату рождения пользователя и пересчитывает возраст"""
        # Проверяем, что дата корректна
        try:
            datetime.strptime(new_birth_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Неверный формат даты")
        
        age = Database._calculate_age(new_birth_date)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET birth_date = %s, age = %s WHERE user_id = %s', 
                        (new_birth_date, age, user_id))
            conn.commit()
        print(f'Дата рождения пользователя user_id: {user_id} изменена на: {new_birth_date}')

    @staticmethod
    def _calculate_age(birth_date_str: str) -> int:
        """Вычисляет возраст из даты рождения"""
        try:
            birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
            today = datetime.now().date()
            age = today.year - birth_date.year
            # Проверяем, был ли уже день рождения в этом году
            if today.month < birth_date.month or (today.month == birth_date.month and today.day < birth_date.day):
                age -= 1
            return age
        except:
            return 0

    @staticmethod
    def add_subscription(user_id: int):
        """Добавляет подписку на карту дня"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO daily_card_subscriptions (user_id, subscribed_at, last_sent_date)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    subscribed_at = EXCLUDED.subscribed_at,
                    last_sent_date = EXCLUDED.last_sent_date
            ''', (user_id, datetime.now(), None))
            conn.commit()

    @staticmethod
    def remove_subscription(user_id: int):
        """Удаляет подписку на карту дня"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM daily_card_subscriptions WHERE user_id = %s', (user_id,))
            conn.commit()

    @staticmethod
    def is_subscribed(user_id: int) -> bool:
        """Проверяет, подписан ли пользователь"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM daily_card_subscriptions WHERE user_id = %s', (user_id,))
            return cursor.fetchone() is not None

    @staticmethod
    def get_all_subscribers() -> List[int]:
        """Получает список всех подписчиков"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM daily_card_subscriptions')
            return [row[0] for row in cursor.fetchall()]

    @staticmethod
    def update_last_sent_date(user_id: int):
        """Обновляет дату последней отправки карты дня"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE daily_card_subscriptions 
                SET last_sent_date = %s 
                WHERE user_id = %s
            ''', (datetime.now().date(), user_id))
            conn.commit()

    @staticmethod
    def can_offer_subscription_today(user_id: int) -> bool:
        """Проверяет, можно ли предложить подписку сегодня (не предлагали ли уже)"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT last_offer_date FROM subscription_offers 
                WHERE user_id = %s
            ''', (user_id,))
            row = cursor.fetchone()
            
            if not row or not row[0]:
                return True
            
            last_offer = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(row[0])
            today = datetime.now().date()
            
            return last_offer.date() < today

    @staticmethod
    def record_subscription_offer(user_id: int):
        """Записывает факт предложения подписки сегодня"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO subscription_offers (user_id, last_offer_date, offer_count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id) DO UPDATE SET 
                    last_offer_date = EXCLUDED.last_offer_date,
                    offer_count = subscription_offers.offer_count + 1
            ''', (user_id, datetime.now()))
            conn.commit()