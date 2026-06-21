#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# clone-prod-to-staging.sh — РАЗОВО склонировать боевую БД prod → staging
# для отладки бага на реальных данных, НЕ трогая prod.
#
# Запуск на сервере (из /opt/factory-platform):
#   bash services/erp/scripts/clone-prod-to-staging.sh
#
# Что делает:
#   1. Свежий логический бэкап prod (bench backup --with-files) — prod не останавливается.
#   2. Восстанавливает дамп в staging-БД (bench restore --force, дроп+воссоздание).
#   3. Выравнивает пароль site-юзера staging по site_config (артефакт restore).
#   4. ⚠️ ОБЯЗАТЕЛЬНО выключает Email Account в staging (enable_incoming/outgoing=0),
#      чтобы staging НЕ полез в боевой ящик pmkpark@mail.ru.
#   5. clear-cache staging.
#
# Идемпотентно: можно гонять повторно. Боевую среду (erp-*) только читает (backup).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/../../.."   # → /opt/factory-platform
set -a; . ./.env; set +a

PROD_BACKEND=erp-backend-1
STG_BACKEND=erp-staging-backend-1
STG_DB=erp-staging-db-1
SITE=erp.localhost
STG_COMPOSE="services/erp/docker-compose.staging.yml"

echo "🔒 [1/5] Свежий бэкап PROD (prod не трогаем, только читаем)..."
docker exec "$PROD_BACKEND" bench --site "$SITE" backup --with-files >/dev/null
DUMP_HOST=$(docker run --rm -v erp_sites:/s alpine sh -c "ls -t /s/$SITE/private/backups/*-database.sql.gz | head -1")
DUMP_NAME=$(basename "$DUMP_HOST")
echo "   дамп: $DUMP_NAME"

echo "📤 [2/5] Переносим дамп в staging sites-том и восстанавливаем..."
# копируем свежий дамп из prod-тома в staging-том
docker run --rm -v erp_sites:/from:ro -v erp-staging_sites:/to alpine \
  sh -c "cp /from/$SITE/private/backups/$DUMP_NAME /to/$SITE/private/backups/"
DUMP_IN="/home/frappe/frappe-bench/sites/$SITE/private/backups/$DUMP_NAME"
docker compose -p erp-staging -f "$STG_COMPOSE" run --rm backend \
  bench --site "$SITE" --force restore "$DUMP_IN" --db-root-password "$DB_ROOT_PASSWORD"

echo "🔑 [3/5] Выравниваем пароль site-юзера staging по site_config..."
read SDBN SDBP < <(docker exec "$STG_BACKEND" cat /home/frappe/frappe-bench/sites/$SITE/site_config.json \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['db_name'], d['db_password'])")
docker exec "$STG_DB" mysql -uroot -p"$DB_ROOT_PASSWORD" -e "
  CREATE USER IF NOT EXISTS \`$SDBN\`@'%' IDENTIFIED BY '$SDBP';
  ALTER USER \`$SDBN\`@'%' IDENTIFIED BY '$SDBP';
  GRANT ALL PRIVILEGES ON \`$SDBN\`.* TO \`$SDBN\`@'%';
  FLUSH PRIVILEGES;"

echo "📭 [4/5] ⚠️ ВЫКЛЮЧАЕМ Email Account в staging (НЕ лезть в боевой ящик)..."
docker exec "$STG_DB" mysql -uroot -p"$DB_ROOT_PASSWORD" -e "
  UPDATE \`$SDBN\`.\`tabEmail Account\`
  SET enable_incoming=0, enable_outgoing=0, default_incoming=0, default_outgoing=0;"
echo "   статус ящиков staging:"
docker exec "$STG_DB" mysql -uroot -p"$DB_ROOT_PASSWORD" -N -e \
  "SELECT email_id, enable_incoming, enable_outgoing FROM \`$SDBN\`.\`tabEmail Account\`;"

echo "🧹 [5/5] clear-cache staging..."
docker exec "$STG_BACKEND" bench --site "$SITE" clear-cache || true

echo "✅ Готово: staging склонирован с prod, боевой ящик в staging ВЫКЛЮЧЕН."
echo "   Проверь: http://<server>:8081  и убедись, что Email Account disabled."
