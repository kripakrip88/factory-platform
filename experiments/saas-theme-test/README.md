# saas-theme-test

Эксперимент: тестирование темы SaaS Theme (CommitStreet) на изолированном ERPNext v16.

**Статус:** эксперимент

## Запуск

```bash
cd experiments/saas-theme-test

# 1. Собрать образ и поднять базу
docker compose up -d db redis-cache redis-queue redis-socketio

# 2. Собрать кастомный образ с темой
docker compose build

# 3. Создать сайт и установить тему (одноразово, ждать ~5 мин)
docker compose run --rm create-site

# 4. Поднять всё остальное
docker compose up -d backend frontend websocket queue-short queue-default scheduler
```

Открыть: http://localhost:8090
Логин: Administrator / admin

## Остановка и очистка

```bash
docker compose down -v
docker rmi saas-theme-test-backend
```
