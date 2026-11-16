#!/bin/bash
# Ночная выгрузка базы 1С в .dt (16.11.2026). Cron 03:30 — до выгрузки в облако (04:20, backup-offsite.sh).
#   30 3 * * * /opt/factory-platform/infra/1c/backup-1c.sh >> /var/log/1c-backup.log 2>&1
# Файловая база: на время выгрузки Apache останавливается (ночью, 1–2 пользователя — секунды-минуты).
# Восстановление: bash /opt/factory-platform/infra/1c/restore-1c.sh /opt/backups/1c/buh_….dt
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/version.sh"   # VER, BIN
DB=/opt/1c/bases/buh
DIR=/opt/backups/1c
KEEP_DAYS=14
[ -f "$DB/1Cv8.1CD" ] || { echo "нет базы 1С в $DB — пропуск"; exit 0; }
mkdir -p "$DIR"
OUT=$DIR/buh_$(date +%Y%m%d_%H%M%S).dt
echo "── $(date '+%F %T') выгрузка 1С"
systemctl stop apache2
trap 'systemctl start apache2' EXIT
"$BIN/ibcmd" infobase dump --db-path="$DB" "$OUT.part" 2>&1 | tail -1
systemctl start apache2; trap - EXIT
[ -s "$OUT.part" ] || { echo "ОШИБКА: пустая выгрузка"; rm -f "$OUT.part"; exit 1; }
mv "$OUT.part" "$OUT"
find "$DIR" -maxdepth 1 -name 'buh_*.dt' -mtime +$KEEP_DAYS -delete
echo "   $(basename "$OUT") $(du -h "$OUT" | cut -f1) — ок"
