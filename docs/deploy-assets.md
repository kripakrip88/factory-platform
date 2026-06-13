# Как ассеты saas_theme доезжают до браузера

## Путь файла: репозиторий → браузер

1. **Репозиторий**: `services/erp/saas_theme/saas_theme/public/{css,js}/saas_theme.{css,js}`
2. **Docker build** (`services/erp/Dockerfile`): `COPY saas_theme` в
   `/home/frappe/frappe-bench/apps/saas_theme` + `bench build --app saas_theme`.
   Файлы оказываются в **image layer** каждого образа, собранного из этого Dockerfile.
3. **Контейнеры**: `backend` и `frontend` собираются из ОДНОГО Dockerfile,
   но это ДВА РАЗНЫХ образа (`erp-backend`, `erp-frontend`). Ассеты запечены в оба.
4. **Volume `erp_assets`** (external, монтируется в оба контейнера как
   `/home/frappe/frappe-bench/assets`): содержит `saas_theme` как **симлинк** на
   `/home/frappe/frappe-bench/apps/saas_theme/saas_theme/public`.
   Симлинк разрешается **внутри каждого контейнера** → каждый контейнер видит
   файл из СВОЕГО image layer, а не общий файл.
5. **Nginx (frontend)**: отдаёт `/assets/saas_theme/js/saas_theme.js` →
   симлинк → файл из image layer **frontend-образа**.

## Следствие (ключевое!)

Браузер получает файл из **frontend-образа**. Если пересобрать только backend —
браузер продолжит получать старую версию. Поэтому:

```bash
# Правильный деплой — ВСЕГДА оба образа + force-recreate:
docker compose -f services/erp/docker-compose.yml build --no-cache
docker compose -f services/erp/docker-compose.yml up -d --force-recreate
docker exec erp-backend-1 bash -c "cd /home/frappe/frappe-bench && bench --site erp.localhost clear-cache"
```

CI/CD (`.github/workflows/deploy-erp.yml`) делает именно это.

## Правила

1. **Ручное копирование файлов в контейнеры ЗАПРЕЩЕНО** — маскирует проблему
   до следующего `--force-recreate`, после которого "внезапно" всё откатывается.
2. **После каждого деплоя — smoke-тест**: curl-ом проверить что сервер отдаёт
   новую версию, ПРЕЖДЕ чем тестировать в браузере:

```bash
curl -s "http://155.212.143.179:8080/assets/saas_theme/js/saas_theme.js" | grep -c "<маркер новой версии>"
```

   Smoke-тест встроен в GitHub Actions (шаг после clear-cache).
3. **Кэши**: Frappe кэширует boot info (с версией `?v=N` из hooks.py) в Redis —
   `bench clear-cache` обязателен. Браузер кэширует сам файл — поэтому каждое
   изменение JS/CSS требует инкремента `?v=N` в `hooks.py`.

## История инцидента (2026-06-12)

Горизонтальная навигация "исчезла" после `--force-recreate`: рабочее состояние
было достигнуто ручным копированием файла в контейнер, а пересоздание контейнера
вернуло файл из образа. Это и есть причина запрета ручных копий.
