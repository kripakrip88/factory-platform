# -*- coding: utf-8 -*-
"""Виды сделки и воронки после шага 31 — собранная разметка, как её получает
браузер (get_views: все наследники применены, ничего не выключено).

Глазами это не заменяет: вид проверяет основной агент в браузере на копии.
Здесь ловится то, что ломается молча: xpath, который перестал находить узел
(Odoo выключает такой вид с WARNING), вторая залитая кнопка и семь видов
воронки. «СМС» в списке сделок — модуль pmk_deal_sms, его тесты там.
"""
from lxml import etree

from odoo.tests import TransactionCase, tagged


def hidden(node):
    """Скрыт ли узел насовсем (invisible="1" — после сборки может стать True)."""
    return (node.get("invisible") or "").strip() in ("1", "True", "true")


@tagged("post_install", "-at_install")
class TestDealViews(TransactionCase):

    def _arch(self, view_type, view_xmlid=None):
        view_id = self.env.ref(view_xmlid).id if view_xmlid else False
        views = self.env["crm.lead"].get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def test_our_views_are_active(self):
        """Вид с упавшим xpath Odoo выключает при загрузке — ловим это."""
        for xmlid in (
            "pmk_deal.view_crm_lead_form_money",
            "pmk_deal.view_crm_lead_kanban_money",
            "pmk_deal.view_crm_lead_search_money",
            "pmk_deal.view_crm_lead_quick_create_money",
            "pmk_deal.view_crm_lead_form_hide_empty_quotations",
            "pmk_deal.view_crm_lead_list_tones",
        ):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_form_one_filled_button_is_ours(self):
        arch = self._arch("form")
        header = arch.find("header")
        filled = [b for b in header.iter("button") if "oe_highlight" in (b.get("class") or "")]
        ours = [b for b in filled if b.get("name") == "action_open_specs"]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0].get("string"), "Расчёт и КП")
        # Остальные залитые — не для сделки в работе: «Сделать сделкой» у
        # лида и спрятанная штатная «Новое КП».
        for button in filled:
            if button is ours[0]:
                continue
            invisible = button.get("invisible") or ""
            self.assertTrue(
                hidden(button) or "type == 'opportunity'" in invisible,
                "Лишняя залитая кнопка: %s" % etree.tostring(button, encoding="unicode"))
        quotation = header.find(".//button[@name='action_sale_quotations_new']")
        self.assertIsNotNone(quotation, "Штатная кнопка скрыта, а не удалена.")
        self.assertTrue(hidden(quotation))
        # Порядок: наша первой, перед «Выиграно».
        names = [b.get("name") for b in header.iter("button")]
        self.assertLess(names.index("action_open_specs"), names.index("action_set_won_rainbowman"))

    def test_form_money_line_and_hidden_blocks(self):
        arch = self._arch("form")
        title = arch.xpath("//div[contains(concat(' ', @class, ' '), ' oe_title ')]")[0]
        self.assertTrue(hidden(title.find("h2")), "Доход и вероятность скрыты целиком.")
        money = title.find("div[@class='pmk-deal-money']")
        self.assertIsNotNone(money)
        self.assertIsNotNone(money.find("field[@name='pmk_spec_summary']"))
        self.assertIsNotNone(money.find("field[@name='pmk_no_price_label']"))
        # Подсказка про кнопку — только там, где кнопка есть: у проигранной
        # (архивной) сделки «Расчёт и КП» скрыта.
        hint = money.find("span[@class='pmk-deal-money__empty']")
        self.assertEqual(hint.get("invisible"), "pmk_spec_id or not active")
        button = arch.find(".//header/button[@name='action_open_specs']")
        self.assertIn("not active", button.get("invisible"))
        self.assertTrue(hidden(arch.find(".//page[@name='lead']")))
        opp = arch.find(".//group[@name='opportunity_partner']")
        for fname in ("partner_name", "contact_name", "function"):
            with self.subTest(field=fname):
                node = opp.find("field[@name='%s']" % fname)
                self.assertIsNotNone(node)
                self.assertEqual(node.get("invisible"), "partner_id")
        # Метка лида привязана к своему полю, а не к нашему наверху.
        lead_info = arch.find(".//group[@name='lead_info']")
        self.assertEqual(lead_info.find("label").get("for"), "contact_name_group_lead_info")
        self.assertEqual(lead_info.find(".//field[@name='contact_name']").get("id"),
                         "contact_name_group_lead_info")
        self.assertEqual(arch.find(".//label[@for='date_deadline']").get("string"),
                         "Ответить клиенту до")
        # Подсказка «?» у метки — наша, а не «дата, когда возможность будет
        # выиграна»; атрибут вида не зависит от переводов поля.
        deadline = arch.xpath("//field[@name='date_deadline'][@placeholder]")[0]
        self.assertIn("Срок ответа клиенту", deadline.get("help"))
        # Кнопка-счётчик «Расчёты» — только у сделки: расчёт по лиду не
        # заводят (поле «Сделка» у расчёта принимает только сделки).
        counter = arch.xpath("//button[@name='action_open_specs'][contains(@class, 'oe_stat_button')]")
        self.assertEqual(len(counter), 1)
        self.assertEqual(counter[0].get("invisible"), "type == 'lead'")
        self.assertEqual(len(arch.findall(".//field[@name='pmk_source']")), 2,
                         "«Откуда пришёл» — у лида и у сделки.")
        # Команда продаж: у лида — поле скрыто, у сделки — на скрытой вкладке.
        lead_team = arch.xpath("/form/sheet/group/group/field[@name='team_id']")
        self.assertEqual(len(lead_team), 1)
        self.assertTrue(hidden(lead_team[0]))
        self.assertTrue(arch.xpath("//page[@name='lead']//field[@name='team_id']"))

    def test_kanban_card(self):
        arch = self._arch("kanban", "crm.crm_case_kanban_view_leads")
        card = arch.find(".//t[@t-name='card']")
        self.assertIsNotNone(card.find(".//div[@class='pmk-deal-card']"))
        revenue = card.find(".//div[@class='o_kanban_card_crm_lead_revenue']")
        self.assertIsNotNone(revenue, "Узел дохода на месте — на нём прогнозный канбан.")
        self.assertEqual(revenue.get("invisible"), "pmk_spec_id")
        client = card.find("field[@name='pmk_client_id']")
        self.assertIsNotNone(client, "Клиент — без имени человека.")
        self.assertEqual(client.get("invisible"), "not partner_id")
        self.assertIsNone(card.find("field[@name='commercial_partner_id']"),
                          "Штатное commercial_partner_id пусто у компании и частного лица.")
        rotting = card.find(".//footer//span[@invisible='not is_rotting']")
        self.assertIsNotNone(rotting)
        self.assertIn("дн", "".join(rotting.itertext()))
        progressbar = arch.find("progressbar")
        self.assertEqual(progressbar.get("sum_field"), "expected_revenue",
                         "Сумма в шапке колонки — доход, то есть цена клиенту.")

    def test_forecast_kanban_still_builds(self):
        """Прогнозный канбан заменяет узел дохода своим xpath'ом."""
        arch = self._arch("kanban", "crm.crm_lead_view_kanban_forecast")
        self.assertEqual(arch.find("progressbar").get("sum_field"), "prorated_revenue")

    def test_list_deadline(self):
        arch = self._arch("list", "crm.crm_case_tree_view_oppor")
        deadline = arch.find(".//field[@name='date_deadline'][@optional]")
        self.assertEqual(deadline.get("string"), "Ответить клиенту до")

    def test_list_stage_badge(self):
        """Стадия — нашим виджетом: у него своя ширина колонки (шаг 24,
        listViewWidth в stage_badge_field.js), и «КП отправлено · 8 дн» не
        режется. Ширину в атрибуте вида не задаём — она бы её перебила."""
        arch = self._arch("list", "crm.crm_case_tree_view_oppor")
        stage = arch.xpath("//field[@name='stage_id']")
        self.assertEqual(len(stage), 1)
        self.assertEqual(stage[0].get("widget"), "pmk_stage_badge")
        self.assertIsNone(stage[0].get("width"))

    def test_deadline_field_label_everywhere(self):
        """Подпись и подсказка — в самом поле: «Добавить свой фильтр»,
        своя группировка и выгрузка берут их из описания поля."""
        info = self.env["crm.lead"].fields_get(["date_deadline"], ["string", "help"])["date_deadline"]
        self.assertEqual(info["string"], "Ответить клиенту до")
        self.assertIn("Срок ответа клиенту", info["help"])
        self.assertNotIn("возможность", info["help"])

    def test_quick_create_without_revenue(self):
        """Быстрое создание в воронке: доход не вписывают — его даёт расчёт."""
        views = self.env["crm.lead"].get_views(
            [(self.env.ref("crm.quick_create_opportunity_form").id, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        revenue = arch.find(".//field[@name='expected_revenue']")
        self.assertIsNotNone(revenue, "Поле скрыто, а не удалено.")
        self.assertTrue(hidden(revenue))
        priority = arch.find(".//field[@name='priority']")
        self.assertFalse(hidden(priority), "Звёзды приоритета остаются.")
        self.assertFalse(arch.xpath("//i[contains(@class, 'fa-money')]"))

    def test_partner_deals_button_same_views_as_pipeline(self):
        """Клиент → «Сделки»: без графика, сводной и календаря, как воронка;
        список первым, как у ядра."""
        partner = self.env["res.partner"].create({"name": "ООО «Проба»", "is_company": True})
        action = partner.action_view_opportunity()
        modes = [mode for _view, mode in action["views"]]
        self.assertEqual(modes[0], "list")
        self.assertFalse({"graph", "pivot", "calendar"} & set(modes), modes)
        self.assertIn("kanban", modes)
        self.assertEqual(action["view_mode"], ",".join(modes))

    def test_search_group_by_source(self):
        arch = self._arch("search", "crm.view_crm_case_opportunities_filter")
        node = arch.find(".//filter[@name='groupby_pmk_source']")
        self.assertIsNotNone(node)
        self.assertEqual(node.get("string"), "Откуда пришёл")

    def test_pipeline_three_views(self):
        action = self.env.ref("crm.crm_lead_action_pipeline")
        modes = [mode for _view, mode in action.views]
        self.assertEqual(modes, ["kanban", "list", "form", "activity"])
        analytics = self.env.ref("pmk_deal.action_pipeline_analytics")
        kept = {mode for _view, mode in analytics.views}
        self.assertTrue({"calendar", "pivot", "graph"} <= kept,
                        "Аналитические виды не удалены, а собраны отдельно.")
        self.assertEqual(
            self.env.ref("crm.crm_lead_action_pipeline_view_graph").act_window_id, analytics)

    def test_stage_thresholds_after_install(self):
        """post_init_hook выставил сроки на новой базе, как миграция на боевой."""
        for xmlid, days in (("crm.stage_lead1", 1), ("crm.stage_lead2", 2),
                            ("crm.stage_lead3", 7), ("crm.stage_lead4", 0)):
            with self.subTest(stage=xmlid):
                self.assertEqual(self.env.ref(xmlid).rotting_threshold_days, days)


@tagged("post_install", "-at_install")
class TestSpecFormDeal(TransactionCase):
    """Расчёт, разбор UX, шаг 32: «Сделка» — первой и во всю ширину."""

    def test_deal_first_in_spec_head(self):
        self.assertTrue(self.env.ref("pmk_deal.view_metal_spec_form_deal").active)
        views = self.env["pmk.metal.spec"].get_views([(False, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        head = arch.xpath("//div[contains(concat(' ', @class, ' '), ' pmk-doc-head__fields ')]")[0]
        blocks = [d for d in head if d.tag == "div"]
        self.assertEqual(blocks[0].get("name"), "pmk_f_deal")
        self.assertIsNotNone(blocks[0].find("field[@name='opportunity_id']"))
        self.assertIn("pmk-field--wide", blocks[0].get("class"),
                      "Во всю ширину: в половине название сделки обрезалось.")
        self.assertEqual(blocks[1].get("name"), "pmk_f_partner")
