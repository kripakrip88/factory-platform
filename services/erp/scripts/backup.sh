#!/bin/bash
# Бэкап ERPNext — запускается по cron раз в сутки
BACKUP_DIR="/opt/factory-platform/backups/erp"
DATE=$(date +%Y-%m-%d_%H-%M)
KEEP_DAYS=7

mkdir -p $BACKUP_DIR

# Бэкап через bench
docker compose -f /opt/factory-platform/services/erp/docker-compose.yml \
  exec -T backend \
  bench --site erp.localhost backup --with-files

# Скопировать из контейнера
docker compose -f /opt/factory-platform/services/erp/docker-compose.yml \
  cp backend:/home/frappe/frappe-bench/sites/erp.localhost/private/backups/. \
  $BACKUP_DIR/

# Переименовать последний бэкап с датой
find $BACKUP_DIR -newer $BACKUP_DIR -name "*.sql.gz" | \
  xargs -I{} mv {} $BACKUP_DIR/${DATE}-database.sql.gz 2>/dev/null || true

# Удалить бэкапы старше 7 дней
find $BACKUP_DIR -mtime +$KEEP_DAYS -delete

echo "✅ Бэкап завершён: $BACKUP_DIR/${DATE}-database.sql.gz"
