# -*- coding: utf-8 -*-
"""Пункты шестерёнки «убрать совсем» и «до востребования» — разбор UX,
шаг 29 (02.10.2026).

Что прячем (группа-выключатель — security/pmk_step29_groups.xml):
  • «Убранное (показать)»: «Отправить SMS» и «Добавить / удалить
    наблюдателей» у сделки; «Отправить SMS», «Поиск конфиденциальности»,
    «Загрузить (vCard)» у контрагента; «Отправить напоминание» у запроса КП;
    «Вычислить цену на основе ведомости материалов», «Отчёт по
    прейскуранту», «Пополнение» у товара;
  • «Склад (показать)»: «Печать этикеток» у товара;
  • «Деньги (показать)»: «Печатать акт сверки» у контрагента (российская
    локализация, l10n_ru_act_rev).

КАК. Шестерёнку браузер получает от get_views(toolbar=True), а тот берёт
пункты из ir.actions.actions.get_bindings. Здесь — после ядра: ядро уже
отбросило то, на что у пользователя нет штатной группы действия или прав на
модель окна; мы отбрасываем ещё и пункты из HIDDEN_BINDINGS, если у
пользователя нет группы-выключателя. Штатная группа продолжает работать
(«Акт сверки» увидит только тот, у кого и «Администратор» учёта, и
«Деньги (показать)»).

ПОЧЕМУ НЕ <function write> group_ids, как опасные действия шага 23. Там
действие должно было не запускаться и по прямой ссылке — это опасные пункты.
Здесь пункты безвредные, а запись в чужие действия -u модуля-источника
перезаписал бы. Здесь в базе ничего не меняется; xml-id ищется при каждом
вызове (кэш ядра _xmlid_lookup) без raise — модуль-источник снят или ещё не
стоит, строка молча пропускается, зависимостей нет.

Вернуть один пункт — убрать его строку из HIDDEN_BINDINGS и выложить
pmk_theme; кучку — добавить себя в группу. Таблица —
docs/disabled-features.md, раздел «шаг 29».

ИМЕНА ПУНКТОВ — СЛОВАМИ ЗАВОДА (разбор UX, шаг 39, 05.10.2026). Там же, после
ядра, пункт получает имя из ACTION_TITLES (models/ir_actions_act_window.py),
если оно там есть: «Пометить потерянным» → «Отметить проигрыш» у сделки,
«Заказ на покупку» → «Заказ поставщику» и «Запрос на коммерческое
предложение» → «Запрос КП» в «Печати» закупки, «запрос котировок» →
«запросы КП» в её «Действиях». Окно, которое пункт откроет, называется так
же: имя действия-окна подменяет _get_action_dict. В базе имена штатные.
"""
from odoo import api, models

from .ir_actions_act_window import ACTION_TITLES

REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"
MONEY = "pmk_theme.group_pmk_money"

# xml-id действия → группа-выключатель, без которой пункта в шестерёнке нет.
HIDDEN_BINDINGS = {
    # Сделка и лид.
    "crm_sms.crm_lead_act_window_sms_composer_single": REMOVED,  # список, канбан
    "crm_sms.crm_lead_act_window_sms_composer_multi": REMOVED,   # форма
    "crm.mail_followers_edit_action_from_lead": REMOVED,
    # Контрагент.
    "sms.res_partner_act_window_sms_composer_multi": REMOVED,
    "sms.res_partner_act_window_sms_composer_single": REMOVED,
    "privacy_lookup.ir_action_server_action_privacy_lookup_partner": REMOVED,
    "web.download_contact": REMOVED,
    "l10n_ru_act_rev.act_action_general_ledger_wizard_partner_relation": MONEY,
    # Запрос КП / заказ поставщику.
    "purchase.action_purchase_send_reminder": REMOVED,
    # Товар: шаблон и вариант.
    "mrp_account.action_compute_price_bom_template": REMOVED,
    "mrp_account.action_compute_price_bom_product": REMOVED,
    "product.action_product_template_price_list_report": REMOVED,
    "product.action_product_price_list_report": REMOVED,
    "stock.action_product_template_replenishment": REMOVED,
    "stock.action_product_replenishment": REMOVED,
    "product.action_product_template_print_labels": STOCK,
    "product.action_product_print_labels": STOCK,
}


class IrActionsActions(models.Model):
    _inherit = "ir.actions.actions"

    @api.model
    def get_bindings(self, model_name):
        result = super().get_bindings(model_name)
        hidden = self._pmk_hidden_binding_groups()
        titles = self._pmk_binding_titles()
        if not hidden and not titles:
            return result
        user = self.env.user
        filtered = {}
        for kind, actions in result.items():
            kept = []
            for action in actions:
                if action["id"] in hidden and not user.has_group(hidden[action["id"]]):
                    continue
                title = titles.get(action["id"])
                if title:
                    action = dict(action, name=title)
                kept.append(action)
            if kept:
                filtered[kind] = kept
        return filtered

    @api.model
    def _pmk_binding_titles(self):
        """id действия → имя словами завода (ACTION_TITLES; только существующие)."""
        to_id = self.env["ir.model.data"]._xmlid_to_res_id
        result = {}
        for xmlid, title in ACTION_TITLES.items():
            action_id = to_id(xmlid, raise_if_not_found=False)
            if action_id:
                result[action_id] = title
        return result

    @api.model
    def _pmk_hidden_binding_groups(self):
        """id действия → группа-выключатель (только существующие действия)."""
        to_id = self.env["ir.model.data"]._xmlid_to_res_id
        result = {}
        for xmlid, group in HIDDEN_BINDINGS.items():
            action_id = to_id(xmlid, raise_if_not_found=False)
            if action_id and to_id(group, raise_if_not_found=False):
                result[action_id] = group
        return result
