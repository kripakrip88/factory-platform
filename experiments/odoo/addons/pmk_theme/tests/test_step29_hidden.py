# -*- coding: utf-8 -*-
"""Убрать совсем и спрятать до востребования — разбор UX, шаг 29, pmk_theme.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Разметка — как её
получает браузер (get_views: все наследники применены, узлы чужих групп
вырезаны сервером).

Что ловим:
  • группы-выключатели пустые, admin не в них; «Склад (показать)» даёт
    права склада;
  • Настройки: без разделов «Сайт», «Проект», «Обслуживание», иностранных
    коннекторов и сервисов (Ringover, SEPA / чеки, OCR, Intrastat,
    barcodelookup) и «Сводки»; «Доставка» (не коннектор) и соседи
    иностранных сервисов на месте; группа — всё вернулось;
  • заказ поставщику: узлы purchase_stock / project_purchase спрятаны без
    зависимости от них — и возвращаются группой (значит, правило бьёт в
    существующий узел, а не в пустоту);
  • «Свойства» — только администратору: у сделки, контрагента, товара нет
    ни поля, ни группировки, и значит — пункта ⚙ «Изменить свойства»;
  • шестерёнка: пункты из HIDDEN_BINDINGS спрятаны, соседи на месте,
    группа возвращает ровно спрятанное;
  • «Сводка» выключена один раз: метка стоит, повторный вызов включённую
    сводку не трогает;
  • «Мои предпочтения»: без вкладки «Календарь», часовой пояс — на
    «Предпочтениях», ключи API — только администратору. В окне hr (его
    собирает суперпользователь, groups= там не годится) — по контексту
    окна из hr.action_get: менеджер не видит ключей, admin видит, календарь
    возвращается группой;
  • лента и «SMS» у телефона: hidden.scss в бандле после dark.scss и
    компилируется вместе со всей сборкой в состоянии стенда.

Глазами — Настройки без трёх разделов, лента без «Отправить сообщение»,
окно предпочтений — смотрит основной агент.
"""
import ast
import re

from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open
from odoo.tools.safe_eval import safe_eval

from odoo.addons.pmk_theme.models.digest import MARK
from odoo.addons.pmk_theme.models.hidden_nodes import HIDDEN_NODES
from odoo.addons.pmk_theme.models.ir_actions import HIDDEN_BINDINGS

REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"
MONEY = "pmk_theme.group_pmk_money"
HIDDEN = ("1", "True", "true")
SCSS = "pmk_theme/static/src/scss/"
# Живые на стенде файлы темы после шага 29 (navbar_nexus, переключатель,
# forms_nexus, dark — SELECT path, active FROM ir_asset, 02.10.2026 — и
# hidden.scss этого шага). В свежей тестовой базе включены все записи темы.
LIVE_THEME_PATHS = {
    SCSS + "navbar_nexus.scss",
    "pmk_theme/static/src/xml/theme_toggle.xml",
    SCSS + "forms_nexus.scss",
    SCSS + "dark.scss",
    SCSS + "hidden.scss",
}


def shown(arch, expr):
    """Узлы, которые человек увидит: ядро досоздаёт поля из модификаторов
    соседей невидимыми (_add_missing_fields) — такие не считаем."""
    return [node for node in arch.xpath(expr)
            if (node.get("invisible") or "").strip() not in HIDDEN
            and (node.get("column_invisible") or "").strip() not in HIDDEN]


@tagged("post_install", "-at_install")
class TestHiddenStep29(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        # Штатные права, при которых скрытое было бы видно без шага 29:
        # разделы Настроек, кнопки закупки, пункты шестерёнки.
        core = [
            "base.group_system",
            "sales_team.group_sale_manager",
            "purchase.group_purchase_manager",
            "stock.group_stock_manager",
            "stock.group_stock_multi_locations",
            "mrp.group_mrp_manager",
            "account.group_account_manager",
            "product.group_product_pricelist",
            "project.group_project_manager",
            "maintenance.group_equipment_manager",
            "hr.group_hr_manager",
            "website.group_website_designer",
            "purchase.group_send_reminder",
        ]
        groups = [cls.env.ref(xmlid, raise_if_not_found=False) for xmlid in core]
        # Группы самих скрытых действий — чтобы пункт был виден ядру и
        # тест ловил именно наше скрытие.
        for xmlid in HIDDEN_BINDINGS:
            action = cls.env.ref(xmlid, raise_if_not_found=False)
            if action and "group_ids" in action._fields:
                groups += list(action.group_ids)
        cls.admin.write({"group_ids": [Command.link(group.id) for group in groups if group]})

    def _installed(self, module):
        return self.env["ir.module.module"]._get(module).state == "installed"

    def _arch(self, model, view_type="form", view_xmlid=None, user=None):
        view_id = self.env.ref(view_xmlid).id if view_xmlid else False
        views = self.env[model].with_user(user or self.admin).get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _join(self, xmlid):
        self.admin.write({"group_ids": [Command.link(self.env.ref(xmlid).id)]})

    # ─── Группы ─────────────────────────────────────────────────────────
    def test_switch_groups_empty(self):
        for xmlid in (REMOVED, STOCK, MONEY):
            with self.subTest(group=xmlid):
                group = self.env.ref(xmlid)
                self.assertFalse(group.with_context(active_test=False).user_ids,
                                 "В группе-выключателе никого быть не должно.")
                self.assertFalse(self.admin.has_group(xmlid))

    def test_stock_switch_brings_stock_rights(self):
        """«Склад (показать)» вместо штатной группы склада у части узлов —
        поэтому сама даёт «Склад: пользователь» (остатки без прав не
        прочитать)."""
        stock_user = self.env.ref("stock.group_stock_user")
        self.assertIn(stock_user, self.env.ref(STOCK).implied_ids)

    # ─── Настройки ──────────────────────────────────────────────────────
    def _settings(self):
        return self._arch("res.config.settings")

    # Иностранные сервисы в CRM, Счетах и Складе (доводка шага 29).
    FOREIGN = (
        "//setting[@id='ringover-voip']",
        "//block[@id='print_vendor_checks_setting_container']",
        "//block[@id='account_digitalization']",
        "//setting[@id='intrastat_statistics']",
        "//setting[@id='process_stock_barcodelookup']",
    )

    def test_settings_apps_and_connectors_gone(self):
        arch = self._settings()
        for app in ("website", "project", "maintenance"):
            with self.subTest(app=app):
                self.assertFalse(arch.xpath("//app[@name='%s']" % app))
        for expr in ("//block[@id='connectors_setting_container']",
                     "//block[@name='shipping_connectors_setting_container']",
                     "//setting[@id='digest']") + self.FOREIGN:
            with self.subTest(node=expr):
                self.assertFalse(arch.xpath(expr))
        # Соседи иностранных сервисов на месте: блоки не опустели.
        for expr in ("//setting[@id='partnership_settings']",
                     "//setting[@id='process_operations_barcodes']",
                     "//setting[@id='default_incoterm']"):
            with self.subTest(neighbour=expr):
                self.assertTrue(arch.xpath(expr))
        shipping = arch.xpath("//block[@name='sale_shipping_setting_container']/setting")
        self.assertEqual([node.get("id") for node in shipping], ["delivery"],
                         "В «Доставке» продаж остаётся сама доставка, перевозчиков нет.")
        # Соседи на месте.
        for app in ("general_settings", "crm", "purchase", "stock"):
            with self.subTest(neighbour=app):
                self.assertTrue(arch.xpath("//app[@name='%s']" % app))
        self.assertTrue(arch.xpath("//block[@id='emails']"), "Блок писем остался, ушла только сводка.")

    def test_settings_reversible(self):
        self._join(REMOVED)
        arch = self._settings()
        apps = ["project", "maintenance"] + (["website"] if self._installed("website") else [])
        for app in apps:
            with self.subTest(app=app):
                self.assertTrue(arch.xpath("//app[@name='%s']" % app))
        self.assertTrue(arch.xpath("//block[@id='connectors_setting_container']"))
        self.assertTrue(arch.xpath("//block[@name='shipping_connectors_setting_container']"))
        self.assertTrue(arch.xpath("//setting[@id='digest']"))
        self.assertGreater(len(arch.xpath("//block[@name='sale_shipping_setting_container']/setting")), 1)
        # Правило бьёт в существующий узел, а не в пустоту.
        for expr in self.FOREIGN:
            with self.subTest(back=expr):
                self.assertTrue(arch.xpath(expr))

    # ─── Заказ поставщику: узлы чужих модулей ───────────────────────────
    def test_purchase_foreign_nodes(self):
        rules = HIDDEN_NODES[("purchase.order", "form")]
        arch = self._arch("purchase.order")
        for expr, _group in rules:
            with self.subTest(node=expr):
                self.assertFalse(shown(arch, expr))
        # Вернуть: обе группы — каждый узел на месте (правило не в пустоту).
        self._join(REMOVED)
        self._join(STOCK)
        arch = self._arch("purchase.order")
        modules = {
            "picking_type_id": "purchase_stock", "incoterm_id": "purchase_stock",
            "incoterm_location": "purchase_stock", "project_id": "project_purchase",
            "on_time_rate": "purchase_stock", "action_product_forecast_report": "purchase_stock",
        }
        for expr, _group in rules:
            module = next(m for key, m in modules.items() if key in expr)
            if not self._installed(module):
                continue
            with self.subTest(back=expr):
                self.assertTrue(shown(arch, expr))

    def test_purchase_required_field_still_defaults(self):
        """«Доставить в» обязателен — спрятан, а заказ создаётся: ядро
        ставит тип приёмки сам."""
        if "picking_type_id" not in self.env["purchase.order"]._fields:
            self.skipTest("purchase_stock не установлен")
        partner = self.env["res.partner"].create({"name": "Поставщик (тест 29)"})
        order = self.env["purchase.order"].with_user(self.admin).create({"partner_id": partner.id})
        self.assertTrue(order.picking_type_id)

    # ─── «Свойства» — только администратору ─────────────────────────────
    def _plain_user(self):
        """Внутренний пользователь без «Администрирования»: продажи, закупки,
        склад — права, при которых свойства были бы видны."""
        groups = ("base.group_user", "sales_team.group_sale_salesman_all_leads",
                  "purchase.group_purchase_user", "stock.group_stock_user")
        return self.env["res.users"].create({
            "name": "Менеджер (тест 29)",
            "login": "pmk_step29_plain",
            "group_ids": [Command.set([self.env.ref(x).id for x in groups])],
        })

    def test_properties_admin_only(self):
        user = self._plain_user()
        self.assertFalse(user.has_group("base.group_system"))
        cases = (
            ("crm.lead", "form", "crm.crm_lead_view_form", "lead_properties"),
            ("crm.lead", "search", "crm.view_crm_case_opportunities_filter", "lead_properties"),
            ("res.partner", "form", "base.view_partner_form", "properties"),
            ("res.partner", "search", "base.view_res_partner_filter", "properties"),
            ("product.template", "form", "product.product_template_only_form_view", "product_properties"),
        )
        for model, view_type, xmlid, field in cases:
            with self.subTest(model=model, view=view_type, user="менеджер"):
                arch = self._arch(model, view_type, xmlid, user=user)
                self.assertFalse(shown(arch, "//field[@name='%s']" % field))
                group_by = [n for n in arch.xpath("//filter[@context]") if field in n.get("context")]
                self.assertFalse(group_by, "Группировка «Свойства» — только администратору.")
            with self.subTest(model=model, view=view_type, user="admin"):
                arch = self._arch(model, view_type, xmlid)
                self.assertTrue(shown(arch, "//field[@name='%s']" % field))

    # ─── Шестерёнка ─────────────────────────────────────────────────────
    def _gear(self, model):
        """Пункты ⚙ — «Действия» и «Печать» (с шага З-2 спрятан и отчёт)."""
        bindings = self.env["ir.actions.actions"].with_user(self.admin).get_bindings(model)
        return {action["id"] for kind in ("action", "report") for action in bindings.get(kind, ())}

    def _hidden_actions(self):
        """xml-id → (действие, модель шестерёнки); снятые модули пропускаем."""
        found = {}
        for xmlid in HIDDEN_BINDINGS:
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action and action.binding_model_id:
                found[xmlid] = (action, action.binding_model_id.model)
        return found

    def test_gear_hidden(self):
        hidden = self._hidden_actions()
        self.assertGreaterEqual(len(hidden), 12, "Почти все модули-источники стоят и в тестовой базе.")
        for xmlid, (action, model) in hidden.items():
            with self.subTest(action=xmlid):
                self.assertNotIn(action.id, self._gear(model))

    def test_gear_neighbours_stay(self):
        neighbours = {
            "base.action_partner_merge": "res.partner",
            "purchase.action_confirm_rfqs": "purchase.order",
        }
        for xmlid, model in neighbours.items():
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if not action:
                continue
            with self.subTest(action=xmlid):
                self.assertIn(action.id, self._gear(model))

    def test_gear_reversible_by_group(self):
        hidden = self._hidden_actions()
        models = {model for _action, model in hidden.values()}
        before = {model: self._gear(model) for model in models}
        for group in (REMOVED, STOCK, MONEY):
            self._join(group)
        hidden_ids = {action.id for action, _model in hidden.values()}
        for model in models:
            after = self._gear(model)
            with self.subTest(model=model):
                self.assertLessEqual(before[model], after, "Группа ничего не убирает.")
                self.assertLessEqual(after - before[model], hidden_ids,
                                     "Группа возвращает только спрятанные пункты.")
        for xmlid, (action, model) in hidden.items():
            with self.subTest(back=xmlid):
                self.assertIn(action.id, self._gear(model))

    def test_gear_needs_its_own_group(self):
        """«Печать этикеток» — «Склад», «Акт сверки» — «Деньги»: «Убранное»
        их не возвращает."""
        self._join(REMOVED)
        hidden = self._hidden_actions()
        for xmlid, group in HIDDEN_BINDINGS.items():
            if group == REMOVED or xmlid not in hidden:
                continue
            action, model = hidden[xmlid]
            with self.subTest(action=xmlid):
                self.assertNotIn(action.id, self._gear(model))

    # ─── «Сводка» ───────────────────────────────────────────────────────
    def test_digest_off_once(self):
        params = self.env["ir.config_parameter"].sudo()
        digest = self.env.ref("digest.digest_digest_default")
        self.assertTrue(params.get_param(MARK), "Метка стоит после установки модуля.")
        self.assertEqual(digest.state, "deactivated")
        self.assertFalse(params.get_param("digest.default_digest_emails"))
        # Владелец включил обратно — деплой (повторный вызов) не трогает.
        digest.action_activate()
        params.set_param("digest.default_digest_emails", True)
        self.assertFalse(self.env["digest.digest"]._pmk_digest_off_once())
        self.assertEqual(digest.state, "activated")
        self.assertTrue(params.get_param("digest.default_digest_emails"))
        # Метку стёрли — следующий вызов снова выключает.
        params.set_param(MARK, False)
        self.assertTrue(self.env["digest.digest"]._pmk_digest_off_once())
        self.assertEqual(digest.state, "deactivated")
        self.assertTrue(params.get_param(MARK))

    def test_digest_data_is_function(self):
        """Выключение — вызовом метода, а не записью: <record> на штатную
        сводку при -u молча пропустился бы (noupdate) и не знал бы метки."""
        with file_open("pmk_theme/data/digest_off.xml", "rb") as f:
            root = etree.parse(f).getroot()
        calls = root.findall("function")
        self.assertEqual([(c.get("model"), c.get("name")) for c in calls],
                         [("digest.digest", "_pmk_digest_off_once")])
        self.assertFalse(root.findall("record"))

    # ─── «Мои предпочтения» ─────────────────────────────────────────────
    def test_prefs_view_active(self):
        for xmlid in ("pmk_theme.view_users_prefs_step29", "pmk_theme.view_users_prefs_hr_step29"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_prefs_calendar_and_api_keys(self):
        """Штатное окно (у человека нет карточки сотрудника) собирается от
        его имени — здесь работает groups=."""
        user = self._plain_user()
        xmlid = "base.view_users_form_simple_modif"
        with self.subTest(user="менеджер"):
            arch = self._arch("res.users", "form", xmlid, user=user)
            self.assertFalse(arch.xpath("//page[@name='calendar']"))
            tz = shown(arch, "//page[@name='preferences_page']//field[@name='tz']")
            self.assertEqual(len(tz), 1, "Часовой пояс — на «Предпочтениях».")
            self.assertTrue(arch.xpath("//page[@name='preferences_page']//field[@name='tz_offset']"))
            self.assertFalse(arch.xpath("//div[@name='api_keys']"),
                             "Ключи API — только администратору.")
            self.assertTrue(arch.xpath("//page[@name='page_security']"),
                            "Пароль и вход — на месте.")
        with self.subTest(user="admin"):
            arch = self._arch("res.users", "form", xmlid)
            self.assertTrue(arch.xpath("//div[@name='api_keys']"))
            self.assertFalse(arch.xpath("//page[@name='calendar']"))
        self._join(REMOVED)
        arch = self._arch("res.users", "form", xmlid)
        self.assertTrue(arch.xpath("//page[@name='calendar']"), "Календарь возвращается группой.")
        self.assertFalse(arch.xpath("//page[@name='calendar']//field[@name='tz']"),
                         "Часовой пояс остаётся на «Предпочтениях».")

    def _hr_window(self, user):
        """Окно «Мои предпочтения» человека с карточкой сотрудника — как его
        получает браузер: действие hr.action_get (в контексте — xml-id его
        групп) и разметка hr.res_users_view_form_preferences (hr собирает её
        от имени суперпользователя)."""
        if not user.employee_id:
            self.env["hr.employee"].create({"name": user.name, "user_id": user.id})
        action = self.env["res.users"].with_user(user).action_get()
        self.assertEqual(action["res_model"], "res.users")
        context = ast.literal_eval(action["context"])
        self.assertTrue(context.get("base.group_user"), "Предпосылка: hr кладёт группы в контекст.")
        arch = self._arch("res.users", "form", "hr.res_users_view_form_preferences", user=user)
        return arch, context

    def _visible(self, arch, expr, context):
        """Узел есть ровно один (сервер его не вырезал) — и виден ли он при
        этом контексте окна."""
        nodes = arch.xpath(expr)
        self.assertEqual(len(nodes), 1, "%s: узел должен приходить всем, прячет invisible." % expr)
        invisible = nodes[0].get("invisible")
        return not (invisible and safe_eval(invisible, {"context": context}))

    def test_prefs_hr_window(self):
        """Окно hr: groups= там сверялись бы с группами суперпользователя
        (ключи API — всем, календарь — никому), поэтому скрытие — по
        контексту окна."""
        if not self.env.ref("hr.res_users_view_form_preferences", raise_if_not_found=False):
            self.skipTest("hr не установлен")
        user = self._plain_user()
        arch, context = self._hr_window(user)
        tz = shown(arch, "//page[@name='preferences_page']//field[@name='tz']")
        self.assertEqual(len(tz), 1, "Часовой пояс — на «Предпочтениях».")
        self.assertFalse(arch.xpath("//page[@name='calendar']//field[@name='tz']"))
        self.assertFalse(self._visible(arch, "//page[@name='calendar']", context))
        self.assertFalse(self._visible(arch, "//div[@name='api_keys']", context),
                         "Ключи API — только администратору.")
        self.assertTrue(arch.xpath("//page[@name='page_security']"), "Пароль и вход — на месте.")
        arch, context = self._hr_window(self.admin)
        self.assertTrue(self._visible(arch, "//div[@name='api_keys']", context))
        self.assertFalse(self._visible(arch, "//page[@name='calendar']", context))
        self._join(REMOVED)
        arch, context = self._hr_window(self.admin)
        self.assertTrue(self._visible(arch, "//page[@name='calendar']", context),
                        "Календарь возвращается группой и в окне hr.")

    # ─── Лента ──────────────────────────────────────────────────────────
    def _paths(self, bundle="web.assets_backend"):
        return [entry[0].lstrip("/") for entry in self.env["ir.asset"]._get_asset_paths(bundle, {})]

    def test_hidden_scss_live_after_dark(self):
        record = self.env.ref("pmk_theme.asset_scss_hidden")
        self.assertTrue(record.active)
        self.assertEqual(record.sequence, 43)
        paths = self._paths()
        self.assertIn(SCSS + "hidden.scss", paths)
        self.assertLess(paths.index(SCSS + "dark.scss"), paths.index(SCSS + "hidden.scss"))
        # Признак модели на корне ленты — из нашего шаблона: без него
        # правила не сработают.
        self.assertIn("pmk_theme/static/src/xml/chatter.xml", paths)

    def test_backend_css_with_hidden_rules(self):
        """Сборка в состоянии стенда (живые файлы темы + hidden.scss)
        компилируется одним источником, правила ленты в ней есть."""
        theme = self.env["ir.asset"].search([("path", "=like", "pmk_theme/static/src/%")])
        theme.filtered(lambda a: a.path not in LIVE_THEME_PATHS).active = False
        bundle = self.env["ir.qweb"]._get_asset_bundle("web.assets_backend", js=False)
        css = re.sub(r"\s+", " ", bundle.preprocess_css())
        self.assertFalse(bundle.css_errors, bundle.css_errors)
        for model in ("pmk.metal.spec", "pmk.dobor.order", "pmk.cut.plan", "pmk.laser.job",
                      "product.template", "product.product"):
            for cls in ("o-mail-Chatter-sendMessage", "o-mail-Followers"):
                with self.subTest(model=model, button=cls):
                    self.assertIn('.o-mail-Chatter[data-pmk-model="%s"] .%s' % (model, cls), css)
        self.assertIn('.o-mail-Chatter[data-pmk-model^="stock."] .o-mail-Chatter-sendMessage', css)
        # «Задачи» на складе не прячем — их судьбу разбор оставил открытой.
        self.assertNotIn('[data-pmk-model^="stock."] .o-mail-Chatter-activity', css)
        # «SMS» у телефона (кнопка модуля sms) — во всех формах и списках.
        self.assertRegex(css, r"\.o_field_phone_sms ?\{ ?display: ?none ?!important;? ?\}")
