#!/bin/bash
# Выдать свежую ссылку для входа в Carbon.
#
# Зачем: у Carbon нет входа по паролю — только «волшебная ссылка» на почту, а SMTP
# у стенда не настроен, письма не уходят. Скрипт берёт ссылку у самого GoTrue
# (admin/generate_link) и чинит её: GoTrue отдаёт action_link БЕЗ префикса /auth/v1,
# по такой ссылке вход не работает.
#
# Запуск на сервере:  bash /opt/experiments/carbon/login-link.sh [email]
# По умолчанию — admin@erppark.ru. Ссылка одноразовая.

set -uo pipefail

EMAIL="${1:-admin@erppark.ru}"
API_PUBLIC="https://api.erppark.ru"
APP_PUBLIC="https://carbon.erppark.ru"

# service_role_key смонтирован секретом в несколько сервисов стека — берём из любого живого
SRC=$(docker ps --filter "name=carbon_storage" --format "{{.Names}}" | head -1)
[ -n "$SRC" ] || SRC=$(docker ps --filter "name=carbon_erp" --format "{{.Names}}" | head -1)
[ -n "$SRC" ] || { echo "❌ стек carbon не запущен"; exit 1; }

KEY=$(docker exec "$SRC" cat /run/secrets/service_role_key 2>/dev/null)
[ -n "$KEY" ] || { echo "❌ не удалось прочитать service_role_key"; exit 1; }

REQ=$(mktemp)
printf '{"type":"magiclink","email":"%s"}' "$EMAIL" > "$REQ"

RESP=$(docker run --rm --network carbon_internal -v "$REQ":/d.json:ro curlimages/curl:latest \
  -s -X POST http://kong:8000/auth/v1/admin/generate_link \
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" --data @/d.json 2>&1)
rm -f "$REQ"

TOKEN=$(printf '%s' "$RESP" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("hashed_token") or d.get("action_link","").split("token=")[-1].split("&")[0])
except Exception:
    print("")
' 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "❌ токен не получен. Ответ GoTrue:"
  printf '%s\n' "$RESP" | head -c 400
  exit 1
fi

echo
echo "Ссылка для входа ($EMAIL) — одноразовая:"
echo
echo "${API_PUBLIC}/auth/v1/verify?token=${TOKEN}&type=magiclink&redirect_to=${APP_PUBLIC}/callback"
echo
