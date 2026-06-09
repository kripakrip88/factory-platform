#!/bin/bash
# Run once after first docker compose up to create the ERPNext site
# Usage: bash services/erp/init-site.sh

set -e

SITE_NAME=${SITE_NAME:-erp.localhost}
ADMIN_PASSWORD=${ERP_ADMIN_PASSWORD:-admin}
DB_ROOT_PASSWORD=${DB_ROOT_PASSWORD:-changeme}

echo "Creating site: $SITE_NAME"

docker compose -f services/erp/docker-compose.yml exec backend \
  bench new-site "$SITE_NAME" \
  --mariadb-root-password "$DB_ROOT_PASSWORD" \
  --admin-password "$ADMIN_PASSWORD" \
  --install-app erpnext

echo "Setting site as default"
docker compose -f services/erp/docker-compose.yml exec backend \
  bench --site "$SITE_NAME" set-config host_name "http://$SITE_NAME"

docker compose -f services/erp/docker-compose.yml exec backend \
  bench use "$SITE_NAME"

echo ""
echo "✅ ERPNext site created: $SITE_NAME"
echo "   Admin password: $ADMIN_PASSWORD"
echo "   Open: http://$SITE_NAME (or http://SERVER_IP:8080)"
