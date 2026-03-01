import os
import json
import random
import asyncio
import sqlite3
from io import BytesIO
from typing import List, Dict, Any, Optional
from collections import deque
from datetime import datetime, timedelta
from contextlib import contextmanager
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from mistralai import Mistral
from PIL import Image, ImageDraw, ImageFont

from deck import deck

load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = "mistral-large-latest"
DATABASE_PATH = "tarot_bot.db"

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
mistral_client = Mistral(api_key=MISTRAL_API_KEY)

# Определяем состояния для FSM
class RegistrationStates(StatesGroup):
    waiting_for_registration = State()

# Системный промпт для регистрации
REGISTRATION_SYSTEM_PROMPT = """Ты ассистент для регистрации пользователей в боте-тарологе.
Из сообщений пользователя нужно извлечь имя и возраст.

Правила извлечения:
- Имя может быть в любой форме
- Возраст должен быть числом от 1 до 120
- Если в сообщении есть и имя, и возраст - возвращай оба
- Если есть только имя - возвращай имя, age = null
- Если есть только возраст - возвращай возраст, name = null
- Если ничего не найдено - возвращай null для обоих полей

ВАЖНО: Анализируй ВСЮ историю переписки с пользователем.

Отвечай строго в формате JSON:
{
    "success": true/false,
    "name": "извлеченное имя или null",
    "age": извлеченный возраст или null,
    "message": "сообщение для пользователя",
    "registration_complete": true/false
}
"""

# УЛУЧШЕННЫЙ системный промпт для таролога
SYSTEM_PROMPT = """Ты дружелюбный и опытный таролог. Отвечай на вопросы о картах Таро, делай расклады и давай интерпретации.

ВАЖНЫЕ ПРАВИЛА ПОВЕДЕНИЯ:
1. Отвечай кратко и по делу, не раскрывай технических деталей работы
2. Не говори о том, что ты ИИ, бот или программа
3. Будь дружелюбным, но не слишком разговорчивым
4. Отвечай только на текущий вопрос пользователя, не опираясь на предыдущие запросы раскладов

КРИТИЧЕСКИ ВАЖНО: 
- Если пользователь в ТЕКУЩЕМ сообщении просит сделать расклад, погадать или вытянуть карты - используй response_type="spread"
- Если пользователь в ТЕКУЩЕМ сообщении задает любой другой вопрос - используй response_type="text"
- НЕ ДЕЛАЙ расклад, если пользователь просто спрашивает о значении карт или задает общие вопросы или просто ведет диалог
- Предыдущие сообщения с раскладами НЕ ДОЛЖНЫ влиять на текущий ответ

ФОРМАТ ОТВЕТА:
Всегда отвечай строго в формате JSON:
{
    "response_type": "text" | "spread",
    "message": "текстовый ответ пользователю (обязательное поле)",
    "spread_cards": [список номеров карт для расклада] (только если response_type="spread"),
    "spread_name": "название расклада" (только если response_type="spread"),
    "spread_positions": ["названия позиций"] (только если response_type="spread"),
    "spread_topic": "тема расклада" (только если response_type="spread")
}

ПРАВИЛА ДЛЯ РАСКЛАДОВ:
- Используй карты из диапазона 0-155 (0-77 - прямые, 78-155 - перевернутые)
- Карты не должны повторяться
- Количество карт: 1-5 в зависимости от запроса
- Для тем: "отношения", "карьера", "финансы", "здоровье", "общий"

ПРИМЕРЫ ПРАВИЛЬНЫХ ОТВЕТОВ:

1. На обычный вопрос о значении карты:
   {"response_type": "text", "message": "Шут символизирует новые начинания, спонтанность и веру в лучшее. Это карта чистого потенциала."}

2. На просьбу сделать расклад:
   {"response_type": "spread", "spread_cards": [6, 37, 76], "spread_name": "Расклад на отношения", "spread_positions": ["Прошлое", "Настоящее", "Будущее"], "spread_topic": "отношения", "message": "Вот ваш расклад на отношения:"}

3. На вопрос после расклада (не просьба сделать новый):
   {"response_type": "text", "message": "В этом раскладе карты показывают гармоничное развитие отношений."}
"""

# Работа с базой данных
@contextmanager
def get_db_connection():
    """Контекстный менеджер для подключения к БД"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

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
                age INTEGER,
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

def register_user(user_id: int, username: str, first_name: str, last_name: str, 
                  name: str, age: int):
    """Регистрация нового пользователя"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, last_name, name, age, 
             registration_date, last_activity, messages_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, username, first_name, last_name, name, age,
            datetime.now(), datetime.now(), 0
        ))
        cursor.execute('DELETE FROM registration_temp WHERE user_id = ?', (user_id,))
        conn.commit()

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

def get_user_info(user_id: int) -> Optional[Dict]:
    """Получает информацию о пользователе"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def save_temp_registration(user_id: int, name: Optional[str], age: Optional[int], message: str):
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
            INSERT OR REPLACE INTO registration_temp (user_id, name, age, messages, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, name, age, json.dumps(messages), datetime.now()))
        conn.commit()

def get_temp_registration(user_id: int) -> Optional[Dict]:
    """Получает временные данные регистрации"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM registration_temp WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def clear_temp_registration(user_id: int):
    """Очищает временные данные регистрации"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM registration_temp WHERE user_id = ?', (user_id,))
        conn.commit()

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

# Функция для проверки регистрации
async def is_user_registered(user_id: int) -> bool:
    """Проверяет, зарегистрирован ли пользователь"""
    user_info = get_user_info(user_id)
    return user_info is not None

# Функция для обработки регистрации через AI
async def process_registration_with_ai(user_id: int, user_message: str) -> Dict[str, Any]:
    """Обрабатывает регистрационные данные через AI"""
    temp_data = get_temp_registration(user_id)
    
    registration_context = "История сообщений пользователя:\n"
    if temp_data and temp_data.get('messages'):
        messages = json.loads(temp_data['messages'])
        for msg in messages:
            registration_context += f"- {msg['text']}\n"
    
    registration_context += f"\nТекущее сообщение: {user_message}"
    
    if temp_data:
        if temp_data.get('name'):
            registration_context += f"\n\nУже извлеченное имя: {temp_data['name']}"
        if temp_data.get('age'):
            registration_context += f"\nУже извлеченный возраст: {temp_data['age']}"
    
    try:
        response = await mistral_client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": REGISTRATION_SYSTEM_PROMPT},
                {"role": "user", "content": registration_context}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=500
        )
        
        content = response.choices[0].message.content
        result = json.loads(content)
        
        save_temp_registration(
            user_id, 
            result.get('name'), 
            result.get('age'),
            user_message
        )
        
        return result
    except Exception as e:
        return {
            "success": False,
            "name": None,
            "age": None,
            "message": "Извините, произошла ошибка. Попробуйте еще раз.",
            "registration_complete": False
        }

# Функция для создания коллажа из карт
async def create_collage(card_numbers: List[int]) -> BytesIO:
    """Создает коллаж из карт Таро в один ряд с градиентным фоном"""
    # Все карты в один ряд
    cols = len(card_numbers)
    rows = 1
    
    card_width, card_height = 300, 520
    padding = 20
    
    # Создаем градиентный фон
    collage_width = cols * card_width + (cols + 1) * padding
    collage_height = card_height + 2 * padding
    
    # Создаем градиент от темно-фиолетового к чуть более светлому
    base_color = (46, 33, 53)  # Темно-фиолетовый
    light_color = (76, 53, 83)  # Светло-фиолетовый
    
    collage = Image.new('RGB', (collage_width, collage_height), base_color)
    draw = ImageDraw.Draw(collage)
    
    # Рисуем вертикальный градиент
    for y in range(collage_height):
        ratio = y / collage_height
        r = int(base_color[0] * (1 - ratio) + light_color[0] * ratio)
        g = int(base_color[1] * (1 - ratio) + light_color[1] * ratio)
        b = int(base_color[2] * (1 - ratio) + light_color[2] * ratio)
        draw.line([(0, y), (collage_width, y)], fill=(r, g, b))
    
    # Золотистая рамка
    draw.rectangle([(0, 0), (collage_width-1, collage_height-1)], outline=(212, 175, 55), width=5)
    
    # Размещаем карты
    for idx, card_num in enumerate(card_numbers):
        x = padding + idx * (card_width + padding)
        y = padding
        
        card_path = f"deck/{card_num}.jpg"
        if os.path.exists(card_path):
            card_img = Image.open(card_path)
            card_img = card_img.resize((card_width, card_height), Image.Resampling.LANCZOS)
            collage.paste(card_img, (x, y))
    
    img_byte_arr = BytesIO()
    collage.save(img_byte_arr, format='JPEG', quality=95)
    img_byte_arr.seek(0)
    return img_byte_arr

# Функция для получения ответа от Mistral AI
async def get_mistral_response(user_id: int, user_message: str) -> Dict[str, Any]:
    """Получает ответ от Mistral AI"""
    
    user_info = get_user_info(user_id)
    last_spread = get_last_spread(user_id)
    
    # Создаем персонализированный промпт
    personalized_prompt = SYSTEM_PROMPT
    
    if user_info:
        personalized_prompt += f"\n\nИнформация о пользователе: {user_info['name']}, {user_info['age']} лет"
    
    if last_spread:
        # Добавляем информацию о последнем раскладе для контекста, но с предупреждением
        cards_names = [deck.get(card, f"Карта {card}") for card in last_spread['cards']]
        personalized_prompt += f"\n\nПоследний расклад пользователя был на тему '{last_spread['spread_topic']}' с картами: {', '.join(cards_names)}"
        personalized_prompt += "\nНО ЭТО НЕ ЗНАЧИТ, ЧТО ТЕКУЩИЙ ЗАПРОС ТРЕБУЕТ РАСКЛАДА. Оценивай ТОЛЬКО текущее сообщение."
    
    # Получаем историю, но будем использовать её осторожно
    history = get_message_history(user_id)
    
    messages = [
        {"role": "system", "content": personalized_prompt},
    ]
    
    # Добавляем ТОЛЬКО последние 2 сообщения для контекста, чтобы избежать путаницы
    recent_history = history[-2:] if len(history) > 2 else history
    for msg in recent_history:
        if msg["role"] in ["user", "assistant"]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"][:300]  # Уменьшаем длину контекста
            })
    
    # Добавляем текущее сообщение пользователя с акцентом на его анализ
    messages.append({
        "role": "user", 
        "content": f"ТЕКУЩЕЕ СООБЩЕНИЕ (определи по нему тип ответа): {user_message}"
    })
    
    try:
        response = await mistral_client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=800  # Уменьшаем для краткости
        )
        
        content = response.choices[0].message.content
        result = json.loads(content)
        
        # Проверяем обязательные поля
        if "response_type" not in result:
            result["response_type"] = "text"
        if "message" not in result:
            result["message"] = "Я внимательно изучил ваш вопрос."
        
        return result
    except Exception as e:
        return {
            "response_type": "text",
            "message": "Извините, сейчас я не могу дать подробный ответ. Давайте попробуем еще раз?"
        }

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if await is_user_registered(user_id):
        user_info = get_user_info(user_id)
        update_user_activity(user_id)
        
        welcome_text = (
            f"С возвращением, {user_info['name']}! 🔮\n\n"
            f"Чем я могу вам помочь сегодня?"
        )
        
        save_message_to_history(user_id, "assistant", welcome_text)
        await message.answer(welcome_text)
    else:
        clear_temp_registration(user_id)
        await state.set_state(RegistrationStates.waiting_for_registration)
        await message.answer(
            "Добро пожаловать! Я помогу вам с вопросами о картах Таро.\n\n"
            "Для начала скажите, как вас зовут и сколько вам лет?\n",
            parse_mode="Markdown"
        )

# Обработчик регистрации
@dp.message(RegistrationStates.waiting_for_registration)
async def process_registration(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_text = message.text
    
    await bot.send_chat_action(chat_id=user_id, action="typing")
    
    ai_response = await process_registration_with_ai(user_id, user_text)
    
    if ai_response.get("registration_complete"):
        name = ai_response.get("name")
        age = ai_response.get("age")
        
        if name and age:
            register_user(
                user_id=user_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                name=name,
                age=age
            )
            
            await state.clear()
            
            welcome_text = (
                f"Рада познакомиться, {name}! 🌟\n\n"
                f"Я готова ответить на ваши вопросы о картах Таро или сделать расклад.\n"
                f"Просто напишите, что вас интересует."
            )
            
            save_message_to_history(user_id, "assistant", welcome_text)
            await message.answer(welcome_text)
        else:
            await message.answer("Извините, произошла ошибка. Попробуйте еще раз через /start")
            await state.clear()
    else:
        await message.answer(ai_response.get("message", "Пожалуйста, продолжите регистрацию."))

# Обработчик команды /profile
@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    
    if not await is_user_registered(user_id):
        await message.answer("Используйте /start для регистрации.")
        return
    
    user_info = get_user_info(user_id)
    last_spread = get_last_spread(user_id)
    
    profile_text = (
        f"👤 {user_info['name']}, {user_info['age']} лет\n"
        f"📊 Сообщений: {user_info['messages_count']}\n"
    )
    
    if last_spread:
        cards_names = [deck.get(card, f"Карта {card}")[:20] for card in last_spread['cards']]
        profile_text += f"🔮 Последний расклад: {last_spread['spread_name']} ({', '.join(cards_names)})\n"
        profile_text += f"📝 Вопрос: {last_spread['question'][:100]}..."
    
    await message.answer(profile_text)

# Обработчик команды /help
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    user_id = message.from_user.id
    
    if not await is_user_registered(user_id):
        await message.answer("Используйте /start для регистрации.")
        return
    
    help_text = (
        "🔮 *О боте*\n\n"
        "Я помогу вам:\n"
        "• Узнать значение карт Таро\n"
        "• Сделать расклад на ситуацию\n"
        "• Получить совет карт\n\n"
        "*Примеры запросов:*\n"
        "• «Что значит карта Шут?»\n"
        "• «Сделай расклад на отношения»\n"
        "• «Как интерпретировать этот расклад?»\n\n"
        "*Команды:*\n"
        "/profile - ваш профиль\n"
        "/clear - очистить историю\n"
        "/help - эта справка"
    )
    
    await message.answer(help_text, parse_mode="Markdown")

# Обработчик команды /clear
@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_id = message.from_user.id
    
    if not await is_user_registered(user_id):
        await message.answer("Используйте /start для регистрации.")
        return
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM message_history WHERE user_id = ?', (user_id,))
        conn.commit()
    
    await message.answer("История диалога очищена.")

# Основной обработчик сообщений
@dp.message()
async def handle_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_text = message.text
    
    if user_text.startswith('/'):
        return
    
    if not await is_user_registered(user_id):
        await message.answer("Используйте /start для регистрации.")
        return
    
    if len(user_text) > 1000:
        await message.answer("Пожалуйста, сформулируйте вопрос короче (до 1000 символов).")
        return
    
    update_user_activity(user_id)
    save_message_to_history(user_id, "user", user_text)
    
    await bot.send_chat_action(chat_id=user_id, action="typing")
    
    # Получаем ответ от AI
    response_data = await get_mistral_response(user_id, user_text)
    
    # Обрабатываем ответ в зависимости от типа
    if response_data["response_type"] == "spread":
        
        # Это расклад
        card_numbers = response_data.get("spread_cards", [])
        spread_topic = response_data.get("spread_topic", "общий")
        spread_name = response_data.get("spread_name", "Расклад")
        positions = response_data.get("spread_positions", [])
        
        # Проверяем и корректируем данные
        if not card_numbers:
            card_numbers = random.sample(range(78), 3)
            positions = ["Прошлое", "Настоящее", "Будущее"]
            spread_name = "Расклад на три карты"
        
        # Убеждаемся, что карты уникальны
        if len(card_numbers) != len(set(card_numbers)):
            card_numbers = list(set(card_numbers))
            while len(card_numbers) < len(positions):
                new_card = random.choice([i for i in range(156) if i not in card_numbers])
                card_numbers.append(new_card)
        
        # Сохраняем расклад
        save_last_spread(user_id, user_text[:200], card_numbers, positions, spread_name, spread_topic)
        
        # Создаем и отправляем коллаж
        collage_bytes = await create_collage(card_numbers)
        await message.answer_photo(
            photo=BufferedInputFile(collage_bytes.getvalue(), filename="spread.jpg"),
            caption=f"🔮 {spread_name}",
        )
        
        # Формируем описание карт
        cards_description = []
        for i, card_num in enumerate(card_numbers):
            card_name = deck.get(card_num, f"Карта {card_num}")
            position = positions[i] if i < len(positions) else f"Позиция {i+1}"
            cards_description.append(f"• {position}: {card_name}")
        
        spread_text = response_data.get("message", "Вот ваш расклад:")
        spread_text += "\n\n" + "\n".join(cards_description)
        spread_text += f"\n\n💫 Тема расклада: {spread_topic}"
        
        await message.answer(spread_text[:4000])
        save_message_to_history(user_id, "assistant", f"Расклад на тему: {spread_topic}")
        
    else:
        # Обычный текстовый ответ
        answer = response_data.get("message", "Я внимательно изучила ваш вопрос.")
        await message.answer(answer[:4000])
        save_message_to_history(user_id, "assistant", answer[:200])

# Обработчик ошибок
@dp.error()
async def error_handler(event: types.ErrorEvent):
    print(f"❌ Ошибка: {event.exception}")

# Функция для проверки изображений карт
async def check_deck_images():
    """Проверяет наличие изображений карт"""
    missing = []
    for i in range(156):
        if not os.path.exists(f"deck/{i}.jpg"):
            missing.append(i)
    
    if missing:
        print(f"⚠️ Отсутствуют изображения для {len(missing)} карт")
    else:
        print("✅ Все изображения карт найдены")

# Функция для очистки старых данных
async def cleanup_old_data():
    """Очищает старые данные из БД"""
    while True:
        await asyncio.sleep(86400)
        
        threshold = datetime.now() - timedelta(days=30)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM message_history WHERE created_at < ?', (threshold,))
            cursor.execute('DELETE FROM last_spread WHERE created_at < ?', (threshold,))
            cursor.execute('DELETE FROM registration_temp WHERE updated_at < ?', (threshold,))
            conn.commit()
        
        print("🔄 Очистка старых данных выполнена")

# Запуск бота
async def main():
    print("🚀 Запуск бота...")
    
    init_database()
    await check_deck_images()
    asyncio.create_task(cleanup_old_data())
    
    print("✅ Бот готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())