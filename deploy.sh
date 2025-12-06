#!/bin/bash
# =============================================================================
# БайЭл - Production Deployment Script
# =============================================================================
# Использование: ./deploy.sh [команда]
# Команды: init, start, stop, restart, logs, ssl, backup, update

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функции
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Проверка .env файла
check_env() {
    if [ ! -f .env ]; then
        log_error ".env файл не найден!"
        log_info "Скопируйте .env.production в .env и заполните значения"
        exit 1
    fi
}

# Инициализация (первый запуск)
init() {
    log_info "Инициализация БайЭл..."
    
    check_env
    
    # Создаём директории
    mkdir -p certbot/conf certbot/www
    mkdir -p nginx/conf.d
    
    # Используем временную конфигурацию nginx
    if [ -f nginx/conf.d/baiel.conf ]; then
        mv nginx/conf.d/baiel.conf nginx/conf.d/baiel.conf.ssl
    fi
    cp nginx/conf.d/baiel-init.conf nginx/conf.d/default.conf
    
    # Запускаем контейнеры
    docker-compose up -d --build
    
    log_info "Ожидание запуска сервисов..."
    sleep 10
    
    # Применяем миграции
    docker-compose exec web python manage.py migrate --noinput
    
    log_info "Инициализация завершена!"
    log_info "Теперь выполните: ./deploy.sh ssl для получения SSL сертификата"
}

# Получение SSL сертификата
ssl() {
    log_info "Получение SSL сертификата..."
    
    # Получаем сертификат
    docker-compose run --rm certbot certonly \
        --webroot \
        --webroot-path=/var/www/certbot \
        --email admin@baielapp.com.kg \
        --agree-tos \
        --no-eff-email \
        -d baielapp.com.kg \
        -d www.baielapp.com.kg \
        -d api.baielapp.com.kg
    
    # Переключаемся на production конфигурацию nginx
    rm -f nginx/conf.d/default.conf
    if [ -f nginx/conf.d/baiel.conf.ssl ]; then
        mv nginx/conf.d/baiel.conf.ssl nginx/conf.d/baiel.conf
    fi
    
    # Перезапускаем nginx
    docker-compose restart nginx
    
    log_info "SSL сертификат получен и настроен!"
}

# Запуск
start() {
    log_info "Запуск БайЭл..."
    check_env
    docker-compose up -d
    log_info "Сервисы запущены"
    docker-compose ps
}

# Остановка
stop() {
    log_info "Остановка БайЭл..."
    docker-compose down
    log_info "Сервисы остановлены"
}

# Перезапуск
restart() {
    log_info "Перезапуск БайЭл..."
    docker-compose restart
    log_info "Сервисы перезапущены"
}

# Логи
logs() {
    SERVICE=${2:-""}
    if [ -z "$SERVICE" ]; then
        docker-compose logs -f --tail=100
    else
        docker-compose logs -f --tail=100 $SERVICE
    fi
}

# Бэкап базы данных
backup() {
    log_info "Создание бэкапа базы данных..."
    
    BACKUP_DIR="./backups"
    mkdir -p $BACKUP_DIR
    
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/baiel_backup_$TIMESTAMP.sql"
    
    docker-compose exec -T db pg_dump -U baiel baiel > $BACKUP_FILE
    
    # Сжимаем
    gzip $BACKUP_FILE
    
    log_info "Бэкап создан: ${BACKUP_FILE}.gz"
    
    # Удаляем старые бэкапы (старше 7 дней)
    find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
    log_info "Старые бэкапы удалены"
}

# Обновление
update() {
    log_info "Обновление БайЭл..."
    
    # Создаём бэкап перед обновлением
    backup
    
    # Получаем новый код
    git pull origin main
    
    # Пересобираем и перезапускаем
    docker-compose up -d --build
    
    # Применяем миграции
    docker-compose exec web python manage.py migrate --noinput
    
    # Собираем статику
    docker-compose exec web python manage.py collectstatic --noinput
    
    log_info "Обновление завершено!"
}

# Создание суперпользователя
createsuperuser() {
    log_info "Создание суперпользователя..."
    docker-compose exec web python manage.py createsuperuser
}

# Статус
status() {
    docker-compose ps
}

# Проверка здоровья
health() {
    log_info "Проверка здоровья сервисов..."
    
    # Проверяем web
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/docs/ || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        log_info "Web: OK ($HTTP_CODE)"
    else
        log_error "Web: FAIL ($HTTP_CODE)"
    fi
    
    # Проверяем Redis
    REDIS_PING=$(docker-compose exec -T redis redis-cli ping 2>/dev/null || echo "FAIL")
    if [ "$REDIS_PING" = "PONG" ]; then
        log_info "Redis: OK"
    else
        log_error "Redis: FAIL"
    fi
    
    # Проверяем PostgreSQL
    PG_STATUS=$(docker-compose exec -T db pg_isready -U baiel 2>/dev/null && echo "OK" || echo "FAIL")
    log_info "PostgreSQL: $PG_STATUS"
}

# Показать помощь
help() {
    echo "БайЭл - Production Deployment Script"
    echo ""
    echo "Использование: ./deploy.sh [команда]"
    echo ""
    echo "Команды:"
    echo "  init              Первичная инициализация"
    echo "  ssl               Получение SSL сертификата"
    echo "  start             Запустить сервисы"
    echo "  stop              Остановить сервисы"
    echo "  restart           Перезапустить сервисы"
    echo "  logs [service]    Показать логи (опционально: web, db, redis, celery)"
    echo "  backup            Создать бэкап базы данных"
    echo "  update            Обновить приложение"
    echo "  createsuperuser   Создать суперпользователя"
    echo "  status            Показать статус контейнеров"
    echo "  health            Проверить здоровье сервисов"
    echo "  help              Показать эту справку"
}

# Основная логика
case "${1:-help}" in
    init)
        init
        ;;
    ssl)
        ssl
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    logs)
        logs "$@"
        ;;
    backup)
        backup
        ;;
    update)
        update
        ;;
    createsuperuser)
        createsuperuser
        ;;
    status)
        status
        ;;
    health)
        health
        ;;
    help|*)
        help
        ;;
esac
