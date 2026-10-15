# -*- coding: utf-8 -*-
"""Раскрой-документ (pmk.laser.nest): кнопки на все толщины сразу (15.10.2026).

Каждая программа по толщине считается своим прогоном (models/run.py) в общей очереди —
«Рассчитать все» ставит их в очередь подряд, движок считает по одному.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LaserNest(models.Model):
    _inherit = "pmk.laser.nest"

    nest_busy = fields.Boolean("Считается", compute="_compute_nest_flags")
    nest_can_build_any = fields.Boolean(compute="_compute_nest_flags")
    nest_can_accept_any = fields.Boolean(compute="_compute_nest_flags")

    @api.depends("program_ids.nest_busy", "program_ids.nest_can_build", "program_ids.nest_can_accept")
    def _compute_nest_flags(self):
        for nest in self:
            progs = nest.program_ids
            nest.nest_busy = any(progs.mapped("nest_busy"))
            nest.nest_can_build_any = any(progs.mapped("nest_can_build"))
            nest.nest_can_accept_any = any(progs.mapped("nest_can_accept"))

    def _each(self, progs, method, done_word):
        ok, errors = [], []
        for prog in progs:
            try:
                getattr(prog, method)()
                ok.append(prog.name)
            except UserError as e:
                errors.append("%s: %s" % (prog.name, e.args[0] if e.args else e))
        if not ok and errors:
            raise UserError("\n".join(errors))
        msg = _("%(w)s: %(n)s.") % {"w": done_word, "n": ", ".join(ok)}
        if errors:
            msg += " " + _("Не получилось: %s") % "; ".join(errors)
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "warning" if errors else "info", "title": self.name, "message": msg, "sticky": bool(errors),
            "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def action_nest_plan_all(self):
        self.ensure_one()
        progs = self.program_ids.filtered(lambda p: p.part_ids and not p.nest_busy and not p.sheet_ids)
        if not progs:
            raise UserError(_("Считать нечего: у программ нет деталей, они уже считаются или приняты."))
        return self._each(progs, "action_nest_plan", _("Раскрой считается в фоне"))

    def action_nest_build_all(self):
        self.ensure_one()
        progs = self.program_ids.filtered("nest_can_build")
        if not progs:
            raise UserError(_("Собирать нечего: сначала «Рассчитать все» и выберите порядок резки в каждой "
                              "программе."))
        return self._each(progs, "action_nest_build", _("Программы собираются в фоне"))

    def action_nest_accept_all(self):
        self.ensure_one()
        progs = self.program_ids.filtered("nest_can_accept")
        if not progs:
            raise UserError(_("Принимать нечего: соберите программы."))
        return self._each(progs, "action_nest_accept", _("Принято в очередь листов"))
