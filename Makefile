# AntiSpam Bot Makefile - Production Ready
# Modern Architecture: CAS + RUSpam + OpenAI (NO heuristics and ML)

.PHONY: help install test clean run-telegram run-http run-both test-deployment test-http-api

# Variables
PYTHON = python
PIP = pip
ENV_FILE = .env
DOCKER_COMPOSE = docker-compose

# Help
help:
	@echo "===================================================="
	@echo "AntiSpam Bot v2.0 - Modern Architecture"
	@echo "CAS + RUSpam + OpenAI (NO outdated heuristics and ML)"
	@echo "===================================================="
	@echo ""
	@echo "SETUP AND CONFIGURATION:"
	@echo "  make install          - Install dependencies"
	@echo "  make setup-env        - Create .env file from example"
	@echo "  make setup-db         - Setup database"
	@echo ""
	@echo "RUNNING:"
	@echo "  make run-telegram     - Run Telegram bot only"
	@echo "  make run-http         - Run HTTP API only"
	@echo "  make run-both         - Run Telegram + HTTP"
	@echo ""
	@echo "TESTING:"
	@echo "  make quick-test       - Quick components test"
	@echo "  make test-deployment  - Full deployment test"
	@echo "  make test-http-api    - Test HTTP API"
	@echo "  make test-detectors   - Test spam detectors"
	@echo ""
	@echo "DOCKER:"
	@echo "  make docker-build     - Build Docker image"
	@echo "  make docker-up        - Start via Docker Compose"
	@echo "  make docker-down      - Stop Docker Compose"
	@echo ""
	@echo "CLEANUP:"
	@echo "  make clean            - Clean temporary files"
	@echo "  make clean-cache      - Clean Python cache"

# Install dependencies
install:
	@echo "Installing modern dependencies..."
	@echo "Outdated ML libraries excluded"
	$(PIP) install -r requirements.txt
	@echo "Dependencies installed successfully"

# Create .env file
setup-env:
	@if [ ! -f $(ENV_FILE) ]; then \
		echo "Creating .env file..."; \
		cp .env.example $(ENV_FILE); \
		echo ".env file created from .env.example"; \
		echo "WARNING: Edit .env file with your settings"; \
	else \
		echo "INFO: .env file already exists"; \
	fi

# Setup database
setup-db:
	@echo "Setting up database..."
	@if [ -f alembic.ini ]; then \
		echo "Running migrations..."; \
		alembic upgrade head; \
		echo "Migrations completed"; \
	else \
		echo "ERROR: alembic.ini not found"; \
	fi

# Quick test of main components
quick-test:
	@echo "Quick components test..."
	@set PYTHONIOENCODING=utf-8 && $(PYTHON) quick_test.py

# Run Telegram bot only
run-telegram:
	@echo "Starting Telegram bot..."
	RUN_MODE=telegram $(PYTHON) src/main.py

# Run HTTP API only
run-http:
	@echo "Starting HTTP API..."
	RUN_MODE=http $(PYTHON) src/main.py

# Run both services
run-both:
	@echo "Starting Telegram + HTTP..."
	RUN_MODE=both $(PYTHON) src/main.py

# Full deployment test
test-deployment:
	@echo "Full deployment test..."
	@set PYTHONIOENCODING=utf-8 && $(PYTHON) test_deployment.py

# Test HTTP API
test-http-api:
	@echo "Testing HTTP API..."
	@set PYTHONIOENCODING=utf-8 && $(PYTHON) test_http_api.py

# Check dependencies
check-deps:
	@echo "Checking dependencies..."
	$(PYTHON) -c "import sys; sys.path.insert(0, '.'); from src.main import check_environment; check_environment()"

# Test modern detectors (NO heuristics and ML)
test-detectors:
	@echo "Testing modern detectors..."
	@set PYTHONIOENCODING=utf-8 && $(PYTHON) -c "\
import asyncio; \
import sys; \
sys.path.insert(0, '.'); \
from src.domain.service.detector.ensemble import EnsembleDetector; \
from src.domain.entity.message import Message; \
async def test(): \
    config = {'spam_threshold': 0.6, 'use_ruspam': False, 'use_openai_fallback': False}; \
    detector = EnsembleDetector(config); \
    msg = Message(user_id=1, chat_id=1, text='URGENT! Free money! Contact us!'); \
    result = await detector.detect(msg, {}); \
    print(f'Modern detection: {\"SPAM\" if result.is_spam else \"NOT SPAM\"} (confidence: {result.overall_confidence:.2f})'); \
    health = await detector.health_check(); \
    print(f'Architecture: {health.get(\"architecture\", \"unknown\")}'); \
    print(f'Status: {health[\"status\"]}'); \
asyncio.run(test())"

# Docker commands
docker-build:
	@echo "Building Docker image..."
	docker build -t antispam-bot:latest .

docker-up:
	@echo "Starting via Docker Compose..."
	$(DOCKER_COMPOSE) up -d
	@echo "Containers started successfully"
	@echo "API docs: http://localhost:8080/docs"

docker-down:
	@echo "Stopping Docker Compose..."
	$(DOCKER_COMPOSE) down

docker-logs:
	@echo "Container logs..."
	$(DOCKER_COMPOSE) logs -f

# Cleanup
clean:
	@echo "Cleaning temporary files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name "*.log" -delete 2>/dev/null || true
	@echo "Cleanup completed"

clean-cache:
	@echo "Cleaning Python cache..."
	$(PIP) cache purge
	@echo "Cache cleaned"

# Check status
status:
	@echo "Modern system status:"
	@echo ""
	@echo "Configuration check:"
	@if [ -f $(ENV_FILE) ]; then \
		echo "  OK: .env file found"; \
	else \
		echo "  ERROR: .env file not found"; \
	fi
	@echo ""
	@echo "Modern dependencies check:"
	@$(PYTHON) -c "import aiogram, fastapi, asyncpg; print('  OK: Core dependencies installed')" 2>/dev/null || echo "  ERROR: Missing dependencies"
	@$(PYTHON) -c "import torch, transformers; print('  OK: RUSpam BERT dependencies')" 2>/dev/null || echo "  WARNING: RUSpam BERT unavailable"
	@$(PYTHON) -c "import openai; print('  OK: OpenAI client')" 2>/dev/null || echo "  WARNING: OpenAI unavailable"
	@echo ""
	@echo "Docker status:"
	@docker --version 2>/dev/null | sed 's/^/  OK: /' || echo "  ERROR: Docker not installed"
	@$(DOCKER_COMPOSE) --version 2>/dev/null | sed 's/^/  OK: /' || echo "  ERROR: Docker Compose not installed"

# Quick setup for new project
quick-setup: setup-env install quick-test
	@echo "=================================================="
	@echo "Quick setup completed!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env file with your settings"
	@echo "  2. Run: make test-deployment"
	@echo "  3. If tests pass, run: make run-both"
	@echo "=================================================="

# Development mode with auto-reload
dev:
	@echo "Development mode..."
	@echo "Files will be watched for changes"
	$(PYTHON) -m uvicorn src.delivery.http.app:create_app --reload --host 0.0.0.0 --port 8080

# Production deployment
deploy-prod:
	@echo "Production deployment..."
	@echo "WARNING: Make sure that:"
	@echo "  - .env configured for production"
	@echo "  - Database is available"
	@echo "  - All secrets are configured"
	@echo "  - Using modern architecture (CAS + RUSpam + OpenAI)"
	@read -p "Continue? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	make docker-build
	ENVIRONMENT=production $(DOCKER_COMPOSE) -f docker-compose.yml up -d

# Database backup (for production)
backup-db:
	@echo "Creating database backup..."
	@timestamp=$$(date +%Y%m%d_%H%M%S); \
	docker exec $$(docker-compose ps -q postgres) pg_dump -U antispam antispam_db > "backup_$$timestamp.sql"; \
	echo "Backup created: backup_$$timestamp.sql"

# Full CI/CD test
ci-test: install quick-test test-deployment
	@echo "CI/CD testing completed"

# Show architecture
show-architecture:
	@echo "=================================================="
	@echo "MODERN ANTI-SPAM BOT v2.0 ARCHITECTURE"
	@echo "=================================================="
	@echo ""
	@echo "Spam Detectors:"
	@echo "  1. CAS - banned users database"
	@echo "  2. RUSpam - BERT model for Russian language"
	@echo "  3. OpenAI - LLM analysis for complex cases"
	@echo ""
	@echo "REMOVED outdated components:"
	@echo "  - Heuristic rules (emoji count, CAPS)"
	@echo "  - ML classifiers (scikit-learn, pandas)"
	@echo ""
	@echo "ADVANTAGES of new architecture:"
	@echo "  - High accuracy without false positives"
	@echo "  - Adaptivity to new spam types"
	@echo "  - Contextual analysis via LLM"
	@echo "  - 200MB+ dependencies reduction"
	@echo "=================================================="

# Show quick start commands
quick-start:
	@echo "=================================================="
	@echo "QUICK START GUIDE:"
	@echo ""
	@echo "1. Initial setup:"
	@echo "   make quick-setup"
	@echo ""
	@echo "2. Edit configuration:"
	@echo "   notepad .env"
	@echo ""
	@echo "3. Test system:"
	@echo "   make test-deployment"
	@echo ""
	@echo "4. Run system:"
	@echo "   make run-both"
	@echo ""
	@echo "5. Test API:"
	@echo "   make test-http-api"
	@echo "=================================================="