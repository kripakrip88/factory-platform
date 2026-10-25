# -*- coding: utf-8 -*-
"""Шаг 75 (25.10.2026): шапка — разделы вкладками, как вкладки документа.

Открытый раздел — вкладка цвета карточки с «ножками» (приём шага 67), под ней
белая карточка пунктов раздела; текущий пункт — бледная плашка тона раздела;
«Настройки» — значком справа; ассистент — значком ✦ (pmk_ai).
Здесь — что раздел на месте, собирается libsass, несёт ключевые правила и
тёмную пару. Вид — глазами на копии.
"""
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open

from odoo.addons.pmk_theme.tests.test_step30_highlights import LIVE_THEME_PATHS

NAV_SCSS = "pmk_theme/static/src/scss/navbar_nexus.scss"
AI_XML = "pmk_ai/static/src/ai_panel.xml"
MARK = "// ═══ Шаг 75"


def _read(path):
    with file_open(path) as f:
        return f.read()


def _compile(path):
    import sass
    return re.sub(r"\s+", " ", sass.compile(string=_read(path)))


@tagged("post_install", "-at_install")
class TestStep75NavbarTabs(TransactionCase):

    def test_section_live_and_last(self):
        self.assertIn(NAV_SCSS, LIVE_THEME_PATHS)
        source = _read(NAV_SCSS)
        self.assertEqual(source.count(MARK), 1)
        self.assertEqual(source.find("// ═══", source.index(MARK) + 1), -1,
                         "раздел шага 75 — последний в файле")

    def test_compiles_with_key_rules(self):
        css = _compile(NAV_SCSS)
        # Открытая вкладка с ножками и карточка под ней на −1 px.
        self.assertIn("header.o_navbar .pmk_apps_bar .pmk_app.pmk_app--active::after", css)
        self.assertIn("radial-gradient(circle at 0 0", css)
        self.assertRegex(css, r"header\.o_navbar \.o_menu_sections \{[^}]*margin: -1px 16px 0 !important")
        # Текущий пункт — плашка тона, точки шага 23 нет.
        self.assertRegex(css, r"\.pmk_section--active::before \{ display: none;")
        # «Настройки» — значком справа.
        self.assertRegex(css, r'data-menu-xmlid="base\.menu_administration"\] \{ margin-left: auto;')

    def test_tone_for_every_section(self):
        css = _compile(NAV_SCSS)
        icons = set(re.findall(r'\.pmk_app\[data-menu-xmlid="([^"]+)"\]::before \{ content', css))
        self.assertTrue(icons)
        for xmlid in icons:
            with self.subTest(xmlid=xmlid):
                self.assertIn('header.o_navbar[data-pmk-app="%s"] { --pmk-nav-tone' % xmlid, css)
                self.assertIn('body.o_nexus_dark header.o_navbar[data-pmk-app="%s"] { --pmk-nav-tone' % xmlid, css)

    def test_dark_pair_outweighs_light(self):
        css = _compile(NAV_SCSS)
        # Светлая тёмной темы (шаг 23) — body.o_nexus_dark.o_web_client … с
        # !important: пара шага 75 того же веса и ниже по файлу.
        old = css.index("body.o_nexus_dark.o_web_client header.o_navbar .o_menu_sections .pmk_section--active {")
        new = css.index("body.o_nexus_dark.o_web_client header.o_navbar .o_menu_sections .pmk_section--active, ")
        self.assertGreater(new, old)
        self.assertIn("--pmk-nav-card: var(--pmk-surface-2", css)

    def test_assistant_icon_only(self):
        xml = _read(AI_XML)
        button = re.search(r'<button[^>]*class="o_pmk_ai__btn"[^>]*>(.*?)</button>', xml, re.S)
        self.assertTrue(button)
        self.assertEqual(button.group(1).strip(), "✦")
        self.assertIn('aria-label="Ассистент"', button.group(0))
