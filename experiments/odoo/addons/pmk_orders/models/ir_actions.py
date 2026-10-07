# -*- coding: utf-8 -*-
"""«Продажи → Счета покупателям» открывается действующими счетами (шаг З-2).

Штатное окно sale.action_orders открывается с фильтром «только
подтверждённые» (search_default_sales): выставленные и ждущие оплаты счета
по умолчанию не видны, а именно их менеджер и ищет. Подменяем контекст
окна на фильтр «Действующие» (без прежних редакций) — в момент отдачи
браузеру, как заголовки окон темы (pmk_theme, ACTION_TITLES): запись ядра
не меняется, и -u sale подмену не сотрёт.

Вернуть штатное — убрать этот файл из models/__init__.py и выложить.
"""
from odoo import models

ORDERS_CONTEXT = {
    "sale.action_orders": "{'search_default_pmk_current': 1}",
}


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def _get_action_dict(self):
        result = super()._get_action_dict()
        context = ORDERS_CONTEXT.get(result.get("xml_id"))
        if context:
            result["context"] = context
        return result
