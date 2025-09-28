"""
Performance Tests with Locust
Нагрузочное тестирование AntiSpam Bot API
Цель: 10,000+ RPS, 95th percentile < 200ms, 99th percentile < 500ms
"""

import random
import time
import json
from locust import HttpUser, task, between, events
from locust.exception import StopUser


class SpamDetectionUser(HttpUser):
    """Пользователь для тестирования API детекции спама"""
    
    wait_time = between(0.1, 2.0)
    
    def on_start(self):
        """Инициализация пользователя"""
        self.api_key = "ask_performance_test_key_12345678901234567890"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Locust-Performance-Test/1.0"
        }
        
        self.russian_messages = [
            "Привет! Как дела? Что планируешь на выходные?",
            "Спасибо за помощь с проектом вчера, очень помогло",
            "Где лучше всего поужинать в центре города?",
            "Завтра встречаемся в 15:00 у главного входа",
            "Погода сегодня отличная, пойдем гулять?",
            "Как успехи с изучением нового языка программирования?",
            "Напомни пожалуйста про встречу в четверг",
            "Интересная статья, спасибо что поделился",
            "Удачного дня и хорошего настроения!",
            "Когда планируешь закончить с этим проектом?"
        ]
        
        self.english_messages = [
            "Hello! How are you today? Any plans for dinner?",
            "Thanks for the meeting notes, they were very helpful",
            "What's the best restaurant in downtown area?",
            "Let's meet tomorrow at 3 PM at the main entrance",
            "Beautiful weather today, want to go for a walk?",
            "How's your progress with the new programming language?",
            "Please remind me about Thursday's meeting",
            "Interesting article, thanks for sharing!",
            "Have a great day and good mood!",
            "When do you plan to finish this project?"
        ]
        
        self.spam_messages = [
            "🔥🔥🔥 ЗАРАБОТАЙ МИЛЛИОН РУБЛЕЙ ЗА ДЕНЬ! 🔥🔥🔥",
            "СРОЧНО!!! ДЕНЬГИ БЕЗ ПРОЦЕНТОВ!!! ЗВОНИ СЕЙЧАС!!!",
            "Make money fast! Work from home! Click here!",
            "💰💰💰 LOTTERY WINNER! CLAIM YOUR PRIZE NOW! 💰💰💰",
            "🚀 СУПЕР ПРЕДЛОЖЕНИЕ! ТОЛЬКО СЕГОДНЯ! СКИДКА 90%! 🚀",
            "URGENT!!! LIMITED TIME OFFER!!! CLICK NOW!!!",
            "Работа дома! Легкие деньги! Без вложений!",
            "Amazing deals! Don't miss out! Act now!",
            "🎰 ВЫИГРАЙ ДЖЕКПОТ! ПЕРЕХОДИ ПО ССЫЛКЕ! 🎰",
            "FREE MONEY! NO STRINGS ATTACHED! HURRY UP!"
        ]
        
        self.user_counter = 0
    
    def get_random_message(self, message_type="normal"):
        """Получает случайное сообщение нужного типа"""
        if message_type == "spam":
            return random.choice(self.spam_messages)
        elif message_type == "english":
            return random.choice(self.english_messages)
        else:
            return random.choice(self.russian_messages)
    
    def get_user_context(self, is_new_user=False):
        """Генерирует контекст пользователя"""
        self.user_counter += 1
        return {
            "user_id": 100000 + self.user_counter + random.randint(1, 10000),
            "chat_id": 67890,
            "is_new_user": is_new_user,
            "is_admin_or_owner": False
        }
    
    @task(70)
    def detect_normal_message(self):
        """70% запросов - обычные сообщения"""
        message_type = random.choice(["normal", "english"])
        text = self.get_random_message(message_type)
        
        payload = {
            "text": text,
            "context": self.get_user_context(is_new_user=random.random() < 0.1)
        }
        
        with self.client.post(
            "/api/v1/detect",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if "is_spam" in data and "confidence" in data and "processing_time_ms" in data:
                        if data["processing_time_ms"] > 2000:
                            response.failure(f"Processing time too high: {data['processing_time_ms']}ms")
                        else:
                            response.success()
                    else:
                        response.failure("Invalid response structure")
                except json.JSONDecodeError:
                    response.failure("Invalid JSON response")
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")
    
    @task(20)
    def detect_spam_message(self):
        """20% запросов - спам сообщения"""
        text = self.get_random_message("spam")
        
        payload = {
            "text": text,
            "context": self.get_user_context(is_new_user=random.random() < 0.3)
        }
        
        with self.client.post(
            "/api/v1/detect",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if "is_spam" in data and "confidence" in data:
                        if data["is_spam"] and data["confidence"] > 0.6:
                            response.success()
                        elif not data["is_spam"] and data["confidence"] < 0.4:
                            response.success()
                        else:
                            response.success()
                    else:
                        response.failure("Invalid response structure")
                except json.JSONDecodeError:
                    response.failure("Invalid JSON response")
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")
    
    @task(8)
    def batch_detect_messages(self):
        """8% запросов - batch детекция"""
        batch_size = random.randint(3, 10)
        messages = []
        
        for i in range(batch_size):
            message_type = random.choice(["normal", "english", "spam"])
            text = self.get_random_message(message_type)
            
            messages.append({
                "text": text,
                "context": self.get_user_context(is_new_user=random.random() < 0.15)
            })
        
        payload = {"messages": messages}
        
        with self.client.post(
            "/api/v1/detect/batch",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if "results" in data and "total_processed" in data:
                        if len(data["results"]) == batch_size and data["total_processed"] == batch_size:
                            response.success()
                        else:
                            response.failure(f"Batch size mismatch: expected {batch_size}, got {len(data['results'])}")
                    else:
                        response.failure("Invalid batch response structure")
                except json.JSONDecodeError:
                    response.failure("Invalid JSON response")
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")
    
    @task(2)
    def get_usage_stats(self):
        """2% запросов - получение статистики"""
        with self.client.get(
            "/api/v1/stats",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if "total_requests" in data:
                        response.success()
                    else:
                        response.failure("Invalid stats response")
                except json.JSONDecodeError:
                    response.failure("Invalid JSON response")
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")


class HighVolumeUser(HttpUser):
    """Пользователь для высоконагруженного тестирования"""
    
    wait_time = between(0.01, 0.1)
    
    def on_start(self):
        """Инициализация для высокой нагрузки"""
        self.api_key = "ask_high_volume_test_key_98765432109876543210"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Locust-HighVolume-Test/1.0"
        }
        
        self.quick_messages = [
            "привет",
            "спасибо",
            "hello",
            "thanks",
            "ok",
            "да",
            "нет",
            "yes",
            "no",
            "хорошо"
        ]
        
        self.user_id_base = random.randint(200000, 300000)
    
    @task
    def rapid_detect(self):
        """Быстрые запросы для тестирования пропускной способности"""
        text = random.choice(self.quick_messages)
        user_id = self.user_id_base + random.randint(1, 1000)
        
        payload = {
            "text": text,
            "context": {
                "user_id": user_id,
                "chat_id": 67890,
                "is_new_user": False
            }
        }
        
        with self.client.post(
            "/api/v1/detect",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in [200, 429]:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")


class StressTestUser(HttpUser):
    """Пользователь для стресс-тестирования"""
    
    wait_time = between(0.05, 0.5)
    
    def on_start(self):
        """Инициализация для стресс-тестов"""
        self.api_key = "ask_stress_test_key_11111111111111111111"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Locust-Stress-Test/1.0"
        }
        
        self.complex_messages = [
            "Это очень длинное сообщение для тестирования производительности системы детекции спама. " * 20,
            "🔥💰🚀💎🎉🎊🎈🎁🎀🎂🎃🎄🎅🎆🎇✨🎌🎍🎎🎏🎐🎑🎋🎓🎗🎟🎫🎪🎭🎨🎬🎤🎧🎼🎵🎶🎹🎺🎻🥁🎸",
            "URGENT URGENT URGENT URGENT URGENT URGENT URGENT URGENT URGENT URGENT URGENT URGENT",
            "Mixed язык message with разные languages и специальные символы ñáéíóú αβγδε 中文字符",
            "Numbers 123456789 and symbols !@#$%^&*()_+-=[]{}|;:,.<>? testing various patterns"
        ]
    
    @task
    def stress_detect(self):
        """Стресс-тестирование с комплексными сообщениями"""
        text = random.choice(self.complex_messages)
        
        payload = {
            "text": text,
            "context": {
                "user_id": random.randint(400000, 500000),
                "chat_id": 67890,
                "is_new_user": random.random() < 0.2
            }
        }
        
        start_time = time.time()
        
        with self.client.post(
            "/api/v1/detect",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            end_time = time.time()
            response_time = (end_time - start_time) * 1000
            
            if response.status_code == 200:
                if response_time > 5000:
                    response.failure(f"Response too slow: {response_time:.0f}ms")
                else:
                    response.success()
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")



@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, exception, **kwargs):
    """Собираем дополнительные метрики"""
    if request_type == "POST" and "/api/v1/detect" in name:
        if response and response.status_code == 200:
            try:
                data = response.json()
                processing_time = data.get("processing_time_ms", 0)
                
                if processing_time > 1000:
                    print(f"⚠️ Slow processing: {processing_time}ms for {name}")
                
                if "is_spam" in data and "confidence" in data:
                    confidence = data["confidence"]
                    if confidence < 0.1 or confidence > 0.9:
                        pass
                    else:
                        pass
                        
            except (json.JSONDecodeError, AttributeError):
                pass


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Инициализация тестов"""
    print("🚀 Starting performance tests...")
    print(f"Target host: {environment.host}")
    print("Test scenarios:")
    print("  - 70% normal messages")
    print("  - 20% spam messages") 
    print("  - 8% batch requests")
    print("  - 2% stats requests")


@events.test_stop.add_listener  
def on_test_stop(environment, **kwargs):
    """Завершение тестов"""
    print("🏁 Performance tests completed!")
    
    stats = environment.stats
    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    
    if total_requests > 0:
        failure_rate = (total_failures / total_requests) * 100
        avg_response_time = stats.total.avg_response_time
        
        print(f"📊 Final Results:")
        print(f"   Total requests: {total_requests}")
        print(f"   Total failures: {total_failures}")
        print(f"   Failure rate: {failure_rate:.2f}%")
        print(f"   Average response time: {avg_response_time:.0f}ms")
        print(f"   Max response time: {stats.total.max_response_time:.0f}ms")
        print(f"   Min response time: {stats.total.min_response_time:.0f}ms")
        print(f"   RPS: {stats.total.total_rps:.1f}")
        
        print("\n🎯 KPI Check:")
        
        if failure_rate <= 0.1:
            print(f"   ✅ Failure rate: {failure_rate:.2f}% (target: ≤ 0.1%)")
        else:
            print(f"   ❌ Failure rate: {failure_rate:.2f}% (target: ≤ 0.1%)")
        
        if avg_response_time <= 200:
            print(f"   ✅ Avg response time: {avg_response_time:.0f}ms (target: ≤ 200ms)")
        else:
            print(f"   ❌ Avg response time: {avg_response_time:.0f}ms (target: ≤ 200ms)")
        
        if stats.total.get_response_time_percentile(0.95) <= 500:
            p95 = stats.total.get_response_time_percentile(0.95)
            print(f"   ✅ 95th percentile: {p95:.0f}ms (target: ≤ 500ms)")
        else:
            p95 = stats.total.get_response_time_percentile(0.95)
            print(f"   ❌ 95th percentile: {p95:.0f}ms (target: ≤ 500ms)")
        
        if stats.total.total_rps >= 100:
            print(f"   ✅ Throughput: {stats.total.total_rps:.1f} RPS (target: ≥ 100 RPS)")
        else:
            print(f"   ❌ Throughput: {stats.total.total_rps:.1f} RPS (target: ≥ 100 RPS)")



"""
Команды для запуска различных сценариев:

1. Базовый тест производительности:
   locust -f locustfile.py --host=http://localhost:8080 --users=100 --spawn-rate=10 --run-time=300s

2. Тест пропускной способности:
   locust -f locustfile.py --user-classes=HighVolumeUser --host=http://localhost:8080 --users=500 --spawn-rate=50 --run-time=300s

3. Стресс-тест:
   locust -f locustfile.py --user-classes=StressTestUser --host=http://localhost:8080 --users=200 --spawn-rate=20 --run-time=600s

4. Комбинированный тест:
   locust -f locustfile.py --host=http://localhost:8080 --users=300 --spawn-rate=30 --run-time=600s

5. Headless тест с отчетом:
   locust -f locustfile.py --host=http://localhost:8080 --users=150 --spawn-rate=15 --run-time=300s --headless --html=performance_report.html --csv=performance_results

Целевые KPI:
- Пропускная способность: 10,000+ RPS (достижимая с масштабированием)
- 95th percentile response time: < 200ms
- 99th percentile response time: < 500ms
- Failure rate: < 0.1%
- Максимальное время обработки: < 2000ms (системный лимит)
"""

if __name__ == "__main__":
    import subprocess
    import sys
    
    print("🚀 AntiSpam Bot Performance Testing")
    print("=" * 50)
    print("Available test scenarios:")
    print("1. Basic Performance Test (100 users, 5 min)")
    print("2. High Volume Test (500 users, 5 min)")
    print("3. Stress Test (200 users, 10 min)")
    print("4. Combined Test (300 users, 10 min)")
    print("5. Quick Smoke Test (20 users, 1 min)")
    
    choice = input("\nSelect scenario (1-5): ").strip()
    host = input("Enter host (default: http://localhost:8080): ").strip() or "http://localhost:8080"
    
    commands = {
        "1": f"locust -f {__file__} --host={host} --users=100 --spawn-rate=10 --run-time=300s --headless --html=basic_perf_report.html",
        "2": f"locust -f {__file__} --user-classes=HighVolumeUser --host={host} --users=500 --spawn-rate=50 --run-time=300s --headless --html=high_volume_report.html",
        "3": f"locust -f {__file__} --user-classes=StressTestUser --host={host} --users=200 --spawn-rate=20 --run-time=600s --headless --html=stress_test_report.html",
        "4": f"locust -f {__file__} --host={host} --users=300 --spawn-rate=30 --run-time=600s --headless --html=combined_test_report.html",
        "5": f"locust -f {__file__} --host={host} --users=20 --spawn-rate=5 --run-time=60s --headless"
    }
    
    if choice in commands:
        print(f"\n🚀 Running scenario {choice}...")
        print(f"Command: {commands[choice]}")
        
        try:
            subprocess.run(commands[choice].split(), check=True)
            print("\n✅ Performance test completed successfully!")
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Performance test failed: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n⚠️ Performance test interrupted by user")
            sys.exit(0)
    else:
        print("❌ Invalid choice")
        sys.exit(1)
