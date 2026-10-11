# -*- coding: utf-8 -*-
"""Плоско на бежевом: шапка и состав документа в рамках (разбор UX, шаг 52,
11.10.2026) — что доезжает до браузера и до вида.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py):
  odoo -d pmk52_test -i pmk_theme,pmk_deal,pmk_org,pmk_tech,pmk_cut,pmk_laser,theme_nexus --test-enable \
       --test-tags /pmk_theme:TestStep52Flat,/pmk_theme:TestStep49bAside,/pmk_theme:TestStep49Width,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme:TestStep39Words,/pmk_deal,/pmk_org,/pmk_laser,/pmk_tech \
       --stop-after-init --http-port 8099

Вид (шапка одной карточкой со строкой кнопок, ярлыки на бежевом, вкладка
карточкой, таблица своей рамкой и шире на ~68 px, подписи колонок
вентзонтов в одну строку; обе темы; 1440 и 1366; все вкладки) смотрит
основной агент глазами на копии. Здесь — то, что ломается молча:
  • раздел лёг в выключенный файл темы или не в конец файла;
  • правило вне @media screen и (min-width: 768px) — задело телефон или
    печать; правило без .o_action_manager — задело окна-диалоги; правило без
    pmk-doc-top — задело формы без обёртки шапки;
  • min()/max() — libsass Odoo роняет весь бандл (calc() — можно, им пользуется и ядро); :has() в :has() —
    браузер отбрасывает правило; яркий лайм;
  • правило слабее чужой темы (лист, строка кнопок, рамка таблицы — с
    !important) или ядра (отрицательные поля вкладки и таблицы);
  • обёртка шапки не собралась: xpath наследника промахнулся, узел шапки
    остался над рамкой, вкладки уехали внутрь рамки;
  • ядро переименовало то, на чём держатся правила (лист, строка кнопок,
    shadow-sm прилипшей строки, переменные полей листа и вкладок).
"""
import re

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open

from odoo.addons.pmk_theme.tests.test_step30_highlights import (
    DEAD_THEME_PATHS,
    LIVE_THEME_PATHS,
    _media_blocks,
    _read,
    _rules,
)
from odoo.addons.pmk_theme.tests.test_step40_dark import BRIGHT_LIME, _specificity
from odoo.addons.pmk_theme.tests.test_step48_header import _strip_media

SCSS = "pmk_theme/static/src/scss/"
FORMS_SCSS = SCSS + "forms_nexus.scss"
OLD_FORMS_SCSS = SCSS + "forms.scss"
DARK_SCSS = SCSS + "dark.scss"
STEP_MARK = "// ═══ Шаг 52"
MEDIA = "@media screen and (min-width: 768px)"

AM = ".o_action_manager .o_form_view "
SHEET = AM + ".o_form_sheet_bg > .o_form_sheet:has(> .pmk-doc-top)"
TOP = AM + ".o_form_sheet > .pmk-doc-top"
BAR = AM + ".o_form_sheet_bg:has(> .o_form_sheet > .pmk-doc-top) > .o_form_statusbar"
BAR_SEAM = AM + ".o_form_sheet_bg > .o_form_statusbar:has(+ .o_form_sheet > .pmk-doc-top)"
TOP_SEAM = AM + ".o_form_sheet_bg > .o_form_statusbar + .o_form_sheet > .pmk-doc-top"
BAR_PINNED = AM + ".o_form_sheet_bg > .o_form_statusbar.shadow-sm:has(+ .o_form_sheet > .pmk-doc-top)"
NOTEBOOK = AM + ".o_form_sheet:has(> .pmk-doc-top) > .o_notebook"
TAB_CARD = NOTEBOOK + " > .o_notebook_content"
ONE_TABLE = ":has(> .tab-pane > .o_field_widget:only-child > .o_field_x2many_list)"
TAB_BARE = TAB_CARD + ONE_TABLE
FLOW = NOTEBOOK + " .o_pmk_flow:not(.o_pmk_flow--page) .o_pmk_flow_scroll"
TABLE = AM + ".o_form_sheet:has(> .pmk-doc-top) .o_field_x2many_list > .o_list_renderer"
KPI = AM + ".o_form_sheet > .pmk-doc-top .pmk-kpi__card"
# 52.7 (осмотр 11.10): линия раздела во всю ширину группы — по отступу карточки.
SEPARATOR = AM + ".o_form_sheet:has(> .pmk-doc-top) .o_notebook_content .o_group.row > .o_horizontal_separator"

DARK = "body.o_nexus_dark "
CARD_BG = "var(--pmk-surface, #fff)"
CARD_LINE = "1px solid var(--pmk-border, #e3e4e8)"

# Формы документов с обёрткой: (модель, xmlid вида, модуль-владелец обёртки,
# узлы, которые обязаны лежать в рамке). Модули вне зависимостей pmk_theme
# (pmk_cut, pmk_laser, pmk_orders) — если стоят.
FORMS = (
    ("pmk.metal.spec", "pmk_calc.view_metal_spec_form",
     ("div[contains(concat(' ', @class, ' '), ' pmk-spec-title ')]",
      "div[@name='pmk_layout_stale']", "div[contains(concat(' ', @class, ' '), ' pmk-doc-head ')]")),
    ("pmk.dobor.order", "pmk_calc.view_dobor_order_form",
     ("div[contains(concat(' ', @class, ' '), ' oe_title ')]",
      "div[contains(concat(' ', @class, ' '), ' pmk-doc-head ')]")),
    ("pmk.vent.hood.order", "pmk_calc.view_vent_hood_order_form",
     ("div[contains(concat(' ', @class, ' '), ' oe_title ')]",
      "div[contains(concat(' ', @class, ' '), ' alert-danger ')]",
      "div[contains(concat(' ', @class, ' '), ' pmk-doc-head ')]")),
    ("crm.lead", "crm.crm_lead_view_form",
     ("div[contains(concat(' ', @class, ' '), ' oe_title ')]",
      "group/group[label[@for='date_deadline']]", "div[field[@name='lead_properties']]")),
    ("sale.order", "sale.view_order_form",
     ("div[contains(concat(' ', @class, ' '), ' oe_title ')]", "group[@name='sale_header']")),
    ("purchase.order", "purchase.purchase_order_form",
     ("div[contains(concat(' ', @class, ' '), ' oe_title ')]", "group")),
    ("res.partner", "base.view_partner_form",
     ("div[contains(concat(' ', @class, ' '), ' mb8 ')]",)),
    ("project.task", "project.view_task_form2",
     ("div[contains(concat(' ', @class, ' '), ' justify-content-between ')]", "group",
      "field[@name='task_properties']")),
    ("project.task", "pmk_orders.view_task_order_form",
     ("div[contains(concat(' ', @class, ' '), ' oe_title ')]", "group[@name='pmk_order_main']",
      "group[@name='pmk_order_shop']", "group[@name='pmk_order_note']")),
    ("pmk.cut.plan", "pmk_cut.view_cut_plan_form",
     ("div[contains(concat(' ', @class, ' '), ' oe_title ')]",
      "div[contains(concat(' ', @class, ' '), ' pmk-doc-head ')]")),
    ("pmk.laser.job", "pmk_laser.view_laser_job_form",
     ("div[contains(concat(' ', @class, ' '), ' oe_title ')]",
      "div[@class='pmk-job-signals']", "div[@name='pmk_job_metal']")),
)


def _section(source):
    """Раздел «Шаг 52» — до следующего «// ═══» или до конца файла."""
    start = source.find(STEP_MARK)
    assert start != -1, "раздела шага 52 нет"
    end = source.find("// ═══", start + 1)
    return source[start:end if end != -1 else None]


def _code(source):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", source, flags=re.S))


def _compile(source):
    import sass

    return re.sub(r"\s+", " ", sass.compile(string=source))


def _hidden(node):
    return (node.tag == "field" and node.get("invisible") in ("1", "True")) or \
        node.get("name") == "button_box" or node.get("name") == "web_ribbon"


@tagged("post_install", "-at_install")
class TestStep52Flat(TransactionCase):

    _backend_css_cache = None

    # ─── Исходник ──────────────────────────────────────────────────────
    def test_section_in_live_files(self):
        self.assertIn(FORMS_SCSS, LIVE_THEME_PATHS)
        self.assertIn(DARK_SCSS, LIVE_THEME_PATHS)
        self.assertIn(OLD_FORMS_SCSS, DEAD_THEME_PATHS)
        for path in (FORMS_SCSS, DARK_SCSS):
            source = _read(path)
            with self.subTest(path=path):
                start = source.index(STEP_MARK)
                self.assertEqual(source.count(STEP_MARK), 1)
                # Ниже шага 52 — только более поздние разделы (11.10: «Лента
                # документа в рамке»), старые правила его не перебивают.
                later = source.find("// ═══", start + 1)
                if later != -1:
                    self.assertIn("Лента документа в рамке", source[later:later + 80],
                                  "Ниже шага 52 — только разделы новее него.")
        forms = _read(FORMS_SCSS)
        self.assertLess(forms.index("// ═══ Шаг 49Б"), forms.index(STEP_MARK))
        self.assertNotIn("Шаг 52", _read(OLD_FORMS_SCSS), "forms.scss выключен — правка туда не доедет.")
        assets = self.env["ir.asset"].search([("path", "in", [FORMS_SCSS, DARK_SCSS])])
        self.assertEqual(set(assets.mapped("path")), {FORMS_SCSS, DARK_SCSS})
        self.assertTrue(all(assets.mapped("active")), "Живые файлы темы включены.")

    def test_section_source(self):
        for path in (FORMS_SCSS, DARK_SCSS):
            code = _code(_section(_read(path)))
            with self.subTest(path=path):
                self.assertEqual(code.count("@media"), 1)
                self.assertIn(MEDIA, code)
                for banned in ("min(", "max(", "grid-column", "grid-template-columns",
                               "white-space", "rgb", "hsl"):
                    self.assertNotIn(banned, code, "libsass и сетка формы — грабли (см. раздел).")
                lower = code.lower()
                for lime in BRIGHT_LIME:
                    self.assertNotIn(lime, lower)

    # ─── Раздел отдельно ───────────────────────────────────────────────
    def test_light_rules(self):
        css = _compile(_section(_read(FORMS_SCSS)))
        self.assertFalse(_rules(_strip_media(css)), "Вне @media правил нет — телефон и печать не задеты.")
        rules = _rules(_media_blocks(css, MEDIA))
        self.assertEqual(set(rules), {SHEET, TOP, TOP + ":last-child", BAR, BAR_SEAM, TOP_SEAM, BAR_PINNED,
                                      NOTEBOOK, NOTEBOOK + " > .o_notebook_headers .nav", TAB_CARD,
                                      TAB_CARD + " > .tab-pane", TAB_BARE, FLOW, TABLE, KPI, SEPARATOR})
        for selector in rules:
            with self.subTest(selector=selector):
                self.assertTrue(selector.startswith(".o_action_manager "), "Только основное окно, не диалоги.")
                self.assertIn("pmk-doc-top", selector, "Только формы с обёрткой шапки.")
                self.assertNotRegex(selector, r":has\([^)]*:has\(", ":has() в :has() браузер отбрасывает.")

        self.assertEqual(rules[SHEET], {
            "--formView-sheet-padding-x": "0px", "--formView-sheet-padding-y": "0px",
            "padding": "0 !important", "background": "transparent !important",
            "border": "0 !important", "border-radius": "0 !important", "box-shadow": "none !important",
        })
        self.assertEqual(rules[TOP], {"margin": "0 0 16px", "padding": "16px 20px 12px",
                                      "background": CARD_BG, "border": CARD_LINE, "border-radius": "10px"})
        self.assertEqual(rules[BAR]["border"], CARD_LINE + " !important")
        self.assertEqual(rules[BAR]["background"], CARD_BG + " !important")
        self.assertEqual(rules[BAR]["margin-inline"], "0")
        self.assertEqual(rules[BAR_SEAM], {"margin-bottom": "0", "border-radius": "10px 10px 0 0"})
        self.assertEqual(rules[TOP_SEAM], {"border-top": "0", "border-radius": "0 0 10px 10px"})
        self.assertEqual(rules[BAR_PINNED], {"border-radius": "10px"})
        self.assertEqual(rules[SEPARATOR], {"width": "calc(100% - 32px)", "margin-inline": "16px",
                                            "padding-inline": "0"})
        self.assertEqual(rules[TAB_CARD]["margin-top"], "12px", "12 от ярлыков вкладок.")
        self.assertEqual(rules[TAB_CARD]["border"], CARD_LINE)
        self.assertEqual(rules[TAB_BARE], {"padding": "0", "background": "transparent", "border": "0",
                                           "border-radius": "0"}, "Одна таблица — своей рамкой.")
        self.assertEqual(rules[FLOW], {"border": "0", "border-radius": "0"})
        self.assertEqual(rules[TABLE], {"--ListRenderer-table-padding-x": "12px !important",
                                        "margin": "0 !important", "border": CARD_LINE + " !important",
                                        "border-radius": "10px"})
        self.assertEqual(rules[KPI], {"border-radius": "10px"})
        # рамка — как у состава (образец, pmk_calc dobor_builder.scss)
        with file_open("pmk_calc/static/src/scss/dobor_builder.scss") as f:
            self.assertIn("border: 1px solid var(--pmk-border, #e3e4e8);", f.read())

    def test_weights(self):
        """Чужая тема: лист .o_form_sheet (0,1,0) и тёмный (0,2,1) с !important,
        строка кнопок (0,1,0) и тёмная (0,2,1) с !important; ядро: строка
        кнопок .o_form_view .o_form_statusbar (0,2,0), первая таблица вкладки
        (0,9,0). Шов строки и шапки — сильнее общих правил строки и шапки."""
        self.assertGreater(_specificity(SHEET), (0, 2, 1))
        self.assertGreater(_specificity(BAR), (0, 2, 1))
        self.assertGreater(_specificity(TABLE), (0, 2, 1))
        self.assertGreaterEqual(_specificity(BAR_SEAM), _specificity(BAR))
        self.assertGreater(_specificity(TOP_SEAM), _specificity(TOP))
        self.assertGreater(_specificity(TAB_BARE), _specificity(TAB_CARD))
        self.assertGreater(_specificity(TAB_CARD), (0, 3, 0), "ядро: .o_form_view .o_notebook > .tab-content")
        self.assertGreater(_specificity(TAB_CARD + " > .tab-pane"), (0, 4, 0))
        self.assertGreater(_specificity(FLOW), _specificity(".o_pmk_flow_scroll"))

    def test_dark_rules(self):
        css = _compile(_section(_read(DARK_SCSS)))
        self.assertFalse(_rules(_strip_media(css)))
        rules = _rules(_media_blocks(css, MEDIA))
        for selector in rules:
            with self.subTest(selector=selector):
                self.assertTrue(selector.startswith(DARK + ".o_action_manager "))
                self.assertIn("pmk-doc-top", selector)
        self.assertEqual(rules[DARK + TOP], {"background": "var(--pmk-surface)", "border-color": "var(--pmk-border)"})
        self.assertEqual(rules[DARK + BAR], {"background": "var(--pmk-surface) !important",
                                             "border-color": "var(--pmk-border) !important"})
        self.assertEqual(rules[DARK + TABLE], {"border-color": "var(--pmk-border) !important"})
        # сильнее тёмной чужой темы и своего светлого правила
        for light in (BAR, TABLE):
            self.assertGreater(_specificity(DARK + light), _specificity(light))
        for vendor in (".o_form_statusbar", ".o_list_renderer", ".o_form_sheet"):
            self.assertGreater(_specificity(DARK + BAR), _specificity(DARK + vendor))
        # словарь тёмной темы задаёт переменные, на которых стоят светлые правила
        dark = _read(DARK_SCSS)
        self.assertIn("--pmk-surface: #1e2025;", dark)
        self.assertIn("--pmk-border: #33363d;", dark)

    # ─── Договор с ядром и чужой темой ─────────────────────────────────
    def test_core_contract(self):
        checks = {
            "web/static/src/views/form/form_compiler.js": (
                'sheetBG.className = "o_form_sheet_bg"', 'sheetFG.className = "o_form_sheet position-relative"',
                "'shadow-sm': __comp__.state.isStatusbarStickyPinned",
                # узлы до <sheet> (строка кнопок, плашки) ядро кладёт в подложку перед листом
                "compiled.prepend(...compiledList)"),
            "web/static/src/views/form/form_controller.scss": (
                "--formView-sheet-padding-x", "--Notebook-margin-x: calc(var(--formView-sheet-padding-x) * -1)",
                "--ListRenderer-table-padding-x: var(--Notebook-padding-x)", "position: sticky"),
            "web/static/src/core/notebook/notebook.xml": ("o_notebook_content tab-content", "tab-pane active"),
            "web/static/src/views/fields/x2many/x2many_field.js": ("o_field_x2many_${this.props.viewMode}",),
            "theme_nexus/static/src/scss/forms.scss": ("padding: 26px 30px !important",),
            "pmk_flow/static/src/flow_map.xml": ("o_pmk_flow--page", "o_pmk_flow_scroll"),
        }
        for path, needles in checks.items():
            try:
                with file_open(path) as f:
                    source = f.read()
            except FileNotFoundError:
                if path.startswith(("theme_nexus/", "pmk_flow/")):
                    continue
                raise
            for needle in needles:
                with self.subTest(path=path, needle=needle):
                    self.assertIn(needle, source)

    # ─── Сборка ────────────────────────────────────────────────────────
    def _backend_css(self):
        cls = type(self)
        if cls._backend_css_cache is None:
            theme = self.env["ir.asset"].search([("path", "=like", "pmk_theme/static/src/%")])
            theme.filtered(lambda a: a.path in DEAD_THEME_PATHS).active = False
            live = set(theme.filtered("active").mapped("path"))
            self.assertTrue(LIVE_THEME_PATHS <= live, live)
            bundle = self.env["ir.qweb"]._get_asset_bundle("web.assets_backend", js=False)
            css = bundle.preprocess_css()
            self.assertFalse(bundle.css_errors, bundle.css_errors)
            css = re.sub(r"\s*([{}])\s*", r" \1 ", css)
            cls._backend_css_cache = re.sub(r"\s+", " ", css)
        return cls._backend_css_cache

    def test_backend_bundle(self):
        rules = _rules(_media_blocks(self._backend_css(), MEDIA))
        for selector in (SHEET, TOP, BAR, BAR_SEAM, TOP_SEAM, BAR_PINNED, TAB_CARD, TAB_BARE, TABLE,
                         DARK + TOP, DARK + BAR, DARK + TABLE):
            with self.subTest(selector=selector):
                self.assertIn(selector, rules)

    # ─── Виды: обёртка шапки ───────────────────────────────────────────
    def _arch(self, model, xmlid):
        view = self.env.ref(xmlid, raise_if_not_found=False)
        if view is None or model not in self.env:
            return None
        return etree.fromstring(self.env[model].get_views([(view.id, "form")])["views"]["form"]["arch"])

    def test_forms_wrapped(self):
        checked = 0
        for model, xmlid, inside in FORMS:
            arch = self._arch(model, xmlid)
            if arch is None:
                continue
            checked += 1
            with self.subTest(form=xmlid):
                sheet = arch.find("sheet")
                tops = sheet.xpath("div[@name='pmk_doc_top']")
                self.assertEqual(len(tops), 1, "Ровно одна рамка шапки — прямо в листе.")
                top = tops[0]
                self.assertIn("pmk-doc-top", (top.get("class") or "").split())
                self.assertEqual(len(arch.xpath("//div[@name='pmk_doc_top']")), 1)
                for path in inside:
                    self.assertTrue(top.xpath(path), "В рамке: %s" % path)
                # Выше вкладок / таблицы — ничего видимого, кроме рамки:
                # кнопки-счётчики уходят в строку пути, ленты — поверх листа.
                rows = [c for c in sheet if isinstance(c.tag, str) and not _hidden(c)]
                self.assertIs(rows[0], top, [c.get("class") or c.tag for c in rows])
                notebook = sheet.find("notebook")
                if notebook is not None:
                    self.assertLess(rows.index(top), rows.index(notebook), "Вкладки — после рамки, не в ней.")
                    self.assertIsNone(top.find(".//notebook"))
        self.assertGreaterEqual(checked, 8, "Основные документы на месте.")

    def test_purchase_alerts_inside(self):
        """Плашки заявки на металл (pmk_tech) — в рамке, перед номером."""
        arch = self._arch("purchase.order", "purchase.purchase_order_form")
        if not arch.xpath("//div[@name='pmk_no_supplier']"):
            self.skipTest("pmk_tech не установлен")
        top = arch.find("sheet/div[@name='pmk_doc_top']")
        names = [c.get("name") or c.get("class") for c in top if isinstance(c.tag, str)]
        title = [i for i, c in enumerate(top) if "oe_title" in (c.get("class") or "")][0]
        for name in ("pmk_no_supplier", "pmk_pending_lines"):
            with self.subTest(alert=name):
                self.assertIn(name, names)
                self.assertLess(top.index(top.find("div[@name='%s']" % name)), title)

    def test_views_active(self):
        for xmlid in ("pmk_theme.view_crm_lead_form_doc_top", "pmk_theme.view_sale_order_form_doc_top",
                      "pmk_theme.view_purchase_order_form_doc_top", "pmk_theme.view_partner_form_doc_top",
                      "pmk_theme.view_task_form2_doc_top"):
            with self.subTest(view=xmlid):
                view = self.env.ref(xmlid)
                self.assertTrue(view.active, "Вид не выключен при загрузке.")
                self.assertEqual(view.priority, 990, "Перенос — после всех наших наследников.")

    def test_dialog_forms_untouched(self):
        """Окно размера вентзонта, позиции доборки — без обёртки: рамки только
        у документа в основном окне."""
        for model, xmlid in (("pmk.vent.hood", "pmk_calc.view_vent_hood_form"),):
            arch = self._arch(model, xmlid)
            with self.subTest(form=xmlid):
                self.assertFalse(arch.xpath("//div[@name='pmk_doc_top']"))

    # ─── Вентзонты: подписи колонок в одну строку ──────────────────────
    def test_vent_hood_columns(self):
        arch = self._arch("pmk.vent.hood.order", "pmk_calc.view_vent_hood_order_form")
        if arch is None:
            self.skipTest("pmk_calc не установлен")
        columns = {f.get("name"): f for f in arch.xpath("//field[@name='line_ids']/list/field")}
        Line = self.env["pmk.vent.hood"]
        # Итог строки (количество × на один зонт) подписан иначе, чем расход
        # на один зонт (окно размера) и итоги заказа (карточки в шапке): одно
        # слово на два числа — строку примут за зонт и умножат ещё раз.
        per_hood = {Line._fields["sheet_1250_m"].string, Line._fields["mass_net_kg"].string}
        order_kpi = {node.text.strip() for node in arch.xpath("//div[contains(concat(' ', @class, ' '), ' pmk-kpi__label ')]")}
        for name, label in (("total_sheet_1250_m", "Лист всего, пог. м"),
                            ("total_mass_net_kg", "Вес всего, кг")):
            with self.subTest(column=name):
                string = columns[name].get("string")
                self.assertEqual(string, label)
                self.assertIn("всего", string)
                self.assertNotIn(string, per_hood)
                self.assertNotIn(string, order_kpi)
        self.assertEqual(columns["width"].get("string"), "Ширина, мм")
        self.assertEqual(columns["length"].get("string"), "Длина, мм")
        # Ширина таблицы на 1280 px (ноутбук 1920 при 150 %) — без прокрутки
        # вбок. Доступно: 1280 − 32 (поля подложки) − 2 (рамка таблицы) − 17
        # (полоса прокрутки Windows) = 1229. Ядро (web/views/list/
        # column_width_hook.js) даёт колонке с width ровно эту ширину + поля
        # ячейки; ручка — 20 (handle listViewWidth), корзина — 12
        # (DELETE_BUTTON_WIDTH). Поля: у колонок полей 8 + 8, у крайних
        # ячеек снаружи 12 (--ListRenderer-table-padding-x, шаг 52.5).
        visible = [f for f in columns.values()
                   if f.get("optional") != "hide" and f.get("column_invisible") is None
                   and f.get("widget") != "handle"]
        for field in visible:
            with self.subTest(column=field.get("name")):
                self.assertTrue(field.get("width"), "Без width колонка тянется на свободное место.")
        handle, trash = 20, 12
        cells = len(visible) + 2
        paddings = cells * 16 + (12 - 8) * 2
        total = sum(int(f.get("width").rstrip("px")) for f in visible) + handle + trash + paddings
        self.assertLessEqual(total, 1229, total)
