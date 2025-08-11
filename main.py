import asyncio
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncpg
from dotenv import load_dotenv
import re

# Загрузка данных из .env
load_dotenv()

# Получение переменных окружения
API_TOKEN = os.getenv('API_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

logging.basicConfig(level=logging.INFO)


async def get_user_projects(telegram_id):
    """Получает список уникальных проектов пользователя из БД"""
    conn = await asyncpg.connect(DATABASE_URL)

    # Создаем таблицы если их нет
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

    # Получаем уникальные проекты пользователя
    projects = await conn.fetch("""
        SELECT DISTINCT p.project_name
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1
        ORDER BY p.project_name
    """, telegram_id)

    await conn.close()
    return [project['project_name'] for project in projects]


async def get_stats_for_period(telegram_id, days=None):
    """Получает статистику пользователя за определенный период"""
    conn = await asyncpg.connect(DATABASE_URL)

    if days:
        # Статистика за последние N дней
        stats = await conn.fetch(f"""
            SELECT
                p.project_name,
                COUNT(*) as sessions_count,
                SUM(EXTRACT(EPOCH FROM p.duration)) as total_seconds
            FROM projects p
            JOIN users u ON p.user_id = u.id
            WHERE u.telegram_id = $1
                AND p.start_time >= NOW() - INTERVAL '{days} days'
                AND p.duration IS NOT NULL
            GROUP BY p.project_name
            ORDER BY total_seconds DESC
        """, telegram_id)
    else:
        # Статистика за все время
        stats = await conn.fetch("""
            SELECT
                p.project_name,
                COUNT(*) as sessions_count,
                SUM(EXTRACT(EPOCH FROM p.duration)) as total_seconds
            FROM projects p
            JOIN users u ON p.user_id = u.id
            WHERE u.telegram_id = $1
                AND p.duration IS NOT NULL
            GROUP BY p.project_name
            ORDER BY total_seconds DESC
        """, telegram_id)

    await conn.close()
    return stats


def format_stats_message(stats, period_name):
    """Форматирует статистику в красивое сообщение"""
    if not stats:
        return f"📊 Статистика {period_name}\n\nДанных пока нет."

    message = f"📊 Статистика {period_name}\n\n"
    total_time = 0

    for project in stats:
        name = project['project_name']
        sessions = project['sessions_count']
        seconds = project['total_seconds'] or 0
        total_time += seconds

        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = f"{int(hours):02}:{int(minutes):02}"

        message += f"🔸 {name}\n"
        message += f"   Время: {time_str} ({sessions} сессий)\n\n"

    # Общее время
    total_hours, remainder = divmod(total_time, 3600)
    total_minutes, _ = divmod(remainder, 60)
    total_time_str = f"{int(total_hours):02}:{int(total_minutes):02}"

    message += f"⏱ Общее время: {total_time_str}"
    return message


async def get_project_stats(telegram_id, project_name):
    """Получает детальную статистику по конкретному проекту"""
    conn = await asyncpg.connect(DATABASE_URL)

    stats = await conn.fetch("""
        SELECT
            DATE(p.start_time) as work_date,
            COUNT(*) as sessions_count,
            SUM(EXTRACT(EPOCH FROM p.duration)) as total_seconds
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1
            AND p.project_name = $2
            AND p.duration IS NOT NULL
        GROUP BY DATE(p.start_time)
        ORDER BY work_date DESC
        LIMIT 10
    """, telegram_id, project_name)

    total_stats = await conn.fetchrow("""
        SELECT
            COUNT(*) as total_sessions,
            SUM(EXTRACT(EPOCH FROM p.duration)) as total_seconds
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1
            AND p.project_name = $2
            AND p.duration IS NOT NULL
    """, telegram_id, project_name)

    await conn.close()
    return stats, total_stats


def validate_date_format(date_text):
    """Валидация формата даты ДД ММ ГГ"""
    pattern = r'^(\d{1,2})\s+(\d{1,2})\s+(\d{2})$'
    match = re.match(pattern, date_text.strip())
    if not match:
        return None
    
    day, month, year = map(int, match.groups())
    
    # Проверяем корректность даты
    try:
        # Год 20XX
        full_year = 2000 + year
        date_obj = datetime(full_year, month, day)
        return date_obj
    except ValueError:
        return None


def validate_time_format(time_text):
    """Валидация формата времени ЧЧ:ММ"""
    pattern = r'^(\d{1,2}):(\d{2})$'
    match = re.match(pattern, time_text.strip())
    if not match:
        return None
    
    hours, minutes = map(int, match.groups())
    
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        return None
    
    return hours * 3600 + minutes * 60  # возвращаем секунды


async def save_manual_entry(user_id, message):
    """Сохраняет ручную запись времени"""
    timer_data = user_timers.get(user_id, {})
    
    project_name = timer_data.get('manual_project')
    manual_date = timer_data.get('manual_date')
    manual_duration_seconds = timer_data.get('manual_duration_seconds')
    manual_comment = timer_data.get('manual_comment')
    
    if not all([project_name, manual_date, manual_duration_seconds, manual_comment]):
        await message.edit_text("❌ Ошибка: не все данные заполнены.")
        return
    
    # Создаем start_time и end_time
    start_time = manual_date
    duration_td = timedelta(seconds=manual_duration_seconds)
    end_time = start_time + duration_td
    
    # Сохраняем в БД
    await save_time_entry(user_id, user_id, project_name, start_time, end_time, duration_td, manual_comment)
    
    # Обновляем локальный кэш проектов
    if user_id not in user_projects:
        user_projects[user_id] = []
    if project_name not in user_projects[user_id]:
        user_projects[user_id].append(project_name)
    
    # Очищаем состояние
    user_timers[user_id] = {'state': 'idle'}
    
    # Форматируем время для отображения
    hours, remainder = divmod(manual_duration_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    time_str = f"{int(hours):02}:{int(minutes):02}"
    
    await message.edit_text(f"✅ Запись сохранена!\n\n"
                           f"Проект: {project_name}\n"
                           f"Дата: {manual_date.strftime('%d.%m.%Y')}\n"
                           f"Время: {time_str}\n"
                           f"Комментарий: {manual_comment}")


async def save_time_entry(user_id, telegram_id, project_name, start_time, end_time, duration, comment):
    conn = await asyncpg.connect(DATABASE_URL)
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

# Функция для обработки команды /manual
@dp.message(Command('manual'))
async def cmd_manual(message: types.Message):
    user_id = message.from_user.id
    
    # Получаем проекты пользователя из БД
    projects = await get_user_projects(user_id)
    
    if not projects:
        # Если проектов нет, предлагаем создать новый
        user_timers[user_id] = {'state': 'manual_awaiting_new_project'}
        await message.answer("У вас пока нет проектов. Введите название нового проекта:")
    else:
        # Показываем список проектов + кнопка добавить новый
        buttons = []
        for project_name in projects:
            buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"manual_project:{project_name}")])
        buttons.append([InlineKeyboardButton(text="Добавить новый", callback_data="manual_new_project")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите проект для ручного добавления времени:", reply_markup=keyboard)


# Функция для обработки команды /stats
@dp.message(Command('stats'))
async def cmd_stats(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text="📅 За неделю", callback_data="stats:week")],
        [InlineKeyboardButton(text="📆 За месяц", callback_data="stats:month")],
        [InlineKeyboardButton(text="📊 По проекту (за все время)", callback_data="stats:project")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выбери период для статистики:", reply_markup=keyboard)


# Функция для обработки команды /start
@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id

    # Получаем проекты пользователя из БД
    projects = await get_user_projects(user_id)

    # Обновляем локальный кэш проектов
    user_projects[user_id] = projects

    # Если у пользователя нет проектов в БД
    if not projects:
        user_timers[user_id] = {'state': 'awaiting_new_project'}
        await message.answer(
            "Введи название нового проекта:",
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        buttons = []
        for project_name in projects:
            buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"project:{project_name}")])
        buttons.append([InlineKeyboardButton(text="Добавить новый", callback_data="new_project")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        user_timers[user_id] = {'state': 'selecting_project'}
        await message.answer(
            "Выбери проект или создай новый:",
            reply_markup=keyboard
        )

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
        buttons = [[InlineKeyboardButton(text="⏹ Стоп", callback_data="stop_timer")]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(f"Проект '{project_name}' добавлен, таймер запущен! Нажми 'Стоп' для остановки.", reply_markup=keyboard)

# Обработчик инлайн-кнопок
@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if callback.data.startswith("project:"):
        # Выбор существующего проекта
        project_name = callback.data.replace("project:", "")
        user_timers[user_id] = {
            'project': project_name,
            'start_time': datetime.now(),
            'state': 'running'
        }
        buttons = [[InlineKeyboardButton(text="⏹ Стоп", callback_data="stop_timer")]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Таймер для '{project_name}' запущен! Нажми 'Стоп' для остановки.", reply_markup=keyboard)

    elif callback.data == "new_project":
        # Создание нового проекта
        user_timers[user_id] = {'state': 'awaiting_new_project'}
        await callback.message.edit_text("Введи название нового проекта:")

    elif callback.data == "stop_timer":
        # Остановка таймера
        if user_id in user_timers and user_timers[user_id].get('start_time'):
            start_time = user_timers[user_id]['start_time']
            end_time = datetime.now()
            elapsed_time = end_time - start_time

            # Сохраняем в user_timers время и ожидаем комментарий
            user_timers[user_id]['end_time'] = end_time
            user_timers[user_id]['duration'] = elapsed_time
            user_timers[user_id]['state'] = 'awaiting_comment'

            await callback.message.edit_text("Таймер остановлен. Введи комментарий:")

    elif callback.data.startswith("stats:"):
        # Обработка статистики
        stats_type = callback.data.replace("stats:", "")

        if stats_type == "week":
            stats = await get_stats_for_period(user_id, 7)
            message = format_stats_message(stats, "за неделю")
            await callback.message.edit_text(message)

        elif stats_type == "month":
            stats = await get_stats_for_period(user_id, 30)
            message = format_stats_message(stats, "за месяц")
            await callback.message.edit_text(message)

        elif stats_type == "project":
            # Показать список проектов для выбора
            projects = await get_user_projects(user_id)
            if not projects:
                await callback.message.edit_text("У вас пока нет проектов.")
            else:
                buttons = []
                for project_name in projects:
                    buttons.append([InlineKeyboardButton(
                        text=project_name,
                        callback_data=f"project_stats:{project_name}"
                    )])
                keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                await callback.message.edit_text(
                    "Выбери проект для просмотра статистики:",
                    reply_markup=keyboard
                )

    elif callback.data.startswith("project_stats:"):
        # Статистика по конкретному проекту
        project_name = callback.data.replace("project_stats:", "")
        daily_stats, total_stats = await get_project_stats(user_id, project_name)

        if not total_stats or not total_stats['total_seconds']:
            await callback.message.edit_text(f"📊 Проект: {project_name}\n\nДанных пока нет.")
        else:
            total_seconds = total_stats['total_seconds']
            total_sessions = total_stats['total_sessions']

            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            total_time_str = f"{int(hours):02}:{int(minutes):02}"

            message = f"📊 Проект: {project_name}\n\n"
            message += f"⏱ Общее время: {total_time_str}\n"
            message += f"📋 Всего сессий: {total_sessions}\n\n"

            if daily_stats:
                message += "📅 Последние 10 дней:\n"
                for day in daily_stats:
                    date = day['work_date'].strftime("%d.%m")
                    sessions = day['sessions_count']
                    seconds = day['total_seconds'] or 0

                    day_hours, remainder = divmod(seconds, 3600)
                    day_minutes, _ = divmod(remainder, 60)
                    day_time = f"{int(day_hours):02}:{int(day_minutes):02}"

                    message += f"• {date}: {day_time} ({sessions} сессий)\n"
            
            await callback.message.edit_text(message)
    
    elif callback.data.startswith("manual_project:"):
        # Ручное добавление для существующего проекта
        project_name = callback.data.replace("manual_project:", "")
        user_timers[user_id] = {
            'state': 'manual_awaiting_date',
            'manual_project': project_name
        }
        await callback.message.edit_text(f"Проект: {project_name}\n\nВведите дату в формате ДД ММ ГГ (например: 15 08 24):")
    
    elif callback.data == "manual_new_project":
        # Создание нового проекта для ручного добавления
        user_timers[user_id] = {'state': 'manual_awaiting_new_project'}
        await callback.message.edit_text("Введите название нового проекта:")
    
    elif callback.data == "manual_save":
        # Сохранение ручной записи
        await save_manual_entry(user_id, callback.message)
    
    await callback.answer()



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
    buttons = []
    for project_name in user_projects[user_id]:
        buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"project:{project_name}")])
    buttons.append([InlineKeyboardButton(text="Добавить новый", callback_data="new_project")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        f"Комментарий: {comment}\nВремя: {formatted_time}."
    )
    await message.answer(
        "Выбери следующий проект или добавь новый:",
        reply_markup=keyboard
    )


# Обработчики для ручного ввода времени
@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'manual_awaiting_new_project')
async def handle_manual_new_project(message: types.Message):
    user_id = message.from_user.id
    project_name = message.text.strip()

    if project_name:
        # Добавляем проект в локальный кэш
        if user_id not in user_projects:
            user_projects[user_id] = []
        user_projects[user_id].append(project_name)

        # Переходим к вводу даты
        user_timers[user_id] = {
            'state': 'manual_awaiting_date',
            'manual_project': project_name
        }
        await message.answer(f"Проект: {project_name}\n\nВведите дату в формате ДД ММ ГГ (например: 15 08 24):")


@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'manual_awaiting_date')
async def handle_manual_date(message: types.Message):
    user_id = message.from_user.id
    date_text = message.text.strip()
    
    parsed_date = validate_date_format(date_text)
    if not parsed_date:
        await message.answer("❌ Неверный формат даты. Используйте формат ДД ММ ГГ (например: 15 08 24):")
        return
    
    # Сохраняем дату и переходим к вводу времени
    user_timers[user_id]['manual_date'] = parsed_date
    user_timers[user_id]['state'] = 'manual_awaiting_time'
    
    await message.answer(f"Дата: {parsed_date.strftime('%d.%m.%Y')}\n\nВведите количество затраченных часов в формате ЧЧ:ММ (например: 02:30):")


@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'manual_awaiting_time')
async def handle_manual_time(message: types.Message):
    user_id = message.from_user.id
    time_text = message.text.strip()
    
    duration_seconds = validate_time_format(time_text)
    if duration_seconds is None:
        await message.answer("❌ Неверный формат времени. Используйте формат ЧЧ:ММ (например: 02:30):")
        return
    
    # Сохраняем время и переходим к вводу комментария
    user_timers[user_id]['manual_duration_seconds'] = duration_seconds
    user_timers[user_id]['state'] = 'manual_awaiting_comment'
    
    await message.answer(f"Время: {time_text}\n\nВведите комментарий:")


@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'manual_awaiting_comment')
async def handle_manual_comment(message: types.Message):
    user_id = message.from_user.id
    comment = message.text.strip()
    
    # Сохраняем комментарий
    user_timers[user_id]['manual_comment'] = comment
    user_timers[user_id]['state'] = 'manual_ready_to_save'
    
    # Показываем сводку и кнопку сохранения
    timer_data = user_timers[user_id]
    project_name = timer_data['manual_project']
    manual_date = timer_data['manual_date']
    duration_seconds = timer_data['manual_duration_seconds']
    
    hours, remainder = divmod(duration_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    time_str = f"{int(hours):02}:{int(minutes):02}"
    
    buttons = [[InlineKeyboardButton(text="💾 Сохранить", callback_data="manual_save")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await message.answer(
        f"📋 Проверьте данные:\n\n"
        f"Проект: {project_name}\n"
        f"Дата: {manual_date.strftime('%d.%m.%Y')}\n"
        f"Время: {time_str}\n"
        f"Комментарий: {comment}\n\n"
        f"Нажмите 'Сохранить' для подтверждения:",
        reply_markup=keyboard
    )


# Запуск бота
async def main():
    db = await asyncpg.create_pool(DATABASE_URL)

    # Получаем название базы данных
    async with db.acquire() as connection:
        db_name = await connection.fetchval("SELECT current_database()")
        print(f"Подключение установлено к базе данных: {db_name}")

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
