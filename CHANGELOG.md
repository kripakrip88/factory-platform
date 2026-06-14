# Changelog

## 2026-06-14

### services/erp — новый app `metal_calculator`
- [feat] калькулятор веса металлопроката (конструкционная сталь), изолированная frappe-аппа
- [feat] DocTypes `Metal Profile`, `Metal Sheet Grade`, `Steel Grade` (без Link на стандартные DocType ERP)
- [feat] seed справочников строго из ГОСТ (118 профилей, 15 толщин листа, 8 марок), идемпотентно
- [feat] `api.calculate` — расчёт с явной конвертацией мм→м, валидация, без геометрии
- [feat] Workspace «Калькуляторы» (fixture) + 3 раздела (калькулятор + 2 заглушки)
- [feat] Page `metal_calculator` (UI, рус.) + Page `module_in_progress` (заглушка)
- [test] юнит-тесты: якоря 1278/85.2/282.6 кг + контроль конвертации мм→м
- [build] `Dockerfile`: вшивание аппы в образ; `scripts/install-metal-calculator.sh`

## 2026-06-11 (3)

### services/erp-translations
- [feat] добавлен `factory-glossary.py` — ~200 точных терминов завода без API
- [feat] добавлен `generate-factory-translations.py` — v2 генератор с глоссарием и улучшенным промптом
- [docs] обновлён README: v2 как рекомендуемый метод, раздел об ограничении падежей
- [docs] создан Issue #2 — проработка контекстных ключей перевода

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
