# -*- coding: utf-8 -*-
"""Лист в м², габарит — единица-«упаковка» (№309, 19.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py). Числа — в уме:
  • лист 5 мм: 39,25 кг/м²; 1500×6000 = 9 м² = 353,25 кг; 1500×3000 = 4,5 м²;
  • прайс «за лист 1500×6000» 31 792,50 ₽ → 3 532,50 ₽/м² → 90 000 ₽/т;
  • прайс «за лист 1500×3000» 16 335 ₽ → 3 630 ₽/м² (мелкий лист дороже за м²).

Ловим: масса единицы листа — кг/м² справочника при любом габарите (мина
«второй габарит обнулит вес карточки» снята); цена — по габариту строки, нет
его у поставщиков — с любого (вариант «а») с подсказкой; без габарита — как до
№309, 1500×6000.
"""
import datetime

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSheetM2(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        old = fields.Date.context_today(cls.env["res.partner"]) - datetime.timedelta(days=10)
        cls.today = fields.Date.context_today(cls.env["res.partner"])
        cls.Uom = cls.env["uom.uom"]
        cls.sqm = cls.env.ref("uom.product_uom_square_meter")
        cls.u6000 = cls.Uom._pmk_sheet_uom("1500x6000")
        cls.u3000 = cls.Uom._pmk_sheet_uom("1500x3000")
        cls.metal = cls.env["res.partner"].create({
            "name": "Металлсервис (тест м²)", "is_company": True, "pmk_supplier_rank": 10})
        cls.tmpl = cls.env["product.template"].create({
            "name": "Лист 5 мм (тест м²)", "uom_id": cls.sqm.id, "weight": 39.25})
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест м²)", "thickness_mm": 5.0, "gost": "ГОСТ тест",
            "mass_per_sqm": 39.25, "product_tmpl_id": cls.tmpl.id})
        Info = cls.env["product.supplierinfo"]
        cls.p6000 = Info.create({
            "partner_id": cls.metal.id, "product_tmpl_id": cls.tmpl.id,
            "product_uom_id": cls.u6000.id, "price": 31792.5, "date_start": old})
        cls.p3000 = Info.create({
            "partner_id": cls.metal.id, "product_tmpl_id": cls.tmpl.id,
            "product_uom_id": cls.u3000.id, "price": 16335.0, "date_start": old})

    def test_units(self):
        """Пять габаритов — единицы от м² с площадью листа, ОКЕИ «лист»."""
        expect = {"1250x2500": 3.125, "1500x3000": 4.5, "1500x6000": 9.0,
                  "2000x6000": 12.0, "1000x4000": 4.0}
        for size, area in expect.items():
            uom = self.Uom._pmk_sheet_uom(size)
            self.assertTrue(uom, size)
            self.assertEqual(uom.relative_uom_id, self.sqm)
            self.assertAlmostEqual(uom.relative_factor, area)
            self.assertEqual(uom._pmk_sheet_size(), size)
            self.assertEqual(uom.okei, "625")
        self.assertEqual(self.Uom._pmk_sheet_uom("1500×6000"), self.u6000, "знак × тоже понимаем")
        self.assertFalse(self.Uom._pmk_sheet_uom("1600x6000"))
        self.assertEqual(self.sqm._pmk_sheet_size(), "")

    def test_mass_and_price_per_sqm(self):
        """Масса единицы — кг/м²; цена «за лист» приходит в м²; ₽/т сходится."""
        self.assertTrue(self.tmpl._pmk_is_sqm())
        self.assertAlmostEqual(self.sheet._pmk_mass_per_unit(self.tmpl), 39.25)
        self.assertAlmostEqual(self.p6000.price_discounted, 3532.5, places=2)
        self.assertAlmostEqual(self.p3000.price_discounted, 3630.0, places=2)
        self.assertAlmostEqual(self.p6000.pmk_price_ton, 90000.0, places=0)
        self.assertEqual(self.p3000.pmk_variant_label, "1500x3000")

    def test_find_seller_by_gabarit(self):
        """Строка габарита; нет такого — любой (вариант «а»); без габарита — 1500×6000."""
        T = self.tmpl
        self.assertEqual(T._pmk_find_seller(self.today, uom=self.u3000), self.p3000)
        self.assertEqual(T._pmk_find_seller(self.today, uom=self.u6000), self.p6000)
        u2500 = self.Uom._pmk_sheet_uom("1250x2500")
        # Нет у поставщиков — самая дешёвая за м²: 1500×6000.
        self.assertEqual(T._pmk_find_seller(self.today, uom=u2500), self.p6000)
        # Без габарита — 1500×6000, хотя с ним и так совпадает самая дешёвая.
        self.assertEqual(T._pmk_find_seller(self.today), self.p6000)
        self.p6000.date_end = self.today - datetime.timedelta(days=1)
        self.assertEqual(T._pmk_find_seller(self.today), self.p3000,
                         "1500×6000 нет — любой габарит, а не «нет цены»")

    def test_spec_line_takes_gabarit_price(self):
        """Строка расчёта берёт цену своего габарита, сумма — по весу."""
        spec = self.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True).create({
                "supplier_id": self.metal.id,
                "product_ids": [Command.create({"name": "рама", "qty": 1, "line_ids": [
                    Command.create({"calc_mode": "sheet", "sheet_id": self.sheet.id,
                                    "a_mm": 1000, "b_mm": 1000, "qty": 1,
                                    "layout_sheet_size": "1500x3000"}),
                    Command.create({"calc_mode": "sheet", "sheet_id": self.sheet.id,
                                    "a_mm": 1000, "b_mm": 1000, "qty": 1,
                                    "layout_sheet_size": "1250x2500"})]})]})
        l3000, l2500 = spec.product_ids.line_ids.sorted("id")
        self.assertEqual(l3000.price_source_id, self.p3000)
        self.assertAlmostEqual(l3000.price_unit, 3630.0, places=2)
        self.assertAlmostEqual(l3000.price_ton, 3630.0 / 39.25 * 1000, places=0)
        self.assertFalse(l3000.price_gabarit_note)
        # 1250×2500 у поставщика нет — цена с листа 1500×6000 и подсказка.
        self.assertEqual(l2500.price_source_id, self.p6000)
        self.assertIn("1250×2500 нет у поставщиков", l2500.price_gabarit_note)
        self.assertIn("1500×6000", l2500.price_gabarit_note)

    def test_packaging_added_once(self):
        """На карточку — только нужные габариты, без повторов."""
        self.tmpl._pmk_add_packaging(self.u6000)
        self.tmpl._pmk_add_packaging(self.u6000)
        self.tmpl._pmk_add_packaging(self.sqm)
        self.assertEqual(self.tmpl.uom_ids, self.u6000)


@tagged("post_install", "-at_install")
class TestSheetGrade(TransactionCase):
    """Марка — вариант листа, цена — по марке строки (№309, этап 2, 19.10.2026).

    Ловим: вариант марки заводится, не трогая базовый (Ст3сп) и не обнуляя
    артикул карточки; цена берётся по марке, без марки — базовая; марки нет в
    прайсах — цены нет (подставлять Ст3сп вместо 09Г2С нельзя).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        old = fields.Date.context_today(cls.env["res.partner"]) - datetime.timedelta(days=10)
        cls.today = fields.Date.context_today(cls.env["res.partner"])
        sqm = cls.env.ref("uom.product_uom_square_meter")
        cls.u6000 = cls.env["uom.uom"]._pmk_sheet_uom("1500x6000")
        attr = cls.env.ref("pmk_bridge.attr_grade")
        st3 = attr.value_ids.filtered(lambda v: v.name == "Ст3сп")
        cls.tmpl = cls.env["product.template"].create({
            "name": "Лист 10 мм (тест марки)", "uom_id": sqm.id, "weight": 78.5,
            "default_code": "LST-T-10"})
        # Правило одного значения (product_attribute.xml): вариант впитывает Ст3сп.
        cls.tmpl.attribute_line_ids = [Command.create({"attribute_id": attr.id, "value_ids": [st3.id]})]
        cls.base = cls.tmpl.product_variant_ids
        cls.metal = cls.env["res.partner"].create({
            "name": "Металлсервис (тест марки)", "is_company": True, "pmk_supplier_rank": 10})
        Info = cls.env["product.supplierinfo"]
        cls.p_st3 = Info.create({"partner_id": cls.metal.id, "product_tmpl_id": cls.tmpl.id,
                                 "product_id": cls.base.id, "product_uom_id": cls.u6000.id,
                                 "price": 50000.0, "date_start": old})
        cls.v09 = cls.tmpl._pmk_grade_variant("09Г2С", create=True)
        cls.p_09 = Info.create({"partner_id": cls.metal.id, "product_tmpl_id": cls.tmpl.id,
                                "product_id": cls.v09.id, "product_uom_id": cls.u6000.id,
                                "price": 60000.0, "date_start": old})

    def test_variant_created_code_kept(self):
        self.assertTrue(self.v09)
        self.assertNotEqual(self.v09, self.base)
        self.assertTrue(self.base.active, "Базовый вариант жив.")
        self.assertEqual(self.base.default_code, "LST-T-10")
        self.assertEqual(self.v09.default_code, "LST-T-10-09G2S")
        self.assertEqual(self.tmpl.default_code, "LST-T-10", "Артикул карточки не обнулился.")
        self.assertAlmostEqual(self.v09.weight, 78.5)
        self.assertEqual(self.tmpl._pmk_grade_variant("09Г2С", create=True), self.v09, "Без дублей.")
        self.assertFalse(self.tmpl._pmk_grade_variant("10ХСНД"), "Без create не заводит.")

    def test_find_seller_by_grade(self):
        T = self.tmpl
        self.assertEqual(T._pmk_find_seller(self.today, grade="09Г2С"), self.p_09)
        self.assertEqual(T._pmk_find_seller(self.today, grade="Ст3сп"), self.p_st3)
        self.assertEqual(T._pmk_find_seller(self.today), self.p_st3, "Без марки — самая дешёвая (Ст3сп).")
        self.p_09.price = 45000.0
        self.assertEqual(T._pmk_find_seller(self.today), self.p_09,
                         "Без марки — самая дешёвая, даже если это не Ст3сп (Антон 19.10).")
        self.assertEqual(T._pmk_find_seller(self.today, grade="Ст3сп"), self.p_st3)
        self.p_09.price = 60000.0
        self.assertFalse(T._pmk_find_seller(self.today, grade="10ХСНД"),
                         "Марки нет в прайсах — цены нет, Ст3сп не подставляем.")

    def test_spec_line_takes_grade_price(self):
        """Строка расчёта с маркой 09Г2С берёт цену 09Г2С, без марки — Ст3сп."""
        sheet = self.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест марки)", "thickness_mm": 10.0, "gost": "ГОСТ тест",
            "mass_per_sqm": 78.5, "product_tmpl_id": self.tmpl.id})
        g09 = self.env["pmk.metal.grade"].search([("name", "=", "09Г2С")], limit=1)
        spec = self.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True).create({
                "product_ids": [Command.create({"name": "рама", "qty": 1, "line_ids": [
                    Command.create({"calc_mode": "sheet", "sheet_id": sheet.id, "a_mm": 500,
                                    "b_mm": 500, "qty": 1, "grade_id": g09.id}),
                    Command.create({"calc_mode": "sheet", "sheet_id": sheet.id, "a_mm": 500,
                                    "b_mm": 500, "qty": 1, "grade_id": False})]})]})
        l09, lbase = spec.product_ids.line_ids.sorted("id")
        self.assertEqual(l09.price_source_id, self.p_09)
        self.assertEqual(lbase.price_source_id, self.p_st3)
