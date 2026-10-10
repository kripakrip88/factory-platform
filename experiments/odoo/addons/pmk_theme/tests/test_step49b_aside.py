# -*- coding: utf-8 -*-
"""Лента справа от листа на широком экране (разбор UX, шаг 49Б, 10.10.2026) —
что доезжает до браузера.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py):
  odoo -d pmk49b_test -i pmk_theme,pmk_deal,theme_nexus --test-enable \
       --test-tags /pmk_theme:TestStep49bAside,/pmk_theme:TestStep49Width,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme:TestHighlightsStep30 \
       --stop-after-init --http-port 8099
Правила без Odoo — node static/tests/chatter_aside_step49b.test.mjs.

Вид (2560: лист 1800 и лента 720 справа; 2200: лента 420; 1920 и уже —
лента под листом, как в шаге 49; обе темы) смотрит основной агент глазами на
копии — туры здесь не запустить. Здесь — то, что ломается молча:
  • раздел лёг в выключенный файл темы (forms.scss) или не в конец файла;
  • правило вне @media screen и (min-width: порог) — задело экраны уже 2200
    или печать;
  • правило без .o-aside — задело ленту под листом (шаг 49);
  • порог в SCSS разошёлся с порогом в JS (лента сбоку без наших ширин или
    наши ширины без ленты сбоку);
  • правило слабее ядра (flex: 2 1 990px листа, width: 530px ленты);
  • правило тронуло сетку групп или принесло цвет без тёмной пары;
  • chatter_inline.js снова подменяет SIDE → BOTTOM без условия или
    свёрнутая лента сбоку (шаблон смотрит на pmk.collapsed);
  • ядро переименовало то, на чём держится боковой режим (раскладка
    SIDE_CHATTER от XXL, класс o-aside, своя прокрутка ленты, перерисовка
    рендерера по resize).
"""
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open

from odoo.addons.pmk_theme.tests.test_step30_highlights import (
    DEAD_THEME_PATHS,
    LIVE_THEME_PATHS,
    _media_blocks,
    _read,
    _rules,
    _specificity,
)
from odoo.addons.pmk_theme.tests.test_step40_dark import BRIGHT_LIME
from odoo.addons.pmk_theme.tests.test_step48_header import _strip_media

SCSS = "pmk_theme/static/src/scss/"
FORMS_SCSS = SCSS + "forms_nexus.scss"
OLD_FORMS_SCSS = SCSS + "forms.scss"
DARK_SCSS = SCSS + "dark.scss"
JS = "pmk_theme/static/src/js/"
RULES_JS = JS + "chatter_aside_rules.js"
INLINE_JS = JS + "chatter_inline.js"
CHATTER_XML = "pmk_theme/static/src/xml/chatter.xml"
STEP_MARK = "// ═══ Шаг 49Б"

WIDE = "@media screen and (min-width: 2200px)"
NO_PREVIEW = ":not(:has(> .o_attachment_preview))"
SHEET = (".o_form_view .o_form_renderer" + NO_PREVIEW
         + ":has(> .o-mail-Form-chatter.o-aside) > .o_form_sheet_bg")
ASIDE = ".o_form_view .o_form_renderer" + NO_PREVIEW + " > .o-mail-Form-chatter.o-aside"
TOGGLE = ".o-mail-Form-chatter.o-aside .pmk-chatter-toggle"
# Строки кнопок в листе нет (шаг 48) — подложка сверху 8 px, лента вровень.
ASIDE_BARE = (".o_form_view .o_form_renderer" + NO_PREVIEW
              + " > .o_form_sheet_bg:not(:has(.o_form_statusbar)) ~ .o-mail-Form-chatter.o-aside")
# Шаг 49 — до порога и под ним без изменений.
STEP49_SHEET = ".o_form_view .o_form_renderer:not(:has(> .o_attachment_preview)) > .o_form_sheet_bg"
STEP49_CHATTER = ".o_form_renderer > .o-mail-Form-chatter:not(.o-aside)"


def _section(source):
    """Раздел «Шаг 49Б» — до следующего «// ═══» или до конца файла."""
    start = source.find(STEP_MARK)
    assert start != -1, "раздела шага 49Б нет"
    end = source.find("// ═══", start + 1)
    return source[start:end if end != -1 else None]


def _code(source):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", source, flags=re.S))


@tagged("post_install", "-at_install")
class TestStep49bAside(TransactionCase):

    _backend_css_cache = None

    # ─── Исходник ──────────────────────────────────────────────────────
    def test_section_in_live_file(self):
        source = _read(FORMS_SCSS)
        self.assertIn(FORMS_SCSS, LIVE_THEME_PATHS)
        self.assertIn(OLD_FORMS_SCSS, DEAD_THEME_PATHS)
        start = source.index(STEP_MARK)
        # Тест шага 49 берёт ПЕРВОЕ «// ═══ Шаг 49» — это должен быть шаг 49.
        self.assertLess(source.index("// ═══ Шаг 49:"), start)
        self.assertEqual(source.find("// ═══ Шаг 49"), source.index("// ═══ Шаг 49:"))
        for earlier in ("// ═══ Шаг 48", "// ═══ Шаг 55", "// ═══ Счёт покупателю по-нашему"):
            with self.subTest(earlier=earlier):
                self.assertLess(source.index(earlier), start, "Раздел — в конце файла.")
        self.assertEqual(source.find("// ═══", start + 1), -1, "После раздела 49Б разделов нет.")
        self.assertNotIn("Шаг 49Б", _read(OLD_FORMS_SCSS), "forms.scss выключен — правка туда не доедет.")

    def test_section_source(self):
        code = _code(_section(_read(FORMS_SCSS)))
        self.assertEqual(code.count("@media"), 1)
        self.assertIn("@media screen and (min-width: $pmk-aside-from)", code)
        for banned in ("grid-column", "grid-template-columns", "white-space", "#", "rgb", "hsl"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, code, "Ни сетки групп, ни цветов (тёмной пары нет).")
        lower = code.lower()
        for lime in BRIGHT_LIME:
            with self.subTest(lime=lime):
                self.assertNotIn(lime, lower)

    def _step_css(self):
        import sass

        css = sass.compile(string=_section(_read(FORMS_SCSS)))
        return re.sub(r"\s+", " ", css)

    def test_section_compiles(self):
        css = self._step_css()
        self.assertFalse(_rules(_strip_media(css)), "Вне @media правил нет — уже 2200 и печать не задеты.")
        rules = _rules(_media_blocks(css, WIDE))
        self.assertEqual(set(rules), {SHEET, ASIDE, ASIDE_BARE, TOGGLE})
        for selector in rules:
            with self.subTest(selector=selector):
                self.assertIn(".o-aside", selector)
                self.assertNotIn(":not(.o-aside)", selector)

        self.assertEqual(rules[SHEET], {
            "flex": "0 1 1800px",
            "min-width": "0",
            "margin-right": "0",
            # шире 1800 + 720 + 16 — пара по центру, уже — 0
            "margin-left": "max(0px, calc((100% - 2536px) / 2))",
        })
        self.assertEqual(rules[ASIDE], {
            "flex": "1 1 0",
            "width": "auto",
            "min-width": "420px",
            "max-width": "720px",
            # поля, а не отступы: фон контейнера ленты не вылезает полосой
            "margin": "18px 16px 16px 0",
            "padding": "0",
        })
        self.assertEqual(rules[ASIDE_BARE], {"margin-top": "8px"})
        self.assertEqual(rules[TOGGLE], {"display": "none !important"})
        # :has() внутри :has() браузер отбрасывает вместе со всем правилом
        for selector in rules:
            with self.subTest(selector=selector):
                self.assertNotRegex(selector, r":has\([^)]*:has\(")

    def test_widths_add_up(self):
        """2560: лист 1800 + лента 720 + поле 16 — остаток меньше 100 px;
        на пороге лента не уже 420, лист ужимается меньше чем на 40 px."""
        rules = _rules(_media_blocks(self._step_css(), WIDE))
        sheet = int(rules[SHEET]["flex"].split()[2].rstrip("px"))
        aside_max = int(rules[ASIDE]["max-width"].rstrip("px"))
        aside_min = int(rules[ASIDE]["min-width"].rstrip("px"))
        right = int(rules[ASIDE]["margin"].split()[1].rstrip("px"))
        self.assertLess(2560 - (sheet + aside_max + right), 100)
        self.assertGreaterEqual(2560 - (sheet + aside_max + right), 0)
        self.assertLess(sheet + aside_min + right - 2200, 40)

    def test_weights_beat_core(self):
        """Ядро: .o_form_view.o_xxl_form_view .o_form_sheet_bg (0,3,0);
        .o-mail-Form-chatter.o-aside (0,2,0); кнопка — класс d-flex
        (!important), у нас тоже !important и вес выше (0,1,0)."""
        self.assertGreater(_specificity(SHEET), (0, 3, 0))
        self.assertGreater(_specificity(ASIDE), (0, 2, 0))
        self.assertGreater(_specificity(TOGGLE), (0, 1, 0))
        # 8 px без строки кнопок перебивает 18 px ленты
        self.assertGreater(_specificity(ASIDE_BARE), _specificity(ASIDE))
        # потолок листа шага 49 (max-width 1800) действует и сбоку
        self.assertGreater(_specificity(SHEET), _specificity(STEP49_SHEET))

    # ─── Порог един в SCSS и JS ────────────────────────────────────────
    def test_threshold_shared(self):
        js = _read(RULES_JS)
        match = re.search(r"export const ASIDE_MIN_WIDTH = (\d+);", js)
        self.assertTrue(match)
        scss = _section(_read(FORMS_SCSS))
        scss_match = re.search(r"\$pmk-aside-from: (\d+)px;", scss)
        self.assertTrue(scss_match)
        self.assertEqual(match.group(1), scss_match.group(1))
        self.assertIn("@media screen and (min-width: %spx)" % match.group(1), self._step_css())

    # ─── JS-договор ────────────────────────────────────────────────────
    def test_js_contract(self):
        inline = _code(_read(INLINE_JS))
        self.assertIn("chatterLayout(super.mailLayout(", inline)
        self.assertIn('from "@pmk_theme/js/chatter_aside_rules"', inline)
        self.assertIn("pmkCollapsedNow", inline)
        self.assertNotRegex(inline, r'layout === "SIDE_CHATTER" \? "BOTTOM_CHATTER"',
                            "безусловная подмена SIDE → BOTTOM вернулась")
        self.assertIn("ASIDE_MEDIA", inline)
        self.assertIn("this.props.isChatterAside", inline)
        # смена порога пересчитывает состояние только при расширении окна
        self.assertIn("shouldApplyOnWidth(", inline)

        rules = _code(_read(RULES_JS))
        self.assertNotIn("import", rules, "чистые функции без импортов Odoo — их гоняет node")

        xml = _read(CHATTER_XML)
        self.assertIn("""<attribute name="t-att-data-pmk-collapsed">pmkCollapsedNow ? '1' : '0'</attribute>""", xml)
        self.assertIn("""t-att-aria-expanded="pmkCollapsedNow""", xml)
        self.assertNotIn("pmk.collapsed ?", xml)

        manifest = _read("pmk_theme/__manifest__.py")
        self.assertLess(manifest.index('"' + RULES_JS + '"'), manifest.index('"' + INLINE_JS + '"'),
                        "правила раньше патча, который их импортирует")

    # ─── Договор с ядром ───────────────────────────────────────────────
    def test_core_contract(self):
        checks = {
            "mail/static/src/chatter/web/form_renderer.js": (
                'return "SIDE_CHATTER"', "SIZES.XXL", "useDebounced(this.render, 200)"),
            # лента — соседка подложки ПОСЛЕ неё (на этом держится ~ в ASIDE_BARE)
            "mail/static/src/chatter/web/form_compiler.js": (
                '"o-aside w-print-100"', "isChatterAside", "after sheet bg"),
            "theme_nexus/static/src/scss/forms.scss": ("padding: 18px 0",),
            "mail/static/src/chatter/web/chatter_patch.js": ("this.state.aside = this.props.isChatterAside",),
            "mail/static/src/chatter/web/chatter.xml": ("'overflow-auto o-scrollbar-thin': props.isChatterAside",),
            "mail/static/src/chatter/web/form_renderer.scss": ("flex-grow: 1", "margin: 0 auto"),
            "web/static/src/views/form/form_controller.scss": (
                ".o_form_view.o_xxl_form_view", "flex: 2 1 $o-form-sheet-min-width", "overflow: auto",
                # верх подложки без строки кнопок — 8 px (на нём ASIDE_BARE)
                "&:not(:has(.o_form_statusbar))", "padding-top: map-get($spacers, 2)"),
            "web/static/src/views/form/form_controller.js": ("o_xxl_form_view h-100",),
            "web/static/src/views/form/form_compiler.js": ('"flex-nowrap h-100"',),
            "web/static/src/core/browser/browser.js": ("matchMedia",),
        }
        for path, needles in checks.items():
            with file_open(path) as f:
                source = f.read()
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
        css = self._backend_css()
        wide = _rules(_media_blocks(css, WIDE))
        for selector in (SHEET, ASIDE, ASIDE_BARE, TOGGLE):
            with self.subTest(selector=selector):
                self.assertIn(selector, wide)
        self.assertEqual(wide[ASIDE]["max-width"], "720px")
        # шаг 49 на месте с прежними значениями
        screen = _rules(_media_blocks(css, "@media screen {"))
        self.assertEqual(screen[STEP49_SHEET]["max-width"], "1800px")
        self.assertEqual(screen[STEP49_CHATTER]["max-width"], "1800px")
        md = _rules(_media_blocks(css, "@media screen and (min-width: 768px)"))
        self.assertEqual(md[STEP49_CHATTER]["max-width"], "1768px")
        self.assertEqual(md[STEP49_CHATTER]["margin-left"], "16px")

    def test_dark_chatter_covered(self):
        """Цветов в разделе нет: ленту сбоку в тёмной теме красит dark.scss,
        раздел 11 (контейнер и сама лента)."""
        dark = _read(DARK_SCSS)
        self.assertIn("body.o_nexus_dark .o-mail-Chatter,", dark)
        self.assertIn("body.o_nexus_dark .o-mail-Form-chatter,", dark)
