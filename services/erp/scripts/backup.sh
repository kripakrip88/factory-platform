#!/bin/bash
# Ежедневный бэкап платформы. Запускается по cron в 03:00 (install-cron.sh).
# Подробности и политика восстановления — docs/backup.md
#
# ЧТО ПОКРЫВАЕТ:
#   1. Odoo (боевой с 21.09.2026) — дамп базы odoo ежедневно (pg_dump -Fc, ~23 МБ),
#      14 дней; вложения (filestore, ~0.9 ГБ) — ежедневный снимок «только новое»
#      (rsync --link-dest: неизменившиеся файлы — жёсткие ссылки на прошлый
#      снимок, места не занимают), 7 снимков. До 15.10.2026 Odoo этот скрипт НЕ
#      сохранял — только бэкапы перед выкладкой (/opt/backups/odoo) и снимки Бегета.
#   2. infra-postgres — n8n (БЕЗ истории выполнений: она 533 МБ из 551 МБ и
#      расходная), factory, globals (роли).
#   3. brain-db — целиком, она мелкая.
#
#   ERPNext убран 15.10.2026 (Антон: «к нему больше не вернёмся»): контейнеры
#   остановлены с 21.09, скрипт каждую ночь падал «С ОШИБКАМИ» на остановленном
#   контейнере. Последние дампы ERPNext — в $BACKUP_DIR (erp_localhost-*).
#
# ЧЕГО НЕ ПОКРЫВАЕТ (сознательно):
#   - STAGING — расходная среда, восстанавливается клоном с prod
#     (clone-prod-to-staging.sh).
#   - Сам сервер/ОС/тома — это снимает Бегет: автоматически раз в 2-4 дня,
#     до 10 копий, в отдельном дата-центре. Наши дампы нужны для другого —
#     откатить одну БД на вчера перед рискованным деплоем.

set -uo pipefail

BACKUP_DIR="/opt/factory-platform/backups/erp"
PG_DIR="$BACKUP_DIR/postgres"

ODOO_DIR="/opt/factory-platform/backups/odoo"
ODOO_DB_CONTAINER="odoo-db"
ODOO_DB="odoo"
ODOO_FILESTORE="/var/lib/docker/volumes/odoo_odoo_data/_data/filestore/$ODOO_DB"
KEEP_FILESTORE_SNAPSHOTS=7

PG_CONTAINER="infra-postgres-1"
BRAIN_PG_CONTAINER="brain-db"

KEEP_DB_DAYS=14         # дампы БД (мелкие) и конфиги
KEEP_FILES_DAYS=28      # недельные архивы вложений (тяжёлые)
MIN_FREE_GB=5           # ниже этого не начинаем — иначе добьём диск

STAMP="$(date +%Y%m%d_%H%M%S)"
failed=0
fail() { echo "❌ $*"; failed=1; }

mkdir -p "$BACKUP_DIR" "$PG_DIR" "$ODOO_DIR/db" "$ODOO_DIR/filestore"

# ─── Предохранитель: не начинать бэкап на переполненном диске ─────────────────
free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]; then
  echo "❌ ОТМЕНА: на / свободно ${free_gb} ГБ (< ${MIN_FREE_GB} ГБ). Бэкап не начат."
  exit 1
fi

echo "═══ Бэкап $(date '+%F %T') · свободно ${free_gb} ГБ ═══"

# ─── 1. Odoo ─────────────────────────────────────────────────────────────────
echo "── Odoo"
if ! docker ps --format '{{.Names}}' | grep -qx "$ODOO_DB_CONTAINER"; then
  fail "контейнер $ODOO_DB_CONTAINER не запущен — база Odoo НЕ сохранена"
else
  out="$ODOO_DIR/db/odoo-$STAMP.dump"
  # -Fc: сжатый формат pg_restore; пользователь — из окружения контейнера.
  if docker exec "$ODOO_DB_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -Fc '"$ODOO_DB" > "$out.part" \
     && [ -s "$out.part" ]; then
    mv "$out.part" "$out"
    echo "   база: $(basename "$out") — $(du -h "$out" | cut -f1)"
  else
    rm -f "$out.part"
    fail "дамп базы Odoo не снят"
  fi
fi

if [ -d "$ODOO_FILESTORE" ]; then
  snap="$ODOO_DIR/filestore/$STAMP"
  prev="$(ls -1d "$ODOO_DIR"/filestore/2* 2>/dev/null | tail -1)"
  if rsync -a --delete ${prev:+--link-dest="$prev"} "$ODOO_FILESTORE/" "$snap.part/"; then
    mv "$snap.part" "$snap"
    echo "   вложения: $(basename "$snap") — $(du -sh "$snap" | cut -f1) (новое за сутки — без повторов)"
  else
    rm -rf "$snap.part"
    fail "снимок вложений Odoo не снят"
  fi
else
  fail "нет папки вложений Odoo $ODOO_FILESTORE"
fi

# ─── 2/3. Postgres ───────────────────────────────────────────────────────────
# $1=контейнер $2=имя файла $3=команда (выполняется внутри контейнера, поэтому
# $POSTGRES_USER раскрывается ТАМ — пароли в скрипт не попадают).
pg_dump_to() {
  local container="$1" out="$2" cmd="$3"
  if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
    fail "контейнер $container не запущен — $out пропущен"
    return
  fi
  if docker exec "$container" sh -c "$cmd" 2>/dev/null | gzip > "$PG_DIR/$out.part"; then
    mv "$PG_DIR/$out.part" "$PG_DIR/$out"
    echo "   $out — $(du -h "$PG_DIR/$out" | cut -f1)"
  else
    rm -f "$PG_DIR/$out.part"       # битый/обрезанный дамп не оставляем
    fail "дамп $out не снят"
  fi
}

echo "── Postgres (infra)"
# История выполнений n8n исключена: 533 МБ из 551 МБ, расходная. Схема таблиц
# сохраняется — восстановление работает, просто без логов прогонов.
pg_dump_to "$PG_CONTAINER" "n8n-$STAMP.sql.gz" \
  'pg_dump -U "$POSTGRES_USER" -d n8n --exclude-table-data=execution_data --exclude-table-data=execution_entity'
pg_dump_to "$PG_CONTAINER" "factory-$STAMP.sql.gz" \
  'pg_dump -U "$POSTGRES_USER" -d factory'
pg_dump_to "$PG_CONTAINER" "globals-$STAMP.sql.gz" \
  'pg_dumpall -U "$POSTGRES_USER" --globals-only'

echo "── Postgres (brain)"
pg_dump_to "$BRAIN_PG_CONTAINER" "brain-$STAMP.sql.gz" \
  'pg_dumpall -U "$POSTGRES_USER"'

# ─── 4. Ретеншен ─────────────────────────────────────────────────────────────
# Odoo: дампы базы — 14 дней, снимки вложений — последние 7.
find "$ODOO_DIR/db" -maxdepth 1 -type f -name 'odoo-*.dump' -mtime "+$KEEP_DB_DAYS" -delete
ls -1d "$ODOO_DIR"/filestore/2* 2>/dev/null | head -n -"$KEEP_FILESTORE_SNAPSHOTS" | xargs -r rm -rf

# Тяжёлые архивы вложений держим 28 дней, всё остальное 14.
find "$BACKUP_DIR" -maxdepth 1 -type f -name '*private-files.tar' \
  -mtime "+$KEEP_FILES_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f ! -name '*private-files.tar' \
  -mtime "+$KEEP_DB_DAYS" -delete
find "$PG_DIR" -maxdepth 1 -type f -name '*.sql.gz' \
  -mtime "+$KEEP_DB_DAYS" -delete

# ─── Итог ────────────────────────────────────────────────────────────────────
occupied="$(du -sh "$BACKUP_DIR" "$ODOO_DIR" | awk '{print $1}' | paste -sd+ -)"
free_after="$(df -h / | awk 'NR==2{print $4}')"
if [ "$failed" = 0 ]; then
  echo "✅ Бэкап завершён $(date '+%F %T') · занято $occupied · свободно $free_after"
else
  echo "❌ Бэкап завершён С ОШИБКАМИ $(date '+%F %T') · занято $occupied · свободно $free_after"
  exit 1
fi
