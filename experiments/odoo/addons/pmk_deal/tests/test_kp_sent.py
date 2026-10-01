# -*- coding: utf-8 -*-
"""КП отправлено — сделка это видит (разбор UX, шаг 33).

Гонять ТОЛЬКО на одноразовой ЧИСТОЙ базе (см. tests/__init__.py).

Письма наружу не уходят: MailCommon ядра, отправка внутри
mock_mail_gateway(), копия в IMAP-«Отправленные» (pmk_mail_ui) — заглушкой.
"""
from contextlib import contextmanager
from unittest.mock import patch

from odoo import Command
from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user
from odoo.tests import Form, tagged

from ..models import kp_sent

# Значение по умолчанию — до любых патчей в тестах.
_DEFAULT_MOVES = kp_sent.KP_SENT_MOVES_STAGE

COMPANY_BOX = "kp.box@example.com"


@tagged("post_install", "-at_install")
class TestKpSentDeal(MailCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("ru_RU")
        cls.company_admin.email = COMPANY_BOX
        cls.env["ir.mail_server"].create({
            "name": "Ящик завода (тест)", "smtp_host": "localhost",
            "from_filter": COMPANY_BOX, "sequence": 1,
        })
        cls.client = cls.env["res.partner"].create({
            "name": "ООО «Арестак-Строй» (тест)", "is_company": True,
            "email": "office@arestak.example.com",
        })
        cls.contact = cls.env["res.partner"].create({
            "name": "Цыганов Михаил Анатольевич", "parent_id": cls.client.id,
            "email": "tsyganov@arestak.example.com",
        })
        # Пробный адрес: человек не из компании клиента.
        cls.tester = cls.env["res.partner"].create({
            "name": "Антон (проба)", "email": "anton.test@example.com"})
        cls.stage_request = cls.env.ref("crm.stage_lead1")
        cls.stage_calc = cls.env.ref("crm.stage_lead2")
        cls.stage_kp = cls.env.ref(kp_sent.KP_SENT_STAGE)
        cls.stage_won = cls.env.ref("crm.stage_lead4")

    def setUp(self):
        super().setUp()
        # В режиме тестов Odoo рисует отчёт HTML-ом, а настоящий PDF
        # (wkhtmltopdf) в TransactionCase зависает: он ходит за стилями на
        # сервер, занятый тестом. Подменяем рендер: вложение — «PDF КП» с
        # правильным типом, содержимое неважно.
        Report = type(self.env["ir.actions.report"])
        self.patch(Report, "_render_qweb_pdf",
                   lambda report, report_ref, res_ids=None, data=None: (b"%PDF-1.4 test", "pdf"))
        # Переход стадии выключен решением Антона («без автоперехода»);
        # логику перехода проверяем с включённым переключателем, а то, что
        # по умолчанию он выключен, — отдельным тестом.
        self.patch(kp_sent, "KP_SENT_MOVES_STAGE", True)

    def test_default_moves_stage(self):
        self.assertTrue(_DEFAULT_MOVES, "Антон 01.10.2026: автопереход в «КП отправлено» включён.")

    # ─── помощники ──────────────────────────────────────────────────────
    def _deal(self, stage, user=None):
        return self.env["crm.lead"].with_context(mail_create_nolog=True).create({
            "name": "МК п. Горный (тест)", "type": "opportunity",
            "partner_id": self.contact.id, "stage_id": stage.id,
            "user_id": (user or self.user_admin).id,
        })

    def _spec(self, deal, user=None):
        return self.env["pmk.metal.spec"].with_user(user or self.user_admin).with_context(
            mail_create_nolog=True).create({
                "opportunity_id": deal.id, "partner_id": self.client.id,
                "contact_id": self.contact.id, "note": "Каркас",
                "product_ids": [Command.create({
                    "name": "Каркас", "qty": 1, "price_customer_unit": 1000.0})],
            })

    def _window(self, spec, user=None, recipients=None):
        user = user or self.user_admin
        action = spec.with_user(user).action_send_quotation()
        form = Form(self.env["mail.compose.message"].with_user(user).with_context(action["context"]))
        if recipients is not None:
            form.partner_ids.set(recipients)
        return form.save()

    @contextmanager
    def _no_real_mail(self):
        server_cls = type(self.env["ir.mail_server"])
        with self.mock_mail_gateway():
            if hasattr(server_cls, "_pmk_file_to_sent"):
                with patch.object(server_cls, "_pmk_file_to_sent", autospec=True, return_value=False):
                    yield
            else:
                yield

    def _send(self, spec, user=None, recipients=None, without_pdf=False):
        composer = self._window(spec, user=user, recipients=recipients)
        if without_pdf:
            # Менеджер убрал вложение в окне.
            composer.attachment_ids = [Command.clear()]
        with self._no_real_mail():
            composer.action_send_mail()
        return composer

    def _notes(self, deal, spec):
        deal.invalidate_recordset(["message_ids"])
        return deal.message_ids.filtered(lambda m: spec.name in (m.body or ""))

    # ─── стадия вперёд ─────────────────────────────────────────────────
    def test_forward_from_request_and_calc(self):
        for stage in (self.stage_request, self.stage_calc):
            with self.subTest(stage=stage.name):
                deal = self._deal(stage)
                spec = self._spec(deal)
                self._send(spec)
                self.assertEqual(deal.stage_id, self.stage_kp)
                note = self._notes(deal, spec)
                self.assertEqual(len(note), 1)
                self.assertIn("отправлено", note.body)
                self.assertIn("tsyganov@arestak.example.com", note.body)
                self.assertIn("в ленте расчёта", note.body)
                self.assertTrue(note.subtype_id.internal, "Заметка, а не письмо подписчикам.")
                self.assertEqual(note.author_id, self.partner_admin)

    def test_opening_window_moves_nothing(self):
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        self._window(spec)
        self.assertEqual(deal.stage_id, self.stage_request)
        self.assertFalse(self._notes(deal, spec))

    # ─── только вперёд ────────────────────────────────────────────────
    def test_never_backwards_won_or_lost(self):
        deal_kp = self._deal(self.stage_kp)
        deal_won = self._deal(self.stage_request)
        deal_won.action_set_won()
        deal_lost = self._deal(self.stage_calc)
        deal_lost.action_set_lost()
        self.assertEqual(deal_won.won_status, "won")
        self.assertEqual(deal_lost.won_status, "lost")
        for deal, stage in ((deal_kp, self.stage_kp),
                            (deal_won, deal_won.stage_id),
                            (deal_lost, self.stage_calc)):
            with self.subTest(deal=deal.id):
                spec = self._spec(deal)
                self._send(spec)
                self.assertEqual(deal.stage_id, stage)
                self.assertEqual(len(self._notes(deal, spec)), 1,
                                 "Заметка пишется и повторно, и у выигранной, и у проигранной.")
        self.assertFalse(deal_lost.active)
        self.assertEqual(deal_won.won_status, "won")

    # ─── пробный адрес ─────────────────────────────────────────────────
    def test_test_address_does_not_move(self):
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        self._send(spec, recipients=self.tester)
        self.assertEqual(deal.stage_id, self.stage_request)
        note = self._notes(deal, spec)
        self.assertEqual(len(note), 1)
        self.assertIn("anton.test@example.com", note.body)
        self.assertIn("стадию не меняли", note.body)

    def test_typed_client_address_counts(self):
        """Клиент без контакта: вписали адрес клиента руками — это клиент."""
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        same_box = self.env["res.partner"].create({
            "name": "Приёмная", "email": "Office@Arestak.example.com"})
        self._send(spec, recipients=same_box)
        self.assertEqual(deal.stage_id, self.stage_kp)

    def test_switch_off_leaves_stage(self):
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        with patch.object(kp_sent, "KP_SENT_MOVES_STAGE", False):
            self._send(spec)
        self.assertEqual(deal.stage_id, self.stage_request)
        note = self._notes(deal, spec)
        self.assertEqual(len(note), 1)
        self.assertNotIn("стадию не меняли", note.body)

    # ─── проба на свой ящик: завод — не клиент ─────────────────────────
    def test_own_box_deal_trial_does_not_move(self):
        """Как сделка №1 живой базы: заведена из письма своего ящика, контакт —
        сама организация. Проба на ящик завода стадию не двигает."""
        own = self.company_admin.partner_id
        self.assertEqual(own.email_normalized, COMPANY_BOX)
        deal = self.env["crm.lead"].with_context(mail_create_nolog=True).create({
            "name": "Возможность (тест)", "type": "opportunity",
            "partner_id": own.id, "email_from": COMPANY_BOX,
            "stage_id": self.stage_request.id, "user_id": self.user_admin.id,
        })
        self.assertEqual(deal.email_normalized, COMPANY_BOX)
        for partner in (own, self.client):
            with self.subTest(spec_partner=partner.name):
                spec = self.env["pmk.metal.spec"].with_context(mail_create_nolog=True).create({
                    "opportunity_id": deal.id, "partner_id": partner.id,
                    "product_ids": [Command.create({
                        "name": "Каркас", "qty": 1, "price_customer_unit": 1000.0})],
                })
                self._send(spec, recipients=own)
                self.assertEqual(deal.stage_id, self.stage_request)
                note = self._notes(deal, spec)
                self.assertEqual(len(note), 1)
                self.assertIn(COMPANY_BOX, note.body)
                self.assertIn("стадию не меняли", note.body)

    def test_employee_address_does_not_move(self):
        """Сотрудник завода в «Кому» — не клиент, даже с почтой на домене клиента."""
        self.partner_employee.email = "staff@arestak.example.com"
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        self._send(spec, recipients=self.partner_employee)
        self.assertEqual(deal.stage_id, self.stage_request)

    # ─── новый адрес клиента ───────────────────────────────────────────
    def test_new_address_on_client_domain_counts(self):
        """Вписали в «Кому» новый адрес клиента, которого нет в карточках."""
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        typed = self.env["res.partner"].create({
            "name": "Снабжение", "email": "Snab@Arestak.example.com"})
        self.assertFalse(typed.parent_id)
        self._send(spec, recipients=typed)
        self.assertEqual(deal.stage_id, self.stage_kp)
        self.assertNotIn("стадию не меняли", self._notes(deal, spec).body)

    def test_public_domain_is_not_enough(self):
        """У клиента почта на gmail.com: чужой адрес на gmail.com — не его человек."""
        self.client.email = "arestak.office@gmail.com"
        self.contact.email = "tsyganov.arestak@gmail.com"
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        stranger = self.env["res.partner"].create({
            "name": "Кто-то", "email": "someone.else@gmail.com"})
        self._send(spec, recipients=stranger)
        self.assertEqual(deal.stage_id, self.stage_request)
        # А сам контакт с gmail.com — клиент (по карточке).
        self._send(spec)
        self.assertEqual(deal.stage_id, self.stage_kp)

    def test_domain_helper(self):
        self.assertEqual(kp_sent.mail_domain("Snab@ArestakStroy.RU"), "arestakstroy.ru")
        self.assertEqual(kp_sent.mail_domain('"Отдел" <a@b.ru>'), "b.ru")
        self.assertEqual(kp_sent.mail_domain(False), "")
        self.assertEqual(kp_sent.mail_domain("не адрес"), "")
        self.assertIn("mail.ru", kp_sent.PUBLIC_MAIL_DOMAINS)
        _partners, emails, domains = self.env["pmk.metal.spec"]._pmk_own_mail()
        self.assertIn(COMPANY_BOX, emails, "Почта организации и from_filter ящика — свои.")
        self.assertIn("example.com", domains)

    # ─── письмо без PDF КП ─────────────────────────────────────────────
    def test_without_pdf_does_not_move(self):
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        self._send(spec, without_pdf=True)
        self.assertEqual(deal.stage_id, self.stage_request)
        note = self._notes(deal, spec)
        self.assertEqual(len(note), 1)
        self.assertIn("без PDF", note.body)
        self.assertIn("стадию не меняли", note.body)

    def test_own_pdf_with_number_counts(self):
        """Менеджер заменил PDF своим — с номером расчёта в имени это КП."""
        deal = self._deal(self.stage_request)
        spec = self._spec(deal)
        composer = self._window(spec)
        # Файл приложен в окне: его создатель — тот, кто отправляет.
        own_pdf = self.env["ir.attachment"].with_user(self.user_admin).create({
            "name": "КП %s исправленное.pdf" % spec.name, "raw": b"%PDF-1.4 test",
            "mimetype": "application/pdf",
            "res_model": "mail.compose.message", "res_id": 0,
        })
        composer.attachment_ids = [Command.set(own_pdf.ids)]
        with self._no_real_mail():
            composer.action_send_mail()
        self.assertEqual(deal.stage_id, self.stage_kp)

    # ─── права: чужая сделка ───────────────────────────────────────────
    def _salesman(self):
        return mail_new_test_user(
            self.env, login="salesman_kp", name="Сергей Продажин",
            groups="base.group_user,sales_team.group_sale_salesman",
            notification_type="inbox")

    def test_salesman_cannot_touch_someone_elses_deal(self):
        """Менеджер «только свои» шлёт КП по сделке admin: письмо уходит, а
        сделку он не видит — её не трогаем, объяснение — в ленте расчёта."""
        salesman = self._salesman()
        deal = self._deal(self.stage_request)
        self.assertFalse(deal.with_user(salesman).has_access("read"))
        spec = self._spec(deal)
        self._send(spec, user=salesman)
        self.assertEqual(deal.stage_id, self.stage_request)
        self.assertFalse(self._notes(deal, spec), "В чужую сделку ничего не пишем.")
        spec.invalidate_recordset(["message_ids"])
        explained = spec.message_ids.filtered(lambda m: "менять нельзя по правам" in (m.body or ""))
        self.assertEqual(len(explained), 1)
        self.assertEqual(explained.author_id, salesman.partner_id)

    def test_salesman_moves_own_deal(self):
        salesman = self._salesman()
        deal = self._deal(self.stage_request, user=salesman)
        spec = self._spec(deal)
        self._send(spec, user=salesman)
        self.assertEqual(deal.stage_id, self.stage_kp)
        note = self._notes(deal, spec)
        self.assertEqual(note.author_id, salesman.partner_id, "Автор — кто отправил, не sudo.")

    # ─── менеджер в КП ─────────────────────────────────────────────────
    def test_manager_is_deal_owner(self):
        deal = self._deal(self.stage_request, user=self.user_employee)
        spec = self._spec(deal)
        self.assertEqual(spec._pmk_manager(), self.user_employee,
                         "Ответственный сделки — впереди создавшего расчёт.")
        self.assertTrue(spec.pmk_manager_line().startswith(
            "Менеджер: %s" % self.user_employee.name))
        # Ответственный уволен (в архиве) — менеджер тот, кто создал расчёт.
        self.user_employee.active = False
        spec.invalidate_recordset()
        self.assertEqual(spec._pmk_manager(), self.user_admin)
