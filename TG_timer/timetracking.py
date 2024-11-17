import asyncio
import asyncpg
from asyncpg import create_pool
from datetime import datetime, timedelta
import logging
logging.basicConfig(level=logging.INFO)
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from env import API_TOKEN, host, port, user, password, dbname


async def save_time_entry(user_id, telegram_id, project_name, start_time, end_time, duration, comment):
    conn = await asyncpg.connect(
        user=user,
        password=password,
        database=dbname,
        host=host.split('@')[-1].split(':')[0],
        port=port
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE NOT NULL,
            project_name TEXT NOT NULL,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration INTERVAL,
            comment TEXT
        );
    """)

    await conn.execute("""
        INSERT INTO users (telegram_id) 
        VALUES ($1) 
        ON CONFLICT (telegram_id) DO NOTHING
    """, telegram_id)

    user_id = await conn.fetchval("""
        SELECT id FROM users WHERE telegram_id = $1
    """, telegram_id)

    await conn.execute("""
        INSERT INTO projects (user_id, project_name, start_time, end_time, duration, comment)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, user_id, project_name, start_time, end_time, duration, comment)

    await conn.close()

# Создаем объекты бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Переменные для отслеживания состояния пользователей
user_timers = {}  # Хранение таймеров и состояния для каждого пользователя
user_projects = {}  # Хранение проектов для каждого пользователя

# Функция для обработки команды /start
@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id

    # Если у пользователя нет проектов
    if user_id not in user_projects or not user_projects[user_id]:
        user_timers[user_id] = {'state': 'awaiting_new_project'}
        await message.answer("Введи название нового проекта:", reply_markup=types.ReplyKeyboardRemove())
    else:
        buttons = [[KeyboardButton(text=project_name) for project_name in user_projects[user_id]], [KeyboardButton(text="Новый проект")]]
        keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        user_timers[user_id] = {'state': 'selecting_project'}
        await message.answer("Выбери проект или добавь новый:", reply_markup=keyboard)

# Функция для обработки ввода названия нового проекта
@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'awaiting_new_project')
async def handle_new_project(message: types.Message):
    user_id = message.from_user.id
    project_name = message.text.strip()

    if project_name:
        if user_id not in user_projects:
            user_projects[user_id] = []
        user_projects[user_id].append(project_name)

        user_timers[user_id] = {
            'project': project_name,
            'start_time': datetime.now(),
            'state': 'running'
        }
        buttons = [[KeyboardButton(text="Стоп")]]
        keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await message.answer(f"Проект '{project_name}' добавлен, таймер запущен! Нажми 'Стоп' для остановки.", reply_markup=keyboard)

# Функция для выбора существующего проекта
@dp.message(lambda message: message.text in user_projects.get(message.from_user.id, []) and user_timers.get(message.from_user.id, {}).get('state') == 'selecting_project')
async def project_selection(message: types.Message):
    user_id = message.from_user.id
    user_timers[user_id] = {
        'project': message.text,
        'start_time': datetime.now(),
        'state': 'running'
    }
    buttons = [[KeyboardButton(text="Стоп")]]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer(f"Таймер для '{message.text}' запущен! Нажми 'Стоп' для остановки.", reply_markup=keyboard)

# Функция для обработки запроса на создание нового проекта
@dp.message(lambda message: message.text == "Новый проект")
async def request_new_project(message: types.Message):
    user_id = message.from_user.id
    user_timers[user_id] = {'state': 'awaiting_new_project'}
    await message.answer("Введи название нового проекта:", reply_markup=types.ReplyKeyboardRemove())


# Функция для обработки команды "Стоп"
@dp.message(lambda message: message.text == "Стоп" and user_timers.get(message.from_user.id, {}).get('state') == 'running')
async def cmd_stop(message: types.Message):
    user_id = message.from_user.id

    if user_id in user_timers and user_timers[user_id]['start_time']:
        start_time = user_timers[user_id]['start_time']
        end_time = datetime.now()
        elapsed_time = end_time - start_time

        # Сохраняем в user_timers время и ожидаем комментарий
        user_timers[user_id]['end_time'] = end_time
        user_timers[user_id]['duration'] = elapsed_time
        user_timers[user_id]['state'] = 'awaiting_comment'

        await message.answer(
            f"Таймер остановлен. Введи комментарий:",
            reply_markup=types.ReplyKeyboardRemove()
        )

# Обработка комментария
@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'awaiting_comment')
async def handle_comment(message: types.Message):
    user_id = message.from_user.id
    telegram_id = message.from_user.id  # telegram_id тот же, что и user_id
    project_name = user_timers[user_id]['project']
    start_time = user_timers[user_id]['start_time']
    end_time = user_timers[user_id]['end_time']
    duration = user_timers[user_id]['duration']
    elapsed_time = end_time - start_time
    comment = message.text

   # Преобразование времени в формат hh:mm
    hours, remainder = divmod(elapsed_time.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)
    formatted_time = f"{int(hours):02}:{int(minutes):02}"


    # Сохранение в БД
    await save_time_entry(user_id, telegram_id, project_name, start_time, end_time, duration, comment)

    # Предложение выбрать проект
    user_timers[user_id] = {'state': 'selecting_project'}
    buttons = [[KeyboardButton(text=project_name) for project_name in user_projects[user_id]], [KeyboardButton(text="Новый проект")]]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    await message.answer(
        f"Комментарий: {comment}\nВремя: {formatted_time}."
    )
    await message.answer(
        f"Выбери следующий проект или добавь новый.")
    reply_markup=keyboard


# Запуск бота
async def main():
    db = await create_pool(
        user=user,
        password=password,
        database=dbname,
        host=host.split('@')[-1].split(':')[0],
        port=port
    )

    # Получаем название базы данных
    async with db.acquire() as connection:
        db_name = await connection.fetchval("SELECT current_database()")
        print(f"Подключение установлено к базе данных: {db_name}")

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
