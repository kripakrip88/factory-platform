# -*- coding: utf-8 -*-
"""Запрос КП, заказ поставщику и карточка товара-металла — разбор UX, шаг 29.

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo (см. __init__.py).
Разметка — собранная, как её получает браузер (get_views: все наследники
применены, узлы чужих групп вырезаны сервером).

Что ловим:
  • виды шага живы (упавший xpath Odoo выключает при загрузке молча);
  • admin (со штатными правами продаж, закупок, склада, производства) не
    видит убранного и спрятанного до востребования, а нужное на месте:
    поставщики с ценами, «Вес», категория, артикул, «Закупка»;
  • поля, на которые ссылаются соседи (цена-по-умолчанию поставщика —
    «Стоимость», «Продажи», «Тип товара»), ядро досоздало невидимыми;
  • группы возвращают каждая свою кучку — значит, xpath бьёт в узел;
  • форма товара и запроса КП по-прежнему создаёт запись (Form — тот же
    вид и onchange, что у браузера): спрятанные обязательные поля берут
    умолчания;
  • «Номенклатура» — список и форма; в базе у действия виды прежние;
    список вариантов («Искать ещё…» у товара в строке запроса КП) — без
    тех же колонок;
  • единица товара: с «Единицами измерения» видна при любом наборе групп
    шага, свой узел — только когда штатных «за [ед.]» нет;
  • панель «Запросов КП»: флаги карточек «Не подтверждены поставщиком» и
    «Поставки в срок» — по группам; шаблон и стиль их читают.

Глазами — карточка товара на всех вкладках и запрос КП во всех состояниях
— смотрит основной агент.
"""
from lxml import etree

from odoo import Command, fields
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.misc import file_open

REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"
MONEY = "pmk_theme.group_pmk_money"
HIDDEN = ("1", "True", "true")

VIEWS = (
    "pmk_purchase.view_purchase_order_form_step29",
    "pmk_purchase.view_purchase_order_tree_step29",
    "pmk_purchase.view_purchase_order_kpis_tree_step29",
    "pmk_purchase.view_purchase_order_view_tree_step29",
    "pmk_purchase.view_purchase_order_filter_step29",
    "pmk_purchase.view_purchase_order_search_step29",
    "pmk_purchase.view_product_template_form_step29",
    "pmk_purchase.view_product_product_form_step29",
    "pmk_purchase.view_supplierinfo_list_step29",
    "pmk_purchase.view_product_template_list_step29",
    "pmk_purchase.view_product_product_list_step29",
)

# Карточка шаблона: xpath → группа, которая узел возвращает.
TEMPLATE_HIDDEN = {
    "//button[@name='action_open_documents']": REMOVED,
    "//div[@name='button_box']/button[field[@name='bom_count']]": REMOVED,
    "//button[@name='action_view_related_putaway_rules']": REMOVED,
    "//button[@name='action_view_storage_category_capacity']": REMOVED,
    "//button[@name='action_view_sales']": REMOVED,
    "//button[@name='action_product_tmpl_forecast_report']": STOCK,
    "//button[@name='action_view_orderpoints']": STOCK,
    "//button[@name='action_view_stock_move_lines']": STOCK,
    "//field[@name='is_favorite']": REMOVED,
    "//span[@name='sale_option']": REMOVED,
    "//field[@name='type']": REMOVED,
    "//field[@name='product_tooltip']": REMOVED,
    "//field[@name='invoice_policy']": REMOVED,
    "//field[@name='is_storable']": STOCK,
    "//label[@for='qty_available']": STOCK,
    "//field[@name='list_price']": REMOVED,
    "//field[@name='taxes_id']": MONEY,
    "//field[@name='standard_price']": STOCK,
    "//field[@name='barcode']": STOCK,
    "//page[@name='sales']": REMOVED,
    "//page[@name='sales_price']": REMOVED,
    "//field[@name='purchase_method']": REMOVED,
    "//field[@name='route_ids']": REMOVED,
    "//field[@name='responsible_id']": REMOVED,
    "//field[@name='volume']": REMOVED,
    "//field[@name='sale_delay']": REMOVED,
    "//field[@name='description_pickingin']": REMOVED,
    "//field[@name='description_pickingout']": REMOVED,
}
# То, ради чего карточка металла нужна, — должно остаться.
TEMPLATE_KEPT = (
    "//field[@name='name']",
    "//field[@name='purchase_ok']",
    "//field[@name='categ_id']",
    "//field[@name='default_code']",
    "//field[@name='supplier_taxes_id']",
    "//field[@name='seller_ids']",
    "//field[@name='description_purchase']",
    "//field[@name='weight']",
    "//field[@name='description']",
    "//button[@name='action_view_po']",
)


def shown(arch, expr):
    """Узлы, которые человек увидит: поля, досозданные ядром невидимыми
    (_add_missing_fields), не считаем."""
    return [node for node in arch.xpath(expr)
            if (node.get("invisible") or "").strip() not in HIDDEN
            and (node.get("column_invisible") or "").strip() not in HIDDEN]


@tagged("post_install", "-at_install")
class TestPurchaseHiddenStep29(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        core = (
            "purchase.group_purchase_manager",
            "purchase.group_send_reminder",
            "sales_team.group_sale_manager",
            "stock.group_stock_manager",
            "stock.group_stock_multi_locations",
            "mrp.group_mrp_manager",
            "account.group_account_manager",
            "product.group_product_pricelist",
            "project.group_project_manager",
        )
        groups = [cls.env.ref(x, raise_if_not_found=False) for x in core]
        cls.admin.write({"group_ids": [Command.link(g.id) for g in groups if g]})

    def _arch(self, model, view_xmlid=None, view_type="form"):
        view_id = self.env.ref(view_xmlid).id if view_xmlid else False
        views = self.env[model].with_user(self.admin).get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _join(self, *xmlids):
        self.admin.write({"group_ids": [Command.link(self.env.ref(x).id) for x in xmlids]})

    def test_views_active(self):
        for xmlid in VIEWS:
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    # ─── Запрос КП / заказ поставщику ───────────────────────────────────
    def test_order_form(self):
        arch = self._arch("purchase.order")
        for expr in ("//field[@name='priority']",
                     "//label[@for='receipt_reminder_email']",
                     "//div[@name='reminder']",
                     "//button[@name='action_acknowledge']",
                     "//field[@name='fiscal_position_id']",
                     "//widget[@name='purchase_file_uploader']"):
            with self.subTest(hidden=expr):
                self.assertFalse(shown(arch, expr))
        ref = shown(arch, "//field[@name='partner_ref']")
        self.assertEqual(len(ref), 1)
        self.assertEqual(ref[0].get("string"), "Номер у поставщика")
        # Оставлено намеренно: налоги, условия платежа, «Условия и положения».
        for expr in ("//field[@name='payment_term_id']", "//field[@name='note']",
                     "//field[@name='tax_totals']", "//field[@name='order_line']"):
            with self.subTest(kept=expr):
                self.assertTrue(shown(arch, expr))

    def test_order_form_reversible(self):
        self._join(REMOVED)
        arch = self._arch("purchase.order")
        for expr in ("//field[@name='priority']", "//div[@name='reminder']",
                     "//button[@name='action_acknowledge']", "//field[@name='fiscal_position_id']"):
            with self.subTest(back=expr):
                self.assertTrue(shown(arch, expr))
        self.assertFalse(arch.xpath("//widget[@name='purchase_file_uploader']"),
                         "«Загрузить счёт» — «Деньги», не «Убранное».")
        self._join(MONEY)
        arch = self._arch("purchase.order")
        self.assertTrue(arch.xpath("//widget[@name='purchase_file_uploader']"))

    def test_order_lists_and_search(self):
        for xmlid in ("purchase.purchase_order_tree", "purchase.purchase_order_kpis_tree",
                      "purchase.purchase_order_view_tree"):
            arch = self._arch("purchase.order", xmlid, "list")
            with self.subTest(view=xmlid):
                ref = arch.xpath("/list/field[@name='partner_ref']")
                self.assertEqual(len(ref), 1)
                self.assertEqual(ref[0].get("string"), "Номер у поставщика")
                self.assertFalse(shown(arch, "/list/field[@name='priority']"))
        for xmlid, names in (("purchase.view_purchase_order_filter", ("starred", "not_acknowledged")),
                             ("purchase.purchase_order_view_search", ("starred",))):
            arch = self._arch("purchase.order", xmlid, "search")
            for name in names:
                with self.subTest(view=xmlid, filter=name):
                    self.assertFalse(arch.xpath("//filter[@name='%s']" % name))
            with self.subTest(view=xmlid, kept="order_date"):
                self.assertTrue(arch.xpath("//filter[@name='order_date']"))

    def test_order_still_created_from_form(self):
        """Спрятанное обязательное («Доставить в») берёт умолчание: запрос
        КП создаётся через тот же вид и onchange, что у браузера."""
        partner = self.env["res.partner"].create({"name": "Поставщик (тест 29)", "is_company": True})
        form = Form(self.env["purchase.order"].with_user(self.admin))
        form.partner_id = partner
        record = form.save()
        self.assertEqual(record.partner_id, partner)
        if "picking_type_id" in record._fields:
            self.assertTrue(record.picking_type_id)

    # ─── Карточка товара ────────────────────────────────────────────────
    def test_template_form_hidden_and_kept(self):
        arch = self._arch("product.template", "product.product_template_only_form_view")
        for expr in TEMPLATE_HIDDEN:
            with self.subTest(hidden=expr):
                self.assertFalse(shown(arch, expr))
        for expr in TEMPLATE_KEPT:
            with self.subTest(kept=expr):
                self.assertTrue(shown(arch, expr))
        # Пустой левой колонки «Основной информации» нет.
        self.assertFalse(arch.xpath("//group[@name='group_general']"))
        # Признак проката для колонки «Длина хлыста» (R11) — на месте.
        self.assertTrue(arch.xpath("//field[@name='pmk_is_linear']"))

    def test_template_neighbour_fields_still_loaded(self):
        """Скрытое, на что ссылаются видимые соседи, ядро досоздало
        невидимым: «Стоимость» — в контексте списка поставщиков (цена новой
        строки по умолчанию), «Тип товара» — в условиях вкладок «Покупка» и
        «Склад» и галочки «Закупка». Без них браузер не посчитал бы условия."""
        arch = self._arch("product.template", "product.product_template_only_form_view")
        for name in ("standard_price", "type"):
            with self.subTest(field=name):
                nodes = arch.xpath("//field[@name='%s']" % name)
                self.assertTrue(nodes)
                self.assertFalse(shown(arch, "//field[@name='%s']" % name))

    def test_template_groups_bring_back(self):
        for group in (REMOVED, STOCK, MONEY):
            self._join(group)
            arch = self._arch("product.template", "product.product_template_only_form_view")
            for expr, owner in TEMPLATE_HIDDEN.items():
                if owner != group:
                    continue
                with self.subTest(group=group, back=expr):
                    self.assertTrue(arch.xpath(expr))

    def test_variant_form(self):
        arch = self._arch("product.product", "product.product_normal_form_view")
        for expr in ("//button[@name='action_view_bom']", "//button[@name='action_product_forecast_report']",
                     "//field[@name='lst_price']", "//page[@name='sales']", "//field[@name='barcode']",
                     "//field[@name='is_favorite']", "//group[@name='group_general']"):
            with self.subTest(hidden=expr):
                self.assertFalse(shown(arch, expr))
        self.assertTrue(shown(arch, "//field[@name='seller_ids']"))
        if "kod_tnved" in self.env["product.product"]._fields:
            self.assertFalse(shown(arch, "//field[@name='kod_tnved']"))
            self._join(MONEY)
            arch = self._arch("product.product", "product.product_normal_form_view")
            self.assertTrue(shown(arch, "//field[@name='kod_tnved']"), "«Код ТНВЭД» — «Деньги».")

    def test_product_still_created_from_form(self):
        """Спрятаны «Тип товара» и цена продажи — новый товар из формы
        получает их умолчания."""
        form = Form(self.env["product.template"].with_user(self.admin))
        form.name = "Уголок 50х5 (тест 29)"
        record = form.save()
        self.assertEqual(record.type, "consu")
        self.assertTrue(record.purchase_ok)
        # Расчёт читает товар в Python, мимо вида: цена закупки находится,
        # как и до шага (pmk_bridge, reference_price.py, _pmk_find_seller).
        supplier = self.env["res.partner"].create({"name": "Металлобаза (тест 29)", "is_company": True})
        line = self.env["product.supplierinfo"].create({
            "partner_id": supplier.id, "product_tmpl_id": record.id, "price": 95000.0,
        })
        self.assertEqual(record._pmk_find_seller(fields.Date.context_today(record)), line)

    def test_products_list(self):
        arch = self._arch("product.template", "product.product_template_tree_view", "list")
        for name in ("is_favorite", "list_price", "standard_price", "qty_available", "virtual_available"):
            with self.subTest(hidden=name):
                self.assertFalse(shown(arch, "/list/field[@name='%s']" % name))
        for name in ("name", "default_code"):
            with self.subTest(kept=name):
                self.assertTrue(shown(arch, "/list/field[@name='%s']" % name))

    def test_variants_list(self):
        """«Искать ещё…» у поля «Товар» в строке запроса КП открывает список
        вариантов по умолчанию — без продажной цены и складских колонок."""
        hidden = {"is_favorite": REMOVED, "lst_price": REMOVED, "standard_price": STOCK,
                  "qty_available": STOCK, "virtual_available": STOCK}
        default = self.env["product.product"].get_views([(False, "list")])
        self.assertEqual(default["views"]["list"]["id"], self.env.ref("product.product_product_tree_view").id,
                         "Предпосылка: этот вид — список вариантов по умолчанию.")
        arch = self._arch("product.product", "product.product_product_tree_view", "list")
        for name in hidden:
            with self.subTest(hidden=name):
                self.assertFalse(shown(arch, "/list/field[@name='%s']" % name))
        for name in ("name", "default_code"):
            with self.subTest(kept=name):
                self.assertTrue(shown(arch, "/list/field[@name='%s']" % name))
        for group in (REMOVED, STOCK):
            self._join(group)
            arch = self._arch("product.product", "product.product_product_tree_view", "list")
            for name, owner in hidden.items():
                if owner != group:
                    continue
                with self.subTest(group=group, back=name):
                    self.assertTrue(arch.xpath("/list/field[@name='%s']" % name))

    def _switches(self, *xmlids):
        """У admin ровно эти группы-выключатели шага, остальные сняты."""
        self.admin.write({"group_ids": [Command.unlink(self.env.ref(x).id) for x in (REMOVED, STOCK, MONEY)]
                                       + [Command.link(self.env.ref(x).id) for x in xmlids]})

    def test_uom_still_editable(self):
        """Единица товара в Odoo 19 — только в «… за [ед.]» у «Цены продажи»
        и «Стоимости», оба блока спрятаны. С «Единицами измерения» её видно
        при любом наборе групп шага, а свой узел — только когда штатных
        мест нет."""
        cases = (
            ("product.template", "product.product_template_only_form_view"),
            ("product.product", "product.product_normal_form_view"),
        )
        own = "//group[@name='group_standard_price']/field[@name='uom_id']"
        # Демо-данные одноразовой базы могли включить «Единицы измерения».
        if not self.admin.has_group("uom.group_uom"):
            for model, xmlid in cases:
                with self.subTest(view=xmlid, uom=False):
                    self.assertFalse(shown(self._arch(model, xmlid), "//field[@name='uom_id']"),
                                     "Без «Единиц измерения» — как у ядра, не видно.")
            self._join("uom.group_uom")
        for switches in ((), (REMOVED,), (STOCK,), (REMOVED, STOCK)):
            self._switches(*switches)
            for model, xmlid in cases:
                arch = self._arch(model, xmlid)
                with self.subTest(view=xmlid, switches=switches):
                    self.assertTrue(shown(arch, "//field[@name='uom_id']"), "Единицу видно и можно сменить.")
                    self.assertEqual(bool(shown(arch, own)), not switches)

    # ─── Панель «Запросов КП» ───────────────────────────────────────────
    def test_dashboard_flags(self):
        """«Не подтверждены поставщиком» — только с «Убранным»,
        «Поставки в срок» — только со «Складом»."""
        def flags():
            return self.env["purchase.order"].with_user(self.admin).retrieve_dashboard()["pmk_show"]
        self.assertEqual(flags(), {"not_acknowledged": False, "otd": False})
        self._join(REMOVED)
        self.assertEqual(flags(), {"not_acknowledged": True, "otd": False})
        self._join(STOCK)
        self.assertEqual(flags(), {"not_acknowledged": True, "otd": True})

    def test_dashboard_template_reads_flags(self):
        with file_open("pmk_purchase/static/src/xml/purchase_dashboard.xml", "rb") as f:
            root = etree.parse(f).getroot()
        for name in ("not_acknowledged", "not_acknowledged,my_purchases"):
            nodes = root.xpath("//xpath[@expr=\"//div[@filter_name='%s']\"]/attribute[@name='t-if']" % name)
            with self.subTest(card=name):
                self.assertEqual(len(nodes), 1)
                self.assertIn("pmk_show.not_acknowledged", nodes[0].text)
        root_attr = root.xpath("//xpath[@expr=\"//div[hasclass('o_purchase_dashboard')]\"]"
                               "/attribute[@name='t-att-data-pmk-otd-off']")
        self.assertEqual(len(root_attr), 1)
        self.assertIn("pmk_show.otd", root_attr[0].text)
        with file_open("pmk_purchase/static/src/scss/purchase_dashboard.scss", "r") as f:
            self.assertIn('.o_purchase_dashboard[data-pmk-otd-off] [title="OTD"]', f.read())

    def test_supplier_lines_lead_time_in_gear(self):
        for xmlid in ("purchase.product_supplierinfo_tree_view2",
                      "purchase.product_product_supplierinfo_tree_view2"):
            arch = self._arch("product.supplierinfo", xmlid, "list")
            with self.subTest(view=xmlid):
                delay = arch.xpath("/list/field[@name='delay']")
                self.assertEqual(len(delay), 1)
                self.assertEqual(delay[0].get("optional"), "hide")
                self.assertTrue(shown(arch, "/list/field[@name='price']"))

    def test_products_action_list_and_form(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.product_template_action_product")
        self.assertEqual([mode for _id, mode in action["views"]], ["list", "form"])
        self.assertEqual(action["view_mode"], "list,form")
        record = self.env.ref("stock.product_template_action_product")
        self.assertIn("kanban", record.view_mode, "В базе действие не тронуто.")
