import random

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

BOT_TOKEN = '7769254890:AAHKxCtnL7qg3goFCKQCshZNfBDSmqs1hfg'

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
ATTEMPTS = 5

user = {'in_game': False,
        'secret_number': None,
        'attempts': None,
        'total_games': 0,
        'wins': 0}


async def get_random_number() -> int:
    return random.randint(1, 100)


@dp.message(CommandStart())
async def process_start_command(message: Message):
    await message.answer(
        'Приветствую! \nСыграем? Я загадаю число от 1 до 100, а вы угадаете?\n'
        '/help поможет понять, какие команды я понимаю.\n'
    )


@dp.message(Command(commands='help'))
async def process_help_command(message: Message):
    await message.answer(
        f'Правила игры:\n\nЯ загадываю число от 1 до 100, '
        f'а вам нужно его угадать\nУ вас есть {ATTEMPTS} '
        f'попыток\n\nДоступные команды:\n/cancel - выйти из игры\n'
        f'/stat - посмотреть статистику\n\nДавай сыграем?'
    )

@dp.message(Command(commands='stat'))
async def process_stat_command(message: Message):
    await message.answer(
        f' Всего сыграно игр: {user["total_games"]}\n'
        f'Игр выиграно: {user["wins"]}'
    )

@dp.message(Command(commands='cancel'))
async def process_cancel_command(message: Message):
    if user['in_game']:
        user['in_game'] = False
        await message.answer(
            'Вы вышли из игры. Если захотите сыграть '
            'снова - напишите об этом'
        )
    else:
        await message.answer(
            'А мы итак с вами не играем. '
            'Может, сыграем разок?'
        )


@dp.message(F.text.lower().in_(['да', 'давай', 'сыграем', 'игра', 'играть', 'хочу играть']))
async def process_positive_answer(message: Message):
    if not user['in_game']:
        user['in_game'] = True
        user['secret_number'] = get_random_number()
        user['attempts'] = ATTEMPTS
        await message.answer(
            f'Ура!\n\nЯ загадал число от 1 до 100, '
            'попробуй угадать!'
        )
    else:
        await message.answer(
             'Пока мы играем в игру я могу '
            'реагировать только на числа от 1 до 100 '
            'и команды /cancel и /stat'
        )
@dp.message(F.text.lower().in_(['нет','не', 'не хочу', 'не буду']))
async def process_negative_answer(message: Message):
    if not user['in_game']:
        await message.amswer(
            'Жаль :(\n\nЕсли захотите поиграть - просто '
            'напишите об этом'
        )
    else:
        await message.answer(
            'Мы же сейчас с вами играем. Присылайте, '
            'пожалуйста, числа от 1 до 100'
        )

@dp.message(lambda x: x.text and x.text.isdigit() and 1 <= int(x.text) <= 100)
async def process_numbers_answer(message: Message):
    if user ['in_game']:
        if int(message.text) == user['secret_number']:
            user['in_game'] = False
            user['total_games'] += 1
            user['wins'] += 1
            await message.answer(
                'Ура!!! Вы угадали число!\n\n'
                'Может, сыграем еще?'
            )
        elif int(message.text) > user['secret_number']:
            user['attempts'] -= 1
            await message.answer('Мое число меньше')
        elif int(message.text) < user['secret_number']:
            user['attempts'] -= 1
            await message.answer('Мое число больше')

        if user['attempts'] == 0:
            user['in_game'] = False
            user['total_games'] += 1
            await message.answer('Кончились попытки. '
                                 'Вы проиграли :(\n\nМое число '
                f'было {user["secret_number"]}\n\nДавайте '
                f'сыграем еще?'
                    )
        else:
            await message.answer('Мы еще не играем. Хотите сыграть?')

@dp.message()
async def process_other_answers(message: Message):
    if user['in_game']:
        await message.answer(
            'Мы же сейчас с вами играем. '
            'Присылайте, пожалуйста, числа от 1 до 100'
        )
    else:
        await message.answer(
            'Я довольно ограниченный бот, давайте '
            'просто сыграем в игру?'
        )

if __name__ == '__main__':
    dp.run_polling(bot)
await bot.delete_webhook(drop_pending_updates=True)
