# -*- coding: utf-8 -*-
"""Счёт МоегоСклада → сделка воронки (21.10.2026), на подставных ответах API."""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_org.hooks import ensure_taxes

from .test_moysklad import AGENTS, ORGS, meta, pos

H = "https://api.moysklad.ru/api/remap/1.2/entity/"


def _moment(days=0):
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S.000")


def invoice(mid, state, total=1000, shipped=0, updated=None, owner=None):
    row = dict(meta("invoiceout", mid), name="Т-%s" % mid, moment=_moment(),
               updated=updated or _moment(), organization=meta("organization", "o-chulkov"),
               agent=meta("counterparty", "c-1"), state={"name": state}, sum=total * 100,
               shippedSum=shipped * 100, vatEnabled=True, vatIncluded=True,
               attributes=[{"name": "Объект:", "value": "Площадка ПС"}],
               positions={"rows": [pos("Площадка обслуживания", 1, total, 22)]})
    if owner:
        row["owner"] = owner
    return row


@tagged("post_install", "-at_install")
class TestMsDealLink(TransactionCase):

    def setUp(self):
        super().setUp()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("pmk_moysklad.token", "test")
        params.set_param("pmk_moysklad.deals_since", "2026-01-01 00:00:00.000")
        ensure_taxes(self.env, self.env.company)
        self.invoices, self.demands = [], []
        test = self

        def fake_get(_self, path, params=None):
            if path.startswith("entity/invoiceout/"):
                mid = path.rsplit("/", 1)[-1]
                return next(i for i in test.invoices if i["meta"]["href"].endswith("/" + mid))
            if path.startswith("entity/counterparty/"):
                return AGENTS[0]
            rows = {"entity/organization": ORGS, "entity/counterparty": AGENTS,
                    "entity/invoiceout": test.invoices, "entity/demand": test.demands}[path]
            return {"rows": rows if not (params or {}).get("offset") else [], "meta": {"size": len(rows)}}

        patcher = patch.object(type(self.env["pmk.moysklad"]), "_ms_get", fake_get)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.env["res.partner"].create({
            "name": "ООО «Тест МойСклад»", "is_company": True, "vat": "2700000001", "pmk_ms_id": "c-1"})
        self.manager = self.env["res.users"].create({"name": "Иван Сделкин", "login": "ms_deal_mgr"})
        self.stage = {x: self.env.ref(x) for x in (
            "crm.stage_lead1", "pmk_deal.stage_invoiced", "pmk_deal.stage_in_work", "crm.stage_lead4")}

    def _sync(self):
        self.env["pmk.moysklad"].with_context(pmk_ms_no_commit=True).sync_all(full=True)

    def _order(self, mid):
        return self.env["sale.order"].with_context(active_test=False).search([("pmk_ms_id", "=", mid)])

    def _deal(self, **kw):
        vals = {"name": "Площадка", "type": "opportunity", "partner_id": self.client.id,
                "stage_id": self.stage["crm.stage_lead1"].id}
        vals.update(kw)
        return self.env["crm.lead"].create(vals)

    def test_invoice_moves_open_deal_through_funnel(self):
        deal = self._deal()
        self.invoices.append(invoice("a1", "Согласование"))
        self._sync()
        order = self._order("a1")
        self.assertEqual(order.opportunity_id, deal)
        self.assertEqual(deal.stage_id, self.stage["pmk_deal.stage_invoiced"])
        # Оплатили — «Оплачено / в работе»; счёт МоегоСклада Odoo не подтверждает,
        # строку «Заказов в работе» не заводит.
        self.invoices[0] = invoice("a1", "Оплачен", updated=_moment(1))
        self._sync()
        self.assertEqual(deal.stage_id, self.stage["pmk_deal.stage_in_work"])
        self.assertNotEqual(order.state, "sale")
        self.assertFalse(self.env["project.task"].with_context(active_test=False).search_count(
            [("pmk_deal_id", "=", deal.id)]))
        # Отгрузили на всю сумму — «Закрыта».
        self.invoices[0] = invoice("a1", "Оплачен", shipped=1000, updated=_moment(1))
        self.demands.append(dict(meta("demand", "d-a1"), moment=_moment(), updated=_moment(2),
                                 invoicesOut=[meta("invoiceout", "a1")]))
        self._sync()
        self.assertEqual(deal.stage_id, self.stage["crm.stage_lead4"])
        self.assertIn("МоегоСклада", " ".join(deal.message_ids.mapped("body")))

    def test_paid_invoice_without_deal_creates_deal(self):
        self.invoices.append(invoice("b1", "Предоплата получена", total=5000,
                                     owner={"firstName": "Иван", "lastName": "Сделкин"}))
        self._sync()
        deal = self._order("b1").opportunity_id
        self.assertTrue(deal)
        self.assertEqual(deal.stage_id, self.stage["pmk_deal.stage_in_work"])
        self.assertEqual((deal.pmk_source, deal.partner_id, deal.user_id), ("ms", self.client, self.manager))
        self.assertIn("Площадка ПС", deal.name)
        self.assertEqual(deal.expected_revenue, 5000)

    def test_unpaid_invoice_without_deal_no_deal(self):
        self.invoices.append(invoice("c1", "Согласование"))
        # Отгружен, а статус не ведут — тоже без сделки (прогон на копии 21.10).
        self.invoices.append(invoice("c2", "Согласование", shipped=1000))
        self._sync()
        self.assertFalse(self._order("c1").opportunity_id)
        self.assertFalse(self._order("c2").opportunity_id)
        self.assertFalse(self.env["crm.lead"].search_count([("pmk_source", "=", "ms")]))

    def test_paid_and_shipped_new_deal_closed_named_by_line(self):
        row = invoice("h1", "Оплачен", shipped=1000)
        row["attributes"] = [{"name": "Объект:", "value": "3"}]
        self.invoices.append(row)
        self._sync()
        deal = self._order("h1").opportunity_id
        self.assertEqual(deal.stage_id, self.stage["crm.stage_lead4"])
        self.assertTrue(deal.name.startswith("Площадка обслуживания"), deal.name)

    def test_old_invoices_untouched(self):
        deal = self._deal()
        self.invoices.append(invoice("d1", "Оплачен", updated="2025-12-31 10:00:00.000"))
        self._sync()
        self.assertFalse(self._order("d1").opportunity_id)
        self.assertEqual(deal.stage_id, self.stage["crm.stage_lead1"])

    def test_forward_only(self):
        deal = self._deal(stage_id=self.stage["pmk_deal.stage_in_work"].id)
        self.invoices.append(invoice("e1", "Согласование"))
        self._sync()
        self.assertEqual(self._order("e1").opportunity_id, deal)
        self.assertEqual(deal.stage_id, self.stage["pmk_deal.stage_in_work"],
                         "Новый счёт в «Согласовании» оплаченную сделку не откатывает.")

    def test_not_actual_loses_only_its_deal(self):
        deal = self._deal()
        self.invoices.append(invoice("f1", "Согласование"))
        self._sync()
        self.invoices[0] = invoice("f1", "Не актуальна", updated=_moment(1))
        self._sync()
        self.assertFalse(deal.active)
        self.assertEqual(deal.won_status, "lost")
        # Чужой отменённый счёт свежую сделку того же клиента не проигрывает.
        fresh = self._deal(name="Новая заявка")
        self.invoices.append(invoice("f2", "Не актуальна", updated=_moment(2)))
        self._sync()
        self.assertTrue(fresh.active)
        self.assertFalse(self._order("f2").opportunity_id)

    def test_late_deal_not_matched(self):
        """Сделка, заведённая больше чем через 3 дня после счёта, — не его."""
        deal = self._deal()
        row = invoice("g1", "Согласование")
        row["moment"] = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S.000")
        self.invoices.append(row)
        self._sync()
        self.assertFalse(self._order("g1").opportunity_id)
        self.assertEqual(deal.stage_id, self.stage["crm.stage_lead1"])

    # ── 18.11.2026: смена клиента в счёте, ручная привязка ─────────────────
    def _other_client(self):
        AGENTS_EXTRA = dict(meta("counterparty", "c-2"), name="ООО «Другой клиент»", inn="2700000002",
                            companyType="legal", updated="2026-10-01 10:00:00.000")
        return self.env["res.partner"].create({
            "name": AGENTS_EXTRA["name"], "is_company": True, "vat": "2700000002", "pmk_ms_id": "c-2"})

    def test_client_changed_relinks(self):
        """Копию счёта привязало к сделке прежнего клиента; клиента сменили — счёт уходит."""
        deal = self._deal()
        self.invoices.append(invoice("r1", "Согласование"))
        self._sync()
        order = self._order("r1")
        self.assertEqual(order.opportunity_id, deal)
        other = self._other_client()
        other_deal = self._deal(name="Сделка другого", partner_id=other.id)
        row = invoice("r1", "Согласование", updated=_moment(1))
        row["agent"] = meta("counterparty", "c-2")
        self.invoices[0] = row
        with patch.object(type(self.env["pmk.moysklad"]), "_partner_by_ms",
                          lambda _s, m, cache: other):
            self._sync()
        self.assertEqual(order.partner_id, other)
        self.assertEqual(order.opportunity_id, other_deal, "Подобрана сделка нового клиента.")
        self.assertIn("отвязан", " ".join(deal.message_ids.mapped("body")))

    def test_client_changed_no_deal_left_unlinked(self):
        deal = self._deal()
        self.invoices.append(invoice("r2", "Согласование"))
        self._sync()
        other = self._other_client()
        row = invoice("r2", "Согласование", updated=_moment(1))
        self.invoices[0] = row
        with patch.object(type(self.env["pmk.moysklad"]), "_partner_by_ms",
                          lambda _s, m, cache: other):
            self._sync()
        order = self._order("r2")
        self.assertFalse(order.opportunity_id, "У нового клиента сделки нет — счёт без сделки.")
        self.assertEqual(deal.stage_id, self.stage["pmk_deal.stage_invoiced"])

    def test_manual_link_kept(self):
        """Менеджер выбрал другую сделку того же клиента — синхронизация её не меняет."""
        older = self._deal(name="Старая")
        self.invoices.append(invoice("m1", "Согласование"))
        self._sync()
        order = self._order("m1")
        newer = self._deal(name="Правильная")
        self.assertNotEqual(order.opportunity_id, newer)
        order.opportunity_id = newer
        self.invoices[0] = invoice("m1", "Оплачен", updated=_moment(1))
        self._sync()
        self.assertEqual(order.opportunity_id, newer)
        self.assertEqual(newer.stage_id, self.stage["pmk_deal.stage_in_work"])
        self.assertTrue(older.exists())


@tagged("post_install", "-at_install")
class TestMsReconcile(TestMsDealLink):
    """Ночная сверка: счета, удалённые в МоёмСкладе, отменяются в Odoo."""

    def setUp(self):
        super().setUp()
        self.deleted = set()
        test = self
        base_get = type(self.env["pmk.moysklad"])._ms_get

        def fake_get(_self, path, params=None):
            if path.startswith("entity/invoiceout/"):
                mid = path.rsplit("/", 1)[-1]
                if mid in test.deleted:
                    return {"meta": {}, "deleted": "2026-11-18 07:50:59.545"}
            if path == "entity/invoiceout" and (params or {}).get("limit") == 1000:
                rows = [i for i in test.invoices if i["meta"]["href"].rsplit("/", 1)[-1] not in test.deleted]
                return {"rows": rows if not params.get("offset") else [], "meta": {"size": len(rows)}}
            return base_get(_self, path, params)

        patcher = patch.object(type(self.env["pmk.moysklad"]), "_ms_get", fake_get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_deleted_invoice_cancelled_and_detached(self):
        deal = self._deal()
        self.invoices += [invoice("x1", "Согласование"), invoice("x2", "Согласование")]
        self._sync()
        gone, kept = self._order("x1"), self._order("x2")
        self.assertEqual(gone.opportunity_id, deal)
        self.deleted.add("x1")
        done = self.env["pmk.moysklad"]._cron_ms_reconcile()
        self.assertEqual(done, 1)
        self.assertEqual(gone.state, "cancel")
        self.assertFalse(gone.opportunity_id)
        self.assertNotEqual(kept.state, "cancel")
        self.assertIn("удалён в МоёмСкладе", " ".join(deal.message_ids.mapped("body")))

    def test_mass_disappearance_ignored(self):
        """Пропало слишком много — это сбой, а не работа менеджеров: ничего не отменяем."""
        mids = ["y%s" % n for n in range(30)]
        self.invoices += [invoice(m, "Согласование") for m in mids]
        self._sync()
        self.deleted.update(mids[:25])
        self.assertEqual(self.env["pmk.moysklad"]._cron_ms_reconcile(), 0)
        self.assertFalse(self.env["sale.order"].search_count(
            [("pmk_ms_id", "in", mids), ("state", "=", "cancel")]))

    def test_not_confirmed_not_cancelled(self):
        """Нет в списке, но отдельный запрос удаление не подтвердил — не трогаем."""
        self.invoices += [invoice("z1", "Согласование"), invoice("z2", "Согласование")]
        self._sync()
        order = self._order("z1")
        listed = [i for i in self.invoices if not i["meta"]["href"].endswith("/z1")]
        with patch.object(type(self.env["pmk.moysklad"]), "_ms_all_invoice_ids",
                          lambda _s: {i["meta"]["href"].rsplit("/", 1)[-1] for i in listed}):
            self.assertEqual(self.env["pmk.moysklad"]._cron_ms_reconcile(), 0)
        self.assertNotEqual(order.state, "cancel")
