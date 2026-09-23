# -*- coding: utf-8 -*-
"""Загрузка прайса поставщика в product.supplierinfo: руб/тонна -> руб за единицу товара.

ПОЧЕМУ ЭТОГО НЕ СДЕЛАТЬ «ПРОСТО ЗАПИСЬЮ ЦЕНЫ»

Замер на свежей копии живой базы (odoo_prices, карточка TRK-89x4 «Труба
круглая 89x4», единица учёта — МЕТР); всё внутри SAVEPOINT и откачено:

    строка прайса: 62 000 руб за ТОННУ с НДС
    (1) пишем как есть          -> supplierinfo.price = 62 000, единица «m»,
                                   price_discounted = 62 000 руб за МЕТР.
                                   Ни ошибки, ни предупреждения.
                                   Завышение в 143 раза.
    (2) честно ставим единицу
        «тонна» в product_uom_id -> Odoo 19 пересчитывает по ОТНОШЕНИЮ
                                   МНОЖИТЕЛЕЙ: 62000 * 1000 / 1 000 000 = 62,00
                                   руб за метр. Занижение в 7 раз. Тоже молча.

Второй случай особенно неприятен: в Odoo 19 из uom_uom.py::_compute_price
убрали проверку категории, осталось `price * to_unit.factor / self.factor`.
Тонна (factor 1e6, отсчёт от грамма) и метр (factor 1e3, отсчёт от миллиметра)
лежат в разных измерениях, но арифметика всё равно выполняется и даёт
правдоподобное число. Правдоподобное — хуже, чем абсурдное: абсурдное заметят.

Значит единственное место, где ошибку можно поймать, — загрузчик. Здесь цена
никогда не «просто число»: она всегда пара (сумма, единица) — класс Money, —
а запись в базу идёт ровно одной дверью assert_price_unit(), которая
отказывает, если единица цены не совпала с единицей карточки.

ЧТО СЧИТАЕМ И ИЗ ЧЕГО

    цена без НДС  = цена с НДС / (1 + ставка/100)   ставка — параметр ПРАЙСА
    руб за метр   = цена_без_НДС / 1000 * кг_в_метре
    руб за штуку  = цена_без_НДС / 1000 * кг_в_штуке   (лист)
    руб за кг     = цена_без_НДС / 1000               (метизы, ЛКП)

Масса берётся ИЗ ПРАЙСА (колонка «Вес 1 шт., кг», для проката делённая на
длину хлыста), а не из нашего справочника. Решение владельца, и причина
денежная: счёт поставщик выставит по СВОЕЙ массе. Наша теоретическая масса
остаётся для расчёта КП и здесь работает только как СТОРОЖ: если масса прайса
разошлась с нашей больше, чем на допуск, это уже не разница обмера, а ошибка
или другая позиция — строка отбивается. Реальный улов на этом прайсе:
«Балка 30К2, вес 1 шт. = 1,128» (поставщик написал тонны вместо килограммов;
без сторожа цена метра вышла бы в 1000 раз меньше).

СТАВКА НДС — ПАРАМЕТР, А НЕ КОНСТАНТА. Она меняется реже прайсов, но
меняется: 18 -> 20 -> 22. Прайс, залитый по вчерашней ставке, ошибается на
всю разницу и молча. Поэтому ставка лежит рядом с датой и поставщиком —
в описании прайса, и печатается в отчёте.

ДАТУ НЕ УГАДЫВАЕМ. В файле Металлсервиса две ячейки-даты (16.06.2026 и
20.08.2018) и ни одной подписи, какая из них дата прайса. Угадывание даты —
та же ошибка класса «чужая единица»: цены копятся рядом по date_start, и
неверная дата тихо перекрывает чужой период. Дату задаёт человек.

ЗАПУСК

    # 1) без базы — разбор, пересчёт и отчёт (ничего никуда не пишет)
    python3 experiments/odoo/addons/pmk_bridge/tools/load_prices.py \
        --file price_metallservice.xls --date 2026-06-16 --vat 22 --supplier 19

    # 2) на копии базы — то же самое, но цели ищутся среди карточек
    sh /tmp/run_prices.sh <этот файл> "PMK_PRICE_FILE=/tmp/price.xls \
        PMK_PRICE_DATE=2026-06-16 PMK_PRICE_VAT=22 PMK_PRICE_SUPPLIER=19"

    # 3) то же с записью: добавить PMK_PRICE_APPLY=1
    # 4) показать работу защиты: добавить PMK_PRICE_SELFTEST=1

Скрипт идемпотентен: повторный прогон того же прайса с той же датой создаёт
0 записей.
"""

import csv
import datetime
import math
import os
import re
import sys
from collections import Counter, defaultdict, namedtuple

# ─── ПРЕДОХРАНИТЕЛЬ ───────────────────────────────────────────────────────
# Скрипт пишет сотни строк цен и ФИКСИРУЕТ их (env.cr.commit ниже). У трёх его
# соседей по каталогу такой предохранитель есть, у него не было — приёмка это
# и поймала: один неверный ключ -d, и прайс ложится в боевую базу.
# Живая заливка разрешается только осознанно, переменной PMK_LIVE=1.
REHEARSAL_DBS = ("odoo_rehearsal", "odoo_probe", "odoo_rollback", "odoo_rollback_adopt")
_LIVE_OK = os.environ.get("PMK_LIVE") == "1"
if env.cr.dbname not in REHEARSAL_DBS and not _LIVE_OK:  # noqa: F821
    sys.exit("ОТКАЗ: %r не копия. Цены репетируют на копии; для боевой заливки"
             " запускать с PMK_LIVE=1." % env.cr.dbname)  # noqa: F821
if _LIVE_OK and env.cr.dbname not in REHEARSAL_DBS:  # noqa: F821
    print("@@ ВНИМАНИЕ: боевая заливка цен в базу %r (PMK_LIVE=1)" % env.cr.dbname)  # noqa: F821


# Внутри odoo shell скрипт приходит по stdin, и __file__ там не существует —
# отсюда запасной путь. Пути нужны только режиму без базы (справочник из CSV,
# разборщик рядом), внутри Odoo и то и другое берётся из базы и из окружения.
try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.getcwd()
MODULE_DIR = os.path.normpath(os.path.join(HERE, ".."))
ADDONS_DIR = os.path.normpath(os.path.join(MODULE_DIR, ".."))
# experiments/price-matching — разборщик названий. Свой в модуль не тянем:
# он уже проверен на 437 живых строках, дублировать правила значит развести
# два набора, которые разойдутся в первый же месяц.
MATCH_DIR_DEFAULT = os.path.normpath(
    os.path.join(ADDONS_DIR, "..", "..", "price-matching"))

# env приходит из odoo shell. Вне odoo его нет — и это рабочий режим, а не
# ошибка: разбор и пересчёт базы не требуют.
ODOO = globals().get("env")

SEP = "─" * 78


# ═══════════════════════════════════════════════════════════════════════════
# 1. ЦЕНА С ЕДИНИЦЕЙ
# ═══════════════════════════════════════════════════════════════════════════

class PriceUnitError(Exception):
    """Цена в чужой единице. Единственное исключение, которое нельзя глушить."""


class PriceRowError(Exception):
    """Строка прайса не годится.

    Причина хранится двумя частями: `kind` — вид отказа, по нему отчёт
    группируется, `detail` — конкретика с цифрами этой строки. Одной строкой
    текста так не сделать: «масса разошлась» в сводке нужна одной цифрой, а в
    разборе — с обеими массами и процентом.
    """

    def __init__(self, kind, detail):
        self.kind = kind
        self.detail = detail
        super(PriceRowError, self).__init__("%s: %s" % (kind, detail))


# Внутренние обозначения единиц цены. Строки, а не объекты uom: пересчёт
# должен работать и без базы — тогда его видно в отчёте до всякой записи.
RUB_T = "руб/т"
RUB_M = "руб/м"
RUB_PCS = "руб/шт"
RUB_KG = "руб/кг"
RUB_M2 = "руб/м²"

# Единица цены, которую ждёт карточка, — по единице учёта товара.
# Ключ — внешний идентификатор единицы, он не переводится (в базе стенда
# единицы называются по-английски: m, Units, kg, Ton).
UNIT_BY_UOM_XMLID = {
    "uom.product_uom_meter": RUB_M,
    "uom.product_uom_unit": RUB_PCS,
    "uom.product_uom_kgm": RUB_KG,
    "uom.product_uom_ton": RUB_T,
    "uom.product_uom_square_meter": RUB_M2,
}

Money = namedtuple("Money", "amount unit")


def money_str(m):
    return "%.2f %s" % (m.amount, m.unit)


# ⚠️ НДС БОЛЬШЕ НЕ СНИМАЕМ ПРИ ЗАЛИВКЕ (решение владельца 24.09.2026).
# Поставщики называют цену с НДС, и внутренний учёт ведётся так же: в базе
# лежит ровно то число, что в бумаге, чтобы его можно было сверить глазами.
# Функция ниже оставлена — она нужна отчётам и проверкам, где цену надо
# очистить, — но в заливку она больше не входит.
#
# Прежнее поведение (деление на 1,22) применялось к 780 записям 16.06.2026;
# 24.09.2026 они возвращены к исходным значениям умножением на ту же ставку.
def net_of_vat(gross, vat_rate):
    """Снять НДС. Ставка — из описания прайса, не из кода."""
    return Money(gross.amount / (1.0 + vat_rate / 100.0), gross.unit)


def to_product_unit(price, unit_to, mass_kg, what):
    """Пересчитать цену в единицу товара. Без массы — отказ, а не догадка.

    Именно здесь живёт вся арифметика перехода «тонна -> метр/штука». Отдельной
    функцией, потому что её результат надо показывать человеку в отчёте ДО
    записи: цифру, которую нельзя проверить глазами, в базу класть нельзя.
    """
    if price.unit == unit_to:
        return price
    if price.unit != RUB_T:
        raise PriceUnitError(
            "%s: цена объявлена в «%s», карточка считается в «%s» — такой "
            "пересчёт не описан, а угадывать нельзя" % (what, price.unit, unit_to))
    if unit_to == RUB_KG:
        return Money(price.amount / 1000.0, unit_to)
    if unit_to in (RUB_M, RUB_PCS):
        if not mass_kg or mass_kg <= 0:
            raise PriceUnitError(
                "%s: цена в «%s», карточка в «%s», а массы в строке прайса нет "
                "(пустой вес или нечисловая длина) — пересчитать не из чего"
                % (what, price.unit, unit_to))
        return Money(price.amount / 1000.0 * mass_kg, unit_to)
    raise PriceUnitError(
        "%s: перевод «%s» -> «%s» не описан" % (what, price.unit, unit_to))


def unit_of_product(product):
    """Единица цены, которую ждёт карточка."""
    xmlid = product.uom_id.get_external_id().get(product.uom_id.id)
    unit = UNIT_BY_UOM_XMLID.get(xmlid)
    if not unit:
        raise PriceUnitError(
            "единица «%s» (%s) карточки %s неизвестна загрузчику: не понимая "
            "единицу, цену класть нельзя" % (product.uom_id.name, xmlid,
                                             product.display_name))
    return unit


def assert_price_unit(product, price, env=None):
    """ЕДИНСТВЕННАЯ ДВЕРЬ В БАЗУ. Не совпала единица — отказ с объяснением.

    Сообщение намеренно длинное. Тот, кто увидит его через полгода, должен
    из одного текста понять: что не так, что бы сделал Odoo без этой проверки
    и как починить. Короткое «unit mismatch» такой задачи не решает.
    """
    want = unit_of_product(product)
    if price.unit == want:
        return
    silent = ""
    if env is not None:
        # Показываем ровно то, что Odoo сделал бы молча. Числа не выдуманы:
        # это тот же вызов uom._compute_price, который стоит в
        # product.supplierinfo::_compute_price_discounted.
        try:
            wrong_uom = env.ref({
                RUB_T: "uom.product_uom_ton", RUB_KG: "uom.product_uom_kgm",
                RUB_PCS: "uom.product_uom_unit", RUB_M: "uom.product_uom_meter",
            }[price.unit])
            as_is = price.amount
            converted = wrong_uom._compute_price(price.amount, product.uom_id)
            silent = (
                "\n    Odoo такую подмену НЕ ловит:"
                "\n      - оставить единицу карточки -> закупка прочтёт "
                "%.2f %s;"
                "\n      - поставить в product_uom_id «%s» -> Odoo поделит "
                "множители единиц (%s / %s) и прочтёт %.2f %s."
                "\n    Оба раза без единого сообщения об ошибке."
                % (as_is, want, wrong_uom.name, product.uom_id.factor,
                   wrong_uom.factor, converted, want))
        except Exception:                      # noqa: BLE001 — отчёт важнее
            silent = ""
    raise PriceUnitError(
        "ОТКАЗ: цена %s не может лечь на карточку %s.\n"
        "    Карточка считается в «%s» (единица учёта «%s»), цена объявлена "
        "в «%s»." % (money_str(price), product.display_name, want,
                     product.uom_id.name, price.unit)
        + silent +
        "\n    ЧТО ДЕЛАТЬ: пересчитать цену через массу —"
        "\n      руб/м = руб/т / 1000 * кг/м   (лист: руб/шт = руб/т / 1000 * кг/шт)"
        "\n    Массу брать из прайса (вес хлыста / длина), готовый пересчёт —"
        "\n    to_product_unit(); наша теоретическая масса тут только сторож.")


# ═══════════════════════════════════════════════════════════════════════════
# 2. ОПИСАНИЕ ПРАЙСА
# ═══════════════════════════════════════════════════════════════════════════

class PriceBook(object):
    """Прайс как объект: у цены есть не только сумма, но и обстоятельства.

    Ставка НДС, дата, валюта и единица цены — свойства ЭТОГО прайса, а не
    константы программы. Следующий поставщик пришлёт цену без НДС и в рублях
    за килограмм, и менять придётся вызов, а не арифметику.
    """

    def __init__(self, path, supplier_id, date, vat_rate=22.0, currency="RUB",
                 price_unit=RUB_T, mass_tolerance_pct=10.0, supplier_name=""):
        self.path = path
        self.supplier_id = int(supplier_id)
        self.supplier_name = supplier_name
        self.date = date                      # datetime.date, задаёт человек
        self.vat_rate = float(vat_rate)
        self.currency = currency
        self.price_unit = price_unit          # в чём цены в файле по умолчанию
        self.mass_tolerance_pct = float(mass_tolerance_pct)

    def describe(self):
        return [
            ("файл", os.path.basename(self.path)),
            ("поставщик", "id=%s %s" % (self.supplier_id, self.supplier_name)),
            ("дата прайса (date_start)", self.date.isoformat()),
            ("ставка НДС", "%.6g %% (параметр прайса)" % self.vat_rate),
            ("валюта", self.currency),
            ("единица цены в файле", self.price_unit),
            ("допуск расхождения массы", "%.6g %%" % self.mass_tolerance_pct),
        ]


# ═══════════════════════════════════════════════════════════════════════════
# 3. РАЗБОР ФАЙЛА
# ═══════════════════════════════════════════════════════════════════════════

Tier = namedtuple("Tier", "no column label qty_from unit")

PriceRow = namedtuple(
    "PriceRow", "excel_row section profile size grade length weight tiers gross")

# Заголовок раздела: одинокая колонка 0. Виды перечислены явно — в файле есть
# и реквизиты, и режим работы, и «Скидка от объёма!».
SECTION_RE = re.compile(
    r"^(Труба|Лист|Уголок|Швеллер|Балка|Арматура|Квадрат|Полоса|Сетка|"
    r"Профиль|Круг|Шестигранник|цветной)", re.I)
SKIP_PREFIX = ("Адрес", "ОГРН", "ИНН", "Р/с", "К/с", "Тел", "Банк", "ООО",
               "Е-mail", "- ", "Режим", "Выходной", "300 руб")

# Уровни объёма стоят не в файле целиком, а в шапке КАЖДОГО раздела, и они
# разные: «до 0,3 тн» у труб (305 строк), «до 0,5 тн» у листа и уголка
# (275 строк), «до 10 шт» у арматурной сетки (9 строк). Прошить 0,3
# константой значит на 275 строках объявить оптовую цену раньше, чем её даёт
# поставщик, — и опять молча.
TIER_UPTO_RE = re.compile(r"^до\s+([\d,\.]+)\s*(тн|т|кг|шт)", re.I)
TIER_FROM_RE = re.compile(r"^от\s+([\d,\.]+)(?:\s*тн)?\s*(?:до\s+[\d,\.]+)?\s*(тн|т|кг|шт)", re.I)


def _num(text):
    """Число из ячейки прайса: запятая как разделитель дробной части."""
    text = (text or "").strip().replace(",", ".").replace(" ", "")
    if not re.match(r"^\d+(\.\d+)?$", text):
        return None
    return float(text)


def parse_tiers(cells):
    """Разобрать шапку уровней объёма раздела: три ячейки под ценами."""
    tiers = []
    for no, (col, raw) in enumerate(cells, start=1):
        raw = (raw or "").strip()
        if not raw:
            continue
        m = TIER_UPTO_RE.match(raw)
        if m:
            tiers.append(Tier(no, col, raw, 0.0, m.group(2).lower()))
            continue
        m = TIER_FROM_RE.match(raw)
        if m:
            qty = float(m.group(1).replace(",", "."))
            tiers.append(Tier(no, col, raw, qty, m.group(2).lower()))
            continue
        # Незнакомая шапка — не уровень. Молча пропустить нельзя: из этой
        # ячейки берут цену.
        tiers.append(Tier(no, col, raw, None, None))
    return tiers


def read_price_xls(path):
    """Прочитать .xls Металлсервиса. Возвращает (строки, разделы, диагностика)."""
    try:
        import xlrd
    except ImportError:                        # pragma: no cover
        raise SystemExit("нужен xlrd: pip install xlrd (в контейнере он есть)")
    book = xlrd.open_workbook(path)
    # Второй лист «Сервис» — услуги резки и доставки, не номенклатура.
    sheet = book.sheet_by_name("Металл")

    def cell(r, c):
        v = sheet.cell_value(r, c)
        if isinstance(v, float) and v == int(v):
            v = int(v)
        return str(v).strip()

    rows, sections = [], []
    section, tiers = "", []
    date_cells = []
    for r in range(sheet.nrows):
        for c in range(sheet.ncols):
            if sheet.cell(r, c).ctype == 3:    # XL_CELL_DATE
                from xlrd.xldate import xldate_as_datetime
                date_cells.append(xldate_as_datetime(
                    sheet.cell(r, c).value, book.datemode).date())
        a, b = cell(r, 0), cell(r, 1)
        if a and not b:
            if SECTION_RE.match(a) and not a.startswith(SKIP_PREFIX):
                section, tiers = a, []
                sections.append(section)
            continue
        # Шапка таблицы раздела и строка уровней объёма.
        if b.lower().startswith(("размер", "профиль")):
            continue
        if not a and cell(r, 4).lower().startswith(("до ", "от ")):
            tiers = parse_tiers([(4, cell(r, 4)), (5, cell(r, 5)), (6, cell(r, 6))])
            continue
        if not (a and b) or a.startswith(SKIP_PREFIX):
            continue
        rows.append(PriceRow(
            excel_row=r + 1, section=section, profile=a, size=b,
            grade=cell(r, 2), length=cell(r, 3), weight=cell(r, 7),
            tiers=tiers, gross=[cell(r, 4), cell(r, 5), cell(r, 6)]))
    return rows, sections, sorted(set(date_cells))


def price_row_name(row):
    """Название строки для разборщика: вид часто стоит только в заголовке.

    «Квадратная 40 х 40 х 2» само по себе не значит ничего — квадратной бывает
    и труба, и заготовка. Вид даёт раздел, и без него разбор теряет 114 строк
    из 596 (замер: 303 совпадения против 417).
    """
    p, low = row.profile, row.profile.lower()
    if low in ("квадратная", "прямоугольная"):
        return "Труба профильная %s %s" % (low, row.size)
    if low.startswith("труба эл/св"):
        return "Труба электросварная %s%s" % (
            row.size, " оцинкованная" if "оцинк" in low else "")
    if low.startswith("труба б/ш"):
        return "Труба бесшовная %s" % row.size
    if low.startswith("труба вгп"):
        return "Труба ВГП %s" % row.size
    if low == "балка":
        return "Двутавр %s" % row.size
    if low.startswith("гнутый швеллер"):
        return "Швеллер гнутый %s" % row.size
    if low.startswith("лист"):
        return "Лист %s" % row.size
    return "%s %s" % (p, row.size)


# ═══════════════════════════════════════════════════════════════════════════
# 4. ПРОВЕРКИ СТРОКИ
# ═══════════════════════════════════════════════════════════════════════════

# Слово-признак в прайсе обязано подтверждаться позицией справочника, на
# которую строка легла. Иначе цена ложится на ДРУГОЙ металл, и это молча:
# разборщик названий на покрытие и сплав не смотрит, он сличает вид и размеры.
# Улов на этом прайсе — оцинкованные трубы на чёрных карточках, алюминиевый
# лист на стальном и чечевичное рифление на гладком листе.
QUALIFIERS = [
    ("оцинк", ("оцинк",), "оцинкованная позиция"),
    ("алюмин", ("алюмин",), "алюминий"),
    ("нержав", ("нержав",), "нержавеющая сталь"),
    ("латун", ("латун",), "латунь"),
    ("медн", ("медн",), "медь"),
    ("чечев", ("чечев",), "чечевичное рифление"),
    ("рифл", ("рифл",), "рифление"),
    ("просечно", ("просечно",), "просечно-вытяжной"),
    ("пвл", ("просечно",), "просечно-вытяжной"),
    ("бесшов", ("бесш",), "бесшовная труба"),
    ("б/ш", ("бесш",), "бесшовная труба"),
]


def check_qualifiers(row, ref_item):
    """Сличить признаки материала строки прайса и позиции справочника."""
    price_text = ("%s %s %s" % (row.section, row.profile, row.size)).lower()
    ref_text = ("%s %s" % (ref_item.get("type", ""), ref_item.get("size", ""))).lower()
    for word, expected, human in QUALIFIERS:
        if word in price_text and not any(e in ref_text for e in expected):
            raise PriceRowError(
                "покрытие или сплав не подтверждается справочником",
                "в прайсе «%s», а справочник даёт «%s %s» — %s; цена легла бы "
                "на другой металл" % (word, ref_item.get("type", ""),
                                      ref_item.get("size", ""), human))


def row_mass(row, is_sheet):
    """Масса единицы ИЗ ПРАЙСА: кг в метре для проката, кг в листе для листа."""
    weight = _num(row.weight)
    if weight is None:
        raise PriceRowError("нет веса в строке прайса",
                            "пересчитывать руб/т в руб/ед. не из чего")
    if is_sheet:
        # У листа колонка «Длина, м» пуста: вес указан за лист целиком.
        return weight
    length = _num(row.length)
    if length is None or length <= 0:
        raise PriceRowError(
            "длина хлыста не число",
            "«%s» (мотки, «2-3,5», «н/д») — массу метра не посчитать" % row.length)
    return weight / length


def check_mass(mass_price, mass_ours, tolerance_pct, what):
    """Наша теоретическая масса — сторож, а не источник цены.

    До допуска расхождение считаем настоящим: поставщик взвешивает партию, у
    тонкостенных разница доходит до 5%. Выше допуска это уже не обмер:
    «Балка 30К2, вес 1 шт. 1,128 кг» при 12-метровом хлысте — тонны вместо
    килограммов, и цена метра ушла бы в 1000 раз вниз.
    """
    if not mass_ours:
        return 0.0
    dev = abs(mass_price - mass_ours) / mass_ours * 100.0
    if dev > tolerance_pct:
        raise PriceRowError(
            "масса прайса разошлась со справочником",
            "%.4f кг против %.4f кг (%.1f%%, допуск %.6g%%) — это не разница "
            "обмера; %s" % (mass_price, mass_ours, dev, tolerance_pct, what))
    return dev


# ═══════════════════════════════════════════════════════════════════════════
# 5. МАРКА И ГАБАРИТ ЛИСТА
# ═══════════════════════════════════════════════════════════════════════════

# Марки прайса -> значения характеристики «Марка стали». Ключ нормализован:
# верхний регистр, убраны пробелы и обратные слэши. «Ст3сп\пс» значит «сп или
# пс на выбор поставщика» — берём сп, она в справочнике помечена основной.
GRADE_MAP = {
    "СТ3СП": "Ст3сп", "СТ3ПС": "Ст3пс", "СТ3СППС": "Ст3сп", "СТ3": "Ст3сп",
    "СТ3СППСНМЗ": "Ст3сп",
    "09Г2С": "09Г2С", "09Г2С12": "09Г2С", "СТ09Г2С": "09Г2С",
    "10ХСНД": "10ХСНД", "15ХСНД": "15ХСНД", "17Г1С": "17Г1С",
    "СТ20": "Ст20", "40Х": "40Х",
}


# Марка, которой заливка карточек метит единственный вариант (SEED_GRADE в
# scripts/load_products.py). При столкновении цен разных марок цена этой марки
# имеет преимущество: именно её купят.
BASE_GRADE = "Ст3сп"


def normalise_grade(raw):
    """Привести марку прайса к ключу.

    Грабли из живого файла: «О9Г2С-12» начинается с КИРИЛЛИЧЕСКОЙ «О», а не с
    нуля — 18 строк листа. Глазом не отличить, а ключ разъезжается, и лист
    09Г2С молча уходит в «марка не заведена».
    """
    s = (raw or "").upper().replace("Ё", "Е")          # Ё -> Е
    s = s.replace("О", "0") if re.match(r"^О\d", s) else s  # О9Г2С -> 09Г2С
    s = re.sub(r"[\s\\/\.\-\(\)]", "", s)
    s = re.sub(r"(2СОРТ|НМЗ)$", "", s)
    return s


def map_grade(raw):
    return GRADE_MAP.get(normalise_grade(raw))


def sheet_gabarit(size_label):
    """Из «3 х 1500 х 6000» вынуть габарит «1500x6000»."""
    nums = re.findall(r"\d+(?:[.,]\d+)?", (size_label or "").replace(",", "."))
    if len(nums) < 3:
        return None
    def clean(x):
        return str(int(float(x))) if float(x) == int(float(x)) else x
    return "%sx%s" % (clean(nums[1]), clean(nums[2]))


# ═══════════════════════════════════════════════════════════════════════════
# 6. СПРАВОЧНИК
# ═══════════════════════════════════════════════════════════════════════════

def reference_from_csv():
    """Справочник из CSV модуля pmk_calc — режим без базы."""
    data = os.path.join(ADDONS_DIR, "pmk_calc", "data")
    profiles, sheets = [], []
    with open(os.path.join(data, "pmk.metal.profile.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            profiles.append({"id": r["id"], "type": r["profile_type"],
                             "size": r["size_label"], "gost": r["gost"],
                             "mass": float(r["mass_per_meter"] or 0)})
    with open(os.path.join(data, "pmk.metal.sheet.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sheets.append({"id": r["id"], "type": r["sheet_type"],
                           "th": float(r["thickness_mm"]), "gost": r["gost"],
                           "mass": float(r["mass_per_sqm"] or 0)})
    return {"profiles": profiles, "sheets": sheets}


def reference_from_db(env):
    """Справочник из базы: ровно те строки, у которых есть карточки.

    Ключ строки — имя её внешнего идентификатора без модуля. По нему же
    собирается внешний идентификатор карточки (pmk_bridge.product_<ключ>),
    так что сопоставление прайса и поиск товара идут по одному и тому же
    ключу, а не по имени, которое переводится.
    """
    profiles, sheets = [], []
    recs = env["pmk.metal.profile"].search([], order="id")
    ext = recs.get_external_id()
    for rec in recs:
        xmlid = ext.get(rec.id)
        if xmlid:
            profiles.append({"id": xmlid.split(".", 1)[1], "type": rec.profile_type,
                             "size": rec.size_label, "gost": rec.gost,
                             "mass": rec.mass_per_meter})
    recs = env["pmk.metal.sheet"].search([], order="id")
    ext = recs.get_external_id()
    for rec in recs:
        xmlid = ext.get(rec.id)
        if xmlid:
            sheets.append({"id": xmlid.split(".", 1)[1], "type": rec.sheet_type,
                           "th": rec.thickness_mm, "gost": rec.gost,
                           "mass": rec.mass_per_sqm})
    return {"profiles": profiles, "sheets": sheets}


# ═══════════════════════════════════════════════════════════════════════════
# 7. ПОДГОТОВКА ЗАПИСЕЙ
# ═══════════════════════════════════════════════════════════════════════════

Prepared = namedtuple(
    "Prepared", "row ref_id is_sheet gabarit grade mass mass_dev gross net "
                "per_unit unit vendor_name")


def prepare(rows, matcher, book):
    """Разобрать, сопоставить и пересчитать. Базы здесь ещё нет.

    Возвращает (готовые, отказы, счётчики). Всё, что можно проверить без
    базы, проверяется до записи — отчёт по цифрам должен быть виден раньше,
    чем что-то попадёт в supplierinfo.
    """
    prepared, refused = [], []
    stat = Counter()
    for row in rows:
        res = matcher.match(price_row_name(row))
        stat["строк"] += 1
        if res["status"] != "совпало":
            stat["не сопоставлено"] += 1
            refused.append((row, "разборщик названий: %s" % res["status"], ""))
            continue
        stat["сопоставлено"] += 1
        item = res["matches"][0]
        is_sheet = str(res.get("type") or "").startswith("Лист")
        try:
            # Уровни объёма берём из шапки РАЗДЕЛА. Нет шапки или она в
            # штуках — значит цена в разделе не за тонну, и угадывать нельзя.
            tiers = [t for t in row.tiers if t.qty_from is not None]
            if not tiers:
                raise PriceRowError("шапка уровней объёма не разобрана",
                                    "раздел «%s» идёт без строки «до 0,3 тн | ...»"
                                    % row.section[:40])
            bad = [t for t in tiers if t.unit not in ("тн", "т")]
            if bad:
                raise PriceRowError(
                    "уровни объёма раздела не в тоннах",
                    "«%s» — значит и цена в разделе не за тонну, а угадывать "
                    "нельзя" % bad[0].label)
            check_qualifiers(row, item)
            mass = row_mass(row, is_sheet)
            ours = item.get("mass") or 0.0
            if is_sheet:
                gab = sheet_gabarit(row.size)
                if not gab:
                    raise PriceRowError("в размере нет габарита листа",
                                        "«%s»" % row.size)
                w, l = [float(x) for x in gab.split("x")]
                ours = ours * (w * l / 1e6)    # кг/м² -> кг в листе
            else:
                gab = None
            dev = check_mass(mass, ours, book.mass_tolerance_pct,
                             "строка отбита, нужен человек")
            gross = Money(_num(row.gross[0]) or 0.0, book.price_unit)
            if not gross.amount:
                raise PriceRowError("нет цены первого уровня", "ячейка пуста")
            unit = RUB_PCS if is_sheet else RUB_M
            # Цена хранится КАК В ПРАЙСЕ, с НДС: переменная называется net по
            # истории, но очистка отключена (см. комментарий у net_of_vat).
            net = gross
            per_unit = to_product_unit(net, unit, mass, "строка %s" % row.excel_row)
        except PriceRowError as exc:
            stat["отбито проверками"] += 1
            refused.append((row, exc.kind, exc.detail))
            continue
        except PriceUnitError as exc:
            stat["отбито проверками"] += 1
            refused.append((row, "цена в чужой единице", str(exc).split("\n")[0]))
            continue
        prepared.append(Prepared(
            row=row, ref_id=item["id"], is_sheet=is_sheet, gabarit=gab,
            grade=row.grade, mass=mass, mass_dev=dev, gross=gross, net=net,
            per_unit=per_unit, unit=unit,
            vendor_name=("%s %s %s" % (row.profile, row.size, row.grade)).strip()))
    return prepared, refused, stat


def pick_winners(prepared):
    """Одна цена на позицию: одна и та же позиция встречается в прайсе дважды.

    Две разные причины, и решаются они по-разному.

    1. Один и тот же профиль разной длины хлыста: «Труба эл/св 57 х 3» идёт
       6 м (24,8 кг -> 265,24 руб/м) и 12 м (48,0 кг -> 256,69 руб/м) —
       поставщик взвесил по-своему. Берём БОЛЬШУЮ: занизить себестоимость КП
       хуже, чем завысить.
    2. Один профиль разной МАРКИ: «Труба эл/св 114 х 4» есть Ст3сп\пс за
       78 290 и Ст 09Г2С за 92 290 руб/т. Разница 18% — это не обмер, это
       другой металл. Здесь «взять большую» неверно: карточка проката сегодня
       живёт одним вариантом Ст3сп (его сажает заливка карточек, SEED_GRADE),
       и цена 09Г2С на нём означала бы, что обычная труба стоит на 18%
       дороже, чем её продают. Поэтому сначала предпочитаем строку БАЗОВОЙ
       марки, и только среди равных берём большую цену.

    Обе строки в любом случае печатаются: решение «взять большую» — наше, а
    не поставщика, и человек должен видеть, из чего выбирали.
    """
    by_target = defaultdict(list)
    for p in prepared:
        # У листа марка и габарит задают ВАРИАНТ, то есть разные цели, и
        # склеивать их нельзя. У проката цель одна — шаблон.
        key = (p.ref_id, p.gabarit, map_grade(p.grade) if p.is_sheet else None)
        by_target[key].append(p)
    winners, collisions = [], []
    for key, items in by_target.items():
        items.sort(key=lambda p: (map_grade(p.grade) == BASE_GRADE,
                                  p.per_unit.amount), reverse=True)
        winners.append(items[0])
        if len(items) > 1 and abs(items[0].per_unit.amount
                                  - items[-1].per_unit.amount) > 0.005:
            collisions.append((key, items))
    return winners, collisions


def min_qty_in_product_unit(tonnes, mass_kg, unit, digits):
    """Границу уровня из ТОНН перевести в единицу товара.

    Это тот же дефект, что и с ценой, только в другом поле: Odoo сравнивает
    min_qty с количеством в единице продавца (product_product.py::
    _get_filtered_sellers), то есть в МЕТРАХ. Оставить там 0,3 значит объявить
    скидку с 0,3 метра.

    Округляем ВВЕРХ: min_qty — нижняя граница уровня. Округлив вниз, мы дадим
    оптовую цену на объёме, на котором поставщик её не даёт, и занизим
    себестоимость — молча.
    """
    if not tonnes:
        return 0.0
    qty = tonnes * 1000.0 / mass_kg
    if unit == RUB_PCS:
        return float(math.ceil(qty))           # штуками дробных не бывает
    k = 10 ** digits
    return math.ceil(qty * k) / k


# ═══════════════════════════════════════════════════════════════════════════
# 8. ЗАПИСЬ В БАЗУ
# ═══════════════════════════════════════════════════════════════════════════

def resolve_target(env, item, sheet_sizes):
    """Куда ложится цена: шаблон (прокат) или конкретный вариант (лист).

    Прокат — на ШАБЛОН: габарита у него нет, цена метра одна на карточку, а
    вариант сегодня ровно один. Лист — на ВАРИАНТ: единица «штука», и штука
    1500x6000 стоит вдвое дороже штуки 1500x3000; на шаблоне такая цена
    означала бы «лист любого размера по цене шестиметрового».

    Вариантов загрузчик цен НЕ СОЗДАЁТ. Создание второго варианта обнуляет
    артикул шаблона (product.template.default_code вычисляется по
    единственному варианту — замер в README), а чинить это должен тот, кто
    заливает карточки, не тот, кто грузит цены.
    """
    tmpl = env.ref("pmk_bridge.product_%s" % item.ref_id, raise_if_not_found=False)
    if not tmpl:
        raise PriceRowError("нет карточки под позицию справочника",
                            "pmk_bridge.product_%s" % item.ref_id)
    if not item.is_sheet:
        return tmpl, env["product.product"].browse()
    grade = map_grade(item.grade)
    if not grade:
        raise PriceRowError(
            "марка листа не заведена характеристикой",
            "«%s» — вариант листа не опознать" % item.grade)
    if item.gabarit not in sheet_sizes:
        raise PriceRowError(
            "габарит листа не заведён характеристикой",
            "%s, а заведены %s — цена штуки легла бы не на тот лист"
            % (item.gabarit, ", ".join(sorted(sheet_sizes))))
    for variant in tmpl.product_variant_ids:
        names = set(variant.product_template_attribute_value_ids.mapped(
            "product_attribute_value_id.name"))
        if grade in names and item.gabarit in names:
            return tmpl, variant
    raise PriceRowError(
        "варианта листа нет, а создавать его загрузчику цен нельзя",
        "(%s, %s) у карточки %s; второй вариант обнуляет артикул шаблона"
        % (grade, item.gabarit, tmpl.default_code or tmpl.name))


def upsert_supplierinfo(env, book, tmpl, variant, tier, price, min_qty, vendor_name):
    """Записать цену уровня, НЕ затирая прошлую: ряд копится по date_start.

    Ключ ряда — (поставщик, товар, номер уровня). Номер уровня держим в
    sequence: min_qty для этого не годится, он пересчитывается из массы и
    у нового прайса будет другим, а ряд должен остаться тем же.
    sequence в Odoo — только тай-брейк при равной цене (_select_seller
    сортирует по price_discounted), так что смысла записи он не меняет.

    Прошлую запись ряда закрываем датой за день до новой: перекрывающиеся
    периоды Odoo не считает ошибкой, он просто возьмёт ту, что дешевле,
    и старая цена будет всплывать годами.
    """
    SI = env["product.supplierinfo"]
    domain = [("partner_id", "=", book.supplier_id),
              ("product_tmpl_id", "=", tmpl.id),
              ("product_id", "=", variant.id if variant else False),
              ("sequence", "=", tier.no)]
    series = SI.search(domain, order="date_start")
    vals = {
        "partner_id": book.supplier_id,
        "product_tmpl_id": tmpl.id,
        "product_id": variant.id if variant else False,
        "sequence": tier.no,
        "min_qty": min_qty,
        "price": price.amount,
        "date_start": book.date,
        "product_name": vendor_name,
        "currency_id": env.company.currency_id.id,
        # Единицу проставляем ЯВНО, хотя Odoo подставил бы её сам: явная
        # запись означает «цена уже в единице товара», и её видно в форме.
        "product_uom_id": (variant or tmpl).uom_id.id,
    }
    same_date = series.filtered(lambda r: r.date_start == book.date)
    if same_date:
        rec = same_date[0]
        if (abs(rec.price - price.amount) < 0.005
                and abs(rec.min_qty - min_qty) < 1e-9):
            return rec, "без изменений"
        rec.write(vals)
        return rec, "исправлено"
    previous = series.filtered(
        lambda r: r.date_start and r.date_start < book.date
        and (not r.date_end or r.date_end >= book.date))
    closed = 0
    for rec in previous:
        rec.date_end = book.date - datetime.timedelta(days=1)
        closed += 1
    rec = SI.create(vals)
    return rec, ("создано, закрыт прошлый период" if closed else "создано")


def verify_written(rec, price):
    """Прочитать записанное глазами Odoo. Тихая подмена единицы всплывёт здесь.

    price_discounted — это ровно то число, которое увидит закупка:
    product_uom_id._compute_price(price, единица товара). Если единица цены
    и единица товара разошлись, оно не совпадёт с тем, что мы считали.
    """
    seen = rec.price_discounted
    if abs(seen - price.amount) > 0.005:
        raise PriceUnitError(
            "записали %s, а Odoo читает %.2f за единицу товара — единица цены "
            "и единица карточки разошлись" % (money_str(price), seen))


# ═══════════════════════════════════════════════════════════════════════════
# 9. ОТЧЁТ
# ═══════════════════════════════════════════════════════════════════════════

def head(title):
    print("\n" + SEP)
    print(title)
    print(SEP)


def print_first_rows(winners, book, limit=10):
    head("ПЕРВЫЕ %s ПОЗИЦИЙ: ЦЕНА ЗА ТОННУ -> ЦЕНА ЗА ЕДИНИЦУ" % limit)
    print("  %-22s %-26s %10s %10s %8s %9s %7s" % (
        "позиция прайса", "справочник", "руб/т НДС", "руб/т без", "кг/ед", "цена/ед", "ед"))
    for p in winners[:limit]:
        print("  %-22s %-26s %10.2f %10.2f %8.4f %9.2f %7s" % (
            ("%s %s" % (p.row.profile, p.row.size))[:22], p.ref_id[:26],
            p.gross.amount, p.net.amount, p.mass, p.per_unit.amount, p.unit))
    print("\n  Проверка первой строки руками: %.2f / (1 + %.6g/100) = %.4f руб/т без НДС;"
          % (winners[0].gross.amount, book.vat_rate, winners[0].net.amount))
    print("  %.4f / 1000 * %.4f кг = %.2f %s"
          % (winners[0].net.amount, winners[0].mass,
             winners[0].per_unit.amount, winners[0].unit))


def selftest_guard(env, book):
    """Показать, что цена за тонну на товар в метрах больше не проходит."""
    head("ЗАЩИТА: ПОПЫТКА ПОЛОЖИТЬ ЦЕНУ ЗА ТОННУ НА ТОВАР В МЕТРАХ")
    product = env["product.product"].search([("default_code", "=", "TRK-89x4")], limit=1)
    if not product:
        print("  карточки TRK-89x4 нет — показать не на чем")
        return
    raw = Money(62000.0, RUB_T)
    print("  карточка: %s, единица учёта «%s»" % (product.display_name, product.uom_id.name))
    print("  пробуем записать: %s\n" % money_str(raw))
    try:
        assert_price_unit(product, raw, env=env)
        print("  !!! ПРОВЕРКА НЕ СРАБОТАЛА — цена прошла")
    except PriceUnitError as exc:
        print("  " + str(exc).replace("\n", "\n  "))
    mass = 102.26 / 12.0
    good = to_product_unit(net_of_vat(raw, book.vat_rate), RUB_M, mass, "проверка")
    print("\n  Тот же прайс через пересчёт: %.2f / %.2f / 1000 * %.4f = %s"
          % (raw.amount, 1 + book.vat_rate / 100.0, mass, money_str(good)))
    assert_price_unit(product, good, env=env)
    print("  эта цена проверку проходит: единица «%s» совпала с единицей карточки"
          % good.unit)


# ═══════════════════════════════════════════════════════════════════════════
# 10. ГЛАВНОЕ
# ═══════════════════════════════════════════════════════════════════════════

def read_params():
    """Параметры: из командной строки вне Odoo, из окружения внутри него.

    Внутри odoo shell скрипт приходит по stdin, и sys.argv принадлежит самому
    Odoo — читать оттуда наши ключи нельзя.
    """
    if ODOO is None:
        import argparse
        ap = argparse.ArgumentParser(description="Загрузка прайса поставщика")
        ap.add_argument("--file", required=True)
        ap.add_argument("--date", required=True, help="дата прайса, ГГГГ-ММ-ДД")
        ap.add_argument("--vat", default="22", help="ставка НДС прайса, %%")
        ap.add_argument("--supplier", default="0")
        ap.add_argument("--tolerance", default="10", help="допуск массы, %%")
        a = ap.parse_args()
        return dict(path=a.file, date=a.date, vat=a.vat, supplier=a.supplier,
                    tolerance=a.tolerance, apply=False, selftest=False,
                    match_dir=os.environ.get("PMK_PRICE_MATCH", MATCH_DIR_DEFAULT))
    env_get = os.environ.get
    return dict(
        path=env_get("PMK_PRICE_FILE", ""), date=env_get("PMK_PRICE_DATE", ""),
        vat=env_get("PMK_PRICE_VAT", "22"), supplier=env_get("PMK_PRICE_SUPPLIER", "0"),
        tolerance=env_get("PMK_PRICE_TOLERANCE", "10"),
        apply=env_get("PMK_PRICE_APPLY") == "1",
        selftest=env_get("PMK_PRICE_SELFTEST") == "1",
        match_dir=env_get("PMK_PRICE_MATCH", "/tmp/pmk_price_code"))


def main():
    par = read_params()
    if not par["path"] or not os.path.exists(par["path"]):
        sys.exit("ОТКАЗ: файла прайса нет: %r" % par["path"])
    sys.path.insert(0, par["match_dir"])
    try:
        from match import Matcher
    except ImportError:
        sys.exit("ОТКАЗ: рядом нет match.py (ищу в %s)" % par["match_dir"])

    rows, sections, date_cells = read_price_xls(par["path"])
    if not par["date"]:
        sys.exit(
            "ОТКАЗ: дата прайса не задана. Угадывать нельзя: цены копятся "
            "рядом по date_start, и неверная дата тихо перекроет чужой период."
            "\n  Даты, найденные в файле (какая из них дата прайса — "
            "неизвестно): %s" % ", ".join(d.isoformat() for d in date_cells))
    book = PriceBook(
        path=par["path"], supplier_id=par["supplier"],
        date=datetime.date(*[int(x) for x in par["date"].split("-")]),
        vat_rate=par["vat"], mass_tolerance_pct=par["tolerance"])

    env = ODOO
    if env is not None:
        partner = env["res.partner"].browse(book.supplier_id)
        if not partner.exists():
            sys.exit("ОТКАЗ: поставщика id=%s в базе нет" % book.supplier_id)
        book.supplier_name = partner.name
        if env.company.currency_id.name != book.currency:
            sys.exit("ОТКАЗ: прайс в %s, компания считает в %s — курс не наше дело"
                     % (book.currency, env.company.currency_id.name))
        reference = reference_from_db(env)
    else:
        reference = reference_from_csv()

    head("ПРАЙС")
    for k, v in book.describe():
        print("  %-26s %s" % (k + ":", v))
    print("  %-26s %s" % ("даты внутри файла:", ", ".join(d.isoformat() for d in date_cells)))
    print("  %-26s %s" % ("режим:", "ЗАПИСЬ В БАЗУ" if par["apply"] else
                          ("расчёт по базе, без записи" if env is not None else
                           "расчёт без базы")))

    head("РАЗБОР ФАЙЛА")
    print("  разделов: %s, строк-позиций: %s" % (len(sections), len(rows)))
    tier_kinds = Counter(tuple(t.label for t in r.tiers) for r in rows)
    for labels, n in tier_kinds.most_common():
        print("    уровни объёма %-46s строк: %s" % (" | ".join(labels)[:46], n))

    matcher = Matcher(reference)
    prepared, refused, stat = prepare(rows, matcher, book)
    winners, collisions = pick_winners(prepared)

    head("СОПОСТАВЛЕНИЕ И ПРОВЕРКИ")
    print("  строк всего:            %s" % stat["строк"])
    print("  сопоставлено правилами: %s" % stat["сопоставлено"])
    print("  отбито проверками:      %s" % stat["отбито проверками"])
    print("  годных строк:           %s" % len(prepared))
    print("  позиций после склейки дублей: %s (столкновений цен: %s)"
          % (len(winners), len(collisions)))
    kinds = Counter()
    example = {}
    for row, kind, detail in refused:
        kinds[kind] += 1
        example.setdefault(kind, (row, detail))
    print("\n  ПОЧЕМУ ОТБИТО, по видам (строка прайса -> пример):")
    for kind, n in kinds.most_common():
        row, detail = example[kind]
        print("    %-46s %4s   стр.%s «%s %s» %s"
              % (kind[:46], n, row.excel_row, row.profile[:16], row.size[:16],
                 detail[:60]))
    if collisions:
        print("\n  СТОЛКНОВЕНИЯ (берём большую цену, обе печатаем):")
        for key, items in collisions[:5]:
            print("    %s: %s" % (key[0], "; ".join(
                "строка %s -> %.2f %s (%s м, %s кг)"
                % (i.row.excel_row, i.per_unit.amount, i.unit, i.row.length, i.row.weight)
                for i in items)))

    if not winners:
        sys.exit("ОТКАЗ: годных строк нет — писать нечего")
    winners.sort(key=lambda p: p.row.excel_row)
    print_first_rows(winners, book)

    if env is None:
        head("ИТОГ (без базы)")
        print("  позиций готово: %s; записей вышло бы: %s (три уровня объёма)"
              % (len(winners), len(winners) * 3))
        print("\n=== КОНЕЦ ===")
        return

    # ── дальше нужна база: цели, единицы, запись
    sizes = set(env["product.attribute"].search(
        [("name", "=", "Габарит листа")], limit=1).value_ids.mapped("name"))
    digits = env["decimal.precision"].precision_get("Product Unit")
    targets, no_target = [], []
    for item in winners:
        try:
            tmpl, variant = resolve_target(env, item, sizes)
            product = variant or tmpl.product_variant_ids[:1]
            if not product:
                raise PriceRowError("у карточки нет ни одного варианта",
                                    tmpl.default_code or tmpl.name)
            # Единица карточки — последнее слово. Совпала ли она с тем, во что
            # мы пересчитали, решает не намерение, а проверка.
            assert_price_unit(product, item.per_unit, env=env)
            targets.append((item, tmpl, variant, product))
        except (PriceRowError, PriceUnitError) as exc:
            no_target.append((item, str(exc).split("\n")[0]))

    head("ЦЕЛИ В БАЗЕ")
    on_tmpl = len([t for t in targets if not t[2]])
    on_variant = len(targets) - on_tmpl
    print("  позиций с целью:   %s" % len(targets))
    print("    из них прокат — на ШАБЛОН (габарита нет, цена метра одна): %s" % on_tmpl)
    print("    из них лист — на ВАРИАНТ (штука габарита X, цена от габарита): %s" % on_variant)
    print("  позиций без цели:  %s" % len(no_target))
    reasons = Counter(why[:74] for _i, why in no_target)
    for why, n in reasons.most_common(12):
        print("    %-74s %s" % (why, n))

    if par["selftest"]:
        selftest_guard(env, book)

    if not par["apply"]:
        print("\n  записей вышло бы: %s" % sum(
            len([t for t in i.row.tiers if t.qty_from is not None]) for i, _, _, _ in targets))
        print("\n=== КОНЕЦ ===")
        return

    head("ЗАПИСЬ")
    made = Counter()
    for item, tmpl, variant, product in targets:
        for tier in [t for t in item.row.tiers if t.qty_from is not None]:
            gross = Money(_num(item.row.gross[tier.column - 4]) or 0.0, book.price_unit)
            if not gross.amount:
                made["уровень без цены"] += 1
                continue
            price = to_product_unit(net_of_vat(gross, book.vat_rate), item.unit,
                                    item.mass, "строка %s" % item.row.excel_row)
            assert_price_unit(product, price, env=env)   # дверь одна
            min_qty = min_qty_in_product_unit(tier.qty_from, item.mass, item.unit, digits)
            rec, what = upsert_supplierinfo(env, book, tmpl, variant, tier,
                                            price, min_qty, item.vendor_name)
            verify_written(rec, price)
            made[what] += 1
    for what, n in made.most_common():
        print("  %-32s %s" % (what, n))
    print("  ВСЕГО ЗАПИСЕЙ ПРАЙСА В БАЗЕ: %s"
          % env["product.supplierinfo"].search_count(
              [("partner_id", "=", book.supplier_id)]))

    env.cr.commit()
    print("\nзафиксировано в базе %s" % env.cr.dbname)
    print("\n=== КОНЕЦ ===")


if globals().get("__name__") == "__main__" or ODOO is not None:
    main()
