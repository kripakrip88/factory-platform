# -*- coding: utf-8 -*-
"""Схема раскроя читается в обеих темах (разбор UX, шаг 40, 05.10.2026).

Было: белый текст на полупрозрачных заливках (под прежнюю тёмную тему) — в
светлой контраст 1,2–1,3, подпись над полосой белым по белому. Здесь — то,
что ломается молча: стиль собирается, текст тёмный, контраст с заливкой не
ниже 4,5 в светлой и в тёмной паре (pmk_theme/static/src/scss/dark.scss,
раздел «Шаг 40», 40.5), запасные цвета совпадают с тонами темы, классы,
которые пишет _layout_html (и которые уже лежат в базе готовым HTML), все со
стилем. Печатный лист раскроя (models/cut_sheet.py) — свой чёрно-белый
стиль, его шаг не трогал. Доводка: цвет повторён словом — легенда под
схемой в форме строки («деталь», «годный остаток», «лом» на плашках тех же
цветов) и слово в подсказке отрезка («лом, 150 мм»).

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py):
  odoo -d pmk40_test -i pmk_cut --test-enable --test-tags /pmk_cut \
       --stop-after-init
Глазами — основной агент: РК-00001 → «Результат» → строка → окно со схемой,
обе темы.
"""
import re

import sass
from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open

CUT_SCSS = "pmk_cut/static/src/scss/cut.scss"
DARK_SCSS = "pmk_theme/static/src/scss/dark.scss"
THEME_LIGHT_SCSS = "pmk_theme/static/src/scss/forms_nexus.scss"
DARK = "body.o_nexus_dark "
# Тон плашек темы → часть схемы.
TONES = {".pmk-cut__piece": "blue", ".pmk-cut__rest--useful": "green", ".pmk-cut__rest--scrap": "red"}


def _read(path):
    with file_open(path) as f:
        return f.read()


def _rules(css):
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for decl in body.split(";"):
            if ":" in decl:
                name, value = decl.split(":", 1)
                decls[name.strip()] = value.strip()
        for selector in selectors.split(","):
            found.setdefault(selector.strip(), {}).update(decls)
    return found


def _hex(value):
    """Цвет из значения: литерал или запасное значение var(--x, #abc123)."""
    match = re.search(r"#[0-9a-fA-F]{6}\b", value or "")
    return match.group(0).lower() if match else None


def _lum(color):
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@tagged("post_install", "-at_install")
class TestCutSchemeStep40(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rules = _rules(sass.compile(string=_read(CUT_SCSS), output_style="compressed"))
        cls.dark = _rules(sass.compile(string=_read(DARK_SCSS), output_style="expanded"))

    def test_light_text_readable(self):
        ink = _hex(self.rules[".pmk-cut__piece"]["color"])
        self.assertEqual(ink, "#16191c")
        self.assertEqual(_hex(self.rules[".pmk-cut__rest"]["color"]), ink)
        for selector in TONES:
            with self.subTest(selector=selector):
                fill = _hex(self.rules[selector]["background"])
                self.assertTrue(fill)
                self.assertGreaterEqual(_contrast(ink, fill), 4.5)
        head = _hex(self.rules[".pmk-cut__head"]["color"])
        self.assertGreaterEqual(_contrast(head, "#ffffff"), 4.5, "подпись «6000 мм × 2» на белом листе")

    def test_no_white_text_left(self):
        for selector, decls in self.rules.items():
            if "pmk-cut__" in selector:
                with self.subTest(selector=selector):
                    color = decls.get("color", "").replace(" ", "").lower()
                    self.assertNotIn("255,255,255", color)
                    self.assertNotIn(color, ("#fff", "#ffffff", "white"))

    def test_fallbacks_are_theme_tones(self):
        """Заливки — тона плашек темы (переменные --pmk-tone-*-bd), запасной
        цвет — тот же, что в светлой теме: без темы схема выглядит так же."""
        light = _read(THEME_LIGHT_SCSS)
        for selector, tone in TONES.items():
            with self.subTest(selector=selector):
                value = self.rules[selector]["background"]
                self.assertIn("var(--pmk-tone-%s-bd" % tone, value)
                pair = re.search(r"\b%s: \((#[0-9a-fA-F]{6}), (#[0-9a-fA-F]{6})\)" % tone, light)
                self.assertTrue(pair, tone)
                self.assertEqual(_hex(value), pair.group(2).lower())

    def test_dark_pair_readable(self):
        """Тёмная пара: светлый текст на тёмных тонах тех же цветов (5,2–5,6),
        подпись — приглушённым светлым; переменные тонов в тёмной теме
        тёмные, поэтому и заливки светлого правила там темнеют сами."""
        tones = self.dark[DARK.strip()]
        self.assertEqual(self.dark[DARK + ".pmk-cut__piece"]["color"], "var(--pmk-ink)")
        ink = _hex(tones["--pmk-ink"])
        for selector, tone in TONES.items():
            with self.subTest(selector=selector):
                self.assertEqual(self.dark[DARK + selector]["background"], "var(--pmk-tone-%s-bd)" % tone)
                fill = _hex(tones["--pmk-tone-%s-bd" % tone])
                self.assertGreaterEqual(_contrast(ink, fill), 4.5)
        self.assertEqual(self.dark[DARK + ".pmk-cut__head"]["color"], "var(--pmk-ink-2)")
        self.assertGreaterEqual(_contrast(_hex(tones["--pmk-ink-2"]), _hex(tones["--pmk-surface"])), 4.5)

    def test_layout_classes_styled(self):
        plan = self.env["pmk.cut.plan"].new({"min_useful_mm": 500})
        html = str(plan._layout_html({"patterns": [
            {"stock_length": 6000, "pieces": [2000, 2000], "leftover": 1900, "count": 2},
            {"stock_length": 6000, "pieces": [5800], "leftover": 150, "count": 1},
        ]}))
        names = {name for value in re.findall(r'class="([^"]+)"', html) for name in value.split()}
        self.assertTrue({"pmk-cut__piece", "pmk-cut__rest--useful", "pmk-cut__rest--scrap"} <= names)
        # Цвет повторён словом и в подсказке отрезка (доводка шага 40): красный
        # «150» без слова не опознать как лом.
        self.assertIn('title="деталь, 2000 мм"', html)
        self.assertIn('title="годный остаток, 1900 мм"', html)
        self.assertIn('title="лом, 150 мм"', html)
        # С цветом — всё, кроме обёрток (отступы); у каждого с цветом — тёмная пара.
        coloured = {"pmk-cut__head", "pmk-cut__bar", "pmk-cut__piece", "pmk-cut__rest",
                    "pmk-cut__rest--useful", "pmk-cut__rest--scrap"}
        self.assertTrue(coloured <= names)
        for name in names - {"pmk-cut"}:
            with self.subTest(css_class=name):
                self.assertIn("." + name, self.rules)
                if name in coloured:
                    self.assertIn(DARK + "." + name, self.dark)

    def test_legend_under_scheme(self):
        """Легенда под схемой в форме строки «Результата»: цвет повторён
        словом (правило разбора UX; доводка шага 40). Плашки несут классы
        отрезков — цвет и тёмная пара у них общие с полосой. Легенда в форме,
        а не в HTML схемы: у раскроев, посчитанных раньше, HTML уже в базе."""
        view = self.env.ref("pmk_cut.view_cut_plan_form")
        arch = etree.fromstring(
            self.env["pmk.cut.plan"].get_views([(view.id, "form")])["views"]["form"]["arch"])
        legends = arch.xpath(
            "//field[@name='result_ids']/form//div"
            "[contains(concat(' ', normalize-space(@class), ' '), ' pmk-cut__legend ')]")
        self.assertEqual(len(legends), 1)
        legend = legends[0]
        self.assertEqual(legend.get("invisible"), "not layout_html", "без схемы легенда не нужна")
        # Сразу под схемой (комментарии вида — не узлы формы).
        prev = legend.getprevious()
        while prev is not None and not isinstance(prev.tag, str):
            prev = prev.getprevious()
        self.assertEqual((prev.tag, prev.get("name")), ("field", "layout_html"))
        keys = {" ".join(span.text.split()): set(span.get("class").split()) for span in legend.iter("span")}
        self.assertEqual(keys, {
            "деталь": {"pmk-cut__key", "pmk-cut__piece"},
            "годный остаток": {"pmk-cut__key", "pmk-cut__rest", "pmk-cut__rest--useful"},
            "лом": {"pmk-cut__key", "pmk-cut__rest", "pmk-cut__rest--scrap"},
        })
        # Заливка и текст плашек — правила отрезков, в обеих темах; у самой
        # легенды — только посадка, своего цвета нет.
        for selector in TONES:
            with self.subTest(selector=selector):
                self.assertIn("background", self.rules[selector])
                self.assertIn(DARK + selector, self.dark)
        layout = [selector for selector in self.rules if "pmk-cut__legend" in selector]
        self.assertTrue(any("pmk-cut__key" in selector for selector in layout), layout)
        for selector in layout:
            with self.subTest(selector=selector):
                self.assertFalse({"color", "background", "background-color"} & set(self.rules[selector]))
