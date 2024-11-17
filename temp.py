from aiogram import Bot
import asyncio

TOKEN = "7898507076:AAHwUq8bJl-DIqZ6fKgKiK0DPlPDJhV7Pog"

async def get_updates():
    bot = Bot(token=TOKEN)
    updates = await bot.get_updates()
    for update in updates:
        if update.message:
            print(f"Chat ID: {update.message.chat.id}")
    await bot.session.close()

asyncio.run(get_updates())
