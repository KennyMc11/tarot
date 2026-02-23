from mistralai import Mistral
from main import deck


# Простая функция для работы с API Mistral
def ask_mistral(cards, query, name, age):

    api_key = 'ubepjqpwvE39l1T0qBXfLzy2S0eOtSlj'
    # Создаем клиент
    client = Mistral(api_key=api_key)
    
    prompt = f'''Ты проффесиональный таролог. 
    Меня зовут {name}. Мне {age} лет.
    Вот мой вопрос к картам: "{query}"
    Вот какие каты мне выпали: {deck[cards[0]]}, {deck[cards[1]]}, {deck[cards[2]]}
    Как профессиональный таролог, расскажи что это значит.'''

    # Отправляем запрос
    model="mistral-tiny"
    response = client.chat.complete(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.choices[0].message.content