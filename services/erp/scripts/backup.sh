#!/bin/bash
# Ежедневный бэкап платформы. Запускается по cron в 03:00 (install-cron.sh).
# Подробности и политика восстановления — docs/backup.md
#
# ЧТО ПОКРЫВАЕТ:
#   1. ERPNext PROD — дамп БД ежедневно; вложения (--with-files) раз в неделю (вс).
#      Вложения ~1.6 ГБ и почти не меняются: ежедневная копия давала +1.6 ГБ/сутки
#      и съела 13 ГБ диска (см. CHANGELOG v1.3.1).
#   2. infra-postgres — n8n (БЕЗ истории выполнений: она 533 МБ из 551 МБ и
#      расходная), factory, globals (роли).
#   3. brain-db — целиком, она мелкая.
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

ERP_CONTAINER="erp-backend-1"
ERP_SITE="erp.localhost"
ERP_IN_CONTAINER="/home/frappe/frappe-bench/sites/$ERP_SITE/private/backups"

PG_CONTAINER="infra-postgres-1"
BRAIN_PG_CONTAINER="brain-db"

KEEP_DB_DAYS=14         # дампы БД (мелкие) и конфиги
KEEP_FILES_DAYS=28      # недельные архивы вложений (тяжёлые)
MIN_FREE_GB=5           # ниже этого не начинаем — иначе добьём диск

STAMP="$(date +%Y%m%d_%H%M%S)"
failed=0
fail() { echo "❌ $*"; failed=1; }

mkdir -p "$BACKUP_DIR" "$PG_DIR"

# ─── Предохранитель: не начинать бэкап на переполненном диске ─────────────────
free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]; then
  echo "❌ ОТМЕНА: на / свободно ${free_gb} ГБ (< ${MIN_FREE_GB} ГБ). Бэкап не начат."
  exit 1
fi

echo "═══ Бэкап $(date '+%F %T') · свободно ${free_gb} ГБ ═══"

# ─── 1. ERPNext PROD ─────────────────────────────────────────────────────────
# Вложения — только по воскресеньям (date +%u == 7).
if [ "$(date +%u)" = "7" ]; then WITH_FILES="--with-files"; else WITH_FILES=""; fi

echo "── ERPNext $ERP_SITE${WITH_FILES:+ (+ вложения, недельный)}"
if ! docker ps --format '{{.Names}}' | grep -qx "$ERP_CONTAINER"; then
  fail "контейнер $ERP_CONTAINER не запущен — бэкап ERP пропущен"
elif docker exec "$ERP_CONTAINER" \
       bench --site "$ERP_SITE" backup $WITH_FILES; then
  # Забрать на хост И освободить том контейнера (иначе там навсегда висит 1.6 ГБ)
  if docker cp "$ERP_CONTAINER:$ERP_IN_CONTAINER/." "$BACKUP_DIR/"; then
    docker exec "$ERP_CONTAINER" sh -c "rm -f $ERP_IN_CONTAINER/*" \
      || fail "не удалось очистить $ERP_IN_CONTAINER в контейнере"
  else
    fail "не удалось скопировать бэкап ERP на хост (в контейнере НЕ чистим)"
  fi
else
  fail "bench backup упал"
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
# Тяжёлые архивы вложений держим 28 дней, всё остальное 14.
find "$BACKUP_DIR" -maxdepth 1 -type f -name '*private-files.tar' \
  -mtime "+$KEEP_FILES_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f ! -name '*private-files.tar' \
  -mtime "+$KEEP_DB_DAYS" -delete
find "$PG_DIR" -maxdepth 1 -type f -name '*.sql.gz' \
  -mtime "+$KEEP_DB_DAYS" -delete

# ─── Итог ────────────────────────────────────────────────────────────────────
occupied="$(du -sh "$BACKUP_DIR" | cut -f1)"
free_after="$(df -h / | awk 'NR==2{print $4}')"
if [ "$failed" = 0 ]; then
  echo "✅ Бэкап завершён $(date '+%F %T') · занято $occupied · свободно $free_after"
else
  echo "❌ Бэкап завершён С ОШИБКАМИ $(date '+%F %T') · занято $occupied · свободно $free_after"
  exit 1
fi
