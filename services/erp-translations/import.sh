#!/usr/bin/env bash
# Импорт кастомных переводов ru-metal.csv в ERPNext
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CSV_FILE="${SCRIPT_DIR}/ru-metal.csv"
SITE_NAME="${SITE_NAME:-erp.localhost}"
ERP_COMPOSE="-f ${REPO_ROOT}/services/erp/docker-compose.yml"

# ─── Проверки ─────────────────────────────────────────────────────────────────

if [[ ! -f "${CSV_FILE}" ]]; then
  echo "ERROR: ${CSV_FILE} не найден. Сначала запустите generate-translations.py"
  exit 1
fi

echo "[1/4] Проверка доступности ERPNext..."
if ! docker compose ${ERP_COMPOSE} ps backend 2>/dev/null | grep -q "running"; then
  echo "ERROR: контейнер backend не запущен"
  echo "Запустите: docker compose ${ERP_COMPOSE} --env-file ${REPO_ROOT}/.env up -d"
  exit 1
fi
echo "    OK"

# ─── Копируем CSV в контейнер ─────────────────────────────────────────────────

echo "[2/4] Копирование CSV в контейнер..."
CONTAINER_CSV="/tmp/ru-metal.csv"
docker compose ${ERP_COMPOSE} cp "${CSV_FILE}" backend:"${CONTAINER_CSV}"
echo "    OK → ${CONTAINER_CSV}"

# ─── Импорт через frappe.translate ────────────────────────────────────────────

echo "[3/4] Импорт переводов..."
docker compose ${ERP_COMPOSE} exec backend \
  bench --site "${SITE_NAME}" import-translations ru "${CONTAINER_CSV}"
echo "    OK"

# ─── Очистка кэша ─────────────────────────────────────────────────────────────

echo "[4/4] Очистка кэша..."
docker compose ${ERP_COMPOSE} exec backend \
  bench --site "${SITE_NAME}" clear-cache
echo "    OK"

# ─── Итог ─────────────────────────────────────────────────────────────────────

ROW_COUNT=$(tail -n +2 "${CSV_FILE}" | wc -l | tr -d ' ')
echo ""
echo "✅ Импорт завершён"
echo "   Записей: ${ROW_COUNT}"
echo "   Сайт: ${SITE_NAME}"
echo "   Для проверки откройте: http://SERVER_IP:8080 → Setup → Translation"
