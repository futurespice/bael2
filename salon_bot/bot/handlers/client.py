from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime

from bot.states import BookingStates
from bot.keyboards.client import (
    main_menu_kb, salons_kb, services_kb,
    masters_kb, dates_kb, time_slots_kb, my_bookings_kb, booking_detail_kb
)
from bot.database import Database

router = Router()


@router.message(F.text == "📅 Записаться")
async def start_booking(message: Message, state: FSMContext, db: Database):
    """Начало процесса записи"""
    salons = await db.get_active_salons()

    if not salons:
        await message.answer("😔 Сейчас нет доступных салонов.")
        return

    await message.answer(
        "🏢 *Выберите салон:*",
        reply_markup=salons_kb(salons),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_salon)


@router.callback_query(F.data.startswith("salon_"))
async def choose_salon(callback: CallbackQuery, state: FSMContext, db: Database):
    """Выбор салона"""
    salon_id = int(callback.data.split("_")[1])
    await state.update_data(salon_id=salon_id)

    services = await db.get_services_by_salon(salon_id)

    if not services:
        await callback.message.edit_text("😔 В этом салоне пока нет услуг.")
        await callback.answer()
        return

    await callback.message.edit_text(
        "💇 *Выберите услугу:*",
        reply_markup=services_kb(services),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_service)
    await callback.answer()


@router.callback_query(F.data.startswith("service_"))
async def choose_service(callback: CallbackQuery, state: FSMContext, db: Database):
    """Выбор услуги"""
    service_id = int(callback.data.split("_")[1])
    await state.update_data(service_id=service_id)

    data = await state.get_data()

    # Получаем ВСЕХ активных мастеров салона
    all_masters = await db.get_masters_by_salon(data['salon_id'])

    if not all_masters:
        await callback.message.edit_text(
            "😔 Нет мастеров.\nПопробуйте другой салон."
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "👨‍💼 *Выберите мастера:*",
        reply_markup=masters_kb(all_masters),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_master)
    await callback.answer()


@router.callback_query(F.data.startswith("master_"))
async def choose_master(callback: CallbackQuery, state: FSMContext):
    """Выбор мастера"""
    master_id = int(callback.data.split("_")[1])
    await state.update_data(master_id=master_id)

    await callback.message.edit_text(
        "📅 *Выберите дату:*",
        reply_markup=dates_kb(),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_date)
    await callback.answer()


@router.callback_query(F.data.startswith("date_"))
async def choose_date(callback: CallbackQuery, state: FSMContext, db: Database):
    """Выбор даты"""
    date = callback.data.split("_", 1)[1]
    await state.update_data(date=date)

    data = await state.get_data()

    # Получаем длительность услуги
    service = await db.get_service(data['service_id'])

    # Получаем свободные слоты
    available_slots = await db.get_available_time_slots(
        data['master_id'],
        date,
        service['duration']
    )

    if not available_slots:
        await callback.message.edit_text(
            f"😔 На {date} нет свободных мест\n\n"
            f"Выберите другую дату:",
            reply_markup=dates_kb()
        )
        await callback.answer("Нет свободных мест", show_alert=True)
        return

    # Форматируем дату красиво
    from datetime import datetime
    date_obj = datetime.strptime(date, '%Y-%m-%d')
    date_formatted = date_obj.strftime('%d.%m.%Y')

    await callback.message.edit_text(
        f"🕐 *Свободное время на {date_formatted}:*\n"
        f"Доступно: {len(available_slots)} слотов",
        reply_markup=time_slots_kb(available_slots, date),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_time)
    await callback.answer()


@router.callback_query(F.data.startswith("time_"))
async def choose_time(callback: CallbackQuery, state: FSMContext):
    """Выбор времени"""
    parts = callback.data.split("_")
    date = parts[1]
    time = parts[2]

    await state.update_data(time=time)

    await callback.message.edit_text(
        "📱 *Ваш номер телефона:*\n\n"
        "Формат: 555123456 или +996555123456",
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.entering_phone)
    await callback.answer()


@router.message(BookingStates.entering_phone)
async def enter_phone(message: Message, state: FSMContext, db: Database):
    """Ввод телефона и создание записи"""
    phone = message.text.strip()

    # Упрощенная валидация - просто проверяем что есть цифры
    # Автоматически добавляем +996 если не указан код
    if not phone.startswith('+'):
        # Убираем все нецифровые символы
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
    
    # Проверяем что есть хотя бы 9 цифр
    digits = ''.join(filter(str.isdigit, phone))
    if len(digits) < 9:
        await message.answer(
            "❌ Слишком короткий номер\n\n"
            "Введите: 555123456 или +996555123456"
        )
        return

    await state.update_data(phone=phone)
    data = await state.get_data()

    # Формируем datetime
    booking_datetime = f"{data['date']} {data['time']}:00"

    # Получаем информацию для подтверждения
    service = await db.get_service(data['service_id'])
    master = await db.get_master(data['master_id'])

    # Финальная проверка доступности слота
    is_available = await db.is_slot_available(
        data['master_id'],
        booking_datetime,
        service['duration']
    )

    if not is_available:
        await message.answer(
            "😔 Время уже занято\n\n"
            "Начните заново: /start",
            reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    # Сохраняем в БД
    booking_id = await db.create_booking({
        'client_telegram_id': message.from_user.id,
        'client_name': message.from_user.full_name,
        'client_phone': phone,
        'master_id': data['master_id'],
        'service_id': data['service_id'],
        'booking_datetime': booking_datetime
    })

    # Форматируем дату красиво
    from datetime import datetime
    date_obj = datetime.strptime(data['date'], '%Y-%m-%d')
    date_formatted = date_obj.strftime('%d.%m.%Y')

    # Красивое подтверждение с информацией о мастере
    await message.answer(
        f"✅ *Запись #{booking_id} создана!*\n\n"
        f"┌─ 📅 {date_formatted} в {data['time']}\n"
        f"├─ 💇 {service['name']}\n"
        f"├─ ⏱ {service['duration']} минут\n"
        f"└─ 💰 {int(service['price'])} сом\n\n"
        f"👨‍💼 *Ваш специалист:*\n"
        f"┌─ 👤 {master['name']}\n"
        f"└─ 💼 {master['specialization']}\n\n"
        f"📱 Контакт: {phone}\n"
        f"⏰ Напоминание за 24 часа\n\n"
        f"_Ждем вас!_ 💫",
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )

    # Уведомляем мастера
    if master['telegram_id']:
        try:
            await message.bot.send_message(
                master['telegram_id'],
                f"🔔 *Новая запись #{booking_id}*\n\n"
                f"👤 {message.from_user.full_name}\n"
                f"📱 {phone}\n"
                f"💇 {service['name']}\n"
                f"🕐 {date_formatted} {data['time']}\n"
                f"⏱ {service['duration']} мин\n\n"
                f"Управление: /manage {booking_id}",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Failed to notify master: {e}")

    await state.clear()


@router.message(F.text == "📋 Мои записи")
async def my_bookings(message: Message, db: Database):
    """Просмотр записей"""
    bookings = await db.get_client_bookings(message.from_user.id)

    if not bookings:
        await message.answer(
            "У вас пока нет записей\n\n"
            "Нажмите 📅 Записаться",
            reply_markup=main_menu_kb()
        )
        return

    text = "📋 *Ваши записи:*\n\n"
    for i, booking in enumerate(bookings, 1):
        # Форматируем дату
        datetime_str = booking['booking_datetime'][:16]
        
        text += f"{i}. 🕐 {datetime_str}\n"
        text += f"   💇 {booking['service_name']}\n"
        text += f"   👤 {booking['master_name']}\n"
        text += f"   📊 {booking['status']}\n\n"

    text += "_Нажмите для деталей_ 👇"

    await message.answer(text, parse_mode="Markdown", reply_markup=my_bookings_kb(bookings))


@router.callback_query(F.data.startswith("view_booking_"))
async def view_booking_detail(callback: CallbackQuery, db: Database):
    """Детали записи"""
    booking_id = int(callback.data.split("_")[2])
    booking = await db.get_booking(booking_id)

    if not booking:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    text = f"📋 *Запись #{booking['id']}*\n\n"
    text += f"🕐 {booking['booking_datetime']}\n"
    text += f"💇 {booking['service_name']}\n"
    text += f"👤 {booking['master_name']}\n"
    text += f"📱 {booking['client_phone']}\n"
    text += f"📊 {booking['status']}\n"

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=booking_detail_kb(booking_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_booking_"))
async def cancel_booking(callback: CallbackQuery, db: Database):
    """Отмена записи клиентом"""
    booking_id = int(callback.data.split("_")[2])

    # Проверяем возможность отмены
    can_cancel, message_text = await db.can_cancel_booking(booking_id)

    if not can_cancel:
        await callback.answer(message_text, show_alert=True)
        return

    # Получаем данные мастера для уведомления
    booking = await db.get_booking(booking_id)
    master = await db.get_master(booking['master_id'])

    # Отменяем запись
    await db.cancel_booking(booking_id)

    await callback.message.edit_text(
        f"✅ Запись #{booking_id} отменена"
    )

    # Уведомляем мастера
    try:
        await callback.bot.send_message(
            master['telegram_id'],
            f"❌ Клиент отменил запись #{booking_id}:\n\n"
            f"👤 {booking['client_name']}\n"
            f"🕐 {booking['booking_datetime']}\n"
            f"💇 {booking['service_name']}"
        )
    except:
        pass

    await callback.answer("Запись отменена")


@router.callback_query(F.data == "back_to_my_bookings")
async def back_to_bookings(callback: CallbackQuery, db: Database):
    """Возврат к списку записей"""
    bookings = await db.get_client_bookings(callback.from_user.id)

    text = "📋 *Ваши записи:*\n\n"
    for i, booking in enumerate(bookings, 1):
        text += f"{i}. 🕐 {booking['booking_datetime'][:16]}\n"
        text += f"   💇 {booking['service_name']}\n"
        text += f"   👤 {booking['master_name']}\n\n"

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=my_bookings_kb(bookings)
    )
    await callback.answer()


# Навигация назад
@router.callback_query(F.data == "back_to_salons")
async def back_to_salons(callback: CallbackQuery, state: FSMContext, db: Database):
    salons = await db.get_active_salons()
    await callback.message.edit_text(
        "🏢 *Выберите салон:*", 
        reply_markup=salons_kb(salons),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_salon)
    await callback.answer()


@router.callback_query(F.data == "back_to_services")
async def back_to_services(callback: CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    services = await db.get_services_by_salon(data['salon_id'])
    await callback.message.edit_text(
        "💇 *Выберите услугу:*", 
        reply_markup=services_kb(services),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_service)
    await callback.answer()


@router.callback_query(F.data == "back_to_masters")
async def back_to_masters(callback: CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    all_masters = await db.get_masters_by_salon(data['salon_id'])
    await callback.message.edit_text(
        "👨‍💼 *Выберите мастера:*", 
        reply_markup=masters_kb(all_masters),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_master)
    await callback.answer()


@router.callback_query(F.data == "back_to_dates")
async def back_to_dates(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📅 *Выберите дату:*", 
        reply_markup=dates_kb(),
        parse_mode="Markdown"
    )
    await state.set_state(BookingStates.choosing_date)
    await callback.answer()
