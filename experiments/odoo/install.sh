#!/bin/bash
# Развернуть Odoo 19 Community + RuOdoo как изолированный эксперимент.
#
# Запускать НА СЕРВЕРЕ из любого места:
#   bash <путь>/experiments/odoo/install.sh
#
# Стек разворачивается в /opt/experiments/odoo — СПЕЦИАЛЬНО вне git-чекаута
# /opt/factory-platform: деплой делает там `git reset --hard` и затёр бы .env с паролями.
#
# Идемпотентно. Прод (erp), staging, WEM, Carbon и infra НЕ затрагиваются.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STACK_DIR="/opt/experiments/odoo"
RUODOO_SRC="$STACK_DIR/ruodoo"
ENV_FILE="$STACK_DIR/.env"
DB_NAME="odoo"
PORT=8084

RUODOO_REPO="https://git.ruodoo.ru/ruodoo-public/public.git"

failed=0
step() { printf '\n\033[1;36m── %s\033[0m\n' "$*"; }
ok()   { printf '   ✓ %s\n' "$*"; }
bad()  { printf '   ❌ %s\n' "$*"; failed=1; }
die()  { printf '\n❌ %s\n' "$*"; exit 1; }

echo "═══ Odoo 19 Community + RuOdoo ═══"

# ─── 0. Предохранители ───────────────────────────────────────────────────────
step "Проверки"
free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[ "${free_gb:-0}" -ge 8 ] || die "на / свободно ${free_gb} ГБ, нужно ≥ 8"
avail_mb=$(free -m | awk '/^Mem:/{print $7}')
[ "${avail_mb:-0}" -ge 3000 ] || die "доступно ${avail_mb} МБ RAM, нужно ≥ 3000"
ss -tln 2>/dev/null | grep -q ":$PORT " && die "порт $PORT занят"
ok "диск ${free_gb} ГБ · RAM ${avail_mb} МБ · порт $PORT свободен"

prod_before=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:8080/api/method/ping || echo 000)
ok "прод до начала: $prod_before"

# ─── 1. Разложить стек вне git-чекаута ──────────────────────────────────────
step "Раскладываю стек в $STACK_DIR"
mkdir -p "$STACK_DIR"
cp "$HERE/docker-compose.yml" "$STACK_DIR/docker-compose.yml"
ok "compose на месте"

# ─── 2. Пароли ───────────────────────────────────────────────────────────────
step "Конфигурация"
if [ -f "$ENV_FILE" ]; then
  ok ".env уже есть — пароли не перегенерирую (иначе БД перестанет пускать)"
else
  {
    echo "RUODOO_SRC=$RUODOO_SRC"
    echo "ODOO_DB_USER=odoo"
    echo "ODOO_DB_PASSWORD=$(openssl rand -hex 16)"
    echo "ODOO_ADMIN_PASSWD=$(openssl rand -hex 16)"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "создан $ENV_FILE"
fi
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

# odoo.conf рендерим с мастер-паролем (он не должен лежать в git)
sed "s|__ADMIN_PASSWD__|${ODOO_ADMIN_PASSWD}|" "$HERE/odoo.conf" > "$STACK_DIR/odoo.conf"
chmod 600 "$STACK_DIR/odoo.conf"
ok "odoo.conf отрендерен (мастер-пароль подставлен, в git его нет)"

# ─── 3. RuOdoo ───────────────────────────────────────────────────────────────
step "Российская локализация RuOdoo"
if [ -d "$RUODOO_SRC/.git" ]; then
  git -C "$RUODOO_SRC" pull --ff-only -q 2>/dev/null || echo "   ⚠️ обновить не удалось, работаю на текущей копии"
else
  git clone -q --depth 1 "$RUODOO_REPO" "$RUODOO_SRC" || die "не удалось склонировать RuOdoo"
fi
ok "$(ls -d "$RUODOO_SRC"/*/ 2>/dev/null | wc -l) модулей, $(git -C "$RUODOO_SRC" log --oneline -1 | cut -c1-50)"
# Odoo читает каталог модулей от своего пользователя — права должны позволять
chmod -R a+rX "$RUODOO_SRC" 2>/dev/null

# ─── 4. Запуск ───────────────────────────────────────────────────────────────
cd "$STACK_DIR"
step "Поднимаю контейнеры"
docker compose up -d 2>&1 | tail -4
ok "контейнеры запущены"

step "Жду готовности Postgres"
ready=0
for _ in $(seq 1 40); do
  docker compose exec -T db pg_isready -U "$ODOO_DB_USER" >/dev/null 2>&1 && { ready=1; break; }
  sleep 3
done
[ "$ready" = 1 ] && ok "Postgres готов" || bad "Postgres не поднялся"

# ─── 5. Создание базы ────────────────────────────────────────────────────────
# Создаём базу через CLI, а не через веб-мастер: в конфиге list_db = False,
# менеджер баз наружу не отдаётся (стенд смотрит в интернет).
step "База данных «$DB_NAME»"
if docker compose exec -T db psql -U "$ODOO_DB_USER" -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "$DB_NAME"; then
  ok "база уже существует — не пересоздаю"
else
  echo "   инициализация (base + русский язык), это несколько минут…"
  docker compose run --rm -T odoo \
    odoo -d "$DB_NAME" -i base --load-language=ru_RU --without-demo=all --stop-after-init \
    >/tmp/odoo-init.log 2>&1 \
    && ok "база создана" \
    || { bad "инициализация не удалась"; tail -20 /tmp/odoo-init.log | sed 's/^/      /'; }
fi

# ─── 6. Модули ───────────────────────────────────────────────────────────────
# Ставим то, что нужно заводу: продажи, закупки, склад, производство, CRM, бухгалтерия,
# проекты — плюс российскую локализацию.
step "Установка модулей"
BASE_MODULES="crm,sale_management,purchase,stock,mrp,mrp_account,account,project,hr,maintenance,repair,uom,contacts"
RU_MODULES="l10n_ru_base,l10n_ru_doc,l10n_ru_upd_xml,l10n_ru_act_rev,l10n_ru_attorney,l10n_ru_advance_payments,l10n_ru_contract"

echo "   базовые: $BASE_MODULES"
docker compose run --rm -T odoo \
  odoo -d "$DB_NAME" -i "$BASE_MODULES" --stop-after-init \
  >/tmp/odoo-mods.log 2>&1 \
  && ok "базовые модули установлены" \
  || { bad "часть базовых модулей не встала"; grep -iE 'error|critical' /tmp/odoo-mods.log | tail -8 | sed 's/^/      /'; }

echo "   российские: $RU_MODULES"
docker compose run --rm -T odoo \
  odoo -d "$DB_NAME" -i "$RU_MODULES" --stop-after-init \
  >/tmp/odoo-ru.log 2>&1 \
  && ok "RuOdoo установлен" \
  || { bad "часть модулей RuOdoo не встала — см. ниже"; grep -iE 'error|critical|not found' /tmp/odoo-ru.log | tail -10 | sed 's/^/      /'; }

step "Перезапуск приложения"
docker compose restart odoo >/dev/null 2>&1 && ok "перезапущен"

# ─── 7. Проверка ─────────────────────────────────────────────────────────────
step "Проверка"
code=000
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "http://127.0.0.1:$PORT/web/login" || echo 000)
  [ "$code" = 200 ] && break
  sleep 4
done
[ "$code" = 200 ] && ok "Odoo отвечает (HTTP $code)" || bad "Odoo не отвечает (HTTP $code) — docker compose logs odoo"

step "Прод и соседи целы?"
for p in 8080:прод 8081:staging 8082:WEM 8083:Carbon; do
  printf '   %-9s :%s → %s\n' "${p##*:}" "${p%%:*}" \
    "$(curl -s -o /dev/null -w '%{http_code}' -m 12 "http://127.0.0.1:${p%%:*}/" || echo 000)"
done
free -h | sed -n 2p | sed 's/^/   /'
df -h / | tail -1 | sed 's/^/   /'

echo
if [ "$failed" = 0 ]; then echo "═══ ✅ Odoo развёрнут ═══"; else echo "═══ ⚠️  Развёрнут С ЗАМЕЧАНИЯМИ ═══"; fi
cat <<INFO

Открыть: http://155.212.143.179:$PORT
Логин при первом входе создаётся мастером настройки Odoo.
Мастер-пароль баз (для служебных операций) — в $ENV_FILE, переменная ODOO_ADMIN_PASSWD.

Управление (из $STACK_DIR):
  docker compose stop / start
  docker compose logs -f odoo
  docker compose down -v      # снести вместе с базой
INFO
[ "$failed" = 0 ] || exit 1
