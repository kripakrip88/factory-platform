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
