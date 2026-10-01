# -*- coding: utf-8 -*-
"""Формы расчёта и доборки — один стиль подписей (разбор UX, шаг 27).

Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py).

Подпись слева и ряды «Клиент | Контактное лицо», «Цены на дату |
Организация» смотрит основной агент глазами на 1440 px, в обеих темах.
Здесь — то, что ломается молча: класс формы, на который опираются стили
темы (pmk_theme, forms_nexus.scss, раздел 9), короткая подпись «Предмет КП»
при прежнем названии поля, строки доборки по центру.
"""
from lxml import etree

from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path


@tagged("post_install", "-at_install")
class TestFormsStep27(TransactionCase):

    def _form(self, model, xmlid=None):
        view_id = self.env.ref(xmlid).id if xmlid else False
        views = self.env[model].get_views([(view_id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_spec_form_class_and_subject_label(self):
        arch = self._form("pmk.metal.spec")
        classes = arch.get("class", "").split()
        self.assertIn("pmk-spec-form", classes, "Класс шага 32 на месте.")
        self.assertIn("pmk-doc-form", classes)
        note = arch.xpath("//div[@name='pmk_f_note']/label[@for='note']")
        self.assertEqual(len(note), 1)
        self.assertEqual(note[0].get("string"), "Предмет КП",
                         "Подпись в одну строку — колонку подписей не раздувает.")
        # Название поля прежнее: его видят список, поиск и выгрузка; смысл
        # «видит клиент» — в подсказке «?».
        field = self.env["pmk.metal.spec"]._fields["note"]
        self.assertEqual(field.string, "Предмет КП (видит клиент)")
        self.assertIn("КП", field.help)
        # Окно изделия — своя форма, класс до неё не доходит.
        product_form = arch.xpath("//field[@name='product_ids']/form")[0]
        self.assertNotIn("pmk-doc-form", (product_form.get("class") or "").split())

    def test_head_blocks_keep_markup(self):
        """Разметку шапки не трогали: блоки pmk-field с подписью и полем —
        на них опираются xpath мостов и стили подписи слева."""
        arch = self._form("pmk.metal.spec")
        head = arch.xpath("//div[contains(concat(' ', @class, ' '), ' pmk-doc-head__fields ')]")[0]
        for block in head:
            if block.tag != "div" or "pmk-field" not in (block.get("class") or "").split():
                continue
            with self.subTest(block=block.get("name")):
                self.assertEqual(block[0].tag, "label", "Подпись — первой, поле — за ней.")

    def test_dobor_form_class(self):
        arch = self._form("pmk.dobor.order", "pmk_calc.view_dobor_order_form")
        self.assertIn("pmk-doc-form", arch.get("class", "").split())
        line_form = arch.xpath("//field[@name='line_ids']/form")[0]
        self.assertNotIn("pmk-doc-form", (line_form.get("class") or "").split(),
                         "Окно позиции — своя форма в своём диалоге.")
        self.assertTrue(arch.xpath("//field[@name='line_ids']/list/field[@name='sketch'][@widget='pmk_svg']"),
                        "Эскиз в строке — на нём правило «всё по центру строки».")

    def test_dobor_rows_centered(self):
        path = "pmk_calc/static/src/scss/dobor_builder.scss"
        self.assertIn(path, get_manifest("pmk_calc")["assets"]["web.assets_backend"])
        with open(file_path(path), encoding="utf-8") as f:
            scss = f.read()
        rule = scss[scss.index(".o_list_renderer .o_data_row:has(.pmk-sketch) > td {"):]
        self.assertIn("vertical-align: middle", rule[:rule.index("}")])
