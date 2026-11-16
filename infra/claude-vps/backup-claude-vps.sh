#!/bin/bash
# Ночной бэкап сервера с ИИ claude-vps (132.243.127.33, FirstVDS) в Yandex Object Storage (Антон 16.11.2026).
# Ставится: /usr/local/sbin/backup-claude-vps (root). Cron root: 40 4 * * *  (время сервера, +10).
# Второй уровень к ежедневному бэкапу всей машины у FirstVDS (Кибер Бэкап).
#
# ЧТО: один архив за ночь daily/claude-vps_ГГГГММДД_ЧЧММ.tar.zst.enc — проекты тем, сессии и настройки Claude,
#   мост Телеграма и его состояние, ключи SSH, хранилище Обсидиана (claudeuser), гость chulkov, claudeadmin,
#   /opt/modules (Qdrant-память, заметки, VPN), системное (песочница, claude-guest, sudoers, systemd, ufw, cron).
# БЕЗ: окружения Python/Node, модель распознавания речи (.hf-cache), кэши — всё это ставится заново.
# ШИФР: openssl aes-256-cbc pbkdf2 200000, пароль /root/.backup-passphrase (у Антона в менеджере паролей;
#   НЕ тот, что у pmk-main). Ключ бакета /root/.yc-backup.env — сервисный аккаунт claude-vps-backup-writer,
#   storage.uploader ТОЛЬКО на бакет pmk-claude-vps-backup: загрузить можно, удалить/прочитать чужое — нет.
#   Хранение — правило бакета daily/ 30 дней (+ версии 30 дней).
# ВОССТАНОВЛЕНИЕ:
#   rclone copyto yc:pmk-claude-vps-backup/daily/<архив> ./b.enc
#   openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:./пароль -in b.enc | zstd -d | tar -xf - -C /
set -euo pipefail
LOG_TAG="── $(date '+%F %T') claude-vps → Yandex"
echo "$LOG_TAG"
ENV=/root/.yc-backup.env; PASSF=/root/.backup-passphrase; STATE=/var/lib/claude-vps-backup
[ -r "$ENV" ] || { echo "ОШИБКА: нет $ENV"; exit 1; }
[ -s "$PASSF" ] || { echo "ОШИБКА: нет $PASSF"; exit 1; }
. "$ENV"; : "${YC_KEY_ID:?}" "${YC_SECRET:?}" "${YC_BUCKET:?}"
export RCLONE_CONFIG=/dev/null RCLONE_CONFIG_YC_TYPE=s3 RCLONE_CONFIG_YC_PROVIDER=Other \
  RCLONE_CONFIG_YC_ENDPOINT=https://storage.yandexcloud.net RCLONE_CONFIG_YC_REGION=ru-central1 \
  RCLONE_CONFIG_YC_ACCESS_KEY_ID="$YC_KEY_ID" RCLONE_CONFIG_YC_SECRET_ACCESS_KEY="$YC_SECRET" \
  RCLONE_CONFIG_YC_NO_CHECK_BUCKET=true
mkdir -p "$STATE"

# Snapshot Qdrant лучше делать через его API, но для 1–2 пользователей хватает копии каталога на лету:
# коллекция маленькая (≈90 МБ), Qdrant пишет WAL — при восстановлении он дочитает журнал.
INCLUDE=(
  /home/claudeuser /home/chulkov /home/claudeadmin /opt/modules
  /etc/apparmor.d/bwrap /usr/local/bin/claude-guest /usr/local/share/claude-guest
  /etc/sudoers.d /etc/systemd/system /etc/ssh/sshd_config.d /etc/ufw /etc/fail2ban
  /var/spool/cron/crontabs /etc/hosts /etc/hostname
)
EXCLUDE=(
  --exclude='*/.cache' --exclude='*/.local/share/scrapling-venv' --exclude='*/.local/node'
  --exclude='*/.local/share/photo-venv' --exclude='*/tools/.photo-venv' --exclude='*/.venv*' --exclude='*/.hf-cache'
  --exclude='*/.npm' --exclude='*/node_modules' --exclude='*/__pycache__'
  --exclude='*/.local/share/claude' --exclude='*/.local/share/uv'                  # сам Claude Code — ставится заново
  --exclude='*/.local/share/stt/venv' --exclude='*/.local/share/stt/model-*'      # распознавание речи: 0,9 ГБ, скачивается
  --exclude='*/.local/share/photo-venv'
  --exclude='*/outbox/sent'
)
present=(); for p in "${INCLUDE[@]}"; do [ -e "$p" ] && present+=("${p#/}"); done
OUT=/var/tmp/claude-vps_$(date +%Y%m%d_%H%M).tar.zst.enc
trap 'rm -f "$OUT"' EXIT
tar -C / "${EXCLUDE[@]}" --warning=no-file-changed --ignore-failed-read -cf - "${present[@]}" 2>/dev/null \
  | zstd -q -T2 -10 \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$PASSF" > "$OUT" || [ "${PIPESTATUS[0]}" -le 1 ]
size=$(stat -c %s "$OUT")
[ "$size" -gt 1048576 ] || { echo "ОШИБКА: архив подозрительно мал ($size Б)"; exit 1; }
# проверка: архив расшифровывается и читается до конца
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$PASSF" -in "$OUT" | zstd -q -d | tar -tf - > /dev/null \
  || { echo "ОШИБКА: архив не читается после шифрования"; exit 1; }
rclone --retries 5 --low-level-retries 10 --stats 0 copyto "$OUT" "yc:$YC_BUCKET/daily/$(basename "$OUT")" --s3-no-head
echo "   $(basename "$OUT") $((size / 1048576)) МБ — выгружен"
date '+%F %T' > "$STATE/last_ok"
echo "   готово"
