# -*- coding: utf-8 -*-
"""Удаление лидов и сделок (№306, Владимир; Антон 24.10.2026: «принимаем»).

В Odoo удалять лиды и сделки может только «Продажи: Администратор» — у Владимира
(«Пользователь: Все документы») в шестерёнке не было «Удалить». Право удаления
этой группе даёт security/ir.model.access.csv (права в Odoo складываются).

Предохранитель: сделку со СЧЁТОМ удаляет только администратор продаж. Счёт
пережил бы удаление (связь обнуляется), но потерял бы сделку — воронку, «Связи»,
сделку МойСклада. Остальным — подсказка закрыть сделку как проигранную.
"""
from odoo import _, models
from odoo.exceptions import UserError


class CrmLeadPmkDelete(models.Model):
    _inherit = "crm.lead"

    def unlink(self):
        if not self.env.su and not self.env.user.has_group("sales_team.group_sale_manager"):
            with_orders = self.sudo().filtered(lambda lead: lead.order_ids)
            if with_orders:
                raise UserError(_(
                    "У сделки есть счёт — её удаляет только администратор продаж: %s.\n"
                    "Сделка не нужна — закройте её как проигранную.")
                    % ", ".join(with_orders.mapped("display_name")[:5]))
        return super().unlink()
