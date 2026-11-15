#!/bin/bash
# Обновить модули на копии: bash stage_upd.sh <m1,m2|all> [ref] [install_mods]
#   ref — ветка/коммит (по умолчанию код, уже лежащий в dryrun/addons-extra; если задан — разложить его).
# DB-доступ — через переменные HOST/USER/PASSWORD: entrypoint образа дописывает --db_* из них ПОСЛЕ
# наших аргументов и перебивает их (по умолчанию пароль «odoo» — «password authentication failed»).
# Порядок как у боевого deploy.sh: стоп → -u → чистка /web/assets → старт. В конце «DONE».
set -euo pipefail
STAND=/opt/experiments/odoo
DRY=$STAND/dryrun
MODS="${1:?модули через запятую или all}"
REF="${2:-}"
INST="${3:-}"
cd "$STAND"; set -a; . ./.env; set +a
IMG=odoo-ru:19.0-20261006

if [ -n "$REF" ]; then
  W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
  git -C /opt/factory-platform fetch -q origin || true
  git -C /opt/factory-platform archive "$REF" experiments/odoo/addons experiments/odoo/vendor | tar -x -C "$W"
  rsync -a "$W/experiments/odoo/addons/" "$DRY/addons-extra/"; rsync -a "$W/experiments/odoo/vendor/" "$DRY/addons-extra/"
  chmod -R a+rX "$DRY/addons-extra"
fi
if [ "$MODS" = all ]; then
  MODS=$(grep -m1 '^OURS=' /opt/factory-platform/experiments/odoo/deploy.sh | cut -d'"' -f2 | tr ' ' ',')
fi

RUN="docker run --rm --network odoo_default -e HOST=db -e USER=$ODOO_DB_USER -e PASSWORD=$ODOO_DB_PASSWORD -v $STAND/odoo.conf:/etc/odoo/odoo.conf:ro \
  -v $STAND/ruodoo:/mnt/extra-addons:ro -v $DRY/addons-extra:/mnt/third-party:ro -v $DRY/stage-data:/stage-data \
  $IMG odoo -d odoo_stage --data-dir /stage-data"

docker rm -f odoo-stage >/dev/null 2>&1 || true
ARGS="-u $MODS"; [ -n "$INST" ] && ARGS="$ARGS -i $INST"
$RUN $ARGS --stop-after-init 2>&1 | grep -E "CRITICAL|ERROR|Failed to|Modules loaded" | grep -v UserWarning | tail -15 || true
docker compose exec -T db psql -U "$ODOO_DB_USER" -d odoo_stage -qtAc "DELETE FROM ir_attachment WHERE url LIKE '/web/assets/%';"

docker run -d --name odoo-stage --restart unless-stopped --network odoo_default -p 127.0.0.1:8099:8069 \
  --memory 1536m --cpus 1.5 -e HOST=db -e USER="$ODOO_DB_USER" -e PASSWORD="$ODOO_DB_PASSWORD" \
  -v "$STAND/odoo.conf":/etc/odoo/odoo.conf:ro -v "$STAND/ruodoo":/mnt/extra-addons:ro \
  -v "$DRY/addons-extra":/mnt/third-party:ro -v "$DRY/stage-data":/stage-data \
  "$IMG" odoo -d odoo_stage \
  --db-filter='^odoo_stage$' --data-dir /stage-data --workers 0 --max-cron-threads 0 >/dev/null
echo DONE
