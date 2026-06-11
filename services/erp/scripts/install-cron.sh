#!/bin/bash
# Устанавливает cron job для автобэкапа ERPNext
# Запускать один раз на сервере: bash services/erp/scripts/install-cron.sh

CRON_JOB="0 3 * * * /opt/factory-platform/services/erp/scripts/backup.sh >> /var/log/erp-backup.log 2>&1"

# Добавить если ещё не добавлен
(crontab -l 2>/dev/null | grep -q "backup.sh") || \
  (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "✅ Cron job установлен — бэкап каждый день в 03:00"
crontab -l
