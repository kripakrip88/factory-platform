# -*- coding: utf-8 -*-
"""Доборка знает свою сделку, сделка — свои доборки (разбор UX, шаг 35).

ЗАЧЕМ. «Клиент / изделие» у доборки был свободным текстом: ни клиента, ни
сделки, и доборки по заявке находились только глазами. Шаг 35 даёт доборке
поле «Клиент» (pmk_calc, контрагент) и «Сделку» — здесь, а на сделке —
кнопку-счётчик «Доборки», как «Расчёты».

ПОЧЕМУ ЗДЕСЬ, А НЕ В pmk_calc. Калькулятор (pmk_calc) намеренно не знает CRM:
он должен работать и без продаж. Связь «сделка ↔ расчёт» уже живёт в этом
модуле (deal_link.py), он зависит и от crm, и от pmk_calc — доборка встаёт
рядом тем же приёмом. Новых зависимостей ни у кого не появилось.

Хранится ОДНИМ полем на доборке, как у расчёта: у сделки доборок бывает
несколько (дозаказ), у доборки сделка одна. Старые доборки не переносились:
сделки у них нет, текст «Изделие / объект» на месте.
"""

from odoo import Command, _, api, fields, models


class DoborOrderDeal(models.Model):
    _inherit = "pmk.dobor.order"

    # copy=True — копия доборки остаётся в той же сделке, как копия расчёта
    # (приёмка 01.10.2026, R4).
    opportunity_id = fields.Many2one(
        "crm.lead", "Сделка", index=True, ondelete="set null", copy=True,
        tracking=True,
        # Только сделки, не лиды: как у расчёта (deal_link.py) — делают по
        # заявке, которую взяли в работу.
        domain="[('type', '=', 'opportunity')]",
        help="К какой сделке доборка. Клиент подставляется из неё.")

    @api.onchange("opportunity_id")
    def _onchange_opportunity_id(self):
        """Клиент — из сделки, если ещё не выбран.

        Клиент — компания контакта сделки (как у расчёта, шаг 11): иначе
        клиентом доборки стал бы инженер заказчика, и группировка «Клиент»
        разбивалась бы по людям. Заполненного не перетираем: выбор менеджера
        важнее автоподстановки.
        """
        for order in self:
            deal = order.opportunity_id
            if deal and not order.partner_id:
                order.partner_id = deal.partner_id.commercial_partner_id


class CrmLeadDobor(models.Model):
    _inherit = "crm.lead"

    dobor_ids = fields.One2many("pmk.dobor.order", "opportunity_id", "Доборки")
    dobor_count = fields.Integer("Доборок", compute="_compute_dobor_count")

    @api.depends("dobor_ids")
    def _compute_dobor_count(self):
        Order = self.env["pmk.dobor.order"]
        # Нет права читать доборки — ноль, как у штатных счётчиков ядра.
        if not Order.has_access("read"):
            self.dobor_count = 0
            return
        # Запросом, а не длиной набора: на списке сделок иначе подгружались
        # бы все доборки каждой строки.
        data = Order._read_group(
            [("opportunity_id", "in", self.ids)], ["opportunity_id"], ["__count"])
        counts = {lead.id: count for lead, count in data}
        for lead in self:
            lead.dobor_count = counts.get(lead.id, 0)

    def action_open_dobors(self):
        """Кнопка-счётчик «Доборки» — сразу к делу, как «Расчёты»:
          • доборок нет — форма новой, сделка и клиент уже подставлены;
          • одна — она сама;
          • несколько — список доборок сделки, все, включая изготовленные.
        Стадию сделки кнопка не двигает.
        """
        self.ensure_one()
        orders = self.env["pmk.dobor.order"].search([("opportunity_id", "=", self.id)])
        action = {
            "type": "ir.actions.act_window",
            "name": _("Доборки по сделке"),
            "res_model": "pmk.dobor.order",
            "target": "current",
            "context": self._pmk_dobor_defaults(),
        }
        if not orders:
            action.update(name=_("Новая доборка"), views=[(False, "form")])
        elif len(orders) == 1:
            action.update(name=orders.name, res_id=orders.id, views=[(False, "form")])
        else:
            action.update(
                view_mode="list,form",
                views=[(False, "list"), (False, "form")],
                domain=[("opportunity_id", "=", self.id)],
            )
        return action

    def _pmk_dobor_defaults(self):
        """Что подставить в новую доборку со сделки: сделку и клиента —
        компанию контакта сделки. «Изделие / объект» не подставляем: название
        сделки — тема заявки («Запрос стоимости…»), а не изделие, и в листе
        оно встало бы строкой «Заказчик»."""
        self.ensure_one()
        return {
            "default_opportunity_id": self.id,
            "default_partner_id": self.partner_id.commercial_partner_id.id,
        }

    def _merge_get_fields_specific(self):
        """Объединение сделок: доборки всех сделок — к итоговой, как расчёты
        (deal_money.py). Иначе удалённая сделка оставила бы доборку без
        сделки (ondelete set null)."""
        fields_info = super()._merge_get_fields_specific()
        fields_info["dobor_ids"] = lambda fname, leads: [
            Command.link(order.id) for order in leads.dobor_ids]
        return fields_info
