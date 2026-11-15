#!/bin/bash
# Восстановить БОЕВУЮ базу Odoo из файла бэкапа (база + вложения) и довести код до текущего.
# Только по фразе Антона «выкладывай … на боевой» и после проверки того же файла на копии
# (experiments/odoo/stage/stage_rebuild.sh с DUMP=… FILESTORE=…).
#
#   DUMP=/opt/backups/odoo/beget-2210/odoo-20261022_030001.dump \
#   FILESTORE=/opt/backups/odoo/beget-2210/filestore \
#   bash restore-prod-from-dump.sh
#
# Первый раз — 15.11.2026: перенос базы от 22.10 со старого сервера (копия Бегета) на pmk-main.
set -euo pipefail
: "${DUMP:?DUMP=файл дампа}" "${FILESTORE:?FILESTORE=каталог вложений}"
STAND=/opt/experiments/odoo
cd "$STAND"; set -a; . ./.env; set +a
PSQL="docker compose exec -T db psql -U $ODOO_DB_USER"
STAMP=$(date +%Y%m%d-%H%M)
[ -s "$DUMP" ] || { echo "нет файла $DUMP"; exit 1; }
[ -d "$FILESTORE" ] || { echo "нет каталога $FILESTORE"; exit 1; }

echo "→ бэкап нынешней боевой (на всякий случай)"
docker compose exec -T db pg_dump -U "$ODOO_DB_USER" -Fc odoo > "/opt/backups/odoo/odoo-before-restore-$STAMP.dump"

echo "→ гашу Odoo и фоновые процессы"
docker compose stop odoo ai-worker nest-worker zk-worker >/dev/null 2>&1 || true

echo "→ база из $DUMP"
$PSQL -d postgres -qc "DROP DATABASE IF EXISTS odoo WITH (FORCE);"
$PSQL -d postgres -qc "CREATE DATABASE odoo OWNER $ODOO_DB_USER;"
docker compose exec -T db pg_restore -U "$ODOO_DB_USER" -d odoo --no-owner < "$DUMP" || echo "   (pg_restore: предупреждения выше)"

echo "→ вложения из $FILESTORE"
docker run --rm -v odoo_odoo_data:/data -v "$FILESTORE":/src:ro alpine:3.20 \
  sh -c 'rm -rf /data/filestore/odoo && mkdir -p /data/filestore && cp -a /src /data/filestore/odoo && chown -R 100:101 /data/filestore'

RUN="docker compose run --rm -T odoo odoo -d odoo --stop-after-init"
echo "→ RuOdoo 2026-11: новые зависимости l10n_ru_advance_payments"
$RUN -i l10n_latam_check,docx_report -u l10n_ru_advance_payments 2>&1 | grep -E "CRITICAL| ERROR |Modules loaded" | tail -4 || true

echo "→ l10n_ru_act_rev выведен RuOdoo по безопасности — удаляю (на время делаю устанавливаемым)"
M=$STAND/ruodoo/l10n_ru_act_rev/__manifest__.py
sed -i 's/"installable": False/"installable": True/' "$M"
echo 'm=env["ir.module.module"].search([("name","=","l10n_ru_act_rev"),("state","=","installed")]); m and m.button_immediate_uninstall(); env.cr.commit(); print("ACT_REV", env["ir.module.module"].search([("name","=","l10n_ru_act_rev")]).state)' \
  | docker compose run --rm -T odoo odoo shell -d odoo --no-http 2>&1 | grep -E "^ACT_REV|Error" || true
sed -i 's/"installable": True/"installable": False/' "$M"

echo "→ код до текущего: deploy.sh (-u всех наших, чистка ассетов, старт)"
sh /opt/factory-platform/experiments/odoo/deploy.sh

echo "→ проверка"
sleep 5
curl -s -o /dev/null -w "   /web/login %{http_code}\n" http://172.17.0.1:8084/web/login
echo "DONE"
