#!/bin/bash
# 1С:Предприятие 8.3 на pmk-main (16.11.2026): ФАЙЛОВАЯ база + веб-публикация в Apache.
# Решения Антона: Бухгалтерия предприятия 3.0, 1–2 пользователя, существующая база (.dt пришлют), лицензии купят.
#
#   bash install-1c.sh            — платформа, Apache, проверочная пустая база «buh», публикация /buh
# Идемпотентно. Сервер 1С (ragent, порты 1540/1541/1560+) НЕ запускается: файловому режиму не нужен.
# Снаружи — только https://1c.erppark.ru (общий nginx → 172.17.0.1:8091 → Apache → модуль 1С).
#
# Загрузить настоящую базу: bash /opt/factory-platform/infra/1c/restore-1c.sh /путь/база.dt
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/version.sh"   # VER, BIN
DIST=/opt/1c/dist
ZIP=$DIST/deb64_${VER//./_}.zip
BASES=/opt/1c/bases
IB=buh
WWW=/opt/1c/www
export DEBIAN_FRONTEND=noninteractive
step() { echo; echo "══ $*"; }

step "1. Русская локаль, шрифты, зависимости платформы"
apt-get update -qq
apt-get install -y -qq locales fontconfig fonts-liberation fonts-dejavu-core libgsf-1-114 libglib2.0-0 \
  unixodbc imagemagick libkrb5-3 unzip >/dev/null
grep -q '^ru_RU.UTF-8' /etc/locale.gen || echo 'ru_RU.UTF-8 UTF-8' >> /etc/locale.gen
locale-gen ru_RU.UTF-8 >/dev/null

step "2. Платформа 1С $VER (common, server, ws + русский язык)"
if [ ! -x "$BIN/ibcmd" ]; then
  [ -f "$ZIP" ] || { echo "нет $ZIP (releases.1c.ru → Платформа 8.3 → Сервер для DEB-based Linux)"; exit 1; }
  rm -rf "$DIST/deb" && mkdir -p "$DIST/deb" && unzip -q -o "$ZIP" -d "$DIST/deb"
  cd "$DIST/deb"
  dpkg -i ./*-common_*.deb ./*-common-nls_*.deb ./*-server_*.deb ./*-server-nls_*.deb ./*-ws_*.deb ./*-ws-nls_*.deb \
    >/dev/null 2>&1 || apt-get install -f -y -qq >/dev/null
  dpkg -l | grep -c "1c-enterprise-$VER" | xargs echo "пакетов 1С:"
fi
# прежние версии платформы — убрать (модуль Apache должен быть один, от $VER)
old=$(dpkg-query -W -f '${Package}\n' '1c-enterprise-*' 2>/dev/null | grep -v -- "-$VER-" | grep -v -- "-$VER\$" || true)
[ -n "$old" ] && { echo "удаляю прежние пакеты 1С: $(echo $old | tr '\n' ' ')"; apt-get purge -y -qq $old >/dev/null; }
"$BIN/ibcmd" --version 2>/dev/null | head -1 || true

step "3. Apache только на 172.17.0.1:8091 (80/443 — у общего nginx)"
if ! command -v apache2 >/dev/null; then
  # не дать apt запустить Apache на *:80 — там общий nginx в Docker
  printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d; chmod +x /usr/sbin/policy-rc.d
  apt-get install -y -qq apache2 >/dev/null
  rm -f /usr/sbin/policy-rc.d
fi
echo "Listen 172.17.0.1:8091" > /etc/apache2/ports.conf
a2dissite -q 000-default >/dev/null 2>&1 || true
a2enmod -q remoteip headers >/dev/null
cat > /etc/apache2/sites-available/1c.conf <<'EOF'
# 1С за общим nginx (infra/edge, 1c.erppark.ru): TLS снимает он, сюда — http на 172.17.0.1:8091
<VirtualHost 172.17.0.1:8091>
    ServerName 1c.erppark.ru
    DocumentRoot /opt/1c/www
    RemoteIPHeader X-Real-IP
    RemoteIPTrustedProxy 172.16.0.0/12
    RedirectMatch 302 ^/$ https://1c.erppark.ru/buh/
    ErrorLog ${APACHE_LOG_DIR}/1c-error.log
    CustomLog ${APACHE_LOG_DIR}/1c-access.log "%a %t \"%r\" %>s %b %D"
</VirtualHost>
EOF
a2ensite -q 1c >/dev/null
# общий nginx живёт в Docker-сети: к Apache (процесс на хосте, не порт Docker) его пускает только это правило
ufw allow from 172.16.0.0/12 to 172.17.0.1 port 8091 proto tcp comment '1C apache for edge nginx' >/dev/null
mkdir -p "$WWW" "$BASES"

step "4. Информационная база «$IB» (пока пустая проверочная — заменит restore-1c.sh)"
if [ ! -f "$BASES/$IB/1Cv8.1CD" ]; then
  mkdir -p "$BASES/$IB"
  "$BIN/ibcmd" infobase create --db-path="$BASES/$IB" 2>&1 | tail -2
fi
chown -R www-data:www-data "$BASES" "$WWW"
chmod 750 "$BASES"
# 1С пишет кэш в домашнюю папку пользователя Apache (www-data → /var/www, она root) — без этого
# веб-клиент: «В данный момент вход в приложение невозможен»
install -d -o www-data -g www-data /var/www/.1cv8 /var/www/.1C
# Лицензия файловой базы через веб: её получает модуль 1С в Apache (www-data) и пишет в /var/1C/licenses
# (владелец usr1cv8:grp1cv8) — без группы активация пин-кода падает на сохранении файла (17.11.2026)
getent group grp1cv8 >/dev/null && usermod -aG grp1cv8 www-data

step "5. Веб-публикация /$IB"
CONF=/etc/apache2/conf-available/1c-$IB.conf
rm -f "$CONF"; touch "$CONF"   # модуль wsap24 — от текущей $VER
"$BIN/webinst" -publish -apache24 -wsdir "$IB" -dir "$WWW/$IB" -connstr "File=\"$BASES/$IB\";" -confpath "$CONF" 2>&1 | tail -1
a2enconf -q "1c-$IB" >/dev/null
chown -R www-data:www-data "$WWW"
apache2ctl configtest 2>&1 | tail -1
systemctl enable -q apache2 && systemctl restart apache2

step "6. Проверка"
sleep 2
ss -ltnp | grep -E ':8091 ' | sed 's/users:.*//'
curl -s -o /dev/null -w "веб-клиент /$IB/: %{http_code}\n" "http://172.17.0.1:8091/$IB/ru_RU/"
echo "Готово. Дальше: DNS 1c.erppark.ru → сертификат (edge.sh cert 1c.erppark.ru), база — restore-1c.sh, лицензия."
