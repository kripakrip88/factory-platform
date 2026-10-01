# -*- coding: utf-8 -*-
"""Колонка «Сделок» в списке «Продажи → Клиенты» (разбор UX, шаг 25).

ПОЧЕМУ НЕ ШТАТНЫЙ opportunity_count. Ядро (crm) считает им ВСЕ записи
crm.lead клиента — с active_test=False и без отбора по типу: в счётчик
попадают лиды (этап «Лиды» у завода включён) и проигранные сделки (они в
архиве). Клиент с одним лидом из почты и одной проигранной сделкой получал
«Сделок: 2», хотя сделок в работе нет, — лид назван сделкой.

Здесь — только сделки (type = opportunity), кроме проигранных: в работе и
выигранные. Сделки контактного лица считаются его компании — как у ядра.
Счётчик видят те, кто видит сделки; остальным — ноль, как у ядра.
"""

from odoo import fields, models


class ResPartnerDealCount(models.Model):
    _inherit = "res.partner"

    pmk_deal_count = fields.Integer(
        "Сделок", compute="_compute_pmk_deal_count",
        help="Сделки клиента в работе и выигранные. Лиды и проигранные не "
             "считаются; сделки контактных лиц — у их компании.")

    def _compute_pmk_deal_count(self):
        self.pmk_deal_count = 0
        if not self.env.user.has_group("sales_team.group_sale_salesman"):
            return
        # Без active_test=False: проигранные сделки в архиве и не считаются.
        data = self.env["crm.lead"]._read_group(
            domain=[("type", "=", "opportunity")] + self._get_contact_opportunities_domain(),
            groupby=["partner_id"], aggregates=["__count"])
        current = set(self._ids)
        for partner, count in data:
            while partner:
                if partner.id in current:
                    partner.pmk_deal_count += count
                partner = partner.parent_id
