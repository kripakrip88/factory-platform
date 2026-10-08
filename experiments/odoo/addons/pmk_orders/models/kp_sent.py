# -*- coding: utf-8 -*-
"""«Отправить КП» → счёт ЭТОГО расчёта «Отправлен» (шаги З-2 и З-9).

После настоящей отправки КП людям клиента (pmk_deal/models/kp_sent.py, шаг
33) мост зовёт _pmk_kp_move_stage: сделка переходит в «КП отправлено». Счёт
отмечаем отправленным по тому расчёту, КП которого ушло, а не по главному: у
сделки их бывает несколько (crm_lead.py, _pmk_invoice_kp_sent).

Переход стадии идёт с контекстом pmk_orders_skip — иначе write сделки принял
бы его за перенос руками («отправлен вне системы»). Сделка уже стояла в «КП
отправлено» (повторная отправка изменённого КП) — стадия не меняется, и write
не сработал бы вовсе: поэтому счёт (или его новая редакция) — здесь, явно.

Выигранную и проигранную сделку не трогаем: у выигранной счёт уже в работе,
у проигранной — отменён (вернуть — восстановить сделку и снова «КП
отправлено»).
"""
from odoo import models

from odoo.addons.pmk_deal.models.kp_sent import KP_SENT_STAGE

from .sale_order import SKIP


class MetalSpecKpInvoice(models.Model):
    _inherit = "pmk.metal.spec"

    def _pmk_kp_move_stage(self, deal):
        moved = super()._pmk_kp_move_stage(deal.with_context(**{SKIP: True}))
        target = self.env.ref(KP_SENT_STAGE, raise_if_not_found=False)
        if (target and deal.type == "opportunity" and deal.active
                and deal.won_status == "pending" and deal.stage_id == target):
            deal._pmk_orders_safely("_pmk_invoice_kp_sent", self)
        return moved
