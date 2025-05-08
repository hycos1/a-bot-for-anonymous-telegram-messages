import logging
import asyncio
from typing import Dict, Optional
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
BOT_TOKEN = "YOUR_BOT_TOKEN"  # Замените на свой токен
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Словарь для хранения идентификаторов каналов пользователей
# user_id -> channel_id
user_channels: Dict[int, str] = {}

# Определение состояний для FSM
class ChannelStates(StatesGroup):
    waiting_for_channel = State()

class AnonymousMessageStates(StatesGroup):
    waiting_for_message = State()

# Роутеры для структурирования логики бота
main_router = Router()
anon_router = Router()

# Обработчик команды /start
@main_router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    anon_link = f"https://t.me/{(await bot.get_me()).username}?start=anon_{user_id}"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Настроить канал", callback_data="set_channel")
            ]
        ]
    )
    
    await message.answer(
        f"👋 Привет! Я бот для анонимных сообщений.\n\n"
        f"🔗 Вот твоя персональная ссылка для приема анонимных сообщений:\n"
        f"{anon_link}\n\n"
        f"📣 В данный момент сообщения будут приходить в личку. "
        f"Используй кнопку ниже, чтобы настроить отправку в канал.",
        reply_markup=keyboard
    )

# Обработчик кнопки настройки канала
@main_router.callback_query(F.data == "set_channel")
async def set_channel_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "Пожалуйста, перешли мне любое сообщение из канала, "
        "в который ты хочешь получать анонимные сообщения.\n\n"
        "Убедись, что я добавлен в этот канал как администратор с правом публикации сообщений.\n\n"
        "Чтобы отменить настройку, отправь /cancel."
    )
    await state.set_state(ChannelStates.waiting_for_channel)

# Обработчик для отмены текущего действия
@main_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        await message.answer("Действие отменено.")
    else:
        await message.answer("Нет активных действий для отмены.")

# Обработчик пересланного сообщения из канала
@main_router.message(ChannelStates.waiting_for_channel)
async def process_channel_selection(message: Message, state: FSMContext):
    # Проверяем, является ли сообщение пересланным из канала
    if message.forward_from_chat and message.forward_from_chat.type == "channel":
        channel_id = message.forward_from_chat.id
        user_channels[message.from_user.id] = channel_id
        
        channel_title = message.forward_from_chat.title
        await message.answer(
            f"✅ Готово! Теперь анонимные сообщения будут отправляться в канал '{channel_title}'.\n\n"
            f"Для возврата к получению сообщений в личку используй команду /reset_channel"
        )
        await state.clear()
    else:
        await message.answer(
            "❌ Это не похоже на сообщение из канала. Пожалуйста, перешли сообщение из нужного канала "
            "или отправь /cancel для отмены."
        )

# Обработчик сброса настроек канала
@main_router.message(Command("reset_channel"))
async def cmd_reset_channel(message: Message):
    user_id = message.from_user.id
    if user_id in user_channels:
        del user_channels[user_id]
        await message.answer("✅ Настройки сброшены. Анонимные сообщения снова будут приходить в личку.")
    else:
        await message.answer("ℹ️ У вас не настроена пересылка в канал.")

# Обработчик начала анонимного сообщения
@anon_router.message(CommandStart(deep_link=True))
async def start_with_deep_link(message: Message, state: FSMContext):
    deep_link_args = message.text.split()[1]
    if deep_link_args.startswith("anon_"):
        recipient_id = deep_link_args[5:]
        try:
            recipient_id = int(recipient_id)
            # Сохраняем ID получателя в состоянии
            await state.update_data(recipient_id=recipient_id)
            await state.set_state(AnonymousMessageStates.waiting_for_message)
            
            await message.answer(
                "✍️ Напиши свое анонимное сообщение или отправь фото (с подписью или без). "
                "Оно будет отправлено получателю, но он не узнает, кто его отправил.\n\n"
                "Для отмены отправь /cancel."
            )
        except ValueError:
            await message.answer("❌ Некорректная ссылка для анонимного сообщения.")
    else:
        # Перенаправляем на обычный обработчик /start
        await cmd_start(message)

# Обработчик получения анонимного сообщения
@anon_router.message(AnonymousMessageStates.waiting_for_message, F.text | F.photo)
async def process_anonymous_message(message: Message, state: FSMContext):
    data = await state.get_data()
    recipient_id = data.get("recipient_id")
    
    # Проверяем тип сообщения (текст или фото)
    if not message.text and not message.photo:
        await message.answer("Пожалуйста, отправь текстовое сообщение или фото с подписью или без.")
        return
    
    try:
        # Определяем куда отправлять: в канал или личку
        target_id = user_channels.get(recipient_id, recipient_id)
        
        if message.photo:
            # Обрабатываем сообщение с фото
            photo_id = message.photo[-1].file_id  # Берем самое качественное фото
            caption = message.caption or ""
            
            # Формируем подпись с префиксом
            full_caption = f"📨 <b>Анонимное сообщение:</b>\n\n{caption}" if caption else "📨 <b>Анонимное сообщение</b>"
            
            # Отправляем фото
            await bot.send_photo(
                chat_id=target_id,
                photo=photo_id,
                caption=full_caption,
                parse_mode="HTML"
            )
        else:
            # Отправляем текстовое сообщение
            await bot.send_message(
                chat_id=target_id,
                text=f"📨 <b>Анонимное сообщение:</b>\n\n{message.text}",
                parse_mode="HTML"
            )
        
        await message.answer("✅ Анонимное сообщение успешно отправлено!")
        await state.clear()
    except Exception as e:
        logging.error(f"Error sending message: {e}")
        await message.answer(
            "❌ Не удалось отправить сообщение. Возможно, получатель заблокировал бота "
            "или произошла ошибка при отправке в канал."
        )
        await state.clear()

# Регистрация роутеров
dp.include_router(anon_router)
dp.include_router(main_router)

# Запуск бота
async def main():
    # Пропускаем накопившиеся апдейты
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())