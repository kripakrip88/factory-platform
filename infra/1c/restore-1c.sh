#!/bin/bash
# Загрузить базу 1С из выгрузки .dt (16.11.2026). Текущая база не удаляется — уходит в buh.before-<время>.
#   bash restore-1c.sh /путь/база.dt
# Перед загрузкой Apache останавливается (файловая база — монопольный доступ), после — проверка веб-клиента.
set -euo pipefail
DT="${1:?путь к выгрузке .dt}"
VER=8.3.27.2342
BIN=/opt/1cv8/x86_64/$VER
BASES=/opt/1c/bases
IB=buh
[ -s "$DT" ] || { echo "нет файла $DT"; exit 1; }
STAMP=$(date +%Y%m%d-%H%M)
systemctl stop apache2
if [ -d "$BASES/$IB" ]; then mv "$BASES/$IB" "$BASES/$IB.before-$STAMP"; echo "прежняя база → $BASES/$IB.before-$STAMP"; fi
mkdir -p "$BASES/$IB"
"$BIN/ibcmd" infobase create --db-path="$BASES/$IB" --restore="$DT" 2>&1 | tail -2
chown -R www-data:www-data "$BASES"
systemctl start apache2
sleep 2
ls -la "$BASES/$IB/1Cv8.1CD"
curl -s -o /dev/null -w "веб-клиент: %{http_code}\n" "http://172.17.0.1:8091/$IB/ru_RU/"
