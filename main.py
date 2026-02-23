import random
from PIL import Image
import matplotlib.pyplot as plt
import os
from io import BytesIO
import asyncio
import contextlib
import logging



# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

deck = {
  0: "Шут",
  1: "Маг",
  2: "Верховная Жрица",
  3: "Императрица",
  4: "Император",
  5: "Иерофант",
  6: "Влюбленные",
  7: "Колесница",
  8: "Сила",
  9: "Отшельник",
  10: "Колесо Фортуны",
  11: "Справедливость",
  12: "Повешенный",
  13: "Смерть",
  14: "Умеренность",
  15: "Дьявол",
  16: "Башня",
  17: "Звезда",
  18: "Луна",
  19: "Солнце",
  20: "Суд",
  21: "Мир",
  22: "Туз Жезлов",
  23: "Двойка Жезлов",
  24: "Тройка Жезлов",
  25: "Четверка Жезлов",
  26: "Пятерка Жезлов",
  27: "Шестерка Жезлов",
  28: "Семерка Жезлов",
  29: "Восьмерка Жезлов",
  30: "Девятка Жезлов",
  31: "Десятка Жезлов",
  32: "Паж Жезлов",
  33: "Рыцарь Жезлов",
  34: "Королева Жезлов",
  35: "Король Жезлов",
  36: "Туз Кубков",
  37: "Двойка Кубков",
  38: "Тройка Кубков",
  39: "Четверка Кубков",
  40: "Пятерка Кубков",
  41: "Шестерка Кубков",
  42: "Семерка Кубков",
  43: "Восьмерка Кубков",
  44: "Девятка Кубков",
  45: "Десятка Кубков",
  46: "Паж Кубков",
  47: "Рыцарь Кубков",
  48: "Королева Кубков",
  49: "Король Кубков",
  50: "Туз Мечей",
  51: "Двойка Мечей",
  52: "Тройка Мечей",
  53: "Четверка Мечей",
  54: "Пятерка Мечей",
  55: "Шестерка Мечей",
  56: "Семерка Мечей",
  57: "Восьмерка Мечей",
  58: "Девятка Мечей",
  59: "Десятка Мечей",
  60: "Паж Мечей",
  61: "Рыцарь Мечей",
  62: "Королева Мечей",
  63: "Король Мечей",
  64: "Туз Пентаклей",
  65: "Двойка Пентаклей",
  66: "Тройка Пентаклей",
  67: "Четверка Пентаклей",
  68: "Пятерка Пентаклей",
  69: "Шестерка Пентаклей",
  70: "Семерка Пентаклей",
  71: "Восьмерка Пентаклей",
  72: "Девятка Пентаклей",
  73: "Десятка Пентаклей",
  74: "Паж Пентаклей",
  75: "Рыцарь Пентаклей",
  76: "Королева Пентаклей",
  77: "Король Пентаклей"
}

def random_3_cards():
    card1 = random.randint(0, 77)
    card2 = random.randint(0, 77)
    while card2 == card1:
        card2 = random.randint(0, 77)
    
    card3 = random.randint(0, 77)
    while card3 == card1 or card3 == card2:
        card3 = random.randint(0, 77)
    
    return card1, card2, card3


async def merge_images_async(image1, image2, image3):
    loop = asyncio.get_event_loop()
    
    image1_path = f'deck/{image1}.jpg'
    image2_path = f'deck/{image2}.jpg'
    image3_path = f'deck/{image3}.jpg'
    
    with contextlib.ExitStack() as stack:
        # Загружаем изображения
        img1 = await loop.run_in_executor(None, lambda: Image.open(image1_path))
        stack.callback(img1.close)
        
        img2 = await loop.run_in_executor(None, lambda: Image.open(image2_path))
        stack.callback(img2.close)
        
        img3 = await loop.run_in_executor(None, lambda: Image.open(image3_path))
        stack.callback(img3.close)
        
        # Конвертируем в RGB
        if img1.mode != 'RGB':
            img1 = img1.convert('RGB')
            stack.callback(img1.close)
        if img2.mode != 'RGB':
            img2 = img2.convert('RGB')
            stack.callback(img2.close)
        if img3.mode != 'RGB':
            img3 = img3.convert('RGB')
            stack.callback(img3.close)
        
        # Масштабируем
        target_height = max(img1.height, img2.height, img3.height)
        
        if img1.height != target_height:
            ratio = target_height / img1.height
            new_width = int(img1.width * ratio)
            img1 = img1.resize((new_width, target_height), Image.Resampling.LANCZOS)
            stack.callback(img1.close)
            
        if img2.height != target_height:
            ratio = target_height / img2.height
            new_width = int(img2.width * ratio)
            img2 = img2.resize((new_width, target_height), Image.Resampling.LANCZOS)
            stack.callback(img2.close)
            
        if img3.height != target_height:
            ratio = target_height / img3.height
            new_width = int(img3.width * ratio)
            img3 = img3.resize((new_width, target_height), Image.Resampling.LANCZOS)
            stack.callback(img3.close)
        
        # Создаем итоговое изображение (слева направо)
        total_width = img1.width + img2.width + img3.width
        new_image = Image.new('RGB', (total_width, target_height), color='white')
        stack.callback(new_image.close)
        
        # Вставляем в правильном порядке
        x_offset = 0
        new_image.paste(img1, (x_offset, 0))
        x_offset += img1.width
        new_image.paste(img2, (x_offset, 0))
        x_offset += img2.width
        new_image.paste(img3, (x_offset, 0))
        
        # Сохраняем
        img_bytes = BytesIO()
        await loop.run_in_executor(
            None, 
            lambda: new_image.save(img_bytes, format='PNG')
        )
        img_bytes.seek(0)
        
        return img_bytes

