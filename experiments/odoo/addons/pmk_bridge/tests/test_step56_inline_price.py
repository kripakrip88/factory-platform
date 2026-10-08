# -*- coding: utf-8 -*-
"""«Цена за шт» в строке «Состава» и КП при устаревшей раскладке — разбор UX,
шаг 56 (08.10.2026).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk56_test -i pmk_deal --test-enable \\
         --test-tags /pmk_calc,/pmk_bridge --stop-after-init --http-port 8099

Антон 07.10: «Почему нельзя изменить цену за штуку в общем списке расчета
металлопроката и количество?» Цена — обычное ручное поле (без наценки и без
вычисления), мешал только вид: список изделий не редактировался на месте.
Правку в строке делает JS (pmk_calc, product_lines_field.js; цену добавляет
static/src/js/product_lines_cost.js) — её смотрит основной агент глазами.
Здесь — что запись строки (команда, как присылает браузер, и onchange до
сохранения) пересчитывает «Сумму», «Цену клиенту» и маржу, как из окна.

Цены — свои: болт 110 ₽ (прайс от 21.09), 10 болтов в изделии — металл
1 100 ₽ на штуку.
"""
import datetime

from lxml import etree

from odoo import Command
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.misc import file_path

D = datetime.date


@tagged("post_install", "-at_install")
class TestInlinePriceStep56(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        supplier = cls.env["res.partner"].create({
            "name": "АО «Металлсервис» (тест 56)", "is_company": True})
        tmpl = cls.env["product.template"].create({"name": "Болт М12×40 (тест 56)"})
        cls.bolt = cls.env["pmk.metal.fastener"].create({
            "name": "Болт М12×40 (тест 56)", "weight_kg": 0.5, "product_tmpl_id": tmpl.id})
        cls.env["product.supplierinfo"].create({
            "partner_id": supplier.id, "product_tmpl_id": tmpl.id,
            "price": 110.0, "date_start": D(2026, 9, 21)})
        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    def _spec(self):
        return self.Spec.create({
            "price_date": D(2026, 9, 27),
            "product_ids": [
                Command.create({
                    "name": "Каркас", "qty": 1, "price_customer_unit": 5000.0,
                    "line_ids": [Command.create({
                        "calc_mode": "fastener", "fastener_id": self.bolt.id, "qty": 10})]}),
                Command.create({"name": "Без состава", "qty": 2, "price_customer_unit": 300.0}),
            ],
        })

    def test_price_and_qty_by_command(self):
        """Как присылает браузер правку строки: Command.update изделия."""
        spec = self._spec()
        frame, empty = spec.product_ids.sorted("id")
        self.assertEqual(frame.cost_fact_total, 1100.0)
        self.assertEqual(spec.price_customer_total, 5600.0)

        spec.write({"product_ids": [
            Command.update(frame.id, {"price_customer_unit": 6000.0, "qty": 2}),
            Command.update(empty.id, {"price_customer_unit": 450.0}),
        ]})
        self.assertEqual(frame.price_customer_unit, 6000.0, "Ручная цена сохранена как есть.")
        self.assertEqual(frame.price_customer_total, 12000.0)
        self.assertEqual(frame.cost_fact_total, 2200.0, "Металл — на оба изделия.")
        self.assertEqual(empty.price_customer_total, 900.0, "Изделие без состава — тоже.")
        self.assertEqual(spec.price_customer_total, 12900.0)
        self.assertEqual(spec.margin_amount, 12900.0 - spec.total_cost_fact)

    def test_price_by_onchange(self):
        """До «Сохранить»: карточки «Цена клиенту» и маржа — сразу."""
        spec = self._spec()
        form = Form(spec)
        with form.product_ids.edit(0) as row:
            row.price_customer_unit = 7000.0
        self.assertEqual(form.price_customer_total, 7600.0)
        self.assertEqual(form.margin_amount, 7600.0 - spec.total_cost_fact)
        with form.product_ids.edit(0) as row:
            row.qty = 3
        self.assertEqual(form.price_customer_total, 21600.0)
        form.save()
        frame = spec.product_ids.sorted("id")[0]
        self.assertEqual((frame.price_customer_unit, frame.qty), (7000.0, 3))
        self.assertEqual(spec.price_customer_total, 21600.0)

    def test_price_column_in_row(self):
        """Колонка «Цена за шт» не только для чтения, ширина прежняя; JS моста
        дописывает её к правке в строке."""
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_views(
            [(False, "form")])["views"]["form"]["arch"])
        price = arch.xpath("//field[@name='product_ids']/list/field[@name='price_customer_unit']")[0]
        self.assertNotIn(price.get("readonly"), ("1", "True"))
        self.assertEqual(price.get("width"), "130px")
        self.assertEqual(price.get("widget"), "monetary")
        with open(file_path("pmk_bridge/static/src/js/product_lines_cost.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('[...super.pmkInlineFieldNames(), "price_customer_unit"]', js)

    def test_stale_layout_does_not_block_kp(self):
        """Сигнал «Раскладка устарела» показывает, а не запрещает: КП
        печатается, как раньше."""
        spec = self._spec()
        spec.product_ids[:1].write({"line_ids": [Command.create({
            "calc_mode": "sheet", "detail_name": "Пластина",
            "sheet_id": self.env.ref("pmk_calc.sheet_гладкий_4").id,
            "a_mm": 1000.0, "b_mm": 500.0, "qty": 2})]})
        spec.action_draft_layout()
        spec.product_ids[:1].qty = 4
        self.assertTrue(spec.layout_stale)
        action = spec.action_print_quotation()
        self.assertEqual(action["type"], "ir.actions.report")
        report = self.env["ir.actions.report"].with_user(self.env.ref("base.user_admin"))
        html, _fmt = report._render_qweb_html(
            "pmk_bridge.action_report_metal_spec_quotation", spec.ids)
        html = html.decode()
        self.assertIn("Каркас", html)
        self.assertNotIn("Раскладка устарела", html, "Сигнал — экрану, не клиенту.")
