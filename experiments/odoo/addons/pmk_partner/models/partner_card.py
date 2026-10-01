# -*- coding: utf-8 -*-
"""Карточка контрагента — разбор UX, шаг 28 (01.10.2026).

1. ПЕРЕКЛЮЧАТЕЛЬ ТИПА: «ИП или физлицо / Организация» вместо «Гость /
   Компания». «Гость» — перевод ядра для «Person» (base/i18n/ru.po), и на
   заводе так никого не зовут. Значения прежние (person / company), меняются
   только подписи.

   ПОЧЕМУ СПИСОК — МЕТОДОМ, А НЕ ПРЯМО В ПОЛЕ. Подписи списка-литерала ядро
   отдаёт через перевод (ir.model.fields.selection, _description_selection):
   новые слова легли бы только в en_US, а русский остался бы «Гость» — и
   вернулся бы при каждом обновлении base по его xmlid. Подписи метода ядро
   отдаёт как есть, без перевода. Список с теми же значениями в другом
   порядке ядро ещё и предупреждает «use selection_add». selection_add на
   company_type нет ни в одном установленном модуле (проверено поиском по
   ядру, RuOdoo и нашим модулям) — иначе метод был бы несовместим с ним.

2. КНОПКА «СДЕЛКИ» ОТКРЫВАЕТ ТО, ЧТО СЧИТАЕТ. Число на кнопке теперь наше —
   pmk_deal_count (сделки в работе и выигранные, models/res_partner.py,
   шаг 25), а штатное действие ядра открывало другое:
   • домен без отбора по типу — в списке «Сделки» стояли и лиды;
   • ключи search_default_filter_won / _ongoing / _lost мёртвые: фильтры в
     поиске CRM называются filter_won_status_won / _pending / _lost, и
     список открывался без фильтров — с проигранными (в домене ядра
     active in [True, False]).
   Здесь: только сделки, по умолчанию фильтры «Выиграно» и «В работе» —
   строк ровно столько, сколько на кнопке: счётчик считает теми же
   условиями (PMK_DEAL_DOMAIN в models/res_partner.py), в том числе
   выигранную сделку, убранную в архив, — «Выиграно» её показывает, домен
   ядра берёт и архив. Сузить домен до active = True нельзя: перестанет
   работать фильтр «Проигранные» (проигранные — в архиве). «Проигранные» —
   тем же фильтром поиска, одним щелчком.

   Заголовок экрана — «Сделки», как подпись кнопки: действие ядра
   (crm.crm_lead_opportunities) называется «Возможности», и по щелчку на
   «Сделки» открывались «Возможности» (осмотр копии 02.10).

   Складывается с переопределением в pmk_deal (тот убирает из ответа виды
   аналитики): каждый меняет свои ключи ответа, порядок вызова не важен.
"""

from odoo import fields, models

COMPANY_TYPES = [
    ("person", "ИП или физлицо"),
    ("company", "Организация"),
]

# Ключи ядра (crm/models/res_partner.py, action_view_opportunity), которым в
# поиске CRM Odoo 19 не соответствует ни один фильтр.
DEAD_DEAL_FILTERS = (
    "search_default_filter_won",
    "search_default_filter_ongoing",
    "search_default_filter_lost",
)


class ResPartnerCard(models.Model):
    _inherit = "res.partner"

    company_type = fields.Selection(selection="_pmk_company_type_selection")

    def _pmk_company_type_selection(self):
        return COMPANY_TYPES

    def action_view_opportunity(self):
        action = super().action_view_opportunity()
        action["name"] = "Сделки"
        # Ядро (crm, Odoo 19) отдаёт домен списком, а контекст — словарём.
        # Строкой их могла бы вернуть чужая надстройка — тогда не трогаем, а
        # не режем строку на символы и не теряем её ключи.
        domain = action.get("domain")
        if isinstance(domain, (list, tuple)):
            action["domain"] = [("type", "=", "opportunity")] + list(domain)
        context = action.get("context")
        if isinstance(context, dict):
            context = {key: value for key, value in context.items()
                       if key not in DEAD_DEAL_FILTERS}
            context.update({
                "search_default_filter_won_status_won": 1,
                "search_default_filter_won_status_pending": 1,
            })
            action["context"] = context
        return action
