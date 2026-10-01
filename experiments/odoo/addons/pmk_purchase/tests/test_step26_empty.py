# -*- coding: utf-8 -*-
"""Закупки: пустые экраны и списки — разбор UX, шаг 26.

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo (см. __init__.py).

Что ловим:
  • «Поставщики прайсов» открываются без группировки, группировка «Что
    возит» осталась в поиске; метки — виджетом в одну строку;
  • подсказки закупок — наши;
  • у «Запросов КП» и «Заказов поставщикам» только список и форма, хотя у
    заказов канбан привязан отдельной строкой (view_ids ядра);
  • панель «Запросов КП»: пусто — прочерк, а не «0.00» и «100 %»; есть
    заказ — число по-русски, с запятой;
  • скрипты и шаблоны шага — в бандле.

  • запрос КП из файла погашен всеми тремя путями: «Загрузить»,
    перетаскивание, вставка из буфера.

Глазами — высота строки, «+N» с подсказкой, кнопки «Загрузить» нет, файл,
брошенный в список, не создаёт запрос и не открывается в браузере — смотрит
основной агент.
"""
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open

from odoo.addons.pmk_purchase.models.ir_actions_act_window import EMPTY_HELP
from odoo.addons.pmk_purchase.models.purchase_order import DASH


@tagged("post_install", "-at_install")
class TestPurchaseEmptyStep26(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("ru_RU")
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("purchase.group_purchase_manager").id),
        ]})
        cls.Action = cls.env["ir.actions.act_window"]

    # ─── Поставщики прайсов ─────────────────────────────────────────────
    def test_price_suppliers_not_grouped(self):
        action = self.Action._for_xml_id("pmk_purchase.action_price_supplier")
        self.assertNotIn("search_default_by_supply", action["context"])
        self.assertNotIn("group_by", action["context"])
        search = self.env.ref("pmk_purchase.view_price_supplier_search")
        arch = etree.fromstring(self.env["res.partner"].get_view(search.id, "search")["arch"])
        self.assertTrue(arch.xpath("//filter[@name='by_supply']"),
                        "Группировка «Что возит» осталась в поиске.")

    def test_price_supplier_list_one_line(self):
        view = self.env.ref("pmk_purchase.view_price_supplier_list")
        arch = etree.fromstring(self.env["res.partner"].get_view(view.id, "list")["arch"])
        self.assertIn("o_pmk_price_supplier_list", arch.get("class", ""))
        tags = arch.xpath("/list/field[@name='pmk_supply_ids']")
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0].get("widget"), "pmk_tags_line")
        self.assertEqual(tags[0].get("width"), "170px")

    # ─── Подсказки ──────────────────────────────────────────────────────
    def test_help_replaced(self):
        for xmlid, text in EMPTY_HELP.items():
            for lang in ("en_US", "ru_RU"):
                with self.subTest(action=xmlid, lang=lang):
                    action = self.Action.with_context(lang=lang)._for_xml_id(xmlid)
                    self.assertEqual(action["help"], text)
                    self.assertNotIn("Odoo", text)

    # ─── Виды: список и форма ───────────────────────────────────────────
    def test_rfq_views_list_and_form(self):
        action = self.Action._for_xml_id("purchase.purchase_rfq")
        self.assertEqual([mode for _id, mode in action["views"]], ["list", "form"])
        self.assertEqual(action["view_mode"], "list,form")
        self.assertEqual(action["views"][0][0], self.env.ref("purchase.purchase_order_kpis_tree").id,
                         "Список — штатный, с панелью показателей.")

    def test_orders_views_list_and_form(self):
        """Канбан у заказов привязан строкой view_ids (без xml-id), и одного
        view_mode мало — Odoo 19 показывает привязанный вид при любом."""
        record = self.env.ref("purchase.purchase_form_action")
        self.assertIn("kanban", record.view_ids.mapped("view_mode"),
                      "Предпосылка теста: у ядра канбан привязан строкой.")
        action = self.Action._for_xml_id("purchase.purchase_form_action")
        self.assertEqual([mode for _id, mode in action["views"]], ["list", "form"])
        self.assertEqual(action["views"][0][0], self.env.ref("purchase.purchase_order_view_tree").id)
        # В базе ничего не тронуто — вернуть можно, убрав строку из VIEW_MODES.
        self.assertIn("kanban", record.view_mode)

    def test_other_purchase_action_untouched(self):
        """Соседнее действие закупок (кнопка «Покупки» у контрагента) —
        со своими видами."""
        xmlid = "purchase.act_res_partner_2_purchase_order"
        record = self.env.ref(xmlid, raise_if_not_found=False)
        if not record:
            self.skipTest(xmlid)
        action = self.Action._for_xml_id(xmlid)
        self.assertEqual(action["view_mode"], record.view_mode)

    # ─── Панель «Запросов КП» ───────────────────────────────────────────
    def _dashboard(self):
        return self.env["purchase.order"].with_user(self.admin).with_context(
            lang="ru_RU").retrieve_dashboard()

    def _no_orders(self):
        # Чистая картина в транзакции теста (откатится): заказов нет.
        self.env.cr.execute("UPDATE purchase_order SET state = 'cancel' WHERE state = 'purchase'")
        self.env["purchase.order"].invalidate_model(["state"])

    def test_dashboard_empty_is_dash(self):
        self._no_orders()
        data = self._dashboard()
        self.assertEqual(data["pmk_days_to_order"], {"global": DASH, "my": DASH})
        if "otd" in data["global"]:
            self.assertEqual(data["global"]["otd"], DASH, "Не «100 %» при нуле поставок.")
            self.assertEqual(data["my"]["otd"], DASH)
        # Сырое значение ядра осталось: по нему шаблон красит карточку.
        self.assertIn("days_to_order", data["global"])

    def test_dashboard_with_order_russian_number(self):
        self._no_orders()
        partner = self.env["res.partner"].create({"name": "Поставщик (тест 26)"})
        product = self.env["product.product"].create({"name": "Лист (тест 26)", "type": "consu"})
        order = self.env["purchase.order"].with_user(self.admin).create({
            "partner_id": partner.id,
            "user_id": self.admin.id,
            "order_line": [Command.create({
                "product_id": product.id, "product_qty": 1, "price_unit": 100,
            })],
        })
        order.button_confirm()
        self.assertEqual(order.state, "purchase")
        data = self._dashboard()
        # Запрос подтверждён в ту же минуту — 0 дней, но заказ БЫЛ: число,
        # а не прочерк, и с запятой, а не с точкой.
        self.assertEqual(data["pmk_days_to_order"]["global"], "0,0")
        self.assertEqual(data["pmk_days_to_order"]["my"], "0,0")
        if "otd" in data["global"]:
            self.assertNotEqual(data["global"]["otd"], DASH)

    # ─── Клиентская часть ───────────────────────────────────────────────
    def test_assets_in_bundle(self):
        paths = [entry[0].lstrip("/") for entry in
                 self.env["ir.asset"]._get_asset_paths("web.assets_backend", {})]
        for name in ("js/purchase_list_upload.js", "xml/purchase_list_upload.xml",
                     "js/tags_line_field.js", "xml/tags_line_field.xml",
                     "scss/price_supplier_list.scss", "xml/purchase_dashboard.xml"):
            with self.subTest(file=name):
                self.assertIn("pmk_purchase/static/src/" + name, paths)
        # Патч импортирует контроллер списка закупок — он должен быть раньше.
        self.assertLess(paths.index("purchase/static/src/views/purchase_listview.js"),
                        paths.index("pmk_purchase/static/src/js/purchase_list_upload.js"))
        # Расширения шаблонов списка — после самих шаблонов.
        self.assertLess(paths.index("purchase/static/src/views/purchase_listview.xml"),
                        paths.index("pmk_purchase/static/src/xml/purchase_list_upload.xml"))

    def test_upload_all_paths_closed(self):
        """Запрос КП из файла — тремя путями: «Загрузить», перетаскивание,
        вставка из буфера. Все три ведут в create_document_from_attachment,
        который сам коммитит запрос КП «от» сотрудника. Гасим все три, а
        брошенный файл не должен открыться в браузере вместо системы.
        Само поведение — глазами (в контейнере нет Chrome для туров)."""
        with file_open("pmk_purchase/static/src/js/purchase_list_upload.js") as f:
            js = f.read()
        self.assertIn("this.hideUploadButton = true", js)
        self.assertIn("patch(PurchaseDashBoardRenderer.prototype", js)
        for stub in ("onDragStart() {}", "onPaste() {}", "pmkSwallowFileDrop(ev)"):
            with self.subTest(js=stub):
                self.assertIn(stub, js)
        with file_open("pmk_purchase/static/src/xml/purchase_list_upload.xml") as f:
            xml = etree.fromstring(f.read().encode())
        renderer = xml.xpath("//t[@t-inherit='purchase.ListRenderer']")
        self.assertEqual(len(renderer), 1)
        attrs = {a.get("name"): a.text for a in renderer[0].iter("attribute")}
        self.assertEqual(attrs.get("t-on-dragover"), "pmkSwallowFileDrop")
        self.assertEqual(attrs.get("t-on-drop"), "pmkSwallowFileDrop")
        self.assertTrue(xml.xpath("//t[@t-inherit='purchase.ListView']"
                                  "//attribute[@name='t-if'][text()='false']"))
