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

С шага 28 то же число стоит на кнопке «Сделки» в карточке, и считается оно
ровно как список, который кнопка открывает (pmk_partner/models/
partner_card.py): фильтры поиска CRM «Выиграно» и «В работе» (crm,
crm_lead_views.xml, filter_won_status_won / _pending). Отсюда условие
PMK_DEAL_DOMAIN и active_test=False. Выигранная сделка, убранная в архив,
остаётся выигранной: архивирование в Odoo 19 ни вероятность, ни этап не
меняет (crm_lead.py, action_unarchive: «a lead can be archived and not
lost»), и фильтр «Выиграно» её показывает — значит, и считаем. Сделка в
работе, убранная в архив, не считается — её не показывает «В работе».
Проигранная (won_status = lost) не считается никогда.
"""

from odoo import fields, models

# Те же условия, что у фильтров «Выиграно» и «В работе» поиска сделок: в
# одной группе поиска фильтры складываются через «или».
PMK_DEAL_DOMAIN = [
    ("type", "=", "opportunity"),
    "|", ("won_status", "=", "won"),
    "&", ("won_status", "=", "pending"), ("active", "=", True),
]


class ResPartnerDealCount(models.Model):
    _inherit = "res.partner"

    pmk_deal_count = fields.Integer(
        "Сделок", compute="_compute_pmk_deal_count",
        help="Сделки клиента в работе и выигранные (выигранные — и убранные в "
             "архив). Лиды и проигранные не считаются; сделки контактных лиц — "
             "у их компании.")

    def _compute_pmk_deal_count(self):
        self.pmk_deal_count = 0
        if not self.env.user.has_group("sales_team.group_sale_salesman"):
            return
        # active_test=False: архив отбирает само условие (см. выше), как в
        # списке по кнопке, где у ядра active in [True, False].
        data = self.env["crm.lead"].with_context(active_test=False)._read_group(
            domain=PMK_DEAL_DOMAIN + self._get_contact_opportunities_domain(),
            groupby=["partner_id"], aggregates=["__count"])
        current = set(self._ids)
        for partner, count in data:
            while partner:
                if partner.id in current:
                    partner.pmk_deal_count += count
                partner = partner.parent_id
