# -*- coding: utf-8 -*-
"""Клиент из письма: не плодить дубли (шаг З-14, 10.10.2026) — через модель.

Ловим:
  • клиент по домену адреса (сайт, почта, почта для прайсов, контакт внутри
    компании) и по ИНН; общие почтовые домены и свои не связывают; из двух
    на одном домене не угадываем;
  • мастер «В сделку»: «Связать с существующим» с найденным клиентом,
    «Создать нового» — только когда не нашли; подсказка со списком;
  • почта и телефон лида не уходят в карточку организации и не затираются ею;
  • команда «Продажи» в исходном имени;
  • «Возможные дубли»: группы, «Объединить…» открывает штатный мастер с
    нужной целевой карточкой, объединяет только человек, письма и сделки
    переезжают; права.
Правила без базы — test_partner_keys_rules.py.
"""

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestZ14ClientMatch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # ИНН ставим без проверки base_vat: проверяется здесь не она.
        Partner = cls.env["res.partner"].with_context(no_vat_validation=True)
        # Филиал из реестра поставщиков — в архиве, без почты, с сайтом.
        cls.branch = Partner.create({
            "name": "ООО ПО «Трубное решение-Тест», филиал Хабаровск",
            "is_company": True, "website": "https://hab.trubotest-z14.ru/",
            "phone": "+7 (4212) 52-93-57", "active": False,
        })
        # Дубль из переноса таблицы заказов — голое название.
        cls.copy = Partner.create({"name": "ТРУБНОЕ РЕШЕНИЕ-ТЕСТ", "is_company": True})
        cls.inn_company = Partner.create({
            "name": "ООО «ИНН-Тест З14»", "is_company": True, "vat": "7707083893"})

    def _lead(self, email=None, **values):
        values.setdefault("name", "Заявка З-14")
        values.setdefault("type", "lead")
        if email:
            values["email_from"] = email
        return self.env["crm.lead"].create(values)

    def _wizard(self, lead):
        return self.env["crm.lead2opportunity.partner"].with_context(
            active_model="crm.lead", active_id=lead.id, active_ids=lead.ids,
        ).create({"lead_id": lead.id, "name": "convert"})

    # ------------------------------------------------------------------
    # поиск
    # ------------------------------------------------------------------
    def test_domain_by_website_archived(self):
        match = self.env["res.partner"]._pmk_find_company(email="6574@trubotest-z14.ru")
        self.assertEqual(match["partners"], self.branch, "Сайт hab.… на том же домене.")
        self.assertEqual(match["how"], "domain")
        self.assertEqual(match["key"], "trubotest-z14.ru")
        self.assertTrue(match["archived"], "Карточка из реестра — в архиве, но найдена.")

    def test_domain_by_contact_and_price_email(self):
        company = self.env["res.partner"].create({"name": "ООО «Домен-Тест»", "is_company": True})
        self.env["res.partner"].create({
            "name": "Иванов", "parent_id": company.id, "email": "ivanov@domtest-z14.ru"})
        match = self.env["res.partner"]._pmk_find_company(email="petrov@domtest-z14.ru")
        self.assertEqual(match["partners"], company, "Контакт внутри — клиентом становится компания.")
        if "pmk_price_email" in self.env["res.partner"]._fields:
            supplier = self.env["res.partner"].create({
                "name": "ООО «Прайс-Тест»", "is_company": True,
                "pmk_price_email": "hbr@pricetest-z14.ru"})
            match = self.env["res.partner"]._pmk_find_company(email="sales@pricetest-z14.ru")
            self.assertEqual(match["partners"], supplier)

    def test_substring_domain_does_not_match(self):
        match = self.env["res.partner"]._pmk_find_company(email="a@nottrubotest-z14.ru")
        self.assertFalse(match["partners"], "Подстрока домена — не тот же домен.")

    def test_public_domains_never_match(self):
        Partner = self.env["res.partner"]
        for domain in ("mail.ru", "gmail.com", "yandex.ru", "bk.ru", "list.ru",
                       "inbox.ru", "rambler.ru", "icloud.com"):
            with self.subTest(domain=domain):
                Partner.create({"name": "ООО «%s»" % domain, "is_company": True,
                                "email": "info@%s" % domain})
                match = Partner._pmk_find_company(email="client@%s" % domain)
                self.assertFalse(match["partners"])
        # Дописанный параметром — тоже общий.
        Partner.create({"name": "ООО «Провайдер»", "is_company": True,
                        "email": "dmk@mail.provider-z14.ru"})
        self.assertTrue(Partner._pmk_find_company(email="x@provider-z14.ru")["partners"])
        self.env["ir.config_parameter"].sudo().set_param(
            "pmk_partner.public_mail_domains", "provider-z14.ru")
        self.assertFalse(Partner._pmk_find_company(email="x@provider-z14.ru")["partners"])

    def test_own_company_never_match(self):
        self.env.company.partner_id.website = "https://own-z14.ru"
        self.assertFalse(self.env["res.partner"]._pmk_find_company(
            email="colleague@own-z14.ru")["partners"])
        self.env["res.partner"].create({
            "name": "ООО «Клиент»", "is_company": True, "email": "box@box-z14.ru"})
        self.assertFalse(self.env["res.partner"]._pmk_find_company(
            email="a@box-z14.ru", exclude_domains={"mail.box-z14.ru"})["partners"],
            "Домен ящика «Почты» завода передаёт вызывающий.")

    def test_two_on_one_domain_not_guessed(self):
        Partner = self.env["res.partner"]
        first = Partner.create({"name": "ООО «Север-1»", "is_company": True,
                                "email": "a@sever-z14.ru"})
        second = Partner.create({"name": "ООО «Север-2»", "is_company": True,
                                 "website": "sever-z14.ru"})
        match = Partner._pmk_find_company(email="new@sever-z14.ru")
        self.assertEqual(match["partners"], first | second)
        lead = self._lead("new@sever-z14.ru")
        self.assertFalse(lead._find_matching_partner(), "Из двух не угадываем.")
        wizard = self._wizard(lead)
        self.assertEqual(wizard.action, "exist", "Нашли — «Создать нового» не по умолчанию.")
        self.assertFalse(wizard.partner_id, "Клиента выбирает менеджер.")
        self.assertIn("подходят несколько клиентов", wizard.pmk_client_hint)
        self.assertIn("ООО «Север-1»", wizard.pmk_client_hint)
        self.assertIn("ООО «Север-2»", wizard.pmk_client_hint)

    def test_inn_in_text(self):
        match = self.env["res.partner"]._pmk_find_company(
            email="buh@gmail.com", text="С уважением\nИНН/КПП 7707083893/770701001")
        self.assertEqual(match["partners"], self.inn_company)
        self.assertEqual(match["how"], "inn")
        self.env.company.partner_id.with_context(no_vat_validation=True).vat = "7717625418"
        match = self.env["res.partner"]._pmk_find_company(text="Наш ИНН 7717625418")
        self.assertFalse(match["partners"], "Свой ИНН клиентом не делает.")
        self.assertFalse(self.env["res.partner"]._pmk_find_company(
            text="ИНН 7707083894")["partners"], "Неверная контрольная цифра.")

    # ------------------------------------------------------------------
    # мастер «В сделку»
    # ------------------------------------------------------------------
    def test_wizard_links_found_client(self):
        lead = self._lead("6574@trubotest-z14.ru", phone="+7 (924) 916-84-62")
        self.assertEqual(lead._find_matching_partner(), self.branch)
        wizard = self._wizard(lead)
        self.assertEqual(wizard.action, "exist")
        self.assertEqual(wizard.partner_id, self.branch)
        self.assertIn("по домену trubotest-z14.ru", wizard.pmk_client_hint)
        self.assertIn("карточка в архиве", wizard.pmk_client_hint)
        self.assertIn("верните карточку из архива", wizard.pmk_client_hint)
        wizard.action_apply()
        self.assertEqual(lead.type, "opportunity")
        self.assertEqual(lead.partner_id, self.branch, "Третьего «Трубного решения» нет.")
        self.assertEqual(lead.email_from, "6574@trubotest-z14.ru")
        self.assertEqual(lead.phone, "+7 (924) 916-84-62", "Мобильный из подписи не затёрт.")
        self.assertFalse(self.branch.email, "Личный адрес не ушёл в карточку филиала.")
        self.assertEqual(self.branch.phone, "+7 (4212) 52-93-57")

    def test_wizard_creates_only_when_nothing_found(self):
        lead = self._lead("someone@nobody-z14.ru", contact_name="Пётр")
        wizard = self._wizard(lead)
        self.assertEqual(wizard.action, "create")
        self.assertFalse(wizard.pmk_client_hint)
        lead = self._lead("someone@mail.ru")
        self.assertEqual(self._wizard(lead).action, "create", "Общий домен — не находка.")

    def test_archived_client_already_in_lead(self):
        """Лид из письма ставит клиента сам (18 из архива): мастер показывает
        не находку, а что карточка в архиве — письма ей не уходят."""
        lead = self._lead("6574@trubotest-z14.ru", partner_id=self.branch.id)
        wizard = self._wizard(lead)
        self.assertEqual(wizard.action, "exist")
        self.assertEqual(wizard.partner_id, self.branch)
        self.assertIn("в архиве", wizard.pmk_client_hint)
        self.assertIn("верните карточку из архива", wizard.pmk_client_hint)
        self.assertNotIn("по домену", wizard.pmk_client_hint)
        active = self.env["res.partner"].create({"name": "ООО «Актив З14»", "is_company": True})
        lead = self._lead("a@active-z14.ru", partner_id=active.id)
        self.assertFalse(self._wizard(lead).pmk_client_hint, "Клиент в лиде, не в архиве — строки нет.")

    def test_person_never_client_by_domain_or_inn(self):
        """По домену и ИНН клиентом становится только организация: человек
        верхнего уровня (на бою — 92 «Заявка Листы…» на bvbmail.ru, ИП
        физлицом) не ставится, его карточка не меняется."""
        Partner = self.env["res.partner"].with_context(no_vat_validation=True)
        person = Partner.create({
            "name": "Заявка Листы З14", "email": "vld12@person-z14.ru",
            "phone": "+7 (924) 000-00-01", "vat": "500100732259"})
        self.assertFalse(person.is_company)
        match = Partner._pmk_find_company(email="other@person-z14.ru")
        self.assertFalse(match["partners"], "По домену — только компания.")
        match = Partner._pmk_find_company(text="ИНН 500100732259")
        self.assertFalse(match["partners"], "По ИНН — только компания.")
        lead = self._lead("other@person-z14.ru", phone="+7 (924) 916-84-62")
        self.assertFalse(lead._find_matching_partner())
        wizard = self._wizard(lead)
        self.assertEqual(wizard.action, "create")
        self.assertEqual(person.email, "vld12@person-z14.ru", "Чужой адрес в карточку не ушёл.")
        self.assertEqual(person.phone, "+7 (924) 000-00-01")
        self.assertEqual(lead.email_from, "other@person-z14.ru")
        # Точный адрес человека по-прежнему находит его (ядро).
        self.assertEqual(self._lead("vld12@person-z14.ru")._find_matching_partner(), person)

    def test_exact_email_still_first(self):
        person = self.env["res.partner"].create({
            "name": "Кытманова", "email": "6574@trubotest-z14.ru", "parent_id": self.copy.id})
        lead = self._lead("6574@trubotest-z14.ru")
        self.assertEqual(lead._find_matching_partner(), person,
                         "Точный адрес ядра — главнее домена.")

    # ------------------------------------------------------------------
    # почта и телефон: лид ↔ карточка организации
    # ------------------------------------------------------------------
    def test_company_card_keeps_its_contacts(self):
        company = self.env["res.partner"].create({
            "name": "ООО «Синхро»", "is_company": True,
            "email": "office@sync-z14.ru", "phone": "+7 (4212) 00-00-00"})
        lead = self._lead("ivan@sync-z14.ru", phone="+7 (924) 111-22-33", partner_id=company.id)
        self.assertEqual(lead.email_from, "ivan@sync-z14.ru")
        self.assertEqual(lead.phone, "+7 (924) 111-22-33")
        lead.write({"phone": "+7 (924) 999-88-77"})
        self.assertEqual(company.phone, "+7 (4212) 00-00-00")
        self.assertEqual(company.email, "office@sync-z14.ru")
        self.assertFalse(lead.partner_email_update, "Нет значка «адрес отличается».")
        self.assertFalse(lead.partner_phone_update)
        # Пустое поле лида организация заполняет — как у ядра.
        empty = self._lead(partner_id=company.id)
        self.assertEqual(empty.email_from, "office@sync-z14.ru")
        self.assertEqual(empty.phone, "+7 (4212) 00-00-00")

    def test_client_change_takes_new_card_contacts(self):
        """Почта и телефон, подтянутые из прежней организации, при смене
        клиента A → B меняются на B (как у ядра); свои — остаются."""
        Partner = self.env["res.partner"]
        first = Partner.create({"name": "ООО «Первая З14»", "is_company": True,
                                "email": "info@first-z14.ru", "phone": "+7 (4212) 11-11-11"})
        second = Partner.create({"name": "ООО «Вторая З14»", "is_company": True,
                                 "email": "info@second-z14.ru", "phone": "+7 (4212) 22-22-22"})
        lead = self._lead(partner_id=first.id)
        self.assertEqual(lead.email_from, "info@first-z14.ru")
        self.assertEqual(lead.phone, "+7 (4212) 11-11-11")
        lead.write({"partner_id": second.id})
        self.assertEqual(lead.email_from, "info@second-z14.ru", "Почта первой не осталась.")
        self.assertEqual(lead.phone, "+7 (4212) 22-22-22", "Телефон первой не остался.")
        self.assertFalse(lead.partner_email_update)
        self.assertEqual(first.email, "info@first-z14.ru")
        self.assertEqual(second.email, "info@second-z14.ru")
        # Своё значение лида (из письма) при смене клиента не трогается.
        own = self._lead("ivan@first-z14.ru", phone="+7 (924) 111-22-33", partner_id=first.id)
        own.write({"partner_id": second.id})
        self.assertEqual(own.email_from, "ivan@first-z14.ru")
        self.assertEqual(own.phone, "+7 (924) 111-22-33")
        self.assertEqual(second.email, "info@second-z14.ru")
        # Правка в форме: прежний клиент — из _origin.
        lead = self._lead(partner_id=first.id)
        draft = lead.new(origin=lead)
        draft.partner_id = second
        self.assertEqual(draft.email_from, "info@second-z14.ru")
        self.assertEqual(draft.phone, "+7 (4212) 22-22-22")

    def test_person_sync_as_core(self):
        person = self.env["res.partner"].create({"name": "Петров", "email": "p@person-z14.ru"})
        lead = self._lead("p@person-z14.ru", partner_id=person.id)
        lead.write({"phone": "+7 (924) 123-45-67"})
        self.assertEqual(person.phone, "+7 (924) 123-45-67", "С человеком — как у ядра.")

    # ------------------------------------------------------------------
    # команда «Продажи»
    # ------------------------------------------------------------------
    def test_sales_team_russian(self):
        team = self.env.ref("sales_team.team_sales_department")
        team.with_context(lang="en_US").name = "Sales"
        self.env["crm.team"]._pmk_russian_sales_team()
        self.assertEqual(team.with_context(lang="en_US").name, "Продажи")
        team.with_context(lang="en_US").name = "Отдел Петрова"
        self.env["crm.team"]._pmk_russian_sales_team()
        self.assertEqual(team.with_context(lang="en_US").name, "Отдел Петрова",
                         "Переименованную команду не трогаем.")

    # ------------------------------------------------------------------
    # «Возможные дубли»
    # ------------------------------------------------------------------
    def _rows(self):
        self.env["res.partner"].action_pmk_duplicates()
        return self.env["pmk.partner.duplicate"].search([("create_uid", "=", self.env.uid)])

    def test_duplicates_button_call(self):
        """Кнопка в шапке списка клиентов зовёт метод так, как веб-клиент:
        call_kw с отмеченными строками первым аргументом (найдено на копии 11.10:
        «takes 1 positional argument but 2 were given»)."""
        from odoo.service.model import call_kw
        action = call_kw(self.env["res.partner"], "action_pmk_duplicates", [[]], {})
        self.assertEqual(action["res_model"], "pmk.partner.duplicate")

    def test_duplicates_default_grouping(self):
        """По умолчанию — группировка «Похожие», а не поиск «1» по полю того же
        имени (найдено на копии 11.10: окно открывалось пустым)."""
        action = self.env["res.partner"].action_pmk_duplicates()
        ctx = action["context"] if isinstance(action["context"], dict) else eval(action["context"])  # noqa: S307
        self.assertIn("search_default_by_group", ctx)
        view = self.env.ref("pmk_partner.view_partner_duplicate_search")
        self.assertIn('filter name="by_group"', view.arch_db)

    def test_duplicates_screen(self):
        action = self.env["res.partner"].action_pmk_duplicates()
        self.assertEqual(action["res_model"], "pmk.partner.duplicate")
        rows = self._rows()
        pair = rows.filtered(lambda row: row.partner_id in (self.branch | self.copy))
        self.assertEqual(len(pair), 2, "18/159: архивная из реестра и голое название.")
        self.assertEqual(len(set(pair.mapped("group_no"))), 1, "Одна группа.")
        self.assertEqual(set(pair.mapped("reason")), {"Название"})
        self.assertEqual(pair.filtered(lambda r: r.partner_id == self.branch).partner_archived, "Да")
        self.assertFalse(rows.filtered(lambda r: r.partner_id == self.inn_company),
                         "Одиночка в список не попадает.")
        own = self.env.company.partner_id
        self.assertFalse(rows.filtered(lambda r: r.partner_id == own))
        # Повтор пересобирает, а не копит.
        self.assertEqual(len(self._rows()), len(rows))

    def test_duplicates_by_inn_and_domain(self):
        Partner = self.env["res.partner"].with_context(no_vat_validation=True)
        a = Partner.create({"name": "Альфа З14", "is_company": True, "vat": "500100732259"})
        b = Partner.create({"name": "Бета З14", "is_company": True, "vat": "RU500100732259"})
        c = Partner.create({"name": "Гамма З14", "is_company": True, "email": "x@gamma-z14.ru"})
        d = Partner.create({"name": "Дельта З14", "is_company": True})
        Partner.create({"name": "Сотрудник", "parent_id": d.id, "email": "y@gamma-z14.ru"})
        e = Partner.create({"name": "Эпсилон З14", "is_company": True, "email": "e@mail.ru"})
        f = Partner.create({"name": "Зета З14", "is_company": True, "email": "f@mail.ru"})
        rows = self._rows()
        reasons = {row.partner_id: row.reason for row in rows}
        self.assertEqual(reasons.get(a), "ИНН 500100732259")
        self.assertEqual(reasons.get(b), "ИНН 500100732259")
        self.assertEqual(reasons.get(c), "Домен gamma-z14.ru")
        self.assertEqual(reasons.get(d), "Домен gamma-z14.ru", "Домен — и у контакта внутри.")
        self.assertNotIn(e, reasons, "Общий почтовый домен дублей не делает.")
        self.assertNotIn(f, reasons)

    def test_merge_opens_standard_wizard(self):
        lead = self._lead("6574@trubotest-z14.ru", partner_id=self.branch.id)
        message = lead.message_post(body="Письмо клиента")
        rows = self._rows().filtered(lambda row: row.partner_id in (self.branch | self.copy))
        action = rows.action_pmk_merge()
        self.assertEqual(action["res_model"], "base.partner.merge.automatic.wizard")
        context = action["context"]
        self.assertEqual(set(context["active_ids"]), {self.branch.id, self.copy.id})
        self.assertEqual(context["pmk_merge_dst_id"], self.branch.id,
                         "Остаётся карточка, к которой привязан лид.")
        self.assertTrue(self.copy.exists(), "Кнопка ничего не объединяет сама.")

        Wizard = self.env["base.partner.merge.automatic.wizard"].with_context(**context)
        wizard = Wizard.create({})
        self.assertEqual(wizard.dst_partner_id, self.branch)
        self.assertEqual(wizard.partner_ids, self.branch | self.copy)
        copy_lead = self._lead("other@x-z14.ru", partner_id=self.copy.id)
        wizard.action_merge()
        self.assertFalse(self.copy.exists())
        self.assertTrue(self.branch.active, "Архивная 18 стала активной от 159.")
        self.assertEqual(self.branch.name, "ООО ПО «Трубное решение-Тест», филиал Хабаровск")
        self.assertEqual(lead.partner_id, self.branch)
        self.assertEqual(copy_lead.partner_id, self.branch, "Сделки переехали.")
        self.assertTrue(message.exists())
        self.assertFalse(rows.exists(),
                         "Строки объединённых карточек убраны: группа разобрана.")

    def test_merge_one_group_only(self):
        Partner = self.env["res.partner"]
        Partner.create({"name": "ООО «Меридиан З14»", "is_company": True})
        Partner.create({"name": "МЕРИДИАН З14", "is_company": True})
        rows = self._rows()
        pair = rows.filtered(lambda row: row.partner_id in (self.branch | self.copy))
        other = rows.filtered(lambda row: row.group_no != pair[:1].group_no)[:1]
        self.assertTrue(other)
        with self.assertRaises(UserError) as caught:
            (pair[:1] | other).action_pmk_merge()
        self.assertIn("разных групп", str(caught.exception))
        self.assertTrue(self.copy.exists())

    def test_duplicates_list_view(self):
        view = self.env.ref("pmk_partner.view_partner_duplicate_list")
        arch = self.env["pmk.partner.duplicate"].get_views(
            [(view.id, "list")])["views"]["list"]["arch"]
        self.assertIn('expand="1"', arch, "Группы раскрыты сразу.")
        self.assertIn('action="action_pmk_open_partner"', arch, "Щелчок по строке — карточка.")
        self.env["res.partner"].action_pmk_duplicates()
        labels = set(self._rows().mapped("group_label"))
        self.assertTrue(labels)
        self.assertTrue(all(label.startswith("Похожие: ") for label in labels))
        row = self._rows()[:1]
        action = row.action_pmk_open_partner()
        self.assertEqual((action["res_model"], action["res_id"]), ("res.partner", row.partner_id.id))

    def test_merge_needs_two_or_three(self):
        rows = self._rows()
        with self.assertRaises(UserError):
            rows[:1].action_pmk_merge()
        Partner = self.env["res.partner"]
        many = Partner.browse()
        for index in range(4):
            many |= Partner.create({"name": "ООО «Квартет З14»", "is_company": True})
        rows = self._rows().filtered(lambda row: row.partner_id in many)
        self.assertEqual(len(rows), 4)
        with self.assertRaises(UserError):
            rows.action_pmk_merge()

    def test_rights(self):
        salesman = new_test_user(
            self.env, login="z14_salesman", groups="sales_team.group_sale_salesman")
        self.assertFalse(salesman.has_group("base.group_partner_manager"))
        self.env["res.partner"].with_user(salesman).action_pmk_duplicates()
        rows = self.env["pmk.partner.duplicate"].with_user(salesman).search(
            [("create_uid", "=", salesman.id)])
        self.assertTrue(rows, "Смотреть дубли может менеджер по продажам.")
        pair = rows.filtered(lambda row: row.partner_id in (self.branch | self.copy))
        with self.assertRaises(UserError):
            pair.action_pmk_merge()
        view = self.env.ref("pmk_partner.view_partner_duplicate_list")
        arch = self.env["pmk.partner.duplicate"].with_user(salesman).get_views(
            [(view.id, "list")])["views"]["list"]["arch"]
        self.assertNotIn("action_pmk_merge", arch, "Кнопки «Объединить…» у него нет.")
        admin = self.env.ref("base.user_admin")
        admin.write({"group_ids": [Command.link(self.env.ref("base.group_partner_manager").id)]})
        arch = self.env["pmk.partner.duplicate"].with_user(admin).get_views(
            [(view.id, "list")])["views"]["list"]["arch"]
        self.assertIn("action_pmk_merge", arch)

    def test_customers_list_button(self):
        view = self.env.ref("pmk_partner.view_partner_customer_list")
        admin = self.env.ref("base.user_admin")
        admin.write({"group_ids": [Command.link(self.env.ref("sales_team.group_sale_salesman").id)]})
        arch = self.env["res.partner"].with_user(admin).get_views(
            [(view.id, "list")])["views"]["list"]["arch"]
        self.assertIn('name="action_pmk_duplicates"', arch)
        self.assertIn("Возможные дубли", arch)
        self.assertNotIn("btn-primary", arch, "Кнопка контурная.")
