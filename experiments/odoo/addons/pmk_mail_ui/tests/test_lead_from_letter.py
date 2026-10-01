# -*- coding: utf-8 -*-
"""Лид из письма: название и адрес (разбор UX, шаг 27) — через модель.

Сами правила без базы проверяет test_lead_text_rules.py; здесь — что кнопка
«Лид» ими пользуется, что письмо в ленте лида осталось каким пришло, что
имя контакта-человека ставит ядро, и миграция 19.0.1.0.6 на лидах,
заведённых раньше: таблица LIVE_LEADS боевой базы, повторный запуск, сделки
не тронуты, отметок в ленте нет, имя с пробелом посреди слова — в написании
из «Почты», почта карточки контакта не меняется.
"""
import importlib.util

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

from .test_lead_text_rules import LIVE_LEADS


def load_migration():
    path = file_path("pmk_mail_ui/migrations/19.0.1.0.6/post-migrate.py")
    spec = importlib.util.spec_from_file_location("pmk_mail_ui_mig_19_0_1_0_6", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestLeadFromLetter(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        # Ящик завода в тесте — «наш адрес»: пересылка коллеги с него имени
        # контакта не даёт.
        cls.account = cls.env["mail.client.account"].create({
            "name": "Заявки", "email": "zayavki@example.org", "server_id": cls.server.id,
        })
        cls.folder = cls.env["mail.client.folder"].create({
            "name": "INBOX", "account_id": cls.account.id,
            "imap_path": "INBOX", "role": "inbox",
        })
        cls.uid_seq = 100

    def _letter(self, subject, email_from):
        type(self).uid_seq += 1
        return self.env["mail.client.message"].create({
            "account_id": self.account.id, "folder_id": self.folder.id,
            "imap_uid": self.uid_seq, "subject": subject,
            "email_from": email_from, "date": fields.Datetime.now(),
            "body_html": "<div>Прошу посчитать</div>", "body_state": "fetched",
            "structure_state": "parsed", "pmk_cid_checked": True,
        })

    def test_name_address_and_contact(self):
        letter = self._letter("RE: запрос МЦ СИЗ и САС",
                              "Кузнецов Алексей <kuznetsov.a@technoavia-test.ru>")
        letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertEqual(lead.name, "Запрос МЦ СИЗ и САС")
        self.assertEqual(lead.email_from, "kuznetsov.a@technoavia-test.ru")
        self.assertEqual(lead.contact_name, "Кузнецов Алексей")
        # Письмо в ленте — каким пришло: своя тема, свой отправитель.
        posted = lead.message_ids.filtered(lambda m: m.message_type == "email")
        self.assertEqual(posted.subject, "RE: запрос МЦ СИЗ и САС")
        self.assertIn("Кузнецов Алексей", posted.email_from)

    def test_bare_address_and_name_like_address(self):
        letter = self._letter("FW: Заявка на закладные", "u.pyankova@uess-test.ru")
        letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertEqual(lead.name, "Заявка на закладные")
        self.assertEqual(lead.email_from, "u.pyankova@uess-test.ru")
        self.assertFalse(lead.contact_name)

        letter = self._letter("Заявка Листы", "vld12@bvb-test.ru <vld12@bvb-test.ru>")
        letter.action_pmk_create_lead()
        self.assertEqual(letter.pmk_lead_id.email_from, "vld12@bvb-test.ru")
        self.assertFalse(letter.pmk_lead_id.contact_name, "Имя-адрес — не имя.")

    def test_empty_subject_after_prefix(self):
        letter = self._letter("RE:", "Оксана <oksana@cks-test.ru>")
        letter.action_pmk_create_lead()
        self.assertEqual(letter.pmk_lead_id.name, "Без темы")

    def test_forward_from_own_mailbox_gives_no_contact(self):
        letter = self._letter("Fwd: RE: ммк", '"Владимир Голубенко" <ZAYAVKI@example.org>')
        letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertEqual(lead.name, "ммк", "Сокращение строчными — как написано, не «Ммк».")
        self.assertEqual(lead.email_from, "ZAYAVKI@example.org")
        self.assertFalse(lead.contact_name, "Пересылка коллеги — не контакт клиента.")
        self.assertIn("zayavki@example.org", self.env["mail.client.message"]._pmk_own_addresses())

    def test_person_contact_name_from_card(self):
        """Письмо привязано к контакту-человеку — имя из карточки (ядро), а не
        из письма: в письме бывает «Миша», в карточке — полное имя."""
        company = self.env["res.partner"].create({"name": "ООО «Проба»", "is_company": True})
        person = self.env["res.partner"].create({
            "name": "Цыганов Михаил Анатольевич", "parent_id": company.id,
            "email": "tsyganov@proba-test.ru"})
        letter = self._letter("Re: Запрос стоимости", "Миша <tsyganov@proba-test.ru>")
        self.assertEqual(letter.partner_id, person, "Почтовый модуль находит контакт по адресу.")
        letter.action_pmk_create_lead()
        lead = letter.pmk_lead_id
        self.assertEqual(lead.partner_id, person)
        self.assertEqual(lead.contact_name, "Цыганов Михаил Анатольевич")
        self.assertEqual(lead.email_from, "tsyganov@proba-test.ru")

    def test_company_contact_takes_letter_name(self):
        company = self.env["res.partner"].create({
            "name": "ООО «Металл-проба»", "is_company": True, "email": "info@metall-test.ru"})
        letter = self._letter("Прайс", "Анна Сергеевна <info@metall-test.ru>")
        self.assertEqual(letter.partner_id, company)
        letter.action_pmk_create_lead()
        self.assertEqual(letter.pmk_lead_id.contact_name, "Анна Сергеевна")

    def test_migration_live_leads(self):
        Lead = self.env["crm.lead"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True, tracking_disable=True)
        # Наш ящик в тесте — адрес лида 5 с боевой базы.
        self.env["mail.client.account"].create({
            "name": "Боевой", "email": "pmkpark@mail.ru", "server_id": self.server.id,
            "active": False,
        })
        created = {}
        for lead_id, active, name, email, contact, _expected in LIVE_LEADS:
            created[lead_id] = Lead.create({
                "type": "lead", "name": name, "email_from": email,
                "contact_name": contact or False, "active": active,
            })
        deal = Lead.create({
            "type": "opportunity", "name": "Fwd: Re: Cчет Сч-0015114",
            "email_from": '"Владимир Голубенко" <pmkpark@mail.ru>',
        })
        messages_before = {lead.id: len(lead.message_ids) for lead in created.values()}

        migration = load_migration()
        migration.migrate(self.env.cr, "19.0.1.0.5")
        self.env.invalidate_all()

        for lead_id, _active, name, email, contact, expected in LIVE_LEADS:
            lead = created[lead_id]
            with self.subTest(lead=lead_id):
                self.assertEqual(lead.name, expected.get("name", name))
                self.assertEqual(lead.email_from, expected.get("email_from", email))
                self.assertEqual(lead.contact_name or "", expected.get("contact_name", contact))
                self.assertEqual(len(lead.message_ids), messages_before[lead.id],
                                 "Без отметок в ленте.")
        self.assertEqual(deal.name, "Fwd: Re: Cчет Сч-0015114", "Сделки не трогаем.")
        self.assertEqual(deal.email_from, '"Владимир Голубенко" <pmkpark@mail.ru>')

        # Повторный запуск — ничего не меняет.
        snapshot = {lead.id: (lead.name, lead.email_from, lead.contact_name)
                    for lead in created.values()}
        migration.migrate(self.env.cr, "19.0.1.0.5")
        self.env.invalidate_all()
        for lead in created.values():
            self.assertEqual((lead.name, lead.email_from, lead.contact_name), snapshot[lead.id])

    def test_migration_spelling_from_letters(self):
        """«Сергеев ич» из алиаса ядра — написание из письма «Почты» с тем же
        адресом; другой адрес или другое имя — как было."""
        Lead = self.env["crm.lead"].with_context(tracking_disable=True)
        self._letter("Прайс", "Киселёв Николай Сергеевич <kiselev@mmk-test.ru>")
        self._letter("Прайс", "Иван Петров <other@mmk-test.ru>")
        broken = Lead.create({
            "type": "lead", "name": "RE: Запрос прайса",
            "email_from": '"Киселёв Николай Сергеев ич" <kiselev@mmk-test.ru>',
        })
        alien = Lead.create({
            "type": "lead", "name": "Запрос",
            "email_from": '"Пётр Сидор ов" <sidorov@mmk-test.ru>',
        })
        load_migration().migrate(self.env.cr, "19.0.1.0.5")
        self.env.invalidate_all()
        self.assertEqual(broken.name, "Запрос прайса")
        self.assertEqual(broken.email_from, "kiselev@mmk-test.ru")
        self.assertEqual(broken.contact_name, "Киселёв Николай Сергеевич")
        self.assertEqual(alien.contact_name, "Пётр Сидор ов",
                         "Писем с этим адресом нет — имя как пришло, не угадываем.")

    def test_migration_keeps_partner_email(self):
        """У лида с контактом, почта которого другая, «Эл. почту» не правим:
        ядро (crm.lead._inverse_email_from) переписало бы адрес в карточку."""
        company = self.env["res.partner"].create({
            "name": "ООО «Фирма-проба»", "is_company": True, "email": "office@firma-test.ru"})
        lead = self.env["crm.lead"].with_context(tracking_disable=True).create({
            "type": "lead", "name": "Fwd: заявка", "partner_id": company.id,
        })
        # Рассинхрон, как у лида, к которому контакт привязали позже: ORM его
        # не допускает (почта лида и контакта синхронизируются), поэтому — SQL.
        # Сначала сбросить отложенные вычисления ORM: иначе следующий flush
        # перезаписал бы наш UPDATE почтой контакта.
        self.env.flush_all()
        self.env.cr.execute("UPDATE crm_lead SET email_from = %s WHERE id = %s",
                            ['Анна <anna@firma-test.ru>', lead.id])
        self.env.invalidate_all()
        load_migration().migrate(self.env.cr, "19.0.1.0.5")
        self.env.invalidate_all()
        self.assertEqual(lead.name, "Заявка")
        self.assertEqual(lead.email_from, "Анна <anna@firma-test.ru>")
        self.assertEqual(company.email, "office@firma-test.ru", "Карточка контакта не тронута.")
        self.assertEqual(lead.contact_name, "Анна", "Контакт — компания: имя из письма.")
