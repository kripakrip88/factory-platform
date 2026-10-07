# -*- coding: utf-8 -*-
"""Меню внутри разделов — разбор UX, шаг 38, pmk_theme.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Меню — как их получает
браузер: load_web_menus (видимость по группам и правам на модель действия,
поддеревья только видимых корней).

Что ловим:
  • Продажи: Воронка сделок · Почта · Расчёты и КП · Клиенты · Лиды — у
    обычного менеджера и у администратора; «Расчёты и КП» открывает расчёты
    (то же действие, что «Калькуляторы → Расчёт металлопроката», и тот пункт
    на месте);
  • «Коммерческие предложения» и «Счета покупателям» (до шага 58 — «Заказы клиентов») — только с «Деньги
    (показать)»;
  • разделы «Ещё» (Производство, Склад, Деньги, Отчёты) скрыты без групп и
    видны с группой; «Сотрудники» — на месте; документы спрятанных разделов
    по-прежнему открываются (действия целы);
  • только администратору: «Обслуживание оборудования», «Ремонты»,
    «Подразделения», пункты «Отчётов»;
  • «Номенклатура» достижима без «Склада» (пункт в Закупках);
  • группы-выключатели пустые и без privilege_id (галочка — в «Дополнительных
    правах» карточки, режим разработчика);
  • окна «Заказы поставщикам» и «Номенклатура» называются как пункты;
  • подсказки пустых экранов ведут в живые пункты меню;
  • внутри каждого раздела у пунктов разные ключи подсветки (номер действия и
    path) — иначе горели бы два пункта (static/src/js/active_section_keys.js).

Глазами (строка разделов, точка «где я», «Ещё», карточка пользователя) —
основной агент на копии.
"""
import re

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged

PRODUCTION = "pmk_theme.group_pmk_production"
STOCK = "pmk_theme.group_pmk_stock"
MONEY = "pmk_theme.group_pmk_money"
REMOVED = "pmk_theme.group_pmk_removed"
SWITCHES = (PRODUCTION, STOCK, MONEY, REMOVED)

SALES = ["Воронка сделок", "Почта", "Расчёты и КП", "Клиенты", "Лиды"]
MORE = ("pmk_theme.menu_pmk_production", "pmk_theme.menu_pmk_stock",
        "pmk_theme.menu_pmk_money", "pmk_theme.menu_pmk_reports")

# «Раздел → Пункт» в кавычках-ёлочках внутри подсказки.
MENU_PATH = re.compile(r"«([^«»]+? → [^«»]+?)»")


@tagged("post_install", "-at_install")
class TestMenusStep38(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        # Штатные права, при которых всё спрятанное было бы видно без шага 38.
        core = ["base.group_system", "sales_team.group_sale_manager",
                "purchase.group_purchase_manager", "stock.group_stock_manager",
                "mrp.group_mrp_manager", "account.group_account_manager",
                "hr.group_hr_manager"]
        cls.admin.write({"group_ids": [Command.link(cls.env.ref(x).id) for x in core]
                                      + [Command.unlink(cls.env.ref(x).id) for x in SWITCHES]})
        # Обычный менеджер: продажи и закупки, без администрирования.
        cls.manager = new_test_user(
            cls.env, login="pmk38_manager",
            groups="base.group_user,sales_team.group_sale_salesman,purchase.group_purchase_user")
        cls.env["res.lang"]._activate_lang("ru_RU")
        cls.sales = list(SALES)
        if not cls.env.ref("pmk_mail_ui.menu_mail_sale", raise_if_not_found=False):
            cls.sales.remove("Почта")

    # ─── помощники ──────────────────────────────────────────────────────
    def _installed(self, module):
        return self.env["ir.module.module"]._get(module).state == "installed"

    def _menus(self, user):
        return self.env["ir.ui.menu"].with_user(user).load_web_menus(False)

    def _apps(self, user):
        menus = self._menus(user)
        return {menus[mid]["xmlid"] for mid in menus["root"]["children"]}

    def _items(self, user, app_xmlid):
        """Пункты раздела по порядку; None — раздела у человека нет."""
        menus = self._menus(user)
        app = self.env.ref(app_xmlid).id
        if app not in menus:
            return None
        return [menus[mid]["name"] for mid in menus[app]["children"]]

    def _join(self, user, *xmlids):
        user.write({"group_ids": [Command.link(self.env.ref(x).id) for x in xmlids]})

    # ─── Продажи ────────────────────────────────────────────────────────
    def test_sales_items(self):
        for user in (self.manager, self.admin):
            with self.subTest(user=user.login):
                self.assertEqual(self._items(user, "pmk_theme.menu_pmk_sales"), self.sales)

    def test_sales_opens_pipeline(self):
        """Раздел по-прежнему открывается воронкой (первый пункт)."""
        menus = self._menus(self.manager)
        self.assertEqual(menus[self.env.ref("pmk_theme.menu_pmk_sales").id]["actionID"],
                         self.env.ref("crm.crm_lead_action_pipeline").id)

    def test_specs_item_opens_calculations(self):
        menus = self._menus(self.manager)
        spec_action = self.env.ref("pmk_calc.action_metal_spec")
        ours = self.env.ref("pmk_theme.menu_pmk_sales_specs")
        self.assertEqual(menus[ours.id]["actionID"], spec_action.id)
        self.assertEqual(spec_action.res_model, "pmk.metal.spec")
        calc = self.env.ref("pmk_calc.menu_pmk_calc_spec")
        self.assertIn(calc.id, menus, "В «Калькуляторах» пункт остаётся.")
        self.assertEqual(menus[calc.id]["actionID"], spec_action.id)

    def test_standard_quotations_and_orders_with_money(self):
        # «Счета покупателям» — штатный заказ клиента (шаг 58).
        names = ("Коммерческие предложения", "Счета покупателям")
        for name in names:
            self.assertNotIn(name, self._items(self.admin, "pmk_theme.menu_pmk_sales"))
        self._join(self.admin, MONEY)
        self.assertEqual(self._items(self.admin, "pmk_theme.menu_pmk_sales"),
                         self.sales + list(names))

    # ─── «Ещё» ──────────────────────────────────────────────────────────
    def test_more_sections_hidden_without_switch(self):
        for user in (self.manager, self.admin):
            with self.subTest(user=user.login):
                self.assertFalse(self._apps(user) & set(MORE))
        self.assertIn("pmk_theme.menu_pmk_people", self._apps(self.admin),
                      "«Сотрудники» остаются (операторы лазера).")
        if self._installed("pmk_laser"):
            self.assertIn("pmk_laser.menu_pmk_laser", self._apps(self.admin),
                          "Лазерная резка — наш раздел, не штатное производство.")

    def test_section_by_switch(self):
        cases = [
            (STOCK, "pmk_theme.menu_pmk_stock",
             ["Обзор операций", "Приёмки", "Отгрузки", "Остатки", "Номенклатура"]),
            (PRODUCTION, "pmk_theme.menu_pmk_production",
             ["Производственные заказы", "Рабочие задания", "Спецификации", "Рабочие центры",
              "Обслуживание оборудования", "Ремонты"]),
            (MONEY, "pmk_theme.menu_pmk_money",
             ["Реализации", "Счета от поставщиков", "Платежи полученные",
              "Платежи отправленные"]),
        ]
        for group, app, items in cases:
            with self.subTest(group=group):
                self.assertIsNone(self._items(self.admin, app))
                self._join(self.admin, group)
                self.assertEqual(self._items(self.admin, app), items)

    def test_reports_admin_with_money_only(self):
        items = ["Продажи", "Коммерческие предложения", "Счета", "Загрузка рабочих центров"]
        self._join(self.manager, MONEY)
        self.assertIsNone(self._items(self.manager, "pmk_theme.menu_pmk_reports"),
                          "Отчёты — только администратору, даже с «Деньгами».")
        self.assertIsNone(self._items(self.admin, "pmk_theme.menu_pmk_reports"))
        self._join(self.admin, MONEY)
        self.assertEqual(self._items(self.admin, "pmk_theme.menu_pmk_reports"), items)

    def test_production_service_items_admin_only(self):
        mrp_user = new_test_user(self.env, login="pmk38_mrp",
                                 groups="base.group_user,mrp.group_mrp_user," + PRODUCTION)
        self.assertEqual(self._items(mrp_user, "pmk_theme.menu_pmk_production"),
                         ["Производственные заказы", "Рабочие задания", "Спецификации",
                          "Рабочие центры"])

    def test_departments_admin_only(self):
        hr_user = new_test_user(self.env, login="pmk38_hr",
                                groups="base.group_user,hr.group_hr_user")
        self.assertEqual(self._items(hr_user, "pmk_theme.menu_pmk_people"), ["Сотрудники"])
        self.assertEqual(self._items(self.admin, "pmk_theme.menu_pmk_people"),
                         ["Сотрудники", "Подразделения"])
        self.assertNotIn("pmk_theme.menu_pmk_people", self._apps(self.manager),
                         "Без прав на сотрудников раздела нет: «Подразделения» были единственным пунктом.")

    def test_hidden_sections_documents_still_open(self):
        """Спрятан пункт, а не документ: действия целы и открываются (по
        ссылке, кнопкой, вкладкой «Связи»)."""
        Action = self.env["ir.actions.act_window"].with_user(self.admin)
        for xmlid, model in (("mrp.mrp_production_action", "mrp.production"),
                             ("stock.action_picking_tree_incoming", "stock.picking"),
                             ("account.action_move_out_invoice", "account.move"),
                             ("sale.action_orders", "sale.order"),
                             ("purchase.purchase_form_action", "purchase.order")):
            with self.subTest(action=xmlid):
                self.assertEqual(Action._for_xml_id(xmlid)["res_model"], model)

    # ─── Номенклатура ───────────────────────────────────────────────────
    def test_nomenclature_reachable_without_stock(self):
        menus = self._menus(self.manager)
        ours = self.env.ref("pmk_theme.menu_pmk_purch_products")
        self.assertIn(ours.id, menus, "«Закупки → Номенклатура» видна без «Склада».")
        self.assertEqual(menus[ours.id]["actionID"],
                         self.env.ref("stock.product_template_action_product").id)
        self.assertEqual(menus[ours.id]["appID"], self.env.ref("pmk_theme.menu_pmk_purchase").id)
        self.assertNotIn(self.env.ref("pmk_theme.menu_pmk_stock_products").id, menus)
        self._join(self.admin, STOCK)
        self.assertIn("Номенклатура", self._items(self.admin, "pmk_theme.menu_pmk_stock"),
                      "Пункт «Склада» на месте — для тех, у кого «Склад (показать)».")

    # ─── Группы ─────────────────────────────────────────────────────────
    def test_switch_groups(self):
        for xmlid in (PRODUCTION, STOCK, MONEY):
            with self.subTest(group=xmlid):
                group = self.env.ref(xmlid)
                self.assertFalse(group.privilege_id,
                                 "Без privilege — галочка в «Дополнительных правах».")
                self.assertFalse(group.with_context(active_test=False).user_ids)
                self.assertTrue(group.comment, "Подсказка у галочки.")
        self.assertFalse(self.env.ref(PRODUCTION).implied_ids,
                         "Прав «Производство (показать)» не даёт.")

    def test_roots_carry_switch_groups(self):
        """Группа на корне, а не на каждом пункте: раздел открывается одной
        галочкой; «Сотрудники», Продажи и Закупки — без группы."""
        expected = {
            "pmk_theme.menu_pmk_production": PRODUCTION,
            "pmk_theme.menu_pmk_stock": STOCK,
            "pmk_theme.menu_pmk_money": MONEY,
            "pmk_theme.menu_pmk_reports": MONEY,
        }
        for xmlid, group in expected.items():
            with self.subTest(menu=xmlid):
                self.assertEqual(self.env.ref(xmlid).group_ids, self.env.ref(group))
        for xmlid in ("pmk_theme.menu_pmk_sales", "pmk_theme.menu_pmk_purchase",
                      "pmk_theme.menu_pmk_people"):
            with self.subTest(menu=xmlid):
                self.assertFalse(self.env.ref(xmlid).group_ids)

    # ─── Заголовки окон ─────────────────────────────────────────────────
    def test_window_titles(self):
        Action = self.env["ir.actions.act_window"]
        for xmlid, title in (("purchase.purchase_rfq", "Заказы поставщикам"),
                             ("stock.product_template_action_product", "Номенклатура")):
            for lang in ("en_US", "ru_RU"):
                with self.subTest(action=xmlid, lang=lang):
                    action = Action.with_context(lang=lang)._for_xml_id(xmlid)
                    self.assertEqual(action["name"], title)
                    self.assertEqual(action["display_name"], title)
                    # Меню грузит по номеру (/web/action/load) — тот же заголовок.
                    by_id = self.env.ref(xmlid).sudo().with_context(lang=lang)._get_action_dict()
                    self.assertEqual(by_id["name"], title)
                    self.assertEqual(by_id["display_name"], title)

    def test_window_titles_only_ours(self):
        """Соседнее действие — со своим именем; в базе имя не тронуто.

        Сосед — «Лиды»: «Подтверждённые заказы» (purchase_form_action), сосед
        до шага 39, с шага 39 тоже в ACTION_TITLES (одно понятие — одно слово).
        """
        record = self.env.ref("crm.crm_lead_all_leads")
        self.assertEqual(self.env["ir.actions.act_window"]._for_xml_id(
            "crm.crm_lead_all_leads")["name"], record.name)
        self.assertNotEqual(self.env.ref("purchase.purchase_rfq").name, "Заказы поставщикам",
                            "Подмена при отдаче браузеру, запись ядра прежняя.")

    # ─── Подсказки ведут в живые пункты ─────────────────────────────────
    def test_empty_help_points_to_live_menus(self):
        if not all(self._installed(m) for m in ("pmk_purchase", "pmk_mail_ui")):
            self.skipTest("Нужны pmk_purchase и pmk_mail_ui: их пункты названы в подсказках.")
        self._join(self.admin, *SWITCHES)
        menus = self._menus(self.admin)
        paths = set()
        stack = [(mid, menus[mid]["name"]) for mid in menus["root"]["children"]]
        roots = {name for _mid, name in stack}
        while stack:
            mid, path = stack.pop()
            paths.add(path)
            stack.extend((child, path + " → " + menus[child]["name"])
                         for child in menus[mid]["children"])
        texts = self.env["ir.actions.act_window"]._pmk_empty_help()
        checked = 0
        for xmlid, text in texts.items():
            for path in MENU_PATH.findall(text):
                with self.subTest(action=xmlid, path=path):
                    if path.split(" → ")[0] not in roots:
                        continue  # раздел модуля, которого нет в базе (лазер)
                    self.assertIn(path, paths)
                    checked += 1
        self.assertIn("«Продажи → Расчёты и КП»",
                      texts["sale.action_order_report_quotation_salesteam"])
        self.assertGreater(checked, 5)

    # ─── Подсветка «где я» ──────────────────────────────────────────────
    def test_section_keys_unique_within_app(self):
        """Ключ пункта — номер действия и path (active_section_keys.js,
        menuKeys). Два пункта одного раздела с одним ключом горели бы оба."""
        self._join(self.admin, *SWITCHES)
        menus = self._menus(self.admin)
        checked = 0
        for app_id in menus["root"]["children"]:
            # Свои разделы; в штатных «Настройках» ключи не наши.
            if not menus[app_id]["xmlid"].startswith(("pmk_theme.", "pmk_calc.", "pmk_laser.")):
                continue
            keys = []
            stack = list(menus[app_id]["children"])
            while stack:
                item = menus[stack.pop()]
                stack.extend(item["children"])
                if item["actionID"]:
                    keys.append("action-%s" % item["actionID"])
                if item["actionPath"]:
                    keys.append(item["actionPath"])
            with self.subTest(app=menus[app_id]["name"]):
                self.assertEqual(len(keys), len(set(keys)), keys)
                checked += 1
        self.assertGreaterEqual(checked, 7, "Продажи, Закупки, Калькуляторы и четыре раздела «Ещё».")
