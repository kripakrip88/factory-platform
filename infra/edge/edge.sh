#!/bin/sh
# Общий вход pmk-main (nginx 80/443). Рабочая папка /opt/edge — вне git-чекаута: включённые сайты
# — состояние сервера, а не репозитория.
#
#   sh edge.sh up                         — разложить конфиг из репо, поднять/перечитать nginx
#   sh edge.sh cert erppark.ru www.erppark.ru — выпустить сертификат (имя = первый домен) и
#                                            включить сайт sites-available/<первый домен>.conf
#   sh edge.sh renew                      — продлить сертификаты (крон, раз в сутки)
#   sh edge.sh status                     — включённые сайты, сроки сертификатов
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
RUN=/opt/edge
EMAIL="kripakrip88@gmail.com"
mkdir -p "$RUN/nginx/sites"

sync_conf() {
  cp "$HERE/docker-compose.yml" "$RUN/docker-compose.yml"
  cp "$HERE/nginx/nginx.conf" "$RUN/nginx/nginx.conf"
  # Включённые сайты обновить из репо (включены — те, что уже лежат в sites/).
  for f in "$RUN"/nginx/sites/*.conf; do
    [ -f "$f" ] || continue
    src="$HERE/nginx/sites-available/$(basename "$f")"
    [ -f "$src" ] && cp "$src" "$f"
  done
}

reload() {
  cd "$RUN"
  docker compose up -d >/dev/null
  docker compose exec -T nginx nginx -t && docker compose exec -T nginx nginx -s reload
}

case "$1" in
  up)
    sync_conf; reload; echo "→ вход поднят" ;;
  cert)
    shift; [ $# -ge 1 ] || { echo "укажи домены"; exit 1; }
    name="$1"; args=""
    for d in "$@"; do args="$args -d $d"; done
    sync_conf; reload
    cd "$RUN"
    # shellcheck disable=SC2086
    docker run --rm -v edge_certbot_conf:/etc/letsencrypt -v edge_certbot_www:/var/www/certbot \
      certbot/certbot:v4.1.1 certonly --webroot -w /var/www/certbot --cert-name "$name" $args \
      --email "$EMAIL" --agree-tos --no-eff-email --non-interactive --keep-until-expiring
    [ -f "$HERE/nginx/sites-available/$name.conf" ] && cp "$HERE/nginx/sites-available/$name.conf" "$RUN/nginx/sites/"
    reload; echo "→ $name: сертификат есть, сайт включён" ;;
  renew)
    docker run --rm -v edge_certbot_conf:/etc/letsencrypt -v edge_certbot_www:/var/www/certbot \
      certbot/certbot:v4.1.1 renew --quiet
    cd "$RUN" && docker compose exec -T nginx nginx -s reload ;;
  status)
    ls "$RUN/nginx/sites"
    docker run --rm -v edge_certbot_conf:/etc/letsencrypt certbot/certbot:v4.1.1 certificates 2>/dev/null \
      | grep -E "Certificate Name|Expiry" || true ;;
  *) sed -n 2,9p "$0"; exit 1 ;;
esac
