# -*- coding: utf-8 -*-
"""Счёт покупателю по-нашему (разбор UX, шаг З-9, 09.10.2026), pmk_orders.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные.

Решения Антона 09.10: счёт создаётся на этапе расчёта (кнопкой «Счёт»),
меняется и дополняется, прописывают условия, согласуют с руководителем — и
только потом отправляют. «Автоотправки не нужны, перенос либо руками, либо
после нажатия на кнопку «Отправить КП»».

Что ловим:
  • «Счёт» в расчёте — черновик (один на сделку; повтор открывает тот же;
    черновик другого расчёта переключается, а не множится); без сделки или
    клиента — ошибка словами; отправленный — открывается с подсказкой «ред. N»;
  • черновик идёт за расчётом (состав, количество, цена, новое и удалённое
    изделие) без редакций; услуги не трогаются; отправленный — не меняется,
    на нём «расчёт изменился после отправки»;
  • строки-изделия в счёте только для чтения на сервере (цена, количество,
    название, удаление — ошибка), услуги правятся и удаляются; «Добавить
    услугу» ставит товар «Услуга», налог — режим организации;
  • условия (оплата, срок изготовления, доставка + адрес, прочее)
    сохраняются, переносятся в редакцию, лежат в снимке; строки для печати;
  • согласование: «На согласование» — задача руководителю без письма;
    «Согласовано» и «Вернуть на доработку» — только группе (AccessError);
    правка после «Согласован» (в счёте или в расчёте) — снова «Черновик»;
    отправка без согласования не блокируется, видна пометка;
  • «Отправить КП» → «Отправлен» (черновик или новый), сделка в «КП
    отправлено»; перенос руками: черновик → «Отправлен», без счёта — НЕ
    создаётся, заметка; после отправки правка расчёта → «ред. N» при
    следующей отправке, услуги переходят в редакцию, подпись без услуг;
  • «Выиграно» без счёта — строка планировщика без счёта, счёт не
    заводится; из черновика — в работу;
  • итог: «в том числе НДС 22%: …» / «Без НДС (УСН)»; группа налога режима —
    «НДС 22%», не «Налог 15%»;
  • «Новое» и «Дублировать» убраны; спрятанное возвращает «Убранное»;
    залитая кнопка одна в каждом состоянии; писем клиенту нет ни одного.

Глазами (все состояния счёта, окно «Отправить КП», расчёт, сделка, светлая и
тёмная тема) — основной агент на копии.
"""
import re

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.pmk_org import hooks as org_hooks

from .test_step_z2_invoice import Z2Common

APPROVER = "pmk_orders.group_invoice_approver"


@tagged("post_install", "-at_install")
class TestStepZ9Invoice(Z2Common):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver = new_test_user(
            cls.env, login="pmkz9_boss", name="Руководитель (шаг З-9)",
            groups="base.group_user,sales_team.group_sale_manager," + APPROVER)
        cls.extra = cls.env.ref("pmk_orders.product_extra_service").product_variant_id

    # ─── помощники ──────────────────────────────────────────────────────
    def _draft(self, deal=None, spec=None, user=None):
        deal = deal or self._deal()
        spec = spec or deal.pmk_spec_id or self._spec(deal)
        spec.with_user(user or self.manager).action_pmk_invoice()
        return deal, spec, self._invoices(deal)

    def _mails(self):
        return self.env["mail.mail"].sudo().search_count([])

    def _spec_lines(self, invoice):
        return invoice.order_line.filtered("pmk_from_spec").sorted("sequence")

    def _add_service(self, invoice, name="Доставка", price=1500.0, qty=1):
        invoice.with_user(self.manager).write({"order_line": [Command.create({
            "product_id": self.extra.id, "name": name, "product_uom_qty": qty,
            "price_unit": price})]})
        return invoice.order_line.filtered(lambda line: line.name == name)

    # ─── «Счёт» в расчёте ───────────────────────────────────────────────
    def test_invoice_button_creates_one_draft(self):
        mails = self._mails()
        deal, spec, invoice = self._draft()
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.state, "draft", "Черновик — не отправлен.")
        self.assertEqual(invoice.pmk_status, "draft")
        self.assertEqual(invoice.pmk_approval, "none")
        self.assertFalse(invoice.pmk_sent_date)
        self.assertEqual(invoice.pmk_spec_id, spec)
        self.assertEqual(invoice.partner_id, self.client)
        self.assertEqual(invoice.pmk_org_id, self.org_vat)
        self.assertEqual(self._spec_lines(invoice).mapped("name"),
                         ["Секция ограждения ОГ-1", "Ферма Ф-1"])
        self.assertIn("Пробное изделие", invoice.pmk_skip_text or "", "Без цены — сигнал.")
        self.assertIn("Черновик счёта", self._notes(deal))
        self.assertNotEqual(deal.stage_id, self.stage_kp, "Сделку кнопка «Счёт» не двигает.")
        # Повтор — тот же счёт, открывается формой без «Новое».
        action = spec.with_user(self.manager).action_pmk_invoice()
        self.assertEqual(self._invoices(deal), invoice)
        self.assertEqual(action["res_id"], invoice.id)
        self.assertEqual(action["res_model"], "sale.order")
        self.assertFalse(action["context"]["create"])
        self.assertEqual(self._mails(), mails, "Писем нет.")

    def test_invoice_button_needs_deal_and_client(self):
        lonely = self._spec(False)
        with self.assertRaises(UserError):
            lonely.with_user(self.manager).action_pmk_invoice()
        deal = self._deal(partner_id=False)
        spec = self._spec(deal, partner_id=False)
        with self.assertRaises(UserError):
            spec.with_user(self.manager).action_pmk_invoice()
        self.assertFalse(self._invoices(deal))

    def test_invoice_button_switches_draft_to_other_spec(self):
        deal = self._deal()
        first = self._spec(deal, products=[("Вариант А", 1, 1000.0)])
        second = self._spec(deal, products=[("Вариант Б", 2, 3000.0)])
        _deal, _spec, invoice = self._draft(deal, first)
        service = self._add_service(invoice)
        second.with_user(self.manager).action_pmk_invoice()
        self.assertEqual(self._invoices(deal), invoice, "Не плодим счета: тот же черновик.")
        self.assertEqual(invoice.pmk_spec_id, second)
        self.assertEqual(self._spec_lines(invoice).mapped("name"), ["Вариант Б"])
        self.assertTrue(service.exists(), "Услуга осталась.")
        self.assertAlmostEqual(invoice.amount_total, 6000.0 + 1500.0, places=2)
        self.assertIn("переключён", self._notes(deal))

    def test_invoice_button_on_sent_invoice(self):
        deal, spec, invoice = self._draft()
        self._send_kp(deal, spec)
        self.assertEqual(invoice.state, "sent")
        spec.product_ids[:1].with_user(self.manager).write({"price_customer_unit": 4800.0})
        action = spec.with_user(self.manager).action_pmk_invoice()
        self.assertEqual(action["tag"], "display_notification")
        self.assertIn("ред. 2", action["params"]["message"])
        self.assertEqual(action["params"]["next"]["res_id"], invoice.id)
        self.assertEqual(invoice.pmk_revision, 1, "Кнопка «Счёт» редакцию не делает.")
        self.assertIn("ред. 2", invoice.pmk_spec_changed_text)

    # ─── Черновик идёт за расчётом ──────────────────────────────────────
    def test_draft_follows_spec(self):
        deal, spec, invoice = self._draft()
        service = self._add_service(invoice)
        section, truss, probe = spec.product_ids.sorted("sequence")
        spec.with_user(self.manager).write({"product_ids": [
            Command.update(section.id, {"qty": 10, "price_customer_unit": 4600.0}),
            Command.delete(truss.id),
            Command.update(probe.id, {"price_customer_unit": 700.0}),
            Command.create({"name": "Опора О-1", "qty": 2, "price_customer_unit": 1000.0,
                            "sequence": 40}),
        ]})
        lines = self._spec_lines(invoice)
        self.assertEqual(lines.mapped("name"),
                         ["Секция ограждения ОГ-1", "Пробное изделие", "Опора О-1"])
        self.assertEqual(lines.mapped("product_uom_qty"), [10, 1, 2])
        self.assertAlmostEqual(invoice.amount_total, 46000 + 700 + 2000 + 1500, places=2)
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.pmk_revision, 1, "Черновик — без редакций.")
        self.assertFalse(self._snapshots(invoice))
        self.assertTrue(service.exists())
        self.assertAlmostEqual(service.price_unit, 1500.0)
        self.assertFalse(invoice.pmk_skip_text)
        # Правка изделия прямо (окно изделия — запись изделия, не расчёта).
        section.with_user(self.manager).write({"name": "Секция ОГ-1 (оцинк.)"})
        self.assertIn("Секция ОГ-1 (оцинк.)", self._spec_lines(invoice).mapped("name"))
        section.with_user(self.manager).unlink()
        self.assertNotIn("Секция ОГ-1 (оцинк.)", self._spec_lines(invoice).mapped("name"))
        # Клиент и организация — тоже.
        spec.with_user(self.manager).write({"pmk_org_id": self.org_usn.id})
        self.assertEqual(invoice.pmk_org_id, self.org_usn)
        self.assertEqual(self._spec_lines(invoice).tax_ids, self.taxes["usn0"])

    def test_sent_invoice_does_not_follow(self):
        deal, spec, invoice = self._draft()
        self._send_kp(deal, spec)
        total = invoice.amount_total
        spec.product_ids.filtered("price_customer_unit")[:1].with_user(self.manager).write(
            {"price_customer_unit": 9999.0})
        self.assertAlmostEqual(invoice.amount_total, total, msg="Отправленный не меняется.")
        self.assertIn("изменился после отправки", invoice.pmk_spec_changed_text)

    # ─── Строки ─────────────────────────────────────────────────────────
    def test_spec_lines_read_only(self):
        deal, spec, invoice = self._draft()
        line = self._spec_lines(invoice)[:1]
        for vals in ({"price_unit": 1.0}, {"product_uom_qty": 99}, {"name": "Другое"}):
            with self.subTest(vals=vals), self.assertRaises(UserError):
                line.with_user(self.manager).write(vals)
        with self.assertRaises(UserError):
            line.with_user(self.manager).unlink()
        with self.assertRaises(UserError):
            invoice.with_user(self.manager).write({"order_line": [Command.update(line.id, {"price_unit": 2.0})]})
        # Флаг пересборки без sudo не действует (контекст задаёт браузер).
        with self.assertRaises(UserError):
            line.with_user(self.manager).with_context(pmk_spec_lines_sync=True).write({"price_unit": 3.0})
        # То же значение и порядок — можно.
        line.with_user(self.manager).write({"price_unit": line.price_unit, "sequence": 99})
        self.assertEqual(line.sequence, 99)
        # Услуга правится и удаляется.
        service = self._add_service(invoice)
        service.with_user(self.manager).write({"price_unit": 2500.0, "name": "Доставка до объекта"})
        self.assertAlmostEqual(service.price_unit, 2500.0)
        service.with_user(self.manager).unlink()
        self.assertFalse(service.exists())

    def test_add_service_line(self):
        deal, spec, invoice = self._draft()
        Line = self.env["sale.order.line"].with_user(self.manager)
        defaults = Line.with_context(pmk_add_service=True).default_get(["product_id", "display_type"])
        self.assertEqual(defaults.get("product_id"), self.extra.id)
        self.assertFalse(Line.default_get(["product_id"]).get("product_id"),
                         "Без кнопки — как у ядра.")
        with Form(invoice.with_user(self.manager)) as form:
            with form.order_line.new() as line:
                line.product_id = self.extra
                line.name = "Монтаж"
                line.price_unit = 12000.0
        mount = invoice.order_line.filtered(lambda l: l.name == "Монтаж")
        self.assertEqual(mount.product_id, self.extra)
        self.assertFalse(mount.pmk_from_spec)
        self.assertEqual(mount.tax_ids, self.taxes["vat22"], "Налог — режим организации.")
        self.assertAlmostEqual(mount.price_total, 12000.0, msg="Цена с налогом.")
        # Строка без товара у счёта из расчёта — «Услуга».
        invoice.write({"order_line": [Command.create({"name": "Разгрузка", "product_uom_qty": 1,
                                                      "price_unit": 500.0})]})
        unload = invoice.order_line.filtered(lambda l: l.name == "Разгрузка")
        self.assertEqual(unload.product_id, self.extra)
        self.assertEqual(self.extra.type, "service")
        self.assertFalse(self.extra.purchase_ok, "Перепродажа отложена: без закупки.")

    # ─── Условия ────────────────────────────────────────────────────────
    def test_terms_saved_and_kept(self):
        deal, spec, invoice = self._draft()
        term = self.env["account.payment.term"].search([], limit=1)
        invoice.with_user(self.manager).write({
            "payment_term_id": term.id,
            "pmk_payment_note": "50% предоплата, 50% перед отгрузкой",
            "pmk_lead_days": 20, "pmk_lead_from": "payment",
            "pmk_delivery": "delivery", "pmk_delivery_address": "Хабаровск, ул. Заводская, 1",
            "note": "Гарантия 12 месяцев",
        })
        self.assertEqual(invoice.pmk_lead_text, "20 раб. дней с момента оплаты")
        self.assertEqual(invoice.pmk_delivery_text, "Доставка: Хабаровск, ул. Заводская, 1")
        invoice.pmk_lead_days = 3
        self.assertEqual(invoice.pmk_lead_text, "3 раб. дня с момента оплаты")
        invoice.pmk_lead_days = 21
        self.assertEqual(invoice.pmk_lead_text, "21 раб. день с момента оплаты")
        invoice.pmk_delivery = "pickup"
        self.assertEqual(invoice.pmk_delivery_text, "Самовывоз")
        self._send_kp(deal, spec)
        spec.product_ids[:1].write({"price_customer_unit": 4700.0})
        self._send_kp(deal, spec)
        self.assertEqual(invoice.pmk_revision, 2)
        self.assertEqual(invoice.pmk_payment_note, "50% предоплата, 50% перед отгрузкой",
                         "Условия — в новой редакции.")
        self.assertEqual(invoice.payment_term_id, term)
        snapshot = self._snapshots(invoice)
        self.assertEqual(snapshot.pmk_lead_days, 21, "Снимок хранит условия.")
        self.assertEqual(snapshot.pmk_delivery, "pickup")
        with self.assertRaises(UserError):
            snapshot.with_user(self.manager).write({"pmk_lead_days": 5})

    def test_delivery_address_onchange(self):
        self.client.write({"city": "Хабаровск", "street": "ул. Тестовая, 5"})
        deal, spec, invoice = self._draft()
        with Form(invoice.with_user(self.manager)) as form:
            form.pmk_delivery = "delivery"
            self.assertIn("Хабаровск", form.pmk_delivery_address or "")

    # ─── Согласование ───────────────────────────────────────────────────
    def test_approval_flow(self):
        mails = self._mails()
        deal, spec, invoice = self._draft()
        invoice.with_user(self.manager).action_pmk_to_approval()
        self.assertEqual(invoice.pmk_approval, "pending")
        self.assertEqual(invoice.pmk_status, "approval")
        activity = invoice.activity_ids.filtered(
            lambda a: a.activity_type_id == self.env.ref("pmk_orders.mail_activity_type_invoice_approve"))
        self.assertEqual(len(activity), 1, "Руководителю — задача «Согласовать счёт».")
        self.assertTrue(activity.user_id.has_group(APPROVER))
        self.assertEqual(self._mails(), mails, "Задача без письма.")
        # Менеджер согласовать не может — и кнопки у него нет.
        self.assertFalse(invoice.with_user(self.manager).pmk_is_approver)
        with self.assertRaises(AccessError):
            invoice.with_user(self.manager).action_pmk_approve()
        self.assertTrue(invoice.with_user(self.approver).pmk_is_approver)
        invoice.with_user(self.approver).action_pmk_approve()
        self.assertEqual(invoice.pmk_approval, "approved")
        self.assertEqual(invoice.pmk_status, "approved")
        self.assertFalse(invoice.activity_ids.filtered(lambda a: a.id == activity.id),
                         "Задача закрыта.")
        # Правка счёта после согласования — снова «Черновик».
        invoice.with_user(self.manager).write({"pmk_lead_days": 15})
        self.assertEqual(invoice.pmk_approval, "none")
        self.assertEqual(invoice.pmk_status, "draft")
        # Правка расчёта после согласования — тоже.
        invoice.with_user(self.approver).action_pmk_approve()
        spec.product_ids[:1].with_user(self.manager).write({"qty": 15})
        self.assertEqual(invoice.pmk_approval, "none")
        invoice.invalidate_recordset(["message_ids"])
        self.assertIn("изменён после согласования", " ".join(str(m.body) for m in invoice.message_ids))
        # Согласованный уходит без пометки.
        invoice.with_user(self.approver).action_pmk_approve()
        self._send_kp(deal, spec)
        self.assertEqual(invoice.state, "sent")
        self.assertFalse(invoice.pmk_approval_signal)
        self.assertEqual(self._mails(), mails, "Писем нет.")

    def test_return_to_rework(self):
        deal, spec, invoice = self._draft()
        invoice.with_user(self.manager).action_pmk_to_approval()
        with self.assertRaises(AccessError):
            invoice.with_user(self.manager).action_pmk_return()
        action = invoice.with_user(self.approver).action_pmk_return()
        wizard = self.env[action["res_model"]].with_user(self.approver).with_context(
            action["context"]).create({"comment": "Срок 15 дней, не 20"})
        wizard.action_return()
        self.assertEqual(invoice.pmk_approval, "none")
        rework = invoice.activity_ids.filtered(
            lambda a: a.activity_type_id == self.env.ref("pmk_orders.mail_activity_type_invoice_rework"))
        self.assertEqual(rework.user_id, self.manager)
        self.assertIn("Срок 15 дней", str(rework.note))
        invoice.invalidate_recordset(["message_ids"])
        self.assertIn("Срок 15 дней", " ".join(str(m.body) for m in invoice.message_ids))

    def test_send_without_approval_not_blocked(self):
        deal, spec, invoice = self._draft()
        invoice.with_user(self.manager).action_pmk_to_approval()
        self._send_kp(deal, spec)
        self.assertEqual(invoice.state, "sent", "Отправка без согласования не блокируется.")
        self.assertEqual(deal.stage_id, self.stage_kp)
        self.assertEqual(invoice.pmk_approval_signal, "Отправлен без согласования")
        self.assertFalse(invoice.activity_ids.filtered(
            lambda a: a.activity_type_id == self.env.ref("pmk_orders.mail_activity_type_invoice_approve")),
            "Задача «Согласовать» закрыта отправкой.")
        self.assertIn("Счёт не согласован", self._notes(deal))
        unapproved = self.env["sale.order"].search([
            ("state", "in", ("sent", "sale")), ("pmk_approval", "!=", "approved"),
            ("pmk_is_revision", "=", False)])
        self.assertIn(invoice, unapproved, "Фильтр «Отправлены без согласования».")

    # ─── «Отправить КП» и перенос руками ────────────────────────────────
    def test_kp_send_marks_draft_sent(self):
        deal, spec, invoice = self._draft()
        service = self._add_service(invoice)
        self._send_kp(deal, spec)
        self.assertEqual(deal.stage_id, self.stage_kp)
        self.assertEqual(invoice.state, "sent")
        self.assertEqual(invoice.pmk_status, "sent")
        self.assertTrue(invoice.pmk_sent_date)
        self.assertEqual(self._invoices(deal), invoice, "Тот же счёт.")
        self.assertTrue(service.exists())

    def test_drag_marks_draft_sent(self):
        deal, spec, invoice = self._draft()
        deal.with_user(self.manager).write({"stage_id": self.stage_kp.id})
        self.assertEqual(invoice.state, "sent")
        self.assertIn("руками", self._notes(deal))
        invoice.invalidate_recordset(["message_ids"])
        self.assertIn("вне системы", " ".join(str(m.body) for m in invoice.message_ids))

    def test_drag_without_invoice_creates_nothing(self):
        deal = self._deal()
        self._spec(deal)
        deal.with_user(self.manager).write({"stage_id": self.stage_kp.id})
        self.assertEqual(deal.stage_id, self.stage_kp)
        self.assertFalse(self._invoices(deal), "Перенос руками счёт не заводит.")
        self.assertIn("кнопкой «Счёт» в расчёте", self._notes(deal))
        # Сделка, заведённая сразу в «КП отправлено», тоже счёта не получает.
        fresh = self._deal(stage_id=self.stage_kp.id)
        self._spec(fresh)
        self.assertFalse(self._invoices(fresh))

    def test_revision_keeps_services(self):
        deal, spec, invoice = self._draft()
        service = self._add_service(invoice)
        self._send_kp(deal, spec)
        signature = invoice._pmk_signature()
        # Услуга в подпись не входит: правка услуги не «меняет расчёт».
        service.with_user(self.manager).write({"price_unit": 1800.0})
        self.assertEqual(invoice._pmk_signature(), signature)
        self.assertFalse(invoice.pmk_spec_changed_text)
        self._send_kp(deal, spec)
        self.assertEqual(invoice.pmk_revision, 1, "Расчёт не менялся — редакции нет.")
        spec.product_ids.filtered("price_customer_unit")[:1].write({"price_customer_unit": 4700.0})
        self._send_kp(deal, spec)
        self.assertEqual(invoice.pmk_revision, 2)
        self.assertIn("Доставка", invoice.order_line.mapped("name"), "Услуга — в новой редакции.")
        snapshot = self._snapshots(invoice)
        self.assertIn("Доставка", snapshot.order_line.mapped("name"), "И в прежней.")
        self.assertEqual(invoice.state, "sent")

    def test_won_without_invoice_creates_none(self):
        deal = self._deal()
        self._spec(deal)
        deal.with_user(self.manager).action_set_won()
        self.assertFalse(self._invoices(deal), "«Выиграно» счёт не заводит.")
        row = self._rows(deal)
        self.assertEqual(len(row), 1)
        self.assertFalse(row.pmk_sale_order_id)
        self.assertIn("без счёта", self._notes(deal))

    def test_won_from_draft_confirms(self):
        deal, spec, invoice = self._draft()
        deal.with_user(self.manager).action_set_won()
        self.assertEqual(invoice.state, "sale")
        self.assertEqual(invoice.pmk_status, "sale")
        self.assertEqual(self._rows(deal).pmk_sale_order_id, invoice)
        self.assertIn("не отмечался", self._notes(deal))

    # ─── Итог и налог ───────────────────────────────────────────────────
    def test_tax_text(self):
        deal, spec, invoice = self._draft(spec=None)
        self.assertTrue(invoice.pmk_tax_text.startswith("в том числе НДС 22%:"), invoice.pmk_tax_text)
        self.assertIn(invoice.currency_id.symbol, invoice.pmk_tax_text)
        usn_deal = self._deal(org=self.org_usn)
        usn_spec = self._spec(usn_deal, org=self.org_usn)
        _d, _s, usn_invoice = self._draft(usn_deal, usn_spec)
        self.assertEqual(usn_invoice.pmk_tax_text, "Без НДС (УСН)")

    def test_tax_group_named_by_regime(self):
        vat = self.taxes["vat22"]
        country = vat.country_id or self.company.account_fiscal_country_id or self.env.ref("base.ru")
        shared = self.env["account.tax.group"].create({
            "name": "Налог 15%", "company_id": self.company.id, "country_id": country.id})
        vat.tax_group_id = shared
        moved = org_hooks.ensure_tax_groups(self.env, self.company)
        self.assertIn("vat22", moved)
        self.assertEqual(vat.tax_group_id.name, "НДС 22%")
        self.assertEqual(shared.name, "Налог 15%", "Чужую общую группу не переименовываем.")
        self.assertEqual(vat.amount, 22.0, "Ставка не меняется.")
        self.assertFalse(org_hooks.ensure_tax_groups(self.env, self.company), "Повтор — ничего.")

    # ─── Виды ───────────────────────────────────────────────────────────
    def _arch(self, model, view_type, user=None, view=None):
        view_id = self.env.ref(view).id if view else False
        res = self.env[model].with_user(user or self.manager).get_views([(view_id, view_type)])
        return etree.fromstring(res["views"][view_type]["arch"])

    def test_no_new_button(self):
        form = self._arch("sale.order", "form", view="sale.view_order_form")
        self.assertEqual(form.get("create"), "0")
        self.assertEqual(form.get("duplicate"), "0")
        for xmlid in ("sale.view_order_tree", "sale.view_quotation_tree"):
            with self.subTest(view=xmlid):
                self.assertEqual(self._arch("sale.order", "list", view=xmlid).get("create"), "0")
        self.assertEqual(self._arch("sale.order", "kanban", view="sale.view_sale_order_kanban").get("create"), "0")
        self.assertTrue(self.env.ref("pmk_orders.view_order_kanban_pmk_orders").active)
        self.assertTrue(self.env.ref("pmk_orders.view_metal_spec_form_invoice").active)
        self.assertTrue(self.env.ref("pmk_orders.view_mail_compose_kp_invoice").active)

    def test_form_hidden_and_returned(self):
        keeper = new_test_user(
            self.env, login="pmkz9_removed", name="Убранное (шаг З-9)",
            groups="base.group_user,sales_team.group_sale_salesman_all_leads,"
                   "pmk_theme.group_pmk_removed,pmk_theme.group_pmk_money")
        lean = self._arch("sale.order", "form", view="sale.view_order_form")
        full = self._arch("sale.order", "form", user=keeper, view="sale.view_order_form")
        hidden = (
            "//page[@name='other_information']",
            "//group[@name='sale_total']/field[@name='tax_totals']",
            "//field[@name='order_line']/list/control/create[@name='add_product_control']",
            "//field[@name='order_line']/list/control/create[@name='add_section_control']",
            "//field[@name='order_line']/list/control/create[@name='add_note_control']",
            "//field[@name='order_line']/list/control/button[@name='action_add_from_catalog']",
            "//field[@name='order_line']/list/field[@name='product_template_id']",
            "//field[@name='order_line']/list/field[@name='tax_ids']",
            "//field[@name='order_line']/list/field[@name='qty_invoiced']",
            "//group[@name='order_details']/field[@name='validity_date']",
        )
        for expr in hidden:
            with self.subTest(hidden=expr):
                # Ядро досоздаёт спрятанное поле невидимым, если на него
                # ссылаются модификаторы соседей (price_unit → qty_invoiced).
                shown = [n for n in lean.xpath(expr)
                         if n.get("column_invisible") not in ("True", "1")
                         and n.get("invisible") not in ("True", "1")]
                self.assertFalse(shown, "Спрятано у менеджера.")
                self.assertTrue(full.xpath(expr), "«Убранное» возвращает.")
        for arch in (lean, full):
            control = arch.xpath("//field[@name='order_line']/list/control/create[@name='pmk_add_service']")
            self.assertEqual(len(control), 1)
            self.assertEqual(control[0].get("string"), "Добавить услугу")
        # Условия и итог.
        terms = lean.xpath("//group[@name='pmk_terms']")[0]
        names = [f.get("name") for f in terms.iter("field")]
        for name in ("payment_term_id", "pmk_payment_note", "pmk_lead_days", "pmk_lead_from",
                     "pmk_delivery", "pmk_delivery_address", "note"):
            self.assertIn(name, names)
        self.assertTrue(lean.xpath("//div[@name='pmk_invoice_total']//field[@name='pmk_tax_text']"))
        # Шапка листа: дата счёта видна у черновика, сделка — тут же.
        date = lean.xpath("//group[@name='order_details']/field[@name='date_order'][not(@invisible)]")
        self.assertEqual(len(date), 1)
        self.assertTrue(lean.xpath("//group[@name='order_details']/field[@name='opportunity_id']"))
        # Строки-изделия — только для чтения.
        for name in ("name", "product_uom_qty", "price_unit"):
            node = lean.xpath("//field[@name='order_line']/list/field[@name='%s']" % name)[0]
            with self.subTest(readonly=name):
                self.assertIn("pmk_from_spec", node.get("readonly"))
        # Узлы модулей вне зависимостей (тема, STEP_Z9_NODES).
        from odoo.addons.pmk_theme.models.hidden_nodes import STEP_Z9_NODES
        for expr, _group in STEP_Z9_NODES[("sale.order", "form")]:
            with self.subTest(theme=expr):
                self.assertFalse(lean.xpath(expr))

    def test_one_filled_button_per_state(self):
        """Залитая кнопка шапки — одна в каждом состоянии счёта (и у
        руководителя, и у менеджера)."""
        arch = self._arch("sale.order", "form", user=self.approver, view="sale.view_order_form")
        header = arch.find(".//header")
        filled = [b for b in header.iter("button")
                  if {"btn-primary", "oe_highlight"} & set((b.get("class") or "").split())]
        words = re.compile(r"[A-Za-z_][A-Za-z_0-9.]*")
        keywords = {"not", "and", "or", "in", "True", "False", "None"}

        def visible(button, values):
            expr = button.get("invisible") or "False"
            stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "''", expr)
            env = {name: False for name in words.findall(stripped) if name not in keywords}
            env.update(values)
            return not safe_eval(expr, env)

        for state, approval, approver in (
                ("draft", "none", False), ("draft", "none", True),
                ("draft", "pending", False), ("draft", "pending", True),
                ("draft", "approved", False), ("sent", "none", False), ("sent", "approved", True),
                ("sale", "none", False), ("cancel", "none", False)):
            values = {"state": state, "pmk_approval": approval, "pmk_is_approver": approver,
                      "pmk_spec_id": 1, "id": 1, "invoice_status": "no", "invoice_count": 0}
            shown = [b.get("string") for b in filled if visible(b, values)]
            with self.subTest(state=state, approval=approval, approver=approver):
                self.assertLessEqual(len(shown), 1, shown)
        # Следующий шаг по состояниям.
        steps = {("draft", "none"): "На согласование", ("draft", "approved"): "Отправить КП",
                 ("sent", "none"): "Оплата пришла — в работу"}
        for (state, approval), word in steps.items():
            values = {"state": state, "pmk_approval": approval, "pmk_is_approver": False,
                      "pmk_spec_id": 1, "id": 1, "invoice_status": "no", "invoice_count": 0}
            with self.subTest(step=word):
                self.assertEqual([b.get("string") for b in filled if visible(b, values)], [word])

    def test_spec_button(self):
        spec_arch = self._arch("pmk.metal.spec", "form")
        button = spec_arch.xpath("//header/button[@name='action_pmk_invoice']")
        self.assertEqual(len(button), 1)
        self.assertEqual(button[0].get("string"), "Счёт")
        self.assertNotIn("btn-primary", button[0].get("class") or "", "Залитая — «КП (PDF)».")
        self.assertIn("opportunity_id", button[0].get("invisible"))

    def test_kp_window_hint(self):
        deal, spec, invoice = self._draft()
        action = spec.with_user(self.manager).action_send_quotation()
        form = Form(self.env["mail.compose.message"].with_user(self.manager).with_context(action["context"]))
        self.assertIn("не согласован", form.pmk_kp_invoice_hint or "")
        self.assertIn("станет «Отправлен»", form.pmk_kp_invoice_text or "")
        # Из счёта — то же окно расчёта.
        again = invoice.with_user(self.manager).action_pmk_send_kp()
        self.assertEqual(again["res_model"], "mail.compose.message")
        self.assertEqual(again["context"]["default_res_ids"], spec.ids)

    def test_status_words(self):
        labels = dict(self.env["sale.order"]._fields["pmk_status"].selection)
        self.assertEqual(
            [labels[key] for key in ("draft", "approval", "approved", "sent", "sale", "cancel")],
            ["Черновик", "На согласовании", "Согласован", "Отправлен", "В работе (оплачен)", "Отменён"])

    # ─── Доводка З-9 (находки проверки 09.10) ───────────────────────────
    def _activities(self, invoice, xmlid):
        invoice.invalidate_recordset(["activity_ids"])
        kind = self.env.ref(xmlid)
        return invoice.activity_ids.filtered(lambda a: a.activity_type_id == kind)

    def test_qty_only_change_keeps_price(self):
        """В расчёте поменяли ТОЛЬКО количество — цена строки черновика
        остаётся (ядро не перетирает её ценой товара, 0 ₽), итог верен сразу."""
        deal, spec, invoice = self._draft()
        line = self._spec_lines(invoice)[:1]
        item = line.pmk_spec_product_id
        price = item.price_customer_unit
        self.assertEqual(line.technical_price_unit, 0.0, "Цена — ручная для ядра.")
        item.with_user(self.manager).write({"qty": item.qty + 3})
        self.assertEqual(line.product_uom_qty, item.qty)
        self.assertAlmostEqual(line.price_unit, price, places=2, msg="Цена не сбросилась в 0.")
        self.assertAlmostEqual(invoice.amount_total, self._priced_total(spec), places=2)
        # Старые строки (technical = price, как ставит ядро) — тоже чинятся.
        # (ядро пускает technical без price только из своего пересчёта)
        line.sudo().with_context(sale_write_from_compute=True).write(
            {"technical_price_unit": price})
        self.assertAlmostEqual(line.technical_price_unit, price)
        item.with_user(self.manager).write({"qty": item.qty + 1})
        self.assertAlmostEqual(line.price_unit, price, places=2)
        self.assertEqual(line.technical_price_unit, 0.0)
        # Перенос руками фиксирует ту же сумму.
        deal.with_user(self.manager).write({"stage_id": self.stage_kp.id})
        self.assertEqual(invoice.state, "sent")
        self.assertAlmostEqual(invoice.amount_total, self._priced_total(spec), places=2)

    def test_approval_tasks_closed(self):
        approve = "pmk_orders.mail_activity_type_invoice_approve"
        rework = "pmk_orders.mail_activity_type_invoice_rework"
        deal, spec, invoice = self._draft()
        invoice.with_user(self.manager).action_pmk_to_approval()
        action = invoice.with_user(self.approver).action_pmk_return()
        self.env[action["res_model"]].with_user(self.approver).with_context(
            action["context"]).create({"comment": "Поправьте срок"}).action_return()
        self.assertTrue(self._activities(invoice, rework))
        invoice.with_user(self.manager).action_pmk_to_approval()
        self.assertFalse(self._activities(invoice, rework), "Доработан — задача закрыта.")
        self.assertTrue(self._activities(invoice, approve))
        # В работу прямо с согласования — задача руководителя не висит.
        deal.with_user(self.manager).action_set_won()
        self.assertEqual(invoice.state, "sale")
        self.assertFalse(self._activities(invoice, approve))
        self.assertEqual(invoice.pmk_approval, "none")
        self.assertEqual(invoice.pmk_approval_signal, "Отправлен без согласования")
        # Отмена с согласования — тоже.
        deal2, spec2, invoice2 = self._draft()
        invoice2.with_user(self.manager).action_pmk_to_approval()
        invoice2.with_user(self.manager).action_cancel()
        self.assertEqual(invoice2.state, "cancel")
        self.assertFalse(self._activities(invoice2, approve))
        self.assertEqual(invoice2.pmk_approval, "none")
        # Отправка закрывает и «Доработать».
        deal3, spec3, invoice3 = self._draft()
        invoice3.with_user(self.manager).action_pmk_to_approval()
        action = invoice3.with_user(self.approver).action_pmk_return()
        self.env[action["res_model"]].with_user(self.approver).with_context(
            action["context"]).create({"comment": "Цена"}).action_return()
        self._send_kp(deal3, spec3)
        self.assertFalse(self._activities(invoice3, rework))

    def test_sent_invoice_new_revision(self):
        """Отправленный: условия, услуги, дата — только для чтения в форме;
        «Новая редакция» — снимок того, что видел клиент, и снова черновик."""
        deal, spec, invoice = self._draft()
        self._add_service(invoice, price=1500.0)
        invoice.with_user(self.manager).write({"pmk_payment_note": "100% предоплата"})
        with self.assertRaises(UserError):
            invoice.with_user(self.manager).action_pmk_new_revision()
        self._send_kp(deal, spec)
        self.assertIn("Новая редакция", invoice.pmk_lines_hint)
        action = invoice.with_user(self.manager).action_pmk_new_revision()
        self.assertEqual(action["res_id"], invoice.id)
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.pmk_revision, 2)
        snapshot = self._snapshots(invoice)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot.pmk_payment_note, "100% предоплата")
        service = invoice.order_line.filtered(lambda l: l.name == "Доставка")
        service.with_user(self.manager).write({"price_unit": 3000.0})
        invoice.with_user(self.manager).write({"pmk_payment_note": "50/50"})
        old = snapshot.order_line.filtered(lambda l: l.name == "Доставка")
        self.assertAlmostEqual(old.price_unit, 1500.0, msg="Снимок — то, что ушло клиенту.")
        self.assertEqual(snapshot.pmk_payment_note, "100% предоплата")
        self._send_kp(deal, spec)
        self.assertEqual(invoice.state, "sent")
        self.assertEqual(invoice.pmk_revision, 2, "Расчёт не менялся — ред. та же.")
        # Вид: у отправленного закрыто.
        arch = self._arch("sale.order", "form", view="sale.view_order_form")
        lines = arch.xpath("//field[@name='order_line'][@widget='sol_o2m']")[0]
        self.assertIn("'sent'", lines.get("readonly"))
        for name in ("pmk_payment_note", "pmk_lead_days", "pmk_delivery", "note", "payment_term_id"):
            node = arch.xpath("//group[@name='pmk_terms']//field[@name='%s']" % name)[0]
            with self.subTest(sent_readonly=name):
                self.assertIn("'sent'", node.get("readonly"))
        date = arch.xpath("//group[@name='order_details']/field[@name='date_order'][not(@invisible)]")[0]
        self.assertIn("'sent'", date.get("readonly"))
        button = arch.xpath("//button[@name='action_pmk_new_revision']")
        self.assertEqual(len(button), 1)
        self.assertNotIn("btn-primary", button[0].get("class"))

    def test_invoice_from_file_refused(self):
        attachment = self.env["ir.attachment"].create({"name": "заявка.pdf", "raw": b"%PDF-1.4"})
        before = self.env["sale.order"].search_count([])
        with self.assertRaises(UserError):
            self.env["sale.order"].with_user(self.manager).create_document_from_attachment(
                attachment.ids)
        self.assertEqual(self.env["sale.order"].search_count([]), before)

    def test_kp_window_extra_and_cancel(self):
        deal, spec, invoice = self._draft()
        self._add_service(invoice, name="Доставка", price=50000.0)
        invoice.with_user(self.manager).write({"pmk_lead_days": 20, "pmk_delivery": "pickup"})
        context = spec.with_user(self.manager).action_send_quotation()["context"]
        form = Form(self.env["mail.compose.message"].with_user(self.manager).with_context(context))
        extra = form.pmk_kp_invoice_extra or ""
        self.assertIn("Доставка", extra)
        self.assertIn("срок изготовления", extra)
        self.assertIn("впишите их в письмо", extra)
        # Отменённый — «снова «Отправлен»», а не «уже отправлен».
        invoice.with_user(self.manager).action_cancel()
        form = Form(self.env["mail.compose.message"].with_user(self.manager).with_context(context))
        shown = (form.pmk_kp_invoice_text or "") + (form.pmk_kp_invoice_hint or "")
        self.assertIn("отменён", shown)
        self.assertNotIn("уже отправлен", shown)

    def test_kp_window_approved_other_spec(self):
        deal, spec, invoice = self._draft()
        invoice.with_user(self.approver).action_pmk_approve()
        other = self._spec(deal)
        context = other.with_user(self.manager).action_send_quotation()["context"]
        form = Form(self.env["mail.compose.message"].with_user(self.manager).with_context(context))
        self.assertIn("согласование сбросится", form.pmk_kp_invoice_hint or "")

    def test_lines_and_header_controls(self):
        arch = self._arch("sale.order", "form", view="sale.view_order_form")
        for mode in ("list", "kanban"):
            delete = arch.xpath("//field[@name='order_line']/%s/control/delete" % mode)
            with self.subTest(delete=mode):
                self.assertEqual(len(delete), 1)
                self.assertEqual(delete[0].get("invisible"), "pmk_from_spec")
        for name in ("product_uom_id", "discount"):
            nodes = arch.xpath("//field[@name='order_line']/form//field[@name='%s']" % name)
            for node in nodes:
                if node.get("invisible") in ("True", "1"):
                    continue    # досозданный ядром невидимый узел (нет группы uom)
                with self.subTest(form_readonly=name):
                    self.assertIn("pmk_from_spec", node.get("readonly"))
        card = arch.xpath("//field[@name='order_line']/kanban//field[@name='name']"
                          "[contains(@class, 'fw-bold')]")
        self.assertTrue(card, "Карточка строки — название изделия.")
        for name in ("partner_id", "pmk_org_id"):
            node = arch.xpath("//group[@name='sale_header']//field[@name='%s']" % name)[0]
            with self.subTest(from_spec=name):
                self.assertIn("pmk_spec_id", node.get("readonly"))
        header = arch.find(".//header")
        self.assertFalse(header.xpath("./button[@name='action_confirm'][not(@id)]"),
                         "«Оплата пришла» у черновика — в «Убранном».")
        quotes = self._arch("sale.order", "list", view="sale.view_quotation_tree")
        self.assertEqual(quotes.xpath("//field[@name='state']")[0].get("optional"), "hide")
        self.assertFalse(quotes.xpath("//field[@name='create_date']"))
        kanban = self._arch("sale.order", "kanban", view="sale.view_sale_order_kanban")
        self.assertTrue(kanban.xpath("//field[@name='pmk_status']"))

    def test_gear_hides_core_send(self):
        from odoo.addons.pmk_theme.models.ir_actions import HIDDEN_BINDINGS, REMOVED
        for xmlid in ("sale.model_sale_order_send_mail",
                      "sale.model_sale_order_action_quotation_sent"):
            with self.subTest(action=xmlid):
                self.assertEqual(HIDDEN_BINDINGS.get(xmlid), REMOVED)
        bindings = self.env["ir.actions.actions"].with_user(self.manager).get_bindings("sale.order")
        shown = {a["id"] for kind in ("action", "report") for a in bindings.get(kind, ())}
        send = self.env.ref("sale.model_sale_order_send_mail")
        self.assertNotIn(send.id, shown)

    def test_tax_group_accounts_copied(self):
        vat = self.taxes["vat22"]
        country = vat.country_id or self.company.account_fiscal_country_id or self.env.ref("base.ru")
        account = self.env["account.account"].search(
            [("company_ids", "in", self.company.id)], limit=1)
        if not account:
            self.skipTest("Нет плана счетов.")
        shared = self.env["account.tax.group"].create({
            "name": "Налог 15%", "company_id": self.company.id, "country_id": country.id,
            "tax_payable_account_id": account.id, "tax_receivable_account_id": account.id})
        vat.tax_group_id = shared
        org_hooks.ensure_tax_groups(self.env, self.company)
        group = vat.tax_group_id
        self.assertNotEqual(group, shared)
        # Пустые счета новой группы — из прежней (свои, если были, не трогаем).
        self.assertTrue(group.tax_payable_account_id)
        self.assertTrue(group.tax_receivable_account_id)
        self.assertEqual(shared.tax_payable_account_id, account, "Прежняя группа не тронута.")
