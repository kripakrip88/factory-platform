# ERPNext Service

ERPNext v16 — core ERP for CRM, Quotation, BOM, Production.

## First Deploy

```bash
# 1. Add to .env in repo root:
# DB_ROOT_PASSWORD=<strong-password>
# ERP_ADMIN_PASSWORD=<strong-password>
# DOMAIN=yourdomain.com  (or leave empty for IP access)

# 2. Start containers
docker compose -f services/erp/docker-compose.yml --env-file .env up -d

# 3. Wait ~2 min for MariaDB to be ready, then create site (run once)
bash services/erp/init-site.sh

# 4. Access ERPNext at http://SERVER_IP:8080
```

## Daily Operations

```bash
# Start
docker compose -f services/erp/docker-compose.yml --env-file .env up -d

# Stop
docker compose -f services/erp/docker-compose.yml down

# Logs
docker compose -f services/erp/docker-compose.yml logs -f backend

# Restart single service
docker compose -f services/erp/docker-compose.yml restart backend
```

## Containers

| Container | Role |
|-----------|------|
| `db` | MariaDB 10.6 — ERPNext database |
| `backend` | Frappe/ERPNext Python app |
| `frontend` | Nginx serving ERPNext UI on :8080 |
| `websocket` | Realtime updates (Socket.IO) |
| `queue-short/long/default` | Background job workers |
| `scheduler` | Cron jobs (emails, reports) |
| `redis-cache/queue/socketio` | Redis instances |

## Переводы

Кастомная русская локализация под терминологию металлопроизводства — в [`services/erp-translations/`](../erp-translations/README.md).

После первого запуска или обновления ERPNext нужно перегенерировать и залить переводы:
```bash
# 1. Удалить прогресс предыдущей генерации (если есть)
rm -f services/erp-translations/progress.json

# 2. Сгенерировать ru-metal.csv (~14k строк через Claude Haiku API)
docker compose -f services/erp/docker-compose.yml cp \
  services/erp-translations/generate-translations.py \
  backend:/tmp/generate-translations.py
docker compose -f services/erp/docker-compose.yml exec \
  -e ANTHROPIC_API_KEY=$(grep ANTHROPIC_API_KEY .env | cut -d= -f2) \
  backend python /tmp/generate-translations.py
docker compose -f services/erp/docker-compose.yml cp \
  backend:/tmp/ru-metal.csv services/erp-translations/ru-metal.csv

# 3. Залить в Translation DocType
ANTHROPIC_API_KEY=<key> ERP_API_KEY=<key> ERP_API_SECRET=<secret> \
  python3 services/erp-translations/upload-translations.py
```

## Настройка CRM

После первого запуска применить настройки CRM одной командой:

```bash
docker compose -f services/erp/docker-compose.yml cp \
  services/erp/setup/crm_setup.py backend:/tmp/crm_setup.py
docker compose -f services/erp/docker-compose.yml exec backend \
  bench --site erp.localhost execute /tmp/crm_setup.py
```

Создаёт 7 этапов воронки и скрывает лишние поля в форме Opportunity.

Реестр всех отключённых полей и модулей: [`docs/disabled-features.md`](../../docs/disabled-features.md)

## Установленные приложения

| Приложение | Репозиторий | Ветка | Описание |
|------------|-------------|-------|----------|
| erpnext | frappe/erpnext | v16 | Core ERP — продажи, закупки, производство, склад |
| saas_theme | monorepo: `services/erp/saas_theme/` | — | Кастомная UI-тема (см. ниже) |

CRM: используется встроенный CRM ERPNext (модуль CRM в основном приложении).

## SaaS Theme

Кастомная UI-тема хранится локально в `services/erp/saas_theme/` и копируется в Docker-образ при сборке.

Подробная документация: [`docs/saas-theme.md`](../../docs/saas-theme.md)

Текущая версия: **v76**

### Обновить тему

Все изменения вносятся в:
- `saas_theme/public/js/saas_theme.js` — логика
- `saas_theme/public/css/saas_theme.css` — стили
- `saas_theme/hooks.py` — версия (`?v=N`, инкрементить при каждом изменении)

После изменений — пуш в `develop`, CI/CD пересобирает образ автоматически.

## История версий ERPNext

| Версия | Дата | Изменения |
|--------|------|-----------|
| v16 | 2026-06-10 | Миграция с v15 — более стабильная ветка, актуальные строки интерфейса |
| v15.110.0 | 2026-06-09 | Первоначальный запуск |
