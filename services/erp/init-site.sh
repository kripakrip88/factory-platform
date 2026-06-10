#!/bin/bash
# Run once after first docker compose up to create the ERPNext site
# Usage: bash services/erp/init-site.sh

set -e

SITE_NAME=${SITE_NAME:-erp.localhost}
ADMIN_PASSWORD=${ERP_ADMIN_PASSWORD:-admin}
DB_ROOT_PASSWORD=${DB_ROOT_PASSWORD:-changeme}

echo "Creating site: $SITE_NAME"

# Write common_site_config.json with correct db_host for Docker networking
docker compose -f services/erp/docker-compose.yml exec backend bash -c '
cat > /home/frappe/frappe-bench/sites/common_site_config.json << EOF
{
  "db_host": "db",
  "db_port": 3306,
  "redis_cache": "redis://redis-cache:6379",
  "redis_queue": "redis://redis-queue:6379",
  "redis_socketio": "redis://redis-socketio:6379",
  "socketio_port": 9000
}
EOF'

docker compose -f services/erp/docker-compose.yml exec backend \
  bench new-site "$SITE_NAME" \
  --mariadb-root-password "$DB_ROOT_PASSWORD" \
  --admin-password "$ADMIN_PASSWORD" \
  --install-app erpnext

# Grant DB user access from any host (needed in Docker networking)
DB_NAME=$(docker compose -f services/erp/docker-compose.yml exec backend \
  cat /home/frappe/frappe-bench/sites/"$SITE_NAME"/site_config.json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['db_name'])")
DB_PASS=$(docker compose -f services/erp/docker-compose.yml exec backend \
  cat /home/frappe/frappe-bench/sites/"$SITE_NAME"/site_config.json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['db_password'])")
docker compose -f services/erp/docker-compose.yml exec db \
  mysql -uroot -p"$DB_ROOT_PASSWORD" -e \
  "GRANT ALL ON \`${DB_NAME}\`.* TO '${DB_NAME}'@'%' IDENTIFIED BY '${DB_PASS}'; FLUSH PRIVILEGES;"

echo "Installing Frappe CRM..."
docker compose -f services/erp/docker-compose.yml exec backend \
  bench get-app crm --branch main
docker compose -f services/erp/docker-compose.yml exec backend \
  bench --site "$SITE_NAME" install-app crm

echo "Installing saas_theme..."
docker compose -f services/erp/docker-compose.yml exec backend \
  bench get-app saas_theme --branch version-16 https://github.com/vineyrawat/saas_theme
docker compose -f services/erp/docker-compose.yml exec backend \
  bench --site "$SITE_NAME" install-app saas_theme

echo "Setting site as default"
docker compose -f services/erp/docker-compose.yml exec backend \
  bench --site "$SITE_NAME" set-config host_name "http://$SITE_NAME"

docker compose -f services/erp/docker-compose.yml exec backend \
  bench use "$SITE_NAME"

echo ""
echo "✅ ERPNext site created: $SITE_NAME"
echo "   Admin password: $ADMIN_PASSWORD"
echo "   ERP:  http://SERVER_IP:8080"
echo "   CRM:  http://SERVER_IP:8080/crm"
