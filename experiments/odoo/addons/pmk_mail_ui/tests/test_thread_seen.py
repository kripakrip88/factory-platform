# -*- coding: utf-8 -*-
"""Открыл переписку — прочитана вся переписка («Почта как в Mail.ru», Г9).

Строка-переписка жирная, пока непрочитано любое её письмо в ящике, а модуль
почты при открытии помечал одно письмо. Здесь проверяем серверную половину:
pmk_mark_threads_seen находит все письма переписки в своём ящике — вместе с
«Отправленными» и с копией письма, которую прячет get_thread, — и не трогает
чужие переписки и чужие ящики. При открытии (upto) — только письма не новее
открытого; в «Все входящие» (unified) — во всех ящиках, где можно писать.
"""
from datetime import datetime

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..models.mail_client_flags import SHARED_FLAGS_MODE

ROOT = "<root@example.org>"
OTHER = "<other@example.org>"


@tagged("post_install", "-at_install")
class TestThreadSeen(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        cls.account = cls.env["mail.client.account"].create({
            "name": "Завод", "email": "me@example.org", "server_id": cls.server.id,
            "sync_mode": SHARED_FLAGS_MODE,
        })
        cls.second = cls.env["mail.client.account"].create({
            "name": "Второй", "email": "second@example.org", "server_id": cls.server.id,
        })
        Folder = cls.env["mail.client.folder"]
        cls.inbox = Folder.create({"name": "INBOX", "account_id": cls.account.id,
                                   "imap_path": "INBOX", "role": "inbox"})
        cls.sent = Folder.create({"name": "Sent", "account_id": cls.account.id,
                                  "imap_path": "Sent", "role": "sent"})
        cls.second_inbox = Folder.create({"name": "INBOX", "account_id": cls.second.id,
                                          "imap_path": "INBOX", "role": "inbox"})
        cls.Message = cls.env["mail.client.message"]

        def message(uid, folder, key, day, seen, message_id=None, account=None):
            return cls.Message.create({
                "account_id": (account or cls.account).id, "folder_id": folder.id,
                "imap_uid": uid, "subject": "Счёт", "thread_key": key,
                "email_from": "client@example.org", "flag_seen": seen,
                "message_id": message_id or "<m%s-%s@example.org>" % (folder.id, uid),
                "date": datetime(2026, 9, day, 10, 0, 0),
            })

        # Переписка ROOT: старое письмо клиента не прочитано, новое прочитано
        # (оно и представляет строку), наш ответ — в «Отправленных», одно
        # письмо лежит двумя копиями, и не прочитана как раз та, которую
        # get_thread спрячет.
        cls.old = message(1, cls.inbox, ROOT, 1, False)
        cls.latest = message(2, cls.inbox, ROOT, 5, True)
        cls.reply = message(3, cls.sent, ROOT, 3, True)
        cls.copy_inbox = message(4, cls.inbox, ROOT, 2, True, "<dup@example.org>")
        cls.copy_sent = message(5, cls.sent, ROOT, 2, False, "<dup@example.org>")
        # Чужая переписка и та же переписка в другом ящике.
        cls.other = message(6, cls.inbox, OTHER, 4, False)
        cls.elsewhere = message(1, cls.second_inbox, ROOT, 1, False, account=cls.second)

    def _ops(self, account=None):
        return self.env["mail.client.sync.op"].search(
            [("account_id", "=", (account or self.account).id)])

    def _row(self, key):
        result = self.env["mail.client.folder"].get_messages(
            folder_id=self.inbox.id, threaded=True)
        return next(r for r in result["messages"] if r["thread_key"] == key)

    # ------------------------------------------------------------------
    def test_row_was_stuck_before(self):
        """Та самая беда: представитель прочитан, а строка жирная."""
        row = self._row(ROOT)
        self.assertEqual(row["id"], self.latest.id)
        self.assertFalse(row["flag_seen"])

    def test_whole_thread_is_read(self):
        result = self.Message.pmk_mark_threads_seen([self.latest.id])

        self.assertEqual(set(result["ids"]), {self.old.id, self.copy_sent.id})
        self.assertTrue(self.old.flag_seen)
        self.assertTrue(self.copy_sent.flag_seen,
                        "Копию, которую прячет get_thread, счётчик папки считает.")
        self.assertFalse(self.other.flag_seen, "Чужая переписка не тронута.")
        self.assertFalse(self.elsewhere.flag_seen, "Другой ящик — другая переписка.")
        self.assertEqual(result["threads"], [{"thread_key": ROOT, "unread": 0}])
        self.assertEqual(
            {f["id"]: f["unread"] for f in result["folders"]},
            {self.inbox.id: 1, self.sent.id: 0},
            "Точные счётчики обеих затронутых папок.")

        row = self._row(ROOT)
        self.assertTrue(row["flag_seen"])
        self.assertEqual(row["unread_count"], 0)

    def test_opened_from_the_thread_pane(self):
        """Письмо переписки, открытое не из строки списка, гасит ту же строку."""
        self.Message.pmk_mark_threads_seen([self.reply.id], upto=True)
        self.assertTrue(self._row(ROOT)["flag_seen"])

    def _newer_reply(self):
        """Ответ клиента, пришедший ПОСЛЕ нашего письма, — во «Входящих»."""
        return self.Message.create({
            "account_id": self.account.id, "folder_id": self.inbox.id,
            "imap_uid": 7, "subject": "Re: Счёт", "thread_key": ROOT,
            "email_from": "client@example.org", "flag_seen": False,
            "message_id": "<newer@example.org>", "date": datetime(2026, 9, 6, 10, 0, 0),
        })

    def test_opening_in_sent_keeps_a_newer_reply_unread(self):
        """Открыли переписку в «Отправленных» — видно наше письмо, а не ответ,
        пришедший позже. Старое непрочитанное гасим, новый ответ — нет."""
        newer = self._newer_reply()
        result = self.Message.pmk_mark_threads_seen([self.reply.id], upto=True)

        self.assertTrue(self.old.flag_seen)
        self.assertTrue(self.copy_sent.flag_seen)
        self.assertFalse(newer.flag_seen, "Ответ клиента не открывали.")
        self.assertNotIn(newer.id, self._ops().message_id.ids,
                         "И на mail.ru он остаётся непрочитанным.")
        self.assertEqual(result["threads"], [{"thread_key": ROOT, "unread": 1}],
                         "Строка честно остаётся жирной — окно гасит её по этому числу.")

    def test_read_button_reads_the_whole_thread(self):
        """«Прочитано» на строке в «Отправленных» — просьба прочитать
        переписку целиком, иначе кнопка там ничего бы не делала."""
        newer = self._newer_reply()
        result = self.Message.pmk_mark_threads_seen([self.reply.id])
        self.assertTrue(newer.flag_seen)
        self.assertEqual(result["threads"], [{"thread_key": ROOT, "unread": 0}])

    def test_unified_inbox_reads_the_thread_in_every_mailbox(self):
        """В «Все входящие» строка одна на оба ящика и жирная, пока непрочитано
        письмо в любом из них: гасим в обоих, иначе после перезагрузки
        списка она снова жирная."""
        (self.account | self.second).user_id = self.env.uid
        result = self.Message.pmk_mark_threads_seen([self.latest.id], unified=True)
        self.assertTrue(self.old.flag_seen)
        self.assertTrue(self.elsewhere.flag_seen, "Та же переписка во втором ящике.")
        self.assertFalse(self.other.flag_seen)
        self.assertEqual(result["threads"], [{"thread_key": ROOT, "unread": 0}])

        rows = self.env["mail.client.folder"].get_messages(threaded=True, unified=True)
        row = next(r for r in rows["messages"] if r["thread_key"] == ROOT)
        self.assertEqual(row["unread_count"], 0)

    def test_unified_skips_a_mailbox_the_user_may_only_view(self):
        Users = self.env["res.users"].with_context(no_reset_password=True)
        agent = Users.create({
            "name": "Менеджер", "login": "pmk_agent", "email": "agent@example.org",
            "group_ids": [(6, 0, [
                self.env.ref("mail_client.group_mail_client_user").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.account.user_id = agent
        self.env["mail.client.access"].create({
            "account_id": self.second.id, "user_id": agent.id, "role": "viewer",
        })
        result = self.Message.with_user(agent).pmk_mark_threads_seen(
            [self.latest.id], unified=True)
        self.assertTrue(self.old.flag_seen)
        self.assertFalse(self.elsewhere.flag_seen, "Во втором ящике — только смотреть.")
        self.assertEqual(result["threads"], [{"thread_key": ROOT, "unread": 1}])

    def test_bulk_reads_both_threads(self):
        self.Message.pmk_mark_threads_seen([self.latest.id, self.other.id])
        self.assertTrue(self._row(ROOT)["flag_seen"])
        self.assertTrue(self._row(OTHER)["flag_seen"])
        self.assertFalse(self.elsewhere.flag_seen)

    def test_marks_go_to_the_queue_once(self):
        self.Message.pmk_mark_threads_seen([self.latest.id])
        ops = self._ops()
        self.assertEqual(len(ops), 2, "По операции на каждое помеченное письмо.")
        self.assertEqual(set(ops.mapped("op_type")), {"set_flag"})
        self.assertEqual(set(ops.message_id.ids), {self.old.id, self.copy_sent.id})

        again = self.Message.pmk_mark_threads_seen([self.latest.id])
        self.assertEqual(again["ids"], [])
        self.assertEqual(len(self._ops()), 2, "Повтор ничего не ставит в очередь.")

    def test_two_way_and_one_way(self):
        self.account.sync_mode = "two_way"
        self.Message.pmk_mark_threads_seen([self.latest.id])
        self.assertEqual(len(self._ops()), 2)

        self.Message.pmk_mark_threads_seen([self.elsewhere.id])
        self.assertTrue(self.elsewhere.flag_seen)
        self.assertFalse(self._ops(self.second), "«Только чтение» — только в Odoo.")

    def test_viewer_cannot_mark(self):
        Users = self.env["res.users"].with_context(no_reset_password=True)
        viewer = Users.create({
            "name": "Зритель", "login": "pmk_viewer", "email": "viewer@example.org",
            "group_ids": [(6, 0, [
                self.env.ref("mail_client.group_mail_client_user").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.account.user_id = False
        self.env["mail.client.access"].create({
            "account_id": self.account.id, "user_id": viewer.id, "role": "viewer",
        })
        with self.assertRaises(AccessError):
            self.Message.with_user(viewer).pmk_mark_threads_seen([self.latest.id])
        self.assertFalse(self.old.flag_seen)
