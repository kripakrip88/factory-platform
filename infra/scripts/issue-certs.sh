#!/bin/bash
# Первичный выпуск Let's Encrypt сертов для erppark.ru (Фаза 2).
# Предусловие: Фаза A задеплоена (nginx отдаёт /.well-known/acme-challenge/ по :80)
# и DNS всех доменов уже резолвится на этот сервер.
# Запуск на сервере: bash /opt/factory-platform/infra/scripts/issue-certs.sh
# Тест без выпуска: DRY_RUN=1 bash .../issue-certs.sh

set -e
EMAIL="kripakrip88@gmail.com"
DOMAINS=(erppark.ru www.erppark.ru d.erppark.ru n8n.erppark.ru)

# Реальные имена томов (проект compose может быть не "infra").
VOL_CONF=$(docker volume ls --format '{{.Name}}' | grep -E 'certbot_conf$' | head -1)
VOL_WWW=$(docker volume ls --format '{{.Name}}' | grep -E 'certbot_www$' | head -1)
[ -n "$VOL_CONF" ] && [ -n "$VOL_WWW" ] || { echo "❌ ABORT: тома certbot_conf/certbot_www не найдены — сначала задеплой Фазу A."; exit 1; }
echo "📦 Тома: conf=$VOL_CONF www=$VOL_WWW"

echo "🔎 Проверка ACME-пути (Фаза A должна отдавать его по HTTP):"
for d in "${DOMAINS[@]}"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://$d/.well-known/acme-challenge/probe" || echo 000)
  echo "  $d → http=$code (404 = путь обслуживается, ок; 000/301 = проблема DNS/конфига)"
done

ARGS=(); for d in "${DOMAINS[@]}"; do ARGS+=( -d "$d" ); done
DRY=""; [ "${DRY_RUN:-0}" = "1" ] && DRY="--dry-run" && echo "🧪 DRY_RUN — серты НЕ выпускаются, только проверка."

echo "🔐 certbot certonly (webroot)..."
docker run --rm \
  -v "$VOL_CONF":/etc/letsencrypt \
  -v "$VOL_WWW":/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  "${ARGS[@]}" --email "$EMAIL" --agree-tos --no-eff-email \
  --non-interactive --keep-until-expiring $DRY

[ -n "$DRY" ] && { echo "✅ DRY_RUN ок — можно запускать без DRY_RUN."; exit 0; }
echo "✅ Серты выпущены в томе $VOL_CONF (/etc/letsencrypt/live/erppark.ru/)."
echo "   Дальше — Фаза B: включить TLS-конфиг nginx (см. infra/README-domains.md)."
