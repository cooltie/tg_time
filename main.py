import asyncio
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
import asyncpg
from dotenv import load_dotenv
import re
from collections import defaultdict
import csv
import tempfile

# Load data from .env
load_dotenv()

# Get environment variables
API_TOKEN = os.getenv('API_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Predefined project types
DEFAULT_PROJECT_TYPES = [
    "🦹‍♀️ automation",
    "🍿 design", 
    "🫄 presale"
]

logging.basicConfig(level=logging.INFO)


async def check_user_exists(telegram_id):
    """Checks if user exists in database"""
    conn = await asyncpg.connect(DATABASE_URL)

    # Create tables if they don't exist
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
            comment TEXT,
            archived BOOLEAN DEFAULT FALSE
        );
    """)

    # Add archived column if it doesn't exist (migration)
    await conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='projects' AND column_name='archived'
            ) THEN
                ALTER TABLE projects ADD COLUMN archived BOOLEAN DEFAULT FALSE;
            END IF;
        END $$;
    """)

    # Check if user exists
    user_exists = await conn.fetchval("""
        SELECT EXISTS(SELECT 1 FROM users WHERE telegram_id = $1)
    """, telegram_id)

    # If user doesn't exist, create them
    if not user_exists:
        await conn.execute("""
            INSERT INTO users (telegram_id) VALUES ($1)
        """, telegram_id)

    await conn.close()
    return user_exists


async def get_user_project_types(telegram_id):
    """Gets all project types for user"""
    conn = await asyncpg.connect(DATABASE_URL)
    
    # Get unique types from existing user projects
    types = await conn.fetch("""
        SELECT DISTINCT p.type
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1 AND p.type IS NOT NULL
        ORDER BY p.type
    """, telegram_id)
    
    await conn.close()
    
    # Combine with predefined types
    user_types = [t['type'] for t in types]
    all_types = list(set(DEFAULT_PROJECT_TYPES + user_types))
    return all_types


async def add_project_type(telegram_id, project_type):
    """Добавляет новый тип проекта для пользователя"""
    conn = await asyncpg.connect(DATABASE_URL)
    
    # Получаем ID пользователя
    user_id = await conn.fetchval("""
        SELECT id FROM users WHERE telegram_id = $1
    """, telegram_id)
    
    if user_id:
        # Добавляем запись с новым типом
        await conn.execute("""
            INSERT INTO projects (user_id, project_name, type)
            VALUES ($1, '', $2)
            ON CONFLICT DO NOTHING
        """, user_id, project_type)
    
    await conn.close()


async def update_project_type(telegram_id, project_name, project_type):
    """Обновляет тип для конкретного проекта"""
    conn = await asyncpg.connect(DATABASE_URL)
    
    await conn.execute("""
        UPDATE projects 
        SET type = $3
        FROM users u
        WHERE projects.user_id = u.id 
        AND u.telegram_id = $1 
        AND projects.project_name = $2
    """, telegram_id, project_name, project_type)
    
    await conn.close()


async def get_user_projects(telegram_id):
    """Получает список уникальных проектов пользователя из БД (только активные)"""
    conn = await asyncpg.connect(DATABASE_URL)

    # Получаем уникальные активные проекты пользователя
    projects = await conn.fetch("""
        SELECT DISTINCT p.project_name
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1 AND (p.archived = FALSE OR p.archived IS NULL)
        ORDER BY p.project_name
    """, telegram_id)

    await conn.close()
    return [project['project_name'] for project in projects]


async def get_all_user_projects(telegram_id):
    """Получает список всех проектов пользователя из БД (включая архивные)"""
    conn = await asyncpg.connect(DATABASE_URL)

    # Получаем все уникальные проекты пользователя
    projects = await conn.fetch("""
        SELECT DISTINCT p.project_name, p.archived
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1
        ORDER BY p.project_name
    """, telegram_id)

    await conn.close()
    return [project['project_name'] for project in projects]


async def get_archived_projects(telegram_id):
    """Получает список архивных проектов пользователя"""
    conn = await asyncpg.connect(DATABASE_URL)

    projects = await conn.fetch("""
        SELECT DISTINCT p.project_name
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.telegram_id = $1 AND p.archived = TRUE
        ORDER BY p.project_name
    """, telegram_id)

    await conn.close()
    return [project['project_name'] for project in projects]


async def archive_project(telegram_id, project_name):
    """Архивирует проект"""
    conn = await asyncpg.connect(DATABASE_URL)

    await conn.execute("""
        UPDATE projects p
        SET archived = TRUE
        FROM users u
        WHERE p.user_id = u.id
        AND u.telegram_id = $1
        AND p.project_name = $2
    """, telegram_id, project_name)

    await conn.close()


async def unarchive_project(telegram_id, project_name):
    """Восстанавливает проект из архива"""
    conn = await asyncpg.connect(DATABASE_URL)

    await conn.execute("""
        UPDATE projects p
        SET archived = FALSE
        FROM users u
        WHERE p.user_id = u.id
        AND u.telegram_id = $1
        AND p.project_name = $2
    """, telegram_id, project_name)

    await conn.close()


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


async def get_stats_for_custom_period(telegram_id, start_date, end_date):
    """Сессии за произвольный период (с start_date по end_date включительно)"""
    conn = await asyncpg.connect(DATABASE_URL)

    # Convert dates to datetime at start and end of day
    start_datetime = datetime.combine(start_date, datetime.min.time())
    end_datetime = datetime.combine(end_date, datetime.max.time())

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
          AND p.start_time >= $2
          AND p.start_time <= $3
        ORDER BY p.start_time ASC
        """,
        telegram_id,
        start_datetime,
        end_datetime,
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
    """Format: header, then by dates: project, totals for period,
    then lines "date/time/what you did"."""
    if not stats:
        return f"📊 Statistics {period_name}\n\nNo data yet."

    # Totals for period by each project
    totals_by_project = {}
    for project_name, sessions in stats.items():
        total_seconds = sum(int(s.get("seconds") or 0) for s in sessions)
        totals_by_project[project_name] = {
            "sessions_count": len(sessions),
            "total_seconds": int(total_seconds),
        }

    # Determine period boundaries
    all_dates = []
    for sessions in stats.values():
        for s in sessions:
            if s.get("start_time"):
                all_dates.append(s["start_time"].date())
    
    if all_dates:
        period_start = min(all_dates)
        period_end = max(all_dates)
        period_header = (
            f"📊 Statistics {period_name} "
            f"({period_start.strftime('%d.%m.%Y')} — "
            f"{period_end.strftime('%d.%m.%Y')})"
        )
    else:
        period_header = f"📊 Statistics {period_name}"

    # Group by date -> project -> sessions
    grouped = defaultdict(lambda: defaultdict(list))
    for project_name, sessions in stats.items():
        for s in sessions:
            start_dt = s.get("start_time")
            if not start_dt:
                continue
            date_key = start_dt.date()
            grouped[date_key][project_name].append(s)

    lines = [period_header, ""]

    # Add general summary for period
    lines.append("Total:")
    total_by_project = {}
    for project_name, sessions in stats.items():
        total_seconds = sum(int(s.get("seconds") or 0) for s in sessions)
        sessions_count = len(sessions)
        total_by_project[project_name] = {
            "total_seconds": total_seconds,
            "sessions_count": sessions_count
        }
    
    for project_name in sorted(total_by_project.keys()):
        totals = total_by_project[project_name]
        total_seconds = totals["total_seconds"]
        sessions_count = totals["sessions_count"]
        
        # Format time
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = f"{int(hours):02}:{int(minutes):02}"
        
        lines.append(f"{project_name} | {sessions_count} — {time_str}")
    
    lines.append("")  # Empty line before detailed statistics

    for date_key in sorted(grouped.keys(), reverse=True):
        lines.append(f"## {date_key.strftime('%d.%m.%Y')}")
        lines.append("")

        projects_for_date = grouped[date_key]
        for project_name in sorted(projects_for_date.keys()):
            # Get project statistics only for this day
            day_sessions = projects_for_date[project_name]
            day_total_seconds = sum(int(s.get("seconds") or 0) for s in day_sessions)
            day_sessions_count = len(day_sessions)
            
            # Format time
            p_hours, p_rem = divmod(day_total_seconds, 3600)
            p_minutes, _ = divmod(p_rem, 60)
            project_time_str = f"{int(p_hours):02}:{int(p_minutes):02}"
            
            # Form project header with daily statistics
            project_header = (
                f"{project_name} (sessions: {day_sessions_count}, "
                f"time spent: {project_time_str})"
            )
            lines.append(project_header)
            
            for s in projects_for_date[project_name]:
                seconds = int(s.get("seconds") or 0)
                h, rem = divmod(seconds, 3600)
                m, _ = divmod(rem, 60)
                time_str = f"{int(h):02}:{int(m):02}"
                sess_date = s["start_time"].strftime('%d.%m')
                comment = s.get("comment") or "-"
                lines.append(f"{sess_date} | {time_str} | {comment}")

            lines.append("")

    return "\n".join(lines).rstrip()


def format_flat_period_stats(stats, period_name, start_date=None, end_date=None, days=None):
    """Flat output: header with period dates, then lines
    "DD.MM | HH:MM | project | comment", sorted by session date."""
    # Collect all sessions in one list
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
        all_sessions.sort(key=lambda x: x[0])  # by time ascending
        calc_start = all_sessions[0][0].date()
        calc_end = all_sessions[-1][0].date()
    else:
        calc_start = (datetime.now() - timedelta(days=(days or 1) - 1)).date()
        calc_end = datetime.now().date()

    header_start = (start_date or calc_start)
    header_end = (end_date or calc_end)

    lines = [
        f"📊 Statistics {period_name} ({header_start.strftime('%d.%m.%Y')} — {header_end.strftime('%d.%m.%Y')})",
        "",
    ]

    if not all_sessions:
        lines.append("No data yet.")
        return "\n".join(lines)

    # Total time for period across all projects
    total_seconds_all = sum(s[1] for s in all_sessions)
    t_hours, t_rem = divmod(int(total_seconds_all), 3600)
    t_minutes, _ = divmod(t_rem, 60)
    total_time_str = f"{int(t_hours):02}:{int(t_minutes):02}"
    lines.append(f"Total time for period: {total_time_str}")
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

def generate_csv_file(stats, period_name):
    """Создает CSV файл со статистикой и возвращает путь к файлу"""
    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8-sig')

    try:
        writer = csv.writer(temp_file)

        # Write header
        writer.writerow(['Date', 'Time (HH:MM)', 'Project', 'Comment'])

        # Collect all sessions
        all_sessions = []
        for project_name, sessions in stats.items():
            for s in sessions:
                start_dt = s.get("start_time")
                if not start_dt:
                    continue
                seconds = int(s.get("seconds") or 0)
                hours, remainder = divmod(seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                time_str = f"{int(hours):02}:{int(minutes):02}"
                comment = s.get("comment") or "-"
                date_str = start_dt.strftime('%d.%m.%Y')

                all_sessions.append((start_dt, date_str, project_name, time_str, comment))

        # Sort by date
        all_sessions.sort(key=lambda x: x[0])

        # Write data
        for _, date_str, project_name, time_str, comment in all_sessions:
            writer.writerow([date_str, time_str, project_name, comment])

        temp_file.close()
        return temp_file.name

    except Exception as e:
        temp_file.close()
        os.unlink(temp_file.name)
        raise e


def format_summary_message(stats, period_name):
    """Краткая сводка по статистике (без детального списка сессий)"""
    if not stats:
        return f"📊 Statistics {period_name}\n\nNo data yet."

    # Determine period boundaries
    all_dates = []
    for sessions in stats.values():
        for s in sessions:
            if s.get("start_time"):
                all_dates.append(s["start_time"].date())

    if all_dates:
        period_start = min(all_dates)
        period_end = max(all_dates)
        period_header = (
            f"📊 Statistics {period_name}\n"
            f"({period_start.strftime('%d.%m.%Y')} — "
            f"{period_end.strftime('%d.%m.%Y')})"
        )
    else:
        period_header = f"📊 Statistics {period_name}"

    lines = [period_header, ""]

    # Calculate totals by project
    total_by_project = {}
    grand_total_seconds = 0
    for project_name, sessions in stats.items():
        total_seconds = sum(int(s.get("seconds") or 0) for s in sessions)
        sessions_count = len(sessions)
        total_by_project[project_name] = {
            "total_seconds": total_seconds,
            "sessions_count": sessions_count
        }
        grand_total_seconds += total_seconds

    # Grand total
    hours, remainder = divmod(grand_total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    grand_total_str = f"{int(hours):02}:{int(minutes):02}"
    lines.append(f"⏱ Total time: {grand_total_str}")
    lines.append("")

    # By project
    lines.append("📋 By projects:")
    for project_name in sorted(total_by_project.keys()):
        totals = total_by_project[project_name]
        total_seconds = totals["total_seconds"]
        sessions_count = totals["sessions_count"]

        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = f"{int(hours):02}:{int(minutes):02}"

        lines.append(f"  • {project_name}: {time_str} ({sessions_count} sessions)")

    lines.append("")

    # Daily summary
    lines.append("📅 By days:")

    # Group sessions by date
    daily_stats = {}
    for project_name, sessions in stats.items():
        for s in sessions:
            start_dt = s.get("start_time")
            if not start_dt:
                continue
            date_key = start_dt.date()
            if date_key not in daily_stats:
                daily_stats[date_key] = {"sessions": 0, "seconds": 0}
            daily_stats[date_key]["sessions"] += 1
            daily_stats[date_key]["seconds"] += int(s.get("seconds") or 0)

    # Display daily stats in reverse chronological order
    for date_key in sorted(daily_stats.keys(), reverse=True):
        day_data = daily_stats[date_key]
        hours, remainder = divmod(day_data["seconds"], 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = f"{int(hours):02}:{int(minutes):02}"
        lines.append(f"  • {date_key.strftime('%d.%m.%Y')} (sessions: {day_data['sessions']}, time spent: {time_str})")

    lines.append("")
    lines.append("📎 Detailed data exported to CSV file")

    return "\n".join(lines)


def split_message(text, max_length=4000):
    """Разбивает длинное сообщение на части по max_length символов"""
    if len(text) <= max_length:
        return [text]

    parts = []
    current_part = ""

    for line in text.split('\n'):
        # Если добавление строки превысит лимит, сохраняем текущую часть
        if len(current_part) + len(line) + 1 > max_length:
            if current_part:
                parts.append(current_part.rstrip())
                current_part = ""

        # Если одна строка длиннее лимита, режем её
        if len(line) > max_length:
            if current_part:
                parts.append(current_part.rstrip())
                current_part = ""
            # Режем длинную строку на куски
            for i in range(0, len(line), max_length):
                parts.append(line[i:i+max_length])
        else:
            current_part += line + '\n'

    if current_part:
        parts.append(current_part.rstrip())

    return parts


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
        await message.edit_text("❌ Error: not all data filled.")
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
        f"✅ Entry saved!\n\n"
                           f"Project: {project_name}\n"
                           f"Date: {manual_date.strftime('%d.%m.%Y')}\n"
                           f"Time: {time_str}\n"
        f"What you did: {manual_comment}"
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

# Create bot and dispatcher objects
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Variables for tracking user state
user_timers = {}  # Store timers and state for each user
user_projects = {}  # Store projects for each user

# Background reminders by users (user_id -> asyncio.Task)
user_reminder_tasks = {}


async def reminder_loop(user_id):
    """Каждые 15 минут напоминает пользователю про активный таймер."""
    try:
        while True:
            await asyncio.sleep(15 * 60)

            # If timer is no longer active — exit
            if user_timers.get(user_id, {}).get('state') != 'running':
                break

            buttons = [[InlineKeyboardButton(text="⏹ Stop", callback_data="stop_timer")]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="⏰ Are you still working? If you're done, press Stop.",
                    reply_markup=keyboard,
                )
            except Exception:
                # Safely ignore single send errors
                pass
    except asyncio.CancelledError:
        # Correct completion when task is cancelled
        pass


def start_user_reminder(user_id):
    """Starts reminder for user if timer is active and task is not yet started."""
    # Reminder only for active timer, not for manual modes
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

# Function for handling /manual command
@dp.message(Command('manual'))
async def cmd_manual(message: types.Message):
    user_id = message.from_user.id

    # Get user projects from database
    projects = await get_user_projects(user_id)

    if not projects:
        # If no projects, offer to create new one
        user_timers[user_id] = {'state': 'manual_awaiting_new_project'}
        await message.answer("You don't have any projects yet. Enter a name for a new project:")
    else:
        # Show project list + add new button
        buttons = []
        for project_name in projects:
            buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"manual_project:{project_name}")])
        buttons.append([InlineKeyboardButton(text="Add new", callback_data="manual_new_project")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Choose a project for manual time entry:", reply_markup=keyboard)

# Function for handling /stats command
@dp.message(Command('stats'))
async def cmd_stats(message: types.Message):
    buttons = [
        [InlineKeyboardButton(text="📅 For the week", callback_data="stats:week")],
        [InlineKeyboardButton(text="📆 For the month", callback_data="stats:month")],
        [InlineKeyboardButton(text="📊 By project (all time)", callback_data="stats:project")],
        [InlineKeyboardButton(text="📆 Custom period", callback_data="stats:custom")]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Choose a period for statistics:", reply_markup=keyboard)


# Function for handling /archive command
@dp.message(Command('archive'))
async def cmd_archive(message: types.Message):
    user_id = message.from_user.id

    # Get active projects
    projects = await get_user_projects(user_id)

    if not projects:
        await message.answer("You don't have any active projects to archive.")
        return

    buttons = []
    for project_name in projects:
        buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"archive_project:{project_name}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Choose a project to archive:", reply_markup=keyboard)


# Function for handling /unarchive command
@dp.message(Command('unarchive'))
async def cmd_unarchive(message: types.Message):
    user_id = message.from_user.id

    # Get archived projects
    projects = await get_archived_projects(user_id)

    if not projects:
        await message.answer("You don't have any archived projects.")
        return

    buttons = []
    for project_name in projects:
        buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"unarchive_project:{project_name}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Choose a project to restore:", reply_markup=keyboard)


# Function for handling /start command
@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id

    # Check if this is a new user
    user_exists = await check_user_exists(user_id)

    # If user is new, show welcome message
    if not user_exists:
        await message.answer(
            "Hello! 👋\n"
            "The app will ask you to enter a project name 📝, then immediately start a timer that will track the time you spend on the project.\n\n"
            "In the menu you can:\n"
            "	•	view statistics for your projects 📊\n"
            "	•	manually add time if you worked without a timer ⌛"
        )

        # Show typing effect for 5 seconds
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        await asyncio.sleep(5)

    # Get user projects from database
    projects = await get_user_projects(user_id)

    # Update local project cache
    user_projects[user_id] = projects

    # If user has no projects in database
    if not projects:
        user_timers[user_id] = {'state': 'awaiting_new_project'}
        await message.answer(
            "You don't have any projects yet. Enter a name for a new project:",
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        buttons = []
        for project_name in projects:
            buttons.append([InlineKeyboardButton(text=project_name, callback_data=f"project:{project_name}")])
        buttons.append([InlineKeyboardButton(text="Add new", callback_data="new_project")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        user_timers[user_id] = {'state': 'selecting_project'}
        await message.answer(
            "Choose a project or create a new one:",
            reply_markup=keyboard
        )

# Function for handling new project name input
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
        # start reminder
        start_user_reminder(user_id)
        buttons = [[InlineKeyboardButton(text="⏹ Stop", callback_data="stop_timer")]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(f"Project '{project_name}' added, timer started! Press 'Stop' to stop.", reply_markup=keyboard)

# Inline button handler
@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if callback.data.startswith("project:"):
        # Select existing project
        project_name = callback.data.replace("project:", "")
        user_timers[user_id] = {
            'project': project_name,
            'start_time': datetime.now(),
            'state': 'running'
        }
        buttons = [[InlineKeyboardButton(text="⏹ Stop", callback_data="stop_timer")]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Timer for '{project_name}' started! Press 'Stop' to stop.", reply_markup=keyboard)
        # start reminder
        start_user_reminder(user_id)

    elif callback.data == "new_project":
        # Create new project
        user_timers[user_id] = {'state': 'awaiting_new_project'}
        await callback.message.edit_text("Enter a name for the new project:")

    elif callback.data == "stop_timer":
        # Stop timer
        if user_id in user_timers and user_timers[user_id].get('start_time'):
            start_time = user_timers[user_id]['start_time']
            end_time = datetime.now()
            elapsed_time = end_time - start_time

            # Save to user_timers and wait for comment
            user_timers[user_id]['end_time'] = end_time
            user_timers[user_id]['duration'] = elapsed_time
            user_timers[user_id]['state'] = 'awaiting_comment'

            await callback.message.edit_text("Timer stopped. Tell me what you were doing:")
            # stop reminder
            await stop_user_reminder(user_id)

    elif callback.data.startswith("stats:"):
        # Handle statistics
        stats_type = callback.data.replace("stats:", "")

        if stats_type == "week":
            stats = await get_stats_for_current_week(user_id)
            message = format_stats_message(
                stats, "for the week"
            )
            # Split message if too long
            message_parts = split_message(message)
            await callback.message.edit_text(message_parts[0])
            # Send remaining parts as new messages
            for part in message_parts[1:]:
                await callback.message.answer(part)

        elif stats_type == "month":
            stats = await get_stats_for_current_month(user_id)
            message = format_stats_message(
                stats, "for the month"
            )
            # Split message if too long
            message_parts = split_message(message)
            await callback.message.edit_text(message_parts[0])
            # Send remaining parts as new messages
            for part in message_parts[1:]:
                await callback.message.answer(part)

        elif stats_type == "custom":
            # Start custom period selection
            user_timers[user_id] = {'state': 'stats_awaiting_start_date'}
            await callback.message.edit_text("Enter start date in format DD MM YY (e.g.: 15 08 24):")

        elif stats_type == "project":
            # Show project list for selection (including archived projects)
            projects = await get_all_user_projects(user_id)
            if not projects:
                await callback.message.edit_text("You don't have any projects yet.")
            else:
                buttons = []
                for project_name in projects:
                    buttons.append([InlineKeyboardButton(
                        text=project_name,
                        callback_data=f"project_stats:{project_name}"
                    )])
                keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                await callback.message.edit_text(
                    "Choose a project to view statistics:",
                    reply_markup=keyboard
                )

    elif callback.data.startswith("project_stats:"):
        # Statistics for specific project
        project_name = callback.data.replace("project_stats:", "")
        daily_stats, total_stats = await get_project_stats(user_id, project_name)
        sessions_rows = await get_project_sessions(user_id, project_name)

        if not total_stats or not total_stats['total_seconds']:
            await callback.message.edit_text(f"📊 Project: {project_name}\n\nNo data yet.")
        else:
            total_seconds = total_stats['total_seconds']
            total_sessions = total_stats['total_sessions']

            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            total_time_str = f"{int(hours):02}:{int(minutes):02}"

            message = f"All time: {project_name}\n"
            message += f"Total time for period: {total_time_str}\n"

            if sessions_rows:
                message += "\n🧾 Sessions:\n"
                for r in sessions_rows:
                    sess_dt = r['start_time']
                    seconds = int(r['seconds'] or 0)
                    h, rem = divmod(seconds, 3600)
                    m, _ = divmod(rem, 60)
                    time_str = f"{int(h):02}:{int(m):02}"
                    sess_date = sess_dt.strftime('%d.%m')
                    comment = r['comment'] or "-"
                    message += f"{sess_date} | {time_str} | {comment}\n"

            # Split message if too long
            message_parts = split_message(message)
            await callback.message.edit_text(message_parts[0])
            # Send remaining parts as new messages
            for part in message_parts[1:]:
                await callback.message.answer(part)

    elif callback.data.startswith("manual_project:"):
        # Manual entry for existing project
        project_name = callback.data.replace("manual_project:", "")
        user_timers[user_id] = {
            'state': 'manual_awaiting_date',
            'manual_project': project_name
        }
        await callback.message.edit_text(f"Project: {project_name}\n\nEnter date in format DD MM YY (e.g.: 15 08 24):")

    elif callback.data == "manual_new_project":
        # Create new project for manual entry
        user_timers[user_id] = {'state': 'manual_awaiting_new_project'}
        await callback.message.edit_text("Enter a name for the new project:")

    elif callback.data == "manual_save":
        # Save manual entry
        await save_manual_entry(user_id, callback.message)

    elif callback.data.startswith("archive_project:"):
        # Archive a project
        project_name = callback.data.replace("archive_project:", "")
        await archive_project(user_id, project_name)
        await callback.message.edit_text(f"✅ Project '{project_name}' has been archived.\n\nIt won't appear in the project list anymore, but will remain in statistics.\n\nUse /unarchive to restore it.")

    elif callback.data.startswith("unarchive_project:"):
        # Unarchive a project
        project_name = callback.data.replace("unarchive_project:", "")
        await unarchive_project(user_id, project_name)
        await callback.message.edit_text(f"✅ Project '{project_name}' has been restored.\n\nIt will now appear in the project list again.")

    await callback.answer()



# Comment handling
@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'awaiting_comment')
async def handle_comment(message: types.Message):
    user_id = message.from_user.id
    telegram_id = message.from_user.id  # telegram_id is the same as user_id
    project_name = user_timers[user_id]['project']
    start_time = user_timers[user_id]['start_time']
    end_time = user_timers[user_id]['end_time']
    duration = user_timers[user_id]['duration']
    elapsed_time = end_time - start_time
    comment = message.text

    # Convert time to hh:mm format
    hours, remainder = divmod(elapsed_time.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)
    formatted_time = f"{int(hours):02}:{int(minutes):02}"


    # Save to database
    await save_time_entry(user_id, telegram_id, project_name, start_time, end_time, duration, comment)

    # Offer to select project
    user_timers[user_id] = {'state': 'selecting_project'}
    # Safely load project list
    projects = user_projects.get(user_id) or await get_user_projects(user_id)
    user_projects[user_id] = projects
    buttons = []
    for next_project in projects:
        buttons.append([InlineKeyboardButton(text=next_project, callback_data=f"project:{next_project}")])
    buttons.append([InlineKeyboardButton(text="Add new", callback_data="new_project")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Save confirmation message without manual_* fields
    await message.answer(
        f"✅ Entry saved!\n\n"
        f"Project: {project_name}\n"
        f"Date: {start_time.strftime('%d.%m.%Y')}\n"
        f"Time: {formatted_time}\n"
        f"What you did: {comment}"
    )
    await message.answer(
        "Choose next project or add a new one:",
        reply_markup=keyboard
    )


# Handlers for manual time entry
@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'manual_awaiting_new_project')
async def handle_manual_new_project(message: types.Message):
    user_id = message.from_user.id
    project_name = message.text.strip()

    if project_name:
        # Add project to local cache
        if user_id not in user_projects:
            user_projects[user_id] = []
        user_projects[user_id].append(project_name)

        # Move to date input
        user_timers[user_id] = {
            'state': 'manual_awaiting_date',
            'manual_project': project_name
        }
        await message.answer(f"Project: {project_name}\n\nEnter date in format DD MM YY (e.g.: 15 08 24):")


@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'manual_awaiting_date')
async def handle_manual_date(message: types.Message):
    user_id = message.from_user.id
    date_text = message.text.strip()

    parsed_date = validate_date_format(date_text)
    if not parsed_date:
        await message.answer("❌ Invalid date format. Use format DD MM YY (e.g.: 15 08 24):")
        return

    # Save date and move to time input
    user_timers[user_id]['manual_date'] = parsed_date
    user_timers[user_id]['state'] = 'manual_awaiting_time'

    await message.answer(f"Date: {parsed_date.strftime('%d.%m.%Y')}\n\nEnter hours spent in format HH:MM (e.g.: 02:30):")


@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'stats_awaiting_start_date')
async def handle_stats_start_date(message: types.Message):
    user_id = message.from_user.id
    date_text = message.text.strip()

    parsed_date = validate_date_format(date_text)
    if not parsed_date:
        await message.answer("❌ Invalid date format. Use format DD MM YY (e.g.: 15 08 24):")
        return

    # Save start date and move to end date input
    user_timers[user_id]['stats_start_date'] = parsed_date
    user_timers[user_id]['state'] = 'stats_awaiting_end_date'

    await message.answer(f"Start date: {parsed_date.strftime('%d.%m.%Y')}\n\nEnter end date in format DD MM YY (e.g.: 20 08 24):")


@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'stats_awaiting_end_date')
async def handle_stats_end_date(message: types.Message):
    user_id = message.from_user.id
    date_text = message.text.strip()

    parsed_date = validate_date_format(date_text)
    if not parsed_date:
        await message.answer("❌ Invalid date format. Use format DD MM YY (e.g.: 20 08 24):")
        return

    start_date = user_timers[user_id]['stats_start_date']

    # Validate that end date is after start date
    if parsed_date < start_date:
        await message.answer("❌ End date must be after start date. Enter end date in format DD MM YY (e.g.: 20 08 24):")
        return

    # Fetch stats for the custom period
    stats = await get_stats_for_custom_period(user_id, start_date, parsed_date)

    # Clear the state
    user_timers[user_id] = {'state': 'idle'}

    if not stats:
        await message.answer("📊 Statistics for custom period\n\nNo data yet.")
        return

    # Generate summary message
    summary = format_summary_message(stats, "for custom period")
    await message.answer(summary)

    # Generate and send CSV file
    csv_file_path = generate_csv_file(stats, "custom_period")
    try:
        file = FSInputFile(csv_file_path, filename=f"stats_{start_date.strftime('%d%m%y')}-{parsed_date.strftime('%d%m%y')}.csv")
        await message.answer_document(file)
    finally:
        # Clean up temporary file
        if os.path.exists(csv_file_path):
            os.unlink(csv_file_path)


@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'manual_awaiting_time')
async def handle_manual_time(message: types.Message):
    user_id = message.from_user.id
    time_text = message.text.strip()

    duration_seconds = validate_time_format(time_text)
    if duration_seconds is None:
        await message.answer("❌ Invalid time format. Use format HH:MM (e.g.: 02:30):")
        return

    # Save time and move to comment input
    user_timers[user_id]['manual_duration_seconds'] = duration_seconds
    user_timers[user_id]['state'] = 'manual_awaiting_comment'

    await message.answer(f"Time: {time_text}\n\nWrite what you did:")


@dp.message(lambda message: user_timers.get(message.from_user.id, {}).get('state') == 'manual_awaiting_comment')
async def handle_manual_comment(message: types.Message):
    user_id = message.from_user.id
    comment = message.text.strip()

    # Save comment
    user_timers[user_id]['manual_comment'] = comment
    user_timers[user_id]['state'] = 'manual_ready_to_save'

    # Show summary and save button
    timer_data = user_timers[user_id]
    project_name = timer_data['manual_project']
    manual_date = timer_data['manual_date']
    duration_seconds = timer_data['manual_duration_seconds']

    hours, remainder = divmod(duration_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    time_str = f"{int(hours):02}:{int(minutes):02}"

    buttons = [[InlineKeyboardButton(text="💾 Save", callback_data="manual_save")]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        f"📋 Check the data:\n\n"
        f"Project: {project_name}\n"
        f"Date: {manual_date.strftime('%d.%m.%Y')}\n"
        f"Time: {time_str}\n"
        f"What you did: {comment}\n\n"
        f"Press 'Save' to confirm:",
        reply_markup=keyboard
    )


# Bot startup
async def main():
    db = await asyncpg.create_pool(DATABASE_URL)

    # Get database name
    async with db.acquire() as connection:
        db_name = await connection.fetchval("SELECT current_database()")
        print(f"Connection established to database: {db_name}")

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
