# src/delivery/http/schema/openapi_generator.py
"""
Production-ready OpenAPI Schema Generator
Автоматическая генерация детальной документации для Swagger UI
"""

from typing import Dict, Any, List
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def generate_production_openapi_schema(app: FastAPI) -> Dict[str, Any]:
    """
    Генерирует production-ready OpenAPI схему с детальной документацией

    Args:
        app: FastAPI приложение

    Returns:
        Полная OpenAPI схема
    """

    if app.openapi_schema:
        return app.openapi_schema

    # Базовая схема
    openapi_schema = get_openapi(
        title="AntiSpam Detection API",
        version="2.0.0",
        description=_get_api_description(),
        routes=app.routes,
        servers=[
            {"url": "https://api.antispam.com", "description": "Production Server"},
            {"url": "https://staging.api.antispam.com", "description": "Staging Server"},
            {"url": "http://localhost:8080", "description": "Development Server"},
        ],
    )

    # Добавляем кастомизации
    _add_security_schemes(openapi_schema)
    _add_response_examples(openapi_schema)
    _add_error_schemas(openapi_schema)
    _add_rate_limiting_info(openapi_schema)
    _add_usage_examples(openapi_schema)
    _add_sdk_information(openapi_schema)

    # Кэшируем схему
    app.openapi_schema = openapi_schema
    return openapi_schema


def _get_api_description() -> str:
    """Возвращает детальное описание API"""
    return """
# 🛡️ AntiSpam Detection API v2.0

**Production-ready API для высокоточной детекции спама** с поддержкой русского и английского языков.

## 🚀 Основные возможности

- **Многослойная детекция**: CAS + RUSpam BERT + OpenAI GPT-4
- **Batch обработка**: до 100 сообщений за один запрос
- **Real-time аналитика**: детальная статистика использования
- **Гибкая аутентификация**: API ключи + JWT токены
- **Rate limiting**: настраиваемые лимиты по тарифным планам
- **High availability**: 99.9% uptime, <200ms response time

## 🎯 Архитектура детекции

1. **CAS Check** (100ms) - проверка базы забаненных пользователей
2. **RUSpam BERT** (300ms) - ML модель для русскоязычных текстов
3. **OpenAI Analysis** (1.5s) - контекстуальный анализ сложных случаев

## 📊 Тарифные планы

| План | Запросов/мин | Запросов/день | Цена |
|------|-------------|---------------|------|
| Free | 60 | 5,000 | Бесплатно |
| Basic | 120 | 10,000 | $9/мес |
| Pro | 300 | 50,000 | $49/мес |
| Enterprise | 1,000+ | 1,000,000+ | По запросу |

## 🔗 Полезные ссылки

- **Документация**: https://docs.antispam.com
- **Python SDK**: `pip install antispam-client`
- **JavaScript SDK**: `npm install @antispam/client`
- **Support**: support@antispam.com
- **Status Page**: https://status.antispam.com

## 🛠️ Быстрый старт

```bash
# 1. Получите API ключ
curl -X POST "https://api.antispam.com/api/v1/auth/keys" \\
  -u "admin:password" \\
  -H "Content-Type: application/json" \\
  -d '{"client_name": "My App", "contact_email": "dev@company.com"}'

# 2. Проверьте сообщение
curl -X POST "https://api.antispam.com/api/v1/detect" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Привет! Хочешь заработать?"}'
```
    """.strip()


def _add_security_schemes(openapi_schema: Dict[str, Any]) -> None:
    """Добавляет схемы безопасности"""
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}

    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API Key",
            "description": "API ключ в формате: `antispam_your_api_key_here`",
        },
        "JWTAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT токен, полученный через `/auth/token`",
        },
        "ApiKeyHeader": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API ключ в заголовке X-API-Key",
        },
        "BasicAuth": {
            "type": "http",
            "scheme": "basic",
            "description": "Basic Auth для админских endpoints",
        },
    }

    # Глобальная безопасность
    openapi_schema["security"] = [{"ApiKeyAuth": []}, {"JWTAuth": []}, {"ApiKeyHeader": []}]


def _add_response_examples(openapi_schema: Dict[str, Any]) -> None:
    """Добавляет примеры ответов"""

    # Схемы компонентов
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    if "schemas" not in openapi_schema["components"]:
        openapi_schema["components"]["schemas"] = {}

    # Примеры успешных ответов
    openapi_schema["components"]["schemas"]["SpamDetectionExample"] = {
        "type": "object",
        "example": {
            "is_spam": True,
            "confidence": 0.89,
            "primary_reason": "openai",
            "reasons": ["promotional_content", "urgent_language", "contact_request"],
            "recommended_action": "ban_and_delete",
            "notes": "Обнаружена реклама с призывом к контакту в ЛС",
            "processing_time_ms": 342.5,
            "detection_id": "det_1234567890abcdef",
            "api_version": "2.0",
        },
    }

    openapi_schema["components"]["schemas"]["CleanMessageExample"] = {
        "type": "object",
        "example": {
            "is_spam": False,
            "confidence": 0.15,
            "primary_reason": "openai_clean",
            "reasons": [],
            "recommended_action": "allow",
            "notes": "Сообщение выглядит безопасным",
            "processing_time_ms": 125.8,
            "detection_id": "det_9876543210fedcba",
            "api_version": "2.0",
        },
    }

    openapi_schema["components"]["schemas"]["UsageStatsExample"] = {
        "type": "object",
        "example": {
            "api_key_info": {
                "id": 42,
                "client_name": "My Awesome Bot",
                "plan": "basic",
                "status": "active",
            },
            "usage_stats": {
                "total_requests": 1250,
                "successful_requests": 1198,
                "error_requests": 52,
                "success_rate": 95.84,
                "spam_detected": 89,
                "clean_detected": 1109,
                "spam_detection_rate": 7.43,
                "avg_confidence": 0.752,
                "avg_processing_time_ms": 234.5,
            },
            "rate_limits": {
                "current": {"requests_per_minute": 120, "requests_per_day": 10000},
                "remaining": {"requests_per_minute": 85, "requests_per_day": 8750},
            },
        },
    }


def _add_error_schemas(openapi_schema: Dict[str, Any]) -> None:
    """Добавляет схемы ошибок"""

    openapi_schema["components"]["schemas"]["ErrorResponse"] = {
        "type": "object",
        "properties": {
            "error": {"type": "string", "description": "Описание ошибки"},
            "details": {"type": "string", "description": "Детальная информация об ошибке"},
            "error_code": {"type": "string", "description": "Код ошибки для программной обработки"},
            "timestamp": {"type": "number", "description": "Unix timestamp ошибки"},
            "request_id": {"type": "string", "description": "ID запроса для трейсинга"},
        },
        "required": ["error", "timestamp"],
    }

    openapi_schema["components"]["schemas"]["ValidationError"] = {
        "type": "object",
        "properties": {
            "error": {"type": "string", "example": "Validation failed"},
            "details": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"field": {"type": "string"}, "message": {"type": "string"}},
                },
                "example": [
                    {"field": "text", "message": "Text cannot be empty"},
                    {"field": "context.user_id", "message": "Must be positive integer"},
                ],
            },
        },
    }

    openapi_schema["components"]["schemas"]["RateLimitError"] = {
        "type": "object",
        "properties": {
            "error": {"type": "string", "example": "Rate limit exceeded"},
            "limit_type": {"type": "string", "example": "per_minute"},
            "retry_after_seconds": {"type": "integer", "example": 45},
            "reset_time": {
                "type": "string",
                "format": "date-time",
                "example": "2024-01-15T14:30:00Z",
            },
        },
    }


def _add_rate_limiting_info(openapi_schema: Dict[str, Any]) -> None:
    """Добавляет информацию о rate limiting"""

    # Добавляем в описание
    rate_limit_info = """

## 🚦 Rate Limiting

API использует rate limiting для обеспечения справедливого использования ресурсов.

### Заголовки Rate Limiting

Каждый ответ содержит заголовки:

- `X-RateLimit-Limit-Minute`: Лимит запросов в минуту
- `X-RateLimit-Remaining-Minute`: Оставшиеся запросы в текущей минуте  
- `X-RateLimit-Reset`: Unix timestamp сброса лимита
- `Retry-After`: Секунды до повторной попытки (при превышении лимита)

### Обработка ошибки 429

```python
import time
import requests

def make_request_with_retry(url, headers, data, max_retries=3):
    for attempt in range(max_retries):
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 60))
            print(f"Rate limited. Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            continue
            
        return response
    
    raise Exception("Max retries exceeded")
```

### Лимиты по планам

| План | Запросов/мин | Запросов/день | Burst |
|------|-------------|---------------|-------|
| Free | 60 | 5,000 | 10 |
| Basic | 120 | 10,000 | 20 |  
| Pro | 300 | 50,000 | 50 |
| Enterprise | 1,000+ | Без лимитов | 200 |

"""

    if "info" in openapi_schema:
        openapi_schema["info"]["description"] += rate_limit_info


def _add_usage_examples(openapi_schema: Dict[str, Any]) -> None:
    """Добавляет примеры использования"""

    usage_examples = """

## 🔧 Примеры использования

### Python

```python
import requests

# Настройка
API_KEY = "antispam_your_api_key_here"
BASE_URL = "https://api.antispam.com/api/v1"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Проверка одного сообщения
response = requests.post(
    f"{BASE_URL}/detect",
    headers=headers,
    json={
        "text": "Хочешь заработать? Пиши в ЛС!",
        "context": {
            "user_id": 12345,
            "is_new_user": True,
            "language_hint": "ru"
        }
    }
)

result = response.json()
print(f"Spam: {result['is_spam']}, Confidence: {result['confidence']}")

# Batch обработка
messages = [
    {"text": "Привет, как дела?"},
    {"text": "СРОЧНО! ЗАРАБОТАЙ МИЛЛИОН!"},
    {"text": "Спасибо за информацию"}
]

batch_response = requests.post(
    f"{BASE_URL}/detect/batch",
    headers=headers,
    json={"messages": messages}
)

batch_result = batch_response.json()
print(f"Обработано: {batch_result['summary']['total_messages']}")
print(f"Спам найден: {batch_result['summary']['spam_detected']}")
```

### JavaScript/Node.js

```javascript
const axios = require('axios');

const API_KEY = 'antispam_your_api_key_here';
const BASE_URL = 'https://api.antispam.com/api/v1';

const headers = {
    'Authorization': `Bearer ${API_KEY}`,
    'Content-Type': 'application/json'
};

// Проверка сообщения
async function checkSpam(text, context = {}) {
    try {
        const response = await axios.post(
            `${BASE_URL}/detect`,
            { text, context },
            { headers }
        );
        
        return response.data;
    } catch (error) {
        if (error.response?.status === 429) {
            const retryAfter = error.response.headers['retry-after'];
            console.log(`Rate limited. Retry after ${retryAfter} seconds`);
        }
        throw error;
    }
}

// Использование
checkSpam('Хочешь заработать быстрые деньги?')
    .then(result => {
        console.log(`Spam: ${result.is_spam}, Confidence: ${result.confidence}`);
    });
```

### cURL

```bash
# Простая проверка
curl -X POST "https://api.antispam.com/api/v1/detect" \\
  -H "Authorization: Bearer antispam_your_api_key_here" \\
  -H "Content-Type: application/json" \\
  -d '{
    "text": "Хочешь заработать? Пиши в ЛС!",
    "context": {"user_id": 12345, "is_new_user": true}
  }'

# Получение статистики
curl -X GET "https://api.antispam.com/api/v1/stats?hours=24" \\
  -H "Authorization: Bearer antispam_your_api_key_here"

# Health check
curl -X GET "https://api.antispam.com/api/v1/health"
```

"""

    if "info" in openapi_schema:
        openapi_schema["info"]["description"] += usage_examples


def _add_sdk_information(openapi_schema: Dict[str, Any]) -> None:
    """Добавляет информацию об SDK"""

    sdk_info = """

## 📦 Официальные SDK

### Python SDK

```bash
pip install antispam-client
```

```python
from antispam_client import AntiSpamClient

client = AntiSpamClient(api_key="your_api_key")

# Простая проверка
result = await client.detect("Хочешь заработать?")
print(result.is_spam)  # True/False

# Batch обработка
messages = ["Message 1", "Message 2", "Message 3"]
results = await client.detect_batch(messages)

# Статистика
stats = await client.get_usage_stats(hours=24)
print(f"Requests today: {stats.total_requests}")
```

### JavaScript SDK

```bash
npm install @antispam/client
```

```javascript
import { AntiSpamClient } from '@antispam/client';

const client = new AntiSpamClient({
    apiKey: 'your_api_key',
    baseUrl: 'https://api.antispam.com'
});

// Проверка спама
const result = await client.detect('Хочешь заработать?');
console.log(result.isSpam);

// Batch обработка  
const messages = ['Message 1', 'Message 2'];
const results = await client.detectBatch(messages);

// Статистика
const stats = await client.getUsageStats({ hours: 24 });
```

### PHP SDK

```bash
composer require antispam/php-client
```

```php
use AntiSpam\\Client;

$client = new Client('your_api_key');

// Проверка сообщения
$result = $client->detect('Хочешь заработать?');
echo $result->isSpam ? 'SPAM' : 'CLEAN';

// Batch проверка
$messages = ['Message 1', 'Message 2'];
$results = $client->detectBatch($messages);
```

### Go SDK

```bash
go get github.com/antispam/go-client
```

```go
package main

import (
    "github.com/antispam/go-client"
)

func main() {
    client := antispam.NewClient("your_api_key")
    
    result, err := client.Detect("Хочешь заработать?")
    if err != nil {
        log.Fatal(err)
    }
    
    fmt.Printf("Spam: %v, Confidence: %.2f\\n", 
        result.IsSpam, result.Confidence)
}
```

## 🔗 Дополнительные ресурсы

- **Документация**: https://docs.antispam.com
- **GitHub**: https://github.com/antispam-api
- **Support**: support@antispam.com  
- **Status**: https://status.antispam.com
- **Changelog**: https://docs.antispam.com/changelog

"""

    if "info" in openapi_schema:
        openapi_schema["info"]["description"] += sdk_info


def customize_swagger_ui() -> Dict[str, Any]:
    """Кастомизация Swagger UI"""
    return {
        "swagger_ui_parameters": {
            "deepLinking": True,
            "displayRequestDuration": True,
            "docExpansion": "none",
            "operationsSorter": "method",
            "filter": True,
            "showExtensions": True,
            "showCommonExtensions": True,
            "defaultModelsExpandDepth": 2,
            "defaultModelExpandDepth": 2,
            "displayOperationId": True,
            "tryItOutEnabled": True,
        },
        "swagger_ui_oauth2_redirect_url": None,
        "swagger_ui_init_oauth": None,
    }


# Функция для интеграции с FastAPI app
def setup_openapi_documentation(app: FastAPI) -> None:
    """
    Настраивает OpenAPI документацию для FastAPI приложения

    Args:
        app: FastAPI приложение
    """

    # Кастомизация Swagger UI
    ui_config = customize_swagger_ui()

    for key, value in ui_config.items():
        setattr(app, key, value)

    # Кастомная схема
    @app.get("/openapi.json", include_in_schema=False)
    async def custom_openapi():
        return generate_production_openapi_schema(app)

    print("✅ OpenAPI документация настроена")
    print("📚 Доступна по адресу: /docs")
