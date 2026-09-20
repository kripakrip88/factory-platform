# -*- coding: utf-8 -*-
"""Контрольный снимок базы: что обязано пережить заливку номенклатуры.

Скрипт НИЧЕГО НЕ ПИШЕТ. Его гоняют дважды — до заливки и после — и сравнивают
вывод построчно. Смысл именно в сравнении: «остатки на месте» без двух
одинаковых столбцов цифр — это не проверка, а надежда.

Что снимаем и почему:

  * веса четырёх спецификаций. Спецификация считает массу по строкам, а строки
    ссылаются на pmk.metal.profile / pmk.metal.sheet ПРЯМО, не через товар.
    Внешние ключи у этих ссылок стоят ON DELETE SET NULL — то есть удаление
    строки справочника не падает с ошибкой, а молча обнуляет ссылку, и вес
    спецификации меняется. Это единственный способ испортить уже посчитанный
    заказ, и ловится он только сверкой чисел;
  * остатки и движения по каждому варианту. Характеристика, навешенная на
    товар с историей, архивирует вариант вместе с остатком (замер — в
    product_attribute.xml). Количество при этом не меняется, поэтому смотреть
    надо и на количество, и на active;
  * партии (stock.lot). Кусок проката = партия, по решению владельца. Партия,
    оставшаяся без варианта, — это потерянный кусок металла на площадке;
  * дубли артикулов. База уникальность default_code НЕ сторожит: в Odoo 19 на
    product_product нет ни unique-индекса, ни _sql_constraints на это поле.
    Два товара с одним артикулом ловятся только запросом.

Запуск: sh /tmp/run_reh.sh <этот файл>
"""

import sys

SEP = "─" * 78


def head(title):
    print("\n" + SEP)
    print(title)
    print(SEP)


print("БАЗА: %s" % env.cr.dbname)  # noqa: F821
if env.cr.dbname == "odoo":  # noqa: F821
    # Снимок читает, но подключаться к живой базе этим раннером нечего: ошибка
    # в имени базы здесь означает ошибку в имени базы и в заливочном скрипте.
    sys.exit("ОТКАЗ: это живая база. Снимок снимают с копии.")

# ── 1. Справочники: сколько строк под перенос ────────────────────────────
head("1. СПРАВОЧНИК pmk_calc")
REFS = (
    ("pmk.metal.profile", "прокат"),
    ("pmk.metal.sheet", "лист"),
    ("pmk.metal.fastener", "метизы"),
    ("pmk.paint.coating", "ЛКП"),
)
imd = env["ir.model.data"]  # noqa: F821
total_rows = 0
for model, label in REFS:
    rows = env[model].search([])  # noqa: F821
    with_xmlid = sum(
        1 for r in rows
        if imd.search_count([("model", "=", model), ("res_id", "=", r.id)]))
    total_rows += len(rows)
    print("  %-22s строк %-4d из них с внешним идентификатором %d"
          % (label, len(rows), with_xmlid))
print("  ИТОГО строк справочника: %d" % total_rows)

# ── 2. Номенклатура ──────────────────────────────────────────────────────
head("2. НОМЕНКЛАТУРА")
Tmpl = env["product.template"].with_context(active_test=False)  # noqa: F821
Prod = env["product.product"].with_context(active_test=False)  # noqa: F821
tmpls = Tmpl.search([])
prods = Prod.search([])
print("  шаблонов: %d (активных %d)" % (len(tmpls), len(tmpls.filtered("active"))))
print("  вариантов: %d (активных %d)" % (len(prods), len(prods.filtered("active"))))
print("  с артикулом: %d, без артикула: %d"
      % (len(prods.filtered("default_code")), len(prods.filtered(lambda p: not p.default_code))))

env.cr.execute("""
    SELECT default_code, count(*) FROM product_product
     WHERE default_code IS NOT NULL AND default_code <> ''
     GROUP BY default_code HAVING count(*) > 1 ORDER BY 2 DESC, 1
""")  # noqa: F821
dups = env.cr.fetchall()  # noqa: F821
print("  ДУБЛИ артикулов: %d %s"
      % (len(dups), "" if not dups else "→ " + ", ".join("%s×%d" % d for d in dups)))

no_categ = tmpls.filtered(lambda t: not t.categ_id)
no_uom = tmpls.filtered(lambda t: not t.uom_id)
print("  без категории: %d, без единицы: %d" % (len(no_categ), len(no_uom)))

for t in tmpls.sorted("id"):
    print("      шаблон %-4s %-46s кат=%-22s ед=%-6s вес=%.4f активен=%s"
          % (t.id, (t.name or "")[:46], (t.categ_id.name or "—")[:22],
             t.uom_id.name, t.weight, t.active))

# ── 3. Спецификации ──────────────────────────────────────────────────────
head("3. СПЕЦИФИКАЦИИ (главная контрольная цифра)")
specs = env["pmk.metal.spec"].search([], order="name")  # noqa: F821
Line = env["pmk.metal.spec.line"]  # noqa: F821
print("  спецификаций: %d" % len(specs))
for s in specs:
    lines = Line.search([("spec_id", "=", s.id)])
    broken = lines.filtered(
        lambda l: not (l.profile_id or l.sheet_id or l.fastener_id or l.paint_id))
    print("      %-10s вес=%12.3f кг  изделий=%-3s деталей=%-4s строк=%-3d "
          "битых ссылок=%d"
          % (s.name, s.total_weight, s.total_products, s.total_details,
             len(lines), len(broken)))
    if broken:
        print("          СТРОКИ БЕЗ ССЫЛКИ НА СОРТАМЕНТ: %s"
              % ", ".join("id %s «%s»" % (l.id, l.detail_name) for l in broken))
print("  строк спецификаций всего: %d" % Line.search_count([]))
print("  изделий в спецификациях:  %d"
      % env["pmk.metal.spec.product"].search_count([]))  # noqa: F821

# ── 4. Склад ─────────────────────────────────────────────────────────────
head("4. СКЛАД: остатки, движения, партии")
Quant = env["stock.quant"]  # noqa: F821
Move = env["stock.move"]  # noqa: F821
Lot = env["stock.lot"]  # noqa: F821
print("  квантов: %d, движений: %d, партий: %d"
      % (Quant.search_count([]), Move.search_count([]), Lot.search_count([])))

env.cr.execute("""
    SELECT p.id, COALESCE(p.default_code, '—'), t.name->>'en_US', p.active,
           COALESCE(SUM(q.quantity), 0), COALESCE(SUM(q.reserved_quantity), 0),
           (SELECT count(*) FROM stock_move m WHERE m.product_id = p.id),
           (SELECT count(*) FROM stock_lot  l WHERE l.product_id = p.id)
      FROM product_product p
      JOIN product_template t ON t.id = p.product_tmpl_id
      LEFT JOIN stock_quant q ON q.product_id = p.id
       AND q.location_id IN (SELECT id FROM stock_location WHERE usage = 'internal')
     GROUP BY p.id, p.default_code, t.name, p.active
     ORDER BY p.id
""")  # noqa: F821
for pid, code, name, active, qty, res, moves, lots in env.cr.fetchall():  # noqa: F821
    print("      вариант %-4s %-14s %-38s активен=%-5s склад=%11.3f "
          "резерв=%8.3f движ=%-3s партий=%s"
          % (pid, code, (name or "")[:38], active, qty, res, moves, lots))

print("  партии поимённо:")
# ГРАБЛЯ: сначала ВЫБИРАЕМ всё одним запросом и только потом печатаем. Если
# обратиться к lot.product_id прямо в аргументах print, ORM пойдёт в базу тем
# же курсором, результат предыдущего execute пропадёт, и fetchone вернёт None.
env.cr.execute("""
    SELECT l.id, l.name, p.id, COALESCE(p.default_code, 'без артикула'),
           COALESCE((SELECT SUM(q.quantity) FROM stock_quant q WHERE q.lot_id = l.id), 0)
      FROM stock_lot l JOIN product_product p ON p.id = l.product_id
     ORDER BY l.id
""")  # noqa: F821
for lot_id, lot_name, pid, code, qty in env.cr.fetchall():  # noqa: F821
    print("      партия %-4s %-20s товар %-4s (%-14s) остаток=%.3f"
          % (lot_id, lot_name, pid, code, qty))

# ── 5. Среда под номенклатуру ────────────────────────────────────────────
head("5. СРЕДА: категории, характеристики, единицы")
Categ = env["product.category"]  # noqa: F821
Attr = env["product.attribute"]  # noqa: F821
print("  категорий: %d" % Categ.search_count([]))
print("  характеристик: %d (значений: %d)"
      % (Attr.search_count([]), env["product.attribute.value"].search_count([])))  # noqa: F821
for a in Attr.search([]):
    print("      %-16s значений %-3d режим=%s"
          % (a.name, len(a.value_ids), a.create_variant))
uoms = env["uom.uom"].with_context(active_test=False).search([])  # noqa: F821
print("  единиц: %d, из них с кодом ОКЕИ: %d"
      % (len(uoms), len(uoms.filtered(lambda u: u.okei))))
print("  записей ir.model.data модуля pmk_bridge: %d"
      % imd.search_count([("module", "=", "pmk_bridge")]))

print("\n" + SEP)
print("Снимок снят. Ничего не записано: транзакцию odoo shell откатит сам.")
print("=== КОНЕЦ ===")  # маркер для раннера: без него он покажет stderr целиком
print(SEP)
