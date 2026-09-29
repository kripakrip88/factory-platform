# -*- coding: utf-8 -*-
"""Общие отметки с mail.ru (разбор UX, Г1): «Только чтение + общие отметки».

Что защищаем:
• отметка из Odoo уходит на сервер штатной очередью — в нашем режиме, и ни
  в каком другом по-новому (one_way — пусто, two_way — ровно одна операция);
• перенос и удаление в нашем режиме закрыты так же, как в «только чтении»;
• отметки с сервера читаются одной командой по окну, строка без FLAGS ничего
  не снимает, письмо с неотправленной операцией сервер не перебивает;
• за один проход крона отметка доходит туда, а чужая — обратно, и проход
  сообщает, скольким письмам пришли отметки (сигнал шины, шаг 22);
• проход не пишет is_dirty (шаг 22): массовый UPDATE вне точки сохранения
  ронял первую папку, если менеджер трогал письмо в первые секунды прохода.

Настоящего IMAP нет: FlagServer отвечает так, как отвечает imaplib.
"""
import importlib.util
import os
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail_client.tools.imap_client import ImapError

from ..models.mail_client_flags import FLAG_FIELDS, SHARED_FLAGS_MODE


class FlagServer:
    """Почтовый сервер с одной папкой глазами ImapConnection.

    flags — {UID: набор отметок}. STORE меняет их, UID FETCH … (FLAGS) их же
    и отдаёт — поэтому отметка, ушедшая из Odoo, видна при чтении обратно.
    raw — готовый ответ FETCH вместо собранного из flags.
    """

    supports_qresync = False

    def __init__(self, flags=None, uid_next=None, mod_seq=0, raw=None, fail=None,
                 changed=None, refuse_store=None):
        self.flags = {uid: set(values) for uid, values in (flags or {}).items()}
        self.uid_next = uid_next or max(self.flags, default=0) + 1
        self.mod_seq = mod_seq
        self.raw = raw
        self.fail = fail
        # Ответ CHANGEDSINCE (сервер с CONDSTORE): UID с изменёнными отметками.
        self.changed = changed or []
        # Ответ сервера, отвергающего запись отметок.
        self.refuse_store = refuse_store
        self.fetches = []
        self.stored = []
        self.closed = False

    def list_folders(self):
        return [{"path": "INBOX", "delimiter": "/", "flags": set(), "subscribed": True}]

    def select(self, path, readonly=True, uid_validity=None, mod_seq=None):
        return {"uid_validity": 7, "uid_next": self.uid_next, "mod_seq": self.mod_seq,
                "exists": len(self.flags), "vanished": [], "qresync_used": False}

    def fetch_headers(self, uid_from, uid_to="*"):
        return []

    def fetch_structures(self, uids):
        return {}

    def fetch_flags_since(self, mod_seq):
        return [{"uid": uid, "flags": sorted(self.flags.get(uid, ()))}
                for uid in self.changed], []

    def search_all_uids(self):
        return sorted(self.flags)

    def store_flags(self, uid, flags, add=True):
        if self.refuse_store:
            raise ImapError(self.refuse_store)
        self.stored.append((uid, tuple(flags), add))
        current = self.flags.setdefault(uid, set())
        if add:
            current.update(flags)
        else:
            current.difference_update(flags)

    def _uid(self, command, *args):
        assert command == "FETCH", command
        self.fetches.append(args[0])
        if self.fail:
            raise ImapError(self.fail)
        if self.raw is not None:
            return "OK", list(self.raw)
        low, high = args[0].split(":")
        high = self.uid_next - 1 if high == "*" else int(high)
        data = []
        for number, uid in enumerate(sorted(self.flags), start=1):
            if int(low) <= uid <= high:
                data.append(b"%d (UID %d FLAGS (%s))" % (
                    number, uid, " ".join(sorted(self.flags[uid])).encode()))
        return "OK", data

    def close(self):
        self.closed = True


class ReadOnlyServer(FlagServer):
    """Соединение, которому диапазонный FETCH задавать нельзя."""

    def _uid(self, command, *args):
        raise AssertionError("Чужой режим не должен спрашивать отметки диапазоном.")


@tagged("post_install", "-at_install")
class TestSharedFlags(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["mail.client.server"].create({
            "name": "mail.ru", "imap_host": "imap.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        cls.account = cls.env["mail.client.account"].create({
            "name": "Общий", "email": "shared@example.org",
            "server_id": cls.server.id, "sync_mode": SHARED_FLAGS_MODE,
            "sync_window_days": 30,
        })
        Folder = cls.env["mail.client.folder"]
        cls.inbox = Folder.create({
            "name": "INBOX", "account_id": cls.account.id,
            "imap_path": "INBOX", "role": "inbox", "uid_validity": 7,
        })
        cls.spam = Folder.create({
            "name": "Спам", "account_id": cls.account.id,
            "imap_path": "Спам", "role": "spam", "uid_validity": 7,
        })
        cls.archive = Folder.create({
            "name": "Archive", "account_id": cls.account.id,
            "imap_path": "Archive", "role": "archive",
        })

    def _message(self, uid, folder=None, days_ago=1, **values):
        return self.env["mail.client.message"].create({
            "account_id": self.account.id,
            "folder_id": (folder or self.inbox).id,
            "imap_uid": uid,
            "subject": "Письмо %s" % uid,
            "email_from": "client@example.org",
            "date": fields.Datetime.now() - timedelta(days=days_ago),
            **values,
        })

    def _ops(self):
        return self.env["mail.client.sync.op"].search([("account_id", "=", self.account.id)])

    def _server(self, flags=None, folder=None, **kwargs):
        """Сервер и папка «не в первый раз»: новых писем нет, uid_next совпадает."""
        server = FlagServer(flags, **kwargs)
        (folder or self.inbox).uid_next = server.uid_next
        return server

    def _spy_writes(self):
        """id писем, которым записали отметки."""
        Message = type(self.env["mail.client.message"])
        original = Message.write
        written = set()

        def spy(records, vals):
            if set(vals) & set(FLAG_FIELDS.values()):
                written.update(records.ids)
            return original(records, vals)

        self.patch(Message, "write", spy)
        return written

    # ------------------------------------------------------------------
    # туда: очередь
    # ------------------------------------------------------------------
    def test_marks_are_queued_in_shared_mode(self):
        message = self._message(101)
        message._set_flag("\\Seen", True)
        message._set_flag("\\Flagged", True)
        message._set_flag("\\Answered", True)
        message._set_flag("\\Seen", False)
        self.assertEqual(
            [(op.op_type, op.payload["flags"]) for op in self._ops()],
            [("set_flag", ["\\Seen"]), ("set_flag", ["\\Flagged"]),
             ("set_flag", ["\\Answered"]), ("unset_flag", ["\\Seen"])])
        self.assertEqual(set(self._ops().mapped("imap_uid")), {101})
        self.assertFalse(message.flag_seen, "Локально — сразу, как и раньше.")

    def test_one_way_still_queues_nothing(self):
        self.account.sync_mode = "one_way"
        message = self._message(101)
        message._set_flag("\\Seen", True)
        self.assertTrue(message.flag_seen)
        self.assertFalse(self._ops(), "«Только чтение» по-прежнему ничего не пишет.")

    def test_two_way_gets_exactly_one_operation(self):
        self.account.sync_mode = "two_way"
        self._message(101)._set_flag("\\Seen", True)
        self.assertEqual(len(self._ops()), 1, "Нашей второй операции быть не должно.")

    def test_tags_stay_in_odoo(self):
        tag = self.env["mail.client.tag"].create({
            "account_id": self.account.id, "name": "Срочно", "imap_keyword": "Urgent",
        })
        message = self._message(101)
        message._set_tag(tag, True)
        self.assertIn(tag, message.tag_ids)
        self.assertFalse(self._ops(), "Метки в этом режиме на сервер не уходят.")

    def test_move_and_delete_stay_closed(self):
        message = self._message(101)
        with self.assertRaises(UserError):
            message._move_to(self.archive)
        with self.assertRaises(UserError):
            message._delete()
        with self.assertRaises(UserError):
            self.env["mail.client.message"].delete_bulk(message.ids)
        self.assertTrue(message.exists())
        self.assertFalse(self._ops())

    def test_inbox_state_hides_move_and_delete(self):
        self.account.user_id = self.env.uid
        state = self.env["mail.client.account"].get_inbox_state()
        row = next(a for a in state["accounts"] if a["id"] == self.account.id)
        self.assertFalse(row["can_act"])

    # ------------------------------------------------------------------
    # обратно: чтение отметок
    # ------------------------------------------------------------------
    def test_fetch_lines_are_read_carefully(self):
        old = self._message(50, days_ago=60, flag_seen=True)
        seen = self._message(101)
        answered = self._message(102)
        no_flags = self._message(103, flag_seen=True)
        same = self._message(104, flag_seen=True)
        server = self._server(uid_next=105, raw=[
            b"1 (UID 101 FLAGS (\\Seen))",
            b"2 (FLAGS (\\Answered \\Flagged) UID 102)",
            b"3 (UID 103)",
            b"4 (UID 50 FLAGS ())",
            b"5 (UID 104 FLAGS (\\Seen))",
        ])
        written = self._spy_writes()
        self.inbox._pmk_pull_flags(server, server.select("INBOX"))

        self.assertEqual(server.fetches, ["101:104"],
                         "Окно — от меньшего UID писем за 30 дней до uid_next-1.")
        self.assertTrue(seen.flag_seen)
        self.assertTrue(answered.flag_answered)
        self.assertTrue(answered.flag_flagged)
        self.assertFalse(answered.flag_seen)
        self.assertTrue(no_flags.flag_seen, "Строка без FLAGS не значит «отметок нет».")
        self.assertTrue(old.flag_seen, "UID ниже окна отбрасываем.")
        self.assertTrue(same.flag_seen)
        self.assertEqual(written, {seen.id, answered.id},
                         "Письма без изменений не переписываются.")

    def test_folder_without_fresh_mail_is_not_asked(self):
        self._message(60, days_ago=90)
        server = self._server({60: {"\\Seen"}})
        self.inbox._pmk_pull_flags(server, server.select("INBOX"))
        self.assertEqual(server.fetches, [])

    def test_spam_is_not_asked(self):
        self._message(70, folder=self.spam)
        server = self._server(folder=self.spam, flags={70: {"\\Seen"}})
        self.spam._reconcile_existing(server, server.select("Спам"))
        self.assertEqual(server.fetches, [])

    def test_pending_operation_beats_the_server(self):
        message = self._message(101)
        message._set_flag("\\Seen", True)
        server = self._server({101: set()})
        self.inbox._pmk_pull_flags(server, server.select("INBOX"))
        self.assertTrue(message.flag_seen,
                        "Сервер ещё не знает об отметке — его «не прочитано» устарело.")

        self._ops().write({"state": "failed"})
        self.inbox._pmk_pull_flags(server, server.select("INBOX"))
        self.assertTrue(message.flag_seen,
                        "Сервер отверг отметку пять раз — она всё равно не откатывается молча.")

        self._ops().write({"state": "done"})
        self.inbox._pmk_pull_flags(server, server.select("INBOX"))
        self.assertFalse(message.flag_seen, "Операция закрыта — дальше прав сервер.")

    def test_old_refused_operation_stops_holding(self):
        message = self._message(101)
        message._set_flag("\\Seen", True)
        self._ops().write({"state": "failed"})
        self.env.cr.execute(
            "UPDATE mail_client_sync_op SET create_date = now() - interval '40 days' "
            "WHERE id IN %s", [tuple(self._ops().ids)])
        self.env.invalidate_all()
        server = self._server({101: set()})
        self.inbox._pmk_pull_flags(server, server.select("INBOX"))
        self.assertFalse(message.flag_seen, "Держим не дольше окна отметок.")

    def test_overtaken_refusal_stops_holding(self):
        """Отказ перекрыт более поздней операцией по той же отметке, которая
        прошла: право записи уже есть, старое намерение заменено новым."""
        message = self._message(101)
        message._set_flag("\\Seen", True)
        self._ops().write({"state": "failed"})
        message._set_flag("\\Seen", False)
        self._ops().filtered(lambda op: op.state == "pending").write({"state": "done"})
        SyncOp = self.env["mail.client.sync.op"]
        self.assertFalse(SyncOp._pmk_live_refusals([("account_id", "=", self.account.id)]))
        self.assertNotIn(101, self.inbox._pmk_uids_waiting_push())

    def test_refusal_on_another_mark_still_holds(self):
        message = self._message(101)
        message._set_flag("\\Seen", True)
        self._ops().write({"state": "failed"})
        message._set_flag("\\Flagged", True)
        self._ops().filtered(lambda op: op.state == "pending").write({"state": "done"})
        self.assertIn(101, self.inbox._pmk_uids_waiting_push(),
                      "Прошёл флажок, а «прочитано» так и не дошло — держим.")

    def test_refusal_in_archived_folder_is_not_an_alarm(self):
        folder = self.env["mail.client.folder"].create({
            "name": "Старая", "account_id": self.account.id,
            "imap_path": "Старая", "role": "other", "uid_validity": 7,
        })
        message = self._message(101, folder=folder)
        message._set_flag("\\Seen", True)
        self._ops().write({"state": "failed"})
        folder.active = False
        SyncOp = self.env["mail.client.sync.op"]
        self.assertFalse(SyncOp._pmk_live_refusals([("account_id", "=", self.account.id)]),
                         "Папку убрали на сервере — «дайте право записи» было бы неправдой.")

    def test_condstore_server_keeps_the_standard_path(self):
        self._message(101)
        self.inbox.highest_mod_seq = "10"
        server = self._server({101: {"\\Seen"}}, mod_seq=20, changed=[101])
        self.inbox._reconcile_existing(server, server.select("INBOX"))
        self.assertEqual(server.fetches, [],
                         "С CONDSTORE отметки приходят через CHANGEDSINCE, штатно.")
        self.assertTrue(self._message_by_uid(101).flag_seen)

    def test_condstore_keeps_tags_and_pending_marks(self):
        """Наше «прочитано» поднимает MODSEQ, и CHANGEDSINCE возвращает письмо
        без меток: штатная запись стёрла бы метку, поставленную в Odoo."""
        tag = self.env["mail.client.tag"].create({
            "account_id": self.account.id, "name": "Срочно", "imap_keyword": "Urgent",
        })
        tagged_mail = self._message(101)
        tagged_mail._set_tag(tag, True)
        pending = self._message(102, flag_seen=True)
        pending._set_flag("\\Flagged", True)
        self.inbox.highest_mod_seq = "10"
        server = self._server({101: {"\\Seen"}, 102: set()}, mod_seq=20, changed=[101, 102])
        self.inbox._reconcile_existing(server, server.select("INBOX"))

        self.assertTrue(tagged_mail.flag_seen, "Отметки с сервера пришли.")
        self.assertIn(tag, tagged_mail.tag_ids, "Метка Odoo на месте.")
        self.assertTrue(pending.flag_seen and pending.flag_flagged,
                        "Неотправленную отметку сервер не перебивает.")

    def test_other_modes_keep_the_vendor_condstore_path(self):
        tag = self.env["mail.client.tag"].create({
            "account_id": self.account.id, "name": "Срочно", "imap_keyword": "Urgent",
        })
        self.account.sync_mode = "two_way"
        message = self._message(101, tag_ids=[fields.Command.link(tag.id)])
        self.inbox._apply_flag_changes([{"uid": 101, "flags": ["\\Seen"]}])
        self.assertTrue(message.flag_seen)
        self.assertFalse(message.tag_ids, "В двусторонней метки — с сервера, как у вендора.")

    def _message_by_uid(self, uid):
        return self.env["mail.client.message"].search(
            [("folder_id", "=", self.inbox.id), ("imap_uid", "=", uid)])

    def test_other_modes_never_reach_the_range_fetch(self):
        for mode in ("one_way", "two_way"):
            with self.subTest(mode=mode):
                self.account.sync_mode = mode
                self._message(101 if mode == "one_way" else 102)
                server = ReadOnlyServer({101: {"\\Seen"}, 102: {"\\Seen"}})
                self.inbox.uid_next = server.uid_next
                self.inbox._sync_messages(server)

    def test_fetch_error_does_not_break_the_folder(self):
        message = self._message(101)
        server = self._server({101: {"\\Seen"}}, fail="connection reset")
        server.uid_next = 106
        with self.assertLogs("odoo.addons.pmk_mail_ui.models.mail_client_flags",
                             level="WARNING"):
            self.inbox._sync_messages(server)
        self.assertEqual(self.inbox.uid_next, 106, "Папка дошла до конца прохода.")
        self.assertTrue(self.inbox.last_sync_date)
        self.assertFalse(message.flag_seen)

    def test_local_tags_survive_the_pull(self):
        tag = self.env["mail.client.tag"].create({
            "account_id": self.account.id, "name": "Срочно", "imap_keyword": "Urgent",
        })
        message = self._message(101, tag_ids=[fields.Command.link(tag.id)])
        server = self._server({101: {"\\Seen"}})
        self.inbox._pmk_pull_flags(server, server.select("INBOX"))
        self.assertTrue(message.flag_seen)
        self.assertIn(tag, message.tag_ids, "Метки живут только в Odoo — не стираем.")

    def test_pull_cost_does_not_grow_with_the_window(self):
        Message = self.env["mail.client.message"]
        now = fields.Datetime.now()
        Message.create([{
            "account_id": self.account.id, "folder_id": self.inbox.id,
            "imap_uid": uid, "subject": "Письмо %s" % uid,
            "date": now - timedelta(days=1),
        } for uid in range(1, 201)])
        server = self._server({uid: set() for uid in range(1, 201)})
        server.flags[42] = {"\\Seen"}
        status = server.select("INBOX")
        written = self._spy_writes()
        self.env.invalidate_all()
        # Три чтения, точка сохранения, один UPDATE и дочитка папки/ящика
        # (журнал, пересчёт зависимых полей) — около десятка при 200 письмах.
        # Узко намеренно: запись по письму дала бы сотни.
        with self.assertQueryCount(__system__=14):
            self.inbox._pmk_pull_flags(server, status)
        self.assertEqual(len(written), 1)
        changed = Message.search([("folder_id", "=", self.inbox.id), ("imap_uid", "=", 42)])
        self.assertTrue(changed.flag_seen)

    # ------------------------------------------------------------------
    # проход целиком
    # ------------------------------------------------------------------
    def test_one_pass_carries_marks_both_ways(self):
        opened = self._message(101)
        read_on_web = self._message(102)
        opened._set_flag("\\Seen", True)
        server = self._server({101: set(), 102: {"\\Seen"}})

        # Проход фиксирует каждую папку (cr.commit) — в тесте это запрещено.
        # rollback подменён, чтобы сбой внутри _sync не откатил весь тест.
        with patch.object(self.env.cr, "commit"), \
                patch.object(self.env.cr, "rollback") as rollback, \
                patch.object(type(self.account), "_open_connection", return_value=server):
            summary = self.account._sync()

        rollback.assert_not_called()
        self.assertEqual(self.account.state, "connected", self.account.error_message)
        self.assertEqual(server.stored, [(101, ("\\Seen",), True)])
        self.assertIn("\\Seen", server.flags[101])
        self.assertTrue(opened.flag_seen, "Отметка из Odoo не откатилась чтением.")
        # Шаг 22: в этом режиме is_dirty не ведётся (шапка mail_client_flags.py,
        # «IS_DIRTY»): что письмо ждёт сервера, говорят операции.
        self.assertTrue(opened.is_dirty)
        self.assertTrue(read_on_web.flag_seen, "Прочитанное на mail.ru пришло в Odoo.")
        self.assertEqual(self._ops().mapped("state"), ["done"])
        self.assertTrue(server.closed)
        # Отметка с mail.ru — изменение прохода: почта перечитает список.
        self.assertEqual((summary["flags"], summary["changed"]), (1, True))

    def test_pass_does_not_rewrite_is_dirty(self):
        """Шаг 22: проход в нашем режиме не пишет is_dirty ни одному письму.
        Штатный _push_pending_ops снимал его со всех грязных писем ящика
        одним UPDATE вне точки сохранения — менеджер тронул письмо в первые
        секунды прохода, и проход откатывал первую папку с ошибкой ящика."""
        opened = self._message(101)
        touched_before = self._message(102, is_dirty=True)
        opened._set_flag("\\Seen", True)
        server = self._server({101: set(), 102: set()})
        Message = type(self.env["mail.client.message"])
        original = Message.write
        dirty_writes = []

        def spy(records, vals):
            if "is_dirty" in vals:
                dirty_writes.append((tuple(records.ids), vals["is_dirty"]))
            return original(records, vals)

        self.patch(Message, "write", spy)
        self._passes(server, 1)
        self.assertEqual(self._ops().mapped("state"), ["done"], "Очередь ушла штатно.")
        self.assertEqual(dirty_writes, [], "Ни одной записи is_dirty за проход.")
        self.assertTrue(opened.is_dirty and touched_before.is_dirty)

        # «Двусторонняя» — как у модуля почты: после отправки очереди снято.
        self.account.sync_mode = "two_way"
        opened._set_flag("\\Flagged", True)
        dirty_writes.clear()
        self._passes(server, 1)
        self.assertIn(False, [value for _ids, value in dirty_writes])
        self.assertFalse(opened.is_dirty)

    def _passes(self, server, count):
        with patch.object(self.env.cr, "commit"), \
                patch.object(self.env.cr, "rollback"), \
                patch.object(type(self.account), "_open_connection", return_value=server):
            for _pass in range(count):
                self.account._sync()

    def test_refused_marks_stay_and_raise_the_alarm(self):
        """Сервер не даёт писать (пароль без права записи): через пять
        проходов модуль почты бросает операцию. Отметка Odoo при этом не
        откатывается, а ящик честно показывает ошибку."""
        opened = self._message(101)
        opened._set_flag("\\Seen", True)
        server = self._server({101: set()}, refuse_store="NO [READ-ONLY] mailbox")

        self._passes(server, 4)
        self.assertEqual(self._ops().mapped("state"), ["pending"])
        self.assertEqual(self.account.state, "connected", "Пока повторяем — не ошибка.")

        self._passes(server, 2)
        self.assertEqual(self._ops().mapped("state"), ["failed"])
        self.assertTrue(opened.flag_seen, "Отметка Odoo не откатилась молча.")
        self.assertEqual(self.account.state, "error")
        self.assertIn("READ-ONLY", self.account.error_message)
        self.assertIn("Повторить", self.account.error_message)

        # Право записи дали, в «Ожидающих операциях» нажали «Повторить».
        server.refuse_store = None
        self._ops().action_retry()
        self._passes(server, 1)
        self.assertEqual(self._ops().mapped("state"), ["done"])
        self.assertIn("\\Seen", server.flags[101])
        self.assertEqual(self.account.state, "connected")

    # ------------------------------------------------------------------
    # миграция 19.0.1.0.4
    # ------------------------------------------------------------------
    def _migrate(self):
        path = os.path.join(os.path.dirname(__file__), os.pardir, "migrations",
                            "19.0.1.0.4", "post-migrate.py")
        spec = importlib.util.spec_from_file_location("pmk_mail_ui_migrate_1_0_4", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, "19.0.1.0.3")

    def test_migration_switches_the_mailbox_and_keeps_opened_mail(self):
        mailru = self.env["mail.client.account"].create({
            "name": "mail.ru", "email": "PMKPARK@mail.ru", "server_id": self.server.id,
        })
        zakaz = self.env["mail.client.account"].create({
            "name": "zakaz", "email": "zakaz@example.org", "server_id": self.server.id,
        })
        folder = self.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": mailru.id, "imap_path": "INBOX", "role": "inbox",
        })
        Message = self.env["mail.client.message"]
        opened = Message.create({"account_id": mailru.id, "folder_id": folder.id,
                                 "imap_uid": 1, "flag_seen": True, "is_dirty": True})
        Message.create({"account_id": mailru.id, "folder_id": folder.id,
                        "imap_uid": 2, "flag_seen": False, "is_dirty": True})
        Message.create({"account_id": mailru.id, "folder_id": folder.id,
                        "imap_uid": 3, "flag_seen": True})
        # Ответили из Odoo (модуль почты ставит «отвечено») и поставили флажок.
        answered = Message.create({
            "account_id": mailru.id, "folder_id": folder.id, "imap_uid": 4,
            "flag_seen": True, "flag_answered": True, "flag_flagged": True, "is_dirty": True})

        self._migrate()
        mailru.sync_mode = "one_way"    # повтор (или ручное переключение туда-обратно)
        self._migrate()                 # не ставит вторую операцию

        self.assertEqual(mailru.sync_mode, SHARED_FLAGS_MODE)
        self.assertEqual(zakaz.sync_mode, "one_way")
        ops = self.env["mail.client.sync.op"].search([("account_id", "=", mailru.id)])
        self.assertEqual(
            {op.message_id: (op.op_type, op.payload["flags"], op.state) for op in ops},
            {opened: ("set_flag", ["\\Seen"], "pending"),
             answered: ("set_flag", ["\\Seen", "\\Answered", "\\Flagged"], "pending")},
            "Стоящие отметки — на сервер; «непрочитано» (письмо 2) — нет.")
