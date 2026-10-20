# -*- coding: utf-8 -*-
"""Воронка «сделка → (расчёт) → счёт», меню документов, обзвон лидов (20.10.2026).

Гонять ТОЛЬКО на одноразовой базе. Ловим: порядок стадий без «КП отправлено»;
расчёт ставит сделку в «Расчёт» — и назад из «Счёт выставлен» (решение Антона),
но не трогает закрытую; меню отдаёт пункты, «КП (PDF)» — только когда есть
расчёт; дата следующего звонка лида — одна задача «Звонок», дату переносим.
"""
import datetime

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDealFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env["crm.lead"].with_context(mail_create_nolog=True)
        cls.client = cls.env["res.partner"].create({"name": "ООО «Тест воронки»", "is_company": True})
        cls.st_request = cls.env.ref("crm.stage_lead1")
        cls.st_calc = cls.env.ref("crm.stage_lead2")
        cls.st_invoiced = cls.env.ref("pmk_deal.stage_invoiced")
        cls.st_closed = cls.env.ref("crm.stage_lead4")

    def _deal(self, stage):
        return self.Lead.create({"name": "Решётки (тест воронки)", "type": "opportunity",
                                 "partner_id": self.client.id, "stage_id": stage.id})

    def _spec(self, deal):
        return self.env["pmk.metal.spec"].with_context(mail_create_nolog=True).create({
            "opportunity_id": deal.id, "partner_id": self.client.id,
            "product_ids": [Command.create({"name": "Решётка", "qty": 1})]})

    def test_stages_order(self):
        Stage = self.env["crm.stage"]
        # Колонка «Разобрал ассистент» (pmk_ai_mail) стоит перед воронкой — не этап сделки.
        domain = [("pmk_ai_only", "=", False)] if "pmk_ai_only" in Stage._fields else []
        names = Stage.search(domain, order="sequence, id").mapped("name")
        self.assertEqual(names[:5], ["Заявка", "Расчёт", "Счёт выставлен", "Оплачено / в работе", "Закрыта"])
        self.assertFalse(self.env.ref("crm.stage_lead3", raise_if_not_found=False),
                         "«КП отправлено» убрана (Антон 20.10: «не нужна»).")
        self.assertTrue(self.st_closed.is_won)

    def test_spec_moves_deal_back_and_forth(self):
        deal = self._deal(self.st_request)
        self._spec(deal)
        self.assertEqual(deal.stage_id, self.st_calc)
        deal.stage_id = self.st_invoiced
        self._spec(deal)
        self.assertEqual(deal.stage_id, self.st_calc, "Расчёт после счёта откатывает — решение Антона.")

    def test_closed_or_lost_untouched(self):
        won = self._deal(self.st_request)
        won.action_set_won()
        stage = won.stage_id
        self._spec(won)
        self.assertEqual(won.stage_id, stage)
        lost = self._deal(self.st_request)
        lost.action_set_lost()
        self._spec(lost)
        self.assertEqual(lost.with_context(active_test=False).stage_id, self.st_request)

    def test_doc_menu(self):
        deal = self._deal(self.st_request)
        menu = deal.pmk_doc_menu()
        keys = [item["key"] for item in menu["create"]]
        self.assertEqual(keys[0], "spec")
        self.assertIn("task", keys)
        self.assertNotIn("kp", keys, "«КП из расчёта» не нужна (Антон 20.10).")
        self.assertEqual(menu["print"], [], "Печатать нечего, пока нет расчёта.")
        self._spec(deal)
        self.assertEqual([i["key"] for i in deal.pmk_doc_menu()["print"]], ["kp"])
        self.assertEqual(self.env["crm.lead"].pmk_doc_menu()["print"], [], "Несохранённая сделка.")
        action = deal.action_pmk_new_spec()
        self.assertEqual(action["res_model"], "pmk.metal.spec")
        self.assertEqual(action["context"]["default_opportunity_id"], deal.id)
        task = deal.action_pmk_new_task()
        self.assertEqual(task["res_model"], "mail.activity.schedule")
        self.assertEqual(task["context"]["active_ids"], deal.ids)

    def test_next_call_plans_one_task(self):
        call = self.env.ref("mail.mail_activity_data_call")
        today = fields.Date.context_today(self.env["crm.lead"])
        lead = self.Lead.create({"name": "Лид для обзвона", "type": "lead",
                                 "pmk_next_call": today + datetime.timedelta(days=2)})
        self.assertEqual(lead.pmk_call_state, "new")
        planned = lead.activity_ids.filtered(lambda a: a.activity_type_id == call)
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned.date_deadline, today + datetime.timedelta(days=2))
        lead.write({"pmk_next_call": today + datetime.timedelta(days=5), "pmk_call_state": "recall"})
        planned = lead.activity_ids.filtered(lambda a: a.activity_type_id == call)
        self.assertEqual(len(planned), 1, "Дату переносим, а не плодим задачи.")
        self.assertEqual(planned.date_deadline, today + datetime.timedelta(days=5))
        lead.pmk_next_call = False
        self.assertFalse(lead.activity_ids.filtered(lambda a: a.activity_type_id == call))
