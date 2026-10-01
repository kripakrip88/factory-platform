# -*- coding: utf-8 -*-
"""Подсветки и лента (разбор UX, шаг 30) — что доезжает до браузера.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py), с темой theme_nexus:
  odoo -d pmk30_test -i pmk_theme,theme_nexus,pmk_mail_ui --test-enable \
       --test-tags /pmk_theme --stop-after-init --http-port 8099

Вид (контурные кнопки ленты, «История» слева, лаймовые выбранные строки,
обе темы) смотрит основной агент глазами на копии. Здесь — то, что ломается
молча:
  • сборка стилей бэкенда падает (ошибка SCSS — и без стилей вся система);
  • правило положено в выключенный scss и на стенд не доехало;
  • светлое правило слабее заливки темы (чёрной или тёмного лайма) — кнопка
    так и остаётся залитой; тёмная пара слабее светлого правила — в тёмной
    теме белая кнопка;
  • у правила с цветом нет тёмной пары;
  • контурная кнопка потеряла кольцо фокуса с клавиатуры (box-shadow: none
    сильнее кольца темы — доводка: так было у «Написать» в почте);
  • ядро после обновления сменило разметку, на которую опираются правила
    (классы кнопок ленты, «Новое» формы, «Сохранить и создать» в окне новой
    строки, классы выбранной строки, плашка «N выбрано», строка почты и
    редактор письма) — правило перестанет срабатывать молча.
"""
import copy
import re

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open
from odoo.tools.template_inheritance import locate_node

SCSS = "pmk_theme/static/src/scss/"
LIVE_THEME_PATHS = {
    SCSS + "navbar_nexus.scss",
    "pmk_theme/static/src/xml/theme_toggle.xml",
    SCSS + "forms_nexus.scss",
    SCSS + "dark.scss",
}
# Выключенные на стенде записи ir.asset темы (SELECT path, active FROM
# ir_asset, 02.10.2026) — явным списком, а не «всё, кроме живых»: файл,
# который подключит следующий шаг, тест выключать не должен.
DEAD_THEME_PATHS = {SCSS + "vendor/%s.scss" % name for name in (
    "variables", "glass_theme", "buttons", "forms", "lists", "kanban", "modals", "navbar")} | {
    SCSS + "%s.scss" % name for name in (
        "tokens", "base", "navbar", "surfaces", "controls", "chatter", "charts", "forms",
        "third_party")}

DARK = "body.o_nexus_dark "
SEND = ".o-mail-Chatter-topbar .btn-primary.o-mail-Chatter-sendMessage"
NOTE = ".o-mail-Chatter-topbar .btn-primary.o-mail-Chatter-logNote"
CREATE = ".btn.o_form_button_create"
COMPOSE = ".o_mail_client:has(.o_mail_client_composer) .o_mail_client_topbar .btn-primary"
CODE_TOGGLE = ".o_mail_client_composer .btn-sm.btn-primary"
# «Сохранить и создать» в окне новой строки (доводка шага 30).
SAVE_NEW = ".modal-footer .btn.o_form_button_save_new"
TOGGLE = ".o-mail-Chatter-topbar > .pmk-chatter-toggle.btn"
ROW = ".o_list_renderer .o_data_row.o_data_row_selected"
ROW_TICK = ROW + " > td.o_list_record_selector"
BOX = ".o_selection_box .list-group-item.active"
SELECT_ALL = BOX + " .o_select_domain.btn-info"
# Контурные кнопки шага: белые с рамкой, тень погашена — кольцо фокуса с
# клавиатуры у каждой возвращено своим :focus-visible.
OUTLINED = (SEND, NOTE, CREATE, COMPOSE, CODE_TOGGLE, SAVE_NEW)
# Правила шага с цветом: у каждого — тёмная пара (геометрия «Истории» — нет).
COLOURED = OUTLINED + (ROW, ROW_TICK, SELECT_ALL)


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
        for selector in selectors.split(","):
            found.setdefault(selector.strip(), {}).update(decls)
    return found


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
            inner = max(_specificity(part) for part in selector[match.end():pos - 1].split(","))
            ids, classes, tags = ids + inner[0], classes + inner[1], tags + inner[2]
        selector = selector[:match.start()] + selector[pos:]
    ids += len(re.findall(r"#[\w-]+", selector))
    classes += (len(re.findall(r"\.[\w-]+", selector)) + len(re.findall(r"\[[^\]]*\]", selector))
                + len(re.findall(r"(?<!:):[\w-]+", selector)))
    tags += len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", selector)) + len(re.findall(r"::[\w-]+", selector))
    return ids, classes, tags


def _xml(path):
    with file_open(path, "rb") as f:
        return etree.parse(f).getroot()


def _read(path):
    with file_open(path) as f:
        return f.read()


def _template(path, name):
    node = _xml(path).find("t[@t-name='%s']" % name)
    assert node is not None, (path, name)
    return copy.deepcopy(node)


def _classes(node):
    return (node.get("class") or "").split()


@tagged("post_install", "-at_install")
class TestHighlightsStep30(TransactionCase):

    _backend_css_cache = None

    def _nexus_installed(self):
        return self.env["ir.module.module"]._get("theme_nexus").state == "installed"

    def _stand_like_assets(self):
        theme = self.env["ir.asset"].search([("path", "=like", "pmk_theme/static/src/%")])
        theme.filtered(lambda a: a.path in DEAD_THEME_PATHS).active = False
        live = set(theme.filtered("active").mapped("path"))
        self.assertTrue(LIVE_THEME_PATHS <= live, live)
        self.assertFalse(live & DEAD_THEME_PATHS)

    def _backend_css(self):
        cls = type(self)
        if cls._backend_css_cache is None:
            self._stand_like_assets()
            bundle = self.env["ir.qweb"]._get_asset_bundle("web.assets_backend", js=False)
            css = bundle.preprocess_css()
            self.assertFalse(bundle.css_errors, bundle.css_errors)
            cls._backend_css_cache = re.sub(r"\s+", " ", css)
        return cls._backend_css_cache

    # ─── Сборка ─────────────────────────────────────────────────────────
    def test_backend_css_compiles(self):
        """Вся сборка web.assets_backend компилируется одним источником SCSS
        (ошибка в нашем файле оставила бы без стилей всю систему), и правила
        шага — в ней: значит, лежат в живых файлах темы."""
        rules = _rules(self._backend_css())
        for selector in COLOURED + (TOGGLE, BOX):
            with self.subTest(selector=selector):
                self.assertIn(selector, rules)
            if selector != TOGGLE:
                with self.subTest(dark=selector):
                    self.assertIn(DARK + selector, rules, "у правила с цветом нет тёмной пары")

    def test_light_rules(self):
        rules = _rules(self._backend_css())
        for selector in (SEND, NOTE, CREATE, COMPOSE, SAVE_NEW):
            with self.subTest(selector=selector):
                decls = rules[selector]
                self.assertTrue(decls["background"].startswith("#fff"), decls)
                self.assertIn("#dad5c8", decls["border"])
                self.assertEqual(decls["box-shadow"], "none !important")
                self.assertIn(selector + ":hover", rules)
        # Кольцо фокуса с клавиатуры не погашено (box-shadow: none выше): у
        # всех контурных кнопок шага, в том числе в почте (доводка: у
        # «Написать» и нажатой «</>» кольца не было), — и сильнее гашения.
        for selector in OUTLINED:
            with self.subTest(focus=selector):
                focus = selector + ":focus-visible"
                self.assertIn("0 0 0 3px", rules[focus]["box-shadow"])
                self.assertIn("!important", rules[focus]["box-shadow"])
                self.assertGreater(_specificity(focus), _specificity(selector))
        # Нажатая кнопка ленты и нажатая «</>» в почте — тёмной рамкой.
        self.assertIn("#16191c", rules[SEND + ".active"]["border-color"])
        self.assertIn("#16191c", rules[CODE_TOGGLE]["border-color"])

        toggle = rules[TOGGLE]
        self.assertEqual(toggle["width"], "auto", "«История» по содержимому, не на всю строку")
        self.assertEqual(toggle["flex"], "0 0 auto")
        self.assertEqual(toggle["min-height"], "0")
        self.assertIn("--btn-padding-y", toggle["padding"], "высота — как у соседних кнопок")
        self.assertEqual(rules[TOGGLE + " .pmk-chatter-toggle__arrow"]["margin-left"], "0")

        row = rules[ROW]
        self.assertEqual(row["--table-bg"], "#ddeb94")
        self.assertEqual(row["--table-striped-bg"], "transparent !important",
                         "иначе подложка полос темы закроет лайм у каждой второй строки")
        self.assertIn("!important", row["--table-hover-bg"])
        self.assertNotEqual(row["--table-hover-bg"].split()[0], "transparent",
                            "выбранная под курсором — темнее выбранной")
        tick = rules[ROW_TICK]["box-shadow"]
        self.assertIn("inset 3px 0 0 #7f9412", tick)
        self.assertIn("9999px var(--table-bg-state", tick, "без подложки Bootstrap пропадёт наведение")
        self.assertIn("#ddeb94", rules[BOX]["background-color"])

    def test_same_lime_as_open_letter(self):
        """Выбранная строка — тем же лаймом, что открытое письмо в почте."""
        rules = _rules(self._backend_css())
        self.assertEqual(rules[".o_mail_client"]["--mc-active-bg"], rules[ROW]["--table-bg"])
        dark_row = _rules(_media_blocks(self._backend_css(), "@media screen"))[DARK + ROW]
        self.assertEqual(rules[DARK + ".o_mail_client"]["--mc-active-bg"], dark_row["--table-bg"])

    def test_dark_pairs(self):
        """Тёмная пара — под @media screen (печать светлая) и тёмными цветами."""
        screen = _rules(_media_blocks(self._backend_css(), "@media screen"))
        for selector in OUTLINED:
            with self.subTest(selector=selector):
                decls = screen[DARK + selector]
                self.assertEqual(decls["background"], "var(--pmk-surface-2) !important")
                self.assertEqual(decls["color"], "var(--pmk-ink) !important")
                self.assertIn(DARK + selector + ":hover", screen)
                # Светлое кольцо на тёмном листе: тёмное светлой темы не видно.
                focus = screen[DARK + selector + ":focus-visible"]["box-shadow"]
                self.assertIn("rgba(255,255,255", focus.replace(" ", ""))
        # Соседи ленты отвечают на наведение так же.
        self.assertIn(DARK + ".o-mail-Chatter-topbar .btn-secondary:hover", screen)
        row = screen[DARK + ROW]
        self.assertEqual(row["--table-bg"], "#3d451e")
        self.assertEqual(row["--table-striped-bg"], "transparent !important")
        self.assertIn("#9bb52a", screen[DARK + ROW_TICK]["box-shadow"])
        self.assertIn("--pmk-accent", screen[
            DARK + ROW + " .o_list_record_selector .form-check-input:checked"]["border-color"],
            "отмеченный флажок на тёмном лайме строки — с рамкой")

    def test_outweigh_theme(self):
        """Наше правило сильнее заливки темы, тёмная пара — сильнее светлой.
        Правила темы, с которыми спорим, — живые (есть в сборке)."""
        rules = _rules(self._backend_css())
        # Правила чужой темы theme_nexus — в сборке, только если она стоит.
        nexus_only = {".o_form_button_create", DARK + ".form-check-input:checked"}
        theirs = {
            SEND: ".btn-primary", NOTE: ".btn-primary", COMPOSE: ".btn-primary",
            CODE_TOGGLE: ".btn-primary", CREATE: ".o_form_button_create",
            SAVE_NEW: ".btn-primary",
            TOGGLE: ".pmk-chatter-toggle.btn", ROW: ".table-info",
        }
        # Тёмная заливка лаймом — dark.scss, разделы 4 и 5 (и theme_nexus).
        dark_theirs = {
            SEND: DARK + ".btn-primary", NOTE: DARK + ".btn-primary", COMPOSE: DARK + ".btn-primary",
            CODE_TOGGLE: DARK + ".btn-primary", CREATE: DARK + ".o_form_button_create",
            SAVE_NEW: DARK + ".btn-primary",
            ROW: DARK + ".o_list_renderer .table-info",
            DARK + ROW + " .o_list_record_selector .form-check-input:checked":
                DARK + ".form-check-input:checked",
        }
        for ours, other in theirs.items():
            with self.subTest(ours=ours):
                if other in nexus_only and not self._nexus_installed():
                    continue
                self.assertIn(other, rules, "правило темы не найдено — сверка веса без смысла")
                self.assertGreater(_specificity(ours), _specificity(other))
        for ours, other in dark_theirs.items():
            dark = ours if ours.startswith(DARK) else DARK + ours
            with self.subTest(dark=dark):
                if not ours.startswith(DARK):
                    self.assertGreater(_specificity(dark), _specificity(ours),
                                       "тёмная пара слабее светлого — в тёмной теме светлая кнопка")
                if other in nexus_only and not self._nexus_installed():
                    continue
                self.assertIn(other, rules)
                self.assertGreater(_specificity(dark), _specificity(other))
        # Сама функция веса — на известных примерах.
        self.assertEqual(_specificity(SEND), (0, 3, 0))
        self.assertEqual(_specificity(DARK + ".btn-primary"), (0, 2, 1))
        self.assertEqual(_specificity(COMPOSE), (0, 4, 0))
        self.assertEqual(_specificity(SAVE_NEW), (0, 3, 0))
        self.assertEqual(_specificity(DARK + SAVE_NEW), (0, 4, 1))
        self.assertEqual(_specificity(ROW_TICK), (0, 4, 1))

    # ─── Разметка ядра, на которую опираются правила ────────────────────
    def test_core_chatter_markup(self):
        """Кнопки ленты — дети строки кнопок (между ними только <t>), класс
        btn-primary ядро ставит им через t-att-class; наш шаблон вставляет
        «Историю» перед «Отправить сообщение» — тоже прямым ребёнком строки."""
        chatter = _template("mail/static/src/chatter/web/chatter.xml", "mail.Chatter")
        topbar = chatter.xpath(".//div[contains(concat(' ', @class, ' '), ' o-mail-Chatter-topbar ')]")
        self.assertEqual(len(topbar), 1)
        for cls in ("o-mail-Chatter-sendMessage", "o-mail-Chatter-logNote"):
            with self.subTest(button=cls):
                buttons = topbar[0].xpath(".//button[contains(concat(' ', @class, ' '), ' %s ')]" % cls)
                self.assertEqual(len(buttons), 1)
                button = buttons[0]
                self.assertIn("btn-primary", button.get("t-att-class") or "")
                parent = button.getparent()
                while parent is not topbar[0]:
                    self.assertEqual(parent.tag, "t", "между строкой и кнопкой появился узел")
                    parent = parent.getparent()

        ours = _xml("pmk_theme/static/src/xml/chatter.xml").find("t[@t-inherit='mail.Chatter']")
        spec = [x for x in ours.iter("xpath") if x.get("position") == "before"]
        self.assertEqual(len(spec), 1)
        self.assertIn("o-mail-Chatter-sendMessage", spec[0].get("expr"))
        self.assertIsNotNone(locate_node(chatter, spec[0]))
        self.assertIn("pmk-chatter-toggle", _classes(spec[0].find("button")))
        self.assertIn("btn", _classes(spec[0].find("button")))

    def test_core_form_and_list_markup(self):
        form = _xml("web/static/src/views/form/form_controller.xml")
        creates = form.xpath("//button[contains(concat(' ', @class, ' '), ' o_form_button_create ')]")
        self.assertEqual(len(creates), 2, "«Новое» в панели и в окне формы")
        for button in creates:
            self.assertIn("btn", _classes(button))

        js = _read("web/static/src/views/list/list_renderer.js")
        self.assertIn('classNames.push("table-info")', js)
        self.assertIn('classNames.push("o_data_row_selected")', js)
        lst = _read("web/static/src/views/list/list_renderer.xml")
        self.assertIn("table-striped", lst)
        self.assertIn('class="o_list_record_selector', lst)

        box = _template("web/static/src/views/view_components/selection_box.xml", "web.SelectionBox")
        item = box.find(".//span")
        self.assertIn("list-group-item", _classes(item))
        self.assertIn("active", _classes(item))
        domain = item.xpath(".//button[contains(concat(' ', @class, ' '), ' o_select_domain ')]")
        self.assertTrue(domain and "btn-info" in _classes(domain[0]))

    def test_core_dialog_buttons_markup(self):
        """Окно новой строки (доводка шага 30, 30.2в): «Сохранить и создать» —
        btn-primary рядом с главной «Сохранить и закрыть»; кнопки лежат в
        подвале окна footer.modal-footer — на нём держится правило."""
        utils = "web/static/src/views/fields/relational_utils.xml"
        buttons = _template(utils, "web.X2ManyFieldDialogDefaultButtons")

        def by_class(node, cls):
            return node.xpath(".//button[contains(concat(' ', @class, ' '), ' %s ')]" % cls)

        save_new = by_class(buttons, "o_form_button_save_new")
        self.assertEqual(len(save_new), 1)
        self.assertIn("btn", _classes(save_new[0]))
        self.assertIn("btn-primary", _classes(save_new[0]),
                      "ядро само сделало её контурной — правило 30.2в больше не нужно")
        save = by_class(buttons, "o_form_button_save")
        self.assertTrue(save)
        for button in save:
            self.assertIn("btn-primary", _classes(button), "главная — «Сохранить (и закрыть)»")

        dialog = _template(utils, "web.X2ManyFieldDialog")
        self.assertTrue(dialog.xpath(
            ".//t[@t-set-slot='footer']//t[@t-call='web.X2ManyFieldDialogDefaultButtons']"))
        core = _template("web/static/src/core/dialog/dialog.xml", "web.Dialog")
        footer = core.xpath(".//footer[contains(concat(' ', @class, ' '), ' modal-footer ')]")
        self.assertEqual(len(footer), 1)
        self.assertTrue(footer[0].xpath(".//t[@t-slot='footer']"))

        # Окно «Создать и изменить…»: кнопки формы ядро переносит в подвал
        # окна (web.Layout, t-portal) — то же правило.
        to_many = _template("web/static/src/views/view_dialogs/form_view_dialog.xml",
                            "web.FormViewDialog.ToMany.buttons")
        self.assertTrue(by_class(to_many, "o_form_button_save_new"))
        self.assertIn(".modal-footer'", _read("web/static/src/search/layout.xml"))

    def test_mail_client_markup(self):
        try:
            action = _template("mail_client/static/src/mail_client_action.xml", "mail_client.Inbox")
            composer = _xml("mail_client/static/src/composer/composer.xml")
        except FileNotFoundError:
            self.skipTest("модуля почты mail_client нет в путях")
        topbar = action.xpath(".//div[contains(concat(' ', @class, ' '), ' o_mail_client_topbar ')]")
        self.assertTrue(topbar)
        compose = topbar[0].xpath("./button[contains(concat(' ', @class, ' '), ' btn-primary ')]")
        self.assertEqual(len(compose), 1, "«Написать» — единственная залитая в строке почты")
        self.assertTrue(composer.xpath("//div[contains(concat(' ', @class, ' '), ' o_mail_client_composer ')]"))
        send = composer.xpath("//div[contains(concat(' ', @class, ' '), ' o_mail_client_composer_footer ')]"
                              "/button[contains(concat(' ', @class, ' '), ' btn-primary ')]")
        self.assertEqual(len(send), 1)
        self.assertNotIn("btn-sm", _classes(send[0]), "«Отправить» не должна попасть под правило «</>»")
        code = [b for b in composer.iter("button") if "btn-primary" in (b.get("t-att-class") or "")]
        self.assertEqual(len(code), 1)
        self.assertIn("btn-sm", _classes(code[0]))
