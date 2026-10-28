#!/bin/bash
# Установка синхронизации на VPN-сервер. Запускать на VPN-сервере от root:
#   bash install.sh <адрес сервера для ссылок> [адрес Odoo]
#   bash install.sh 31.77.141.89 https://erppark.ru/pmk_vpn/sync
#
# Что делает (повторный запуск безопасен):
#   1. кладёт vpn_sync.py в /usr/local/lib/vpn-sync/;
#   2. создаёт /etc/vpn-sync/env с новым секретом (если файла ещё нет);
#   3. включает в конфиге Xray API и статистику — с копией конфига и
#      проверкой; при изменении перезапускает Xray (соединения рвутся на секунду);
#   4. ставит и запускает службу vpn-sync.
# В конце печатает секрет: его же записать в Odoo (pmk_vpn.sync_token).
set -euo pipefail
HOST=${1:?укажите адрес сервера для ссылок, например 31.77.141.89}
ODOO_URL=${2:-https://erppark.ru/pmk_vpn/sync}
HERE=$(cd "$(dirname "$0")" && pwd)
CONFIG=/usr/local/etc/xray/config.json

install -d -m 755 /usr/local/lib/vpn-sync
install -m 755 "$HERE/vpn_sync.py" /usr/local/lib/vpn-sync/vpn_sync.py

install -d -m 700 /etc/vpn-sync
if [ ! -f /etc/vpn-sync/env ]; then
    umask 077
    cat > /etc/vpn-sync/env <<EOF
ODOO_URL=$ODOO_URL
SYNC_TOKEN=$(openssl rand -hex 32)
VPN_HOST=$HOST
XRAY_CONFIG=$CONFIG
XRAY_API=127.0.0.1:10085
EOF
fi

cp "$CONFIG" "$CONFIG.bak-vpnsync-$(date +%Y%m%d-%H%M%S)"
if [ "$(XRAY_CONFIG=$CONFIG XRAY_API=127.0.0.1:10085 python3 /usr/local/lib/vpn-sync/vpn_sync.py --prepare-config)" = changed ]; then
    chgrp nogroup "$CONFIG"; chmod 640 "$CONFIG"
    xray run -test -config "$CONFIG" >/dev/null
    systemctl restart xray
    echo "Xray: включены API и статистика, перезапущен"
fi

install -m 644 "$HERE/vpn-sync.service" /etc/systemd/system/vpn-sync.service
systemctl daemon-reload
systemctl enable --now vpn-sync >/dev/null
systemctl restart vpn-sync
sleep 3
systemctl --no-pager --lines=5 status vpn-sync | sed -n '1,3p;/INFO\|WARN\|ERROR/p'
echo
echo "Секрет для Odoo (системный параметр pmk_vpn.sync_token):"
grep '^SYNC_TOKEN=' /etc/vpn-sync/env | cut -d= -f2
