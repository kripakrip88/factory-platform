#!/bin/bash
# Развернуть Carbon (crbnos/carbon) как изолированный эксперимент на нашем сервере.
#
# Запускать НА СЕРВЕРЕ:  bash <путь>/experiments/carbon/install.sh
#
# Стек живёт в /opt/experiments/carbon — вне git-чекаута /opt/factory-platform,
# потому что деплой делает там `git reset --hard` и затёр бы .env и патчи.
#
# ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ ИХ ИНСТРУКЦИИ (contrib/deploying/simple-docker-caddy):
#   1. Образы НЕ собираются здесь — приходят готовыми из ghcr (см.
#      .github/workflows/build-carbon.yml). Их сборке нужно 8 ГБ heap, а рядом
#      работает боевой ERPNext.
#   2. scripts/harden.sh НЕ запускается НИКОГДА. Он ставит UFW «только SSH+80/443»
#      и отрезал бы 8080/8081/8082/5678 — прод, staging, WEM и n8n.
#   3. Caddy получает один порт 8083 вместо 80/443: эти порты держит infra-nginx.
#      TLS терминирует он, Caddy разводит по Host. См. patch-compose.py.
#   4. swarm init делается ЗАРАНЕЕ с явными подсетями: docker_gwbridge по умолчанию
#      берёт 172.18.0.0/16, а она уже занята нашей infra_default.
#   5. Миграции и seed гоняются из образа carbon-ops, а не carbon-erp: стадия
#      runner вырезает supabase CLI. И seed их deploy.sh не запускает вовсе, хотя
#      без него пустая таблица config и фронт не поднимется.
#
# Идемпотентно. Прод (erp), staging, WEM и infra не затрагиваются.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STACK_DIR="/opt/experiments/carbon"
SRC="$STACK_DIR/src"
UPSTREAM="$SRC/contrib/deploying/simple-docker-caddy"
ENV_FILE="$UPSTREAM/.env"
PATCHED="$STACK_DIR/docker-compose.prod.patched.yml"

REPO="https://github.com/crbnos/carbon.git"
# Пин — тот же коммит, из которого собраны образы в Actions.
CARBON_REF="7daffaaba2ec6196a0af9f76b22c188b05c67a00"

STACK_NAME="carbon"
CADDY_HTTP_PORT="8083"

# Подсети заняты: 172.17 (bridge), 172.18 (infra), 172.19 (erp), 172.20 (brain),
# 172.21 (erp-staging). Берём заведомо свободные.
GWBRIDGE_SUBNET="172.28.0.0/16"
SWARM_POOL="10.30.0.0/16"

OWNER="kripakrip88"
IMG_ERP="ghcr.io/$OWNER/carbon-erp:latest"
IMG_MES="ghcr.io/$OWNER/carbon-mes:latest"
IMG_OPS="ghcr.io/$OWNER/carbon-ops:latest"

failed=0
step() { printf '\n\033[1;36m── %s\033[0m\n' "$*"; }
ok()   { printf '   ✓ %s\n' "$*"; }
bad()  { printf '   ❌ %s\n' "$*"; failed=1; }
die()  { printf '\n❌ %s\n' "$*"; exit 1; }

echo "═══ Carbon: развёртывание ═══"

# ─── 0. Предохранители ───────────────────────────────────────────────────────
step "Проверки перед началом"

free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "${free_gb:-0}" -ge 12 ] || die "на / свободно ${free_gb} ГБ, нужно ≥ 12"
ok "диск ${free_gb} ГБ"

avail_mb=$(free -m | awk '/^Mem:/{print $7}')
[ "${avail_mb:-0}" -ge 5000 ] || die "доступно ${avail_mb} МБ RAM, нужно ≥ 5000 (Carbon по их докам минимум 4 ГБ)"
ok "RAM ${avail_mb} МБ"

if ss -tln 2>/dev/null | grep -q ":$CADDY_HTTP_PORT "; then
  die "порт $CADDY_HTTP_PORT занят"
fi
ok "порт $CADDY_HTTP_PORT свободен"

# Образы должны быть уже загружены воркфлоу build-carbon.yml
for img in "$IMG_ERP" "$IMG_MES" "$IMG_OPS"; do
  docker image inspect "$img" >/dev/null 2>&1 \
    || die "нет образа $img — сначала прогнать .github/workflows/build-carbon.yml"
done
ok "все три образа на месте"

# Боевые порты не должны пострадать — фиксируем, чтобы сверить в конце
before_prod=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:8080/api/method/ping || echo 000)
ok "прод до начала работ: $before_prod"

# ─── 1. Исходники ────────────────────────────────────────────────────────────
step "Исходники Carbon (нужны на хосте: bind-моунты kong.yml, edge-функций, init-скриптов postgres)"
mkdir -p "$STACK_DIR"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch -q --depth 1 origin "$CARBON_REF" 2>/dev/null || git -C "$SRC" fetch -q origin
  git -C "$SRC" checkout -q "$CARBON_REF" 2>/dev/null || true
else
  git clone -q --filter=blob:none "$REPO" "$SRC" || die "клон не удался"
  git -C "$SRC" checkout -q "$CARBON_REF" || die "не удалось переключиться на $CARBON_REF"
fi
ok "$(git -C "$SRC" rev-parse --short HEAD) $(git -C "$SRC" log -1 --format=%s | cut -c1-60)"

# Их скрипты bind-моунтятся в контейнеры и должны быть исполняемыми на хосте
chmod +x "$UPSTREAM/bin/secrets-entrypoint.sh" "$UPSTREAM/postgres/"*.sh "$UPSTREAM/scripts/"*.sh 2>/dev/null

# ─── 2. Swarm с явными подсетями ─────────────────────────────────────────────
step "Docker Swarm"
if [ "$(docker info --format '{{.Swarm.LocalNodeState}}')" = "active" ]; then
  ok "swarm уже активен"
else
  # docker_gwbridge создаём САМИ до вступления в swarm: иначе docker возьмёт
  # 172.18.0.0/16, занятую нашей infra_default (nginx, n8n, postgres).
  if ! docker network inspect docker_gwbridge >/dev/null 2>&1; then
    docker network create \
      --subnet "$GWBRIDGE_SUBNET" \
      --opt com.docker.network.bridge.name=docker_gwbridge \
      --opt com.docker.network.bridge.enable_icc=false \
      --opt com.docker.network.bridge.enable_ip_masquerade=true \
      docker_gwbridge >/dev/null || die "не удалось создать docker_gwbridge"
    ok "docker_gwbridge создан на $GWBRIDGE_SUBNET (не на дефолтной 172.18)"
  else
    ok "docker_gwbridge уже есть: $(docker network inspect docker_gwbridge --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')"
  fi
  docker swarm init \
    --advertise-addr 127.0.0.1 \
    --default-addr-pool "$SWARM_POOL" \
    --default-addr-pool-mask-length 24 >/dev/null || die "swarm init не удался"
  ok "swarm поднят, пул оверлейных сетей $SWARM_POOL"
fi

# Контроль: существующие стеки не должны пострадать
running=$(docker ps -q | wc -l)
ok "контейнеров запущено: $running"

# ─── 3. Патч compose (порты Caddy) ───────────────────────────────────────────
step "Патч их docker-compose.prod.yml"
python3 "$HERE/patch-compose.py" "$UPSTREAM/docker-compose.prod.yml" "$PATCHED" \
  || die "патч не применился — см. сообщение выше"

# ─── 4. .env ─────────────────────────────────────────────────────────────────
step "Конфигурация (.env)"
if [ -f "$ENV_FILE" ]; then
  ok ".env уже есть — не перезаписываю (там могли быть правки)"
else
  sed -e "s|@@CARBON_REPO@@|$SRC|g" \
      -e "s|@@IMG_ERP@@|$IMG_ERP|g" \
      -e "s|@@IMG_MES@@|$IMG_MES|g" \
      -e "s|@@IMG_OPS@@|$IMG_OPS|g" \
      -e "s|@@CADDY_HTTP_PORT@@|$CADDY_HTTP_PORT|g" \
      "$HERE/env.template" > "$ENV_FILE"

  # Ключи realtime: в их compose стоят ДЕФОЛТЫ, ЗАХАРДКОЖЕННЫЕ В ПУБЛИЧНОМ РЕПО
  # (DB_ENC_KEY=supabaserealtime и фиксированный SECRET_KEY_BASE). Стенд смотрит
  # в интернет, поэтому генерируем свои — их же комментарий это и советует.
  # DB_ENC_KEY у supabase/realtime должен быть РОВНО 16 байт (ключ AES).
  enc=$(openssl rand -hex 8)                       # 8 байт hex = 16 символов
  base=$(openssl rand -base64 48 | tr -d '\n')     # Phoenix secret_key_base
  sed -i "s|^REALTIME_DB_ENC_KEY=.*|REALTIME_DB_ENC_KEY=$enc|" "$ENV_FILE"
  sed -i "s|^REALTIME_SECRET_KEY_BASE=.*|REALTIME_SECRET_KEY_BASE=$base|" "$ENV_FILE"
  [ "${#enc}" -eq 16 ] || bad "REALTIME_DB_ENC_KEY длиной ${#enc}, а нужно ровно 16"

  chmod 600 "$ENV_FILE"
  ok "создан $ENV_FILE (ключи realtime сгенерированы, не дефолтные из их репо)"
fi

# ─── 5. Секреты (их deploy.sh init) ──────────────────────────────────────────
step "Секреты Swarm (их deploy.sh init — 11 секретов)"
( cd "$UPSTREAM" && bash ./deploy.sh init ) 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]:-1}" = 0 ] || bad "deploy.sh init вернул ошибку"

# ─── 6. Деплой стека ─────────────────────────────────────────────────────────
step "Разворачиваю стек (14 сервисов)"
set -a; . "$ENV_FILE"; set +a
docker stack deploy --detach=true --resolve-image always -c "$PATCHED" "$STACK_NAME" \
  || die "stack deploy не удался"
ok "стек $STACK_NAME отправлен в swarm"

# ─── 7. Ожидание готовности ──────────────────────────────────────────────────
wait_healthy() {
  local svc="$1" timeout="${2:-300}" name="${STACK_NAME}_$1" waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if docker ps --filter "label=com.docker.swarm.service.name=$name" \
                 --filter health=healthy -q | grep -q .; then
      ok "$name healthy (${waited}с)"; return 0
    fi
    sleep 5; waited=$((waited + 5))
  done
  bad "$name не стал healthy за ${timeout}с"
  return 1
}

step "Ждём базу и хранилище"
wait_healthy postgres 420 || die "postgres не поднялся — docker service logs ${STACK_NAME}_postgres"
wait_healthy storage 300 || bad "storage не поднялся"

# ─── 8. Миграции и seed — из образа OPS ──────────────────────────────────────
# Почему не их `deploy.sh migrate`: он гоняет supabase CLI из carbon-erp, а стадия
# runner этот CLI вырезает (в Dockerfile прямо перечислено `-name 'supabase@*'`).
run_job() {
  local job_name="$1" image="$2" workdir="$3" cmd="$4"; shift 4
  local job="${STACK_NAME}_${job_name}"
  docker service rm "$job" >/dev/null 2>&1
  docker service create \
    --name "$job" --mode replicated-job --detach \
    --network "${STACK_NAME}_internal" \
    --restart-condition on-failure --restart-max-attempts 5 \
    --env PGSSLMODE=disable \
    --workdir "$workdir" \
    "$@" \
    "$image" sh -c "$cmd" >/dev/null || { bad "не удалось создать job $job"; return 1; }

  local waited=0 states
  while [ "$waited" -lt 900 ]; do
    states=$(docker service ps "$job" --format '{{.CurrentState}}' 2>/dev/null)
    printf '%s\n' "$states" | grep -q '^Complete' && {
      ok "$job_name выполнен (${waited}с)"; docker service rm "$job" >/dev/null 2>&1; return 0; }
    if ! printf '%s\n' "$states" | grep -qE '^(Running|Ready|Preparing|Assigned|Starting|New|Pending|Accepted)' \
       && printf '%s\n' "$states" | grep -qE '^(Failed|Rejected)'; then
      bad "$job_name упал. Логи:"; docker service logs "$job" 2>&1 | tail -40 | sed 's/^/      /'
      docker service rm "$job" >/dev/null 2>&1; return 1
    fi
    sleep 5; waited=$((waited + 5))
  done
  bad "$job_name не завершился за 900с"; docker service logs "$job" 2>&1 | tail -30 | sed 's/^/      /'
  docker service rm "$job" >/dev/null 2>&1; return 1
}

step "Миграции схемы (из образа OPS)"
run_job migrate "$IMG_OPS" /repo/packages/database \
  'pnpm exec supabase migration up --include-all --db-url "postgresql://supabase_admin:$(cat /run/secrets/postgres_password)@postgres:5432/postgres"' \
  --secret postgres_password \
  || die "миграции не прошли — дальше идти нельзя"

step "Seed (config + тарифы) — их deploy.sh этого НЕ делает, без него фронт пустой"
# SUPABASE_URL здесь внутрисетевой (kong:8000): публичный поддомен из контейнера
# ещё не резолвится. Публичный apiUrl для браузера выставим отдельным шагом,
# когда появятся DNS-записи и nginx.
run_job seed "$IMG_OPS" /repo/packages/database \
  'SUPABASE_SERVICE_ROLE_KEY=$(cat /run/secrets/service_role_key) SUPABASE_ANON_KEY=$(cat /run/secrets/anon_key) SUPABASE_URL=http://kong:8000 pnpm run db:seed' \
  --secret service_role_key --secret anon_key \
  || bad "seed не прошёл — фронт может не подняться"

# ─── 9. Перекатить приложения (схема появилась после их старта) ──────────────
step "Перекатываю erp и mes"
for s in erp mes; do
  docker service update --force --detach "${STACK_NAME}_${s}" >/dev/null 2>&1 \
    && ok "$s перекатан" || bad "$s перекатать не удалось"
done

wait_healthy erp 420 || bad "erp не стал healthy"
wait_healthy mes 420 || bad "mes не стал healthy"
wait_healthy caddy 180 || bad "caddy не стал healthy"

# ─── 10. Итог + контроль, что прод цел ───────────────────────────────────────
step "Состояние стека"
docker stack services "$STACK_NAME" --format 'table {{.Name}}\t{{.Replicas}}\t{{.Image}}' 2>/dev/null | head -20

step "Проверка маршрутизации (DNS ещё может не быть — идём через заголовок Host)"
for pair in "carbon.erppark.ru:ERP" "mes.erppark.ru:MES" "api.erppark.ru:Supabase"; do
  host="${pair%%:*}"; label="${pair##*:}"
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 -H "Host: $host" "http://127.0.0.1:$CADDY_HTTP_PORT/" || echo 000)
  printf '   %-10s (%s) → HTTP %s\n' "$label" "$host" "$code"
done

step "Ничего боевого не пострадало?"
for p in 8080:прод 8081:staging 8082:WEM; do
  port="${p%%:*}"; label="${p##*:}"
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "http://127.0.0.1:$port/" || echo 000)
  printf '   %-8s :%s → HTTP %s\n' "$label" "$port" "$code"
done
free -h | sed -n 2p | sed 's/^/   /'
df -h / | tail -1 | sed 's/^/   /'

echo
if [ "$failed" = 0 ]; then
  echo "═══ ✅ Carbon развёрнут ═══"
else
  echo "═══ ⚠️  Carbon развёрнут С ЗАМЕЧАНИЯМИ (см. ❌ выше) ═══"
fi
cat <<INFO

Дальше нужны DNS-записи (A → 155.212.143.179):
   carbon.erppark.ru   mes.erppark.ru   api.erppark.ru
После них — nginx + сертификаты и правка config.apiUrl на публичный адрес.

Управление (из $STACK_DIR):
   docker stack services $STACK_NAME
   docker service logs ${STACK_NAME}_erp --tail 50
   docker stack rm $STACK_NAME            # снять стек (тома останутся)
INFO
[ "$failed" = 0 ] || exit 1
