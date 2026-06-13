# Обновление ERPNext

> **Источник правил пиннинга версий — `CLAUDE.md` → блок «Версии frappe/erpnext».**
> Здесь только процедура. Главное правило: **frappe и erpnext обновляются ТОЛЬКО
> парой, точными версиями.** Образ не пуллится — он **собирается** из
> `services/erp/Dockerfile`.

## Патч-обновление (v16.X → v16.Y)

1. Выбрать совместимую пару версий (тег образа `frappe/erpnext:vX.Y.Z` бандлит
   конкретные frappe+erpnext — сверить, что erpnext не вызывает методов, которых
   нет в его frappe; см. прецедент в CLAUDE.md).
2. Изменить **одновременно** в двух местах:
   - тег в `services/erp/Dockerfile`:
     ```dockerfile
     FROM frappe/erpnext:v16.Y.Z
     ```
   - значения в `services/erp/versions.lock` (пара frappe+erpnext):
     ```
     frappe=16.A.B
     erpnext=16.Y.Z
     ```
3. Пересобрать образы (НЕ pull — версия запечена в Dockerfile-сборку):
   ```bash
   docker compose -f services/erp/docker-compose.yml build --no-cache
   docker compose -f services/erp/docker-compose.yml up -d --force-recreate
   ```
4. Применить миграции БД (обязательно):
   ```bash
   docker compose -f services/erp/docker-compose.yml exec backend \
     bench --site erp.localhost migrate
   ```
5. Очистить кэш:
   ```bash
   docker compose -f services/erp/docker-compose.yml exec backend \
     bench --site erp.localhost clear-cache
   ```
6. Проверить версии в браузере (`frappe.boot.versions`) — обе из одной волны —
   и прогнать регрессию ключевых форм (Lead, Quotation, Work Order и т.д.).

При деплое через CI всё это делает `.github/workflows/deploy-erp.yml`: он сам
сверяет версии в контейнере с `versions.lock` и **падает при дрейфе**. Если
поменял Dockerfile, но забыл `versions.lock` (или наоборот) — CI не пропустит.

Данные сохраняются. Настройки сохраняются. Переводы сохраняются.

## Мажорное обновление (v16 → v17)

1. Дождаться стабильного релиза (3–6 месяцев после выхода)
2. Проверить совместимость: `crm`, `saas_theme`, и любых кастомных приложений
3. Сделать полный бэкап БД:
   ```bash
   docker compose -f services/erp/docker-compose.yml exec backend \
     bench --site erp.localhost backup --with-files
   ```
4. Тестовое развёртывание на копии данных (отдельный Docker Compose)
5. Только после успешного теста — обновлять production:
   ```bash
   # Сменить тег в services/erp/Dockerfile → FROM frappe/erpnext:v17.X.Y
   # и обновить services/erp/versions.lock (пара frappe+erpnext) одновременно.
   # Остановить, удалить volumes сайта, пересобрать образ с новым тегом:
   docker compose -f services/erp/docker-compose.yml down
   docker volume rm erp_sites erp_logs
   docker compose -f services/erp/docker-compose.yml build --no-cache
   docker compose -f services/erp/docker-compose.yml up -d --force-recreate
   bash services/erp/init-site.sh  # пересоздаёт сайт
   ```
6. Перегенерировать переводы — строки интерфейса меняются при мажорном обновлении:
   ```bash
   rm -f services/erp-translations/progress.json
   # запустить generate-translations.py + upload-translations.py
   # см. services/erp-translations/README.md
   ```

Кастомизации через код (`erp-translations`, кастомные DocType) совместимы автоматически
если Frappe API не менялся. Проверять по changelog Frappe/ERPNext.

## Что НЕ делать

- Не дропать volumes (`erp_db_data`) если есть production-данные
- Не обновляться в первый месяц после мажорного релиза
- Не делать ручные правки внутри контейнера — они теряются при пересоздании
- Не пропускать шаг `bench migrate` после обновления образа
- Не обновлять версию через `docker compose pull` — образ собирается из
  `Dockerfile`, pull подтянет не тот тег и разойдётся с `versions.lock`
- Не менять только `Dockerfile` или только `versions.lock` — они меняются парой,
  иначе CI завалит деплой на проверке версий
- Не обновлять frappe и erpnext по отдельности — только согласованной парой

## Установленные приложения и их репозитории

| Приложение | Репозиторий | Ветка |
|------------|-------------|-------|
| frappe | https://github.com/frappe/frappe | version-16 |
| erpnext | https://github.com/frappe/erpnext | version-16 |
| crm | https://github.com/frappe/crm | main |
| saas_theme | https://github.com/vineyrawat/saas_theme | version-16 |
