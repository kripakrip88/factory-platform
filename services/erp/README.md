# ERPNext Service

ERPNext v15 — core ERP for CRM, Quotation, BOM, Production.

## First Deploy

```bash
# 1. Add to .env in repo root:
# DB_ROOT_PASSWORD=<strong-password>
# ERP_ADMIN_PASSWORD=<strong-password>
# DOMAIN=yourdomain.com  (or leave empty for IP access)

# 2. Start containers
docker compose -f services/erp/docker-compose.yml --env-file .env up -d

# 3. Wait ~2 min for MariaDB to be ready, then create site (run once)
bash services/erp/init-site.sh

# 4. Access ERPNext at http://SERVER_IP:8080
```

## Daily Operations

```bash
# Start
docker compose -f services/erp/docker-compose.yml --env-file .env up -d

# Stop
docker compose -f services/erp/docker-compose.yml down

# Logs
docker compose -f services/erp/docker-compose.yml logs -f backend

# Restart single service
docker compose -f services/erp/docker-compose.yml restart backend
```

## Containers

| Container | Role |
|-----------|------|
| `db` | MariaDB 10.6 — ERPNext database |
| `backend` | Frappe/ERPNext Python app |
| `frontend` | Nginx serving ERPNext UI on :8080 |
| `websocket` | Realtime updates (Socket.IO) |
| `queue-short/long/default` | Background job workers |
| `scheduler` | Cron jobs (emails, reports) |
| `redis-cache/queue/socketio` | Redis instances |
