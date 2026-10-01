# -*- coding: utf-8 -*-
"""«Продажи → Клиенты»: список и форма, без канбана — разбор UX, шаг 29
(02.10.2026).

Канбан клиентов — плитки с фиолетовыми квадратами-буквами вместо списка
с ИНН, городом и менеджером (свой список шага 25,
views/res_partner_list_views.xml). Видов оставляем два — в момент отдачи
действия браузеру (_get_action_dict: через него идут и меню, и кнопки), тем
же приёмом, что виды «Запросов КП» шага 26 (pmk_purchase,
models/ir_actions_act_window.py). В базе ничего не меняется: у действия
account.res_partner_action_customer в «Технический → Оконные действия»
по-прежнему list,kanban,form, и -u account этого не вернёт и не сломает.
«Закупки → Поставщики» (account.res_partner_action_supplier) не тронуты —
разбор просил только клиентов.

Вернуть: убрать строку из VIEW_MODES и выложить pmk_partner. Таблица —
docs/disabled-features.md, раздел «шаг 29».
"""
from odoo import models

# xml-id действия → какие виды отдавать браузеру (порядок — штатный).
VIEW_MODES = {
    "account.res_partner_action_customer": ("list", "form"),
}


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def _get_action_dict(self):
        result = super()._get_action_dict()
        modes = VIEW_MODES.get(result.get("xml_id"))
        if modes:
            result["views"] = [view for view in result.get("views") or [] if view[1] in modes]
            result["view_mode"] = ",".join(
                mode for mode in (result.get("view_mode") or "").split(",") if mode in modes)
        return result
