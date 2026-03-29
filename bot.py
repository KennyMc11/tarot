import os
import asyncio
import random
from io import BytesIO
from datetime import datetime, timedelta, timezone
from typing import List
import json

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PIL import Image, ImageDraw, ImageFont

from deck import deck
from database import Database
from ai import AIAssistant



# Функция для получения актуальной даты
def get_current_date():
    """Возвращает актуальную текущую дату в UTC"""
    return datetime.now(timezone.utc).date()

load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_API_KEYS = os.getenv("MISTRAL_API_KEYS", "").split(",")
MISTRAL_API_KEYS = [key.strip() for key in MISTRAL_API_KEYS if key.strip()]
MISTRAL_MODEL = "mistral-large-latest"
YOUR_ADMIN_ID = os.getenv("YOUR_ADMIN_ID")

if not MISTRAL_API_KEYS and MISTRAL_API_KEY:
    MISTRAL_API_KEYS = [MISTRAL_API_KEY]

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация компонентов
db = Database()
ai = AIAssistant(api_keys=MISTRAL_API_KEYS, model=MISTRAL_MODEL)


def get_profile_keyboard(is_subscribed: bool):
    """Клавиатура профиля с кнопкой подписки"""
    builder = InlineKeyboardBuilder()
    
    # Кнопка редактирования профиля
    builder.row(InlineKeyboardButton(text="✏️ Редактировать профиль", callback_data="edit_profile"))
    
    # Кнопка подписки/отписки
    if is_subscribed:
        builder.row(InlineKeyboardButton(text="🔔 Отписаться от карты дня", callback_data="unsubscribe_daily"))
    else:
        builder.row(InlineKeyboardButton(text="🔮 Подписаться на карту дня", callback_data="subscribe_daily"))
    
    builder.row(InlineKeyboardButton(text="❌ Закрыть", callback_data="close_profile"))
    return builder.as_markup()

def get_edit_profile_keyboard():
    """Клавиатура для выбора действия при редактировании профиля"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Изменить имя", callback_data="edit_name"),
        InlineKeyboardButton(text="📅 Изменить дату рождения", callback_data="edit_birth_date")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_profile"))
    return builder.as_markup()

def get_daily_card_keyboard():
    """Клавиатура для предложения подписки на карту дня"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔮 Подписаться на карту дня", callback_data="subscribe_daily"),
        InlineKeyboardButton(text="❌ Не сейчас", callback_data="close_suggestion")
    )
    return builder.as_markup()

def get_confirmation_keyboard(action: str):
    """Клавиатура для подтверждения действий"""
    builder = InlineKeyboardBuilder()
    confirm_data = f"confirm_{action}"
    print(f"Создание кнопки с callback_data: {confirm_data}")  # Отладка
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=confirm_data),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")
    )
    return builder.as_markup()


def generate_spread_cards(spread_type: str, topic: str = "общий") -> List[int]:
    
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
        is_reversed = random.random() < 0.03
        
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

class EditProfileStates(StatesGroup):
    waiting_for_edit_choice = State()
    waiting_for_new_name = State()
    waiting_for_new_birth_date = State()


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
            "✨Добро пожаловать!✨\n\n"
            "Меня зовут Афина, и я ваш проводник в мир Таро.🃏\n\n"
            "Чтобы настроиться на вашу энергию и сделать точный расклад, мне нужно знать ваше *имя* и *дату рождения*.\n"
            "Напишите их, пожалуйста.\n",
            parse_mode="Markdown"
        )

@dp.message(Command("keystats"))
async def cmd_keystats(message: types.Message):
    """Показывает статистику использования API ключей (только для админа)"""
    # Добавьте проверку на админа
    if message.from_user.id != int(YOUR_ADMIN_ID):  # Замените на свой ID
        return
    
    if hasattr(ai, 'key_pool') and ai.key_pool:
        stats = ai.key_pool.get_stats()
        stats_text = f"📊 *Статистика API ключей*\n\n"
        stats_text += f"Всего ключей: {stats['total_keys']}\n"
        stats_text += f"Активных: {stats['active_keys']}\n"
        stats_text += f"Всего запросов: {stats['total_requests']}\n"
        stats_text += f"Ошибок: {stats['total_fails']}\n\n"
        stats_text += "*Детали:*\n"
        for k in stats['keys']:
            status = "✅" if k['is_active'] else "❌"
            stats_text += f"{status} {k['key']}: {k['requests']} запр., {k['fails']} ошиб.\n"
        
        await message.answer(stats_text, parse_mode="Markdown")
    else:
        await message.answer("Пул ключей не используется")

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
        birth_date = ai_response.get("birth_date")  # изменено с age
        
        if name and birth_date:
            db.register_user(
                user_id=user_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                name=name,
                birth_date=birth_date  # изменено с age
            )
            
            await state.clear()
            
            # Получаем возраст для приветствия
            user_info = db.get_user_info(user_id)
            age = user_info['age'] if user_info else '?'
            
            welcome_text = (
                f"Рада познакомиться, {name}! 🌟\n\n"
                f"Я готова ответить на ваши вопросы о картах Таро или сделать расклад.\n"
                f"Просто напишите, что вас интересует."
            )
            
            db.save_message_to_history(user_id, "assistant", welcome_text)
            await message.answer(welcome_text)

            await message.answer(
                "🌟 Хотите получать карту дня каждое утро? Это поможет вам лучше понимать энергию дня!",
                reply_markup=get_daily_card_keyboard()
            )

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
    is_subscribed = db.is_subscribed(user_id)
    
    profile_text = (
        f"👤 *Ваш профиль*\n\n"
        f"**Имя:** {user_info['name']}\n"
        f"**Дата рождения:** {user_info['birth_date']}\n"
        f"**Возраст:** {user_info['age']} лет\n"
        f"**Сообщений:** {user_info['messages_count']}\n"
        f"**Карта дня:** {'🔔 подписан' if is_subscribed else '🔕 не подписан'}\n"
    )
    
    if last_spread:
        cards_names = [deck.get(card, f"Карта {card}")[:20] for card in last_spread['cards']]
        profile_text += f"\n🔮 *Последний расклад:*\n"
        profile_text += f"• {last_spread['spread_name']}\n"
        profile_text += f"• {', '.join(cards_names)}\n"
        profile_text += f"📝 *Вопрос:* {last_spread['question'][:100]}..."
    
    await message.answer(
        profile_text, 
        parse_mode="Markdown",
        reply_markup=get_profile_keyboard(is_subscribed)
    )


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


@dp.callback_query(lambda c: c.data == "edit_profile")
async def edit_profile_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "✏️ *Редактирование профиля*\n\n"
        "Выберите, что хотите изменить:",
        parse_mode="Markdown",
        reply_markup=get_edit_profile_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_profile")
async def back_to_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.delete()
    await show_updated_profile(callback.message, user_id)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "subscribe_daily")
async def subscribe_daily(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    db.add_subscription(user_id)
    
    await callback.message.edit_text(
        "✅ *Вы подписались на карту дня!*\n\n"
        "Каждое утро я буду отправлять вам *карту дня* с интерпретацией.\n\n",
        parse_mode="Markdown"
    )
    await callback.answer("Подписка оформлена!")

@dp.callback_query(lambda c: c.data == "unsubscribe_daily")
async def unsubscribe_daily(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    db.remove_subscription(user_id)
    
    await callback.message.edit_text(
        "❌ *Вы отписались от карты дня*\n\n"
        "Если захотите возобновить подписку, зайдите в профиль.",
        parse_mode="Markdown"
    )
    await callback.answer("Подписка отменена")

@dp.callback_query(lambda c: c.data == "close_suggestion")
async def close_suggestion(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith('confirm_'))
async def confirm_edit(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    action = callback.data.replace('confirm_', '')
    
    data = await state.get_data()
    
    if action == "name":
        new_name = data.get('new_name')
        if new_name:
            # Изменяем имя в БД
            db.change_name(user_id, new_name)
            
            await callback.message.edit_text(
                f"✅ Имя успешно изменено на **{new_name}**!",
                parse_mode="Markdown"
            )
            
            # Логируем действие
            print(f"Пользователь {user_id} изменил имя на {new_name}")
    
    elif action == "birth_date":
        new_birth_date = data.get('new_birth_date')
        if new_birth_date:
            # Изменяем дату рождения в БД
            db.change_birth_date(user_id, new_birth_date)
            
            age = db._calculate_age(new_birth_date)
            
            await callback.message.edit_text(
                f"✅ Дата рождения успешно изменена на **{new_birth_date}**!\n"
                f"Новый возраст: **{age}** лет",
                parse_mode="Markdown"
            )
            
            # Логируем действие
            print(f"Пользователь {user_id} изменил дату рождения на {new_birth_date}")
    
    # Очищаем состояние
    await state.clear()
    
    # Показываем обновленный профиль
    await callback.message.answer(
        "🔄 *Обновленный профиль*",
        parse_mode="Markdown"
    )
    await show_updated_profile(callback.message, user_id)
    
    await callback.answer()


@dp.callback_query(lambda c: c.data == 'cancel_edit')
async def cancel_edit(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Редактирование отменено."
    )
    # Показываем обновленный профиль
    await show_updated_profile(callback.message, callback.from_user.id)
    await callback.answer()


@dp.callback_query()
async def handle_profile_edit(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    action = callback.data
    
    if action == "edit_name":
        await state.set_state(EditProfileStates.waiting_for_new_name)
        await callback.message.edit_text(
            "📝 *Изменение имени*\n\n"
            "Напишите новое имя:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
            )
        )
    
    elif action == "edit_birth_date":
        await state.set_state(EditProfileStates.waiting_for_new_birth_date)
        await callback.message.edit_text(
            "📅 *Изменение даты рождения*\n\n"
            "Напишите новую дату рождения в формате **ГГГГ-ММ-ДД**\n"
            "Например: 1990-05-15",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
            )
        )
    
    elif action == "close_profile":
        await callback.message.delete()
        await callback.answer("Профиль закрыт")
    
    elif action == "cancel_edit":
        await state.clear()
        await callback.message.edit_text(
            "❌ Редактирование отменено.",
            reply_markup=None
        )
        # Показываем обновленный профиль
        await show_updated_profile(callback.message, user_id)
    
    await callback.answer()


async def send_daily_cards():
    """Отправляет карту дня всем подписчикам каждый день в UTC"""
    while True:
        # Получаем текущее время для расчета
        now = datetime.now(timezone.utc)
        
        # Целевое время сегодня в UTC
        target_time = now.replace(hour=4, minute=0, second=0, microsecond=0)
        
        # Если уже прошло сегодня, переносим на завтра
        if now >= target_time:
            target_time = target_time + timedelta(days=1)
        
        # Ждем до целевого времени
        wait_seconds = (target_time - now).total_seconds()
        print(f"🕐 Следующая рассылка через {wait_seconds/3600:.1f} часов (в {target_time} UTC)")
        await asyncio.sleep(wait_seconds)
        
        # ПОЛУЧАЕМ АКТУАЛЬНУЮ ДАТУ ЧЕРЕЗ ФУНКЦИЮ!
        today = get_current_date()
        print(f"📅 Отправка карты дня на {today.strftime('%d.%m.%Y')}")
        
        # Получаем всех подписчиков
        subscribers = db.get_all_subscribers()
        
        for user_id in subscribers:
            try:
                # Проверяем, не отправляли ли уже сегодня
                user_info = db.get_user_info(user_id)
                
                # Генерируем карту дня (одна карта)
                card_numbers = generate_spread_cards("1", "карта дня")
                
                # Создаем коллаж
                collage_bytes = await create_collage(card_numbers)
                
                # Отправляем карту с ПРАВИЛЬНОЙ датой
                await bot.send_photo(
                    chat_id=user_id,
                    photo=BufferedInputFile(collage_bytes.getvalue(), filename="daily_card.jpg"),
                    caption=f"🌟 *Карта дня на сегодня!*",
                    parse_mode="Markdown"
                )
                
                # Генерируем интерпретацию через AI
                interpretation = await ai.generate_daily_card_interpretation(
                    card_numbers[0], 
                    user_info
                )
                
                await bot.send_message(
                    chat_id=user_id,
                    text=interpretation,
                    parse_mode="Markdown"
                )
                
                # Обновляем дату отправки
                db.update_last_sent_date(user_id)
                
                # Небольшая задержка между отправками
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"❌ Ошибка при отправке карты дня пользователю {user_id}: {e}")
                # Если бот заблокирован или пользователь неактивен, отписываем
                if "bot was blocked" in str(e).lower():
                    db.remove_subscription(user_id)
                    print(f"🚫 Пользователь {user_id} отписан (бот заблокирован)")


# Функция для показа обновленного профиля
async def show_updated_profile(message: types.Message, user_id: int):
    """Показывает обновленный профиль с учетом статуса подписки"""
    user_info = db.get_user_info(user_id)
    last_spread = db.get_last_spread(user_id)
    is_subscribed = db.is_subscribed(user_id)
    
    profile_text = (
        f"👤 *Ваш профиль*\n\n"
        f"**Имя:** {user_info['name']}\n"
        f"**Дата рождения:** {user_info['birth_date']}\n"
        f"**Возраст:** {user_info['age']} лет\n"
        f"**Сообщений:** {user_info['messages_count']}\n"
        f"**Карта дня:** {'🔔 подписан' if is_subscribed else '🔕 не подписан'}\n"
    )
    
    if last_spread:
        cards_names = [deck.get(card, f"Карта {card}")[:20] for card in last_spread['cards']]
        profile_text += f"\n🔮 *Последний расклад:*\n"
        profile_text += f"• {last_spread['spread_name']}\n"
        profile_text += f"• {', '.join(cards_names)}\n"
        profile_text += f"📝 *Вопрос:* {last_spread['question'][:100]}..."
    
    await message.answer(
        profile_text,
        parse_mode="Markdown",
        reply_markup=get_profile_keyboard(is_subscribed)
    )


@dp.message(EditProfileStates.waiting_for_new_name)
async def process_new_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    # Показываем индикатор печатания
    await bot.send_chat_action(chat_id=user_id, action="typing")
    
    # Используем AI для извлечения имени
    result = await ai.extract_name(user_text)

    print(f"Результат AI: {result}")  # Отладка
    
    if result.get("success") and result.get("name"):
        new_name = result["name"]
        
        # Проверяем длину имени
        if len(new_name) < 2 or len(new_name) > 50:
            await message.answer(
                "❌ Имя должно быть от 2 до 50 символов. Попробуйте еще раз:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
                )
            )
            return
        
        # Сохраняем имя в состоянии для подтверждения
        await state.update_data(new_name=new_name)
        
        await message.answer(
            f"📝 *Подтверждение*\n\n"
            f"Новое имя: **{new_name}**\n\n"
            f"Всё верно?",
            parse_mode="Markdown",
            reply_markup=get_confirmation_keyboard("name")
        )
    else:
        # AI не смог извлечь имя
        ai_message = result.get("message", "Пожалуйста, напишите ваше имя")
        await message.answer(
            f"❌ {ai_message}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
            )
        )


@dp.message(EditProfileStates.waiting_for_new_birth_date)
async def process_new_birth_date(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    # Показываем индикатор печатания
    await bot.send_chat_action(chat_id=user_id, action="typing")
    
    # Используем AI для извлечения даты рождения
    result = await ai.extract_birth_date(user_text)

    print(f"Результат AI: {result}")  # Отладка
    
    if result.get("success") and result.get("date"):
        new_birth_date = result["date"]
        
        # Проверяем дату
        try:
            from datetime import datetime
            birth_date_obj = datetime.strptime(new_birth_date, "%Y-%m-%d").date()
            
            # Проверяем, что дата не в будущем
            if birth_date_obj > datetime.now().date():
                await message.answer(
                    "❌ Дата рождения не может быть в будущем. Попробуйте еще раз:",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
                    )
                )
                return
            
            # Проверяем возраст
            age = db._calculate_age(new_birth_date)
            if age < 13:
                await message.answer(
                    "❌ Вам должно быть не менее 13 лет. Попробуйте еще раз:",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
                    )
                )
                return
            if age > 120:
                await message.answer(
                    "❌ Пожалуйста, введите корректную дату рождения.",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
                    )
                )
                return
            
            # Сохраняем дату в состоянии для подтверждения
            await state.update_data(new_birth_date=new_birth_date)
            
            await message.answer(
                f"📅 *Подтверждение*\n\n"
                f"Я определила дату: **{new_birth_date}**\n"
                f"Возраст: **{age}** лет\n\n"
                f"Всё верно?",
                parse_mode="Markdown",
                reply_markup=get_confirmation_keyboard("birth_date")
            )
            
        except ValueError as e:
            await message.answer(
                "❌ Произошла ошибка при обработке даты. Попробуйте еще раз:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
                )
            )
    else:
        # AI не смог извлечь дату
        ai_message = result.get("message", "Пожалуйста, укажите вашу дату рождения")
        await message.answer(
            f"❌ {ai_message}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_edit")]]
            )
        )


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

    if "карта дня" in user_text.lower() or "карту дня" in user_text.lower():
        # Получаем актуальную дату
        today = get_current_date()
        
        # Генерируем карту дня
        card_numbers = generate_spread_cards("1", "карта дня")
        collage_bytes = await create_collage(card_numbers)
        
        await message.answer_photo(
            photo=BufferedInputFile(collage_bytes.getvalue(), filename="daily_card.jpg"),
            caption=f"🌟 *Ваша карта дня на сегодня!*",
            parse_mode="Markdown"
        )
        
        # Получаем информацию о пользователе
        user_info = db.get_user_info(user_id)
        
        # Генерируем интерпретацию через AI
        thinking_msg = await message.answer("🔮 Получаю послание карты...")
        interpretation = await ai.generate_daily_card_interpretation(card_numbers[0], user_info)
        await thinking_msg.delete()
        
        await message.answer(interpretation, parse_mode="Markdown")
        
        # Если пользователь не подписан - предлагаем подписку
        if not db.is_subscribed(user_id):
            await message.answer(
                "🔮 Хотите получать карту дня автоматически каждое утро?",
                reply_markup=get_daily_card_keyboard()
            )
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
            interpretation = interpretation[:4000] + "...\n"
        await message.answer(interpretation, parse_mode="Markdown")

        if not db.is_subscribed(user_id) and db.can_offer_subscription_today(user_id) and random.random() < 0.7:
            # Отмечаем, что сегодня уже предлагали
            db.record_subscription_offer(user_id)
            
            # Отправляем предложение
            await message.answer(
                "💫 Если вам понравился этот расклад, возможно, вам будет интересно"
                "*получать карту дня каждое утро*.\nЭто бесплатно и помогает "
                "лучше понимать энергию каждого дня!",
                reply_markup=get_daily_card_keyboard()
            )

        # Сохраняем в историю
        db.save_message_to_history(user_id, "assistant", f"Расклад на тему: {spread_topic}")
        db.save_message_to_history(user_id, "assistant", interpretation[:200] + "...")
        
    else:
        # Обычный текстовый ответ
        answer = response_data.get("message", "Я внимательно изучила ваш вопрос.")
        if len(answer) > 4000:
            answer = answer[:4000] + "...\n"
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
    asyncio.create_task(send_daily_cards())
    
    print("✅ Бот готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())