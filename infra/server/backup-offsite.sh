#!/bin/bash
# Бэкап Odoo вне Бегета — Yandex Object Storage (Антон 16.11.2026: «бэкап на яндекс»).
# Повод: атака на Бегет 02.11.2026 — сервер погиб, дампов базы вне VPS не было, потеряно 22.10–02.11.
#
# ЧТО КЛАДЁМ (бакет $YC_BUCKET):
#   odoo/db/odoo_ГГГГММДД_ЧЧММСС.dump — ночной дамп базы (~25 МБ), каждую ночь. Старые удаляет сам бакет
#                                      правилом жизненного цикла (30 дней) — у ключа нет права удалять.
#   odoo/filestore/<xx>/<sha1>        — вложения ПО ФАЙЛАМ, только новые. Файл filestore не меняется
#                                      никогда (имя = sha1 содержимого), поэтому ежедневный архив на 1 ГБ
#                                      не нужен: первый раз ~1 ГБ, дальше — что добавилось за сутки.
#   archive/                          — разовое: дамп 22.10 со старого сервера.
#
# КЛЮЧ: /root/.yc-backup.env (chmod 600, в git не кладём):
#   YC_KEY_ID=…  YC_SECRET=…  YC_BUCKET=…
# Сервисный аккаунт с ролью storage.uploader (загрузить и прочитать; удалить — нельзя). В бакете
# включено версионирование — перезапись не уничтожает прежнюю копию.
#
# CRON (после backup-stand.sh в 03:40):
#   20 4 * * * /opt/factory-platform/infra/server/backup-offsite.sh >> /var/log/odoo-offsite.log 2>&1
#
# ВОССТАНОВЛЕНИЕ (на любом сервере с rclone и тем же ключом):
#   rclone copyto yc:$YC_BUCKET/odoo/db/<дамп> ./odoo.dump
#   rclone copy  yc:$YC_BUCKET/odoo/filestore ./filestore
#   DUMP=./odoo.dump FILESTORE=./filestore bash experiments/odoo/scripts/restore-prod-from-dump.sh
#   (в filestore могут быть лишние файлы удалённых вложений — Odoo их не видит, вреда нет)
set -euo pipefail
ENV=/root/.yc-backup.env
BK=/opt/backups/odoo
STATE=/var/lib/pmk-offsite
mkdir -p "$STATE"
echo "── $(date '+%F %T') offsite → Yandex Object Storage"

[ -r "$ENV" ] || { echo "ОШИБКА: нет $ENV — ключ Яндекса не вписан"; exit 1; }
# shellcheck disable=SC1090
. "$ENV"
: "${YC_KEY_ID:?нет YC_KEY_ID}" "${YC_SECRET:?нет YC_SECRET}" "${YC_BUCKET:?нет YC_BUCKET}"
export RCLONE_CONFIG=/dev/null RCLONE_CONFIG_YC_TYPE=s3 RCLONE_CONFIG_YC_PROVIDER=Other \
  RCLONE_CONFIG_YC_ENDPOINT=https://storage.yandexcloud.net RCLONE_CONFIG_YC_REGION=ru-central1 \
  RCLONE_CONFIG_YC_ACCESS_KEY_ID="$YC_KEY_ID" RCLONE_CONFIG_YC_SECRET_ACCESS_KEY="$YC_SECRET" \
  RCLONE_CONFIG_YC_NO_CHECK_BUCKET=true
R="rclone --retries 5 --low-level-retries 10 --stats 0"

# 1. Дамп базы — самый свежий; старше суток = ночной бэкап не отработал, это ошибка.
last=$(ls -1t "$BK"/odoo_*.dump 2>/dev/null | head -1 || true)
[ -n "$last" ] || { echo "ОШИБКА: в $BK нет дампов"; exit 1; }
age=$(( $(date +%s) - $(stat -c %Y "$last") ))
[ "$age" -lt 86400 ] || { echo "ОШИБКА: свежего дампа нет, последний $(basename "$last") ($((age/3600)) ч)"; exit 1; }
dst="yc:$YC_BUCKET/odoo/db/$(basename "$last")"
$R copyto "$last" "$dst"
remote=$($R lsjson "$dst" | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["Size"])')
local_size=$(stat -c %s "$last")
[ "$remote" = "$local_size" ] || { echo "ОШИБКА: размер в облаке $remote ≠ $local_size"; exit 1; }
echo "   база: $(basename "$last") $((local_size/1048576)) МБ — ок"

# 2. Вложения — только новые файлы (--size-only: имя = sha1, сравнивать время незачем).
FS="$(docker volume inspect odoo_odoo_data --format '{{.Mountpoint}}')/filestore/odoo"
[ -d "$FS" ] || { echo "ОШИБКА: нет каталога вложений $FS"; exit 1; }
before=$(find "$FS" -type f | wc -l)
$R copy "$FS" "yc:$YC_BUCKET/odoo/filestore" --size-only --transfers 8 --checkers 16
echo "   вложения: $before файлов на сервере, новые догружены — ок"

# 3. Разовое: дамп 22.10 со старого сервера (единственная копия данных до атаки).
OLD=$BK/beget-2210/odoo-20261022_030001.dump
if [ -f "$OLD" ] && [ ! -f "$STATE/archive-2210.done" ]; then
  $R copyto "$OLD" "yc:$YC_BUCKET/archive/odoo-20261022_030001.dump" && touch "$STATE/archive-2210.done"
  echo "   архив 22.10 — выгружен"
fi

# 4. Сайт pmkpark.ru (с 16.11.2026, infra/site): ночной дамп базы → site/db/ (бакет удаляет через 30 дней),
#    файлы → site/www/ только изменённые (--checksum: md5 из листинга, без запроса на каждый файл).
if [ -d /opt/site/www ] && docker ps --format '{{.Names}}' | grep -qx site-db; then
  sd=$(ls -1t /opt/backups/site/site_*.sql.gz 2>/dev/null | head -1 || true)
  [ -n "$sd" ] || { echo "ОШИБКА: нет дампа сайта в /opt/backups/site"; exit 1; }
  sage=$(( $(date +%s) - $(stat -c %Y "$sd") ))
  [ "$sage" -lt 86400 ] || { echo "ОШИБКА: свежего дампа сайта нет, последний $(basename "$sd")"; exit 1; }
  $R copyto "$sd" "yc:$YC_BUCKET/site/db/$(basename "$sd")"
  echo "   сайт, база: $(basename "$sd") — ок"
  $R copy /opt/site/www "yc:$YC_BUCKET/site/www" --checksum --transfers 8 --checkers 16 \
    --exclude "/bitrix/cache/**" --exclude "/bitrix/managed_cache/**" --exclude "/bitrix/stack_cache/**" \
    --exclude "/bitrix/tmp/**" --exclude "/upload/tmp/**" --exclude "/upload/resize_cache/**"
  echo "   сайт, файлы: изменённые догружены — ок"
fi

# 4б. 1С (с 16.11.2026, infra/1c): ночная выгрузка .dt → 1c/db/ (бакет удаляет через 30 дней)
if [ -f /opt/1c/bases/buh/1Cv8.1CD ]; then
  cd1=$(ls -1t /opt/backups/1c/buh_*.dt 2>/dev/null | head -1 || true)
  [ -n "$cd1" ] || { echo "ОШИБКА: нет выгрузки 1С в /opt/backups/1c"; exit 1; }
  [ $(( $(date +%s) - $(stat -c %Y "$cd1") )) -lt 86400 ] || { echo "ОШИБКА: свежей выгрузки 1С нет, последняя $(basename "$cd1")"; exit 1; }
  $R copyto "$cd1" "yc:$YC_BUCKET/1c/db/$(basename "$cd1")"
  echo "   1С: $(basename "$cd1") — ок"
fi

# 5. Комплект восстановления: код, RuOdoo, образы Docker, секреты — чтобы всё поднималось из одного бакета
R="$R" YC_BUCKET="$YC_BUCKET" bash "$(dirname "$0")/backup-kit.sh"

date '+%F %T' > "$STATE/last_ok"
echo "   готово"
