# -*- coding: utf-8 -*-
"""Заливка 752 карточек номенклатуры из справочника pmk_calc. ТОЛЬКО НА КОПИИ.

Зачем. Цена поставщика в Odoo живёт в product.supplierinfo и требует товар.
Сортамент лежит в собственных таблицах pmk_calc и товаром не является — цене
некуда лечь. Этот скрипт заводит на каждую строку справочника карточку.

КЛЮЧ СОПОСТАВЛЕНИЯ — внешний идентификатор строки справочника. На строку
pmk_calc.profile_двутавр_20б1 заводится карточка с внешним идентификатором
pmk_bridge.product_profile_двутавр_20б1. Не имя (переводится и переписывается)
и не артикул (сегодня схема одна, завтра владелец попросит другую — и связь с
справочником порвётся). Внешний идентификатор не меняется никогда, поэтому
повторный запуск находит ту же карточку и правит её, а не заводит вторую.

ПОРЯДОК ДЕЙСТВИЙ — НЕ ПЕРЕСТАВЛЯТЬ. Разобран по product_template.py
::_create_variant_ids и подтверждён замером (scripts/risk_attribute.py):

    1. карточка создаётся БЕЗ характеристик — тогда Odoo делает ей один
       вариант без меток;
    2. на этот вариант пишется артикул. Артикул шаблона — вычисляемое поле:
       `_compute_default_code` берёт его у ЕДИНСТВЕННОГО варианта, а при
       нуле или двух вариантах ставит False;
    3. характеристика вешается с ОДНИМ значением: ветка single_value_lines
       дописывает значение существующему варианту, и он остаётся жив вместе
       с остатком и артикулом;
    4. только теперь строка расширяется до всех значений;
    5. и только после этого на ВАРИАНТ пишется вес: у листа он зависит от
       габарита, то есть от варианта, а габарит появляется на шаге 3.

Если создать карточку сразу с характеристикой, на шаге создания вариантов ещё
нет, ветка single_value_lines работать не с чем, а dynamic новых не создаёт —
получится карточка с НУЛЁМ вариантов, без места под артикул и без склада.
Замер: 8 значений сразу на живой трубе → вариант в архиве, 3621,790 м из
системы исчезли (остались в базе, но не видны ни в остатках, ни в подборе).

ВЕС ЖИВЁТ НА ВАРИАНТЕ, А НЕ НА КАРТОЧКЕ. product.template.weight — не
самостоятельное поле, а зеркало варианта: product_template.py
::_compute_template_field_from_variant_field отдаёт вес ЕДИНСТВЕННОГО
варианта, а как только вариантов становится два — ставит 0; обратная запись
(_set_product_variant_field) по той же причине доходит до варианта только
пока он один. Замер на копии, карточка LST-GL-10:

    вариантов 1                     → вес шаблона 78,50000
    родился вариант 1500x3000       → вес шаблона 0,00000

Поэтому писать вес на карточку бессмысленно вдвойне: три габарита листа
весили бы одинаково, а после появления второго варианта — вообще ничего.

Запуск (после prepare_environment.py, он готовит категории и характеристики):

    sh /tmp/run_reh.sh <этот файл>

Скрипт идемпотентен: второй прогон обязан создать 0 карточек.
"""

import csv
import os
import sys
import time

# ─── ПРЕДОХРАНИТЕЛЬ ───────────────────────────────────────────────────────
# Скрипт пишет 752 карточки. На живой базе он не запускается: имя базы
# задаётся ключом -d, а odoo.conf держит db_name = odoo, так что ошибиться
# легко. Умираем до первой записи.
REHEARSAL_DBS = ("odoo_rehearsal", "odoo_probe")
# Живая заливка разрешается ТОЛЬКО осознанно: переменная PMK_LIVE=1 в окружении
# контейнера. Предохранитель при этом не снимается — он остаётся для случайного
# запуска без ключа, а владелец получает одну явную точку, где он говорит «да,
# я лью в боевую базу». Заливка 20.09.2026 сделана владельцем именно так.
_LIVE_OK = os.environ.get("PMK_LIVE") == "1"
if env.cr.dbname not in REHEARSAL_DBS and not _LIVE_OK:  # noqa: F821
    sys.exit("ОТКАЗ: %r не копия. Заливку репетируют на копии; для боевой"
             " заливки запускать с PMK_LIVE=1." % env.cr.dbname)  # noqa: F821
if _LIVE_OK and env.cr.dbname not in REHEARSAL_DBS:  # noqa: F821
    print("@@ ВНИМАНИЕ: боевая заливка в базу %r (PMK_LIVE=1)" % env.cr.dbname)  # noqa: F821

DATA_DIR = "/tmp/pmk_bridge_data"
CODE_DIR = "/tmp/pmk_bridge_code"   # сюда раннер кладёт models/sku.py
MODULE = "pmk_bridge"
SEP = "─" * 78

# Генератор артикулов лежит в модуле, а модуль не установлен — импортируем
# файлом. В sku.py нет ни ORM, ни относительных импортов ровно для этого:
# один и тот же код проверяется тестами без базы и работает здесь.
sys.path.insert(0, CODE_DIR)
import sku as sku_gen  # noqa: E402

# Марка, которой помечается первый (и пока единственный) вариант каждой
# карточки. Ст3сп стоит is_default в pmk.metal.grade — это то, что завод
# возит по умолчанию. Метка нужна не для красоты: без неё правило одного
# значения не сработает и вариант потеряется.
SEED_GRADE = "pmk_bridge.attr_grade_st3sp"
# Габарит по умолчанию для листа. 1500x6000 — самый ходовой, и именно он
# подтверждён единственным приходом листа 4 мм (9,000 м² = 1,5 x 6).
SEED_SIZE = "pmk_bridge.attr_sheet_size_1500x6000"

# Четыре карточки, которые на стенде УЖЕ ЕСТЬ и по которым уже прошли приходы,
# списания и резервы. Их надо переиспользовать, а не продублировать: дубль
# оставил бы остаток и историю на карточке, которую никто не спросит.
# Ключ — артикул, значение — имя карточки на стенде. Имя тут одноразовое:
# им карточка опознаётся ровно один раз, дальше её держит внешний
# идентификатор, а имя скрипт приводит к справочнику.
ADOPT_BY_NAME = {
    "TPK-100x100x3": "Труба профильная 100x100x3 ГОСТ 8639-82",
    "UGR-63x63x5": "Уголок равнополочный 63x63x5 ГОСТ 8509-93",
    "LST-GL-4": "Лист горячекатаный 4 мм ГОСТ 19903-2015",
    "LST-GL-8": "Лист горячекатаный 8 мм ГОСТ 19903-2015",
}


def head(n, title):
    print("\n" + SEP)
    print("ШАГ %s. %s" % (n, title))
    print(SEP)


# ─── Площадь габарита листа ───────────────────────────────────────────────
# Габарит приходит МЕТКОЙ варианта («1500x6000»), то есть строкой: значения
# характеристики в Odoo — это имена, чисел там нет. Площадь считаем из метки,
# а не берём из второй таблицы: заведут четвёртый габарит (1250x2500 под
# оцинковку) — он заработает сам, и никто не забудет дописать его в таблицу.
#
# Разделитель — тот же латинский «x» (U+0078), что и в типоразмерах проката:
# в data/product_attribute.xml все три габарита записаны именно им (проверено
# побайтно). Кириллическую «х» и знак «×» НЕ принимаем, хотя глазом они не
# отличаются: молча разобрав чужой разделитель, можно получить не ту площадь
# и занизить вес всей карточки — ровно та ошибка, которую этот шаг и чинит.
def sheet_area_m2(size_name):
    """Метка габарита «1500x6000» → площадь одного листа, м² (9.0).

    Габариты в миллиметрах, поэтому делим на 1 000 000 ОДИН раз, а не два:
    1500 x 6000 = 9 000 000 мм², это ровно 9,0 м² без потери на округлении.
    """
    name = (size_name or "").strip()
    if not name:
        raise ValueError("пустая метка габарита листа")
    for alien, what in ((sku_gen.FASTENER_SEP, "знак «×» метизов"),
                        (sku_gen.CYRILLIC_X, "кириллическая «х»")):
        if alien in name:
            raise ValueError("в габарите %r %s вместо латинской «x» — "
                             "площадь по такой метке считать нельзя" % (size_name, what))
    parts = name.split(sku_gen.PROFILE_SEP)
    if len(parts) != 2:
        raise ValueError("габарит %r не вида «ширина x длина»" % (size_name,))
    try:
        width_mm, length_mm = (float(p) for p in parts)
    except ValueError:
        raise ValueError("в габарите %r не число" % (size_name,))
    if width_mm <= 0 or length_mm <= 0:
        raise ValueError("в габарите %r сторона <= 0" % (size_name,))
    return width_mm * length_mm / 1000000.0


def expected_variant_weight(item, tmpl, variant, size_attr, unit, sqm):
    """Сколько должен весить ОДИН вариант в единице хранения своей карточки.

    Прокат, метизы и ЛКП: вес от варианта не зависит — метр двутавра весит
    одинаково хоть из Ст3сп, хоть из 09Г2С (масса метра в справочнике одна,
    она геометрическая). Возвращаем вес из плана.

    Лист: в справочнике лежит mass_per_sqm — масса одного КВАДРАТНОГО МЕТРА,
    а учитываем мы лист ШТУКАМИ определённого размера (решение владельца).
    Значит вес штуки = масса квадрата x площадь габарита. Габарит берём с
    самого варианта, а не из SEED_SIZE: у карточки их три, и каждый весит своё.

    ЕДИНИЦА РЕШАЕТ, УМНОЖАТЬ ИЛИ НЕТ. Карточку листа, по которой уже прошли
    движения, в штуки переводит технолог вместе с инвентаризацией, а не
    скрипт (шаг 6 prepare_environment.py и шаг 4 здесь). Пока такая карточка
    осталась в м², единица хранения — квадратный метр, и весит он ровно
    массу квадрата. Умножить её на площадь означало бы завысить вес во
    столько же раз, во сколько прежняя заливка его занижала.
    """
    if item["sqm_mass"] is None:
        return item["weight"]

    if tmpl.uom_id == sqm:
        return item["sqm_mass"]
    if tmpl.uom_id != unit:
        raise ValueError("%s: единица %r — не штуки и не м², сколько весит "
                         "одна единица, скрипт не знает"
                         % (item["sku"], tmpl.uom_id.name))

    labels = variant.product_template_attribute_value_ids.filtered(
        lambda v: v.attribute_id == size_attr)
    if len(labels) != 1:
        raise ValueError("%s: у варианта %s меток габарита %d, а нужна ровно "
                         "одна — без габарита площадь неизвестна"
                         % (item["sku"], variant.id, len(labels)))
    return item["sqm_mass"] * sheet_area_m2(labels.name)


# ═══ ШАГ 1 ════════════════════════════════════════════════════════════════
def fix_weight_precision():
    """Поднять точность массы до 5 знаков ДО того, как массы поедут в базу.

    Поля weight и у product.template, и у product.product объявлены как
    Float(digits='Stock Weight') — точность у них ОДНА на двоих, и поднимать
    её надо здесь, до шага 6, где вес пишется на варианты. «Stock Weight» на
    стенде стоит 2 знака. Массы справочника в эти два знака не влезают, и
    Odoo округлит их МОЛЧА, при записи:

        болт М8×20   0,01180 кг/шт -> 0,01   (ошибка 18%)
        шайба 8      0,00210 кг/шт -> 0,00   (масса исчезла совсем)
        арматура d6  0,222  кг/м   -> 0,22   (ошибка 1%)

    Для метизов это не косметика: прайс приходит в руб/кг, и цена штуки
    считается как руб/кг x масса штуки. При массе 0,00 цена болта — ноль.

    5 знаков — не с потолка: ровно столько у weight_kg в pmk.metal.fastener
    (digits=(12,5)), у остальных справочников знаков меньше.
    """
    head(1, "Точность массы")
    dp = env["decimal.precision"].search([("name", "=", "Stock Weight")])  # noqa: F821
    if not dp:
        sys.exit("ОТКАЗ: нет записи точности «Stock Weight» — округление не проверить")
    print("  было: %s знака" % dp.digits)
    if dp.digits < 5:
        dp.digits = 5
        # Точность читается через ormcache; без сброса поле продолжит
        # округлять по-старому до конца процесса.
        env.registry.clear_cache()  # noqa: F821
    print("  стало: %s знаков (нужно 5: weight_kg метизов — digits=(12,5))" % dp.digits)


# ═══ ШАГ 2 ════════════════════════════════════════════════════════════════
def build_plan():
    """Собрать план: что должно получиться из каждой строки справочника.

    План строится ЦЕЛИКОМ до первой записи. Так ошибка разбора (чужой
    разделитель в типоразмере, неизвестный вид проката) ловится на пустой
    базе, а не на середине заливки, когда половина карточек уже создана.
    """
    head(2, "План заливки")

    # Категория выводится из того же префикса, что и артикул: ARM -> categ_
    # rolled_arm. Вторая таблица соответствий рассинхронизировалась бы с
    # первой при любом добавлении вида проката.
    def profile_categ(profile_type):
        return "pmk_bridge.categ_rolled_%s" % sku_gen.PROFILE_PREFIX[profile_type].lower()

    def sheet_categ(sheet_type):
        return "pmk_bridge.categ_sheet_%s" % sku_gen.SHEET_PREFIX[sheet_type].split("-")[1].lower()

    def fastener_categ(fastener_type):
        return "pmk_bridge.categ_hw_%s" % sku_gen.FASTENER_KIND[fastener_type].lower()

    # Единица — из утверждённой таблицы data/uom_by_category.csv, а не из
    # третьего места в коде. Таблица уже проверена шагом 7 подготовки среды.
    uom_by_categ = {}
    with open(os.path.join(DATA_DIR, "uom_by_category.csv"), encoding="utf-8") as fp:
        for row in csv.DictReader(fp):
            uom_by_categ[row["category_xmlid"]] = row["uom_xmlid"]

    plan = []
    problems = []

    # weight   — вес одной единицы хранения, когда он от варианта НЕ зависит
    #            (метр проката, штука метиза, килограмм краски);
    # sqm_mass — масса квадратного метра, только у листа. Две разные величины
    #            в одном поле как раз и дали занижение в девять раз: масса
    #            квадрата уехала в вес ШТУКИ листа 1500x6000, а это 9 м².
    #            Пока они лежат врозь, перепутать их молча уже нельзя.
    def add(model, rec, xmlid, name, sku, categ, weight, tracking, attrs,
            sqm_mass=None):
        key = xmlid.split(".", 1)[1]
        plan.append({
            "model": model, "res_id": rec.id, "ref_xmlid": xmlid,
            "xmlid": "%s.product_%s" % (MODULE, key),
            "name": name, "sku": sku, "categ": categ,
            "uom": uom_by_categ[categ], "weight": weight,
            "sqm_mass": sqm_mass,
            "tracking": tracking, "attrs": attrs,
        })

    # Прокат: метрами, партия = кусок, марка стали — характеристика.
    profiles = env["pmk.metal.profile"].search([], order="id")  # noqa: F821
    xmlids = profiles.get_external_id()
    for rec in profiles:
        xmlid = xmlids.get(rec.id)
        if not xmlid:
            problems.append("pmk.metal.profile id %s без внешнего идентификатора" % rec.id)
            continue
        try:
            sku = sku_gen.profile_sku(rec.profile_type, rec.size_label)
        except sku_gen.SkuError as exc:
            problems.append("pmk.metal.profile id %s: %s" % (rec.id, exc))
            continue
        add("pmk.metal.profile", rec, xmlid,
            "%s %s" % (rec.display_name, rec.gost), sku,
            profile_categ(rec.profile_type), rec.mass_per_meter, "lot", ["grade"])

    # Лист: штуками листа определённого размера, габарит — вторая характеристика.
    sheets = env["pmk.metal.sheet"].search([], order="id")  # noqa: F821
    xmlids = sheets.get_external_id()
    for rec in sheets:
        xmlid = xmlids.get(rec.id)
        if not xmlid:
            # Строка листа без внешнего идентификатора — это ручной дубль
            # (шаг 2 подготовки среды его удаляет). Заводить по нему карточку
            # нельзя: цена ляжет на ту из двух, которую не спросят.
            problems.append("pmk.metal.sheet id %s (%s %s мм) без внешнего "
                            "идентификатора — дубль не удалён"
                            % (rec.id, rec.sheet_type, rec.thickness_mm))
            continue
        try:
            sku = sku_gen.sheet_sku(rec.sheet_type, rec.thickness_mm, rec.size_label)
        except sku_gen.SkuError as exc:
            problems.append("pmk.metal.sheet id %s: %s" % (rec.id, exc))
            continue
        # Веса карточки у листа НЕТ: штука листа — это габарит, а габарит
        # живёт на варианте. Отдаём массу квадрата отдельным полем, вес
        # посчитается на шаге 6 для каждого варианта по его габариту.
        add("pmk.metal.sheet", rec, xmlid,
            "%s %s" % (rec.display_name, rec.gost), sku,
            sheet_categ(rec.sheet_type), None, "lot", ["grade", "size"],
            sqm_mass=rec.mass_per_sqm)

    # Метизы: штуками, марка стали не применима (у метиза класс прочности,
    # а не марка проката), партии не нужны — болт от болта неотличим.
    fasteners = env["pmk.metal.fastener"].search([], order="id")  # noqa: F821
    xmlids = fasteners.get_external_id()
    for rec in fasteners:
        xmlid = xmlids.get(rec.id)
        if not xmlid:
            problems.append("pmk.metal.fastener id %s без внешнего идентификатора" % rec.id)
            continue
        try:
            sku = sku_gen.fastener_sku(rec.fastener_type, rec.size_label)
        except sku_gen.SkuError as exc:
            problems.append("pmk.metal.fastener id %s: %s" % (rec.id, exc))
            continue
        name = ("%s %s" % (rec.name, rec.gost)).strip() if rec.gost else rec.name
        add("pmk.metal.fastener", rec, xmlid, name, sku,
            fastener_categ(rec.fastener_type), rec.weight_kg, "none", [])

    # ЛКП: килограммами (решение владельца). Массы в справочнике нет и быть
    # не может — там расход кг/м². Килограмм товара весит килограмм, это не
    # допущение, а определение единицы, поэтому 1,0 честнее нуля.
    paints = env["pmk.paint.coating"].search([], order="id")  # noqa: F821
    xmlids = paints.get_external_id()
    for rec in paints:
        xmlid = xmlids.get(rec.id)
        if not xmlid:
            problems.append("pmk.paint.coating id %s без внешнего идентификатора" % rec.id)
            continue
        sku = sku_gen.paint_sku(xmlid)
        add("pmk.paint.coating", rec, xmlid, rec.name, sku,
            "pmk_bridge.categ_paint", 1.0, "none", [])

    print("  строк разобрано: %d" % len(plan))
    for model, label in (("pmk.metal.profile", "прокат"), ("pmk.metal.sheet", "лист"),
                         ("pmk.metal.fastener", "метизы"), ("pmk.paint.coating", "ЛКП")):
        print("      %-8s %d" % (label, sum(1 for p in plan if p["model"] == model)))

    codes = [p["sku"] for p in plan]
    dups = sorted({c for c in codes if codes.count(c) > 1})
    print("  уникальных артикулов: %d, столкновений: %d %s"
          % (len(set(codes)), len(dups), ", ".join(dups)))
    if dups:
        sys.exit("ОТКАЗ: артикулы столкнулись, заливать нельзя — цены разъедутся")
    if problems:
        print("  ПРОБЛЕМЫ (%d):" % len(problems))
        for p in problems:
            print("      %s" % p)
        sys.exit("ОТКАЗ: план собран не полностью, заливка не начиналась")
    return plan


# ═══ ШАГ 3 ════════════════════════════════════════════════════════════════
def adopt_existing(plan):
    """Привязать внешние идентификаторы к УЖЕ СУЩЕСТВУЮЩИМ карточкам.

    Делается ДО создания и ДО переименования: опознать карточку по имени
    можно только пока имя старое. После усыновления имя больше не нужно —
    карточку держит внешний идентификатор.

    Если карточки с таким именем нет (её могли удалить или стенд подняли с
    нуля), это не ошибка: скрипт заведёт её как новую. Отказ тут вреднее —
    он остановил бы заливку 752 карточек из-за одной ненайденной.
    """
    head(3, "Существующие карточки")
    imd = env["ir.model.data"]  # noqa: F821
    Tmpl = env["product.template"]  # noqa: F821
    by_sku = {p["sku"]: p for p in plan}
    adopted = 0
    for sku, name in ADOPT_BY_NAME.items():
        item = by_sku.get(sku)
        if not item:
            sys.exit("ОТКАЗ: артикула %s нет в плане — схема артикулов разъехалась "
                     "со списком существующих карточек" % sku)
        module, ident = item["xmlid"].split(".", 1)
        if imd.search_count([("module", "=", module), ("name", "=", ident)]):
            print("  %-16s уже усыновлена" % sku)
            adopted += 1
            continue
        tmpl = Tmpl.search([("name", "=", name)])
        if len(tmpl) != 1:
            print("  %-16s карточек с именем «%s»: %d — будет создана новая"
                  % (sku, name, len(tmpl)))
            continue
        imd.create({"module": module, "name": ident, "model": "product.template",
                    "res_id": tmpl.id,
                    # noupdate=True НЕ формальность. При установке или
                    # обновлении модуля Odoo подчищает «осиротевшие» записи
                    # своего модуля — те, что не встретились в файлах данных
                    # и у которых noupdate=false. Наши 752 карточки в файлах
                    # данных не лежат: их пишет этот скрипт. Без флага первая
                    # же установка pmk_bridge снесла бы всю номенклатуру.
                    "noupdate": True})
        env.cr.execute(  # noqa: F821
            "SELECT count(*) FROM stock_move m JOIN product_product p ON p.id=m.product_id "
            "WHERE p.product_tmpl_id=%s", (tmpl.id,))
        print("  %-16s усыновлена: шаблон %s «%s», движений %s"
              % (sku, tmpl.id, name, env.cr.fetchone()[0]))  # noqa: F821
        adopted += 1
    print("  усыновлено: %d из %d" % (adopted, len(ADOPT_BY_NAME)))


# ═══ ШАГ 4 ════════════════════════════════════════════════════════════════
def sync_products(plan):
    """Создать недостающие карточки и привести существующие к справочнику.

    Возвращает список созданных карточек — им отдельно вешаются
    характеристики, у остальных они уже есть.
    """
    head(4, "Карточки")
    imd = env["ir.model.data"]  # noqa: F821
    Tmpl = env["product.template"]  # noqa: F821

    # Один запрос вместо 752: ir.model.data — таблица, а не индекс.
    known = {r["name"]: r["res_id"] for r in imd.search_read(
        [("module", "=", MODULE), ("model", "=", "product.template"),
         ("name", "like", "product_%")], ["name", "res_id"])}
    print("  карточек уже привязано к справочнику: %d" % len(known))

    categ_cache, uom_cache = {}, {}

    def ref(xmlid, cache):
        if xmlid not in cache:
            cache[xmlid] = env.ref(xmlid)  # noqa: F821
        return cache[xmlid]

    to_create, existing = [], []
    for item in plan:
        ident = item["xmlid"].split(".", 1)[1]
        if ident in known:
            existing.append((item, known[ident]))
        else:
            to_create.append(item)

    created_ids = []
    if to_create:
        started = time.time()
        # Карточки создаются БЕЗ характеристик — иначе вариантов не будет
        # вовсе (см. порядок действий в шапке файла). Пачками по 100, чтобы
        # при падении было видно, на какой сотне встало.
        for start in range(0, len(to_create), 100):
            chunk = to_create[start:start + 100]
            tmpls = Tmpl.create([{
                "name": item["name"],
                "type": "consu",          # в Odoo 19 «товар» — это consu...
                "is_storable": True,      # ...плюс этот флаг, он и даёт склад
                "tracking": item["tracking"],
                "categ_id": ref(item["categ"], categ_cache).id,
                "uom_id": ref(item["uom"], uom_cache).id,
                # У листа вес зависит от габарита, а габарит появится только
                # на шаге 5 вместе с характеристикой. Кладём ноль: пусть
                # карточка постоит без веса, чем с неверным. Настоящий вес
                # проставит шаг 6, и шаг 7 откажется фиксировать, если нет.
                "weight": 0.0 if item["weight"] is None else item["weight"],
                "purchase_ok": True,
                "sale_ok": True,
            } for item in chunk])
            # Артикул пишем ОТДЕЛЬНЫМ действием, когда вариант уже создан:
            # default_code шаблона — вычисляемое поле от единственного
            # варианта, в один create с созданием шаблона оно не успевает.
            for item, tmpl in zip(chunk, tmpls):
                tmpl.default_code = item["sku"]
            imd.create([{
                "module": MODULE, "name": item["xmlid"].split(".", 1)[1],
                "model": "product.template", "res_id": tmpl.id, "noupdate": True,
            } for item, tmpl in zip(chunk, tmpls)])
            created_ids += tmpls.ids
            print("  создано %d/%d" % (len(created_ids), len(to_create)))
        print("  создание заняло %.1f с" % (time.time() - started))
    else:
        print("  создавать нечего: все карточки уже есть")

    # Существующие приводим к справочнику пофамильно и печатаем, что именно
    # поменяли: молчаливое «обновлено 4» ничего не доказывает.
    changed = 0
    for item, tmpl_id in existing:
        tmpl = Tmpl.browse(tmpl_id)
        if not tmpl.exists():
            sys.exit("ОТКАЗ: внешний идентификатор %s указывает на удалённую "
                     "карточку %s" % (item["xmlid"], tmpl_id))
        wanted = {
            "name": item["name"],
            "categ_id": ref(item["categ"], categ_cache).id,
            "default_code": item["sku"],
        }
        # Вес карточки правим только там, где он от варианта не зависит.
        # У листа запись сюда либо не дойдёт до варианта вовсе (как только
        # вариантов стало два, _set_product_variant_field молчит), либо
        # перебьёт правильный вес габарита массой квадрата — то самое
        # занижение в девять раз. Лист считает шаг 6, по каждому варианту.
        if item["weight"] is not None:
            wanted["weight"] = item["weight"]
        diff = {k: v for k, v in wanted.items()
                if (tmpl[k].id if k.endswith("_id") else tmpl[k]) != v}
        # Единица — отдельно и с оглядкой на историю. Смена единицы в Odoo 19
        # НЕ пересчитывает числа, она их переименовывает: «1 м² = 1 шт», и
        # один лист 1500x6000 стал бы девятью листами. Карточку с движениями
        # переводит технолог вместе с инвентаризацией, а не скрипт.
        uom = ref(item["uom"], uom_cache)
        if tmpl.uom_id != uom:
            env.cr.execute(  # noqa: F821
                "SELECT count(*) FROM stock_move m JOIN product_product p "
                "ON p.id=m.product_id WHERE p.product_tmpl_id=%s", (tmpl.id,))
            moves = env.cr.fetchone()[0]  # noqa: F821
            if moves:
                print("  %-16s ЕДИНИЦА НЕ ТРОНУТА: %s вместо %s, движений %d — "
                      "перевод только вместе с инвентаризацией"
                      % (item["sku"], tmpl.uom_id.name, uom.name, moves))
            else:
                diff["uom_id"] = uom.id
        if diff:
            tmpl.write(diff)
            changed += 1
            print("  %-16s обновлено: %s" % (item["sku"], ", ".join(sorted(diff))))
    print("  создано: %d, обновлено: %d, без изменений: %d"
          % (len(created_ids), changed, len(existing) - changed))
    return Tmpl.browse(created_ids)


# ═══ ШАГ 5 ════════════════════════════════════════════════════════════════
def attach_attributes(plan, created):
    """Навесить характеристики по правилу одного значения и расширить.

    Порядок ровно такой, каким он показан замером: сначала строка с ОДНИМ
    значением (вариант впитывает метку и остаётся жив вместе с артикулом),
    потом расширение до полного набора. Обратный порядок архивирует вариант.
    """
    head(5, "Характеристики")
    Line = env["product.template.attribute.line"]  # noqa: F821
    grade = env.ref("pmk_bridge.attr_grade")  # noqa: F821
    size = env.ref("pmk_bridge.attr_sheet_size")  # noqa: F821
    seeds = {"grade": (grade, env.ref(SEED_GRADE)),  # noqa: F821
             "size": (size, env.ref(SEED_SIZE))}  # noqa: F821

    by_xmlid = {}
    for r in env["ir.model.data"].search_read(  # noqa: F821
            [("module", "=", MODULE), ("model", "=", "product.template"),
             ("name", "like", "product_%")], ["name", "res_id"]):
        by_xmlid[r["name"]] = r["res_id"]

    # Что уже висит — чтобы повторный прогон не заводил вторую строку той же
    # характеристики (Odoo этого не запрещает, а варианты после такого не
    # собрать).
    have = set()
    for line in Line.search([("attribute_id", "in", (grade + size).ids)]):
        have.add((line.product_tmpl_id.id, line.attribute_id.id))

    to_add = []
    for item in plan:
        tmpl_id = by_xmlid.get(item["xmlid"].split(".", 1)[1])
        if not tmpl_id:
            sys.exit("ОТКАЗ: карточка %s потерялась между шагами" % item["xmlid"])
        for kind in item["attrs"]:
            attr, seed = seeds[kind]
            if (tmpl_id, attr.id) in have:
                continue
            to_add.append({"product_tmpl_id": tmpl_id, "attribute_id": attr.id,
                           "value_ids": [(6, 0, seed.ids)]})

    print("  карточек создано в этот прогон: %d" % len(created))
    print("  строк характеристик уже есть: %d, нужно добавить: %d"
          % (len(have), len(to_add)))
    if to_add:
        started = time.time()
        for start in range(0, len(to_add), 200):
            Line.create(to_add[start:start + 200])
            print("  добавлено %d/%d" % (min(start + 200, len(to_add)), len(to_add)))
        print("  добавление заняло %.1f с" % (time.time() - started))

    # Расширение до полного набора значений — одной записью на характеристику.
    started = time.time()
    for attr in (grade, size):
        lines = Line.search([("attribute_id", "=", attr.id)])
        narrow = lines.filtered(lambda l, a=attr: len(l.value_ids) != len(a.value_ids))
        print("  «%s»: строк %d, из них неполных %d"
              % (attr.name, len(lines), len(narrow)))
        if narrow:
            narrow.write({"value_ids": [(6, 0, attr.value_ids.ids)]})
    print("  расширение заняло %.1f с" % (time.time() - started))


# ═══ ШАГ 6 ════════════════════════════════════════════════════════════════
# Карточки, на которых печатается сама арифметика веса. Шесть штук, по одной
# на вид листа плюс контрольная LST-GL-10 приёмщика: «сверено 56, расхождений
# 0» ничего не доказывает, пока не видно, из чего число получилось.
WEIGHT_SAMPLES = ("LST-GL-3", "LST-GL-4", "LST-GL-10",
                  "LST-RF-4", "LST-PV-406", "LST-ZN-0.5")


def set_variant_weights(plan):
    """Проставить вес КАЖДОМУ варианту. У листа он зависит от габарита.

    ЧТО ЧИНИМ. Прежняя заливка клала в вес карточки листа mass_per_sqm —
    массу одного КВАДРАТНОГО МЕТРА. А учитываем мы лист ШТУКАМИ листа
    определённого размера (решение владельца), и штука 1500x6000 — это 9 м².
    Замер приёмщика: LST-GL-10 весил 78,5 кг вместо 706,5 — занижение ровно
    в площадь габарита, в девять раз, на 56 карточках из 56.

    ПОЧЕМУ НА ВАРИАНТ, А НЕ НА КАРТОЧКУ. Габаритов у карточки три, и весят
    они разное: 9,0 / 4,5 / 4,0 м². Одно число на карточку — это одно из трёх
    неверных, а с появлением второго варианта поле карточки вообще обнуляется
    (замер в шапке файла: 78,50000 → 0,00000). Собственное поле веса есть
    только у product.product, туда и пишем.

    АРХИВНЫЕ ВАРИАНТЫ ТОЖЕ. active_test=False стоит не для красоты: вариант
    с движениями Odoo не удаляет, а архивирует (_unlink_or_archive), остаток
    при этом остаётся на нём. Архивный вариант с неверным весом — это тонны,
    которые вылезут при первой же инвентаризации или разархивации.
    """
    head(6, "Вес вариантов")
    Tmpl = env["product.template"]  # noqa: F821
    size_attr = env.ref("pmk_bridge.attr_sheet_size")  # noqa: F821
    unit = env.ref("uom.product_uom_unit")  # noqa: F821
    sqm = env.ref("uom.product_uom_square_meter")  # noqa: F821

    print("  площади габаритов (считаются из метки варианта, не из таблицы):")
    for val in size_attr.value_ids.sorted("sequence"):
        print("      %-12s %8.4f м²" % (val.name, sheet_area_m2(val.name)))

    by_ident = {r["name"]: r["res_id"] for r in env["ir.model.data"].search_read(  # noqa: F821
        [("module", "=", MODULE), ("model", "=", "product.template"),
         ("name", "like", "product_%")], ["name", "res_id"])}

    started = time.time()
    seen = touched = 0
    samples = []
    for item in plan:
        tmpl_id = by_ident.get(item["xmlid"].split(".", 1)[1])
        if not tmpl_id:
            sys.exit("ОТКАЗ: карточка %s потерялась между шагами" % item["xmlid"])
        tmpl = Tmpl.browse(tmpl_id)
        for var in tmpl.with_context(active_test=False).product_variant_ids:
            seen += 1
            try:
                want = expected_variant_weight(item, tmpl, var, size_attr, unit, sqm)
            except ValueError as exc:
                sys.exit("ОТКАЗ: %s" % exc)
            if round(var.weight, 5) != round(want, 5):
                var.weight = want
                touched += 1
            if item["sku"] in WEIGHT_SAMPLES:
                label = var.product_template_attribute_value_ids.filtered(
                    lambda v: v.attribute_id == size_attr).name or "без габарита"
                # Множитель печатаем тот, что применён на самом деле: у
                # карточки, оставленной в м², он равен 1, и это видно.
                area = sheet_area_m2(label) if tmpl.uom_id == unit else 1.0
                samples.append((item["sku"], item["sqm_mass"], label,
                                area, tmpl.uom_id.name, want))

    print("  вариантов просмотрено: %d, вес изменён у %d" % (seen, touched))
    print("  арифметика на контрольных карточках:")
    for sku, sqm_mass, label, area, uom_name, want in sorted(samples):
        print("      %-12s %9.5f кг/м² x %7.4f м² (%s) = %10.5f кг/%s"
              % (sku, sqm_mass, area, label, want, uom_name))
    print("  проставление заняло %.1f с" % (time.time() - started))


# ═══ ШАГ 7 ════════════════════════════════════════════════════════════════
def check_weights_and_variants(plan):
    """Проверка ДО фиксации. Не пройдена — значит отката не потребуется.

    Оба пункта проверяются заново и на своих цифрах, а не «шаг 6 отработал
    без исключений»:

      1. У КАЖДОЙ карточки есть вариант. Грабля из product_template.py
         ::_create_variant_ids: карточка, созданная СРАЗУ с характеристикой,
         получает НОЛЬ вариантов — ветка single_value_lines дописывает
         значение существующим вариантам, а у новой карточки их ещё нет, и
         dynamic новых не создаёт. Карточка без варианта — это карточка без
         артикула (default_code вычисляется от единственного варианта), без
         веса и без склада, и выглядит она в списке совершенно нормально.

      2. Вес каждого варианта равен расчётному. Вес читаем ЗАПРОСОМ, а не
         через ORM: в кэше лежит то, что мы сами только что записали, а в
         колонке — то, что из него получилось после округления по точности
         «Stock Weight». Разница видна только при чтении из базы.

    sys.exit до env.cr.commit() означает откат всей транзакции: заливка либо
    правильная целиком, либо её нет.
    """
    head(7, "Проверка веса и вариантов")
    env.flush_all()  # noqa: F821
    env.invalidate_all()  # noqa: F821

    Tmpl = env["product.template"]  # noqa: F821
    size_attr = env.ref("pmk_bridge.attr_sheet_size")  # noqa: F821
    unit = env.ref("uom.product_uom_unit")  # noqa: F821
    sqm = env.ref("uom.product_uom_square_meter")  # noqa: F821
    by_ident = {r["name"]: r["res_id"] for r in env["ir.model.data"].search_read(  # noqa: F821
        [("module", "=", MODULE), ("model", "=", "product.template"),
         ("name", "like", "product_%")], ["name", "res_id"])}

    want_by_var, group_of, no_variant = {}, {}, []
    for item in plan:
        tmpl = Tmpl.browse(by_ident[item["xmlid"].split(".", 1)[1]])
        variants = tmpl.with_context(active_test=False).product_variant_ids
        if not variants:
            no_variant.append(item["sku"])
            continue
        for var in variants:
            try:
                want_by_var[var.id] = expected_variant_weight(
                    item, tmpl, var, size_attr, unit, sqm)
            except ValueError as exc:
                sys.exit("ОТКАЗ: %s" % exc)
            group_of[var.id] = item["model"]

    print("  карточек в плане %d, вариантов у них %d, карточек БЕЗ варианта %d"
          % (len(plan), len(want_by_var), len(no_variant)))
    if no_variant:
        sys.exit("ОТКАЗ: у %d карточек нет ни одного варианта (%s) — грабля "
                 "_create_variant_ids сработала, фиксировать нельзя"
                 % (len(no_variant), ", ".join(no_variant[:10])))

    env.cr.execute(  # noqa: F821
        "SELECT id, COALESCE(weight, 0) FROM product_product WHERE id = ANY(%s)",
        (list(want_by_var),))
    got = {r[0]: float(r[1]) for r in env.cr.fetchall()}  # noqa: F821

    by_group = {}
    bad, worst, zeroed = [], 0.0, []
    for var_id, want in want_by_var.items():
        have = got.get(var_id)
        if have is None:
            sys.exit("ОТКАЗ: вариант %s пропал между шагами" % var_id)
        # Границы диапазона заводим значением первого варианта, а не нулём:
        # ноль как «минимум по умолчанию» скрыл бы ровно то, что мы ищем —
        # вес, схлопнувшийся в ноль.
        stat = by_group.setdefault(group_of[var_id], [0, have, have])
        stat[0] += 1
        stat[1] = min(stat[1], have)
        stat[2] = max(stat[2], have)
        worst = max(worst, abs(want - have))
        if round(want, 5) != round(have, 5):
            bad.append("вариант %s: ждали %.5f, в базе %.5f" % (var_id, want, have))
        # Отдельно: вес, схлопнувшийся в ноль округлением. Для метизов это не
        # косметика — цена штуки считается как руб/кг x масса штуки, и при
        # массе 0,00 болт становится бесплатным.
        if want > 0 and round(have, 5) == 0.0:
            zeroed.append(var_id)

    for model, label in (("pmk.metal.profile", "прокат"), ("pmk.metal.sheet", "лист"),
                         ("pmk.metal.fastener", "метизы"), ("pmk.paint.coating", "ЛКП")):
        cnt, lo, hi = by_group.get(model, (0, 0.0, 0.0))
        print("      %-8s вариантов %-4d вес от %10.5f до %10.5f" % (label, cnt, lo, hi))
    print("  расхождений %d, максимальное отклонение %.8f кг, весов, "
          "схлопнутых в ноль: %d" % (len(bad), worst, len(zeroed)))
    if bad or zeroed:
        for line in bad[:10]:
            print("      %s" % line)
        sys.exit("ОТКАЗ: вес в базе не сошёлся с расчётным — фиксировать нельзя")


# ═══ ШАГ 8 ════════════════════════════════════════════════════════════════
def short_report(plan):
    """Короткий итог. Полная проверка — отдельным скриптом verify_load.py."""
    head(8, "Итог заливки")
    env.flush_all()  # noqa: F821
    env.cr.execute("""
        SELECT count(*) FROM ir_model_data
         WHERE module = %s AND model = 'product.template' AND name LIKE 'product_%%'
    """, (MODULE,))  # noqa: F821
    print("  карточек привязано к справочнику: %d (в плане %d)"
          % (env.cr.fetchone()[0], len(plan)))  # noqa: F821
    env.cr.execute("SELECT count(*) FROM product_template")  # noqa: F821
    print("  шаблонов в базе всего: %d" % env.cr.fetchone()[0])  # noqa: F821
    env.cr.execute("SELECT count(*) FROM product_product WHERE active")  # noqa: F821
    print("  активных вариантов: %d" % env.cr.fetchone()[0])  # noqa: F821
    env.cr.execute(
        "SELECT count(*) FROM product_product WHERE default_code IS NOT NULL "
        "AND default_code <> ''")  # noqa: F821
    print("  вариантов с артикулом: %d" % env.cr.fetchone()[0])  # noqa: F821


started_all = time.time()
fix_weight_precision()
plan = build_plan()
adopt_existing(plan)
created = sync_products(plan)
attach_attributes(plan, created)
# Вес — ПОСЛЕ характеристик: у листа он считается по габариту, а габарит
# появляется на варианте только вместе с характеристикой.
set_variant_weights(plan)
check_weights_and_variants(plan)
short_report(plan)

print("\n" + SEP)
print("Заливка заняла %.1f с. Фиксируем: без commit следующий запуск увидит"
      % (time.time() - started_all))
print("пустую базу и заведёт всё заново — то есть проверить идемпотентность")
print("будет не на чем. Предохранитель наверху уже доказал, что база — копия.")
print(SEP)
env.cr.commit()  # noqa: F821
print("зафиксировано в базе %s" % env.cr.dbname)  # noqa: F821
print("=== КОНЕЦ ===")
