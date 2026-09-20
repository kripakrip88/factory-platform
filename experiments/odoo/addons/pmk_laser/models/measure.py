# -*- coding: utf-8 -*-
"""Реальный замер резки листа.

ДВА КАСАНИЯ. От оператора требуется ровно две кнопки: «начал» и «закончил».
Всё остальное — станок, материал, толщина, заказ, длина реза, проколы —
подставляется из задания. Это не удобство, а условие работоспособности: если
оператору вбивать семь полей, он не будет, и замеров не появится вовсе, а без
замеров весь участок остаётся без нормативов.

ЧТО СЧИТАЕТСЯ ИЗ ДВУХ КАСАНИЙ:

    полное время листа   = «закончил» − «начал»
    чистое время резки   = полное − загрузка стола − разгрузка стола

Загрузка и разгрузка — константы станка на лист (см. machine.py). Вычитаются
они здесь, а не в нормативе, чтобы в норматив попадало уже сопоставимое время:
станок с гидроподъёмником и станок без него дают разное полное время при
одинаковой резке.

ПОЧЕМУ ЕСТЬ ГАЛКА «НЕ УЧИТЫВАТЬ». Один обед внутри замера портит норматив
навсегда: скорость упадёт вдвое и останется такой, пока кто-нибудь не заметит.
Убирает замер из статистики мастер, а не оператор, и с причиной — так видно,
сколько замеров выкинуто и почему.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

SECONDS_IN_MINUTE = 60.0


class LaserMeasure(models.Model):
    _name = "pmk.laser.measure"
    _description = "Замер резки листа"
    _order = "started_at desc, id desc"
    _rec_name = "display_name"

    job_id = fields.Many2one("pmk.laser.job", "Задание", required=True, ondelete="cascade", index=True)
    sheet_line_id = fields.Many2one(
        "pmk.laser.job.sheet", "Лист", required=True, ondelete="cascade", index=True,
        domain="[('job_id', '=', job_id)]")
    operator_id = fields.Many2one("hr.employee", "Оператор")

    started_at = fields.Datetime("Начал", readonly=True, copy=False)
    finished_at = fields.Datetime("Закончил", readonly=True, copy=False)

    # Всё, что ниже — из задания. Хранимые копии, а не related: норматив
    # группирует замеры по станку, виду листа и толщине, и делать это через
    # цепочку в три таблицы на каждой выборке незачем. Плюс исторический смысл:
    # если через год в задании поменяют марку, старый замер не должен
    # переехать в другую группу.
    machine_id = fields.Many2one(
        "pmk.laser.machine", "Станок", compute="_compute_from_job", store=True, index=True)
    sheet_type = fields.Char("Вид листа", compute="_compute_from_job", store=True)
    thickness_mm = fields.Float("Толщина, мм", compute="_compute_from_job", store=True, digits=(6, 2))

    duration_minutes = fields.Float("Лист занял, мин", compute="_compute_duration", store=True, digits=(8, 1))
    cut_minutes = fields.Float(
        "Чистая резка, мин", compute="_compute_duration", store=True, digits=(8, 1),
        help="Полное время листа минус загрузка и разгрузка стола. Именно эта "
             "величина идёт в норматив.")
    state = fields.Selection(
        [("waiting", "Не начат"), ("running", "Режет"), ("done", "Закончен")],
        "Состояние", compute="_compute_duration", store=True, default="waiting")

    excluded = fields.Boolean(
        "Не учитывать в нормативе",
        help="Ставит мастер, когда внутри замера был обед, поломка или чужой "
             "лист. Замер остаётся в истории, но в норматив не идёт.")
    exclude_reason = fields.Char("Почему не учитывать")

    display_name = fields.Char(compute="_compute_display_name")

    _finish_after_start = models.Constraint(
        "CHECK(finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)",
        "«Закончил» не может быть раньше, чем «начал».",
    )

    @api.depends("job_id.machine_id", "job_id.sheet_type", "job_id.thickness_mm")
    def _compute_from_job(self):
        for measure in self:
            measure.machine_id = measure.job_id.machine_id
            measure.sheet_type = measure.job_id.sheet_type
            measure.thickness_mm = measure.job_id.thickness_mm

    @api.depends("started_at", "finished_at",
                 "machine_id.load_min", "machine_id.unload_min")
    def _compute_duration(self):
        for measure in self:
            if not measure.started_at:
                measure.state = "waiting"
                measure.duration_minutes = 0.0
                measure.cut_minutes = 0.0
                continue
            if not measure.finished_at:
                measure.state = "running"
                measure.duration_minutes = 0.0
                measure.cut_minutes = 0.0
                continue
            machine = measure.machine_id
            measure.state = "done"
            measure.duration_minutes = (
                measure.finished_at - measure.started_at).total_seconds() / SECONDS_IN_MINUTE
            # Может выйти отрицательным на очень коротком листе, если константы
            # станка завышены. Оставляем как есть: это сигнал, что загрузку и
            # разгрузку пора перемерить, а не повод молча подставить ноль.
            measure.cut_minutes = measure.duration_minutes - machine.load_min - machine.unload_min

    @api.depends("job_id.name", "sheet_line_id.number")
    def _compute_display_name(self):
        for measure in self:
            measure.display_name = _("%(job)s, лист %(sheet)s") % {
                "job": measure.job_id.name or "",
                "sheet": measure.sheet_line_id.number or 0,
            }

    def action_start(self):
        """Касание первое."""
        for measure in self:
            if measure.started_at:
                raise UserError(_("Замер уже начат в %s") % measure.started_at)
            measure.started_at = fields.Datetime.now()
        return True

    def action_finish(self):
        """Касание второе."""
        for measure in self:
            if not measure.started_at:
                raise UserError(_("Сначала «начал», потом «закончил»"))
            if measure.finished_at:
                raise UserError(_("Замер уже закрыт в %s") % measure.finished_at)
            measure.finished_at = fields.Datetime.now()
        return True
