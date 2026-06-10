# erp-translations — Кастомная русская локализация ERPNext

Модуль генерирует и импортирует профессиональный русский перевод интерфейса ERPNext,
адаптированный под терминологию завода металлоконструкций.

## Зачем

Стандартный перевод ERPNext — машинный, неточный для производственного контекста.
Этот модуль создаёт перевод через Claude API с закреплёнными терминами-якорями:
"Work Order" → "Производственный заказ", "BOM" → "Спецификация" и т.д.

## Файлы

| Файл | Назначение |
|------|-----------|
| `generate-translations.py` | Генерирует `ru-metal.csv` через Claude API |
| `import.sh` | Импортирует CSV в ERPNext |
| `reset.sh` | Откат к стандартным переводам |
| `ru-metal.csv` | Сгенерированный файл переводов (коммитится в репо) |
| `progress.json` | Временный файл прогресса (создаётся и удаляется скриптом) |

## Быстрый старт

### 1. Генерация переводов

Запускать **на сервере** внутри контейнера `backend`:

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

### 2. Импорт в ERPNext

```bash
bash services/erp-translations/import.sh
```

Скрипт:
1. Проверяет что ERPNext запущен
2. Копирует CSV в контейнер
3. Импортирует через `frappe.translate.import_translations`
4. Очищает кэш

### 3. Откат к стандартным переводам

```bash
bash services/erp-translations/reset.sh
```

Удаляет все кастомные записи из таблицы переводов и очищает кэш.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `ANTHROPIC_API_KEY` | — | **Обязателен**. Ключ Claude API |
| `SITE_NAME` | `erp.localhost` | Имя сайта Frappe |

## Ручное редактирование переводов

После импорта отдельные термины можно поправить прямо в UI:

1. Откройте ERPNext → **Setup → Translation**
2. Фильтр: Language = Russian
3. Найдите нужную строку и отредактируйте поле **Translated Text**

Изменения применяются сразу после сохранения (кэш очищается автоматически).

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

## Обновление переводов

При выходе новой версии ERPNext или добавлении новых модулей:

1. Удалите `progress.json` если он остался
2. Запустите `generate-translations.py` заново — он переведёт только новые строки
3. Запустите `import.sh`
4. Закоммитьте обновлённый `ru-metal.csv`
