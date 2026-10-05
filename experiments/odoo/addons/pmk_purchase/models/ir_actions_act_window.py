# -*- coding: utf-8 -*-
"""Закупки: пустые экраны и виды «Запросов КП» (разбор UX, шаг 26, 01.10.2026).

1. ПОДСКАЗКА ПУСТОГО ЭКРАНА — нашими словами, через точку расширения
   pmk_theme (_pmk_empty_help; как и зачем — в
   pmk_theme/models/ir_actions_act_window.py). Штатный список поставщиков —
   здесь, а не в теме: этот модуль открывает его списком поставщиков прайсов
   (views/res_partner_views.xml, action_supplier_list_binding).

   С шага 38 (05.10.2026) пункты Закупок другие: «Запросы КП» →
   «Заказы поставщикам» (то же действие purchase_rfq, окно названо так же —
   ACTION_TITLES темы), «Поставщики прайсов» → «Поставщики», штатные
   «Поставщики» → «Все поставщики» и «Заказы поставщикам» → «Подтверждённые
   заказы» (оба — с «Убранным»). Подсказки ведут в рабочие пункты.

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
    # С шага 38 это «Закупки → Заказы поставщикам»: запросы КП и заказы всех
    # стадий одним списком (pmk_theme/data/menus.xml).
    "purchase.purchase_rfq": hint(
        "По выбранным фильтрам заказов поставщикам нет.",
        "Новый запрос КП — кнопка «Новое»; когда поставщик ответит — «Подтвердите заказ».",
    ),
    # «Подтверждённые заказы» и «Все поставщики» — с шага 38 только с
    # «Убранным»; подсказки ведут в рабочие пункты раздела.
    "purchase.purchase_form_action": hint(
        "Заказ поставщику появляется из запроса КП кнопкой «Подтвердите заказ».",
        "Запросы КП и заказы всех стадий — «Закупки → Заказы поставщикам».",
    ),
    "account.res_partner_action_supplier": hint(
        "По выбранным фильтрам поставщиков нет.",
        "У кого спрашиваем цены — «Закупки → Поставщики».",
    ),
}

# xml-id действия → какие виды отдавать браузеру (порядок — штатный).
VIEW_MODES = {
    "purchase.purchase_rfq": ("list", "form"),
    "purchase.purchase_form_action": ("list", "form"),
    # «Номенклатура» без канбана (разбор UX, шаг 29, 02.10.2026): плитки
    # металла с «1,00 руб» и нулевым остатком вместо списка. В базе у
    # действия по-прежнему list,kanban,form.
    "stock.product_template_action_product": ("list", "form"),
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
