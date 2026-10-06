# -*- coding: utf-8 -*-
"""Шапка сделки — разбор UX, шаг 48 (06.10.2026): номер «СД-» и карточка
без «Новое».

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py), не на боевой odoo.

Вид шапки (номер в строке пути, кнопки наверху, «Новое» нет, «Дублировать»
есть) смотрит основной агент глазами на копии — туры здесь не запустить
(в контейнере нет браузера). Здесь — то, что ломается молча: номер не
выдался или выдался лиду и архивной сделке, дата не в том поясе, миграция
пронумеровала архив, имя сделки поменялось (тема писем), вид потерял
xpath, «Новое» пропало и в воронке.
"""
import re
from datetime import date, datetime

from lxml import etree
from psycopg2 import IntegrityError

from odoo import SUPERUSER_ID, api, fields
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger
from odoo.tools.misc import file_path

from odoo.addons.pmk_deal.hooks import number_active_deals
from odoo.addons.pmk_deal.models.deal_number import SEQUENCE_CODE, number_label

NUMBER = re.compile(r"^СД-\d{5}$")
TZ = "Asia/Vladivostok"


def local_day(record, moment, tz=TZ):
    return fields.Date.context_today(record.with_context(tz=tz), moment)


@tagged("post_install", "-at_install")
class TestDealNumberStep48(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login="pmk48_manager", tz=TZ,
            groups="base.group_user,sales_team.group_sale_salesman_all_leads")
        cls.Lead = cls.env["crm.lead"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True, tracking_disable=True)

    def _deal(self, **vals):
        values = {"name": "Запрос стоимости (шаг 48)", "type": "opportunity",
                  "user_id": self.manager.id}
        values.update(vals)
        return self.Lead.create(values)

    def _lead(self, **vals):
        values = {"name": "Заявка с почты (шаг 48)", "type": "lead",
                  "user_id": self.manager.id}
        values.update(vals)
        return self.Lead.create(values)

    # ─── Выдача номера ──────────────────────────────────────────────────
    def test_created_as_deal_gets_number(self):
        deal = self._deal()
        self.assertRegex(deal.pmk_number or "", NUMBER)
        self.assertEqual(deal.pmk_number_date, local_day(deal, deal.create_date),
                         "Дата — день создания по поясу менеджера.")
        self.assertEqual(deal.pmk_number_label, "%s от %s" % (
            deal.pmk_number, deal.pmk_number_date.strftime("%d.%m.%Y")))

    def test_lead_has_no_number(self):
        lead = self._lead()
        self.assertFalse(lead.pmk_number)
        self.assertFalse(lead.pmk_number_date)
        self.assertFalse(lead.pmk_number_label)

    def test_convert_opportunity_gets_number(self):
        lead = self._lead()
        lead.convert_opportunity(self.env["res.partner"])
        self.assertEqual(lead.type, "opportunity")
        self.assertRegex(lead.pmk_number or "", NUMBER)
        self.assertTrue(lead.date_conversion)
        self.assertEqual(lead.pmk_number_date, local_day(lead, lead.date_conversion),
                         "Дата номера — день превращения в сделку.")

    def test_convert_wizard_gets_number(self):
        lead = self._lead()
        wizard = self.env["crm.lead2opportunity.partner"].with_context(
            active_model="crm.lead", active_id=lead.id, active_ids=lead.ids,
        ).create({"name": "convert", "action": "exist", "lead_id": lead.id})
        wizard.action_apply()
        self.assertEqual(lead.type, "opportunity")
        self.assertRegex(lead.pmk_number or "", NUMBER)

    def test_conversion_day_in_manager_timezone(self):
        """02.10 22:55 UTC — уже 03.10 во Владивостоке (сделка №19)."""
        lead = self._lead()
        lead.with_context(tz=False).write({
            "type": "opportunity",
            "date_conversion": datetime(2026, 10, 2, 22, 55, 32),
        })
        self.assertEqual(lead.pmk_number_date, date(2026, 10, 3))

    def test_archived_deal_numbered_on_restore(self):
        deal = self._deal(active=False)
        self.assertFalse(deal.pmk_number, "Архивной сделке номер не выдаётся.")
        deal.action_restore()
        self.assertTrue(deal.active)
        self.assertRegex(deal.pmk_number or "", NUMBER)
        other = self._deal(active=False)
        other.action_unarchive()
        self.assertRegex(other.pmk_number or "", NUMBER)
        self.assertNotEqual(other.pmk_number, deal.pmk_number)

    def test_lost_deal_keeps_number(self):
        deal = self._deal()
        number = deal.pmk_number
        deal.action_set_lost()
        self.assertFalse(deal.active)
        self.assertEqual(deal.pmk_number, number)
        deal.action_restore()
        self.assertEqual(deal.pmk_number, number, "Восстановленная — со своим номером.")

    def test_back_to_lead_keeps_number(self):
        deal = self._deal()
        number = deal.pmk_number
        deal.write({"type": "lead"})
        self.assertEqual(deal.pmk_number, number, "Номер хранится, показ — по типу.")

    def test_duplicate_gets_new_number(self):
        # Оригинал превращён в сделку давно — как сделка №12 (27.09).
        deal = self._lead()
        deal.with_context(tz=False).write({
            "type": "opportunity",
            "date_conversion": datetime(2020, 1, 15, 3, 0, 0),
        })
        self.assertEqual(deal.pmk_number_date, date(2020, 1, 15))
        copy = deal.copy()
        self.assertRegex(copy.pmk_number or "", NUMBER)
        self.assertNotEqual(copy.pmk_number, deal.pmk_number)
        self.assertFalse(copy.date_conversion,
                         "Копия создана сразу сделкой — даты превращения у неё нет.")
        self.assertEqual(copy.pmk_number_date, local_day(copy, copy.create_date),
                         "Дата номера копии — день её создания, а не превращения оригинала.")
        self.assertEqual(deal.date_conversion, datetime(2020, 1, 15, 3, 0, 0),
                         "Оригинал свою дату превращения хранит.")
        kept = deal.copy({"date_conversion": datetime(2021, 3, 1, 3, 0, 0)})
        self.assertEqual(kept.date_conversion, datetime(2021, 3, 1, 3, 0, 0),
                         "Явно переданную дату copy_data не трогает.")

    def test_numbers_follow_sequence(self):
        first, second = self._deal(), self._deal()
        self.assertLess(first.pmk_number, second.pmk_number)

    def test_field_flags_and_unique(self):
        field = self.Lead._fields["pmk_number"]
        self.assertTrue(field.readonly)
        self.assertFalse(field.copy)
        self.assertTrue(self.Lead._fields["pmk_number_date"].readonly)
        self.assertFalse(self.Lead._fields["pmk_number_date"].copy)
        first, second = self._deal(), self._deal()
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                second.write({"pmk_number": first.pmk_number})
                second.flush_recordset(["pmk_number"])
        self.env.invalidate_all()

    def test_sequence_record(self):
        seq = self.env.ref("pmk_deal.seq_deal")
        self.assertEqual(seq.code, SEQUENCE_CODE)
        self.assertEqual(seq.prefix, "СД-")
        self.assertEqual(seq.padding, 5)
        self.assertFalse(seq.company_id)
        data = self.env["ir.model.data"].search([
            ("module", "=", "pmk_deal"), ("name", "=", "seq_deal")])
        self.assertTrue(data.noupdate, "Иначе обновление модуля сбросит счётчик.")

    def test_label_helper(self):
        self.assertEqual(number_label("СД-00001", date(2026, 9, 27)), "СД-00001 от 27.09.2026")
        self.assertEqual(number_label("СД-00001", False), "СД-00001")
        self.assertEqual(number_label(False, date(2026, 9, 27)), "")

    # ─── Миграция: только активные сделки ────────────────────────────────
    def test_migration_numbers_only_active_deals(self):
        a = self._deal(name="Сделка А")
        b = self._deal(name="Сделка Б")
        archived = self._deal(name="Архивная В")
        archived.action_archive()
        lead = self._lead(name="Лид Г")
        records = a | b | archived | lead
        self.env.flush_all()
        # Как на боевой до миграции: номеров нет, даты превращения — свои.
        self.env.cr.execute(
            "UPDATE crm_lead SET pmk_number = NULL, pmk_number_date = NULL WHERE id IN %s",
            [tuple(records.ids)])
        self.env.cr.execute("UPDATE crm_lead SET date_conversion = %s WHERE id = %s",
                            [datetime(2026, 10, 2, 22, 55, 32), b.id])
        self.env.cr.execute("UPDATE crm_lead SET date_conversion = %s WHERE id = %s",
                            [datetime(2026, 9, 27, 10, 27, 57), a.id])
        records.invalidate_recordset()
        # Окружение миграции: __system__, контекст пустой — пояса нет.
        env = api.Environment(self.env.cr, SUPERUSER_ID, {})
        self.assertGreaterEqual(number_active_deals(env), 2)
        records.invalidate_recordset()
        self.assertRegex(a.pmk_number or "", NUMBER)
        self.assertRegex(b.pmk_number or "", NUMBER)
        self.assertLess(a.pmk_number, b.pmk_number, "Порядок — по дню превращения.")
        self.assertEqual(a.pmk_number_date, date(2026, 9, 27))
        self.assertEqual(b.pmk_number_date, date(2026, 10, 3),
                         "Пояс менеджера, а не UTC: 22:55 UTC 02.10 = 03.10 во Владивостоке.")
        self.assertFalse(archived.pmk_number, "Архивные — без номера (решение Антона).")
        self.assertFalse(lead.pmk_number, "Лидам номер не нужен.")
        before = (a.pmk_number, b.pmk_number)
        self.assertEqual(number_active_deals(env), 0, "Повторный запуск ничего не меняет.")
        records.invalidate_recordset()
        self.assertEqual((a.pmk_number, b.pmk_number), before)

    def test_migration_script_present(self):
        path = file_path("pmk_deal/migrations/19.0.1.0.7/post-migrate.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("number_active_deals", source)
        from odoo.modules.module import get_manifest
        self.assertEqual(get_manifest("pmk_deal")["version"], "19.0.1.0.7")

    # ─── Имя и поиск ────────────────────────────────────────────────────
    def test_display_name_unchanged(self):
        """Тему письма почта берёт из display_name — номера в нём нет."""
        deal = self._deal(name="Запрос стоимости изготовления МК")
        self.assertTrue(deal.pmk_number)
        self.assertIn("Запрос стоимости изготовления МК", deal.display_name)
        self.assertNotIn(deal.pmk_number, deal.display_name)
        self.assertNotIn("СД-", deal.name)

    def test_name_search_by_number(self):
        deal = self._deal(name="Запрос без номера в теме")
        found = dict(self.Lead.name_search(deal.pmk_number))
        self.assertIn(deal.id, found, "Поле «Сделка» расчёта находит по «СД-…».")
        self.assertIn(deal.id, self.Lead.search([("pmk_number", "ilike", deal.pmk_number)]).ids)


@tagged("post_install", "-at_install")
class TestDealHeadViewsStep48(TransactionCase):

    def _arch(self, view_type, view_xmlid=None, model="crm.lead"):
        view_id = self.env.ref(view_xmlid).id if view_xmlid else False
        views = self.env[model].get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def test_views_active(self):
        for xmlid in ("pmk_deal.view_crm_lead_form_step48",
                      "pmk_deal.view_crm_lead_list_step48",
                      "pmk_deal.view_crm_lead_kanban_step48",
                      "pmk_deal.view_crm_opportunities_search_step48"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_form_without_new_keeps_duplicate(self):
        """«Новое» убирает свой контроллер (canCreate=false), не create="0":
        тот унёс бы «Дублировать» в ⚙."""
        form = self._arch("form", "crm.crm_lead_view_form")
        self.assertEqual(form.get("js_class"), "pmk_crm_form")
        self.assertIsNone(form.get("create"))
        self.assertIsNone(form.get("duplicate"))
        self.assertIn("o_lead_opportunity_form", (form.get("class") or "").split())
        label = form.find(".//sheet//field[@name='pmk_number_label']")
        self.assertIsNotNone(label, "Подпись строки пути — в данных записи.")
        self.assertIn(label.get("invisible"), ("1", "True"))
        # Шапка осталась в разметке — наследники и тесты ищут кнопки в ней.
        self.assertIsNotNone(form.find("header/button[@name='action_set_won_rainbowman']"))

    def test_create_stays_in_pipeline_and_lists(self):
        pipeline = self._arch("kanban", "crm.crm_case_kanban_view_leads")
        self.assertNotIn(pipeline.get("create"), ("0", "false", "False"))
        self.assertEqual(pipeline.get("on_create"), "quick_create", "Плюсики в колонках воронки.")
        for xmlid in ("crm.crm_case_tree_view_oppor", "crm.crm_case_tree_view_leads"):
            with self.subTest(list=xmlid):
                self.assertNotIn(self._arch("list", xmlid).get("create"), ("0", "false", "False"))
        for xmlid in ("crm.crm_lead_action_pipeline", "crm.crm_lead_all_leads"):
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if not action:
                continue
            with self.subTest(action=xmlid):
                context = action.context or ""
                self.assertNotRegex(context.replace(" ", ""), r"['\"]create['\"]:(False|0)",
                                    "create: False в действии убрал бы «Новое» и в воронке.")

    def test_list_number_column(self):
        arch = self._arch("list", "crm.crm_case_tree_view_oppor")
        names = [f.get("name") for f in arch.iter("field") if f.get("column_invisible") not in ("1", "True")]
        self.assertIn("pmk_number", names)
        self.assertLess(names.index("pmk_number"), names.index("name"), "«Номер» — перед названием.")
        column = arch.find(".//field[@name='pmk_number']")
        self.assertEqual(column.get("string"), "Номер")
        self.assertEqual(column.get("width"), "105px", "Как у СМ-: номер не обрезается.")

    def test_kanban_number_small(self):
        arch = self._arch("kanban", "crm.crm_case_kanban_view_leads")
        number = arch.find(".//footer//field[@name='pmk_number']")
        self.assertIsNotNone(number)
        classes = (number.get("class") or "").split()
        self.assertIn("small", classes)
        self.assertIn("text-muted", classes)
        self.assertEqual(number.get("invisible"), "not pmk_number")

    def test_search_by_number(self):
        arch = self._arch("search", "crm.view_crm_case_opportunities_filter")
        name = arch.find(".//field[@name='name']")
        domain = name.get("filter_domain") or ""
        for fname in ("partner_id", "partner_name", "email_from", "name", "contact_name", "pmk_number"):
            with self.subTest(field=fname):
                self.assertIn("'%s'" % fname, domain)
        self.assertEqual(domain.count("'|'"), 5, "Шесть условий через ИЛИ.")
        self.assertIsNotNone(arch.find(".//field[@name='pmk_number']"))

    def test_assets_after_crm_form(self):
        from odoo.modules.module import get_manifest
        assets = get_manifest("pmk_deal")["assets"]["web.assets_backend"]
        rules = "pmk_deal/static/src/js/deal_head_rules.js"
        view = "pmk_deal/static/src/js/deal_form_view.js"
        self.assertIn(rules, assets)
        self.assertIn(view, assets)
        self.assertLess(assets.index(rules), assets.index(view))
        files = [f["url"] for f in self.env["ir.qweb"]._get_asset_content("web.assets_backend")[0]]
        crm_form = next(i for i, url in enumerate(files) if url.endswith("crm/static/src/views/crm_form/crm_form.js"))
        ours = next(i for i, url in enumerate(files) if url.endswith(view))
        self.assertLess(crm_form, ours, "crm_form зарегистрирован раньше нашего вида.")
        with open(file_path(view), encoding="utf-8") as f:
            source = f.read()
        self.assertIn('import "@crm/views/crm_form/crm_form";', source)
        self.assertIn('views.get("crm_form")', source)
        self.assertIn("this.canCreate = false", source)
        self.assertIn('views.add("pmk_crm_form"', source)
        self.assertNotRegex(source, r"static\s+components\s*=",
                            "Компоненты — от FormController (кнопки шапки темы pmk_theme).")


@tagged("post_install", "-at_install")
class TestDealCrumbsReload(HttpCase):
    """Строка пути после перезагрузки страницы (F5) — controllers/breadcrumbs.py.

    Прежние звенья пути браузер восстанавливает запросом
    /web/action/load_breadcrumbs: у звена-сделки с номером — «СД-… от …»,
    как до перезагрузки; лид, сделка без номера, чужие записи — как в ядре.
    """

    def test_reload_keeps_deal_number(self):
        password = "pmk48-crumbs-pass"
        user = new_test_user(
            self.env, login="pmk48_crumbs", password=password, tz=TZ,
            groups="base.group_user,sales_team.group_sale_salesman_all_leads")
        Lead = self.env["crm.lead"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True, tracking_disable=True)
        subject = "Запрос стоимости изготовления МК п. Горный (шаг 48)"
        deal = Lead.create({"name": subject, "type": "opportunity", "user_id": user.id})
        lead = Lead.create({"name": "Заявка с почты (шаг 48)", "type": "lead",
                            "user_id": user.id})
        unnumbered = Lead.create({"name": "Архивная без номера (шаг 48)",
                                  "type": "opportunity", "user_id": user.id,
                                  "active": False})
        self.assertTrue(deal.pmk_number_label)
        self.assertFalse(unnumbered.pmk_number)
        pipeline = self.env.ref("crm.crm_lead_action_pipeline")
        partner = self.env["res.partner"].create({"name": "ООО Ромашка (шаг 48)"})
        self.env.flush_all()

        self.authenticate(user.login, password)
        result = self.make_jsonrpc_request("/web/action/load_breadcrumbs", {"actions": [
            {"action": pipeline.id},
            {"action": pipeline.id, "resId": deal.id},
            {"action": "crm.crm_lead_action_pipeline", "resId": deal.id},
            {"model": "crm.lead", "resId": deal.id},
            {"model": "crm.lead", "resId": lead.id},
            {"action": pipeline.id, "resId": unnumbered.id},
            {"action": pipeline.id, "resId": "new"},
            {"model": "res.partner", "resId": partner.id},
        ]})
        self.assertEqual(len(result), 8, "Ответ — по звену на действие, как в ядре.")
        names = [item.get("display_name") for item in result]
        self.assertTrue(names[0], "Звено списка — имя действия, как в ядре.")
        self.assertNotIn("СД-", names[0])
        for index in (1, 2, 3):
            with self.subTest(crumb=index):
                self.assertEqual(names[index], deal.pmk_number_label)
        self.assertEqual(names[4], lead.display_name, "Лиду номер не нужен — тема.")
        self.assertEqual(names[5], unnumbered.display_name, "Без номера — тема, как в ядре.")
        self.assertTrue(names[6], "Новая запись — «Новое», как в ядре.")
        self.assertNotIn("СД-", names[6])
        self.assertEqual(names[7], partner.display_name, "Чужие записи не тронуты.")
        self.assertEqual(deal.display_name, subject,
                         "Имя сделки прежнее: тема писем и поле «Сделка» расчёта.")
