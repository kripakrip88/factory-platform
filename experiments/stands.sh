#!/bin/bash
# Управление оценочными стендами (Carbon, WebErpMesv2, Odoo).
#
# ЗАЧЕМ. Стенды нужны периодически — посмотреть, как у них сделана та или иная
# вещь. Держать их поднятыми постоянно незачем: Carbon один ест ~3 ГБ памяти.
# Скрипт прячет разницу между swarm (Carbon) и compose (остальные).
#
# ВАЖНО: «погасить» здесь НИКОГДА не значит «удалить». Базы, настройки и всё,
# что вы натыкали, остаётся в томах. Удаление данных — только руками, командой
# с флагом -v, и в этом скрипте её нет намеренно.
#
# Запуск на сервере:
#   bash /opt/experiments/stands.sh status
#   bash /opt/experiments/stands.sh stop  carbon|wem|odoo|all
#   bash /opt/experiments/stands.sh start carbon|wem|odoo

set -uo pipefail

CARBON_DIR="/opt/experiments/carbon"
WEM_DIR="/opt/experiments/weberpmes"
ODOO_DIR="/opt/experiments/odoo"

usage() {
  cat <<TXT
Стенды: carbon (:8083) · wem (:8082) · odoo (:8084)

  bash $0 status              что сейчас поднято, сколько ест
  bash $0 stop  <стенд|all>   погасить (данные сохраняются)
  bash $0 start <стенд>       поднять обратно

Данные НЕ удаляются ни при какой из этих команд.
TXT
}

# ─── Carbon живёт в swarm: масштабируем сервисы в 0 вместо удаления стека,
#     чтобы определение стека и секреты остались на месте.
carbon_scale() {
  local n="$1" svc
  docker stack services carbon --format '{{.Name}}' 2>/dev/null | while read -r svc; do
    docker service scale --detach "$svc=$n" >/dev/null 2>&1
  done
}

carbon_running() {
  docker stack services carbon --format '{{.Replicas}}' 2>/dev/null | grep -qv '^0/' && return 0 || return 1
}

status() {
  printf '\n%-10s %-8s %-10s %s\n' "СТЕНД" "ПОРТ" "СОСТОЯНИЕ" "ПАМЯТЬ"
  printf -- '─%.0s' {1..52}; echo

  local up
  up=$(docker stack services carbon --format '{{.Replicas}}' 2>/dev/null | grep -cv '^0/' || echo 0)
  if [ "${up:-0}" -gt 0 ]; then
    printf '%-10s %-8s %-10s %s МБ\n' "carbon" ":8083" "работает" \
      "$(docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' 2>/dev/null | awk '/^carbon/{split($2,a,"MiB"); s+=a[1]} END{printf "%d", s}')"
  else
    printf '%-10s %-8s %-10s %s\n' "carbon" ":8083" "погашен" "—"
  fi

  local d name port
  for pair in "wem:$WEM_DIR:8082" "odoo:$ODOO_DIR:8084"; do
    name="${pair%%:*}"; d=$(echo "$pair" | cut -d: -f2); port=$(echo "$pair" | cut -d: -f3)
    if [ -d "$d" ] && docker compose -f "$d/docker-compose.yml" ps --status running -q 2>/dev/null | grep -q .; then
      printf '%-10s :%-7s %-10s %s МБ\n' "$name" "$port" "работает" \
        "$(docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' 2>/dev/null | awk -v p="^${name/wem/wem-}" '$1 ~ p {split($2,a,"MiB"); s+=a[1]} END{printf "%d", s}')"
    else
      printf '%-10s :%-7s %-10s %s\n' "$name" "$port" "погашен" "—"
    fi
  done

  echo
  free -h | sed -n 2p | sed 's/^/  /'
  df -h / | tail -1 | sed 's/^/  /'
  echo
  echo "  Боевое (не трогаем): прод :8080, staging :8081"
}

do_stop() {
  case "$1" in
    carbon) echo "── гашу Carbon (14 сервисов swarm)"; carbon_scale 0; echo "   ✓ погашен, тома целы" ;;
    wem)    echo "── гашу WebErpMesv2"; (cd "$WEM_DIR" && docker compose stop >/dev/null 2>&1) && echo "   ✓ погашен, база цела" ;;
    odoo)   echo "── гашу Odoo"; (cd "$ODOO_DIR" && docker compose stop >/dev/null 2>&1) && echo "   ✓ погашен, база цела" ;;
    all)    do_stop carbon; do_stop wem; do_stop odoo ;;
    *) echo "неизвестный стенд: $1"; usage; exit 1 ;;
  esac
}

do_start() {
  case "$1" in
    carbon)
      echo "── поднимаю Carbon (сервисам нужно ~2-3 минуты)"
      carbon_scale 1
      echo "   вход: bash $CARBON_DIR/login-link.sh"
      ;;
    wem)  echo "── поднимаю WebErpMesv2"; (cd "$WEM_DIR" && docker compose start >/dev/null 2>&1) && echo "   ✓ http://155.212.143.179:8082" ;;
    odoo) echo "── поднимаю Odoo"; (cd "$ODOO_DIR" && docker compose start >/dev/null 2>&1) && echo "   ✓ http://155.212.143.179:8084" ;;
    *) echo "неизвестный стенд: $1"; usage; exit 1 ;;
  esac
}

case "${1:-status}" in
  status) status ;;
  stop)   [ $# -ge 2 ] || { usage; exit 1; }; do_stop "$2"; echo; status ;;
  start)  [ $# -ge 2 ] || { usage; exit 1; }; do_start "$2" ;;
  *)      usage; exit 1 ;;
esac
