# -*- coding: utf-8 -*-
"""Колонки списков сделок и лидов — разбор UX, шаг 25.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Разметка — собранная,
как её получает браузер (get_views: все наследники применены). Глазами это не
заменяет: ширину, перенос шапки и полоску маржи смотрит основной агент в
браузере. Здесь ловится то, что ломается молча: упавший xpath (Odoo выключает
такой вид), колонка, вернувшаяся в меню колонок, и порядок колонок.
"""
from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.tests import TransactionCase, tagged

HIDDEN = ("1", "True", "true")


def invisible_column(node):
    return (node.get("column_invisible") or "").strip() in HIDDEN


def shown(node):
    """Колонка видна без ⚙: не убрана и не спрятана в меню колонок."""
    return not invisible_column(node) and node.get("optional") != "hide"


@tagged("post_install", "-at_install")
class TestDealListColumnsStep25(TransactionCase):

    def _arch(self, view_xmlid):
        views = self.env["crm.lead"].get_views([(self.env.ref(view_xmlid).id, "list")])
        return etree.fromstring(views["views"]["list"]["arch"])

    def _one(self, arch, name):
        nodes = arch.xpath("/list/field[@name='%s']" % name)
        self.assertEqual(len(nodes), 1, name)
        return nodes[0]

    def test_views_active(self):
        for xmlid in ("pmk_deal.view_crm_lead_list_columns",
                      "pmk_deal.view_crm_lead_list_activities_keep",
                      "pmk_deal.view_crm_lead_leads_list_columns",
                      "pmk_deal.view_crm_lead_list_tones"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_deal_list_order(self):
        """Сделка · Клиент · Имя контакта · Менеджер · Цена клиенту · Маржа ·
        Вес, т · Ответить клиенту до · Стадия — порядок документа разбора."""
        arch = self._arch("crm.crm_case_tree_view_oppor")
        visible = [f.get("name") for f in arch.xpath("/list/field") if shown(f)]
        expected = ["name", "pmk_client_id", "contact_name", "user_id", "expected_revenue",
                    "pmk_margin_pct", "pmk_weight_t", "date_deadline", "stage_id"]
        self.assertEqual([n for n in visible if n in expected], expected)
        self.assertEqual(self._one(arch, "user_id").get("string"), "Менеджер")
        # Шаг 31 не сломан: подписи и виджет стадии на месте.
        self.assertEqual(self._one(arch, "expected_revenue").get("string"), "Цена клиенту")
        deadline = arch.xpath("/list/field[@name='date_deadline'][@optional]")[0]
        self.assertEqual(deadline.get("string"), "Ответить клиенту до")
        self.assertEqual(self._one(arch, "stage_id").get("widget"), "pmk_stage_badge")

    def test_margin_and_weight(self):
        arch = self._arch("crm.crm_case_tree_view_oppor")
        margin = self._one(arch, "pmk_margin_pct")
        self.assertEqual(margin.get("widget"), "pmk_margin_bar")
        options = margin.get("options")
        for key in ("pmk_price_incomplete", "pmk_spec_price", "pmk_no_price_count"):
            self.assertIn(key, options)
        # База — цена из расчёта, а не правимая в строке «Цена клиенту».
        self.assertNotIn("expected_revenue", options)
        # Служебные поля полоски — в разметке (иначе браузер их не загрузит),
        # но колонками не показываются и в ⚙ не попадают.
        for name in ("pmk_price_incomplete", "pmk_no_price_count", "pmk_spec_price"):
            with self.subTest(field=name):
                self.assertTrue(invisible_column(self._one(arch, name)))
        weight = self._one(arch, "pmk_weight_t")
        self.assertEqual(weight.get("digits"), "[12,3]")
        self.assertTrue(weight.get("sum"))
        # Проценты маржи в строке группы не складываются.
        info = self.env["crm.lead"].fields_get(["pmk_margin_pct"], ["aggregator"])
        self.assertFalse(info["pmk_margin_pct"].get("aggregator"))

    def test_deal_list_hidden(self):
        arch = self._arch("crm.crm_case_tree_view_oppor")
        self.assertEqual(self._one(arch, "email_from").get("optional"), "hide",
                         "Эл. почта — в меню колонок, не убрана.")
        for name in ("city", "state_id", "country_id", "team_id", "probability",
                     "campaign_id", "medium_id", "source_id", "tag_ids",
                     "activity_ids", "activity_user_id", "my_activity_date_deadline"):
            with self.subTest(field=name):
                self.assertTrue(invisible_column(self._one(arch, name)),
                                "Убрана из меню колонок, узел на месте.")
        for xmlid in ("crm.action_lead_mass_mail", "crm.action_lead_mail_compose"):
            with self.subTest(button=xmlid):
                buttons = arch.xpath("//button[@name='%s']" % self.env.ref(xmlid).id)
                self.assertTrue(buttons, "Кнопка скрыта, а не удалена.")
                for button in buttons:
                    self.assertIn(button.get("invisible"), HIDDEN)

    def test_my_activities_keep_task_columns(self):
        """«Мои задачи» — тот же список, но про задачи: колонки задач там в ⚙."""
        arch = self._arch("crm.crm_lead_view_list_activities")
        for name in ("activity_ids", "activity_user_id", "my_activity_date_deadline"):
            with self.subTest(field=name):
                node = self._one(arch, name)
                self.assertFalse(invisible_column(node))
                self.assertEqual(node.get("optional"), "hide")

    def test_reporting_lists_still_build(self):
        """Анализ воронки и прогноз строятся из списка сделок своими xpath'ами."""
        for xmlid in ("crm.crm_lead_view_tree_opportunity_reporting",
                      "crm.crm_lead_view_tree_forecast",
                      "crm.crm_lead_view_tree_reporting"):
            with self.subTest(view=xmlid):
                self._arch(xmlid)

    def test_lead_list(self):
        arch = self._arch("crm.crm_case_tree_view_leads")
        names = [f.get("name") for f in arch.xpath("/list/field")]
        self.assertEqual(names[names.index("name") + 1], "pmk_received",
                         "«Получен» — сразу за названием лида.")
        received = self._one(arch, "pmk_received")
        self.assertEqual(received.get("widget"), "date")
        self.assertEqual(received.get("optional"), "show")
        self.assertEqual(self.env["crm.lead"].fields_get(["pmk_received"])["pmk_received"]["string"],
                         "Получен")
        # Штатная «Дата создания» — на своём месте в ⚙, без чужой подписи.
        created = self._one(arch, "create_date")
        self.assertEqual(created.get("optional"), "hide")
        self.assertIsNone(created.get("string"))
        self.assertLess(names.index("create_date"), names.index("name"))
        for name in ("city", "country_id", "team_id"):
            with self.subTest(field=name):
                self.assertEqual(self._one(arch, name).get("optional"), "hide")
        self.assertEqual(self._one(arch, "pmk_source").get("optional"), "hide")
        visible = [f.get("name") for f in arch.xpath("/list/field") if shown(f)]
        expected = ["name", "pmk_received", "email_from", "user_id"]
        self.assertEqual([n for n in visible if n in expected], expected)
        for name in ("city", "country_id", "team_id"):
            self.assertNotIn(name, visible)


@tagged("post_install", "-at_install")
class TestDealMarginWeightFields(TransactionCase):
    """Маржа и вес в списке — окно в главный расчёт, а не копия."""

    def test_related_to_main_spec(self):
        partner = self.env["res.partner"].create({"name": "ООО «Тест 25»", "is_company": True})
        deal = self.env["crm.lead"].create({
            "name": "Ангар (тест 25)", "type": "opportunity", "partner_id": partner.id})
        self.assertFalse(deal.pmk_spec_id)
        self.assertEqual(deal.pmk_weight_t, 0.0)
        spec = self.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True).create({
                "partner_id": partner.id, "opportunity_id": deal.id})
        deal.invalidate_recordset()
        self.assertEqual(deal.pmk_spec_id, spec)
        self.assertEqual(deal.pmk_margin_pct, spec.margin_pct)
        self.assertEqual(deal.pmk_weight_t, spec.total_weight_t)
        self.assertEqual(deal.pmk_no_price_count, spec.no_price_count)
        self.assertEqual(deal.pmk_price_incomplete, spec.price_incomplete)
        for name in ("pmk_margin_pct", "pmk_weight_t", "pmk_no_price_count",
                     "pmk_price_incomplete"):
            with self.subTest(field=name):
                self.assertFalse(deal._fields[name].store, "Не хранится — не копия.")

    def test_margin_base_is_spec_price(self):
        """Сделка без расчёта, но со вписанной ценой: база полоски — 0,
        полоска даёт прочерк, а не «0,0 %» как плохую маржу."""
        deal = self.env["crm.lead"].create({
            "name": "Без расчёта (тест 25)", "type": "opportunity"})
        deal.expected_revenue = 500000.0
        self.assertFalse(deal.pmk_spec_id)
        self.assertEqual(deal.expected_revenue, 500000.0, "Цену в строке вписать можно.")
        self.assertEqual(deal.pmk_spec_price, 0.0)
        self.assertEqual(deal.pmk_margin_pct, 0.0)
        field = deal._fields["pmk_spec_price"]
        self.assertFalse(field.store, "Не хранится — окно в расчёт.")
        self.assertEqual(field.related, "pmk_spec_id.price_customer_total")


@tagged("post_install", "-at_install")
class TestLeadReceived(TransactionCase):
    """«Получен» у лида — когда клиент написал, а не когда завели лид."""

    def test_manual_lead_is_create_date(self):
        lead = self.env["crm.lead"].create({"name": "Звонок (тест 25)", "type": "lead"})
        self.assertEqual(lead.pmk_received, lead.create_date)

    def test_given_date_kept(self):
        letter = fields.Datetime.now() - timedelta(days=4)
        lead = self.env["crm.lead"].create({
            "name": "Письмо (тест 25)", "type": "lead", "pmk_received": letter})
        self.assertEqual(lead.pmk_received, letter)
        lead.write({"name": "Письмо, переименовано (тест 25)"})
        self.assertEqual(lead.pmk_received, letter, "Считается один раз, правки не сдвигают.")

    def test_backfill_from_first_email(self):
        """Как при установке поля на боевой: лиды до шага 25 получают дату
        самого раннего входящего письма в чате (лид 4: письмо 16.09, лид
        заведён 20.09)."""
        lead = self.env["crm.lead"].create({"name": "Старый лид (тест 25)", "type": "lead"})
        early = fields.Datetime.now() - timedelta(days=4)
        later = fields.Datetime.now() - timedelta(days=2)
        lead.message_post(body="Второе письмо", message_type="email", date=later,
                          subtype_xmlid="mail.mt_comment")
        lead.message_post(body="Первое письмо", message_type="email", date=early,
                          subtype_xmlid="mail.mt_comment")
        lead.message_post(body="Заметка раньше всех", message_type="comment",
                          date=early - timedelta(days=1), subtype_xmlid="mail.mt_note")
        self.env.add_to_compute(lead._fields["pmk_received"], lead)
        self.assertEqual(lead.pmk_received, early,
                         "Самое раннее входящее письмо; заметки не считаются.")

    def test_merge_keeps_earliest(self):
        early = fields.Datetime.now() - timedelta(days=5)
        late = fields.Datetime.now() - timedelta(days=1)
        first = self.env["crm.lead"].create({
            "name": "Заявка 1 (тест 25)", "type": "lead", "pmk_received": late,
            "email_from": "same@example.org"})
        second = self.env["crm.lead"].create({
            "name": "Заявка 2 (тест 25)", "type": "lead", "pmk_received": early,
            "email_from": "same@example.org"})
        merged = (first | second).merge_opportunity(auto_unlink=False)
        self.assertEqual(merged.pmk_received, early)
