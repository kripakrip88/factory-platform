#!/bin/sh
# Запуск python-скрипта в odoo shell на стенде. $1 — файл на хосте.
set -e
cd /opt/experiments/odoo
docker compose cp "$1" odoo:/tmp/run_current.py >/dev/null
docker compose exec -T odoo sh -c 'cat /tmp/run_current.py | odoo shell -d odoo --no-http -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=$PASSWORD' 2>&1
