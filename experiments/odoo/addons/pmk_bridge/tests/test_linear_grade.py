# -*- coding: utf-8 -*-
"""Марка проката в цене (№313, Владимир 24.10.2026).

Числа: труба 114×4, 10,85 кг/м; Ст3сп 849,40 ₽/м (78 290 ₽/т), 09Г2С 1 001,30 ₽/м.
Ловим: марка 09Г2С — цена 09Г2С, а не Ст3; марки нет в прайсах — цены нет;
старая цена на шаблоне — только базовой марке; перенос старых цен по марке из
названия строки прайса, ряд цен — с историей.
"""
import datetime

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged

from ..tools import grades


@tagged("post_install", "-at_install")
class TestLinearGrade(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env["res.partner"])
        cls.old = cls.today - datetime.timedelta(days=10)
        attr = cls.env.ref("pmk_bridge.attr_grade")
        st3 = attr.value_ids.filtered(lambda v: v.name == "Ст3сп")
        cls.tmpl = cls.env["product.template"].create({
            "name": "Труба 114×4 (тест №313)", "default_code": "TRK-T-114x4", "weight": 10.85})
        cls.tmpl.attribute_line_ids = [Command.create({"attribute_id": attr.id, "value_ids": [st3.id]})]
        cls.base = cls.tmpl.product_variant_ids
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Труба (тест №313)"})
        cls.profile = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Труба (тест №313)", "gost": "ГОСТ тест",
            "size_label": "114×4", "mass_per_meter": 10.85, "product_tmpl_id": cls.tmpl.id})
        cls.metal = cls.env["res.partner"].create({
            "name": "Металлсервис (тест №313)", "is_company": True, "pmk_supplier_rank": 10})
        cls.Info = cls.env["product.supplierinfo"]
        cls.g09 = cls.env["pmk.metal.grade"].search([("name", "=", "09Г2С")], limit=1)

    def _info(self, name, price, variant=None, start=None, end=None):
        return self.Info.create({
            "partner_id": self.metal.id, "product_tmpl_id": self.tmpl.id,
            "product_id": variant.id if variant else False, "price": price,
            "product_name": name, "date_start": start or self.old, "date_end": end})

    def test_grade_from_vendor_name(self):
        self.assertEqual(grades.grade_from_vendor_name("Труба эл/св 114 х 4 Ст 09Г2С"), "09Г2С")
        self.assertEqual(grades.grade_from_vendor_name("Балка 20Б1 С 255"), "Ст3сп")
        self.assertEqual(grades.grade_from_vendor_name("Балка 25К1 С 355"), "09Г2С")
        self.assertEqual(grades.grade_from_vendor_name("Труба эл/св 159 х 6 Ст 20"), "Ст20")
        self.assertEqual(grades.grade_from_vendor_name("Уголок 160х100х10  C255"), "Ст3сп", "латинская C")
        self.assertIsNone(grades.grade_from_vendor_name("Круг 20"), "размер, не сталь 20")
        self.assertIsNone(grades.grade_from_vendor_name("Труба профильная 60х40х3"))
        self.assertIsNone(grades.grade_from_vendor_name("Труба 57х3 Ст2кп"), "марка не заведена")
        self.assertEqual(grades.map_grade("С345"), "09Г2С")
        self.assertEqual(grades.map_grade("с 345"), "09Г2С")
        self.assertEqual(grades.grade_family("Ст3пс"), {"Ст3сп", "Ст3пс"})
        self.assertEqual(grades.grade_family("09Г2С"), {"09Г2С"})

    def test_find_seller_by_grade(self):
        st3 = self._info("Труба эл/св 114 х 4 Ст3сп\\пс", 849.40, self.base)
        v09 = self.tmpl._pmk_grade_variant("09Г2С", create=True)
        p09 = self._info("Труба эл/св 114 х 4 Ст 09Г2С", 1001.30, v09)
        T = self.tmpl
        self.assertEqual(T._pmk_find_seller(self.today, grade="09Г2С"), p09)
        self.assertEqual(T._pmk_find_seller(self.today, grade="Ст3сп"), st3)
        self.assertEqual(T._pmk_find_seller(self.today), st3, "Без марки — самая дешёвая.")
        self.assertFalse(T._pmk_find_seller(self.today, grade="10ХСНД"),
                         "Марки нет в прайсах — цены нет, Ст3 не подставляем.")

    def test_template_price_only_for_base_grade(self):
        """Цена на шаблоне (марка не опознана) — обычная сталь: Ст3сп и «любая», не 09Г2С."""
        tmpl_price = self._info("Труба эл/св 114 х 4 Углерод.", 849.40)
        T = self.tmpl
        self.assertEqual(T._pmk_find_seller(self.today), tmpl_price)
        self.assertEqual(T._pmk_find_seller(self.today, grade="Ст3сп"), tmpl_price)
        self.assertFalse(T._pmk_find_seller(self.today, grade="09Г2С"))

    def test_spec_line_takes_grade_price(self):
        st3 = self._info("Труба эл/св 114 х 4 Ст3сп", 849.40, self.base)
        v09 = self.tmpl._pmk_grade_variant("09Г2С", create=True)
        p09 = self._info("Труба эл/св 114 х 4 Ст 09Г2С", 1001.30, v09)
        spec = self.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True).create({
                "product_ids": [Command.create({"name": "стойка", "qty": 1, "line_ids": [
                    Command.create({"calc_mode": "linear", "profile_id": self.profile.id,
                                    "length_mm": 1000, "qty": 1, "grade_id": self.g09.id}),
                    Command.create({"calc_mode": "linear", "profile_id": self.profile.id,
                                    "length_mm": 1000, "qty": 1})]})]})
        l09, lbase = spec.product_ids.line_ids.sorted("id")
        self.assertEqual(l09.price_source_id, p09)
        self.assertAlmostEqual(l09.price_unit, 1001.30, places=2)
        self.assertEqual(lbase.price_source_id, st3)
        lbase.grade_id = self.g09
        self.assertEqual(lbase.price_source_id, p09, "Сменили марку — цена марки сразу.")

    def test_move_old_prices_to_grade_variants(self):
        """Миграция 19.0.0.9.4: старые цены с шаблона — на вариант марки из названия."""
        st3_old = self._info("Труба эл/св 114 х 4 Ст3сп\\пс", 820.0,
                             start=self.old - datetime.timedelta(days=30), end=self.old - datetime.timedelta(days=1))
        st3 = self._info("Труба эл/св 114 х 4 Ст3сп\\пс", 849.40)
        p09 = self._info("Труба эл/св 114 х 4 Ст 09Г2С", 1001.30)
        other = self._info("Труба эл/св 114 х 4 Ст2кп", 800.0)
        moved, kept, refused = self.env["product.template"]._pmk_linear_prices_to_grade_variants()
        self.assertEqual(st3_old.product_id, self.base, "История ряда — тоже.")
        self.assertEqual(st3.product_id, self.base)
        self.assertEqual(p09.product_id.product_template_attribute_value_ids.name, "09Г2С")
        self.assertFalse(other.product_id, "Марка не заведена — на шаблоне.")
        self.assertGreaterEqual(moved.get("Ст3сп", 0), 2)
        self.assertGreaterEqual(kept, 1)
        self.assertEqual(self.tmpl.default_code, "TRK-T-114x4", "Артикул карточки цел.")
        self.assertEqual(self.tmpl._pmk_find_seller(self.today, grade="09Г2С"), p09)

    def test_bare_card_gets_base_grade(self):
        """Карточка проката без характеристики марки — получает Ст3сп, вариант тот же."""
        tmpl = self.env["product.template"].create({"name": "Труба 140×3 (тест №313)",
                                                    "default_code": "TPK-T-140x3"})
        variant = tmpl.product_variant_ids
        self.env["pmk.metal.profile"].create({
            "type_id": self.profile.type_id.id, "profile_type": "Труба (тест №313)", "gost": "ГОСТ тест",
            "size_label": "140×3", "mass_per_meter": 12.0, "product_tmpl_id": tmpl.id})
        info = self.Info.create({"partner_id": self.metal.id, "product_tmpl_id": tmpl.id,
                                 "price": 900.0, "product_name": "Труба 140 х 3 Ст3пс",
                                 "date_start": self.old})
        self.env["product.template"]._pmk_linear_prices_to_grade_variants()
        self.assertEqual(tmpl._pmk_grade_variant("Ст3сп"), variant, "Единственный вариант — Ст3сп.")
        self.assertEqual(tmpl.default_code, "TPK-T-140x3")
        self.assertEqual(info.product_id.product_template_attribute_value_ids.name, "Ст3пс")
        self.assertEqual(tmpl._pmk_find_seller(self.today, grade="Ст3сп"), info,
                         "Ст3пс годится строке Ст3сп — взаимозаменяемые (Антон 25.10).")
        self.assertFalse(tmpl._pmk_find_seller(self.today, grade="09Г2С"))
        self.assertEqual(tmpl._pmk_find_seller(self.today), info, "Без марки — какая есть.")
