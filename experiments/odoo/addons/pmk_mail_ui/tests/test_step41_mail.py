# -*- coding: utf-8 -*-
"""Почта, остальное — разбор удобства, шаг 41 (05.10.2026).

- Имена вложений (В4): пишутся при синхронизации из описания письма
  (BODYSTRUCTURE) — без скачивания файлов (у заглушки соединения нет
  fetch_part: попытка скачать уронила бы тест); при дочитке старых писем и
  при открытии; картинка из подписи (Content-ID) — не вложение. Строка
  списка — три имени и общее число; строка-переписка — имена со всех писем,
  новые первыми. Помощники миграции 19.0.1.0.7.
- Лид у строки (А5): свой, от другого письма переписки, архивный; без права
  на лиды — значка нет. Кнопка «Лид» отдаёт значок для строки; у ответа в
  переписке с лидом — открывает тот же лид, второго не заводит (в другом
  ящике — свой).
- Фильтр «С лидом» (А7), неизвестный фильтр по-прежнему отказ.
- Звезда переписки: снять — со всех отмеченных писем, поставить — одно.
- Счётчик новых (Г12): «Входящие» доступных ящиков, непрочитанные, за 30
  дней; без прав — 0; в session_info — только у кого есть почта.
- Ассеты: файлы в сборке, сборка стилей без ошибок, правила шага на месте,
  пункт меню, на который смотрит счётчик, существует.

Гонять на одноразовой базе (см. tests/__init__.py).
"""
import re
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_path

from odoo.addons.mail_client.tests.test_folder_sync import (
    PARTS_TEXT_ONLY,
    PARTS_WITH_PDF,
    StubConnection,
    make_header,
)

# Письмо со счётом, спецификацией и логотипом в подписи (часть с
# Content-ID, на которую ссылается текст, — не вложение).
PARTS_RICH = PARTS_WITH_PDF + [
    {'part_number': '3', 'content_type': 'application/vnd.ms-excel',
     'maintype': 'application', 'subtype': 'vnd.ms-excel', 'encoding': 'base64',
     'size': 8000, 'charset': '', 'filename': 'Спецификация.xlsx',
     'disposition': 'attachment', 'content_id': '', 'is_attachment': True},
    {'part_number': '4', 'content_type': 'image/png', 'maintype': 'image',
     'subtype': 'png', 'encoding': 'base64', 'size': 3000, 'charset': '',
     'filename': 'image001.png', 'disposition': 'inline',
     'content_id': 'image001.png@01DC', 'is_attachment': False},
]

JS = "pmk_mail_ui/static/src/js/"
SALES_MAIL_MENU = "pmk_mail_ui.menu_mail_sale"


def _read(path):
    with open(file_path(path), encoding="utf-8") as handle:
        return handle.read()


class _MailCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        cls.account = cls.env["mail.client.account"].create({
            "name": "Завод", "email": "me@example.org", "server_id": cls.server.id,
            "sync_window_days": 0,
        })
        cls.account.user_id = cls.env.uid
        Folder = cls.env["mail.client.folder"]

        def folder(path, role="other"):
            return Folder.create({"name": path.rsplit("/", 1)[-1], "account_id": cls.account.id,
                                  "imap_path": path, "delimiter": "/", "role": role})

        cls.inbox = folder("INBOX", "inbox")
        cls.sent = folder("Sent", "sent")
        cls.spam = folder("Spam", "spam")
        cls.trash = folder("Trash", "trash")
        cls.newsletters = folder("INBOX/Newsletters")
        cls.Folder = Folder
        cls.Message = cls.env["mail.client.message"]
        cls.uid_seq = 1000

    def _message(self, folder, subject="Письмо", days_ago=1, key=None, seen=True,
                 names=None, account=None, **values):
        type(self).uid_seq += 1
        uid = self.uid_seq
        values.update({
            "account_id": (account or self.account).id, "folder_id": folder.id,
            "imap_uid": uid, "subject": subject, "email_from": "client@firm.ru",
            "flag_seen": seen, "thread_key": key or "<t%s@x>" % uid,
            "message_id": "<m%s@x>" % uid,
            "date": fields.Datetime.now() - timedelta(days=days_ago),
        })
        if names is not None:
            values.update({"has_attachment": bool(names),
                           "pmk_attachment_names": "\n".join(names) or False})
        return self.Message.create(values)

    def _lead(self, name="Ограждение лестниц", **values):
        return self.env["crm.lead"].create(dict({"name": name}, **values))


# ═══ Имена вложений ══════════════════════════════════════════════════════════
@tagged("post_install", "-at_install")
class TestAttachmentNames(_MailCase):

    def test_sync_records_names_without_downloading(self):
        connection = StubConnection(
            uid_validity=100, uid_next=3,
            headers=[make_header(1), make_header(2)],
            structures={1: PARTS_RICH, 2: PARTS_TEXT_ONLY},
        )
        self.assertFalse(hasattr(connection, "fetch_part"), "заглушка не умеет качать файлы")
        self.inbox._sync_messages(connection)
        by_uid = {m.imap_uid: m for m in self.inbox.message_ids}
        self.assertEqual(by_uid[1].pmk_attachment_names, "invoice.pdf\nСпецификация.xlsx",
                         "логотип подписи (Content-ID) — не вложение")
        self.assertFalse(by_uid[2].pmk_attachment_names)
        self.assertFalse(by_uid[1].client_attachment_ids, "строки вложений — только при открытии")

    def test_backfill_writes_names(self):
        old = self.Message.create({
            "account_id": self.account.id, "folder_id": self.inbox.id, "imap_uid": 7,
            "subject": "Старое", "structure_state": "unknown",
            "date": fields.Datetime.now(),
        })
        connection = StubConnection(structures={7: PARTS_WITH_PDF})
        self.assertEqual(self.inbox._backfill_structures(connection), 1)
        self.assertEqual(old.pmk_attachment_names, "invoice.pdf")
        self.assertTrue(old.has_attachment)

    def test_open_writes_names_and_keeps_numbering(self):
        from odoo.addons.mail_client.tools import bodystructure
        letter = self._message(self.inbox)
        letter._sync_attachment_records(bodystructure.attachments(PARTS_RICH))
        self.assertEqual(letter.pmk_attachment_names, "invoice.pdf\nСпецификация.xlsx")
        self.assertEqual(letter.client_attachment_ids.sorted("sequence").mapped("sequence"),
                         [10, 11], "нумерация модуля почты (на неё рассчитан _pmk_record_inline_parts)")

    def test_row_shows_three_names_and_count(self):
        self._message(self.inbox, names=["Счёт 00627.pdf", "Спецификация.xlsx", "КМД.dwg",
                                         "Фото.jpg", "Договор.docx"])
        row = self.Folder.get_messages(folder_id=self.inbox.id)["messages"][0]
        self.assertEqual(row["attachment_names"], ["Счёт 00627.pdf", "Спецификация.xlsx", "КМД.dwg"])
        self.assertEqual(row["attachment_count"], 5)

    def test_thread_row_collects_names_from_every_letter(self):
        self._message(self.inbox, key="<k@x>", days_ago=3, names=["Заявка.pdf", "Общее.xlsx"])
        self._message(self.sent, key="<k@x>", days_ago=1, names=["Счёт 00627.pdf", "Общее.xlsx"])
        row = self.Folder.get_messages(folder_id=self.inbox.id, threaded=True)["messages"][0]
        self.assertEqual(row["attachment_names"], ["Счёт 00627.pdf", "Общее.xlsx", "Заявка.pdf"],
                         "новые первыми, без повторов")
        self.assertEqual(row["attachment_count"], 3)

    def test_migration_helpers(self):
        opened = self._message(self.inbox, has_attachment=True)
        self.env["mail.client.attachment"].create([
            {"message_id": opened.id, "sequence": 10, "name": "Счёт 00627.pdf",
             "part_number": "2", "content_type": "application/pdf"},
            {"message_id": opened.id, "sequence": 11, "name": "часть 3",
             "part_number": "3", "content_type": "application/octet-stream"},
            {"message_id": opened.id, "sequence": 100, "name": "image001",
             "part_number": "4", "content_type": "image/png", "pmk_inline": True},
        ])
        inbox_old = self._message(self.inbox, has_attachment=True, structure_state="parsed")
        named = self._message(self.inbox, names=["Есть.pdf"], structure_state="parsed")
        spam_old = self._message(self.spam, has_attachment=True, structure_state="parsed")
        trash_old = self._message(self.trash, has_attachment=True, structure_state="parsed")
        plain = self._message(self.inbox, structure_state="parsed")

        self.assertGreaterEqual(self.Message._pmk_names_from_rows(), 1)
        self.assertEqual(opened.pmk_attachment_names, "Счёт 00627.pdf",
                         "без «часть N» и без картинки из текста")

        self.Message._pmk_queue_name_backfill()
        self.assertEqual(inbox_old.structure_state, "unknown", "дочитает крон")
        for untouched in (named, spam_old, trash_old, plain):
            with self.subTest(message=untouched.subject, folder=untouched.folder_id.name):
                self.assertEqual(untouched.structure_state, "parsed")
        # Повторный запуск ничего не находит.
        inbox_old.structure_state = "parsed"
        inbox_old.pmk_attachment_names = "Счёт.pdf"
        self.assertEqual(self.Message._pmk_queue_name_backfill(), 0)


# ═══ Лид у строки, фильтр «С лидом», звезда переписки ════════════════════════
@tagged("post_install", "-at_install")
class TestLeadOnRows(_MailCase):

    def test_row_badge_own_and_from_thread(self):
        lead = self._lead(type="opportunity")
        first = self._message(self.inbox, key="<k@x>", days_ago=3)
        reply = self._message(self.sent, key="<k@x>", days_ago=2)
        newest = self._message(self.inbox, key="<k@x>", days_ago=1)
        reply.pmk_lead_id = lead
        expected = {"id": lead.id, "name": lead.name, "type": "opportunity", "active": True}

        flat = {row["id"]: row for row in self.Folder.get_messages(folder_id=self.inbox.id)["messages"]}
        self.assertEqual(flat[first.id]["pmk_lead"], expected, "лид другого письма переписки")
        self.assertEqual(flat[newest.id]["pmk_lead"], expected)
        threaded = self.Folder.get_messages(folder_id=self.inbox.id, threaded=True)["messages"]
        self.assertEqual(threaded[0]["pmk_lead"], expected)

    def test_badge_marks_archived_lead(self):
        lead = self._lead()
        letter = self._message(self.inbox, pmk_lead_id=lead.id)
        lead.active = False
        row = self.Folder.get_messages(folder_id=self.inbox.id)["messages"][0]
        self.assertEqual(row["id"], letter.id)
        self.assertIs(row["pmk_lead"]["active"], False)

    def test_no_badge_without_rights_on_leads(self):
        buyer = new_test_user(
            self.env, login="pmk41_buyer",
            groups="base.group_user,mail_client.group_mail_client_user")
        self.account.user_id = buyer
        self._message(self.inbox, pmk_lead_id=self._lead().id)
        self.assertFalse(self.env["crm.lead"].with_user(buyer).has_access("read"))
        row = self.Folder.with_user(buyer).get_messages(folder_id=self.inbox.id)["messages"][0]
        self.assertIs(row["pmk_lead"], False)

    def test_create_lead_returns_badge(self):
        letter = self._message(self.inbox, body_html="<div>Прошу посчитать</div>",
                               body_state="fetched", structure_state="parsed",
                               pmk_cid_checked=True)
        result = letter.action_pmk_create_lead()
        self.assertEqual(result["lead"]["id"], letter.pmk_lead_id.id)
        self.assertEqual(result["thread_key"], letter.thread_key)
        badges = self.Message.pmk_lead_badges([letter.id])
        self.assertEqual(badges, [{"id": letter.id, "thread_key": letter.thread_key,
                                   "lead": result["lead"]}])

    def test_lead_button_on_reply_opens_thread_lead(self):
        """Доводка шага 41: клиент ответил в переписке, где лид уже есть, —
        «Лид» у ответа (кнопка, клавиша L, значок строки) открывает этот лид,
        привязывает к нему письмо и второго не заводит."""
        lead = self._lead()
        self._message(self.inbox, key="<deal@x>", days_ago=3, pmk_lead_id=lead.id)
        reply = self._message(self.inbox, key="<deal@x>", days_ago=1)
        leads_before = self.env["crm.lead"].with_context(active_test=False).search_count([])
        result = reply.action_pmk_create_lead()
        self.assertFalse(result["created"])
        self.assertTrue(result["from_thread"])
        self.assertEqual(result["action"]["res_id"], lead.id)
        self.assertEqual(result["lead"]["id"], lead.id)
        self.assertEqual(reply.pmk_lead_id, lead, "ответ привязан к лиду переписки")
        self.assertEqual(
            self.env["crm.lead"].with_context(active_test=False).search_count([]),
            leads_before, "второго лида на переписку нет")
        # Повторное нажатие — лид самого письма, не «от переписки».
        again = reply.action_pmk_create_lead()
        self.assertFalse(again["created"])
        self.assertFalse(again["from_thread"])

    def test_lead_of_another_mailbox_is_not_reused(self):
        """Та же переписка в другом ящике — другая переписка (как у значка
        строки): кнопка заводит свой лид."""
        other = self.env["mail.client.account"].create({
            "name": "Заявки", "email": "zakaz@example.org", "server_id": self.server.id,
            "sync_window_days": 0,
        })
        other.user_id = self.env.uid
        other_inbox = self.Folder.create({"name": "INBOX", "account_id": other.id,
                                          "imap_path": "INBOX", "role": "inbox"})
        lead = self._lead()
        self._message(other_inbox, key="<both@x>", days_ago=3, account=other,
                      pmk_lead_id=lead.id)
        letter = self._message(self.inbox, key="<both@x>", days_ago=1,
                               body_html="<div>Прошу посчитать</div>", body_state="fetched",
                               structure_state="parsed", pmk_cid_checked=True)
        result = letter.action_pmk_create_lead()
        self.assertTrue(result["created"])
        self.assertFalse(result["from_thread"])
        self.assertNotEqual(letter.pmk_lead_id, lead)

    def test_lead_filter(self):
        lead = self._lead()
        with_lead = self._message(self.inbox, key="<lead@x>", days_ago=2)
        self._message(self.sent, key="<lead@x>", days_ago=1, pmk_lead_id=lead.id)
        self._message(self.inbox, key="<plain@x>", days_ago=1)
        flat = self.Folder.get_messages(folder_id=self.inbox.id, message_filter="pmk_lead")
        self.assertEqual([row["id"] for row in flat["messages"]], [with_lead.id])
        threaded = self.Folder.get_messages(
            folder_id=self.inbox.id, threaded=True, message_filter="pmk_lead")
        self.assertEqual([row["thread_key"] for row in threaded["messages"]], ["<lead@x>"])
        with self.assertRaises(UserError):
            self.Folder.get_messages(folder_id=self.inbox.id, message_filter="nonsense")

    def test_unstar_thread_clears_every_flagged_letter(self):
        row = self._message(self.inbox, key="<s@x>", days_ago=1, flag_flagged=True)
        reply = self._message(self.sent, key="<s@x>", days_ago=2, flag_flagged=True)
        other = self._message(self.inbox, key="<other@x>", flag_flagged=True)
        result = self.Message.pmk_set_threads_flagged([row.id], False)
        self.assertFalse(row.flag_flagged)
        self.assertFalse(reply.flag_flagged, "звезда переписки снимается целиком")
        self.assertTrue(other.flag_flagged, "чужая переписка не тронута")
        self.assertEqual(result["threads"], [{"thread_key": "<s@x>", "flagged": False}])

        result = self.Message.pmk_set_threads_flagged([row.id], True)
        self.assertTrue(row.flag_flagged)
        self.assertFalse(reply.flag_flagged, "поставить — только письмо строки")
        self.assertEqual(result["threads"], [{"thread_key": "<s@x>", "flagged": True}])


# ═══ Счётчик новых писем ═════════════════════════════════════════════════════
@tagged("post_install", "-at_install")
class TestUnreadCounter(_MailCase):

    def test_counts_recent_unread_in_own_inboxes(self):
        stranger = self.env["mail.client.account"].create({
            "name": "Чужой", "email": "other@example.org", "server_id": self.server.id,
        })
        stranger_inbox = self.Folder.create({
            "name": "INBOX", "account_id": stranger.id, "imap_path": "INBOX", "role": "inbox"})
        self._message(self.inbox, seen=False, days_ago=1)          # +1
        self._message(self.inbox, seen=False, days_ago=29)         # +1
        self._message(self.inbox, seen=False, days_ago=40)         # старше окна
        self._message(self.inbox, seen=True, days_ago=1)           # прочитано
        self._message(self.sent, seen=False, days_ago=1)           # не «Входящие»
        self._message(self.spam, seen=False, days_ago=1)
        self._message(self.newsletters, seen=False, days_ago=1)    # подпапка-сортировщик
        self._message(stranger_inbox, seen=False, days_ago=1, account=stranger)
        self.assertEqual(self.env["mail.client.account"].pmk_mail_unread_count(), 2)

    def test_zero_without_mail_rights(self):
        clerk = new_test_user(self.env, login="pmk41_clerk", groups="base.group_user")
        self._message(self.inbox, seen=False)
        self.assertEqual(self.env["mail.client.account"].with_user(clerk).pmk_mail_unread_count(), 0)

    def test_assets_and_menu_contract(self):
        paths = [p[0].lstrip("/") for p in
                 self.env["ir.asset"]._get_asset_paths("web.assets_backend", {})]
        for name in ("mail_counter_rules.js", "mail_counter.js", "step41_mail.js"):
            with self.subTest(name=name):
                self.assertIn(JS + name, paths)
        self.assertIn("pmk_mail_ui/static/src/xml/step41_mail.xml", paths)
        self.assertIn("pmk_mail_ui/static/src/scss/mail_step41.scss", paths)
        # Счётчик ищет пункт меню по xmlid — пункт существует.
        self.assertTrue(self.env.ref(SALES_MAIL_MENU, raise_if_not_found=False))
        self.assertIn('"%s"' % SALES_MAIL_MENU, _read(JS + "mail_counter_rules.js"))
        # Патч окна письма грузится после файла, который заводит кнопку «Лид».
        self.assertIn("@pmk_mail_ui/js/reading_pane_lead", _read(JS + "step41_mail.js"))
        code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", _read(JS + "mail_counter.js"),
                                             flags=re.S))
        self.assertNotIn("useService(", code, "грабля шага 31: сервисы — через env.services")

    def test_styles_compile_with_step_rules(self):
        # Как на стенде: выключенные файлы темы не собираются (ir.asset, шаг 40).
        from odoo.addons.pmk_theme.tests.test_step40_dark import DEAD_THEME_PATHS
        theme = self.env["ir.asset"].search([("path", "=like", "pmk_theme/static/src/%")])
        theme.filtered(lambda asset: asset.path in DEAD_THEME_PATHS).active = False
        bundle = self.env["ir.qweb"]._get_asset_bundle("web.assets_backend", js=False)
        css = bundle.preprocess_css()
        self.assertFalse(bundle.css_errors, bundle.css_errors)
        for selector in (".o_mail_client_resizer", ".o_mail_client_row_actions",
                         ".o_mail_client_quick", ".o_mail_client_rail", "[data-pmk-count]",
                         ".pmk-mail-deal"):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)


@tagged("post_install", "-at_install")
class TestUnreadCounterSession(HttpCase):

    def test_session_info_only_with_mail(self):
        password = "pmk41-session-pass"
        reader = new_test_user(self.env, login="pmk41_reader", password=password,
                               groups="base.group_user,mail_client.group_mail_client_user")
        clerk = new_test_user(self.env, login="pmk41_noclient", password=password,
                              groups="base.group_user")
        self.authenticate(reader.login, password)
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertEqual(info.get("pmk_mail_unread"), 0, "ящиков нет — ноль, без ошибки")
        self.authenticate(clerk.login, password)
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertNotIn("pmk_mail_unread", info, "почты нет — счётчик не запускается")
