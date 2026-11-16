#!/bin/bash
# Поднять базу сайта pmkpark.ru из дампа и запустить сайт (16.11.2026). Файлы сайта уже должны лежать в
# /opt/site/www. Логин/пароль/имя базы берутся из настроек Битрикса (bitrix/.settings.php) — как было.
#   bash site-restore.sh /opt/backups/site/site_ГГГГММДД_ЧЧММСС.sql.gz
# Повторный запуск безопасен: база пересоздаётся из дампа.
set -euo pipefail
DUMP="${1:?путь к дампу .sql.gz}"
SITE=/opt/site
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -s "$DUMP" ] || { echo "нет дампа $DUMP"; exit 1; }
[ -f $SITE/www/bitrix/.settings.php ] || { echo "нет файлов сайта в $SITE/www"; exit 1; }

mkdir -p $SITE
cp "$HERE/Dockerfile" "$HERE/docker-compose.yml" $SITE/ && cp -r "$HERE/conf" $SITE/
cd $SITE
[ -f .env ] || { umask 077; echo "MYSQL_ROOT_PASSWORD=$(openssl rand -hex 24)" > .env; }
# образ: готовый (из комплекта восстановления) или собрать
docker image inspect pmkpark-web:8.3.35 >/dev/null 2>&1 || docker compose build web
docker compose up -d --no-build db
for i in $(seq 1 60); do [ "$(docker inspect -f '{{.State.Health.Status}}' site-db)" = healthy ] && break; sleep 3; done
echo "база MySQL: $(docker inspect -f '{{.State.Health.Status}}' site-db)"

read -r DB_NAME DB_USER DB_PASS < <(docker run --rm -v $SITE/www:/w:ro pmkpark-web:8.3.35 php -r \
  '$s=include "/w/bitrix/.settings.php"; $c=$s["connections"]["value"]["default"]; echo $c["database"]," ",$c["login"]," ",$c["password"],PHP_EOL;')
echo "база: $DB_NAME, пользователь: $DB_USER"
docker exec -i site-db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' 2>/dev/null <<SQL
DROP DATABASE IF EXISTS \`$DB_NAME\`;
CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb3 COLLATE utf8mb3_unicode_ci;
CREATE USER IF NOT EXISTS "$DB_USER"@"localhost" IDENTIFIED BY "$DB_PASS";
ALTER USER "$DB_USER"@"localhost" IDENTIFIED BY "$DB_PASS";
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO "$DB_USER"@"localhost";
FLUSH PRIVILEGES;
SQL
gunzip -c "$DUMP" | docker exec -i site-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" $DB_NAME" 2>&1 | grep -v "Using a password" || true
n=$(docker exec site-db sh -c "mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" -N -e \"select count(*) from information_schema.tables where table_schema='$DB_NAME'\"" 2>/dev/null)
echo "таблиц: $n"
chown -R 33:33 $SITE/www
docker compose up -d --no-build web
sleep 3
curl -s -o /dev/null -w "сайт: %{http_code}\n" -H "Host: pmkpark.ru" -H "X-Forwarded-Proto: https" http://172.17.0.1:8090/
