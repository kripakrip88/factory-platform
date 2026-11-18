# -*- coding: utf-8 -*-
"""Карточки действий ассистента (19.11.2026): письмо → сделка и контрагент, спецификация →
расчёт «Конструкции». Claude и DaData — заглушки."""
import base64
import io
import json
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

DADATA = {"name": {"short_with_opf": "ООО \"СТРОЙПРИМЕР\"", "full_with_opf": "ООО \"СТРОЙПРИМЕР\""},
          "address": {"value": "г Хабаровск, ул Тестовая, д 1", "data": {"city": "Хабаровск"}},
          "state": {"status": "ACTIVE"}, "kpp": "272101001", "ogrn": "1022700000000"}

KONSTR = {"products": [
    {"name": "МН 111-1", "qty": 240, "details": [
        {"pos": "1", "name": "Лист 10х200", "length_mm": 300, "qty": 1, "grade": "С255"},
        {"pos": "2", "name": "Арматура А500С 12", "length_mm": 600, "qty": 4}]},
    {"name": "МН 112-2", "qty": 10, "details": [
        {"pos": "1", "name": "Уголок 63х5", "length_mm": 1200, "qty": 2, "grade": "С345"}]}],
    "unclear": ["стр. 7: «закладная по месту» — без размеров"], "note": "2 изделия"}


def _claude(data, name="konstr"):
    return ({"content": [{"type": "tool_use", "name": name, "input": data}],
             "usage": {"input_tokens": 2000, "output_tokens": 500}}, 1.0)


@tagged("post_install", "-at_install")
class TestAiActions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("pmk_ai.api_key", "test-key")
        params.set_param("pmk_ai.budget", "100")
        cls.Chat = cls.env["pmk.ai.chat"]
        server = cls.env["mail.client.server"].create({
            "name": "тест", "imap_host": "mail.invalid", "auth_mode": "master", "master_user": "m"})
        cls.account = cls.env["mail.client.account"].create({
            "name": "Почта (тест действий)", "email": "actions-test@example.org", "server_id": server.id,
            "user_id": cls.env.uid})
        cls.inbox = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": cls.account.id, "imap_path": "INBOX", "role": "inbox"})
        cls.client = cls.env["res.partner"].create({"name": "ООО «Клиент действий»", "is_company": True})

    def _letter(self, sender="Алёна Лыкова <lykova@stroyprimer.example>", subject="Заявка на закладные МН 111-1"):
        return self.env["mail.client.message"].create({
            "account_id": self.account.id, "folder_id": self.inbox.id, "imap_uid": 77001, "subject": subject,
            "email_from": sender, "date": fields.Datetime.now(), "body_state": "fetched",
            "body_html": "<p>Просим рассчитать закладные, 240 шт. ООО «Стройпример», ИНН 2721999998.</p>",
            "message_id": "<a1@test>", "thread_key": "<a1@test>"})

    def _card(self, result):
        self.assertIn("карточка", result, result)
        return self.env["pmk.ai.proposal"].browse(result["карточка"])

    # ─── письмо → сделка ─────────────────────────────────────────────────
    def test_letters_found_by_sender(self):
        letter = self._letter()
        res = self.Chat._run_tool("find_letters", {"who": "лыкова"})
        self.assertIn(letter.id, [row["id"] for row in res["письма"]])
        text = self.Chat._run_tool("read_letter", {"id": letter.id})["текст"]
        self.assertIn("ИНН 2721999998", text)

    def test_deal_and_partner_from_letter(self):
        letter = self._letter()
        Message = type(self.env["mail.client.message"])
        Partner = type(self.env["res.partner"])
        with patch.object(Partner, "_pmk_dadata_find", return_value=DADATA):
            prop = self._card(self.Chat._run_tool("propose_deal", {
                "letter_id": letter.id, "title": "Закладные МН 111-1, 240 шт", "inn": "2721999998",
                "contact": "Алёна Лыкова", "phone": "+7 914 000-00-00"}))
        self.assertEqual(prop.state, "proposed")
        self.assertFalse(self.env["crm.lead"].search_count([("name", "=", "Закладные МН 111-1, 240 шт")]),
                         "До кнопки ничего не создано.")
        self.assertIn("заведу новым", json.dumps(json.loads(prop.lines_json), ensure_ascii=False))
        with patch.object(Partner, "_pmk_dadata_find", return_value=DADATA), \
                patch.object(Message, "_pmk_letter_attachments", return_value=([], [])):
            card = self.Chat.execute_proposal(prop.id)
        self.assertEqual(card["state"], "done", card)
        lead = self.env["crm.lead"].browse(card["result"]["id"])
        self.assertEqual(lead.type, "opportunity")
        self.assertEqual(lead.name, "Закладные МН 111-1, 240 шт")
        company = lead.partner_id.commercial_partner_id
        self.assertEqual((company.vat, company.is_company), ("2721999998", True))
        self.assertEqual(lead.partner_id.name, "Алёна Лыкова")
        self.assertEqual(letter.pmk_lead_id, lead)
        # Второй раз — не выполняется.
        self.assertEqual(self.Chat.execute_proposal(prop.id)["state"], "done")
        self.assertEqual(self.env["crm.lead"].search_count([("name", "=", "Закладные МН 111-1, 240 шт")]), 1)

    def test_letter_already_in_deal(self):
        letter = self._letter()
        letter.pmk_lead_id = self.env["crm.lead"].create({"name": "Уже есть", "type": "opportunity"})
        res = self.Chat._run_tool("propose_deal", {"letter_id": letter.id, "title": "Дубль"})
        self.assertIn("ошибка", res)

    # ─── спецификация → расчёт «Конструкции» ─────────────────────────────
    def _deal_with_file(self):
        import openpyxl
        deal = self.env["crm.lead"].create({"name": "Закладные", "type": "opportunity", "partner_id": self.client.id})
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(["Поз.", "Наименование", "Длина", "Кол-во", "Марка"])
        sheet.append(["1", "-10х200", 300, 1, "С255"])
        buf = io.BytesIO()
        book.save(buf)
        att = self.env["ir.attachment"].create({
            "name": "Спецификация.xlsx", "res_model": "crm.lead", "res_id": deal.id,
            "datas": base64.b64encode(buf.getvalue())})
        return deal, att

    def test_konstr_from_spec_file(self):
        deal, att = self._deal_with_file()
        files = self.Chat._run_tool("deal_files", {"deal_id": deal.id})
        self.assertIn(att.id, [f["id"] for f in files["файлы"]])
        with patch("odoo.addons.pmk_ai.tools.claude.messages", return_value=_claude(KONSTR)) as api:
            prop = self._card(self.Chat._run_tool("propose_konstr", {"deal_id": deal.id, "attachment_id": att.id}))
        self.assertTrue(api.called)
        self.assertIn("Не понял 1", prop.warn)
        self.assertFalse(self.env["pmk.metal.spec"].search_count([("opportunity_id", "=", deal.id)]))
        card = self.Chat.execute_proposal(prop.id)
        self.assertEqual(card["state"], "done", card)
        spec = self.env["pmk.metal.spec"].browse(card["result"]["id"])
        self.assertEqual(spec.opportunity_id, deal)
        self.assertEqual(spec.partner_id, self.client)
        self.assertEqual(spec.product_ids.sorted("sequence").mapped("name"), ["МН 111-1", "МН 112-2"])
        self.assertEqual(spec.product_ids.sorted("sequence")[0].qty, 240)
        lines = spec.product_ids.mapped("line_ids")
        self.assertEqual(len(lines), 3)
        self.assertIn("Уголок 63х5", lines.mapped("pmk_text"))

    def test_other_file_refused(self):
        deal, _att = self._deal_with_file()
        other, foreign = self._deal_with_file()
        res = self.Chat._run_tool("propose_konstr", {"deal_id": deal.id, "attachment_id": foreign.id})
        self.assertIn("ошибка", res)

    # ─── чужая карточка, отмена, подсказка ───────────────────────────────
    def test_foreign_card_and_cancel(self):
        deal, att = self._deal_with_file()
        with patch("odoo.addons.pmk_ai.tools.claude.messages", return_value=_claude(KONSTR)):
            prop = self._card(self.Chat._run_tool("propose_konstr", {"deal_id": deal.id, "attachment_id": att.id}))
        stranger = self.env["res.users"].create({"name": "Чужой", "login": "ai_actions_stranger"})
        with self.assertRaises(AccessError):
            self.Chat.with_user(stranger).execute_proposal(prop.id)
        self.assertEqual(self.Chat.cancel_proposal(prop.id)["state"], "cancelled")
        self.assertEqual(self.Chat.execute_proposal(prop.id)["state"], "cancelled")

    def test_system_knows_cards(self):
        text = self.Chat._system({})[0]["text"]
        self.assertIn("propose_deal", text)
        self.assertNotIn("Инструменты только читают: если нужно", text)
        names = [t["name"] for t in self.Chat._tools()]
        for name in ("find_letters", "read_letter", "deal_files", "propose_deal", "propose_konstr", "search_records"):
            self.assertIn(name, names)
