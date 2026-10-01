# -*- coding: utf-8 -*-
"""«Копировать» у позиции доборки (приёмка 01.10.2026, R9b).

Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py).

Копию делает браузер — штатный метод вложенного списка duplicateRecords
(web, static_list.js), потому что серверная кнопка у несохранённой строки не
срабатывает (static/src/js/dobor_copy_line.js). Щелчок здесь не повторить —
его смотрит основной агент глазами. Проверяем три половины, которые от
сервера зависят:
  • разметка: кнопка стоит в строке, а скрытые поля, которые копия обязана
    унести (чертёж, ширина рулона), в списке есть — без них браузеру нечего
    копировать; толщины в списке и в окне позиции НЕТ (иначе onchange
    перепишет её у копии и у каждой новой позиции — см. COPY_FIELDS);
  • сервер: те же значения, что пришлёт браузер (onchange_batch — копируемые
    поля и номер порядка «исходный + 1»), дают ту же развёртку, гибы, вес и
    эскиз, а сохранение ставит копию сразу под исходной с ТОЙ ЖЕ толщиной,
    что у исходной (в печатном листе — одна толщина и один вес);
  • имена «Доборка N»: строки одной пачки (новый заказ, копия ещё не
    сохранённой позиции) нумеруются подряд, занятое имя пропускается.
"""
import json

from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged

SNAPSHOT = json.dumps({
    "start": {"x": 0, "y": 0},
    "segs": [{"len": 85, "dir": 0}, {"len": 61, "dir": 90}, {"len": 20, "dir": 180}],
    "hemLeft": True, "hemLen": 10,
})


@tagged("post_install", "-at_install")
class TestDoborCopyLine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Оцинкованный", "thickness_mm": 0.7,
            "gost": "ГОСТ 14918-2020 (тест)", "mass_per_sqm": 5.495})
        cls.coating = cls.env["pmk.dobor.coating"].create({
            "name": "RAL 8017 (тест)", "ral_code": "8017", "hex_color": "#45322e"})
        cls.Order = cls.env["pmk.dobor.order"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    def _order(self):
        # Толщину НЕ задаём — как форма: поля толщины в ней нет, позиция
        # получает умолчание 0,5 при металле 0,7. Так на живой базе у строк
        # 12, 18, 19, 20 (металл 0,40–0,65, толщина 0,5).
        line = {"coating_id": self.coating.id, "sheet_id": self.sheet.id,
                "plank_length": 2000.0, "qty": 3}
        return self.Order.create({
            "customer": "Тест копии",
            "line_ids": [
                Command.create({**line, "title": "Конёк", "sequence": 10}),
                Command.create({**line, "title": "Отлив", "sequence": 11,
                                "profile_snapshot_json": SNAPSHOT,
                                "plank_length": 2500.0, "qty": 7, "coil_width": 1250.0}),
                Command.create({**line, "title": "Планка", "sequence": 12}),
            ],
        })

    # ─── Разметка ───────────────────────────────────────────────────────
    def _form_arch(self):
        views = self.env["pmk.dobor.order"].get_views([(False, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_button_in_the_row(self):
        lst = self._form_arch().xpath("//field[@name='line_ids']/list")[0]
        widgets = lst.xpath("widget[@name='pmk_dobor_copy_line']")
        self.assertEqual(len(widgets), 1, "«Копировать» — в строке позиции.")
        names = [f.get("name") for f in lst.xpath("field")]
        for name in ("profile_snapshot_json", "coil_width"):
            with self.subTest(field=name):
                self.assertIn(name, names, "Копия уносит поле — оно должно быть в списке.")
        handle = lst.xpath("field[@name='sequence']")[0]
        self.assertEqual(handle.get("widget"), "handle",
                         "Копию под исходной ставит номер порядка (поле-ручка).")
        self.assertIsNone(lst.get("editable"),
                          "Список по-прежнему открывает окно позиции с построителем.")

    def test_thickness_not_in_line_views(self):
        """Толщины нет ни в списке позиций, ни в окне позиции. Появись она в
        любом из них — onchange по металлу начнёт её сохранять: у копии
        толщина станет толщиной листа, а у исходной останется 0,5, и в
        печатном листе одна планка выйдет двумя толщинами (находка проверки
        01.10.2026). Брать толщину из металла — отдельное решение."""
        line_ids = self._form_arch().xpath("//field[@name='line_ids']")[0]
        self.assertFalse(line_ids.xpath(".//field[@name='thickness']"))

    def test_assets_registered(self):
        from odoo.modules.module import get_manifest
        assets = get_manifest("pmk_calc")["assets"]["web.assets_backend"]
        self.assertIn("pmk_calc/static/src/js/dobor_copy_line.js", assets)
        self.assertIn("pmk_calc/static/src/xml/dobor_copy_line.xml", assets)

    # ─── Сервер: то, что пришлёт браузер ───────────────────────────────
    def test_copy_values_compute_like_the_source(self):
        order = self._order()
        source = order.line_ids.filtered(lambda l: l.title == "Отлив")
        Line = self.env["pmk.dobor.order.line"]
        # Как static_list.js (_duplicateRecords): копируемые поля строки,
        # many2one — словарём {id, display_name}, номер порядка «исходный + 1»,
        # родитель — {id}.
        changes = {
            "title": source.title,
            "coating_id": {"id": self.coating.id, "display_name": self.coating.display_name},
            "sheet_id": {"id": self.sheet.id, "display_name": self.sheet.display_name},
            "plank_length": source.plank_length,
            "qty": source.qty,
            "profile_snapshot_json": source.profile_snapshot_json,
            "coil_width": source.coil_width,
            "sequence": source.sequence + 1,
            "order_id": {"id": order.id},
        }
        spec = {name: {} for name in (
            "sequence", "sketch", "title", "plank_length", "qty", "developed_width",
            "bends", "strips", "strip_waste", "weight_total", "profile_snapshot_json",
            "coil_width")}
        spec["coating_id"] = {"fields": {"display_name": {}}}
        spec["sheet_id"] = {"fields": {"display_name": {}}}
        [result] = Line.onchange_batch([changes], [], spec)
        value = result["value"]
        for name in ("developed_width", "bends", "weight_total", "strips", "strip_waste"):
            with self.subTest(field=name):
                self.assertAlmostEqual(value[name], source[name], places=4)
        self.assertTrue(value["sketch"], "Эскиз рисуется и у копии.")

    def test_saved_copy_goes_right_below(self):
        """Сохранение: копия — сразу под исходной, строки ниже сдвинуты
        (как их сдвигает браузер), чертёж и параметры — те же. Толщину
        браузер не присылает (её нет в виде) — у копии та же, что у исходной:
        в печатном листе одна толщина и один вес на один металл."""
        order = self._order()
        source = order.line_ids.filtered(lambda l: l.title == "Отлив")
        below = order.line_ids.filtered(lambda l: l.title == "Планка")
        self.assertEqual(source.thickness, 0.5, "Умолчание, как у позиций из формы.")
        order.write({"line_ids": [
            Command.create({
                "title": source.title, "coating_id": self.coating.id,
                "sheet_id": self.sheet.id, "plank_length": source.plank_length,
                "qty": source.qty, "profile_snapshot_json": source.profile_snapshot_json,
                "coil_width": source.coil_width, "sequence": source.sequence + 1}),
            Command.update(below.id, {"sequence": source.sequence + 2}),
        ]})
        titles = order.line_ids.sorted(lambda l: (l.sequence, l.id)).mapped("title")
        self.assertEqual(titles, ["Конёк", "Отлив", "Отлив", "Планка"])
        copy = order.line_ids.filtered(lambda l: l.title == "Отлив") - source
        self.assertEqual(len(copy), 1)
        for name in ("profile_snapshot_json", "coating_id", "sheet_id", "plank_length",
                     "qty", "coil_width", "thickness", "developed_width", "bends",
                     "weight_total"):
            with self.subTest(field=name):
                self.assertEqual(copy[name], source[name])
        self.assertEqual(order.total_positions, 4)
        self.assertEqual(order.total_qty, 3 + 7 + 7 + 3)

    # ─── Имена «Доборка N» ─────────────────────────────────────────────
    def _untitled(self, **extra):
        return Command.create({"coating_id": self.coating.id, "sheet_id": self.sheet.id,
                               "plank_length": 2000.0, "qty": 1, **extra})

    def test_new_order_untitled_lines_numbered_in_order(self):
        """Новый заказ: позицию нарисовали без названия и сразу скопировали —
        обе уходят одной пачкой. Было: обе «Доборка 2». Стало: 1 и 2."""
        order = self.Order.create({
            "customer": "Тест имён",
            "line_ids": [self._untitled(sequence=10), self._untitled(sequence=11)],
        })
        titles = order.line_ids.sorted(lambda l: (l.sequence, l.id)).mapped("title")
        self.assertEqual(titles, ["Доборка 1", "Доборка 2"])

    def test_batch_numbered_in_list_order(self):
        """Две новые позиции без названия, и первую скопировали: копия
        встала между ними (порядок 10, 20, 30), хотя записана последней.
        Номера — в том порядке, как строки стоят в списке и в листе."""
        order = self.Order.create({
            "customer": "Тест порядка",
            "line_ids": [self._untitled(sequence=10), self._untitled(sequence=30),
                         self._untitled(sequence=20)],
        })
        titles = order.line_ids.sorted(lambda l: (l.sequence, l.id)).mapped("title")
        self.assertEqual(titles, ["Доборка 1", "Доборка 2", "Доборка 3"])

    def test_saved_order_untitled_batch_numbered_in_order(self):
        """Сохранённый заказ с одной позицией: новая без названия и её копия
        уходят одной пачкой. Было: обе «Доборка 3». Стало: 2 и 3."""
        order = self._order()
        order.line_ids.filtered(lambda l: l.title != "Конёк").unlink()
        order.write({"line_ids": [self._untitled(sequence=20), self._untitled(sequence=21)]})
        titles = order.line_ids.sorted(lambda l: (l.sequence, l.id)).mapped("title")
        self.assertEqual(titles, ["Конёк", "Доборка 2", "Доборка 3"])

    def test_single_untitled_line_as_before(self):
        """Одна новая позиция — номер как раньше: позиций было три, она
        четвёртая."""
        order = self._order()
        order.write({"line_ids": [self._untitled(sequence=30)]})
        last = order.line_ids.sorted(lambda l: (l.sequence, l.id))[-1]
        self.assertEqual(last.title, "Доборка 4")

    def test_taken_name_skipped(self):
        """После удаления позиции счёт по количеству попадает на занятое имя
        — берётся следующий свободный номер, двух «Доборка 2» нет."""
        order = self.Order.create({
            "customer": "Тест занятого имени",
            "line_ids": [self._untitled(sequence=10), self._untitled(sequence=11)],
        })
        order.line_ids.filtered(lambda l: l.title == "Доборка 1").unlink()
        order.write({"line_ids": [self._untitled(sequence=12)]})
        titles = sorted(order.line_ids.mapped("title"))
        self.assertEqual(titles, ["Доборка 2", "Доборка 3"])

    def test_named_lines_keep_their_names(self):
        """Своё имя не трогается, и в пачке оно занимает свой номер позиции."""
        order = self.Order.create({
            "customer": "Тест своих имён",
            "line_ids": [self._untitled(sequence=10, title="Отлив"),
                         self._untitled(sequence=11)],
        })
        titles = order.line_ids.sorted(lambda l: (l.sequence, l.id)).mapped("title")
        self.assertEqual(titles, ["Отлив", "Доборка 2"])
