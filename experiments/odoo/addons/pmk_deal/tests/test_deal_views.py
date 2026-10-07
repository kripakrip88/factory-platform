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
        # Приёмка 01.10.2026 (R1): карточки вместо одной строки.
        self.assertIsNone(money.find(".//field[@name='pmk_spec_summary']"),
                          "Строка «СМ · т · цена · металл · маржа» сливалась.")
        kpi = money.find("div[@class='pmk-deal-kpi']")
        self.assertIsNotNone(kpi)
        self.assertEqual(kpi.get("invisible"), "not pmk_spec_id")
        cards = [c for c in kpi if c.tag == "div"]
        labels = [c.find("div[@class='pmk-kpi__label']").text for c in cards]
        self.assertEqual(labels, ["Расчёт", "Вес", "Цена клиенту", "Металл",
                                  "Маржа", "Маржа", "Без цены"])
        for card in cards:
            self.assertIn("pmk-kpi__card", card.get("class").split(), "Классы темы.")
        spec = cards[0].find(".//field[@name='pmk_spec_id']")
        self.assertFalse(hidden(spec), "Номер расчёта — видимой ссылкой.")
        names = [c.find(".//field").get("name") for c in cards]
        self.assertEqual(names, ["pmk_spec_id", "pmk_kpi_weight", "pmk_kpi_price",
                                 "pmk_kpi_metal", "pmk_kpi_margin", "pmk_kpi_margin",
                                 "pmk_no_price_count"])
        margin, margin_bad, no_price = cards[4], cards[5], cards[6]
        self.assertNotIn("pmk-deal-kpi__card--bad", margin.get("class"))
        self.assertIn("pmk-deal-kpi__card--bad", margin_bad.get("class"))
        self.assertEqual(margin.get("invisible"), "pmk_price_incomplete and pmk_spec_price")
        self.assertEqual(margin_bad.get("invisible"),
                         "not pmk_price_incomplete or not pmk_spec_price")
        self.assertIn("pmk-deal-kpi__card--bad", no_price.get("class"))
        self.assertEqual(no_price.get("invisible"), "not pmk_no_price_count",
                         "«Без цены» — только когда больше нуля.")
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

    def test_lead_left_column_step27(self):
        """Лид без дыры в левой колонке (разбор UX, шаг 27): слева Компания ·
        Менеджер · Откуда пришёл · Приоритет · Теги, справа — контакт.
        Поля перенесены (move), не продублированы; опустевшие группы скрыты,
        узел «Команды продаж» на месте."""
        arch = self._arch("form")
        lead = arch.xpath("//group[@name='lead_partner']")[0]
        visible = [f.get("name") for f in lead.findall("field")
                   if not hidden(f) and f.get("name") != "partner_id"]
        expected = ["partner_name", "user_id", "pmk_source", "priority", "tag_ids"]
        # Шаг 53: теги — до востребования (pmk_theme, группа «Убранное
        # (показать)»): сервер вырезает узел у того, кого в группе нет.
        removed = self.env.ref("pmk_theme.group_pmk_removed", raise_if_not_found=False)
        if removed and removed not in self.env.user.all_group_ids:
            expected.remove("tag_ids")
        self.assertEqual(visible, expected)
        self.assertEqual(lead.find("field[@name='partner_name']").get("string"), "Компания")
        self.assertTrue(lead.find("field[@name='partner_name']").get("help"))
        user = lead.find("field[@name='user_id']")
        self.assertEqual(user.get("string"), "Менеджер")
        self.assertEqual(user.get("widget"), "many2one_avatar_leader_user",
                         "Перенесён штатный узел — со своим виджетом и teamField.")
        self.assertEqual(user.get("teamField"), "team_id")
        self.assertEqual(lead.find("field[@name='priority']").get("widget"), "priority")
        # Одна «Откуда пришёл» у лида, одна у сделки.
        self.assertEqual(len(arch.xpath("//group[@name='lead_partner']/field[@name='pmk_source']")), 1)
        # Группа «Менеджер / Команда продаж» лида — скрыта, в ней только команда.
        team_group = arch.xpath("/form/sheet/group/group[field[@name='team_id']]")
        self.assertEqual(len(team_group), 1)
        self.assertTrue(hidden(team_group[0]))
        self.assertEqual([f.get("name") for f in team_group[0].findall("field")], ["team_id"])
        priority_group = arch.xpath("//group[@name='lead_priority']")[0]
        self.assertTrue(hidden(priority_group))
        self.assertFalse(priority_group.findall("field"), "Приоритет и теги перенесены.")
        # Правая колонка лида — без изменений.
        info = arch.xpath("//group[@name='lead_info']")[0]
        self.assertTrue({"contact_name", "email_from", "function", "phone"}
                        <= {f.get("name") for f in info.iter("field")})
        # Сделка: «Менеджер» и «Компания» — те же слова.
        deal = arch.xpath("/form/sheet/group/group[label[@for='date_deadline']]")[0]
        self.assertEqual(deal.find("field[@name='user_id']").get("string"), "Менеджер")
        opp = arch.find(".//group[@name='opportunity_partner']")
        self.assertEqual(opp.find("field[@name='partner_name']").get("string"), "Компания")
        # «Вероятность» у лида скрыта с шага 31 — блок h2 целиком.
        self.assertTrue(hidden(arch.xpath("//div[contains(concat(' ', @class, ' '), ' oe_title ')]/h2")[0]))
        # Подписи верхних групп — в одну строку (штатный o_label_nowrap):
        # «Ответить клиенту до» со знаком «?» шире колонки ядра в 150 px.
        top = arch.xpath("/form/sheet/group")[0]
        self.assertIn("o_label_nowrap", (top.get("class") or "").split())

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

    def test_pipeline_colors_request_not_component_bound(self):
        """Воронка не появлялась на живом стенде (01.10.2026, v1.17.0): общий
        запрос цветов этапов шёл через this.orm шапки — службу, «защищённую»
        компонентом. Шапка, начавшая запрос, погибала при пересоздании колонок,
        и её промис не разрешался никогда — остальные шапки ждали вечно.
        Общий запрос — только через незащищённую env.services.orm."""
        from odoo.tools.misc import file_path

        with open(file_path("pmk_deal/static/src/js/pipeline_kanban.js"), encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("loadStageColors(this.orm", source)
        self.assertRegex(source, r"loadStageColors\(\s*this\.env\.services\.orm")

    def test_pipeline_header_assets(self):
        """Приёмка 01.10.2026 (R10): шапка колонки воронки — свои шаблоны
        поверх штатных crm/mail. Сам вид смотрит основной агент глазами;
        здесь — что файлы подключены и шаблоны наследуют то, что надо."""
        from odoo.modules.module import get_manifest
        from odoo.tools.misc import file_path

        assets = get_manifest("pmk_deal")["assets"]["web.assets_backend"]
        for path in ("pmk_deal/static/src/js/money_short.js",
                     "pmk_deal/static/src/js/pipeline_kanban.js",
                     "pmk_deal/static/src/xml/pipeline_kanban.xml",
                     "pmk_deal/static/src/scss/pipeline_kanban.scss"):
            with self.subTest(asset=path):
                self.assertIn(path, assets)
        with open(file_path("pmk_deal/static/src/xml/pipeline_kanban.xml"), "rb") as f:
            templates = etree.fromstring(f.read())
        by_name = {t.get("t-name"): t for t in templates.findall("t")}
        progress = by_name["pmk_deal.ColumnProgress"]
        self.assertEqual(progress.get("t-inherit"), "crm.ColumnProgress")
        self.assertEqual(progress.get("t-inherit-mode"), "primary")
        # Полоски задач нет только в воронке: тот же компонент рисует шапку
        # канбана лидов, там она штатная (находка проверки 01.10.2026).
        bar = progress.find("xpath")
        self.assertIn("o_column_progress", bar.get("expr"))
        self.assertEqual(bar.get("position"), "attributes", "Скрыта условием, не вырезана.")
        self.assertEqual(bar.find("attribute[@name='t-if']").text, "!env.pmkPipeline")
        header = by_name["pmk_deal.KanbanHeader"]
        self.assertEqual(header.get("t-inherit"), "mail.RottingKanbanHeader")
        self.assertEqual(header.get("t-inherit-mode"), "primary")
        strip = header.find(".//div[@class='pmk-stage-strip']")
        self.assertIsNotNone(strip)
        self.assertIn("o_colorlist_item_color_", strip.get("t-attf-class"))
        count = header.find("xpath[@position='attributes']/attribute[@name='t-if']")
        self.assertIn("env.pmkPipeline or !progressBar", count.text,
                      "«(N)» всегда — только в воронке.")
        # Цвет этапа — поле «Цвет» в «Настройки CRM → Этапы».
        self.assertIn("color", self.env["crm.stage"]._fields)

    def test_pipeline_marker_only_on_pipeline(self):
        """Признак, по которому шапка воронки отличает себя от канбана лидов
        (js/pipeline_kanban.js, isPipelineArch): класс o_opportunity_kanban.
        Он должен быть у воронки и НЕ быть у канбана лидов — у того полоска
        задач без суммы, число в шапке — счёт лидов, и наш денежный формат
        написал бы «5 ₽»."""
        pipeline = self._arch("kanban", "crm.crm_case_kanban_view_leads")
        self.assertEqual(pipeline.get("js_class"), "crm_kanban")
        self.assertIn("o_opportunity_kanban", (pipeline.get("class") or "").split())
        leads = self._arch("kanban", "crm.view_crm_lead_kanban")
        self.assertEqual(leads.get("js_class"), "crm_kanban", "Тот же рендерер.")
        self.assertNotIn("o_opportunity_kanban", (leads.get("class") or "").split())
        self.assertFalse(leads.find("progressbar").get("sum_field"),
                         "У лидов в шапке счёт, а не деньги.")

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
