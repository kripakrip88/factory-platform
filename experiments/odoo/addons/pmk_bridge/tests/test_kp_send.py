# -*- coding: utf-8 -*-
"""Печать и отправка КП из расчёта (разбор UX, шаг 33).

Гонять ТОЛЬКО на одноразовой ЧИСТОЙ базе — не на боевой odoo и не на копии
прода (там подключены настоящие ящики):
    odoo -d pmk_kp_test -i pmk_deal,pmk_mail_ui --test-enable \\
         --test-tags /pmk_bridge,/pmk_deal,/pmk_mail_ui --stop-after-init --http-port 8099

ПИСЬМА НАРУЖУ НЕ УХОДЯТ. Класс — MailCommon ядра, каждая отправка — внутри
mock_mail_gateway(): SMTP подменён, письма ложатся в self._mails (сборка
письма) и self.emails (что получил бы SMTP-сервер). Копию в IMAP-папку
«Отправленные» (pmk_mail_ui) держит предохранитель модуля, а здесь она ещё и
заменена заглушкой: поддельного IMAP у ядра нет.

Ящик завода в тестах — kp.box@example.com и свой исходящий сервер с тем же
from_filter, как Mail.ru на живой базе (from_filter = pmkpark@mail.ru).
"""
from contextlib import contextmanager
from unittest.mock import patch

from lxml import etree

from odoo import Command
from odoo.addons.mail.tests.common import MailCommon
from odoo.tests import Form, tagged
from odoo.tools import email_normalize

from ..tools import spec_text

COMPANY_BOX = "kp.box@example.com"


@tagged("post_install", "-at_install")
class TestKpSend(MailCommon):

    def setUp(self):
        super().setUp()
        # В режиме тестов Odoo рисует отчёт HTML-ом, а настоящий PDF
        # (wkhtmltopdf) в TransactionCase зависает: он ходит за стилями на
        # сервер, занятый тестом. Подменяем рендер: вложение — «PDF КП» с
        # правильным типом, содержимое неважно.
        Report = type(self.env["ir.actions.report"])
        self.patch(Report, "_render_qweb_pdf",
                   lambda report, report_ref, res_ids=None, data=None: (b"%PDF-1.4 test", "pdf"))

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Шаблон письма и печать — на ru_RU, как на живой базе.
        cls.env["res.lang"]._activate_lang("ru_RU")
        # Как на живой базе: почта организации — ящик, через который шлём, и
        # единственный контрагент с этим адресом — сама организация.
        cls.company_admin.email = COMPANY_BOX
        cls.box_server = cls.env["ir.mail_server"].create({
            "name": "Ящик завода (тест)",
            "smtp_host": "localhost",
            "from_filter": COMPANY_BOX,
            "sequence": 1,
        })
        cls.client = cls.env["res.partner"].create({
            "name": "ООО «Арестак-Строй» (тест)", "is_company": True,
            "email": "office@arestak.example.com",
        })
        cls.contact = cls.env["res.partner"].create({
            "name": "Цыганов Михаил Анатольевич", "parent_id": cls.client.id,
            "email": "tsyganov@arestak.example.com",
        })
        cls.template = cls.env.ref("pmk_bridge.mail_template_metal_spec_quotation")

    # ─── помощники ──────────────────────────────────────────────────────
    def _spec(self, user=None, **values):
        vals = {
            "partner_id": self.client.id,
            "contact_id": self.contact.id,
            "note": "Каркас навеса",
            "product_ids": [
                Command.create({"name": "Каркас", "qty": 1, "price_customer_unit": 5000.0}),
                Command.create({"name": "тест", "qty": 2}),
            ],
        }
        vals.update(values)
        return self.env["pmk.metal.spec"].with_user(user or self.user_admin).with_context(
            mail_create_nolog=True).create(vals)

    def _open(self, spec, user=None):
        """Нажать «Отправить КП» и открыть окно письма (без отправки)."""
        user = user or self.user_admin
        action = spec.with_user(user).action_send_quotation()
        composer = self.env["mail.compose.message"].with_user(user).with_context(action["context"])
        return action, Form(composer)

    @contextmanager
    def _no_real_mail(self):
        """SMTP подменён ядром; копию в IMAP (pmk_mail_ui) — заглушкой."""
        server_cls = type(self.env["ir.mail_server"])
        with self.mock_mail_gateway():
            if hasattr(server_cls, "_pmk_file_to_sent"):
                with patch.object(server_cls, "_pmk_file_to_sent",
                                  autospec=True, return_value=False) as filed:
                    yield filed
            else:
                yield None

    # ─── кнопка ─────────────────────────────────────────────────────────
    def test_button_only_opens_window(self):
        spec = self._spec()
        messages = len(spec.message_ids)
        with self._no_real_mail():
            action = spec.with_user(self.user_admin).action_send_quotation()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "mail.compose.message")
        self.assertEqual(action["target"], "new")
        ctx = action["context"]
        self.assertEqual(ctx["default_template_id"], self.template.id)
        self.assertEqual(ctx["default_res_ids"], spec.ids)
        self.assertEqual(ctx["default_composition_mode"], "comment")
        self.assertTrue(ctx["pmk_kp_send"])
        self.assertIs(ctx["mail_post_autofollow"], False,
                      "Клиент не становится подписчиком расчёта.")
        self.assertFalse(self._new_mails, "Кнопка сама ничего не отправляет.")
        spec.invalidate_recordset(["message_ids"])
        self.assertEqual(len(spec.message_ids), messages)

    # ─── окно письма ────────────────────────────────────────────────────
    def test_window_is_prefilled(self):
        # Как у admin на живой базе: своей почты нет.
        self.partner_admin.email = False
        spec = self._spec()
        _action, form = self._open(spec)
        self.assertEqual(form.pmk_kp_to_hint, False)
        composer = form.save()

        self.assertEqual(composer.template_id, self.template)
        self.assertEqual(composer.subject,
                         "Коммерческое предложение %s — Каркас навеса" % spec.name)
        self.assertEqual(composer.partner_ids, self.contact,
                         "Кому — контактное лицо с почтой.")
        self.assertEqual(email_normalize(composer.email_from), COMPANY_BOX,
                         "Отправитель — ящик организации: Mail.ru примет только его.")
        self.assertIn(self.user_admin.name, composer.email_from, "Имя — пользователя.")
        self.assertEqual(email_normalize(composer.reply_to), COMPANY_BOX,
                         "Ответ — в тот же ящик, а не в catchall.")
        self.assertEqual(composer.author_id, self.partner_admin,
                         "Автор — кто отправляет, а не организация с тем же адресом.")
        self.assertFalse(composer.email_add_signature, "Подпись — в тексте шаблона.")

        names = composer.attachment_ids.mapped("name")
        self.assertEqual(len(names), 1, names)
        self.assertTrue(names[0].startswith("КП %s." % spec.name), names)

        body = composer.body
        self.assertIn("Здравствуйте, Михаил Анатольевич!", body)
        self.assertIn(spec.name, body)
        self.assertIn("Каркас навеса", body)
        self.assertIn(self.user_admin.name, body)
        self.assertIn(COMPANY_BOX, body)

        self.assertTrue(composer.pmk_kp_skip_text)
        self.assertEqual(composer.pmk_kp_skip_text, spec.kp_skip_text,
                         "Тот же сигнал, что в шапке расчёта.")
        self.assertIn(COMPANY_BOX, composer.pmk_kp_sender_text)
        self.assertIn("ответ клиента придёт в этот ящик", composer.pmk_kp_sender_text)
        self.assertFalse(composer.pmk_kp_sender_hint, "Адрес есть — жёлтой плашки нет.")
        self.assertFalse(composer.pmk_kp_pdf_hint, "PDF приложен — плашки нет.")
        self.assertTrue(spec._pmk_kp_pdf(composer.attachment_ids))
        # Тёмный цвет текста в теле письма в тёмной теме не читался бы ни в
        # окне, ни в ленте расчёта: цвета в шаблоне нет.
        self.assertNotIn("color:#1a1a1a", body.replace(" ", ""))
        self.assertNotIn("color:", self.template.body_html.replace(" ", ""))

    def test_recipient_falls_back_to_client(self):
        self.contact.email = False
        composer = self._open(self._spec())[1].save()
        self.assertEqual(composer.partner_ids, self.client)
        self.assertIn("Здравствуйте!", composer.body, "Компании — без имени.")

    def test_no_email_window_still_opens(self):
        """Сигнал, не запрет: окно открывается, получателя вписывают сами."""
        self.contact.email = False
        self.client.email = False
        _action, form = self._open(self._spec())
        self.assertEqual(len(form.partner_ids), 0)
        self.assertEqual(form.pmk_kp_to_hint,
                         "Впишите получателя: у контактного лица и клиента нет почты")
        self.assertTrue(form.subject)
        typed = self.env["res.partner"].create({
            "name": "Снабжение", "email": "supply@arestak.example.com"})
        form.partner_ids.add(typed)
        self.assertFalse(form.pmk_kp_to_hint, "Вписали — подсказка гаснет.")

    def test_no_client_window_still_opens(self):
        spec = self._spec(partner_id=False, contact_id=False)
        _action, form = self._open(spec)
        self.assertEqual(len(form.partner_ids), 0)
        self.assertEqual(form.pmk_kp_to_hint, "Впишите получателя: в расчёте не выбран клиент")

    # ─── сигналы окна (доводка шага 33) ────────────────────────────────
    def test_sender_missing_is_signal_not_grey(self):
        """Нет почты ни у организации, ни у пользователя: не серая справка, а
        жёлтая плашка — сервер такое письмо не примет."""
        self.company_admin.email = False
        self.partner_admin.email = False
        _action, form = self._open(self._spec())
        self.assertFalse(form.pmk_kp_sender_text)
        self.assertEqual(form.pmk_kp_sender_hint, spec_text.kp_sender_hint(False))
        self.assertIn("адрес не задан", form.pmk_kp_sender_hint)

    def test_empty_kp_signal(self):
        """КП без единого изделия с ценой — плашка; окно открывается."""
        _action, form = self._open(self._spec(product_ids=[]))
        self.assertEqual(form.pmk_kp_skip_text, "КП пустое: в расчёте нет изделий")
        _action, form = self._open(self._spec(product_ids=[
            Command.create({"name": "тест", "qty": 2})]))
        self.assertEqual(form.pmk_kp_skip_text,
                         "КП пустое: ни у одного изделия нет цены клиенту")
        # Есть с ценой — обычный сигнал «не попадут без цены».
        spec = self._spec()
        _action, form = self._open(spec)
        self.assertEqual(form.pmk_kp_skip_text, spec.kp_skip_text)

    def test_no_pdf_signal(self):
        """Убрали PDF в окне — плашка; вернули — гаснет."""
        spec = self._spec()
        _action, form = self._open(spec)
        pdf = form.attachment_ids[0]
        self.assertFalse(form.pmk_kp_pdf_hint)
        form.attachment_ids.clear()
        self.assertEqual(form.pmk_kp_pdf_hint, spec_text.KP_NO_PDF)
        form.attachment_ids.add(pdf)
        self.assertFalse(form.pmk_kp_pdf_hint)

    def test_template_deleted_window_still_opens(self):
        """Шаблон удалили в Настройках: окно пустое, но отправитель — ящик
        завода, и видно, что PDF нет."""
        self.template.unlink()
        spec = self._spec()
        action, form = self._open(spec)
        self.assertFalse(action["context"]["default_template_id"])
        self.assertEqual(email_normalize(form.email_from), COMPANY_BOX)
        self.assertEqual(form.pmk_kp_pdf_hint, spec_text.KP_NO_PDF)

    def test_window_from_chatter_is_untouched(self):
        """То же окно без флага (из ленты документа) — как было."""
        spec = self._spec()
        form = Form(self.env["mail.compose.message"].with_user(self.user_admin).with_context(
            default_model=spec._name, default_res_ids=spec.ids,
            default_composition_mode="comment"))
        self.assertFalse(form.pmk_kp_sender_text)
        self.assertFalse(form.pmk_kp_sender_hint)
        self.assertFalse(form.pmk_kp_skip_text)
        self.assertFalse(form.pmk_kp_pdf_hint)
        self.assertFalse(form.pmk_kp_to_hint)
        self.assertFalse(form.template_id)

    def test_view_signals_and_hidden_reply_to(self):
        arch = self.env["mail.compose.message"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("context.get('pmk_kp_send')", arch)
        tree = etree.fromstring(arch)
        # Справка — серым, проблемы — жёлтыми плашками.
        for name, css in (("pmk_kp_sender_text", "text-muted"),
                          ("pmk_kp_sender_hint", "pmk-signal"),
                          ("pmk_kp_skip_text", "pmk-signal"),
                          ("pmk_kp_pdf_hint", "pmk-signal"),
                          ("pmk_kp_to_hint", "pmk-signal")):
            with self.subTest(field=name):
                span = tree.xpath("//span[field[@name='%s']]" % name)
                self.assertEqual(len(span), 1)
                self.assertIn(css, span[0].get("class").split())
                self.assertEqual(span[0].get("invisible"), "not %s" % name)
        self.assertTrue(self.env.ref("pmk_bridge.view_mail_compose_kp").active,
                        "Вид с упавшим xpath Odoo выключает при загрузке.")

    # ─── отправка ───────────────────────────────────────────────────────
    def test_send_goes_from_company_box(self):
        self.partner_admin.email = False
        spec = self._spec()
        composer = self._open(spec)[1].save()
        with self._no_real_mail() as filed:
            composer.action_send_mail()

        # Одно письмо — контактному лицу; автору (admin) уведомления нет.
        self.assertEqual(len(self._new_mails), 1)
        self.assertEqual(self._new_mails.recipient_ids, self.contact)
        # Сервер — ящик завода, конверт и заголовок From — его адрес.
        self.assertSMTPEmailsSent(smtp_from=COMPANY_BOX, mail_server=self.box_server,
                                  emails_count=1)
        sent = self.emails[0]
        self.assertEqual(email_normalize(sent["msg_from"]), COMPANY_BOX)
        self.assertIn(self.user_admin.name, sent["msg_from"])
        self.assertIn("tsyganov@arestak.example.com", sent["smtp_to_list"])

        built = self._mails[0]
        self.assertEqual(email_normalize(built["reply_to"]), COMPANY_BOX)
        self.assertEqual(built["subject"], "Коммерческое предложение %s — Каркас навеса" % spec.name)
        self.assertTrue(any(name.startswith("КП %s." % spec.name)
                            for name, *_rest in built["attachments"]), built["attachments"])
        self.assertIn("Здравствуйте, Михаил Анатольевич!", built["body"])
        self.assertNotIn("Powered by", built["body"], "Внешнему получателю — без подвала Odoo.")

        # В ленте расчёта — письмо от пользователя с PDF; клиент не подписан.
        spec.invalidate_recordset()
        message = spec.message_ids.filtered(lambda m: m.message_type == "comment")[:1]
        self.assertTrue(message)
        self.assertEqual(message.author_id, self.partner_admin)
        self.assertEqual(message.partner_ids, self.contact)
        self.assertEqual(len(message.attachment_ids), 1)
        self.assertNotIn(self.contact, spec.message_partner_ids)
        self.assertNotIn(self.client, spec.message_partner_ids)
        if filed is not None:
            filed.assert_not_called()

    def test_hook_fires_only_on_real_send(self):
        spec = self._spec()
        spec_cls = type(self.env["pmk.metal.spec"])
        with patch.object(spec_cls, "_pmk_kp_sent", autospec=True, return_value=True) as sent:
            composer = self._open(spec)[1].save()
            sent.assert_not_called()                      # окно открыли — и всё
            # Внутренняя заметка с тем же флагом — не КП.
            spec.with_user(self.user_admin).with_context(pmk_kp_send=True).message_post(
                body="уточнить толщину у технолога",
                subtype_xmlid="mail.mt_note", message_type="comment")
            sent.assert_not_called()
            with self._no_real_mail():
                composer.action_send_mail()
            self.assertEqual(sent.call_count, 1)
            record, message = sent.call_args[0]
            self.assertEqual(record, spec)
            self.assertEqual(message.message_type, "comment")
            self.assertEqual(message.partner_ids, self.contact)

    def test_sales_user_without_template_rights(self):
        """Менеджер без группы «редактор шаблонов», как будет на живой базе
        (mail.restrict.template.rendering = True): окно и отправка работают."""
        self.env["ir.config_parameter"].set_param("mail.restrict.template.rendering", True)
        self.user_employee.group_ids -= self.env.ref("mail.group_mail_template_editor")
        self.assertFalse(self.user_employee.has_group("mail.group_mail_template_editor"))
        spec = self._spec()
        composer = self._open(spec, user=self.user_employee)[1].save()
        self.assertIn("Здравствуйте, Михаил Анатольевич!", composer.body)
        self.assertEqual(email_normalize(composer.email_from), COMPANY_BOX)
        self.assertIn(self.user_employee.name, composer.email_from)
        self.assertEqual(composer.author_id, self.user_employee.partner_id)
        with self._no_real_mail():
            composer.action_send_mail()
        self.assertSMTPEmailsSent(smtp_from=COMPANY_BOX, mail_server=self.box_server)

    # ─── печать ─────────────────────────────────────────────────────────
    def _print_html(self, spec, user=None):
        report = self.env["ir.actions.report"].with_user(user or self.user_admin)
        html, _fmt = report._render_qweb_html(
            "pmk_bridge.action_report_metal_spec_quotation", spec.ids)
        return html.decode()

    def test_print_two_totals_and_manager(self):
        spec = self._spec()
        html = self._print_html(spec).replace("\xa0", " ")
        self.assertIn("Итого к оплате:", html)
        self.assertIn("в том числе НДС", html)
        self.assertNotIn("Итого:", html, "«Итого» и «Итого к оплате» — было одно число дважды.")
        self.assertLess(html.index("Итого к оплате:"), html.index("в том числе НДС"),
                        "«В том числе» — под суммой, к которой относится.")
        self.assertIn("Менеджер: %s, тел. %s" % (self.user_admin.name, self.partner_admin.phone), html)
        self.assertIn("Каркас", html)
        self.assertNotIn(">тест<", html, "Изделие без цены в КП не попадает.")

    def test_manager_empty_parts_not_printed(self):
        self.partner_admin.write({"phone": False, "email": False})
        spec = self._spec()
        self.assertEqual(spec.pmk_manager_line(), "Менеджер: %s" % self.user_admin.name)

    def test_manager_creator_then_current_user_not_odoobot(self):
        # Создал admin, печатает сотрудник — менеджер тот, кто создал.
        spec = self._spec()
        self.assertEqual(spec.with_user(self.user_employee)._pmk_manager(), self.user_admin)
        # Создал OdooBot (как СМ-15/21/22) — менеджер тот, кто печатает.
        bot_spec = self.env["pmk.metal.spec"].create({"partner_id": self.client.id})
        self.assertEqual(bot_spec.create_uid, self.env.ref("base.user_root"))
        self.assertEqual(bot_spec.with_user(self.user_employee)._pmk_manager(), self.user_employee)
        line = bot_spec.with_user(self.user_employee).pmk_manager_line()
        self.assertTrue(line.startswith("Менеджер: %s" % self.user_employee.name), line)
        self.assertNotIn("OdooBot", line)
