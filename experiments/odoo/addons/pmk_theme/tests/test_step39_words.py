# -*- coding: utf-8 -*-
"""Одно понятие — одно слово (разбор UX, шаг 39), pmk_theme.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py):
  odoo -d pmk39_test -i pmk_theme,pmk_purchase,pmk_deal --test-enable \
       --test-tags /pmk_theme:TestStep39Words,/pmk_theme:TestStep39Screens \
       --stop-after-init --http-port 8099

Что ловим:
  • файлы слов разбирает штатный PoFileReader; у каждой записи «#. module:»
    своего модуля, нет ссылок на имена действий и меню (это ACTION_TITLES),
    строка кода помечена odoo-python / odoo-javascript; в переводах нет
    старых слов;
  • подписи полей, значения списков и имена моделей в ru_RU — словами
    завода (сделка, проиграно, в работе, менеджер, снабженец, поставщик,
    эл. почта, регион, задача, закупка);
  • строки кода: Python (_()) и браузер (_t(), шаблоны) — наши, у модулей
    без файла слов и у других языков — как у ядра;
  • DATA_WORDS: подтипы ленты, тип задачи «Письмо», подпись вида «Задачи»,
    язык «Русский» — только поверх штатного слова, ручная правка цела,
    повтор ничего не меняет;
  • крючок _load_module_terms: загрузка перевода crm с перезаписью без
    темы возвращает «Возможность», с темой в списке — снова «Сделка» (так
    идёт -u crm: тема обновляется следом);
  • заголовки окон и пункты шестерёнки «Действия» / «Печать» — ACTION_TITLES,
    спрятанное шагом 29 по-прежнему спрятано;
  • поставщику — слова ядра: в файлах слов нет ссылок на портал, строка
    кода «Purchase Order» (фильтр портала, кнопка в письме поставщику) — как
    у ядра; тип задачи To-Do — «Напоминание», не «Задача»; окно «Сделка или
    лид» — как имя модели; страница входа, сотрудник, рабочая почта,
    подсказка региона компании и банка (доводка шага);
  • экраны (TestStep39Screens): штатный русский перевод модулей загружен,
    слова поверх — в разметке воронки, сделки, лида, контрагента,
    «Моих предпочтений», закупки, товара, окна задачи и расчёта и в
    подписях их полей нет старых слов; окна пунктов Продаж и Закупок
    называются без них.

Глазами (часики в шапке, лента, переключатель видов, печать закупки) —
основной агент на копии.
"""
import io
import re

from lxml import etree

from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_open
from odoo.tools.translate import (
    JAVASCRIPT_TRANSLATION_COMMENT,
    PYTHON_TRANSLATION_COMMENT,
    CodeTranslations,
    PoFileReader,
    get_translation,
)

from odoo.addons.pmk_theme.models.ir_actions import HIDDEN_BINDINGS
from odoo.addons.pmk_theme.models.ir_actions_act_window import ACTION_TITLES
from odoo.addons.pmk_theme.models.words import DATA_WORDS, LANG, LANG_NAME, WORDS_PATH, words_modules

REMOVED = "pmk_theme.group_pmk_removed"
# Старые слова словаря разбора. «Спецификация» — отдельно: на заводе это
# чертёж клиента, а у спрятанного Производства — состав изделия (mrp), его
# слова шаг не трогает.
OLD_RU = re.compile(
    r"возможност|потерян|причин\w* потер|покупател|закупщик|продавц|продавец|активност|"
    r"\bдел[оа]?\b|мероприят|на покупку|\bпокупк|частное государство|частная страна|ваш email",
    re.I)
OLD_EN = re.compile(r"\b(?:E-?mail|EMAIL|Email|Opportunit\w*|Lost|Activit\w*)\b")
SPEC = re.compile(r"спецификац", re.I)
VISIBLE_ATTRS = ("string", "help", "placeholder", "title", "confirm", "aria-label", "sum")
# Ссылки, которых в файлах слов быть не должно (сборщик их отбрасывает).
FORBIDDEN_REFS = re.compile(
    r"^model:(ir\.ui\.menu|ir\.actions\.act_window|ir\.actions\.server|mail\.message\.subtype|"
    r"mail\.activity\.type|mail\.template|res\.groups),")


def visible_texts(arch):
    """Видимые тексты разметки: подписи, подсказки, тексты узлов."""
    root = etree.fromstring(arch) if isinstance(arch, (str, bytes)) else arch
    out = []
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue  # комментарии
        out += [node.get(attr) for attr in VISIBLE_ATTRS if node.get(attr)]
        out += [text.strip() for text in (node.text, node.tail) if text and text.strip()]
    return out


# «Счета покупателям» / «Счёт покупателю» — название заказа клиента по
# прямой просьбе Антона (шаг 58, 08.10.2026); в остальных местах «клиент».
ALLOWED_RU = re.compile(r"сч[её]т\w*\s+покупател\w*", re.I)


def old_words(text, spec=False):
    text = ALLOWED_RU.sub("", text)
    found = OLD_RU.findall(text) + OLD_EN.findall(text)
    if spec:
        found += SPEC.findall(text)
    return found


def read_words(module):
    with file_open(WORDS_PATH % module, "rb") as fh:
        data = fh.read()
    stream = io.BytesIO(data)
    stream.name = WORDS_PATH % module
    return list(PoFileReader(stream))


class Step39Common(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang(LANG)
        cls.Module = cls.env["ir.module.module"]
        cls.ru = cls.env(context=dict(cls.env.context, lang=LANG))

    def _installed(self, module):
        return self.env["ir.module.module"]._get(module).state == "installed"

    def _label(self, model, field):
        return self.ru[model].fields_get([field], ["string"])[field]["string"]

    def _selection(self, model, field):
        return dict(self.ru[model].fields_get([field], ["selection"])[field]["selection"])

    def _set_ru(self, record, fname, value):
        """Записать русское значение, как его кладёт загрузка перевода ядра."""
        self.env.flush_all()
        self.env.cr.execute(
            'UPDATE "%s" SET "%s" = COALESCE("%s", \'{}\'::jsonb) || jsonb_build_object(%%s, %%s::text)'
            ' WHERE id = %%s' % (record._table, fname, fname), (LANG, value, record.id))
        record.invalidate_recordset([fname])
        self.env.registry.clear_cache("stable", "templates")

    def _ru(self, record, fname):
        return record.with_context(lang=LANG)[fname]


@tagged("post_install", "-at_install")
class TestStep39Words(Step39Common):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Module._pmk_apply_words()

    # ─── Файлы слов ─────────────────────────────────────────────────────
    def test_words_files(self):
        modules = words_modules()
        self.assertGreaterEqual(set(modules), {"base", "crm", "mail", "purchase", "product"})
        for module in modules:
            rows = read_words(module)
            with self.subTest(module=module):
                self.assertTrue(rows, "Файл слов не пуст.")
            for row in rows:
                with self.subTest(module=module, src=row["src"][:50]):
                    self.assertTrue(row["value"], "Пустой перевод ядро пропустит молча.")
                    if row["type"] == "code":
                        self.assertEqual(row["module"], module)
                        self.assertTrue(PYTHON_TRANSLATION_COMMENT in row["comments"]
                                        or JAVASCRIPT_TRANSLATION_COMMENT in row["comments"])
                    else:
                        ref = "model:%s,%s" % (row["imd_model"], row["name"].split(",")[1])
                        self.assertFalse(FORBIDDEN_REFS.match(ref), ref)
                        self.assertEqual(row["module"], module, "xml-id своего модуля.")
                    # Видимый текст перевода: без разметки, подсказки — из title.
                    shown = re.sub(r"<[^>]+>", " ", row["value"]) + " ".join(
                        re.findall(r'title="([^"]*)"', row["value"]))
                    self.assertFalse(old_words(shown), shown)

    def test_words_still_match_core(self):
        """Обновили Odoo — запись слов перестала совпадать с ядром молча:
        xml-id пропал, термина вида больше нет, строки кода нет в переводе
        модуля. Ловим здесь."""
        arch_field = self.env["ir.ui.view"]._fields["arch_db"]
        installed = {m.name for m in self.env["ir.module.module"].search([("state", "=", "installed")])}
        for module in words_modules():
            if module not in installed:
                continue
            core_code = {}
            for comment in (PYTHON_TRANSLATION_COMMENT, JAVASCRIPT_TRANSLATION_COMMENT):
                core_code[comment] = CodeTranslations._get_code_translations(
                    module, LANG, lambda row, c=comment: row.get("value") and c in row["comments"])
            for row in read_words(module):
                with self.subTest(module=module, src=row["src"][:50]):
                    if row["type"] == "code":
                        kinds = [c for c in core_code if c in row["comments"]]
                        self.assertTrue(any(row["src"] in core_code[c] for c in kinds),
                                        "Строки кода нет в переводе модуля.")
                        continue
                    record = self.env.ref("%s.%s" % (row["module"], row["imd_name"]), raise_if_not_found=False)
                    self.assertTrue(record, "xml-id на месте.")
                    self.assertEqual(record._name, row["imd_model"])
                    if row["type"] == "model_terms":
                        en = record.with_context(lang="en_US")[row["name"].split(",")[1]]
                        self.assertIn(row["src"], arch_field.get_trans_terms(en), "Термин вида на месте.")

    # ─── Подписи полей, значения списков, имена моделей ─────────────────
    def test_crm_labels(self):
        self.assertEqual(self._label("crm.lead", "name"), "Сделка")
        self.assertEqual(self._label("crm.lead", "lost_reason_id"), "Причина проигрыша")
        self.assertEqual(self._label("crm.lead", "won_status"), "Выиграно/проиграно")
        self.assertEqual(self._label("crm.lead", "user_id"), "Менеджер")
        won = self._selection("crm.lead", "won_status")
        self.assertEqual((won["lost"], won["pending"]), ("Проиграно", "В работе"))
        self.assertEqual(self._selection("crm.lead", "type")["opportunity"], "Сделка")
        self.assertEqual(self._label("crm.lead.lost", "lost_reason_id"), "Причина проигрыша")
        self.assertIn("эл. почте", self.ru["crm.lead"].fields_get(["partner_id"], ["help"])["partner_id"]["help"])

    def test_partner_and_user_labels(self):
        for model in ("res.partner", "res.users"):
            with self.subTest(model=model):
                self.assertEqual(self._label(model, "email"), "Эл. почта")
                self.assertEqual(self._label(model, "state_id"), "Регион")
                self.assertEqual(self._label(model, "user_id"), "Менеджер")
                self.assertEqual(self._label(model, "activity_ids"), "Задачи")
                self.assertEqual(self._label(model, "opportunity_ids"), "Сделки")
                if self._installed("purchase"):
                    self.assertEqual(self._label(model, "buyer_id"), "Снабженец")
        self.assertEqual(self._label("res.users", "signature"), "Подпись в письмах")
        if self._installed("hr"):
            self.assertEqual(self._label("res.users", "private_email"), "Личная эл. почта")
            self.assertEqual(self._label("res.users", "private_state_id"), "Регион (домашний адрес)")

    def test_purchase_and_product_labels(self):
        if not self._installed("purchase"):
            self.skipTest("purchase")
        self.assertEqual(self._label("purchase.order", "user_id"), "Снабженец")
        self.assertEqual(self._label("purchase.order", "partner_id"), "Поставщик")
        state = self._selection("purchase.order", "state")
        self.assertEqual((state["draft"], state["sent"], state["purchase"]),
                         ("Запрос КП", "Запрос КП отправлен", "Заказ поставщику"))
        # «Закупки» — пара к «Продажам» рядом и как раздел в шапке.
        self.assertEqual(self._label("product.template", "purchase_ok"), "Закупки")
        self.assertEqual(self._label("product.template", "seller_ids"), "Поставщики")
        self.assertEqual(self._label("product.template", "description_purchase"), "Описание для закупки")
        self.assertEqual(self._label("product.supplierinfo", "partner_id"), "Поставщик")
        if self._installed("purchase_stock"):
            self.assertEqual(self._label("product.supplierinfo", "last_purchase_date"), "Последняя закупка")

    def test_activity_labels(self):
        self.assertEqual(self._label("mail.activity", "activity_type_id"), "Тип задачи")
        self.assertEqual(self._label("mail.activity.schedule", "activity_type_id"), "Тип задачи")
        self.assertEqual(self._label("res.partner", "activity_date_deadline"), "Срок следующей задачи")

    def test_model_names(self):
        Model = self.env["ir.model"]
        expected = {"crm.lead": "Сделка или лид", "crm.lost.reason": "Причина проигрыша",
                    "crm.lead.lost": "Указать причину проигрыша", "mail.activity": "Задача",
                    "mail.activity.type": "Тип задачи"}
        if self._installed("purchase"):
            expected.update({"purchase.order": "Заказ поставщику",
                             "purchase.order.line": "Позиция заказа поставщику"})
        for model, name in expected.items():
            with self.subTest(model=model):
                self.assertEqual(self._ru(Model._get(model), "name"), name)

    def test_hr_labels(self):
        """Сотрудник и рабочая почта (раздел «Сотрудники», «Мои предпочтения»)."""
        if not self._installed("hr"):
            self.skipTest("hr")
        self.assertEqual(self._label("res.users", "work_email"), "Рабочая эл. почта")
        self.assertEqual(self._label("hr.employee", "work_email"), "Рабочая эл. почта")
        self.assertEqual(self._label("hr.employee", "private_email"), "Личная эл. почта")
        self.assertEqual(self._label("hr.employee", "email"), "Эл. почта")
        self.assertEqual(self._label("hr.employee", "activity_ids"), "Задачи")
        self.assertEqual(self._label("hr.employee", "activity_type_id"), "Тип следующей задачи")
        self.assertEqual(self._label("hr.employee", "activity_date_deadline"), "Срок следующей задачи")
        self.assertEqual(self._label("hr.employee", "my_activity_date_deadline"), "Срок моей задачи")

    def test_todo_type_is_reminder(self):
        """Тип To-Do — «Напоминание»: «Задача» — всё понятие (имя модели)."""
        todo = self.env.ref("mail.mail_activity_data_todo")
        self._set_ru(todo, "name", "Задача")
        self.Module._pmk_apply_data_words()
        self.assertEqual(self._ru(todo, "name"), "Напоминание")
        self.assertNotEqual(self._ru(todo, "name"), self._ru(self.env["ir.model"]._get("mail.activity"), "name"))
        message = get_translation("mail", LANG, (
            "The 'To-Do' activity type is used to create reminders from the top bar menu and the "
            "command palette. Consequently, it cannot be archived or deleted."), ())
        self.assertIn("«Напоминание»", message)

    def test_vendor_facing_untouched(self):
        """Поставщику — слова ядра: портал /my/purchase и письмо ему.

        Строка кода «Purchase Order» у purchase стоит только там (фильтр
        портала и кнопка «Просмотреть …» в письме — model_description),
        поэтому её в файле слов нет; ссылок на виды портала — тоже."""
        for module in words_modules():
            for row in read_words(module):
                ref = row.get("imd_name") or row.get("name") or ""
                with self.subTest(module=module, ref=ref):
                    self.assertNotIn("portal", ref)
        if not self._installed("purchase"):
            return
        filter_py = lambda row: row.get("value") and PYTHON_TRANSLATION_COMMENT in row["comments"]  # noqa: E731
        core = CodeTranslations._get_code_translations("purchase", LANG, filter_py)
        self.assertEqual(get_translation("purchase", LANG, "Purchase Order", ()),
                         core.get("Purchase Order", "Purchase Order"))
        # Внутри завода — наши слова: имя модели и статус заказа.
        self.assertEqual(self._ru(self.env["ir.model"]._get("purchase.order"), "name"), "Заказ поставщику")
        self.assertEqual(self._selection("purchase.order", "state")["purchase"], "Заказ поставщику")

    def test_login_page(self):
        """Страница входа: администратор входит логином, остальные — почтой."""
        arch = self.env.ref("web.login").with_context(lang=LANG).arch_db
        self.assertIn("Логин или эл. почта</label>", arch)
        self.assertIn('placeholder="Введите логин или эл. почту"', arch)
        self.assertFalse(re.search(r">\s*Email\s*<", arch), "Подписи «Email» нет.")

    # ─── Строки кода ────────────────────────────────────────────────────
    def test_code_translations_python(self):
        self.assertTrue(getattr(CodeTranslations, "_pmk_words", False), "Обёртка стоит.")
        self.assertEqual(get_translation("crm", LANG, "%s's opportunity", ("ООО Ромашка",)),
                         "Сделка ООО Ромашка")
        self.assertEqual(get_translation("crm", LANG, "Opportunities", ()), "Сделки")
        self.assertEqual(get_translation("mail", LANG, "Other activities", ()), "Другие задачи")
        if self._installed("purchase"):
            self.assertEqual(get_translation("purchase", LANG, "Purchases", ()), "Закупки")
            # Окно кнопки «Закуплено» в карточке товара.
            self.assertEqual(get_translation("purchase", LANG, "Purchase History for %s", ("Лист 3",)),
                             "История закупок: Лист 3")
        # Окно после перевода лида в сделку и объединения — как имя модели.
        self.assertEqual(get_translation("crm", LANG, "Lead or Opportunity", ()),
                         self._ru(self.env["ir.model"]._get("crm.lead"), "name"))
        if self._installed("project_todo"):
            # Группа напоминаний в часиках.
            self.assertEqual(get_translation("project_todo", LANG, "To-Do", ()), "Напоминания")
        self.assertEqual(get_translation("crm", "en_US", "%s's opportunity", ("X",)), "X's opportunity",
                         "Английский не тронут.")

    def test_code_translations_web(self):
        translations, _params = self.env["ir.http"]._get_translations_for_webclient(["mail", "crm"], LANG)
        mail = {m["id"]: m["string"] for m in translations["mail"]["messages"]}
        # Часики: ссылка внизу и пустое меню; лента: кнопка и список задач.
        self.assertEqual(mail["View all activities"], "Мои задачи")
        self.assertEqual(mail["Congratulations, you're done with your activities."], "Все задачи выполнены.")
        self.assertEqual(mail["Activity"], "Задача")
        self.assertEqual(mail["Planned Activities"], "Запланированные задачи")
        self.assertEqual(mail["Schedule Activity"], "Запланировать задачу")
        crm = {m["id"]: m["string"] for m in translations["crm"]["messages"]}
        self.assertEqual(crm["Close opportunities to get insights."], "Закрывайте сделки, чтобы видеть аналитику.")
        if self._installed("project_todo"):
            # Палитра команд (Ctrl+K) и окно: напоминание, а не «дело».
            todo, _params = self.env["ir.http"]._get_translations_for_webclient(["project_todo"], LANG)
            todo = {m["id"]: m["string"] for m in todo["project_todo"]["messages"]}
            self.assertEqual(todo["Add a To-Do"], "Добавить напоминание")

    def test_code_translations_merge_not_replace(self):
        """Слова доливаются поверх перевода модуля, а не вместо него; модуль
        без файла слов — как у ядра."""
        fresh = CodeTranslations()
        fresh._load_python_translations("crm", LANG)
        filter_py = lambda row: row.get("value") and PYTHON_TRANSLATION_COMMENT in row["comments"]  # noqa: E731
        core = CodeTranslations._get_code_translations("crm", LANG, filter_py)
        merged = fresh.python_translations[("crm", LANG)]
        self.assertLessEqual(set(core), set(merged), "Ни одна строка ядра не пропала.")
        untouched = [key for key in core if merged[key] == core[key]]
        self.assertGreater(len(untouched), len(core) // 2, "Остальное — перевод ядра.")
        self.assertEqual(merged["%s's opportunity"], "Сделка %s")
        fresh._load_python_translations("sale", LANG)
        self.assertEqual(dict(fresh.python_translations[("sale", LANG)]),
                         CodeTranslations._get_code_translations("sale", LANG, filter_py))
        fresh._load_python_translations("crm", "fr_FR")
        self.assertNotEqual(fresh.python_translations[("crm", "fr_FR")].get("%s's opportunity"), "Сделка %s")

    # ─── Данные noupdate ────────────────────────────────────────────────
    def test_data_words(self):
        for xmlid, fname, old, new in DATA_WORDS:
            record = self.env.ref(xmlid, raise_if_not_found=False)
            if not record:
                continue
            with self.subTest(record=xmlid, field=fname):
                self._set_ru(record, fname, old)
                self.Module._pmk_apply_data_words()
                self.assertEqual(self._ru(record, fname), new)
                self.Module._pmk_apply_data_words()
                self.assertEqual(self._ru(record, fname), new, "Повтор ничего не меняет.")
                self._set_ru(record, fname, "Своё слово")
                self.Module._pmk_apply_data_words()
                self.assertEqual(self._ru(record, fname), "Своё слово", "Ручная правка цела.")

    def test_view_switcher_label(self):
        """Переключатель видов берёт подпись вида из списка значений поля type."""
        record = self.env.ref("mail.selection__ir_ui_view__type__activity")
        self._set_ru(record, "name", "Активность")
        self.Module._pmk_apply_words()
        info = self.ru["ir.ui.view"].get_view_info()
        self.assertEqual(info["activity"]["display_name"], "Задачи")

    def test_language_name(self):
        xmlid, old, new = LANG_NAME
        lang = self.env.ref(xmlid)
        lang.name = old
        self.Module._pmk_apply_data_words()
        self.assertEqual(lang.name, new)
        self.assertIn((LANG, new), self.env["res.lang"].get_installed(),
                      "Выбор языка в «Моих предпочтениях» — «Русский».")
        lang.name = "Русский (свой)"
        self.Module._pmk_apply_data_words()
        self.assertEqual(lang.name, "Русский (свой)", "Ручная правка цела.")

    # ─── Крючок загрузки переводов ──────────────────────────────────────
    def test_load_module_terms_hook(self):
        field = self.env["ir.model.fields"]._get("crm.lead", "name")
        # Перевод crm с перезаписью без темы — штатное слово ядра.
        self.Module._load_module_terms(["crm"], [LANG], overwrite=True)
        self.assertNotEqual(self._ru(field, "field_description"), "Сделка",
                            "Посылка: загрузка ядра с перезаписью затирает слово.")
        # Тема в списке (так идёт -u crm: тема обновляется следом) — снова наше.
        self.Module._load_module_terms(["crm", "pmk_theme"], [LANG], overwrite=True)
        self.assertEqual(self._ru(field, "field_description"), "Сделка")
        self.env.registry.clear_cache("stable")
        self.assertEqual(self._label("crm.lead", "name"), "Сделка")

    # ─── Заголовки окон и шестерёнка ────────────────────────────────────
    def test_window_titles(self):
        Action = self.env["ir.actions.act_window"]
        expected = {
            "crm.crm_lead_opportunities": "Сделки",
            "crm.crm_lead_lost_action": "Отметить проигрыш",
            "crm.crm_lost_reason_action": "Причины проигрыша",
            "mail.mail_activity_action_my": "Мои задачи",
            "mail.mail_activity_without_access_action": "Другие задачи",
        }
        if self._installed("purchase"):
            expected.update({"purchase.purchase_form_action": "Подтверждённые заказы",
                             "purchase.act_res_partner_2_purchase_order": "Закупки"})
        for xmlid, title in expected.items():
            self.assertEqual(ACTION_TITLES[xmlid], title)
            for lang in ("en_US", LANG):
                with self.subTest(action=xmlid, lang=lang):
                    action = Action.with_context(lang=lang)._for_xml_id(xmlid)
                    self.assertEqual((action["name"], action["display_name"]), (title, title))
        self.assertNotEqual(self._ru(self.env.ref("crm.crm_lead_lost_action"), "name"),
                            "Отметить проигрыш", "В базе имя штатное — подмена при отдаче.")

    def test_gear_titles_and_hidden(self):
        user = new_test_user(
            self.env, login="pmk39_gear",
            groups="base.group_user,sales_team.group_sale_salesman_all_leads,"
                   "purchase.group_purchase_manager")
        self.assertFalse(user.has_group(REMOVED), "Посылка: «Убранного» у человека нет.")
        Actions = self.env["ir.actions.actions"].with_user(user).with_context(lang=LANG)

        def names(model):
            bindings = Actions.get_bindings(model)
            return {action["id"]: action["name"]
                    for kind in ("action", "report") for action in bindings.get(kind, ())}

        lead = names("crm.lead")
        lost = self.env.ref("crm.crm_lead_lost_action")
        self.assertEqual(lead.get(lost.id), "Отметить проигрыш")
        for xmlid in HIDDEN_BINDINGS:
            hidden = self.env.ref(xmlid, raise_if_not_found=False)
            if hidden and hidden.binding_model_id.model == "crm.lead":
                with self.subTest(hidden=xmlid):
                    self.assertNotIn(hidden.id, lead, "Спрятанное шагом 29 — по-прежнему спрятано.")
        if not self._installed("purchase"):
            return
        po = names("purchase.order")
        for xmlid in ("purchase.action_report_purchase_order", "purchase.report_purchase_quotation",
                      "purchase.action_confirm_rfqs", "purchase.action_merger"):
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action and action.id in po:
                with self.subTest(action=xmlid):
                    self.assertEqual(po[action.id], ACTION_TITLES[xmlid])
        reminder = self.env.ref("purchase.action_purchase_send_reminder", raise_if_not_found=False)
        if reminder:
            self.assertNotIn(reminder.id, po)


# Экраны шага: (модель, xml-id вида, тип вида, проверять «спецификацию»).
SCREENS = [
    ("crm.lead", "crm.crm_case_kanban_view_leads", "kanban", False),
    ("crm.lead", "crm.crm_case_tree_view_oppor", "list", False),
    ("crm.lead", "crm.crm_case_tree_view_leads", "list", False),
    ("crm.lead", "crm.crm_lead_view_form", "form", False),
    ("crm.lead", "crm.view_crm_case_opportunities_filter", "search", False),
    ("crm.lead", "crm.view_crm_case_leads_filter", "search", False),
    ("crm.lead", "crm.crm_lead_view_activity", "activity", False),
    ("crm.lead.lost", "crm.crm_lead_lost_view_form", "form", False),
    ("res.partner", "base.view_partner_form", "form", False),
    ("res.partner", "base.view_res_partner_filter", "search", False),
    ("res.users", "base.view_users_form_simple_modif", "form", False),
    ("res.users", "hr.res_users_view_form_preferences", "form", False),
    ("mail.activity.schedule", "mail.mail_activity_schedule_view_form", "form", False),
    ("mail.activity", "mail.mail_activity_view_form_popup", "form", False),
    ("purchase.order", "purchase.purchase_order_form", "form", False),
    ("purchase.order", "purchase.purchase_order_kpis_tree", "list", False),
    ("purchase.order", "purchase.view_purchase_order_filter", "search", False),
    ("product.template", "product.product_template_form_view", "form", False),
    ("product.template", "product.product_template_search_view", "search", False),
    ("product.supplierinfo", "product.product_supplierinfo_form_view", "form", False),
    ("pmk.metal.spec", "pmk_calc.view_metal_spec_form", "form", True),
    ("pmk.metal.spec", "pmk_calc.view_metal_spec_list", "list", True),
    ("pmk.metal.spec", "pmk_calc.view_metal_spec_search", "search", True),
]


@tagged("post_install", "-at_install")
class TestStep39Screens(Step39Common):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Штатный русский перевод всех модулей, чьи поля и виды на экранах
        # шага (как «Обновить» перевод языка; без перезаписи), — тема в том
        # же списке: её крючок кладёт слова поверх. Иначе на свежей базе
        # подписи чужих модулей остались бы английскими и путали проверку.
        models = tuple({model for model, _xmlid, _type, _spec in SCREENS})
        cls.env.flush_all()
        cls.env.cr.execute("""
            SELECT d.module FROM ir_model_data d
              JOIN ir_model_fields f ON d.model = 'ir.model.fields' AND d.res_id = f.id
             WHERE f.model IN %s
            UNION
            SELECT d.module FROM ir_model_data d
              JOIN ir_ui_view v ON d.model = 'ir.ui.view' AND d.res_id = v.id
             WHERE v.model IN %s
        """, [models, models])
        owners = {row[0] for row in cls.env.cr.fetchall()} | {"base", "web", "mail", "pmk_theme"}
        Module = cls.env["ir.module.module"]
        Module.search([("name", "in", list(owners)), ("state", "=", "installed")])._update_translations([LANG])
        cls.manager = new_test_user(
            cls.env, login="pmk39_screens",
            groups="base.group_user,sales_team.group_sale_salesman,purchase.group_purchase_user")

    def _arch(self, model, xmlid, view_type):
        view = self.env.ref(xmlid, raise_if_not_found=False)
        if not view or model not in self.env:
            return None
        views = self.env[model].with_user(self.manager).with_context(lang=LANG).get_views(
            [(view.id, view_type)])
        return views["views"][view_type]["arch"]

    def test_screens_without_old_words(self):
        checked = 0
        for model, xmlid, view_type, spec in SCREENS:
            arch = self._arch(model, xmlid, view_type)
            if arch is None:
                continue
            checked += 1
            root = etree.fromstring(arch)
            for text in visible_texts(root):
                with self.subTest(view=xmlid, text=text[:60]):
                    self.assertFalse(old_words(text, spec), text)
            fields = {node.get("name") for node in root.iter("field")}
            info = self.ru[model].fields_get(list(fields), ["string", "selection"])
            for fname, desc in info.items():
                texts = [desc.get("string") or ""] + [label for _v, label in desc.get("selection") or []]
                for text in texts:
                    with self.subTest(view=xmlid, field=fname, text=text[:60]):
                        self.assertFalse(old_words(str(text), spec), text)
        self.assertGreaterEqual(checked, 15)

    def test_screens_new_words(self):
        """Слова завода стоят там, где стояли старые (а не пропали вместе с узлом)."""
        expected = {
            "crm.view_crm_case_opportunities_filter": ['string="Сделки в работе"', 'string="Проиграно"',
                                                        'string="В работе"', 'help="Без менеджера"',
                                                        'string="Причина проигрыша"'],
            "crm.crm_lead_view_form": ['string="Проиграно"', 'title="Отметить проигрыш"'],
            "crm.crm_case_kanban_view_leads": ["Полоса фильтрует сделки по запланированным задачам."],
            # Группа поставщика на вкладке «Продажи и закупки» — пара к «Продажам».
            "base.view_partner_form": ['title="Эл. почта"', 'placeholder="Регион"', 'string="Закупки"'],
            "purchase.view_purchase_order_filter": ['string="Снабженец"', 'string="Мои задачи"'],
            "pmk_calc.view_metal_spec_list": ['string="Расчёты"'],
            "hr.res_users_view_form_preferences": ['title="Рабочая эл. почта"', 'placeholder="Регион"'],
        }
        types = {xmlid: (model, view_type) for model, xmlid, view_type, _spec in SCREENS}
        for xmlid, needles in expected.items():
            model, view_type = types[xmlid]
            arch = self._arch(model, xmlid, view_type)
            if arch is None:
                continue
            for needle in needles:
                with self.subTest(view=xmlid, needle=needle):
                    self.assertIn(needle, arch)

    def test_product_flags_pair(self):
        """Флажки под названием товара — пара «Продажи / Закупки» (у «Продаж»
        перевод ядра, поэтому здесь, где он загружен)."""
        self.assertEqual((self._label("product.template", "sale_ok"),
                          self._label("product.template", "purchase_ok")), ("Продажи", "Закупки"))

    def test_neighbour_screens_new_words(self):
        """Соседи, куда достают те же слова (доводка шага): карточка компании и
        банка (подсказка региона), сотрудник (рабочая почта, задачи). Под
        администратором: у менеджера нет прав на сотрудников."""
        expected = {
            ("res.company", "base.view_company_form", "form"): ['placeholder="Регион"'],
            ("res.bank", "base.view_res_bank_form", "form"): ['placeholder="Регион"'],
            ("hr.employee", "hr.view_employee_form", "form"): ['title="Рабочая эл. почта"'],
            ("hr.employee", "hr.view_employee_tree", "list"): ['string="Исполнитель задачи"'],
            ("hr.employee", "hr.view_employee_filter", "search"): [
                'string="Мои задачи"', 'string="Просроченные задачи"'],
            ("hr.employee", "hr.hr_kanban_view_employees", "kanban"): ['title="Эл. почта"'],
        }
        for (model, xmlid, view_type), needles in expected.items():
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if not view or model not in self.env:
                continue
            arch = self.env[model].with_context(lang=LANG).get_views([(view.id, view_type)])
            arch = arch["views"][view_type]["arch"]
            for needle in needles:
                with self.subTest(view=xmlid, needle=needle):
                    self.assertIn(needle, arch)

    def test_menu_windows_without_old_words(self):
        """Окна пунктов Продаж и Закупок называются без старых слов."""
        roots = [self.env.ref(x, raise_if_not_found=False)
                 for x in ("pmk_theme.menu_pmk_sales", "pmk_theme.menu_pmk_purchase")]
        menus = self.env["ir.ui.menu"].search([("id", "child_of", [r.id for r in roots if r])])
        checked = 0
        for menu in menus:
            action = menu.action
            if not action or action._name != "ir.actions.act_window":
                continue
            name = action.with_context(lang=LANG)._get_action_dict()["name"]
            checked += 1
            with self.subTest(menu=menu.complete_name, window=name):
                self.assertFalse(old_words(name), name)
        self.assertGreater(checked, 5)

    def test_systray_and_chatter_words(self):
        translations, _params = self.env["ir.http"]._get_translations_for_webclient(["mail"], LANG)
        mail = {m["id"]: m["string"] for m in translations["mail"]["messages"]}
        for msgid in ("Activities", "Activity", "View all activities", "Planned Activities",
                      "Schedule Activity", "Schedule an activity", "Show activities",
                      "Congratulations, you're done with your activities.", "Email Failure: %(modelName)s"):
            with self.subTest(msgid=msgid):
                self.assertFalse(old_words(mail[msgid]), mail[msgid])
