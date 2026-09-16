# Carbon — эксперимент (оценка)

**Что это.** [crbnos/carbon](https://github.com/crbnos/carbon) — открытая ERP/MES/QMS
для производства. TypeScript/React Router + полный дата-план Supabase (Postgres, GoTrue,
Kong, PostgREST, Realtime, Storage, Studio, edge-runtime) + Redis + Inngest. 2412★,
коммиты ежедневно.

**Зачем.** Антон хочет посмотреть вживую и сравнить с ERPNext + saas_theme. Это
**оценка, не внедрение**.

**Статус.** Ветка `feature/experiment-carbon`, в `develop` не вливается без решения Антона.

---

## ⚠️ Лицензия — прочитать до того, как решать о внедрении

В их `LICENSE` дословно: *«любое использование этого ПО для внутреннего продакшена
строго запрещено, если только изменения не открыты под AGPLv3 либо не приобретена
коммерческая лицензия»*. Отдельно: всё в `packages/ee` и файлы с `.ee` требуют
коммерческой лицензии.

Для оценки это не мешает. Но если система понравится и завод начнёт на ней работать —
это либо публикация своих доработок под AGPLv3, либо деньги. У ERPNext (GPL) и
WebErpMesv2 (MIT) такого ограничения нет. **Это стоит учитывать при сравнении, а не
только интерфейс.**

Прямое следствие для нас: **образы приватные и должны такими остаться.** Их Dockerfile
копирует `packages` целиком, включая `packages/ee` → публикация образа = распространение
ee-кода.

---

## Что сделано иначе, чем в их инструкции

Их `contrib/deploying/simple-docker-caddy` рассчитан на **пустой** VPS. У нас на машине
уже живут боевой ERPNext, staging, n8n и WEM. Пять отличий:

| Их способ | Наш | Почему |
|---|---|---|
| `deploy.sh build` собирает образы на сервере | Сборка в **GitHub Actions** → `ghcr.io` → на сервер только `pull` | В их Dockerfile `NODE_OPTIONS=--max-old-space-size=8024`: сборке нужно 8 ГБ heap. На VPS 11 ГБ всего, рядом боевой ERPNext. В июле 2026 ровно такая сборка (Frappe CRM) дала load 185 и положила прод |
| `scripts/harden.sh` (рекомендован) | **Не запускается никогда** | Ставит UFW «только SSH + 80/443» → отрезал бы 8080, 8081, 8082, 5678: прод, staging, WEM, n8n |
| Caddy берёт 80/443/443udp в `mode: host` | Caddy получает **один порт 8083**, TLS терминирует наш `infra-nginx` | 80/443 держит infra-nginx для `erppark.ru`. В `.env` хосты с префиксом `http://` → Caddy не включает свой ACME. Маршрутизацию по Host и заголовки безопасности у Caddy сохраняем |
| `deploy.sh init` делает `docker swarm init` без параметров | swarm поднимается **заранее с явными подсетями** | `docker_gwbridge` по умолчанию берёт `172.18.0.0/16`, а она занята нашей `infra_default`. Берём `172.28.0.0/16` и пул оверлеев `10.30.0.0/16` |
| `migrate` гоняет supabase CLI из образа `carbon-erp` | Отдельный образ **`carbon-ops`** (стадия `ops`) | Стадия `pruned`, из которой собран `runner`, вырезает supabase CLI (в Dockerfile прямо `-name 'supabase@*'`). Стадия `ops` заведена у них ровно под migrate/seed и CLI сохраняет — расхождение внутри их же репозитория |
| seed не запускается вовсе | Запускаем `db:seed` из `carbon-ops` | Их `seed.ts` заполняет таблицу `config` (apiUrl + anonKey) и тарифы. Без неё фронт не поднимется |

Плюс мелочь по гигиене: ключи `REALTIME_DB_ENC_KEY` и `REALTIME_SECRET_KEY_BASE` в их
compose имеют **дефолты, захардкоженные в публичном репозитории**. Стенд смотрит наружу,
поэтому `install.sh` генерирует свои (их собственный комментарий это и советует).

## Изоляция

| | |
|---|---|
| Стек swarm | `carbon` (14 сервисов) |
| Порт наружу | только `8083` (Caddy), остальное в оверлейной сети |
| Подсети | `docker_gwbridge` 172.28.0.0/16, оверлеи 10.30.0.0/16 — не пересекаются с 172.17–172.21 |
| Файлы стека | `/opt/experiments/carbon` — вне git-чекаута, деплой его не трёт |
| Что НЕ тронуто | `services/erp/**`, `infra/**`, прод, staging, WEM, n8n |
| Postgres | урезан против их дефолтов: лимит 1536M, shared_buffers 384MB (рядом боевая MariaDB) |

## Порядок развёртывания

### 1. Собрать образы (GitHub Actions)

Пуш в `feature/experiment-carbon` с изменением `.github/workflows/build-carbon.yml`
запускает сборку. Собираются три образа и сами доставляются на сервер по SSH
(логин в ghcr эфемерным `GITHUB_TOKEN` — на сервере не остаётся долгоживущих кредов).

### 2. Развернуть стек

```bash
ssh factory 'cd /opt/factory-platform && git fetch -q origin feature/experiment-carbon \
  && rm -rf /tmp/carbon-stage && mkdir -p /tmp/carbon-stage \
  && git archive origin/feature/experiment-carbon experiments/carbon \
     | tar -x -C /tmp/carbon-stage --strip-components=2 \
  && bash /tmp/carbon-stage/install.sh'
```

Скрипт идемпотентен и перед началом проверяет: диск ≥ 12 ГБ, RAM ≥ 5 ГБ, порт 8083
свободен, все три образа на месте. Иначе отказывается стартовать.

### 3. DNS — нужны три записи (это делает Антон)

A-записи на `155.212.143.179`:

```
carbon.erppark.ru      mes.erppark.ru      api.erppark.ru
```

Wildcard у домена нет, проверено. `api.` обязателен: браузер обращается к шлюзу
Supabase напрямую, это не внутренний адрес.

### 4. Сертификат и nginx (после DNS)

Текущий SAN-серт покрывает 4 имени (`erppark.ru`, `www`, `d`, `n8n`) — расширить до 7:

```bash
ssh factory 'docker run --rm \
  -v infra_certbot_conf:/etc/letsencrypt -v infra_certbot_www:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot --expand --non-interactive \
  --cert-name erppark.ru \
  -d erppark.ru -d www.erppark.ru -d d.erppark.ru -d n8n.erppark.ru \
  -d carbon.erppark.ru -d mes.erppark.ru -d api.erppark.ru'
```

Затем три `server`-блока в `infra/nginx/nginx.conf`, все на `host.docker.internal:8083`
(Caddy сам разведёт по Host). Заголовки `Host $host` и `X-Forwarded-Proto $scheme` там
уже стоят глобально — именно то, что нужно. **Это правка `infra/**`, то есть интеграция
в основной стек → только по явному согласованию с Антоном.**

### 5. Публичный apiUrl и первый пользователь

Seed при установке пишет `config.apiUrl` как внутренний `http://kong:8000` (публичный
поддомен из контейнера ещё не резолвится). После настройки nginx — заменить на
`https://api.erppark.ru`. Первого пользователя заводим напрямую в БД: регистрация
закрыта (`GOTRUE_DISABLE_SIGNUP=true`), почты у стенда нет.

## Проверка без DNS

Пока записей нет, маршрутизация проверяется заголовком Host:

```bash
ssh factory 'curl -s -o /dev/null -w "%{http_code}\n" -H "Host: carbon.erppark.ru" http://127.0.0.1:8083/'
```

## Управление

```bash
docker stack services carbon
docker service logs carbon_erp --tail 50
docker stack rm carbon          # снять стек (тома остаются)
```

## Открытые вопросы

- Stripe / Resend / PostHog / Google OAuth — ключи не заведены. Биллинг, почта и
  аналитика работать не будут; для оценки не требуются.
- Rust-сервис геометрии (CAD/коллизии) из `crates/` не собирается — по их же словам
  ERP/MES работают без него.
- Studio (админка БД) не публикуется: у неё нет своей аутентификации. База — через
  `ssh` + `docker exec psql`.

---

## Вход: важное про магические ссылки

**У Carbon НЕТ входа по паролю.** Их `AUTH_PROVIDERS` принимает только
`email,google,azure,passkey`, где `email` — это magic link. Пароль в GoTrue при этом
работает (`grant_type=password` отдаёт токен), но интерфейс Carbon его не предлагает.

Почта у стенда не настроена → письмо со ссылкой не приходит. Пока это так, ссылку
нужно генерировать вручную:

```bash
ssh factory '
C=$(docker ps --filter "name=carbon_storage" --format "{{.Names}}" | head -1)
KEY=$(docker exec "$C" cat /run/secrets/service_role_key)
echo "{\"type\":\"magiclink\",\"email\":\"admin@erppark.ru\"}" > /tmp/gl.json
docker run --rm --network carbon_internal -v /tmp/gl.json:/d.json:ro curlimages/curl:latest \
  -s -X POST http://kong:8000/auth/v1/admin/generate_link \
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  --data @/d.json'
```

⚠️ В `action_link` из ответа GoTrue **отсутствует префикс `/auth/v1`** (следствие того,
как задан его EXTERNAL_URL). Рабочий вид ссылки:

```
https://api.erppark.ru/auth/v1/verify?token=<ТОКЕН>&type=magiclink&redirect_to=https://carbon.erppark.ru/callback
```

Токен одноразовый.

### Почему НЕ включён DEV_BYPASS_EMAIL

В их `login.tsx` есть переменная `DEV_BYPASS_EMAIL`: если она равна адресу, вход
происходит **вообще без проверки** — достаточно ввести этот адрес на странице входа.
Стенд открыт в интернет, поэтому включать нельзя ни при каких условиях.

### Как сделать нормально

Настроить SMTP для GoTrue — тогда ссылки будут приходить письмом и костыль не нужен:

1. В `.env` заполнить `GOTRUE_SMTP_HOST`, `GOTRUE_SMTP_PORT`, `GOTRUE_SMTP_USER`,
   `GOTRUE_SMTP_ADMIN_EMAIL`.
2. Пароль положить секретом Swarm (его набирает владелец ящика, не Claude):
   ```bash
   cd /opt/experiments/carbon/src/contrib/deploying/simple-docker-caddy
   printf '%s' 'ПАРОЛЬ' | bash ./deploy.sh secret smtp_password
   ```
3. `docker service update --force carbon_gotrue`

## Первичная настройка выполнена

Мастер онбординга пройден целиком (тема → пользователь → компания). Создано:

| | |
|---|---|
| Компания | `PMK Park`, Khabarovsk, RU |
| Валюта | **RUB** |
| Часовой пояс | Asia/Vladivostok (GMT+10) — определился сам, верно |
| Сайт | pmkpark.ru |
| Пользователь | Anton Karneev, `admin@erppark.ru`, активен, привязан сотрудником |

⚠️ **Адрес и индекс — заглушки:** `addressLine1 = "TBD - уточнить"`, `postalCode = 680000`
(общий индекс Хабаровска). Реального адреса завода я не знаю и выдумывать его не стал —
поправить в настройках компании.

### Грабли их интерфейса (если придётся повторять)

Комбобоксы Carbon (страна, валюта) не принимают синтетический ввод: значение задваивается,
Backspace не удаляет, а type-ahead в открытом списке молча меняет уже выбранное на другое
(так страна дважды становилась Angola). Надёжно работает установка значения через нативный
сеттер `HTMLInputElement.prototype.value` + `input`-событие — в том числе для скрытого поля
`baseCurrencyCode`, через которое и была выставлена RUB.
