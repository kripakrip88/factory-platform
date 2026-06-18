# Changelog

С v1.0.0 версии тегаются по semver `vMAJOR.MINOR.PATCH` (см. CLAUDE.md). Каждый
деплой в develop = тег + запись здесь. Откат: `git checkout vX.Y.Z` → деплой.

## v1.0.1 — 2026-06-18
Почта (прод, с бэкапом `20260618_143752`):
- [fix] отправленные mail.ru: имя папки `Sent`→**«Отправленные»** + приём папки
  «Отправленные» (IMAP Folder pull) — письма с телефона/веба подтягиваются как Sent,
  дедуп по Message-ID; sync=ALL, From=аккаунт.
- [fix] имя отправителя: `frappe.parse_addr` теряет display-name из From
  (`=?utf-8?B?...?= <email>`) → sender_full_name=email. Чиним без патча ядра —
  `saas_theme.email_names`: сверка имён из IMAP правильным парсером. Бэкфилл
  загруженных писем + планировщик `hourly_long` (go-forward).
- [fix] инбокс грузил свой набор полей без `sender_full_name` → имена всегда падали
  в fallback. Подтягиваем поле одним запросом + обновляем имя на повторном декоре.
- Имя папки `\Sent` берём с сервера (modified UTF-7) — `«Отправленные»` (Unicode)
  роняет imaplib. Логика консолидирована в `saas_theme/email_names.py` (удалён
  `setup/email_delivery.py`). saas_theme `?v=132`. Бэкфилл вживую: 183 письма,
  kev.unit → «Евгений Кругликов».

## v1.0.0 — 2026-06-18
Базовый тег (снимок текущего develop: ERPNext v16 + saas_theme + калькулятор
металла + раскрой + доборка с конструктором, заказами и PDF-листом + почта).
Плюс правки этого захода (saas_theme `?v=130`):
- [fix] список писем: имя отправителя вместо email (локальная часть как fallback),
  заголовки колонок под содержимое («Тема»→«Отправитель / тема», «С»→«Почта»),
  убран дубль отправителя.
- [feat] правило версионирования/тегов в CLAUDE.md (semver, тег+CHANGELOG на деплой).
- [feat] `setup/email_delivery.py` — pull-синхронизация папки «Отправленные» mail.ru
  (отправленные с других устройств подтягиваются) + исправлено имя папки Sent→
  «Отправленные». ⚠️ применяется на проде осознанно + живой тест (см. email_delivery_tests.md).

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
