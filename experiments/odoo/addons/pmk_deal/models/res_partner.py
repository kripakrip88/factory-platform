# -*- coding: utf-8 -*-
"""Клиент → «Сделки»: те же виды, что у воронки (разбор UX, шаг 31).

Воронка показывает три вида вместо семи — канбан, список, активность
(data/crm_pipeline_views.xml). Кнопка «Сделки» в карточке клиента открывает
другое действие ядра, crm.crm_lead_opportunities, с тем же канбаном (и уже с
нашей карточкой), но с графиком, сводной и календарём в переключателе.

ПОЧЕМУ ЗДЕСЬ, А НЕ В ДАННЫХ. Привязки графика, сводной и календаря у этого
действия — те же виды, что у воронки; перевесить их на «Аналитику воронки»
значит получить там каждый вид дважды. Поэтому убираем их из ответа кнопки:
действие ядра и его привязки не тронуты, вернуть — удалить этот файл.
"""

from odoo import models

# Виды аналитики — они живут в «Аналитике воронки» (pmk_deal.action_pipeline_analytics).
ANALYTICS_VIEW_MODES = ("graph", "pivot", "calendar")


class ResPartnerDeals(models.Model):
    _inherit = "res.partner"

    def action_view_opportunity(self):
        action = super().action_view_opportunity()
        views = [(view_id, mode) for view_id, mode in action.get("views", [])
                 if mode not in ANALYTICS_VIEW_MODES]
        action["views"] = views
        action["view_mode"] = ",".join(mode for _view_id, mode in views)
        return action
