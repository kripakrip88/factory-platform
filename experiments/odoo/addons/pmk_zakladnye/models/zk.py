# -*- coding: utf-8 -*-
"""Документ «Закладные» (ЗК-00001) и его строки — марка, серия, длина, количество.

Состав и масса считаются сразу, в Odoo (модель генератора, доли секунды). Чертёж PDF —
фоновым процессом (job.py → worker/): строка помнит, для какой марки и длины чертёж
нарисован (drawing_key); поменяли марку — чертёж «устарел», рисуется заново.
"""
import json

from odoo import _, api, fields, models

from ..tools import catalog

DRAW_STATES = [("none", "Нет"), ("queued", "В очереди"), ("done", "Готов"),
               ("stale", "Устарел"), ("error", "Ошибка")]


def _fmt(v):
    return ("%g" % v).replace(".", ",")


class ZkCalc(models.Model):
    _name = "pmk.zk.calc"
    _description = "Закладные изделия"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    opportunity_id = fields.Many2one("crm.lead", "Сделка", index=True, tracking=True,
                                     help="Необязательно: к какой сделке закладные.")
    partner_id = fields.Many2one("res.partner", "Клиент", tracking=True)
    object_name = fields.Char("Объект", tracking=True,
                              help="Объект или заказ — свободным текстом («Эстакада ТП-2, ось 3–7»).")
    user_id = fields.Many2one("res.users", "Ответственный", default=lambda self: self.env.user, tracking=True)
    note = fields.Text("Примечание")
    line_ids = fields.One2many("pmk.zk.line", "calc_id", "Изделия", copy=True)
    job_ids = fields.One2many("pmk.zk.job", "calc_id", "Задания на чертежи")

    total_qty = fields.Integer("Изделий, шт", compute="_compute_totals", store=True)
    mark_count = fields.Integer("Марок", compute="_compute_totals", store=True)
    total_weight = fields.Float("Масса всего, кг", compute="_compute_totals", store=True, digits=(12, 1))
    has_warnings = fields.Boolean("Есть пометки", compute="_compute_totals", store=True)
    draw_ready = fields.Integer("Чертежей готово", compute="_compute_draw")
    draw_total = fields.Integer("Чертежей нужно", compute="_compute_draw")
    draw_text = fields.Char("Чертежи", compute="_compute_draw")
    draw_busy = fields.Boolean("Чертежи готовятся", compute="_compute_draw")

    @api.depends("line_ids.qty", "line_ids.mass_one", "line_ids.build_error", "line_ids.parse_error",
                 "line_ids.mark")
    def _compute_totals(self):
        for calc in self:
            good = calc.line_ids.filtered(lambda l: l._zk_ok())
            calc.total_qty = sum(good.mapped("qty"))
            calc.mark_count = len(good)
            calc.total_weight = sum(l.mass_one * l.qty for l in good)
            calc.has_warnings = any(l.parse_error or l.build_error for l in calc.line_ids if l.mark or l.pmk_text)

    @api.depends("line_ids.draw_state", "job_ids.state")
    def _compute_draw(self):
        for calc in self:
            good = calc.line_ids.filtered(lambda l: l._zk_ok())
            calc.draw_total = len(good)
            calc.draw_ready = len(good.filtered(lambda l: l.draw_state == "done"))
            calc.draw_busy = any(j.state in ("queued", "running") for j in calc.job_ids)
            if not good:
                calc.draw_text = False
            elif calc.draw_busy:
                calc.draw_text = _("Готовятся: %(r)d из %(t)d", r=calc.draw_ready, t=calc.draw_total)
            else:
                calc.draw_text = _("Готово %(r)d из %(t)d", r=calc.draw_ready, t=calc.draw_total)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.zk.calc") or "Черновик"
        return super().create(vals_list)

    @api.onchange("opportunity_id")
    def _onchange_opportunity(self):
        for calc in self:
            if calc.opportunity_id and calc.opportunity_id.partner_id:
                calc.partner_id = calc.opportunity_id.partner_id.commercial_partner_id

    def action_zk_save(self):
        """«Сохранить» шапки — форма записывается до вызова; ячейки таблицы и так сохраняются сами."""
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": _("Сохранено"), "type": "success", "sticky": False}}


class ZkLine(models.Model):
    _name = "pmk.zk.line"
    _description = "Закладное изделие — строка"
    _order = "calc_id, sequence, id"

    calc_id = fields.Many2one("pmk.zk.calc", "Документ", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer("№", default=10)
    series = fields.Selection(catalog.SERIES, "Серия")
    mark = fields.Char("Марка", help="Как в серии: «МН 201-5», «М1-9-7».")
    length = fields.Float("Длина, мм", digits=(10, 0), help="Только у погонных (МН 104, 127–132).")
    qty = fields.Integer("Кол-во", default=1)
    pmk_text = fields.Char("Запись", help="Как набрали в таблице, если калькулятор её не понял.")
    parse_error = fields.Char("Не понял")

    full_mark = fields.Char("Изделие", compute="_compute_model", store=True)
    plate = fields.Char("Пластина", compute="_compute_model", store=True)
    anchors = fields.Char("Анкеры", compute="_compute_model", store=True)
    weld = fields.Char("Шов", compute="_compute_model", store=True)
    mass_one = fields.Float("Масса 1 шт, кг", compute="_compute_model", store=True, digits=(12, 2))
    site_mass = fields.Float("Масса по серии, кг", compute="_compute_model", store=True, digits=(12, 2))
    build_error = fields.Char("Не поддержано", compute="_compute_model", store=True)
    warning = fields.Char("Пометки", compute="_compute_model", store=True)
    comp_json = fields.Text("Состав (JSON)", compute="_compute_model", store=True)
    mass_total = fields.Float("Всего, кг", compute="_compute_mass_total", store=True, digits=(12, 1))

    pdf = fields.Binary("Чертёж PDF", attachment=True, copy=False)
    png = fields.Binary("Лист 1 (картинка)", attachment=True, copy=False)
    drawing_key = fields.Char("Чертёж нарисован для", copy=False)
    draw_queued = fields.Boolean("В очереди на чертёж", copy=False)
    draw_error = fields.Char("Ошибка чертежа", copy=False)
    draw_state = fields.Selection(DRAW_STATES, "Чертёж", compute="_compute_draw_state")

    def _zk_key(self):
        self.ensure_one()
        return "%s|%s|%s" % (self.series or "", self.mark or "", _fmt(self.length or 0))

    def _zk_ok(self):
        self.ensure_one()
        return bool(self.mark and self.series and not self.build_error and not self.parse_error)

    @api.depends("series", "mark", "length")
    def _compute_model(self):
        for line in self:
            vals = dict(full_mark=False, plate=False, anchors=False, weld=False, mass_one=0.0,
                        site_mass=0.0, build_error=False, warning=False, comp_json=False)
            if line.mark and line.series:
                M, ms, why = catalog.model(line.series, line.mark, line.length or 0.0)
                if not M:
                    vals["build_error"] = why
                else:
                    info = catalog.summary(M, ms)
                    notes = []
                    if info["warn"]:
                        notes.append(_("Вне табл. 16 ГОСТ 14098 (по решению завода): %s") % "; ".join(info["warn"][:3]))
                    if info["unc"]:
                        notes.append(_("Не подтверждено по листу: %s") % "; ".join(info["unc"][:2]))
                    comp = catalog.composition(M, ms)
                    vals.update(full_mark=info["full_mark"], plate=info["plate"], anchors=info["anchors"],
                                weld=info["weld"], mass_one=info["mass"], site_mass=info["site_mass"] or 0.0,
                                warning=" · ".join(notes) or False,
                                comp_json=json.dumps(comp, ensure_ascii=False))
            line.update(vals)

    @api.depends("mass_one", "qty")
    def _compute_mass_total(self):
        for line in self:
            line.mass_total = (line.mass_one or 0.0) * (line.qty or 0)

    @api.depends("drawing_key", "draw_queued", "draw_error", "series", "mark", "length")
    def _compute_draw_state(self):
        for line in self:
            if line.draw_queued:
                line.draw_state = "queued"
            elif line.draw_error and not line.drawing_key:
                line.draw_state = "error"
            elif not line.drawing_key:
                line.draw_state = "none"
            elif line.drawing_key == line._zk_key():
                line.draw_state = "done"
            else:
                line.draw_state = "stale"

    def _zk_composition(self):
        self.ensure_one()
        try:
            return json.loads(self.comp_json or "[]")
        except ValueError:
            return []

    def _zk_model(self):
        """Модель генератора для чертежа/DXF — заново (в базе её не храним)."""
        self.ensure_one()
        return catalog.model(self.series, self.mark, self.length or 0.0)
