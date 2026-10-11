# -*- coding: utf-8 -*-
"""Штатный мастер «Объединить контакты» — какая карточка остаётся
(шаг З-14, 10.10.2026).

Мастер ядра (base/wizard/base_partner_merge.py, default_get) по умолчанию
оставляет «активную самую свежую» карточку. Для пары 18/159 это была бы
159 «ТРУБНОЕ РЕШЕНИЕ» из таблицы заказов — с голым названием и без
реквизитов, а филиал 18 со сделкой ушёл бы в неё. Экран «Возможные дубли»
(models/partner_duplicate.py) передаёт в контексте pmk_merge_dst_id —
карточку, к которой привязано больше документов; здесь она и ставится
целевой. Выбрать другую можно в самом мастере. Само объединение — штатное
и только по кнопке человека.

Поля при объединении мастер берёт так: заполненное у оставшейся карточки
не трогает, пустое берёт у объединяемых (_update_values). Архивная 18
станет активной: «Активно» у 159 заполнено, а у 18 — нет.
"""

from odoo import api, models


class PartnerMergeWizard(models.TransientModel):
    _inherit = "base.partner.merge.automatic.wizard"

    @api.model
    def default_get(self, fields):
        result = super().default_get(fields)
        context = self.env.context
        dst = context.get("pmk_merge_dst_id")
        if (dst and "dst_partner_id" in fields and context.get("active_model") == "res.partner"
                and dst in (context.get("active_ids") or [])):
            result["dst_partner_id"] = dst
        return result

    def _merge(self, partner_ids, dst_partner=None, extra_checks=True):
        """Строки «Возможных дублей» объединяемых карточек — убрать.

        Мастер переводит на оставшуюся карточку ВСЕ ссылки на объединяемые,
        в том числе строки нашего экрана (_update_foreign_keys идёт по всем
        внешним ключам на res_partner), и в списке стояли бы две строки
        одной карточки. Группа разобрана — её строки не нужны; остальное
        покажет повторное «Возможные дубли». Ошибка мастера откатит и это."""
        ids = [getattr(item, "id", item) for item in partner_ids or ()]
        if len(ids) > 1:
            self.env["pmk.partner.duplicate"].sudo().search(
                [("partner_id", "in", ids)]).unlink()
        return super()._merge(partner_ids, dst_partner=dst_partner, extra_checks=extra_checks)
