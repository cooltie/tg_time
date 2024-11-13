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


async def save_time_entry(user_id, project_name, start_time, end_time, duration, comment):
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
            telegram_id BIGINT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS projects (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            project_name TEXT,
            project_id INT REFERENCES projects(id) ON DELETE CASCADE,
            entry_datetime TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration INTERVAL,
            comment TEXT
        )
    """)
    await conn.execute("""
            INSERT INTO projects (user_id, project_name, start_time, end_time, duration, comment)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, user_id, project_name, start_time, end_time, duration, comment)

    ("""
            INSERT INTO users (telegram_id, username)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO NOTHING
        """, telegram_id)
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

@dp.message(Command('stats'))
async def show_stats_menu(message: types.Message):
    # Создаем кнопки для выбора статистики
    buttons = [
        [KeyboardButton(text="За день")],
        [KeyboardButton(text="За неделю")],
        [KeyboardButton(text="За месяц")]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    # Отправляем сообщение с выбором
    await message.answer("Выбери период статистики:", reply_markup=keyboard)

# Обработка кнопки "За день"
@dp.message(lambda message: message.text == "За день")
async def stats_for_day(message: types.Message):
    today = datetime.now().strftime("%d.%m.%y")
    projects_data = get_project_data_for_period('day')  # Функция для получения данных за день
    response = format_stats_response(projects_data, today, "Всего за сегодня")
    await message.answer(response)

# Обработка кнопки "За неделю"
@dp.message(lambda message: message.text == "За неделю")
async def stats_for_week(message: types.Message):
    start_of_week = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%d.%m.%y")
    today = datetime.now().strftime("%d.%m.%y")
    projects_data = get_project_data_for_period('week')  # Функция для получения данных за неделю
    response = format_stats_response(projects_data, f"{start_of_week} - {today}", "Всего за неделю")
    await message.answer(response)

# Обработка кнопки "За месяц"
@dp.message(lambda message: message.text == "За месяц")
async def stats_for_month(message: types.Message):
    start_of_month = datetime.now().replace(day=1).strftime("%d.%m.%y")
    today = datetime.now().strftime("%d.%m.%y")
    projects_data = get_project_data_for_period('month')  # Функция для получения данных за месяц
    response = format_stats_response(projects_data, f"{start_of_month} - {today}", "Всего за месяц")
    await message.answer(response)

# Функция для получения данных за указанный период
def get_project_data_for_period(period):
    # Реализуйте логику для получения данных из Google Spreadsheet за указанный период
    pass

# Функция для форматирования ответа
def format_stats_response(projects_data, date_range, total_label):
    response = ""
    for project, total_time in projects_data.items():
        response += f"<b>{project}</b>\n{date_range}\n{total_label}: {total_time}\n\n"
    return response


# Функция для обработки команды "Стоп"
@dp.message(lambda message: message.text == "Стоп" and user_timers.get(message.from_user.id, {}).get('state') == 'running')
async def cmd_stop(message: types.Message):
    user_id = message.from_user.id

    if user_id in user_timers and user_timers[user_id]['start_time']:
        start_time = user_timers[user_id]['start_time']
        end_time = datetime.now()
        elapsed_time = end_time - start_time

        # Преобразование времени в формат hh:mm
        hours, remainder = divmod(elapsed_time.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        formatted_time = f"{int(hours):02}:{int(minutes):02}"

        user_timers[user_id]['state'] = 'awaiting_comment'
        user_timers[user_id]['formatted_time'] = formatted_time
        try:
            # Пробуем записать данные в Google Spreadsheet
            await message.answer("Таймер остановлен! Введи комментарий:")
        except Exception as e:
            # Обработка ошибки при работе с Google Spreadsheet
            await message.answer("Ошибка при попытке отправить данные на сервер. Связь с сервером прервалась.")
            # Логируем ошибку (если есть логирование)
            print(f"Ошибка: {e}")

            # Фиксируем остановку таймера и сохраняем данные локально (в памяти)
            # Можно добавить механизм повторной отправки данных позже
            user_timers[user_id] = {
                'project': user_timers[user_id]['project'],
                'formatted_time': formatted_time,
                'state': 'error',  # В случае ошибки устанавливаем состояние
            #                'error'
                'error_time': datetime.now()  # Фиксируем время
            #                возникновения ошибки
            }

# Обработка комментария
@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'awaiting_comment')
async def handle_comment(message: types.Message):
    user_id = message.from_user.id
    project_name = user_timers[user_id]['project']
    formatted_time = user_timers[user_id]['formatted_time']
    current_date = datetime.now().strftime("%d.%m.%y")
    comment = message.text

    start_time = user_timers[user_id]['start_time']
    end_time = datetime.now()

    duration = end_time - start_time
    await save_time_entry(user_id, project_name, start_time, end_time, duration, comment)

    try:
        # Возвращаемся в состояние выбора проекта
        user_timers[user_id] = {'state': 'selecting_project'}

        # Выводим сообщение и предлагаем выбрать проект или добавить новый
        buttons = [[KeyboardButton(text=project_name) for project_name in user_projects[user_id]], [KeyboardButton(text="Новый проект")]]
        keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

        await message.answer(
            f"Ура, данные сохранены! \nПроект: {project_name} занял: {formatted_time}\nКомментарий: {comment}\nВыбери следующий проект или добавь новый:",
            reply_markup=keyboard
        )

    except Exception as e:
        # Обработка ошибки при отправке комментария
        await message.answer("Ошибка при попытке отправить данные на сервер. Связь с сервером прервалась.")
        print(f"Ошибка: {e}")

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
