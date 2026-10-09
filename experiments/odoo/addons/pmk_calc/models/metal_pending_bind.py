# -*- coding: utf-8 -*-
"""Окно «Привязать к существующей» (шаг З-10).

Позиция «на разнос» оказалась той, что в справочнике уже есть под другим
названием («Уголок 75×6 09Г2С» = «Уголок равнополочный 75x6»). Выбираем
настоящую позицию того же вида — во всех деталях всех расчётов (и в
раскроях, заданиях лазеру, доборках) временная заменяется ею, в ленту
расчётов — заметка, временная уходит в архив (metal_pending.py,
_pmk_pending_bind). Окно — только у администратора справочника.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError

from .metal_pending_report import KINDS


class MetalPendingBind(models.TransientModel):
    _name = "pmk.metal.pending.bind"
    _description = "Привязать позицию на разнос к существующей"

    source_model = fields.Char("Справочник", required=True, readonly=True)
    source_id = fields.Integer("Позиция", required=True, readonly=True)
    kind = fields.Selection(KINDS, "Вид", readonly=True)
    source_name = fields.Char("Позиция на разнос", readonly=True)
    usage_text = fields.Char("Где стоит", readonly=True)
    # Отбор — только настоящие позиции: «на разнос» к «на разнос» не вяжут.
    # Подсказка — тот же умный поиск, что в детали («уг 75 6»); строки
    # «завести новую» здесь нет (нет ключа pmk_pending_create в контексте).
    profile_id = fields.Many2one(
        "pmk.metal.profile", "Позиция справочника", domain=[("pmk_pending", "=", False)])
    sheet_id = fields.Many2one(
        "pmk.metal.sheet", "Позиция справочника", domain=[("pmk_pending", "=", False)])
    fastener_id = fields.Many2one(
        "pmk.metal.fastener", "Позиция справочника", domain=[("pmk_pending", "=", False)])

    def _target(self):
        self.ensure_one()
        return {"linear": self.profile_id, "sheet": self.sheet_id,
                "fastener": self.fastener_id}.get(self.kind)

    def action_bind(self):
        self.ensure_one()
        source = self.env[self.source_model].browse(self.source_id).exists()
        if not source:
            raise UserError(_("Позиции уже нет — обновите список."))
        target = self._target()
        if not target:
            raise UserError(_("Выберите позицию справочника, к которой привязать."))
        count = source._pmk_pending_bind(target)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("«%(old)s» заменена на «%(new)s»: деталей — %(count)s. "
                             "Временная позиция — в архиве.",
                             old=self.source_name, new=target.display_name, count=count),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
