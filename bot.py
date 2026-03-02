import os
import asyncio
import random
from io import BytesIO
from datetime import datetime, timedelta
from typing import List

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from PIL import Image, ImageDraw, ImageFont

from deck import deck
from database import Database
from ai import AIAssistant

load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = "mistral-large-latest"

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация компонентов
db = Database()
ai = AIAssistant(api_key=MISTRAL_API_KEY, model=MISTRAL_MODEL)


def generate_spread_cards(spread_type: str, topic: str = "общий") -> List[int]:
    """Генерирует случайные уникальные карты для расклада с учетом вероятности перевернутых карт"""
    
    # Определяем количество карт
    card_counts = {
        "1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
        "6": 6, "7": 7, "8": 8, "9": 9, "10": 10
    }
    num_cards = card_counts.get(spread_type, 3)
    
    # Получаем все доступные базовые номера карт (0-77)
    available_bases = list(range(78))
    selected_cards = []
    
    # Перемешиваем доступные базовые номера для случайности
    random.shuffle(available_bases)
    
    # Берем нужное количество базовых карт
    for i in range(min(num_cards, len(available_bases))):
        base_card = available_bases[i]
        
        # Определяем, будет ли карта перевернутой с вероятностью 33% (чтобы прямые выпадали в 2 раза чаще)
        # 33% * 78 = ~26 перевернутых карт, 67% * 78 = ~52 прямых карт (соотношение ~2:1)
        is_reversed = random.random() < 0.33
        
        if is_reversed:
            selected_cards.append(base_card + 78)  # Перевернутая
        else:
            selected_cards.append(base_card)  # Прямая
    
    return selected_cards


# Функция для генерации позиций, если AI их не предоставил
def generate_positions(spread_type: str, num_cards: int) -> List[str]:
    """Генерирует стандартные названия позиций для расклада"""
    
    if spread_type == "1":
        return ["Совет дня"]
    elif spread_type == "2":
        return ["Настоящее", "Будущее"]
    elif spread_type == "3":
        return ["Прошлое", "Настоящее", "Будущее"]
    elif spread_type == "4" and num_cards == 4:
        return ["Ситуация", "Проблема", "Совет", "Итог"]
    elif spread_type == "5" and num_cards == 5:
        return ["Прошлое", "Настоящее", "Будущее", "Причина", "Совет"]
    else:
        return [f"Позиция {i+1}" for i in range(num_cards)]


# Определяем состояния для FSM
class RegistrationStates(StatesGroup):
    waiting_for_registration = State()


# Функция для проверки регистрации
async def is_user_registered(user_id: int) -> bool:
    """Проверяет, зарегистрирован ли пользователь"""
    user_info = db.get_user_info(user_id)
    return user_info is not None


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
    light_color = (140, 90, 156)  # Светло-фиолетовый
    
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


# Функция для периодической очистки старых данных
async def cleanup_old_data():
    """Периодически очищает старые данные из БД"""
    while True:
        await asyncio.sleep(86400)  # 24 часа
        db.cleanup_old_data(days=30)
        print("🔄 Очистка старых данных выполнена")


# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if await is_user_registered(user_id):
        user_info = db.get_user_info(user_id)
        db.update_user_activity(user_id)
        
        welcome_text = (
            f"С возвращением, {user_info['name']}! 🔮\n\n"
            f"Чем я могу вам помочь сегодня?"
        )
        
        db.save_message_to_history(user_id, "assistant", welcome_text)
        await message.answer(welcome_text)
    else:
        db.clear_temp_registration(user_id)
        await state.set_state(RegistrationStates.waiting_for_registration)
        await message.answer(
            "Добро пожаловать!\n\nМеня зовут Афина.\nЯ помогу вам с вопросами о картах Таро.\n\n"
            "Для начала скажите, как вас зовут и сколько вам лет?\n",
            parse_mode="Markdown"
        )


# Обработчик регистрации
@dp.message(RegistrationStates.waiting_for_registration)
async def process_registration(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_text = message.text
    
    await bot.send_chat_action(chat_id=user_id, action="typing")
    
    temp_data = db.get_temp_registration(user_id)
    ai_response = await ai.process_registration(user_id, user_text, temp_data, db)
    
    if ai_response.get("registration_complete"):
        name = ai_response.get("name")
        age = ai_response.get("age")
        
        if name and age:
            db.register_user(
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
            
            db.save_message_to_history(user_id, "assistant", welcome_text)
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
    
    user_info = db.get_user_info(user_id)
    last_spread = db.get_last_spread(user_id)
    
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
    
    db.clear_message_history(user_id)
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
    
    db.update_user_activity(user_id)
    db.save_message_to_history(user_id, "user", user_text)
    
    await bot.send_chat_action(chat_id=user_id, action="typing")
    
    # Получаем данные для AI
    user_info = db.get_user_info(user_id)
    last_spread = db.get_last_spread(user_id)
    message_history = db.get_message_history(user_id)
    
    # Подготавливаем данные о последнем раскладе
    last_spread_data = None
    if last_spread:
        cards_names = [deck.get(card, f"Карта {card}") for card in last_spread['cards']]
        last_spread_data = {
            'spread_topic': last_spread['spread_topic'],
            'cards_names': cards_names
        }
    
    # Получаем ответ от AI
    response_data = await ai.get_response(
        user_id, user_text, user_info, last_spread_data, message_history
    )
    
    # Обрабатываем ответ в зависимости от типа
    if response_data["response_type"] == "spread":
        spread_type = response_data.get("spread_type", "три карты")
        spread_topic = response_data.get("spread_topic", "общий")
        spread_name = response_data.get("spread_name", "Расклад")
        positions = response_data.get("spread_positions", [])

        # Генерируем карты на основе типа расклада
        card_numbers = generate_spread_cards(spread_type, spread_topic)

        # Корректируем количество позиций под количество карт
        if len(positions) != len(card_numbers):
            positions = generate_positions(spread_type, len(card_numbers))
        
        # Сохраняем расклад
        db.save_last_spread(user_id, user_text[:200], card_numbers, positions, spread_name, spread_topic)
        
        # Отправляем уведомление о начале создания расклада
        wait_message = await message.answer("🔮 Создаю расклад и готовлю интерпретацию...")
        
        # Создаем и отправляем коллаж
        collage_bytes = await create_collage(card_numbers)
        await message.answer_photo(
            photo=BufferedInputFile(collage_bytes.getvalue(), filename="spread.jpg"),
            caption=f"🔮 *{spread_name}*",
            parse_mode="Markdown"
        )
        
        # Удаляем уведомление
        await wait_message.delete()
        
        # Отправляем новое уведомление о подготовке интерпретации
        thinking_message = await message.answer("📖 Готовлю подробное толкование расклада...")
        
        # Генерируем интерпретацию расклада
        spread_data_for_ai = {
            'cards': card_numbers,
            'positions': positions,
            'spread_name': spread_name,
            'spread_topic': spread_topic,
            'question': user_text
        }
        
        interpretation = await ai.generate_spread_interpretation(
            user_id, spread_data_for_ai, user_info
        )
        
        # Удаляем уведомление
        await thinking_message.delete()
        
        # Отправляем интерпретацию с проверкой длины
        if len(interpretation) > 4000:
            # Если сообщение слишком длинное, обрезаем и добавляем предупреждение
            interpretation = interpretation[:4000] + "...\n\n*Интерпретация сокращена из-за ограничений Telegram*"
        await message.answer(interpretation, parse_mode="Markdown")
        
        # Сохраняем в историю
        db.save_message_to_history(user_id, "assistant", f"Расклад на тему: {spread_topic}")
        db.save_message_to_history(user_id, "assistant", interpretation[:200] + "...")
        
    else:
        # Обычный текстовый ответ
        answer = response_data.get("message", "Я внимательно изучила ваш вопрос.")
        if len(answer) > 4000:
            answer = answer[:4000] + "...\n\n*Сообщение сокращено из-за ограничений Telegram*"
        await message.answer(answer, parse_mode="Markdown")
        db.save_message_to_history(user_id, "assistant", answer[:200])


# Обработчик ошибок
@dp.error()
async def error_handler(event: types.ErrorEvent):
    print(f"❌ Ошибка: {event.exception}")


# Запуск бота
async def main():
    print("🚀 Запуск бота...")
    
    db.init_database()
    await check_deck_images()
    asyncio.create_task(cleanup_old_data())
    
    print("✅ Бот готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())