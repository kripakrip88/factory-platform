# -*- coding: utf-8 -*-
"""Разбор почты ассистентом (20.10.2026): очередь, отсев без ассистента,
заявка → сделка в колонке «Разобрал ассистент», оценка и замечания."""
import io
import json
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..tools import parts

REQUEST = {
    "kind": "request", "title": "Вентзонты 10 шт — АЭС", "summary": "Просят КП на 10 вентзонтов до 22.10.",
    "reason": "Есть изделия и просьба КП.",
    "client": {"company": "ООО «Энергомонтаж»", "inn": "2721000000", "contact": "Ирина Петрова",
               "phone": "+7 914 000-00-00"},
    "items": [{"name": "Зонт 800×1600", "qty": "6", "unit": "шт", "note": "оцинк. 0,65"}],
    "deadline": "КП до 22.10", "place": "Хабаровск", "missing": ["цвет RAL"],
}


def _response(data, usage=None):
    """Как claude.messages: (ответ, секунды)."""
    return ({"content": [{"type": "tool_use", "name": "triage", "input": data}],
             "usage": usage or {"input_tokens": 3000, "output_tokens": 400}}, 1.0)


@tagged("post_install", "-at_install")
class TestMailTriage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reviewer = cls.env["res.users"].create({
            "name": "Проверяющий (тест)", "login": "ai_reviewer_test",
            "group_ids": [(4, cls.env.ref("sales_team.group_sale_salesman_all_leads").id)]})
        server = cls.env["mail.client.server"].create({
            "name": "тест", "imap_host": "mail.invalid", "auth_mode": "master", "master_user": "m"})
        cls.account = cls.env["mail.client.account"].create({
            "name": "Заявки (тест)", "email": "zayavki-test@example.org", "server_id": server.id,
            "user_id": cls.env.uid})
        cls.inbox = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": cls.account.id, "imap_path": "INBOX", "role": "inbox"})
        cls.other = cls.env["mail.client.folder"].create({
            "name": "Чеки", "account_id": cls.account.id, "imap_path": "Receipts", "role": "other"})
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("pmk_ai_mail.enabled", "1")
        params.set_param("pmk_ai_mail.account", "zayavki-test@example.org")
        params.set_param("pmk_ai_mail.since", "2026-01-01 00:00:00")
        params.set_param("pmk_ai_mail.user_id", str(cls.reviewer.id))
        params.set_param("pmk_ai.api_key", "test-key")
        params.set_param("pmk_ai.budget", "100")
        cls.Triage = cls.env["pmk.ai.mail.triage"]
        cls.uid_seq = 1000

    def _letter(self, subject="Запрос КП на зонты", sender="Ирина <snab@energo.example.com>",
                folder=None, thread=None, **kw):
        type(self).uid_seq += 1
        vals = {"account_id": self.account.id, "folder_id": (folder or self.inbox).id,
                "imap_uid": self.uid_seq, "subject": subject, "email_from": sender,
                "date": fields.Datetime.now(), "body_html": "<p>Прошу КП на зонты 800×1600 — 6 шт.</p>",
                "body_state": "fetched", "message_id": "<m%s@test>" % self.uid_seq,
                "thread_key": thread or "<m%s@test>" % self.uid_seq}
        vals.update(kw)
        return self.env["mail.client.message"].create(vals)

    def _run(self, letter, response=None, attachments=([], [])):
        """Поставить в очередь, взять и разобрать — с заглушкой Claude и без IMAP."""
        self.Triage._enqueue()
        triage = self.Triage.search([("message_id", "=", letter.id)])
        self.assertTrue(triage)
        triage.state = "running"
        Message = type(self.env["mail.client.message"])
        with patch("odoo.addons.pmk_ai.tools.claude.messages", return_value=response) as api, \
                patch.object(Message, "_pmk_letter_attachments", return_value=attachments):
            self.Triage._process(triage.id)
        return triage, api

    def test_request_becomes_deal_in_ai_column(self):
        letter = self._letter()
        triage, api = self._run(letter, _response(REQUEST))
        self.assertEqual(api.call_count, 1)
        payload = api.call_args[0][1]
        self.assertEqual(payload["tool_choice"], {"type": "auto"})
        self.assertIn("Запрос КП на зонты", payload["messages"][0]["content"][0]["text"])
        self.assertEqual((triage.state, triage.kind), ("done", "request"))
        lead = triage.lead_id
        self.assertTrue(lead)
        self.assertEqual(lead.stage_id, self.env.ref("pmk_ai_mail.stage_ai"))
        self.assertEqual(lead.type, "opportunity")
        self.assertEqual(lead.name, "Вентзонты 10 шт — АЭС")
        self.assertEqual(lead.user_id, self.reviewer)
        self.assertEqual(lead.pmk_ai_triage_id, triage)
        self.assertEqual(letter.pmk_lead_id, lead)
        self.assertIn("Энергомонтаж", lead.pmk_ai_card)
        self.assertEqual(lead.partner_name, "ООО «Энергомонтаж»", "Нового клиента — организацией из письма.")
        self.assertIn("Зонт 800×1600", lead.pmk_ai_card)
        self.assertGreater(triage.usage_id.cost, 0)
        self.assertEqual(triage.usage_id.user_id, self.reviewer)

    def test_json_in_text_accepted(self):
        """Модель ответила текстом с JSON вместо вызова — тоже разбор."""
        triage, _api = self._run(self._letter(), ({"content": [{"type": "text", "text": "Вот: " + json.dumps(
            {"kind": "ad", "summary": "Реклама.", "reason": "рассылка"}, ensure_ascii=False)}],
            "usage": {"input_tokens": 100, "output_tokens": 20}}, 1.0))
        self.assertEqual((triage.state, triage.kind), ("done", "ad"))

    def test_missing_files_told_to_model(self):
        """Файл не скачался — ассистент знает, что он был, а не «вложения нет»."""
        letter = self._letter(subject="Счёт", pmk_attachment_names="Счёт 28611.pdf")
        triage, api = self._run(letter, _response({"kind": "supplier", "summary": "Счёт.", "reason": "счёт"}),
                                attachments=([], [("Счёт 28611.pdf", "IMAP недоступен")]))
        head = api.call_args[0][1]["messages"][0]["content"][0]["text"]
        self.assertIn("Счёт 28611.pdf — не скачан", head)
        self.assertIn("Счёт 28611.pdf — не скачан", triage.files_note)
        letter2 = self._letter(subject="Счёт 2", pmk_attachment_names="a.pdf\nb.xlsx")
        _t, api2 = self._run(letter2, _response({"kind": "supplier", "summary": "Счёт.", "reason": "счёт"}))
        self.assertIn("a.pdf, b.xlsx", api2.call_args[0][1]["messages"][0]["content"][0]["text"])

    def test_not_request_no_deal(self):
        triage, _api = self._run(self._letter(subject="Счёт на оплату", sender="kutilov@mc.example.ru"),
                                 _response({"kind": "supplier", "summary": "Счёт поставщика.", "reason": "счёт"}))
        self.assertEqual((triage.state, triage.kind), ("done", "supplier"))
        self.assertFalse(triage.lead_id)

    def test_free_skips_without_ai(self):
        own = self._letter(sender="Мы <zayavki-test@example.org>")
        robot = self._letter(sender="noreply@ag.example.market")
        for letter, kind in ((own, "internal"), (robot, "auto")):
            triage, api = self._run(letter, _response(REQUEST))
            self.assertEqual(api.call_count, 0, kind)
            self.assertEqual((triage.state, triage.kind), ("skipped", kind))

    def test_own_forward_goes_to_ai(self):
        """Сотрудник переслал письмо клиента в ящик — это может быть заявка."""
        letter = self._letter(subject="Fwd: МК ПС Амурская", sender="pmkpark <zayavki-test@example.org>")
        triage, api = self._run(letter, _response(REQUEST))
        self.assertEqual(api.call_count, 1)
        self.assertEqual(triage.kind, "request")

    def test_same_letter_twice_one_deal(self):
        first = self._letter(subject="Fwd: МК ПС Амурская")
        triage, _api = self._run(first, _response(REQUEST))
        again = self._letter(subject="Fwd: МК ПС Амурская")
        triage2, api = self._run(again, _response(REQUEST))
        self.assertEqual(api.call_count, 0)
        self.assertEqual((triage2.kind, triage2.lead_id), ("reply", triage.lead_id))

    def test_reply_in_deal_thread_linked(self):
        first = self._letter()
        triage, _api = self._run(first, _response(REQUEST))
        reply = self._letter(subject="RE: Запрос КП на зонты", thread=first.thread_key)
        triage2, api = self._run(reply, _response(REQUEST))
        self.assertEqual(api.call_count, 0, "Ответ в переписке сделки — без ассистента.")
        self.assertEqual((triage2.kind, triage2.lead_id), ("reply", triage.lead_id))
        self.assertEqual(reply.pmk_lead_id, triage.lead_id)

    def test_enqueue_only_inbox_since_not_spam(self):
        old = self._letter(date=fields.Datetime.to_datetime("2025-12-31 10:00:00"))
        receipt = self._letter(folder=self.other)
        spam = self._letter(is_spam=True)
        fresh = self._letter()
        self.Triage._enqueue()
        queued = self.Triage.search([]).message_id
        self.assertIn(fresh, queued)
        for letter in (old, receipt, spam):
            self.assertNotIn(letter, queued)
        self.Triage._enqueue()
        self.assertEqual(self.Triage.search_count([("message_id", "=", fresh.id)]), 1, "Без повторов.")

    def test_default_stage_is_not_ai_column(self):
        lead = self.env["crm.lead"].create({"name": "Вручную", "type": "opportunity"})
        self.assertNotEqual(lead.stage_id, self.env.ref("pmk_ai_mail.stage_ai"))

    def test_rating_and_feedback_teach_next_prompt(self):
        triage, _api = self._run(self._letter(), _response(REQUEST))
        lead = triage.lead_id.with_user(self.reviewer)
        lead.action_pmk_ai_bad()
        lead.write({"pmk_ai_feedback": "АЭС — постоянный клиент, цвет всегда RAL 8017"})
        self.assertEqual((triage.rating, triage.rated_by), ("bad", self.reviewer))
        self.assertIn("RAL 8017", triage.feedback)
        system = self.Triage._system()[0]["text"]
        self.assertIn("Замечания проверяющего", system)
        self.assertIn("RAL 8017", system)

    def test_budget_over_waits_in_queue(self):
        self.env["ir.config_parameter"].sudo().set_param("pmk_ai.budget", "0")
        triage, api = self._run(self._letter(), _response(REQUEST))
        self.assertEqual(api.call_count, 0)
        self.assertEqual(triage.state, "queued")

    def test_worker_jobs_include_triage(self):
        self._letter()
        jobs = self.env["pmk.ai.chat"]._worker_jobs(4)
        self.assertTrue([j for j in jobs if j[0] == "pmk.ai.mail.triage"])
        self.env["ir.config_parameter"].sudo().set_param("pmk_ai_mail.enabled", "0")
        self.assertFalse([j for j in self.env["pmk.ai.chat"]._worker_jobs(4) if j[0] == "pmk.ai.mail.triage"])


@tagged("post_install", "-at_install")
class TestTriageParts(TransactionCase):

    def test_blocks(self):
        from PIL import Image
        big = io.BytesIO()
        Image.new("RGB", (2400, 1800), (200, 30, 30)).save(big, "PNG")
        noisy = io.BytesIO()
        Image.effect_noise((900, 900), 80).convert("RGB").save(noisy, "PNG")
        logo = io.BytesIO()
        Image.new("RGB", (60, 20), (0, 0, 0)).save(logo, "PNG")
        import openpyxl
        book = openpyxl.Workbook()
        book.active.append(["Наименование", "Кол-во"])
        book.active.append(["Зонт 800×1600", 6])
        xlsx = io.BytesIO()
        book.save(xlsx)
        pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        blocks, notes = parts.build([("logo.png", logo.getvalue()), ("скан.png", noisy.getvalue()),
                                     ("ТЗ.pdf", pdf), ("Спец.xlsx", xlsx.getvalue()),
                                     ("чертёж.dwg", b"AC1027" + b"0" * 100)])
        kinds = [b["type"] for b in blocks]
        self.assertIn("image", kinds)
        self.assertIn("document", kinds)
        self.assertTrue(any("Зонт 800×1600" in b.get("text", "") for b in blocks))
        joined = "\n".join(notes)
        self.assertIn("logo.png — пропущен", joined)
        self.assertIn("чертёж.dwg — только имя", joined)
        image = next(b for b in blocks if b["type"] == "image")
        self.assertEqual(image["source"]["media_type"], "image/jpeg")
        self.assertTrue(json.dumps(blocks))
