# БайЭл Backend v2.0

B2B платформа для управления дистрибуцией товаров.

## 🚀 Быстрый старт (локальная разработка)

### 1. Клонирование и настройка

```bash
git clone https://github.com/your-repo/bael2.git
cd bael2

# Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

# Установить зависимости
pip install -r requirements.txt

# Создать .env файл
cp .env.example .env
# Отредактировать .env
```

### 2. Запуск баз данных через Docker

```bash
docker-compose -f docker-compose.dev.yml up -d
```

### 3. Миграции и запуск

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

API будет доступен по адресу: http://localhost:8000/api/docs/

---

## 🏭 Production деплой

### Требования на сервере

- Docker & Docker Compose
- Домен, направленный на IP сервера
- Открытые порты: 80, 443

### 1. Подготовка сервера

```bash
# Клонировать репозиторий
git clone https://github.com/your-repo/bael2.git
cd bael2

# Создать .env файл
cp .env.production .env
nano .env  # Заполнить все значения!
```

### 2. Настройка .env (ОБЯЗАТЕЛЬНО!)

```bash
# Генерация SECRET_KEY
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Заполните в `.env`:
- `SECRET_KEY` - сгенерированный ключ
- `DB_PASSWORD` - надёжный пароль для PostgreSQL
- `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` - данные SMTP

### 3. Первый запуск

```bash
# Сделать скрипт исполняемым
chmod +x deploy.sh

# Инициализация (первый запуск)
./deploy.sh init
```

### 4. Получение SSL сертификата

```bash
./deploy.sh ssl
```

### 5. Создание суперпользователя

```bash
./deploy.sh createsuperuser
```

---

## 📋 Команды управления

```bash
./deploy.sh start      # Запустить
./deploy.sh stop       # Остановить
./deploy.sh restart    # Перезапустить
./deploy.sh logs       # Логи всех сервисов
./deploy.sh logs web   # Логи Django
./deploy.sh backup     # Бэкап БД
./deploy.sh update     # Обновить из git
./deploy.sh status     # Статус контейнеров
./deploy.sh health     # Проверка здоровья
```

---

## 🔗 Endpoints

| URL | Описание |
|-----|----------|
| https://api.baielapp.com.kg/api/docs/ | Swagger документация |
| https://api.baielapp.com.kg/api/redoc/ | ReDoc документация |
| https://api.baielapp.com.kg/admin/ | Django Admin |
| https://api.baielapp.com.kg/health/ | Health check |

---

## 📁 Структура проекта

```
bael2/
├── config/              # Django настройки
├── users/               # Пользователи и аутентификация
├── products/            # Товары и расходы
├── stores/              # Магазины и география
├── orders/              # Заказы и долги
├── reports/             # Статистика
├── notifications/       # Уведомления
├── nginx/               # Nginx конфигурация
├── docker-compose.yml   # Production Docker
├── docker-compose.dev.yml # Development Docker
├── Dockerfile
├── deploy.sh            # Скрипт деплоя
└── requirements.txt
```

---

## 🔐 Безопасность

В production обязательно:
- [ ] Изменить `SECRET_KEY`
- [ ] Установить `DEBUG=False`
- [ ] Использовать HTTPS
- [ ] Настроить сложный `DB_PASSWORD`
- [ ] Настроить firewall (открыть только 80, 443, 22)

---

## 📞 Поддержка

- Email: support@baielapp.com.kg
- Telegram: @baielapp
