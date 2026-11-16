#!/bin/bash
# Ночной бэкап базы 1С (16.11.2026). Cron 03:30 — до выгрузки в облако (04:20, backup-offsite.sh).
#   30 3 * * * /opt/factory-platform/infra/1c/backup-1c.sh >> /var/log/1c-backup.log 2>&1
# Копия ФАЙЛА базы 1Cv8.1CD, сжатая zstd, а не выгрузка .dt: `ibcmd infobase dump` требует логин и пароль
# администратора базы, а хранить пароль бухгалтерии на сервере не хочется. Файловая база = один файл,
# его копия при остановленном Apache — полноценный бэкап (грузится той же платформой 8.5).
# Apache стоит только на время копирования файла (секунды), сжатие — уже при работающей 1С.
# Восстановление: bash /opt/factory-platform/infra/1c/restore-1c.sh /opt/backups/1c/buh_….1cd.zst
set -euo pipefail
DB=/opt/1c/bases/buh
DIR=/opt/backups/1c
KEEP_DAYS=14
[ -f "$DB/1Cv8.1CD" ] || { echo "нет базы 1С в $DB — пропуск"; exit 0; }
mkdir -p "$DIR"
OUT=$DIR/buh_$(date +%Y%m%d_%H%M%S).1cd.zst
TMP=$DIR/.buh.1cd.tmp
echo "── $(date '+%F %T') бэкап 1С"
systemctl stop apache2
trap 'systemctl start apache2' EXIT
cp "$DB/1Cv8.1CD" "$TMP"
systemctl start apache2; trap - EXIT
zstd -q -T2 -6 --rm "$TMP" -o "$OUT.part"
zstd -q -t "$OUT.part" || { echo "ОШИБКА: архив 1С не прошёл проверку"; rm -f "$OUT.part"; exit 1; }
mv "$OUT.part" "$OUT"
find "$DIR" -maxdepth 1 \( -name 'buh_*.1cd.zst' -o -name 'buh_*.dt' \) -mtime +$KEEP_DAYS -delete
echo "   $(basename "$OUT") $(du -h "$OUT" | cut -f1) — ок"
