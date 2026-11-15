#!/bin/bash
# Копия Odoo для проверки (odoo_stage, 127.0.0.1:8099) — пересоздать из боевой базы.
# Правило Антона 14.10.2026: любой шаг сначала на копию → Антон смотрит → «выкладывай vX на боевой».
# Смотреть с Mac: ssh -N -L 8099:127.0.0.1:8099 odoo-new → http://localhost:8099
#
# Восстановлено 15.11.2026 (на старом сервере скрипты жили только в /opt/experiments/odoo/dryrun и
# погибли вместе с ним). Боевую базу только читает (pg_dump).
#   bash stage_rebuild.sh [ref]   — ref: ветка/коммит кода для копии (по умолчанию как у боевого)
#   DUMP=/путь/odoo.dump FILESTORE=/путь/filestore bash stage_rebuild.sh — копия не из боевой базы, а из
#   файла (восстановление бэкапа: сначала на копию, Антон смотрит, потом на боевой).
set -euo pipefail
STAND=/opt/experiments/odoo
DRY=$STAND/dryrun
REF="${1:-feature/experiment-carbon}"
cd "$STAND"; set -a; . ./.env; set +a
PSQL="docker compose exec -T db psql -U $ODOO_DB_USER"
mkdir -p "$DRY/addons-extra" "$DRY/stage-data"

echo "→ код копии: $REF"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
git -C /opt/factory-platform fetch -q origin || true
git -C /opt/factory-platform archive "$REF" experiments/odoo/addons experiments/odoo/vendor | tar -x -C "$W"
rsync -a --delete "$W/experiments/odoo/addons/" "$W/experiments/odoo/vendor/" "$DRY/addons-extra/" 2>/dev/null \
  || { rsync -a --delete "$W/experiments/odoo/addons/" "$DRY/addons-extra/"; rsync -a "$W/experiments/odoo/vendor/" "$DRY/addons-extra/"; }
chmod -R a+rX "$DRY/addons-extra"

echo "→ гашу копию, пересоздаю базу odoo_stage из боевой"
docker rm -f odoo-stage >/dev/null 2>&1 || true
$PSQL -d postgres -qc "DROP DATABASE IF EXISTS odoo_stage WITH (FORCE);"
$PSQL -d postgres -qc "CREATE DATABASE odoo_stage OWNER $ODOO_DB_USER;"
if [ -n "${DUMP:-}" ]; then
  echo "   из файла $DUMP"
  docker compose exec -T db pg_restore -U "$ODOO_DB_USER" -d odoo_stage --no-owner < "$DUMP" || echo "   (pg_restore: предупреждения — см. выше)"
else
  docker compose exec -T db sh -c "pg_dump -U $ODOO_DB_USER -Fc odoo | pg_restore -U $ODOO_DB_USER -d odoo_stage --no-owner"
fi

echo "→ вложения (filestore)"
rm -rf "$DRY/stage-data/filestore/odoo_stage"; mkdir -p "$DRY/stage-data/filestore"
if [ -n "${FILESTORE:-}" ]; then
  cp -a "$FILESTORE" "$DRY/stage-data/filestore/odoo_stage"; chown -R 100:101 "$DRY/stage-data"
else
  docker run --rm -v odoo_odoo_data:/src:ro -v "$DRY/stage-data":/dst alpine:3.20 \
    sh -c 'if [ -d /src/filestore/odoo ]; then cp -a /src/filestore/odoo /dst/filestore/odoo_stage; else mkdir -p /dst/filestore/odoo_stage; fi; chown -R 100:101 /dst'
fi

echo "→ обезвреживаю: кроны, почта, ящики"
$PSQL -d odoo_stage -q <<'SQL'
UPDATE ir_cron SET active = false;
UPDATE ir_mail_server SET active = false, smtp_host = 'smtp.disabled.invalid';
DO $$ BEGIN
  IF to_regclass('fetchmail_server') IS NOT NULL THEN UPDATE fetchmail_server SET active = false; END IF;
  IF to_regclass('mail_client_server') IS NOT NULL THEN UPDATE mail_client_server SET imap_host = 'imap.disabled.invalid'; END IF;
END $$;
-- Боты, банки, МойСклад, ассистент: ключи копии не нужны — второй потребитель того же бота/вебхука
-- ломает боевой. Пусто = модуль молчит.
DELETE FROM ir_config_parameter WHERE key ~ '^(pmk_telegram|pmk_bank|pmk_moysklad|pmk_cloud|pmk_vpn)\.'
  AND key ~ '(token|key|secret|password|webhook)';
SQL
docker compose run --rm -T odoo odoo neutralize -d odoo_stage >/dev/null 2>&1 || echo "   (neutralize: предупреждение, см. вручную)"

echo "→ -u всех наших модулей на коде копии"
bash "$(dirname "$0")/stage_upd.sh" all

echo "→ готово: http://localhost:8099 через туннель"
