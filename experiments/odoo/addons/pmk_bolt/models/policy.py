# -*- coding: utf-8 -*-
"""Ценовая политика — наценка по сезонам (Антон 21.10.2026: «возможность
проставлять ценовую политику от сезона к сезону, как отдельный справочник»).

Период (с … по) и наценка по виду изделий. Калькулятор берёт политику,
действующую на дату документа: несколько подходят — с самым поздним
началом. Вид пока один — фундаментные болты; зонты, доборка и прочее
добавятся строками того же справочника.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

KINDS = [("bolt", "Фундаментные болты")]


class PricePolicy(models.Model):
    _name = "pmk.price.policy"
    _description = "Ценовая политика"
    _order = "date_from desc, id desc"

    name = fields.Char("Название", required=True, help="Например «Зима 2026/27».")
    date_from = fields.Date("Действует с", required=True)
    date_to = fields.Date("по", help="Пусто — пока не задана следующая.")
    active = fields.Boolean(default=True)
    line_ids = fields.One2many("pmk.price.policy.line", "policy_id", "Наценки")
    note = fields.Text("Заметка")

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_("«По» раньше, чем «с»."))

    @api.model
    def _pmk_markup(self, kind, date):
        """Наценка, % на дату или None — политики нет."""
        date = date or fields.Date.context_today(self)
        lines = self.env["pmk.price.policy.line"].search([
            ("kind", "=", kind), ("policy_id.active", "=", True), ("policy_id.date_from", "<=", date),
            "|", ("policy_id.date_to", "=", False), ("policy_id.date_to", ">=", date)])
        line = lines.sorted(lambda l: (l.policy_id.date_from, l.policy_id.id), reverse=True)[:1]
        return line.markup_pct if line else None


class PricePolicyLine(models.Model):
    _name = "pmk.price.policy.line"
    _description = "Наценка ценовой политики"

    policy_id = fields.Many2one("pmk.price.policy", required=True, ondelete="cascade")
    kind = fields.Selection(KINDS, "Вид изделий", required=True, default="bolt")
    markup_pct = fields.Float("Наценка, %", digits=(6, 1), required=True)

    _kind_uniq = models.Constraint("UNIQUE(policy_id, kind)", "Вид изделий в политике — один раз.")
