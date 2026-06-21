# Среды: PROD и STAGING

Один сервер (Beget VPS `155.212.143.179`), две изолированные среды на разных портах,
с раздельными БД/томами/redis/сетью. Эксперименты в staging не видят сотрудники и не
ломают боевые данные.

## Схема

| | PROD (боевая) | STAGING (тестовая) |
|---|---|---|
| Кто работает | Сотрудники | Claude Code пилит, Антон проверяет |
| Ветка | `main` | `develop` |
| Порт | `:8080` | `:8081` |
| URL | http://155.212.143.179:8080 | http://155.212.143.179:8081 |
| Compose | `services/erp/docker-compose.yml` | `services/erp/docker-compose.staging.yml` |
| Проект (docker) | `erp` | `erp-staging` |
| Контейнеры | `erp-*` (erp-backend-1 …) | `erp-staging-*` |
| Тома | `erp_db_data`, `erp_sites`, `erp_assets`, `erp_redis_*`, `erp_logs` | `erp-staging_db_data`, `erp-staging_sites`, `erp-staging_assets`, `erp-staging_redis_*`, `erp-staging_logs` |
| Почта | боевой ящик `pmkpark@mail.ru` (вкл) | ⚠️ боевой ящик ВЫКЛЮЧЕН; свой тестовый ящик — позже |

Сайт в обеих средах называется `erp.localhost`, логическое имя БД одинаковое
(`_96a0525548ff990d`) — это артефакт клона, НО инстансы MariaDB, тома и docker-сети
**физически разные** → данные не пересекаются (доказано: маркер из staging в prod-БД = 0).

## Деплой

- Пуш в `develop` → автодеплой **staging** (`.github/workflows/deploy-erp.yml`, ветка-зависимая логика).
- Пуш в `main` → деплой **prod**, ТОЛЬКО по явному подтверждению Антона.
- Пуш в `develop` НЕ может задеть prod: другой проект/контейнеры/тома/порт.
- Workflow выбирает среду по `github.ref_name` (main→prod, иначе→staging) и гоняет
  backup→build→up→migrate→clear-cache→flush-redis→version-check→smoke против нужного порта.

## ⚠️ Почта (критично)

- Боевой ящик `pmkpark@mail.ru` обрабатывает ТОЛЬКО prod.
- Staging НИКОГДА не подключается к боевому ящику (иначе два инстанса в одном ящике =
  перехват писем, дубли классификации, риск отправки клиенту из теста).
- После любого клона prod→staging Email Account в staging автоматически выключается
  (`enable_incoming/outgoing=0`) — см. скрипт клонирования.
- Тестовая почта на staging — через ОТДЕЛЬНЫЙ тестовый ящик (Антон заведёт, введёт пароль сам),
  переиспользуя готовый код почтовой настройки (классификатор, папки, имена, направление, TZ).

## Копирование prod → staging (для отладки на реальных данных)

Разово, по требованию, на сервере из `/opt/factory-platform`:

```bash
bash services/erp/scripts/clone-prod-to-staging.sh
```

Делает: свежий бэкап prod (читает, не трогает) → restore в staging → выравнивание
site-юзера → **выключение боевого ящика в staging** → clear-cache. Идемпотентно.

## Откат

- **Staging целиком снести:** `docker compose -p erp-staging -f services/erp/docker-compose.staging.yml down -v`
  (тома `erp-staging_*` удаляются; prod не затронут). Поднять заново — см. ниже.
- **Prod откат кода:** `git checkout <tag>` в `main` → деплой; перед этим бэкап
  (workflow делает сам). Серверные изменения (Property Setter, Email Account) тег не откатывает.
- **Бэкап перед разделением:** тег `v1.0.13-pre-split`; дампы `/opt/backups/presplit-*.tgz`
  + bench-бэкап `20260621_124440` в `erp_sites/.../private/backups`.

## Поднять STAGING с нуля (если снесли)

Из `/opt/factory-platform` (детали — в истории этого ТЗ / скрипте клона):

```bash
docker compose -p erp-staging -f services/erp/docker-compose.staging.yml build
docker volume create erp-staging_sites; docker volume create erp-staging_assets
docker run --rm -v erp_sites:/from:ro   -v erp-staging_sites:/to   alpine sh -c "cp -a /from/. /to/"
docker run --rm -v erp_assets:/from:ro  -v erp-staging_assets:/to  alpine sh -c "cp -a /from/. /to/"
docker compose -p erp-staging -f services/erp/docker-compose.staging.yml up -d db redis-cache redis-queue redis-socketio
# затем: bash services/erp/scripts/clone-prod-to-staging.sh   (restore + выключение ящика)
docker compose -p erp-staging -f services/erp/docker-compose.staging.yml up -d
```
