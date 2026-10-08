# -*- coding: utf-8 -*-
"""Пустые экраны, разбор UX, шаг 26: что доезжает до браузера.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py).

Что ловим:
  • подсказка штатных экранов — наша, и по-английски, и по-русски (поле help
    переводимое: запись XML поверх штатной сменила бы только en_US);
  • приёмки, отгрузки и перемещения — наши по ЛЮБОМУ пути: из меню и из
    карточек «Склад → Обзор операций» (stock.picking.type._get_action рисует
    шаблон stock.help_message_template уже после _for_xml_id); без
    «Установите приложение штрихкодов» и без кнопок purchase_stock/sale_stock;
  • карточки «Производство» и «Ремонты» в «Обзоре операций» — тоже наши;
  • у «Сотрудников» больше нет кнопки «Загрузить пример данных»;
  • в подсказках ни слова латиницей и ни одной картинки;
  • соседние действия, которых нет в списке, не тронуты;
  • демо-строк нет ни у одного вида: атрибут sample снят у собранной
    разметки, включая расширение mrp, которое дописывает его само;
  • шаблон с видео и BillGuide — в бандле; стили — в живом scss.

Как подсказка выглядит (бледно, по центру, в тёмной теме) — глазами, это
делает основной агент.
"""
import re

from lxml import etree

from odoo.tests import TransactionCase, tagged

from odoo.addons.pmk_theme.models.ir_actions_act_window import EMPTY_HELP

LATIN = re.compile(r"[A-Za-z]")
TAGS = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")

# Шаблон склада (views/stock_empty_help.xml): код типа операции → строки.
PICKING_LINES = {
    "incoming": [
        "Приёмка появится, когда заявка поставщику станет заказом — кнопка «Подтвердить заказ».",
        "Металл на складе в системе пока не учитывается.",
    ],
    "outgoing": ["Отгрузки пока ведутся в МоёмСкладе."],
    "internal": [
        "По выбранным фильтрам перемещений нет.",
        "Металл на складе в системе пока не учитывается.",
    ],
    False: ["По выбранным фильтрам операций нет."],
}


def lines(help_html):
    """Текст абзацев подсказки — без разметки и отступов шаблона."""
    root = etree.fromstring("<div>%s</div>" % help_html)
    return [SPACES.sub(" ", "".join(p.itertext())).strip() for p in root.iter("p")]


@tagged("post_install", "-at_install")
class TestEmptyScreensStep26(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("ru_RU")
        cls.Action = cls.env["ir.actions.act_window"]

    def _help(self, xmlid, lang=None):
        Action = self.Action.with_context(lang=lang) if lang else self.Action
        return Action._for_xml_id(xmlid)["help"]

    # ─── Подсказки ──────────────────────────────────────────────────────
    def test_help_replaced(self):
        for xmlid, text in EMPTY_HELP.items():
            for lang in ("en_US", "ru_RU"):
                with self.subTest(action=xmlid, lang=lang):
                    self.assertEqual(self._help(xmlid, lang), text)

    def test_help_replaced_via_menu_load(self):
        """Меню грузит действие по номеру (/web/action/load → _get_action_dict
        на sudo), а не по xml-id — подсказка та же."""
        for xmlid in ("sale.action_quotations_with_onboarding", "stock.stock_quant_action"):
            with self.subTest(action=xmlid):
                action = self.env.ref(xmlid).sudo().with_context(lang="ru_RU")
                self.assertEqual(action._get_action_dict()["help"], EMPTY_HELP[xmlid])

    # ─── Склад: шаблон stock.help_message_template ──────────────────────
    def _assert_picking_help(self, help_html, code):
        self.assertEqual(lines(help_html), PICKING_LINES[code], help_html)
        text = TAGS.sub("", str(help_html))
        self.assertFalse(LATIN.search(text), text)
        self.assertNotIn("штрих", text.lower())
        for trace in ("action_install_barcode", "<a", "<img", "btn", "o_view_nocontent"):
            self.assertNotIn(trace, str(help_html))

    def test_picking_template_ours(self):
        """Наследник с приоритетом 99 — применяется после purchase_stock и
        sale_stock и снимает и их кнопки «Заказы на покупку/продажу»."""
        view = self.env.ref("pmk_theme.stock_help_message")
        self.assertTrue(view.active)
        self.assertEqual(view.inherit_id, self.env.ref("stock.help_message_template"))
        self.assertEqual(view.priority, 99)
        View = self.env["ir.ui.view"]
        for lang in ("en_US", "ru_RU"):
            for code in PICKING_LINES:
                with self.subTest(lang=lang, code=code):
                    self._assert_picking_help(View.with_context(lang=lang)._render_template(
                        "stock.help_message_template", {"picking_type_code": code}), code)

    def test_picking_help_via_menu(self):
        """Меню: read() → stock.picking.get_empty_list_help с контекстом
        действия (restricted_picking_type_code)."""
        for xmlid, code in (("stock.action_picking_tree_incoming", "incoming"),
                            ("stock.action_picking_tree_outgoing", "outgoing"),
                            ("stock.action_picking_tree_internal", "internal"),
                            ("stock.action_picking_tree_all", False)):
            with self.subTest(action=xmlid):
                self.assertNotIn(xmlid, EMPTY_HELP, "Тексты склада — в шаблоне, не в словаре.")
                self._assert_picking_help(self._help(xmlid, "ru_RU"), code)

    def test_picking_help_via_overview_cards(self):
        """«Склад → Обзор операций»: заголовок карточки и её кнопки идут через
        stock.picking.type._get_action — шаблон рисуется ПОСЛЕ _for_xml_id и
        раньше затирал нашу подсказку рекламой штрихкодов."""
        methods = ("get_stock_picking_action_picking_type", "get_action_picking_tree_ready",
                   "get_action_picking_tree_waiting", "get_action_picking_tree_late",
                   "get_action_picking_tree_backorder", "get_action_picking_type_ready_moves")
        for xmlid, code in (("stock.picking_type_in", "incoming"),
                            ("stock.picking_type_out", "outgoing"),
                            ("stock.picking_type_internal", "internal")):
            picking_type = self.env.ref(xmlid, raise_if_not_found=False)
            for method in methods:
                with self.subTest(card=xmlid, method=method):
                    if not picking_type:
                        self.skipTest(xmlid)
                    self.assertEqual(picking_type.code, code)
                    action = getattr(picking_type.with_context(lang="ru_RU"), method)()
                    self._assert_picking_help(action["help"], code)

    def test_picking_help_via_picking_model(self):
        """Щелчок по графику карточки и прямые вызовы stock.picking._get_action."""
        Picking = self.env["stock.picking"].with_context(lang="ru_RU")
        for method, code in (("get_action_picking_tree_incoming", "incoming"),
                             ("get_action_picking_tree_outgoing", "outgoing"),
                             ("get_action_picking_tree_internal", "internal")):
            with self.subTest(method=method):
                self._assert_picking_help(getattr(Picking, method)()["help"], code)

    def test_mrp_repair_overview_cards(self):
        """Карточки «Производство» и «Ремонты» открывают свои действия через
        _for_xml_id — подсказка та же, что из меню."""
        Type = self.env["stock.picking.type"].with_context(lang="ru_RU")
        cases = (
            ("get_mrp_stock_picking_action_picking_type", "mrp_operation",
             "mrp.mrp_production_action_picking_deshboard", "mrp.mrp_production_action"),
            ("get_repair_stock_picking_action_picking_type", "repair_operation",
             "repair.action_picking_repair", "repair.action_repair_order_tree"),
        )
        for method, code, card_xmlid, menu_xmlid in cases:
            with self.subTest(card=card_xmlid):
                if not hasattr(Type, method):
                    self.skipTest(method)
                picking_type = Type.search([("code", "=", code)], limit=1)
                help_html = getattr(picking_type, method)()["help"]
                self.assertEqual(help_html, EMPTY_HELP[card_xmlid])
                self.assertEqual(EMPTY_HELP[card_xmlid], EMPTY_HELP[menu_xmlid])

    def test_employees_no_demo_button(self):
        """Штатная подсказка «Сотрудников» несла кнопку «Загрузить пример
        данных» — она заливает демо-сотрудников в боевую базу."""
        help_html = self._help("hr.open_view_employee_list_my", "ru_RU")
        self.assertNotIn("action_hr_employee_load_demo_data", help_html)
        self.assertNotIn("button", help_html)

    def test_help_texts_are_ours(self):
        """Ни латиницы (ни «Odoo», ни адресов-шлюзов), ни картинок: только
        абзацы, первая строка — что с экраном, вторая — куда идти."""
        self.assertGreaterEqual(len(EMPTY_HELP), 26)
        for xmlid, text in EMPTY_HELP.items():
            with self.subTest(action=xmlid):
                self.assertFalse(LATIN.search(TAGS.sub("", text)), text)
                self.assertNotIn("@", text)
                self.assertNotIn("class=", text)
                paragraphs = text.count("<p>")
                self.assertTrue(1 <= paragraphs <= 2, "Одна-две строки: %s" % text)

    def test_every_action_exists(self):
        """Опечатка в xml-id молча оставила бы штатную рекламу на месте."""
        for xmlid in EMPTY_HELP:
            with self.subTest(action=xmlid):
                action = self.env.ref(xmlid, raise_if_not_found=False)
                self.assertTrue(action, xmlid)
                self.assertEqual(action._name, "ir.actions.act_window")

    def test_other_actions_untouched(self):
        """Действие не из списка отдаёт свой help, как раньше."""
        xmlid = "contacts.action_contacts"
        self.assertNotIn(xmlid, EMPTY_HELP)
        # read() без списка полей — как в ядре (_get_action_dict): help
        # проходит get_empty_list_help с контекстом самого действия.
        expected = self.env.ref(xmlid).sudo().read()[0]["help"]
        self.assertTrue(expected)
        self.assertEqual(self._help(xmlid), expected)

    # ─── Демо-строки ────────────────────────────────────────────────────
    def test_no_sample_in_any_view(self):
        """Ни один вид не отдаёт браузеру sample: под пустым экраном нет
        размытых строк с чужими суммами."""
        views = self.env["ir.ui.view"].search([
            ("type", "in", ("list", "kanban", "graph", "pivot")),
            ("mode", "=", "primary"),
            ("arch_db", "ilike", "sample"),
        ])
        self.assertGreater(len(views), 20, "На стенде таких видов больше сотни.")
        checked = 0
        for view in views:
            if view.model not in self.env:
                continue
            with self.subTest(view=view.xml_id or view.id):
                arch = self.env[view.model].get_view(view.id, view.type)["arch"]
                self.assertIsNone(etree.fromstring(arch).get("sample"))
                checked += 1
        self.assertGreater(checked, 20)

    def test_no_sample_from_extension(self):
        """mrp дописывает sample расширением к виду рабочих заданий —
        снимаем и его (собранная разметка, а не исходная)."""
        view = self.env.ref("mrp.mrp_production_workorder_tree_view", raise_if_not_found=False)
        if not view:
            self.skipTest("mrp без вида рабочих заданий")
        arch = self.env[view.model].get_view(view.id, view.type)["arch"]
        self.assertIsNone(etree.fromstring(arch).get("sample"))

    def test_main_empty_screens_no_sample(self):
        """Те, что видны из меню: первый вид действия без sample."""
        for xmlid in ("sale.action_quotations_with_onboarding", "stock.stock_quant_action",
                      "mrp.mrp_workorder_todo", "maintenance.hr_equipment_request_action",
                      "account.action_move_in_invoice", "hr.open_view_employee_list_my"):
            with self.subTest(action=xmlid):
                action = self.Action._for_xml_id(xmlid)
                view_id, view_type = action["views"][0]
                res = self.env[action["res_model"]].get_views([(view_id, view_type)])
                arch = etree.fromstring(res["views"][view_type]["arch"])
                self.assertIsNone(arch.get("sample"))

    # ─── Клиентская часть ───────────────────────────────────────────────
    def _paths(self, bundle="web.assets_backend"):
        return [entry[0].lstrip("/") for entry in self.env["ir.asset"]._get_asset_paths(bundle, {})]

    def test_template_in_bundle(self):
        paths = self._paths()
        ours = "pmk_theme/static/src/xml/empty_screens.xml"
        self.assertIn(ours, paths)
        # Расширения чужих шаблонов — после самих шаблонов.
        for core in ("sale/static/src/js/sale_action_helper/sale_action_helper.xml",
                     "account/static/src/views/account_upload_list/account_upload_list_renderer.xml"):
            with self.subTest(template=core):
                self.assertIn(core, paths)
                self.assertLess(paths.index(core), paths.index(ours))

    def test_styles_in_live_files(self):
        """Стиль подсказки — в живых scss (forms_nexus, dark): остальные
        файлы темы на стенде выключены (ir.asset active=False)."""
        paths = self._paths()
        for name in ("forms_nexus.scss", "dark.scss"):
            with self.subTest(file=name):
                self.assertIn("pmk_theme/static/src/scss/" + name, paths)
