#!/bin/bash
# Сторож бэкапов (16.11.2026, Антон: «проверим, что бэкапы постоянно создаются на Яндекс Клауд»).
# Cron 09:00. Молчит, когда всё хорошо. Пишет ЛИЧНО Антону (admin) через бота @Dv_laba_bot, если:
#   - выгрузки в облако не было больше 26 ч (/var/lib/pmk-offsite/last_ok),
#   - ночной дамп Odoo старше 26 ч,
#   - в журнале выгрузки за последний прогон есть «ОШИБКА».
#   0 9 * * * /opt/factory-platform/infra/server/backup-check.sh >> /var/log/backup-check.log 2>&1
set -uo pipefail
LIMIT=$((26 * 3600))
now=$(date +%s)
problems=()

age_of() { [ -e "$1" ] && echo $(( now - $(stat -c %Y "$1") )) || echo 999999999; }

[ "$(age_of /var/lib/pmk-offsite/last_ok)" -lt "$LIMIT" ] || \
  problems+=("в Яндекс не выгружалось больше суток (последний раз: $(cat /var/lib/pmk-offsite/last_ok 2>/dev/null || echo никогда))")
last_dump=$(ls -1t /opt/backups/odoo/odoo_*.dump 2>/dev/null | head -1)
[ -n "$last_dump" ] && [ "$(age_of "$last_dump")" -lt "$LIMIT" ] || \
  problems+=("ночной дамп Odoo не снят (последний: $(basename "${last_dump:-нет}"))")
if [ -d /opt/site/www ]; then
  last_site=$(ls -1t /opt/backups/site/site_*.sql.gz 2>/dev/null | head -1)
  [ -n "$last_site" ] && [ "$(age_of "$last_site")" -lt "$LIMIT" ] || \
    problems+=("ночной дамп сайта не снят (последний: $(basename "${last_site:-нет}"))")
fi
run=$(tac /var/log/odoo-offsite.log 2>/dev/null | sed '/^── /q' | tac)
echo "$run" | grep -q "ОШИБКА" && problems+=("выгрузка: $(echo "$run" | grep -m1 'ОШИБКА')")

echo "── $(date '+%F %T') проблем: ${#problems[@]}"
[ ${#problems[@]} -eq 0 ] && exit 0
printf '   %s\n' "${problems[@]}"

# Токен бота и Телеграм Антона — из базы Odoo (в файлах сервера их нет)
q() { docker exec odoo-db psql -U odoo -d odoo -tAc "$1" 2>/dev/null; }
token=$(q "select value from ir_config_parameter where key='pmk_telegram.token'")
chat=$(q "select pmk_telegram_id from res_users where login='admin'")
[ -n "$token" ] && [ -n "$chat" ] || { echo "   некому сообщить: нет токена бота или Телеграма admin"; exit 1; }
text="⚠️ Бэкапы сервера pmk-main (45.153.188.84):"
for p in "${problems[@]}"; do text="$text
• $p"; done
text="$text
Журнал: /var/log/odoo-offsite.log"
curl -sS -m 20 -o /dev/null -w "   Телеграм: %{http_code}\n" "https://api.telegram.org/bot$token/sendMessage" \
  --data-urlencode "chat_id=$chat" --data-urlencode "text=$text"
