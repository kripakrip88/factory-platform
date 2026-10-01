# -*- coding: utf-8 -*-
"""Карточка контрагента — разбор UX, шаг 28 (01.10.2026).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo (см. __init__.py).
Разметка — собранная, как её получает браузер (get_views: все наследники
применены). Глазами это не заменяет: кнопки, квадрат и подсказки смотрит
основной агент в браузере на копии.

Ловим:
  • тип контрагента словами завода, значения прежние; фильтры поиска —
    теми же словами («Организации» / «ИП и физлица»);
  • штатные кнопки-счётчики — только при числе больше нуля, «Сделки»
    показывает наш счётчик и открывает ровно то, что считает (и выигранную
    сделку в архиве);
  • квадрат с буквой — только у людей и у организаций со своей картинкой;
  • подсказка должности по-русски и в карточке, и в окне контакта.
"""
from lxml import etree

from odoo import Command
from odoo.fields import Domain
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

HIDDEN = ("1", "True", "true")
JOB_HINT = "например, главный инженер"


@tagged("post_install", "-at_install")
class TestPartnerCardStep28(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [Command.link(cls.env.ref(xmlid).id) for xmlid in (
            "sales_team.group_sale_salesman",
            "purchase.group_purchase_user",
            "account.group_account_invoice",
        )]})
        cls.Partner = cls.env["res.partner"].with_user(cls.admin)

    def _form(self):
        view_id = self.env.ref("base.view_partner_form").id
        views = self.Partner.get_views([(view_id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def _one(self, arch, xpath):
        nodes = arch.xpath(xpath)
        self.assertEqual(len(nodes), 1, xpath)
        return nodes[0]

    # ─── Тип контрагента ────────────────────────────────────────────────
    def test_company_type_labels(self):
        """«ИП или физлицо / Организация» вместо «Гость / Компания»."""
        selection = self.Partner.fields_get(["company_type"])["company_type"]["selection"]
        self.assertEqual([tuple(item) for item in selection],
                         [("person", "ИП или физлицо"), ("company", "Организация")])
        # Подписи не переводятся ядром — те же при любом языке интерфейса.
        en = self.Partner.with_context(lang="en_US").fields_get(["company_type"])
        self.assertEqual([label for _value, label in en["company_type"]["selection"]],
                         ["ИП или физлицо", "Организация"])
        # Значения прежние: переключатель по-прежнему ставит is_company.
        company = self.Partner.create({"name": "ООО «Тип 28»", "company_type": "company"})
        person = self.Partner.create({"name": "Иван (тип 28)", "company_type": "person"})
        self.assertTrue(company.is_company)
        self.assertFalse(person.is_company)
        self.assertEqual(company.company_type, "company")
        person.company_type = "company"
        self.assertTrue(person.is_company)

    # ─── Кнопки-счётчики ────────────────────────────────────────────────
    def test_standard_buttons_only_when_nonzero(self):
        arch = self._form()
        cases = {
            "//button[field[@name='sale_order_count']]": "not sale_order_count",
            "//button[field[@name='purchase_order_count']]": "not purchase_order_count",
            "//button[@name='action_view_partner_invoices']": "not total_invoiced",
            "//button[@name='action_view_contract']": "not contract_count",
            "//button[@name='action_view_opportunity']": "not pmk_deal_count",
        }
        for xpath, expected in cases.items():
            with self.subTest(button=xpath):
                self.assertEqual(self._one(arch, xpath).get("invisible"), expected)
        purchases = self._one(arch, "//button/field[@name='purchase_order_count']")
        self.assertEqual(purchases.get("string"), "Закупки", "«Покупки» → «Закупки».")
        invoices = self._one(arch, "//button[@name='action_view_partner_invoices']")
        self.assertEqual(invoices.get("icon"), "fa-file-text-o", "Значок шага 3 на месте.")

    def test_deals_button_shows_our_count(self):
        arch = self._form()
        button = self._one(arch, "//button[@name='action_view_opportunity']")
        ours = self._one(button, "./field[@name='pmk_deal_count']")
        self.assertEqual(ours.get("widget"), "statinfo")
        self.assertEqual(ours.get("string"), "Сделки")
        # Штатное поле в кнопке скрыто, но не удалено — на него ссылается
        # подпись pmk_deal.
        standard = self._one(button, "./field[@name='opportunity_count']")
        self.assertIn(standard.get("invisible"), HIDDEN)

    def test_deals_button_opens_what_it_counts(self):
        """Строк в списке «Сделки» по умолчанию — столько же, сколько на
        кнопке: сделки в работе и выигранные, в том числе выигранная в
        архиве; лид, проигранная и сделка в работе, убранная в архив, — нет."""
        company = self.Partner.create({"name": "ООО «Клиент 28»", "is_company": True})
        person = self.Partner.create({"name": "Иван (клиент 28)", "parent_id": company.id})
        Lead = self.env["crm.lead"]
        won_stage = self.env["crm.stage"].search([("is_won", "=", True)], limit=1)
        Lead.create({"name": "В работе 28", "type": "opportunity", "partner_id": person.id})
        Lead.create({"name": "Выиграна 28", "type": "opportunity", "partner_id": company.id,
                     "stage_id": won_stage.id})
        Lead.create({"name": "Лид из почты 28", "type": "lead", "partner_id": company.id})
        lost = Lead.create({"name": "Проиграна 28", "type": "opportunity",
                            "partner_id": company.id})
        lost.action_set_lost()
        # Находка проверки шага 28: выигранную сделку убрали в архив. Odoo 19
        # оставляет её выигранной (архив не трогает ни вероятность, ни
        # этап), и фильтр «Выиграно» её показывает — значит, и кнопка считает.
        archived_won = Lead.create({"name": "Выиграна, в архиве 28", "type": "opportunity",
                                    "partner_id": company.id, "stage_id": won_stage.id})
        archived_won.action_archive()
        self.assertEqual((archived_won.active, archived_won.won_status), (False, "won"),
                         "Посылка случая: архив выигранную сделку выигранной оставляет.")
        # Сделка в работе, убранная в архив: «В работе» её не показывает
        # (условие active = True у фильтра) — и кнопка не считает.
        archived_open = Lead.create({"name": "В работе, в архиве 28", "type": "opportunity",
                                     "partner_id": company.id, "probability": 30})
        archived_open.action_archive()
        self.assertEqual((archived_open.active, archived_open.won_status), (False, "pending"))
        self.assertEqual(company.pmk_deal_count, 3,
                         "В работе (контактного лица), выигранная и выигранная в архиве.")

        action = company.action_view_opportunity()
        self.assertIn(("type", "=", "opportunity"), action["domain"])
        context = action["context"]
        for dead in ("search_default_filter_won", "search_default_filter_ongoing",
                     "search_default_filter_lost"):
            self.assertNotIn(dead, context, "Ключ без фильтра в поиске CRM.")
        enabled = sorted(key[len("search_default_"):] for key, value in context.items()
                         if key.startswith("search_default_") and value)
        self.assertEqual(enabled, ["filter_won_status_pending", "filter_won_status_won"])

        # Фильтры берём из настоящего поиска действия: переименует их ядро —
        # тест упадёт, а не молча пропустит мёртвые ключи.
        search_id = self.env.ref("crm.crm_lead_opportunities").search_view_id.id
        search = etree.fromstring(self.env["crm.lead"].get_views(
            [(search_id, "search")])["views"]["search"]["arch"])
        domains = []
        for name in enabled:
            node = search.xpath("//filter[@name='%s']" % name)
            self.assertEqual(len(node), 1, "Фильтр %s есть в поиске сделок." % name)
            domains.append(Domain(safe_eval(node[0].get("domain"))))
        # Фильтры одной группы поиска складываются через «или».
        shown = self.env["crm.lead"].search(Domain(action["domain"]) & Domain.OR(domains))
        self.assertEqual(len(shown), company.pmk_deal_count)
        self.assertNotIn(lost, shown)
        self.assertIn(archived_won, shown)
        self.assertNotIn(archived_open, shown)
        self.assertEqual(set(shown.mapped("type")), {"opportunity"})

    def test_type_filters_named_like_card(self):
        """Фильтры поиска — теми же словами, что переключатель в карточке:
        «Организации» / «ИП и физлица», а не «Компании» / «Физические лица»."""
        search_id = self.env.ref("base.view_res_partner_filter").id
        search = etree.fromstring(self.Partner.get_views(
            [(search_id, "search")])["views"]["search"]["arch"])
        labels = {"type_company": "Организации", "type_person": "ИП и физлица"}
        for name, label in labels.items():
            with self.subTest(filter=name):
                node = self._one(search, "//filter[@name='%s']" % name)
                self.assertEqual(node.get("string"), label)
        # Отбор прежний — по is_company.
        self.assertEqual(safe_eval(self._one(search, "//filter[@name='type_company']")
                                   .get("domain")), [("is_company", "=", True)])
        # Ключ меню «Клиенты» по-прежнему находит фильтр.
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "account.res_partner_action_customer")
        self.assertIn("search_default_type_company", action["context"])

    # ─── Квадрат с буквой ───────────────────────────────────────────────
    def test_avatar_only_for_people_and_real_logos(self):
        arch = self._form()
        avatar = arch.xpath("//sheet//field[@name='image_1920']")[0]
        self.assertEqual(avatar.get("widget"), "contact_image", "Первый — аватар шапки.")
        expression = avatar.get("invisible")
        self.assertEqual(expression, "is_company and not image_1920")
        self.assertTrue(safe_eval(expression, {"is_company": True, "image_1920": False}),
                        "Заглушка с буквой у организации — скрыта.")
        self.assertFalse(safe_eval(expression, {"is_company": True, "image_1920": "15 Kb"}),
                         "Свой логотип организации — виден.")
        self.assertFalse(safe_eval(expression, {"is_company": False, "image_1920": False}),
                         "У человека квадрат остаётся.")
        # Аватар во вложенной форме контактного лица не тронут.
        nested = arch.xpath("//field[@name='child_ids']/form//field[@name='image_1920']")
        self.assertTrue(nested)
        self.assertIsNone(nested[0].get("invisible"))

    # ─── Подсказки ──────────────────────────────────────────────────────
    def test_job_title_hint(self):
        arch = self._form()
        nested = self._one(arch, "//field[@name='child_ids']/form//field[@name='function']")
        self.assertEqual(nested.get("placeholder"), JOB_HINT)
        main = self._one(arch, "//page[@name='pmk_main']//field[@name='function']")
        self.assertEqual(main.get("placeholder"), JOB_HINT)
        for node in arch.xpath("//field[@name='function']"):
            self.assertNotIn("Sales Director", node.get("placeholder") or "")

    def test_views_active(self):
        """Вид с упавшим xpath Odoo выключает при загрузке — ловим это."""
        for xmlid in ("pmk_partner.view_partner_invoices_button_icon",
                      "pmk_partner.view_partner_deals_button_count",
                      "pmk_partner.view_partner_sale_button_nonzero",
                      "pmk_partner.view_partner_purchase_button_nonzero",
                      "pmk_partner.view_partner_contract_button_nonzero",
                      "pmk_partner.view_partner_search_type_labels",
                      "pmk_partner.view_partner_form_tabs"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)
