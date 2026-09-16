#!/bin/bash
# Развернуть WebErpMesv2 как изолированный эксперимент на сервере.
#
# Запускать НА СЕРВЕРЕ из любого места:
#   bash <путь>/experiments/weberpmes/install.sh
#
# Стек разворачивается в /opt/experiments/weberpmes — СПЕЦИАЛЬНО вне git-чекаута
# /opt/factory-platform, потому что деплой делает там `git reset --hard` и затёр бы
# файлы эксперимента (а вместе с ними .env с паролями БД).
#
# Идемпотентно. Прод (erp), staging (erp-staging) и infra НЕ затрагиваются.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
STACK_DIR="/opt/experiments/weberpmes"
SRC="$STACK_DIR/src"
ENV_FILE="$STACK_DIR/.env"
REPO="https://github.com/SMEWebify/WebErpMesv2.git"

echo "═══ WebErpMesv2: развёртывание ═══"

# ─── 0. Предохранители: не начинать, если ресурсов мало ──────────────────────
free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "${free_gb:-0}" -lt 8 ]; then
  echo "❌ ОТМЕНА: на / свободно ${free_gb} ГБ, нужно ≥ 8 (образы ~3.5 ГБ + сборка)"
  exit 1
fi
avail_mb=$(free -m | awk '/^Mem:/{print $7}')
if [ "${avail_mb:-0}" -lt 1500 ]; then
  echo "❌ ОТМЕНА: доступно ${avail_mb} МБ RAM, нужно ≥ 1500 (сборка vite)"
  echo "   Освободить, остановив staging:"
  echo "   docker compose -p erp-staging -f /opt/factory-platform/services/erp/docker-compose.staging.yml stop"
  exit 1
fi
if ss -tln 2>/dev/null | grep -q ':8082 '; then
  echo "❌ ОТМЕНА: порт 8082 уже занят"
  exit 1
fi
echo "✓ диск ${free_gb} ГБ · RAM ${avail_mb} МБ · порт 8082 свободен"

# ─── 1. Разложить стек вне git-чекаута ──────────────────────────────────────
mkdir -p "$STACK_DIR/nginx"
cp "$HERE/docker-compose.yml" "$STACK_DIR/docker-compose.yml"
cp "$HERE/nginx/default.conf" "$STACK_DIR/nginx/default.conf"
echo "✓ стек разложен в $STACK_DIR"

# ─── 2. Пароли — генерируются один раз и переживают переустановку ────────────
if [ ! -f "$ENV_FILE" ]; then
  echo "── генерирую пароли → $ENV_FILE"
  {
    echo "WEM_SRC=$SRC"
    echo "WEM_DB_NAME=wem"
    echo "WEM_DB_USER=wem_user"
    echo "WEM_DB_PASSWORD=$(openssl rand -hex 16)"
    echo "WEM_DB_ROOT_PASSWORD=$(openssl rand -hex 16)"
    echo "WEM_APP_URL=http://155.212.143.179:8082"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
else
  echo "✓ $ENV_FILE уже есть — пароли не перегенерирую (иначе БД перестанет пускать)"
fi

# ─── 3. Исходники (сторонний код — вне нашего репозитория) ──────────────────
if [ -d "$SRC/.git" ]; then
  echo "── исходники есть, обновляю"
  git -C "$SRC" pull --ff-only || echo "⚠️ pull не удался — работаю на текущей копии"
else
  echo "── клонирую $REPO"
  git clone --depth 1 "$REPO" "$SRC"
fi
echo -n "   версия: "; git -C "$SRC" log --oneline -1

cd "$STACK_DIR"

# ─── 4. Сборка и запуск ─────────────────────────────────────────────────────
echo "── сборка образа (php 8.2 + composer install + npm ci) — это долго"
docker compose build

echo "── запуск"
docker compose up -d

# ─── 5. Vite-ассеты ─────────────────────────────────────────────────────────
# В их Dockerfile есть npm ci, но НЕТ npm run build, а их entrypoint пропускает
# сборку при непустом node_modules (он непустой — приходит из образа).
# Без этого шага public/build пустой и фронт битый.
echo "── ждём готовности приложения"
ready=0
for _ in $(seq 1 80); do
  if docker compose exec -T app php -v >/dev/null 2>&1; then ready=1; break; fi
  sleep 3
done
[ "$ready" = 1 ] || { echo "⚠️ app не ответил за 4 минуты — смотри: docker compose logs app"; }

if [ -f "$SRC/public/build/manifest.json" ]; then
  echo "✓ vite-ассеты уже собраны"
elif [ "$ready" = 1 ]; then
  echo "── собираю vite-ассеты (npm run build)"
  docker compose exec -T app npm run build || echo "⚠️ npm run build упал — фронт будет без стилей"
fi

# ─── 6. Итог ────────────────────────────────────────────────────────────────
echo
echo "═══ Готово ═══"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo
echo "Открыть:  http://155.212.143.179:8082"
echo "Логин:    см. CreateAdminUserSeeder в их репозитории; СМЕНИТЬ пароль сразу"
echo
echo "Управление (из $STACK_DIR):"
echo "  docker compose stop      # остановить, освободить RAM (данные целы)"
echo "  docker compose start     # поднять снова"
echo "  docker compose logs -f app"
echo "  docker compose down -v   # снести вместе с БД"
