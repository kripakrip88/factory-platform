# -*- coding: utf-8 -*-
"""Вкладка «Письма» в сделке (15.10.2026): письма сделки, «Ещё письма
клиента — не привязаны», привязка и отвязка, переход в почту, отдельное окно.

Данные обезличены (example.org). Почтовый сервер не трогаем: у писем текст
уже есть, вложений нет.
"""
from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..tools import deal_letters as rules

# Ящик — на своём домене: свой домен ключом клиента не бывает.
BOX = "letters.box@pmk.example.net"


@tagged("post_install", "-at_install")
class TestDealLettersRules(TransactionCase):
    """Чистые правила tools/deal_letters.py."""

    def test_addresses(self):
        self.assertEqual(rules.addresses('"Иван, ООО Ромашка" <Ivan@Client.example.org>, b@x.ru', None),
                         ["ivan@client.example.org", "b@x.ru"])

    def test_registrable_domain(self):
        self.assertEqual(rules.domain_of("dmk@mail.redcom.ru"), "redcom.ru")
        self.assertEqual(rules.domain_of("a@shop.com.ru"), "shop.com.ru")
        self.assertEqual(rules.domain_of("broken"), "")

    def test_client_keys_skip_public_and_own(self):
        mails, domains = rules.client_keys(
            ["ivan@zavod.example.org", "petr@mail.ru", "box@pmkpark.ru", ""],
            own_addresses=["box@pmkpark.ru", "zakaz@pmkpark.ru"])
        self.assertEqual(mails, ["ivan@zavod.example.org", "petr@mail.ru"])
        # mail.ru — общая служба: только адрес, не домен; свой домен — никак.
        self.assertEqual(domains, ["example.org"])

    def test_match_reason(self):
        self.assertEqual(rules.match_reason(["buh@hab.zavod.ru"], [], ["zavod.ru"]), "domain")
        self.assertIsNone(rules.match_reason(["x@zavod.ru.example.com"], [], ["zavod.ru"]))
        mails, domains = ["ivan@zavod.ru"], ["zavod.ru"]
        self.assertEqual(rules.match_reason(["ivan@zavod.ru"], mails, domains), "address")
        self.assertEqual(rules.match_reason(["buh@zavod.ru"], mails, domains), "domain")
        self.assertIsNone(rules.match_reason(["x@other.ru"], mails, domains))
        # «_» в LIKE — любой знак: ivanXzavod.ru не адрес клиента.
        self.assertIsNone(rules.match_reason(["ivan@zavodXru.com"], mails, []))


@tagged("post_install", "-at_install")
class TestDealLetters(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server = cls.env["mail.client.server"].create({
            "name": "Stub", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master"})
        cls.account = cls.env["mail.client.account"].create({
            "name": "Letters", "email": BOX, "server_id": server.id, "user_id": cls.env.uid})
        Folder = cls.env["mail.client.folder"]
        cls.inbox = Folder.create({"name": "INBOX", "account_id": cls.account.id,
                                   "imap_path": "INBOX", "role": "inbox", "subscribed": True})
        cls.sent = Folder.create({"name": "Sent", "account_id": cls.account.id,
                                  "imap_path": "Sent", "role": "sent", "subscribed": True})
        cls.company = cls.env["res.partner"].create({
            "name": "ООО «Письма»", "is_company": True, "email": "office@zavod.example.org"})
        cls.person = cls.env["res.partner"].create({
            "name": "Иван Тестов", "email": "ivan@mail.ru", "parent_id": cls.company.id})
        cls.deal = cls.env["crm.lead"].create({
            "name": "Ферма 12 м", "type": "opportunity", "partner_id": cls.person.id})
        cls.other_deal = cls.env["crm.lead"].create({
            "name": "Другая сделка", "type": "opportunity", "partner_id": cls.company.id})
        cls.Message = cls.env["mail.client.message"]
        now = datetime.now()
        uid = iter(range(100, 200))

        def letter(subject, folder, email_from, email_to, days=0, **extra):
            return cls.Message.create(dict({
                "account_id": cls.account.id, "folder_id": folder.id, "imap_uid": next(uid),
                "subject": subject, "email_from": email_from, "email_to": email_to,
                "message_id": "<%s-%s@example.org>" % (subject.replace(" ", "-"), days),
                "date": now - timedelta(days=days), "body_html": "<p>%s</p>" % subject,
                "body_state": "fetched", "structure_state": "parsed", "pmk_cid_checked": True},
                **extra))

        cls.linked = letter("Запрос фермы", cls.inbox, '"Иван" <ivan@mail.ru>', BOX, days=3,
                            thread_key="t-ferma", pmk_lead_id=cls.deal.id)
        cls.reply = letter("Re: Запрос фермы", cls.sent, BOX, "ivan@mail.ru", days=2,
                           thread_key="t-ferma")
        cls.no_subject = letter("без темы", cls.inbox, "ivan@mail.ru", BOX, days=1)
        cls.by_domain = letter("Счёт", cls.inbox, "buh@zavod.example.org", BOX, days=5)
        cls.ours_to_client = letter("Чертежи", cls.sent, BOX, '"Офис" <office@zavod.example.org>', days=6)
        cls.in_other = letter("Другая", cls.inbox, "office@zavod.example.org", BOX, days=7,
                              pmk_lead_id=cls.other_deal.id)
        cls.old = letter("Старое", cls.inbox, "ivan@mail.ru", BOX, days=200)
        cls.public_neighbour = letter("Сосед по mail.ru", cls.inbox, "petya@mail.ru", BOX, days=1)
        cls.spam = letter("Спам", cls.inbox, "ivan@mail.ru", BOX, days=1, is_spam=True)

    def test_linked_letters_with_thread(self):
        data = self.env["crm.lead"].pmk_deal_letters(self.deal.id)
        ids = [row["id"] for row in data["letters"]]
        self.assertEqual(ids, [self.reply.id, self.linked.id], "новые сверху, переписка — тоже")
        rows = {row["id"]: row for row in data["letters"]}
        self.assertTrue(rows[self.linked.id]["direct"])
        self.assertFalse(rows[self.reply.id]["direct"], "ответ — по переписке")
        self.assertTrue(rows[self.reply.id]["is_outgoing"])

    def test_candidates(self):
        data = self.env["crm.lead"].pmk_deal_letters(self.deal.id)
        rows = {row["id"]: row for row in data["candidates"]}
        self.assertIn(self.no_subject.id, rows, "письмо с затёртой темой — по адресу")
        self.assertEqual(rows[self.no_subject.id]["reason"], "address")
        self.assertEqual(rows[self.by_domain.id]["reason"], "domain")
        self.assertIn(self.ours_to_client.id, rows, "наши письма клиенту — тоже")
        self.assertEqual(rows[self.in_other.id]["lead"]["id"], self.other_deal.id)
        self.assertFalse(rows[self.in_other.id]["lead"]["same"])
        for absent in (self.linked, self.reply, self.old, self.public_neighbour, self.spam):
            self.assertNotIn(absent.id, rows, absent.subject)
        self.assertTrue(data["older"])
        self.assertEqual(data["domains"], ["example.org"])
        everything = self.env["crm.lead"].pmk_deal_letters(self.deal.id, show_all=True)
        self.assertIn(self.old.id, [row["id"] for row in everything["candidates"]])

    def test_foreign_mailbox_hidden(self):
        admin, root = self.env.ref("base.user_admin"), self.env.ref("base.user_root")
        self.account.write({"user_id": (root if self.env.uid == admin.id else admin).id,
                            "allowed_user_ids": [(5, 0, 0)]})
        data = self.env["crm.lead"].pmk_deal_letters(self.deal.id)
        self.assertEqual(data["letters"], [])
        self.assertEqual(data["candidates"], [])

    def test_link_and_unlink(self):
        self.Message.pmk_link_lead(self.no_subject.id, self.deal.id)
        self.assertEqual(self.no_subject.pmk_lead_id, self.deal)
        data = self.env["crm.lead"].pmk_deal_letters(self.deal.id)
        self.assertIn(self.no_subject.id, [row["id"] for row in data["letters"]])
        self.assertTrue(self.deal.message_ids.filtered(lambda m: m.subject == "без темы"),
                        "письмо легло в ленту сделки")
        self.Message.pmk_unlink_lead(self.no_subject.id, self.deal.id)
        self.assertFalse(self.no_subject.pmk_lead_id)
        with self.assertRaises(UserError):
            self.Message.pmk_unlink_lead(self.reply.id, self.deal.id)

    def test_mail_action(self):
        action = self.Message.pmk_letter_mail_action(self.linked.id, reply=True)
        self.assertEqual(action["params"]["pmk_message_id"], self.linked.id)
        self.assertTrue(action["params"]["pmk_reply"])
        self.inbox.subscribed = False
        self.assertFalse(self.Message.pmk_letter_mail_action(self.linked.id))

    def test_form_tab_first(self):
        arch = self.env["crm.lead"].get_view(view_type="form")["arch"]
        self.assertLess(arch.index('name="pmk_letters"'), arch.index('name="internal_notes"'))
        self.assertIn('name="pmk_deal_letters"', arch)


@tagged("post_install", "-at_install")
class TestLetterWindow(HttpCase):

    def test_window_page_is_sandboxed(self):
        server = self.env["mail.client.server"].create({
            "name": "Stub", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master"})
        admin = self.env.ref("base.user_admin")
        account = self.env["mail.client.account"].create({
            "name": "W", "email": "w@example.org", "server_id": server.id, "user_id": admin.id})
        folder = self.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": account.id, "imap_path": "INBOX", "role": "inbox"})
        message = self.env["mail.client.message"].create({
            "account_id": account.id, "folder_id": folder.id, "imap_uid": 1,
            "subject": "Тема <b>жирно</b>", "email_from": "a@example.org", "email_to": "w@example.org",
            "date": datetime.now(), "body_state": "fetched", "structure_state": "parsed",
            "pmk_cid_checked": True, "body_html": '<p onclick="x()">Текст "письма"</p><script>alert(1)</script>'})
        self.authenticate("admin", "admin")
        response = self.url_open("/pmk_mail/letter/%d" % message.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("script-src 'none'", response.headers["Content-Security-Policy"])
        html = response.text
        self.assertIn("Тема &lt;b&gt;жирно&lt;/b&gt;", html, "тема — текстом")
        self.assertIn('sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"', html)
        self.assertNotIn("<script>", html, "тело только внутри srcdoc, экранированным")
        missing = self.url_open("/pmk_mail/letter/%d" % (message.id + 100000))
        self.assertEqual(missing.status_code, 404)
