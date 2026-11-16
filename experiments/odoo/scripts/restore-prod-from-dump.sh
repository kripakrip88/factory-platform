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

if [ -z "${SKIP_BACKUP:-}" ]; then   # SKIP_BACKUP=1 — повторный запуск, бэкап уже снят
  echo "→ бэкап нынешней боевой (на всякий случай)"
  docker compose exec -T db pg_dump -U "$ODOO_DB_USER" -Fc odoo > "/opt/backups/odoo/odoo-before-restore-$STAMP.dump"
fi

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
# Одним проходом: зависимости RuOdoo 2026-11 + модули после 22.10 + -u всех наших. Порознь нельзя
# (16.11.2026): реестр грузит НОВЫЙ код наших модулей на СТАРЫЕ таблицы (нет колонок
# pmk_telegram_link_hash и др.) — Odoo ловит ошибку и сам себя блокирует на чтении полей.
OURS=$(grep -m1 '^OURS=' /opt/factory-platform/experiments/odoo/deploy.sh | cut -d'"' -f2 | tr ' ' ',')
NEW=pmk_opora,pmk_zakladnye,pmk_supplier_invoice,pmk_vpn
echo "→ RuOdoo 2026-11 + новые модули + обновление наших (одним проходом)"
timeout 1800 $RUN -i l10n_latam_check,docx_report,$NEW -u l10n_ru_advance_payments,$OURS 2>&1 \
  | grep -E "CRITICAL| ERROR |Modules loaded|not loaded" | grep -v "(ERROR/3)" | tail -15 || true

echo "→ l10n_ru_act_rev выведен RuOdoo по безопасности — удаляю (на время делаю устанавливаемым)"
M=$STAND/ruodoo/l10n_ru_act_rev/__manifest__.py
sed -i 's/"installable": False/"installable": True/' "$M"
echo 'm=env["ir.module.module"].search([("name","=","l10n_ru_act_rev"),("state","=","installed")]); m and m.button_immediate_uninstall(); env.cr.commit(); print("ACT_REV", env["ir.module.module"].search([("name","=","l10n_ru_act_rev")]).state)' \
  | docker compose run --rm -T odoo odoo shell -d odoo --no-http 2>&1 | grep -E "^ACT_REV|Error" || true
sed -i 's/"installable": True/"installable": False/' "$M"

echo "→ адрес Anthropic — туннель через NL (служба anthropic-relay, с IP в РФ ответ 403)"
$PSQL -d odoo -qc "INSERT INTO ir_config_parameter(key,value,create_date,write_date) VALUES ('pmk_ai.api_base','https://api.anthropic.com:8443',now(),now()) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, write_date=now();"

echo "→ код до текущего: deploy.sh (-u всех наших, чистка ассетов, старт)"
# Модули, сделанные после 22.10, в базе 22.10 не установлены, а deploy.sh их только обновляет (-u
# неустановленного ничего не делает) — ставим явно (16.11.2026: на копии без этого их не было).
INSTALL="pmk_opora pmk_zakladnye pmk_supplier_invoice pmk_vpn" sh /opt/factory-platform/experiments/odoo/deploy.sh
# deploy.sh делает stop/start — новые extra_hosts (туннель Anthropic) так не подхватятся
docker compose up -d odoo ai-worker

echo "→ проверка"
sleep 5
curl -s -o /dev/null -w "   /web/login %{http_code}\n" http://172.17.0.1:8084/web/login
echo "DONE"
