# -*- coding: utf-8 -*-
"""Закупки: пустые экраны и виды «Запросов КП» (разбор UX, шаг 26, 01.10.2026).

1. ПОДСКАЗКА ПУСТОГО ЭКРАНА — нашими словами, через точку расширения
   pmk_theme (_pmk_empty_help; как и зачем — в
   pmk_theme/models/ir_actions_act_window.py). «Закупки → Поставщики» —
   здесь, а не в теме: этот модуль открывает их списком поставщиков прайсов
   (views/res_partner_views.xml, action_supplier_list_binding).

2. ВИДЫ: СПИСОК И ФОРМА. У «Запросов КП» и «Заказов поставщикам» было
   шесть видов (список, канбан, календарь, сводная, график, активность) при
   одном документе. Оставляем список и форму — в момент отдачи действия
   браузеру, как и подсказку. Записью XML с полем view_mode не обойтись:
     • у «Заказов поставщикам» канбан привязан отдельной строкой
       (view_ids в purchase_views.xml, без xml-id), а Odoo 19 показывает
       привязанный вид при любом view_mode;
     • -u purchase вернул бы view_mode штатный — запись чужого модуля.
   Здесь в базе ничего не меняется: в «Технический → Оконные действия»
   остаются семь видов, браузер получает два.

Вернуть: убрать строку из EMPTY_HELP или VIEW_MODES и выложить pmk_purchase.
Таблица — docs/disabled-features.md.
"""
from odoo import api, models

from odoo.addons.pmk_theme.models.ir_actions_act_window import hint

EMPTY_HELP = {
    "purchase.purchase_rfq": hint(
        "По выбранным фильтрам запросов КП нет.",
        "Новый запрос — кнопка «Новое»; когда поставщик ответит — «Подтвердите заказ».",
    ),
    "purchase.purchase_form_action": hint(
        "Заказ поставщику появляется из запроса КП кнопкой «Подтвердите заказ».",
        "Запросы — «Закупки → Запросы КП».",
    ),
    "account.res_partner_action_supplier": hint(
        "По выбранным фильтрам поставщиков нет.",
        "У кого спрашиваем цены — «Закупки → Поставщики прайсов».",
    ),
}

# xml-id действия → какие виды отдавать браузеру (порядок — штатный).
VIEW_MODES = {
    "purchase.purchase_rfq": ("list", "form"),
    "purchase.purchase_form_action": ("list", "form"),
}


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    @api.model
    def _pmk_empty_help(self):
        texts = super()._pmk_empty_help()
        texts.update(EMPTY_HELP)
        return texts

    def _get_action_dict(self):
        result = super()._get_action_dict()
        modes = VIEW_MODES.get(result.get("xml_id"))
        if modes:
            result["views"] = [view for view in result.get("views") or [] if view[1] in modes]
            result["view_mode"] = ",".join(
                mode for mode in (result.get("view_mode") or "").split(",") if mode in modes)
        return result
