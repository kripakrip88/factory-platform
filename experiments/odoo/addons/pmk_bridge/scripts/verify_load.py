# -*- coding: utf-8 -*-
"""Приёмка заливки: семь пунктов, каждый — цифрой. Скрипт ничего не пишет.

Проверяется не «скрипт отработал без ошибок», а что получилось в базе. Odoo
почти ничего из этого не сторожит сам: уникальности артикула в схеме нет,
массу он молча округлит по настройке точности, а единицу листа поменяет,
переименовав квадратные метры в штуки без пересчёта.

Контрольные цифры «до» зашиты константами ниже. Они сняты
scripts/control_numbers.py на свежей копии дампа odoo_20260920_102418.dump
ДО заливки: сверять «после» не с чем, если «до» нигде не записано.

Запуск: sh /tmp/run_reh.sh <этот файл>
"""

import sys

REHEARSAL_DBS = ("odoo_rehearsal", "odoo_probe")
if env.cr.dbname not in REHEARSAL_DBS:  # noqa: F821
    sys.exit("ОТКАЗ: %r не копия." % env.cr.dbname)  # noqa: F821

MODULE = "pmk_bridge"
SEP = "─" * 78

# ── Контрольные цифры ДО заливки ────────────────────────────────────────
SPEC_WEIGHT_BEFORE = {
    "СМ-00015": 89.564, "СМ-00016": 4720.172,
    "СМ-00021": 1681.868, "СМ-00022": 442.428,
}
SPEC_LINES_BEFORE = 29
SPEC_PRODUCTS_BEFORE = 8
QUANTS_BEFORE, MOVES_BEFORE, LOTS_BEFORE = 21, 21, 7
# товар -> (остаток на внутренних складах, движений, партий)
STOCK_BEFORE = {
    "TPK-100x100x3": (3621.790, 15, 6),   # шаблон 9, труба профильная
    "UGR-63x63x5": (0.0, 0, 0),           # шаблон 10, уголок
    "LST-GL-4": (3.150, 6, 1),            # шаблон 11, лист 4 мм
    "LST-GL-8": (0.0, 0, 0),              # шаблон 12, лист 8 мм
}
# Ожидаемые единицы хранения по группам — решения владельца, а не догадка.
UOM_EXPECTED = {
    "pmk.metal.profile": ("uom.product_uom_meter", 665),
    "pmk.metal.sheet": ("uom.product_uom_unit", 56),
    "pmk.metal.fastener": ("uom.product_uom_unit", 25),
    "pmk.paint.coating": ("uom.product_uom_kgm", 6),
}
MASS_FIELD = {
    "pmk.metal.profile": "mass_per_meter",
    "pmk.metal.sheet": "mass_per_sqm",
    "pmk.metal.fastener": "weight_kg",
}

verdicts = []


def check(num, title, ok, detail):
    verdicts.append((num, ok, title, detail))
    print("\n%s\nПУНКТ %s. %s\n%s" % (SEP, num, title, SEP))
    print("  %s" % detail)
    print("  ВЕРДИКТ: %s" % ("ПРОЙДЕН" if ok else "НЕ ПРОЙДЕН"))


# Карта «карточка -> строка справочника»: внешний идентификатор карточки это
# внешний идентификатор строки справочника с приставкой product_.
imd = env["ir.model.data"]  # noqa: F821
cards = {}      # ident справочника -> res_id карточки
for r in imd.search_read([("module", "=", MODULE), ("model", "=", "product.template"),
                          ("name", "like", "product_%")], ["name", "res_id"]):
    cards[r["name"][len("product_"):]] = r["res_id"]

ref_rows = {}   # (модель, ident) -> запись справочника
for model in ("pmk.metal.profile", "pmk.metal.sheet",
              "pmk.metal.fastener", "pmk.paint.coating"):
    recs = env[model].search([])  # noqa: F821
    for rec_id, xmlid in recs.get_external_id().items():
        if xmlid:
            ref_rows[xmlid.split(".", 1)[1]] = (model, env[model].browse(rec_id))  # noqa: F821

# ── 1. Масса ────────────────────────────────────────────────────────────
Tmpl = env["product.template"]  # noqa: F821
bad_mass, checked_mass, worst = [], 0, 0.0
paints = 0
for ident, tmpl_id in cards.items():
    model, rec = ref_rows[ident]
    tmpl = Tmpl.browse(tmpl_id)
    if model == "pmk.paint.coating":
        # У покрытия массы в справочнике нет — там расход кг/м². Единица
        # хранения кг, поэтому масса килограмма равна единице по определению.
        paints += 1
        if round(tmpl.weight, 5) != 1.0:
            bad_mass.append("%s ЛКП вес %s вместо 1.0" % (tmpl.default_code, tmpl.weight))
        continue
    want = rec[MASS_FIELD[model]]
    got = tmpl.weight
    checked_mass += 1
    worst = max(worst, abs(want - got))
    if round(want, 5) != round(got, 5):
        bad_mass.append("%s: в справочнике %.5f, в карточке %.5f"
                        % (tmpl.default_code, want, got))
check(1, "Масса карточки равна массе строки справочника",
      not bad_mass,
      "сверено %d карточек (прокат+лист+метизы) + %d ЛКП; расхождений %d; "
      "максимальное отклонение %.8f кг%s"
      % (checked_mass, paints, len(bad_mass), worst,
         "" if not bad_mass else "\n      " + "\n      ".join(bad_mass[:10])))

# ── 2. Дубли артикулов ──────────────────────────────────────────────────
# Уникальность default_code в Odoo не сторожит ни база, ни ORM: ни unique-
# индекса, ни _sql_constraints на это поле нет. Проверяем запросом.
env.cr.execute("""
    SELECT default_code, count(*) FROM product_product
     WHERE default_code IS NOT NULL AND default_code <> ''
     GROUP BY default_code HAVING count(*) > 1
""")  # noqa: F821
dups = env.cr.fetchall()  # noqa: F821
env.cr.execute("""
    SELECT count(*) FROM product_product
     WHERE default_code IS NOT NULL AND default_code <> ''
""")  # noqa: F821
with_code = env.cr.fetchone()[0]  # noqa: F821
env.cr.execute("SELECT count(*) FROM product_product WHERE default_code ~ '[^ -~]'")  # noqa: F821
non_ascii = env.cr.fetchone()[0]  # noqa: F821
check(2, "Дублей артикулов нет",
      not dups and non_ascii == 0,
      "вариантов с артикулом %d, дублей %d, артикулов с не-ASCII символами %d%s"
      % (with_code, len(dups), non_ascii,
         "" if not dups else " → " + ", ".join("%s×%d" % d for d in dups)))

# ── 3. Единицы измерения ────────────────────────────────────────────────
uom_report, uom_ok = [], True
for model, (uom_xmlid, expected) in UOM_EXPECTED.items():
    uom = env.ref(uom_xmlid)  # noqa: F821
    ids = [cards[i] for i, (m, _r) in ref_rows.items() if m == model and i in cards]
    tmpls = Tmpl.browse(ids)
    right = tmpls.filtered(lambda t, u=uom: t.uom_id == u)
    wrong = tmpls - right
    uom_report.append("%-22s карточек %-3d в «%s» %-3d, в других %d%s"
                      % (model, len(tmpls), uom.name, len(right), len(wrong),
                         "" if not wrong else " → " + ", ".join(
                             "%s(%s)" % (t.default_code, t.uom_id.name) for t in wrong)))
    if len(tmpls) != expected or wrong:
        uom_ok = False
check(3, "Единицы: прокат в метрах, лист в штуках, метизы в штуках, ЛКП в кг",
      uom_ok, "\n      ".join(uom_report))

# ── 4. Веса спецификаций ────────────────────────────────────────────────
spec_report, spec_ok = [], True
for spec in env["pmk.metal.spec"].search([], order="name"):  # noqa: F821
    was = SPEC_WEIGHT_BEFORE.get(spec.name)
    now = spec.total_weight
    same = was is not None and round(was, 3) == round(now, 3)
    spec_ok = spec_ok and same
    spec_report.append("%-10s было %10.3f  стало %10.3f  %s"
                       % (spec.name, was if was is not None else -1, now,
                          "совпало" if same else "РАСХОЖДЕНИЕ"))
lines_now = env["pmk.metal.spec.line"].search_count([])  # noqa: F821
prods_now = env["pmk.metal.spec.product"].search_count([])  # noqa: F821
spec_ok = spec_ok and lines_now == SPEC_LINES_BEFORE and prods_now == SPEC_PRODUCTS_BEFORE
spec_report.append("строк спецификаций было %d, стало %d; изделий было %d, стало %d"
                   % (SPEC_LINES_BEFORE, lines_now, SPEC_PRODUCTS_BEFORE, prods_now))
# Ссылки строк на сортамент: удаление дубля листа могло их обнулить молча —
# внешний ключ стоит ON DELETE SET NULL.
env.cr.execute("""
    SELECT count(*) FROM pmk_metal_spec_line
     WHERE profile_id IS NULL AND sheet_id IS NULL
       AND fastener_id IS NULL AND paint_id IS NULL
""")  # noqa: F821
spec_report.append("строк без ссылки на сортамент: %d (было 2: id 62 и 63, "
                   "они такими и лежали в дампе)" % env.cr.fetchone()[0])  # noqa: F821
check(4, "Веса четырёх спецификаций совпали до третьего знака",
      spec_ok, "\n      ".join(spec_report))

# ── 5. Склад ────────────────────────────────────────────────────────────
stock_report, stock_ok = [], True
for code, (qty_was, moves_was, lots_was) in sorted(STOCK_BEFORE.items()):
    env.cr.execute("""
        SELECT p.id, p.active,
               COALESCE((SELECT SUM(q.quantity) FROM stock_quant q
                          JOIN stock_location l ON l.id = q.location_id
                         WHERE q.product_id = p.id AND l.usage = 'internal'), 0),
               (SELECT count(*) FROM stock_move m WHERE m.product_id = p.id),
               (SELECT count(*) FROM stock_lot  s WHERE s.product_id = p.id)
          FROM product_product p WHERE p.default_code = %s
    """, (code,))  # noqa: F821
    rows = env.cr.fetchall()  # noqa: F821
    if len(rows) != 1:
        stock_report.append("%-16s вариантов с таким артикулом %d — сверять нечего"
                            % (code, len(rows)))
        stock_ok = False
        continue
    pid, active, qty, moves, lots = rows[0]
    same = (round(float(qty), 3) == round(qty_was, 3)
            and moves == moves_was and lots == lots_was and active)
    stock_ok = stock_ok and same
    stock_report.append(
        "%-16s вариант %-4s активен=%-5s склад %10.3f (было %10.3f)  "
        "движ %2d (было %2d)  партий %d (было %d)  %s"
        % (code, pid, active, qty, qty_was, moves, moves_was, lots, lots_was,
           "ок" if same else "РАСХОЖДЕНИЕ"))

for label, model, was in (("квантов", "stock.quant", QUANTS_BEFORE),
                          ("движений", "stock.move", MOVES_BEFORE),
                          ("партий", "stock.lot", LOTS_BEFORE)):
    now = env[model].search_count([])  # noqa: F821
    stock_ok = stock_ok and now == was
    stock_report.append("%-9s было %d, стало %d %s"
                        % (label, was, now, "ок" if now == was else "РАСХОЖДЕНИЕ"))
# Партия, оставшаяся без товара, — это потерянный кусок металла на площадке.
env.cr.execute("""
    SELECT count(*) FROM stock_lot l
     LEFT JOIN product_product p ON p.id = l.product_id WHERE p.id IS NULL
""")  # noqa: F821
orphan_lots = env.cr.fetchone()[0]  # noqa: F821
stock_ok = stock_ok and orphan_lots == 0
stock_report.append("партий без товара: %d" % orphan_lots)
check(5, "Партии и движения на месте и на том же товаре",
      stock_ok, "\n      ".join(stock_report))

# ── 6. Категория и единица у всех ───────────────────────────────────────
ours = Tmpl.browse(list(cards.values()))
no_categ = ours.filtered(lambda t: not t.categ_id)
no_uom = ours.filtered(lambda t: not t.uom_id)
all_tmpl = Tmpl.with_context(active_test=False).search([])
alien = all_tmpl - ours
check(6, "Товаров без категории или без единицы — 0",
      not no_categ and not no_uom,
      "наших карточек %d: без категории %d, без единицы %d\n"
      "      чужих карточек в базе %d (%s) — не наши, в приёмку не входят"
      % (len(ours), len(no_categ), len(no_uom), len(alien),
         ", ".join("«%s»" % t.name for t in alien) or "нет"))

# ── 7. Карточка жива и опознаётся ───────────────────────────────────────
env.cr.execute("""
    SELECT count(*) FROM product_template t
     WHERE t.id = ANY(%s)
       AND NOT EXISTS (SELECT 1 FROM product_product p
                        WHERE p.product_tmpl_id = t.id AND p.active)
""", (list(cards.values()),))  # noqa: F821
no_variant = env.cr.fetchone()[0]  # noqa: F821
env.cr.execute("""
    SELECT count(*) FROM product_product p
     WHERE p.product_tmpl_id = ANY(%s) AND p.active
       AND (p.default_code IS NULL OR p.default_code = '')
""", (list(cards.values()),))  # noqa: F821
no_code = env.cr.fetchone()[0]  # noqa: F821
env.cr.execute("""
    SELECT count(*) FROM product_template t
     WHERE t.id = ANY(%s) AND (t.default_code IS NULL OR t.default_code = '')
""", (list(cards.values()),))  # noqa: F821
tmpl_no_code = env.cr.fetchone()[0]  # noqa: F821
lines = env["product.template.attribute.line"].search_count(  # noqa: F821
    [("product_tmpl_id", "in", list(cards.values()))])
check(7, "У каждой карточки жив вариант и на нём артикул",
      no_variant == 0 and no_code == 0,
      "карточек без активного варианта %d; активных вариантов без артикула %d; "
      "шаблонов без артикула %d; строк характеристик %d"
      % (no_variant, no_code, tmpl_no_code, lines))

print("\n" + SEP)
print("ИТОГ ПРИЁМКИ")
print(SEP)
for num, ok, title, _d in verdicts:
    print("  %s %-62s %s" % (num, title[:62], "ПРОЙДЕН" if ok else "НЕ ПРОЙДЕН"))
failed = [v for v in verdicts if not v[1]]
print("  пунктов пройдено: %d из %d" % (len(verdicts) - len(failed), len(verdicts)))
print("=== КОНЕЦ ===")
