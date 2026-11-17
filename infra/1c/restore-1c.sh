#!/bin/bash
# Загрузить базу 1С (16.11.2026). Текущая база не удаляется — уходит в buh.before-<время>.
#   bash restore-1c.sh /путь/база.dt          — выгрузка из конфигуратора («Выгрузить информационную базу»)
#   bash restore-1c.sh /путь/buh_….1cd.zst   — ночной бэкап (сжатый файл базы, backup-1c.sh)
# Перед загрузкой Apache останавливается (файловая база — монопольный доступ), после — проверка веб-клиента.
set -euo pipefail
DT="${1:?путь к .dt или .1cd.zst}"
. "$(dirname "$(readlink -f "$0")")/version.sh"   # VER, BIN
BASES=/opt/1c/bases
IB=buh
export LANG=ru_RU.UTF-8   # 17.11.2026: без --locale база бралась с языком оболочки (en_US) → «Национальные настройки не соответствуют»
[ -s "$DT" ] || { echo "нет файла $DT"; exit 1; }
STAMP=$(date +%Y%m%d-%H%M)
systemctl stop apache2
if [ -d "$BASES/$IB" ]; then mv "$BASES/$IB" "$BASES/$IB.before-$STAMP"; echo "прежняя база → $BASES/$IB.before-$STAMP"; fi
mkdir -p "$BASES/$IB"
case "$DT" in
  *.1cd.zst) zstd -q -d "$DT" -o "$BASES/$IB/1Cv8.1CD" ;;
  *)         "$BIN/ibcmd" infobase create --db-path="$BASES/$IB" --locale=ru_RU --restore="$DT" 2>&1 | tail -2 ;;
esac
chown -R www-data:www-data "$BASES"
systemctl start apache2
sleep 2
ls -la "$BASES/$IB/1Cv8.1CD"
curl -s -o /dev/null -w "веб-клиент: %{http_code}\n" "http://172.17.0.1:8091/$IB/ru_RU/"
