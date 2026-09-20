#!/bin/bash
# Бэкап стенда Odoo 19 Community (:8084): база + файловое хранилище.
#
# Стенд живёт отдельно от боевого ERPNext — свои контейнеры (odoo-app, odoo-db),
# свой том, свой каталог бэкапов. services/erp/scripts/backup.sh про стенд не
# знает и знать не должен, поэтому здесь отдельный скрипт, а не ещё одна ветка
# в боевом. До сегодняшнего дня бэкапа у стенда не было вовсе: единственная
# копия базы снималась руками перед рискованными операциями.
#
# ЧТО ПОКРЫВАЕТ:
#   1. База odoo в контейнере odoo-db — pg_dump -Fc, ежедневно (~9 МБ сжатого).
#      Формат custom, а не plain SQL: из него можно достать одну таблицу и он
#      уже сжат, gzip сверху не нужен.
#   2. Том odoo_odoo_data (/var/lib/odoo — filestore вложений + sessions) —
#      архив раз в неделю, по воскресеньям. 267 МБ сырых / ~57 МБ в архиве:
#      ежедневная копия на диске, занятом на 85%, добьёт его за месяц.
#      Разовый архив вне расписания: backup-stand.sh --with-files
#
# ЧЕГО НЕ ПОКРЫВАЕТ (сознательно):
#   - Код модулей — он в гите (experiments/odoo/addons), раскладывает deploy.sh.
#   - Сервер/тома целиком — это снимает Бегет раз в 2-4 дня в отдельный ДЦ
#     (docs/backup.md). Наши дампы нужны для другого: откатить базу стенда на
#     вчера, когда эксперимент с номенклатурой пошёл не туда.
#
# CRON — НЕ УСТАНОВЛЕН НАМЕРЕННО. Это постоянная запись в системе, ставит её
# владелец. Готовая строка (crontab -e от root):
#   40 3 * * * /opt/factory-platform/experiments/odoo/scripts/backup-stand.sh >> /var/log/odoo-backup.log 2>&1
# Именно 03:40, а не 03:00: в 03:00 уже идёт бэкап боевого ERPNext, складывать
# два дампа и tar в одну минуту на один диск незачем.
#
# ВОССТАНОВЛЕНИЕ (грабля: на ХОСТЕ нет клиента postgres, только внутри odoo-db):
#   docker cp /opt/backups/odoo/odoo_ГГГГММДД_ЧЧММСС.dump odoo-db:/tmp/r.dump
#   docker compose -f /opt/experiments/odoo/docker-compose.yml stop odoo
#   docker exec odoo-db sh -c 'dropdb -U "$POSTGRES_USER" odoo && createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" odoo'
#   docker exec odoo-db sh -c 'pg_restore -U "$POSTGRES_USER" -d odoo /tmp/r.dump'
#   Вложения: tar xzf filestore_*.tgz -C "$(docker volume inspect odoo_odoo_data --format '{{.Mountpoint}}')"
#   Базу и filestore восстанавливать ПАРОЙ: вложение — это строка в ir_attachment
#   плюс файл на диске, поодиночке получаются битые ссылки.

set -euo pipefail

BACKUP_DIR="/opt/backups/odoo"      # здесь уже лежит ручной бэкап от 20.09.2026
DB_CONTAINER="odoo-db"
DB_NAME="odoo"

# ТОЧНОЕ имя тома. Рядом в системе живут odoo_odoo-data (пустой остаток от
# первой сборки стенда) и odoo_odoo_db_data (это PGDATA постгреса, его бэкапит
# pg_dump, а не tar). Ошибка в одном символе = архив не того каталога, поэтому
# имя резолвим через docker volume inspect: на неверном имени он падает, и это
# ровно то поведение, которое здесь нужно.
FILESTORE_VOLUME="odoo_odoo_data"

KEEP_DB_DAYS=14                     # дампы базы мелкие — держим две недели
KEEP_FILES_DAYS=28                  # недельные архивы вложений — 4 недели (4 шт.)
MIN_FREE_GB=2                       # ниже этого не начинаем, см. предохранитель
MIN_TABLES=300                      # в живой базе 742 таблицы с данными

STAMP="$(date +%Y%m%d_%H%M%S)"
DB_OUT="$BACKUP_DIR/odoo_$STAMP.dump"          # имена как у ручного бэкапа —
FS_OUT="$BACKUP_DIR/filestore_$STAMP.tgz"      # чтобы ретеншен ловил и его тоже
DUMP_IN_CONTAINER="/tmp/backup-stand-$STAMP.dump"

# Любой обрыв должен быть громким: молчаливый недобэкап уже случался в боевом
# backup.sh, и «файл вроде есть» там оказался обрезанным.
die() { trap - ERR; echo "❌ $*"; exit 1; }
trap 'echo "❌ Бэкап стенда Odoo ОБОРВАН (строка $LINENO), причина выше"' ERR

# Недоделанные .part и временный дамп внутри контейнера не должны пережить
# запуск: .part легко спутать с готовым бэкапом, а дамп в /tmp контейнера
# занимает тот же диск, что и всё остальное.
cleanup() {
  docker exec "$DB_CONTAINER" rm -f "$DUMP_IN_CONTAINER" >/dev/null 2>&1 || true
  rm -f "$DB_OUT.part" "$FS_OUT.part" 2>/dev/null || true
}
trap cleanup EXIT

# Вложения — по воскресеньям (date +%u == 7) либо по явному флагу.
WITH_FILES=0
case "${1:-}" in
  --with-files) WITH_FILES=1 ;;
  "") if [ "$(date +%u)" = "7" ]; then WITH_FILES=1; fi ;;
  *) echo "Использование: $0 [--with-files]"; exit 2 ;;
esac

mkdir -p "$BACKUP_DIR"

# ─── Предохранитель: диск занят на 85%, дополнять его нечем ───────────────────
# Порог не про размер бэкапа (дамп 9 МБ + архив 60 МБ), а про состояние сервера:
# при свободе меньше 2 ГБ на 62-ГБ диске постгресу уже негде разложить WAL и
# временные файлы сортировки, и pg_dump большой таблицы уронит стенд целиком.
free_mb=$(df -BM --output=avail "$BACKUP_DIR" | tail -1 | tr -dc '0-9')
if [ "${free_mb:-0}" -lt "$((MIN_FREE_GB * 1024))" ]; then
  die "ОТМЕНА: на разделе $BACKUP_DIR свободно ${free_mb:-0} МБ (< ${MIN_FREE_GB} ГБ). Бэкап не начат."
fi

echo "═══ Бэкап стенда Odoo $(date '+%F %T') · свободно $((free_mb / 1024)) ГБ ═══"

# ─── 1. База ─────────────────────────────────────────────────────────────────
docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER" \
  || die "контейнер $DB_CONTAINER не запущен — бэкап базы невозможен"

echo "── База $DB_NAME (контейнер $DB_CONTAINER)"
# Пароль постгреса живёт в окружении контейнера. Команду выполняем ВНУТРИ него и
# подставляем аргументы через sh -c '...' _ arg1 arg2: $POSTGRES_USER
# раскрывается там, в скрипт и в ps на хосте секрет не попадает.
docker exec "$DB_CONTAINER" \
  sh -c 'pg_dump -U "$POSTGRES_USER" -Fc -d "$1" -f "$2"' _ "$DB_NAME" "$DUMP_IN_CONTAINER" \
  || die "pg_dump упал — дамп базы $DB_NAME не снят"

# Целостность проверяем ТОЖЕ внутри контейнера: на хосте pg_restore отсутствует
# (postgres стоит только в образах). pg_restore -l читает оглавление архива —
# обрезанный или недописанный дамп на этом месте разваливается.
if ! docker exec "$DB_CONTAINER" \
     sh -c 'pg_restore -l "$1" >/dev/null' _ "$DUMP_IN_CONTAINER"; then
  die "pg_restore -l не прочитал оглавление — дамп битый, на хост не берём"
fi
# Второй проход считает записи с данными. grep -c без совпадений возвращает 1,
# и внутри контейнера его гасим через || true: пустой дамп — это не сбой grep,
# а повод сработать проверке ниже с внятным числом.
tables=$(docker exec "$DB_CONTAINER" \
  sh -c 'pg_restore -l "$1" | grep -c "TABLE DATA" || true' _ "$DUMP_IN_CONTAINER")

if [ "$tables" -lt "$MIN_TABLES" ]; then
  die "в дампе всего $tables таблиц с данными (ожидалось ≥ $MIN_TABLES) — похоже на пустую или недокачанную базу"
fi

# Сначала .part, потом mv: прерванный docker cp не должен оставить в каталоге
# файл с правильным именем, который потом примут за рабочий бэкап.
docker cp "$DB_CONTAINER:$DUMP_IN_CONTAINER" "$DB_OUT.part" >/dev/null \
  || die "не удалось забрать дамп из контейнера на хост"
mv "$DB_OUT.part" "$DB_OUT"
docker exec "$DB_CONTAINER" rm -f "$DUMP_IN_CONTAINER" >/dev/null 2>&1 || true
echo "   $(basename "$DB_OUT") — $(du -h "$DB_OUT" | cut -f1), таблиц с данными: $tables"

# ─── 2. Вложения (filestore) ─────────────────────────────────────────────────
if [ "$WITH_FILES" = 1 ]; then
  echo "── Вложения, том $FILESTORE_VOLUME"
  mount_point=$(docker volume inspect "$FILESTORE_VOLUME" --format '{{.Mountpoint}}') \
    || die "тома $FILESTORE_VOLUME нет — проверь имя (рядом есть odoo_odoo-data и odoo_odoo_db_data)"

  # Odoo в этот момент работает, файлы под ним могут меняться. GNU tar на такое
  # отвечает кодом 1 («file changed as we read it») — это не поломка архива, а
  # предупреждение; фатальные ошибки у него от 2 и выше.
  rc=0
  tar czf "$FS_OUT.part" --warning=no-file-changed -C "$mount_point" . || rc=$?
  if [ "$rc" -ge 2 ]; then
    die "tar упал (код $rc) — архив вложений не снят"
  fi
  if [ "$rc" = 1 ]; then
    echo "   ⚠ файлы менялись во время архивации (стенд работает) — архив пригоден, но это не мгновенный снимок"
  fi

  # Проверка содержимого, а не только факта «файл создался»: пустой или
  # собранный не из того каталога архив бесполезен, узнать об этом при
  # восстановлении — худший вариант.
  files=$(tar tzf "$FS_OUT.part" | grep -c '^\./filestore/' || true)
  if [ "${files:-0}" -lt 1 ]; then
    die "в архиве нет ./filestore/ — заархивирован не тот каталог ($mount_point)"
  fi
  mv "$FS_OUT.part" "$FS_OUT"
  echo "   $(basename "$FS_OUT") — $(du -h "$FS_OUT" | cut -f1), объектов filestore: $files"
else
  echo "── Вложения пропущены (недельный архив снимается по воскресеньям; разово — --with-files)"
fi

# ─── 3. Ретеншен ─────────────────────────────────────────────────────────────
# Раздельный: дампы базы мелкие и нужны частыми, архивы вложений тяжёлые и
# редкие. Одна общая планка либо съела бы диск, либо оставила стенд без истории.
removed_db=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'odoo_*.dump' \
  -mtime "+$KEEP_DB_DAYS" -print -delete | wc -l)
removed_fs=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'filestore_*.tgz' \
  -mtime "+$KEEP_FILES_DAYS" -print -delete | wc -l)
# Осиротевшие .part от прерванных запусков: свежие мог оставить параллельный
# процесс, поэтому трогаем только вчерашние и старше.
find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.part' -mtime +1 -delete

echo "── Ретеншен: удалено дампов $removed_db (>$KEEP_DB_DAYS дн.), архивов вложений $removed_fs (>$KEEP_FILES_DAYS дн.)"

# ─── Итог ────────────────────────────────────────────────────────────────────
kept_db=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'odoo_*.dump' | wc -l)
kept_fs=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'filestore_*.tgz' | wc -l)
trap - ERR
echo "✅ Бэкап стенда Odoo завершён $(date '+%F %T') · в каталоге $kept_db дампов и $kept_fs архивов вложений · занято $(du -sh "$BACKUP_DIR" | cut -f1) · свободно $(df -h "$BACKUP_DIR" | awk 'NR==2{print $4}')"
