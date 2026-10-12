# -*- coding: utf-8 -*-
"""Задача 265 (шаг 67, 12.10.2026): вкладки документа как в Chrome.

Открытая вкладка — того же цвета, что карточка под ней, со скруглением сверху
и вогнутыми «ножками» снизу; карточка подтянута под полосу ярлыков на 1 px.
Только документы с шапкой-карточкой шага 52 (.o_form_sheet:has(> .pmk-doc-top)).
Здесь — что раздел на месте, собирается libsass и несёт ключевые правила.
"""
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open

from odoo.addons.pmk_theme.tests.test_step30_highlights import LIVE_THEME_PATHS
from odoo.addons.pmk_theme.tests.test_step40_dark import BRIGHT_LIME

SCSS = "pmk_theme/static/src/scss/"
FORMS_SCSS = SCSS + "forms_nexus.scss"
DARK_SCSS = SCSS + "dark.scss"
MARK = "// ═══ Шаг 67"
SCOPE = ".o_form_sheet:has(> .pmk-doc-top) > .o_notebook"
VARS = ('$pmk-card-bg: unquote("var(--pmk-surface, #fff)");\n'
        '$pmk-card-line: unquote("var(--pmk-border, #e3e4e8)");\n')


def _read(path):
    with file_open(path) as f:
        return f.read()


def _section(source):
    start = source.index(MARK)
    end = source.find("// ═══", start + 1)
    return source[start:end if end != -1 else None]


def _code(source):
    return re.sub(r"//[^\n]*", "", source)


def _compile(source):
    import sass
    return re.sub(r"\s+", " ", sass.compile(string=VARS + source))


@tagged("post_install", "-at_install")
class TestT265ChromeTabs(TransactionCase):

    def test_section_in_live_files_last(self):
        for path in (FORMS_SCSS, DARK_SCSS):
            with self.subTest(path=path):
                self.assertIn(path, LIVE_THEME_PATHS)
                source = _read(path)
                self.assertEqual(source.count(MARK), 1)
                start = source.index(MARK)
                self.assertEqual(source.find("// ═══", start + 1), -1, "Раздел — последним в файле.")
                self.assertLess(source.index("// ═══ Шаг 66"), start)

    def test_section_compiles_without_min_max(self):
        for path in (FORMS_SCSS, DARK_SCSS):
            code = _code(_section(_read(path)))
            with self.subTest(path=path):
                self.assertNotRegex(code, r"\b(?:min|max)\(", "libsass Odoo роняет сборку")
                for lime in BRIGHT_LIME:
                    self.assertNotIn(lime, code.lower())
        css = _compile(_section(_read(FORMS_SCSS)))
        self.assertIn(SCOPE.replace("> ", ">").replace(" >", ">"), css.replace("> ", ">").replace(" >", ">"))

    def test_key_rules(self):
        css = _compile(_section(_read(FORMS_SCSS)))
        # Открытая вкладка — фоном и чертой карточки, сильнее !important темы.
        self.assertRegex(css, r"\.nav-link\.active \{[^}]*background: var\(--pmk-tab-fill\) !important")
        self.assertIn("--pmk-tab-fill: var(--pmk-surface, #fff)", css)
        self.assertRegex(css, r"\.nav-link\.active \{[^}]*border-color: var\(--pmk-border, #e3e4e8\) !important")
        # Ножки — дуга radial-gradient по обе стороны.
        self.assertIn("radial-gradient(circle at 0 0", css)
        self.assertIn("radial-gradient(circle at 100% 0", css)
        # Черта полосы снята, карточка подтянута под вкладку.
        self.assertRegex(css, r"\.nav \{[^}]*border-bottom: 0 !important")
        self.assertRegex(css, r"\.o_notebook_content \{ margin-top: -1px")

    def test_dark_pair_hover(self):
        css = _compile(_section(_read(DARK_SCSS)))
        self.assertIn("body.o_nexus_dark", css)
        self.assertIn("rgba(255, 255, 255, 0.07)", css)
        self.assertIn("--pmk-tab-fill: var(--pmk-surface-2, #25272d)", css)
