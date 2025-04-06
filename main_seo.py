import os
import sys
import logging
import asyncio
import requests
from requests.exceptions import Timeout
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import subprocess
import time
import threading

# Загрузка переменных окружения из .env файла
load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Состояния разговора
CHOOSING, ANALYZE_URL, CHATTING = range(3)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reply_keyboard = [
        [
             [KeyboardButton('Анализировать URL'), KeyboardButton('Поболтать')],
             [KeyboardButton('Перезагрузить')]
        ]
    ]

    await update.message.reply_text(
        'Привет! Я бот для анализа URL и бесед.\n\n'
        'Выберите действие:',
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return CHOOSING

# Обработчик кнопки "Анализировать URL"
async def analyze_url_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Пожалуйста, отправьте мне URL для анализа.')
    return ANALYZE_URL

# Обработка URL от пользователя
async def analyze_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = update.message.text

    # Отправка сообщения с песочными часами
    waiting_message = await update.message.reply_text('⏳ Пожалуйста, подождите, идет анализ URL...')

    try:
        # Извлечение контента из URL
        content = await asyncio.get_event_loop().run_in_executor(None, extract_content_from_url, url)

        # Отправка контента в DeepSeek API для анализа
        summary = await asyncio.get_event_loop().run_in_executor(None, analyze_content_with_deepseek, content)

        # Удаление сообщения с песочными часами
        await waiting_message.delete()

        # Отправка результата пользователю
        await update.message.reply_text('Краткое содержание:\n\n' + summary)
    except Timeout:
        await waiting_message.delete()
        await update.message.reply_text('Модель сейчас очень занята, попробуйте позже.')
    except Exception as e:
        logger.error(f'Ошибка при обработке URL: {e}')
        await waiting_message.delete()
        await update.message.reply_text(f'Произошла ошибка при обработке URL. Пожалуйста, убедитесь, что вы отправили корректный URL.- {e}')

    # Возврат к выбору действия
    return await start(update, context)

# Обработчик кнопки "Поболтать"
async def start_chatting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        'Давайте поболтаем! Напишите мне что-нибудь.\n\n'
        'Для выхода из режима беседы отправьте команду /exit или напишите "выход".'
    )
    return CHATTING

# Обычный диалог с пользователем в состоянии CHATTING
async def chat_with_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_message = update.message.text

    # Проверка на ввод слова "выход"
    if user_message.lower() == 'выход':
        return await exit_chatting(update, context)

    # Отправка сообщения с песочными часами
    waiting_message = await update.message.reply_text('⏳ Пожалуйста, подождите, идет формирование ответа...')

    try:
        # Обращение к DeepSeek API для обычного диалога с моделью 'deepseek-chat'
        response_text = await asyncio.get_event_loop().run_in_executor(None, chat_with_deepseek, user_message)

        # Удаление сообщения с песочными часами
        await waiting_message.delete()

        # Отправка ответа пользователю
        await update.message.reply_text(response_text)
    except Timeout:
        await waiting_message.delete()
        await update.message.reply_text('Модель сейчас очень занята, попробуйте позже.')
    except Exception as e:
        logger.error(f'Ошибка при общении с DeepSeek: {e}')
        await waiting_message.delete()
        await update.message.reply_text(f'Произошла ошибка при обработке вашего сообщения. Пожалуйста, попробуйте позже {e}.')

    return CHATTING  # Остаёмся в состоянии CHATTING для продолжения диалога

# Команда /exit для выхода из состояния CHATTING
async def exit_chatting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Вы вышли из режима беседы.')
    return await start(update, context)

# Обработка текстовых сообщений вне состояний
async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
   await update.message.reply_text(
       'Извините, я не понимаю эту команду. Пожалуйста, выберите действие из меню или введите корректную команду.'
   )

# Функция для извлечения текста с веб-страницы
def extract_content_from_url(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=120)
    except Timeout:
        raise Timeout("Превышено время ожидания при получении контента URL.")
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')

    # Удаляем скрипты и стили
    for script in soup(['script', 'style']):
        script.decompose()

    paragraphs = soup.find_all('p')
    text = '\n'.join([p.get_text() for p in paragraphs])
    
    return text

# Функция для отправки контента в DeepSeek API для анализа
def analyze_content_with_deepseek(content):
    # Ограничение длины контента, если необходимо
    max_content_length = 1500  # Настройте по своему усмотрению
    if len(content) > max_content_length:
        content = content[:max_content_length] + "..."

    # Создаем промпт для получения краткого содержания
    prompt = f"Пожалуйста, сделай перевод на русский язык и краткое содержание следующего текста:\n\n{content}"

    # Код обращения к DeepSeek API
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    data = {
        "model": "deepseek-reasoner",  # Используем модель 'deepseek-reasoner' для анализа URL
        "messages": [
            {"role": "system", "content": "You are a professional assistant who summarizes texts in russian"},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
    except Timeout:
        raise Timeout("Превышено время ожидания при общении с DeepSeek API.")
    response.raise_for_status()
    result = response.json()

    # Получаем ответ ассистента
    summary = result['choices'][0]['message']['content']
    return summary

# Функция для обычного диалога с DeepSeek API
def chat_with_deepseek(user_message):
    # Код обращения к DeepSeek API
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    data = {
        "model": "deepseek-chat",  # Используем модель 'deepseek-chat' для общения
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_message}
        ],
        "stream": False
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
    except Timeout:
        raise Timeout("Превышено время ожидания при общении с DeepSeek API.")
    response.raise_for_status()
    result = response.json()

    # Получаем ответ ассистента
    reply = result['choices'][0]['message']['content']
    return reply

async def reboot_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Бот перезапускается...')
    # Здесь вы можете добавить логику для сброса состояния или перезапуска
    # Например, вернём пользователя в начальное состояние
    return await start(update, context)

def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    logger.info("Бот запущен.")

    # Определение обработчиков разговоров
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING: [
                MessageHandler(filters.Regex('Анализировать URL', flags=re.IGNORECASE), analyze_url_start),
                MessageHandler(filters.Regex('Поболтать', flags=re.IGNORECASE), start_chatting),
                MessageHandler(filters.Regex('Перезагрузить', flags=re.IGNORECASE), reboot_bot)
            ],
            ANALYZE_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_url_received)
            ],
            CHATTING: [
                MessageHandler(filters.Regex('^(выход)$'), exit_chatting),
                MessageHandler(filters.TEXT & ~filters.COMMAND, chat_with_user)
            ]
        },
        fallbacks=[CommandHandler('start', start)],
    )

    # Добавление обработчиков в приложение
    application.add_handler(conv_handler)

    # Обработчик для неизвестных сообщений и команд
    application.add_handler(MessageHandler(filters.COMMAND, unknown_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    # Запуск бота с параметром drop_pending_updates=True
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()