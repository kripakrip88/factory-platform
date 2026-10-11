# -*- coding: utf-8 -*-
"""Окно «История» как «История изменений» МоегоСклада (разбор UX, шаг 66,
11.10.2026) — что доезжает до браузера и на чём держится.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py):
  odoo -d pmk66_test -i pmk_theme,pmk_deal,pmk_calc,pmk_flow,tracking_manager,theme_nexus \
       --test-enable \
       --test-tags /pmk_theme:TestStep66HistoryView,/pmk_theme:TestStep65History,/pmk_theme:TestStep52Flat,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme:TestStep39Words \
       --stop-after-init --http-port 8099
Правила без Odoo — node static/tests/history_step66.test.mjs (краткое имя
автора, действие словом, дата, разбор изменений в «Поле | Было | Стало» на
настоящих телах с боевой базы).

Вид (заголовок «Карнеев А., изменено 08.10.2026 22:48», таблица, линии между
событиями, без значков действий, обе темы, сделка и расчёт, телефон) смотрит
основной агент глазами на копии — туров здесь нет. Здесь — то, что ломается
молча:
  • шаблон события потерял ссылку, на которой держится логика ядра (root —
    подсветка сообщения по ссылке, body — ссылки в тексте, shadowBody —
    письмо в тени) или снова тянет значки действий, реакции, правку;
  • в шаблоне компонент, которого нет у Message — Owl покажет белое окно;
  • ядро переименовало то, на что опираются подклассы (свойства Thread
    showDates / messageActions, Message.formatTracking, шаблон
    mail.Message.notification, Owl берёт components у класса при отрисовке);
  • tracking_manager поменял разметку записи — разбор в таблицу молча
    перестанет срабатывать (тогда запись покажется как есть, списком);
  • файлы не в бандле или не в том порядке;
  • раздел стилей лёг в выключенный файл, не в конец, с min()/max() или
    ярким лаймом, без тёмной пары; сборка web.assets_backend с ошибкой.
"""
import re

from lxml import etree
from lxml import html as lxml_html

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open

from odoo.addons.pmk_theme.tests.test_step30_highlights import (
    DEAD_THEME_PATHS,
    LIVE_THEME_PATHS,
    _media_blocks,
    _rules,
)
from odoo.addons.pmk_theme.tests.test_step40_dark import BRIGHT_LIME

SCSS = "pmk_theme/static/src/scss/"
FORMS_SCSS = SCSS + "forms_nexus.scss"
OLD_FORMS_SCSS = SCSS + "forms.scss"
DARK_SCSS = SCSS + "dark.scss"
STEP_MARK = "// ═══ Шаг 66"
JS = "pmk_theme/static/src/js/"
RULES_JS = JS + "history_rules.js"
HISTORY_JS = JS + "doc_history.js"
TOOLS_JS = JS + "doc_tools.js"
OURS = "pmk_theme/static/src/xml/doc_history.xml"
TOOLS_XML = "pmk_theme/static/src/xml/doc_tools.xml"
TEMPLATE = "pmk_theme.HistoryMessage"
DIALOG = ".pmk-history-dialog "
DARK = "body.o_nexus_dark "


def _read(path):
    with file_open(path) as f:
        return f.read()


def _xml(path):
    with file_open(path, "rb") as f:
        return etree.parse(f).getroot()


def _section(source):
    """Раздел «Шаг 66» — до следующего «// ═══» или до конца файла."""
    start = source.find(STEP_MARK)
    assert start != -1, "раздела шага 66 нет"
    end = source.find("// ═══", start + 1)
    return source[start:end if end != -1 else None]


def _code(source):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", source, flags=re.S))


def _compile(source):
    import sass

    return re.sub(r"\s+", " ", sass.compile(string=source))


def _outside_media(css):
    """Правила вне блоков @media — по парным скобкам."""
    out, start = [], 0
    pos = css.find("@media")
    while pos != -1:
        out.append(css[start:pos])
        depth, i = 1, css.index("{", pos) + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        start = i
        pos = css.find("@media", start)
    out.append(css[start:])
    return " ".join(out)


@tagged("post_install", "-at_install")
class TestStep66HistoryView(TransactionCase):

    _backend_css_cache = None

    # ─── Шаблон события ────────────────────────────────────────────────
    def _template(self):
        node = _xml(OURS).find("t[@t-name='%s']" % TEMPLATE)
        self.assertIsNotNone(node, "шаблон события на месте")
        return node

    def test_template_own_not_inherited(self):
        """Свой шаблон, не расширение mail.Message: ни одного xpath в ядро."""
        node = self._template()
        self.assertIsNone(node.get("t-inherit"))
        root = _xml(OURS)
        self.assertFalse(root.xpath("//*[@t-inherit]"), "в файле шага нет расширений чужих шаблонов")
        self.assertFalse(root.xpath("//xpath"))

    def test_template_refs_and_root(self):
        node = self._template()
        tops = [c for c in node if isinstance(c.tag, str)]
        self.assertEqual(len(tops), 1, "один корень")
        top = tops[0]
        self.assertEqual(top.get("t-ref"), "root", "подсветка сообщения по ссылке (registerMessageRef)")
        self.assertEqual(top.get("t-if"), "message.exists()")
        classes = top.get("class").split()
        self.assertIn("o-mail-Message", classes, "класс подсветки ядра (.o-mail-Message.o-highlighted)")
        self.assertIn("pmk-hist-event", classes)
        self.assertEqual(top.get("t-att-class"), "pmkRootClass", "props.className — o-highlighted")
        self.assertEqual(top.get("t-on-click"), "onClick", "ссылки в тексте — обработчик ядра")
        refs = [n.get("t-ref") for n in node.iter() if isinstance(n.tag, str) and n.get("t-ref")]
        self.assertEqual(sorted(refs), ["body", "root", "shadowBody"])
        body = node.xpath(".//*[@t-ref='body']")[0]
        self.assertIn("o-mail-Message-body", body.get("class").split(), "ссылки подчёркнуты (forms_nexus)")
        self.assertEqual(body.get("t-out"), "message.richBody")
        self.assertEqual(node.xpath(".//*[@t-ref='shadowBody']")[0].get("t-if"), "pmkIsEmail")
        self.assertTrue(node.xpath(".//t[@t-call='mail.Message.notification']"), "значок доставки письма")

    def test_template_read_only(self):
        """Без значков действий, реакций, правки, ответа-цитаты, свайпа."""
        text = etree.tostring(self._template(), encoding="unicode")
        for gone in ("mail.Message.actions", "ActionSwiper", "MessageReactions", "MessageInReply",
                     "Composer", "ActionList", "Dropdown", "computeActions", "MessageLinkPreviewList",
                     "o-mail-Message-actions", "starred"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)

    def test_template_components_known(self):
        """Компоненты шаблона — только из Message.components (иначе Owl:
        «Cannot find the definition of component»)."""
        used = {n.tag for n in self._template().iter() if isinstance(n.tag, str) and n.tag[:1].isupper()}
        self.assertEqual(used, {"AttachmentList"})
        message_js = _read("mail/static/src/core/common/message.js")
        self.assertRegex(message_js, r"static components = \{[^}]*\bAttachmentList,")

    def test_table_markup(self):
        node = self._template()
        table = node.xpath(".//table")
        self.assertEqual(len(table), 1)
        table = table[0]
        self.assertIn("pmk-hist-table", table.get("class"))
        self.assertEqual(table.xpath("./thead/tr/th")[0].get("t-foreach"), "pmkHeadCells")
        cells = table.xpath("./tbody/tr/td")
        self.assertEqual([c.get("t-esc") for c in cells], ["row.field", "row.old", "row.new"])
        self.assertIn("'—'", cells[1].get("t-att-class"), "пустое — бледным")

    def test_words(self):
        """Одно понятие — одно слово, без английского."""
        rules = _read(RULES_JS)
        for word in ('"Поле", "Было", "Стало"', '"Система"', '"—"', '"письмо"', '"задача выполнена"',
                     '"создано"', '"изменено"', '"заметка"', '"запись"', "добавлено", "удалено"):
            with self.subTest(word=word):
                self.assertIn(word, rules)
        self.assertIn("Тема: ", _read(OURS))
        texts = []
        for node in _xml(OURS).iter():
            if not isinstance(node.tag, str):
                continue
            texts += [node.text or "", node.tail or ""]
            texts += [node.get(attr) or "" for attr in ("title", "aria-label", "placeholder", "alt")]
        visible = " ".join(texts)
        self.assertNotRegex(visible, r"\b(?:Subject|Field|Old|New|Changed|Created|History|Note)\b")

    # ─── JS: договор и порядок ─────────────────────────────────────────
    def test_js_contract(self):
        from odoo.modules.module import get_manifest

        assets = get_manifest("pmk_theme")["assets"]["web.assets_backend"]
        for path in (RULES_JS, HISTORY_JS, OURS):
            with self.subTest(asset=path):
                self.assertIn(path, assets)
        self.assertLess(assets.index(RULES_JS), assets.index(HISTORY_JS), "правила — раньше классов")
        self.assertLess(assets.index(HISTORY_JS), assets.index(TOOLS_JS))
        self.assertLess(assets.index(TOOLS_XML), assets.index(OURS))
        self.assertNotIn("import", _code(_read(RULES_JS)), "чистые функции без импортов Odoo")

        history = _code(_read(HISTORY_JS))
        for needle in ("class PmkHistoryMessage extends Message",
                       'static template = "pmk_theme.HistoryMessage"',
                       "class PmkHistoryThread extends Thread",
                       "{ ...Thread.components, Message: PmkHistoryMessage }",
                       "showDates: false, messageActions: false",
                       "{ ...Chatter.components, Thread: PmkHistoryThread }",
                       'static template = "pmk_theme.HistoryChatter"',  # шаг 65 на месте
                       "openMobileActions() {}",
                       "this.formatTracking(",
                       'createElementWithContent("div", this.message.body)',
                       'from "@pmk_theme/js/history_rules"'):
            with self.subTest(needle=needle):
                self.assertIn(needle, history)
        # components и defaultProps — геттерами: патчи mail дописывают их
        # после загрузки модуля.
        self.assertIn("static get components()", history)
        self.assertIn("static get defaultProps()", history)
        self.assertNotRegex(history, r"static components = \{ \.\.\.(?:Thread|Chatter)\.components")
        self.assertNotIn("patch(Message", history, "штатное сообщение остальных лент не трогаем")
        self.assertNotIn("patch(Thread", history)

    # ─── Договор с ядром ───────────────────────────────────────────────
    def test_core_contract(self):
        checks = {
            "mail/static/src/core/common/thread.js": (
                "static components = { Message,", '"showDates?"', '"messageActions?"',
                "showDates: true", "messageActions: true", "getMessageClassName(message)"),
            "mail/static/src/core/common/thread.xml": (
                't-if="msg.dateDay !== currentDay and props.showDates"',
                'hasActions="props.messageActions', 'showDates="props.showDates"',
                'className="getMessageClassName(msg)"', 'registerMessageRef="registerMessageRef"'),
            "mail/static/src/core/common/message.js": (
                'static template = "mail.Message"', 'this.root = useRef("root")',
                'this.messageBody = useRef("body")', 'this.shadowBody = useRef("shadowBody")',
                "openMobileActions(ev)", "async onClickAttachmentUnlink(attachment)",
                "onClickNotification(ev)", "get authorAvatarUrl()", "prepareMessageBody(bodyEl)",
                "if (!bodyEl) {", "async onClick(ev)"),
            "mail/static/src/core/common/message.xml": (
                '<t t-name="mail.Message.notification">', "o-mail-Message-avatar"),
            "mail/static/src/core/web/message_patch.js": (
                "formatTracking(trackingFieldInfo, trackingValue)", "formatMonetary(trackingValue"),
            "mail/static/src/core/common/message_model.js": (
                "trackingValues = [];", "get isSubjectSimilarToThreadName()", "get isSubjectDefault()",
                "extra_body_attachment_ids", "isBodyEmpty", "get isNote()", "get isDiscussion()",
                "get datetime()", "get authorName()", "subtype_id = fields.One"),
            "mail/static/src/core/common/store_service.js": ('odoobot = fields.One("res.partner")',),
            # Автор-организация — название как есть (doc_history.pmkAuthor:
            # message.author_id?.is_company): ядро присылает is_company с автором.
            "mail/models/res_partner.py": ('"is_company",',),
            "mail/static/src/core/common/res_partner_model.js": ("is_company;",),
            "pmk_theme/static/src/js/doc_history.js": ("isCompany: Boolean(message.author_id?.is_company)",),
            "mail/static/src/chatter/web/chatter.xml": ('<Thread t-else=""',),
            "mail/static/src/chatter/web/chatter_patch.js": ("Object.assign(Chatter.components,",),
            "mail/static/src/core/common/attachment_list.js": ('static props = ["attachments", "unlinkAttachment"',),
            "mail/models/mail_tracking_value.py": ("'changedField'", "'isPropertyField'", "'fieldType'"),
            "web/static/src/core/utils/html.js": ("export function createElementWithContent(",),
            # Owl берёт components и defaultProps у класса при отрисовке —
            # на этом держатся геттеры подклассов.
            "web/static/lib/owl/owl.js": (
                "const components = parent.constructor.components;", "const defaultProps = C.defaultProps;"),
        }
        for path, needles in checks.items():
            with file_open(path) as f:
                source = f.read()
            for needle in needles:
                with self.subTest(path=path, needle=needle):
                    self.assertIn(needle, source)

    def test_tracking_manager_markup(self):
        """Разметка записи tracking_manager — та, которую разбирает
        history_rules.tmTree: div > ul > li > b (имя поля), br, по одному ul
        на строку с <b>меткой</b> и текстом записи, у «изменено» — ul > li
        «имя : было <div стрелка/> стало». Поменяется — разбор молча
        перестанет срабатывать (запись покажется как есть)."""
        if not self.env["ir.module.module"].search_count(
                [("name", "=", "tracking_manager"), ("state", "=", "installed")]):
            self.skipTest("tracking_manager не установлен")
        html = self.env["ir.qweb"]._render("tracking_manager.track_o2m_m2m_template", {"lines": [{
            "name": "Изделия",
            "messages": [
                {"mode": "create", "record": "Ферма Ф-1"},
                {"mode": "unlink", "record": "Ферма Ф-2"},
                {"mode": "update", "record": "Ферма Ф-3",
                 "changes": [{"name": "Детали", "old": "12", "new": "13"}]},
            ],
        }]})
        root = lxml_html.fragment_fromstring(str(html), create_parent="root")
        div = root.find("div")
        self.assertIsNotNone(div)
        li = div.find("ul/li")
        self.assertIsNotNone(li)
        kids = [k for k in li if isinstance(k.tag, str)]
        self.assertEqual(kids[0].tag, "b")
        self.assertIn("Изделия", kids[0].text)
        self.assertEqual(kids[1].tag, "br")
        rows = kids[2:]
        self.assertEqual([r.tag for r in rows], ["ul", "ul", "ul"])
        for row, record in zip(rows, ("Ферма Ф-1", "Ферма Ф-2", "Ферма Ф-3")):
            with self.subTest(record=record):
                first = [k for k in row if isinstance(k.tag, str)][0]
                self.assertEqual(first.tag, "b", "метка — первым узлом")
                self.assertRegex(first.text.strip(), r"(?i)^(?:добавлено|удалено|изменено|new|delete|change)\s*:$")
                self.assertIn(record, first.tail or "")
        change = rows[2].find("ul/li")
        self.assertIsNotNone(change)
        self.assertIn("Детали :", change.text)
        arrow = change.find("div")
        self.assertIn("fa-long-arrow-right", arrow.get("class"))
        self.assertIn("13", arrow.tail)

    # ─── Стили ─────────────────────────────────────────────────────────
    def test_section_in_live_files(self):
        self.assertIn(FORMS_SCSS, LIVE_THEME_PATHS)
        self.assertIn(DARK_SCSS, LIVE_THEME_PATHS)
        self.assertIn(OLD_FORMS_SCSS, DEAD_THEME_PATHS)
        for path in (FORMS_SCSS, DARK_SCSS):
            source = _read(path)
            with self.subTest(path=path):
                start = source.index(STEP_MARK)
                self.assertEqual(source.count(STEP_MARK), 1)
                self.assertEqual(source.find("// ═══", start + 1), -1, "Раздел — последним в файле.")
                self.assertLess(source.index("// ═══ Шаг 65"), start)
                self.assertLess(source.index("// ═══ Шаг 52"), start)
        self.assertNotIn("Шаг 66", _read(OLD_FORMS_SCSS), "forms.scss выключен — правка туда не доедет.")

    def test_section_source(self):
        for path in (FORMS_SCSS, DARK_SCSS):
            code = _code(_section(_read(path)))
            with self.subTest(path=path):
                self.assertNotRegex(code, r"\b(?:min|max)\(", "libsass Odoo роняет сборку")
                lower = code.lower()
                for lime in BRIGHT_LIME:
                    self.assertNotIn(lime, lower)
        light = _code(_section(_read(FORMS_SCSS)))
        # Только окно истории: Discuss, почта, чат, лента под формой — штатные.
        for selector in re.findall(r"([^{};]+)\{", re.sub(r"@media[^{]*\{", "", light)):
            selector = selector.strip()
            if not selector:
                continue
            for part in selector.split(","):
                with self.subTest(selector=part.strip()):
                    self.assertTrue(part.strip().startswith(".pmk-history-dialog "))
        dark = _code(_section(_read(DARK_SCSS)))
        self.assertTrue(dark.strip().startswith("@media screen {"), "тёмная пара — только на экране")
        self.assertEqual(dark.count("@media"), 1)

    def test_light_rules(self):
        css = _compile(_section(_read(FORMS_SCSS)))
        top = _rules(_outside_media(css))
        event = DIALOG + ".o-mail-Message.pmk-hist-event"
        self.assertEqual(top[event]["border-radius"], "0", "без скругления темы Nexus")
        self.assertIn("1px solid", top[event]["border-bottom"])
        self.assertEqual(top[event + ":last-child"]["border-bottom"], "0")
        self.assertEqual(top[DIALOG + ".pmk-hist-avatar"]["width"], "20px")
        self.assertEqual(top[DIALOG + ".pmk-hist-avatar"]["border-radius"], "50%")
        self.assertEqual(top[DIALOG + ".pmk-hist-head__author"]["font-weight"], "600")
        self.assertEqual(top[DIALOG + ".pmk-hist-head__stamp"]["font-variant-numeric"], "tabular-nums")
        self.assertEqual(top[DIALOG + ".pmk-hist-body"]["padding-left"], "28px", "под текстом заголовка")
        table = top[DIALOG + ".pmk-hist-table"]
        self.assertEqual(table["border-collapse"], "collapse")
        self.assertEqual(table["table-layout"], "fixed")
        cell = top[DIALOG + ".pmk-hist-table td"]
        self.assertIn("1px solid", cell["border"], "тонкие линии")
        self.assertEqual(cell["overflow-wrap"], "break-word",
                         "длинное переносится по пробелам; сумма с «руб» не рвётся посреди слова")
        self.assertEqual(top[DIALOG + ".pmk-hist-table th:first-child"]["width"], "28%")
        self.assertIn(DIALOG + ".pmk-hist-table td.pmk-hist-cell--none", top)
        self.assertEqual(top[DIALOG + ".pmk-hist-text.o-mail-Message-body"]["padding"], "0",
                         "без боковых отступов ядра")
        phone = _rules(_media_blocks(css, "@media (max-width: 767.98px)"))
        self.assertEqual(phone[DIALOG + ".pmk-hist-body"]["padding-left"], "0")
        self.assertEqual(phone[DIALOG + ".pmk-hist-table th:first-child"]["width"], "24%",
                         "на телефоне шире «Было» и «Стало»")

    def test_dark_pairs(self):
        css = _compile(_section(_read(DARK_SCSS)))
        dark = _rules(_media_blocks(css, "@media screen"))
        pairs = {
            ".pmk-hist-head": "var(--pmk-ink-3)",
            ".pmk-hist-head__author": "var(--pmk-ink)",
            ".pmk-hist-subtype": "var(--pmk-ink-3)",
            ".pmk-hist-table th": "var(--pmk-ink-3)",
            ".pmk-hist-table td": "var(--pmk-ink)",
            ".pmk-hist-table td.pmk-hist-cell--none": "var(--pmk-ink-faint)",
        }
        for selector, colour in pairs.items():
            with self.subTest(selector=selector):
                self.assertEqual(dark[DARK + DIALOG + selector]["color"], colour)
        self.assertEqual(dark[DARK + DIALOG + ".pmk-hist-table th"]["background"], "var(--pmk-surface-2)")
        # Цвета светлых правил — у каждого тёмная пара.
        light = _rules(_outside_media(_compile(_section(_read(FORMS_SCSS)))))
        for selector, decls in light.items():
            if "color" in decls or "background" in decls:
                with self.subTest(light=selector):
                    self.assertIn(DARK + selector, dark, "светлому цвету — тёмная пара")

    def test_backend_bundle(self):
        cls = type(self)
        if cls._backend_css_cache is None:
            theme = self.env["ir.asset"].search([("path", "=like", "pmk_theme/static/src/%")])
            theme.filtered(lambda a: a.path in DEAD_THEME_PATHS).active = False
            bundle = self.env["ir.qweb"]._get_asset_bundle("web.assets_backend", js=False)
            css = bundle.preprocess_css()
            self.assertFalse(bundle.css_errors, bundle.css_errors)
            cls._backend_css_cache = re.sub(r"\s+", " ", css)
        css = cls._backend_css_cache
        for needle in (".pmk-history-dialog .pmk-hist-table",
                       ".pmk-history-dialog .o-mail-Message.pmk-hist-event",
                       "body.o_nexus_dark .pmk-history-dialog .pmk-hist-table td"):
            with self.subTest(needle=needle):
                self.assertIn(needle, css)

    def test_js_in_bundle(self):
        paths = [p[0].lstrip("/") for p in self.env["ir.asset"]._get_asset_paths("web.assets_backend", {})]
        for path in (RULES_JS, HISTORY_JS, OURS):
            with self.subTest(path=path):
                self.assertIn(path, paths)
        self.assertLess(paths.index(RULES_JS), paths.index(HISTORY_JS))
