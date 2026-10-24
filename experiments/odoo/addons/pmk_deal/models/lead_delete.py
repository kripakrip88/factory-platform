# -*- coding: utf-8 -*-
"""Удаление лидов (№306, Владимир; Антон 24.10.2026: вариант «в»).

В Odoo удалять лиды и сделки может только «Продажи: Администратор» — у Владимира
(«Пользователь: Все документы») в шестерёнке не было «Удалить». Право удаления
этой группе даёт security/ir.model.access.csv (права в Odoo складываются).

Удаление — насовсем, корзины нет. Поэтому:
  • ЛИД удаляется: спам и дубли из почты не жалко;
  • СДЕЛКА — только в архив (шестерёнка → «Архивировать») или «проиграна»: это
    история продаж, а расчёты и счета после удаления потеряли бы сделку. Насовсем
    сделку удаляет администратор продаж;
  • лид со счётом (бывает после смены типа) — так же, как сделка.
"""
from odoo import _, models
from odoo.exceptions import UserError


class CrmLeadPmkDelete(models.Model):
    _inherit = "crm.lead"

    def unlink(self):
        if not self.env.su and not self.env.user.has_group("sales_team.group_sale_manager"):
            kept = self.sudo().filtered(lambda lead: lead.type == "opportunity" or lead.order_ids)
            if kept:
                raise UserError(_(
                    "Сделки не удаляются — это история продаж: %s.\n"
                    "Уберите сделку в архив (шестерёнка → «Архивировать») или закройте как "
                    "проигранную. Из архива её можно вернуть. Удалить насовсем может "
                    "администратор продаж.")
                    % ", ".join(kept.mapped("display_name")[:5]))
        return super().unlink()
