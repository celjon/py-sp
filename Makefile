# AntiSpam Bot Makefile
# Упрощает команды разработки и деплоя

.PHONY: help install test clean run-telegram run-http run-both test-deployment test-http-api

# Переменные
PYTHON = python
PIP = pip
ENV_FILE = .env
DOCKER_COMPOSE = docker-compose

# Помощь
help:
	@echo "🤖 AntiSpam Bot - Доступные команды:"
	@echo ""
	@echo "📦 Установка и настройка:"
	@echo "  make install          - Установить зависимости"
	@echo "  make setup-env        - Создать .env файл из примера"
	@echo "  make setup-db         - Настроить базу данных (миграции)"
	@echo ""
	@echo "🚀 Запуск:"
	@echo "  make run-telegram     - Запустить только Telegram бот"
	@echo "  make run-http         - Запустить только HTTP API"
	@echo "  make run-both         - Запустить Telegram + HTTP"
	@echo ""
	@echo "🧪 Тестирование:"
	@echo "  make test-deployment  - Комплексный тест системы"
	@echo "  make test-http-api    - Тест HTTP API (если запущен)"
	@echo "  make test-detectors   - Тест только детекторов"
	@echo ""
	@echo "🐳 Docker:"
	@echo "  make docker-build     - Собрать Docker образ"
	@echo "  make docker-up        - Запустить через Docker Compose"
	@echo "  make docker-down      - Остановить Docker Compose"
	@echo ""
	@echo "🧹 Очистка:"
	@echo "  make clean            - Очистить временные файлы"
	@echo "  make clean-cache      - Очистить кэш Python"

# Установка зависимостей
install:
	@echo "📦 Установка зависимостей..."
	$(PIP) install -r requirements.txt
	@echo "✅ Зависимости установлены"

# Создание .env файла
setup-env:
	@if [ ! -f $(ENV_FILE) ]; then \
		echo "📝 Создание .env файла..."; \
		cp env.example $(ENV_FILE); \
		echo "✅ Файл .env создан из env.example"; \
		echo "⚠️  Отредактируйте .env файл с вашими настройками"; \
	else \
		echo "ℹ️  Файл .env уже существует"; \
	fi

# Настройка базы данных
setup-db:
	@echo "💾 Настройка базы данных..."
	@if [ -f alembic.ini ]; then \
		echo "🔄 Выполнение миграций..."; \
		alembic upgrade head; \
		echo "✅ Миграции выполнены"; \
	else \
		echo "❌ alembic.ini не найден"; \
	fi

# Запуск только Telegram бота
run-telegram:
	@echo "🤖 Запуск Telegram бота..."
	RUN_MODE=telegram $(PYTHON) src/main.py

# Запуск только HTTP API
run-http:
	@echo "🌐 Запуск HTTP API..."
	RUN_MODE=http $(PYTHON) src/main.py

# Запуск обоих сервисов
run-both:
	@echo "🚀 Запуск Telegram + HTTP..."
	RUN_MODE=both $(PYTHON) src/main.py

# Комплексный тест системы
test-deployment:
	@echo "🧪 Комплексный тест системы..."
	@set PYTHONIOENCODING=utf-8 && $(PYTHON) test_deployment.py

# Тест HTTP API
test-http-api:
	@echo "🌐 Тест HTTP API..."
	@set PYTHONIOENCODING=utf-8 && $(PYTHON) test_http_api.py

# Проверка зависимостей
check-deps:
	@echo "🔍 Проверка зависимостей..."
	$(PYTHON) check_deps.py
test-detectors:
	@echo "🔍 Быстрый тест детекторов..."
	@set PYTHONIOENCODING=utf-8 && $(PYTHON) -c "\
import asyncio; \
from src.domain.service.detector.ensemble import EnsembleDetector; \
from src.domain.entity.message import Message; \
async def test(): \
    detector = EnsembleDetector({'spam_threshold': 0.6, 'heuristic': {'spam_threshold': 0.6}}); \
    msg = Message(user_id=1, chat_id=1, text='🔥🔥🔥 Заработок! Детали в ЛС!'); \
    result = await detector.detect(msg, {}); \
    print(f'Тест спам-детекции: {\"СПАМ\" if result.is_spam else \"НЕ СПАМ\"} (confidence: {result.overall_confidence:.2f})'); \
asyncio.run(test())"

# Docker команды
docker-build:
	@echo "🐳 Сборка Docker образа..."
	docker build -t antispam-bot:latest .

docker-up:
	@echo "🐳 Запуск через Docker Compose..."
	$(DOCKER_COMPOSE) up -d
	@echo "✅ Контейнеры запущены"
	@echo "📚 API docs: http://localhost:8080/docs"

docker-down:
	@echo "🐳 Остановка Docker Compose..."
	$(DOCKER_COMPOSE) down

docker-logs:
	@echo "📋 Логи контейнеров..."
	$(DOCKER_COMPOSE) logs -f

# Очистка
clean:
	@echo "🧹 Очистка временных файлов..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name "*.log" -delete 2>/dev/null || true
	@echo "✅ Очистка завершена"

clean-cache:
	@echo "🧹 Очистка кэша Python..."
	$(PIP) cache purge
	@echo "✅ Кэш очищен"

# Проверка статуса
status:
	@echo "📊 Статус системы:"
	@echo ""
	@echo "🔍 Проверка конфигурации:"
	@if [ -f $(ENV_FILE) ]; then \
		echo "  ✅ .env файл найден"; \
	else \
		echo "  ❌ .env файл не найден"; \
	fi
	@echo ""
	@echo "📦 Проверка зависимостей:"
	@$(PYTHON) -c "import aiogram, fastapi, asyncpg; print('  ✅ Основные зависимости установлены')" 2>/dev/null || echo "  ❌ Отсутствуют зависимости"
	@echo ""
	@echo "🐳 Docker статус:"
	@docker --version 2>/dev/null | sed 's/^/  ✅ /' || echo "  ❌ Docker не установлен"
	@$(DOCKER_COMPOSE) --version 2>/dev/null | sed 's/^/  ✅ /' || echo "  ❌ Docker Compose не установлен"

# Быстрая установка для нового проекта
quick-setup: setup-env install setup-db
	@echo "🎉 Быстрая настройка завершена!"
	@echo ""
	@echo "📝 Следующие шаги:"
	@echo "  1. Отредактируйте .env файл с вашими настройками"
	@echo "  2. Запустите: make test-deployment"
	@echo "  3. Если тесты прошли, запустите: make run-both"

# Разработка - запуск с автообновлением
dev:
	@echo "🔧 Режим разработки..."
	@echo "  Файлы будут отслеживаться на изменения"
	$(PYTHON) -m uvicorn src.delivery.http.app:create_app --reload --host 0.0.0.0 --port 8080

# Производственный деплой
deploy-prod:
	@echo "🚀 Production деплой..."
	@echo "⚠️  Убедитесь что:"
	@echo "  - .env настроен для production"
	@echo "  - База данных доступна"
	@echo "  - Все секреты настроены"
	@read -p "Продолжить? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	make docker-build
	ENVIRONMENT=production $(DOCKER_COMPOSE) -f docker-compose.yml up -d

# Бэкап базы данных (для production)
backup-db:
	@echo "💾 Создание бэкапа базы данных..."
	@timestamp=$$(date +%Y%m%d_%H%M%S); \
	docker exec $$(docker-compose ps -q postgres) pg_dump -U antispam antispam_db > "backup_$$timestamp.sql"; \
	echo "✅ Бэкап создан: backup_$$timestamp.sql"