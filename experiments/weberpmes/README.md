# WebErpMesv2 — эксперимент (оценка)

**Что это.** [SMEWebify/WebErpMesv2](https://github.com/SMEWebify/WebErpMesv2) — открытая
ERP/MES для механообработки и производства. Laravel 12 / PHP 8.2 / MySQL 8 / Redis,
фронт на React 19 + Blade, лицензия **MIT**. Проект живой (215★, коммиты ежедневно).

**Зачем.** Антон хочет посмотреть систему вживую на своих данных и сравнить с нашей
связкой ERPNext + saas_theme. Это **оценка, не внедрение** — ни одна часть платформы
от этого не зависит.

**Статус.** Развёрнуто на сервере как изолированный стек. Ветка
`feature/experiment-weberpmes`, в `develop` не вливается без решения Антона.

## Изоляция — что гарантировано

По принципу изоляции модулей из `CLAUDE.md`:

| | |
|---|---|
| Проект docker | `wem` (контейнеры `wem-*`) |
| Порт наружу | только `8082` (8080 прод, 8081 staging — не заняты) |
| Тома | `wem_db_data`, `wem_vendor`, `wem_node_modules` — свои |
| Сеть | своя, `wem_default` |
| Исходники | `/opt/experiments/weberpmes/src` — **вне нашего репозитория** |
| Стек (compose/.env) | `/opt/experiments/weberpmes` — вне git-чекаута, деплой его не трёт |
| Потолки памяти | app 1 ГБ, db 768 МБ, worker 512 МБ, nginx/redis по 128 МБ |
| Что НЕ тронуто | `services/erp/**`, `infra/**`, прод, staging, n8n |

Потолки памяти (`mem_limit`) стоят намеренно: эксперимент физически не сможет
выесть память у боевого ERPNext.

## Почему их собственный docker-compose.yaml не используется

В апстримном `docker-compose.yaml` четыре дефекта — с ним стек не поднимется
или поднимется небезопасно:

1. **Сервис `worker` не стартует вообще.** Объявляет `depends_on: redis, db`, а сервисы
   называются `redis-dev` и `db-dev` → `docker compose up` падает с
   «service worker depends on undefined service».
2. **`worker` монтирует код не туда** — `.:/var/www/html`, хотя приложение живёт в `/app`.
   Даже если поправить зависимости, воркер работал бы в пустом каталоге.
3. **Redis и Echo нараспашку.** `redis-dev` публикует `6379:6379`, `laravel-echo-server` —
   `6001:6001`. На машине с публичным IP это открытый наружу Redis без пароля.
4. **Vite-ассеты не собираются.** В `Dockerfile` есть `npm ci`, но нет `npm run build`,
   а их `entrypoint.sh` пропускает сборку, если `node_modules` непустой (а он непустой —
   приходит из образа). Итог: `public/build` пустой, фронт битый.

Наш `docker-compose.yml` всё это исправляет, плюс убирает публикацию портов БД,
добавляет healthcheck на MySQL и потолки памяти. `echo` вынесен в профиль `realtime`
(по умолчанию не запускается — для оценки не нужен, а их вариант тянет node:16 EOL).

## Запуск

Стек живёт в `/opt/experiments/weberpmes` — **специально вне** git-чекаута
`/opt/factory-platform`, потому что деплой делает там `git reset --hard` и затёр бы
файлы эксперимента вместе с `.env` (паролями БД). `install.sh` сам раскладывает туда
compose и конфиг nginx.

```bash
# выложить файлы ветки на сервер и развернуть
ssh factory 'cd /opt/factory-platform && git fetch -q origin feature/experiment-weberpmes \
  && rm -rf /tmp/wem-stage && mkdir -p /tmp/wem-stage \
  && git archive origin/feature/experiment-weberpmes experiments/weberpmes \
     | tar -x -C /tmp/wem-stage --strip-components=2 \
  && bash /tmp/wem-stage/install.sh'
```

Скрипт идемпотентный: раскладывает стек, генерирует пароли в `.env` (один раз,
`chmod 600`, при повторе НЕ перегенерирует — иначе БД перестанет пускать),
клонирует/обновляет исходники, собирает образ, поднимает стек, дособирает
vite-ассеты. Перед работой проверяет диск ≥ 8 ГБ, RAM ≥ 1.5 ГБ и что порт 8082
свободен — иначе отказывается стартовать, чтобы не задеть прод.

Открыть: **http://155.212.143.179:8082**

### Управление

```bash
cd /opt/experiments/weberpmes

docker compose stop      # остановить, освободить RAM (данные целы)
docker compose start     # поднять снова
docker compose logs -f app
docker compose down -v   # снести вместе с БД
```

### Запуск вручную (если не через install.sh)

`docker compose` сам читает `.env` из этой папки, поэтому достаточно:

```bash
cd /opt/experiments/weberpmes && docker compose up -d
```

## Ресурсы

Фактическое потребление в покое — около 0.8 ГБ (php-fpm ~200 МБ, MySQL ~400 МБ,
остальное мелочь). Сборка образа — самая тяжёлая часть: `npm ci` для React 19 +
three.js + OpenCascade WASM. На фоне боевого ERPNext (990 МБ) при 7.8 ГБ на машине
это помещается без остановки прода.

## Открытые вопросы

- Логин администратора создаётся их сидером `CreateAdminUserSeeder` — посмотреть
  в их репозитории, какие там креды по умолчанию, и **сменить пароль сразу после входа**
  (порт 8082 открыт наружу).
- Русификации нет; интерфейс английский/французский. Для оценки это не мешает.
- Если система понравится — следующий шаг вынести на поддомен `wem.erppark.ru`
  через `infra-nginx` + certbot, а не держать открытым порт.
