# -*- coding: utf-8 -*-
"""Планировщик «Заказы в работе» (разбор UX, шаг З-2, 08.10.2026), pmk_orders.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные —
клиентов из Excel-планировщика Антона здесь нет.

Что ловим:
  • проект и семь этапов по порядку, свёрнут только «Отгружено», смысл
    этапов; этапы «Доработки» к проекту не привязаны;
  • % оплаты: сумма оплаты от суммы заказа, сумма 0 — 0 %, хранится;
  • сумма строки идёт за счётом (и за его редакцией), без счёта — руками и
    не затирается;
  • «просрочена сдача» — вычисляется и ищется фильтром; отгружено — нет;
  • колонки списка — в порядке Excel; канбан по этапам; форма без вкладок,
    этап в строке пути, без залитых кнопок; строка открывается своей
    формой отовсюду (get_formview_id), задача «Доработки» — штатной;
    карточка проекта открывает планировщик;
  • меню: «Продажи → Заказы в работе» сразу за «Воронкой», «Проекты →
    Заказы в работе» первым;
  • загрузка (импорт Excel, карточка 3) метками: «Нал», «Да», «Получен»;
  • стили — разделом в живом файле темы, с тёмной парой.

Глазами (список, канбан на 1440 и на широком, форма, светлая и тёмная
тема) — основной агент на копии.
"""
import datetime

from lxml import etree

from odoo.tests import tagged
from odoo.tools.misc import file_open

from .test_step_z2_invoice import Z2Common

D = datetime.date

EXCEL_COLUMNS = [
    "partner_id", "name", "pmk_deal_number", "pmk_date_start", "pmk_date_due", "stage_id",
    "user_ids", "pmk_amount", "pmk_sale_order_id", "pmk_org_id", "pmk_invoice", "pmk_paid_date",
    "pmk_paid_amount", "pmk_paid_pct", "pmk_ready_date", "pmk_ship_date", "pmk_note",
    "pmk_ordered", "pmk_paint", "pmk_passport", "pmk_metal",
]


@tagged("post_install", "-at_install")
class TestStepZ2Planner(Z2Common):

    def _row(self, **values):
        vals = {"name": "Площадка обслуживания (шаг З-2)", "project_id": self.project.id,
                "stage_id": self.queue.id, "partner_id": self.client.id}
        vals.update(values)
        return self.env["project.task"].with_context(mail_create_nolog=True).create(vals)

    def _arch(self, view, view_type):
        res = self.env["project.task"].with_user(self.manager).get_views(
            [(self.env.ref(view).id, view_type)])
        return etree.fromstring(res["views"][view_type]["arch"])

    # ─── Проект и этапы ─────────────────────────────────────────────────
    def test_project_and_stages(self):
        self.assertTrue(self.project.pmk_is_orders)
        self.assertEqual(self.project.privacy_visibility, "employees")
        stages = self.project.type_ids.sorted("sequence")
        self.assertEqual(stages.mapped("name"), [
            "Очередь", "Разработка чертежей", "Ждём металл", "В работе", "Пауза",
            "Готово к отгрузке", "Отгружено"])
        self.assertEqual(stages.mapped("pmk_order_stage"),
                         ["queue", "drawings", "metal", "work", "pause", "ready", "shipped"])
        self.assertEqual(stages.filtered("fold").mapped("name"), ["Отгружено"])
        dev = self.env.ref("pmk_theme.project_dev", raise_if_not_found=False)
        if dev:
            self.assertFalse(dev.type_ids & stages, "Этапы «Доработки» — отдельно.")

    # ─── Деньги ─────────────────────────────────────────────────────────
    def test_paid_pct(self):
        row = self._row(pmk_amount=1000.0, pmk_paid_amount=700.0)
        self.assertAlmostEqual(row.pmk_paid_pct, 70.0)
        row.pmk_amount = 0.0
        self.assertAlmostEqual(row.pmk_paid_pct, 0.0, msg="Сумма 0 — 0 %.")
        row.write({"pmk_amount": 2000.0, "pmk_paid_amount": 2000.0})
        self.assertAlmostEqual(row.pmk_paid_pct, 100.0)
        self.assertTrue(self.env["project.task"]._fields["pmk_paid_pct"].store)

    def test_amount_follows_invoice_manual_kept(self):
        deal = self._deal()
        spec = self._spec(deal)
        deal.write({"stage_id": self.stage_kp.id})
        invoice = self._invoices(deal)
        row = self._row(pmk_sale_order_id=invoice.id)
        self.assertAlmostEqual(row.pmk_amount, invoice.amount_total)
        self.assertEqual(row.pmk_org_id, self.org_vat)
        spec.product_ids.filtered("price_customer_unit")[:1].price_customer_unit = 5000.0
        spec._pmk_kp_move_stage(deal)
        self.assertEqual(invoice.pmk_revision, 2)
        self.assertAlmostEqual(row.pmk_amount, invoice.amount_total, msg="Сумма — за редакцией счёта.")
        manual = self._row(pmk_amount=123456.0)
        manual.write({"name": "Импорт из Excel (шаг З-2)", "pmk_paid_amount": 1000.0})
        self.assertAlmostEqual(manual.pmk_amount, 123456.0, msg="Без счёта сумма руками не затирается.")

    # ─── Просрочка ──────────────────────────────────────────────────────
    def test_overdue(self):
        yesterday = D.today() - datetime.timedelta(days=1)
        work = self.env.ref("pmk_orders.orders_stage_work")
        shipped = self.env.ref("pmk_orders.orders_stage_shipped")
        late = self._row(pmk_date_due=yesterday, stage_id=work.id)
        sent = self._row(pmk_date_due=yesterday, stage_id=shipped.id)
        handed = self._row(pmk_date_due=yesterday, stage_id=work.id, pmk_ship_date=yesterday)
        future = self._row(pmk_date_due=D.today() + datetime.timedelta(days=3), stage_id=work.id)
        self.assertTrue(late.pmk_overdue)
        self.assertFalse(sent.pmk_overdue, "Отгружено — не просрочено.")
        self.assertFalse(handed.pmk_overdue, "Есть дата отгрузки — не просрочено.")
        self.assertFalse(future.pmk_overdue)
        Task = self.env["project.task"]
        mine = late | sent | handed | future
        self.assertEqual(Task.search([("pmk_overdue", "=", True), ("id", "in", mine.ids)]), late)
        self.assertEqual(Task.search([("pmk_overdue", "=", False), ("id", "in", mine.ids)]),
                         sent | handed | future)

    # ─── Виды ───────────────────────────────────────────────────────────
    def test_views_open_and_columns(self):
        for xmlid in ("pmk_orders.view_task_order_list", "pmk_orders.view_task_order_kanban",
                      "pmk_orders.view_task_order_form", "pmk_orders.view_task_order_search",
                      "pmk_orders.view_task_order_quick_create"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)
        listing = self._arch("pmk_orders.view_task_order_list", "list")
        columns = [f.get("name") for f in listing.iter("field")
                   if f.get("column_invisible") not in ("1", "True")
                   and f.get("invisible") not in ("1", "True")]
        # Шаг З-5 (pmk_tech, если стоит): «Металл получен» — сразу за «Металлом».
        extra = (["pmk_metal_date"] if "pmk_metal_date" in self.env["project.task"]._fields
                 else [])
        self.assertEqual(columns, EXCEL_COLUMNS + extra, "Колонки — в порядке Excel.")
        hidden = {f.get("name") for f in listing.iter("field") if f.get("optional") == "hide"}
        self.assertEqual(hidden, {"pmk_org_id", "pmk_ready_date", "pmk_ship_date", "pmk_note",
                                  "pmk_ordered", "pmk_paint", "pmk_passport"},
                         "Редкие колонки — в ⚙, обратимо.")
        stage = listing.xpath("//field[@name='stage_id']")[0]
        self.assertEqual(stage.get("widget"), "badge", "Этап — плашкой.")
        amount = listing.xpath("//field[@name='pmk_amount']")[0]
        self.assertEqual(amount.get("readonly"), "pmk_sale_order_id",
                         "Со счётом сумма — из счёта и в списке (multi_edit), как в форме.")
        kanban = self._arch("pmk_orders.view_task_order_kanban", "kanban")
        self.assertEqual(kanban.get("default_group_by"), "stage_id")
        self.assertIn("o_pmk_orders_kanban", kanban.get("class"))
        card = etree.tostring(kanban, encoding="unicode")
        self.assertIn("просрочена", card, "Цвет «просрочена» повторён словом.")
        form = self._arch("pmk_orders.view_task_order_form", "form")
        self.assertIn("o_pmk_header_up", form.get("class"))
        self.assertIsNone(form.find(".//notebook"), "Без вкладок.")
        # Шаг З-4 (pmk_tech, если стоит): следующий шаг строки — «Технический
        # расчёт» / «Заявка на металл», залитые по одной на состояние.
        filled = {b.get("name") for b in form.xpath(
            "//button[contains(@class, 'oe_highlight') or contains(@class, 'btn-primary')]")}
        self.assertLessEqual(filled, {"action_pmk_tech_spec", "action_pmk_metal_request"},
                             "Своих залитых у строки нет — только шаг З-4.")
        self.assertEqual(form.xpath("//header/field[@name='stage_id']")[0].get("widget"), "statusbar")
        search = self._arch("pmk_orders.view_task_order_search", "search")
        self.assertLessEqual({"not_shipped", "my", "overdue", "metal_wait", "pause", "not_paid"},
                             {f.get("name") for f in search.iter("filter")})

    def test_action_and_formview(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("pmk_orders.action_orders")
        self.assertEqual(action["res_model"], "project.task")
        self.assertEqual(action["views"][0][1], "list", "Список первым — как Excel.")
        context = str(action["context"])
        for key in ("project_kanban", "search_default_not_shipped", "default_project_id"):
            self.assertIn(key, context)
        row = self._row()
        self.assertEqual(row.get_formview_id(), self.env.ref("pmk_orders.view_task_order_form").id)
        dev = self.env.ref("pmk_theme.project_dev", raise_if_not_found=False)
        if dev:
            task = self.env["project.task"].create({"name": "Доработка (шаг З-2)", "project_id": dev.id})
            self.assertNotEqual(task.get_formview_id(), self.env.ref("pmk_orders.view_task_order_form").id)
            self.assertNotEqual(dev.action_view_tasks().get("xml_id"), "pmk_orders.action_orders")
        opened = self.project.action_view_tasks()
        self.assertEqual(opened["res_model"], "project.task")
        self.assertEqual(opened["display_name"], self.project.name)
        self.assertEqual(opened["views"][0][0], self.env.ref("pmk_orders.view_task_order_list").id)

    def test_fields_only_in_planner_views(self):
        """Штатные виды задачи наших полей не показывают — «Доработке» и
        «Списку дел» они не мешают."""
        for xmlid, view_type in (("project.view_task_form2", "form"),
                                 ("project.view_task_tree2", "list"),
                                 ("project.view_task_kanban", "kanban")):
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if not view:
                continue
            with self.subTest(view=xmlid):
                arch = self._arch(xmlid, view_type)
                self.assertFalse(arch.xpath("//field[@name='pmk_amount']"))

    # ─── Меню ───────────────────────────────────────────────────────────
    def test_menus(self):
        action = self.env.ref("pmk_orders.action_orders")
        menus = self.env["ir.ui.menu"].with_user(self.manager).load_web_menus(False)
        sales = self.env.ref("pmk_theme.menu_pmk_sales").id
        names = [menus[mid]["name"] for mid in menus[sales]["children"]]
        self.assertEqual(names[:2], ["Воронка сделок", "Заказы в работе"])
        ours = self.env.ref("pmk_orders.menu_orders_sales")
        self.assertEqual(menus[ours.id]["actionID"], action.id)
        tasks = self.env.ref("pmk_theme.menu_pmk_tasks")
        first = tasks.child_id.sorted("sequence")[:1]
        self.assertEqual(first, self.env.ref("pmk_orders.menu_orders_tasks"))
        self.assertEqual(first.action, action)

    # ─── Импорт (карточка 3) ────────────────────────────────────────────
    def test_import_shape(self):
        pause = self.env.ref("pmk_orders.orders_stage_pause")
        result = self.env["project.task"].load(
            ["name", "project_id/.id", "stage_id/.id", "pmk_invoice", "pmk_ordered", "pmk_metal",
             "pmk_passport", "pmk_date_due", "pmk_amount", "pmk_paid_amount", "pmk_paint"],
            [["Ограждение (импорт, шаг З-2)", str(self.project.id), str(pause.id), "Нал", "Да",
              "Получен", "True", "2026-10-21", "100000", "25000", "RAL 7024"]])
        self.assertFalse([m for m in result["messages"] if m.get("type") == "error"], result["messages"])
        row = self.env["project.task"].browse(result["ids"])
        self.assertEqual(row.stage_id, pause)
        self.assertEqual((row.pmk_invoice, row.pmk_ordered, row.pmk_metal, row.pmk_passport),
                         ("Нал", "yes", "got", True))
        self.assertEqual(row.pmk_date_due, D(2026, 10, 21))
        self.assertAlmostEqual(row.pmk_paid_pct, 25.0)
        self.assertEqual(row.pmk_paint, "RAL 7024")

    # ─── Стили ──────────────────────────────────────────────────────────
    def test_scss_sections(self):
        forms = file_open("pmk_theme/static/src/scss/forms_nexus.scss").read()
        start = forms.index("// ═══ Счета покупателям и планировщик (З-2")
        section = forms[start:]
        for needle in (".o_pmk_orders_kanban .o_kanban_renderer", "--KanbanRecord--small-width",
                       ".o_pmk_overdue", ".o_pmk_revision_banner",
                       '.oe_title h1:has(.o_field_widget[name="pmk_revision_label"])'):
            self.assertIn(needle, section)
        # Класс arch канбана ядро вешает на корень вида, рендерер — потомок:
        # правило на одном элементе (доводка З-2) не срабатывало.
        self.assertNotIn(".o_kanban_renderer.o_pmk_orders_kanban", section)
        dark = file_open("pmk_theme/static/src/scss/dark.scss").read()
        start = dark.index("// ═══ Счета покупателям и планировщик (З-2)")
        section = dark[start:]
        self.assertIn("body.o_nexus_dark .o_pmk_orders_kanban .o_pmk_overdue", section)
        self.assertIn("body.o_nexus_dark .o_form_view .o_pmk_revision_banner", section)
