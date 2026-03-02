import json
import random
from typing import Dict, Any, List, Optional
from mistralai import Mistral

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


class AIAssistant:
    """Класс для работы с AI (Mistral)"""
    
    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        self.client = Mistral(api_key=api_key)
        self.model = model
    
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
            if temp_data.get('age'):
                registration_context += f"\nУже извлеченный возраст: {temp_data['age']}"
        
        try:
            response = await self.client.chat.complete_async(
                model=self.model,
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
            
            if db_instance:
                db_instance.save_temp_registration(
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
    
    async def get_response(self, user_id: int, user_message: str, 
                          user_info: Optional[Dict] = None,
                          last_spread: Optional[Dict] = None,
                          message_history: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Получает ответ от Mistral AI"""
        
        # Создаем персонализированный промпт
        personalized_prompt = SYSTEM_PROMPT
        
        if user_info:
            personalized_prompt += f"\n\nИнформация о пользователе: {user_info['name']}, {user_info['age']} лет"
        
        if last_spread:
            # Добавляем информацию о последнем раскладе для контекста, но с предупреждением
            cards_names = last_spread.get('cards_names', [])
            personalized_prompt += f"\n\nПоследний расклад пользователя был на тему '{last_spread['spread_topic']}' с картами: {', '.join(cards_names)}"
            personalized_prompt += "\nНО ЭТО НЕ ЗНАЧИТ, ЧТО ТЕКУЩИЙ ЗАПРОС ТРЕБУЕТ РАСКЛАДА. Оценивай ТОЛЬКО текущее сообщение."
        
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
                result["message"] = "Я внимательно изучил ваш вопрос."
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
        interpretation_prompt = f"""Ты опытный таролог. Сделай подробную интерпретацию расклада.

    Информация о пользователе: {user_info['name'] if user_info else 'клиент'}, {user_info['age'] if user_info else 'возраст неизвестен'} лет
    Тема расклада: {spread_topic}
    Название расклада: {spread_name}
    Вопрос пользователя: {user_question}

    Карты в раскладе:
    {chr(10).join(cards_info)}

    Твоя задача:
    1. Сделай общий анализ расклада (1-2 предложения)
    2. Подробно опиши значение каждой карты в контексте её позиции (1-2 предложения на карту)
    3. Дай итоговый совет или вывод (1-2 предложения)

    ВАЖНО:
    - Говори от первого лица, как таролог
    - Не упоминай, что ты ИИ или бот
    - Используй дружелюбный, но профессиональный тон
    - Интерпретируй карты в контексте темы расклада ({spread_topic})
    - Если карта перевернутая, учитывай это в интерпретации
    - Будь конкретным, но не слишком категоричным

    Формат ответа: обычный текст, без JSON."""

        try:
            response = await self.client.chat.complete_async(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Ты опытный таролог. Давай подробные и полезные интерпретации раскладов."},
                    {"role": "user", "content": interpretation_prompt}
                ],
                temperature=0.7,
                max_tokens=1500
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