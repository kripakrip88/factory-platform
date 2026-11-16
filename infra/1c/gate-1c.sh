#!/bin/bash
# Второй пароль перед 1С (ворота nginx на https://1c.erppark.ru, 16.11.2026). Создаёт/МЕНЯЕТ:
#   /opt/edge/nginx/auth/1c.htpasswd   — логин и хэш пароля ворот
#   /opt/edge/nginx/auth/1c-gate.conf  — кука-пропуск и заголовок ворот (секрет, только root)
# Новый пароль — в /root/1c-vhod.txt (забрать в менеджер паролей и удалить). Старые куки после смены
# перестают действовать — все заново вводят пароль ворот.
#   bash gate-1c.sh [логин]       (по умолчанию pmk)
set -euo pipefail
AUTH=/opt/edge/nginx/auth
U="${1:-pmk}"
umask 077
mkdir -p "$AUTH"; chmod 711 "$AUTH"
P=$(openssl rand -base64 30 | tr -d '/+=\n' | cut -c1-20)
TOKEN=$(openssl rand -hex 24)
HASH=$(printf '%s' "$P" | openssl passwd -apr1 -stdin)
B64=$(printf '%s:%s' "$U" "$P" | base64 -w0)
printf '%s:%s\n' "$U" "$HASH" > "$AUTH/1c.htpasswd.new"
chmod 644 "$AUTH/1c.htpasswd.new"          # читает рабочий процесс nginx (не root); там только хэш
cat > "$AUTH/1c-gate.conf.new" <<CONF
# создано gate-1c.sh $(date '+%F %T') — не править руками
map \$cookie_pmk1c \$pmk1c_ok { "$TOKEN" 1; default 0; }
map \$host \$pmk1c_token { default "$TOKEN"; }
map \$http_authorization \$pmk1c_auth { "Basic $B64" ""; default \$http_authorization; }
limit_req_zone \$binary_remote_addr zone=pmk1c_gate:1m rate=10r/m;
CONF
mv "$AUTH/1c.htpasswd.new" "$AUTH/1c.htpasswd"
mv "$AUTH/1c-gate.conf.new" "$AUTH/1c-gate.conf"
printf 'Ворота 1С https://1c.erppark.ru\nЛогин: %s\nПароль: %s\n' "$U" "$P" > /root/1c-vhod.txt
echo "ворота 1С: логин $U, новый пароль — в /root/1c-vhod.txt"
if docker ps --format '{{.Names}}' | grep -qx edge-nginx; then
  cd /opt/edge && docker compose exec -T nginx nginx -t -q && docker compose exec -T nginx nginx -s reload && echo "nginx перечитан"
fi
