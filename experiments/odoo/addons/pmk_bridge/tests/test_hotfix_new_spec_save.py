# -*- coding: utf-8 -*-
"""Новый расчёт с листовой деталью сохраняется (дефект 07.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py).

Баг, который ловим: владелец создаёт расчёт (из сделки или из меню),
добавляет изделие, в нём лист с выбранной позицией — «Сохранить» падает:
«Отсутствует обязательное значение для поля 'Изделие' (product_id)».
Onchange расчёта (себестоимость моста) вписывал несохранённую деталь в
зеркало sheet_line_ids, браузер заводил её копию, а web_save присылал
создание этой копии без изделия. Подробно — pmk_calc, spec_layout.py.

Тест идёт через Form — тот же путь, что у браузера: onchange после каждой
правки и сохранение тем, что накопилось в форме. Лежит в мосте, потому что
лишнюю деталь в зеркало вписывал именно расчёт себестоимости моста.
"""
import datetime

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNewSpecSave(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        old = fields.Date.context_today(cls.env["res.partner"]) - datetime.timedelta(days=10)
        metal = cls.env["res.partner"].create({
            "name": "Металлсервис (тест сохранения)", "is_company": True,
            "pmk_supplier_rank": 10})
        Info = cls.env["product.supplierinfo"]

        # Лист с ценой: без цены себестоимость не считается, и дефект
        # не проявлялся бы — на боевой базе у листа цена была.
        sheet_tmpl = cls.env["product.template"].create({
            "name": "Лист 4 мм (тест сохранения)", "weight": 282.6})
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест сохранения)", "thickness_mm": 4.0,
            "gost": "ГОСТ тест", "mass_per_sqm": 31.4, "product_tmpl_id": sheet_tmpl.id})
        Info.create({"partner_id": metal.id, "product_tmpl_id": sheet_tmpl.id,
                     "price": 22588.1, "date_start": old})

        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Уголок (тест сохранения)"})
        angle_tmpl = cls.env["product.template"].create({"name": "Уголок 50×5 (тест сохранения)"})
        cls.angle = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест сохранения)",
            "gost": "ГОСТ тест", "size_label": "50×5", "mass_per_meter": 3.77,
            "product_tmpl_id": angle_tmpl.id})
        Info.create({"partner_id": metal.id, "product_tmpl_id": angle_tmpl.id,
                     "price": 500.0, "date_start": old})

        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)
        cls.Line = cls.env["pmk.metal.spec.line"]

    def _fill_product(self, form, name, sheets=1, linear=0):
        with form.product_ids.new() as product:
            product.name = name
            for i in range(sheets):
                with product.line_sheet_ids.new() as line:
                    line.detail_name = "лист %d" % (i + 1)
                    line.sheet_id = self.sheet
                    line.a_mm = 100
                    line.b_mm = 200
            for i in range(linear):
                with product.line_linear_ids.new() as line:
                    line.detail_name = "стойка %d" % (i + 1)
                    line.profile_id = self.angle
                    line.length_mm = 1000

    def _assert_saved(self, spec, expected):
        lines = self.Line.search([("spec_id", "=", spec.id)])
        self.assertEqual(len(lines), expected,
                         "Деталей ровно столько, сколько добавили — без копий из зеркал.")
        self.assertTrue(all(lines.mapped("product_id")), "У каждой детали есть изделие.")
        self.assertEqual(spec.sheet_line_ids, lines.filtered(lambda l: l.calc_mode == "sheet"))

    def test_new_spec_with_sheet_saves(self):
        """Сценарий владельца: новый расчёт, изделие «цинк», в нём лист."""
        form = Form(self.Spec)
        self._fill_product(form, "цинк")
        spec = form.save()
        self._assert_saved(spec, 1)
        self.assertEqual(spec.product_ids.line_sheet_ids.detail_name, "лист 1")

    def test_new_spec_mixed_details_saves(self):
        """Два изделия, лист и прокат вперемешку — ни одной лишней строки."""
        form = Form(self.Spec)
        self._fill_product(form, "цинк", sheets=2, linear=1)
        self._fill_product(form, "рама", sheets=1, linear=2)
        spec = form.save()
        self._assert_saved(spec, 6)

    def test_existing_spec_add_sheet_saves(self):
        """Тот же путь на сохранённом расчёте: новое изделие с листом."""
        form = Form(self.Spec)
        self._fill_product(form, "цинк")
        spec = form.save()
        form = Form(spec)
        self._fill_product(form, "рама", sheets=2)
        form.save()
        self._assert_saved(spec, 3)

    def test_onchange_does_not_offer_new_lines_to_layout(self):
        """Корень: onchange не отдаёт несохранённую деталь в «Раскладку»."""
        values = {"product_ids": [Command.create({
            "name": "цинк", "qty": 1,
            "line_sheet_ids": [Command.create({
                "calc_mode": "sheet", "detail_name": "лист", "sheet_id": self.sheet.id,
                "a_mm": 100, "b_mm": 200, "qty": 1})]})]}
        spec_fields = {
            "product_ids": {"fields": {"name": {}, "line_sheet_ids": {"fields": {
                "calc_mode": {}, "detail_name": {}, "sheet_id": {}, "a_mm": {},
                "b_mm": {}, "qty": {}}}}},
            # Себестоимость — то, что вписывало деталь в зеркала (мост).
            "total_cost_fact": {},
            "sheet_line_ids": {"fields": {"detail_name": {}, "layout_sheet_size": {}}},
        }
        result = self.Spec.onchange(values, ["product_ids"], spec_fields)
        commands = result["value"].get("sheet_line_ids") or []
        self.assertFalse([c for c in commands if c[0] == Command.CREATE],
                         "Новых деталей в редактируемом зеркале нет.")

    def test_mirror_create_without_product_is_dropped(self):
        """Старая вкладка браузера прислала копию — расчёт всё равно сохраняется."""
        phantom = Command.create({"layout_sheet_size": "1500x6000"})
        spec = self.Spec.create({
            "product_ids": [Command.create({"name": "цинк", "qty": 1, "line_ids": [
                Command.create({"calc_mode": "sheet", "sheet_id": self.sheet.id,
                                "a_mm": 100, "b_mm": 200})]})],
            "sheet_line_ids": [phantom, phantom],
            "price_line_ids": [phantom],
        })
        self._assert_saved(spec, 1)
        spec.write({"sheet_line_ids": [phantom], "price_line_ids": [phantom]})
        self._assert_saved(spec, 1)

    def test_layout_size_still_editable(self):
        """Габарит в «Раскладке» по-прежнему правится (шаг 32)."""
        form = Form(self.Spec)
        self._fill_product(form, "цинк")
        spec = form.save()
        line = spec.sheet_line_ids
        spec.write({"sheet_line_ids": [Command.update(line.id, {"layout_sheet_size": "1500x3000"})]})
        self.assertEqual(line.layout_sheet_size, "1500x3000")

    def test_line_without_product_is_refused(self):
        """Деталь мимо изделия — понятная ошибка, а не падение в базе."""
        with self.assertRaises(ValidationError):
            self.Line.create({"calc_mode": "sheet", "detail_name": "сирота"})
