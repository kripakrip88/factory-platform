# Обновление ERPNext

## Патч-обновление (v16.X → v16.Y)

1. Изменить тег образа в `services/erp/docker-compose.yml`:
   ```yaml
   image: frappe/erpnext:v16.X.Y
   ```
2. Подтянуть новые образы:
   ```bash
   docker compose -f services/erp/docker-compose.yml pull
   ```
3. Перезапустить:
   ```bash
   docker compose -f services/erp/docker-compose.yml up -d
   ```
4. Применить миграции БД:
   ```bash
   docker compose -f services/erp/docker-compose.yml exec backend \
     bench --site erp.localhost migrate
   ```
5. Очистить кэш:
   ```bash
   docker compose -f services/erp/docker-compose.yml exec backend \
     bench --site erp.localhost clear-cache
   ```

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
   # Остановить, удалить volumes, пересоздать с новым образом
   docker compose -f services/erp/docker-compose.yml down
   docker volume rm erp_sites erp_logs
   # Обновить образ в docker-compose.yml → v17
   docker compose -f services/erp/docker-compose.yml pull
   docker compose -f services/erp/docker-compose.yml up -d
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

## Установленные приложения и их репозитории

| Приложение | Репозиторий | Ветка |
|------------|-------------|-------|
| frappe | https://github.com/frappe/frappe | version-16 |
| erpnext | https://github.com/frappe/erpnext | version-16 |
| crm | https://github.com/frappe/crm | main |
| saas_theme | https://github.com/vineyrawat/saas_theme | version-16 |
