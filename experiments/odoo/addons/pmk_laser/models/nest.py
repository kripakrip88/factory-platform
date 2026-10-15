# -*- coding: utf-8 -*-
"""Раскрой (РС) — один документ, детали любых толщин одного или нескольких заказов
(Антон 15.10.2026: «в одном документе сформировать несколько lxds, как с зонтами»).

Внутри — ПРОГРАММЫ по толщине и виду листа (pmk.laser.job): каждая — свой лист, своя
программа CypCut .lxds, свои листы в «Очереди листов», замеры, норматив, премия, баланс.
Это прежняя проверенная математика участка — документ раскроя её только собирает: детали
раскладываются по программам сами (одна толщина и вид листа — одна программа), итоги
складываются.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .task import DEFAULT_SHEET_TYPE, _kg, _mm


class LaserNest(models.Model):
    _name = "pmk.laser.nest"
    _description = "Раскрой"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    active = fields.Boolean("Активен", default=True)
    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    machine_id = fields.Many2one("pmk.laser.machine", "Станок",
                                 help="Для новых программ. Толщину, которую станок не тянет, программа возьмёт "
                                      "на другой станок; у каждой программы станок можно сменить.")
    note = fields.Char("Примечание")
    program_ids = fields.One2many("pmk.laser.job", "nest_id", "Программы по толщинам")
    program_count = fields.Integer("Программ", compute="_compute_totals")
    task_ids = fields.Many2many("pmk.laser.task", string="Задания на резку", compute="_compute_totals")
    task_text = fields.Char("Заказы", compute="_compute_totals")
    thickness_text = fields.Char("Толщины", compute="_compute_totals", store=True)
    sheet_count = fields.Integer("Листов", compute="_compute_totals", store=True)
    sheets_cut = fields.Integer("Порезано листов", compute="_compute_totals", store=True)
    useful_mass_kg = fields.Float("Полезный вес, кг", compute="_compute_totals", store=True, digits=(12, 1))
    mass_kg = fields.Float("Списано металла, кг", compute="_compute_totals", store=True, digits=(12, 1))
    premium_rub = fields.Float("Премия, ₽", compute="_compute_totals", store=True, digits=(10, 0))
    qty_total = fields.Integer("Деталей, шт", compute="_compute_totals", store=True)
    state_text = fields.Char("Состояние", compute="_compute_totals")
    state = fields.Selection([("draft", "Раскладывается"), ("queue", "В очереди"), ("work", "Режется"),
                              ("done", "Порезан")], "Состояние", compute="_compute_totals", store=True)

    @api.depends("program_ids.thickness_mm", "program_ids.sheet_count", "program_ids.sheet_ids.cut_state",
                 "program_ids.useful_mass_kg", "program_ids.mass_kg", "program_ids.premium_rub",
                 "program_ids.part_ids.qty", "program_ids.part_ids.task_part_id")
    def _compute_totals(self):
        for nest in self:
            progs = nest.program_ids
            nest.program_count = len(progs)
            tasks = progs.part_ids.task_part_id.task_id
            nest.task_ids = tasks
            nest.task_text = ", ".join(
                "%s%s" % (t.name, " · %s" % t.partner_id.display_name if t.partner_id else "") for t in tasks
            ) or False
            nest.thickness_text = ", ".join(
                "%s мм" % _mm(t) for t in sorted({round(p.thickness_mm, 2) for p in progs if p.thickness_mm})
            ) or False
            sheets = progs.sheet_ids
            nest.sheet_count = len(sheets)
            nest.sheets_cut = len(sheets.filtered(lambda s: s.cut_state == "done"))
            nest.useful_mass_kg = sum(progs.mapped("useful_mass_kg"))
            nest.mass_kg = sum(progs.mapped("mass_kg"))
            nest.premium_rub = sum(progs.mapped("premium_rub"))
            nest.qty_total = sum(progs.part_ids.mapped("qty"))
            if not sheets:
                nest.state = "draft"
            elif nest.sheets_cut >= len(sheets):
                nest.state = "done"
            elif nest.sheets_cut or sheets.filtered(lambda s: s.cut_state == "running"):
                nest.state = "work"
            else:
                nest.state = "queue"
            nest.state_text = "%s · листов %d из %d · %s кг" % (
                dict(nest._fields["state"].selection)[nest.state], nest.sheets_cut, nest.sheet_count,
                _kg(nest.useful_mass_kg)) if sheets else "Раскладывается"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.laser.nest") or "Черновик"
        return super().create(vals_list)

    def _program_for(self, thickness_mm, sheet_type):
        """Программа этой толщины и вида листа: открытая (листов ещё нет) — она же, иначе новая."""
        self.ensure_one()
        Job = self.env["pmk.laser.job"]
        sheet = Job._sheet_for(thickness_mm, sheet_type or DEFAULT_SHEET_TYPE)
        prog = self.program_ids.filtered(lambda p: p.sheet_id == sheet and not p.sheet_ids)[:1]
        if prog:
            return prog
        machine = self.machine_id
        if not machine or (machine.max_thickness_mm and machine.max_thickness_mm < thickness_mm):
            machine = self.env["pmk.laser.machine"]._for_thickness(thickness_mm)
        return Job.create({"nest_id": self.id, "machine_id": machine.id, "sheet_id": sheet.id,
                           "date": self.date})

    def _add_task_parts(self, parts):
        """Детали заданий → по программам своей толщины и вида листа (создаются сами)."""
        self.ensure_one()
        parts = parts.filtered(lambda p: p.qty_left > 0)
        groups = {}
        for part in parts:
            key = (round(part.thickness_mm, 3), (part.sheet_type or DEFAULT_SHEET_TYPE).strip().lower())
            groups.setdefault(key, self.env["pmk.laser.task.part"])
            groups[key] |= part
        for (thickness, _kind), group in sorted(groups.items()):
            self._program_for(thickness, group[0].sheet_type)._add_task_parts(group)
        return True

    def action_open_programs(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("pmk_laser.action_laser_job")
        action["domain"] = [("nest_id", "=", self.id)]
        action["name"] = _("Программы %s") % self.name
        return action

    def action_add_parts(self):
        """«Добавить детали» — «Детали к раскрою» с отбором неразложенных."""
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("pmk_laser.action_laser_parts_to_nest")
        action["context"] = dict(self.env.context, search_default_left=1, search_default_group_thickness=1,
                                 pmk_target_nest=self.id)
        return action


class LaserJobNest(models.Model):
    """Программа раскроя (бывшее «задание лазеру») — внутри документа «Раскрой»."""
    _inherit = "pmk.laser.job"

    nest_id = fields.Many2one("pmk.laser.nest", "Раскрой", index=True, ondelete="cascade")
    parts_text = fields.Char("Детали", compute="_compute_parts_text")

    @api.depends("part_ids.qty")
    def _compute_parts_text(self):
        for job in self:
            n = len(job.part_ids)
            job.parts_text = ("%d дет. · %d шт" % (n, sum(job.part_ids.mapped("qty")))) if n else False

    @api.model_create_multi
    def create(self, vals_list):
        nests = self.env["pmk.laser.nest"]
        for vals in vals_list:
            if vals.get("nest_id") and vals.get("name", "Черновик") == "Черновик":
                nest = nests.browse(vals["nest_id"])
                sheet = self.env["pmk.metal.sheet"].browse(vals.get("sheet_id"))
                vals["name"] = "%s · %s мм" % (nest.name, _mm(sheet.thickness_mm)) if sheet else nest.name
        return super().create(vals_list)


class LaserTaskPartNest(models.Model):
    _inherit = "pmk.laser.task.part"

    def action_create_nest(self):
        """«Создать раскрой» — один документ, детали любых толщин (хоть из разных заказов):
        программы по толщинам раскладываются сами. Открыт из раскроя («Добавить детали») —
        добавляем в него."""
        self._check_for_nest(mixed=True)
        target = self.env.context.get("pmk_target_nest")
        nest = self.env["pmk.laser.nest"].browse(target) if target else self.env["pmk.laser.nest"].create({})
        nest._add_task_parts(self)
        return {"type": "ir.actions.act_window", "res_model": "pmk.laser.nest", "res_id": nest.id,
                "views": [[False, "form"]], "target": "current"}

    def action_add_to_nest(self):
        self._check_for_nest(mixed=True)
        return {
            "type": "ir.actions.act_window", "res_model": "pmk.laser.add.to.nest", "view_mode": "form",
            "target": "new", "name": _("Добавить в раскрой"),
            "context": {"default_part_ids": self.ids},
        }


class LaserTaskNest(models.Model):
    _inherit = "pmk.laser.task"

    nest_ids = fields.Many2many("pmk.laser.nest", string="Раскрои", compute="_compute_nest_ids")

    @api.depends("part_ids.line_ids.job_id.nest_id")
    def _compute_nest_ids(self):
        for task in self:
            task.nest_ids = task.part_ids.line_ids.job_id.nest_id

    def action_nest_all(self):
        """«Разложить» — все неразложенные детали задания в новый раскрой."""
        self.ensure_one()
        parts = self.part_ids.filtered(lambda p: p.qty_left > 0)
        if not parts:
            raise UserError(_("Все детали задания уже в раскроях."))
        return parts.action_create_nest()
