# -*- coding: utf-8 -*-
"""Список писем как в Mail.ru (шаг 18, 30.09.2026): папки-сортировщики mail.ru.

Рассылки, Чеки, Новости и Соцсети — «тихие» (крючок модуля почты _is_quiet):
счётчик серым и не в итоге свёрнутого ящика, в «ждёт ответа» не участвуют,
в дереве — в самом конце. Во «Входящих» каждая непустая видна одной строкой
(крючок _list_digests) — только на первой странице без поиска и фильтра.
"""
from datetime import datetime, timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.mail_client_folder import LOW_PRIORITY_RANK


@tagged("post_install", "-at_install")
class TestMailList(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        cls.account = cls.env["mail.client.account"].create({
            "name": "Завод", "email": "me@example.org", "server_id": cls.server.id,
        })
        cls.account.user_id = cls.env.uid
        Folder = cls.env["mail.client.folder"]

        def folder(path, role="other"):
            return Folder.create({"name": path.rsplit("/", 1)[-1], "account_id": cls.account.id,
                                  "imap_path": path, "delimiter": "/", "role": role})

        cls.inbox = folder("INBOX", "inbox")
        cls.sent = folder("Sent", "sent")
        cls.spam = folder("Spam", "spam")
        cls.newsletters = folder("INBOX/Newsletters")
        cls.receipts = folder("INBOX/Receipts")
        cls.social = folder("INBOX/Social")          # пустая — строки нет
        cls.projects = folder("Проекты")
        cls.Folder = Folder
        cls.Message = cls.env["mail.client.message"]

    def _message(self, uid, folder, sender, day, seen=False, key=None, subject="Письмо"):
        return self.Message.create({
            "account_id": self.account.id, "folder_id": folder.id, "imap_uid": uid,
            "subject": subject, "email_from": sender, "flag_seen": seen,
            "thread_key": key or "<%s-%s@x>" % (folder.id, uid),
            "message_id": "<%s-%s@x>" % (folder.id, uid),
            "date": datetime(2026, 9, day, 10, 0, 0),
        })

    # ------------------------------------------------------------------
    def test_sorter_folders_are_quiet_and_ranked_last(self):
        quiet = {f.imap_path: f._is_quiet() for f in (
            self.inbox, self.sent, self.spam, self.newsletters, self.receipts,
            self.social, self.projects)}
        self.assertEqual(quiet, {
            "INBOX": False, "Sent": False, "Spam": True, "INBOX/Newsletters": True,
            "INBOX/Receipts": True, "INBOX/Social": True, "Проекты": False,
        })
        self.assertEqual(self.newsletters._role_rank(), LOW_PRIORITY_RANK)
        self.assertLess(self.projects._role_rank(), LOW_PRIORITY_RANK)

        state = self.env["mail.client.account"].get_inbox_state()
        account = next(a for a in state["accounts"] if a["id"] == self.account.id)
        paths = [self.Folder.browse(f["id"]).imap_path for f in account["folders"]]
        self.assertEqual(paths[-3:], ["INBOX/Newsletters", "INBOX/Receipts", "INBOX/Social"],
                         "Сортировщики — в конце дерева.")
        by_id = {f["id"]: f for f in account["folders"]}
        self.assertTrue(by_id[self.newsletters.id]["quiet"])
        self.assertFalse(by_id[self.inbox.id]["quiet"])

    def test_digests_only_on_first_unfiltered_inbox_page(self):
        self._message(1, self.inbox, "client@firm.ru", 20)
        self._message(1, self.newsletters, "Ozon <news@ozon.ru>", 21)
        self._message(2, self.newsletters, "Ozon <news@ozon.ru>", 22, seen=True)
        self._message(3, self.newsletters, "Яндекс Маркет <m@ya.ru>", 23)
        self._message(4, self.newsletters, "sber@sber.ru", 24)
        self._message(5, self.newsletters, "Лемана ПРО <l@lp.ru>", 25)
        self._message(1, self.receipts, "Чек <check@ofd.ru>", 19, seen=True)

        result = self.Folder.get_messages(folder_id=self.inbox.id, threaded=True)
        digests = {d["folder_id"]: d for d in result["digests"]}
        self.assertEqual(set(digests), {self.newsletters.id, self.receipts.id},
                         "Пустая папка строки не даёт.")
        news = digests[self.newsletters.id]
        self.assertEqual((news["unread"], news["total"]), (4, 5))
        self.assertEqual(news["date"], "2026-09-25 10:00:00")
        self.assertEqual(news["name"], "Newsletters")
        self.assertEqual(news["senders"], ["Лемана ПРО", "sber@sber.ru", "Яндекс Маркет"],
                         "Три разных, последние первыми; без имени — адрес.")
        self.assertEqual(digests[self.receipts.id]["unread"], 0)
        self.assertEqual([d["folder_id"] for d in result["digests"]],
                         [self.newsletters.id, self.receipts.id], "По дате последнего письма.")

        # Без переписок — то же.
        flat = self.Folder.get_messages(folder_id=self.inbox.id)
        self.assertEqual(len(flat["digests"]), 2)
        # Только первая страница, без поиска и фильтра, и только во «Входящих».
        for kwargs in ({"before": "2026-09-21 00:00:00"}, {"search": "client"},
                       {"message_filter": "unread"}):
            self.assertEqual(
                self.Folder.get_messages(folder_id=self.inbox.id, **kwargs)["digests"], [], kwargs)
        self.assertEqual(self.Folder.get_messages(folder_id=self.sent.id)["digests"], [])
        self.assertEqual(self.Folder.get_messages(folder_id=self.newsletters.id)["digests"], [])
        # «Все входящие» — тоже.
        unified = self.Folder.get_messages(unified=True, threaded=True)
        self.assertEqual({d["folder_id"] for d in unified["digests"]},
                         {self.newsletters.id, self.receipts.id})

    def test_newsletter_does_not_make_a_thread_await(self):
        """Письмо из «Рассылок» (mail.ru мог положить туда ответ по ошибке)
        переписку не решает; одна рассылка — не «ждёт ответа»."""
        now = fields.Datetime.now()

        def recent(uid, folder, sender, days_ago, key):
            return self.Message.create({
                "account_id": self.account.id, "folder_id": folder.id, "imap_uid": uid,
                "subject": key, "email_from": sender, "thread_key": key,
                "message_id": "<r%s-%s@x>" % (folder.id, uid),
                "date": now - timedelta(days=days_ago, hours=1),
            })

        recent(10, self.inbox, "client@firm.ru", 3, "<deal@x>")
        recent(10, self.sent, "me@example.org", 2, "<deal@x>")
        recent(10, self.newsletters, "client@firm.ru", 1, "<deal@x>")
        recent(11, self.inbox, "client@firm.ru", 1, "<question@x>")
        recent(12, self.newsletters, "news@ozon.ru", 1, "<promo@x>")

        rows = self.Folder.get_messages(folder_id=self.inbox.id, threaded=True)["messages"]
        self.assertEqual({r["thread_key"]: r["awaiting"] for r in rows},
                         {"<deal@x>": "client", "<question@x>": "us"})
        news_rows = self.Folder.get_messages(folder_id=self.newsletters.id, threaded=True)
        self.assertTrue(all(not r["awaiting"] for r in news_rows["messages"]),
                        "В тихой папке плашек нет.")
        # Без переписок в строке нет ключа переписки — тема письма здесь та же.
        awaiting = self.Folder.get_messages(folder_id=self.inbox.id, message_filter="awaiting")
        self.assertEqual([r["subject"] for r in awaiting["messages"]], ["<question@x>"])
