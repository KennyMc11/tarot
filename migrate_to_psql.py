# migrate_to_postgres.py
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# Конфигурация
SQLITE_DB = "tarot_bot.db"
POSTGRES_URL = os.getenv("DATABASE_URL")

def migrate_data():
    """Миграция данных из SQLite в PostgreSQL"""
    
    print("🔄 Начинаем миграцию данных...")
    
    # Подключаемся к SQLite
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    
    # Подключаемся к PostgreSQL
    pg_conn = psycopg2.connect(POSTGRES_URL)
    pg_cursor = pg_conn.cursor()
    
    try:
        # 1. Миграция пользователей
        print("📦 Миграция пользователей...")
        sqlite_cursor.execute("SELECT * FROM users")
        users = sqlite_cursor.fetchall()
        
        for user in users:
            pg_cursor.execute('''
                INSERT INTO users 
                (user_id, username, first_name, last_name, name, birth_date, age,
                 registration_date, last_activity, messages_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            ''', (
                user['user_id'], user['username'], user['first_name'],
                user['last_name'], user['name'], user['birth_date'],
                user['age'], user['registration_date'], user['last_activity'],
                user['messages_count']
            ))
        print(f"✅ Перенесено {len(users)} пользователей")
        
        # 2. Миграция раскладов
        print("📦 Миграция раскладов...")
        sqlite_cursor.execute("SELECT * FROM last_spread")
        spreads = sqlite_cursor.fetchall()
        
        for spread in spreads:
            pg_cursor.execute('''
                INSERT INTO last_spread 
                (id, user_id, question, cards, positions, spread_name, spread_topic, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            ''', (
                spread['id'], spread['user_id'], spread['question'],
                spread['cards'], spread['positions'], spread['spread_name'],
                spread['spread_topic'], spread['created_at']
            ))
        print(f"✅ Перенесено {len(spreads)} раскладов")
        
        # 3. Миграция истории сообщений
        print("📦 Миграция истории сообщений...")
        sqlite_cursor.execute("SELECT * FROM message_history")
        messages = sqlite_cursor.fetchall()
        
        for msg in messages:
            pg_cursor.execute('''
                INSERT INTO message_history 
                (id, user_id, role, content, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            ''', (
                msg['id'], msg['user_id'], msg['role'],
                msg['content'], msg['created_at']
            ))
        print(f"✅ Перенесено {len(messages)} сообщений")
        
        # 4. Миграция подписок
        print("📦 Миграция подписок на карту дня...")
        sqlite_cursor.execute("SELECT * FROM daily_card_subscriptions")
        subscriptions = sqlite_cursor.fetchall()
        
        for sub in subscriptions:
            pg_cursor.execute('''
                INSERT INTO daily_card_subscriptions 
                (user_id, subscribed_at, last_sent_date)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            ''', (
                sub['user_id'], sub['subscribed_at'], sub['last_sent_date']
            ))
        print(f"✅ Перенесено {len(subscriptions)} подписок")
        
        # 5. Миграция предложений подписки
        print("📦 Миграция предложений подписки...")
        sqlite_cursor.execute("SELECT * FROM subscription_offers")
        offers = sqlite_cursor.fetchall()
        
        for offer in offers:
            pg_cursor.execute('''
                INSERT INTO subscription_offers 
                (user_id, last_offer_date, offer_count)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            ''', (
                offer['user_id'], offer['last_offer_date'], offer['offer_count']
            ))
        print(f"✅ Перенесено {len(offers)} предложений")
        
        # 6. Миграция временных данных регистрации
        print("📦 Миграция временных данных регистрации...")
        sqlite_cursor.execute("SELECT * FROM registration_temp")
        temp_data = sqlite_cursor.fetchall()
        
        for temp in temp_data:
            pg_cursor.execute('''
                INSERT INTO registration_temp 
                (user_id, name, birth_date, messages, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            ''', (
                temp['user_id'], temp['name'], temp['birth_date'],
                temp['messages'], temp['updated_at']
            ))
        print(f"✅ Перенесено {len(temp_data)} временных записей")
        
        # Сбрасываем последовательности
        print("🔄 Сброс последовательностей...")
        pg_cursor.execute("SELECT setval('last_spread_id_seq', (SELECT MAX(id) FROM last_spread))")
        pg_cursor.execute("SELECT setval('message_history_id_seq', (SELECT MAX(id) FROM message_history))")
        
        pg_conn.commit()
        print("✅ Миграция успешно завершена!")
        
    except Exception as e:
        pg_conn.rollback()
        print(f"❌ Ошибка при миграции: {e}")
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()

def verify_migration():
    """Проверка корректности миграции"""
    print("\n🔍 Проверка миграции...")
    
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_cursor = sqlite_conn.cursor()
    
    pg_conn = psycopg2.connect(POSTGRES_URL)
    pg_cursor = pg_conn.cursor()
    
    tables = ['users', 'last_spread', 'message_history', 'daily_card_subscriptions', 
              'subscription_offers', 'registration_temp']
    
    for table in tables:
        sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        sqlite_count = sqlite_cursor.fetchone()[0]
        
        pg_cursor.execute(f"SELECT COUNT(*) FROM {table}")
        pg_count = pg_cursor.fetchone()[0]
        
        status = "✅" if sqlite_count == pg_count else "⚠️"
        print(f"{status} {table}: SQLite={sqlite_count}, PostgreSQL={pg_count}")
    
    sqlite_conn.close()
    pg_conn.close()

if __name__ == "__main__":
    migrate_data()
    verify_migration()