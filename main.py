from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import asyncio
import sqlite3
import os
from datetime import datetime, timedelta

# === Добавим F ===
from aiogram import F

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
# === Состояния пользователей: может ли писать ===
user_states = {}  # user_id -> True/False

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
    builder.button(text="❓ Задать вопрос")
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
    builder = ReplyKeyboardBuilder()
    builder.button(text="👥 Пользователи")
    builder.button(text="🗂 История")
    builder.button(text="🧹 Очистить старые")
    builder.button(text="🗑 Очистить всё")
    builder.button(text="⏹ Завершить диалог")
    builder.button(text="❌ Отмена")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)

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

    # Если это вопрос (а не заявка), добавляем кнопку "Ответить"
    if content_type == 'question':
        builder = InlineKeyboardBuilder()
        builder.button(text="💬 Ответить", callback_data=f"reply_{user_id}")
        keyboard = builder.as_markup()

        await bot.forward_message(chat_id=ADMIN_USER_ID, from_chat_id=user_id, message_id=message.message_id)
        await bot.send_message(chat_id=ADMIN_USER_ID, text=f"Вам задали вопрос\n👤 От: {first_name} (@{username or 'no_username'})\nid: {user_id}", reply_markup=keyboard)
    else:
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
        # При первом входе пользователь не может писать
        user_states[user_id] = False
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

    text = "👥 Пользователи:\n"
    for user_id, first_name, username in users:
        name = first_name or "Неизвестный"
        uname = f" (@{username})" if username else ""
        text += f"🆔 {user_id}: {name}{uname}\n"
    await message.answer(text + "\n\nНапишите ID пользователя, чтобы начать диалог:")

# === Обработка кнопок админа ===
@dp.message(lambda msg: msg.text in [
    "👥 Пользователи",
    "🗂 История",
    "🧹 Очистить старые",
    "🗑 Очистить всё",
    "⏹ Завершить диалог"
])
async def handle_admin_buttons(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return

    if message.text == "👥 Пользователи":
        cursor.execute('''
            SELECT DISTINCT user_id, first_name, username
            FROM messages
            WHERE first_name IS NOT NULL OR username IS NOT NULL
            ORDER BY user_id
        ''')
        users = cursor.fetchall()
        if not users:
            await message.answer("❌ Нет пользователей с перепиской.")
        else:
            text = "👥 Пользователи:\n"
            for user_id, first_name, username in users:
                name = first_name or "Неизвестный"
                uname = f" (@{username})" if username else ""
                text += f"🆔 {user_id}: {name}{uname}\n"
            await message.answer(text + "\n\nНапишите ID пользователя, чтобы начать диалог:")

    elif message.text == "🗂 История":
        await message.answer("Введите ID пользователя: /history <id>")

    elif message.text == "🧹 Очистить старые":
        seven_days_ago = datetime.now() - timedelta(days=7)
        cursor.execute('''
            DELETE FROM messages WHERE user_id IN (
                SELECT DISTINCT user_id FROM messages 
                WHERE timestamp < ?
                GROUP BY user_id
            )
        ''', (seven_days_ago.strftime('%Y-%m-%d %H:%M:%S'),))
        db.commit()
        await message.answer("✅ Старые диалоги очищены.")

    elif message.text == "🗑 Очистить всё":
        cursor.execute('DELETE FROM messages')
        db.commit()
        await message.answer("✅ Вся история переписки очищена.")

    elif message.text == "⏹ Завершить диалог":
        admin_id = message.from_user.id
        if admin_id in current_user:
            del current_user[admin_id]
            await message.answer("⏹ Диалог завершён.")
        else:
            await message.answer("ℹ️ Диалог не был начат.")

# === Обработка ввода ID пользователя ===
@dp.message(F.text.func(lambda text: text.isdigit()))
async def handle_user_id_input(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        return

    try:
        target_user_id = int(message.text)
    except ValueError:
        return

    # Проверим, есть ли такой пользователь в базе
    cursor.execute('SELECT 1 FROM messages WHERE user_id = ? LIMIT 1', (target_user_id,))
    if not cursor.fetchone():
        await message.answer("❌ Пользователь с таким ID не найден.")
        return

    current_user[user_id] = target_user_id
    await message.answer(f"✅ Диалог с пользователем ID: {target_user_id} начат.\nТеперь пишите сообщение — оно будет отправлено ему.")

# === Обработка кнопок ===
@dp.message(lambda msg: msg.text in ["📝 Оставить заявку на работу", "❓ Задать вопрос", "❌ Отмена"])
async def handle_user_buttons(message: types.Message):
    user_id = message.from_user.id
    if user_id == ADMIN_USER_ID:
        return

    if message.text == "❌ Отмена":
        user_states[user_id] = False
        await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard())
    else:
        # Любая другая кнопка (кроме "Отмена") — разрешает писать
        user_states[user_id] = True

        if message.text == "📝 Оставить заявку на работу":
            await message.answer("Выберите роль:", reply_markup=get_vacancy_keyboard())
        elif message.text == "❓ Задать вопрос":
            await message.answer("Можете задавать вопрос администратору")

            # Сохраняем в базу, что пользователь начал взаимодействие
            first_name = message.from_user.first_name
            username = message.from_user.username

            cursor.execute('''
                INSERT INTO messages (user_id, sender, content_type, content, first_name, username)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, 'user', 'question_initiated', 'Пользователь начал задавать вопрос', first_name, username))
            db.commit()

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
        await callback_query.message.answer(
            "✅ Ваша заявка отправлена администратору, ожидайте.\n\n"
            "Теперь вы можете писать сообщения, и они будут пересланы администратору."
        )

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

        # === Выводим анкету ===
        await callback_query.message.answer(
            "А теперь давайте заполним небольшую анкетку\n\n"
            "1. Ссылка на ваш профиль на мангалиб\n"
            "2. Возраст\n"
            "3. Есть ли фотошоп\n"
            "4. Ваш часовой пояс\n"
            "5. Сколько времени можете уделять работе?\n"
            "6. Жанры, с которыми хотите и не хотите работать"
        )

    await callback_query.answer()

# === Обработка кнопки "Ответить" при новой заявке ===
@dp.callback_query(lambda c: c.data.startswith('reply_'))
async def process_reply_request(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_USER_ID:
        await callback_query.answer("❌ Доступ запрещён.")
        return

    try:
        user_id = int(callback_query.data.split('_')[1])
    except ValueError:
        await callback_query.answer("❌ Ошибка в ID.")
        return

    # Сохраняем текущего пользователя для админа
    current_user[callback_query.from_user.id] = user_id

    await callback_query.message.answer(
        f"📝 Готов к ответу пользователю ID: {user_id}\n\nНапишите сообщение — оно будет отправлено ему.",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await callback_query.answer()

# === Обработка текста ===
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
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")
    else:
        # Проверяем, может ли пользователь отправлять сообщения
        if user_id in user_states and user_states[user_id]:
            # Проверим, является ли это вопросом (после нажатия "Задать вопрос")
            cursor.execute('SELECT 1 FROM messages WHERE user_id = ? AND content_type = ? LIMIT 1', (user_id, 'question_initiated'))
            if cursor.fetchone():
                await save_and_forward_content(message, 'question', message.text)
            else:
                await save_and_forward_content(message, 'text', message.text)
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")

# === Обработка фото ===
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            caption = message.caption or "Фото без описания"
            await save_and_forward_content(message, 'photo', caption)
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять фото как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "🖼 Фото-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Фото отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка документов ===
@dp.message(F.document)
async def handle_document(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            caption = message.caption or "Документ"
            await save_and_forward_content(message, 'document', caption)
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять документ как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "📁 Документ-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Документ отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка голосовых ===
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            await save_and_forward_content(message, 'voice', "Голосовое сообщение")
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять голос как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "🎤 Голосовой-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Голос отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка видео ===
@dp.message(F.video)
async def handle_video(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            caption = message.caption or "Видео"
            await save_and_forward_content(message, 'video', caption)
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять видео как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "📹 Видео-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Видео отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка аудио ===
@dp.message(F.audio)
async def handle_audio(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            caption = message.caption or "Аудио"
            await save_and_forward_content(message, 'audio', caption)
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять аудио как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "🎵 Аудио-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Аудио отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка стикеров ===
@dp.message(F.sticker)
async def handle_sticker(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            await save_and_forward_content(message, 'sticker', "Стикер")
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять стикер как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "😊 Стикер-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Стикер отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка видеосообщений ===
@dp.message(F.video_note)
async def handle_video_note(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            await save_and_forward_content(message, 'video_note', "Видеосообщение")
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять видеосообщение как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, "📹 Видеосообщение-ответ от администратора:")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Видеосообщение отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка контактов ===
@dp.message(F.contact)
async def handle_contact(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            await save_and_forward_content(message, 'contact', f"Контакт: {message.contact.first_name}")
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять контакт как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, f"👤 Контакт-ответ от администратора: {message.contact.first_name}")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Контакт отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка местоположения ===
@dp.message(F.location)
async def handle_location(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            await save_and_forward_content(message, 'location', f"Местоположение: {message.location.latitude}, {message.location.longitude}")
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять местоположение как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, f"📍 Местоположение-ответ от администратора: {message.location.latitude}, {message.location.longitude}")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Местоположение отправлено пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

# === Обработка опросов ===
@dp.message(F.poll)
async def handle_poll(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_USER_ID:
        if user_id in user_states and user_states[user_id]:
            await save_and_forward_content(message, 'poll', f"Опрос: {message.poll.question}")
        else:
            await message.answer("Для начала взаимодействия с администратором выберите одну из кнопок: 'Оставить заявку' или 'Задать вопрос'")
    else:
        # Админ может отправлять опрос как ответ
        if user_id in current_user:
            target_user_id = current_user[user_id]
            await bot.send_message(target_user_id, f"📊 Опрос-ответ от администратора: {message.poll.question}")
            await bot.copy_message(target_user_id, message.chat.id, message.message_id)
            await message.answer("✅ Опрос отправлен пользователю.")
        else:
            await message.answer("❌ Выберите пользователя для диалога через /users или введите ID.")

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
