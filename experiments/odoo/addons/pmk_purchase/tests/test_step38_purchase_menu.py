# -*- coding: utf-8 -*-
"""Закупки: рабочие пункты и номенклатура — разбор UX, шаг 38.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py).

Что ловим:
  • порядок у закупщика и у администратора: Поставщики · Почта · Цены поставщиков ·
    Номенклатура · Рассылка прайсов · Заказы поставщикам · Группы поставки;
    раздел открывается «Поставщиками»;
  • «Поставщики» — список и поиск реестра прайсов, окно так и называется;
    штатный список — «Все поставщики», только с «Убранным»;
  • доводка: в «Поставщиках» все поставщики — реестр и штатный признак.
    Поставщик, заведённый из заказа поставщику (контекст
    res_partner_search_mode = 'supplier': supplier_rank = 1, флажка реестра
    нет), там есть; его контактное лицо со штатным признаком — нет; клиент —
    нет. Фильтры «В реестре прайсов» / «Не в реестре прайсов»; у строки не
    из реестра пусто «Раз в, дн»; окна «Рассылки прайсов» — только реестр и
    со своим заголовком (display_name);
  • «Заказы поставщикам» — общий список запросов КП и заказов (действие
    «Запросов КП», с панелью; окно — «Заказы поставщикам»); список только
    подтверждённых — «Подтверждённые заказы», только с «Убранным»; те же
    строки в общем списке — фильтр «Заказы на покупку»; доводка: у
    подтверждённого заказа там видно «Ожидаемое прибытие», «Дата
    подтверждения» — в ⚙; почта — с шага 53 и в Закупках (вторым пунктом);
  • «Номенклатура» достижима без «Склада»;
  • подсказки пустых экранов ведут в существующие пункты.
"""
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.pmk_purchase.models.ir_actions_act_window import EMPTY_HELP

REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"
ITEMS = ["Поставщики", "Цены поставщиков", "Номенклатура", "Рассылка прайсов",
         "Заказы поставщикам", "Группы поставки"]


@tagged("post_install", "-at_install")
class TestPurchaseMenuStep38(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("purchase.group_purchase_manager").id),
            Command.unlink(cls.env.ref(REMOVED).id),
            Command.unlink(cls.env.ref(STOCK).id)]})
        cls.buyer = new_test_user(cls.env, login="pmk38_buyer",
                                  groups="base.group_user,purchase.group_purchase_user")
        cls.section = cls.env.ref("pmk_theme.menu_pmk_purchase")

    def _menus(self, user):
        return self.env["ir.ui.menu"].with_user(user).load_web_menus(False)

    def _items(self, user):
        menus = self._menus(user)
        return [menus[mid]["name"] for mid in menus[self.section.id]["children"]]

    def _item(self, user, name):
        menus = self._menus(user)
        found = [menus[mid] for mid in menus[self.section.id]["children"]
                 if menus[mid]["name"] == name]
        self.assertEqual(len(found), 1, name)
        return found[0]

    def _expected_items(self):
        """ITEMS и «Почта» вторым пунктом: с шага 53 она снова у всех
        (pmk_mail_ui, если стоит)."""
        items = list(ITEMS)
        if self.env.ref("pmk_mail_ui.menu_mail_purchase", raise_if_not_found=False):
            items.insert(1, "Почта")
        # Шаг З-4 (pmk_tech, если стоит): «Заявки на металл» — перед
        # «Заказами поставщикам».
        if self.env.ref("pmk_tech.menu_metal_requests", raise_if_not_found=False):
            items.insert(items.index("Заказы поставщикам"), "Заявки на металл")
        return items

    def test_items_and_order(self):
        for user in (self.buyer, self.admin):
            with self.subTest(user=user.login):
                self.assertEqual(self._items(user), self._expected_items())

    def test_section_opens_suppliers(self):
        for user in (self.buyer, self.admin):
            with self.subTest(user=user.login):
                menus = self._menus(user)
                self.assertEqual(menus[self.section.id]["actionID"],
                                 self.env.ref("pmk_purchase.action_price_supplier").id)

    def test_suppliers_is_price_registry(self):
        action = self.env.ref("pmk_purchase.action_price_supplier")
        self.assertEqual(self._item(self.buyer, "Поставщики")["actionID"], action.id)
        loaded = self.env["ir.actions.act_window"]._for_xml_id("pmk_purchase.action_price_supplier")
        self.assertEqual(loaded["name"], "Поставщики", "Окно — как пункт.")
        self.assertIn("pmk_price_supplier", loaded["domain"])
        self.assertIn("supplier_rank", loaded["domain"], "И штатный признак (доводка шага 38).")
        self.assertEqual(loaded["search_view_id"][0],
                         self.env.ref("pmk_purchase.view_price_supplier_search").id,
                         "Поиск реестра: «Пора запросить прайс», «Прайса ещё не было».")

    # ─── Доводка: в «Поставщиках» все поставщики ────────────────────────
    def _suppliers_case(self):
        """Реестр, поставщик из заказа поставщику, его контактное лицо со
        штатным признаком и клиент."""
        Partner = self.env["res.partner"]
        registry = Partner.create({"name": "Реестр прайсов (тест 38)", "is_company": True,
                                   "pmk_price_supplier": True})
        # Как «Создать» в поле «Поставщик» заказа поставщику и строки цены:
        # name_create в контексте поля (purchase_views.xml,
        # product_supplierinfo_views.xml).
        from_order = Partner.browse(Partner.with_context(
            res_partner_search_mode="supplier").name_create("ООО Металлторг (тест 38)")[0])
        # Контактное лицо со штатным признаком: так бывает после счёта
        # поставщика на человека (ранг растёт у него и у компании) или если
        # человека завели в карточке, открытой из списка поставщиков.
        person = Partner.create({"name": "Иван из Металлторга (тест 38)",
                                 "parent_id": from_order.id, "supplier_rank": 1})
        client = Partner.create({"name": "ООО Клиент (тест 38)", "is_company": True})
        return registry, from_order, person, client

    def _found(self, domain, partners):
        return self.env["res.partner"].search(list(domain) + [("id", "in", partners.ids)])

    def test_suppliers_list_has_every_supplier(self):
        registry, from_order, person, client = self._suppliers_case()
        self.assertEqual((from_order.supplier_rank, from_order.pmk_price_supplier), (1, False),
                         "Посылка находки: ядро ставит штатный признак, реестр пуст.")
        domain = safe_eval(self.env.ref("pmk_purchase.action_price_supplier").domain)
        self.assertEqual(self._found(domain, registry | from_order | person | client),
                         registry | from_order,
                         "Поставщик из заказа — в «Поставщиках»; контактное лицо — в карточке "
                         "своей компании; клиент — в «Клиентах».")
        # И в «Клиентах» его нет — значит, «Поставщики» единственный видимый список.
        customers = [("supplier_rank", "=", 0), ("pmk_price_supplier", "=", False)]
        self.assertFalse(self._found(customers, from_order))

    def test_registry_filters(self):
        registry, from_order, person, client = self._suppliers_case()
        domain = safe_eval(self.env.ref("pmk_purchase.action_price_supplier").domain)
        arch = etree.fromstring(self.env["res.partner"].get_view(
            self.env.ref("pmk_purchase.view_price_supplier_search").id, "search")["arch"])
        expected = {"in_registry": registry, "not_in_registry": from_order}
        everyone = registry | from_order | person | client
        for name, partners in expected.items():
            with self.subTest(filter=name):
                node = arch.xpath("//filter[@name='%s']" % name)
                self.assertEqual(len(node), 1)
                self.assertEqual(self._found(domain + safe_eval(node[0].get("domain")), everyone),
                                 partners)
        self.assertFalse(safe_eval(self.env.ref("pmk_purchase.action_price_supplier").context)
                         .get("search_default_in_registry"),
                         "Фильтра по умолчанию нет: поставщик из заказа виден сразу.")

    def test_period_empty_outside_registry(self):
        arch = etree.fromstring(self.env["res.partner"].get_view(
            self.env.ref("pmk_purchase.view_price_supplier_list").id, "list")["arch"])
        for name in ("pmk_price_period_days", "pmk_price_mailing"):
            with self.subTest(field=name):
                node = arch.xpath("/list/field[@name='%s']" % name)
                self.assertEqual(len(node), 1)
                self.assertEqual(node[0].get("invisible"), "not pmk_price_supplier")
                self.assertFalse(node[0].get("column_invisible"),
                                 "Ячейка, не колонка (column_invisible режет загрузку).")

    def test_mailing_windows_registry_only(self):
        registry, from_order, _person, _client = self._suppliers_case()
        mailing = self.env["pmk.price.mailing"].create({})
        cases = ((mailing.action_choose_recipients(), "Выберите получателей рассылки", False),
                 (mailing.action_open_recipients(), "Получатели рассылки", True))
        for action, title, in_mailing in cases:
            with self.subTest(title=title):
                self.assertEqual(action["name"], title)
                self.assertEqual(action["display_name"], title,
                                 "Клиент берёт display_name раньше name.")
                self.assertEqual(action["id"], self.env.ref("pmk_purchase.action_price_supplier").id)
                self.assertEqual(self._found(action["domain"], registry | from_order), registry,
                                 "Рассылка пишет только реестру — отмечать там некого.")
                self.assertEqual(bool(action["context"].get("search_default_in_mailing")),
                                 in_mailing)
                self.assertTrue(action["context"].get("default_pmk_price_supplier"))

    # ─── Доводка: даты подтверждённого заказа в общем списке ────────────
    def test_confirmed_order_dates_in_one_list(self):
        rfq = self.env.ref("purchase.purchase_rfq")
        self.assertTrue(safe_eval(rfq.context).get("quotation_only"),
                        "Посылка: общий список — в контексте запросов КП.")
        views = self.env["purchase.order"].with_user(self.buyer).with_context(
            quotation_only=True).get_views([(rfq.view_id.id, "list")])
        arch = etree.fromstring(views["views"]["list"]["arch"])
        names = [node.get("name") for node in arch.xpath("/list/field")]
        expected = {"date_planned": "show", "date_approve": "hide"}
        for name, optional in expected.items():
            with self.subTest(field=name):
                node = arch.xpath("/list/field[@name='%s']" % name)
                self.assertEqual(len(node), 1)
                self.assertFalse(node[0].get("column_invisible"),
                                 "Колонка есть и в общем списке (ядро прятало её целиком).")
                self.assertEqual(node[0].get("invisible"), "state != 'purchase'",
                                 "Дата — только у подтверждённого заказа.")
                self.assertEqual(node[0].get("optional"), optional)
                self.assertFalse(safe_eval(node[0].get("options")).get("show_time"))
        self.assertEqual(names.index("date_planned") + 1, names.index("date_order"),
                         "Прибытие рядом с «Крайним сроком»: у строки дата своей стадии.")
        self.assertTrue(self.env.ref("pmk_purchase.view_purchase_order_kpis_tree_step38").active)

    def test_orders_is_one_list(self):
        item = self._item(self.buyer, "Заказы поставщикам")
        rfq = self.env.ref("purchase.purchase_rfq")
        self.assertEqual(item["actionID"], rfq.id)
        self.assertEqual(item["actionPath"], rfq.path)
        loaded = self.env["ir.actions.act_window"]._for_xml_id("purchase.purchase_rfq")
        self.assertIn(loaded.get("domain"), (False, None, "[]", []),
                      "Все стадии: запросы КП и заказы.")
        self.assertEqual(loaded["views"][0][0], self.env.ref("purchase.purchase_order_kpis_tree").id,
                         "Список с панелью показателей, как у «Запросов КП».")
        self.assertEqual(loaded["name"], "Заказы поставщикам", "Окно — как пункт (ACTION_TITLES).")
        self.assertNotIn("search_default", str(loaded.get("context")),
                         "Фильтров по умолчанию нет — как было у «Запросов КП».")

    def test_confirmed_orders_filter_in_one_list(self):
        """Подтверждённые заказы — фильтр «Заказы на покупку» общего списка
        (тот же домен, что у спрятанного пункта)."""
        rfq = self.env.ref("purchase.purchase_rfq")
        views = self.env["purchase.order"].with_user(self.buyer).get_views(
            [(rfq.search_view_id.id, "search")])
        arch = etree.fromstring(views["views"]["search"]["arch"])
        approved = arch.xpath("//filter[@name='approved']")
        self.assertEqual(len(approved), 1)
        self.assertIn("'purchase'", approved[0].get("domain"))
        self.assertIn("'purchase'", self.env.ref("purchase.purchase_form_action").domain)

    def test_nomenclature_without_stock(self):
        item = self._item(self.buyer, "Номенклатура")
        self.assertEqual(item["actionID"], self.env.ref("stock.product_template_action_product").id)
        self.assertFalse(self.buyer.has_group(STOCK))
        loaded = self.env["ir.actions.act_window"]._for_xml_id("stock.product_template_action_product")
        self.assertEqual(loaded["name"], "Номенклатура", "Окно — как пункт, не «Товары».")
        self.assertEqual([mode for _id, mode in loaded["views"]], ["list", "form"],
                         "Виды шага 29 при действии.")

    def test_hidden_items_come_back_with_removed(self):
        self.admin.write({"group_ids": [Command.link(self.env.ref(REMOVED).id)]})
        expected = ["Поставщики", "Все поставщики", "Почта", "Цены поставщиков", "Номенклатура",
                    "Рассылка прайсов", "Заказы поставщикам", "Подтверждённые заказы",
                    "Группы поставки"]
        if not self.env.ref("pmk_mail_ui.menu_mail_purchase", raise_if_not_found=False):
            expected.remove("Почта")
        self.assertEqual(self._items(self.admin), expected)
        self.assertEqual(self._item(self.admin, "Все поставщики")["actionID"],
                         self.env.ref("account.res_partner_action_supplier").id)
        self.assertEqual(self._item(self.admin, "Подтверждённые заказы")["actionID"],
                         self.env.ref("purchase.purchase_form_action").id)
        # Раздел по-прежнему открывается «Поставщиками».
        menus = self._menus(self.admin)
        self.assertEqual(menus[self.section.id]["actionID"],
                         self.env.ref("pmk_purchase.action_price_supplier").id)

    def test_empty_help_points_to_live_items(self):
        text = "".join(EMPTY_HELP.values())
        self.assertNotIn("Поставщики прайсов", text)
        self.assertNotIn("«Закупки → Запросы КП»", text)
        self.assertIn("«Закупки → Поставщики»", text)
        self.assertIn("«Закупки → Заказы поставщикам»", text)
        names = set(self._items(self.buyer))
        for path in ("Поставщики", "Заказы поставщикам"):
            self.assertIn(path, names)
