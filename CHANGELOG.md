# Changelog

## 2026-06-11

### services/erp
- [chore] удалена frappe-theme — кривая верстка, оставлен стандартный UI ERPNext

## 2026-06-10 (3)

### services/erp
- [feat] установлена frappe-theme (devlpr-nitish/frappe-theme, ветка develop) — UI тема с Theme Settings
- [chore] удалена saas_theme (сломанный build)

## 2026-06-10 (2)

### services/erp
- [chore] удалён Frappe CRM — используется встроенный CRM ERPNext

## 2026-06-10

### services/erp
- [feat] миграция ERPNext v15 → v16
- [feat] перевод интерфейса под v16, ~14k строк через Claude Haiku API
- [feat] переводы залиты в Translation DocType (Построение → Перевод)
- [feat] установлен Frappe CRM (ветка main)
- [feat] установлена saas_theme (version-16)
- [docs] создан docs/erp-updates.md — инструкции по патч и мажорным обновлениям

## 2026-06-09

### factory-platform
- [feat] инициализация монорепозитория — структура сервисов, Docker Compose, Nginx, GitHub Actions CI/CD
- [feat] services/telegram-bot — базовый скелет с командами /start, /help
- [feat] services/n8n — структура для workflow JSON
- [feat] services/erp — README-заглушка для ERPNext
- [config] infra/docker-compose.yml — все сервисы (postgres, redis, ai-assistant, n8n, telegram-bot, nginx)
- [config] .github/workflows — CI на PR, deploy workflows per service (ai-assistant, telegram-bot)
