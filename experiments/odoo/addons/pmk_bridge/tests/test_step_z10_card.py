# -*- coding: utf-8 -*-
"""Позиция «на разнос» и карточка товара — разбор UX, шаг З-10 (09.10.2026).

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_step_z10_pending.py).

Что ловим:
  • у позиции «на разнос» карточки нет — строка расчёта «Нет карточки
    товара», она в «Нет цены» (сигнал, не ошибка), расчёт не падает;
  • «Привязать к существующей» карточку не заводит: деталь берёт карточку и
    цену настоящей позиции;
  • «Принять в справочник» заводит карточку как у залитых: имя «позиция
    стандарт», артикул генератором (sku.py), категория вида, единица (метр /
    штука), партии, вес единственного варианта (лист — масса м² × 9 м²),
    внешние идентификаторы для загрузчика прайсов; строка расчёта — «Нет цены
    в прайсах» (карточка есть, прайса нет).
"""
import datetime

from lxml import etree

from odoo import fields
from odoo.tests import tagged

from odoo.addons.pmk_calc.tests.test_step_z10_pending import Z10Common


@tagged("post_install", "-at_install")
class TestStepZ10Card(Z10Common):

    def test_pending_has_no_card_and_no_price(self):
        pending = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 75×6 09Г2С",
                                                  "mass_per_meter": 6.89})
        self.assertFalse(pending.product_tmpl_id, "Карточку по черновику не заводим.")
        spec = self._spec([{"calc_mode": "linear", "profile_id": pending.id,
                            "length_mm": 1000.0, "qty": 1}])
        line = spec.product_ids.line_ids
        self.assertEqual(line.price_state, "no_link")
        self.assertEqual(spec.no_price_count, 1, "«Нет цены» — сигнал «в городе нет».")
        self.assertIn("Уголок 75×6 09Г2С", spec.price_missing_text)
        self.assertAlmostEqual(line.weight_total, 6.89, places=3)

    def test_bind_takes_real_card_and_price(self):
        supplier = self.env["res.partner"].create({"name": "Поставщик (тест З-10)",
                                                   "is_company": True})
        tmpl = self.env["product.template"].create({
            "name": "Уголок 63×5 (тест З-10)", "uom_id": self.env.ref("uom.product_uom_meter").id})
        real = self.Profile.create({
            "type_id": self.angle_type.id, "profile_type": self.angle_type.name,
            "gost": "ГОСТ тест", "size_label": "63x5 (тест З-10)", "mass_per_meter": 4.81,
            "product_tmpl_id": tmpl.id})
        self.env["product.supplierinfo"].create({
            "partner_id": supplier.id, "product_tmpl_id": tmpl.id, "price": 481.0,
            "date_start": fields.Date.today() - datetime.timedelta(days=10)})
        pending = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 63×5 Ст3"})
        spec = self._spec([{"calc_mode": "linear", "profile_id": pending.id,
                            "length_mm": 2000.0, "qty": 1}])
        line = spec.product_ids.line_ids
        pending.with_user(self.admin)._pmk_pending_bind(real)
        self.assertFalse(pending.product_tmpl_id, "Привязка карточку не заводит.")
        self.assertEqual(line.profile_id, real)
        self.assertEqual(line.price_state, "ok", "Цена — настоящей позиции.")
        self.assertEqual(line.price_partner_id, supplier)
        self.assertEqual(spec.no_price_count, 0)

    def test_accept_creates_card(self):
        pending = self._new("pmk.metal.profile", {"pmk_pending_name": "Уголок 75×6 09Г2С"})
        spec = self._spec([{"calc_mode": "linear", "profile_id": pending.id,
                            "length_mm": 1000.0, "qty": 1}])
        line = spec.product_ids.line_ids
        pending.with_user(self.admin).write({
            "type_id": self.angle_type.id, "size_label": "75x6 (з10)",
            "gost": "ГОСТ 8509-93", "mass_per_meter": 6.89})
        pending.with_user(self.admin).action_pmk_accept()
        tmpl = pending.product_tmpl_id
        self.assertTrue(tmpl, "«Принять» заводит карточку товара.")
        self.assertEqual(tmpl.name, "Уголок равнополочный 75x6 (з10) ГОСТ 8509-93")
        self.assertEqual(tmpl.uom_id, self.env.ref("uom.product_uom_meter"))
        self.assertEqual(tmpl.type, "consu")
        self.assertTrue(tmpl.is_storable)
        self.assertEqual(tmpl.tracking, "lot")
        self.assertEqual(tmpl.categ_id, self.env.ref("pmk_bridge.categ_rolled_ugr"))
        variant = tmpl.product_variant_id
        self.assertTrue(variant.default_code)
        self.assertTrue(all(ord(ch) < 128 for ch in variant.default_code), "Артикул латиницей.")
        self.assertAlmostEqual(variant.weight, 6.89, places=2)
        self.assertTrue(pending.get_external_id()[pending.id].startswith("pmk_calc."))
        key = pending.get_external_id()[pending.id].split(".", 1)[1]
        self.assertEqual(self.env.ref("pmk_bridge.product_%s" % key), tmpl,
                         "По этим идентификаторам загрузчик прайсов найдёт позицию.")
        self.assertEqual(line.price_state, "no_price", "Карточка есть, прайса нет — «нет цены».")

    def test_accept_sheet_and_fastener_cards(self):
        sheet = self._new("pmk.metal.sheet", {"pmk_pending_name": "Лист 5 мм С345",
                                              "thickness_mm": 5.0})
        sheet.with_user(self.admin).write({"sheet_type": "Гладкий", "size_label": "С345 з10",
                                           "gost": "ГОСТ 19903-2015"})
        sheet.with_user(self.admin).action_pmk_accept()
        card = sheet.product_tmpl_id
        self.assertEqual(card.uom_id, self.env.ref("uom.product_uom_unit"), "Лист — штуками.")
        self.assertAlmostEqual(card.product_variant_id.weight, 39.25 * 9.0, places=2,
                               msg="Масса листа 1500×6000.")

        bolt = self._new("pmk.metal.fastener", {"pmk_pending_name": "Болт М20×85 (з10)",
                                                "weight_kg": 0.25})
        bolt.with_user(self.admin).action_pmk_accept()
        card = bolt.product_tmpl_id
        self.assertEqual(card.uom_id, self.env.ref("uom.product_uom_unit"))
        self.assertEqual(card.tracking, "none")
        self.assertTrue(card.product_variant_id.default_code.startswith("PND-MTZ-"),
                        "Типоразмера нет — служебный артикул, без столкновений.")
        self.assertAlmostEqual(card.product_variant_id.weight, 0.25, places=3)

    def test_reference_forms_show_bridge_price(self):
        """Доводка З-10: форма позиции справочника — с ценой моста, как была
        форма ядра до шага: «Цена, ₽/т», «Поставщик», «Прайс от»."""
        for model in ("pmk.metal.profile", "pmk.metal.sheet", "pmk.metal.fastener"):
            for user in (self.engineer, self.admin):
                with self.subTest(model=model, user=user.login):
                    arch = etree.fromstring(self.env[model].with_user(user).get_views(
                        [(False, "form")])["views"]["form"]["arch"])
                    for fname in ("product_tmpl_id", "pmk_price_ton",
                                  "pmk_price_supplier_label", "pmk_price_date"):
                        self.assertTrue(arch.xpath("//field[@name='%s']" % fname), fname)

    def test_spec_copy_keeps_pending(self):
        """Копия расчёта (технический — тоже копия) ссылается на ту же позицию."""
        pending = self._new("pmk.metal.profile", {"pmk_pending_name": "Тавр 10 (з10)"})
        spec = self._spec([{"calc_mode": "linear", "profile_id": pending.id,
                            "length_mm": 1000.0, "qty": 1}])
        copy = spec.copy()
        self.assertEqual(copy.product_ids.line_ids.profile_id, pending)
        self.assertEqual(copy.pmk_pending_count, 1)
        self.assertEqual(pending.pmk_pending_spec_count, 2)

