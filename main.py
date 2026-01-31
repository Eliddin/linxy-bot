from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import asyncio
import sqlite3
import os
from datetime import datetime, timedelta

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен")

ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
if not ADMIN_USER_ID:
    raise ValueError("ADMIN_USER_ID не установлен")
ADMIN_USER_ID = int(ADMIN_USER_ID)

# === Хранилище для связи админ ↔ пользователь ===
current_user = {}

# === База данных ===
db_path = os.getenv("DATABASE_URL", "dialogs.db")
db = sqlite3.connect(db_path, check_same_thread=False)
cursor = db.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    sender TEXT,
    content_type TEXT,
    content TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    first_name TEXT,
    username TEXT
)
''')

# === Добавляем колонки, если их нет ===
try:
    cursor.execute('ALTER TABLE messages ADD COLUMN first_name TEXT')
except sqlite3.OperationalError:
    pass

try:
    cursor.execute('ALTER TABLE messages ADD COLUMN username TEXT')
except sqlite3.OperationalError:
    pass

db.commit()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === Кнопки для пользователя ===
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📝 Оставить заявку на работу")
    builder.button(text="❌ Отмена")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

def get_vacancy_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Переводчик", callback_data="vacancy_translator")
    builder.button(text="Редактор", callback_data="vacancy_editor")
    builder.button(text="Клинер", callback_data="vacancy_cleaner")
    builder.button(text="Тайпер", callback_data="vacancy_typist")
    builder.adjust(1)
    return builder.as_markup()

# === Кнопки для администратора ===
def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Пользователи", callback_data="users")
    builder.button(text="🗂 История", callback_data="history")
    builder.button(text="🧹 Очистить старые", callback_data="cleanup_now")
    builder.button(text="🗑 Очистить всё", callback_data="clear_all_dialogs")
    builder.button(text="⏹ Завершить диалог", callback_data="end_dialog")
    builder.adjust(1)
    return builder.as_markup()

# === Сохранение и пересылка сообщения ===
async def save_and_forward_content(message: types.Message, content_type: str, content: str):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    username = message.from_user.username

    cursor.execute('''
        INSERT INTO messages (user_id, sender, content_type, content, first_name, username)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, 'user', content_type, content, first_name, username))
    db.commit()

    await bot.forward_message(chat_id=ADMIN_USER_ID, from_chat_id=user_id, message_id=message.message_id)
    await bot.send_message(chat_id=ADMIN_USER_ID, text=f"👤 От: {first_name} (@{username or 'no_username'})\nid: {user_id}")

# === Команда /start ===
@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id == ADMIN_USER_ID:
        await message.answer(
            "👋 Добро пожаловать, администратор!\n\n"
            "Вы можете:\n"
            "• Посмотреть список пользователей\n"
            "• Увидеть историю переписки\n"
            "• Очистить старые диалоги",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "👋 На связи Linxy!\n\n"
            "Рады приветствовать Вас)",
            reply_markup=get_main_keyboard()
        )

# === Команда /menu ===
@dp.message(Command('menu', 'меню'))
async def cmd_menu(message: types.Message):
    user_id = message.from_user.id
    if user_id == ADMIN_USER_ID:
        await message.answer("Выберите действие:", reply_markup=get_admin_keyboard())
    else:
        await message.answer("Для подачи заявки используйте кнопки.", reply_markup=get_main_keyboard())

# === Команда /users ===
@dp.message(Command('users'))
async def cmd_users(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return

    cursor.execute('''
        SELECT DISTINCT user_id, first_name, username
        FROM messages
        WHERE first_name IS NOT NULL OR username IS NOT NULL
        ORDER BY user_id
    ''')
    users = cursor.fetchall()

    if not users:
        await message.answer("❌ Нет пользователей с перепиской.")
        return

    builder = InlineKeyboardBuilder()
    for user_id, first_name, username in users:
        name = first_name or "Неизвестный"
        uname = f" (@{username})" if username else ""
        builder.button(
            text=f"💬 {name}{uname} (ID: {user_id})",
            callback_data=f"start_dialog_{user_id}"
        )
    builder.adjust(1)
    await message.answer("👥 Выберите пользователя для диалога:", reply_markup=builder.as_markup())

# === Обработка кнопок ===
@dp.message(lambda msg: msg.text in ["📝 Оставить заявку на работу", "❌ Отмена"])
async def handle_user_buttons(message: types.Message):
    if message.from_user.id == ADMIN_USER_ID:
        return

    if message.text == "📝 Оставить заявку на работу":
        await message.answer("Выберите роль:", reply_markup=get_vacancy_keyboard())
    elif message.text == "❌ Отмена":
        await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard())

# === Обработка выбора вакансии ===
@dp.callback_query(lambda c: c.data.startswith('vacancy_'))
async def process_vacancy_selection(callback_query: types.CallbackQuery):
    vacancies = {
        'vacancy_translator': 'Переводчик',
        'vacancy_editor': 'Редактор',
        'vacancy_cleaner': 'Клинер',
        'vacancy_typist': 'Тайпер'
    }

    selected_vacancy = vacancies.get(callback_query.data)
    if selected_vacancy:
        # Отправляем пользователю уведомление
        await callback_query.message.answer("✅ Ваша заявка отправлена администратору, ожидайте.\n\nТеперь вы можете писать сообщения, и они будут пересланы администратору.")

        # Сохраняем в базу
        user_id = callback_query.from_user.id
        first_name = callback_query.from_user.first_name
        username = callback_query.from_user.username

        cursor.execute('''
            INSERT INTO messages (user_id, sender, content_type, content, first_name, username)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, 'user', 'application', selected_vacancy, first_name, username))
        db.commit()

        # Отправляем админу уведомление + кнопку "Ответить"
        builder = InlineKeyboardBuilder()
        builder.button(text="💬 Ответить", callback_data=f"reply_{user_id}")
        keyboard = builder.as_markup()

        await bot.send_message(
            ADMIN_USER_ID,
            f"👥 Новый работник на вакансию: {selected_vacancy}\n👤 От: {first_name} (@{username or 'no_username'})",
            reply_markup=keyboard
        )

    await callback_query.answer()

# === Обработка кнопки "Начать диалог" ===
@dp.callback_query(lambda c: c.data.startswith('start_dialog_'))
async def start_dialog(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer("❌ Доступ запрещён.")
        return

    try:
        user_id = int(callback_query.data.split('_')[2])
    except ValueError:
        await callback_query.answer("❌ Ошибка в ID.")
        return

    current_user[callback_query.from_user.id] = user_id
    await callback_query.message.answer(
        f"✅ Диалог с пользователем ID: {user_id} начат.\n\nТеперь напишите сообщение — оно будет отправлено ему.",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await callback_query.answer()

# === Обработка кнопки "Завершить диалог" ===
@dp.callback_query(lambda c: c.data == 'end_dialog')
async def end_dialog(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer("❌ Доступ запрещён.")
        return

    admin_id = callback_query.from_user.id
    if admin_id in current_user:
        del current_user[admin_id]
        await callback_query.message.answer("⏹ Диалог завершён.")
    else:
        await callback_query.message.answer("ℹ️ Диалог не был начат.")
    await callback_query.answer()

# === Обработка текста ===
from aiogram import F

@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    if user_id == ADMIN_USER_ID:
        # Если админ готов ответить
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, f"💬 Ответ администратора:\n{message.text}")
            await message.answer("✅ Ответ отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")
    else:
        # Любой текст от пользователя — пересылаем админу
        await save_and_forward_content(message, 'text', message.text)

# === Обработка фото ===
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        caption = message.caption or "Фото без описания"
        await save_and_forward_content(message, 'photo', caption)
    else:
        # Админ может отправлять фото как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "🖼 Фото-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Фото отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка документов ===
@dp.message(F.document)
async def handle_document(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        caption = message.caption or "Документ"
        await save_and_forward_content(message, 'document', caption)
    else:
        # Админ может отправлять документ как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "📁 Документ-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Документ отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка голосовых ===
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        await save_and_forward_content(message, 'voice', "Голосовое сообщение")
    else:
        # Админ может отправлять голос как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "🎤 Голосовой-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Голос отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка видео ===
@dp.message(F.video)
async def handle_video(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        caption = message.caption or "Видео"
        await save_and_forward_content(message, 'video', caption)
    else:
        # Админ может отправлять видео как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "📹 Видео-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Видео отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка аудио ===
@dp.message(F.audio)
async def handle_audio(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        caption = message.caption or "Аудио"
        await save_and_forward_content(message, 'audio', caption)
    else:
        # Админ может отправлять аудио как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "🎵 Аудио-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Аудио отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка стикеров ===
@dp.message(F.sticker)
async def handle_sticker(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        await save_and_forward_content(message, 'sticker', "Стикер")
    else:
        # Админ может отправлять стикер как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "😊 Стикер-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Стикер отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка видеосообщений ===
@dp.message(F.video_note)
async def handle_video_note(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        await save_and_forward_content(message, 'video_note', "Видеосообщение")
    else:
        # Админ может отправлять видеосообщение как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "📹 Видеосообщение-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Видеосообщение отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка контактов ===
@dp.message(F.contact)
async def handle_contact(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        await save_and_forward_content(message, 'contact', f"Контакт: {message.contact.first_name}")
    else:
        # Админ может отправлять контакт как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, f"👤 Контакт-ответ от администратора: {message.contact.first_name}")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Контакт отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка местоположения ===
@dp.message(F.location)
async def handle_location(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        await save_and_forward_content(message, 'location', f"Местоположение: {message.location.latitude}, {message.location.longitude}")
    else:
        # Админ может отправлять местоположение как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, f"📍 Местоположение-ответ от администратора: {message.location.latitude}, {message.location.longitude}")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Местоположение отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка опросов ===
@dp.message(F.poll)
async def handle_poll(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        await save_and_forward_content(message, 'poll', f"Опрос: {message.poll.question}")
    else:
        # Админ может отправлять опрос как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, f"📊 Опрос-ответ от администратора: {message.poll.question}")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Опрос отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или кнопку Пользователи.")

# === Обработка кнопок админа ===
@dp.callback_query(lambda c: c.data in ['users', 'history', 'cleanup_now', 'clear_all_dialogs'])
async def process_callback_admin(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer("❌ Доступ запрещён.")
        return

    if callback_query.data == 'users':
        cursor.execute('''
            SELECT DISTINCT user_id, first_name, username
            FROM messages
            WHERE first_name IS NOT NULL OR username IS NOT NULL
            ORDER BY user_id
        ''')
        users = cursor.fetchall()

        if not users:
            await callback_query.message.answer("❌ Нет пользователей с перепиской.")
        else:
            builder = InlineKeyboardBuilder()
            for user_id, first_name, username in users:
                name = first_name or "Неизвестный"
                uname = f" (@{username})" if username else ""
                builder.button(
                    text=f"💬 {name}{uname} (ID: {user_id})",
                    callback_data=f"start_dialog_{user_id}"
                )
            builder.adjust(1)
            await callback_query.message.answer("👥 Выберите пользователя для диалога:", reply_markup=builder.as_markup())

    elif callback_query.data == 'history':
        await callback_query.message.answer("Введите ID пользователя: /history <id>")

    elif callback_query.data == 'cleanup_now':
        seven_days_ago = datetime.now() - timedelta(days=7)
        cursor.execute('''
            DELETE FROM messages WHERE user_id IN (
                SELECT DISTINCT user_id FROM messages 
                WHERE timestamp < ?
                GROUP BY user_id
            )
        ''', (seven_days_ago.strftime('%Y-%m-%d %H:%M:%S'),))
        db.commit()
        await callback_query.message.answer("✅ Старые диалоги очищены.")

    elif callback_query.data == 'clear_all_dialogs':
        cursor.execute('DELETE FROM messages')
        db.commit()
        await callback_query.message.answer("✅ Вся история переписки очищена.")

    await callback_query.answer()

# === Команда /history ===
@dp.message(Command('history'))
async def cmd_history(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Используй: /history <user_id>")
        return

    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return

    cursor.execute('SELECT sender, content_type, content, timestamp FROM messages WHERE user_id = ? ORDER BY id ASC', (user_id,))
    records = cursor.fetchall()

    if not records:
        await message.answer("❌ Нет сообщений с этим пользователем.")
        return

    text = f"💬 История с пользователем {user_id}:\n\n"
    for sender, ct, cont, ts in records:
        prefix = "👤" if sender == 'user' else "✅"
        text += f"[{ts}] {prefix} {cont}\n"

    await message.answer(text[:4096] or text)

# === Команда /clear_all_dialogs ===
@dp.message(Command('clear_all_dialogs'))
async def cmd_clear_all_dialogs(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ Доступ запрещён.")
        return

    cursor.execute('DELETE FROM messages')
    db.commit()
    await message.answer("✅ Вся история переписки очищена.")

# === Запуск бота ===
if __name__ == '__main__':
    import asyncio
    async def main():
        await dp.start_polling(bot)

    asyncio.run(main())
