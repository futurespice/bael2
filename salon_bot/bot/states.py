from aiogram.fsm.state import State, StatesGroup

class BookingStates(StatesGroup):
    """Состояния для записи клиента"""
    choosing_salon = State()
    choosing_service = State()
    choosing_master = State()
    choosing_date = State()
    choosing_time = State()
    entering_phone = State()

class MasterStates(StatesGroup):
    """Состояния для мастера"""
    viewing_calendar = State()

class RegistrationStates(StatesGroup):
    """Состояния для регистрации мастера"""
    entering_phone = State()
    selecting_master = State()
    confirming = State()
