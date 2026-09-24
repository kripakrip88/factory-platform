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
# pmk_bridge добавлен 23.09.2026. До этого он жил ТОЛЬКО в репозитории: на
# сервере файлов не было, в ir_module_module записи не было, а 790 служебных
# строк связи «справочник → карточка» в базе создали скрипты, запущенные
# руками. Связь держалась на данных модуля, которого Odoo не знает.
OURS="pmk_calc pmk_theme pmk_pdf pmk_cut pmk_mail_ui pmk_partner pmk_purchase pmk_dadata pmk_laser pmk_bridge pmk_deal"
# Вендорские — только раскладываются. -u им не нужен: мы правим в них код и
# переводы, а не данные, а лишнее обновление перезапускает их data-файлы.
#
# Тема, Team Inbox и tracking_manager добавлены 21.09.2026: до этого они жили
# ТОЛЬКО в addons-extra на сервере, вне git и вне этого списка. Одна неудачная
# команда — и тема, на которой стоит весь вид стенда, исчезла бы без следа.
# Теперь источник истины — репозиторий, как и у mail_client.
VENDOR="mail_client theme_liquid_glass northlight_teaminbox tracking_manager techy_backend_theme theme_nexus"
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
# WARNING показываем наравне с ошибками: именно предупреждением Odoo сообщает,
# что наследуемое представление не применилось и было ВЫКЛЮЧЕНО. Прежний фильтр
# ловил только CRITICAL/ERROR, поэтому такая потеря проходила молча — карточка
# контрагента так и стояла без секций, а деплой писал «готово» (прецедент
# 2026-09-20). Шум чужих модулей (нет license/author в манифесте, незнакомые
# ключи конфига) отсеиваем отдельной строкой, иначе важное утонет в нём.
docker compose run --rm -T odoo odoo -d odoo $ARGS --stop-after-init 2>&1 \
  | grep -E "CRITICAL|ERROR|WARNING|Failed to|Modules loaded" \
  | grep -vE "Missing \`(license|author)\` key|unknown option '|missing --http-interface" \
  | tail -20

# Бандлы ассетов кэшируются в ir_attachment: без чистки сервер продолжит
# отдавать старый CSS/JS, сколько ни обновляй модули (CLAUDE.md, п. 8).
docker compose exec -T db psql -U odoo -d odoo -tAc \
  "DELETE FROM ir_attachment WHERE url LIKE '/web/assets/%';" >/dev/null

# Только старт. Раньше здесь стоял ещё и restart сразу следом — «чтобы сбросить
# кэш переводов в памяти процесса». Он был лишним: процесс гасится в начале
# скрипта (строка 36), поэтому стартует заведомо новый и никакого старого кэша
# в нём нет. Лишний перезапуск заставлял Odoo грузить реестр четыре раза подряд
# вместо двух — около пяти секунд с каждого деплоя на пустом месте
# (замер 21.09.2026: 86 загрузок реестра в логе, по 2,15-2,82 с каждая).
docker compose start odoo >/dev/null 2>&1
echo "→ готово"
