# -*- coding: utf-8 -*-
"""Метки МоегоСклада на записях Odoo: id МоегоСклада и то, чего у Odoo нет."""
from odoo import api, fields, models

MS_URL = "https://online.moysklad.ru/app/#invoiceout/edit?id=%s"

GROUPS = [
    ("embed", "Закладные детали"),
    ("fence", "Ограждения, ворота, 3D-забор"),
    ("steel", "Металлоконструкции"),
    ("roof", "Кровля, водосточка, доборы"),
    ("tpr", "Типовые по ТПР (колодцы, стремянки)"),
    ("vent", "Вентзонты, дефлекторы"),
    ("rolled", "Прокат, лист, пластины"),
    ("service", "Услуги, покраска, доставка"),
    ("fastener", "Крепёж"),
    ("other", "Прочее"),
]


class ResPartnerMs(models.Model):
    _inherit = "res.partner"

    pmk_ms_id = fields.Char("Id МоегоСклада", index=True, copy=False, readonly=True)


class PmkOrgMs(models.Model):
    _inherit = "pmk.org"

    pmk_ms_id = fields.Char("Id МоегоСклада", index=True, copy=False, readonly=True)


class SaleOrderMs(models.Model):
    _inherit = "sale.order"
    # Счёт ищется и по клиенту: строку «Заказов в работе» связывают со счётом руками.
    _rec_names_search = ["name", "partner_id.name", "client_order_ref"]

    pmk_ms_id = fields.Char("Id МоегоСклада", index=True, copy=False, readonly=True)
    pmk_ms_state = fields.Char("Статус МоегоСклада", index=True, copy=False, readonly=True,
                               help="Статус счёта в МоёмСкладе, как там (Согласование, Оплачен, "
                                    "Постоплата…). Наш статус счёта к нему не привязан.")
    pmk_ms_updated = fields.Char("Изменён в МоёмСкладе", copy=False, readonly=True)
    pmk_ms_contract = fields.Char("Договор поставки", copy=False)
    pmk_ms_object = fields.Char("Объект", copy=False)
    pmk_ms_weight = fields.Char("Вес продукции", copy=False)
    pmk_ms_sum = fields.Monetary("Сумма в МоёмСкладе", copy=False, readonly=True)
    pmk_ms_shipped_sum = fields.Monetary("Отгружено на сумму", copy=False, readonly=True)
    pmk_ms_shipped_date = fields.Date("Дата отгрузки", copy=False, readonly=True)
    pmk_ms_note = fields.Char("Расхождения с МоимСкладом", copy=False, readonly=True,
                              help="Налог строк не как у организации на дату счёта или сумма в "
                                   "Odoo не равна сумме МоегоСклада — посмотреть счёт в МоёмСкладе.")
    pmk_ms_url = fields.Char("Открыть в МоёмСкладе", compute="_compute_pmk_ms_url")

    @api.depends("pmk_ms_id")
    def _compute_pmk_ms_url(self):
        for order in self:
            order.pmk_ms_url = MS_URL % order.pmk_ms_id if order.pmk_ms_id else False


class SaleOrderLineMs(models.Model):
    _inherit = "sale.order.line"

    pmk_ms_group = fields.Selection(GROUPS, "Группа изделия", index=True, copy=False,
                                    help="Что продали — по названию строки (правила по словам). "
                                         "Можно поправить руками.")
