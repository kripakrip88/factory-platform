# -*- coding: utf-8 -*-
"""Счёт покупателю из расчёта (разбор UX, шаг З-2, 08.10.2026), pmk_orders.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные.

С шага З-9 (09.10.2026) счёт сам по «КП отправлено» не заводится: «КП
отправлено» здесь — путь «Отправить КП» (мост после письма зовёт
_pmk_kp_move_stage, помощник _send_kp), перенос сделки руками — write стадии.
Новая жизнь счёта (черновик кнопкой «Счёт», согласование, условия, услуги) —
test_step_z9_invoice.py.

Что ловим:
  • «Отправить КП» создаёт РОВНО ОДИН счёт «Отправлен»:
    клиент — компания контакта, наша организация, сделка, расчёт, состояние
    «Выставлен»; строки — изделия с ценой (товар-услуга, название, количество,
    «шт», цена, связь с изделием), налог режима (компания — «цены включают
    налог»), итог = итогу КП,
    валюта компании; изделие без цены — в заметке сделки;
  • повторный переход и повторная отправка без изменений — тот же счёт,
    прежних редакций нет;
  • расчёт поменяли (количество, цена, удалили и добавили изделие) и снова
    отправили КП — тот же счёт «ред. 2», прежняя редакция — снимок со старыми
    ценами, отменён, заблокирован, без сделки, правка и удаление — ошибкой;
  • организация на УСН — «Без НДС (продажа)», налог 0;
  • «Выиграно» — счёт в работе, складских, закупочных, производственных
    документов и задач нет, писем нет; одна строка планировщика в «Очереди»;
    повторы её не дублируют; «Оплата пришла — в работу» в счёте = «Выиграно»;
  • «Проиграно» — счёт отменён, строка цела; восстановили и снова «КП
    отправлено» (перенос руками) — тот же счёт снова «Отправлен»;
  • нет цен, клиента — счёта нет, стадия сменилась, заметка; перенос руками
    без счёта — счёта нет, заметка;
    «Выиграно» без счёта — строка без счёта; счёт в работе расчётом не
    переписывается;
  • счёт выставлен из одного расчёта, главным стал другой (вариант, копия)
    — перетаскивание назад-вперёд, «Выиграно» и восстановление после
    «Проиграно» берут расчёт счёта: редакции нет, сумма — того, что ушло;
    поменяли расчёт отправленного — перенос руками редакцию НЕ даёт (заметка
    «ред. N — по «Отправить КП»»), её даёт «Отправить КП»;
  • флаг pmk_revision_freeze без sudo снимок не открывает (контекст RPC
    задаёт браузер);
  • права: менеджер без прав Проектов проводит свою сделку до строки,
    правит и заводит строки планировщика, удалить не может, чужие задачи
    на запись закрыты;
  • виды: кнопки «Расчёт» и «Заказ» на счёте, «Счёт» и «Заказ» на сделке,
    штатные кнопки sale_crm спрятаны, «Отправить» и «Создать счёт» — в
    группах-выключателях, залитая одна на любое состояние; окно «Счета
    покупателям» — с фильтром «Действующие»; нумератор «СЧ-».

Глазами (счёт во всех состояниях, снимок с плашкой, сделка, светлая и
тёмная тема) — основной агент на копии.
"""
import datetime

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger
from odoo.tools.safe_eval import safe_eval

from odoo.addons.pmk_deal.models.kp_sent import KP_SENT_STAGE
from odoo.addons.pmk_org import hooks as org_hooks
from odoo.addons.pmk_org.tools import regime as rg

from .. import hooks

D = datetime.date


class Z2Common(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        # На чистой базе план счетов грузится после установки pmk_org —
        # налоги режимов заводим явно; компания — «цены включают налог», как
        # на боевой после миграции 19.0.1.1.0 (повтор ничего не меняет).
        cls.taxes = org_hooks.ensure_taxes(env, cls.company)
        org_hooks.ensure_company_price_included(env, cls.company)
        cls.Org = env["pmk.org"]
        cls.org_vat = cls.Org.create({
            "name": "ИП Тестов (шаг З-2)",
            "regime_ids": [Command.create({"date_from": D(2020, 1, 1), "regime": "vat22"})],
        })
        cls.org_usn = cls.Org.create({
            "name": "ООО «Упрощёнка» (шаг З-2)",
            "regime_ids": [Command.create({"date_from": D(2020, 1, 1), "regime": "usn0"})],
        })
        cls.manager = new_test_user(
            env, login="pmkz2_manager", name="Менеджер (шаг З-2)",
            groups="base.group_user,sales_team.group_sale_salesman_all_leads,project.group_project_user")
        cls.salesman = new_test_user(
            env, login="pmkz2_salesman", name="Продавец без Проектов (шаг З-2)",
            groups="base.group_user,sales_team.group_sale_salesman_all_leads")
        cls.client = env["res.partner"].create({"name": "ООО «Арматура-Тест» (шаг З-2)",
                                                "is_company": True})
        cls.person = env["res.partner"].create({"name": "Снабженец Клиента (шаг З-2)",
                                                "parent_id": cls.client.id})
        cls.stage_calc = env.ref("crm.stage_lead2")
        cls.stage_kp = env.ref(KP_SENT_STAGE)
        cls.stage_won = env.ref("crm.stage_lead4")
        cls.service = env.ref("pmk_orders.product_mk_service").product_variant_id
        cls.unit = env.ref("uom.product_uom_unit")
        cls.project = env.ref("pmk_orders.project_orders")
        cls.queue = env.ref("pmk_orders.orders_stage_queue")

    # ─── помощники ──────────────────────────────────────────────────────
    def _deal(self, user=None, org=None, **values):
        vals = {"name": "Ограждение лестницы (шаг З-2)", "type": "opportunity",
                "partner_id": self.person.id, "stage_id": self.stage_calc.id,
                "user_id": (user or self.manager).id,
                "pmk_org_id": (org or self.org_vat).id}
        vals.update(values)
        return self.env["crm.lead"].with_user(user or self.manager).create(vals)

    def _spec(self, deal, user=None, org=None, products=None, **values):
        products = products if products is not None else [
            ("Секция ограждения ОГ-1", 12, 4500.0),
            ("Ферма Ф-1", 3, 333.33),
            ("Пробное изделие", 1, 0.0),
        ]
        vals = {
            "opportunity_id": deal.id if deal else False,
            "partner_id": self.client.id,
            "note": "Ограждение лестницы",
            "pmk_org_id": (org or self.org_vat).id,
            "product_ids": [Command.create({"name": name, "qty": qty, "price_customer_unit": price,
                                            "sequence": 10 * (i + 1)})
                            for i, (name, qty, price) in enumerate(products)],
        }
        vals.update(values)
        return self.env["pmk.metal.spec"].with_user(user or self.manager).with_context(
            mail_create_nolog=True).create(vals)

    def _invoices(self, deal):
        return self.env["sale.order"].search([("opportunity_id", "=", deal.id)])

    def _send_kp(self, deal, spec=None, user=None):
        """«Отправить КП»: после письма людям клиента мост зовёт
        _pmk_kp_move_stage (pmk_deal kp_sent.py) — сделка в «КП отправлено»,
        счёт этого расчёта «Отправлен» (шаг З-9)."""
        user = user or self.manager
        spec = spec or deal.pmk_spec_id
        return spec.with_user(user)._pmk_kp_move_stage(deal.with_user(user))

    def _snapshots(self, order):
        return self.env["sale.order"].search([("pmk_revision_of_id", "=", order.id)])

    def _rows(self, deal):
        return self.env["project.task"].with_context(active_test=False).search(
            [("pmk_deal_id", "=", deal.id)])

    def _notes(self, deal):
        deal.invalidate_recordset(["message_ids"])
        return " ".join(str(m.body) for m in deal.message_ids)

    def _priced_total(self, spec):
        return sum(p.price_customer_unit * p.qty for p in spec.product_ids if p.price_customer_unit)


@tagged("post_install", "-at_install")
class TestStepZ2Invoice(Z2Common):

    # ─── «Отправить КП» → ровно один счёт ───────────────────────────────
    def test_kp_sent_issues_one_invoice(self):
        deal = self._deal()
        spec = self._spec(deal)
        self.assertEqual(deal.pmk_spec_id, spec, "Посылка: главный расчёт сделки.")
        self._send_kp(deal)
        invoice = self._invoices(deal)
        self.assertEqual(len(invoice), 1, "Ровно один счёт.")
        self.assertEqual(deal.stage_id, self.stage_kp)
        self.assertEqual(invoice.partner_id, self.client, "Клиент — компания контакта.")
        self.assertEqual(invoice.opportunity_id, deal)
        self.assertEqual(invoice.pmk_org_id, self.org_vat)
        self.assertEqual(invoice.pmk_spec_id, spec)
        self.assertEqual(invoice.state, "sent", "«Отправлен».")
        self.assertEqual(invoice.pmk_status, "sent")
        self.assertTrue(invoice.pmk_sent_date)
        self.assertFalse(invoice.pmk_is_revision)
        self.assertEqual(invoice.pmk_revision, 1)
        self.assertFalse(invoice.pmk_revision_label)
        self.assertEqual(invoice.currency_id, self.company.currency_id, "Валюта компании = валюта расчёта.")
        self.assertEqual(deal.pmk_invoice_id, invoice)
        self.assertEqual(deal.pmk_invoice_count, 1)
        seq = self.env.ref("sale.seq_sale_order")
        if seq.prefix == hooks.PREFIX:
            self.assertTrue(invoice.name.startswith("СЧ-"), invoice.name)

        lines = invoice.order_line.sorted("sequence")
        self.assertEqual(lines.mapped("name"), ["Секция ограждения ОГ-1", "Ферма Ф-1"],
                         "Изделие без цены в счёт не идёт — как в печати КП.")
        vat = self.taxes["vat22"]
        self.assertTrue(vat.price_include, "Компания — «цены включают налог», налог режима следует ей.")
        for line, (qty, price) in zip(lines, ((12, 4500.0), (3, 333.33))):
            with self.subTest(line=line.name):
                self.assertEqual(line.product_id, self.service)
                self.assertEqual(line.product_id.type, "service")
                self.assertEqual(line.product_uom_qty, qty)
                self.assertEqual(line.product_uom_id, self.unit)
                self.assertAlmostEqual(line.price_unit, price)
                self.assertEqual(line.pmk_spec_product_id.spec_id, spec)
                self.assertTrue(line.pmk_from_spec)
                self.assertEqual(line.tax_ids, vat)
        total = self._priced_total(spec)
        self.assertAlmostEqual(total, 54999.99)
        self.assertAlmostEqual(invoice.amount_total, total, places=2,
                               msg="Сумма счёта = сумме КП (цены с налогом).")
        self.assertAlmostEqual(invoice.amount_tax, round(total * 22 / 122, 2), delta=0.011,
                               msg="«в том числе НДС 22 %», как в печати КП.")
        notes = self._notes(deal)
        self.assertIn(invoice.name, notes)
        self.assertIn("Пробное изделие", notes, "Изделие без цены — в заметке.")

    def test_repeat_does_not_duplicate(self):
        deal = self._deal()
        spec = self._spec(deal)
        self._send_kp(deal)
        invoice = self._invoices(deal)
        deal.write({"stage_id": self.stage_calc.id})
        deal.write({"stage_id": self.stage_kp.id})
        spec._pmk_kp_move_stage(deal)
        self.assertEqual(self._invoices(deal), invoice, "Повтор — тот же счёт.")
        self.assertFalse(self._snapshots(invoice), "Расчёт не менялся — редакций нет.")
        self.assertEqual(invoice.state, "sent")
        self.assertEqual(invoice.pmk_revision, 1)

    def test_kp_send_path_uses_sent_spec(self):
        """«Отправить КП» — из того расчёта, что ушёл (а не главного)."""
        deal = self._deal()
        older = self._spec(deal, products=[("Старый вариант", 1, 1000.0)], date=D(2026, 1, 1))
        self._spec(deal, products=[("Новый вариант", 1, 2000.0)])
        self.assertNotEqual(deal.pmk_spec_id, older)
        older._pmk_kp_move_stage(deal)
        self.assertEqual(deal.stage_id, self.stage_kp)
        invoice = self._invoices(deal)
        self.assertEqual(len(invoice), 1)
        self.assertEqual(invoice.pmk_spec_id, older)
        self.assertEqual(invoice.order_line.mapped("name"), ["Старый вариант"])
        self.assertFalse(self._snapshots(invoice), "Без лишней редакции из главного расчёта.")

    def test_drag_keeps_invoice_spec(self):
        """Счёт выставлен из A, главным стал B — перетаскивание и «Выиграно»
        счёт из B не переписывают (находка проверки З-2)."""
        deal = self._deal()
        first = self._spec(deal, products=[("Вариант А", 2, 1000.0)])
        first._pmk_kp_move_stage(deal)
        invoice = self._invoices(deal)
        self.assertEqual(invoice.pmk_spec_id, first)
        second = self._spec(deal, products=[("Вариант Б", 5, 9000.0)])
        self.assertEqual(deal.pmk_spec_id, second, "Посылка: главным стал новый расчёт.")
        deal.write({"stage_id": self.stage_calc.id})
        deal.write({"stage_id": self.stage_kp.id})
        self.assertEqual(self._invoices(deal), invoice)
        self.assertFalse(self._snapshots(invoice), "Ушедшее клиенту не переписано вариантом.")
        self.assertEqual(invoice.pmk_revision, 1)
        self.assertEqual(invoice.pmk_spec_id, first)
        self.assertEqual(invoice.order_line.mapped("name"), ["Вариант А"])
        # Проиграли, восстановили, выиграли — счёт из того же расчёта.
        deal.action_set_lost()
        self.assertEqual(invoice.state, "cancel")
        deal.action_restore()
        deal.action_set_won()
        self.assertEqual(invoice.state, "sale")
        self.assertEqual(invoice.pmk_spec_id, first)
        self.assertFalse(self._snapshots(invoice))
        self.assertAlmostEqual(invoice.amount_total, 2000.0, places=2)
        row = self._rows(deal)
        self.assertEqual(len(row), 1)
        self.assertAlmostEqual(row.pmk_amount, 2000.0, places=2)

    def test_drag_follows_changes_of_invoice_spec(self):
        """Шаг З-9: поменяли сам расчёт отправленного счёта — перенос руками
        редакции НЕ даёт (только заметка), её даёт «Отправить КП» из него.
        Расчёт счёта отвязали от сделки, проиграли, восстановили и перенесли —
        отменённый счёт снова «Отправлен» уже из главного расчёта (редакция)."""
        deal = self._deal()
        first = self._spec(deal, products=[("Вариант А", 2, 1000.0)])
        first._pmk_kp_move_stage(deal)
        invoice = self._invoices(deal)
        second = self._spec(deal, products=[("Вариант Б", 5, 9000.0)])
        first.product_ids.write({"price_customer_unit": 1100.0})
        self.assertAlmostEqual(invoice.amount_total, 2000.0, places=2,
                               msg="Отправленный счёт за расчётом не идёт.")
        self.assertIn("ред. 2", invoice.pmk_spec_changed_text or "")
        deal.write({"stage_id": self.stage_calc.id})
        deal.write({"stage_id": self.stage_kp.id})
        self.assertEqual(invoice.pmk_revision, 1, "Перенос руками редакцию не даёт.")
        self.assertIn("по «Отправить КП»", self._notes(deal))
        first._pmk_kp_move_stage(deal)
        self.assertEqual(invoice.pmk_revision, 2)
        self.assertEqual(invoice.pmk_spec_id, first)
        self.assertAlmostEqual(invoice.amount_total, 2200.0, places=2)
        first.opportunity_id = False
        deal.action_set_lost()
        deal.action_restore()
        deal.write({"stage_id": self.stage_calc.id})
        deal.write({"stage_id": self.stage_kp.id})
        self.assertEqual(invoice.state, "sent")
        self.assertEqual(invoice.pmk_revision, 3)
        self.assertEqual(invoice.pmk_spec_id, second, "Расчёт ушёл из сделки — главный.")

    # ─── Редакции ───────────────────────────────────────────────────────
    def test_changed_spec_gives_revision(self):
        deal = self._deal()
        spec = self._spec(deal)
        self._send_kp(deal)
        invoice = self._invoices(deal)
        name, first_total = invoice.name, invoice.amount_total
        section, truss, _probe = spec.product_ids.sorted("sequence")
        spec.with_user(self.manager).write({"product_ids": [
            Command.update(section.id, {"qty": 10, "price_customer_unit": 4600.0}),
            Command.delete(truss.id),
            Command.create({"name": "Опора О-1", "qty": 2, "price_customer_unit": 1000.0,
                            "sequence": 40}),
        ]})
        spec._pmk_kp_move_stage(deal)   # повторная отправка КП, сделка уже в «КП отправлено»

        self.assertEqual(self._invoices(deal), invoice, "Тот же счёт — не новый.")
        self.assertEqual(invoice.name, name, "Номер тот же.")
        self.assertEqual(invoice.pmk_revision, 2)
        self.assertEqual(invoice.pmk_revision_label, "ред. 2")
        self.assertEqual(invoice.display_name, "%s ред. 2" % name)
        self.assertEqual(invoice.state, "sent")
        self.assertEqual(sorted(invoice.order_line.mapped("name")), ["Опора О-1", "Секция ограждения ОГ-1"])
        self.assertAlmostEqual(invoice.amount_total, 10 * 4600.0 + 2 * 1000.0, places=2)

        snapshot = self._snapshots(invoice)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(invoice.pmk_revision_ids, snapshot)
        self.assertTrue(snapshot.pmk_is_revision)
        self.assertEqual(snapshot.name, name)
        self.assertEqual(snapshot.pmk_revision_label, "ред. 1")
        self.assertEqual(snapshot.state, "cancel")
        self.assertTrue(snapshot.locked)
        self.assertFalse(snapshot.opportunity_id, "Снимок не считается счётом сделки.")
        self.assertAlmostEqual(snapshot.amount_total, first_total, places=2,
                               msg="Снимок — что и по какой цене уходило.")
        self.assertEqual(sorted(snapshot.order_line.mapped("price_unit")), [333.33, 4500.0])
        self.assertEqual(snapshot.order_line.tax_ids, self.taxes["vat22"])
        self.assertEqual(deal.order_ids, invoice, "У сделки — только действующий.")
        self.assertEqual(deal.pmk_invoice_count, 1)

        # Только для чтения.
        with self.assertRaises(UserError):
            snapshot.with_user(self.manager).write({"note": "правка"})
        with self.assertRaises(UserError):
            snapshot.with_user(self.manager).action_draft()
        with self.assertRaises(UserError):
            snapshot.order_line[:1].with_user(self.manager).write({"price_unit": 1.0})
        with self.assertRaises(UserError):
            snapshot.action_confirm()
        with self.assertRaises(UserError):
            snapshot.unlink()
        # Флаг своих операций из браузера (контекст RPC) без sudo не действует.
        forged = snapshot.with_user(self.manager).with_context(pmk_revision_freeze=True)
        with self.assertRaises(UserError):
            forged.write({"note": "правка"})
        with self.assertRaises(UserError):
            forged.write({"client_order_ref": "другая ссылка"})
        with self.assertRaises(UserError):
            forged.order_line[:1].write({"price_unit": 1.0})
        with self.assertRaises(UserError):
            forged.write({"order_line": [Command.create({
                "product_id": self.service.id, "name": "Лишнее", "product_uom_qty": 1,
                "price_unit": 1.0})]})
        # Права менеджера на удаление — как у ядра (могут отказать раньше нас):
        # главное — снимок цел. AccessError — подкласс UserError: ловим оба
        # (обёртка Odoo assertRaises принимает только один класс, не кортеж).
        with self.assertRaises(UserError):
            forged.unlink()
        self.assertTrue(snapshot.exists())
        self.assertAlmostEqual(snapshot.amount_total, first_total, places=2)
        # Лента снимка живёт: анализировать и обсуждать можно.
        snapshot.message_post(body="Сравнить с ред. 2", message_type="comment",
                              subtype_xmlid="mail.mt_note")

    def test_revision_keeps_manual_lines(self):
        deal = self._deal()
        self._spec(deal, products=[("Каркас", 1, 10000.0)])
        self._send_kp(deal)
        invoice = self._invoices(deal)
        invoice.action_draft()
        extra = self.env.ref("pmk_orders.product_extra_service").product_variant_id
        invoice.write({"order_line": [Command.create({
            "product_id": extra.id, "name": "Доставка", "product_uom_qty": 1,
            "price_unit": 1500.0})]})
        invoice.action_quotation_sent()
        deal.pmk_spec_id.product_ids.write({"price_customer_unit": 12000.0})
        deal.pmk_spec_id._pmk_kp_move_stage(deal)
        self.assertEqual(invoice.pmk_revision, 2)
        self.assertEqual(sorted(invoice.order_line.mapped("name")), ["Доставка", "Каркас"])
        self.assertAlmostEqual(invoice.amount_total, 13500.0, places=2)

    def test_usn_org_no_vat(self):
        deal = self._deal(org=self.org_usn)
        spec = self._spec(deal, org=self.org_usn)
        self._send_kp(deal)
        invoice = self._invoices(deal)
        self.assertEqual(invoice.pmk_org_id, self.org_usn)
        usn = self.taxes["usn0"]
        self.assertEqual(usn.name, rg.TAXES["usn0"][0], "Имя налога не меняется.")
        self.assertEqual(invoice.order_line.tax_ids, usn)
        self.assertAlmostEqual(invoice.amount_tax, 0.0)
        self.assertAlmostEqual(invoice.amount_total, self._priced_total(spec), places=2)

    # ─── «Выиграно» → в работу, одна строка ─────────────────────────────
    def test_won_confirms_and_creates_one_row(self):
        deal = self._deal()
        self._spec(deal)
        self._send_kp(deal)
        invoice = self._invoices(deal)
        mails = self.env["mail.mail"].sudo().search_count([])
        deal.with_user(self.manager).action_set_won()

        self.assertEqual(invoice.state, "sale", "«В работе (оплачен)».")
        if "picking_ids" in invoice._fields:
            self.assertFalse(invoice.picking_ids, "Товар-услуга: отгрузок нет.")
        if "purchase_order_count" in invoice._fields:
            self.assertEqual(invoice.purchase_order_count, 0)
        if "mrp_production_count" in invoice._fields:
            self.assertEqual(invoice.mrp_production_count, 0)
        if "tasks_ids" in invoice._fields:
            self.assertFalse(invoice.sudo().tasks_ids, "Задач на строки нет (sale_project).")
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails, "Писем нет.")

        row = self._rows(deal)
        self.assertEqual(len(row), 1)
        self.assertEqual(row.project_id, self.project)
        self.assertEqual(row.stage_id, self.queue, "Этап «Очередь».")
        self.assertEqual(row.pmk_sale_order_id, invoice)
        self.assertEqual(row.partner_id, self.client)
        self.assertEqual(row.pmk_org_id, self.org_vat)
        self.assertAlmostEqual(row.pmk_amount, invoice.amount_total)
        self.assertEqual(row.user_ids, self.manager)
        self.assertEqual(row.pmk_metal, "none")
        self.assertEqual(invoice.pmk_task_count, 1)
        self.assertEqual(deal.pmk_order_count, 1)

        # Повторы не дублируют.
        deal.write({"stage_id": self.stage_calc.id})
        deal.action_set_won()
        self.assertEqual(len(self._rows(deal)), 1)
        # Из «Выиграно» проиграть нельзя (ядро crm: кнопка «Проиграно» только
        # у сделки в работе, _check_won_validity) — сначала назад по воронке.
        deal.write({"stage_id": self.stage_calc.id})
        deal.action_set_lost()
        self.assertEqual(invoice.state, "cancel", "«Проиграно» — счёт отменён.")
        self.assertEqual(len(self._rows(deal)), 1, "Строка осталась.")
        deal.action_restore()
        deal.action_set_won()
        self.assertEqual(len(self._rows(deal)), 1)
        self.assertEqual(self._invoices(deal), invoice, "Счёт тот же.")
        self.assertEqual(invoice.state, "sale")
        row.active = False
        deal.write({"stage_id": self.stage_calc.id})
        deal.action_set_won()
        self.assertEqual(len(self._rows(deal)), 1, "Строка в архиве — новой нет.")

    def test_confirm_button_wins_deal(self):
        deal = self._deal()
        self._spec(deal)
        self._send_kp(deal)
        invoice = self._invoices(deal)
        invoice.with_user(self.manager).action_confirm()
        self.assertTrue(deal.stage_id.is_won, "«Оплата пришла — в работу» = «Выиграно».")
        self.assertEqual(deal.won_status, "won")
        self.assertEqual(len(self._rows(deal)), 1)
        self.assertEqual(self._rows(deal).pmk_sale_order_id, invoice)

    def test_confirm_without_deal_creates_row(self):
        order = self.env["sale.order"].create({
            "partner_id": self.client.id,
            "order_line": [Command.create({"product_id": self.service.id, "name": "Каркас",
                                           "product_uom_qty": 1, "price_unit": 5000.0})],
        })
        order.action_confirm()
        rows = self.env["project.task"].search([("pmk_sale_order_id", "=", order.id)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.stage_id, self.queue)
        self.assertEqual(rows.name, order.name, "Без сделки и расчёта — номер счёта.")

    # ─── «Проиграно» → счёт отменён ─────────────────────────────────────
    def test_lost_cancels_invoice(self):
        deal = self._deal()
        self._spec(deal)
        self._send_kp(deal)
        invoice = self._invoices(deal)
        deal.action_set_lost()
        self.assertEqual(invoice.state, "cancel")
        self.assertEqual(deal.won_status, "lost")
        deal.action_restore()
        deal.write({"stage_id": self.stage_kp.id})
        self.assertEqual(self._invoices(deal), invoice, "Восстановили — тот же счёт.")
        self.assertEqual(invoice.state, "sent")

    def test_lost_after_won_keeps_row(self):
        """Выиграли, потом сорвалось: сделку возвращают по воронке (из
        «Выиграно» ядро проиграть не даёт) и проигрывают — счёт в работе
        отменяется, строка планировщика остаётся."""
        deal = self._deal()
        self._spec(deal)
        self._send_kp(deal)
        deal.action_set_won()
        row = self._rows(deal)
        invoice = self._invoices(deal)
        self.assertEqual(len(row), 1)
        self.assertEqual(invoice.state, "sale")
        deal.write({"stage_id": self.stage_kp.id})
        self.assertEqual(invoice.state, "sale", "Назад по воронке — счёт в работе не трогаем.")
        deal.action_set_lost()
        self.assertEqual(deal.won_status, "lost")
        self.assertEqual(invoice.state, "cancel")
        self.assertTrue(row.exists(), "Строка планировщика не удаляется.")
        self.assertTrue(row.active)
        self.assertEqual(row.pmk_sale_order_id, invoice)

    # ─── Ничего не блокируем ────────────────────────────────────────────
    def test_no_spec_no_invoice_stage_moves(self):
        deal = self._deal()
        deal.write({"stage_id": self.stage_kp.id})
        self.assertEqual(deal.stage_id, self.stage_kp, "Стадия сменилась — ничего не блокирует.")
        self.assertFalse(self._invoices(deal))
        self.assertIn("сам он не заводится", self._notes(deal),
                      "Шаг З-9: перенос руками счёт не заводит — заметка.")
        deal.action_set_won()
        row = self._rows(deal)
        self.assertEqual(len(row), 1, "«Выиграно» без счёта — строка всё равно есть.")
        self.assertFalse(row.pmk_sale_order_id)
        self.assertIn("без счёта", self._notes(deal))

    def test_no_prices_no_invoice(self):
        deal = self._deal()
        self._spec(deal, products=[("Без цены", 1, 0.0)])
        self._send_kp(deal)
        self.assertEqual(deal.stage_id, self.stage_kp)
        self.assertFalse(self._invoices(deal))
        self.assertIn("нет цены клиенту", self._notes(deal))

    def test_no_client_no_invoice(self):
        deal = self._deal(partner_id=False)
        self._spec(deal, partner_id=False)
        self._send_kp(deal)
        self.assertEqual(deal.stage_id, self.stage_kp)
        self.assertFalse(self._invoices(deal))
        self.assertIn("не указан клиент", self._notes(deal))

    def test_invoice_in_work_not_rewritten(self):
        deal = self._deal()
        spec = self._spec(deal)
        self._send_kp(deal)
        deal.action_set_won()
        invoice = self._invoices(deal)
        total = invoice.amount_total
        spec.product_ids.filtered("price_customer_unit")[:1].price_customer_unit = 9999.0
        deal.write({"stage_id": self.stage_kp.id})
        self.assertEqual(invoice.state, "sale")
        self.assertAlmostEqual(invoice.amount_total, total)
        self.assertFalse(self._snapshots(invoice))
        self.assertIn("уже в работе", self._notes(deal))

    def test_failure_does_not_break_deal_save(self):
        """Сбой нашего кода — заметка, а не упавшее сохранение сделки."""
        deal = self._deal()
        self._spec(deal)
        Order = type(self.env["sale.order"])

        def boom(*args, **kwargs):
            raise ValueError("проверка сбоя")

        self.patch(Order, "_pmk_create_from_spec", boom)
        with mute_logger("odoo.addons.pmk_orders.models.crm_lead"):
            self._send_kp(deal)
        self.assertEqual(deal.stage_id, self.stage_kp)
        self.assertFalse(self._invoices(deal))
        self.assertIn("не получилось", self._notes(deal))

    # ─── Права ──────────────────────────────────────────────────────────
    def test_salesman_without_projects(self):
        user = self.salesman
        self.assertFalse(user.has_group("project.group_project_user"), "Посылка: без Проектов.")
        deal = self._deal(user=user)
        self._spec(deal, user=user)
        self._send_kp(deal, user=user)
        deal.with_user(user).action_set_won()
        invoice = self._invoices(deal)
        self.assertEqual(invoice.state, "sale")
        self.assertNotIn("не получилось", self._notes(deal), "«Выиграно» прошло без сбоя доступа.")
        action = self.env["ir.actions.act_window"]._for_xml_id("pmk_orders.action_orders")
        Task = self.env["project.task"].with_user(user)
        rows = Task.search(safe_eval(action["domain"]) if isinstance(action["domain"], str)
                           else action["domain"])
        row = rows.filtered(lambda r: r.pmk_deal_id == deal)
        self.assertEqual(len(row), 1, "Продавец видит строку своей сделки.")
        row.write({"pmk_paid_amount": invoice.amount_total / 2,
                   "stage_id": self.env.ref("pmk_orders.orders_stage_work").id})
        self.assertAlmostEqual(row.pmk_paid_pct, 50.0, places=0)
        self.assertEqual(deal.with_user(user).pmk_order_count, 1)
        # Правило rule_orders_rows_sales: строку можно завести руками, а
        # удалить — нет; чужие задачи (не планировщик) на запись закрыты.
        manual = Task.create({"name": "Заказ руками (шаг З-2)", "project_id": self.project.id})
        self.assertEqual(manual.project_id, self.project)
        with self.assertRaises(AccessError):
            row.unlink()
        other = self.env["project.project"].create({"name": "Доработка (шаг З-2)"})
        task = self.env["project.task"].create({"name": "Чужая задача", "project_id": other.id})
        with self.assertRaises(AccessError):
            task.with_user(user).write({"name": "правка"})

    # ─── Виды ───────────────────────────────────────────────────────────
    def _arch(self, model, view_type, user=None, view=None):
        view_id = self.env.ref(view).id if view else False
        res = self.env[model].with_user(user or self.manager).get_views([(view_id, view_type)])
        return etree.fromstring(res["views"][view_type]["arch"])

    def test_views_active(self):
        for xmlid in ("pmk_orders.view_order_form_pmk_orders", "pmk_orders.view_order_list_pmk_orders",
                      "pmk_orders.view_order_search_pmk_orders", "pmk_orders.view_crm_lead_form_orders",
                      "pmk_orders.view_crm_lead_form_hide_sale_buttons"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)
        self.assertTrue(self.env.ref("pmk_orders.view_order_search_quotation_pmk_orders").active)

    def test_draft_issue_button(self):
        """Черновик → «Отметить отправленным» (с шага З-9 — в «Убранном»):
        «Отправлен», без письма, дата отправки стоит."""
        order = self.env["sale.order"].with_user(self.manager).create({
            "partner_id": self.client.id,
            "order_line": [Command.create({"product_id": self.service.id, "name": "Каркас",
                                           "product_uom_qty": 1, "price_unit": 5000.0})]})
        self.assertEqual(order.state, "draft")
        mails = self.env["mail.mail"].search_count([])
        order.with_user(self.manager).action_quotation_sent()
        self.assertEqual(order.state, "sent")
        self.assertTrue(order.pmk_sent_date)
        self.assertEqual(self.env["mail.mail"].search_count([]), mails, "Писем нет.")

    def test_invoice_form(self):
        """Шапка и снимок. Залитая одна на каждое состояние — проверка
        перебором состояний в test_step_z9_invoice.py (шаг З-9)."""
        arch = self._arch("sale.order", "form", view="sale.view_order_form")
        self.assertIn("o_pmk_header_up", arch.get("class"))
        box = arch.xpath("//div[@name='button_box']")[0]
        names = [b.get("name") for b in box.iter("button")]
        self.assertIn("action_open_spec", names)
        self.assertIn("action_open_planner_row", names)
        planner = box.xpath(".//button[@name='action_open_planner_row']")[0]
        self.assertEqual(planner.get("invisible"), "pmk_is_revision", "Наш шаг — виден всегда.")
        header = arch.find(".//header")
        confirm = header.xpath("./button[@id='action_confirm']")[0]
        self.assertEqual(confirm.get("string"), "Оплата пришла — в работу")
        self.assertIn("pmk_is_revision", confirm.get("invisible"))
        # Шаг З-9: «Выставить» (З-2) — в «Убранном»: у менеджера узла нет.
        self.assertFalse(header.xpath("./button[@name='action_quotation_sent']"))
        draft_confirm = header.xpath("./button[@name='action_confirm'][not(@id)]")
        for button in draft_confirm:
            with self.subTest(button="action_confirm (черновик)"):
                self.assertEqual(button.get("string"), confirm.get("string"),
                                 "Одно действие — одно слово.")
                self.assertFalse({"btn-primary", "oe_highlight"} & set((button.get("class") or "").split()))
        for name in ("action_quotation_send", "action_preview_sale_order"):
            with self.subTest(button=name):
                self.assertFalse(header.xpath("./button[@name='%s']" % name),
                                 "Спрятано группой «Убранное».")
        self.assertFalse(header.xpath("./button[@id='create_invoice']"), "Спрятано группой «Деньги».")
        # «Разблокировать» — только руководителю продаж (groups ядра): у
        # менеджера узла нет вовсе.
        checked = 0
        for name in ("action_cancel", "action_draft", "action_unlock"):
            for button in header.xpath("./button[@name='%s']" % name):
                with self.subTest(button=name):
                    self.assertIn("pmk_is_revision", button.get("invisible"))
                    checked += 1
        self.assertGreaterEqual(checked, 2)
        page = arch.xpath("//page[@name='pmk_revisions']")
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0].get("invisible"), "not pmk_revision_ids")
        banner = arch.xpath("//div[contains(concat(' ', @class, ' '), ' o_pmk_revision_banner ')]")
        self.assertEqual(banner[0].get("invisible"), "not pmk_is_revision")
        self.assertIsNotNone(arch.find(".//h1/field[@name='pmk_revision_label']"))
        # Прежняя редакция — только для чтения во всех вкладках. «Другая
        # информация» с шага З-9 — в «Убранном»: смотрим у того, кому её вернули.
        keeper = new_test_user(
            self.env, login="pmkz2_removed", name="Убранное показать (шаг З-2)",
            groups="base.group_user,sales_team.group_sale_salesman_all_leads,"
                   "pmk_theme.group_pmk_removed")
        full = self._arch("sale.order", "form", user=keeper, view="sale.view_order_form")
        for name in ("note", "payment_term_id", "fiscal_position_id", "client_order_ref",
                     "user_id", "team_id", "tag_ids", "origin", "pmk_payment_note",
                     "pmk_lead_days", "pmk_delivery"):
            nodes = full.xpath("//sheet//field[@name='%s']" % name)
            with self.subTest(readonly=name):
                self.assertTrue(nodes)
                self.assertTrue(any("pmk_is_revision" in (n.get("readonly") or "") for n in nodes))

    def test_invoice_list_and_search(self):
        arch = self._arch("sale.order", "list", view="sale.view_order_tree")
        names = [f.get("name") for f in arch.iter("field")
                 if f.get("column_invisible") not in ("1", "True") and f.get("invisible") not in ("1", "True")]
        self.assertEqual(names[names.index("name") + 1: names.index("name") + 3],
                         ["pmk_revision_label", "pmk_deal_number"])
        search = self._arch("sale.order", "search", view="sale.sale_order_view_search_inherit_sale")
        filters = {f.get("name") for f in search.iter("filter")}
        self.assertLessEqual({"pmk_current", "pmk_issued", "pmk_in_work", "pmk_cancelled", "pmk_revisions"},
                             filters)
        quotation = self._arch("sale.order", "search", view="sale.sale_order_view_search_inherit_quotation")
        for name in ("draft", "sales"):
            with self.subTest(duplicate=name):
                node = quotation.xpath("//filter[@name='%s']" % name)
                self.assertTrue(node)
                self.assertEqual(node[0].get("invisible"), "1",
                                 "Дубль наших «Выставлены» / «В работе» — спрятан.")
        action = self.env["ir.actions.act_window"]._for_xml_id("sale.action_orders")
        self.assertIn("search_default_pmk_current", action["context"])
        self.assertNotIn("search_default_sales", action["context"])

    def test_deal_form_buttons(self):
        arch = self._arch("crm.lead", "form")
        box = arch.xpath("//div[@name='button_box']")[0]
        names = [b.get("name") for b in box.iter("button")]
        i = names.index("action_open_dobors")
        self.assertEqual(names[i + 1:i + 3], ["action_open_invoice", "action_open_orders"])
        for name, field, label in (("action_open_invoice", "pmk_invoice_count", "Счёт"),
                                   ("action_open_orders", "pmk_order_count", "Заказ")):
            with self.subTest(button=name):
                button = box.xpath(".//button[@name='%s']" % name)[0]
                self.assertEqual(button.get("invisible"), "type == 'lead'")
                stat = button.find("field")
                self.assertEqual((stat.get("name"), stat.get("widget"), stat.get("string")),
                                 (field, "statinfo", label))
        icon = {b.get("name"): b.get("icon") for b in box.iter("button")}
        ours = {icon["action_open_invoice"], icon["action_open_orders"]}
        self.assertEqual(len(ours), 2)
        self.assertFalse(ours & {icon["action_open_specs"], icon["action_open_dobors"]},
                         "Значки свои: надписи кнопок тема прячет.")
        for name in ("action_view_sale_quotation", "action_view_sale_order"):
            with self.subTest(hidden=name):
                self.assertEqual(arch.xpath("//button[@name='%s']" % name)[0].get("invisible"), "1")

    def test_deal_buttons_open(self):
        deal = self._deal()
        self._spec(deal)
        action = deal.action_open_invoice()
        self.assertFalse(action.get("res_id"), "Счёта нет — список с подсказкой.")
        self.assertIn("«Счёт» в расчёте", str(action["help"]))
        self._send_kp(deal)
        invoice = self._invoices(deal)
        action = deal.action_open_invoice()
        self.assertEqual(action["res_id"], invoice.id)
        action = deal.action_open_orders()
        self.assertEqual(action["views"][0][1], "form")
        self.assertEqual(action["context"]["default_pmk_deal_id"], deal.id)
        self.assertEqual(action["context"]["default_project_id"], self.project.id)
        deal.action_set_won()
        row = self._rows(deal)
        self.assertEqual(deal.action_open_orders()["res_id"], row.id)
        self.assertEqual(invoice.action_open_planner_row()["res_id"], row.id)
        self.assertEqual(invoice.action_open_spec()["res_id"], deal.pmk_spec_id.id)

    def test_merge_keeps_rows(self):
        first = self._deal()
        second = self._deal(name="Дубль (шаг З-2)")
        first.action_set_won()
        second.action_set_won()
        rows = self._rows(first) | self._rows(second)
        self.assertEqual(len(rows), 2)
        merged = (first | second).merge_opportunity()
        self.assertEqual(rows.pmk_deal_id, merged, "Строки — у итоговой сделки.")

    # ─── Схема «Связи» (pmk_flow) ───────────────────────────────────────
    def test_flow_links(self):
        if "pmk.flow.builder" not in self.env:
            self.skipTest("pmk_flow не установлен")
        from odoo.addons.pmk_flow.models.flow_builder import _STAGES
        self.assertEqual(_STAGES["sale.order"][1], "Счёт покупателю")
        deal = self._deal()
        spec = self._spec(deal)
        self._send_kp(deal)
        invoice = self._invoices(deal)
        spec.product_ids.filtered("price_customer_unit")[:1].price_customer_unit = 4700.0
        spec._pmk_kp_move_stage(deal)
        snapshot = self._snapshots(invoice)
        deal.action_set_won()
        row = self._rows(deal)
        Builder = self.env["pmk.flow.builder"]

        def nodes(model, res_id):
            return {node["id"] for node in Builder.get_flow_graph(model, res_id)["nodes"]}

        around_invoice = nodes("sale.order", invoice.id)
        for key in ("pmk.metal.spec,%s" % spec.id, "crm.lead,%s" % deal.id,
                    "project.task,%s" % row.id):
            self.assertIn(key, around_invoice)
        around_spec = nodes("pmk.metal.spec", spec.id)
        self.assertIn("sale.order,%s" % invoice.id, around_spec)
        self.assertNotIn("sale.order,%s" % snapshot.id, around_spec, "Прежние редакции — не на схеме.")
        self.assertIn("project.task,%s" % row.id, nodes("crm.lead", deal.id))

    # ─── Нумератор ──────────────────────────────────────────────────────
    def test_sequence_hook(self):
        seq = self.env.ref("sale.seq_sale_order")
        self.env["sale.order"].create({"partner_id": self.client.id})
        seq.prefix = "S"
        hooks.post_init_hook(self.env)
        self.assertEqual(seq.prefix, "S", "Заказы есть — префикс не трогаем.")
        self.env["sale.order"].with_context(active_test=False).search([]).with_context(
            pmk_revision_freeze=True).sudo().filtered(lambda o: o.state in ("draft", "cancel")).unlink()
        if not self.env["sale.order"].with_context(active_test=False).search_count([]):
            hooks.post_init_hook(self.env)
            self.assertEqual(seq.prefix, hooks.PREFIX)
            self.assertEqual(seq.padding, 5)


@tagged("post_install", "-at_install")
class TestStep64Searchpanel(TransactionCase):
    """Шаг 64: в «Заказах в работе» слева панель «Статус» — только этапы планировщика."""

    def test_searchpanel_stages_of_orders_only(self):
        view = self.env.ref("pmk_orders.view_task_order_search")
        self.assertIn("<searchpanel", view.arch)
        res = self.env["project.task"].search_panel_select_multi_range(
            "stage_id", search_domain=[], expand=True, comodel_domain=[("project_ids.pmk_is_orders", "=", True)])
        names = {v["display_name"] for v in res["values"]}
        self.assertIn("Очередь", names)
        self.assertFalse(names & {"Новые", "В очереди"}, "этапы других проектов не попадают")
