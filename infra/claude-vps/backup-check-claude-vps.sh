#!/bin/bash
# Сторож бэкапа claude-vps (16.11.2026). Cron root 0 9 * * *. Молчит, если всё хорошо; иначе — Антону в Телеграм
# через бота моста (@pmkpark_app, токен и чат — /home/claudeuser/.config/agent/notify.env).
set -uo pipefail
LAST=/var/lib/claude-vps-backup/last_ok
age=$(( $(date +%s) - $(stat -c %Y "$LAST" 2>/dev/null || echo 0) ))
echo "── $(date '+%F %T') возраст последней выгрузки: $((age / 3600)) ч"
[ "$age" -lt $((26 * 3600)) ] && exit 0
last_err=$(tac /var/log/claude-vps-backup.log 2>/dev/null | sed '/^── /q' | grep -m1 'ОШИБКА' || true)
. /home/claudeuser/.config/agent/notify.env
text="⚠️ Бэкап сервера с ИИ (claude-vps) в Яндекс не выгружался больше суток (последний раз: $(cat "$LAST" 2>/dev/null || echo никогда)).${last_err:+
$last_err}
Журнал: /var/log/claude-vps-backup.log"
curl -sS -m 20 -o /dev/null -w "   Телеграм: %{http_code}\n" "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
  --data-urlencode "chat_id=${TG_OWNER:-$TG_CHAT}" --data-urlencode "text=$text"
