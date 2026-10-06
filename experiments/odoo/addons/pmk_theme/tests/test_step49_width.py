# -*- coding: utf-8 -*-
"""Ширина экрана (разбор UX, шаг 49, 07.10.2026) — что доезжает до браузера.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py):
  odoo -d pmk49_test -i pmk_theme,pmk_deal,theme_nexus --test-enable \
       --test-tags /pmk_theme:TestStep49Width,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme \
       --stop-after-init --http-port 8099

Вид (лист до 1800 px, лента по краям белой карточки листа, короткие поля
25rem, подсветка по контуру поля; ширины 1024–2560, обе темы) смотрит
основной агент глазами на копии — туры здесь не запустить. Здесь — то, что
ломается молча:
  • раздел лёг в выключенный файл темы (forms.scss, ir.asset seq 37) или
    старый forms.scss снова включился и вернул потолок 1920;
  • правило вне @media screen и попало в печать;
  • правило тронуло сетку групп (grid-column, grid-template-columns,
    white-space — грабли сетки формы с вкладками);
  • предел 25rem лёг на длинные поля (название, адрес, текст, клиент) или на
    «Настройки», окна, формы pmk-form (у них своя мера), наши документы
    pmk-doc-form (поля одной ширины, шаг 27);
  • лента разошлась с краями карточки листа (16 px с 768 px);
  • дробное поле вне наших документов потеряло отклик на наведение;
  • правило слабее ядра (потолок 1400 и margin: 0 auto ленты выигрывают);
  • ядро переименовало классы, на которые опираются селекторы.
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
    _specificity,
)
from odoo.addons.pmk_theme.tests.test_step40_dark import BRIGHT_LIME
from odoo.addons.pmk_theme.tests.test_step48_header import _strip_media

SCSS = "pmk_theme/static/src/scss/"
FORMS_SCSS = SCSS + "forms_nexus.scss"
OLD_FORMS_SCSS = SCSS + "forms.scss"
STEP_MARK = "// ═══ Шаг 49"
PREV_MARK = "// ═══ Шаг 48"

SHEET = ".o_form_view .o_form_renderer:not(:has(> .o_attachment_preview)) > .o_form_sheet_bg"
CHATTER = ".o_form_renderer > .o-mail-Form-chatter:not(.o-aside)"
FORM = (".o_action_manager .o_form_view:not(.o_xxs_form_view):not(.o-settings-form-view)"
        ":not(.pmk-form):not(.pmk-doc-form)")
CELL = FORM + " .o_inner_group .o_cell"
HOVER = ".o_action_manager .o_form_view:not(.pmk-form) .o_inner_group .o_cell:hover"
HOVER_FIELD = ".o_action_manager .o_form_view:not(.pmk-form) .o_inner_group .o_cell:not(:has(table)):hover"
SCREEN = "@media screen {"
SCREEN_MD = "@media screen and (min-width: 768px)"
SHORT = (
    "phone", "email", "url", "date", "datetime", "daterange", "remaining_days",
    "integer", "float", "float_time", "monetary", "percentage", "selection",
    "many2many_tags", "many2many_tags_avatar", "many2one_avatar_user", "many2one_avatar_employee",
)
# Длинные поля — во всю колонку: предел на них не ложится.
LONG = ("o_field_char", "o_field_text", "o_field_html", "x2many")
# Короткие по смыслу char-поля лида и сделки — по имени (контактный блок).
BY_NAME = (
    ' > .o_row:has(> .o_field_widget[name="contact_name"])',
    ' > .o_field_widget[name="contact_name"]',
    ' > .o_field_widget[name="function"]',
    ' > .o_field_widget[name="partner_name"]',
)


def _section(source):
    """Раздел «Шаг 49» — до следующего «// ═══ Шаг …» или до конца файла."""
    start = source.find(STEP_MARK)
    assert start != -1, "раздела шага 49 нет"
    end = source.find("// ═══ Шаг", start + 1)
    return source[start:end if end != -1 else None]


@tagged("post_install", "-at_install")
class TestStep49Width(TransactionCase):

    _backend_css_cache = None

    # ─── Исходник ──────────────────────────────────────────────────────
    def test_section_in_live_file(self):
        source = _read(FORMS_SCSS)
        self.assertIn(FORMS_SCSS, LIVE_THEME_PATHS)
        self.assertIn(OLD_FORMS_SCSS, DEAD_THEME_PATHS)
        self.assertIn(STEP_MARK, source)
        self.assertGreater(source.index(STEP_MARK), source.index(PREV_MARK),
                           "Раздел — в конце файла, после шага 48.")
        self.assertNotIn("Шаг 49", _read(OLD_FORMS_SCSS), "forms.scss выключен — правка туда не доедет.")

    def test_old_forms_stays_off(self):
        """Запись ir.asset старого forms.scss не включается при -u: поля
        active в XML нет (или оно ложно); на стенде запись выключена с 22.09."""
        with file_open("pmk_theme/data/assets_order.xml", "rb") as f:
            root = etree.parse(f).getroot()
        record = root.find(".//record[@id='asset_scss_forms']")
        self.assertIsNotNone(record)
        self.assertEqual(record.findtext("field[@name='path']"), OLD_FORMS_SCSS)
        active = record.find("field[@name='active']")
        if active is not None:
            self.assertIn((active.get("eval") or active.text or "").strip(), ("False", "0", ""))

    def test_section_source(self):
        code = re.sub(r"//[^\n]*", "", _section(_read(FORMS_SCSS)))
        body = code[code.index("@media"):]
        self.assertTrue(body.startswith("@media screen {"), "Всё — внутри @media screen.")
        self.assertEqual(code.count("@media screen"), 1)
        # Вложенный — только порог md ядра (карточка листа в полях подложки).
        self.assertEqual(code.count("@media"), 2)
        self.assertEqual(code.count("@media (min-width: 768px)"), 1)
        self.assertIn("1800px", code)
        for banned in ("grid-column", "grid-template-columns", "white-space", "display:", "display :"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, code, "Сетку групп шаг 49 не трогает.")
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
        self.assertFalse(_rules(_strip_media(css)), "Вне @media screen правил нет — печать не задета.")
        rules = _rules(_media_blocks(css, SCREEN))
        md = _rules(_media_blocks(css, SCREEN_MD))

        self.assertEqual(rules[SHEET]["max-width"], "1800px")
        self.assertEqual(rules[CHATTER]["max-width"], "1800px")
        self.assertEqual(rules[CHATTER]["margin-left"], "0")
        self.assertEqual(rules[CHATTER]["margin-right"], "auto")
        # С 768 px — края белой карточки: подложка 0–1800, карточка 16–1784.
        self.assertEqual(md[CHATTER], {
            "width": "calc(100% - 32px) !important",
            "max-width": "1768px",
            "margin-left": "16px",
        })
        self.assertEqual(list(md), [CHATTER], "В блоке md — только лента.")

        for kind in SHORT:
            for path in (" > .o_field_widget.o_field_", " > .o_row > .o_field_widget.o_field_"):
                with self.subTest(kind=kind, path=path):
                    self.assertEqual(rules[CELL + path + kind]["max-width"], "25rem")

        for path in BY_NAME:
            with self.subTest(path=path):
                self.assertEqual(rules[CELL + path]["max-width"], "25rem")

        limited = [sel for sel, decls in rules.items() if decls.get("max-width") == "25rem"]
        self.assertEqual(len(limited), 2 * len(SHORT) + len(BY_NAME))
        for selector in limited:
            with self.subTest(selector=selector):
                for guard in (".o_action_manager", ":not(.o_xxs_form_view)",
                              ":not(.o-settings-form-view)", ":not(.pmk-form)",
                              ":not(.pmk-doc-form)"):
                    self.assertIn(guard, selector)
                for long_kind in LONG:
                    self.assertNotIn(long_kind, selector)
                # обычный many2one (клиент, контакт) — во всю колонку
                self.assertNotRegex(selector, r"o_field_many2one(?!_avatar)")

        self.assertEqual(rules[HOVER]["background"], "transparent !important")
        # дробное поле вне pmk-doc-form: ввод прозрачный («Рамка в рамке»),
        # заливку получает обёртка виджета
        for target in (" .o_input", " .o_field_widget:not(:has(.o_input))",
                       " .o_field_float:not(.pmk-doc-form *)"):
            with self.subTest(target=target):
                self.assertIn(HOVER_FIELD + target, rules)

    def test_weights_beat_core(self):
        """Потолок ядра — .o_form_view .o_form_sheet_bg (0,2,0); поля ленты
        ядра — .o-mail-Form-chatter { margin: 0 auto } (0,1,0); подсветка
        ячейки чужой темы — .o_cell:hover (0,2,0) с !important."""
        self.assertGreater(_specificity(SHEET), (0, 2, 0))
        self.assertGreater(_specificity(CHATTER), (0, 1, 0))
        self.assertGreater(_specificity(HOVER), (0, 2, 0))

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
            # бандл собран сжато («@media screen{», «sel{decl}») — приводим к виду,
            # который разбирают _media_blocks/_rules: пробел вокруг фигурных скобок
            css = re.sub(r"\s*([{}])\s*", r" \1 ", css)
            cls._backend_css_cache = re.sub(r"\s+", " ", css)
        return cls._backend_css_cache

    def test_backend_bundle(self):
        css = self._backend_css()
        screen = _rules(_media_blocks(css, SCREEN))
        self.assertIn(SHEET, screen)
        self.assertEqual(screen[SHEET]["max-width"], "1800px")
        self.assertEqual(screen[CHATTER]["max-width"], "1800px")
        md = _rules(_media_blocks(css, SCREEN_MD))
        self.assertEqual(md[CHATTER]["margin-left"], "16px")
        self.assertEqual(md[CHATTER]["max-width"], "1768px")
        self.assertIn(CELL + " > .o_field_widget.o_field_phone", screen)
        # прежний потолок 1920 (forms.scss, 80ab7f5) в сборку не попал
        self.assertNotIn(".o_form_view .o_form_sheet_bg { max-width: 1920px", css)

    # ─── Договор с ядром ───────────────────────────────────────────────
    def test_core_contract(self):
        checks = {
            "web/static/src/views/form/form.variables.scss": ("$o-form-view-sheet-max-width: 1400px",),
            "web/static/src/views/form/form_controller.scss": (
                ".o_form_sheet_bg", "max-width: $o-form-view-sheet-max-width", "margin-right: auto",
                # поля подложки 16 px и карточка в них с md — основа 49.2
                "--formView-sheetBg-padding-x: #{map-get($spacers, 3)}",
                "--formView-sheet-margin-x: var(--formView-sheet-margin-x-md, 0)"),
            "web/static/src/scss/primary_variables.scss": ("$o-spacer: 16px",),
            "mail/static/src/chatter/web/form_compiler.js": (
                "o-mail-Form-chatter", '"o-aside w-print-100"', "o_attachment_preview"),
            "mail/static/src/chatter/web/form_renderer.scss": ("margin: 0 auto",),
            "web/static/src/views/fields/field.js": ("`o_field_${this.type}`",),
            "web/static/src/views/form/form_controller.js": ("o_xxs_form_view",),
            "web/static/src/webclient/settings_form_view/settings_form_view.xml": ("o-settings-form-view",),
        }
        for path, needles in checks.items():
            with file_open(path) as f:
                source = f.read()
            for needle in needles:
                with self.subTest(path=path, needle=needle):
                    self.assertIn(needle, source)

    def test_crm_contacts_in_row(self):
        """Почта сделки лежит в <div class="o_row"> — вторая ветка 49.3."""
        with file_open("crm/views/crm_lead_views.xml", "rb") as f:
            root = etree.parse(f).getroot()
        fields = root.xpath("//div[contains(@class, 'o_row')]/field[@name='email_from'][@widget='email']")
        self.assertTrue(fields, "email_from с widget=email внутри o_row")

    def test_crm_contact_fields(self):
        """«Имя контакта» — в .o_row, «Должность» — прямо в ячейке группы
        контакта лида, «Компания» — в группе lead_partner; в сделке pmk_deal
        кладёт «Компанию», «Имя контакта», «Должность» прямо в группу
        клиента. На это опираются правила по имени в 49.3."""
        with file_open("crm/views/crm_lead_views.xml", "rb") as f:
            root = etree.parse(f).getroot()
        group = root.xpath("//group[@name='lead_info']")
        self.assertTrue(group)
        self.assertTrue(group[0].xpath("./div[contains(@class, 'o_row')]/field[@name='contact_name']"))
        self.assertTrue(group[0].xpath("./field[@name='function']"))
        self.assertTrue(root.xpath("//group[@name='lead_partner']/field[@name='partner_name']"))

        deal = self.env["ir.module.module"].search([("name", "=", "pmk_deal")])
        if deal.state != "installed":
            self.skipTest("pmk_deal не установлен — сделка без его полей")
        arch = self.env["crm.lead"].get_view(view_type="form")["arch"]
        form = etree.fromstring(arch)
        partner = form.xpath("//group[@name='opportunity_partner']")
        self.assertTrue(partner)
        for name in ("partner_name", "contact_name", "function"):
            with self.subTest(name=name):
                self.assertTrue(partner[0].xpath("./field[@name='%s']" % name))

    def test_float_input_transparent(self):
        """Договор с разделом «Рамка в рамке»: ввод дробного поля вне
        pmk-doc-form прозрачный — поэтому 49.4 заливает обёртку виджета."""
        source = _read(FORMS_SCSS)
        self.assertIn(".o_field_float:not(.pmk-doc-form *) input.o_input {", source)
