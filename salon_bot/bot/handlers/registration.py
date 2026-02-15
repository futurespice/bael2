from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.database import Database

router = Router()


class RegistrationStates(StatesGroup):
    entering_phone = State()


@router.message(Command("register"))
async def start_registration(message: Message, state: FSMContext, db: Database):
    """Начало регистрации мастера"""

    # Проверяем, не зарегистрирован ли уже
    if await db.is_master(message.from_user.id):
        await message.answer("✅ Вы уже зарегистрированы как мастер!")
        return

    await message.answer(
        "👋 *Регистрация мастера*\n\n"
        "Введите ваш номер телефона:\n\n"
        "Формат: 555123456 или +996555123456\n\n"
        "_Запрос будет направлен администратору_",
        parse_mode="Markdown"
    )
    await state.set_state(RegistrationStates.entering_phone)


@router.message(RegistrationStates.entering_phone)
async def process_phone(message: Message, state: FSMContext, db: Database):
    """Обработка номера телефона"""
    phone = message.text.strip()

    # Упрощенная валидация с автодобавлением +996
    if not phone.startswith('+'):
        digits = ''.join(filter(str.isdigit, phone))
        if len(digits) == 9:
            phone = f"+996{digits}"
        elif len(digits) == 12 and digits.startswith('996'):
            phone = f"+{digits}"
        else:
            await message.answer(
                "❌ Неверный формат\n\n"
                "Введите: 555123456 или +996555123456"
            )
            return
    
    # Проверка минимальной длины
    digits = ''.join(filter(str.isdigit, phone))
    if len(digits) < 9:
        await message.answer(
            "❌ Слишком короткий номер\n\n"
            "Введите: 555123456 или +996555123456"
        )
        return

    # Создаем запрос на регистрацию
    request_id = await db.create_registration_request(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        phone=phone
    )

    if request_id == 0:
        await message.answer(
            "⏳ У вас уже есть активный запрос\n\n"
            "Дождитесь ответа администратора"
        )
        await state.clear()
        return

    await message.answer(
        f"✅ *Запрос отправлен!*\n\n"
        f"📱 {phone}\n"
        f"👤 {message.from_user.full_name}\n\n"
        f"Администратор рассмотрит запрос в ближайшее время\n"
        f"Вы получите уведомление",
        parse_mode="Markdown"
    )

    # Уведомляем всех владельцев салонов
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT telegram_id FROM salon_owners WHERE is_active = 1") as cursor:
            owners = await cursor.fetchall()

    for owner in owners:
        try:
            await message.bot.send_message(
                owner['telegram_id'],
                f"🔔 *Новый запрос на регистрацию*\n\n"
                f"👤 {message.from_user.full_name}\n"
                f"📱 {phone}\n"
                f"🆔 {message.from_user.id}\n\n"
                f"Используйте /admin",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Failed to notify owner: {e}")

    await state.clear()
