# -*- coding: utf-8 -*-
"""Счета поставщиков → цены (25.10.2026). Ассистент подменён ответом по настоящему счёту
Металлсервиса № 0029200 от 23.10.2026 (трубы 40×3, 60×3, 140×5, резка) — строки дословно."""
import base64
import datetime
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..tools import match as M

INVOICE = {
    "is_invoice": True, "supplier_name": 'ООО "МЕТАЛЛСЕРВИС-ХАБАРОВСК"', "supplier_inn": "2724115793",
    "number": "0029200", "date": "2026-10-23", "payer": "ИП Чулков Владислав Витальевич",
    "total": 145358.92, "vat": 26212.27, "vat_rate": 22,
    "lines": [
        {"name": "трубы электросварные квадрат 40х3 ГОСТ дл.6000 ГОСТ8639-82", "unit": "теор.т", "qty": 0.121,
         "price": 71290, "amount": 8626.09, "note": "6шт x 6м = 36п.м", "kind": "metal",
         "catalog_name": "Труба профильная квадратная 40x40x3", "grade": "", "length_mm": 6000, "metres": 36},
        {"name": "трубы электросварные квадрат 60х3 ГОСТ дл.12000 ГОСТ13663-86", "unit": "теор.т", "qty": 1.638,
         "price": 70990, "amount": 116281.62, "note": "26шт x 12м = 312п.м пп", "kind": "metal",
         "catalog_name": "Труба профильная квадратная 60x60x3", "grade": "", "length_mm": 12000, "metres": 312},
        {"name": "угл р/пол о/т А ГОСТ 8509 Ст3пс/сп5 75х5 дл 6м (РегСоюзМет)", "unit": "т", "qty": 0.146,
         "price": 87090, "amount": 12715.14, "note": "4 шт", "kind": "metal",
         "catalog_name": "Уголок равнополочный 75x75x5", "grade": "Ст3пс/сп5", "length_mm": 6000, "metres": 0},
        {"name": "резка", "unit": "шт", "qty": 27, "price": 100, "amount": 2700, "note": "", "kind": "service"},
    ],
}


def _response(data):
    return ({"content": [{"type": "tool_use", "name": "invoice", "input": data}],
             "usage": {"input_tokens": 4000, "output_tokens": 900}}, 1.0)


@tagged("post_install", "-at_install")
class TestSupplierInvoice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("pmk_ai.api_key", "test-key")
        params.set_param("pmk_ai.budget", "100")
        cls.partner = cls.env["res.partner"].create({
            "name": "АО «Металлсервис» (тест)", "is_company": True, "vat": "2724115793"})
        cls.metre = cls.env.ref("uom.product_uom_meter")
        cls.pipe40 = cls._card("Труба профильная квадратная", "40x40x3")
        cls.pipe60 = cls._card("Труба профильная квадратная", "60x60x3")
        cls.angle = cls._card("Уголок равнополочный", "75x75x5")
        cls.Invoice = cls.env["pmk.supplier.invoice"]
        # Прайс 01.10: 72 990 ₽/т на шаблоне 40×40×3 (цена метра — по массе справочника).
        cls.old = cls.env["product.supplierinfo"].create({
            "partner_id": cls.partner.id, "product_tmpl_id": cls.pipe40.id, "sequence": 1, "min_qty": 0,
            "price": 72990 * cls.mass40 / 1000.0, "date_start": datetime.date(2026, 10, 1),
            "product_uom_id": cls.metre.id})

    @classmethod
    def _card(cls, kind, size):
        """Карточка проката под строку справочника — как заливка карточек (pmk_bridge.product_<ключ>)."""
        ref = cls.env["pmk.metal.profile"].search([("profile_type", "=", kind), ("size_label", "=", size)], limit=1)
        assert ref, (kind, size)
        key = ref.get_external_id()[ref.id].split(".", 1)[1]
        tmpl = cls.env["product.template"].create({"name": "%s %s (тест)" % (kind, size), "uom_id": cls.metre.id,
                                                   "type": "consu"})
        cls.env["ir.model.data"].create({"module": "pmk_bridge", "name": "product_%s" % key,
                                         "model": "product.template", "res_id": tmpl.id})
        ref.product_tmpl_id = tmpl
        if size == "40x40x3":
            cls.mass40 = ref.mass_per_meter
        return tmpl

    def _recognize(self, data=INVOICE):
        inv = self.Invoice.create({"file": base64.b64encode(b"%PDF-1.4 test"), "file_name": "0029200.pdf"})
        self.assertEqual(inv.state, "draft")
        inv.action_recognize()
        self.assertEqual(self.Invoice._claim(5), [inv.id])
        with patch("odoo.addons.pmk_ai.tools.claude.messages", return_value=_response(data)), \
                patch("odoo.addons.pmk_ai_mail.tools.parts.build", return_value=([], [])):
            self.Invoice._process(inv.id)
        return inv

    def test_recognize_and_match(self):
        inv = self._recognize()
        self.assertEqual(inv.state, "review", inv.error)
        self.assertEqual((inv.partner_id, inv.number, inv.date), (self.partner, "0029200", datetime.date(2026, 10, 23)))
        self.assertAlmostEqual(inv.amount_total, 145358.92)
        l40, l60, angle, cut = inv.line_ids.sorted("sequence")
        self.assertEqual((l40.product_tmpl_id, l60.product_tmpl_id, angle.product_tmpl_id),
                         (self.pipe40, self.pipe60, self.angle))
        self.assertEqual(cut.match_state, "skip")
        self.assertFalse(cut.apply)
        # 40×3: масса из счёта 0,121 т / 36 м = 3,361 кг/м (в допуске справочника) — цена метра по ней.
        self.assertAlmostEqual(l40.mass_unit, 121.0 / 36, places=3)
        self.assertAlmostEqual(l40.new_price, 71290 * 121.0 / 36 / 1000, places=2)
        self.assertAlmostEqual(l40.price_ton, 71290)
        # Сравнение с прайсом 01.10 того же поставщика.
        self.assertAlmostEqual(l40.current_price, self.old.price, places=2)
        self.assertTrue(l40.apply)
        self.assertIn("марки в счёте нет — Ст3сп", l40.match_note)
        self.assertEqual(l40.price_uom, self.metre.name)
        # Уголок без метров — масса справочника; «Ст3пс/сп5» — обычная сталь.
        self.assertTrue(angle.apply, angle.warning)
        self.assertEqual(inv.apply_count, 3)

    def test_apply_closes_previous_price(self):
        inv = self._recognize()
        inv.action_apply_prices()
        self.assertEqual(inv.state, "applied")
        l40 = inv.line_ids.sorted("sequence")[0]
        new = l40.supplierinfo_id
        self.assertEqual((new.date_start, new.partner_id, new.sequence), (datetime.date(2026, 10, 23), self.partner, 1))
        self.assertEqual(self.old.date_end, datetime.date(2026, 10, 22), "прайс 01.10 закрыт днём раньше счёта")
        self.assertEqual(new.pmk_bar_length_mm, 6000)
        seller = self.pipe40._pmk_find_seller(datetime.date(2026, 10, 24))
        self.assertEqual(seller, new, "система берёт цену из счёта")

    def test_older_invoice_does_not_cover_newer_price(self):
        """Счёт старше последней цены — свой период, новая цена остаётся действующей."""
        data = dict(INVOICE, date="2026-09-25")
        inv = self._recognize(data)
        inv.action_apply_prices()
        new = inv.line_ids.sorted("sequence")[0].supplierinfo_id
        self.assertEqual(new.date_end, datetime.date(2026, 9, 30))
        self.assertFalse(self.old.date_end)
        self.assertEqual(self.pipe40._pmk_find_seller(datetime.date(2026, 10, 5)), self.old)

    def test_partner_with_prices_preferred(self):
        """Одна фирма двумя карточками: с ИНН без цен (из МойСклада) и с ценами без ИНН —
        счёт идёт поставщику с ценами; выбор запоминается для следующих счетов с этим ИНН."""
        Partner = self.env["res.partner"]
        twin = Partner.create({"name": "ООО «ДРУГОЙСТАЛЬ-ХАБАРОВСК»", "is_company": True, "vat": "2700000001"})
        priced = Partner.create({"name": "АО «Другойсталь», филиал Хабаровск", "is_company": True})
        self.env["product.supplierinfo"].create({
            "partner_id": priced.id, "product_tmpl_id": self.pipe60.id, "price": 300,
            "date_start": datetime.date(2026, 10, 1), "product_uom_id": self.metre.id})
        data = dict(INVOICE, supplier_name='ООО "ДРУГОЙСТАЛЬ-ХАБАРОВСК"', supplier_inn="2700000001", number="1")
        inv = self._recognize(data)
        self.assertEqual(inv.partner_id, priced)
        self.assertNotEqual(inv.partner_id, twin)
        inv.partner_id = twin          # проверяющий поправил — строки пересчитались
        self.assertFalse(inv.line_ids.sorted("sequence")[1].current_price)
        inv.partner_id = priced
        inv.action_apply_prices()
        again = self._recognize(dict(data, number="2", supplier_name="Другая подпись"))
        self.assertEqual(again.partner_id, priced, "запомнено по ИНН из прошлого счёта")

    def test_wrong_kind_refused(self):
        """Ассистент назвал «квадрат 40х3» круглой трубой — правила не дают положить цену."""
        data = dict(INVOICE, lines=[dict(INVOICE["lines"][0], catalog_name="Труба круглая 40x3")])
        inv = self._recognize(data)
        line = inv.line_ids
        self.assertEqual(line.match_state, "none")
        self.assertFalse(line.apply)
        self.assertTrue(line.match_note)

    def test_manual_choice_remembered(self):
        data = dict(INVOICE, lines=[dict(INVOICE["lines"][0], catalog_name="")])
        data["lines"][0]["name"] = "профтруба 40/40/3 спец"
        inv = self._recognize(data)
        line = inv.line_ids
        self.assertEqual(line.match_state, "none")
        line.product_tmpl_id = self.pipe40
        self.assertEqual(line.match_state, "manual")
        self.assertTrue(line.new_price)
        line.apply = True
        inv.action_apply_prices()
        again = self._recognize(dict(data, number="0029999"))
        self.assertEqual(again.line_ids.product_tmpl_id, self.pipe40)
        self.assertEqual(again.line_ids.match_state, "manual")

    def test_duplicate_and_not_invoice(self):
        self._recognize()
        dup = self._recognize()
        self.assertEqual(dup.state, "skipped")
        self.assertIn("Повтор", dup.reason)
        other = self._recognize({"is_invoice": False, "reason": "УПД, не счёт"})
        self.assertEqual((other.state, other.reason), ("skipped", "УПД, не счёт"))

    def test_invoice_without_metal_skipped(self):
        """Перевозка и услуги — счёт без металла сам уходит в «Не счёт» (Антон 25.10.2026)."""
        data = dict(INVOICE, number="777", lines=[
            {"name": "Перевозка сборного груза", "unit": "шт", "qty": 1, "price": 4927, "amount": 4927,
             "kind": "service"},
            {"name": "Расширитель 26067RU", "unit": "шт", "qty": 2, "price": 100, "amount": 200, "kind": "other"}])
        inv = self._recognize(data)
        self.assertEqual(inv.state, "skipped")
        self.assertIn("нет металлопроката", inv.reason)
        self.assertEqual(len(inv.line_ids), 2, "строки остаются — видно, что было в счёте")

    def test_sheet_price_per_sheet(self):
        """Счёт Металлсервиса 0029346 от 26.10.2026: 4 листа 3×1500×6000 на 0,872 т по 73 390 ₽/т.
        Было: новая цена за лист (по массе справочника) против текущей за м² — «+755 %», НДС 0 %.
        Стало: масса листа поставщика (218 кг), цена листа 15 999,02, текущая — тоже за лист."""
        ref = self.env["pmk.metal.sheet"].search([("sheet_type", "=", "Гладкий"), ("thickness_mm", "=", 3)], limit=1)
        self.assertTrue(ref)
        key = ref.get_external_id()[ref.id].split(".", 1)[1]
        sqm = self.env.ref("uom.product_uom_square_meter")
        sheet_uom = self.env["uom.uom"]._pmk_sheet_uom("1500x6000")
        self.assertTrue(sheet_uom)
        tmpl = self.env.ref("pmk_bridge.product_%s" % key, raise_if_not_found=False)
        if not tmpl:
            tmpl = self.env["product.template"].create({"name": "Лист гладкий 3 мм (тест)", "uom_id": sqm.id,
                                                        "type": "consu"})
            self.env["ir.model.data"].create({"module": "pmk_bridge", "name": "product_%s" % key,
                                             "model": "product.template", "res_id": tmpl.id})
        self.assertTrue(tmpl._pmk_is_sqm())
        ref.product_tmpl_id = tmpl
        tmpl.seller_ids.unlink()
        old = self.env["product.supplierinfo"].create({
            "partner_id": self.partner.id, "product_tmpl_id": tmpl.id, "sequence": 1, "min_qty": 0,
            "price": 16369.62, "date_start": datetime.date(2026, 10, 1), "product_uom_id": sheet_uom.id})
        data = dict(INVOICE, number="0029346", date="2026-10-26", total=63996.08, vat=11540.28, vat_rate=0, lines=[
            {"name": "лист г/к ГОСТ 16523-97 Ст3пс/сп5 3х1500х6000 (ММК) н/обр", "unit": "т", "qty": 0.872,
             "price": 73390, "amount": 63996.08, "kind": "metal", "catalog_name": "Лист 3x1500x6000",
             "grade": "Ст3пс/сп5", "length_mm": 0, "metres": 0, "note": "4 шт"}])
        inv = self._recognize(data)
        self.assertEqual(inv.vat_rate, 22, "ставка из сумм, раз в счёте её нет")
        line = inv.line_ids
        self.assertEqual((line.product_tmpl_id, line.uom_id), (tmpl, sheet_uom))
        self.assertAlmostEqual(line.mass_unit, 218.0, places=3)
        self.assertAlmostEqual(line.new_price, 63996.08 / 4, places=2)
        self.assertAlmostEqual(line.current_price, old.price, places=2)
        self.assertAlmostEqual(line.diff_pct, (63996.08 / 4 / 16369.62 - 1) * 100, places=1)
        self.assertTrue(line.apply, line.warning)
        inv.action_apply_prices()
        self.assertEqual(line.supplierinfo_id.product_uom_id, sheet_uom)
        self.assertAlmostEqual(line.supplierinfo_id.price, 15999.02, places=2)

    def _sheet_card(self, kind, th):
        """Карточка листа в м² под строку справочника — как заливка (pmk_bridge.product_<ключ>)."""
        ref = self.env["pmk.metal.sheet"].search([("sheet_type", "=", kind), ("thickness_mm", "=", th)], limit=1)
        self.assertTrue(ref, (kind, th))
        key = ref.get_external_id()[ref.id].split(".", 1)[1]
        tmpl = self.env.ref("pmk_bridge.product_%s" % key, raise_if_not_found=False)
        if not tmpl:
            tmpl = self.env["product.template"].create({"name": "Лист %s %s (тест)" % (kind, th), "type": "consu",
                                                        "uom_id": self.env.ref("uom.product_uom_square_meter").id})
            self.env["ir.model.data"].create({"module": "pmk_bridge", "name": "product_%s" % key,
                                             "model": "product.template", "res_id": tmpl.id})
        ref.product_tmpl_id = tmpl
        tmpl.seller_ids.unlink()
        return tmpl

    def test_painted_sheet_per_sqm(self):
        """Счёт ПРОФИЛЬ ДВ ПДФР-007493 от 02.10.2026: «Лист гладкий 0.65 (RAL 3005, Красное вино)
        (710х1250)», 11 шт по 528,95. Крашеный лист — это оцинковка 0,65 (как в доборах и
        вентзонтах); заготовка не габарит-упаковка — цена за м²: 528,95 / 0,8875 = 596,0."""
        tmpl = self._sheet_card("Оцинкованный", 0.65)
        data = dict(INVOICE, number="ПДФР-007493", date="2026-10-02", total=12210.55, vat=2201.9, lines=[
            {"name": "Лист гладкий 0.65 (RAL 3005, Красное вино) (710х1250)", "unit": "шт", "qty": 11,
             "price": 528.95, "amount": 5818.45, "kind": "metal", "catalog_name": "Лист 0.65x710x1250",
             "grade": "", "length_mm": 0, "metres": 0, "note": ""},
            {"name": "Лист гладкий 0.65 (RAL 3005, Красное вино) (780х1250)", "unit": "шт", "qty": 11,
             "price": 581.1, "amount": 6392.1, "kind": "metal", "catalog_name": "Лист 0.65x780x1250",
             "grade": "", "length_mm": 0, "metres": 0, "note": ""}])
        inv = self._recognize(data)
        a, b = inv.line_ids.sorted("sequence")
        for line, area in ((a, 0.71 * 1.25), (b, 0.78 * 1.25)):
            self.assertEqual(line.product_tmpl_id, tmpl, line.match_note)
            self.assertFalse(line.uom_id, "цена — за м² карточки")
            self.assertAlmostEqual(line.new_price, line.price / area, places=2)
            self.assertTrue(line.apply, line.warning)
        self.assertAlmostEqual(a.new_price, 596.0, places=1)
        inv.action_apply_prices()
        self.assertEqual(a.supplierinfo_id.product_uom_id, tmpl.uom_id)

    def test_second_grade_not_applied(self):
        """Второй сорт не покупаем (Антон 26.10.2026) — строка разбирается, но цену не пишем."""
        self._sheet_card("Оцинкованный", 0.7)
        data = dict(INVOICE, number="2СОРТ", lines=[
            {"name": "Лист оцинк. 0,7х1250х2500 08пс (2 сорт )", "unit": "шт", "qty": 10, "price": 1400,
             "amount": 14000, "kind": "metal", "catalog_name": "Лист оцинкованный 0.7x1250x2500",
             "grade": "08пс (2 сорт )", "length_mm": 0, "metres": 0, "note": ""}])
        line = self._recognize(data).line_ids
        self.assertFalse(line.apply)
        self.assertEqual(line.match_state, "skip")
        self.assertIn("второй сорт", line.match_note)

    def test_galvanized_sheet_found(self):
        """Оцинковка (26.10.2026): разборщик искал вид «Оцинкованный тонколистовой», а в справочнике
        «Оцинкованный» — не находилась никогда; 1,5 мм в справочнике не было; «Ст08пс» не опознавалась."""
        from odoo.addons.pmk_bridge.tools import grades
        from ..models.prices import invoice_grade
        m = M.matcher(self.env)
        for th in (0.5, 1.5, 3):
            res = m.match("Лист оцинкованный %sx1250x2500" % th)
            self.assertEqual((res["status"], res["matches"][0]["type"]), ("совпало", "Оцинкованный"), res)
            self.assertEqual(res["nums"], [th])
        self.assertEqual(invoice_grade("Ст08пс"), "08пс")
        self.assertIn("08кп", grades.grade_family("08пс"), "«08кп/пс» прайса и «Ст08пс» счёта — одна цена")

    def test_kind_and_size_rules(self):
        self.assertEqual(M.expected_kind("трубы электросварные квадрат 40х3")[0], "Труба профильная квадратная")
        self.assertEqual(M.expected_kind("Квадрат 16 Ст3")[0], "Квадрат")
        self.assertEqual(M.expected_kind("угл р/пол 75х5")[0], "Уголок")
        self.assertEqual(M.size_numbers("трубы квадрат 60х3 ГОСТ дл.12000 ГОСТ13663-86"), {60.0, 3.0})
        self.assertEqual(M.bar_length_mm("угл 75х5 дл 6м"), 6000)
        self.assertEqual(M.metres_from_note("26шт x 12м = 312п.м пп"), 312)

    def test_enqueue_from_mail(self):
        server = self.env["mail.client.server"].create({
            "name": "тест", "imap_host": "mail.invalid", "auth_mode": "master", "master_user": "m"})
        account = self.env["mail.client.account"].create({
            "name": "Заявки (тест)", "email": "zayavki-si@example.org", "server_id": server.id,
            "user_id": self.env.uid})
        inbox = self.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": account.id, "imap_path": "INBOX", "role": "inbox"})
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("pmk_ai_mail.account", "zayavki-si@example.org")
        params.set_param("pmk_supplier_invoice.since", "2026-01-01 00:00:00")

        def letter(uid, subject, att=True):
            return self.env["mail.client.message"].create({
                "account_id": account.id, "folder_id": inbox.id, "imap_uid": uid, "subject": subject,
                "email_from": "kutilov.ea@mc.example", "date": fields.Datetime.now(), "has_attachment": att,
                "body_state": "fetched", "message_id": "<si%s@test>" % uid, "thread_key": "<si%s@test>" % uid})
        bill = letter(1, "Cчет Сч-0029200 от 23.10.26,  ООО МЕТАЛЛСЕРВИС-ХАБАРОВСК")
        letter(2, "Re: Cчет Сч-0029200 от 23.10.26")
        letter(3, "Прайс на октябрь")
        letter(4, "Счёт без вложения", att=False)
        self.assertEqual(self.Invoice._enqueue(), 1)
        inv = self.Invoice.search([("message_id", "=", bill.id)])
        self.assertEqual(inv.state, "queued")
        self.assertEqual(self.Invoice._enqueue(), 0, "второй раз то же письмо не берём")

    def test_attachment_fetch_failed_is_error(self):
        """Вложение не скачалось — «Ошибка» (повторить), а не «Не счёт» навсегда."""
        inv = self.Invoice.create({"subject": "Cчет Сч-1", "email_from": "x@mc.example"})
        inv.state = "running"
        with patch.object(type(inv), "_files", return_value=([], [("счёт.pdf", "IMAP: timeout")])):
            self.Invoice._process(inv.id)
        self.assertEqual(inv.state, "error")
        self.assertIn("не скачались", inv.error)

    def test_worker_jobs(self):
        inv = self.Invoice.create({"file": base64.b64encode(b"%PDF"), "file_name": "a.pdf"})
        inv.action_recognize()
        jobs = self.env["pmk.ai.chat"]._worker_jobs(4)
        self.assertIn(("pmk.supplier.invoice", "_process", inv.id), jobs)
