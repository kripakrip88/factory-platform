# -*- coding: utf-8 -*-
"""Тёмная тема, этап 2 (разбор UX, шаг 40, 05.10.2026): тема у человека,
тёмный класс до первой отрисовки, тёмные пары оставшихся экранов.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py), с темой theme_nexus и
HTTP-портом — здесь есть HttpCase (страница /odoo без браузера, Chrome не
нужен):
  odoo -d pmk40_test -i pmk_theme,theme_nexus,pmk_cut --test-enable \
       --test-tags /pmk_theme,/pmk_cut --stop-after-init --http-port 8099

Глазами (основной агент, копия, широкий экран, обе темы) — то, что здесь не
проверить: нет белой вспышки при загрузке, переключатель шага 47 мгновенный и
пишет выбор, экраны 40.3–40.5. Чистые правила переключателя
(static/src/js/color_scheme_rules.js) гоняет node вне Odoo. Здесь — то, что
ломается молча:
  • поле темы у человека: без значения по умолчанию (иначе не перенесётся
    выбор из браузера) и не копируется при «Дублировать» учётку, своё
    читается и пишется без прав на пользователей, чужое — нет;
  • сервер рисует body с o_nexus_dark только при выбранной тёмной теме и
    стоящей theme_nexus (без неё нет ни тёмной основы, ни кнопки возврата);
  • xpath нашего шаблона не находит узел ядра — -u упадёт;
  • штатный тёмный бандл не подключён (решение шага);
  • JS-файлы в сборке, правила раньше патча;
  • сборка стилей компилируется, тёмные пары на месте и только на экране,
    сильнее правил ядра (в том числе отложенного бандла) и темы, без яркого
    лайма заливкой (счётчики в шапке тоже); пузыри писем — лист письма:
    светлые, текст в них тёмный, и цвета отправителя в теле письма
    (теневой DOM, тема туда не достаёт) читаются; подпись свёрнутой колонки
    читается и за прозрачностью ядра.
"""
import copy
import re
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_open
from odoo.tools.template_inheritance import locate_node

SCSS = "pmk_theme/static/src/scss/"
JS = "pmk_theme/static/src/js/"
# Выключенные на стенде записи ir.asset темы (SELECT path, active FROM
# ir_asset, 05.10.2026: живые — navbar_nexus 39, theme_toggle 40,
# forms_nexus 41, dark 42, hidden 43) — явным списком, как в шаге 30.
DEAD_THEME_PATHS = {SCSS + "vendor/%s.scss" % name for name in (
    "variables", "glass_theme", "buttons", "forms", "lists", "kanban", "modals", "navbar")} | {
    SCSS + "%s.scss" % name for name in (
        "tokens", "base", "navbar", "surfaces", "controls", "chatter", "charts", "forms",
        "third_party")}
LIVE_THEME_PATHS = {
    SCSS + "navbar_nexus.scss",
    "pmk_theme/static/src/xml/theme_toggle.xml",
    SCSS + "forms_nexus.scss",
    SCSS + "dark.scss",
    SCSS + "hidden.scss",
}
BODY_CLASS = re.compile(r'<body[^>]*\bclass="([^"]*)"')
DARK = "body.o_nexus_dark "
# Яркий лайм заливкой режет глаз (решение владельца): в тёмной паре его нет.
BRIGHT_LIME = ("#c8f000", "#ddeb94", "#eef5c8", "200, 240, 0", "200,240,0", "221, 235, 148")
# Пузырь сообщения в тёмной теме — лист письма (доводка шага 40): светлый,
# как у ядра, внутри — светлая тема.
SHEET = DARK + ".o-discuss-text-body:has(> .o-mail-Message-bubble)"
LINK = "a:not(.btn):not(.nav-link):not(.dropdown-item):not(.pmk_app)"
# Цвета текста отправителя в телах писем стенда (SELECT по mail_message,
# 05.10.2026: письма клиентов в лидах — black, #000000, #1f497d, #004586,
# #2f5496, ссылки Outlook #0563c1; запросы цен — шаблон pmk_purchase с
# color:#1a1a1a и #000000). Тело письма — теневой DOM: тема эти цвета не
# перекрашивает, читаться они должны на самом пузыре.
SENDER_INKS = ("#000000", "#1a1a1a", "#1f497d", "#004586", "#2f5496", "#0563c1")


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _media_blocks(css, query):
    """Содержимое всех блоков «@media <query> { … }» подряд — по парным скобкам."""
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


def _rules(css):
    """{селектор: {свойство: значение}} для правил без вложенных блоков;
    список селекторов через запятую раскладывается по одному, повторы
    сливаются (последний выигрывает — как в браузере при равном весе)."""
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for decl in body.split(";"):
            if ":" in decl:
                name, value = decl.split(":", 1)
                decls[name.strip()] = value.strip()
        for selector in _split_selectors(selectors):
            found.setdefault(selector, {}).update(decls)
    return found


def _split_selectors(selectors):
    """Список через запятую — без разрезания запятых внутри :not(…, …)."""
    parts, depth, current = [], 0, ""
    for ch in selectors:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and not depth:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    parts.append(current.strip())
    return [p for p in parts if p]


def _specificity(selector):
    """Вес селектора (id, класс, тег). :has() :not() :is() — вес самого
    тяжёлого аргумента, :where() — ноль, псевдоэлемент — как тег."""
    ids = classes = tags = 0
    while True:
        match = re.search(r":(has|not|is|where)\(", selector)
        if not match:
            break
        depth, pos = 1, match.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(selector[pos], 0)
            pos += 1
        if match.group(1) != "where":
            inner = max(_specificity(part) for part in _split_selectors(selector[match.end():pos - 1]))
            ids, classes, tags = ids + inner[0], classes + inner[1], tags + inner[2]
        selector = selector[:match.start()] + selector[pos:]
    ids += len(re.findall(r"#[\w-]+", selector))
    classes += (len(re.findall(r"\.[\w-]+", selector)) + len(re.findall(r"\[[^\]]*\]", selector))
                + len(re.findall(r"(?<!:):[\w-]+", selector)))
    tags += len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", selector)) + len(re.findall(r"::[\w-]+", selector))
    return ids, classes, tags


def _hex(value):
    match = re.search(r"#[0-9a-fA-F]{6}\b", value or "")
    return match.group(0).lower() if match else None


def _lum(color):
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _blend(color, under, alpha):
    """Цвет color с прозрачностью alpha поверх under (opacity-50 ядра)."""
    return "#" + "".join(
        "%02x" % round(alpha * int(color[i:i + 2], 16) + (1 - alpha) * int(under[i:i + 2], 16))
        for i in (1, 3, 5))


def _read(path):
    with file_open(path) as f:
        return f.read()


def _xml(path):
    with file_open(path, "rb") as f:
        return etree.parse(f).getroot()


def _nexus_installed(env):
    return "theme_nexus" in env["ir.module.module"]._installed()


# ═══ Тема у человека ════════════════════════════════════════════════════════
@tagged("post_install", "-at_install")
class TestColorSchemeUser(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, login="pmk40_model", groups="base.group_user")
        cls.other = new_test_user(cls.env, login="pmk40_other", groups="base.group_user")

    def test_field(self):
        field = self.env["res.users"]._fields["pmk_color_scheme"]
        self.assertEqual(field.type, "selection")
        self.assertTrue(field.store)
        self.assertEqual(dict(field.selection), {"light": "Светлая", "dark": "Тёмная"})
        # Без значения по умолчанию: пусто = «ещё не выбирал» (светлая), и
        # только так переносится выбор, сохранённый в браузере до шага 40.
        self.assertFalse(field.default)
        self.assertFalse(field.copy, "«Дублировать» учётку не переносит тему")
        self.assertFalse(self.user.pmk_color_scheme)
        self.assertIn("pmk_color_scheme", self.env["res.users"].SELF_READABLE_FIELDS)
        self.assertIn("pmk_color_scheme", self.env["res.users"].SELF_WRITEABLE_FIELDS)

    def test_copy_starts_empty(self):
        """Учётку сотрудника заводят «Дублировать» от существующей (те же
        права): тема с ней не переезжает — у нового пусто, то есть светлая,
        а не чужая тёмная (выбор на сервере главнее браузера)."""
        self.user.pmk_color_scheme = "dark"
        clone = self.user.copy()
        self.assertNotEqual(clone, self.user)
        self.assertIs(clone.pmk_color_scheme, False)
        self.assertEqual(self.user.pmk_color_scheme, "dark", "у образца выбор остался")

    def test_switch_writes_own_choice_only(self):
        """Метод переключателя: своему — да, без прав на пользователей; чужое
        значение — отказ по-русски."""
        Users = self.env["res.users"].with_user(self.user)
        self.assertEqual(Users.pmk_set_color_scheme("dark"), "dark")
        self.assertEqual(self.user.pmk_color_scheme, "dark")
        self.assertFalse(self.other.pmk_color_scheme, "чужому — ничего")
        Users.pmk_set_color_scheme("light")
        self.assertEqual(self.user.pmk_color_scheme, "light")
        with self.assertRaisesRegex(ValidationError, "Тема оформления"):
            Users.pmk_set_color_scheme("purple")
        self.assertEqual(self.user.pmk_color_scheme, "light", "неверное значение не записано")

    def test_self_read_write_others_closed(self):
        """Своё поле — читается и пишется как поле предпочтений (штатный путь
        res.users для своей записи); чужая запись — закрыта, как прежде."""
        me = self.user.with_user(self.user)
        me.write({"pmk_color_scheme": "dark"})
        self.assertEqual(me.read(["pmk_color_scheme"])[0]["pmk_color_scheme"], "dark")
        with self.assertRaises(AccessError):
            self.other.with_user(self.user).write({"pmk_color_scheme": "dark"})

    def test_native_dark_bundle_off(self):
        """Решение шага 40: штатный web.assets_web_dark не включаем."""
        self.assertEqual(self.env["ir.http"].color_scheme(), "light")


# ═══ Шаблон загрузки и сборка JS ════════════════════════════════════════════
@tagged("post_install", "-at_install")
class TestColorSchemeAssets(TransactionCase):

    def test_template_contract(self):
        """Наш xpath находит узел в шаблоне ядра (иначе -u упадёт), вид живой,
        дописывает класс, а не переписывает «o_web_client»."""
        root = _xml("web/views/webclient_templates.xml")
        core = copy.deepcopy(root.find(".//template[@id='web.webclient_bootstrap']"))
        self.assertIsNotNone(core)
        self.assertEqual(len(core.xpath("//t[@t-set='body_classname']")), 1)
        view = self.env.ref("pmk_theme.webclient_color_scheme")
        self.assertTrue(view.active)
        self.assertEqual(view.inherit_id, self.env.ref("web.webclient_bootstrap"))
        arch = etree.fromstring(view.arch_db.encode())
        specs = list(arch.iter("xpath"))
        self.assertEqual(len(specs), 1)
        for spec in specs:
            with self.subTest(expr=spec.get("expr")):
                self.assertIsNotNone(locate_node(core, spec))
                self.assertEqual(spec.get("position"), "after")
                node = spec[0]
                self.assertEqual(node.get("t-set"), "body_classname")
                self.assertIn("session_info.get('pmk_color_scheme') == 'dark'", node.get("t-if"))
                self.assertIn("body_classname +", node.get("t-value"))
                self.assertIn("o_nexus_dark", node.get("t-value"))

    def test_js_in_bundle(self):
        paths = [p[0].lstrip("/") for p in self.env["ir.asset"]._get_asset_paths("web.assets_backend", {})]
        rules, patch_js = JS + "color_scheme_rules.js", JS + "color_scheme.js"
        self.assertIn(rules, paths)
        self.assertIn(patch_js, paths)
        self.assertLess(paths.index(rules), paths.index(patch_js), "правила — раньше патча")
        if _nexus_installed(self.env):
            # Механизм переключения — у чужой темы; порядок патчей не важен
            # (оба крючка срабатывают после всей цепочки setup).
            self.assertIn("theme_nexus/static/src/js/dark_mode.js", paths)
        # Имена, на которые опирается наш патч, — у чужой темы на месте.
        vendor = _read("theme_nexus/static/src/js/dark_mode.js")
        for name in ("nexusDarkState", "isDark", "nexus_theme_dark_mode", "o_nexus_dark"):
            with self.subTest(name=name):
                self.assertIn(name, vendor)
        # Код без комментариев: в пояснениях useService назван.
        code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", _read(patch_js), flags=re.S))
        self.assertIn("this.env.services", code, "запись — через env.services.orm, не useService")
        self.assertNotIn("useService", code, "грабля шага 31: промис компонента после уничтожения")
        self.assertIn('"pmk_set_color_scheme"', code)


# ═══ Страница веб-клиента ═══════════════════════════════════════════════════
@tagged("post_install", "-at_install")
class TestColorSchemePage(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = "pmk40-page-pass"
        self.user = new_test_user(self.env, login="pmk40_page", password=self.password,
                                  groups="base.group_user")

    def _page(self):
        self.authenticate(self.user.login, self.password)
        response = self.url_open("/odoo", timeout=60)
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertNotIn("web.assets_web_dark", html, "тёмный бандл ядра не включаем")
        return html

    def _body_classes(self):
        return BODY_CLASS.search(self._page()).group(1).split()

    def test_body_class_follows_user(self):
        nexus = _nexus_installed(self.env)
        for scheme, dark in ((False, False), ("light", False), ("dark", nexus)):
            with self.subTest(scheme=scheme):
                self.user.pmk_color_scheme = scheme
                classes = self._body_classes()
                self.assertIn("o_web_client", classes)
                self.assertEqual("o_nexus_dark" in classes, dark)
                self.assertEqual(classes.count("o_nexus_dark"), int(dark))

    def test_no_class_without_theme_nexus(self):
        """Чужую тему сняли — выбор в базе остаётся, класс сервер не ставит
        (без её тёмной основы и кнопки человек застрял бы в тёмной)."""
        self.assertEqual(self.env["ir.http"]._pmk_dark_mode_available(), _nexus_installed(self.env))
        self.user.pmk_color_scheme = "dark"
        IrHttp = type(self.env["ir.http"])
        with patch.object(IrHttp, "_pmk_dark_mode_available", lambda self: False):
            self.assertNotIn("o_nexus_dark", self._body_classes())
            info = self.make_jsonrpc_request("/web/session/get_session_info")
            self.assertIs(info["pmk_color_scheme"], False)
        self.user.invalidate_recordset(["pmk_color_scheme"])
        self.assertEqual(self.user.pmk_color_scheme, "dark", "выбор не стёрт")

    def test_session_info_and_switch_rpc(self):
        """Переключатель в браузере: session_info отдаёт выбор, метод пишет."""
        nexus = _nexus_installed(self.env)
        self.authenticate(self.user.login, self.password)
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertIs(info["pmk_color_scheme"], False)
        self.make_jsonrpc_request("/web/dataset/call_kw/res.users/pmk_set_color_scheme", {
            "model": "res.users", "method": "pmk_set_color_scheme",
            "args": ["dark"], "kwargs": {},
        })
        self.user.invalidate_recordset(["pmk_color_scheme"])
        self.assertEqual(self.user.pmk_color_scheme, "dark")
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertEqual(info["pmk_color_scheme"], "dark" if nexus else False)


# ═══ Тёмные пары шага 40 ════════════════════════════════════════════════════
@tagged("post_install", "-at_install")
class TestDarkPairsStep40(TransactionCase):
    """Сборка компилируется, тёмные пары на месте, только на экране (печать
    из тёмной темы остаётся светлой) и сильнее правил, которые закрывают."""

    _css = None
    _lazy_css = None

    def _stand_like_assets(self):
        theme = self.env["ir.asset"].search([("path", "=like", "pmk_theme/static/src/%")])
        theme.filtered(lambda a: a.path in DEAD_THEME_PATHS).active = False
        live = set(theme.filtered("active").mapped("path"))
        self.assertTrue(LIVE_THEME_PATHS <= live, live)

    def _compile(self, bundle_name):
        bundle = self.env["ir.qweb"]._get_asset_bundle(bundle_name, js=False)
        css = bundle.preprocess_css()
        self.assertFalse(bundle.css_errors, bundle.css_errors)
        return re.sub(r"\s+", " ", _strip_comments(css))

    def _backend_css(self):
        cls = type(self)
        if cls._css is None:
            self._stand_like_assets()
            cls._css = self._compile("web.assets_backend")
        return cls._css

    def _lazy(self):
        """Отложенный бандл: сводная, график, вид «Активность» — грузится после
        основного и при равном весе выигрывает."""
        cls = type(self)
        if cls._lazy_css is None:
            cls._lazy_css = self._compile("web.assets_backend_lazy")
        return cls._lazy_css

    def _screen(self):
        return _rules(_media_blocks(self._backend_css(), "@media screen"))

    def _assert_wins(self, ours, theirs, prop, ours_rules, theirs_rules):
        """Наше объявление свойства сильнее чужого: важность не ниже, при
        равной важности — вес выше (порядок файлов не в нашу пользу: у
        отложенного бандла он и вовсе обратный)."""
        self.assertIn(theirs, theirs_rules, "правило не найдено — сверка веса без смысла: " + theirs)
        self.assertIn(ours, ours_rules, ours)
        mine, other = ours_rules[ours].get(prop), theirs_rules[theirs].get(prop)
        self.assertTrue(mine, (ours, prop))
        self.assertTrue(other, (theirs, prop))
        mine_imp, other_imp = "!important" in mine, "!important" in other
        self.assertGreaterEqual(mine_imp, other_imp, "%s: у чужого !important" % prop)
        if mine_imp == other_imp:
            self.assertGreater(_specificity(ours), _specificity(theirs), (ours, theirs))

    def test_rules_present_and_screen_only(self):
        """Правила шага — в собранной сборке и все внутри @media screen."""
        screen = self._screen()
        outside = self._outside_screen()
        for selector in (
            "html:has(> body.o_nexus_dark)",
            DARK + ".o_kanban_renderer",
            DARK + ".o_column_progress.bg-300",
            DARK + ".o_kanban_renderer .o_kanban_counter > .o_column_progress .bg-200",
            DARK + ".o_column_progress .progress-bar.border-white",
            DARK + ".o_kanban_view .o_kanban_group.o_column_folded .o_column_title",
            DARK + ".btn-outline-primary",
            DARK + ".table",
            DARK + ".o_datetime_picker .o_selected",
            DARK + ".o_command_palette_listbox .o_command.focused",
            DARK + ".list-group-item-action:hover",
            DARK + ".o_calendar_renderer",
            DARK + ".o_calendar_renderer .o_calendar_widget",
            DARK + ".o_calendar_renderer .fc-event.o_past_event::after",
            DARK + ".o_calendar_view .fc-timegrid-col.fc-day-today",
            DARK + '.o_cw_popover[class*="o_calendar_color_"] .card-header',
            DARK + ".o_pivot table .o_pivot_header_cell_closed",
            DARK + ".o_pivot table .o_pivot_measure_row:hover",
            DARK + ".o_activity_view .o_activity_record:hover",
            DARK + ".o_activity_view .o_activity_view_table_footer",
            DARK + ".o_base_settings_view .o_form_renderer .o_setting_container .settings_tab .tab:hover",
            DARK + ".o_searchable_setting",
            DARK + ".o_import_data_sidepanel .o_import_file input:not(:valid)",
            DARK + ".o-discuss-text-body",
            SHEET,
            SHEET + " " + LINK,
            SHEET + " .text-muted",
            SHEET + " a.o-discuss-mention",
            SHEET + " .o-mail-Message-bubble.o-muted",
            DARK + ".o_activity_view .o_activity_summary_cell .o-mail-ActivityCell-counter",
            DARK + ".o_main_navbar .o_menu_systray .badge",
            DARK + ".o-main-components-container .o_loading_indicator",
            DARK + ".o-mail-AttachmentContainer",
            DARK + ".o-mail-AttachmentContainer .o-mail-AttachmentImage",
            DARK + ".o-mail-MessagingMenu-tab.active .o-mail-MessagingMenu-tabIcon",
            DARK + ".o-mail-discussSidebarBgColor",
            DARK + ".pmk-cut__piece",
            DARK + ".pmk-cut__rest--scrap",
        ):
            with self.subTest(rule=selector):
                self.assertIn(selector, screen)
                # Вне @media screen этих правил нет: печать из тёмной темы светлая.
                self.assertNotIn(selector, outside)

    def _outside_screen(self):
        """Правила сборки вне блоков «@media screen …» (по парным скобкам)."""
        css, out, start = self._backend_css(), [], 0
        query = "@media screen"
        pos = css.find(query)
        while pos != -1:
            out.append(css[start:pos])
            depth, i = 1, css.index("{", pos) + 1
            while depth:
                depth += {"{": 1, "}": -1}.get(css[i], 0)
                i += 1
            start = i
            pos = css.find(query, start)
        out.append(css[start:])
        return _rules(" ".join(out))

    def test_first_paint_dark(self):
        """Первая отрисовка с классом сервера — уже тёмная: тёмный фон body
        даёт чужая тема (!important), холст окна и полосы прокрутки — наш
        html:has(…)."""
        rules = _rules(self._backend_css())
        html = rules["html:has(> body.o_nexus_dark)"]
        self.assertEqual(html["background-color"], "#16171b")
        self.assertEqual(html["color-scheme"], "dark")
        if _nexus_installed(self.env):
            body = rules.get("body.o_nexus_dark", {})
            self.assertEqual(body.get("background", "").lower(), "#16171b !important")

    def test_outweigh_main_bundle(self):
        """Тёмная пара сильнее правила ядра или темы из основного бандла."""
        rules = _rules(self._backend_css())
        screen = self._screen()
        nexus = _nexus_installed(self.env)
        pairs = [
            (DARK + ".o_kanban_renderer", ".o_kanban_renderer", "--Kanban-background"),
            (DARK + ".o_kanban_renderer", ".o_kanban_renderer", "--KanbanColumn__highlight-selected"),
            (DARK + ".o_column_progress.bg-300", ".bg-300", "--background-color"),
            (DARK + ".o_kanban_renderer .o_kanban_counter > .o_column_progress .bg-200",
             ".o_kanban_renderer .o_kanban_counter > .o_column_progress .bg-200", "--background-color"),
            (DARK + ".btn-outline-primary", ".btn-outline-primary", "--btn-color"),
            (DARK + ".table", ".table", "--table-border-color"),
            (DARK + ".o_datetime_picker .o_selected", ".o_datetime_picker .o_selected", "color"),
            (DARK + ".o_datetime_picker .o_select_start", ".o_datetime_picker .o_select_start",
             "--selected-day-color"),
            (DARK + ".o_command_palette_listbox .o_command.focused",
             ".o_command_palette_listbox .o_command.focused", "background"),
            (DARK + ".o_calendar_renderer", ".o_calendar_renderer", "background-color"),
            (DARK + ".o_calendar_renderer .o_calendar_widget", ".o_calendar_renderer .o_calendar_widget",
             "--fc-page-bg-color"),
            (DARK + ".o_calendar_renderer .fc-event.o_past_event::after",
             ".o_calendar_renderer .fc-event.o_past_event::after", "background-color"),
            (DARK + ".o_calendar_renderer .o_calendar_widget .o_calendar_disabled",
             ".o_calendar_renderer .o_calendar_widget .o_calendar_disabled", "background-color"),
            (DARK + '.o_cw_popover[class*="o_calendar_color_"] .card-header .popover-header',
             ".o_cw_popover.o_calendar_color_1 .card-header .popover-header", "color"),
            (DARK + ".o_base_settings_view .o_form_renderer .o_setting_container .settings_tab .tab:hover",
             ".o_base_settings_view .o_form_renderer .o_setting_container .settings_tab .tab:hover", "color"),
            (DARK + ".o_base_settings_view .o_form_renderer .o_setting_container .settings .settingSearchHeader",
             ".o_base_settings_view .o_form_renderer .o_setting_container .settings .settingSearchHeader",
             "background-color"),
            (DARK + ".o_searchable_setting", ".o_searchable_setting", "--SearchableSetting__highlight-background"),
            (DARK + ".o-discuss-text-body", ".o-discuss-text-body", "color"),
            (DARK + ".o-mail-Message-date", ".o-mail-Message-date", "color"),
            (DARK + ".o-mail-Message-bubble.o-muted", ".o-mail-Message-bubble.o-muted", "background-color"),
            # Цитата «в ответ на» — сама пузырь o-muted: у ядра её подложку
            # задаёт правило o-muted (0,2,0), а не MessageInReply-core (0,1,0).
            (DARK + ".o-mail-Message-bubble.o-muted", ".o-mail-MessageInReply-core", "background-color"),
            (DARK + "a.o-discuss-mention", "a.o-discuss-mention", "background-color"),
            # Лист письма: внутри пузыря светлая тема сильнее тёмных правил
            # ленты и раздела 1 (ссылки), иначе тёмный текст отправителя и
            # светлые ссылки темы смешались бы на светлом пузыре.
            (SHEET, DARK + ".o-discuss-text-body", "color"),
            (SHEET + " " + LINK, DARK + LINK, "color"),
            (SHEET + " .text-muted", DARK + ".text-muted", "color"),
            (SHEET + " a.o-discuss-mention", DARK + "a.o-discuss-mention", "background-color"),
            (SHEET + " a.o_mail_redirect", DARK + "a.o_mail_redirect", "outline-color"),
            (SHEET + " .o-mail-Message-bubble.o-muted", DARK + ".o-mail-Message-bubble.o-muted",
             "background-color"),
            (DARK + ".o-mail-AttachmentContainer", ".o-mail-AttachmentContainer", "background-color"),
            (DARK + ".o-mail-MessagingMenu-tab.active .o-mail-MessagingMenu-tabIcon",
             ".o-mail-MessagingMenu-tab.active .o-mail-MessagingMenu-tabIcon", "background"),
            (DARK + ".o-mail-NotificationItem-markAsRead", ".o-mail-NotificationItem-markAsRead",
             "background-color"),
            (DARK + ".o-mail-discussSidebarBgColor", ".o-mail-discussSidebarBgColor", "background-color"),
            (DARK + ".o-mail-DiscussSearch-inputContainer", ".o-mail-DiscussSearch-inputContainer",
             "background-color"),
            (DARK + ".o-mail-DiscussSidebar-item:hover", ".o-mail-DiscussSidebar-item:hover", "background-color"),
        ]
        if nexus:
            pairs += [
                (DARK + ".list-group-item-action:hover", ".list-group-item-action:hover", "background"),
                (DARK + ".o_kanban_view .o_kanban_group.o_column_folded .o_column_title",
                 ".o_kanban_view .o_kanban_group .o_column_title", "color"),
                # Счётчики в шапке и «Загрузка»: лайм заливкой у темы
                # (dark_mode.scss) — пара тяжелее.
                (DARK + ".o_main_navbar .o_menu_systray .badge", DARK + ".o_menu_systray .badge",
                 "background-color"),
                (DARK + ".o_main_navbar .o_menu_systray .badge", DARK + ".o_menu_systray .badge", "color"),
                (DARK + ".o-main-components-container .o_loading_indicator", DARK + ".o_loading_indicator",
                 "background-color"),
                (DARK + ".o-main-components-container .o_loading_indicator", DARK + ".o_loading_indicator",
                 "color"),
            ]
            # Белое кольцо счётчика светлой темы (border: 2px solid #FFFFFF,
            # theme_nexus/navbar.scss) — пара тяжелее, своя заливка у светлой
            # (background с !important) — тоже.
            light_badge = ".o_main_navbar .o_menu_systray .badge"
            self.assertIn(light_badge, rules)
            self.assertIn("border", rules[light_badge])
            self.assertGreater(_specificity(DARK + light_badge), _specificity(light_badge))
            self.assertEqual(screen[DARK + light_badge]["border-color"], "var(--pmk-surface)")
        if ".o_import_data_sidepanel .o_import_file input:not(:valid)" in rules:
            pairs.append((DARK + ".o_import_data_sidepanel .o_import_file input:not(:valid)",
                          ".o_import_data_sidepanel .o_import_file input:not(:valid)", "background-color"))
        for ours, theirs, prop in pairs:
            with self.subTest(ours=ours, prop=prop):
                self._assert_wins(ours, theirs, prop, screen, rules)
        # Колонка «сегодня» недели — у темы !important, у нас тоже и тяжелее.
        theme_today = ".o_calendar_view .fc-timegrid-col.fc-day-today"
        if theme_today in rules:
            self._assert_wins(DARK + theme_today, theme_today, "background", screen, rules)
        # Функция веса — на известных примерах.
        self.assertEqual(_specificity(DARK + ".o_datetime_picker .o_date_item_picker "
                                      ".o_datetime_button.o_selected:not(.o_select_start, .o_select_end)"),
                         (0, 6, 1))
        self.assertEqual(_specificity(DARK + ".o_calendar_renderer .fc-event.o_past_event::after"), (0, 4, 2))

    def test_outweigh_lazy_bundle(self):
        """Сводная и «Активность» — в отложенном бандле: он грузится позже, при
        равном весе выиграл бы он."""
        lazy = _rules(self._lazy())
        screen = self._screen()
        pairs = [
            (DARK + ".o_pivot table .o_pivot_header_cell_closed",
             ".o_pivot table .o_pivot_header_cell_closed", "color"),
            (DARK + ".o_pivot table.o_enable_linking .o_pivot_cell_value:not(.o_empty)",
             ".o_pivot table.o_enable_linking .o_pivot_cell_value:not(.o_empty)", "color"),
            (DARK + ".o_pivot table .o_pivot_header_cell_opened:hover",
             ".o_pivot table .o_pivot_header_cell_opened:hover", "background-color"),
            (DARK + ".o_pivot table .o_pivot_measure_row:hover",
             ".o_pivot table .o_pivot_measure_row:hover", "background-color"),
        ]
        activity = ".o_activity_view .o_activity_record:hover"
        if activity in lazy:  # вид «Активность» — модуль mail
            pairs += [
                (DARK + activity, activity, "background-color"),
                (DARK + ".o_activity_view .o_activity_summary_cell.o_activity_empty_cell:hover",
                 ".o_activity_view .o_activity_summary_cell.o_activity_empty_cell:hover", "background-color"),
                (DARK + ".o_activity_view .o_activity_view_table_footer",
                 ".o_activity_view .o_activity_view_table_footer", "background-color"),
                (DARK + ".o_activity_view .o_activity_filter_overdue",
                 ".o_activity_view .o_activity_filter_overdue", "background-color"),
                # Счётчик «2» / «1 / 3» в ячейке: подложку bg-light этап 1
                # сделал тёмной, цифру ядро красит тёмной — 1,03.
                (DARK + ".o_activity_view .o_activity_summary_cell .o-mail-ActivityCell-counter",
                 ".o_activity_view .o_activity_summary_cell .o-mail-ActivityCell-counter", "color"),
            ]
            counter = _hex(lazy[".o_activity_view .o_activity_summary_cell .o-mail-ActivityCell-counter"]["color"])
            pill = _hex(screen[DARK + ".bg-light"]["--background-color"])
            if counter:
                self.assertLess(_contrast(counter, pill), 2, "цифра ядра на тёмной подложке — повод пары")
            ink = _hex(screen[DARK.strip()]["--pmk-ink"])
            self.assertGreaterEqual(_contrast(ink, pill), 4.5)
        for ours, theirs, prop in pairs:
            with self.subTest(ours=ours, prop=prop):
                self._assert_wins(ours, theirs, prop, screen, lazy)
        # Ядро красит заголовки сводной литералом $body-color — тёмный текст
        # (поэтому пара и нужна). Перекрасит ядро — пару пересмотреть.
        closed = _hex(lazy[".o_pivot table .o_pivot_header_cell_closed"]["color"])
        if closed:
            self.assertLess(_contrast(closed, "#1e2025"), 2)

    def test_dark_colours_readable(self):
        """Текст ленты без пузыря (заметки, «Изменено») — светлый на тёмном.
        Пузыри писем — лист письма: светлые, как у ядра (тёмной пары у них
        нет), текст в них тёмный — и наш, и цвета отправителя в теле письма
        (теневой DOM: тема туда не достаёт, ядро гасит их только в своём
        тёмном режиме, а его мы не включаем). Подпись свёрнутой колонки — не
        ниже 4,5 и за прозрачностью ядра, счётчики шапки — без лайма,
        полоса прогресса — тёмная."""
        screen = self._screen()
        rules = _rules(self._backend_css())
        tokens = screen[DARK.strip()]
        ink, ink2 = _hex(tokens["--pmk-ink"]), _hex(tokens["--pmk-ink-2"])
        self.assertEqual(screen[DARK + ".o-discuss-text-body"]["color"], "var(--pmk-ink-2) !important")
        self.assertGreaterEqual(_contrast(ink2, _hex(tokens["--pmk-surface"])), 4.5, "заметка на ленте")
        self.assertEqual(screen[SHEET]["color"], "#495057 !important")
        sheet_ink = _hex(screen[SHEET]["color"])
        link_ink = _hex(screen[SHEET + " " + LINK]["color"])
        for bubble in ("o-blue", "o-green", "o-orange"):
            with self.subTest(bubble=bubble):
                for selector in (DARK + ".o-mail-Message-bubble." + bubble,
                                 DARK + ".o-mail-Message-bubbleTail." + bubble):
                    self.assertNotIn("--o-message-bubble-bg", screen.get(selector, {}),
                                     "тёмный пузырь под чёрным текстом письма давал 1,1–2,0")
                bg = _hex(rules[".o-mail-Message-bubble." + bubble]["--o-message-bubble-bg"])
                self.assertTrue(bg)
                self.assertGreater(_lum(bg), 0.7, "пузырь ядра светлый — лист письма")
                for colour in (sheet_ink, link_ink) + SENDER_INKS:
                    with self.subTest(ink=colour):
                        self.assertGreaterEqual(_contrast(colour, bg), 4.5)
                # Светлый текст ленты на таком пузыре пропал бы: потому лист
                # письма и возвращает тёмный.
                self.assertLess(_contrast(ink2, bg), 2)
        # Свёрнутая колонка: ядро гасит подпись opacity-50 — цвет самый светлый.
        folded = screen[DARK + ".o_kanban_view .o_kanban_group.o_column_folded .o_column_title"]
        self.assertEqual(folded["color"], "var(--pmk-ink)")
        for under in (_hex(tokens["--pmk-bg"]), _hex(tokens["--pmk-surface"])):
            with self.subTest(folded_on=under):
                self.assertGreaterEqual(_contrast(_blend(ink, under, 0.5), under), 4.5)
        # Счётчики в шапке и «Загрузка»: светлая заливка под тёмной цифрой.
        for selector in (DARK + ".o_main_navbar .o_menu_systray .badge",
                         DARK + ".o-main-components-container .o_loading_indicator"):
            with self.subTest(selector=selector):
                decls = screen[selector]
                self.assertEqual(decls["background-color"], "var(--pmk-ink) !important")
                self.assertGreaterEqual(_contrast(ink, _hex(decls["color"])), 4.5)
        track = _hex(screen[DARK + ".o_column_progress.bg-300"]["--background-color"])
        self.assertLess(_lum(track), 0.05, "дорожка полосы — тёмная")
        self.assertEqual(screen[DARK + ".o_column_progress .progress-bar.border-white"]["border-color"],
                         "#16171b !important")

    def test_step40_source(self):
        """Раздел «Шаг 40» — в dark.scss одним блоком @media screen, без
        яркого лайма заливкой; прежние разделы на месте."""
        src = _read(SCSS + "dark.scss")
        start = src.index("// ═══ Шаг 40")
        # раздел — до следующего «// ═══ Шаг …» (шаг 48 дописан после)
        nxt = src.find("// ═══ Шаг", start + 1)
        section = src[start:nxt if nxt != -1 else None]
        code = re.sub(r"//[^\n]*", "", section).lower()
        for lime in BRIGHT_LIME:
            with self.subTest(lime=lime):
                self.assertNotIn(lime, code, "лайм заливкой — только приглушённый")
        self.assertTrue(code.strip().startswith("@media screen {"))
        self.assertEqual(code.count("@media"), 1)
        for earlier in ("Шаг 30: подсветки и лента", "Шаг 35: раскрой"):
            with self.subTest(section=earlier):
                self.assertLess(src.index(earlier), start)

    def test_core_markup_contract(self):
        """Разметка ядра, на которую опираются пары: классы на месте."""
        checks = {
            "web/static/src/views/view_components/column_progress.xml": (
                "o_column_progress progress bg-300", "border border-white"),
            # Свёрнутую колонку ядро гасит прозрачностью — цвет пары с запасом.
            "web/static/src/views/kanban/kanban_header.xml": (
                "o_kanban_counter", "o_column_title", "opacity-50 opacity-100-hover"),
            "web/static/src/views/pivot/pivot_renderer.xml": (
                "o_pivot_header_cell_closed", "o_enable_linking", "o_pivot_measure_row"),
            "web/static/src/views/calendar/calendar_common/calendar_common_popover.xml": (
                "card-header", "popover-header"),
            "web/static/src/webclient/settings_form_view/settings_form_view.scss": (
                "settingSearchHeader", ".highlighter"),
            "web/static/src/core/datetime/datetime_picker.xml": ("o_selected", "o_select_start"),
            "mail/static/src/core/common/message.xml": (
                "o-discuss-text-body", "o-mail-Message-bubble", "'o-blue'", "'o-green'", "'o-orange'",
                't-ref="shadowBody"'),
            # Почему пузырь — лист письма: тело письма в теневом DOM, цвета
            # отправителя ядро гасит только в своём тёмном режиме (кука).
            "mail/static/src/core/common/message.js": ("attachShadow", "isOdooWhiteTheme"),
            "mail/static/src/core/common/store_service.js": ('cookie.get("color_scheme")',),
            # Цитата «в ответ на» — сама пузырь o-muted.
            "mail/static/src/core/common/message_in_reply.xml": (
                "o-mail-MessageInReply-core o-mail-Message-bubble o-muted",),
            "mail/static/src/views/web/activity/activity_cell.xml": (
                "o-mail-ActivityCell-counter badge bg-light",),
            "web/static/src/webclient/navbar/navbar.xml": ("o_main_navbar", "o_menu_systray"),
            "web/static/src/core/main_components_container.js": ("o-main-components-container",),
            "web/static/src/webclient/loading_indicator/loading_indicator.xml": ("o_loading_indicator",),
            "mail/static/src/core/common/composer.xml": ("o-discuss-text-body",),
            "mail/static/src/core/common/attachment_list.xml": (
                "o-mail-AttachmentContainer", "o-mail-Attachment-hover", "o-mail-AttachmentImage"),
            "mail/static/src/core/public_web/messaging_menu.scss": ("--mail-MessagingMenu-bg",),
            "mail/static/src/core/common/navigable_list.scss": ("--mail-NavigableList-activeBgColor",),
            "mail/static/src/views/web/activity/activity_renderer.xml": (
                "o_activity_view_table_footer", "o_activity_filter_"),
        }
        for path, needles in checks.items():
            try:
                src = _read(path)
            except (FileNotFoundError, ValueError):
                continue  # модуль не в пути аддонов
            for needle in needles:
                with self.subTest(path=path, needle=needle):
                    self.assertIn(needle, src)
