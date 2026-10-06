# -*- coding: utf-8 -*-
"""Шапка документа (разбор UX, шаг 48, 06.10.2026) — что доезжает до браузера.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py), с темой theme_nexus и
pmk_deal (номер сделки и форма без «Новое» — его тесты):
  odoo -d pmk48_test -i pmk_theme,pmk_deal,theme_nexus --test-enable \
       --test-tags /pmk_theme:TestHeaderStep48,/pmk_deal --stop-after-init \
       --http-port 8099

Вид (кнопки и этап в строке пути на 1200–1920, в листе на 992–1199,
«Сохранить» / «Отменить»,
«⚙ Действия ▾», стрелки листалки, обе темы, «Настройки») смотрит основной
агент глазами на копии — туры здесь не запустить (в контейнере нет
браузера). Здесь — то, что ломается молча:
  • путь xpath наших расширений шаблонов ядра не находит узел — Owl покажет
    белый экран вместо формы (web.FormView, FormStatusIndicator,
    FormCogMenu, Breadcrumbs, Pager);
  • наша правка web.FormView ломает xpath «Настроек» и других наследников;
  • пропали горячие клавиши, t-ref кнопки «Сохранить» (ядро обращается к
    ней) или «Сохранить» снова прячется прозрачностью;
  • метка «кнопки наверх» не дошла до формы (вид выключен) или попала
    туда, где её не ждали (закупка);
  • «Отметить проигрыш» вернулся в ⚙ формы или пропал из ⚙ списка;
  • сборка стилей падает; правило лежит в выключенном файле темы; «Сохранить»
    задевает кнопки «Настроек»; правило заголовка слабее рамки темы; у
    заголовка нет тёмной пары;
  • строка пути снова сжимает номер с кнопками (наезд при правках), правая
    зона уже содержимого (стрелки на этапе), «Сохранить» — вторая залитая
    рядом с главной кнопкой документа.
"""
import copy
import re

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open
from odoo.tools.template_inheritance import apply_inheritance_specs

from odoo.addons.pmk_theme.models.ir_actions import BINDING_VIEW_TYPES
from odoo.addons.pmk_theme.tests.test_step30_highlights import (
    DEAD_THEME_PATHS,
    LIVE_THEME_PATHS,
    _media_blocks,
    _rules,
    _specificity,
)

OURS = "pmk_theme/static/src/xml/form_head.xml"
BREADCRUMBS = "pmk_theme/static/src/xml/breadcrumbs.xml"
FORMS_SCSS = "pmk_theme/static/src/scss/forms_nexus.scss"
DARK_SCSS = "pmk_theme/static/src/scss/dark.scss"
HEAD_JS = "pmk_theme/static/src/js/form_head.js"
RULES_JS = "pmk_theme/static/src/js/form_head_rules.js"
STEP_MARK = "// ═══ Шаг 48"

FORM_XML = "web/static/src/views/form/form_controller.xml"
INDICATOR_XML = "web/static/src/views/form/form_status_indicator/form_status_indicator.xml"
COG_XML = "web/static/src/search/cog_menu/cog_menu.xml"
FORM_COG_XML = "web/static/src/views/form/form_cog_menu/form_cog_menu.xml"
BC_XML = "web/static/src/search/breadcrumbs/breadcrumbs.xml"
PAGER_XML = "web/static/src/core/pager/pager.xml"

# Наследники web.FormView в ядре (путь, имя): их xpath должны находить узлы и
# после нашей правки. Primary-копии берут родителя до нашего файла, но
# проверяем на всякий случай — с правкой они тоже собираются.
FORM_VIEW_HEIRS = [
    ("web/static/src/webclient/settings_form_view/settings_form_view.xml", "web.SettingsFormView"),
    ("resource/static/src/views/form_with_html_expander/form_controller_with_html_expander.xml",
     "resource.FormViewWithHtmlExpander"),
    ("mrp_subcontracting/static/src/subcontracting_portal/picking_form_controller.xml",
     "mrp_subcontracting.PickingFormController"),
    ("website/static/src/components/views/theme_preview.xml", "website.ThemePreviewFormController"),
]
MAIL_FORM_XML = "mail/static/src/chatter/web/form_controller.xml"

DARK = "body.o_nexus_dark "
TITLE = '.o_form_view.o_lead_opportunity_form .oe_title h1 .o_field_widget[name="name"] .o_input'
PIN = ".o_form_view:not(.o-settings-form-view) .o_control_panel .o_control_panel_navigation"


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


def _block(root, inherit):
    node = root.find("t[@t-inherit='%s']" % inherit)
    assert node is not None, inherit
    return node


def _apply(source, block):
    """Применить блок наследования (все xpath) — ValueError, если узла нет."""
    specs = [copy.deepcopy(child) for child in block if isinstance(child.tag, str)]
    return apply_inheritance_specs(source, specs)


def _classes(node):
    return (node.get("class") or "").split()


def _strip_media(css):
    """CSS без блоков @media (по парным скобкам) — правила верхнего уровня."""
    out, pos = [], 0
    while True:
        start = css.find("@media", pos)
        if start == -1:
            out.append(css[pos:])
            return "".join(out)
        out.append(css[pos:start])
        depth, cur = 0, css.index("{", start)
        while True:
            depth += {"{": 1, "}": -1}.get(css[cur], 0)
            cur += 1
            if depth == 0:
                break
        pos = cur


@tagged("post_install", "-at_install")
class TestHeaderStep48(TransactionCase):

    _backend_css_cache = None

    # ─── Шаблоны ядра, на которые опираемся ────────────────────────────
    def _form_view(self):
        """web.FormView в том виде, в каком его получит браузер: ядро →
        расширение mail → наше."""
        form = _template(FORM_XML, "web.FormView")
        try:
            form = _apply(form, _block(_xml(MAIL_FORM_XML), "web.FormView"))
        except FileNotFoundError:
            pass
        return _apply(form, _block(_xml(OURS), "web.FormView"))

    def test_form_view_slots(self):
        form = self._form_view()
        actions = form.find(".//Layout/t[@t-set-slot='layout-actions']")
        children = [c for c in actions if isinstance(c.tag, str)]
        self.assertIn("o_pmk_cp_header_buttons", _classes(children[0]),
                      "Кнопки шапки — перед счётчиками.")
        self.assertEqual(children[1].get("t-if"), "!env.isSmall and buttonBoxTemplate")
        call = children[0].find("t[@t-call]")
        self.assertIn("pmkHeaderButtonsTemplate", call.get("t-call"))
        self.assertIn("state: {}", call.get("t-call-context"),
                      "Шапка читает __comp__.state.isStatusbarStickyPinned.")
        self.assertIn("record: this.model.root", call.get("t-call-context"))
        status = form.find(".//Layout/t[@t-set-slot='control-panel-navigation-additional']")
        self.assertIsNotNone(status)
        self.assertIn("o_pmk_cp_header_status", _classes(status.find("div")))
        self.assertIn("pmkHeaderStatusTemplate", status.find("div/t").get("t-call"))
        # Штатные слоты на месте: «Новое», шестерёнка, облачко, лист.
        for slot in ("control-panel-create-button", "control-panel-additional-actions",
                     "control-panel-status-indicator"):
            with self.subTest(slot=slot):
                self.assertIsNotNone(form.find(".//Layout/t[@t-set-slot='%s']" % slot))

    def test_form_view_heirs_still_apply(self):
        form = self._form_view()
        for path, name in FORM_VIEW_HEIRS:
            with self.subTest(heir=name):
                try:
                    heir = _xml(path).find("t[@t-name='%s']" % name)
                except FileNotFoundError:
                    self.skipTest("нет модуля %s в путях" % path.split("/")[0])
                self.assertIsNotNone(heir)
                built = _apply(copy.deepcopy(form), heir)
                if name != "web.SettingsFormView":
                    continue
                # «Настройки»: своё «Несохранённые изменения» вместо облачка,
                # свои «Сохранить» / «Отменить» (web.FormView.Buttons), поиск
                # в зоне счётчиков — нашей шапки там нет.
                status = built.find(".//Layout/t[@t-set-slot='control-panel-status-indicator']")
                self.assertIsNotNone(status.find(".//span[@class='text-muted ms-2 o_dirty_warning']"))
                self.assertIsNone(status.find(".//FormStatusIndicator"))
                actions = built.find(".//Layout/t[@t-set-slot='layout-actions']")
                self.assertFalse(actions.xpath(".//div[contains(@class, 'o_pmk_cp_header')]"))
                self.assertTrue(actions.xpath(".//div[contains(@class, 'o_cp_searchview')]"))
        buttons = _template(FORM_XML, "web.FormView.Buttons")
        save = buttons.xpath(".//button[contains(concat(' ', @class, ' '), ' o_form_button_save ')]")
        self.assertTrue(save and "btn-primary" in _classes(save[0]),
                        "Кнопки «Настроек» и окон — штатные, наш шаблон их не трогает.")
        self.assertIsNone(_xml(OURS).find("t[@t-inherit='web.FormView.Buttons']"))

    def test_status_indicator_buttons(self):
        indicator = _apply(_template(INDICATOR_XML, "web.FormStatusIndicator"),
                           _block(_xml(OURS), "web.FormStatusIndicator"))
        wrap = indicator.xpath(".//div[contains(concat(' ', @class, ' '), ' o_form_status_indicator_buttons ')]")[0]
        self.assertIn("'d-none'", wrap.get("t-att-class"))
        self.assertNotIn("invisible", wrap.get("t-att-class"),
                         "Без правок кнопок нет совсем, а не прозрачные 56 px.")
        self.assertIn("displayButtons", wrap.get("t-att-class"))
        save = wrap.xpath(".//button[contains(concat(' ', @class, ' '), ' o_form_button_save ')]")[0]
        cancel = wrap.xpath(".//button[contains(concat(' ', @class, ' '), ' o_form_button_cancel ')]")[0]
        self.assertEqual(_classes(save), ["o_form_button_save", "btn", "btn-primary"])
        self.assertEqual(_classes(cancel), ["o_form_button_cancel", "btn", "btn-secondary"])
        self.assertEqual(save.get("data-hotkey"), "s")
        self.assertEqual(cancel.get("data-hotkey"), "j")
        self.assertEqual(save.get("t-ref"), "save", "Ядро обращается к кнопке через t-ref.")
        self.assertEqual(save.get("t-on-click.stop"), "save")
        self.assertEqual(cancel.get("t-on-click.stop"), "discard")
        self.assertEqual(save.find("span").text, "Сохранить")
        self.assertEqual(cancel.find("span").text, "Отменить")
        self.assertIsNone(save.get("data-tooltip"))
        self.assertEqual(save.get("t-att-data-tooltip"), "pmkSaveTip")
        # Красный треугольник ошибки — как в ядре.
        self.assertTrue(indicator.xpath(".//i[contains(@class, 'fa-warning')]"))

    def test_cog_menu_button(self):
        cog = _apply(_template(COG_XML, "web.CogMenu"), _template(FORM_COG_XML, "web.FormCogMenu"))
        cog = _apply(cog, _block(_xml(OURS), "web.FormCogMenu"))
        button = cog.xpath(".//button[@data-hotkey='u']")
        self.assertEqual(len(button), 1, "Alt+U открывает «Действия».")
        self.assertIn("o_pmk_actions_btn", button[0].get("t-att-class"))
        self.assertIn("env.isSmall ? 'btn-secondary'", button[0].get("t-att-class"),
                      "На телефоне — штатная кнопка-значок.")
        label = button[0].find("span")
        self.assertEqual(label.text, "Действия")
        self.assertEqual(label.get("t-if"), "!env.isSmall")
        # Списки и канбан — штатная шестерёнка: web.CogMenu не тронут.
        self.assertIsNone(_xml(OURS).find("t[@t-inherit='web.CogMenu']"))

    def test_breadcrumbs_actions_out_of_title_only_for_forms(self):
        bc = _apply(_template(BC_XML, "web.Breadcrumbs"), _block(_xml(BREADCRUMBS), "web.Breadcrumbs"))
        bc = _apply(bc, _block(_xml(OURS), "web.Breadcrumbs"))
        calls = bc.xpath(".//t[@t-call='web.Breadcrumb.Actions']")
        self.assertEqual(len(calls), 3)
        conditions = sorted(c.get("t-if") for c in calls)
        self.assertEqual(conditions, ["!breadcrumb.isFormView", "!breadcrumb.isFormView",
                                      "breadcrumb.isFormView"])
        moved = [c for c in calls if c.get("t-if") == "breadcrumb.isFormView"][0]
        nxt = moved.getnext()
        self.assertEqual(nxt.get("t-slot"), "breadcrumb-status-indicator",
                         "«Действия» — перед «Сохранить» / «Отменить».")
        last = bc.xpath(".//div[contains(concat(' ', @class, ' '), ' o_last_breadcrumb_item ')]")
        self.assertEqual(len(last), 2)
        for node in last:
            self.assertIn("pmkShortCrumb(breadcrumb.name)", node.get("t-att-class"))
        path_item = bc.xpath(".//t[@t-foreach='visiblePathBreadcrumbs']/li")[0]
        self.assertIn("pmkShortCrumb(breadcrumb.name)", path_item.get("t-att-class"))

    def test_pager_hotkeys_kept(self):
        pager = _apply(_template(PAGER_XML, "web.Pager"), _block(_xml(OURS), "web.Pager"))
        prev = pager.xpath(".//button[contains(concat(' ', @class, ' '), ' o_pager_previous ')]")[0]
        nxt = pager.xpath(".//button[contains(concat(' ', @class, ' '), ' o_pager_next ')]")[0]
        self.assertIn("'p'", prev.get("t-att-data-hotkey"))
        self.assertIn("'n'", nxt.get("t-att-data-hotkey"))
        self.assertEqual(prev.get("t-att-data-tooltip"), "pmkTooltip(-1)")
        self.assertEqual(nxt.get("t-att-data-tooltip"), "pmkTooltip(1)")
        self.assertIsNone(prev.get("data-tooltip"))
        # Счётчик на месте — прячут его стили и только в формах.
        self.assertTrue(pager.xpath(".//span[contains(concat(' ', @class, ' '), ' o_pager_counter ')]"))

    def test_core_compile_header_contract(self):
        """Ядро раскладывает шапку так же, как наши правила (поле без btn —
        этап), и читает state.isStatusbarStickyPinned; кнопки-счётчики
        компилируются отдельно — тем же приёмом идёт и шапка."""
        compiler = _read("web/static/src/views/form/form_compiler.js")
        self.assertIn('getTag(child, true) === "field" && !child.classList.contains("btn")', compiler)
        self.assertIn("__comp__.state.isStatusbarStickyPinned", compiler)
        self.assertIn('{ selector: "header", fn: this.compileHeader }', compiler)
        controller = _read("web/static/src/views/form/form_controller.js")
        self.assertIn("{ isSubView: true }", controller)
        self.assertIn("this.canCreate = create && !this.props.preventCreate;", controller)
        self.assertIn('useBus(this.ui.bus, "resize", this.render);', controller)
        ui = _read("web/static/src/core/ui/ui_service.js")
        self.assertIn("XL: 4", ui, "Порог шапки наверху — SIZES.XL, 1200 px.")
        self.assertIn("{ minWidth: 1200, maxWidth: 1399 }", ui,
                      "На 1200 px ядро шлёт ui.bus «resize» — форма перерисуется.")
        renderer = _read("web/static/src/views/form/form_renderer.js")
        self.assertIn("StatusBarButtons", renderer)
        self.assertIn('browser.addEventListener("resize", this.onResize)', renderer)

    # ─── Метка «кнопки наверх» ──────────────────────────────────────────
    def test_header_up_marker(self):
        for model, xmlid in (("crm.lead", "crm.crm_lead_view_form"),
                             ("pmk.metal.spec", "pmk_calc.view_metal_spec_form"),
                             ("pmk.dobor.order", "pmk_calc.view_dobor_order_form")):
            with self.subTest(model=model):
                views = self.env[model].get_views([(self.env.ref(xmlid).id, "form")])
                arch = etree.fromstring(views["views"]["form"]["arch"])
                self.assertIn("o_pmk_header_up", _classes(arch))
                self.assertIsNotNone(arch.find("header"), "<header> в разметке на месте.")
        for xmlid in ("pmk_theme.view_crm_lead_form_header_up",
                      "pmk_theme.view_metal_spec_form_header_up",
                      "pmk_theme.view_dobor_order_form_header_up"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)
        purchase = self.env.ref("purchase.purchase_order_form", raise_if_not_found=False)
        if purchase:
            views = self.env["purchase.order"].get_views([(purchase.id, "form")])
            arch = etree.fromstring(views["views"]["form"]["arch"])
            self.assertNotIn("o_pmk_header_up", _classes(arch), "Закупки — как были.")

    def test_lost_not_in_form_gear(self):
        lost = self.env.ref("crm.crm_lead_lost_action")
        self.assertEqual(BINDING_VIEW_TYPES["crm.crm_lead_lost_action"], "list")
        self.assertIn("form", lost.binding_view_types, "В базе — штатно, подмена при отдаче.")
        form_id = self.env.ref("crm.crm_lead_view_form").id
        views = self.env["crm.lead"].get_views([(form_id, "form"), (False, "list")], {"toolbar": True})
        form_ids = [a["id"] for a in views["views"]["form"]["toolbar"].get("action", [])]
        list_ids = [a["id"] for a in views["views"]["list"]["toolbar"].get("action", [])]
        self.assertNotIn(lost.id, form_ids, "В ⚙ формы — кнопка «Проиграно» вместо пункта.")
        self.assertIn(lost.id, list_ids, "В ⚙ списка сделок — массовая отметка.")
        arch = etree.fromstring(views["views"]["form"]["arch"])
        button = arch.find("header/button[@name='%s']" % lost.id)
        self.assertIsNotNone(button, "Кнопка «Проиграно» — то же действие.")

    # ─── Стили ─────────────────────────────────────────────────────────
    def _stand_like_assets(self):
        theme = self.env["ir.asset"].search([("path", "=like", "pmk_theme/static/src/%")])
        theme.filtered(lambda a: a.path in DEAD_THEME_PATHS).active = False
        live = set(theme.filtered("active").mapped("path"))
        self.assertTrue(LIVE_THEME_PATHS <= live, live)

    def _backend_css(self):
        cls = type(self)
        if cls._backend_css_cache is None:
            self._stand_like_assets()
            bundle = self.env["ir.qweb"]._get_asset_bundle("web.assets_backend", js=False)
            css = bundle.preprocess_css()
            self.assertFalse(bundle.css_errors, bundle.css_errors)
            cls._backend_css_cache = re.sub(r"\s+", " ", css)
        return cls._backend_css_cache

    def _step_css(self, path):
        """Раздел «Шаг 48» файла, скомпилированный отдельно."""
        import sass

        source = _read(path)
        start = source.find(STEP_MARK)
        self.assertGreater(start, -1, "Раздел шага 48 — в живом файле %s" % path)
        # До следующего раздела («// ═══ Шаг 49» и далее) или до конца файла.
        end = source.find("// ═══ Шаг", start + 1)
        css = sass.compile(string=source[start:end if end != -1 else None])
        return re.sub(r"\s+", " ", css)

    def test_backend_css_compiles_with_step(self):
        css = self._backend_css()
        rules = _rules(css)
        self.assertIn(TITLE, rules)
        wide = _rules(_media_blocks(css, "@media (min-width: 992px)"))
        self.assertIn(PIN, wide)
        self.assertEqual(wide[PIN]["flex-grow"], "0 !important")
        screen = _rules(_media_blocks(css, "@media screen"))
        self.assertIn(DARK + TITLE, screen, "У заголовка — тёмная пара.")

    def test_rules_in_live_files(self):
        for path in (FORMS_SCSS, DARK_SCSS):
            with self.subTest(path=path):
                self.assertIn(path, LIVE_THEME_PATHS)
                self.assertIn(STEP_MARK, _read(path))
        assets = self.env["ir.asset"].search([("path", "in", [FORMS_SCSS, DARK_SCSS])])
        self.assertEqual(len(assets), 2)

    def test_save_cancel_scoped(self):
        """«Сохранить» / «Отменить» — только внутри .o_form_status_indicator:
        у «Настроек» свои кнопки с теми же классами."""
        # _rules видит и правила внутри @media: селектор — текст после
        # последней скобки.
        rules = _rules(self._step_css(FORMS_SCSS))
        touched = [s for s in rules if "o_form_button_save" in s or "o_form_button_cancel" in s]
        self.assertTrue(touched)
        for selector in touched:
            with self.subTest(selector=selector):
                self.assertIn(".o_form_status_indicator", selector)

    def test_pin_excludes_settings(self):
        css = self._step_css(FORMS_SCSS)
        self.assertIn(":not(.o-settings-form-view)", PIN)
        self.assertIn(PIN, css)

    def test_title_outweighs_theme(self):
        self.assertGreater(_specificity(TITLE), _specificity(".o_input"))
        self.assertGreater(_specificity(TITLE), _specificity(DARK + ".o_input:focus"))
        self.assertGreater(_specificity(DARK + TITLE), _specificity(TITLE))
        self.assertEqual(_specificity(TITLE), (0, 6, 1))
        rules = _rules(self._step_css(FORMS_SCSS))
        title = rules[TITLE]
        self.assertEqual(title["border"], "0 !important")
        self.assertEqual(title["background"], "transparent !important")
        h1 = rules[".o_form_view.o_lead_opportunity_form .oe_title h1"]
        self.assertEqual(h1["font-size"], "18px")
        self.assertEqual(h1["font-weight"], "600")
        dark = _rules(_media_blocks(self._step_css(DARK_SCSS), "@media screen"))
        self.assertIn(DARK + TITLE, dark)
        self.assertIn("var(--pmk-ink)", dark[DARK + TITLE]["color"])

    def test_header_up_rules_only_wide(self):
        """Кнопки наверху — только у форм с меткой и от 1200 px."""
        css = self._step_css(FORMS_SCSS)
        wide = _media_blocks(css, "@media (min-width: 1200px)")
        self.assertIn(".o_form_view.o_pmk_header_up .o_control_panel .o_pmk_cp_header > .o_form_statusbar", wide)
        self.assertNotIn("o_pmk_header_up", _media_blocks(css, "@media (min-width: 992px)"),
                         "992–1199 — шапка в листе: правил шапки наверху там нет.")
        top = _strip_media(css)
        for needle in ("o_pmk_cp_header", "o_pmk_header_up"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, top, "Вне @media (min-width: 1200px) правил шапки наверху нет.")
        # Ужимание по ширине — только пока шапка в строке пути.
        for query in ("@media (min-width: 1200px) and (max-width: 1365.98px)",
                      "@media (min-width: 1200px) and (max-width: 1279.98px)"):
            with self.subTest(query=query):
                block = _media_blocks(css, query)
                self.assertTrue(block)
                self.assertIn(".o_control_panel:has(.o_pmk_cp_header)", block)
        # Листалка без счётчика и кнопки сохранения — во всех формах и ширинах.
        self.assertIn(".o_form_view .o_control_panel .o_cp_pager .o_pager_counter", top)
        self.assertIn(".o_form_status_indicator .o_form_button_save", top)

    def test_header_up_never_overlaps(self):
        """Проверка шага 48 (1024 px, правки): колонка пути с номером
        сжималась долей нехватки, а номер и кнопки в ней — нет («✕» наезжал на
        «Расчёт и КП»); правая зона была min-width: 0 (стрелки на этапе).
        Теперь колонка с номером не сжимается, правая зона — не уже
        содержимого, название этапа — одна строка с наименьшей шириной в
        букву, путь над номером ограничен."""
        css = self._step_css(FORMS_SCSS)
        wide = _rules(_media_blocks(css, "@media (min-width: 1200px)"))
        up = ".o_form_view.o_pmk_header_up .o_control_panel "
        column = up + ".o_control_panel_breadcrumbs:has(.o_last_breadcrumb_item.o_pmk_bc_short)"
        self.assertEqual(wide[column]["flex-shrink"], "0")
        self.assertGreater(_specificity(column),
                           _specificity(".o_form_view .o_control_panel .o_control_panel_breadcrumbs"),
                           "Сильнее правила «название во всю ширину» (flex: 1 1 auto).")
        nav = wide[up + ".o_control_panel_navigation"]
        self.assertEqual(nav["min-width"], "min-content", "Стрелки не наезжают на этап.")
        self.assertEqual(nav["flex-shrink"], "4")
        name = wide[up + ".o_pmk_cp_header_status .o_statusbar_status > .btn.o_pmk_stage_toggle .o_pmk_stage_name"]
        self.assertEqual(name["display"], "-webkit-box")
        self.assertEqual(name["-webkit-line-clamp"], "1")
        self.assertEqual(name["overflow-wrap"], "anywhere")
        self.assertEqual(name["white-space"], "normal")
        path = up + ".o_breadcrumb:has(.o_last_breadcrumb_item.o_pmk_bc_short) > ol.breadcrumb"
        self.assertEqual(wide[path]["max-width"], "240px")
        roomy = _rules(_media_blocks(css, "@media (min-width: 1536px)"))
        self.assertEqual(roomy[path]["max-width"], "100%")

    def test_save_not_second_fill(self):
        """Залитая кнопка на экране одна: у документа со своей главной кнопкой
        «Сохранить» — контурная (светлая и тёмная тема)."""
        save = (".o_form_view:has(.o_statusbar_buttons .btn-primary) "
                ".o_form_status_indicator .btn.o_form_button_save")
        top = _rules(_strip_media(self._step_css(FORMS_SCSS)))
        self.assertIn(save, top)
        self.assertEqual(top[save]["background"], "#ffffff !important")
        self.assertIn("#16191c", top[save]["border"])
        self.assertEqual(top[save]["font-weight"], "600")
        self.assertGreater(_specificity(save), _specificity(".btn-primary"))
        self.assertGreater(_specificity(save), _specificity(DARK + ".btn-primary"))
        dark = _rules(_media_blocks(self._step_css(DARK_SCSS), "@media screen"))
        self.assertIn(DARK + save, dark, "Тёмная пара: иначе белая кнопка на тёмном листе.")
        self.assertGreater(_specificity(DARK + save), _specificity(save))
        self.assertIn("var(--pmk-ink)", dark[DARK + save]["border-color"])
        self.assertIn(save, self._backend_css(), "Правило доезжает до сборки стенда.")

    # ─── JS ────────────────────────────────────────────────────────────
    def test_js_order_and_contract(self):
        from odoo.modules.module import get_manifest

        assets = get_manifest("pmk_theme")["assets"]["web.assets_backend"]
        for path in (RULES_JS, HEAD_JS, OURS, BREADCRUMBS):
            with self.subTest(asset=path):
                self.assertIn(path, assets)
        self.assertLess(assets.index(RULES_JS), assets.index(HEAD_JS))
        self.assertLess(assets.index(BREADCRUMBS), assets.index(OURS))
        source = _read(HEAD_JS)
        for needle in ("StatusBarButtons", "compileHeader", "headerUpAt", "SIZES.XL",
                       "useSubEnv", "pmkHeaderUp", "isSubView: true", "pmkShortCrumb",
                       "pmkTooltip", "pmkSaveTip", "pmkCogTip"):
            with self.subTest(needle=needle):
                self.assertIn(needle, source)
        self.assertIn("!this.env.inDialog", source, "В окне (лид из почты) шапка — в листе.")
        manifest = get_manifest("pmk_theme")
        self.assertIn("views/step48_header_up.xml", manifest["data"])
