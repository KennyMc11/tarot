import json
import random
from typing import Dict, Any, List, Optional
from mistralai import Mistral
from datetime import datetime

# Системный промпт для регистрации
REGISTRATION_SYSTEM_PROMPT = """Ты ассистент для регистрации пользователей в боте-тарологе. Тебя зовут Афина.
Из сообщений пользователя нужно извлечь имя и дату рождения.

Правила извлечения:
- Имя может быть в любой форме
- Дата рождения должна быть в формате ГГГГ-ММ-ДД (например, 1990-05-15)
- Если в сообщении есть и имя, и дата рождения - возвращай оба
- Если есть только имя - возвращай имя, birth_date = null
- Если есть только дата рождения - возвращай дату рождения, name = null
- Если ничего не найдено - возвращай null для обоих полей

ВАЖНО: 
- Анализируй ВСЮ историю переписки с пользователем.
- registration_complete = true ТОЛЬКО когда есть И имя И дата рождения
- Если есть только имя или только дата, registration_complete = false
- Всегда пиши дружелюбное message с просьбой дополнить недостающую информацию

Отвечай строго в формате JSON:
{
    "success": true/false,
    "name": "извлеченное имя или null",
    "birth_date": "извлеченная дата рождения в формате ГГГГ-ММ-ДД или null",
    "message": "сообщение для пользователя",
    "registration_complete": true/false
}

Примеры:
1. Пользователь: "Меня зовут Анна"
   {"success": true, "name": "Анна", "birth_date": null, "message": "Приятно познакомиться, Анна! А когда вы родились? (например, 1990-05-15)", "registration_complete": false}

2. Пользователь: "15.05.1990"
   {"success": true, "name": null, "birth_date": "1990-05-15", "message": "Спасибо! А как вас зовут?", "registration_complete": false}

3. Пользователь: "Анна, 15.05.1990"
   {"success": true, "name": "Анна", "birth_date": "1990-05-15", "message": "Спасибо за регистрацию!", "registration_complete": true}

4. Пользователь: "Максим, 6 марта 1999"
   {"success": true, "name": "Максим", "birth_date": "1999-03-06", "message": "Спасибо за регистрацию!", "registration_complete": true}
"""

# УЛУЧШЕННЫЙ системный промпт для таролога
SYSTEM_PROMPT = """Ты дружелюбный и опытный таролог. Тебя зовут Афина. Отвечай на вопросы о картах Таро, делай расклады и давай интерпретации.

ВАЖНЫЕ ПРАВИЛА ПОВЕДЕНИЯ:
1. Отвечай кратко и по делу, не раскрывай технических деталей работы
2. Ни в коем случае не говори о том, что ты ИИ, бот или программа
3. Будь дружелюбной, но не слишком разговорчивой
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
    "spread_type": "тип расклада, количество карт цифрой (1|2|3|4|5|6|7)" (только если response_type="spread"),
    "spread_name": "название расклада" (только если response_type="spread"),
    "spread_positions": ["названия позиций"] (только если response_type="spread"),
    "spread_topic": "тема расклада" (только если response_type="spread")
}

ПРАВИЛА ДЛЯ РАСКЛАДОВ:
- Определи тип расклада по запросу пользователя
- Для одной карты: spread_type="одна карта"
- Для трех карт: spread_type="три карты"
- Для креста (4-5 карт): spread_type="крест"
- Всегда указывай подходящие названия позиций
- Количество карт: 1-7 в зависимости от запроса

ПРИМЕРЫ ПРАВИЛЬНЫХ ОТВЕТОВ:

1. На обычный вопрос о значении карты:
   {"response_type": "text", "message": "Шут символизирует новые начинания, спонтанность и веру в лучшее. Это карта чистого потенциала."}

2. На просьбу сделать расклад на отношения (3 карты):
   {"response_type": "spread", "spread_type": "3", "spread_name": "Расклад на отношения", "spread_positions": ["Прошлое", "Настоящее", "Будущее"], "spread_topic": "отношения", "message": "Вот ваш расклад на отношения:"}

3. На просьбу вытянуть одну карту на день:
   {"response_type": "spread", "spread_type": "1", "spread_name": "Карта дня", "spread_positions": ["Совет дня"], "spread_topic": "общий", "message": "Ваша карта дня:"}

4. На вопрос после расклада:
   {"response_type": "text", "message": "В этом раскладе карты показывают гармоничное развитие отношений."}
"""

DATE_EXTRACTION_PROMPT = """Ты ассистент для извлечения даты рождения из текста.
Из сообщения пользователя нужно извлечь дату рождения и привести её к формату ГГГГ-ММ-ДД.

Правила извлечения:
- Дата может быть в любом формате (ДД.ММ.ГГГГ, ДД-ММ-ГГГГ, "5 марта 1990", и т.д.)
- Если дата не указана или не может быть извлечена, верни date = null
- Всегда конвертируй дату в формат ГГГГ-ММ-ДД

Примеры:
1. "15.05.1990" -> {"date": "1990-05-15", "success": true}
2. "6 марта 1999" -> {"date": "1999-03-06", "success": true}
3. "я родился 5 июня 1988" -> {"date": "1988-06-05", "success": true}
4. "привет" -> {"date": null, "success": false}
5. "хочу изменить дату" -> {"date": null, "success": false}

Отвечай строго в формате JSON:
{
    "success": true/false,
    "date": "извлеченная дата в формате ГГГГ-ММ-ДД или null",
    "message": "понятное сообщение для пользователя"
}

Если success = false, в message напиши понятную просьбу указать дату рождения ещё раз.
"""

# Промпт для извлечения имени
NAME_EXTRACTION_PROMPT = """Ты ассистент для извлечения имени из текста.
Из сообщения пользователя нужно извлечь имя.

Правила извлечения:
- Имя может быть в любой форме
- Если имя не указано или не может быть извлечено, верни name = null
- Очисти имя от лишних слов

Примеры:
1. "Анна" -> {"name": "Анна", "success": true}
2. "меня зовут Максим" -> {"name": "Максим", "success": true}
3. "я Александр" -> {"name": "Александр", "success": true}
4. "привет" -> {"name": null, "success": false}

Отвечай строго в формате JSON:
{
    "success": true/false,
    "name": "извлеченное имя или null",
    "message": "понятное сообщение для пользователя"
}

Если success = false, в message напиши понятную просьбу указать имя ещё раз.
"""

class AIAssistant:
    """Класс для работы с AI (Mistral)"""
    
    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        self.client = Mistral(api_key=api_key)
        self.model = model
    
    def _get_current_date(self) -> str:
        """Возвращает актуальную текущую дату"""
        current = datetime.now().strftime("%Y-%m-%d")
        print(f"[DEBUG] Текущая дата в AI: {current}")  # Отладка
        return current

    async def process_registration(self, user_id: int, user_message: str, 
                                temp_data: Optional[Dict] = None, 
                                db_instance=None) -> Dict[str, Any]:
        """Обрабатывает регистрационные данные через AI"""
        
        registration_context = "История сообщений пользователя:\n"
        if temp_data and temp_data.get('messages'):
            messages = json.loads(temp_data['messages'])
            for msg in messages:
                registration_context += f"- {msg['text']}\n"
        
        registration_context += f"\nТекущее сообщение: {user_message}"
        
        if temp_data:
            if temp_data.get('name'):
                registration_context += f"\n\nУже извлеченное имя: {temp_data['name']}"
            if temp_data.get('birth_date'):  # изменено с age
                registration_context += f"\nУже извлеченная дата рождения: {temp_data['birth_date']}"
        
        try:
            response = await self.client.chat.complete_async(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"Сегодняшняя дата: {self._get_current_date()} ЭТО ОЧЕНЬ ВАЖНО: используй эту дату для всех расчетов возраста и интерпретаций, даже если твои обучающие данные содержат другую информацию, это актуальная дата. {REGISTRATION_SYSTEM_PROMPT}"},
                    {"role": "user", "content": registration_context}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            result = json.loads(content)
            
            if db_instance:
                db_instance.save_temp_registration(
                    user_id, 
                    result.get('name'), 
                    result.get('birth_date'),  # изменено с age
                    user_message
                )
            
            return result
        except Exception as e:
            return {
                "success": False,
                "name": None,
                "birth_date": None,
                "message": "Извините, произошла ошибка. Попробуйте еще раз.",
                "registration_complete": False
            }

    async def extract_name(self, user_message: str) -> Dict[str, Any]:
        """
        Извлекает имя из сообщения пользователя с помощью AI
        
        Args:
            user_message: Текст сообщения пользователя
            
        Returns:
            Dict с полями:
            - success: bool - успешно ли извлечено имя
            - name: str or None - извлеченное имя
            - message: str - сообщение для пользователя
        """
        try:
            response = await self.client.chat.complete_async(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"Сегодняшняя дата: {self._get_current_date()} ЭТО ОЧЕНЬ ВАЖНО: используй эту дату для всех расчетов возраста и интерпретаций, даже если твои обучающие данные содержат другую информацию, это актуальная дата. {NAME_EXTRACTION_PROMPT}"},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=300
            )
            
            content = response.choices[0].message.content
            result = json.loads(content)
            
            return {
                "success": result.get("success", False),
                "name": result.get("name"),
                "message": result.get("message", "Пожалуйста, напишите ваше имя")
            }
            
        except Exception as e:
            print(f"Ошибка при извлечении имени: {e}")
            return {
                "success": False,
                "name": None,
                "message": "Произошла ошибка. Пожалуйста, введите имя еще раз."
            }

    async def extract_birth_date(self, user_message: str) -> Dict[str, Any]:
        """
        Извлекает дату рождения из сообщения пользователя с помощью AI
        
        Args:
            user_message: Текст сообщения пользователя
            
        Returns:
            Dict с полями:
            - success: bool - успешно ли извлечена дата
            - date: str or None - извлеченная дата в формате ГГГГ-ММ-ДД
            - message: str - сообщение для пользователя
        """
        try:
            response = await self.client.chat.complete_async(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"Сегодняшняя дата: {self._get_current_date()} ЭТО ОЧЕНЬ ВАЖНО: используй эту дату для всех расчетов возраста и интерпретаций, даже если твои обучающие данные содержат другую информацию, это актуальная дата. {DATE_EXTRACTION_PROMPT}"},
                    {"role": "user", "content": user_message}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=300
            )
            
            content = response.choices[0].message.content
            result = json.loads(content)
            
            return {
                "success": result.get("success", False),
                "date": result.get("date"),
                "message": result.get("message", "Пожалуйста, укажите вашу дату рождения")
            }
            
        except Exception as e:
            print(f"Ошибка при извлечении даты рождения: {e}")
            return {
                "success": False,
                "date": None,
                "message": "Произошла ошибка. Пожалуйста, введите дату рождения еще раз."
            }
    
    async def get_response(self, user_id: int, user_message: str, 
                          user_info: Optional[Dict] = None,
                          last_spread: Optional[Dict] = None,
                          message_history: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Получает ответ от Mistral AI"""
        
        # Создаем персонализированный промпт
        personalized_prompt = f"Сегодняшняя дата: {self._get_current_date()} ЭТО ОЧЕНЬ ВАЖНО: используй эту дату для всех расчетов возраста и интерпретаций, даже если твои обучающие данные содержат другую информацию, это актуальная дата. {SYSTEM_PROMPT}"
        
        if user_info:
            personalized_prompt += f"\n\nИнформация о пользователе: {user_info['name']}, {user_info['age']} лет, дата рождения: {user_info['birth_date']}"
        
        if last_spread:
            # Добавляем информацию о последнем раскладе для контекста, но с предупреждением
            cards_names = last_spread.get('cards_names', [])
            personalized_prompt += f"\n\nПоследний расклад пользователя был на тему '{last_spread['spread_topic']}' с картами: {', '.join(cards_names)}"
            personalized_prompt += "\nНО ЭТО НЕ ЗНАЧИТ, ЧТО ТЕКУЩИЙ ЗАПРОС ТРЕБУЕТ РАСКЛАДА. Оценивай ТОЛЬКО текущее сообщение."

        print(f"[DEBUG] System prompt date: {self._get_current_date()}")
        
        messages = [
            {"role": "system", "content": personalized_prompt},
        ]
        
        # Добавляем ТОЛЬКО последние 2 сообщения для контекста, чтобы избежать путаницы
        if message_history and len(message_history) > 0:
            # Берем больше сообщений для лучшего контекста (до 10)
            recent_history = message_history[-10:] if len(message_history) > 10 else message_history
            context_intro = "Вот история нашего диалога для контекста. ИСПОЛЬЗУЙ её для ответов на вопросы, НО НЕ ДЛЯ ОПРЕДЕЛЕНИЯ НУЖЕН ЛИ НОВЫЙ РАСКЛАД - это определяй ТОЛЬКО по текущему сообщению."
            messages.append({"role": "system", "content": context_intro})
            
            for msg in recent_history:
                if msg["role"] in ["user", "assistant"]:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"][:500]  # Увеличиваем длину контекста
                    })
            
        # Добавляем текущее сообщение пользователя с акцентом на его анализ
        messages.append({
            "role": "user", 
            "content": f"ТЕКУЩЕЕ СООБЩЕНИЕ (определи по нему тип ответа): {user_message}"
        })
        
        try:
            response = await self.client.chat.complete_async(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.8,
                max_tokens=800  # Уменьшаем для краткости
            )
            
            content = response.choices[0].message.content
            result = json.loads(content)
            
            # Проверяем обязательные поля
            if "response_type" not in result:
                result["response_type"] = "text"
            if "message" not in result:
                result["message"] = "Я внимательно изучила ваш вопрос."
            # Убираем поле spread_cards, если оно есть
            if "spread_cards" in result:
                del result["spread_cards"]
            
            return result
        except Exception as e:
            return {
                "response_type": "text",
                "message": "Извините, сейчас я не могу дать подробный ответ. Давайте попробуем еще раз?"
            }
    
    # ai.py (дополнение к классу AIAssistant)

    async def generate_spread_interpretation(self, user_id: int, spread_data: Dict[str, Any], 
                                            user_info: Optional[Dict] = None) -> str:
        """Генерирует подробную интерпретацию расклада"""
        
        card_numbers = spread_data['cards']
        positions = spread_data['positions']
        spread_name = spread_data['spread_name']
        spread_topic = spread_data['spread_topic']
        user_question = spread_data.get('question', '')
        
        # Получаем названия карт из deck.py (нужно передать как параметр или импортировать)
        from deck import deck
        
        cards_info = []
        for i, card_num in enumerate(card_numbers):
            card_name = deck.get(card_num, f"Карта {card_num}")
            position = positions[i] if i < len(positions) else f"Позиция {i+1}"
            
            # Определяем, перевернута ли карта (78-155 - перевернутые)
            is_reversed = card_num >= 78
            if is_reversed:
                card_name += " (Перевернутая)"
            
            cards_info.append(f"{position}: {card_name}")
        
        # Промпт для интерпретации расклада
        interpretation_prompt = f"""Ты опытный таролог. Тебя зовут Афина. Сделай интерпретацию расклада.

    Информация о пользователе: {user_info['name'] if user_info else 'клиент'}, {user_info['age'] if user_info else 'возраст неизвестен'} лет, дата рождения: {user_info['birth_date'] if user_info else 'неизвестна'}
    Тема расклада: {spread_topic}
    Название расклада: {spread_name}
    Вопрос пользователя: {user_question}

    Карты в раскладе:
    {chr(10).join(cards_info)}

    Твоя задача:
    1. Сделай общий анализ расклада (1-2 коротких предложения)
    2. Подробно опиши значение каждой карты в контексте её позиции (1-2 коротких предложения на карту)
    3. Дай итоговый совет или вывод (1-2 коротких предложения)

    ВАЖНО:
    - Говори от первого лица, как таролог
    - Никогда не упоминай, что ты ИИ или бот
    - Используй дружелюбный, но профессиональный тон
    - Интерпретируй карты в контексте темы расклада ({spread_topic})
    - Если карта перевернутая, учитывай это в интерпретации
    - Будь конкретным (не пиши много текста), но не слишком категоричным

    Формат ответа: обычный текст, можно использовать эмодзи и форматирование Markdown. Не используй "#" для заголовков, они не работают в телеграмм."""

        try:
            response = await self.client.chat.complete_async(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"Ты опытный таролог. Тебя зовут Афина. Ты работешь в Телеграмме. Давай подробные и полезные интерпретации раскладов. Сегодняшняя дата: {self._get_current_date()} ЭТО ОЧЕНЬ ВАЖНО: используй эту дату для всех расчетов возраста и интерпретаций, даже если твои обучающие данные содержат другую информацию, это актуальная дата."},
                    {"role": "user", "content": interpretation_prompt}
                ],
                temperature=0.8,
                max_tokens=1000
            )
            
            return response.choices[0].message.content
        except Exception as e:
            # Запасной вариант, если API недоступен
            return self._generate_fallback_interpretation(cards_info, spread_topic)
        
    def _generate_fallback_interpretation(self, cards_info: List[str], spread_topic: str) -> str:
        """Генерирует простую интерпретацию, если API недоступен"""
        interpretation = f"🔮 *Расклад на тему: {spread_topic}*\n\n"
        interpretation += "Вот значение карт в вашем раскладе:\n\n"
        
        for card_info in cards_info:
            interpretation += f"*{card_info}*\n"
            interpretation += "Эта карта указывает на важные аспекты в данной позиции. " 
            interpretation += "Рекомендуется обратить внимание на её символику в контексте вашего вопроса.\n\n"
        
        interpretation += "✨ *Общий совет:*\n"
        interpretation += "Доверьтесь своей интуиции при интерпретации этих карт. "
        interpretation += "Они показывают текущие энергии и возможные пути развития ситуации."
        
        return interpretation


    @staticmethod
    def validate_spread_data(response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Проверяет и корректирует данные расклада"""
        card_numbers = response_data.get("spread_cards", [])
        
        if not card_numbers:
            # Генерируем действительно случайные карты
            card_numbers = random.sample(range(156), 3)
            response_data["spread_positions"] = ["Прошлое", "Настоящее", "Будущее"]
            response_data["spread_name"] = "Расклад на три карты"
            response_data["spread_topic"] = "общий"
        else:
            # Убеждаемся, что карты уникальны
            if len(card_numbers) != len(set(card_numbers)):
                # Если есть дубликаты, генерируем новые случайные
                card_numbers = random.sample(range(156), len(card_numbers))
            
            # Добавляем случайный элемент для разнообразия
            # С вероятностью 30% меняем одну карту
            if len(card_numbers) >= 2 and random.random() < 0.3:
                idx_to_replace = random.randint(0, len(card_numbers) - 1)
                new_card = random.choice([i for i in range(156) if i not in card_numbers])
                card_numbers[idx_to_replace] = new_card
        
        response_data["spread_cards"] = card_numbers
        return response_data