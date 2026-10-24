# -*- coding: utf-8 -*-
"""«Удалить» у лидов и сделок (№306, Владимир; Антон 24.10.2026: вариант «в» —
лиды удаляются, сделки в архив; «может просто кнопке удалить присвоим функционал
архивирования?»).

В Odoo удалять лиды и сделки может только «Продажи: Администратор» — у Владимира
(«Пользователь: Все документы») в шестерёнке не было «Удалить». Право удаления
этой группе даёт security/ir.model.access.csv (права в Odoo складываются).

Удаление — насовсем, корзины нет. Поэтому у всех, кроме администратора продаж:
  • ЛИД удаляется: спам и дубли из почты не жалко;
  • СДЕЛКА (и лид со счётом) — «Удалить» убирает её в АРХИВ: это история продаж,
    а расчёты и счета после удаления потеряли бы сделку. Вернуть — фильтр
    «Архивные» → «Разархивировать». Насовсем удаляет администратор продаж.
Так же работает и слияние дублей (crm.merge.opportunity удаляет слитые сделки):
у продавца они уйдут в архив.
"""
from odoo import _, models


class CrmLeadPmkDelete(models.Model):
    _inherit = "crm.lead"

    def unlink(self):
        if self.env.su or self.env.user.has_group("sales_team.group_sale_manager"):
            return super().unlink()
        kept = self.filtered(lambda lead: lead.type == "opportunity" or lead.sudo().order_ids)
        for lead in kept:
            lead.message_post(body=_("Убрана в архив кнопкой «Удалить» — сделки не удаляются насовсем."))
        kept.action_archive()
        return super(CrmLeadPmkDelete, self - kept).unlink()
