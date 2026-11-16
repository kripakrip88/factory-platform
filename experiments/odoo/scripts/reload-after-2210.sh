#!/bin/bash
# Повтор записей в базу, сделанных на старом сервере ПОСЛЕ ночного бэкапа 22.10 (база восстановлена из
# него 16.11.2026, данные 22.10–02.11 потеряны). Те же скрипты и файлы, тот же порядок, что 26–27.10:
#   1. прайс Металлсервиса 01.10 заново (файл — вложение 9227): с v1.118.2 разборщик видит оцинковку;
#   2. дубль «ЦЕНТР КРОВЛИ» → ООО «ЦЕНТР КРОВЛИ» (ИНН 2540249518)          — scripts_v1182/merge_ck.py;
#   3. прайс «Центр Кровли» 14.09 (лист гладкий 1250, цинк + краска)        — PMK_PRICE_FORMAT=ck;
#   4. дубли поставщиков крепежа → карточки с ИНН (МК-27, Метиз Центр)     — scripts_v1183/merge_…py;
#   5. 1976 цен метизов ₽/шт                                               — load_fastener_prices.py.
#
#   bash reload-after-2210.sh stage   — копия odoo_stage (:8099)
#   bash reload-after-2210.sh prod    — боевая, ТОЛЬКО по «выкладывай» Антона (бэкап снимается сам)
# Файлы: /opt/backups/odoo/reload-2210/{ms_2026-10-01.xlsx, ck_2026-09-14.xlsx, fasteners_prices.csv}.
set -euo pipefail
TARGET="${1:?stage | prod}"
STAND=/opt/experiments/odoo
FILES=/opt/backups/odoo/reload-2210
REPO=/opt/factory-platform/experiments/odoo
MATCH=/opt/factory-platform/experiments/price-matching   # match.py разборщика прайсов (load_prices ищет в /tmp/pmk_price_code)
cd "$STAND"; set -a; . ./.env; set +a
IMG=odoo-ru:19.0-20261006

case "$TARGET" in
  stage)
    DB=odoo_stage; LIVE=0; DRY=$STAND/dryrun; TOOLS=$DRY/addons-extra/pmk_bridge/tools
    RUN=(docker run --rm -i --network odoo_default -e HOST=db -e USER="$ODOO_DB_USER" -e PASSWORD="$ODOO_DB_PASSWORD"
         -v "$STAND/odoo.conf:/etc/odoo/odoo.conf:ro" -v "$STAND/ruodoo:/mnt/extra-addons:ro"
         -v "$DRY/addons-extra:/mnt/third-party:ro" -v "$DRY/stage-data:/stage-data" -v "$FILES:/reload:ro" -v "$MATCH:/tmp/pmk_price_code:ro")
    TAIL=("$IMG" odoo shell -d odoo_stage --data-dir /stage-data --no-http)
    ;;
  prod)
    DB=odoo; LIVE=1; TOOLS=$STAND/addons-extra/pmk_bridge/tools
    STAMP=$(date +%Y%m%d-%H%M)
    echo "→ бэкап боевой: /opt/backups/odoo/odoo-before-reload-2210-$STAMP.dump"
    docker compose exec -T db pg_dump -U "$ODOO_DB_USER" -Fc odoo > "/opt/backups/odoo/odoo-before-reload-2210-$STAMP.dump"
    RUN=(docker compose run --rm -T -v "$FILES:/reload:ro" -v "$MATCH:/tmp/pmk_price_code:ro")
    TAIL=(odoo odoo shell -d odoo --no-http)
    ;;
  *) echo "stage | prod"; exit 1 ;;
esac

shell() {  # shell <скрипт на хосте> [VAR=…]… — скрипт идёт на stdin odoo shell (точка входа образа сама даёт базу)
  local script="$1"; shift
  local envs=(-e "PMK_LIVE=$LIVE")
  for kv in "$@"; do envs+=(-e "$kv"); done
  "${RUN[@]}" "${envs[@]}" "${TAIL[@]}" < "$script" 2>&1 \
    | grep -vE " (INFO|WARNING) | py.warnings|UserWarning|^\s+(warnings|  )|unknown option" | tail -25
}

echo "══ 1. прайс Металлсервиса 01.10 ($DB)"
shell $TOOLS/load_prices.py PMK_PRICE_FILE=/reload/ms_2026-10-01.xlsx \
  PMK_PRICE_DATE=2026-10-01 PMK_PRICE_VAT=22 PMK_PRICE_SUPPLIER=19 PMK_PRICE_APPLY=1
echo "══ 2. слияние «ЦЕНТР КРОВЛИ»"
shell $REPO/scripts_v1182/merge_ck.py
echo "══ 3. прайс «Центр Кровли» 14.09"
shell $TOOLS/load_prices.py PMK_PRICE_FILE=/reload/ck_2026-09-14.xlsx PMK_PRICE_FORMAT=ck \
  PMK_PRICE_DATE=2026-09-14 PMK_PRICE_VAT=22 PMK_PRICE_SUPPLIER=546 PMK_PRICE_APPLY=1
echo "══ 4. слияние поставщиков крепежа"
shell $REPO/scripts_v1183/merge_fastener_suppliers.py
echo "══ 5. цены метизов"
shell $TOOLS/load_fastener_prices.py PMK_FAST_FILE=/reload/fasteners_prices.csv PMK_FAST_APPLY=1
echo "DONE $TARGET"
