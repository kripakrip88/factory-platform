# -*- coding: utf-8 -*-
"""«Поступления» до учёта и слова закупок (разбор UX, шаг З-6), pmk_tech.

Карточка 6 проекта «Заказ от заявки до цеха»: подтверждённый заказ
поставщику сам заводит «Поступление», а «Подтвердить» в нём проводит приход
— ловушка. Склад не ведём: дороги к «Поступлению» убраны под группы-
выключатели темы (pmk_theme/models/hidden_nodes.py, STEP_Z6_NODES), «Связи»
его не показывают, «Поставка просрочена» считается по «Материал пришёл».

Здесь, а не в pmk_theme: узлы дописывает purchase_stock — от него зависит
pmk_tech, тема — нет; «Материал пришёл» — тоже pmk_tech.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py). Синтетические данные.

Что ловим:
  • снабженец со штатным «Склад: пользователь» (как Владимир), менеджер с
    закупками и admin без групп-выключателей: в заказе поставщику нет
    кнопки-счётчика «Поступления», «Получить», «Статуса получения»,
    колонок строк «Получено» и «Выставленный счёт», в окне строки — тех же
    количеств и вкладки «Счета и поступающие товары», «Статуса выставления
    счетов»; в списке «Подтверждённых заказов» нет «Статуса получения»;
    «Налоги» в строках на месте;
  • «Убранное (показать)» возвращает каждый узел (правило бьёт в
    существующий узел); «Склад (показать)» — только «Поступления», «Деньги
    (показать)» — только счета;
  • форма собирается и правится: заказ заводится, подтверждается, цена
    строки после подтверждения правится (readonly цены ссылается на
    спрятанную колонку — ядро досоздаёт её невидимой);
  • ничего не удаляется и не проводится: подтверждение заводит
    «Поступление», оно не «Выполнено», принято 0; «Материал пришёл»
    работает как раньше и «Поступление» не трогает;
  • «Поставка просрочена» (is_late): подтверждённый заказ с прошедшей
    датой прибытия — просрочен, после «Материал пришёл» — нет;
  • «Связи»: у снабженца узла «Склад» нет и пометки «скрыто правами» за
    него нет; с «Убранным» / «Складом (показать)» — есть;
  • слова: стадии «Заявка» / «Заявка отправлена» / «Отменён» — и теми же
    словами состояние в списке «Заявки на металл» и на «Связях», кнопки
    «Подтвердить заказ», «Отправить заказ поставщику», «Отправить заявку
    поставщику», над номером «Заявка поставщику», отбор «Поставка
    просрочена»; пункты ⚙ — «Заявка поставщику», «Подтвердить заказы»,
    «Объединить заявки».

Глазами (заказ поставщику во всех состояниях, окно строки, ⚙ колонок
списков, «Связи», светлая и тёмная тема) — основной агент на копии.
"""
import datetime

from lxml import etree

from odoo import Command, fields
from odoo.tests import Form, TransactionCase, new_test_user, tagged

from odoo.addons.pmk_tech.models.purchase_order import REQUEST_STATE_LABELS
from odoo.addons.pmk_theme.models.hidden_nodes import HIDDEN_NODES, STEP_Z6_NODES
from odoo.addons.pmk_theme.models.ir_actions_act_window import ACTION_TITLES
from odoo.addons.pmk_theme.models.words import DATA_WORDS, LANG

REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"
MONEY = "pmk_theme.group_pmk_money"
HIDDEN = ("1", "True", "true")
FORM = ("purchase.order", "form")
LIST = ("purchase.order", "list")

RECEIPT_EXPRS = (
    "//button[@name='action_view_picking']",
    "//field[@name='receipt_status'][not(ancestor::field)]",
    "//field[@name='order_line']/list/field[@name='qty_received']",
    "//field[@name='order_line']/form//field[@name='qty_received']",
)
BILL_EXPRS = (
    "//field[@name='order_line']/list/field[@name='qty_invoiced']",
    "//field[@name='order_line']/form//field[@name='qty_invoiced']",
    "//field[@name='invoice_status'][not(ancestor::field)]",
)
LINE_PAGE = "//field[@name='order_line']/form//page[@name='invoices_incoming_shiptments']"


def shown(arch, expr):
    """Узлы, которые человек увидит (поля, досозданные ядром невидимыми, — нет)."""
    return [node for node in arch.xpath(expr)
            if (node.get("invisible") or "").strip() not in HIDDEN
            and (node.get("column_invisible") or "").strip() not in HIDDEN]


@tagged("post_install", "-at_install")
class TestStepZ6(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.admin = env.ref("base.user_admin")
        # Штатные права, при которых «Поступления» были бы видны без шага;
        # групп-выключателей нет (на бою в них никого).
        cls.admin.write({"group_ids": [
            Command.link(env.ref("stock.group_stock_manager").id),
            Command.link(env.ref("purchase.group_purchase_manager").id),
            Command.link(env.ref("account.group_account_invoice").id),
            Command.unlink(env.ref(REMOVED).id),
            Command.unlink(env.ref(STOCK).id),
            Command.unlink(env.ref(MONEY).id),
        ]})
        # Как Владимир Голубенко: закупки + штатный «Склад: пользователь».
        cls.buyer = new_test_user(
            env, login="pmkz6_buyer", name="Снабженец (шаг З-6)",
            groups="base.group_user,purchase.group_purchase_user,stock.group_stock_user")
        cls.manager = new_test_user(
            env, login="pmkz6_manager", name="Менеджер (шаг З-6)",
            groups="base.group_user,sales_team.group_sale_salesman,purchase.group_purchase_user")
        cls.supplier = env["res.partner"].create({"name": "Металлбаза (тест З-6)", "is_company": True})
        cls.product = env["product.product"].create({
            "name": "Лист 3 мм (тест З-6)", "type": "consu", "is_storable": True,
            "purchase_ok": True, "standard_price": 100.0})

    # ─── помощники ──────────────────────────────────────────────────────
    def _arch(self, user, view_type="form", xmlid=None):
        view_id = self.env.ref(xmlid).id if xmlid else False
        views = self.env["purchase.order"].with_user(user).get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _join(self, *xmlids):
        self.admin.write({"group_ids": [Command.link(self.env.ref(x).id) for x in xmlids]})

    def _order(self, user=None, days_ago=0):
        user = user or self.buyer
        planned = fields.Datetime.now() - datetime.timedelta(days=days_ago)
        return self.env["purchase.order"].with_user(user).create({
            "partner_id": self.supplier.id,
            "date_planned": planned,
            "order_line": [Command.create({
                "product_id": self.product.id, "product_qty": 5.0, "price_unit": 100.0,
                "date_planned": planned})],
        })

    # ─── Правила ────────────────────────────────────────────────────────
    def test_rules_registered(self):
        self.assertEqual(set(STEP_Z6_NODES), {FORM, LIST})
        exprs = {expr for expr, _group in STEP_Z6_NODES[FORM]}
        self.assertEqual(set(RECEIPT_EXPRS) | set(BILL_EXPRS) | {LINE_PAGE}, exprs)
        for expr, group in STEP_Z6_NODES[FORM] + STEP_Z6_NODES[LIST]:
            groups = (group,) if isinstance(group, str) else group
            with self.subTest(rule=expr):
                self.assertIn(REMOVED, groups, "«Убранное (показать)» возвращает всё.")
                if expr in RECEIPT_EXPRS:
                    self.assertIn(STOCK, groups, "«Поступления» вернёт и «Склад (показать)».")
                if expr in BILL_EXPRS:
                    self.assertIn(MONEY, groups, "Счета вернут и «Деньги (показать)».")
        # Правила шага 29 — без узлов шага (его тесты перебирают свои).
        own = {expr for expr, _group in HIDDEN_NODES[FORM]}
        self.assertFalse(own & exprs)

    def test_hidden_for_everyone_without_switch(self):
        self.assertTrue(self.buyer.has_group("stock.group_stock_user"),
                        "Посылка: у снабженца штатный склад есть.")
        for user in (self.buyer, self.manager, self.admin):
            form = self._arch(user)
            for expr in RECEIPT_EXPRS + BILL_EXPRS + (LINE_PAGE,):
                with self.subTest(user=user.login, node=expr):
                    self.assertFalse(shown(form, expr))
            for xmlid in ("purchase.purchase_order_view_tree", "purchase.purchase_order_kpis_tree"):
                listing = self._arch(user, "list", xmlid)
                for fname in ("receipt_status", "invoice_status"):
                    with self.subTest(user=user.login, view=xmlid, column=fname):
                        self.assertFalse(shown(listing, "//field[@name='%s']" % fname))
            with self.subTest(user=user.login, node="Налоги"):
                self.assertTrue(shown(form, "//field[@name='order_line']/list/field[@name='tax_ids']"),
                                "«Налоги» в строках — остаются.")
            with self.subTest(user=user.login, node="Материал пришёл"):
                self.assertTrue(form.xpath("//header/button[@name='action_pmk_material_arrived']"))

    def test_removed_brings_every_node_back(self):
        """Правило бьёт в существующий узел, а не в пустоту."""
        self._join(REMOVED)
        form = self._arch(self.admin)
        for expr in RECEIPT_EXPRS + BILL_EXPRS + (LINE_PAGE,):
            with self.subTest(node=expr):
                self.assertTrue(shown(form, expr))
        # Счётчик (button_box) и «Получить» в шапке — оба узла.
        self.assertEqual(len(form.xpath("//button[@name='action_view_picking']")), 2)
        listing = self._arch(self.admin, "list", "purchase.purchase_order_view_tree")
        self.assertTrue(shown(listing, "//field[@name='receipt_status']"))
        self.assertTrue(shown(listing, "//field[@name='invoice_status']"))
        kpis = self._arch(self.admin, "list", "purchase.purchase_order_kpis_tree")
        self.assertTrue(shown(kpis, "//field[@name='invoice_status']"))

    def test_stock_switch_brings_receipts_only(self):
        self._join(STOCK)
        form = self._arch(self.admin)
        for expr in RECEIPT_EXPRS:
            with self.subTest(back=expr):
                self.assertTrue(shown(form, expr))
        for expr in BILL_EXPRS + (LINE_PAGE,):
            with self.subTest(still_hidden=expr):
                self.assertFalse(shown(form, expr))

    def test_money_switch_brings_bills_only(self):
        self._join(MONEY)
        form = self._arch(self.admin)
        for expr in BILL_EXPRS:
            with self.subTest(back=expr):
                self.assertTrue(shown(form, expr))
        for expr in RECEIPT_EXPRS + (LINE_PAGE,):
            with self.subTest(still_hidden=expr):
                self.assertFalse(shown(form, expr))

    # ─── Форма работает, склад не проводится ────────────────────────────
    def test_form_create_confirm_edit(self):
        with Form(self.env["purchase.order"].with_user(self.buyer)) as order:
            order.partner_id = self.supplier
            with order.order_line.new() as line:
                line.product_id = self.product
                line.product_qty = 4.0
                line.price_unit = 90.0
        po = order.record
        self.assertEqual(po.order_line.price_unit, 90.0)
        po.button_confirm()
        self.assertEqual(po.state, "purchase")
        # Цена после подтверждения правится: readonly цены ссылается на
        # спрятанную колонку «Выставленный счёт».
        with Form(po.with_user(self.buyer)) as order:
            with order.order_line.edit(0) as line:
                line.price_unit = 95.0
        self.assertEqual(po.order_line.price_unit, 95.0)

    def test_confirm_does_not_receive_and_arrival_works(self):
        po = self._order()
        po.button_confirm()
        pickings = po.picking_ids
        self.assertTrue(pickings, "Посылка: ядро завело «Поступление».")
        self.assertFalse(pickings.filtered(lambda p: p.state in ("done", "cancel")),
                         "Подтверждение не проводит и не отменяет «Поступление».")
        self.assertEqual(po.order_line.qty_received, 0.0)
        po.with_user(self.buyer).action_pmk_material_arrived()
        self.assertEqual(po.pmk_metal_date, fields.Date.context_today(po))
        pickings.invalidate_recordset()
        self.assertEqual(pickings.exists(), pickings, "«Поступление» в базе, не удалено.")
        self.assertFalse(pickings.filtered(lambda p: p.state in ("done", "cancel")),
                         "«Материал пришёл» «Поступление» не трогает.")
        self.assertEqual(po.order_line.qty_received, 0.0)

    def test_late_signal_follows_arrival(self):
        PO = self.env["purchase.order"].with_user(self.buyer)
        late = self._order(days_ago=3)
        late.button_confirm()
        fresh = self._order(days_ago=-5)
        fresh.button_confirm()
        found = PO.search([("id", "in", (late | fresh).ids), ("is_late", "=", True)])
        self.assertEqual(found, late, "Дата прибытия прошла — «Поставка просрочена».")
        late.with_user(self.buyer).action_pmk_material_arrived()
        found = PO.search([("id", "in", (late | fresh).ids), ("is_late", "=", True)])
        self.assertFalse(found, "Материал пришёл — не просрочен, хотя «Поступление» не проведено.")
        late.with_user(self.buyer).action_pmk_material_undo()
        found = PO.search([("id", "in", (late | fresh).ids), ("is_late", "=", True)])
        self.assertEqual(found, late, "Отметку сняли — снова просрочен.")

    # ─── «Связи» ────────────────────────────────────────────────────────
    def test_flow_map_without_pickings(self):
        if "pmk.flow.builder" not in self.env:
            self.skipTest("pmk_flow не стоит.")
        po = self._order()
        po.button_confirm()
        self.assertTrue(po.picking_ids, "Посылка: «Поступление» есть.")
        Flow = self.env["pmk.flow.builder"]

        def models_of(user):
            graph = Flow.with_user(user).get_flow_graph("purchase.order", po.id)
            return {node["model"] for node in graph["nodes"]}, graph

        for user in (self.buyer, self.admin):
            with self.subTest(user=user.login):
                found, graph = models_of(user)
                self.assertNotIn("stock.picking", found)
        # У admin права есть на всё: пометка могла бы взяться только от нас.
        found, graph = models_of(self.admin)
        self.assertFalse(graph["restricted"],
                         "Убранное до учёта — не «скрыто правами».")
        for group in (STOCK, REMOVED):
            self.admin.write({"group_ids": [Command.unlink(self.env.ref(x).id) for x in (STOCK, REMOVED)]})
            self._join(group)
            with self.subTest(group=group):
                found, _graph = models_of(self.admin)
                self.assertIn("stock.picking", found)

    # ─── Слова ──────────────────────────────────────────────────────────
    def test_titles_and_data_words(self):
        self.assertEqual(ACTION_TITLES["purchase.report_purchase_quotation"], "Заявка поставщику")
        self.assertEqual(ACTION_TITLES["purchase.action_confirm_rfqs"], "Подтвердить заказы")
        self.assertEqual(ACTION_TITLES["purchase.action_merger"], "Объединить заявки")
        self.assertIn(("purchase.mt_rfq_sent", "name", "Запрос КП отправлен", "Заявка отправлена"),
                      DATA_WORDS, "Поверх прежнего нашего слова в базе.")
        # Подписи pmk_purchase в разметке — от языка не зависят.
        form = self._arch(self.buyer)
        labels = [(s.text or "").strip() for s in form.xpath("//div[contains(@class, 'oe_title')]/span")]
        self.assertIn("Заявка поставщику", labels)
        send = form.xpath("//header/button[@name='action_rfq_send']"
                          "[@string='Отправить заявку поставщику']")
        self.assertGreaterEqual(len(send), 2, "Черновик и отправленная заявка.")

    def test_russian_words(self):
        Module = self.env["ir.module.module"]
        self.env["res.lang"]._activate_lang(LANG)
        # Штатный русский перевод закупок (как «Обновить» перевод языка), тема
        # в том же списке — её крючок кладёт слова поверх (так же — шаг 39,
        # TestStep39Screens). Иначе на свежей базе сравнивать не с чем.
        Module.search([("name", "in", ["purchase", "purchase_stock", "pmk_theme"]),
                       ("state", "=", "installed")])._update_translations([LANG])
        for xmlid, fname, old, _new in DATA_WORDS:
            if xmlid.startswith("purchase."):
                record = self.env.ref(xmlid, raise_if_not_found=False)
                if record:
                    self.env.flush_all()
                    self.env.cr.execute(
                        'UPDATE "%s" SET "%s" = COALESCE("%s", \'{}\'::jsonb)'
                        ' || jsonb_build_object(%%s, %%s::text) WHERE id = %%s'
                        % (record._table, fname, fname), (LANG, old, record.id))
                    record.invalidate_recordset([fname])
        Module._pmk_apply_words()
        self.env.registry.clear_cache("stable", "templates")
        ru = self.env(context=dict(self.env.context, lang=LANG))
        for model in ("purchase.order", "purchase.report"):
            state = dict(ru[model].fields_get(["state"], ["selection"])["state"]["selection"])
            with self.subTest(model=model):
                self.assertEqual((state["draft"], state["sent"], state["cancel"]),
                                 ("Заявка", "Заявка отправлена", "Отменён"))
                self.assertEqual(state["purchase"], "Заказ поставщику")
        # «Заявки на металл» — те же слова в списке и на «Связях», что в
        # строке состояния формы (одно понятие — одно слово; доводка З-6).
        state = dict(ru["purchase.order"].fields_get(["state"], ["selection"])["state"]["selection"])
        for value in ("draft", "sent", "purchase", "cancel"):
            with self.subTest(request_state=value):
                self.assertEqual(REQUEST_STATE_LABELS[value], state[value])
        subtype = self.env.ref("purchase.mt_rfq_sent").with_context(lang=LANG)
        self.assertEqual(subtype.name, "Заявка отправлена")
        form = ru["purchase.order"].with_user(self.buyer).get_views(
            [(self.env.ref("purchase.purchase_order_form").id, "form")])["views"]["form"]["arch"]
        for needle in ('string="Подтвердить заказ"', 'string="Отправить заказ поставщику"'):
            with self.subTest(needle=needle):
                self.assertIn(needle, form)
        self.assertNotIn("Подтвердите заказ", form)
        search = ru["purchase.order"].with_user(self.buyer).get_views(
            [(self.env.ref("purchase.view_purchase_order_filter").id, "search")])["views"]["search"]["arch"]
        self.assertIn('string="Поставка просрочена"', search)
