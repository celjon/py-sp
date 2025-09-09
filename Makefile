# AntiSpam Bot v2.0 - Production-Ready Makefile
# Modern Architecture: CAS + RUSpam + OpenAI (NO heuristics and ML)

.PHONY: help install dev-install test clean run-telegram run-http run-both \
        test-deployment test-http-api docker-build docker-up docker-down \
        migrate db-reset lint format type-check security-check \
        prod-deploy staging-deploy backup-db restore-db \
        monitoring setup-monitoring health-check performance-test \
        generate-api-key validate-config quick-start

# === VARIABLES ===
PYTHON = python3
PIP = pip3
ENV_FILE = .env
DOCKER_COMPOSE = docker-compose
DOCKER_COMPOSE_PROD = docker-compose -f docker-compose.prod.yml
PYTHONIOENCODING = utf-8

# Colors for output
RED = \033[31m
GREEN = \033[32m
YELLOW = \033[33m
BLUE = \033[34m
MAGENTA = \033[35m
CYAN = \033[36m
WHITE = \033[37m
RESET = \033[0m

# === HELP ===
help:
	@echo "$(CYAN)======================================================"
	@echo "AntiSpam Bot v2.0 - Production-Ready Commands"
	@echo "Modern Architecture: CAS + RUSpam + OpenAI"
	@echo "======================================================$(RESET)"
	@echo ""
	@echo "$(GREEN)QUICK START:$(RESET)"
	@echo "  make quick-start       - Complete setup in one command"
	@echo "  make dev-setup         - Setup for development"
	@echo "  make prod-setup        - Setup for production"
	@echo ""
	@echo "$(GREEN)DEVELOPMENT:$(RESET)"
	@echo "  make install           - Install dependencies"
	@echo "  make dev-install       - Install dev dependencies"
	@echo "  make run-dev           - Run in development mode"
	@echo "  make run-telegram      - Run Telegram bot only"
	@echo "  make run-http          - Run HTTP API only"
	@echo "  make run-both          - Run both services"
	@echo ""
	@echo "$(GREEN)TESTING:$(RESET)"
	@echo "  make test              - Run all tests"
	@echo "  make test-unit         - Run unit tests"
	@echo "  make test-integration  - Run integration tests"
	@echo "  make test-e2e          - Run end-to-end tests"
	@echo "  make test-coverage     - Run tests with coverage"
	@echo "  make test-deployment   - Test deployment readiness"
	@echo "  make test-http-api     - Test HTTP API endpoints"
	@echo "  make performance-test  - Run performance tests"
	@echo ""
	@echo "$(GREEN)CODE QUALITY:$(RESET)"
	@echo "  make lint              - Check code style"
	@echo "  make format            - Format code"
	@echo "  make type-check        - Check types with mypy"
	@echo "  make security-check    - Security vulnerability scan"
	@echo "  make audit             - Full code audit"
	@echo ""
	@echo "$(GREEN)DATABASE:$(RESET)"
	@echo "  make migrate           - Apply database migrations"
	@echo "  make migrate-create    - Create new migration"
	@echo "  make db-reset          - Reset database"
	@echo "  make db-seed           - Seed database with test data"
	@echo "  make backup-db         - Backup database"
	@echo "  make restore-db        - Restore database from backup"
	@echo ""
	@echo "$(GREEN)DOCKER:$(RESET)"
	@echo "  make docker-build      - Build Docker images"
	@echo "  make docker-up         - Start via Docker Compose"
	@echo "  make docker-down       - Stop Docker Compose"
	@echo "  make docker-logs       - View container logs"
	@echo "  make docker-shell      - Shell into main container"
	@echo ""
	@echo "$(GREEN)PRODUCTION:$(RESET)"
	@echo "  make prod-deploy       - Deploy to production"
	@echo "  make staging-deploy    - Deploy to staging"
	@echo "  make prod-validate     - Validate production config"
	@echo "  make prod-backup       - Create production backup"
	@echo "  make prod-rollback     - Rollback production deployment"
	@echo ""
	@echo "$(GREEN)MONITORING:$(RESET)"
	@echo "  make setup-monitoring  - Setup Prometheus + Grafana"
	@echo "  make health-check      - Full system health check"
	@echo "  make metrics           - View current metrics"
	@echo "  make logs              - View application logs"
	@echo "  make alerts            - Check active alerts"
	@echo ""
	@echo "$(GREEN)UTILITIES:$(RESET)"
	@echo "  make generate-api-key  - Generate new API key"
	@echo "  make validate-config   - Validate configuration"
	@echo "  make clean             - Clean temporary files"
	@echo "  make clean-all         - Deep clean (including caches)"
	@echo "  make show-architecture - Display system architecture"

# === QUICK START ===
quick-start: check-requirements setup-env install migrate docker-build test-deployment
	@echo "$(GREEN)✅ Quick start completed!$(RESET)"
	@echo "$(CYAN)🚀 System is ready. Run: make run-both$(RESET)"

dev-setup: check-requirements setup-env dev-install migrate db-seed
	@echo "$(GREEN)✅ Development setup completed!$(RESET)"

prod-setup: check-requirements validate-config install migrate prod-validate
	@echo "$(GREEN)✅ Production setup completed!$(RESET)"

# === REQUIREMENTS CHECK ===
check-requirements:
	@echo "$(BLUE)🔍 Checking requirements...$(RESET)"
	@command -v python3 >/dev/null 2>&1 || { echo "$(RED)❌ Python 3.8+ required$(RESET)"; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo "$(RED)❌ Docker required$(RESET)"; exit 1; }
	@command -v docker-compose >/dev/null 2>&1 || { echo "$(RED)❌ Docker Compose required$(RESET)"; exit 1; }
	@$(PYTHON) -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" || { echo "$(RED)❌ Python 3.8+ required$(RESET)"; exit 1; }
	@echo "$(GREEN)✅ All requirements satisfied$(RESET)"

# === ENVIRONMENT SETUP ===
setup-env:
	@echo "$(BLUE)📝 Setting up environment...$(RESET)"
	@if [ ! -f $(ENV_FILE) ]; then \
		echo "$(YELLOW)Creating .env file...$(RESET)"; \
		cp .env.example $(ENV_FILE); \
		echo "$(GREEN)✅ .env file created$(RESET)"; \
		echo "$(YELLOW)⚠️  Please edit .env with your settings$(RESET)"; \
	else \
		echo "$(GREEN)✅ .env file already exists$(RESET)"; \
	fi

validate-config:
	@echo "$(BLUE)🔧 Validating configuration...$(RESET)"
	@export PYTHONIOENCODING=utf-8 && $(PYTHON) -c "\
import sys; sys.path.insert(0, '.'); \
from src.config.dependencies import validate_production_config; \
from src.config.config import load_config; \
try: \
    config = load_config(); \
    validate_production_config(config); \
    print('$(GREEN)✅ Configuration is valid$(RESET)'); \
except Exception as e: \
    print(f'$(RED)❌ Configuration error: {e}$(RESET)'); \
    sys.exit(1)"

# === INSTALLATION ===
install:
	@echo "$(BLUE)📦 Installing dependencies...$(RESET)"
	$(PIP) install -r requirements.txt
	@echo "$(GREEN)✅ Dependencies installed$(RESET)"

dev-install:
	@echo "$(BLUE)📦 Installing development dependencies...$(RESET)"
	$(PIP) install -r requirements-dev.txt
	@echo "$(GREEN)✅ Development dependencies installed$(RESET)"

prod-install:
	@echo "$(BLUE)📦 Installing production dependencies...$(RESET)"
	$(PIP) install -r requirements-prod.txt --no-deps
	@echo "$(GREEN)✅ Production dependencies installed$(RESET)"

# === RUNNING ===
run-dev:
	@echo "$(BLUE)🔧 Starting in development mode...$(RESET)"
	ENVIRONMENT=development DEBUG=true $(PYTHON) -m src.main

run-telegram:
	@echo "$(BLUE)🤖 Starting Telegram bot...$(RESET)"
	RUN_MODE=telegram $(PYTHON) -m src.main

run-http:
	@echo "$(BLUE)🌐 Starting HTTP API...$(RESET)"
	RUN_MODE=http $(PYTHON) -m src.main

run-both:
	@echo "$(BLUE)🚀 Starting Telegram + HTTP...$(RESET)"
	RUN_MODE=both $(PYTHON) -m src.main

run-prod:
	@echo "$(BLUE)🏭 Starting in production mode...$(RESET)"
	ENVIRONMENT=production $(PYTHON) -m src.main

# === TESTING ===
test:
	@echo "$(BLUE)🧪 Running all tests...$(RESET)"
	pytest -v --tb=short

test-unit:
	@echo "$(BLUE)🧪 Running unit tests...$(RESET)"
	pytest tests/unit/ -v

test-integration:
	@echo "$(BLUE)🧪 Running integration tests...$(RESET)"
	pytest tests/integration/ -v

test-e2e:
	@echo "$(BLUE)🧪 Running end-to-end tests...$(RESET)"
	pytest tests/e2e/ -v

test-coverage:
	@echo "$(BLUE)🧪 Running tests with coverage...$(RESET)"
	pytest --cov=src --cov-report=html --cov-report=term-missing -v
	@echo "$(GREEN)📊 Coverage report: htmlcov/index.html$(RESET)"

test-deployment:
	@echo "$(BLUE)🧪 Testing deployment readiness...$(RESET)"
	@export PYTHONIOENCODING=utf-8 && $(PYTHON) test_deployment.py

test-http-api:
	@echo "$(BLUE)🧪 Testing HTTP API...$(RESET)"
	@export PYTHONIOENCODING=utf-8 && $(PYTHON) test_http_api.py

performance-test:
	@echo "$(BLUE)⚡ Running performance tests...$(RESET)"
	locust -f tests/performance/locustfile.py --headless -u 50 -r 10 -t 60s --host=http://localhost:8080

# === CODE QUALITY ===
lint:
	@echo "$(BLUE)🔍 Checking code style...$(RESET)"
	flake8 src/ tests/
	pylint src/

format:
	@echo "$(BLUE)✨ Formatting code...$(RESET)"
	black src/ tests/
	isort src/ tests/

type-check:
	@echo "$(BLUE)🔍 Checking types...$(RESET)"
	mypy src/

security-check:
	@echo "$(BLUE)🔒 Security vulnerability scan...$(RESET)"
	bandit -r src/
	safety check

audit: lint type-check security-check test-coverage
	@echo "$(GREEN)✅ Full code audit completed$(RESET)"

# === DATABASE ===
migrate:
	@echo "$(BLUE)🗄️  Running database migrations...$(RESET)"
	alembic upgrade head
	@echo "$(GREEN)✅ Migrations applied$(RESET)"

migrate-create:
	@echo "$(BLUE)🗄️  Creating new migration...$(RESET)"
	@read -p "Migration name: " name; \
	alembic revision --autogenerate -m "$$name"

db-reset:
	@echo "$(YELLOW)⚠️  Resetting database...$(RESET)"
	@read -p "Are you sure? This will delete all data! (y/N): " confirm; \
	if [ "$$confirm" = "y" ]; then \
		alembic downgrade base; \
		alembic upgrade head; \
		echo "$(GREEN)✅ Database reset$(RESET)"; \
	else \
		echo "$(BLUE)Cancelled$(RESET)"; \
	fi

db-seed:
	@echo "$(BLUE)🌱 Seeding database...$(RESET)"
	@export PYTHONIOENCODING=utf-8 && $(PYTHON) -c "\
import asyncio; \
import sys; sys.path.insert(0, '.'); \
from src.config.dependencies import setup_production_services; \
from src.config.config import load_config; \
async def seed(): \
    config = load_config(); \
    services = await setup_production_services(config); \
    print('$(GREEN)✅ Database seeded$(RESET)'); \
asyncio.run(seed())"

backup-db:
	@echo "$(BLUE)💾 Creating database backup...$(RESET)"
	@timestamp=$$(date +%Y%m%d_%H%M%S); \
	if [ -n "$$DATABASE_URL" ]; then \
		pg_dump "$$DATABASE_URL" > "backup_$$timestamp.sql"; \
		echo "$(GREEN)✅ Backup created: backup_$$timestamp.sql$(RESET)"; \
	else \
		echo "$(RED)❌ DATABASE_URL not set$(RESET)"; \
	fi

restore-db:
	@echo "$(YELLOW)⚠️  Restoring database...$(RESET)"
	@ls backup_*.sql 2>/dev/null || { echo "$(RED)❌ No backup files found$(RESET)"; exit 1; }
	@echo "Available backups:"
	@ls -la backup_*.sql
	@read -p "Enter backup filename: " backup; \
	read -p "Are you sure? This will overwrite current data! (y/N): " confirm; \
	if [ "$$confirm" = "y" ] && [ -f "$$backup" ]; then \
		psql "$$DATABASE_URL" < "$$backup"; \
		echo "$(GREEN)✅ Database restored from $$backup$(RESET)"; \
	else \
		echo "$(BLUE)Cancelled or file not found$(RESET)"; \
	fi

# === DOCKER ===
docker-build:
	@echo "$(BLUE)🐳 Building Docker images...$(RESET)"
	docker build -t antispam-bot:latest .
	@echo "$(GREEN)✅ Docker image built$(RESET)"

docker-up:
	@echo "$(BLUE)🐳 Starting Docker Compose...$(RESET)"
	$(DOCKER_COMPOSE) up -d
	@echo "$(GREEN)✅ Containers started$(RESET)"
	@echo "$(CYAN)📚 API docs: http://localhost:8080/docs$(RESET)"
	@echo "$(CYAN)📊 Metrics: http://localhost:9090/metrics$(RESET)"

docker-down:
	@echo "$(BLUE)🐳 Stopping Docker Compose...$(RESET)"
	$(DOCKER_COMPOSE) down
	@echo "$(GREEN)✅ Containers stopped$(RESET)"

docker-logs:
	@echo "$(BLUE)📋 Container logs...$(RESET)"
	$(DOCKER_COMPOSE) logs -f --tail=100

docker-shell:
	@echo "$(BLUE)🐚 Opening shell in main container...$(RESET)"
	$(DOCKER_COMPOSE) exec antispam-api bash

docker-clean:
	@echo "$(BLUE)🧹 Cleaning Docker resources...$(RESET)"
	docker system prune -f
	docker volume prune -f

# === PRODUCTION DEPLOYMENT ===
prod-deploy: prod-validate
	@echo "$(BLUE)🚀 Deploying to production...$(RESET)"
	@read -p "Deploy to production? (y/N): " confirm; \
	if [ "$$confirm" = "y" ]; then \
		echo "$(BLUE)Building production image...$(RESET)"; \
		docker build -f Dockerfile.prod -t antispam-bot:prod .; \
		echo "$(BLUE)Starting production deployment...$(RESET)"; \
		$(DOCKER_COMPOSE_PROD) up -d; \
		echo "$(GREEN)✅ Production deployment completed$(RESET)"; \
	else \
		echo "$(BLUE)Cancelled$(RESET)"; \
	fi

staging-deploy:
	@echo "$(BLUE)🚀 Deploying to staging...$(RESET)"
	ENVIRONMENT=staging $(DOCKER_COMPOSE) -f docker-compose.staging.yml up -d
	@echo "$(GREEN)✅ Staging deployment completed$(RESET)"

prod-validate:
	@echo "$(BLUE)🔍 Validating production readiness...$(RESET)"
	@$(MAKE) validate-config
	@$(MAKE) test-deployment
	@$(MAKE) security-check
	@echo "$(GREEN)✅ Production validation passed$(RESET)"

prod-backup:
	@echo "$(BLUE)💾 Creating production backup...$(RESET)"
	@timestamp=$$(date +%Y%m%d_%H%M%S); \
	kubectl exec -n production deployment/antispam-api -- pg_dump "$$DATABASE_URL" > "prod_backup_$$timestamp.sql" 2>/dev/null || \
	docker exec $$(docker ps -q -f name=antispam-api) pg_dump "$$DATABASE_URL" > "prod_backup_$$timestamp.sql"; \
	echo "$(GREEN)✅ Production backup: prod_backup_$$timestamp.sql$(RESET)"

prod-rollback:
	@echo "$(YELLOW)⚠️  Rolling back production...$(RESET)"
	@read -p "Rollback production? (y/N): " confirm; \
	if [ "$$confirm" = "y" ]; then \
		$(DOCKER_COMPOSE_PROD) down; \
		docker run --rm antispam-bot:previous; \
		echo "$(GREEN)✅ Rollback completed$(RESET)"; \
	fi

# === MONITORING ===
setup-monitoring:
	@echo "$(BLUE)📊 Setting up monitoring...$(RESET)"
	docker-compose -f docker-compose.monitoring.yml up -d
	@echo "$(GREEN)✅ Monitoring stack started$(RESET)"
	@echo "$(CYAN)📊 Prometheus: http://localhost:9091$(RESET)"
	@echo "$(CYAN)📈 Grafana: http://localhost:3000 (admin/admin)$(RESET)"

health-check:
	@echo "$(BLUE)🏥 Running health check...$(RESET)"
	@curl -s http://localhost:8080/health | python3 -m json.tool || echo "$(RED)❌ Health check failed$(RESET)"

metrics:
	@echo "$(BLUE)📊 Current metrics:$(RESET)"
	@curl -s http://localhost:9090/metrics | head -20

logs:
	@echo "$(BLUE)📋 Application logs:$(RESET)"
	@tail -f logs/antispam-bot.log 2>/dev/null || echo "$(YELLOW)No log file found$(RESET)"

alerts:
	@echo "$(BLUE)🚨 Active alerts:$(RESET)"
	@curl -s http://localhost:9093/api/v1/alerts | python3 -m json.tool 2>/dev/null || echo "$(YELLOW)AlertManager not available$(RESET)"

# === UTILITIES ===
generate-api-key:
	@echo "$(BLUE)🔑 Generating API key...$(RESET)"
	@export PYTHONIOENCODING=utf-8 && $(PYTHON) -c "\
import sys; sys.path.insert(0, '.'); \
from src.domain.entity.api_key import ApiKey; \
key = ApiKey.generate_key(); \
print(f'$(GREEN)New API key: {key}$(RESET)'); \
print(f'$(YELLOW)Hash: {ApiKey.hash_key(key)}$(RESET)')"

show-architecture:
	@echo "$(CYAN)======================================================"
	@echo "ANTISPAM BOT v2.0 - MODERN ARCHITECTURE"
	@echo "======================================================"
	@echo ""
	@echo "$(GREEN)🎯 SPAM DETECTION LAYERS:$(RESET)"
	@echo "  1. $(BLUE)CAS$(RESET)     - Banned users database (100ms)"
	@echo "  2. $(BLUE)RUSpam$(RESET)  - BERT model for Russian (300ms)"
	@echo "  3. $(BLUE)OpenAI$(RESET)  - GPT-4 contextual analysis (1.5s)"
	@echo ""
	@echo "$(RED)❌ REMOVED (v1.x legacy):$(RESET)"
	@echo "  - Heuristic rules (emoji count, CAPS)"
	@echo "  - ML classifiers (scikit-learn, pandas)"
	@echo ""
	@echo "$(GREEN)✨ NEW FEATURES (v2.0):$(RESET)"
	@echo "  - JWT authentication with refresh tokens"
	@echo "  - API keys with crypto-strong hashing"
	@echo "  - Rate limiting with sliding window"
	@echo "  - Real-time usage analytics"
	@echo "  - Prometheus metrics (50+ metrics)"
	@echo "  - Circuit breaker pattern"
	@echo "  - Graceful error handling"
	@echo "  - Python SDK"
	@echo ""
	@echo "$(GREEN)🏗️ CLEAN ARCHITECTURE:$(RESET)"
	@echo "  Domain   → Business logic (center)"
	@echo "  Adapter  → External integrations"
	@echo "  Delivery → HTTP API & Telegram"
	@echo "  Lib      → Infrastructure"
	@echo "======================================================"

clean:
	@echo "$(BLUE)🧹 Cleaning temporary files...$(RESET)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache/ .coverage htmlcov/ .mypy_cache/
	@echo "$(GREEN)✅ Cleanup completed$(RESET)"

clean-all: clean docker-clean
	@echo "$(BLUE)🧹 Deep cleaning...$(RESET)"
	rm -rf node_modules/ .venv/ dist/ build/
	docker system prune -a -f --volumes
	@echo "$(GREEN)✅ Deep cleanup completed$(RESET)"

# === SPECIAL TARGETS ===
show-status:
	@echo "$(CYAN)======================================================"
	@echo "SYSTEM STATUS"
	@echo "======================================================"
	@echo ""
	@echo "$(GREEN)📊 Services:$(RESET)"
	@docker ps --filter "name=antispam" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "No containers running"
	@echo ""
	@echo "$(GREEN)💾 Database:$(RESET)"
	@pg_isready -d "$$DATABASE_URL" 2>/dev/null && echo "✅ Connected" || echo "❌ Not connected"
	@echo ""
	@echo "$(GREEN)🔧 Configuration:$(RESET)"
	@[ -f .env ] && echo "✅ .env exists" || echo "❌ .env missing"
	@echo ""
	@echo "$(GREEN)🧪 Last test results:$(RESET)"
	@[ -f .last_test_result ] && cat .last_test_result || echo "No test results"

monitor-performance:
	@echo "$(BLUE)⚡ Monitoring performance...$(RESET)"
	@echo "Press Ctrl+C to stop"
	@while true; do \
		clear; \
		echo "$(CYAN)=== PERFORMANCE MONITOR ===$(RESET)"; \
		echo "Time: $$(date)"; \
		echo ""; \
		curl -s http://localhost:8080/health | python3 -c "import sys,json;data=json.load(sys.stdin);print(f'Status: {data.get(\"status\",\"unknown\")}');print(f'Components: {len(data.get(\"components\",{}))}')"; \
		echo ""; \
		curl -s http://localhost:9090/metrics | grep -E "(antispam_http_requests_total|antispam_http_request_duration)" | tail -5; \
		echo ""; \
		echo "Press Ctrl+C to stop"; \
		sleep 5; \
	done

# === CI/CD HELPERS ===
ci-install:
	@echo "$(BLUE)🤖 CI: Installing dependencies...$(RESET)"
	pip install --upgrade pip
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

ci-test:
	@echo "$(BLUE)🤖 CI: Running tests...$(RESET)"
	pytest --cov=src --cov-report=xml --cov-report=term -v
	@echo $? > .last_test_result

ci-build:
	@echo "$(BLUE)🤖 CI: Building image...$(RESET)"
	docker build -t antispam-bot:ci .

ci-deploy:
	@echo "$(BLUE)🤖 CI: Deploying...$(RESET)"
	@if [ "$$CI_COMMIT_REF_NAME" = "main" ]; then \
		echo "Deploying to production..."; \
		$(MAKE) prod-deploy; \
	elif [ "$$CI_COMMIT_REF_NAME" = "staging" ]; then \
		echo "Deploying to staging..."; \
		$(MAKE) staging-deploy; \
	else \
		echo "Branch $$CI_COMMIT_REF_NAME - no deployment"; \
	fi

# Default target
.DEFAULT_GOAL := help