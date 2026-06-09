# Second Brain — Персональный AI-ассистент

Telegram-бот для автоматического сбора, классификации и review личных знаний:
идеи, статьи, анализы крови, ссылки, вдохновение из TG-групп и личных сообщений.
Каждый айтем классифицируется через Claude API и сохраняется с тегами в PostgreSQL.

---

## Быстрый старт

```bash
cd services/second-brain

# 1. Скопировать и заполнить переменные
cp .env.example .env
# Открой .env и заполни TELEGRAM_BOT_TOKEN, OWNER_USER_ID, ANTHROPIC_API_KEY и пароли

# 2. Запустить
docker compose up -d

# 3. Проверить
docker compose ps
docker compose logs brain-bot -f
```

---

## Как создать бота

1. Открой [@BotFather](https://t.me/BotFather) в Telegram
2. Отправь `/newbot`, задай имя и username
3. Скопируй токен в `TELEGRAM_BOT_TOKEN`

## Как получить ID групп

Способ 1: добавь [@userinfobot](https://t.me/userinfobot) в группу — он покажет chat ID.
Способ 2: перешли сообщение из группы боту [@username_to_id_bot](https://t.me/username_to_id_bot).

ID группы — отрицательное число, например `-1001234567890`.

---

## Команды бота

| Команда | Описание |
|---------|----------|
| `/review` | Показать батч непросмотренных айтемов |
| `/stats` | Статистика по категориям и количеству |
| `/search <запрос>` | Полнотекстовый поиск по базе |
| `/import` | Инструкция по импорту истории групп |

---

## Кнопки review

| Кнопка | Действие |
|--------|----------|
| 👍 Сохранить | Отмечает как просмотрено и важное |
| ⏭ Скипнуть | Пропускает без сохранения |
| ★ Избранное | Помечает как избранное (score=2) |

Дайджест автоматически приходит каждый день в 20:00 (настраивается через `REVIEW_CRON`).

---

## Импорт истории Telegram-групп

Для импорта используется Telethon (userbot, не Bot API).

### Получение credentials

1. Зайди на [my.telegram.org/apps](https://my.telegram.org/apps)
2. Создай приложение, получи `API_ID` и `API_HASH`
3. Добавь в `.env`:
   ```
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
   ```

### Запуск импорта

```bash
docker compose exec brain-bot python -m src.scripts.import_history
```

При первом запуске Telethon попросит номер телефона и код подтверждения.
Прогресс сохраняется в `brain.import_progress` — повторный запуск продолжит с последнего сообщения.

---

## Добавление новых источников

Модуль спроектирован для расширения. Чтобы добавить источник:

1. Создай файл `bot/src/services/pocket_importer.py` (или другой источник)
2. В `save_item()` передавай `source_type="pocket"` (или нужный тип)
3. Добавь команду-обработчик в `review_handler.py`
4. **Не трогай** `infra/docker-compose.yml` — модуль полностью изолирован

Планируемые источники:
- Pocket / Instapaper
- Закладки браузера (Chrome extensions)
- PDF-файлы (анализы крови, документы)
- RSS-ленты

---

## Архитектура

```
brain-bot ─── brain-db  (PostgreSQL 16)
          └── brain-redis (Redis 7, FSM storage)

brain-n8n ─── brain-db  (схема n8n)
```

Все сервисы в изолированной сети `brain-net`. Никаких зависимостей от основного стека платформы.
