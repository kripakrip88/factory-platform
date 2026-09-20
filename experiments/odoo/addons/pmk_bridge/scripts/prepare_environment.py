# -*- coding: utf-8 -*-
"""Подготовка среды под 752 карточки номенклатуры. ТОЛЬКО НА КОПИИ БАЗЫ.

Скрипт готовит то, во что лягут товары: коды ОКЕИ на единицах, дерево
категорий, две характеристики — и приводит четыре УЖЕ СУЩЕСТВУЮЩИХ товара
в тот вид, в котором к ним можно приписывать остальные 748.

Первым делом (шаг 0) он снимает прежние значения ЧУЖИХ записей — тех, что
мост не заводит, а переписывает. Без этого снимка откат заливки невозможен:
созданное он узнаёт по своим внешним идентификаторам, а переписанное чужое
опознать не по чему. Снимок читает scripts/rollback_load.py.

ПОЧЕМУ ТОЛЬКО НА КОПИИ. Шаг 5 меняет живые карточки, по которым уже прошли
приходы, списания в производство и резервы. Один неверный порядок действий
архивирует товар вместе с остатком (замер — ниже, в docstring шага 5).
Поэтому наверху стоит предохранитель по имени базы, и снять его нельзя,
не переписав файл.

КАК ЗАПУСКАТЬ

    # 1. копия живой базы (на ХОСТЕ pg_restore нет, работаем внутри db)
    docker exec odoo-db sh -c '
        psql -U odoo -d postgres -c "DROP DATABASE IF EXISTS odoo_probe" &&
        psql -U odoo -d postgres -c "CREATE DATABASE odoo_probe OWNER odoo" &&
        pg_dump -U odoo -d odoo -Fc -f /tmp/live.dump &&
        pg_restore -U odoo -d odoo_probe --no-owner --no-acl /tmp/live.dump'

    # 2. копия обезврежена: ни писем, ни крона, ни внешних вызовов
    docker exec odoo-db psql -U odoo -d odoo_probe -c "
        UPDATE ir_cron SET active=false;
        UPDATE ir_mail_server SET active=false;
        UPDATE fetchmail_server SET active=false;"

    # 3. данные и скрипт внутрь контейнера приложения
    docker compose cp addons/pmk_bridge/data odoo:/tmp/pmk_bridge_data
    docker compose cp addons/pmk_bridge/scripts/prepare_environment.py odoo:/tmp/prep.py

    # 4. прогон
    docker compose exec -T odoo sh -c 'cat /tmp/prep.py | odoo shell -d odoo_probe \\
        --no-http -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=$PASSWORD'

Скрипт идемпотентен: повторный прогон на той же копии ничего не ломает —
XML грузится в режиме update, категории и характеристики находятся по внешним
идентификаторам, а шаг 5 пропускает товары, у которых характеристика уже есть.
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

from odoo.tools.convert import convert_xml_import

# ─── ПРЕДОХРАНИТЕЛЬ ───────────────────────────────────────────────────────
# Живая база называется odoo, копии — odoo_probe (замеры) и odoo_rehearsal
# (репетиция заливки). Имя задаётся ключом -d; odoo.conf при этом упрямо
# держит db_name = odoo, так что ошибиться легко. Умереть надо ДО первой
# записи, а не после.
#
# Список, а не одно имя: копий стало несколько, и каждая заводится под свою
# задачу. Живой базы в списке нет и быть не должно — на неё этот скрипт
# пускают осознанной правкой файла, а не ключом запуска.
#   odoo_probe          — замеры поведения Odoo;
#   odoo_rehearsal      — репетиция заливки;
#   odoo_rollback       — проверка отката на копии ЖИВОЙ базы (0 товаров);
#   odoo_rollback_adopt — проверка отката на копии со старого дампа, где ещё
#                         живы четыре карточки с движениями и остатками.
PROBE_DBS = ("odoo_probe", "odoo_rehearsal", "odoo_rollback", "odoo_rollback_adopt")
_LIVE_OK = os.environ.get("PMK_LIVE") == "1"
if env.cr.dbname not in PROBE_DBS and not _LIVE_OK:  # noqa: F821 — PMK_LIVE=1 разрешает боевую базу
    sys.exit("ОТКАЗ: скрипт пишет в базу, а подключились к %r вместо одной из %s"
             % (env.cr.dbname, ", ".join(PROBE_DBS)))  # noqa: F821

DATA_DIR = os.environ.get("PMK_BRIDGE_DATA", "/tmp/pmk_bridge_data")
MODULE = "pmk_bridge"
SEP = "─" * 76

# ─── СНИМОК ЧУЖИХ ЗАПИСЕЙ ─────────────────────────────────────────────────
# Мост заводит своё (категории, характеристики, 752 карточки) — и попутно
# ПРАВИТ чужое: коды на стандартных единицах Odoo, точность «Stock Weight»,
# уже существующую категорию «Металлопрокат», уже существующие карточки.
# Созданное откат узнаёт по своим внешним идентификаторам и сносит. Правленое
# чужое по ним не узнать никак: запись принадлежит модулю uom или заведена
# руками, наших следов на ней нет — и «вернуть как было» можно только если
# «как было» кто-то записал ЗАРАНЕЕ. Этим и занят шаг 0.
#
# Почему снимок живёт в параметре базы, а не в файле рядом со скриптом:
# скрипты гоняются внутри контейнера, /tmp контейнера переживает не всё, а
# снимок обязан ехать вместе с той базой, которую он описывает. Параметр
# копируется вместе с базой при pg_dump — значит снимок и база не разойдутся.
# Файл пишется ВТОРЫМ экземпляром, на случай «базу уже откатили, а посмотреть
# надо» и как место стыковки с загрузчиком (см. ДОГОВОР ниже).
SNAPSHOT_PARAM = "pmk_bridge.rollback_snapshot"
# Имя файла НЕСЁТ ИМЯ БАЗЫ, и это не украшение. Копий на стенде несколько, а
# файл один на контейнер: с общим именем снимок odoo_rollback_adopt лёг поверх
# снимка odoo_rollback, и откат второй базы уткнулся в чужой снимок (поймано
# прогоном — откат отказался работать, потому что id в разных базах разные).
SNAPSHOT_FILE = (os.environ.get("PMK_BRIDGE_SNAPSHOT")
                 or "/tmp/pmk_bridge_snapshot_%s.json" % env.cr.dbname)  # noqa: F821
SNAPSHOT_VERSION = 1

# ДОГОВОР С ЗАГРУЗЧИКОМ (scripts/load_products.py — его правит другой агент).
# Здесь снимаются ВСЕ строки перечисленных ниже таблиц, а не только те четыре
# карточки, которые загрузчик усыновляет сегодня. Поэтому загрузчику ничего
# добавлять НЕ НАДО, пока он правит записи ЭТИХ таблиц: что бы он в них ни
# переписал, прежнее значение уже лежит в снимке — снимок берётся до первой
# записи, а подготовка среды всегда идёт перед заливкой.
# Договор нужен на один случай: загрузчик начнёт править чужую запись в
# таблице, которой в списке нет (например, прайс поставщика или партнёра).
# Тогда — НЕ трогая этот файл — дописать в JSON-файл SNAPSHOT_FILE ключ
# "дополнения_загрузчика" той же формы, что и разделы ниже:
#     {"<ключ>": {"таблица": "<имя>", "колонки": [...], "строки": [[...]]}}
# rollback_load.py подмешивает этот раздел к снимку из параметра. Если же
# чужая таблица окажется тронутой и не описанной нигде, откат обязан об этом
# кричать, а не молчать — за этим следит его проверка «неизвестные модели».
#
# Строка снимается ЦЕЛИКОМ, со всеми колонками. Первая версия снимала только
# те поля, которые загрузчик правил на тот день, — и устарела за час: агент,
# который ведёт load_products.py, добавил шаг «вес вариантов», и он пишет
# product_product.weight, колонку, которой в списке не было. Замер: у
# усыновлённой карточки LST-GL-4 вес варианта уходит с 31,40000 на 282,60000
# (масса м² -> масса листа 1500x6000), и откат по списку полей вернул бы всё,
# кроме веса, — молча.
#
# Отсюда правило: перечислять поля нельзя, их перечисляет тот, кто их портит.
# Снимаем всю строку, список колонок берём из information_schema в момент
# снятия. Тогда любая новая правка загрузчика — в любой колонке этих таблиц —
# откатывается без единой строчки согласования.
#
# Цена решения — размер. Здесь таблицы маленькие (5 карточек, 5 вариантов,
# 30 единиц, 4 категории, 57 строк листа), снимок весит килобайты, и его
# длина печатается ниже, чтобы это было видно, а не предполагалось.
SNAPSHOT_TABLES = (
    # ключ,                    таблица
    ("единицы", "uom_uom"),
    ("точность", "decimal_precision"),
    ("категории", "product_category"),
    ("товары", "product_template"),
    ("варианты", "product_product"),
    ("характеристики", "product_attribute"),
    ("значения_характеристик", "product_attribute_value"),
    ("строки_характеристик", "product_template_attribute_line"),
    # Из этой таблицы шаг 2 УДАЛЯЕТ строку-дубль. Переписанное поле можно
    # вернуть, зная одно поле; удалённую строку — только зная её целиком,
    # вместе с id, иначе ссылки на неё не сойдутся.
    ("лист_справочника", "pmk_metal_sheet"),
)

# Типы, которые снимаются текстом. jsonb — чтобы не потерять ни одного ключа
# перевода; numeric — чтобы не потерять знаки после запятой на пути через
# float; timestamp — чтобы не зависеть от часового пояса сессии. Тот же
# список продублирован в rollback_load.py, и совпадать они обязаны: по нему
# строится и выражение чтения, и приведение при записи.
TEXTUAL_TYPES = ("jsonb", "numeric", "timestamp")


def table_columns(table):
    """Колонки таблицы с их типами — из базы, а не из памяти."""
    env.cr.execute(  # noqa: F821
        "SELECT column_name, udt_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,))
    return env.cr.fetchall()  # noqa: F821


def read_expr(col, udt):
    """Выражение чтения колонки: текстовые типы — через ::text (см. выше)."""
    return "%s::text" % col if udt in TEXTUAL_TYPES else col

# Марка, которой помечаем остатки существующих товаров. Ст3сп стоит
# is_default=1 в pmk.metal.grade — это то, что завод возит по умолчанию.
# Метка приклеивается к варианту вместе с его остатком, переклеить её потом
# нельзя, поэтому значение печатается крупно: технолог должен подтвердить.
DEFAULT_GRADE = "pmk_bridge.attr_grade_st3sp"

# Габарит для листа 4 мм. Не догадка: единственный приход по этой карточке —
# 9,000 м² (движение 21), а 1500x6000 — это ровно 1,5 x 6 = 9 м². То есть
# пришёл один лист 1500x6000, и это подтверждается цифрой прихода.
SHEET_4MM_SIZE = "pmk_bridge.attr_sheet_size_1500x6000"

# Куда переезжают четыре существующих товара. Ключ — английское название
# шаблона на стенде: русских имён у них нет, поле name->>'ru_RU' пустое.
EXISTING_PRODUCTS = {
    "Труба профильная 100x100x3 ГОСТ 8639-82": "pmk_bridge.categ_rolled_tpk",
    "Уголок равнополочный 63x63x5 ГОСТ 8509-93": "pmk_bridge.categ_rolled_ugr",
    "Лист горячекатаный 4 мм ГОСТ 19903-2015": "pmk_bridge.categ_sheet_gl",
    "Лист горячекатаный 8 мм ГОСТ 19903-2015": "pmk_bridge.categ_sheet_gl",
}


def head(n, title):
    print("\n" + SEP)
    print("ШАГ %s. %s" % (n, title))
    print(SEP)


# ═══ ШАГ 0 ════════════════════════════════════════════════════════════════
def snapshot_foreign_records():
    """Записать прежние значения чужих записей ДО первой правки.

    Шаг стоит первым и обязан стоять первым. Всё, что идёт ниже, уже меняет
    чужое: шаг 1 выдаёт внешний идентификатор существующей категории (после
    чего product_category.xml перепишет ей removal_strategy_id), шаг 2 УДАЛЯЕТ
    строку из справочника листа, шаг 3 проставляет коды семнадцати
    стандартным единицам Odoo, шаг 5 меняет категорию четырём живым
    карточкам, шаг 6 — единицу одной из них. Замер на копии старого дампа
    (57 строк листа, 5 карточек):

        единиц с кодами        было 0   -> стало 17
        точность Stock Weight  было 2   -> стало 5      (её поднимает загрузчик)
        категория id 6         removal  было NULL -> 1
        строк pmk_metal_sheet  было 57  -> стало 56
        карточка 9   имя «Труба профильная 100x100x3»  -> «...квадратная...»,
                     категория 6 -> 16
        карточка 12  единица 11 (м²) -> 1 (шт)
        варианты 9-12 артикул NULL -> TPK-100x100x3 и т.д.

    Ни одно из этих значений не восстановить по внешним идентификаторам
    моста: своих следов на чужой записи мост не оставляет, он её просто
    переписывает. Отсюда снимок.

    ПОВТОРНЫЙ ПРОГОН СНИМОК НЕ ПЕРЕЗАПИСЫВАЕТ. Это не мелочь: второй прогон
    идёт уже по изменённой базе, и «обновить снимок» означало бы записать в
    него результат заливки как исходное состояние — то есть сделать откат
    бессмысленным, оставив его при этом на вид рабочим.
    """
    head(0, "Снимок чужих записей (то, что мост правит, а не заводит)")
    Param = env["ir.config_parameter"].sudo()  # noqa: F821
    if Param.get_param(SNAPSHOT_PARAM):
        data = json.loads(Param.get_param(SNAPSHOT_PARAM))
        print("  снимок уже есть, снят %s — НЕ перезаписываю." % data.get("снят"))
        print("  Второй прогон видит уже изменённую базу: перезапись превратила бы")
        print("  результат заливки в «исходное состояние», и откат вернул бы не то.")
        return

    # Снимок имеет смысл только пока база чистая. Если мост уже наследил, а
    # снимка нет — значит его не взяли вовремя, и восстанавливать не по чему.
    env.cr.execute("SELECT count(*) FROM ir_model_data WHERE module=%s", (MODULE,))  # noqa: F821
    already = env.cr.fetchone()[0]  # noqa: F821
    if already:
        sys.exit(
            "ОТКАЗ: снимка нет, а записей моста в базе уже %d. Снимок, взятый\n"
            "сейчас, запишет результат заливки как исходное состояние, и откат\n"
            "вернёт базу не туда. Путь один: поднять копию заново из дампа и\n"
            "начать с этого шага." % already)

    snap = {
        "версия": SNAPSHOT_VERSION,
        "база": env.cr.dbname,  # noqa: F821
        # utcnow() в Python 3.12 объявлен устаревшим и шумит предупреждением
        # в лог прогона — берём время с явной зоной.
        "снят": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "разделы": {},
    }
    for key, table in SNAPSHOT_TABLES:
        cols = table_columns(table)
        if not cols:
            sys.exit("ОТКАЗ: таблицы %s нет в базе. Снимок без неё неполон, а "
                     "неполный снимок хуже отсутствующего: он выглядит рабочим."
                     % table)
        names = [c for c, _ in cols]
        select = ", ".join(read_expr(c, udt) for c, udt in cols)
        env.cr.execute("SELECT %s FROM %s ORDER BY id" % (select, table))  # noqa: F821,S608
        rows = env.cr.fetchall()  # noqa: F821
        snap["разделы"][key] = {
            "таблица": table,
            "колонки": names,
            "строка_целиком": True,
            "строки": [list(r) for r in rows],
        }
        print("  %-24s %-34s строк %-5d колонок %d" % (key, table, len(rows), len(names)))

    # Отдельной строкой — то, что откат обязан вернуть к нулю, а не «к тому,
    # что найдёт»: записей моста до заливки нет ни одной.
    snap["было_записей_моста"] = 0

    payload = json.dumps(snap, ensure_ascii=False)
    print("  снимок целиком: %d символов, %d разделов"
          % (len(payload), len(snap["разделы"])))
    Param.set_param(SNAPSHOT_PARAM, payload)
    try:
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as fp:
            fp.write(payload)
        print("  второй экземпляр снимка: %s" % SNAPSHOT_FILE)
    except OSError as exc:
        # Файл — подстраховка, а не источник правды: параметр уже записан.
        print("  файл снимка не записан (%s) — это не отказ, снимок лежит в "
              "параметре %s" % (exc, SNAPSHOT_PARAM))
    print("  снимок записан в параметр %s" % SNAPSHOT_PARAM)


# ═══ ШАГ 1 ════════════════════════════════════════════════════════════════
def adopt_existing_category():
    """Выдать существующей категории «Металлопрокат» внешний идентификатор.

    Категория id 6 заведена руками через интерфейс, внешнего идентификатора
    у неё нет, и в ней лежат все четыре товара. Если просто загрузить
    product_category.xml, Odoo заведёт ВТОРУЮ категорию с тем же названием,
    а товары останутся в первой — и дерево разъедется молча.

    Поэтому сначала привязываем ir.model.data к существующей записи: тогда
    запись pmk_bridge.categ_rolled из XML обновит её, а не создаст дубль.
    """
    head(1, "Усыновление существующей категории «Металлопрокат»")
    imd = env["ir.model.data"]  # noqa: F821
    existing = imd.search([("module", "=", MODULE), ("name", "=", "categ_rolled")])
    if existing:
        print("  уже усыновлена: categ_rolled -> id %s" % existing.res_id)
        return

    categ = env["product.category"].search(  # noqa: F821
        [("name", "=", "Металлопрокат"), ("parent_id", "=", False)])
    if len(categ) != 1:
        sys.exit("ОТКАЗ: ожидалась одна корневая категория «Металлопрокат», "
                 "найдено %d. Разберитесь руками, автоматика тут навредит." % len(categ))

    imd.create({"module": MODULE, "name": "categ_rolled",
                "model": "product.category", "res_id": categ.id, "noupdate": False})
    print("  categ_rolled -> id %s (товаров внутри: %d)" % (categ.id, categ.product_count))


# ═══ ШАГ 2 ════════════════════════════════════════════════════════════════
def drop_duplicate_sheet():
    """Убрать дубль листа из справочника до того, как по нему заведут карточку.

    pmk.metal.sheet id 57 — оцинкованный 0,6 мм, ГОСТ 14918-2020, 4,71 кг/м²,
    без внешнего идентификатора: заведён руками и полностью повторяет строку
    CSV sheet_оцинк_0_6 (id 58). Если оставить, на один физический лист
    заведутся две карточки с разными артикулами, и цена поставщика ляжет на
    ту, которую не спросят.
    """
    head(2, "Дубль листа в справочнике")
    sheets = env["pmk.metal.sheet"].search([])  # noqa: F821
    imd = env["ir.model.data"]  # noqa: F821
    orphans = sheets.filtered(
        lambda s: not imd.search_count(
            [("model", "=", "pmk.metal.sheet"), ("res_id", "=", s.id)]))
    if not orphans:
        print("  строк без внешнего идентификатора нет — дубль уже убран")
        return

    for s in orphans:
        twin = sheets.filtered(
            lambda t, s=s: t.id != s.id and t.sheet_type == s.sheet_type
            and t.thickness_mm == s.thickness_mm and t.gost == s.gost)
        print("  id %s: %s %s мм, %s, %s кг/м² — близнецов: %s"
              % (s.id, s.sheet_type, s.thickness_mm, s.gost, s.mass_per_sqm,
                 ", ".join(str(t.id) for t in twin) or "нет"))
        if twin:
            s.unlink()
            print("      удалён (у близнеца id %s внешний идентификатор есть)" % twin[0].id)
        else:
            print("      НЕ удалён: близнеца нет, это может быть нужная строка")

    print("  осталось строк листа: %d" % env["pmk.metal.sheet"].search_count([]))  # noqa: F821


# ═══ ШАГ 3 ════════════════════════════════════════════════════════════════
def load_data_files():
    """Загрузить справочные XML напрямую, не устанавливая модуль.

    Загрузчик Odoo вызывается тем же кодом, что и при установке модуля
    (convert_xml_import), поэтому поведение здесь и при будущей установке
    pmk_bridge совпадает — а разбираться с манифестом на этапе репетиции
    не нужно.

    ГРАБЛЯ, найденная первым прогоном: в режиме 'update' коды ОКЕИ НЕ
    записались — файл загрузился без единой ошибки, а okei и kod остались
    пустыми у всех тридцати единиц. Причина в orm/models.py::_load_records:

        if not (update and d_noupdate): to_update.append(data)

    где d_noupdate — флаг noupdate в ir_model_data ЦЕЛЕВОЙ записи. У всех
    uom.uom он стоит в true (модуль uom грузит свои единицы с noupdate="1"),
    поэтому чужой модуль их в режиме обновления не перепишет. Атрибут
    noupdate в НАШЕМ файле на это не влияет — проверка смотрит на строку
    в базе, а не на файл.

    Отсюда режимы: единицы грузим в 'init' (update=False, проверка снимается),
    свои категории и характеристики — в 'update', чтобы повторный прогон их
    обновлял, а не плодил.

    То же правило действует и после установки модуля: при первой установке
    Odoo грузит данные в 'init' и коды лягут, а вот `-u pmk_bridge` их уже
    не перепишет. Если коды когда-нибудь поменяются — прогонять этот шаг,
    а не обновление модуля.
    """
    head(3, "Загрузка справочных данных")
    for fname, mode in (("uom_okei.xml", "init"),
                        ("product_category.xml", "update"),
                        ("product_attribute.xml", "update")):
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            sys.exit("ОТКАЗ: нет файла %s. Скопируйте каталог data в контейнер "
                     "или задайте PMK_BRIDGE_DATA." % path)
        with open(path, "rb") as fp:
            convert_xml_import(env, MODULE, fp, {}, mode, False)  # noqa: F821
        print("  загружен %s (режим %s)" % (fname, mode))
    env.flush_all()  # noqa: F821


# ═══ ШАГ 4 ════════════════════════════════════════════════════════════════
def check_uom_codes():
    """Сверить загруженные коды ОКЕИ с таблицей категорий и показать пробелы.

    Проверка УПД (l10n_ru_upd_xml) смотрит на единицу КАЖДОЙ строки документа,
    поэтому пустой okei у любой включённой единицы блокирует выгрузку целиком.
    """
    head(4, "Коды ОКЕИ на единицах измерения")
    uoms = env["uom.uom"].with_context(active_test=False).search([])  # noqa: F821
    filled = uoms.filtered(lambda u: u.okei and u.kod)
    mismatch = uoms.filtered(lambda u: u.okei and u.kod and u.okei != u.kod)
    empty_active = uoms.filtered(lambda u: u.active and not u.okei)

    print("  единиц всего: %d, из них активных: %d"
          % (len(uoms), len(uoms.filtered("active"))))
    print("  заполнено okei и kod: %d" % len(filled))
    for u in uoms.filtered(lambda u: u.active).sorted("id"):
        print("      %-14s okei=%-6s kod=%-6s %s"
              % (u.name, u.okei or "ПУСТО", u.kod or "ПУСТО",
                 "активна" if u.active else ""))
    if mismatch:
        print("  РАСХОЖДЕНИЕ okei != kod у: %s" % ", ".join(mismatch.mapped("name")))
    if empty_active:
        print("  ОСТАЛИСЬ ПУСТЫМИ (заблокируют УПД): %s"
              % ", ".join(empty_active.mapped("name")))
    else:
        print("  пустых активных единиц нет — УПД по ним не встанет")


# ═══ ШАГ 5 ════════════════════════════════════════════════════════════════
def attach_attributes():
    """Повесить характеристики на четыре живых товара, не потеряв остатки.

    ЗАМЕР НА КОПИИ, товар «Труба профильная 100x100x3», 3621,790 м, 15 движений.

    Если повесить характеристику сразу со всеми восемью значениями:
        до:    вариант 9, active=True,  метки нет, склад 3621,790
        после: вариант 9, active=False, метки нет, склад 3621,790
    Остаток цел, но товар в архиве — то есть из отчётов и из подбора он исчез.
    Причина в product_template.py::_create_variant_ids: у старого варианта
    набор значений пуст, _filter_combinations_impossible_by_config сравнивает
    длины (0 против 1) и не пропускает пустую комбинацию, вариант уходит в
    variants_to_unlink, а удалиться не может из-за движений — и молча
    архивируется через _unlink_or_archive.

    Если сначала ОДНО значение, потом остальные (ветка single_value_lines):
        до:               вариант 9, active=True, метки нет,   3621,790
        после 1 значения: вариант 9, active=True, метки Ст3сп, 3621,790
        после всех 8:     вариант 9, active=True, метки Ст3сп, 3621,790

    Для листа характеристик две — правило работает и там: обе строки заводятся
    с одним значением, вариант впитывает обе метки и остаётся живым.
    """
    head(5, "Характеристики на существующие товары (правило одного значения)")
    grade_attr = env.ref("pmk_bridge.attr_grade")  # noqa: F821
    size_attr = env.ref("pmk_bridge.attr_sheet_size")  # noqa: F821
    grade_one = env.ref(DEFAULT_GRADE)  # noqa: F821
    size_one = env.ref(SHEET_4MM_SIZE)  # noqa: F821

    print("  метка марки для всех остатков: %s" % grade_one.name)
    print("  метка габарита для листа:      %s" % size_one.name)
    print("  ПОДТВЕРДИТЬ У ТЕХНОЛОГА: метка приклеивается к варианту вместе с")
    print("  остатком, переклеить её на том же варианте потом нельзя.\n")

    Tmpl = env["product.template"]  # noqa: F821
    handled = 0
    for name_en, categ_xmlid in EXISTING_PRODUCTS.items():
        tmpl = Tmpl.search([("name", "=", name_en)])
        if len(tmpl) != 1:
            print("  ПРОПУСК %r: найдено шаблонов %d" % (name_en, len(tmpl)))
            continue
        handled += 1

        categ = env.ref(categ_xmlid)  # noqa: F821
        # Сравниваем способ учёта затрат ДО переезда: если он совпадает,
        # stock_account не станет переоценивать склад (product.py::write
        # зовёт _update_standard_price только при расхождении).
        old_method, new_method = tmpl.categ_id.property_cost_method, categ.property_cost_method
        tmpl.categ_id = categ.id
        print("  %s" % name_en)
        print("      категория -> %s (учёт затрат %s -> %s%s)"
              % (categ.complete_name, old_method, new_method,
                 "" if old_method == new_method else ", БУДЕТ ПЕРЕОЦЕНКА"))

        wanted = [(grade_attr, grade_one)]
        if categ_xmlid.startswith("pmk_bridge.categ_sheet"):
            wanted.append((size_attr, size_one))

        for attr, one in wanted:
            if attr in tmpl.attribute_line_ids.attribute_id:
                print("      характеристика «%s» уже есть — не трогаем" % attr.name)
                continue
            # Шаг А: строка с ОДНИМ значением — существующий вариант впитает метку.
            tmpl.write({"attribute_line_ids": [
                (0, 0, {"attribute_id": attr.id, "value_ids": [(6, 0, one.ids)]})]})
            # Шаг Б: расширяем до полного набора; вариант уже помечен и уцелеет.
            line = tmpl.attribute_line_ids.filtered(lambda l, a=attr: l.attribute_id == a)
            line.write({"value_ids": [(6, 0, attr.value_ids.ids)]})
            print("      «%s»: 1 значение -> %d значений"
                  % (attr.name, len(attr.value_ids)))

        env.invalidate_all()  # noqa: F821
        for v in tmpl.with_context(active_test=False).product_variant_ids:
            env.cr.execute(  # noqa: F821
                "SELECT COALESCE(SUM(quantity),0) FROM stock_quant WHERE product_id=%s "
                "AND location_id IN (SELECT id FROM stock_location WHERE usage='internal')",
                (v.id,))
            on_hand = env.cr.fetchone()[0]  # noqa: F821
            print("      вариант %s active=%s метки=[%s] на складе=%.3f %s"
                  % (v.id, v.active,
                     ", ".join(v.product_template_attribute_value_ids.mapped("name")) or "нет",
                     on_hand, tmpl.uom_id.name))
            if not v.active:
                sys.exit("ОТКАЗ: вариант %s ушёл в архив — правило одного значения "
                         "не сработало, дальше идти нельзя" % v.id)

    total = env["product.template"].search_count([])  # noqa: F821
    if not handled:
        print("  обработано 0 товаров: в базе сейчас %d карточек. Это не ошибка —"
              % total)
        print("  на пустой базе правило одного значения не нужно, архивировать нечего.")
        print("  Оно понадобится в тот день, когда характеристику будут вешать на")
        print("  карточку, по которой уже прошли движения; замер в docstring этого шага.")
    else:
        print("  обработано товаров: %d из %d в базе" % (handled, total))


# ═══ ШАГ 6 ════════════════════════════════════════════════════════════════
def sheet_uom_report():
    """Лист лежит в м², а по решению владельца считаем штуками. Что с этим делать.

    ЗАМЕР НА КОПИИ. Odoo 19 смену единицы РАЗРЕШАЕТ (stock/models/product.py::
    _update_uom отказывает только если в истории встречалась единица, отличная
    от текущей единицы карточки) — и пересчёта НЕ делает. Её собственное
    предупреждение говорит прямо: «1 старая = 1 новая». Проверено на листе 4 мм:

        до:    движение 21, кол-во 9,000, ед m²
        после: движение 21, кол-во 9,000, ед Units

    То есть один лист 1500x6000 (9 м²) превратится в девять листов. Ошибка
    ровно в площадь габарита — для 1500x6000 это 9 раз.

    Поэтому: карточку БЕЗ движений переводим сразу, карточку С движениями —
    не трогаем, а печатаем цифры для решения. Механический пересчёт здесь не
    поможет и по второй причине: остатки 5,400 / 3,150 / 0,450 м² — это не
    доли листа, а обрезки, а обрезок по решению владельца идёт отдельной
    партией со своими размерами, и на приход его предлагает технолог.
    """
    head(6, "Лист: единица м² -> шт")
    unit = env.ref("uom.product_uom_unit")  # noqa: F821
    sqm = env.ref("uom.product_uom_square_meter")  # noqa: F821
    sheets = env["product.template"].search(  # noqa: F821
        [("categ_id", "child_of", env.ref("pmk_bridge.categ_sheet").id)])  # noqa: F821
    if not sheets:
        print("  карточек листа в базе нет — переводить нечего.")
        print("  Новые заводим сразу в штуках (uom_by_category.csv, строки categ_sheet*):")
        print("  это решение владельца, и на пустой карточке оно ничего не стоит.")
        print("  Разбор ниже нужен, если лист заведут в м² и по нему пройдёт приход.")
        return

    for tmpl in sheets:
        moves = env["stock.move"].search_count(  # noqa: F821
            [("product_id", "in", tmpl.product_variant_ids.ids)])
        print("  %s: единица %s, движений %d" % (tmpl.name, tmpl.uom_id.name, moves))
        if tmpl.uom_id == unit:
            print("      уже в штуках")
            continue
        if tmpl.uom_id != sqm:
            print("      единица не м² — случай не наш, разбирать руками")
            continue
        if moves == 0:
            tmpl.write({"uom_id": unit.id})
            print("      переведён в штуки: движений нет, терять нечего")
            continue

        # Есть история — считаем, во что превратится каждая строка, и молчим.
        env.cr.execute(  # noqa: F821
            "SELECT q.id, l.complete_name, q.quantity, q.reserved_quantity "
            "FROM stock_quant q JOIN stock_location l ON l.id=q.location_id "
            "WHERE q.product_id = ANY(%s) ORDER BY q.id",
            (tmpl.product_variant_ids.ids,))
        quants = env.cr.fetchall()  # noqa: F821
        area = 1.5 * 6.0  # площадь листа 1500x6000, м² — габарит подтверждён приходом 9,000 м²
        print("      НЕ ПЕРЕВЕДЁН. Смена единицы не пересчитает числа, она их "
              "переименует: 1 м² станет 1 шт.")
        print("      что лежит сейчас и сколько это листов 1500x6000 (%.1f м²):" % area)
        for qid, loc, qty, res in quants:
            qty, res = float(qty or 0), float(res or 0)
            print("        квант %-4s %-24s %8.3f м² = %6.3f листа (резерв %.3f м²)"
                  % (qid, loc, qty, qty / area, res))
        print("      доли листа — это обрезки. По решению владельца обрезок идёт")
        print("      отдельной партией со своими размерами, и предлагает его на")
        print("      приход технолог, а не система. Значит путь такой:")
        print("        1) технолог называет, сколько целых листов и какие обрезки лежат;")
        print("        2) эту карточку архивируем (по ней уже есть проведённые документы);")
        print("        3) заводим карточку в штуках с характеристикой «Габарит листа»;")
        print("        4) целые листы ставим приходом, обрезки — отдельными партиями.")


# ═══ ШАГ 7 ════════════════════════════════════════════════════════════════
def final_check():
    """Итог: то, во что лягут товары, посчитано по факту, а не по намерению."""
    head(7, "Проверка готовности")
    ref = lambda x: env.ref(x)  # noqa: E731, F821

    rolled = ref("pmk_bridge.categ_rolled")
    sheet = ref("pmk_bridge.categ_sheet")
    hw = ref("pmk_bridge.categ_hw")
    paint = ref("pmk_bridge.categ_paint")
    Categ = env["product.category"]  # noqa: F821

    print("  дерево категорий:")
    for root in (rolled, sheet, hw, paint):
        kids = Categ.search([("parent_id", "=", root.id)])
        print("      %-28s подкатегорий %-3d учёт=%-9s оценка=%s"
              % (root.name, len(kids), root.property_cost_method, root.property_valuation))
        blank = kids.filtered(lambda c: not c.property_cost_method or not c.property_valuation)
        if blank:
            print("          БЕЗ УЧЁТА ЗАТРАТ ИЛИ ОЦЕНКИ (провалятся к настройке "
                  "компании, а не к родителю): %s" % ", ".join(blank.mapped("name")))
    print("      категорий всего заведено: %d"
          % Categ.search_count([("id", "child_of", [rolled.id, sheet.id, hw.id, paint.id])]))

    print("  характеристики:")
    for xmlid in ("pmk_bridge.attr_grade", "pmk_bridge.attr_sheet_size"):
        a = ref(xmlid)
        print("      %-16s значений %-3d режим=%s"
              % (a.name, len(a.value_ids), a.create_variant))
        if a.create_variant != "dynamic":
            print("          НЕ dynamic — при привязке к живому товару его вариант "
                  "уйдёт в архив вместе с остатком")

    print("  единицы по группам (data/uom_by_category.csv против факта в базе):")
    path = os.path.join(DATA_DIR, "uom_by_category.csv")
    with open(path, encoding="utf-8") as fp:
        for row in csv.DictReader(fp):
            categ = env.ref(row["category_xmlid"], raise_if_not_found=False)  # noqa: F821
            if not categ:
                print("      НЕТ КАТЕГОРИИ %s" % row["category_xmlid"])
                continue
            uom = env.ref(row["uom_xmlid"])  # noqa: F821
            wrong = env["product.template"].search(  # noqa: F821
                [("categ_id", "=", categ.id), ("uom_id", "!=", uom.id)])
            mark = "ок" if not wrong else ("НЕ В %s: %s" % (
                row["uom_name"], ", ".join(wrong.mapped("name"))))
            if wrong or categ.product_count:
                print("      %-34s хранение=%-4s закупка=%-4s окей=%-4s %s"
                      % (categ.name, row["uom_name"], row["purchase_uom_name"],
                         row["okei"], mark))

    # Единицы закупки: в Odoo 19 uom_po_id на товаре БОЛЬШЕ НЕТ, единица
    # закупки живёт только в строке прайса поставщика.
    tmpl_fields = env["product.template"]._fields  # noqa: F821
    si_fields = env["product.supplierinfo"]._fields  # noqa: F821
    print("  единица закупки: product.template.uom_po_id=%s, "
          "product.supplierinfo.product_uom_id=%s"
          % ("uom_po_id" in tmpl_fields, "product_uom_id" in si_fields))
    print("      значит единицу закупки задаём строкой прайса, а не карточкой,")
    print("      и пересчёт руб/т -> руб/м делаем САМИ: Odoo на паре тонна/метр")
    print("      считает 1:1 и молча занижает цену ровно в массу метра.")


# Снимок — первым и только первым: всё, что ниже, уже правит чужие записи.
snapshot_foreign_records()
adopt_existing_category()
drop_duplicate_sheet()
load_data_files()
check_uom_codes()
attach_attributes()
sheet_uom_report()
final_check()

print("\n" + SEP)
print("Подготовка закончена. Фиксируем: заливка номенклатуры идёт следующим")
print("запуском odoo shell, то есть другой транзакцией, и без commit она")
print("не увидит ни категорий, ни характеристик. Предохранитель наверху уже")
print("доказал, что база — копия: на живой скрипт до этой строки не доходит.")
print(SEP)
env.cr.commit()  # noqa: F821
print("зафиксировано в базе %s" % env.cr.dbname)  # noqa: F821
print("=== КОНЕЦ ===")
