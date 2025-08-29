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
from collections import defaultdict

# Загрузка данных из .env
load_dotenv()

# Получение переменных окружения
API_TOKEN = os.getenv('API_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

logging.basicConfig(level=logging.INFO)


async def check_user_exists(telegram_id):
    """Проверяет, существует ли пользователь в БД"""
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

    # Проверяем существование пользователя
    user_exists = await conn.fetchval("""
        SELECT EXISTS(SELECT 1 FROM users WHERE telegram_id = $1)
    """, telegram_id)

    # Если пользователя нет, создаем его
    if not user_exists:
        await conn.execute("""
            INSERT INTO users (telegram_id) VALUES ($1)
        """, telegram_id)

    await conn.close()
    return user_exists


async def get_user_projects(telegram_id):
    """Получает список уникальных проектов пользователя из БД"""
    conn = await asyncpg.connect(DATABASE_URL)

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
    """Получает статистику пользователя за период: сессии по проектам"""
    conn = await asyncpg.connect(DATABASE_URL)

    if days:
        rows = await conn.fetch(
            """
            SELECT
                p.project_name,
                p.start_time,
                EXTRACT(EPOCH FROM p.duration) AS seconds,
                p.comment
            FROM projects p
            JOIN users u ON p.user_id = u.id
            WHERE u.telegram_id = $1
              AND p.start_time >= NOW() - make_interval(days => $2::int)
              AND p.duration IS NOT NULL
            ORDER BY p.start_time DESC
            """,
            telegram_id,
            days,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT
                p.project_name,
                p.start_time,
                EXTRACT(EPOCH FROM p.duration) AS seconds,
                p.comment
            FROM projects p
            JOIN users u ON p.user_id = u.id
            WHERE u.telegram_id = $1
              AND p.duration IS NOT NULL
            ORDER BY p.start_time DESC
            """,
            telegram_id,
        )

    await conn.close()

    stats = {}
    for r in rows:
        name = r["project_name"]
        session = {
            "seconds": int(r["seconds"] or 0),
            "comment": r["comment"] or "",
            "start_time": r["start_time"],
        }
        stats.setdefault(name, []).append(session)

    return stats


async def get_stats_for_current_week(telegram_id):
    """Сессии за текущую календарную неделю (пн–вс)"""
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        """
        SELECT
            p.project_name,
            p.start_time,
            EXTRACT(EPOCH FROM p.duration) AS seconds,
            p.comment
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1
          AND p.duration IS NOT NULL
          AND p.start_time >= date_trunc('week', now())
          AND p.start_time <  date_trunc('week', now()) + interval '7 days'
        ORDER BY p.start_time ASC
        """,
        telegram_id,
    )
    await conn.close()

    stats = {}
    for r in rows:
        name = r["project_name"]
        session = {
            "seconds": int(r["seconds"] or 0),
            "comment": r["comment"] or "",
            "start_time": r["start_time"],
        }
        stats.setdefault(name, []).append(session)
    return stats


async def get_stats_for_current_month(telegram_id):
    """Сессии за текущий календарный месяц (с 1 числа)"""
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        """
        SELECT
            p.project_name,
            p.start_time,
            EXTRACT(EPOCH FROM p.duration) AS seconds,
            p.comment
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1
          AND p.duration IS NOT NULL
          AND p.start_time >= date_trunc('month', now())
          AND p.start_time <  date_trunc('month', now()) + interval '1 month'
        ORDER BY p.start_time ASC
        """,
        telegram_id,
    )
    await conn.close()

    stats = {}
    for r in rows:
        name = r["project_name"]
        session = {
            "seconds": int(r["seconds"] or 0),
            "comment": r["comment"] or "",
            "start_time": r["start_time"],
        }
        stats.setdefault(name, []).append(session)
    return stats

def format_stats_message(stats, period_name):
    """Формат: заголовок, затем по датам: проект, итоги за период,
    далее строки "дата/время/что делал(а)"."""
    if not stats:
        return f"📊 Статистика {period_name}\n\nДанных пока нет."

    # Итоги за период по каждому проекту
    totals_by_project = {}
    for project_name, sessions in stats.items():
        total_seconds = sum(int(s.get("seconds") or 0) for s in sessions)
        totals_by_project[project_name] = {
            "sessions_count": len(sessions),
            "total_seconds": int(total_seconds),
        }

    # Группировка по дате -> проект -> сессии
    grouped = defaultdict(lambda: defaultdict(list))
    for project_name, sessions in stats.items():
        for s in sessions:
            start_dt = s.get("start_time")
            if not start_dt:
                continue
            date_key = start_dt.date()
            grouped[date_key][project_name].append(s)

    lines = [f"📊 Статистика {period_name}", ""]

    for date_key in sorted(grouped.keys(), reverse=True):
        lines.append(f"## {date_key.strftime('%d.%m.%Y')}")
        lines.append("")

        projects_for_date = grouped[date_key]
        for project_name in sorted(projects_for_date.keys()):
            lines.append(f"{project_name}")
            for s in projects_for_date[project_name]:
                seconds = int(s.get("seconds") or 0)
                h, rem = divmod(seconds, 3600)
                m, _ = divmod(rem, 60)
                time_str = f"{int(h):02}:{int(m):02}"
                sess_date = s["start_time"].strftime('%d.%m')
                comment = s.get("comment") or "-"
                lines.append(f"{sess_date} | {time_str} / {comment}")

            lines.append("")

    # Сводка по проектам за период
    if totals_by_project:
        lines.append("Итоги за период:")
        lines.append("")
        for project_name in sorted(totals_by_project.keys()):
            totals = totals_by_project[project_name]
            total_seconds = int(totals["total_seconds"])
            t_hours, t_rem = divmod(total_seconds, 3600)
            t_minutes, _ = divmod(t_rem, 60)
            total_time_str = f"{int(t_hours):02}:{int(t_minutes):02}"

            lines.append(project_name)
            lines.append(
                f"Всего сессий за период: {totals['sessions_count']}"
            )
            lines.append(
                f"Всего времени за период: {total_time_str}"
            )
            lines.append("")

    return "\n".join(lines).rstrip()


def format_flat_period_stats(stats, period_name, start_date=None, end_date=None, days=None):
    """Плоский вывод: заголовок с датами периода, далее строки
    "ДД.ММ | ЧЧ:ММ | проект | комментарий", отсортировано по дате сессии."""
    # Собираем все сессии в один список
    all_sessions = []
    for project_name, sessions in stats.items():
        for s in sessions:
            start_dt = s.get("start_time")
            if not start_dt:
                continue
            seconds = int(s.get("seconds") or 0)
            comment = s.get("comment") or "-"
            all_sessions.append((start_dt, seconds, project_name, comment))

    if all_sessions:
        all_sessions.sort(key=lambda x: x[0])  # по времени возрастанию
        calc_start = all_sessions[0][0].date()
        calc_end = all_sessions[-1][0].date()
    else:
        calc_start = (datetime.now() - timedelta(days=(days or 1) - 1)).date()
        calc_end = datetime.now().date()

    header_start = (start_date or calc_start)
    header_end = (end_date or calc_end)

    lines = [
        f"📊 Статистика {period_name} ({header_start.strftime('%d.%m.%Y')} — {header_end.strftime('%d.%m.%Y')})",
        "",
    ]

    if not all_sessions:
        lines.append("Данных пока нет.")
        return "\n".join(lines)

    # Суммарное время за период по всем проектам
    total_seconds_all = sum(s[1] for s in all_sessions)
    t_hours, t_rem = divmod(int(total_seconds_all), 3600)
    t_minutes, _ = divmod(t_rem, 60)
    total_time_str = f"{int(t_hours):02}:{int(t_minutes):02}"
    lines.append(f"Всего времени за период: {total_time_str}")
    lines.append("")

    for start_dt, seconds, project_name, comment in all_sessions:
        hours, remainder = divmod(int(seconds), 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = f"{int(hours):02}:{int(minutes):02}"
        sess_date = start_dt.strftime('%d.%m')
        lines.append(f"{sess_date} | {time_str} | {project_name} | {comment}")

    return "\n".join(lines)

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


async def get_project_sessions(telegram_id, project_name):
    """Возвращает все сессии по проекту (все время)"""
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        """
        SELECT p.start_time,
               EXTRACT(EPOCH FROM p.duration) AS seconds,
               p.comment
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1
          AND p.project_name = $2
          AND p.duration IS NOT NULL
        ORDER BY p.start_time DESC
        """,
        telegram_id,
        project_name,
    )
    await conn.close()
    return rows

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

    await message.answer(
        f"✅ Запись сохранена!\n\n"
        f"Проект: {project_name}\n"
        f"Дата: {manual_date.strftime('%d.%m.%Y')}\n"
        f"Время: {time_str}\n"
        f"Что делала: {manual_comment}"
    )


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

# Фоновые напоминалки по пользователям (user_id -> asyncio.Task)
user_reminder_tasks = {}


async def reminder_loop(user_id):
    """Каждые 15 минут напоминает пользователю про активный таймер."""
    try:
        while True:
            await asyncio.sleep(15)

            # Если таймер уже не активен — выходим
            if user_timers.get(user_id, {}).get('state') != 'running':
                break

            buttons = [[InlineKeyboardButton(text="⏹ Стоп", callback_data="stop_timer")]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="⏰ Ты ещё работаешь? Если закончил(а), нажми Стоп.",
                    reply_markup=keyboard,
                )
            except Exception:
                # Безопасно игнорируем единичные ошибки отправки
                pass
    except asyncio.CancelledError:
        # Корректное завершение при отмене задачи
        pass


def start_user_reminder(user_id):
    """Запускает напоминалку для пользователя, если таймер активен и задача ещё не запущена."""
    # Напоминалка только при активном таймере, не для ручных режимов
    if user_timers.get(user_id, {}).get('state') != 'running':
        return
    task = user_reminder_tasks.get(user_id)
    if task and not task.done():
        return
    user_reminder_tasks[user_id] = asyncio.create_task(reminder_loop(user_id))


async def stop_user_reminder(user_id):
    """Останавливает активную напоминалку пользователя (если есть)."""
    task = user_reminder_tasks.get(user_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    user_reminder_tasks.pop(user_id, None)

# Функция для обработки команды /manual
@dp.message(Command('manual'))
async def cmd_manual(message: types.Message):
    user_id = message.from_user.id

    # Получаем проекты пользователя из БД
    projects = await get_user_projects(user_id)

    if not projects:
        # Если проектов нет, предлагаем создать новый
        user_timers[user_id] = {'state': 'manual_awaiting_new_project'}
        await message.answer("У тебя пока нет проектов. Введи название нового проекта:")
    else:
        # Показываем список проектов + кнопка добавить новый
        buttons = []
        for project_name in projects:
            buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"manual_project:{project_name}")])
        buttons.append([InlineKeyboardButton(text="Добавить новый", callback_data="manual_new_project")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выбери проект для ручного добавления времени:", reply_markup=keyboard)

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

    # Проверяем, новый ли это пользователь
    user_exists = await check_user_exists(user_id)

    # Если пользователь новый, показываем приветствие
    if not user_exists:
        await message.answer(
            "Привет! 👋\n"
            "Приложение предложит ввести название проекта 📝, а потом сразу запустит таймер — он будет фиксировать время, которое ты тратишь на проект.\n\n"
            "В меню ты сможешь:\n"
            "	•	посмотреть статистику по своим проектам 📊\n"
            "	•	вручную добавить время, если работал без таймера ⌛"
        )

        # Показываем typing эффект на 5 секунд
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        await asyncio.sleep(5)

    # Получаем проекты пользователя из БД
    projects = await get_user_projects(user_id)

    # Обновляем локальный кэш проектов
    user_projects[user_id] = projects

    # Если у пользователя нет проектов в БД
    if not projects:
        user_timers[user_id] = {'state': 'awaiting_new_project'}
        await message.answer(
            "У тебя пока нет проектов. Введи название нового проекта:",
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
        # запуск напоминалки
        start_user_reminder(user_id)
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
        # запуск напоминалки
        start_user_reminder(user_id)

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

            await callback.message.edit_text("Таймер остановлен. Расскажи, что делала:")
            # стоп напоминалки
            await stop_user_reminder(user_id)

    elif callback.data.startswith("stats:"):
        # Обработка статистики
        stats_type = callback.data.replace("stats:", "")

        if stats_type == "week":
            stats = await get_stats_for_current_week(user_id)
            # вычислим календарные границы (пн-вс) для заголовка
            now_dt = datetime.now()
            week_start = (now_dt - timedelta(days=now_dt.weekday())).date()
            week_end = week_start + timedelta(days=6)
            message = format_flat_period_stats(
                stats, "за неделю", start_date=week_start, end_date=week_end
            )
            await callback.message.edit_text(message)

        elif stats_type == "month":
            stats = await get_stats_for_current_month(user_id)
            now_dt = datetime.now()
            month_start = datetime(now_dt.year, now_dt.month, 1).date()
            # до текущей даты включительно
            month_end = now_dt.date()
            message = format_flat_period_stats(
                stats, "за месяц", start_date=month_start, end_date=month_end
            )
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
        sessions_rows = await get_project_sessions(user_id, project_name)

        if not total_stats or not total_stats['total_seconds']:
            await callback.message.edit_text(f"📊 Проект: {project_name}\n\nДанных пока нет.")
        else:
            total_seconds = total_stats['total_seconds']
            total_sessions = total_stats['total_sessions']

            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            total_time_str = f"{int(hours):02}:{int(minutes):02}"

            message = f"За все время: {project_name}\n"
            message += f"Всего времени за период: {total_time_str}\n"

            if sessions_rows:
                message += "\n🧾 Сессии:\n"
                for r in sessions_rows:
                    sess_dt = r['start_time']
                    seconds = int(r['seconds'] or 0)
                    h, rem = divmod(seconds, 3600)
                    m, _ = divmod(rem, 60)
                    time_str = f"{int(h):02}:{int(m):02}"
                    sess_date = sess_dt.strftime('%d.%m')
                    comment = r['comment'] or "-"
                    message += f"{sess_date} | {time_str} | {comment}\n"

            await callback.message.edit_text(message)

    elif callback.data.startswith("manual_project:"):
        # Ручное добавление для существующего проекта
        project_name = callback.data.replace("manual_project:", "")
        user_timers[user_id] = {
            'state': 'manual_awaiting_date',
            'manual_project': project_name
        }
        await callback.message.edit_text(f"Проект: {project_name}\n\nВведи дату в формате ДД ММ ГГ (например: 15 08 24):")

    elif callback.data == "manual_new_project":
        # Создание нового проекта для ручного добавления
        user_timers[user_id] = {'state': 'manual_awaiting_new_project'}
        await callback.message.edit_text("Введи название нового проекта:")

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
    # Безопасно подгружаем список проектов
    projects = user_projects.get(user_id) or await get_user_projects(user_id)
    user_projects[user_id] = projects
    buttons = []
    for project_name in projects:
        buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"project:{project_name}")])
    buttons.append([InlineKeyboardButton(text="Добавить новый", callback_data="new_project")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Сообщение о сохранении без manual_* полей
    await message.answer(
        f"✅ Запись сохранена!\n\n"
        f"Проект: {project_name}\n"
        f"Дата: {start_time.strftime('%d.%m.%Y')}\n"
        f"Время: {formatted_time}\n"
        f"Что делала: {comment}"
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
        await message.answer(f"Проект: {project_name}\n\nВведи дату в формате ДД ММ ГГ (например: 15 08 24):")


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

    await message.answer(f"Время: {time_text}\n\nНапиши, что делала:")


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
        f"Что делала: {comment}\n\n"
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
