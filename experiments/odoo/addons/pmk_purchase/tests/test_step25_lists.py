# -*- coding: utf-8 -*-
"""Колонки списков закупок и «Цены поставщиков» — разбор UX, шаг 25.

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo (см. __init__.py).
Разметка — собранная, как её получает браузер (get_views). Глазами это не
заменяет: ширину, перенос шапки и пустой экран смотрит основной агент.
"""
import datetime

from lxml import etree

from dateutil.relativedelta import relativedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

HIDDEN = ("1", "True", "true")
PATH = "supplier-prices"


@tagged("post_install", "-at_install")
class TestPurchaseListsStep25(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("purchase.group_purchase_manager").id),
        ]})

    def _arch(self, model, view_xmlid, view_type="list"):
        view_id = self.env.ref(view_xmlid).id if view_xmlid else False
        views = self.env[model].with_user(self.admin).get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _one(self, arch, name, path="/list/field"):
        nodes = arch.xpath("%s[@name='%s']" % (path, name))
        self.assertEqual(len(nodes), 1, name)
        return nodes[0]

    def test_views_active(self):
        for xmlid in ("pmk_purchase.purchase_order_kpis_tree_tones",
                      "pmk_purchase.purchase_order_view_tree_pmk",
                      "pmk_purchase.product_supplierinfo_tree_view2_pmk"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    # ─── Поставщики ─────────────────────────────────────────────────────
    def test_suppliers_menu_uses_price_supplier_list(self):
        """«Поставщики» больше не делят вид и выбор колонок с «Клиентами»."""
        action = self.env["ir.actions.act_window"]._for_xml_id("account.res_partner_action_supplier")
        ours = self.env.ref("pmk_purchase.view_price_supplier_list")
        self.assertEqual(tuple(action["views"][0]), (ours.id, "list"))
        customers = self.env["ir.actions.act_window"]._for_xml_id("account.res_partner_action_customer")
        self.assertNotEqual(customers["views"][0][0], ours.id)

    def test_price_supplier_list_inn(self):
        arch = self._arch("res.partner", "pmk_purchase.view_price_supplier_list")
        vat = self._one(arch, "vat")
        self.assertEqual(vat.get("string"), "ИНН")
        self.assertEqual(vat.get("optional"), "hide")
        # «Прайс от» и «Следующий запрос» — видны по умолчанию (шаг 13).
        for name in ("pmk_price_last_date", "pmk_price_next_date"):
            with self.subTest(field=name):
                self.assertEqual(self._one(arch, name).get("optional"), "show")

    def test_mailing_toggle_only_for_registry(self):
        """Переключатель «В рассылке» — только у реестра прайсов: список
        открывают и «Закупки → Поставщики», а крон пишет только реестру."""
        arch = self._arch("res.partner", "pmk_purchase.view_price_supplier_list")
        toggle = self._one(arch, "pmk_price_mailing")
        self.assertEqual(toggle.get("widget"), "boolean_toggle")
        self.assertEqual(toggle.get("invisible"), "not pmk_price_supplier")
        registry = self._one(arch, "pmk_price_supplier")
        self.assertIn(registry.get("column_invisible"), HIDDEN)

    def test_mailing_on_needs_registry(self):
        Partner = self.env["res.partner"]
        outside = Partner.create({"name": "Поставщик не из реестра (тест 25)",
                                  "is_company": True, "supplier_rank": 1,
                                  "pmk_price_email": "price@outside.example"})
        inside = Partner.create({"name": "Поставщик из реестра (тест 25)",
                                 "is_company": True, "pmk_price_supplier": True,
                                 "pmk_price_email": "price@inside.example"})
        with self.assertRaises(UserError):
            outside.action_pmk_mailing_on()
        self.assertFalse(outside.pmk_price_mailing)
        with self.assertRaises(UserError):
            (outside | inside).action_pmk_mailing_on()
        self.assertFalse(inside.pmk_price_mailing, "Пачка не включается наполовину.")
        inside.action_pmk_mailing_on()
        self.assertTrue(inside.pmk_price_mailing)

    def test_panel_counts_like_cron(self):
        """«Получателей в рассылке» — как у крона: реестр И флажок."""
        mailing = self.env["pmk.price.mailing"].create({})
        before = mailing.recipient_count
        Partner = self.env["res.partner"]
        Partner.create({"name": "Снят с реестра (тест 25)", "is_company": True,
                        "pmk_price_mailing": True, "pmk_price_supplier": False})
        Partner.create({"name": "В реестре и рассылке (тест 25)", "is_company": True,
                        "pmk_price_mailing": True, "pmk_price_supplier": True})
        mailing.invalidate_recordset(["recipient_count"])
        self.assertEqual(mailing.recipient_count, before + 1)

    # ─── Запросы КП и заказы поставщикам ────────────────────────────────
    def test_rfq_list(self):
        arch = self._arch("purchase.order", "purchase.purchase_order_kpis_tree")
        for name in ("priority", "activity_ids"):
            with self.subTest(field=name):
                self.assertEqual(self._one(arch, name).get("optional"), "hide")
        self.assertFalse(arch.get("decoration-info"), "Строки не синие (29.09).")

    def test_orders_list(self):
        arch = self._arch("purchase.order", "purchase.purchase_order_view_tree")
        self.assertFalse(arch.get("decoration-info"),
                         "Голубая строка «к выставлению счёта» снята: счета в МоёмСкладе.")
        self.assertEqual(self._one(arch, "name").get("string"), "Номер")
        for name in ("priority", "activity_ids", "invoice_status"):
            with self.subTest(field=name):
                self.assertEqual(self._one(arch, name).get("optional"), "hide")
        bills = arch.xpath("//header/button[@name='action_create_invoice']")
        self.assertEqual(len(bills), 1, "Кнопка скрыта, а не удалена.")
        self.assertIn(bills[0].get("invisible"), HIDDEN)
        cancel = arch.xpath("//header/button[@name='button_cancel']")
        self.assertTrue(cancel and cancel[0].get("invisible") not in HIDDEN)

    # ─── Поставщики в карточке товара ───────────────────────────────────
    def test_product_card_suppliers(self):
        for xmlid in ("purchase.product_supplierinfo_tree_view2",
                      "purchase.product_product_supplierinfo_tree_view2"):
            with self.subTest(view=xmlid):
                arch = self._arch("product.supplierinfo", xmlid)
                names = [f.get("name") for f in arch.xpath("/list/field")]
                self.assertEqual(names.index("pmk_bar_length_mm") + 1, names.index("price"),
                                 "Длина хлыста — рядом с ценой.")
                length = self._one(arch, "pmk_bar_length_mm")
                self.assertEqual(length.get("optional"), "show")
                # Список правится в строке: скрытая ячейка скрывала и поле
                # ввода — у строки без длины её было не дописать.
                self.assertIsNone(length.get("invisible"))
                self.assertIsNone(length.get("readonly"))
                self.assertEqual(length.get("decoration-muted"), "not pmk_bar_length_mm")
                # Приёмка 01.10.2026 (R11): колонка — только у проката.
                self.assertEqual(length.get("column_invisible"), "not parent.pmk_is_linear")
                start = self._one(arch, "date_start")
                self.assertEqual(start.get("optional"), "show")
                self.assertEqual(start.get("string"), "Действует с")
                currency = arch.xpath("/list/field[@name='currency_id']")
                # Колонку ядро показывает только при нескольких валютах.
                for node in currency:
                    self.assertEqual(node.get("optional"), "hide")

    def test_product_card_has_linear_flag(self):
        """R11: признак «прокат» стоит в форме карточки — иначе список
        поставщиков не прочтёт parent.pmk_is_linear и спрячет колонку всем.
        Карточка шаблона и варианта: вариант строится из общей формы."""
        self.assertTrue(self.env.ref("pmk_purchase.view_product_template_is_linear").active)
        for model in ("product.template", "product.product"):
            with self.subTest(model=model):
                views = self.env[model].with_user(self.admin).get_views([(False, "form")])
                arch = etree.fromstring(views["views"]["form"]["arch"])
                flag = arch.xpath("//field[@name='pmk_is_linear']")
                self.assertTrue(flag, "Признак в форме %s." % model)
                self.assertIn(flag[0].get("invisible"), HIDDEN)
                self.assertTrue(arch.xpath("//field[@name='seller_ids']"))

    # ─── «Закупки → Цены поставщиков» ───────────────────────────────────
    def test_prices_menu_and_action(self):
        action = self.env.ref("pmk_purchase.action_supplier_prices")
        self.assertEqual(action.path, PATH)
        self.assertEqual(self.env["ir.actions.actions"].search([("path", "=", PATH)]).ids,
                         [action.id])
        self.assertEqual(action.view_id, self.env.ref("pmk_purchase.view_supplier_price_list"))
        self.assertEqual(action.search_view_id,
                         self.env.ref("pmk_purchase.view_supplier_price_search"))
        menu = self.env.ref("pmk_purchase.menu_supplier_prices")
        self.assertEqual(menu.parent_id, self.env.ref("pmk_theme.menu_pmk_purchase"))
        menus = self.env["ir.ui.menu"].with_user(self.admin).load_web_menus(False)
        self.assertIn(menu.id, menus, "Пункт «Цены поставщиков» должен быть виден.")
        self.assertEqual(menus[menu.id]["actionPath"], PATH)

    def test_prices_list(self):
        arch = self._arch("product.supplierinfo", "pmk_purchase.view_supplier_price_list")
        self.assertEqual(arch.get("create"), "0")
        self.assertEqual(arch.get("delete"), "0")
        self.assertEqual(arch.get("duplicate"), "0")
        self.assertIsNone(arch.get("editable"), "Только просмотр, правка — в карточке строки.")
        names = [f.get("name") for f in arch.xpath("/list/field")
                 if f.get("column_invisible") not in HIDDEN]
        self.assertEqual(names, ["partner_id", "product_tmpl_id", "pmk_variant_label",
                                 "pmk_bar_length_mm", "price", "product_uom_id",
                                 "pmk_price_ton", "date_start", "date_end", "min_qty"])
        self.assertEqual(self._one(arch, "partner_id").get("string"), "Поставщик")
        self.assertEqual(self._one(arch, "date_start").get("string"), "Действует с")
        # R11: у не-проката ячейка пустая, а не «0».
        self.assertEqual(self._one(arch, "pmk_bar_length_mm").get("invisible"),
                         "not pmk_is_linear or not pmk_bar_length_mm")
        self.assertIn(self._one(arch, "pmk_is_linear").get("column_invisible"), HIDDEN)
        search = self._arch("product.supplierinfo", "pmk_purchase.view_supplier_price_search",
                            "search")
        for name in ("current", "older_30", "no_date"):
            with self.subTest(filter=name):
                self.assertTrue(search.xpath("//filter[@name='%s']" % name))

    def test_prices_form_is_read_only_for_rows(self):
        """Из «Цен поставщиков» строку прайса не создать, не удалить и не
        продублировать — ни в списке, ни в форме; длину хлыста — дописать."""
        action = self.env["ir.actions.act_window"]._for_xml_id("pmk_purchase.action_supplier_prices")
        form = self.env.ref("pmk_purchase.view_supplier_price_form")
        self.assertEqual([tuple(v) for v in action["views"]],
                         [(self.env.ref("pmk_purchase.view_supplier_price_list").id, "list"),
                          (form.id, "form")], "Сначала список, форма — наша.")
        arch = self._arch("product.supplierinfo", "pmk_purchase.view_supplier_price_form", "form")
        for attr in ("create", "delete", "duplicate"):
            with self.subTest(attr=attr):
                self.assertEqual(arch.get(attr), "0")
        self.assertEqual(len(arch.xpath("//field[@name='pmk_bar_length_mm']")), 1)
        # R11: у не-проката поля нет, у проката — дописать можно.
        self.assertEqual(arch.xpath("//field[@name='pmk_bar_length_mm']")[0].get("invisible"),
                         "not pmk_is_linear")
        self.assertTrue(arch.xpath("//field[@name='pmk_is_linear']"))
        self.assertTrue(arch.xpath("//field[@name='price']"), "Цену править можно.")
        # Штатная форма строки прайса — для остальных мест — не тронута.
        default = self.env["product.supplierinfo"].get_views([(False, "form")])
        self.assertNotEqual(default["views"]["form"]["id"], form.id)
        std = etree.fromstring(default["views"]["form"]["arch"])
        self.assertNotEqual(std.get("create"), "0")

    def test_prices_list_is_not_default(self):
        """Карточка товара и закупка берут штатный список строк прайса."""
        views = self.env["product.supplierinfo"].get_views([(False, "list")])
        self.assertNotEqual(views["views"]["list"]["id"],
                            self.env.ref("pmk_purchase.view_supplier_price_list").id)

    def test_filters_by_date(self):
        """Фильтры «Действуют сегодня» и «Старше 30 дней» — домены из самого
        вида поиска, вычисленные так, как их вычисляет браузер."""
        supplier = self.env["res.partner"].create({"name": "Поставщик (тест 25)", "is_company": True})
        tmpl = self.env["product.template"].create({"name": "Труба (тест 25)"})
        today = fields.Date.context_today(supplier)
        Info = self.env["product.supplierinfo"]
        fresh = Info.create({"partner_id": supplier.id, "product_tmpl_id": tmpl.id,
                             "price": 10.0, "date_start": today})
        stale = Info.create({"partner_id": supplier.id, "product_tmpl_id": tmpl.id,
                             "price": 9.0, "date_start": today - datetime.timedelta(days=45)})
        closed = Info.create({"partner_id": supplier.id, "product_tmpl_id": tmpl.id,
                              "price": 8.0, "date_start": today - datetime.timedelta(days=90),
                              "date_end": today - datetime.timedelta(days=1)})
        undated = Info.create({"partner_id": supplier.id, "product_tmpl_id": tmpl.id,
                               "price": 7.0})
        search = self._arch("product.supplierinfo", "pmk_purchase.view_supplier_price_search",
                            "search")
        env = {"context_today": lambda: today, "relativedelta": relativedelta}

        def found(filter_name):
            domain = safe_eval(search.xpath("//filter[@name='%s']" % filter_name)[0].get("domain"), env)
            return set(Info.search([("product_tmpl_id", "=", tmpl.id)] + domain).ids)

        self.assertEqual(found("current"), {fresh.id, stale.id, undated.id})
        self.assertEqual(found("older_30"), {stale.id, closed.id})
        self.assertEqual(found("no_date"), {undated.id})

    def test_depends_on_bridge_without_cycle(self):
        Module = self.env["ir.module.module"]
        purchase = Module.search([("name", "=", "pmk_purchase")])
        self.assertIn("pmk_bridge", purchase.dependencies_id.mapped("name"))
        names, todo = set(), Module.search([("name", "=", "pmk_bridge")])
        while todo:
            deps = todo.dependencies_id.depend_id
            todo = deps.filtered(lambda module: module.name not in names)
            names |= set(deps.mapped("name"))
        self.assertNotIn("pmk_purchase", names, "Мост не должен зависеть от закупок.")
