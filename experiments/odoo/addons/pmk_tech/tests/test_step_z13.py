# -*- coding: utf-8 -*-
"""Совместная раскладка и «Листов по факту» (разбор UX, шаг З-13), pmk_tech.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные —
данные шага З-4 (Z4Common: лист 2 мм, 14 130 ₽ за лист 1500×6000).

Пример прогона Кытмановой: П-полоса 120×3000 ×617 и Z-полоса 560×3000 ×265
из одного листа. Раздельно 93 листа, вместе 76.

Что ловим:
  • технический расчёт получает группы раскладки расчёта КП (листы, режим,
    ссылки деталей), плашки «Раскладка устарела» нет;
  • «Заявка на металл» берёт листы ГРУППЫ (76, не 93 и не дважды);
  • «Листов по факту» перекрывает черновик в заявке — только деталей своей
    группы: «больше листа» и добавленная после числа — по весу сверху, с
    заметкой «по весу»; запись — в ленте;
    после заявки — плашка «Состав изменился после заявки» (черновик) и
    «Расходится с заявкой» (подтверждённая), как в З-4;
  • у расчёта КП поле на сбор не влияет и колонки нет;
  • «Разложить листы» число инженера не стирает и напоминает о нём.
"""
import math

from lxml import etree

from odoo import Command
from odoo.tests import tagged

from .test_step_z4 import Z4Common

SHEET = "Лист 2 мм (тест З-4)"
SHEET_KG = 15.7 * 1.5 * 6.0     # лист 2 мм 1500×6000 (Z4Common), кг


@tagged("post_install", "-at_install")
class TestStepZ13(Z4Common):

    def _flow_strips(self, extra=()):
        deal = self._deal()
        spec = self._spec(deal, products=[], product_ids=[Command.create({
            "name": "Полосы (тест З-13)", "qty": 1, "price_customer_unit": 900000.0,
            "line_ids": [
                Command.create({"calc_mode": "sheet", "detail_name": "П-полоса",
                                "sheet_id": self.sheet.id, "a_mm": 120.0, "b_mm": 3000.0,
                                "qty": 617}),
                Command.create({"calc_mode": "sheet", "detail_name": "Z-полоса",
                                "sheet_id": self.sheet.id, "a_mm": 560.0, "b_mm": 3000.0,
                                "qty": 265}),
            ] + [Command.create(dict({"calc_mode": "sheet", "sheet_id": self.sheet.id}, **vals))
                 for vals in extra],
        })])
        spec.action_draft_layout()
        spec._pmk_kp_move_stage(deal)
        order = self._invoices(deal)
        self.assertEqual(len(order), 1, "Посылка: счёт выставлен.")
        return deal, spec, order

    def _notes(self, spec):
        spec.invalidate_recordset(["message_ids"])
        return " ".join(str(m.body) for m in spec.message_ids)

    def test_tech_gets_groups_and_request_takes_group_sheets(self):
        _deal, spec, order = self._flow_strips()
        group_kp = spec.layout_group_ids
        self.assertEqual((group_kp.sheets, group_kp.sheets_separate, group_kp.mode),
                         (76, 93, "joint"), "Посылка: совместная раскладка КП.")
        tech = self._tech(order)
        group = tech.layout_group_ids
        self.assertEqual(len(group), 1, "Группа перенесена в технический.")
        self.assertNotEqual(group, group_kp, "Своя запись, не общая с КП.")
        self.assertEqual((group.sheets, group.sheets_separate, group.mode, group.state),
                         (76, 93, "joint", "ok"))
        self.assertEqual(group.line_ids, tech.sheet_line_ids)
        self.assertEqual(sorted(tech.sheet_line_ids.mapped("layout_sheets")),
                         sorted(spec.sheet_line_ids.mapped("layout_sheets")))
        self.assertFalse(tech.layout_stale)
        self.assertEqual(group_kp.line_ids, spec.sheet_line_ids, "Группа КП цела.")

        self._request(tech)
        po = self._requests(tech).filtered(lambda o: o.partner_id == self.supplier)
        plate = self._line(po, SHEET)
        self.assertEqual(plate.product_qty, 76.0, "Листы группы — не 93 и не дважды.")
        self._signals(tech)
        self.assertNotIn("по весу", tech.pmk_request_warn_text or "",
                         "Доля детали может быть нулём — это не «без раскладки».")

    def test_fact_overrides_draft_and_shows_drift(self):
        _deal, spec, order = self._flow_strips()
        tech = self._tech(order)
        group = tech.layout_group_ids
        self._request(tech)
        po = self._requests(tech).filtered(lambda o: o.partner_id == self.supplier)
        self.assertEqual(self._line(po, SHEET).product_qty, 76.0)

        # Инженер вписал число из CypCut — как присылает форма.
        tech.with_user(self.engineer).write({
            "layout_group_ids": [Command.update(group.id, {"pmk_sheets_fact": 74})]})
        self.assertEqual(group.pmk_sheets_fact, 74)
        self.assertEqual(group.sheets, 76, "Черновик рядом не меняется.")
        self.assertIn("Листов по факту", self._notes(tech))
        self._signals(tech)
        self.assertTrue(tech.pmk_request_stale, "Черновик заявки: «состав изменился».")

        self._request(tech)
        plate = self._line(po, SHEET)
        self.assertEqual(plate.product_qty, 74.0, "Заявка берёт «Листов по факту».")
        self.assertIn("по факту инженера", self._notes(tech))
        self._signals(tech)
        self.assertFalse(tech.pmk_request_stale)
        # «Металл в заявку: по КП → сейчас» — листами: 76 и 74 по 141,3 кг.
        self.assertEqual(tech.pmk_kp_compare_weight, "10,739 → 10,456")

        # Подтверждённую заявку не трогаем — расхождение плашкой (как в З-4).
        po.button_confirm()
        group.write({"pmk_sheets_fact": 72})
        self._request(tech)
        self.assertEqual(self._line(po, SHEET).product_qty, 74.0)
        self._signals(tech)
        diff = tech.pmk_request_diff_text or ""
        self.assertIn(po.name, diff)
        self.assertIn("74 листа, у инженера 72 листа", diff)

        # Сняли число — снова черновик.
        group.write({"pmk_sheets_fact": 0})
        self.assertIn("Листов по факту снято", self._notes(tech))
        rows, _notes = tech._pmk_metal_rows()
        sheet_row = [row for row in rows if row["mode"] == "sheet"][0]
        self.assertEqual(sheet_row["qty"], 76.0)

    def test_relayout_keeps_fact(self):
        _deal, _spec, order = self._flow_strips()
        tech = self._tech(order)
        group = tech.layout_group_ids
        group.write({"pmk_sheets_fact": 74})
        strip = tech.sheet_line_ids.filtered(lambda l: l.detail_name == "Z-полоса")
        strip.write({"qty": 266})
        self.assertEqual(group.state, "none", "Черновик погас…")
        self.assertEqual(group.pmk_sheets_fact, 74, "…число инженера — нет.")
        self.assertTrue(tech.layout_stale)
        rows, _notes = tech._pmk_metal_rows()
        self.assertEqual([row["qty"] for row in rows if row["mode"] == "sheet"], [74.0],
                         "Устарела — заявка всё равно по числу инженера, не «по весу».")
        tech.action_draft_layout()
        self.assertEqual(tech.layout_group_ids, group, "Та же группа — число на месте.")
        self.assertEqual(group.pmk_sheets_fact, 74)
        self.assertIn("Листов по факту оставлено", self._notes(tech))
        self.assertIn("сверьте с CypCut", self._notes(tech))

    def test_kp_spec_ignores_fact(self):
        _deal, spec, _order = self._flow_strips()
        spec.layout_group_ids.write({"pmk_sheets_fact": 10})
        self.assertEqual(spec._pmk_sheets_fact_map(), {})
        rows, _notes = spec._pmk_metal_rows()
        self.assertEqual([row["qty"] for row in rows if row["mode"] == "sheet"], [76.0])

    def test_fact_not_negative(self):
        _deal, _spec, order = self._flow_strips()
        tech = self._tech(order)
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            tech.layout_group_ids.write({"pmk_sheets_fact": -1})

    def test_fact_column_only_in_tech(self):
        views = self.env["pmk.metal.spec"].get_views([(False, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        table = arch.xpath("//field[@name='layout_group_ids']/list")[0]
        names = [node.get("name") for node in table.findall("field")]
        self.assertEqual(names[names.index("sheets") + 1], "pmk_sheets_fact")
        fact = table.find("field[@name='pmk_sheets_fact']")
        self.assertEqual(fact.get("column_invisible"), "parent.pmk_kind != 'tech'")
        self.assertNotEqual(fact.get("readonly"), "1", "Инженер вписывает число в строке.")
        self.assertEqual(fact.get("string"), "Листов по факту")

    # ─── Число инженера покрывает только детали своей группы (доработка) ──
    def _sheet_row(self, tech):
        rows, notes = tech._pmk_metal_rows()
        sheet_rows = [row for row in rows if row["mode"] == "sheet"]
        self.assertEqual(len(sheet_rows), 1)
        return sheet_rows[0], notes

    def test_fact_keeps_by_weight_for_too_big(self):
        """Деталь «больше листа» CypCut не раскладывал: число инженера — за
        группу, металл под большую деталь — по весу сверху, и заметка «по
        весу» не пропадает."""
        _deal, _spec, order = self._flow_strips(extra=[
            {"detail_name": "Огромная", "a_mm": 1600.0, "b_mm": 7000.0, "qty": 1}])
        tech = self._tech(order)
        huge = tech.sheet_line_ids.filtered(lambda l: l.detail_name == "Огромная")
        self.assertEqual(huge.layout_state, "too_big", "Посылка.")
        self.assertEqual(tech.layout_group_ids.sheets, 76)
        by_weight = math.ceil(huge.weight_total / SHEET_KG - 1e-6)
        self.assertGreater(by_weight, 0)
        row, notes = self._sheet_row(tech)
        self.assertEqual(row["qty"], 76.0 + by_weight, "Без числа: черновик + по весу.")

        tech.layout_group_ids.write({"pmk_sheets_fact": 72})
        row, notes = self._sheet_row(tech)
        self.assertEqual(row["qty"], 72.0 + by_weight,
                         "Число инженера заменяет черновик, а не металл большой детали.")
        self.assertEqual(row["fact"], 72)
        self.assertEqual(row["unlaid"], 1)
        self.assertTrue(notes["unlaid"], "Заметка «по весу» остаётся.")
        self._signals(tech)
        self.assertIn("по весу", tech.pmk_request_warn_text or "")

    def test_detail_added_after_fact_goes_by_weight(self):
        """Деталь того же листа, добавленная после числа инженера, в группе
        не состоит — CypCut её не видел: по весу сверху, с заметкой."""
        _deal, _spec, order = self._flow_strips()
        tech = self._tech(order)
        tech.layout_group_ids.write({"pmk_sheets_fact": 74})
        tech.product_ids.write({"line_ids": [Command.create({
            "calc_mode": "sheet", "detail_name": "Косынка", "sheet_id": self.sheet.id,
            "a_mm": 500.0, "b_mm": 500.0, "qty": 10})]})
        added = tech.sheet_line_ids.filtered(lambda l: l.detail_name == "Косынка")
        self.assertFalse(added.layout_group_id, "Посылка: новая деталь вне группы.")
        by_weight = math.ceil(added.weight_total / SHEET_KG - 1e-6)
        row, notes = self._sheet_row(tech)
        self.assertEqual(row["qty"], 74.0 + by_weight)
        self.assertTrue(notes["unlaid"])
        self.assertTrue(tech.layout_stale, "И плашка «Раскладка устарела».")

    def test_fact_sheet_changed_detail_leaves_group(self):
        """Деталь перевели на другой лист — она ушла из группы с числом:
        число инженера её больше не покрывает."""
        _deal, _spec, order = self._flow_strips()
        tech = self._tech(order)
        group = tech.layout_group_ids
        group.write({"pmk_sheets_fact": 74})
        line = tech.sheet_line_ids.filtered(lambda l: l.detail_name == "Z-полоса")
        self.assertEqual(tech._pmk_fact_group(line, "1500x6000", {group.id: 74}), group)
        line.write({"layout_sheet_size": "1500x3000"})
        self.assertEqual(line.layout_group_id, group, "Ссылка остаётся до раскладки…")
        self.assertIsNone(tech._pmk_fact_group(line, "1500x3000", {group.id: 74}),
                          "…но габарит другой — число группы её не покрывает.")
