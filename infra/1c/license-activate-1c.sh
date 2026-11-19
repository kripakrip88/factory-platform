#!/bin/bash
# Активация программной лицензии 1С на сервере pmk-main (17.11.2026).
# Веб-клиент 1С лицензию получать не умеет — нужна утилита 1C:Enterprise License Tools (ring),
# установлена в /opt/1C/1CE (дистрибутив /opt/1c/dist/lictools, releases.1c.ru → EnterpriseLicenseTools).
# Запуск (Антон, с Мака):  ssh -t odoo-new 1c-license-activate
# Пин-код скрипт НЕ знает и не хранит — вводит Антон при запуске.
# Данные владельца — ИП Чулков (реквизиты компании в Odoo). Лицензия — в /var/1C/licenses (её читает Apache).
set -euo pipefail
SERIAL=20001106256
LICDIR=/var/1C/licenses
RING=$(ls -d /opt/1C/1CE/components/1c-enterprise-ring-*/ring | tail -1)
export JAVA_HOME=${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}   # ring 0.20 нужна Java 17 (на 11 не стартует)
# 17.11: модуль лицензий (JAX-WS) на Java 17 падал «Unsafe.defineClass» ДО отправки запроса — открываем java.lang
export RING_OPTS="--add-opens java.base/java.lang=ALL-UNNAMED"
[ -x "$RING" ] || { echo "нет утилиты ring — установить из /opt/1c/dist/lictools (1ce-installer-cli install)"; exit 1; }

read -r -p "Почтовый индекс по адресу регистрации ИП (6 цифр): " ZIP
[[ "$ZIP" =~ ^[0-9]{6}$ ]] || { echo "индекс должен быть из 6 цифр"; exit 1; }
# 19.11: запасной пин — из того же конверта, что и регистрационный номер. Номер с конверта можно ввести
# (Enter — оставить прежний). Офисный сервер активирован основным пином этого же комплекта.
read -r -p "Регистрационный номер с конверта [$SERIAL]: " NEW_SERIAL
NEW_SERIAL=${NEW_SERIAL//[ -]/}
if [ -n "$NEW_SERIAL" ]; then
  [[ "$NEW_SERIAL" =~ ^[0-9]{8,14}$ ]] || { echo "номер — только цифры"; exit 1; }
  SERIAL=$NEW_SERIAL
fi
echo "Регистрационный номер: $SERIAL."
# 17.11: собственный запрос ring «Enter PIN code» по ssh -t зависал на чтении (Enter не доходил) —
# пин читаем сами, без эха, и передаём параметром. Нигде не сохраняется.
read -r -s -p "Пин-код из конверта (цифры не видны при вводе): " PIN; echo
PIN=${PIN//[ -]/}   # убираем только пробелы и дефисы (буквы, если есть в пин-коде, оставляем)
[ ${#PIN} -ge 10 ] || { echo "пин слишком короткий"; exit 1; }
echo "Пин: ${#PIN} знаков. Связываюсь с центром лицензирования 1С (до минуты)…"

before=$(ls "$LICDIR" 2>/dev/null | wc -l)
"$RING" license activate \
  --serial "$SERIAL" \
  --last-name "Чулков" --first-name "Владислав" --middle-name "Витальевич" \
  --company "ИП Чулков Владислав Витальевич" --email "pmkpark@mail.ru" \
  --country "Россия" --region "Хабаровский край" --town "Хабаровск" \
  --street "ул. Калинина" --house "80" --apartment "20" --zip-code "$ZIP" \
  --pin "$PIN" \
  --path "$LICDIR" --conf-location /opt/1cv8/conf --send-statistics false < /dev/null

chown -R usr1cv8:grp1cv8 "$LICDIR"; chmod 2775 "$LICDIR"; chmod 664 "$LICDIR"/* 2>/dev/null || true
echo "Файлов лицензий было: $before, стало: $(ls "$LICDIR" | wc -l)"
"$RING" license list --path "$LICDIR" 2>&1 | tail -5
