# -*- coding: utf-8 -*-
"""Совместная раскладка листа (разбор UX, шаг З-13, 09.10.2026), pmk_calc.

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk_z13_test -i pmk_tech --test-enable \\
         --test-tags /pmk_calc,/pmk_bridge,/pmk_tech --stop-after-init --http-port 8099

Чистые функции укладки — test_sheet_group.py (голым питоном). Здесь — поля
расчёта и деталей, группы «Лист раскладки», история, отпечаток «Раскладка
устарела» (шаг 56) и собранная разметка вкладки «Раскладка».

Пример — прогон Кытмановой (СМ-00037): лист 3 мм 1500×6000, П-полоса
120×3000 ×617 и Z-полоса 560×3000 ×265. Раздельно 93 листа, вместе 76.
"""
import html

from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged

from ..models.sheeting import plan_sheets

NB = " "


def plain(text):
    return html.unescape(str(text or "")).replace(NB, " ")


@tagged("post_install", "-at_install")
class TestStepZ13Layout(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Sheet = cls.env["pmk.metal.sheet"]
        cls.sheet3 = Sheet.create({"sheet_type": "Гладкий (тест З-13)", "thickness_mm": 3.0,
                                   "gost": "ГОСТ тест", "mass_per_sqm": 23.55})
        cls.sheet4 = Sheet.create({"sheet_type": "Гладкий (тест З-13)", "thickness_mm": 4.0,
                                   "gost": "ГОСТ тест", "mass_per_sqm": 31.4})
        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    def _spec(self, lines, qty=1):
        return self.Spec.create({"product_ids": [Command.create({
            "name": "Полосы (тест З-13)", "qty": qty,
            "line_ids": [Command.create(dict({"calc_mode": "sheet",
                                              "sheet_id": self.sheet3.id}, **vals))
                         for vals in lines],
        })]})

    def _kytmanova(self):
        spec = self._spec([
            {"detail_name": "П-полоса", "a_mm": 120.0, "b_mm": 3000.0, "qty": 617},
            {"detail_name": "Z-полоса", "a_mm": 560.0, "b_mm": 3000.0, "qty": 265},
        ])
        lines = spec.sheet_line_ids.sorted("detail_name")
        return spec, lines.filtered(lambda l: l.detail_name == "П-полоса"), \
            lines.filtered(lambda l: l.detail_name == "Z-полоса")

    # ─── Совместная раскладка ────────────────────────────────────────────
    def test_kytmanova_joint_group(self):
        spec, strip_p, strip_z = self._kytmanova()
        self.assertTrue(spec.action_draft_layout())
        group = spec.layout_group_ids
        self.assertEqual(len(group), 1, "Один лист, один габарит — одна группа.")
        self.assertEqual(group.sheet_id, self.sheet3)
        self.assertEqual(group.sheet_size, "1500x6000")
        self.assertEqual(group.line_count, 2)
        self.assertEqual(group.line_ids, strip_p | strip_z)
        self.assertEqual(group.sheets_separate, 93, "Раздельно — как было: 26 + 67.")
        self.assertLessEqual(group.sheets, 80)
        self.assertEqual(group.sheets, 76)
        self.assertEqual(group.mode, "joint")
        self.assertEqual(group.state, "ok")
        self.assertGreater(group.utilization_pct, 95.0)
        self.assertEqual(group.use_level, "ok")
        self.assertIn("560×3000 — 4", group.scheme)
        self.assertEqual(group.parts_label, "120×3000 ×617, 560×3000 ×265")
        self.assertIn("1500 × 6000", group.display_name)

        # Доли строк: сумма = листы группы (итог вкладки и заявка не
        # задваивают); «В листе» — своё, «если резать отдельно».
        self.assertEqual(strip_p.layout_sheets + strip_z.layout_sheets, 76)
        self.assertEqual(sum(spec.sheet_line_ids.mapped("layout_sheets")), group.sheets)
        self.assertEqual(strip_p.layout_per_sheet, 24)
        self.assertEqual(strip_z.layout_per_sheet, 4)
        self.assertEqual(strip_p.layout_state, "ok")
        self.assertEqual(strip_z.layout_group_id, group)
        self.assertEqual(strip_p.layout_group_note, "560×3000")
        self.assertEqual(strip_z.layout_group_note, "120×3000")
        self.assertTrue(strip_p.layout_joint and strip_z.layout_joint)
        self.assertEqual(group.mode_label, "вместе")
        self.assertFalse(spec.layout_stale)
        self.assertFalse(spec.layout_legacy)

        body = plain(spec.message_ids[:1].body)
        self.assertIn("Раскладка листов (черновик): купить 76 листов (раздельно было 93)", body)
        self.assertIn("2 детали вместе (раздельно 93)", body)

    def test_sheets_and_sizes_do_not_mix(self):
        """Разный лист (толщина) и разный габарит — разные группы."""
        spec = self._spec([
            {"detail_name": "А", "a_mm": 560.0, "b_mm": 3000.0, "qty": 10},
            {"detail_name": "Б", "a_mm": 120.0, "b_mm": 3000.0, "qty": 10,
             "sheet_id": self.sheet4.id},
            {"detail_name": "В", "a_mm": 120.0, "b_mm": 1000.0, "qty": 10,
             "layout_sheet_size": "1500x3000"},
        ])
        spec.action_draft_layout()
        groups = spec.layout_group_ids
        self.assertEqual(len(groups), 3)
        self.assertEqual(set(groups.mapped("line_count")), {1})
        self.assertEqual(set(groups.mapped("mode")), {"separate"})
        for line in spec.sheet_line_ids:
            with self.subTest(line=line.detail_name):
                self.assertEqual(line.layout_group_id.line_ids, line)
                self.assertFalse(line.layout_group_note)
        body = plain(spec.message_ids[:1].body)
        self.assertNotIn("раздельно было", body, "Ни одной группы «вместе» — прежний текст.")

    def test_single_detail_same_as_before(self):
        """Одна деталь в группе — тот же plan_sheets, листов не больше."""
        spec = self._spec([{"detail_name": "Пластина", "a_mm": 490.0, "b_mm": 590.0, "qty": 10}],
                          qty=3)
        spec.action_draft_layout()
        line = spec.sheet_line_ids
        plan = plan_sheets(1500.0, 6000.0, 490.0, 590.0, 30)
        self.assertEqual(line.layout_sheets, plan["sheets"])
        self.assertEqual(line.layout_per_sheet, plan["per_sheet"])
        self.assertEqual(line.layout_scheme, plan["scheme"])
        self.assertAlmostEqual(line.layout_utilization_pct, plan["utilization_pct"])
        self.assertEqual(spec.layout_group_ids.sheets, plan["sheets"])
        self.assertEqual(spec.layout_group_ids.mode, "separate")

    def test_too_big_detail_stays_out(self):
        spec = self._spec([
            {"detail_name": "П-полоса", "a_mm": 120.0, "b_mm": 3000.0, "qty": 617},
            {"detail_name": "Z-полоса", "a_mm": 560.0, "b_mm": 3000.0, "qty": 265},
            {"detail_name": "Огромная", "a_mm": 1600.0, "b_mm": 7000.0, "qty": 1},
        ])
        spec.action_draft_layout()
        self.assertEqual(spec.layout_group_ids.sheets, 76)
        huge = spec.sheet_line_ids.filtered(lambda l: l.detail_name == "Огромная")
        self.assertEqual(huge.layout_state, "too_big")
        self.assertEqual(huge.layout_sheets, 0)
        # «Вместе с» — только легшие на общие листы (доработка З-13).
        self.assertFalse(huge.layout_joint)
        self.assertFalse(huge.layout_group_note)
        strip_z = spec.sheet_line_ids.filtered(lambda l: l.detail_name == "Z-полоса")
        self.assertEqual(strip_z.layout_group_note, "120×3000", "Огромной среди соседей нет.")

    def test_exact_detail_not_together(self):
        """Деталь «в размер листа» в группе «вместе» — на своих листах: в
        «Вместе с» её нет, в ленте «2 детали вместе», не 3."""
        spec = self._spec([
            {"detail_name": "П-полоса", "a_mm": 120.0, "b_mm": 3000.0, "qty": 617},
            {"detail_name": "Z-полоса", "a_mm": 560.0, "b_mm": 3000.0, "qty": 265},
            {"detail_name": "Лист в размер", "a_mm": 1500.0, "b_mm": 6000.0, "qty": 2},
        ])
        spec.action_draft_layout()
        group = spec.layout_group_ids
        self.assertEqual((group.mode, group.sheets, group.line_count), ("joint", 78, 3))
        exact = spec.sheet_line_ids.filtered(lambda l: l.detail_name == "Лист в размер")
        strip_p = spec.sheet_line_ids.filtered(lambda l: l.detail_name == "П-полоса")
        self.assertEqual((exact.layout_state, exact.layout_sheets), ("exact", 2))
        self.assertFalse(exact.layout_joint)
        self.assertFalse(exact.layout_group_note)
        self.assertEqual(strip_p.layout_group_note, "560×3000")
        body = plain(spec.message_ids[:1].body)
        self.assertIn("2 детали вместе (раздельно 95)", body)

    def test_grades_do_not_mix(self):
        """Ст3 и 09Г2С одного листа — разные группы: на общий лист не лягут."""
        Grade = self.env["pmk.metal.grade"]
        st3 = Grade.create({"name": "Ст3 (тест З-13)", "standard": "ГОСТ тест"})
        g09 = Grade.create({"name": "09Г2С (тест З-13)", "standard": "ГОСТ тест"})
        spec = self._spec([
            {"detail_name": "П-полоса", "a_mm": 120.0, "b_mm": 3000.0, "qty": 617,
             "grade_id": st3.id},
            {"detail_name": "Z-полоса", "a_mm": 560.0, "b_mm": 3000.0, "qty": 265,
             "grade_id": g09.id},
        ])
        spec.action_draft_layout()
        groups = spec.layout_group_ids
        self.assertEqual(len(groups), 2)
        self.assertEqual(set(groups.mapped("mode")), {"separate"})
        self.assertEqual(sum(groups.mapped("sheets")), 93, "Раздельно по марке — 26 + 67.")
        self.assertEqual(set(groups.mapped("grade_id")), {st3, g09})
        self.assertIn("09Г2С (тест З-13)", groups.filtered(
            lambda g: g.grade_id == g09).display_name)
        # Сменили марку — раскладка гаснет (марка — вход раскладки).
        strip_z = spec.sheet_line_ids.filtered(lambda l: l.detail_name == "Z-полоса")
        strip_z.write({"grade_id": st3.id})
        self.assertEqual(strip_z.layout_state, "none")
        self.assertTrue(spec.layout_stale)
        spec.action_draft_layout()
        group = strip_z.layout_group_id
        self.assertEqual((group.mode, group.sheets, group.grade_id), ("joint", 76, st3))
        self.assertFalse(groups.exists().filtered(lambda g: g.grade_id == g09))

    def test_no_sheet_details_only_separate(self):
        """Детали без выбранного листа — толщина неизвестна: одна группа
        «Лист не выбран», но только отдельно."""
        spec = self._spec([
            {"detail_name": "П-полоса", "a_mm": 120.0, "b_mm": 3000.0, "qty": 617,
             "sheet_id": False},
            {"detail_name": "Z-полоса", "a_mm": 560.0, "b_mm": 3000.0, "qty": 265,
             "sheet_id": False},
        ])
        spec.action_draft_layout()
        group = spec.layout_group_ids
        self.assertEqual(len(group), 1)
        self.assertFalse(group.sheet_id)
        self.assertEqual((group.mode, group.sheets, group.sheets_separate), ("separate", 93, 93))
        self.assertIn("Лист не выбран", group.display_name)
        self.assertFalse(any(spec.sheet_line_ids.mapped("layout_joint")))

    # ─── «Раскладка устарела» с группами (шаг 56) ────────────────────────
    def test_edit_one_detail_resets_whole_joint_group(self):
        spec, strip_p, strip_z = self._kytmanova()
        spec.action_draft_layout()
        group = spec.layout_group_ids
        strip_z.write({"qty": 266})
        for line in (strip_p, strip_z):
            with self.subTest(line=line.detail_name):
                self.assertEqual(line.layout_state, "none",
                                 "Доли соседей посчитаны вместе — гаснут оба.")
                self.assertEqual(line.layout_sheets, 0)
        self.assertEqual(group.state, "none")
        self.assertEqual(group.sheets, 0)
        # Погашенная совместная группа — не «отдельно»: слово «не считалась»
        # повторяет серый цвет строки (доработка З-13).
        self.assertEqual(group.mode, "joint")
        self.assertEqual(group.mode_label, "не считалась")
        self.assertFalse(strip_p.layout_joint)
        self.assertFalse(strip_p.layout_group_note)
        self.assertTrue(spec.layout_stale)
        spec.action_draft_layout()
        self.assertFalse(spec.layout_stale)
        self.assertEqual(spec.layout_group_ids, group, "Группа ключа — та же запись.")
        self.assertEqual(group.state, "ok")

    def test_product_qty_resets_group(self):
        spec, strip_p, _strip_z = self._kytmanova()
        spec.action_draft_layout()
        spec.product_ids.write({"qty": 2})
        self.assertEqual(spec.layout_group_ids.state, "none")
        self.assertTrue(spec.layout_stale)

    def test_separate_group_neighbours_keep_numbers(self):
        """Группа «отдельно»: числа соседей свои — правка одной детали гасит
        её и итог группы, соседа не трогает (как до З-13)."""
        spec = self._spec([
            {"detail_name": "Пластина", "a_mm": 1400.0, "b_mm": 2900.0, "qty": 2},
            {"detail_name": "Лист в размер", "a_mm": 1500.0, "b_mm": 6000.0, "qty": 1},
        ])
        spec.action_draft_layout()
        group = spec.layout_group_ids
        self.assertEqual(group.mode, "separate")
        plate = spec.sheet_line_ids.filtered(lambda l: l.detail_name == "Пластина")
        exact = spec.sheet_line_ids - plate
        plate.write({"qty": 3})
        self.assertEqual(plate.layout_state, "none")
        self.assertEqual(exact.layout_state, "exact", "Сосед по группе «отдельно» цел.")
        self.assertEqual(group.state, "none")
        self.assertTrue(spec.layout_stale)

    def test_delete_joint_detail_resets_neighbours(self):
        """Удалили деталь совместной группы — доля соседа больше не про заказ:
        Z одна требует 67 листов, а её доля в группе — 51."""
        spec, strip_p, strip_z = self._kytmanova()
        spec.action_draft_layout()
        self.assertLess(strip_z.layout_sheets, 67)
        spec.product_ids.write({"line_ids": [Command.delete(strip_p.id)]})
        self.assertEqual(strip_z.layout_state, "none")
        self.assertTrue(spec.layout_stale)
        spec.action_draft_layout()
        self.assertEqual(strip_z.layout_sheets, 67)
        self.assertEqual(spec.layout_group_ids.mode, "separate")

    def test_delete_separate_detail_updates_group(self):
        """Группа «отдельно»: удалили деталь — итог группы по оставшимся,
        сигнала нет (как в шаге 56); опустела — группа уходит."""
        spec = self._spec([
            {"detail_name": "Пластина", "a_mm": 1400.0, "b_mm": 2900.0, "qty": 2},
            {"detail_name": "Лист в размер", "a_mm": 1500.0, "b_mm": 6000.0, "qty": 1},
        ])
        spec.action_draft_layout()
        group = spec.layout_group_ids
        self.assertEqual((group.mode, group.sheets, group.line_count), ("separate", 2, 2))
        plate = spec.sheet_line_ids.filtered(lambda l: l.detail_name == "Пластина")
        exact = spec.sheet_line_ids - plate
        spec.product_ids.write({"line_ids": [Command.delete(exact.id)]})
        self.assertEqual((group.sheets, group.line_count), (1, 1))
        self.assertEqual(group.state, "ok")
        self.assertEqual(plate.layout_state, "ok")
        self.assertFalse(spec.layout_stale)
        spec.product_ids.write({"line_ids": [Command.delete(plate.id)]})
        self.assertFalse(group.exists(), "Листа в расчёте больше нет — группы тоже.")
        self.assertFalse(spec.layout_group_ids)

    def test_regroup_after_sheet_change(self):
        spec, strip_p, strip_z = self._kytmanova()
        spec.action_draft_layout()
        old = spec.layout_group_ids
        strip_p.write({"sheet_id": self.sheet4.id})
        spec.action_draft_layout()
        self.assertEqual(len(spec.layout_group_ids), 2)
        self.assertIn(old, spec.layout_group_ids, "Группа листа 3 мм — та же запись.")
        self.assertNotEqual(strip_p.layout_group_id, strip_z.layout_group_id)
        self.assertEqual(strip_z.layout_sheets, 67)

    # ─── Старые расчёты и копии ──────────────────────────────────────────
    def test_legacy_spec_kept_until_button(self):
        """Разложенный до З-13 расчёт (результаты строк, групп нет) сам не
        пересчитывается: числа прежние, на вкладке подсказка."""
        spec, strip_p, strip_z = self._kytmanova()
        for line, sheets, per in ((strip_p, 26, 24), (strip_z, 67, 4)):
            line.write({"layout_state": "ok", "layout_sheets": sheets, "layout_per_sheet": per,
                        "layout_scheme": "ряды", "layout_utilization_pct": 70.0})
        spec._pmk_store_layout_fingerprint()
        self.assertTrue(spec.layout_legacy)
        self.assertFalse(spec.layout_group_ids)
        self.assertFalse(spec.layout_stale, "Детали не менялись — не устарела.")
        self.assertEqual(strip_z.layout_sheets, 67)
        spec.action_draft_layout()
        self.assertFalse(spec.layout_legacy)
        self.assertEqual(spec.layout_group_ids.sheets, 76)

    def test_copy_has_no_groups(self):
        spec, _p, _z = self._kytmanova()
        spec.action_draft_layout()
        copy = spec.copy()
        self.assertFalse(copy.layout_group_ids, "Раскладку копии — заново кнопкой (R4).")
        self.assertFalse(copy.sheet_line_ids.mapped("layout_group_id"))
        self.assertEqual(len(spec.layout_group_ids), 1, "У оригинала — на месте.")

    # ─── Вкладка «Раскладка» ─────────────────────────────────────────────
    def test_layout_page_groups_table(self):
        views = self.env["pmk.metal.spec"].get_views([(False, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        page = arch.xpath("//page[@name='layout']")[0]
        names = [node.get("name") for node in page if node.tag == "field"]
        self.assertLess(names.index("layout_group_ids"), names.index("sheet_line_ids"),
                        "Листы по раскладке — над деталями.")
        groups = page.find("field[@name='layout_group_ids']")
        table = groups.find("list")
        self.assertEqual((table.get("create"), table.get("delete")), ("0", "0"),
                         "Группы заводит кнопка: ни «Добавить», ни корзины.")
        columns = {node.get("name"): node for node in table.findall("field")}
        visible = [name for name, node in columns.items()
                   if node.get("optional") != "hide"
                   and node.get("column_invisible") not in ("1", "True")
                   and not (node.get("column_invisible") or "").startswith("parent.")]
        self.assertEqual(visible, ["sheet_id", "sheet_size", "line_count", "sheets",
                                   "sheets_separate", "mode_label", "use_label"])
        for name in ("grade_id", "scheme", "parts_label", "state"):
            with self.subTest(hidden=name):
                self.assertEqual(columns[name].get("optional"), "hide")
        for name in ("sheet_id", "grade_id", "sheet_size", "line_count", "sheets",
                     "sheets_separate", "mode_label", "use_label", "scheme", "parts_label"):
            with self.subTest(readonly=name):
                self.assertEqual(columns[name].get("readonly"), "1")
        self.assertEqual(columns["use_label"].get("widget"), "badge")
        # Подписи над таблицами — словами, без английского.
        captions = [node.text.strip() for node in page.xpath(
            ".//div[contains(concat(' ', @class, ' '), ' pmk-layout-caption ')]")]
        # Не «к закупке»: так в шапке подписан металл по чистому весу.
        self.assertEqual(captions, ["Листы по раскладке", "Детали"])
        self.assertEqual(self.env["pmk.metal.spec"]._fields["layout_group_ids"].string,
                         "Листы по раскладке")
        details = page.find("field[@name='sheet_line_ids']/list")
        self.assertEqual(details.find("field[@name='layout_sheets']").get("string"),
                         "Листов (доля)")
        hint = page.xpath(".//div[@invisible='layout_group_ids or not layout_legacy']")
        self.assertEqual(len(hint), 1, "Подсказка старым расчётам.")
        # Сама кнопка на экране — одна, контурная (залитая — «КП (PDF)»).
        buttons = page.xpath(".//button[@name='action_draft_layout']")
        self.assertEqual(len(buttons), 1)
        self.assertNotIn("btn-primary", buttons[0].get("class"))
