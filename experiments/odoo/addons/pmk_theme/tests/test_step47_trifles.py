# -*- coding: utf-8 -*-
"""Мелочи: поиск, переключатель темы, значки видов (разбор UX, шаг 47).

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py), с темой theme_nexus:
  odoo -d pmk47_test -i pmk_theme,theme_nexus --test-enable \
       --test-tags /pmk_theme --stop-after-init --http-port 8099

Вид (капсула поиска, кружок со значком, бледный лайм выбранного вида, тёмная
тема, узкий экран) смотрит основной агент глазами на копии. Здесь — то, что
ломается молча:
  • сборка стилей бэкенда падает (ошибка SCSS — и без стилей вся система);
  • значок внутри data:URI битый (маска ничего не нарисует — пустая кнопка);
  • значок-маска без системного цвета в режиме высокой контрастности Windows
    (forced-colors): фон там подменяется на Canvas — значок пропадает;
  • вид получил класс значка, а правила под него нет (и наоборот);
  • в тёмной теме строка поиска и группа видов разъехались по поверхностям
    (в светлой они одинаковые — белые с одной рамкой);
  • наследование шаблона шапки не находит свой узел (белый экран Owl);
  • ядро после обновления сменило разметку, на которую опирается капсула
    поиска (поле и кнопка фильтров — соседи в одном .input-group) или
    значок вида (класс из view.icon) — правило перестанет срабатывать молча.
"""
import copy
import re
from urllib.parse import unquote

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open
from odoo.tools.template_inheritance import locate_node

from odoo.addons.pmk_theme.models.ir_ui_view import PMK_VIEW_ICONS

SCSS = "pmk_theme/static/src/scss/"
TOGGLE_XML = "pmk_theme/static/src/xml/theme_toggle.xml"
SVG_NS = "{http://www.w3.org/2000/svg}"
# Правило с маской-значком: селектор и первый data:URI в теле. В сборке есть и
# чужие data:URI (галочки и стрелки Bootstrap) — проверяем только наши.
RULE_WITH_ICON = re.compile(r'([^{}]*)\{[^{}]*?url\("data:image/svg\+xml,([^"]+)"\)')
# Живые на стенде записи ir.asset темы (SELECT path, active FROM ir_asset,
# 02.10.2026). Остальные 17 файлов темы на стенде выключены, а в свежей
# тестовой базе включены — сборку приводим к состоянию стенда.
LIVE_THEME_PATHS = {
    SCSS + "navbar_nexus.scss",
    TOGGLE_XML,
    SCSS + "forms_nexus.scss",
    SCSS + "dark.scss",
}
CAPSULE = ".input-group:has(> .o_searchview + .o_searchview_dropdown_toggler)"
FORCED = "@media (forced-colors: active)"


def _media_blocks(css, query):
    """Содержимое всех блоков «@media <query> { … }» подряд — по парным
    скобкам (такой блок может появиться и у ядра, и у других модулей)."""
    parts, start = [], css.find(query)
    while start != -1:
        begin = css.index("{", start) + 1
        depth, pos = 1, begin
        while depth:
            depth += {"{": 1, "}": -1}.get(css[pos], 0)
            pos += 1
        parts.append(css[begin:pos - 1])
        start = css.find(query, pos)
    return " ".join(parts)


def _selector_bodies(css):
    """{селектор: [тела правил]} для правил без вложенных блоков; список
    селекторов через запятую раскладывается по одному."""
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for selector in selectors.split(","):
            found.setdefault(selector.strip(), []).append(body)
    return found


def _decls(body):
    """«a: b; c: d» → {'a': 'b', 'c': 'd'}."""
    pairs = (decl.split(":", 1) for decl in body.split(";") if ":" in decl)
    return {name.strip(): value.strip() for name, value in pairs}


def _read(path):
    with file_open(path) as f:
        return f.read()


def _xml(path):
    with file_open(path, "rb") as f:
        return etree.parse(f).getroot()


def _template(path, name):
    """Шаблон ядра отдельным деревом: «//» в xpath наследника ищет внутри
    шаблона, как в браузере, а не по всему файлу."""
    node = _xml(path).find("t[@t-name='%s']" % name)
    assert node is not None, (path, name)
    return copy.deepcopy(node)


def _classes(node):
    return (node.get("class") or "").split()


@tagged("post_install", "-at_install")
class TestTriflesStep47(TransactionCase):

    # Собранный CSS бэкенда (состояние стенда) — один на класс: сборка всего
    # web.assets_backend занимает секунды, а нужна трём проверкам.
    _backend_css_cache = None

    def _nexus_installed(self):
        return self.env["ir.module.module"]._get("theme_nexus").state == "installed"

    def _stand_like_assets(self):
        """Файлы темы — как на стенде: живые четыре, прочие выключены."""
        theme = self.env["ir.asset"].search([("path", "=like", "pmk_theme/static/src/%")])
        theme.filtered(lambda a: a.path not in LIVE_THEME_PATHS).active = False
        self.assertEqual(set(theme.filtered("active").mapped("path")), LIVE_THEME_PATHS)

    def _paths(self, bundle="web.assets_backend"):
        return [entry[0].lstrip("/") for entry in self.env["ir.asset"]._get_asset_paths(bundle, {})]

    def _backend_css(self):
        """Вся сборка web.assets_backend одним источником SCSS, как на стенде;
        пробелы схлопнуты. Ошибка компиляции — провал сразу."""
        cls = type(self)
        if cls._backend_css_cache is None:
            self._stand_like_assets()
            bundle = self.env["ir.qweb"]._get_asset_bundle("web.assets_backend", js=False)
            css = bundle.preprocess_css()
            self.assertFalse(bundle.css_errors, bundle.css_errors)
            cls._backend_css_cache = re.sub(r"\s+", " ", css)
        return cls._backend_css_cache

    def _icon_rules(self, css):
        """Селекторы наших правил с маской-значком (data:URI) → URI. В сборке
        есть и чужие data:URI (галочки и стрелки Bootstrap) — их не берём."""
        rules = {}
        for selectors, uri in RULE_WITH_ICON.findall(css):
            for selector in selectors.split(","):
                selector = selector.strip()
                if "pmk_" in selector or "o_searchview_dropdown_toggler" in selector:
                    rules[selector] = uri
        return rules

    # ─── Сборка ─────────────────────────────────────────────────────────
    def test_files_in_bundle(self):
        self._stand_like_assets()
        paths = self._paths()
        for path in LIVE_THEME_PATHS:
            with self.subTest(path=path):
                self.assertIn(path, paths)
        # Расширение шаблона шапки — после самого шаблона.
        self.assertLess(paths.index("web/static/src/webclient/navbar/navbar.xml"),
                        paths.index(TOGGLE_XML))
        if self._nexus_installed():
            # Наши стили — ниже темы: при равном весе выигрываем мы.
            self.assertLess(paths.index("theme_nexus/static/src/scss/dark_mode.scss"),
                            paths.index(SCSS + "navbar_nexus.scss"))

    def test_backend_css_compiles(self):
        """Вся сборка web.assets_backend компилируется ОДНИМ источником SCSS:
        ошибка в нашем файле оставила бы без стилей всю систему. Заодно —
        правила шага на месте и каждый значок — корректный SVG (битый
        data:URI маска молча не рисует, кнопка остаётся пустой)."""
        css = self._backend_css()

        for needle in (
            ".pmk_theme_switch__knob::before",
            ".pmk_theme_switch--on .pmk_theme_switch__knob::before",
            CAPSULE + " > .o_searchview_dropdown_toggler::after",
            # Свечение капсулы — от фокуса в поле, а не от кнопки фильтров.
            CAPSULE + ":has(> .o_searchview:focus-within)",
            "body.o_nexus_dark " + CAPSULE,
            # Своё лаймовое свечение поля ввода в тёмной теме погашено.
            "body.o_nexus_dark .o_searchview .o_searchview_input:focus",
            "nav.o_cp_switch_buttons > .o_switch_view.active",
            "body.o_nexus_dark nav.o_cp_switch_buttons > .o_switch_view.active",
            "i.pmk_vi::before",
            # Телефон в тёмной теме: пункты нижней панели выбора вида.
            "body.o_nexus_dark .o_bottom_sheet .o_cp_switch_buttons .o-dropdown-item",
        ):
            with self.subTest(rule=needle):
                self.assertIn(needle, css)
        self.assertNotIn("pmk_theme_switch__glyph", css, "отдельного глифа у дорожки больше нет")

        # У каждого вида из словаря — своё правило значка, и лишних нет.
        rules = set(re.findall(r"i\.pmk_vi--([a-z_]+)", css))
        self.assertEqual(rules, {cls.split("--", 1)[1] for cls in PMK_VIEW_ICONS.values()})

        uris = set(self._icon_rules(css).values())
        self.assertGreaterEqual(len(uris), 12, "фильтры, солнце, месяц и девять видов")
        for uri in uris:
            with self.subTest(uri=uri[:60]):
                self.assertNotIn("#", uri, "«#» обрывает data:URI")
                svg = etree.fromstring(unquote(uri).encode())
                self.assertEqual(svg.tag, SVG_NS + "svg")
                self.assertEqual(svg.get("viewBox"), "0 0 24 24")
                paths = svg.findall(SVG_NS + "path")
                self.assertTrue(paths and all(p.get("d") for p in paths))

    def test_forced_colors_icons(self):
        """Режим высокой контрастности Windows (forced-colors: active)
        подменяет фон на системный Canvas, оставляя прозрачность. Значок,
        нарисованный фоном под маской, слился бы с фоном — пустая кнопка.
        Каждый наш значок-маска обязан получить там системный цвет и
        forced-color-adjust: none; выбранный вид — системный цвет выделения."""
        css = self._backend_css()
        self.assertIn(FORCED, css)
        forced = _selector_bodies(_media_blocks(css, FORCED))

        icons = self._icon_rules(css)
        self.assertGreaterEqual(len(icons), 12, "фильтры, солнце, месяц и девять видов")
        # Маска у значков видов — в i.pmk_vi--<вид>, а фон — в общем i.pmk_vi.
        painted = {"i.pmk_vi" if sel.startswith("i.pmk_vi--") else sel for sel in icons}
        for selector in painted:
            with self.subTest(icon=selector):
                self.assertTrue(selector in forced, "значок без системного цвета пропадёт: " + selector)
                decls = _decls(" ".join(forced[selector]))
                self.assertEqual(decls.get("forced-color-adjust"), "none")
                self.assertEqual(decls.get("background-color"), "ButtonText")

        # Выбранный вид: и в светлой, и в тёмной теме (её правило весомее),
        # и в нижней панели телефона. Значок на выделении — HighlightText.
        for selector in ("nav.o_cp_switch_buttons > .o_switch_view.active",
                         "body.o_nexus_dark nav.o_cp_switch_buttons > .o_switch_view.active",
                         ".o_bottom_sheet .o_cp_switch_buttons .o-dropdown-item.selected"):
            with self.subTest(active=selector):
                decls = _decls(" ".join(forced.get(selector, [])))
                self.assertEqual(decls.get("background-color"), "Highlight !important")
                icon = _decls(" ".join(forced.get(selector + " i.pmk_vi", [])))
                self.assertEqual(icon.get("background-color"), "HighlightText")

    def test_dark_groups_one_surface(self):
        """Строка поиска и группа видов — одна поверхность и одна рамка в
        обеих темах: в светлой обе белые с рамкой #EAE6DC, в тёмной группа
        не должна сливаться с панелью (#1E2025), когда капсула приподнята."""
        rules = _selector_bodies(self._backend_css())

        def surface(selector):
            decls = {}
            for body in rules.get(selector, []):
                decls.update(_decls(body))
            return decls

        for prefix in ("", "body.o_nexus_dark "):
            capsule = surface(prefix + CAPSULE)
            views = surface(prefix + "nav.o_cp_switch_buttons")
            with self.subTest(theme=prefix or "светлая"):
                self.assertTrue(capsule.get("background"))
                self.assertEqual(views.get("background"), capsule.get("background"))
                border = "border" if not prefix else "border-color"
                self.assertTrue(capsule.get(border))
                self.assertEqual(views.get(border), capsule.get(border))
        self.assertNotEqual(surface("body.o_nexus_dark nav.o_cp_switch_buttons").get("background"),
                            "var(--pmk-surface, #1e2025)", "цвет панели — группа проваливается")

    def test_icon_license_noted(self):
        src = _read(SCSS + "navbar_nexus.scss")
        self.assertIn("Tabler", src)
        self.assertIn("MIT", src)

    # ─── Значки видов ───────────────────────────────────────────────────
    def test_view_icons(self):
        info = self.env["ir.ui.view"].get_view_info()
        for view_type in ("list", "kanban", "form", "calendar", "pivot", "graph", "activity"):
            with self.subTest(view=view_type):
                classes = info[view_type]["icon"].split()
                self.assertIn("pmk_vi", classes)
                self.assertIn(PMK_VIEW_ICONS[view_type], classes)
                # Класс ядра — первым: без наших стилей останется штатный глиф.
                self.assertIn(classes[0], ("oi", "fa"))
                # Прочие сведения о виде не тронуты: по multi_record ядро
                # решает, какие виды показать в переключателе.
                self.assertTrue(info[view_type]["display_name"])
        self.assertFalse(info["form"]["multi_record"])
        self.assertTrue(info["list"]["multi_record"])
        # Вид поиска в переключателе не бывает — его значок не трогаем.
        self.assertNotIn("pmk_vi", info["search"]["icon"].split())

    def test_hierarchy_icon_not_rotated(self):
        info = self.env["ir.ui.view"].get_view_info()
        if "hierarchy" not in info:
            self.skipTest("web_hierarchy не установлен")
        classes = info["hierarchy"]["icon"].split()
        self.assertIn(PMK_VIEW_ICONS["hierarchy"], classes)
        self.assertNotIn("fa-rotate-90", classes, "повернул бы и наш значок")

    # ─── Шаблоны: наш и контракт ядра ───────────────────────────────────
    def test_theme_toggle_template(self):
        ext = _xml(TOGGLE_XML).find("t[@t-inherit='web.NavBar']")
        self.assertEqual(ext.get("t-inherit-mode"), "extension")
        navbar = _template("web/static/src/webclient/navbar/navbar.xml", "web.NavBar")
        specs = list(ext.iter("xpath"))
        self.assertTrue(specs)
        for spec in specs:
            with self.subTest(expr=spec.get("expr")):
                self.assertIsNotNone(locate_node(navbar, spec), "узел не найден — белый экран Owl")
        button = ext.find(".//button")
        self.assertEqual(button.get("t-if"), "this.toggleNexusDarkMode",
                         "без проверки снятие чужой темы роняет шапку")
        self.assertIsNone(button.find(".//i"), "значок — в кружке, отдельного глифа нет")
        knob = button.find("span[@class='pmk_theme_switch__track']/span[@class='pmk_theme_switch__knob']")
        self.assertIsNotNone(knob)
        self.assertIsNotNone(button.find("span[@class='visually-hidden']"))
        # Механизм — у чужой темы: имена, на которые опирается шаблон.
        js = _read("theme_nexus/static/src/js/dark_mode.js")
        for name in ("toggleNexusDarkMode", "nexusDarkState", "o_nexus_dark"):
            with self.subTest(name=name):
                self.assertIn(name, js)

    def test_core_search_bar_contract(self):
        """Капсула поиска опирается на разметку ядра: в .input-group подряд
        поле .o_searchview и кнопка .o_searchview_dropdown_toggler."""
        bar = _template("web/static/src/search/search_bar/search_bar.xml", "web.SearchBar")
        group = bar.find("div[@role='search']")
        self.assertIn("input-group", _classes(group))
        children = [c for c in group if isinstance(c.tag, str)]
        self.assertEqual([c.tag for c in children], ["Dropdown", "SearchBarMenu"])
        field = [c for c in children[0] if isinstance(c.tag, str)][0]
        self.assertIn("o_searchview", _classes(field))
        menu = _template("web/static/src/search/search_bar_menu/search_bar_menu.xml", "web.SearchBarMenu")
        toggler = menu.find("Dropdown/button")
        self.assertIn("o_searchview_dropdown_toggler", _classes(toggler))
        self.assertIn("o-dropdown-caret", _classes(toggler), "треугольник ядра, который мы заменяем")
        # Dropdown рисует кнопку без обёртки — поле и кнопка остаются соседями.
        dropdown_js = _read("web/static/src/core/dropdown/dropdown.js")
        self.assertIn('static template = xml`<t t-slot="default"/>`', dropdown_js)

    def test_core_view_switcher_contract(self):
        """Значок вида — класс из view.icon: у кнопок широкого экрана и в
        выпадашке узкого (кнопка активного вида и пункты)."""
        panel = _template("web/static/src/search/control_panel/control_panel.xml", "web.ControlPanel")
        icons = sorted(i.get("t-att-class") for i in panel.iter("i")
                       if i.get("t-att-class") in ("view.icon", "activeView.icon"))
        self.assertEqual(icons, ["activeView.icon", "view.icon", "view.icon"])
        nav = panel.find(".//nav")
        self.assertIn("o_cp_switch_buttons", _classes(nav))
        self.assertIn("o_switch_view", _classes(nav.find(".//button")))
