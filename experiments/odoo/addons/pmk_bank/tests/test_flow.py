# -*- coding: utf-8 -*-
"""Опрос → поступления → сопоставление → группа. Банк и Телеграм подставные."""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models import bank_account
from ..tools import message


def op(oid, amount, inn, purpose, day="2026-10-13", name="ООО Клиент"):
    """Операция в общем виде — так их отдают оба клиента банка."""
    return {"id": oid, "amount": amount, "currency": "RUR", "payer_inn": inn,
            "payer_name": name, "purpose": purpose, "doc_number": "1", "executed": day}


class FakeBank:
    def __init__(self, ops):
        self.ops = ops

    def accounts(self):
        return [{"number": "40802810470010208163", "id": "acc-1"}]

    def incoming(self, account_id, date_from):
        return list(self.ops)


@tagged("post_install", "-at_install")
class TestFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.org = cls.env["pmk.org"].search([("is_default", "=", True)], limit=1) or \
            cls.env["pmk.org"].create({"name": "ИП Тест", "org_type": "ip"})
        cls.org.inn = "272107382162"
        cls.client = cls.env["res.partner"].create(
            {"name": "ООО «ЦК Дальний Восток»", "is_company": True, "vat": "2502075437"})
        cls.order = cls.env["sale.order"].create(
            {"partner_id": cls.client.id, "name": "01183", "pmk_org_id": cls.org.id})
        cls.env["sale.order.line"].create({
            "order_id": cls.order.id, "name": "Снегозадержатель",
            "product_id": cls.env["product.product"].create({"name": "Снегозадержатель"}).id,
            "product_uom_qty": 1, "price_unit": 11500, "tax_ids": [(5, 0, 0)]})
        cls.env["ir.config_parameter"].sudo().set_param("web.base.url", "https://erppark.ru")
        cls.account = cls.env["pmk.bank.account"].create(
            {"org_id": cls.org.id, "bank": "modulbank", "number": "40802810470010208163"})

    def setUp(self):
        super().setUp()
        self.sent = []
        self.files = []

        def send(_s, text, files, markup=None, kind="main"):
            self.files.append(files)
            self.sent.append((text, markup, kind))
            return True
        p = patch.object(type(self.env["pmk.telegram.bot"]), "pmk_send_group_files", send)
        p.start()
        self.addCleanup(p.stop)

    def _sync(self, ops):
        with patch.object(bank_account.PmkBankAccount, "_pmk_client", lambda _s: FakeBank(ops)):
            return self.account.pmk_sync()

    def test_first_sync_is_baseline_no_messages(self):
        new = self._sync([op("a", 100, "1111111111", "старое")])
        self.assertEqual(new.state, "baseline")
        self.assertEqual(self.account.bank_ref, "acc-1")
        self.assertFalse(self.sent)

    def test_new_payment_matched_and_sent_to_money_topic(self):
        self._sync([])
        pay = self._sync([op("b", 11500, "2502075437",
                             "ОПЛАТА ПО СЧЕТУ 01183 ОТ 09.10.2026 ЗА СНЕГОЗАДЕРЖАТЕЛЬ")])
        self.assertEqual(pay.sale_order_id, self.order)
        self.assertEqual(pay.partner_id, self.client)
        self.assertEqual(pay.state, "notified")
        text, markup, kind = self.sent[-1]
        self.assertEqual(kind, "money")
        self.assertIn("01183", text)
        self.assertIn("Оплачен полностью", text)
        self.assertIn("🏦 на %s" % message.org_short(self.org.name), text)
        self.assertIn("📦 снегозадержатель", text)
        self.assertNotIn("8163", text)
        self.assertIn("Открыть счёт", markup["inline_keyboard"][0][0]["text"])

    def test_own_transfer_not_sent(self):
        self._sync([])
        pay = self._sync([op("c", 5000, "272107382162", "Перевод между счетами")])
        self.assertEqual(pay.state, "internal")
        self.assertFalse(self.sent)

    def test_unknown_payer_sent_without_invoice(self):
        self._sync([])
        self._sync([op("d", 700, "7777777777", "Оплата по счету 99999")])
        self.assertIn("плательщика нет в Odoo", self.sent[-1][0])

    def test_repeat_sync_no_duplicates(self):
        self._sync([])
        o = op("e", 11500, "2502075437", "ОПЛАТА ПО СЧЕТУ 01183")
        self._sync([o])
        self._sync([o])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.env["pmk.bank.payment"].search_count([("ext_id", "=", "e")]), 1)

    def test_bank_error_recorded_no_crash(self):
        def boom(_s):
            raise bank_account.ModulbankError("нет связи")
        with patch.object(bank_account.PmkBankAccount, "_pmk_client", boom):
            self.account.pmk_sync()
        self.assertIn("нет связи", self.account.last_error)

    def test_multi_invoice_payment_mentions_others(self):
        self._sync([])
        self._sync([op("f", 11500, "2502075437", "Оплата по счету №01183, №733, №832 без НДС")])
        self.assertIn("ещё счета: 733, 832", self.sent[-1][0])

    def test_own_token_param(self):
        self.env["ir.config_parameter"].sudo().set_param("pmk_bank.tochka.astakhov.token", "jwt-a")
        acc = self.env["pmk.bank.account"].create({"org_id": self.org.id, "bank": "tochka",
            "number": "40802810000000000001", "token_param": "pmk_bank.tochka.astakhov.token"})
        self.assertEqual(type(acc._pmk_client()).__name__, "Tochka")
        self.assertEqual(acc._pmk_client().token, "jwt-a")

    def test_payment_for_several_invoices_vs_their_total(self):
        def mk(name, price):
            o = self.env["sale.order"].create({"partner_id": self.client.id, "name": name,
                                               "pmk_org_id": self.org.id})
            self.env["sale.order.line"].create({
                "order_id": o.id, "name": "Изделие", "product_uom_qty": 1, "price_unit": price,
                "product_id": self.env["product.product"].create({"name": "Изд " + name}).id,
                "tax_ids": [(5, 0, 0)]})
            return o
        a, b = mk("00733", 1000), mk("00832", 2500)
        self._sync([])
        pay = self._sync([op("g", 15000, "2502075437", "Оплата по счету №01183, №733, №832 без НДС")])
        self.assertEqual(pay.sale_order_ids, self.order | a | b)
        text = self.sent[-1][0]
        self.assertIn("Счета <b>01183, 00733, 00832</b>", text)
        self.assertIn("Оплачены полностью", text)

    def test_invoice_pdfs_attached_in_order(self):
        pdfs = [("Счёт 01183.pdf", b"%PDF-1"), ("Счёт 00733.pdf", b"%PDF-2")]
        with patch.object(type(self.env["pmk.bank.payment"]), "_pmk_invoice_pdfs", lambda _s: pdfs):
            self._sync([])
            self._sync([op("h", 11500, "2502075437", "ОПЛАТА ПО СЧЕТУ 01183")])
        self.assertEqual(self.files[-1], pdfs)

    def test_no_moysklad_no_files(self):
        self._sync([])
        pay = self._sync([op("i", 11500, "2502075437", "ОПЛАТА ПО СЧЕТУ 01183")])
        self.assertEqual(pay._pmk_invoice_pdfs(), [])     # в тестовой базе нет МоегоСклада
