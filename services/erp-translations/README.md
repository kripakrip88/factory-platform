# erp-translations — Кастомная русская локализация ERPNext

Модуль генерирует профессиональный русский перевод интерфейса ERPNext,
адаптированный под терминологию завода металлоконструкций, и загружает его
в Translation DocType через REST API.

## Зачем

Стандартный перевод ERPNext — машинный, неточный для производственного контекста.
Этот модуль создаёт перевод через Claude API с закреплёнными терминами-якорями:
"Work Order" → "Производственный заказ", "BOM" → "Спецификация" и т.д.

## Файлы

| Файл | Назначение |
|------|-----------|
| `generate-translations.py` | Генерирует `ru-metal.csv` через Claude API (запуск внутри контейнера) |
| `upload-translations.py` | Загружает переводы в Translation DocType через REST API (запуск с хоста) |
| `reset.sh` | Откат к стандартным переводам |
| `ru-metal.csv` | Сгенерированный файл переводов (коммитится в репо) |
| `progress.json` | Временный файл прогресса (создаётся и удаляется скриптом) |

## Как работает загрузка переводов

Переводы хранятся в **Translation DocType** (таблица `tabTranslation` в MariaDB) — не в файловом кэше.
Загрузка происходит автоматически через REST API: `POST /api/resource/Translation`.

`upload-translations.py` выполняет 5 шагов:
1. Очищает старые переводы из файлового кэша
2. Ищет непереведённые строки в Workspace через MariaDB
3. Допереводит недостающее через Claude API
4. Заливает всё в Translation DocType по одной записи через REST API
5. Очищает кэш ERPNext

## Быстрый старт

### 1. Генерация переводов (при первой установке или после обновления)

Запускать **внутри контейнера** `backend`:

```bash
# Скопировать скрипт в контейнер
docker compose -f services/erp/docker-compose.yml cp \
  services/erp-translations/generate-translations.py \
  backend:/tmp/generate-translations.py

# Запустить (ANTHROPIC_API_KEY берётся из .env)
docker compose -f services/erp/docker-compose.yml exec \
  -e ANTHROPIC_API_KEY=$(grep ANTHROPIC_API_KEY .env | cut -d= -f2) \
  backend python /tmp/generate-translations.py

# Скопировать результат обратно
docker compose -f services/erp/docker-compose.yml cp \
  backend:/tmp/ru-metal.csv services/erp-translations/ru-metal.csv
```

Скрипт поддерживает **прерывание и продолжение** — прогресс сохраняется в `progress.json`.
Если скрипт прерван, повторный запуск продолжит с того же места.

### 2. Загрузка переводов в ERPNext

Запускать **с хоста** из корня репозитория:

```bash
ANTHROPIC_API_KEY=<key> \
ERP_API_KEY=<key> \
ERP_API_SECRET=<secret> \
python3 services/erp-translations/upload-translations.py
```

Сгенерировать `ERP_API_KEY` и `ERP_API_SECRET`:
```bash
docker compose -f services/erp/docker-compose.yml exec backend \
  bench execute frappe.core.doctype.user.user.generate_keys --args "['Administrator']"
```

### 3. Откат к стандартным переводам

```bash
bash services/erp-translations/reset.sh
```

Удаляет все кастомные записи из Translation DocType и очищает кэш.

## Переменные окружения upload-translations.py

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `ANTHROPIC_API_KEY` | — | **Обязателен**. Ключ Claude API |
| `ERP_API_KEY` | — | **Обязателен**. Ключ ERPNext API |
| `ERP_API_SECRET` | — | **Обязателен**. Секрет ERPNext API |
| `SITE_NAME` | `erp.localhost` | Имя сайта Frappe |
| `ERP_BASE_URL` | `http://localhost:8080` | URL ERPNext |

## Ручное редактирование переводов

Отдельные термины можно поправить прямо в браузере:

1. Откройте ERPNext → **Построение → Перевод**
2. Фильтр: Language = Russian
3. Найдите нужную строку и отредактируйте поле **Translated Text**

Изменения применяются сразу после сохранения.

## При установке новых модулей ERPNext

1. Запустите `generate-translations.py` — он переведёт только новые строки (прогресс сохраняется)
2. Закоммитьте обновлённый `ru-metal.csv`
3. Запустите `upload-translations.py` — он допольёт только отсутствующие записи в DocType

## Словарь якорей

Ключевые термины, закреплённые в промпте для консистентности перевода:

| Английский | Русский |
|-----------|---------|
| Item | Номенклатура |
| Work Order | Производственный заказ |
| Bill of Materials / BOM | Спецификация |
| Quotation | Коммерческое предложение |
| Submit | Провести |
| Cancel | Аннулировать |
| Warehouse | Склад |
| Purchase Order | Заказ поставщику |
| Sales Order | Заказ покупателя |
| Lead | Лид |
| Customer | Покупатель |
| Supplier | Поставщик |
| Work in Progress | Незавершённое производство |
| Finished Goods | Готовая продукция |
| Raw Material | Сырьё и материалы |
| Routing | Технологический маршрут |
| Operation | Технологическая операция |
| Workstation | Рабочий центр |

