import asyncio
from datetime import datetime
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Токен бота
API_TOKEN = '7769254890:AAHKxCtnL7qg3goFCKQCshZNfBDSmqs1hfg'

# ID таблицы Google Spreadsheet
SPREADSHEET_ID = '1D1QCbveZEJHjhERzPIC4_uEzbhV1DZccPo6RqjbdMso'

# Авторизация в Google Sheets API
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

json_keyfile = os.environ.get('GOOGLE_SHEETS_KEY_JSON')
if json_keyfile:
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(json_keyfile), scope)
else:
    raise ValueError("Переменная окружения GOOGLE_SHEETS_KEY_JSON не найдена")


client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1  # Открываем первую страницу таблицы

# Создаем объекты бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Переменные для отслеживания времени и текущего проекта
timers = {}
projects = ["WNNB", "UKIDS"]

# Функция для обработки команды /start
@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    buttons = [[KeyboardButton(text=project) for project in projects], [KeyboardButton(text="Добавить новый проект")]]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    timers[message.from_user.id] = {'state': 'selecting_project'}  # Устанавливаем состояние выбора проекта
    await message.answer("Выберите проект или добавьте новый:", reply_markup=keyboard)

# Обработчик для кнопки "Start Over"
@dp.message(lambda message: message.text == "Start Over")
async def cmd_start_over(message: types.Message):
    await cmd_start(message)  # Вызовем ту же функцию, что и для команды /start

# Функция для выбора проекта
@dp.message(lambda message: message.text in projects and timers.get(message.from_user.id, {}).get('state') == 'selecting_project')
async def project_selection(message: types.Message):
    # Запуск таймера сразу после выбора проекта
    timers[message.from_user.id] = {
        'project': message.text,
        'start_time': datetime.now(),
        'state': 'running'  # Состояние таймера запущено
    }
    buttons = [[KeyboardButton(text="Стоп")]]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer(f"Таймер для проекта '{message.text}' запущен! Нажмите 'Стоп' для остановки.", reply_markup=keyboard)

# Функция для обработки нового проекта
@dp.message(lambda message: message.text not in projects and timers.get(message.from_user.id, {}).get('state') == 'selecting_project' and message.text != "Добавить новый проект")
async def new_project(message: types.Message):
    projects.append(message.text)
    timers[message.from_user.id] = {
        'project': message.text,
        'start_time': datetime.now(),
        'state': 'running'  # Состояние таймера запущено
    }
    buttons = [[KeyboardButton(text="Стоп")]]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer(f"Новый проект '{message.text}' добавлен и таймер запущен! Нажмите 'Стоп' для остановки.", reply_markup=keyboard)

# Функция для обработки команды "Стоп"
@dp.message(lambda message: message.text == "Стоп" and timers.get(message.from_user.id, {}).get('state') == 'running')
async def cmd_stop(message: types.Message):
    if message.from_user.id in timers and timers[message.from_user.id]['start_time']:
        start_time = timers[message.from_user.id]['start_time']
        end_time = datetime.now()
        elapsed_time = end_time - start_time

        # Преобразование времени в формат hh:mm
        hours, remainder = divmod(elapsed_time.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        formatted_time = f"{int(hours):02}:{int(minutes):02}"

        # Просим ввести комментарий
        timers[message.from_user.id]['state'] = 'awaiting_comment'  # Меняем состояние на ожидание комментария
        timers[message.from_user.id]['formatted_time'] = formatted_time
        await message.answer("Таймер остановлен! Введите комментарий:")

# Обработка комментария
@dp.message(lambda message: timers.get(message.from_user.id, {}).get('state') == 'awaiting_comment')
async def handle_comment(message: types.Message):
    user_id = message.from_user.id
    project = timers[user_id]['project']
    formatted_time = timers[user_id]['formatted_time']
    current_date = datetime.now().strftime("%d-%m-%y")
    comment = message.text

    # Записываем данные в Google Spreadsheet
    sheet.append_row([current_date, formatted_time, project, comment])

    # Создаем кнопку для команды /start
    start_button = KeyboardButton(text="Start Over")
    start_keyboard = ReplyKeyboardMarkup(keyboard=[[start_button]], resize_keyboard=True)

    # Сообщаем об успешной записи и меняем клавиатуру на кнопку /start
    await message.answer(
        f"Данные отправлены в Google Spreadsheet!\nПроект: {project}\nВремя: {formatted_time}\nКомментарий: {comment}",
        reply_markup=start_keyboard
    )

    # Убираем данные пользователя
    del timers[user_id]

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
