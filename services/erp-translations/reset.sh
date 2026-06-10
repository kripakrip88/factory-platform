#!/usr/bin/env bash
# Откат кастомных переводов — возврат к стандартным переводам ERPNext
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SITE_NAME="${SITE_NAME:-erp.localhost}"
ERP_COMPOSE="-f ${REPO_ROOT}/services/erp/docker-compose.yml"

echo "⚠️  Это удалит ВСЕ кастомные русские переводы для сайта ${SITE_NAME}."
read -r -p "Продолжить? [y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
  echo "Отменено."
  exit 0
fi

echo "[1/2] Удаление кастомных переводов..."
docker compose ${ERP_COMPOSE} exec backend \
  bench --site "${SITE_NAME}" execute frappe.translate.clear_translations --args "['ru']"
echo "    OK"

echo "[2/2] Очистка кэша..."
docker compose ${ERP_COMPOSE} exec backend \
  bench --site "${SITE_NAME}" clear-cache
echo "    OK"

echo ""
echo "✅ Откат завершён. Система вернулась к стандартным переводам ERPNext."
