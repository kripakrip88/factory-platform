#!/bin/bash
# Комплект восстановления в бакете (16.11.2026, Антон: «восстановление из 1 места, без гитхаба и копии на маке»).
# Вызывается из backup-offsite.sh (переменные rclone уже заданы). Выгружает ТОЛЬКО изменившееся:
#   kit/RESTORE.md, kit/restore-all.sh        — инструкция и скрипт (открытым текстом)
#   kit/code/factory-platform.bundle          — весь git (git bundle --all): код, модули, скрипты
#   kit/code/ruodoo.tar.zst                   — локализация RuOdoo с нашей правкой (у RuOdoo нет истории)
#   kit/images/<образ>.tar.zst                — образы Docker: Docker Hub и pypi при восстановлении не нужны
#   kit/secrets.tar.zst.enc                   — .env, odoo.conf (ключ почты!), ключи — зашифровано паролем
# Пароль шифрования: /root/.backup-passphrase (и у Антона в менеджере паролей). Без него секреты не открыть.
set -euo pipefail
R="${R:?вызывать из backup-offsite.sh}"
B="yc:${YC_BUCKET:?}/kit"
STATE=/var/lib/pmk-offsite/kit
REPO=/opt/factory-platform
mkdir -p "$STATE"
changed() {  # changed <имя> <отпечаток> — 0, если отпечаток новый (и запоминает его после успешной выгрузки)
  [ "$(cat "$STATE/$1" 2>/dev/null)" != "$2" ]
}
mark() { echo "$2" > "$STATE/$1"; }

# 1. Инструкция и скрипт восстановления
for f in RESTORE.md restore-all.sh; do
  h=$(sha256sum "$REPO/infra/server/$f" | cut -c1-16)
  if changed "$f" "$h"; then $R copyto "$REPO/infra/server/$f" "$B/$f"; mark "$f" "$h"; echo "   комплект: $f"; fi
done

# 2. Код — git bundle всех веток и тегов, что есть на сервере
h=$(git -C "$REPO" for-each-ref --format='%(objectname)' | sha256sum | cut -c1-16)
if changed code "$h"; then
  git -C "$REPO" bundle create /tmp/factory-platform.bundle --all 2>/dev/null
  $R copyto /tmp/factory-platform.bundle "$B/code/factory-platform.bundle"; rm -f /tmp/factory-platform.bundle
  mark code "$h"; echo "   комплект: код (git bundle)"
fi

# 3. RuOdoo — каталог целиком (вместе с .git и ручной правкой l10n_ru_upd_xml)
RU=/opt/experiments/odoo/ruodoo
h=$( (git -C "$RU" rev-parse HEAD; git -C "$RU" diff) | sha256sum | cut -c1-16)
if changed ruodoo "$h"; then
  tar -C /opt/experiments/odoo -cf - ruodoo | zstd -q -T0 -10 > /tmp/ruodoo.tar.zst
  $R copyto /tmp/ruodoo.tar.zst "$B/code/ruodoo.tar.zst"; rm -f /tmp/ruodoo.tar.zst
  mark ruodoo "$h"; echo "   комплект: RuOdoo"
fi

# 4. Образы Docker, на которых всё работает
for img in odoo-ru:19.0-20261006 pmk-zk-worker:1 postgres:16-alpine pmkpark-web:8.3.35 mysql:8.0.46 \
           nginx:1.27.5-alpine certbot/certbot:v4.1.1 alpine:3.20; do
  id=$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null) || { echo "   ⚠️ нет образа $img"; continue; }
  name=$(echo "$img" | tr '/:' '__')
  if changed "img_$name" "$id"; then
    docker save "$img" | zstd -q -T0 -6 > "/tmp/$name.tar.zst"
    $R copyto "/tmp/$name.tar.zst" "$B/images/$name.tar.zst"; rm -f "/tmp/$name.tar.zst"
    mark "img_$name" "$id"; echo "   комплект: образ $img"
  fi
done

# 5. Секреты — то, чего нет ни в git, ни в бакете открытым текстом
PASSF=/root/.backup-passphrase
[ -s "$PASSF" ] || { echo "ОШИБКА: нет $PASSF — секреты не зашифровать"; exit 1; }
LIST=(/opt/experiments/odoo/.env /opt/experiments/odoo/odoo.conf /opt/site/.env /root/.yc-backup.env
      /root/.ssh/id_relay /root/.ssh/id_relay.pub /etc/systemd/system/anthropic-relay.service)
present=(); for f in "${LIST[@]}"; do [ -e "$f" ] && present+=("$f"); done
h=$(cat "${present[@]}" | sha256sum | cut -c1-16)
if changed secrets "$h"; then
  tar -C / -cf - "${present[@]#/}" 2>/dev/null | zstd -q | \
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$PASSF" > /tmp/secrets.tar.zst.enc
  $R copyto /tmp/secrets.tar.zst.enc "$B/secrets.tar.zst.enc"; rm -f /tmp/secrets.tar.zst.enc
  mark secrets "$h"; echo "   комплект: секреты (${#present[@]} файлов, зашифровано)"
fi
echo "   комплект восстановления — ок"
