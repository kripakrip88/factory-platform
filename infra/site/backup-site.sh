#!/bin/bash
# Ночной дамп базы сайта pmkpark.ru (16.11.2026). Cron 03:50 — до выгрузки в облако (04:20, backup-offsite.sh).
#   50 3 * * * /opt/factory-platform/infra/site/backup-site.sh >> /var/log/site-backup.log 2>&1
# Данные b_user_session не берём (сессии посетителей, 1,6 ГБ мусора), структуру — берём.
# Файлы сайта отдельно не архивируются: в облако они идут по файлам, только изменённые (backup-offsite.sh).
# Восстановление: gunzip -c site_….sql.gz | docker exec -i site-db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" pmkpark_site'
set -euo pipefail
DIR=/opt/backups/site
KEEP_DAYS=14
STAMP=$(date +%Y%m%d_%H%M%S)
OUT=$DIR/site_$STAMP.sql.gz
mkdir -p "$DIR"
echo "── $(date '+%F %T') дамп pmkpark_site"
docker exec site-db sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --quick --routines --triggers --events \
  --ignore-table=pmkpark_site.b_user_session pmkpark_site && mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --no-data pmkpark_site b_user_session' \
  2>/dev/null | gzip -6 > "$OUT.part"
gzip -t "$OUT.part"
tables=$(gunzip -c "$OUT.part" | grep -c '^CREATE TABLE' || true)
[ "$tables" -gt 100 ] || { echo "ОШИБКА: в дампе $tables таблиц"; rm -f "$OUT.part"; exit 1; }
mv "$OUT.part" "$OUT"
find "$DIR" -maxdepth 1 -name 'site_*.sql.gz' -mtime +$KEEP_DAYS -delete
echo "   $(basename "$OUT") $(du -h "$OUT" | cut -f1), таблиц $tables — ок"
