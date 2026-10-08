# -*- coding: utf-8 -*-
"""«Материал пришёл» (разбор UX, шаг З-5), pmk_tech.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные —
фикстура шага З-4 (Z4Common): после «Заявки на металл» два черновика —
поставщик (уголок, лист, болт) и «Поставщик не выбран» (уголок 200×20 без
цены).

Что ловим:
  • подтверждённый заказ → «Материал пришёл»: дата прихода — сегодня,
    состояние заявки «Материал пришёл», заметки в ленте заказа и строки
    планировщика; цены строк при подтверждении не съехали (₽/т × вес);
  • отправленный → кнопка сама подтверждает заказ, ставит дату; на
    согласовании — только дата; черновик и отменённый — пропуск словами;
  • планировщик: пришла часть заявок — «Получен частично» (черновик
    «Поставщик не выбран» с позициями — ещё не заказан); все — «Получен»;
    отменённая не считается; дата — самая поздняя; этап «Ждём металл» сам
    не двигается; повтор «Заявки на металл» после прихода «Получен» не
    сбивает; правка даты руками — в строке; «Снять «Материал пришёл»» —
    назад; «Отменить» → «В черновик» снимает отметку (черновик ещё не
    заказан), повторное подтверждение старую дату не возвращает; из
    технического расчёта убрали весь металл — «Металл» строки всё равно
    пересчитан по оставшимся заявкам;
  • уведомление списка называет заказы, которые кнопка подтвердила;
  • склад: «Поступление» не проведено, движений «Выполнено» нет, принято 0;
  • прайс заявкой не пополняется (строка поставщика с ценой заказа не
    заводится); обычная закупка — как в ядре;
  • права: снабженец только с «Закупками» (без «Проектов» и «Склада») —
    всё работает, строка планировщика обновляется;
  • заказ без сделки и строки — дата ставится, ничего не падает;
  • писем нет;
  • виды: залитая «Материал пришёл» одна (подтверждённый), «Получить» без
    заливки, кнопка в шапке списка «Заявки на металл», колонка и фильтры;
    в планировщике — «Металл получен» (дата), «Получен частично», фильтры
    «Ждём металл» (без «Получен») и «Металл получен», в канбане дата
    отдельной строкой, ряд метки переносится.

Глазами (заказ поставщику во всех состояниях, список «Заявки на металл»,
строка и список «Заказов в работе», канбан, светлая и тёмная тема) —
основной агент на копии.
"""
import datetime

from lxml import etree

from odoo import Command, fields
from odoo.tests import new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from .test_step_z4 import Z4Common, _filled


@tagged("post_install", "-at_install")
class TestStepZ5(Z4Common):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.buyer = new_test_user(
            cls.env, login="pmkz5_buyer", name="Снабженец (шаг З-5)",
            groups="base.group_user,purchase.group_purchase_user")
        cls.today = fields.Date.context_today(cls.env["purchase.order"])

    # ─── помощники ──────────────────────────────────────────────────────
    def _ordered(self):
        """Счёт → технический → заявка: (строка планировщика, заявка
        поставщику, черновик «Поставщик не выбран», технический)."""
        _deal, _spec, order, row = self._flow()
        tech = self._tech(order)
        self._request(tech)
        orders = self._requests(tech)
        po = orders.filtered(lambda o: o.partner_id == self.supplier)
        empty = orders.filtered(lambda o: o.partner_id == self.placeholder)
        self.assertEqual((len(po), len(empty)), (1, 1), "Посылка: два черновика.")
        self.assertEqual(row.stage_id, self.metal_stage, "Посылка: «Ждём металл».")
        return row, po, empty, tech

    def _arrive(self, orders, user=None):
        return orders.with_user(user or self.buyer).action_pmk_material_arrived()

    def _notes(self, record):
        record.invalidate_recordset(["message_ids"])
        return " ".join(str(m.body) for m in record.sudo().message_ids)

    def _no_stock(self, po):
        po.invalidate_recordset()
        self.assertFalse(po.picking_ids.filtered(lambda p: p.state == "done"),
                         "«Поступление» не проведено.")
        self.assertFalse(self.env["stock.move"].search_count([
            ("purchase_line_id", "in", po.order_line.ids), ("state", "=", "done")]),
            "Движений «Выполнено» нет.")
        self.assertEqual(set(po.order_line.mapped("qty_received")), {0.0}, "Принято — 0.")

    # ─── Подтверждённый заказ ───────────────────────────────────────────
    def test_confirmed_order_arrived(self):
        row, po, empty, _tech = self._ordered()
        prices = {line.product_id.product_tmpl_id.name: line.price_unit for line in po.order_line}
        mails = self.env["mail.mail"].sudo().search_count([])
        po.with_user(self.buyer).write({"date_planned": fields.Datetime.now()
                                        + datetime.timedelta(days=5)})
        po.with_user(self.buyer).button_confirm()
        self.assertEqual(po.state, "purchase")
        self.assertEqual(
            {line.product_id.product_tmpl_id.name: line.price_unit for line in po.order_line},
            prices, "Подтверждение цены строк не пересчитало (₽/т × вес — из заявки).")
        self.assertAlmostEqual(self._line(po, "Лист 2 мм (тест З-4)").price_unit, 14130.0, places=2)
        self.assertEqual(po.pmk_request_state_label, "Заказ подтверждён")

        self.assertTrue(self._arrive(po))
        self.assertEqual(po.pmk_metal_date, self.today, "Дата прихода — сегодня.")
        self.assertEqual(po.state, "purchase")
        self.assertEqual(po.pmk_request_state_label, "Материал пришёл")
        self.assertIn("Материал пришёл", self._notes(po))
        self.assertIn("на склад не проводили", self._notes(po))
        self._no_stock(po)

        self.assertEqual(row.pmk_metal, "part",
                         "Черновик «Поставщик не выбран» с позициями — ещё не заказан.")
        self.assertEqual(row.pmk_metal_date, self.today)
        self.assertEqual(row.stage_id, self.metal_stage, "Этап сам не двигается — решает планировщик.")
        notes = self._notes(row)
        self.assertIn("Материал пришёл по заявке %s" % po.name, notes)
        self.assertIn("1 из 2", notes)

        # Отменённая заявка не считается: пришли все действующие.
        empty.button_cancel()
        self.assertEqual(row.pmk_metal, "got", "Отменили «Поставщик не выбран» — «Получен».")
        self.assertEqual(row.stage_id, self.metal_stage)
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails, "Писем нет.")

    def test_all_arrived_got_and_repeat_keeps(self):
        row, po, empty, tech = self._ordered()
        empty.write({"partner_id": self.supplier.id})
        self.assertFalse(self.bare_tmpl.seller_ids, "Посылка: уголка 200×20 в прайсах нет.")
        (po | empty).with_user(self.buyer).button_confirm()
        self.assertFalse(self.bare_tmpl.seller_ids,
                         "Подтверждённая заявка прайс не пополняет (цена 0 стала бы самой дешёвой).")
        yesterday = self.today - datetime.timedelta(days=1)
        self._arrive(empty)
        empty.write({"pmk_metal_date": yesterday})
        self.assertEqual(row.pmk_metal, "part")
        self.assertEqual(row.pmk_metal_date, yesterday, "Правка даты руками — в строке.")
        self._arrive(po)
        self.assertEqual(row.pmk_metal, "got", "Пришли все заявки — «Получен».")
        self.assertEqual(row.pmk_metal_date, self.today, "Дата — самая поздняя.")
        self.assertEqual(row.stage_id, self.metal_stage)

        # Повтор «Заявки на металл» без правок: всё заказано и пришло.
        self._request(tech)
        self.assertEqual(row.pmk_metal, "got", "Повтор «Получен» не сбивает.")
        self.assertEqual(self._requests(tech), po | empty, "Новых черновиков нет.")

    def test_plain_purchase_still_feeds_price_list(self):
        """Обычная закупка (не заявка) — как в ядре: новый поставщик в прайсе."""
        tmpl = self.env["product.template"].create({"name": "Краска (тест З-5)"})
        po = self.env["purchase.order"].create({
            "partner_id": self.supplier.id,
            "order_line": [Command.create({"product_id": tmpl.product_variant_id.id,
                                           "product_qty": 2, "price_unit": 300.0})]})
        po.button_confirm()
        self.assertEqual(tmpl.seller_ids.partner_id, self.supplier)
        # И «Материал пришёл» у заказа без сделки и строки — без ошибок.
        self.assertTrue(self._arrive(po))
        self.assertEqual(po.pmk_metal_date, self.today)
        self.assertFalse(po._pmk_arrival_tasks())
        self._no_stock(po)

    # ─── Отправленный, на согласовании, черновик ────────────────────────
    def test_sent_order_confirmed_by_button(self):
        row, po, _empty, _tech = self._ordered()
        po.write({"state": "sent"})        # письмо поставщику — не в тесте
        price = self._line(po, "Уголок 100×8 (тест З-4)").price_unit
        self._arrive(po)
        self.assertIn(po.state, ("purchase", "to approve"), "Заказ подтверждён штатно.")
        self.assertEqual(po.pmk_metal_date, self.today)
        self.assertAlmostEqual(self._line(po, "Уголок 100×8 (тест З-4)").price_unit, price)
        if po.state == "purchase":
            self.assertIn("подтверждён этой кнопкой", self._notes(po))
        else:
            self.assertIn("на согласование", self._notes(po),
                          "Двойное утверждение — слово по тому, что вышло.")
            self.assertNotIn("подтверждён этой кнопкой", self._notes(po))
        if po.state == "purchase":
            self.assertTrue(po.picking_ids, "Посылка: ядро завело «Поступление».")
        self._no_stock(po)
        self.assertEqual(row.pmk_metal, "part")

    def test_to_approve_only_date(self):
        row, po, empty, _tech = self._ordered()
        po.write({"state": "to approve"})
        empty.button_cancel()
        self._arrive(po)
        self.assertEqual(po.state, "to approve", "На согласовании — только дата.")
        self.assertEqual(po.pmk_metal_date, self.today)
        self.assertEqual(row.pmk_metal, "got")

    def test_list_action_skips_drafts(self):
        _row, po, empty, _tech = self._ordered()
        po.button_confirm()
        result = self._arrive(po | empty)
        self.assertEqual(result["tag"], "display_notification")
        message = result["params"]["message"]
        self.assertIn(po.name, message)
        self.assertIn("черновики", message)
        self.assertEqual(po.pmk_metal_date, self.today)
        self.assertFalse(empty.pmk_metal_date, "Черновик ещё не заказан — не отмечаем.")
        # Повтор: уже отмеченный — пропуск, дата не меняется.
        po.write({"pmk_metal_date": self.today - datetime.timedelta(days=2)})
        again = self._arrive(po)
        self.assertIn("уже отмечены", again["params"]["message"])
        self.assertEqual(po.pmk_metal_date, self.today - datetime.timedelta(days=2))

    def test_list_action_names_confirmed(self):
        """В списке отправленный поставщику подтверждается кнопкой — и
        уведомление это называет, а не молчит."""
        _row, po, empty, _tech = self._ordered()
        empty.write({"partner_id": self.supplier.id})
        po.button_confirm()
        empty.write({"state": "sent"})          # письмо поставщику — не в тесте
        result = self._arrive(po | empty)
        message = result["params"]["message"]
        self.assertIn(empty.name, message)
        if empty.state == "purchase":
            self.assertIn("Подтверждены этой кнопкой: %s" % empty.name, message)
        else:
            self.assertIn("на согласование: %s" % empty.name, message)
        self.assertNotIn("Подтверждены этой кнопкой: %s" % po.name, message,
                         "Подтверждённый раньше — не «подтверждён кнопкой».")

    # ─── Снять отметку ──────────────────────────────────────────────────
    def test_undo(self):
        row, po, empty, _tech = self._ordered()
        empty.button_cancel()
        po.button_confirm()
        self._arrive(po)
        self.assertEqual(row.pmk_metal, "got")
        po.with_user(self.buyer).action_pmk_material_undo()
        self.assertFalse(po.pmk_metal_date)
        self.assertEqual(po.state, "purchase", "Заказ остаётся подтверждённым.")
        self.assertEqual(po.pmk_request_state_label, "Заказ подтверждён")
        self.assertEqual(row.pmk_metal, "wait")
        self.assertFalse(row.pmk_metal_date)
        self.assertIn("снята", self._notes(po))
        self.assertIn("снята", self._notes(row))
        self._no_stock(po)
        # Отметить снова можно.
        self._arrive(po)
        self.assertEqual(row.pmk_metal, "got")

    # ─── Отменить → В черновик ──────────────────────────────────────────
    def test_cancel_then_draft_clears_arrival(self):
        """Снабженец отменил заказ, чтобы поправить поставщика или
        количество, и вернул в черновик: отметка снимается (черновик ещё не
        заказан), в строке — снова «Ждём»; после повторного подтверждения
        старая дата не возвращается."""
        row, po, empty, _tech = self._ordered()
        empty.button_cancel()
        po.button_confirm()
        self._arrive(po)
        self.assertEqual(row.pmk_metal, "got")

        po.with_user(self.buyer).button_cancel()
        self.assertEqual(po.state, "cancel")
        self.assertEqual(po.pmk_request_state_label, "Отменена")
        self.assertFalse(po.search_count([("id", "=", po.id)] + self._arrived_filter()),
                         "Отменённая — не в фильтре «Материал пришёл».")

        po.with_user(self.buyer).button_draft()
        self.assertEqual(po.state, "draft")
        self.assertFalse(po.pmk_metal_date, "Вернули в черновик — отметка снята.")
        self.assertEqual(po.pmk_request_state_label, "Черновик заявки")
        self.assertIn("вернули в черновик", self._notes(po))
        self.assertEqual(row.pmk_metal, "wait", "Черновик с позициями — ещё не заказан.")
        self.assertFalse(row.pmk_metal_date)
        self.assertFalse(po.search_count([("id", "=", po.id)] + self._arrived_filter()))

        po.with_user(self.buyer).button_confirm()
        self.assertFalse(po.pmk_metal_date, "Повторное подтверждение — без старой даты.")
        self.assertEqual(row.pmk_metal, "wait")
        self.assertEqual(po.pmk_request_state_label, "Заказ подтверждён")

    def _arrived_filter(self):
        search = etree.fromstring(self.env["purchase.order"].get_views(
            [(self.env.ref("pmk_tech.view_metal_request_search").id, "search")]
        )["views"]["search"]["arch"])
        node = search.xpath("//filter[@name='pmk_metal_arrived']")[0]
        return safe_eval(node.get("domain"))

    # ─── Металл из технического расчёта убрали ──────────────────────────
    def test_all_metal_removed_recounts_row(self):
        """Заявка A пришла, черновик «Поставщик не выбран» с позициями —
        «Получен частично». Инженер убрал весь металл и повторил «Заявку на
        металл»: черновик опустел и отменён — «Металл» строки пересчитан
        по оставшейся A: «Получен»."""
        row, po, empty, tech = self._ordered()
        po.button_confirm()
        self._arrive(po)
        self.assertEqual(row.pmk_metal, "part")
        tech.product_ids.line_ids.unlink()   # количество изделия 0 запрещено — убираем детали
        self._request(tech)
        self.assertEqual(empty.state, "cancel", "Посылка: черновик опустел и отменён.")
        self.assertEqual(row.pmk_metal, "got", "Действующая заявка одна — пришла.")
        self.assertEqual(row.pmk_metal_date, self.today)
        self.assertEqual(row.stage_id, self.metal_stage, "Этап не трогаем.")

    # ─── Права ──────────────────────────────────────────────────────────
    def test_buyer_without_projects(self):
        row, po, empty, _tech = self._ordered()
        self.assertFalse(self.buyer.has_group("project.group_project_user"))
        self.assertFalse(self.buyer.has_group("stock.group_stock_user"))
        empty.with_user(self.buyer).button_cancel()
        po.with_user(self.buyer).button_confirm()
        self._arrive(po, user=self.buyer)
        self.assertEqual(po.pmk_metal_date, self.today)
        self.assertEqual(row.pmk_metal, "got", "Строку обновили и без «Проектов».")
        self._no_stock(po)

    def test_manual_row_untouched(self):
        """Строка без заявок (руками, импорт) — «Металл» по заявкам не трогаем."""
        row = self.env["project.task"].create({
            "name": "Импорт (тест З-5)", "project_id": self.project.id,
            "stage_id": self.metal_stage.id, "pmk_metal": "wait"})
        row._pmk_metal_refresh()
        self.assertEqual(row.pmk_metal, "wait")
        self.assertFalse(row.pmk_metal_date)

    # ─── Виды ───────────────────────────────────────────────────────────
    def test_views(self):
        for xmlid in ("pmk_tech.purchase_order_form_pmk_arrival",
                      "pmk_tech.view_metal_request_list_arrival",
                      "pmk_tech.view_metal_request_search_arrival",
                      "pmk_tech.view_task_order_list_pmk_arrival",
                      "pmk_tech.view_task_order_kanban_pmk_arrival",
                      "pmk_tech.view_task_order_form_pmk_arrival",
                      "pmk_tech.view_task_order_search_pmk_arrival"):
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active, "Вид не выключен при загрузке.")

        # Администратором: «Получить» видна только «Складу».
        admin = self.env.ref("base.user_admin")
        po_arch = etree.fromstring(self.env["purchase.order"].with_user(admin).get_views(
            [(self.env.ref("purchase.purchase_order_form").id, "form")])["views"]["form"]["arch"])
        header = po_arch.find(".//header")
        arrived = header.xpath("./button[@name='action_pmk_material_arrived']")
        self.assertEqual(len(arrived), 2, "Залитая (подтверждён) и контурная (отправлен).")
        filled = [b for b in arrived if _filled(b)]
        self.assertEqual(len(filled), 1)
        self.assertIn("state != 'purchase'", filled[0].get("invisible"))
        self.assertIn("pmk_metal_date", filled[0].get("invisible"))
        outline = [b for b in arrived if not _filled(b)][0]
        self.assertIn("'sent'", outline.get("invisible"))
        buttons = [b for b in header if b.tag == "button"]
        self.assertEqual((buttons[0].get("name"), _filled(buttons[0])),
                         ("action_pmk_material_arrived", True), "Залитая — первой в шапке.")
        self.assertTrue(header.xpath("./button[@name='action_pmk_material_undo']"))
        # Залитые у подтверждённого: только наша («Получить» — без заливки).
        confirmed = [b.get("name") for b in header.iter("button") if _filled(b)
                     and "state != 'purchase'" in (b.get("invisible") or "")]
        self.assertEqual(confirmed, ["action_pmk_material_arrived"])
        receive = po_arch.xpath("//header/button[@name='action_view_picking']")
        self.assertTrue(receive, "Посылка: «Получить» в шапке есть.")
        for button in receive:
            self.assertFalse(_filled(button), "«Получить» — без заливки (карточка 6 спрячет).")
        self.assertTrue(po_arch.xpath("//label[@for='pmk_metal_date']"))
        self.assertTrue(po_arch.xpath("//field[@name='pmk_metal_date']"))

        PO = self.env["purchase.order"].with_user(self.buyer)
        listing = etree.fromstring(PO.get_views(
            [(self.env.ref("pmk_tech.view_metal_request_list").id, "list")])["views"]["list"]["arch"])
        self.assertTrue(listing.xpath("//header/button[@name='action_pmk_material_arrived']"),
                        "Кнопка для выбранных — в шапке списка.")
        column = listing.xpath("//field[@name='pmk_metal_date']")[0]
        self.assertEqual(column.get("string"), "Материал пришёл")
        state = listing.xpath("//field[@name='pmk_request_state_label']")[0]
        self.assertFalse(state.get("decoration-bf"),
                         "Жирный метке не передаётся (тема) — различие словом.")
        undo = header.xpath("./button[@name='action_pmk_material_undo']")[0]
        self.assertEqual(undo.get("string"), "Снять «Материал пришёл»",
                         "Кнопка говорит, какую отметку снимает.")
        search = etree.fromstring(PO.get_views(
            [(self.env.ref("pmk_tech.view_metal_request_search").id, "search")])["views"]["search"]["arch"])
        names = {f.get("name") for f in search.iter("filter")}
        self.assertLessEqual({"pmk_metal_wait", "pmk_metal_arrived"}, names)

        Task = self.env["project.task"].with_user(self.manager)
        selection = dict(Task._fields["pmk_metal"].selection)
        self.assertEqual(selection.get("part"), "Получен частично")
        self.assertEqual(selection.get("got"), "Получен")
        task_list = etree.fromstring(Task.get_views(
            [(self.env.ref("pmk_orders.view_task_order_list").id, "list")])["views"]["list"]["arch"])
        fields_order = [f.get("name") for f in task_list.iter("field")]
        self.assertEqual(fields_order[fields_order.index("pmk_metal") + 1], "pmk_metal_date",
                         "«Металл получен» — рядом с «Металлом».")
        self.assertEqual(Task._fields["pmk_metal_date"].string, "Металл получен")
        self.assertEqual(self.env["purchase.order"]._fields["pmk_metal_date"].string,
                         "Материал пришёл")
        task_search = etree.fromstring(Task.get_views(
            [(self.env.ref("pmk_orders.view_task_order_search").id, "search")])["views"]["search"]["arch"])
        wait = task_search.xpath("//filter[@name='metal_wait']")[0]
        self.assertIn("part", wait.get("domain"), "«Ждём металл» — и частично полученные.")
        self.assertIn("('pmk_metal', '!=', 'got')", wait.get("domain"),
                      "Этап «Ждём металл» с «Получен» — не в «Ждём металл».")
        self.assertTrue(task_search.xpath("//filter[@name='metal_got']"))
        task_form = etree.fromstring(Task.get_views(
            [(self.env.ref("pmk_orders.view_task_order_form").id, "form")])["views"]["form"]["arch"])
        self.assertTrue(task_form.xpath("//field[@name='pmk_metal_date']"))
        kanban = etree.fromstring(Task.get_views(
            [(self.env.ref("pmk_orders.view_task_order_kanban").id, "kanban")])["views"]["kanban"]["arch"])
        card = etree.tostring(kanban, encoding="unicode")
        self.assertIn("Металл получен", card)
        metal_row = kanban.xpath("//t[@t-name='card']//div[field[@name='pmk_metal']]")[0]
        self.assertIn("flex-wrap", metal_row.get("class"),
                      "Ряд метки переносится — номер сделки не обрезается.")
        date_line = metal_row.getnext()
        self.assertIsNotNone(date_line)
        self.assertTrue(date_line.xpath("./field[@name='pmk_metal_date']"),
                        "Дата — отдельной строкой под рядом метки.")

    def test_flow_map_label(self):
        if "pmk.flow.builder" not in self.env:
            self.skipTest("pmk_flow не стоит.")
        _row, po, empty, tech = self._ordered()
        po.button_confirm()
        self._arrive(po)
        graph = self.env["pmk.flow.builder"].get_flow_graph("pmk.metal.spec", tech.id)
        nodes = {(n["model"], n["res_id"]): n for n in graph["nodes"]}
        self.assertEqual(nodes[("purchase.order", po.id)]["state"], "Материал пришёл")
