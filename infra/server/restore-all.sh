#!/bin/bash
# ВОССТАНОВЛЕНИЕ ВСЕГО ИЗ БАКЕТА YANDEX (Odoo erppark.ru + сайт pmkpark.ru) на чистом сервере Ubuntu 24.04.
# Нужно только: доступ к бакету (ключ Yandex Object Storage) и пароль комплекта. GitHub, Mac, Docker Hub,
# pypi, git.ruodoo.ru — НЕ нужны. Подробно — RESTORE.md рядом в бакете.
#
#   export YC_KEY_ID=… YC_SECRET=… YC_BUCKET=pmkpark-odoo-backup
#   bash restore-all.sh            # спросит пароль комплекта
#   (или BACKUP_PASSPHRASE=… bash restore-all.sh)
#   RESTORE_TEST=1 — ПРОВЕРОЧНОЕ восстановление: Odoo обезврежен (кроны, почта, ключи), без ночных заданий
#   (иначе ночью выгрузит себя в тот же бакет поверх настоящих бэкапов) и без туннеля ассистента.
# Шаги можно повторять: каждый проверяет, сделан ли он.
set -euo pipefail
: "${YC_KEY_ID:?export YC_KEY_ID=…}" "${YC_SECRET:?export YC_SECRET=…}" "${YC_BUCKET:=pmkpark-odoo-backup}"
[ "$(id -u)" = 0 ] || { echo "запускать от root"; exit 1; }
KIT=/root/restore-kit
mkdir -p "$KIT"
step() { echo; echo "══ $*"; }

step "1. Пакеты из архива Ubuntu (docker.io, rclone, zstd, git)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 rclone zstd git openssl curl ufw rsync >/dev/null
systemctl enable --now docker
export RCLONE_CONFIG=/dev/null RCLONE_CONFIG_YC_TYPE=s3 RCLONE_CONFIG_YC_PROVIDER=Other \
  RCLONE_CONFIG_YC_ENDPOINT=https://storage.yandexcloud.net RCLONE_CONFIG_YC_REGION=ru-central1 \
  RCLONE_CONFIG_YC_ACCESS_KEY_ID="$YC_KEY_ID" RCLONE_CONFIG_YC_SECRET_ACCESS_KEY="$YC_SECRET"
R="rclone --retries 5 --stats 0"
$R lsf "yc:$YC_BUCKET/kit/" >/dev/null || { echo "нет доступа к бакету $YC_BUCKET"; exit 1; }

step "2. Комплект: код, RuOdoo, секреты"
$R copy "yc:$YC_BUCKET/kit" "$KIT" --exclude "images/**"
if [ ! -d /opt/factory-platform/.git ]; then
  git clone -q "$KIT/code/factory-platform.bundle" /opt/factory-platform
fi
git -C /opt/factory-platform checkout -q feature/experiment-carbon 2>/dev/null || \
  git -C /opt/factory-platform checkout -q -b feature/experiment-carbon origin/feature/experiment-carbon
echo "код: $(git -C /opt/factory-platform log --oneline -1)"
# deploy.sh делает git fetch origin — пусть origin будет голым репозиторием на этом сервере
if [ ! -d /opt/git/factory-platform.git ]; then
  mkdir -p /opt/git && git clone -q --bare "$KIT/code/factory-platform.bundle" /opt/git/factory-platform.git
fi
git -C /opt/factory-platform remote set-url origin /opt/git/factory-platform.git
mkdir -p /opt/experiments/odoo
[ -d /opt/experiments/odoo/ruodoo ] || zstd -dc "$KIT/code/ruodoo.tar.zst" | tar -C /opt/experiments/odoo -xf -
if [ ! -f /opt/experiments/odoo/.env ]; then
  PASS="${BACKUP_PASSPHRASE:-}"
  [ -n "$PASS" ] || { read -r -s -p "Пароль комплекта восстановления: " PASS; echo; }
  printf '%s' "$PASS" > /root/.backup-passphrase; chmod 600 /root/.backup-passphrase
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:/root/.backup-passphrase \
    -in "$KIT/secrets.tar.zst.enc" | zstd -dc | tar -C / -xf -
  echo "секреты: на месте (.env, odoo.conf, ключ бакета, ключ туннеля)"
fi

step "3. Образы Docker из комплекта"
mkdir -p "$KIT/images"
for f in $($R lsf "yc:$YC_BUCKET/kit/images/"); do
  $R copyto "yc:$YC_BUCKET/kit/images/$f" "$KIT/images/$f"
  zstd -dc "$KIT/images/$f" | docker load -q
done

step "4. Подготовка сервера (bootstrap: часовой пояс, swap, ufw, каталоги)"
bash /opt/factory-platform/infra/server/bootstrap.sh || echo "⚠️ bootstrap с замечаниями — смотри вывод"

step "5. Odoo: стек + база и вложения из бакета"
cd /opt/experiments/odoo
cp /opt/factory-platform/experiments/odoo/docker-compose.yml /opt/factory-platform/experiments/odoo/Dockerfile .
set -a; . ./.env; set +a
docker compose up -d --no-build db
for i in $(seq 1 60); do docker compose exec -T db pg_isready -q && break; sleep 2; done
D=$($R lsf "yc:$YC_BUCKET/odoo/db/" | sort | tail -1)
mkdir -p /opt/backups/odoo/restore
$R copyto "yc:$YC_BUCKET/odoo/db/$D" "/opt/backups/odoo/restore/$D"
$R copy "yc:$YC_BUCKET/odoo/filestore" /opt/backups/odoo/restore/filestore --transfers 16
echo "дамп: $D, вложений: $(find /opt/backups/odoo/restore/filestore -type f | wc -l)"
LAYOUT_ONLY=1 sh /opt/factory-platform/experiments/odoo/deploy.sh   # модули в addons-extra до восстановления базы
NEUTRALIZE="${RESTORE_TEST:-}" DUMP=/opt/backups/odoo/restore/$D FILESTORE=/opt/backups/odoo/restore/filestore SKIP_BACKUP=1 \
  bash /opt/factory-platform/experiments/odoo/scripts/restore-prod-from-dump.sh
# все службы стека (расчётчик раскроя, чертёжный процесс): deploy.sh их только перезапускает, если они есть
export NEST_CPUS=$(( $(nproc) < 3 ? $(nproc) : 3 ))
docker compose up -d --no-build

step "6. Сайт pmkpark.ru: файлы и база из бакета"
mkdir -p /opt/site/www /opt/backups/site
$R copy "yc:$YC_BUCKET/site/www" /opt/site/www --transfers 16 --checkers 16
S=$($R lsf "yc:$YC_BUCKET/site/db/" | sort | tail -1)
$R copyto "yc:$YC_BUCKET/site/db/$S" "/opt/backups/site/$S"
bash /opt/factory-platform/infra/site/site-restore.sh "/opt/backups/site/$S"

step "6б. 1С: платформа из комплекта + последняя выгрузка базы"
if $R lsf "yc:$YC_BUCKET/kit/1c/" 2>/dev/null | grep -q '\.zip$'; then
  mkdir -p /opt/1c/dist /opt/backups/1c
  $R copy "yc:$YC_BUCKET/kit/1c" /opt/1c/dist
  bash /opt/factory-platform/infra/1c/install-1c.sh
  C=$($R lsf "yc:$YC_BUCKET/1c/db/" 2>/dev/null | sort | tail -1 || true)
  if [ -n "$C" ]; then
    $R copyto "yc:$YC_BUCKET/1c/db/$C" "/opt/backups/1c/$C"
    bash /opt/factory-platform/infra/1c/restore-1c.sh "/opt/backups/1c/$C"
  fi
  echo "⚠️ 1С: программные лицензии привязаны к «железу» — на новом сервере их надо активировать заново (пин-коды)."
else
  echo "1С в комплекте нет — пропуск"
fi

step "7. Общий вход nginx и туннель ассистента"
bash /opt/factory-platform/infra/edge/edge.sh up
[ -z "${RESTORE_TEST:-}" ] && [ -f /etc/systemd/system/anthropic-relay.service ] && { systemctl daemon-reload; systemctl enable --now anthropic-relay || true; }

step "8. Ночные задания (бэкапы, сертификаты, сторож)"
if [ -n "${RESTORE_TEST:-}" ]; then echo "RESTORE_TEST: ночные задания НЕ ставлю"; else
crontab - <<'CRON'
40 3 * * * /opt/factory-platform/experiments/odoo/scripts/backup-stand.sh --with-files >> /var/log/odoo-backup.log 2>&1
30 3 * * * /opt/factory-platform/infra/1c/backup-1c.sh >> /var/log/1c-backup.log 2>&1
50 3 * * * /opt/factory-platform/infra/site/backup-site.sh >> /var/log/site-backup.log 2>&1
17 4 * * * sh /opt/factory-platform/infra/edge/edge.sh renew >> /var/log/edge-renew.log 2>&1
20 4 * * * /opt/factory-platform/infra/server/backup-offsite.sh >> /var/log/odoo-offsite.log 2>&1
0 9 * * * /opt/factory-platform/infra/server/backup-check.sh >> /var/log/backup-check.log 2>&1
CRON
fi

IP=$(curl -s -m 10 https://ifconfig.me || hostname -I | cut -d' ' -f1)
cat <<EOF

══ ГОТОВО. Осталось руками:
  1. DNS: erppark.ru, www.erppark.ru, pmkpark.ru, www.pmkpark.ru, 1c.erppark.ru → A $IP
  2. После DNS — сертификаты:
       bash /opt/factory-platform/infra/edge/edge.sh cert erppark.ru www.erppark.ru
       bash /opt/factory-platform/infra/edge/edge.sh cert pmkpark.ru www.pmkpark.ru
       bash /opt/factory-platform/infra/edge/edge.sh cert 1c.erppark.ru
  3. Проверка: https://erppark.ru/web/login, https://pmkpark.ru/
  4. МойСклад/почта/банки — ключи в базе, работают сами. Ассистенту нужен туннель (шаг 7) или новый ретранслятор.
EOF
