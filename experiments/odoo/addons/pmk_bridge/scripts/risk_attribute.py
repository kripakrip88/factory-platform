# -*- coding: utf-8 -*-
"""САМОЕ ОПАСНОЕ МЕСТО ЗАЛИВКИ: характеристика на товар, по которому есть склад.

Что проверяем. Марка стали по решению владельца — характеристика
(product.attribute). Повесить её на пустую карточку ничего не стоит. Но четыре
карточки на стенде уже возили металл: по «Трубе профильной 100x100x3» лежит
3621,790 м в шести партиях и прошло 15 движений. Если Odoo на этой операции
уберёт вариант, вместе с ним из отчётов и из подбора уйдёт весь этот остаток.

Скрипт НИЧЕГО НЕ ОСТАВЛЯЕТ В БАЗЕ. Каждый сценарий крутится внутри SAVEPOINT
и откатывается, commit не вызывается ни разу. Поэтому его можно гонять на
копии сколько угодно раз и в любом порядке относительно заливки.

Три сценария на одном и том же товаре:

  A. dynamic, восемь значений СРАЗУ      — как сделал бы любой скрипт «в лоб»;
  B. dynamic, правило одного значения    — сначала одно, потом остальные семь;
  C. always вместо dynamic, восемь сразу — «а если варианты создавать заранее».

Плюс лист (две характеристики сразу) и проверка, что после всех откатов база
осталась ровно такой, какой была.

Запуск: sh /tmp/run_reh.sh <этот файл>
"""

import os
import sys

from odoo.tools.convert import convert_xml_import

REHEARSAL_DBS = {"odoo_rehearsal", "odoo_probe"}
if env.cr.dbname not in REHEARSAL_DBS:  # noqa: F821
    sys.exit("ОТКАЗ: %r не копия. Замер делают на копии." % env.cr.dbname)  # noqa: F821

DATA_DIR = "/tmp/pmk_bridge_data"
MODULE = "pmk_bridge"
SEP = "─" * 78

# Товары замера. Труба — с остатком 3621,790 м и 15 движениями, лист — с
# резервом и двумя характеристиками.
#
# Ищем сначала по артикулу, потом по имени. До заливки артикула у этих карточек
# нет вообще, и опознать их можно только по имени; после заливки имя приведено
# к справочнику («Труба профильная КВАДРАТНАЯ 100x100x3»), зато есть артикул.
# Один и тот же скрипт должен работать по обе стороны заливки — иначе замер
# нельзя повторить и сравнить.
TUBE = ("TPK-100x100x3", "Труба профильная 100x100x3 ГОСТ 8639-82")
SHEET = ("LST-GL-4", "Лист горячекатаный 4 мм ГОСТ 19903-2015")


class Rollback(Exception):
    """Сигнал «сценарий отработал, откатываемся». Не ошибка."""


def head(title):
    print("\n" + SEP)
    print(title)
    print(SEP)


def state(tmpl, when):
    """Печать состояния шаблона: варианты, их метки, остатки, движения.

    Остаток берём запросом по stock_quant, а не полем qty_available: поле
    считается только по АКТИВНЫМ вариантам и на архивном молча даёт ноль —
    то есть ровно в том случае, ради которого затеян замер, оно соврёт.
    """
    tmpl.invalidate_recordset()
    variants = tmpl.with_context(active_test=False).product_variant_ids
    print("  %-22s вариантов %d (активных %d)"
          % (when, len(variants), len(variants.filtered("active"))))
    for v in variants:
        env.cr.execute(  # noqa: F821
            "SELECT COALESCE(SUM(q.quantity), 0), "
            "       (SELECT count(*) FROM stock_move m WHERE m.product_id = %s), "
            "       (SELECT count(*) FROM stock_lot  l WHERE l.product_id = %s) "
            "  FROM stock_quant q "
            "  JOIN stock_location loc ON loc.id = q.location_id "
            " WHERE q.product_id = %s AND loc.usage = 'internal'",
            (v.id, v.id, v.id))
        qty, moves, lots = env.cr.fetchone()  # noqa: F821
        print("      вариант %-5s активен=%-5s артикул=%-16s метки=[%s] "
              "склад=%9.3f движ=%-3s партий=%s"
              % (v.id, v.active, v.default_code or "—",
                 ", ".join(v.product_template_attribute_value_ids.mapped("name")) or "нет",
                 qty, moves, lots))


def ensure_attributes():
    """Характеристики нужны для замера. Если их ещё нет — грузим файл модуля.

    Загрузка тоже идёт внутри общего отката, так что после скрипта их снова
    не будет. Это нарочно: замер не должен готовить среду, для этого есть
    prepare_environment.py.
    """
    if env.ref("pmk_bridge.attr_grade", raise_if_not_found=False):  # noqa: F821
        return "характеристики уже в базе"
    path = os.path.join(DATA_DIR, "product_attribute.xml")
    if not os.path.exists(path):
        sys.exit("ОТКАЗ: нет %s — скопируйте каталог data в контейнер" % path)
    with open(path, "rb") as fp:
        convert_xml_import(env, MODULE, fp, {}, "init", False)  # noqa: F821
    env.flush_all()  # noqa: F821
    return "характеристики загружены из product_attribute.xml"


Tmpl = env["product.template"]  # noqa: F821


def find(code, name):
    """Карточка по артикулу, а если его ещё нет — по имени."""
    found = Tmpl.search([("default_code", "=", code)]) or Tmpl.search([("name", "=", name)])
    if len(found) != 1:
        sys.exit("ОТКАЗ: по артикулу %s и имени «%s» нашлось карточек %d"
                 % (code, name, len(found)))
    return found


tube = find(*TUBE)
sheet = find(*SHEET)
TUBE_NAME, SHEET_NAME = tube.name, sheet.name

head("ИСХОДНОЕ СОСТОЯНИЕ")
print("  " + ensure_attributes())
grade = env.ref("pmk_bridge.attr_grade")  # noqa: F821
size = env.ref("pmk_bridge.attr_sheet_size")  # noqa: F821
st3sp = env.ref("pmk_bridge.attr_grade_st3sp")  # noqa: F821
size_9m2 = env.ref("pmk_bridge.attr_sheet_size_1500x6000")  # noqa: F821
print("  «%s»: %d значений, режим %s" % (grade.name, len(grade.value_ids), grade.create_variant))
print("  товар замера: %s (id %s)" % (TUBE_NAME, tube.id))
state(tube, "ДО")

# Цифры, с которыми будем сверяться после всех откатов.
before = {
    "templates": Tmpl.with_context(active_test=False).search_count([]),
    "variants": env["product.product"].with_context(active_test=False).search_count([]),  # noqa: F821
    "quants": env["stock.quant"].search_count([]),  # noqa: F821
    "attr_lines": env["product.template.attribute.line"].search_count([]),  # noqa: F821
}


def scenario(title, body, only_before_load=False):
    """Прогнать сценарий внутри SAVEPOINT и откатить в любом случае.

    Откат — не «на всякий случай»: сценарий A архивирует вариант с остатком,
    и оставлять такое в базе нельзя даже на копии, иначе следующий сценарий
    померяет уже испорченную карточку.
    """
    if only_before_load and tube.attribute_line_ids:
        print("\n%s\n%s\n%s" % (SEP, title, SEP))
        print("  ПРОПУЩЕН: на трубе уже %d строк характеристик, то есть заливка"
              % len(tube.attribute_line_ids))
        print("  прошла. Этот сценарий вешает ПЕРВУЮ характеристику, и мерить его")
        print("  надо на чистой копии — иначе замер будет про другое.")
        return
    head(title)
    try:
        with env.cr.savepoint():  # noqa: F821
            body()
            raise Rollback
    except Rollback:
        pass
    env.invalidate_all()  # noqa: F821


# ── A. Восемь значений сразу ─────────────────────────────────────────────
def case_a():
    tube.write({"attribute_line_ids": [
        (0, 0, {"attribute_id": grade.id, "value_ids": [(6, 0, grade.value_ids.ids)]})]})
    env.flush_all()  # noqa: F821
    state(tube, "ПОСЛЕ")
    arch = tube.with_context(active_test=False).product_variant_ids.filtered(
        lambda v: not v.active)
    print("  ИТОГ: вариантов в архиве %d, активных %d"
          % (len(arch), len(tube.product_variant_ids)))
    if arch:
        print("  Остаток не исчез из базы — он исчез из системы: архивный вариант")
        print("  не попадает ни в остатки, ни в подбор, ни в отчёты по складу.")


scenario("A. dynamic, ВОСЕМЬ ЗНАЧЕНИЙ СРАЗУ («в лоб»)", case_a, only_before_load=True)


# ── B. Правило одного значения ───────────────────────────────────────────
def case_b():
    tube.write({"attribute_line_ids": [
        (0, 0, {"attribute_id": grade.id, "value_ids": [(6, 0, st3sp.ids)]})]})
    env.flush_all()  # noqa: F821
    state(tube, "ПОСЛЕ 1 ЗНАЧЕНИЯ")
    line = tube.attribute_line_ids.filtered(lambda l: l.attribute_id == grade)
    line.write({"value_ids": [(6, 0, grade.value_ids.ids)]})
    env.flush_all()  # noqa: F821
    state(tube, "ПОСЛЕ ВСЕХ 8")
    alive = tube.product_variant_ids
    print("  ИТОГ: активных вариантов %d, метка=%s"
          % (len(alive),
             ", ".join(alive.product_template_attribute_value_ids.mapped("name"))))


scenario("B. dynamic, ПРАВИЛО ОДНОГО ЗНАЧЕНИЯ (сначала одно, потом семь)",
         case_b, only_before_load=True)


# ── C. always вместо dynamic ─────────────────────────────────────────────
def case_c():
    grade.write({"create_variant": "always"})
    tube.write({"attribute_line_ids": [
        (0, 0, {"attribute_id": grade.id, "value_ids": [(6, 0, grade.value_ids.ids)]})]})
    env.flush_all()  # noqa: F821
    state(tube, "ПОСЛЕ")
    print("  ИТОГ: старый вариант с остатком ушёл в архив, а рядом встали")
    print("  новые пустые. На 721 карточку это %d вариантов вместо %d."
          % (721 * len(grade.value_ids), 721))


scenario("C. create_variant='always', ВОСЕМЬ ЗНАЧЕНИЙ СРАЗУ", case_c,
         only_before_load=True)

# ── D. Лист: две характеристики сразу ────────────────────────────────────
def case_d():
    print("  товар: %s (id %s), единица %s" % (SHEET_NAME, sheet.id, sheet.uom_id.name))
    state(sheet, "ДО")
    for attr, one in ((grade, st3sp), (size, size_9m2)):
        sheet.write({"attribute_line_ids": [
            (0, 0, {"attribute_id": attr.id, "value_ids": [(6, 0, one.ids)]})]})
        env.flush_all()  # noqa: F821
        line = sheet.attribute_line_ids.filtered(lambda l, a=attr: l.attribute_id == a)
        line.write({"value_ids": [(6, 0, attr.value_ids.ids)]})
        env.flush_all()  # noqa: F821
    state(sheet, "ПОСЛЕ ОБЕИХ")
    print("  комбинаций на будущее: %d марок x %d габаритов = %d, "
          "создаются по требованию"
          % (len(grade.value_ids), len(size.value_ids),
             len(grade.value_ids) * len(size.value_ids)))


scenario("D. ЛИСТ: две характеристики по правилу одного значения", case_d,
         only_before_load=True)


# ── E. Второй вариант и артикул ──────────────────────────────────────────
def case_e():
    """Что станет с артикулом карточки, когда появится вторая марка.

    Это не теория: первый же приход 09Г2С создаст второй вариант. Артикул
    шаблона — поле ВЫЧИСЛЯЕМОЕ и СОХРАНЯЕМОЕ (product_template.py, строка 153:
    compute='_compute_default_code', inverse='_set_default_code', store=True).
    Вычисляется оно из ЕДИНСТВЕННОГО варианта, а при двух и более ставится в
    False. То есть артикул с карточки пропадёт сам, без чьего-либо действия.

    Почему это важно именно нам: прайс поставщика сопоставляется по артикулу.
    Если он пропал с карточки и не проставлен на новом варианте, цена ляжет
    мимо или не ляжет вовсе.
    """
    tmpl = tube if tube.attribute_line_ids else sheet
    if not tmpl.attribute_line_ids:
        print("  ПРОПУЩЕН: характеристик ещё нет, второй вариант делать не из чего")
        return
    line = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == grade)
    print("  товар: %s" % tmpl.name)
    print("  ДО:      артикул шаблона=%s, вариантов %d"
          % (tmpl.default_code, len(tmpl.product_variant_ids)))
    other = line.product_template_value_ids.filtered(lambda v: v.name == "09Г2С")
    combination = other
    for other_line in tmpl.attribute_line_ids - line:
        # У листа вторая характеристика обязательна: комбинация без габарита
        # неполная, и вариант по ней не создастся.
        combination |= other_line.product_template_value_ids[0]
    new_variant = tmpl._create_product_variant(combination)
    env.flush_all()  # noqa: F821
    tmpl.invalidate_recordset()
    print("  ПОСЛЕ:   артикул шаблона=%s, вариантов %d"
          % (tmpl.default_code, len(tmpl.product_variant_ids)))
    for v in tmpl.product_variant_ids:
        print("      вариант %-5s артикул=%-16s метки=[%s]"
              % (v.id, v.default_code or "ПУСТО",
                 ", ".join(v.product_template_attribute_value_ids.mapped("name"))))
    print("  ИТОГ: артикул шаблона обнулился сам, новый вариант %s пришёл без"
          % new_variant.id)
    print("  артикула. Утверждённая схема даёт ему %s-09G2S — но проставлять его"
          % (tmpl.product_variant_ids[0].default_code or "<артикул>"))
    print("  некому: в pmk_bridge такого хука пока нет. Это следующая задача,")
    print("  и до неё сопоставление прайса живёт на карточках с одной маркой.")


scenario("E. ВТОРОЙ ВАРИАНТ: что станет с артикулом карточки", case_e)

# ── Проверка, что замер ничего не оставил ────────────────────────────────
head("ПРОВЕРКА: замер ничего не оставил в базе")
after = {
    "templates": Tmpl.with_context(active_test=False).search_count([]),
    "variants": env["product.product"].with_context(active_test=False).search_count([]),  # noqa: F821
    "quants": env["stock.quant"].search_count([]),  # noqa: F821
    "attr_lines": env["product.template.attribute.line"].search_count([]),  # noqa: F821
}
for k in sorted(before):
    print("  %-12s до=%-6d после=%-6d %s"
          % (k, before[k], after[k], "ок" if before[k] == after[k] else "РАСХОЖДЕНИЕ"))
state(tube, "ТРУБА СЕЙЧАС")
print("\n  Ни одного commit в этом скрипте нет: всё, что выше, откачено.")
print("=== КОНЕЦ ===")
