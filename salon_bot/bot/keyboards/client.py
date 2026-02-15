from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


def main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню клиента"""
    kb = ReplyKeyboardBuilder()
    kb.button(text="📅 Записаться")
    kb.button(text="📋 Мои записи")
    kb.button(text="❓ Помощь")
    kb.adjust(2, 1)
    return kb.as_markup(resize_keyboard=True)


def salons_kb(salons: list) -> InlineKeyboardMarkup:
    """Клавиатура выбора салона - компактная"""
    kb = InlineKeyboardBuilder()
    for salon in salons:
        kb.button(
            text=f"🏢 {salon['name']}",
            callback_data=f"salon_{salon['id']}"
        )
    kb.adjust(1)
    return kb.as_markup()


def services_kb(services: list) -> InlineKeyboardMarkup:
    """Клавиатура выбора услуги - компактная"""
    kb = InlineKeyboardBuilder()
    for service in services:
        # Компактный формат: название - цена (время)
        kb.button(
            text=f"{service['name']} • {int(service['price'])}с • {service['duration']}м",
            callback_data=f"service_{service['id']}"
        )
    kb.button(text="◀️ Назад", callback_data="back_to_salons")
    kb.adjust(1)
    return kb.as_markup()


def masters_kb(masters: list) -> InlineKeyboardMarkup:
    """Клавиатура выбора мастера - только имя и специализация"""
    kb = InlineKeyboardBuilder()
    for master in masters:
        # Убрали лишнюю информацию, только суть
        kb.button(
            text=f"👤 {master['name']} • {master['specialization']}",
            callback_data=f"master_{master['id']}"
        )
    kb.button(text="◀️ Назад", callback_data="back_to_services")
    kb.adjust(1)
    return kb.as_markup()


def dates_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора даты (7 дней)"""
    from datetime import datetime, timedelta

    kb = InlineKeyboardBuilder()
    today = datetime.now()

    days_ru = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

    for i in range(7):
        date = today + timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")

        if i == 0:
            display_text = "📅 Сегодня"
        elif i == 1:
            display_text = "📅 Завтра"
        else:
            day_name = days_ru[date.weekday()]
            display_text = f"{date.strftime('%d.%m')} ({day_name})"

        kb.button(text=display_text, callback_data=f"date_{date_str}")

    kb.button(text="◀️ Назад", callback_data="back_to_masters")
    kb.adjust(1)
    return kb.as_markup()


def time_slots_kb(slots: list, date: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора времени - компактная сетка"""
    kb = InlineKeyboardBuilder()

    if not slots:
        kb.button(text="😔 Нет мест", callback_data="no_slots")
    else:
        for time_str in slots:
            # Только время без эмодзи для компактности
            kb.button(text=time_str, callback_data=f"time_{date}_{time_str}")

    kb.button(text="◀️ Назад", callback_data="back_to_dates")
    
    # 4 кнопки в ряд для компактности
    kb.adjust(4, 4, 4, 4, 4, 4, 1)
    return kb.as_markup()


def my_bookings_kb(bookings: list) -> InlineKeyboardMarkup:
    """Клавиатура со списком записей"""
    kb = InlineKeyboardBuilder()
    for booking in bookings:
        date_str = booking['booking_datetime'][5:16]  # MM-DD HH:MM
        kb.button(
            text=f"🕐 {date_str} • {booking['service_name']}",
            callback_data=f"view_booking_{booking['id']}"
        )
    kb.adjust(1)
    return kb.as_markup()


def booking_detail_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Клавиатура действий с записью"""
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отменить", callback_data=f"cancel_booking_{booking_id}")
    kb.button(text="◀️ К списку", callback_data="back_to_my_bookings")
    kb.adjust(1)
    return kb.as_markup()
