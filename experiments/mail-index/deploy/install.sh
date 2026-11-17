#!/bin/bash
# Установка mail-index на claude-vps (root). Повторный запуск = обновление кода, данные не трогает.
#   bash deploy/install.sh            — из папки experiments/mail-index
# Пароль приложения mail.ru: /etc/mail-index/imap.env (MAIL_USER, MAIL_PASS) — кладёт Антон сам, скрытым вводом.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/mail-index
DATA=/srv/mail-index
USR=mailidx

id "$USR" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$USR"
# Claude в Телеграме (claudeuser) читает Markdown и индекс, но не пароль
getent group "$USR" | grep -q claudeuser || usermod -aG "$USR" claudeuser
command -v pdftotext >/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq poppler-utils >/dev/null

install -d -o root -g root -m 755 "$APP"
rsync -a --delete --exclude tests --exclude '__pycache__' "$SRC/mailindex" "$SRC/requirements.txt" "$APP/"
[ -x "$APP/venv/bin/python" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"

install -d -o "$USR" -g "$USR" -m 2750 "$DATA"
install -d -m 750 -o root -g "$USR" /etc/mail-index
# пароль — только root: systemd читает EnvironmentFile до смены пользователя; claudeuser (в группе mailidx) его не видит
if [ -f /etc/mail-index/imap.env ]; then chown root:root /etc/mail-index/imap.env; chmod 600 /etc/mail-index/imap.env; fi
[ -f /etc/mail-index/settings.env ] || cat > /etc/mail-index/settings.env <<'EOF'
MAIL_INDEX_DIR=/srv/mail-index
# Первая загрузка — только с этой даты (отладка). Пусто = вся история.
MAIL_SINCE=2026-08-17
MAIL_TZ=Asia/Vladivostok
# наш ящик — по нему письма делятся на «наши» и «от собеседника» (нужен и без пароля: reparse, build)
MAIL_OWN_ADDRESSES=pmkpark@mail.ru
EOF
grep -q '^MAIL_OWN_ADDRESSES=' /etc/mail-index/settings.env || echo 'MAIL_OWN_ADDRESSES=pmkpark@mail.ru' >> /etc/mail-index/settings.env

install -m 644 "$SRC/deploy/mail-index-sync.service" "$SRC/deploy/mail-index-sync.timer" /etc/systemd/system/
install -m 755 "$SRC/deploy/mail-search" /usr/local/bin/mail-search
systemctl daemon-reload
echo "установлено. Проба: sudo -u $USR $APP/venv/bin/python -m mailindex sync --limit 30 (с env-файлами)"
echo "таймер (каждые 10 мин) включается отдельно: systemctl enable --now mail-index-sync.timer"
