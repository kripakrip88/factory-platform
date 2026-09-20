#!/bin/sh
# Деплой стенда Odoo (:8084) из репозитория.
#
# Запускать на сервере:  sh /opt/factory-platform/experiments/odoo/deploy.sh
# Поставить новый модуль: INSTALL="pmk_mail_ui" sh .../deploy.sh
#
# Раньше этот скрипт лежал в /tmp на сервере и не был нигде записан: любая
# чистка /tmp — и деплой восстанавливай по памяти. Теперь он в репозитории.
set -e

REPO="${REPO:-/opt/factory-platform}"
STAND="${STAND:-/opt/experiments/odoo}"
DEST="$STAND/addons-extra"
BRANCH="${BRANCH:-feature/experiment-carbon}"

# Наши модули — обновляются через -u на каждом деплое.
OURS="pmk_calc pmk_theme pmk_pdf pmk_cut pmk_mail_ui"
# Вендорские — только раскладываются. -u им не нужен: мы правим в них код и
# переводы, а не данные, а лишнее обновление перезапускает их data-файлы.
VENDOR="mail_client"
# Модули, которые надо ПОСТАВИТЬ, а не обновить (через переменную окружения).
INSTALL="${INSTALL:-}"

echo "→ ветка $BRANCH"
cd "$REPO"
git fetch -q origin "$BRANCH"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
git archive "origin/$BRANCH" experiments/odoo/addons experiments/odoo/vendor \
  | tar -x -C "$WORK"

# Гасим до раскладки: подмена файлов под работающим Odoo даёт странные
# полусостояния, а ALTER TABLE при -u упирается в блокировку от открытой формы.
cd "$STAND"
docker compose stop odoo >/dev/null 2>&1 || true

for M in $OURS; do
  SRC="$WORK/experiments/odoo/addons/$M"
  [ -d "$SRC" ] || { echo "НЕТ МОДУЛЯ В РЕПО: addons/$M"; exit 1; }
  rm -rf "$DEST/$M" && cp -r "$SRC" "$DEST/" && chmod -R a+rX "$DEST/$M"
done

for M in $VENDOR; do
  SRC="$WORK/experiments/odoo/vendor/$M"
  [ -d "$SRC" ] || { echo "НЕТ МОДУЛЯ В РЕПО: vendor/$M"; exit 1; }
  rm -rf "$DEST/$M" && cp -r "$SRC" "$DEST/" && chmod -R a+rX "$DEST/$M"
done
echo "→ разложено: $OURS | вендор: $VENDOR"

UPD="$OURS"
# I18N=1 — дозалить переводы вендорских модулей в базу. Строки кода (.po)
# читаются из файла и обновления не требуют, а метки полей, значения списков,
# подсказки и заголовки форм лежат в jsonb-колонках и попадают туда только при
# -u. Без --i18n-overwrite Odoo лишь доливает недостающие и НЕ заменяет уже
# записанные — то есть исправление перевода без этого флага не доедет.
[ -n "$I18N" ] && UPD="$UPD $VENDOR"
ARGS="-u $(echo $UPD | tr ' ' ',')"
[ -n "$I18N" ] && ARGS="$ARGS --i18n-overwrite"
[ -n "$INSTALL" ] && ARGS="$ARGS -i $(echo $INSTALL | tr ' ' ',')"
echo "→ odoo $ARGS"
docker compose run --rm -T odoo odoo -d odoo $ARGS --stop-after-init 2>&1 \
  | grep -E "CRITICAL|ERROR|Failed to|Modules loaded" | tail -5

# Бандлы ассетов кэшируются в ir_attachment: без чистки сервер продолжит
# отдавать старый CSS/JS, сколько ни обновляй модули (CLAUDE.md, п. 8).
docker compose exec -T db psql -U odoo -d odoo -tAc \
  "DELETE FROM ir_attachment WHERE url LIKE '/web/assets/%';" >/dev/null

# Перезапуск, а не старт: кэш переводов кода живёт в памяти процесса и ничем
# не сбрасывается — без него правка .po в браузере не появится.
docker compose start odoo >/dev/null 2>&1
docker compose restart odoo >/dev/null 2>&1
echo "→ готово"
