# -*- coding: utf-8 -*-
"""Счёт Odoo → МойСклад (этап 6, 22.10.2026). МойСклад подставной: чтение и запись — в списки."""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_moysklad.models import export as ex
from odoo.addons.pmk_org.hooks import ensure_taxes


@tagged("post_install", "-at_install")
class TestMsExport(TransactionCase):

    def setUp(self):
        super().setUp()
        ensure_taxes(self.env, self.env.company)
        Param = self.env["ir.config_parameter"].sudo()
        Param.set_param("pmk_moysklad.odoo_folder_id", "folder-odoo")
        self.org = self.env["pmk.org"].search([], limit=1)
        self.org.pmk_ms_id = "org-ms-1"
        self.client = self.env["res.partner"].create({"name": "ООО «Выгрузка»", "is_company": True,
                                                      "vat": "2700000001"})
        self.writes, self.gets = [], []
        Ms = type(self.env["pmk.moysklad"])

        def fake_get(_s, path, params=None):
            self.gets.append((path, params))
            if path == "entity/invoiceout/metadata":
                return {"states": [{"name": "Из Odoo", "id": "st-odoo"}, {"name": "Не актуальна", "id": "st-off"},
                                   {"name": "Оплачен", "id": "st-paid"}]}
            if path == "entity/uom":
                return {"rows": [{"id": "uom-sht"}]}
            return {"rows": []}

        def fake_write(_s, method, path, body):
            self.writes.append((method, path, body))
            return {"id": "new-%s" % len(self.writes), "updated": "2026-10-22 15:00:00.000"}
        for name, fn in (("_ms_get", fake_get), ("_ms_write", fake_write)):
            p = patch.object(Ms, name, fn)
            p.start()
            self.addCleanup(p.stop)

    def _mode(self, mode):
        self.env["ir.config_parameter"].sudo().set_param(ex.MODE_PARAM, mode)

    def _invoice(self):
        order = self.env["sale.order"].create({"partner_id": self.client.id, "pmk_org_id": self.org.id})
        self.env["sale.order.line"].create({
            "order_id": order.id, "name": "Монтаж ограждения", "product_uom_qty": 2, "price_unit": 1500.5,
            "product_id": self.env["product.product"].create({"name": "Услуга (тест выгрузки)"}).id})
        return order

    def test_queue_and_off(self):
        order = self._invoice()
        self.assertTrue(order.pmk_ms_from_odoo)
        self.assertEqual(order.pmk_ms_export_state, "pending")
        self.env["sale.order"].with_context(pmk_ms_no_commit=True)._cron_ms_export()  # режим не задан — ничего
        self.assertEqual(order.pmk_ms_export_state, "pending")
        self.assertFalse(self.writes)
        ms_order = self.env["sale.order"].create({"partner_id": self.client.id, "name": "01999",
                                                  "pmk_ms_id": "ms-from-ms"})
        self.assertFalse(ms_order.pmk_ms_export_state, "Счёт из МС не выгружаем.")

    def test_dry_writes_nothing(self):
        self._mode("dry")
        order = self._invoice()
        self.env["sale.order"].with_context(pmk_ms_no_commit=True)._cron_ms_export()
        self.assertEqual(order.pmk_ms_export_state, "dry")
        self.assertFalse(self.writes, "Вхолостую — в МС ни одной записи.")
        self.assertIn("создали бы", order.pmk_ms_export_note)
        self.assertIn("завели бы", order.pmk_ms_export_note)
        self.assertFalse(order.pmk_ms_id)

    def test_live_create_update_cancel(self):
        self._mode("live")
        order = self._invoice()
        self.env["sale.order"].with_context(pmk_ms_no_commit=True)._cron_ms_export()
        methods = [(m, p) for m, p, _b in self.writes]
        self.assertEqual(methods, [("POST", "entity/counterparty"), ("POST", "entity/product"),
                                   ("POST", "entity/invoiceout")])
        product = self.writes[1][2]
        self.assertEqual(product["productFolder"]["meta"]["href"].rsplit("/", 1)[-1], "folder-odoo")
        body = self.writes[2][2]
        self.assertEqual(body["name"], order.name)
        self.assertEqual(body["positions"][0]["price"], 150050, "Цена — в копейках.")
        self.assertEqual(body["positions"][0]["quantity"], 2)
        self.assertTrue(body["state"]["meta"]["href"].endswith("/st-odoo"))
        self.assertEqual((order.pmk_ms_id, order.pmk_ms_export_state, order.pmk_ms_state),
                         ("new-3", "done", "Из Odoo"))
        self.assertEqual(self.client.pmk_ms_id, "new-1", "Контрагент запомнил id МС.")
        # Правка строки — обновление без статуса (статус МС ведёт Владимир).
        self.writes.clear()
        order.order_line.price_unit = 1600
        self.assertEqual(order.pmk_ms_export_state, "pending")
        self.env["sale.order"].with_context(pmk_ms_no_commit=True)._cron_ms_export()
        self.assertEqual(self.writes[-1][:2], ("PUT", "entity/invoiceout/new-3"))
        self.assertNotIn("state", self.writes[-1][2])
        # Отмена — «Не актуальна».
        order._action_cancel()
        self.env["sale.order"].with_context(pmk_ms_no_commit=True)._cron_ms_export()
        self.assertTrue(self.writes[-1][2]["state"]["meta"]["href"].endswith("/st-off"))

    def test_sync_keeps_odoo_lines(self):
        """Синхронизация МС → Odoo у счёта из Odoo меняет только статус и суммы."""
        self._mode("live")
        order = self._invoice()
        self.env["sale.order"].with_context(pmk_ms_no_commit=True)._cron_ms_export()
        lines = order.order_line
        inv = {"meta": {"href": "https://x/entity/invoiceout/new-3"}, "name": "ЧУЖОЙ", "moment": "2026-10-22 10:00:00.000",
               "organization": {"meta": {"href": "https://x/entity/organization/org-ms-1"}},
               "agent": {"meta": {"href": "https://x/entity/counterparty/new-1"}},
               "state": {"name": "Оплачен"}, "sum": 320000, "shippedSum": 0, "positions": {"rows": []},
               "updated": "2026-10-22 16:00:00.000"}
        Ms = self.env["pmk.moysklad"]
        ctx = {"taxes": Ms._taxes(), "product": self.env.ref("pmk_moysklad.product_ms_line"), "users": [],
               "tag": self.env.ref("pmk_moysklad.partner_tag_ms", raise_if_not_found=False)}
        Ms._upsert_invoice(inv, {"org-ms-1": self.org}, ctx, self.env["sale.order"])
        self.assertEqual(order.pmk_ms_state, "Оплачен")
        self.assertEqual(order.order_line, lines, "Строки Odoo на месте.")
        self.assertNotEqual(order.name, "ЧУЖОЙ")
        self.assertEqual(order.pmk_ms_export_state, "done", "Приход из МС не ставит в очередь.")

    def test_client_without_inn_not_created(self):
        """Клиент без ИНН и без двойника в МС — счёт не выгружаем: в МС был бы дубль без ИНН."""
        self._mode("live")
        self.client.vat = False
        order = self._invoice()
        self.env["sale.order"].with_context(pmk_ms_no_commit=True)._cron_ms_export()
        self.assertEqual(order.pmk_ms_export_state, "error")
        self.assertIn("нет ИНН", order.pmk_ms_export_note)
        self.assertFalse(self.writes)

