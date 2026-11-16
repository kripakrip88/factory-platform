#!/bin/bash
# Ворота публикации проектов pmkpark.ru (16.11.2026). Ставится в /usr/local/sbin/pmk-site-project (root, 755).
# Единственное, что может ключ Claude из Телеграма (claude-vps) на сервере pmk-main:
#   ssh siteproj@pmk-main list
#   ssh siteproj@pmk-main hide <id> | show <id>
#   tar -czf - -C <папка с project.json и фото> . | ssh siteproj@pmk-main add
# authorized_keys siteproj: from="132.243.127.33",restrict,command="sudo -n /usr/local/sbin/pmk-site-project \"$SSH_ORIGINAL_COMMAND\"" ssh-ed25519 …
# (sudo стирает SSH_ORIGINAL_COMMAND — команда приходит аргументом)
# sudoers: siteproj ALL=(root) NOPASSWD: /usr/local/sbin/pmk-site-project
# Удаления нет. Каждое действие — в /var/log/pmk-site-project.log.
set -euo pipefail
REPO=/opt/factory-platform/infra/site/projects
LOG=/var/log/pmk-site-project.log
C=site-web
MAX=$((150 * 1024 * 1024))
CMD="${SSH_ORIGINAL_COMMAND:-${*:-}}"
log() { echo "$(date '+%F %T') ${SUDO_USER:-root} $*" >> "$LOG"; }   # под sudo SSH_CLIENT не доходит
fail() { echo "{\"ok\":false,\"error\":\"$1\"}"; log "ОТКАЗ: $1 [$CMD]"; exit 1; }

# свежий код из репозитория в контейнер (скрипты маленькие)
sync_code() {
  docker exec "$C" mkdir -p /tmp/pmkproj
  tar -C "$REPO" -cf - _boot.php project.php | docker exec -i "$C" tar -xf - -C /tmp/pmkproj
}
after() {   # файловый кэш Bitrix — как при ручной правке (memory: CleanAll + rm cache)
  docker exec "$C" sh -c 'rm -rf /var/www/html/bitrix/cache/* /var/www/html/bitrix/managed_cache/* 2>/dev/null' || true
}

case "$CMD" in
  list)
    sync_code; docker exec "$C" php /tmp/pmkproj/project.php list ;;
  hide\ [0-9]*|show\ [0-9]*)
    set -- $CMD
    [[ "$2" =~ ^[0-9]{1,7}$ ]] || fail "плохой id"
    sync_code; log "$1 $2"
    docker exec "$C" php /tmp/pmkproj/project.php "$1" "$2" | tee -a "$LOG"; after ;;
  add)
    T=$(mktemp -d /tmp/pmkproj-in.XXXXXX); trap 'rm -rf "$T"' EXIT
    head -c $((MAX + 1)) > "$T/in.tgz"
    [ "$(stat -c %s "$T/in.tgz")" -le "$MAX" ] || fail "архив больше 150 МБ"
    # в архиве — только плоские имена файлов: никаких каталогов, ссылок, «..»
    tar -tvzf "$T/in.tgz" > "$T/list" 2>/dev/null || fail "не tar.gz"
    grep -qvE '^-' "$T/list" && grep -vE '^-' "$T/list" | grep -qvE ' \./?$' && fail "в архиве не только файлы"
    tar -tzf "$T/in.tgz" | sed 's#^\./##' | grep -v '^$' | grep -qvE '^[A-Za-z0-9._-]{1,100}$' && fail "плохие имена файлов"
    mkdir "$T/p" && tar -xzf "$T/in.tgz" -C "$T/p" --no-same-owner --no-same-permissions
    [ -f "$T/p/project.json" ] || fail "нет project.json"
    sync_code
    D=/tmp/pmkproj/in-$(basename "$T")
    docker cp "$T/p" "$C:$D" >/dev/null
    log "add: $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("name","?"))' "$T/p/project.json" 2>/dev/null)"
    set +e; docker exec "$C" php /tmp/pmkproj/project.php add "$D" | tee -a "$LOG"; rc=${PIPESTATUS[0]}; set -e
    docker exec "$C" rm -rf "$D"; after; exit "$rc" ;;
  *) fail "разрешено: list | hide <id> | show <id> | add" ;;
esac
