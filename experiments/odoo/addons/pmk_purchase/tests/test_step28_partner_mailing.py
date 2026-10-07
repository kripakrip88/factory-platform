# -*- coding: utf-8 -*-
"""Карточка поставщика и «Рассылка прайсов» — разбор UX, шаг 28 (01.10.2026).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo (см. __init__.py).
Разметка — собранная, как её получает браузер (get_views). Глазами это не
заменяет: вертикаль полей, подписи в одну строку и строку «Очередь» смотрит
основной агент в браузере на копии.
"""
import pytz

from lxml import etree

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

TZ = "Asia/Vladivostok"


def classes(node):
    return (node.get("class") or "").split()


@tagged("post_install", "-at_install")
class TestPartnerTradeStep28(TransactionCase):

    # Поля, которые форма спрашивает у onchange (как веб-клиент: признак
    # pmk_is_supplier ядро добавляет в вид само — он стоит в invisible).
    SPEC = {name: {} for name in ("name", "is_company", "parent_id", "supplier_rank",
                                  "pmk_price_supplier", "pmk_is_supplier")}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [Command.link(cls.env.ref(xmlid).id) for xmlid in (
            "purchase.group_purchase_manager",
            "sales_team.group_sale_salesman",
            "account.group_account_invoice",
        )]})
        Partner = cls.env["res.partner"]
        cls.client = Partner.create({"name": "ООО «Клиент 28»", "is_company": True})
        cls.supplier = Partner.create({"name": "ООО «Поставщик 28»", "is_company": True,
                                       "supplier_rank": 1})
        cls.price_supplier = Partner.create({"name": "ООО «Прайс 28»", "is_company": True,
                                             "pmk_price_supplier": True})
        cls.user_partner = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Сотрудник (тест 28)", "login": "pmk28_staff",
        }).partner_id
        cls.own_company = cls.env.company.partner_id
        # Контактные лица. Ранг и «Поставщик прайсов» стоят только на
        # компании — человеку они не передаются.
        cls.supplier_person = Partner.create({"name": "Менеджер поставщика 28",
                                              "parent_id": cls.supplier.id})
        cls.price_person = Partner.create({"name": "Менеджер прайса 28",
                                           "parent_id": cls.price_supplier.id})
        cls.client_person = Partner.create({"name": "Инженер клиента 28",
                                            "parent_id": cls.client.id})

    def _form(self):
        view_id = self.env.ref("base.view_partner_form").id
        views = self.env["res.partner"].with_user(self.admin).get_views([(view_id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def _search_domain(self, name):
        search = etree.fromstring(self.env["res.partner"].get_views(
            [(self.env.ref("base.view_res_partner_filter").id, "search")]
        )["views"]["search"]["arch"])
        return safe_eval(self._one(search, "//filter[@name='%s']" % name).get("domain"))

    def _one(self, arch, xpath):
        nodes = arch.xpath(xpath)
        self.assertEqual(len(nodes), 1, xpath)
        return nodes[0]

    @staticmethod
    def _values(partner):
        """Значения полей, как их видят выражения invisible в браузере."""
        return {
            "pmk_is_supplier": partner.pmk_is_supplier,
            "pmk_price_supplier": partner.pmk_price_supplier,
            "supplier_rank": partner.supplier_rank,
            "user_ids": partner.user_ids.ids,
            "ref_company_ids": partner.ref_company_ids.ids,
            "parent_id": partner.parent_id.id or False,
            "is_company": partner.is_company,
            "pmk_spec_count": 0,
        }

    CARD = {
        "sale": "//group[@name='sale']",
        "purchase": "//group[@name='purchase']",
        "switch": "//group[@name='pmk_price_switch']",
        "purchase_flag": "//group[@name='purchase']/field[@name='pmk_price_supplier']",
        "page": "//page[@name='sales_purchases']",
    }

    def _card(self, partner, arch=None):
        """Что видно на «Продажах и закупках»: {узел: виден ли}."""
        arch = self._form() if arch is None else arch
        values = self._values(partner)
        return {key: not safe_eval(self._one(arch, xpath).get("invisible") or "False", values)
                for key, xpath in self.CARD.items()}

    # ─── Блоки «Продажи» и «Закупка» по типу ────────────────────────────
    def test_blocks_follow_customer_filter(self):
        """«Продажи» — ровно у тех, кого показывает фильтр «Клиенты» (шаг 9),
        «Закупка» — у тех, кого показывает фильтр «Поставщики»."""
        arch = self._form()
        customers = self._search_domain("pmk_customers")
        suppliers = self._search_domain("supplier")
        Partner = self.env["res.partner"]
        for partner in (self.client, self.supplier, self.price_supplier,
                        self.user_partner, self.own_company):
            is_customer = bool(Partner.search([("id", "=", partner.id)] + customers))
            is_supplier = bool(Partner.search([("id", "=", partner.id)] + suppliers))
            card = self._card(partner, arch)
            with self.subTest(partner=partner.name):
                self.assertEqual(partner.pmk_is_supplier, is_supplier)
                self.assertEqual(card["sale"], is_customer)
                self.assertEqual(card["switch"], is_customer,
                                 "Строка «Поставщик прайсов» — там, где нет «Закупки».")
                self.assertEqual(card["purchase"], is_supplier)
        self.assertFalse(self._card(self.user_partner, arch)["page"])
        self.assertFalse(self._card(self.own_company, arch)["page"])
        self.assertTrue(self._card(self.client, arch)["page"])
        self.assertTrue(self._card(self.price_supplier, arch)["page"])

    def test_contact_person_follows_company(self):
        """Контактное лицо — сторона своей компании (находка проверки шага
        28): у человека поставщика «Закупка» без флажка, у человека клиента
        «Продажи» без строки «Поставщик прайсов»."""
        arch = self._form()
        for person in (self.supplier_person, self.price_person):
            card = self._card(person, arch)
            with self.subTest(person=person.name):
                self.assertFalse(person.supplier_rank, "Ранг человеку не передаётся.")
                self.assertFalse(person.pmk_price_supplier)
                self.assertTrue(person.pmk_is_supplier, "Поставщик — по своей компании.")
                self.assertFalse(card["sale"], "У человека поставщика нет «Продаж».")
                self.assertTrue(card["purchase"])
                self.assertFalse(card["switch"])
                self.assertFalse(card["purchase_flag"],
                                 "Человека не отметить поставщиком прайсов отдельно от компании.")
        card = self._card(self.client_person, arch)
        self.assertFalse(self.client_person.pmk_is_supplier)
        self.assertTrue(card["sale"])
        self.assertFalse(card["purchase"])
        self.assertFalse(card["switch"], "У контактного лица строки «Поставщик прайсов» нет.")
        # Флажок, уже стоящий у человека, виден — чтобы его можно было снять.
        flagged = self.env["res.partner"].create({"name": "Отмеченный человек 28",
                                                  "parent_id": self.client.id,
                                                  "pmk_price_supplier": True})
        card = self._card(flagged, arch)
        self.assertTrue(card["purchase"])
        self.assertTrue(card["purchase_flag"])

    def test_switch_and_rating(self):
        arch = self._form()
        switch = self._one(arch, "//group[@name='pmk_price_switch']//field[@name='pmk_price_supplier']")
        self.assertIsNotNone(switch)
        purchase = self._one(arch, "//group[@name='purchase']")
        names = [node.get("name") for node in purchase.xpath("./field")]
        self.assertIn("pmk_supplier_rank", names,
                      "Рейтинг — в «Закупке»: на «Основной информации» организаций его не видно.")
        self.assertLess(names.index("pmk_supplier_rank"), names.index("pmk_price_supplier"))
        self.assertEqual(len(arch.xpath("//field[@name='pmk_supplier_rank']")), 1)

    def test_labels(self):
        arch = self._form()
        self.assertEqual(self._one(arch, "//group[@name='sale']/field[@name='user_id']")
                         .get("string"), "Менеджер")
        # «Снабженец» с шага 53 — до востребования (pmk_theme, группа
        # «Убранное (показать)»): подпись проверяем с группой, без неё узла нет.
        removed = self.env.ref("pmk_theme.group_pmk_removed", raise_if_not_found=False)
        if removed and removed not in self.admin.all_group_ids:
            self.assertFalse(arch.xpath("//group[@name='purchase']/field[@name='buyer_id']"))
            self.admin.write({"group_ids": [Command.link(removed.id)]})
            buyer_arch = self._form()
        else:
            buyer_arch = arch
        self.assertEqual(self._one(buyer_arch, "//group[@name='purchase']/field[@name='buyer_id']")
                         .get("string"), "Снабженец")
        # Шаг 37 (проверка): «Адрес» и «Раз в, дн» — те же слова, что в
        # списке «Поставщиков прайсов» (было «Адрес для прайса», «Период,
        # дней»; pmk_purchase/views/step37_price_supplier.xml).
        short = {"pmk_has_stock": "Склад на ДВ", "pmk_price_email": "Адрес",
                 "pmk_price_period_days": "Раз в, дн",
                 "pmk_price_request_date": "Запрос отправлен", "pmk_price_last_date": "Прайс от"}
        for name, label in short.items():
            with self.subTest(field=name):
                node = self._one(arch, "//group[@name='pmk_price']//field[@name='%s']" % name)
                self.assertEqual(node.get("string"), label)
        for xpath in ("//page[@name='sales_purchases']/group[@name='container_row_2']",
                      "//group[@name='pmk_price']", "//group[@name='pmk_price_switch']"):
            with self.subTest(group=xpath):
                group_classes = classes(self._one(arch, xpath))
                self.assertIn("o_pmk_labels_line", group_classes)
                self.assertIn("o_pmk_labels_even", group_classes)

    # ─── «Поставщик прайсов» обратим ────────────────────────────────────
    def test_price_supplier_flag_is_reversible(self):
        """Находка проверки шага 28: флажок поднимал supplier_rank, и снятый
        флажок клиента уже не возвращал. Теперь штатный ранг флажок не трогает,
        а признак «поставщик» вычисляемый: снял — снова клиент."""
        Partner = self.env["res.partner"]
        customers = self._search_domain("pmk_customers")
        client = Partner.create({"name": "ООО «Клиент на время 28»", "is_company": True})

        def in_customers():
            return bool(Partner.search([("id", "=", client.id)] + customers))

        def blocks():
            card = self._card(client)
            return card["sale"], card["purchase"], card["switch"]

        self.assertTrue(in_customers())
        client.pmk_price_supplier = True
        self.assertEqual(client.supplier_rank, 0, "Штатный ранг флажок не трогает.")
        self.assertTrue(client.pmk_is_supplier)
        self.assertFalse(in_customers())
        self.assertEqual(blocks(), (False, True, False), "Карточка поставщика.")

        client.pmk_price_supplier = False
        self.assertEqual(client.supplier_rank, 0)
        self.assertFalse(client.pmk_is_supplier)
        self.assertTrue(in_customers(), "Снял флажок — снова в «Продажи → Клиенты».")
        self.assertEqual(blocks(), (True, False, True), "И снова карточка клиента.")

        # Поставщик по заказам и счетам остаётся поставщиком и без флажка.
        ranked = Partner.create({"name": "ООО «Давний 28»", "is_company": True,
                                 "supplier_rank": 5})
        ranked.pmk_price_supplier = True
        ranked.pmk_price_supplier = False
        self.assertEqual(ranked.supplier_rank, 5)
        self.assertTrue(ranked.pmk_is_supplier)

    def test_sign_before_save(self):
        """Признак пересчитывается в открытой карточке, до сохранения
        (находка проверки шага 28: новый поставщик прайсов показывал
        «Расчёты 0» и считался бы клиентом, пока не сохранён)."""
        Partner = self.env["res.partner"]
        # «Закупки → Поставщики прайсов → Новое»: контекст действия меню.
        context = safe_eval(self.env.ref("pmk_purchase.action_price_supplier").context)
        values = Partner.with_context(**context).onchange({}, [], dict(self.SPEC))["value"]
        self.assertTrue(values["pmk_price_supplier"])
        self.assertFalse(values["supplier_rank"], "Штатный ранг даст только сохранение.")
        self.assertTrue(values["pmk_is_supplier"])
        # Клиенту отметили «Поставщик прайсов» — карточка поставщика сразу.
        client = Partner.create({"name": "ООО «Клиент с флажком 28»", "is_company": True})
        changed = client.onchange({"pmk_price_supplier": True}, ["pmk_price_supplier"],
                                  dict(self.SPEC))["value"]
        self.assertTrue(changed["pmk_is_supplier"])
        self.assertFalse(client.pmk_is_supplier, "В базе ничего не поменялось.")

    def test_specs_button_follows_sign(self):
        """«Расчёты» (pmk_deal) смотрит на тот же признак, что и блоки."""
        arch = self._form()
        buttons = arch.xpath("//button[@name='action_pmk_view_specs']")
        if not buttons:
            self.skipTest("Кнопку «Расчёты» объявляет pmk_deal — он не установлен.")
        expression = buttons[0].get("invisible")
        cases = (
            (self.client, False), (self.client_person, False),
            (self.supplier, True), (self.price_supplier, True),
            (self.supplier_person, True), (self.price_person, True),
        )
        for partner, hidden in cases:
            with self.subTest(partner=partner.name):
                self.assertEqual(bool(safe_eval(expression, self._values(partner))), hidden,
                                 "Ноль: у клиента виден, у поставщика и его людей — нет.")

    def test_views_active(self):
        for xmlid in ("pmk_purchase.view_partner_form_price",
                      "pmk_purchase.view_partner_form_trade_by_type"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)


@tagged("post_install", "-at_install")
class TestPriceMailingFormStep28(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mailing = cls.env["pmk.price.mailing"].create({})
        cls.cron = cls.env.ref("pmk_purchase.cron_price_request")

    def _arch(self):
        view_id = self.env.ref("pmk_purchase.view_price_mailing_form").id
        views = self.env["pmk.price.mailing"].get_views([(view_id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_form(self):
        arch = self._arch()
        for attr in ("create", "delete", "duplicate"):
            with self.subTest(attr=attr):
                self.assertEqual(arch.get(attr), "0", "Запись у рассылки одна.")
        filled = [b.get("name") for b in arch.iter("button")
                  if {"btn-primary", "oe_highlight"} & set(classes(b))]
        self.assertEqual(filled, ["action_run_now"], "Одна залитая кнопка на экран.")
        self.assertFalse(arch.xpath("//field[@name='hour']"), "Вместо «Час» — «Время».")
        self.assertFalse(arch.xpath("//field[@name='minute']"), "Вместо «Минута» — «Время».")
        time = arch.xpath("//field[@name='send_time']")
        self.assertEqual(len(time), 1)
        self.assertEqual(time[0].get("widget"), "float_time")
        # «Открыть очередь» — в одной строке с числом.
        row = arch.xpath("//button[@name='action_open_queue']/..")[0]
        self.assertIn("o_row", classes(row))
        count = row.xpath("./field[@name='queue_count']")
        self.assertTrue(count)
        # Число не растягивается на строку — кнопка стоит сразу за ним
        # (forms_nexus.scss, раздел 8, pmk-row-value; осмотр копии 02.10).
        self.assertIn("pmk-row-value", classes(count[0]))
        self.assertTrue(arch.xpath("//label[@for='queue_count']"))
        for group in arch.xpath("//sheet/group"):
            with self.subTest(group=group.get("string")):
                self.assertIn("o_pmk_labels_line", classes(group))

    def test_send_time_round_trip(self):
        mailing = self.mailing
        mailing.write({"hour": 9, "minute": 10})
        self.assertAlmostEqual(mailing.send_time, 9 + 10 / 60, places=4)

        mailing.send_time = 14.5
        self.assertEqual((mailing.hour, mailing.minute), (14, 30))
        local = pytz.UTC.localize(self.cron.nextcall).astimezone(pytz.timezone(TZ))
        self.assertEqual((local.hour, local.minute), (14, 30),
                         "Время ушло в расписание задания, как раньше час и минута.")
        self.assertEqual(local.weekday(), int(mailing.weekday))

        # 09:10 из виджета — дробь 9,1666…: округляем до минуты, а не вниз.
        mailing.send_time = 9 + 10 / 60 - 1e-9
        self.assertEqual((mailing.hour, mailing.minute), (9, 10))

        for wrong in (24.0, -0.5):
            with self.subTest(value=wrong), self.assertRaises(UserError):
                mailing.write({"send_time": wrong})

    def test_cron_fields_kept(self):
        """Час и минута остались в модели — из них собирается расписание."""
        for name in ("hour", "minute"):
            self.assertIn(name, self.mailing._fields)
        self.mailing.invalidate_recordset()
        self.mailing._pull_from_system()
        local = pytz.UTC.localize(self.cron.nextcall).astimezone(pytz.timezone(TZ))
        self.assertEqual((self.mailing.hour, self.mailing.minute), (local.hour, local.minute))
        self.assertAlmostEqual(self.mailing.send_time, local.hour + local.minute / 60, places=4)
