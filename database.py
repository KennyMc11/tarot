import sqlite3
import json
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import List, Dict, Optional, Any

DATABASE_PATH = "tarot_bot.db"


@contextmanager
def get_db_connection():
    """Контекстный менеджер для подключения к БД"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class Database:
    """Класс для работы с базой данных"""
    
    @staticmethod
    def init_database():
        """Инициализация базы данных"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
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
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    question TEXT,
                    cards TEXT,
                    positions TEXT,
                    spread_name TEXT,
                    spread_topic TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Таблица для временного хранения регистрационных данных
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS registration_temp (
                    user_id INTEGER PRIMARY KEY,
                    name TEXT,
                    birth_date TEXT,
                    messages TEXT,
                    updated_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Таблица для истории сообщений (последние 20)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            conn.commit()
            print("✅ База данных инициализирована")
    
    @staticmethod
    def register_user(user_id: int, username: str, first_name: str, last_name: str, 
                    name: str, birth_date: str):  # вместо age: int
        """Регистрация нового пользователя с датой рождения"""
        # Вычисляем возраст из даты рождения
        age = Database._calculate_age(birth_date)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, name, birth_date, age,
                registration_date, last_activity, messages_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, username, first_name, last_name, name, birth_date, age,
                datetime.now(), datetime.now(), 0
            ))
            cursor.execute('DELETE FROM registration_temp WHERE user_id = ?', (user_id,))
            conn.commit()
    
    @staticmethod
    def update_user_activity(user_id: int):
        """Обновляет время последней активности и счетчик сообщений"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET last_activity = ?, 
                    messages_count = messages_count + 1
                WHERE user_id = ?
            ''', (datetime.now(), user_id))
            conn.commit()
    
    @staticmethod
    def get_user_info(user_id: int) -> Optional[Dict]:
        """Получает информацию о пользователе"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    def save_temp_registration(user_id: int, name: Optional[str], birth_date: Optional[str], message: str):
        """Сохраняет временные данные регистрации"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT messages FROM registration_temp WHERE user_id = ?', (user_id,))
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
                INSERT OR REPLACE INTO registration_temp (user_id, name, birth_date, messages, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, name, birth_date, json.dumps(messages), datetime.now()))
            conn.commit()
    
    @staticmethod
    def get_temp_registration(user_id: int) -> Optional[Dict]:
        """Получает временные данные регистрации"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM registration_temp WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    def clear_temp_registration(user_id: int):
        """Очищает временные данные регистрации"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM registration_temp WHERE user_id = ?', (user_id,))
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
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, question[:200], json.dumps(cards), 
                json.dumps(positions), spread_name, spread_topic, datetime.now()
            ))
            conn.commit()
    
    @staticmethod
    def get_last_spread(user_id: int) -> Optional[Dict]:
        """Получает последний расклад пользователя"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM last_spread 
                WHERE user_id = ? 
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
                VALUES (?, ?, ?, ?)
            ''', (user_id, role, content, datetime.now()))
            
            # Оставляем только последние 20 сообщений
            cursor.execute('''
                DELETE FROM message_history 
                WHERE user_id = ? AND id NOT IN (
                    SELECT id FROM message_history 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 20
                )
            ''', (user_id, user_id))
            
            conn.commit()
    
    @staticmethod
    def get_message_history(user_id: int) -> List[Dict]:
        """Получает историю сообщений пользователя"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT role, content FROM message_history 
                WHERE user_id = ? 
                ORDER BY created_at ASC
            ''', (user_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def clear_message_history(user_id: int):
        """Очищает историю сообщений пользователя"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM message_history WHERE user_id = ?', (user_id,))
            conn.commit()
    
    @staticmethod
    def cleanup_old_data(days: int = 30):
        """Очищает старые данные из БД"""
        threshold = datetime.now() - timedelta(days=days)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM message_history WHERE created_at < ?', (threshold,))
            cursor.execute('DELETE FROM last_spread WHERE created_at < ?', (threshold,))
            cursor.execute('DELETE FROM registration_temp WHERE updated_at < ?', (threshold,))
            conn.commit()
        
        print(f"🔄 Очистка данных старше {days} дней выполнена")

    @staticmethod
    def change_name(user_id: int, new_name: str):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET name = ? WHERE user_id = ?', (new_name, user_id))
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
            cursor.execute('UPDATE users SET birth_date = ?, age = ? WHERE user_id = ?', 
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