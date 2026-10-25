# -*- coding: utf-8 -*-
"""«История» кнопкой в строке пути, лента из формы убрана (разбор UX, шаг 65,
11.10.2026) — что доезжает до браузера и до вида.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py):
  odoo -d pmk65_test -i pmk_theme,pmk_deal,pmk_calc,pmk_flow,pmk_orders,pmk_tech,pmk_cut,pmk_laser,theme_nexus \
       --test-enable \
       --test-tags /pmk_theme:TestStep65History,/pmk_theme:TestStep65Session,/pmk_theme:TestStep52Flat,/pmk_theme:TestStep49bAside,/pmk_theme:TestStep49Width,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme:TestStep39Words,/pmk_flow \
       --stop-after-init --http-port 8099
Правила без Odoo — node static/tests/doc_tools_step65.test.mjs.

Вид (значок «История» между этапом и стрелками, окно истории во весь экран,
вкладка «Файлы» со счётчиком, скрепка у форм без вкладок, «Задача» в
«⚙ Действия», обе темы, все вкладки, соседние документы) смотрит основной
агент глазами на копии — туры здесь не запустить. Здесь — то, что ломается
молча:
  • основные документы не открываются (вид не собирается после вставки
    вкладки);
  • вкладка «Файлы» не встала (или встала не последней, во вложенную панель,
    в форму без ленты, в мастер, в спрятанную панель карточки клиента);
  • выключатель «Убранное (показать)» не возвращает всё как было;
  • путь xpath наших расширений шаблонов не находит узел — Owl покажет белый
    экран (web.FormView и три primary-копии, mail.Chatter, web.Notebook и
    копия у счетов);
  • окно «История» снова с «Отправить сообщение», заметкой, поиском,
    подписчиками — или без задач и писем;
  • ядро переименовало то, на чём держится шаг (контейнер ленты и его
    условие, слот правой зоны строки пути, событие перечитывания записи,
    планирование задачи, загрузка вложений, размер окна «fullscreen»);
  • раздел стилей лёг в выключенный файл, не в конец, с min()/max() или
    ярким лаймом, без тёмной пары.
"""
import copy
import re

from lxml import etree

from odoo import Command
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_open
from odoo.tools.template_inheritance import apply_inheritance_specs

from odoo.addons.pmk_theme.models.doc_history import FILES_LABEL, FILES_PAGE, REMOVED
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
STEP_MARK = "// ═══ Шаг 65"
JS = "pmk_theme/static/src/js/"
RULES_JS = JS + "doc_tools_rules.js"
TOOLS_JS = JS + "doc_tools.js"
FILES_JS = JS + "doc_files.js"
HISTORY_JS = JS + "doc_history.js"
OURS = "pmk_theme/static/src/xml/doc_tools.xml"
HEAD_XML = "pmk_theme/static/src/xml/form_head.xml"
CHATTER_XML = "pmk_theme/static/src/xml/chatter.xml"

FORM_XML = "web/static/src/views/form/form_controller.xml"
MAIL_FORM_XML = "mail/static/src/chatter/web/form_controller.xml"
RESOURCE_XML = "resource/static/src/views/form_with_html_expander/form_controller_with_html_expander.xml"
TASK_XML = "project/static/src/views/project_task_form/project_task_form_controller.xml"
PROJECT_XML = "project/static/src/views/project_form/project_project_form_controller.xml"
MAIL_CHATTER_XML = "mail/static/src/chatter/web/chatter.xml"
NOTEBOOK_XML = "web/static/src/core/notebook/notebook.xml"
ACCOUNT_NOTEBOOK_XML = "account/static/src/components/account_move_form/account_move_form_notebook.xml"

NAV_SLOT = ".//Layout/t[@t-set-slot='control-panel-navigation-additional']"
STATUS_SLOT = ".//Layout/t[@t-set-slot='control-panel-status-indicator']"

# Основные документы: (модель, xmlid формы, вкладка «Файлы» ждётся?).
# None — зависит от соседнего модуля (карточка клиента: панель вкладок
# спрятана шагом 3 pmk_partner — тогда скрепка в строке пути).
FORMS = (
    ("pmk.metal.spec", "pmk_calc.view_metal_spec_form", True),       # расчёт
    ("pmk.vent.hood.order", "pmk_calc.view_vent_hood_order_form", False),  # вентзонты
    ("pmk.dobor.order", "pmk_calc.view_dobor_order_form", True),     # доборка (вкладки с «Раскроем листа», 12.10)
    ("crm.lead", "crm.crm_lead_view_form", True),                    # сделка, лид
    ("sale.order", "sale.view_order_form", True),                    # счёт покупателю
    ("purchase.order", "purchase.purchase_order_form", True),        # заявка на металл
    ("res.partner", "base.view_partner_form", None),                 # клиент
    ("project.task", "pmk_orders.view_task_order_form", False),      # строка «Заказов в работе»
    ("project.task", "project.view_task_form2", True),               # задача
    ("pmk.laser.job", "pmk_laser.view_laser_job_form", True),        # лазер
    ("pmk.cut.plan", "pmk_cut.view_cut_plan_form", True),            # раскрой
)


def _read(path):
    with file_open(path) as f:
        return f.read()


def _xml(path):
    with file_open(path, "rb") as f:
        return etree.parse(f).getroot()


def _template(path, name):
    node = _xml(path).find("t[@t-name='%s']" % name)
    assert node is not None, (path, name)
    return copy.deepcopy(node)


def _block(root, inherit, named=False):
    for node in root.findall("t[@t-inherit='%s']" % inherit):
        if bool(node.get("t-name")) == named:
            return node
    raise AssertionError(inherit)


def _apply(source, block):
    specs = [copy.deepcopy(child) for child in block if isinstance(child.tag, str)]
    return apply_inheritance_specs(source, specs)


def _section(source):
    """Раздел «Шаг 65» — до следующего «// ═══» или до конца файла."""
    start = source.find(STEP_MARK)
    assert start != -1, "раздела шага 65 нет"
    end = source.find("// ═══", start + 1)
    return source[start:end if end != -1 else None]


def _code(source):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", source, flags=re.S))


def _compile(source):
    import sass

    return re.sub(r"\s+", " ", sass.compile(string=source))


@tagged("post_install", "-at_install")
class TestStep65History(TransactionCase):

    _backend_css_cache = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.removed = cls.env.ref(REMOVED)

    # ─── Виды: вкладка «Файлы» ─────────────────────────────────────────
    def _arch(self, model, xmlid, user=None):
        view = self.env.ref(xmlid, raise_if_not_found=False)
        if view is None or model not in self.env:
            return None
        env_model = self.env[model].with_user(user or self.admin)
        return etree.fromstring(env_model.get_views([(view.id, "form")])["views"]["form"]["arch"])

    def test_forms_open_and_files_tab(self):
        checked = 0
        for model, xmlid, expected in FORMS:
            arch = self._arch(model, xmlid)
            if arch is None:
                continue
            checked += 1
            # Раскрой вентзонтов (pmk_vent_nest, 12.10.2026) кладёт размеры во вкладку
            # рядом с «Раскроем» — тогда и «Файлы» у заказа вентзонтов вкладкой.
            if xmlid == "pmk_calc.view_vent_hood_order_form" and self.env["ir.module.module"].search_count(
                    [("name", "=", "pmk_vent_nest"), ("state", "=", "installed")]):
                expected = True
            with self.subTest(form=xmlid):
                self.assertEqual(arch.tag, "form")
                notebook = arch.find("sheet/notebook")
                if expected is None:
                    expected = notebook is not None and notebook.get("invisible") in (None, "0", "False")
                pages = arch.xpath("//page[@name='%s']" % FILES_PAGE)
                if not expected:
                    self.assertFalse(pages, "Без вкладок — скрепка в строке пути, не вкладка.")
                    continue
                self.assertEqual(len(pages), 1)
                own = notebook.findall("page")
                self.assertIs(own[-1], pages[0], "«Файлы» — последней вкладкой листа.")
                page = pages[0]
                self.assertEqual(page.get("string"), FILES_LABEL)
                self.assertTrue(page.xpath("widget[@name='%s']" % FILES_PAGE))
                names = [p.get("name") for p in own]
                if "pmk_flow" in names:
                    self.assertEqual(names[-2], "pmk_flow", "«Файлы» — сразу после «Связей».")
        self.assertGreaterEqual(checked, 8, "Основные документы на месте.")

    def test_files_tab_only_top_notebook(self):
        """Расчёт: во вложенной панели изделия (Прокат/Лист/…) вкладки нет."""
        arch = self._arch("pmk.metal.spec", "pmk_calc.view_metal_spec_form")
        if arch is None:
            self.skipTest("pmk_calc не установлен")
        self.assertEqual(len(arch.xpath("//page[@name='%s']" % FILES_PAGE)), 1)
        self.assertTrue(arch.xpath("/form/sheet/notebook/page[@name='%s']" % FILES_PAGE))

    def test_no_tab_without_chatter(self):
        """Формы без ленты и мастера — без вкладки: окно размера вентзонта
        (вкладки есть, ленты нет), Настройки (мастер)."""
        arch = self._arch("pmk.vent.hood", "pmk_calc.view_vent_hood_form")
        if arch is not None:
            self.assertFalse(arch.xpath("//page[@name='%s']" % FILES_PAGE))
        settings = self.env["res.config.settings"].with_user(self.admin).get_views([(False, "form")])
        self.assertNotIn('name="%s"' % FILES_PAGE, settings["views"]["form"]["arch"])

    def test_reversible_by_group(self):
        self.assertFalse(self.admin._pmk_chatter_in_form())
        self.admin.write({"group_ids": [Command.link(self.removed.id)]})
        self.assertTrue(self.admin._pmk_chatter_in_form())
        for model, xmlid, expected in FORMS:
            arch = self._arch(model, xmlid)
            if arch is None:
                continue
            with self.subTest(form=xmlid):
                self.assertFalse(arch.xpath("//page[@name='%s']" % FILES_PAGE),
                                 "«Убранное (показать)» — всё как было, скрепка в ленте.")
                self.assertTrue(arch.xpath("./chatter | ./sheet/chatter"), "Лента в разметке на месте.")

    def test_todo_form_keeps_own_chatter(self):
        """«Список дел»: у формы дела НЕТ узла <chatter> — своя панель
        todo_chatter_panel со своей кнопкой в строке пути. Клиент ленту не
        убирает (hasChatter=false), значка «История» и «Задачи» в «Действиях»
        у дел нет — задача ставится в их панели, как было. Появится <chatter>
        — лента уйдёт в окно, а меню дел (TodoFormCogMenu) реестр cogMenu не
        читает: тогда «Задачу» туда добавляет патч в doc_tools.js — проверить
        его глазами."""
        arch = self._arch("project.task", "project_todo.project_task_view_todo_form")
        if arch is None:
            self.skipTest("project_todo не установлен")
        self.assertFalse(arch.xpath("./chatter | ./sheet/chatter"))
        self.assertTrue(arch.xpath("//widget[@name='todo_chatter_panel']"))
        self.assertFalse(arch.xpath("//page[@name='%s']" % FILES_PAGE))

    def test_chatter_stays_in_arch(self):
        """Лента из разметки не удаляется: её убирает клиент условием, и
        выключатель возвращает её без -u."""
        for model, xmlid, _expected in FORMS:
            arch = self._arch(model, xmlid)
            if arch is None:
                continue
            with self.subTest(form=xmlid):
                self.assertTrue(arch.xpath("./chatter | ./sheet/chatter"))

    # ─── Шаблоны: xpath находят узлы ───────────────────────────────────
    def _form_core(self):
        form = _template(FORM_XML, "web.FormView")
        return _apply(form, _block(_xml(MAIL_FORM_XML), "web.FormView"))

    def test_form_view_slot(self):
        form = self._form_core()
        form = _apply(form, _block(_xml(HEAD_XML), "web.FormView"))
        form = _apply(form, _block(_xml(OURS), "web.FormView"))
        slot = form.find(NAV_SLOT)
        kids = [c for c in slot if isinstance(c.tag, str)]
        # Шапка «вариант А» (25.10.2026): «⚙» — в этом слоте, перед «Историей».
        self.assertEqual(kids[0].tag, "CogMenu")
        self.assertEqual(kids[0].get("t-if"), "pmkHeadAOn")
        self.assertIn("o_pmk_cp_header_status", (kids[1].get("class") or "").split(), "Этап — перед значками.")
        self.assertEqual(kids[2].get("t-component"), "pmkDocToolsCls", "Значки — после этапа.")
        self.assertEqual(kids[2].get("t-if"), "pmkDocToolsOn")
        self.assertEqual(kids[2].get("t-props"), "pmkDocToolsProps")

    def test_primary_copies_get_slot(self):
        """«Список дел», задачи (и доска «Доработка системы»), проекты:
        primary-копии без слота этапа — заводим свой, ровно один."""
        resource = _apply(self._form_core(), _template(RESOURCE_XML, "resource.FormViewWithHtmlExpander"))
        copies = {
            "resource.FormViewWithHtmlExpander": copy.deepcopy(resource),
        }
        try:
            copies["project.ProjectTaskFormView"] = _apply(
                copy.deepcopy(resource), _template(TASK_XML, "project.ProjectTaskFormView"))
            copies["project.ProjectFormView"] = _apply(
                copy.deepcopy(resource), _template(PROJECT_XML, "project.ProjectFormView"))
        except FileNotFoundError:
            pass
        for name, built in copies.items():
            with self.subTest(template=name):
                self.assertIsNone(built.find(NAV_SLOT), "Слота у копии не было — заводим.")
                built = _apply(built, _block(_xml(OURS), name))
                slots = built.findall(NAV_SLOT)
                self.assertEqual(len(slots), 1)
                self.assertEqual(slots[0][0].get("t-component"), "pmkDocToolsCls")
                self.assertIsNotNone(built.find(STATUS_SLOT))

    def test_history_chatter_template(self):
        chatter = _template(MAIL_CHATTER_XML, "mail.Chatter")
        chatter = _apply(chatter, _block(_xml(CHATTER_XML), "mail.Chatter", named=True))
        history = _apply(chatter, _block(_xml(OURS), "mail.Chatter", named=True))
        text = etree.tostring(history, encoding="unicode")
        for gone in ("o-mail-Chatter-topbar", "o-mail-Chatter-sendMessage", "o-mail-Chatter-logNote",
                     "o-mail-Chatter-activity", "oi-search", "o-mail-Followers", "pmk-chatter-toggle",
                     'data-hotkey="m"', 'data-hotkey="shift+m"', 'data-hotkey="shift+a"'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)
        for kept in ('t-call="mail.ActivityList"', 't-call="mail.ScheduledMessagesList"', "<Thread "):
            with self.subTest(kept=kept):
                self.assertIn(kept, text)
        node = _xml(OURS).find("t[@t-name='pmk_theme.HistoryChatter']")
        self.assertEqual(node.get("t-inherit-mode"), "primary")

    def test_notebook_counter(self):
        for path, name in ((NOTEBOOK_XML, "web.Notebook"), (ACCOUNT_NOTEBOOK_XML, "account.AccountMoveFormNotebook")):
            with self.subTest(template=name):
                try:
                    base = _template(NOTEBOOK_XML, "web.Notebook")
                    if name != "web.Notebook":
                        base = _apply(base, _template(path, name))
                except FileNotFoundError:
                    self.skipTest("нет модуля %s" % path.split("/")[0])
                built = _apply(base, _block(_xml(OURS), name))
                link = built.find(".//a")
                kids = [c for c in link if isinstance(c.tag, str)]
                self.assertEqual(kids[-2].get("t-esc"), "navItem[1].title")
                self.assertEqual(kids[-1].get("t-component"), "pmkFilesCountCls")
                self.assertIn("'%s'" % FILES_PAGE, kids[-1].get("t-if"))

    def test_words(self):
        """Одно понятие — одно слово, без английского."""
        xml = _read(OURS)
        for word in (">Закрыть<", "Добавить файл", "Файлов пока нет", "Задача",
                     "Файлы можно добавить после сохранения документа",
                     ">просрочено<"):
            with self.subTest(word=word):
                self.assertIn(word, xml)
        rules = _read(RULES_JS)
        for word in ("История появится после сохранения", "Файлы появятся после сохранения",
                     "просрочено"):
            with self.subTest(word=word):
                self.assertIn(word, rules)
        # Видимый текст шаблонов — тексты узлов (без комментариев) и подсказки.
        texts = []
        for node in _xml(OURS).iter():
            if not isinstance(node.tag, str):
                continue
            texts += [node.text or "", node.tail or ""]
            texts += [node.get(attr) or "" for attr in ("title", "aria-label", "placeholder")]
        visible = " ".join(texts)
        self.assertNotRegex(visible, r"\b(?:Activity|Activities|Attach|Files|History|Close)\b")
        self.assertNotRegex(visible.lower(), r"активност|вложени")

    # ─── JS: договор и порядок ─────────────────────────────────────────
    def test_js_contract(self):
        from odoo.modules.module import get_manifest

        assets = get_manifest("pmk_theme")["assets"]["web.assets_backend"]
        for path in (RULES_JS, FILES_JS, HISTORY_JS, TOOLS_JS, OURS):
            with self.subTest(asset=path):
                self.assertIn(path, assets)
        self.assertLess(assets.index(RULES_JS), assets.index(FILES_JS))
        self.assertLess(assets.index(FILES_JS), assets.index(TOOLS_JS))
        self.assertLess(assets.index(HISTORY_JS), assets.index(TOOLS_JS))
        self.assertLess(assets.index(CHATTER_XML), assets.index(OURS),
                        "Копия ленты собирается с нашим расширением mail.Chatter.")
        self.assertLess(assets.index(HEAD_XML), assets.index(OURS), "Значок — после этапа шага 48.")
        self.assertLess(assets.index(JS + "form_head.js"), assets.index(TOOLS_JS))

        self.assertNotIn("import", _code(_read(RULES_JS)), "чистые функции без импортов Odoo")
        tools = _read(TOOLS_JS)
        for needle in ('registry.category("cogMenu").add("pmk-schedule-task"', "hideChatterIf(",
                       '"MAIL:RELOAD-THREAD"', "session.pmk_chatter_in_form", "scheduleActivity(",
                       "o_pmk_chatter_out", "useSubEnv", "highlight_message_id",
                       'env.config?.viewType === "form"',
                       # находки проверки шага 65:
                       "fetchCounts(thread, { fresh: true })",  # свежие файлы при открытии
                       "saveThenLoad(record, this.props.saveRecord)",  # счёт: сохранить, потом перечитать
                       'slot.setAttribute("pmk_record", "__comp__.props.record")',  # запись в слоте вкладки
                       "patch(TodoFormCogMenu.prototype"):
            with self.subTest(needle=needle):
                self.assertIn(needle, tools)
        self.assertNotIn('useService("mail.store")', tools,
                         "хранилище — через env.services: промисы не привязаны к компоненту")
        files = _read(FILES_JS)
        for needle in ('registry.category("view_widgets").add(FILES_PAGE', "useAttachmentUploader",
                       "AttachmentList", "useCustomDropzone", "ensureAttachments",
                       "ensureAttachments(thread, { fresh: true })", "shouldFetchAttachments",
                       "export async function saveThenLoad", "saveThenLoad(this.props.record, save)",
                       "pmkFilesRecord(navItem)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, files)
        self.assertNotIn("() => this.props.record.load()", files,
                         "без сохранения load() сбросит правки шапки счёта")
        self.assertNotIn("() => record.load()", tools)
        self.assertEqual(_read(OURS).count("pmkFilesRecord(navItem)?.resId"), 2,
                         "ярлык «Файлы» — запись из слота, и у счетов тоже")
        history = _read(HISTORY_JS)
        self.assertIn('static template = "pmk_theme.HistoryChatter"', history)
        self.assertIn("get pmkCollapsedNow()", history, "в окне история всегда развёрнута")
        self.assertIn("size=\"'fullscreen'\"", _read(OURS), "окно — как позиция доборки")

    # ─── Договор с ядром ───────────────────────────────────────────────
    def test_core_contract(self):
        checks = {
            "mail/static/src/chatter/web/form_compiler.js": (
                '"o-mail-ChatterContainer", "o-mail-Form-chatter"', '"t-if": "!__comp__.env.inDialog"',
                "reload_on_activity", "reload_on_attachment", 'res.querySelector(".o-mail-Form-chatter")'),
            "mail/static/src/chatter/web/form_controller.js": ('"MAIL:RELOAD-THREAD"',),
            "mail/static/src/chatter/web/form_arch_parser.js": ("result.has_activities",),
            "mail/static/src/chatter/web/chatter.xml": (
                "o-mail-Chatter-topbar", 't-call="mail.ActivityList"'),
            "project_todo/static/src/views/todo_form/todo_form_cog_menu.js": (
                "export class TodoFormCogMenu extends FormCogMenu", "async _registryItems()"),
            "web/static/src/views/utils.js": ("return `\\`${str.replaceAll",),
            "mail/static/src/chatter/web/chatter_patch.js": (
                '"has_activities?"', '"hasParentReloadOnActivityChanged?"', '"highlightMessageId?"',
                '"saveRecord?"', '"record?"', "await this.store.scheduleActivity(thread.model, [thread.id])",
                # перечитывание после файлов — сначала сохранение (saveThenLoad)
                "async reloadParentView() {\n        await this.props.saveRecord?.();"),
            # флаг загрузки ставится ДО запроса — на нём держится «один
            # запрос на всех» (shouldFetchAttachments)
            "mail/static/src/chatter/web/thread_model_patch.js": (
                'this.isLoadingAttachments || requestList.includes("attachments");\n        await super.fetchThreadData',),
            "mail/static/src/chatter/web_portal/chatter.js": ("this.env.chatter.fetchThreadData = false",),
            "mail/static/src/core/web/store_service_patch.js": ("async scheduleActivity(resModel, resIds",),
            "mail/static/src/core/common/attachment_uploader_hook.js": (
                "export function useAttachmentUploader", "uploadData(", "async unlink("),
            "mail/static/src/core/common/attachment_list.js": ('static props = ["attachments", "unlinkAttachment"',),
            "mail/models/mail_thread.py": ('res["areAttachmentsLoaded"] = True',),
            "web/static/src/search/control_panel/control_panel.xml": (
                '<t t-slot="control-panel-navigation-additional"/>', "o_control_panel_navigation"),
            "web/static/src/search/cog_menu/cog_menu.js": ('registry.category("cogMenu")', "isDisplayed(this.env)"),
            "web/static/src/core/dialog/dialog.js": ('"fullscreen"',),
            "web/static/src/core/notebook/notebook.xml": ('t-esc="navItem[1].title"', 't-att-name="navItem[1].name"'),
            "web/static/src/views/form/form_controller.js": (
                "get className()", "o_xxl_form_view h-100", "async save(params)"),
            "web/static/src/views/form/form_compiler.js": (
                '"flex-nowrap h-100"', 'pageSlot.setAttribute("name", pageNodeName)',
                'const pageNodeName = toStringExpression(child.getAttribute("name") || "")'),
            "web/static/src/webclient/actions/action_service.js": ("controller.config.getDisplayName",),
            "web/static/src/core/templates.js": ("otherBlockId > blockId",),
        }
        for path, needles in checks.items():
            with file_open(path) as f:
                source = f.read()
            for needle in needles:
                with self.subTest(path=path, needle=needle):
                    self.assertIn(needle, source)
        # Копии web.FormView, у которых наш слот свой.
        for path, name, parent in ((RESOURCE_XML, "resource.FormViewWithHtmlExpander", "web.FormView"),
                                   (TASK_XML, "project.ProjectTaskFormView", "resource.FormViewWithHtmlExpander"),
                                   (PROJECT_XML, "project.ProjectFormView", "resource.FormViewWithHtmlExpander")):
            with self.subTest(template=name):
                node = _xml(path).find("t[@t-name='%s']" % name)
                self.assertIsNotNone(node)
                self.assertEqual(node.get("t-inherit"), parent)

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
                # Ниже шага 65 — только более поздние разделы (шаг 66: окно
                # «История» как в МоёмСкладе), старые правила его не перебивают.
                later = source.find("// ═══", start + 1)
                while later != -1:
                    head = source[later:later + 80]
                    step = re.search(r"Шаг (\d+)", head)
                    self.assertTrue(step and int(step.group(1)) > 65,
                                    "Ниже шага 65 — только разделы новее него: %s" % head)
                    later = source.find("// ═══", later + 1)
                self.assertLess(source.index("// ═══ Шаг 52"), start)
        forms = _read(FORMS_SCSS)
        self.assertLess(forms.index("// ═══ Лента документа в рамке"), forms.index(STEP_MARK))
        self.assertNotIn("Шаг 65", _read(OLD_FORMS_SCSS), "forms.scss выключен — правка туда не доедет.")

    def test_section_source(self):
        for path in (FORMS_SCSS, DARK_SCSS):
            code = _code(_section(_read(path)))
            with self.subTest(path=path):
                self.assertNotRegex(code, r"\b(?:min|max)\(", "libsass Odoo роняет сборку")
                lower = code.lower()
                for lime in BRIGHT_LIME:
                    self.assertNotIn(lime, lower)

    def test_light_rules(self):
        css = _compile(_section(_read(FORMS_SCSS)))
        screen = _rules(_media_blocks(css, "@media screen"))
        flow = ".o_form_view.o_pmk_chatter_out .o_form_renderer:not(:has(> .o_attachment_preview))"
        self.assertEqual(screen[flow]["flex-direction"], "column !important")
        self.assertEqual(screen[flow]["height"], "auto !important")
        self.assertEqual(screen[flow + " > .o_form_sheet_bg"]["flex"], "0 0 auto !important")
        top = _rules(css)
        tools = ".o_control_panel .o_control_panel_navigation > .o_pmk_doc_tools"
        self.assertEqual(top[tools]["order"], "-1", "Перед стрелками листалки, после этапа.")
        btn = ".o_pmk_doc_tools .btn.o_pmk_doc_tools__btn"
        self.assertEqual(top[btn]["height"], "28px", "Как стрелки листалки (48.5).")
        self.assertEqual(top['.o_pmk_doc_tools .btn.o_pmk_doc_tools__btn[aria-disabled="true"]']["cursor"],
                         "default")
        # Просрочка — словом на кнопке; на телефоне слово прячется.
        self.assertEqual(top[".o_pmk_doc_tools .o_pmk_doc_tools__overdue-word"]["font-weight"], "600")
        phone = _rules(_media_blocks(css, "@media (max-width: 767.98px)"))
        self.assertEqual(phone[".o_pmk_doc_tools .o_pmk_doc_tools__overdue-word"]["display"], "none")
        self.assertIn(".o_notebook .nav-link .o_pmk_tab_count", top)
        self.assertEqual(top[".pmk-history-dialog .pmk-history-dialog__col"]["max-width"], "1200px")

    def test_dark_pairs(self):
        css = _compile(_section(_read(DARK_SCSS)))
        dark = _rules(_media_blocks(css, "@media screen"))
        for selector in (".o_notebook .nav-link .o_pmk_tab_count",
                         ".o_pmk_doc_tools .o_pmk_doc_tools__overdue",
                         ".pmk-history-dialog .modal-body"):
            with self.subTest(selector=selector):
                self.assertIn("body.o_nexus_dark " + selector, dark)
        self.assertIn("var(--pmk-tone-red-ink)",
                      dark["body.o_nexus_dark .o_pmk_doc_tools .o_pmk_doc_tools__overdue"]["color"])

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
        for needle in (".o_pmk_doc_tools", ".o_pmk_chatter_out", ".o_pmk_tab_count", ".pmk-history-dialog",
                       "body.o_nexus_dark .o_notebook .nav-link .o_pmk_tab_count"):
            with self.subTest(needle=needle):
                self.assertIn(needle, css)


@tagged("post_install", "-at_install")
class TestStep65Session(HttpCase):
    """Выключатель доходит до браузера: session_info.pmk_chatter_in_form."""

    def test_session_flag_follows_group(self):
        password = "pmk65-session-pass"
        user = new_test_user(self.env, login="pmk65_session", password=password, groups="base.group_user")
        self.authenticate(user.login, password)
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertIs(info["pmk_chatter_in_form"], False)
        user.write({"group_ids": [Command.link(self.env.ref(REMOVED).id)]})
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertIs(info["pmk_chatter_in_form"], True)
