
-- SQL скрипт для настройки PostgreSQL для антиспам бота
-- Запустите этот скрипт под суперпользователем (обычно postgres)

-- Создаем пользователя для бота
DROP USER IF EXISTS antispam_user;
CREATE USER antispam_user WITH PASSWORD 'StrongPassword123!';

-- Создаем базу данных
DROP DATABASE IF EXISTS antispam_bot;
CREATE DATABASE antispam_bot OWNER antispam_user;

-- Даем права пользователю
GRANT ALL PRIVILEGES ON DATABASE antispam_bot TO antispam_user;

-- Подключаемся к новой базе для настройки схемы
\c antispam_bot

-- Даем права на схему public
GRANT ALL ON SCHEMA public TO antispam_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO antispam_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO antispam_user;

-- Настраиваем права по умолчанию для будущих объектов
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO antispam_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO antispam_user;

-- Проверяем что пользователь создан
\du antispam_user

-- Проверяем что база создана
\l antispam_bot

\echo 'База данных настроена успешно!'
\echo 'Теперь обновите .env файл с правильными данными подключения.'

