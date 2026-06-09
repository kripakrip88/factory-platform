# Factory Platform — Claude Rules

## Что это за репозиторий

Монорепозиторий платформы управления металлоконструкционным заводом.
Включает ERPNext, AI Assistant, n8n оркестратор, Telegram Bot.

**Связанный репозиторий (legacy AI module):** https://github.com/kripakrip88/metalpro-ai-polygon

---

## Перед началом любой задачи

1. Прочитать `CLAUDE.md` (этот файл)
2. Если задача затрагивает конкретный сервис — прочитать `services/<name>/README.md`
3. Показать план и ждать подтверждения

---

## Структура

```
services/
  erp/            — ERPNext (Python/Frappe)
  ai-assistant/   — NestJS + Claude API + OCR
  n8n/            — workflow конфиги
  telegram-bot/   — Node.js бот
infra/
  docker-compose.yml
  nginx/
.github/workflows/ — CI/CD per service
```

---

## Стек

- **ERPNext:** Python, Frappe, MariaDB
- **AI Assistant:** NestJS, TypeScript, PostgreSQL, Claude API (claude-sonnet-4-20250514)
- **n8n:** Docker, PostgreSQL
- **Telegram Bot:** Node.js, TypeScript
- **Infra:** Docker Compose, Nginx, GitHub Actions

---

## Деплой

Осуществляется через GitHub Actions автоматически.
`develop` → staging, `main` → production.

```
git push
  ↓ GitHub Actions
  ↓ SSH → сервер
  ↓ docker compose build + up
```

## Secrets (GitHub → Settings → Secrets)

| Secret | Описание |
|--------|----------|
| `SERVER_HOST` | IP сервера |
| `SERVER_USER` | SSH пользователь |
| `SERVER_SSH_KEY` | Приватный SSH ключ |

---

## Правила веток

- **Никогда не пушить напрямую в `main`**
- Ветки: `feature/...`, `fix/...`, `refactor/...`
- PR: `feature/...` → `develop` → `main`

---

## Правила БД

Разрешено: новые таблицы, колонки, индексы, безопасные миграции.
Запрещено без согласования: DROP TABLE, DROP COLUMN, изменение типов с потерей данных.

---

## После каждого значимого изменения

Обновить `CHANGELOG.md`:
```
## YYYY-MM-DD
### factory-platform
- [feat] название — зачем
```
