# -*- coding: utf-8 -*-
"""«Оплачено, а отгрузки нет» — Телеграм Чулкову (21.10.2026)."""
from datetime import date, datetime, timedelta
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_moysklad.models import ship_watch as sw
from odoo.addons.pmk_org.hooks import ensure_taxes


@tagged("post_install", "-at_install")
class TestShipWatch(TransactionCase):

    def setUp(self):
        super().setUp()
        ensure_taxes(self.env, self.env.company)
        self.client = self.env["res.partner"].create({"name": "ООО «Отгрузка»", "is_company": True})
        self.chulkov = self.env["res.users"].create({"name": "Владислав Чулков", "login": "chulkov_test"})
        if "pmk_telegram_id" in self.chulkov._fields:
            self.chulkov.pmk_telegram_id = "777000111"

    def _order(self, name, state="Оплачен", paid_on=date(2026, 10, 12), lead=0, total=1000.0, shipped=0.0,
               when=datetime(2026, 10, 12, 3)):
        return self.env["sale.order"].create({
            "name": name, "partner_id": self.client.id, "date_order": when, "pmk_ms_id": "ms-" + name,
            "pmk_ms_state": state, "pmk_ms_sum": total, "pmk_ms_shipped_sum": shipped,
            "pmk_ms_paid_on": paid_on, "pmk_lead_days": lead})

    def test_due_dates(self):
        no_term = self._order("Т1")
        self.assertEqual(no_term._pmk_ship_due(), date(2026, 10, 22), "без срока — 10 дней")
        term = self._order("Т2", lead=5)  # пн 12.10 + 5 раб. дн. = пн 19.10, + 5 дней запаса
        self.assertEqual(term._pmk_ship_due(), date(2026, 10, 24))
        self.assertEqual(sw.add_workdays(date(2026, 10, 16), 1), date(2026, 10, 19), "пятница + 1 раб. = понедельник")

    def test_pending_filters(self):
        late = self._order("Т3")
        self._order("Т4", shipped=1000.0)                                     # отгружен полностью
        self._order("Т5", state="Согласование")                               # не оплачен
        self._order("Т6", when=datetime(2026, 10, 1, 3), paid_on=date(2026, 10, 1))  # до 10.10
        self._order("Т7", paid_on=date(2026, 10, 20))                        # срок не вышел
        part = self._order("Т8", state="Постоплата", shipped=400.0)          # отгружен частично
        pending = self.env["sale.order"]._pmk_ship_pending(date(2026, 10, 23))
        self.assertEqual(set(pending.mapped("name")), {"Т3", "Т8"})
        self.assertIn(late, pending)
        self.assertIn(part, pending)

    def test_paid_on_set_by_sync(self):
        order = self._order("Т9", state="Согласование", paid_on=False)
        order.pmk_ms_state = "Оплачен"
        self.env["pmk.moysklad"]._ms_deal_after_upsert(order, {"updated": "2020-01-01 00:00:00.000"})
        self.assertTrue(order.pmk_ms_paid_on)

    def test_cron_sends_once_then_monday_full(self):
        if "pmk.telegram.bot" not in self.env:
            self.skipTest("без pmk_telegram сводку не отправить")
        self._order("Т10")
        Bot = type(self.env["pmk.telegram.bot"])
        sent = []
        with patch.object(Bot, "pmk_send_user", lambda _s, user, text, reply_markup=None: sent.append((user, text)) or True), \
                patch.object(sw.fields.Datetime, "now", return_value=datetime(2026, 10, 23, 0, 0)):  # пт 23.10 Хабаровск
            self.assertTrue(self.env["pmk.moysklad"]._cron_ship_watch())
            self.env["pmk.moysklad"]._cron_ship_watch()  # второй раз — про тот же счёт молчит
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], self.chulkov)
        self.assertIn("Т10", sent[0][1])
        self.assertIn("ООО «Отгрузка»", sent[0][1])
        self.assertIn("просрочено 1 дн.", sent[0][1])
        with patch.object(Bot, "pmk_send_user", lambda _s, user, text, reply_markup=None: sent.append((user, text)) or True), \
                patch.object(sw.fields.Datetime, "now", return_value=datetime(2026, 10, 26, 0, 0)):  # пн 26.10
            self.env["pmk.moysklad"]._cron_ship_watch()
        self.assertEqual(len(sent), 2, "в понедельник — полный список, и уже напомненные тоже")
        self.assertIn("всё, что висит", sent[1][1])
