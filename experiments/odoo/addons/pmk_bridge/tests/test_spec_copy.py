# -*- coding: utf-8 -*-
"""Копия расчёта — новый расчёт на сегодня (приёмка 01.10.2026, R4).

Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py).

Баг, который ловим: «Дублировать» переносил цену строки (price_unit), и ядро
при создании копии защищало от пересчёта всю группу полей цены — у копии
СМ-00025 все 22 строки остались «Позиция не выбрана», без ₽/кг и без строки
прайса, металл 0, маржа 100 %.

Цены — свои, проверяются в уме (как test_step25_prices.py):
  • уголок 100×8: масса метра 10 кг; прайс 1 000 ₽/м действует всегда,
    прайс 500 ₽/м закрыт вчера — на старую дату берётся дешёвый 500, на
    сегодня — только 1 000;
  • лист 5 мм: карточка 500 кг, 40 000 ₽/лист → 80 ₽/кг;
  • уголок 200×20 — в прайсах нет.
"""
import datetime

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSpecCopy(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.context_today(cls.env["res.partner"])
        cls.today = today
        cls.old = today - datetime.timedelta(days=100)
        metal = cls.env["res.partner"].create({
            "name": "Металлсервис (тест копии)", "is_company": True, "pmk_supplier_rank": 10})
        Info = cls.env["product.supplierinfo"]

        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Уголок (тест копии)"})
        angle_tmpl = cls.env["product.template"].create({"name": "Уголок 100×8 (тест копии)"})
        cls.angle = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест копии)", "gost": "ГОСТ тест",
            "size_label": "100×8", "mass_per_meter": 10.0, "product_tmpl_id": angle_tmpl.id})
        cls.angle_today = Info.create({
            "partner_id": metal.id, "product_tmpl_id": angle_tmpl.id,
            "price": 1000.0, "date_start": cls.old})
        Info.create({
            "partner_id": metal.id, "product_tmpl_id": angle_tmpl.id,
            "price": 500.0, "date_start": cls.old,
            "date_end": today - datetime.timedelta(days=1)})

        sheet_tmpl = cls.env["product.template"].create({
            "name": "Лист 5 мм (тест копии)", "weight": 500.0})
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест копии)", "thickness_mm": 5.0, "gost": "ГОСТ тест",
            "mass_per_sqm": 39.25, "product_tmpl_id": sheet_tmpl.id})
        Info.create({"partner_id": metal.id, "product_tmpl_id": sheet_tmpl.id,
                     "price": 40000.0, "date_start": cls.old})

        bare_tmpl = cls.env["product.template"].create({"name": "Уголок 200×20 (тест копии)"})
        cls.bare = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест копии)", "gost": "ГОСТ тест",
            "size_label": "200×20", "mass_per_meter": 60.0, "product_tmpl_id": bare_tmpl.id})

        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    def _original(self):
        """Расчёт задним числом: цены на 100 дней назад, ручная цена, раскладка."""
        spec = self.Spec.create({
            "date": self.old,
            "price_date": self.old,
            "product_ids": [Command.create({
                "name": "Рама", "qty": 2, "price_customer_unit": 50000.0,
                "line_ids": [
                    Command.create({"calc_mode": "linear", "detail_name": "Стойка",
                                    "profile_id": self.angle.id, "length_mm": 1000.0, "qty": 1}),
                    Command.create({"calc_mode": "linear", "detail_name": "Связь",
                                    "profile_id": self.angle.id, "length_mm": 500.0, "qty": 2}),
                    Command.create({"calc_mode": "sheet", "detail_name": "Пластина",
                                    "sheet_id": self.sheet.id, "a_mm": 200.0, "b_mm": 300.0,
                                    "qty": 4}),
                    Command.create({"calc_mode": "linear", "detail_name": "Балка",
                                    "profile_id": self.bare.id, "length_mm": 2000.0, "qty": 1}),
                    Command.create({"calc_mode": "linear", "detail_name": "Пустая"}),
                ],
            })],
        })
        lines = {l.detail_name: l for l in spec.product_ids.line_ids}
        self.assertAlmostEqual(lines["Стойка"].price_unit, 500.0,
                               msg="На старую дату действует и дешёвый прайс.")
        lines["Связь"].price_unit = 777.0  # ручная правка цены
        spec.action_draft_layout()
        self.assertEqual(lines["Пластина"].layout_state, "ok")
        return spec, lines

    def test_copy_is_a_new_spec_for_today(self):
        spec, origin_lines = self._original()
        copy = spec.copy()
        self.assertNotEqual(copy.name, spec.name, "Свой номер СМ-.")
        self.assertEqual(copy.date, self.today, "Копия — расчёт сегодняшний.")
        self.assertEqual(copy.price_date, self.today, "Цены — на сегодня.")

        lines = {l.detail_name: l for l in copy.product_ids.line_ids}
        self.assertEqual(set(lines), set(origin_lines))
        expected_state = {"Стойка": "ok", "Связь": "ok", "Пластина": "ok",
                          "Балка": "no_price", "Пустая": "empty"}
        for name, state in expected_state.items():
            with self.subTest(line=name):
                self.assertEqual(lines[name].price_state, state)

        for name in ("Стойка", "Связь"):
            with self.subTest(price=name):
                line = lines[name]
                self.assertAlmostEqual(line.price_unit, 1000.0,
                                       msg="Цена из прайса на сегодня — не старая 500 "
                                           "и не ручная 777.")
                self.assertEqual(line.price_source_id, self.angle_today)
                self.assertAlmostEqual(line.price_kg, 100.0, places=4)
                self.assertTrue(line.price_partner_id)
                self.assertEqual(line.price_date_used, self.old)

        plate = lines["Пластина"]
        self.assertAlmostEqual(plate.price_kg, 80.0, places=4)
        self.assertTrue(plate.price_source_id)

        # Металл на изделие: 1 000 + 0,5 м × 2 × 1 000 + 80 ₽/кг × 2,355 кг × 4
        # = 2 753,6 ₽; изделий 2 — 5 507,2 ₽.
        self.assertGreater(copy.total_cost_fact, 0.0)
        self.assertAlmostEqual(copy.total_cost_fact, 5507.2, places=2)
        self.assertEqual(copy.no_price_count, 1, "Балки нет в прайсах — сигнал на месте.")
        self.assertAlmostEqual(copy.price_customer_total, 100000.0, places=2,
                               msg="Цена клиенту за изделие переносится.")
        self.assertFalse(copy.price_reread_needed)

    def test_copy_drops_layout_and_logs_why(self):
        spec, _lines = self._original()
        copy = spec.copy()
        plate = copy.sheet_line_ids
        self.assertEqual(len(plate), 1)
        self.assertEqual(plate.layout_sheet_size, "1500x6000", "Габарит — вход, копируется.")
        self.assertEqual(plate.layout_state, "none", "Раскладку — заново кнопкой.")
        self.assertEqual(plate.layout_sheets, 0)
        self.assertEqual(plate.layout_per_sheet, 0)
        self.assertFalse(plate.layout_scheme)

        bodies = " ".join(str(m.body) for m in copy.message_ids)
        self.assertIn("Копия %s" % spec.name, bodies)
        self.assertIn("перечитаны из прайсов", bodies)
        self.assertIn("правленные вручную, не перенесены: 1 поз.", bodies)
        self.assertIn("Разложить листы", bodies)

    def test_original_untouched(self):
        spec, lines = self._original()
        spec.copy()
        self.assertEqual(spec.price_date, self.old)
        self.assertAlmostEqual(lines["Стойка"].price_unit, 500.0)
        self.assertAlmostEqual(lines["Связь"].price_unit, 777.0)
        self.assertEqual(lines["Пластина"].layout_state, "ok")

    def test_duplicate_several_from_the_list(self):
        """«Дублировать» в списке копирует несколько расчётов разом."""
        first, _l1 = self._original()
        second, _l2 = self._original()
        copies = (first | second).copy()
        self.assertEqual(len(copies), 2)
        for origin, copy in zip(first | second, copies):
            with self.subTest(origin=origin.name):
                self.assertEqual(copy.price_date, self.today)
                self.assertIn("Копия %s" % origin.name,
                              " ".join(str(m.body) for m in copy.message_ids))
