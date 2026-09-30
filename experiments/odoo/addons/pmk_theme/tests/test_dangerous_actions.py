# -*- coding: utf-8 -*-
"""Опасные действия в шестерёнке — только группе-выключателю (шаг 23).

Что ловим:
  • в группе никого нет, admin пунктов не видит — в шестерёнке их нет, а
    серверное действие не запускается и по прямому вызову;
  • скрыто точечно: соседние пункты шестерёнки на месте;
  • обратимо: admin в группе — пункты вернулись;
  • начисленные расходы и выручку группа одна не возвращает: ядро закрывает
    их ещё и группой «Показать все функции учета» (на боевой в ней никого).
    Чтобы тесты ловили именно НАШЕ скрытие, admin эту группу в тестах
    получает — иначе начисленные были бы не видны и без нас;
  • ⚠️ скрытие переживает -u. «Поделиться» у запроса КП и у счёта в своих
    модулях помечены noupdate, и <record> на них при -u молча пропускается
    (models.py, _load_records). Поэтому data/dangerous_actions.xml написан
    через <function write>, и последний тест прогоняет его в режиме update —
    как deploy.sh на боевой. На одноразовой базе (-i, режим init) обычный
    <record> прошёл бы все остальные тесты и всё равно не сработал бы на
    боевой.
"""
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.tools.convert import convert_file

GROUP = "pmk_theme.group_pmk_dangerous_actions"

# xmlid действия → модель, к шестерёнке которой оно привязано.
HIDDEN = {
    "portal.partner_wizard_action_create_and_open": "res.partner",
    "purchase.model_purchase_order_action_share": "purchase.order",
    "sale.model_sale_order_action_share": "sale.order",
    "account.model_account_move_action_share": "account.move",
    "purchase.action_accrued_expense_entry": "purchase.order",
    "sale.action_accrued_revenue_entry": "sale.order",
    "sale.action_accrued_revenue_entry_sale_order_line": "sale.order.line",
}

# Начисленные: ядро показывает их только с группой «Показать все функции
# учета» — и в group_ids действия, и в правах на мастер.
ACCRUED = (
    "purchase.action_accrued_expense_entry",
    "sale.action_accrued_revenue_entry",
    "sale.action_accrued_revenue_entry_sale_order_line",
)
ACCOUNT_USER = "account.group_account_user"

# Соседи по шестерёнке, которые должны остаться.
NEIGHBOURS = {
    "base.action_partner_merge": "res.partner",
    "purchase.action_confirm_rfqs": "purchase.order",
}


@tagged("post_install", "-at_install")
class TestDangerousActions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group = cls.env.ref(GROUP)
        cls.admin = cls.env.ref("base.user_admin")
        cls.account_user = cls.env.ref(ACCOUNT_USER)
        # Права на сами документы и мастера — чтобы шестерёнка собиралась
        # (get_bindings отбрасывает действие, если модель окна не читается):
        # «Объединить» контрагентов — group_partner_manager, начисленные —
        # «Показать все функции учета». Её НЕ даёт «Администратор» учёта
        # (в CE он подразумевает только «Выставление счетов»), поэтому
        # выдаём отдельно: без неё начисленные скрыты ядром, и тест скрытия
        # проходил бы и без data/dangerous_actions.xml.
        cls.admin.write({"group_ids": [
            Command.link(cls.env.ref("base.group_partner_manager").id),
            Command.link(cls.env.ref("sales_team.group_sale_manager").id),
            Command.link(cls.env.ref("purchase.group_purchase_manager").id),
            Command.link(cls.env.ref("account.group_account_manager").id),
            Command.link(cls.account_user.id),
        ]})

    def _gear_ids(self, model):
        bindings = self.env["ir.actions.actions"].with_user(self.admin).get_bindings(model)
        return {action["id"] for action in bindings.get("action", ())}

    def test_group_is_empty(self):
        self.assertFalse(self.group.with_context(active_test=False).user_ids,
                         "В группе-выключателе никого быть не должно.")
        self.assertFalse(self.admin.has_group(GROUP))

    def test_actions_belong_to_group_only(self):
        for xmlid in HIDDEN:
            with self.subTest(action=xmlid):
                self.assertEqual(self.env.ref(xmlid).group_ids, self.group)

    def test_admin_does_not_see_them(self):
        for xmlid, model in HIDDEN.items():
            with self.subTest(action=xmlid):
                self.assertNotIn(self.env.ref(xmlid).id, self._gear_ids(model))

    def test_neighbours_stay(self):
        for xmlid, model in NEIGHBOURS.items():
            with self.subTest(action=xmlid):
                self.assertIn(self.env.ref(xmlid).id, self._gear_ids(model))

    def test_reversible_by_group(self):
        before = {model: self._gear_ids(model) for model in set(HIDDEN.values())}
        self.admin.write({"group_ids": [Command.link(self.group.id)]})
        hidden_ids = {self.env.ref(x).id for x in HIDDEN}
        for model in set(HIDDEN.values()):
            after = self._gear_ids(model)
            with self.subTest(model=model):
                self.assertLessEqual(before[model], after, "Группа ничего не должна убирать.")
                self.assertLessEqual(after - before[model], hidden_ids,
                                     "Группа возвращает только опасные пункты.")
        for xmlid, model in HIDDEN.items():
            with self.subTest(action=xmlid):
                self.assertIn(self.env.ref(xmlid).id, self._gear_ids(model))

    def test_accrued_need_accounting_group(self):
        """Так на боевой: без «Показать все функции учета» группа-выключатель
        возвращает портал и «Поделиться», а начисленные — нет. Это и написано
        в docs/disabled-features.md («Вернуть всё разом»)."""
        self.admin.write({"group_ids": [
            Command.unlink(self.account_user.id),
            Command.link(self.group.id),
        ]})
        self.assertFalse(self.admin.has_group(ACCOUNT_USER),
                         "Группу учёта admin получил через подразумеваемые — "
                         "поправить инструкцию «Вернуть всё разом».")
        for xmlid, model in HIDDEN.items():
            with self.subTest(action=xmlid):
                gear = self._gear_ids(model)
                if xmlid in ACCRUED:
                    self.assertNotIn(self.env.ref(xmlid).id, gear)
                else:
                    self.assertIn(self.env.ref(xmlid).id, gear)

    def test_server_action_refused_by_direct_call(self):
        partner = self.env["res.partner"].create({"name": "ПМК тест: портал"})
        action = self.env.ref("portal.partner_wizard_action_create_and_open").with_user(self.admin)
        with self.assertRaises(AccessError):
            action.with_context(
                active_model="res.partner", active_id=partner.id, active_ids=partner.ids,
            ).run()

    def test_hiding_survives_module_update(self):
        """Деплой делает -u pmk_theme: скрытие должно вернуться и на noupdate-записях."""
        for xmlid in HIDDEN:
            self.env.ref(xmlid).sudo().write({"group_ids": [Command.clear()]})
        convert_file(self.env, "pmk_theme", "data/dangerous_actions.xml", {},
                     mode="update", noupdate=False)
        for xmlid in HIDDEN:
            with self.subTest(action=xmlid):
                self.assertEqual(self.env.ref(xmlid).group_ids, self.group)
