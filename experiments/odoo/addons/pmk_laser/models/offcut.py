# -*- coding: utf-8 -*-
"""Обрезок листа: то, что осталось на столе и не должно уехать в лом.

РЕШЕНИЕ ВЛАДЕЛЬЦА: остаток предлагает система, а решает технолог. Системе не
нужно быть умной — она предлагает заготовку, технолог видит лист своими глазами
и правит размер.

Предложение сегодня грубое, и это сказано вслух: точный свободный прямоугольник
считается по геометрии раскладки, а она лежит в двоичной части файла
(Shapes2D/data.bin). Пока считается полоса во всю ширину листа длиной
«габарит × (1 − использование)» — на четвёртом листе отводов (занято 25,6%)
это 1500 x 4400 мм, 518 кг цельного металла, который сейчас списывают в лом.

ПОЧЕМУ ХРАНИМ И ПРЕДЛОЖЕНИЕ, И ПРАВКУ. Разница между тем, что предложила
система, и тем, что намерил технолог, — единственные данные, по которым потом
можно будет понять, стоило ли разбирать двоичную геометрию и насколько
предложение врёт. Стереть предложение правкой значит остаться без этой мерки.

УЧЁТ ПО ГАБАРИТУ, а не по весу — решение владельца. По габариту потом можно
искать «куда влезет этот кусок», по весу нельзя.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import money


class LaserOffcut(models.Model):
    _name = "pmk.laser.offcut"
    _description = "Обрезок листа после резки"
    _order = "job_id, sheet_line_id, id"
    _rec_name = "display_name"

    job_id = fields.Many2one("pmk.laser.job", "Задание", required=True, ondelete="cascade", index=True)
    sheet_line_id = fields.Many2one(
        "pmk.laser.job.sheet", "Лист", ondelete="set null", index=True,
        domain="[('job_id', '=', job_id)]")

    sheet_type = fields.Char(related="job_id.sheet_type", string="Вид листа", store=True, readonly=True)
    thickness_mm = fields.Float(related="job_id.thickness_mm", string="Толщина, мм", store=True, readonly=True)

    width_mm = fields.Float("Ширина, мм", required=True, digits=(8, 0))
    length_mm = fields.Float("Длина, мм", required=True, digits=(8, 0))

    proposed_width_mm = fields.Float("Предложено, ширина", readonly=True, digits=(8, 0))
    proposed_length_mm = fields.Float("Предложено, длина", readonly=True, digits=(8, 0))
    deviation_pct = fields.Float(
        "Правка, %", compute="_compute_metal", store=True, digits=(6, 1),
        help="Насколько технолог поправил предложение системы по площади. "
             "Это мерка качества прикидки: пока правки крупные, точную "
             "геометрию раскладки разбирать рано или наоборот — пора.")

    area_m2 = fields.Float("Площадь, м²", compute="_compute_metal", store=True, digits=(10, 3))
    mass_kg = fields.Float("Масса, кг", compute="_compute_metal", store=True, digits=(12, 1))

    state = fields.Selection(
        [("proposal", "Предложен системой"),
         ("confirmed", "Подтверждён"),
         ("scrap", "Оказался ломом")],
        "Состояние", default="proposal", required=True,
        help="В баланс металла идут только подтверждённые: предложение — ещё "
             "не кусок на стеллаже.")
    note = fields.Char("Примечание")

    display_name = fields.Char(compute="_compute_display_name")

    _size_positive = models.Constraint(
        "CHECK(width_mm > 0 AND length_mm > 0)",
        "У обрезка должны быть оба размера — он учитывается по габариту.",
    )

    @api.depends("width_mm", "length_mm", "job_id.mass_per_sqm",
                 "proposed_width_mm", "proposed_length_mm")
    def _compute_metal(self):
        for offcut in self:
            offcut.area_m2 = money.sheet_area_m2(offcut.width_mm, offcut.length_mm)
            offcut.mass_kg = money.mass_kg(offcut.area_m2, offcut.job_id.mass_per_sqm)
            proposed = money.sheet_area_m2(offcut.proposed_width_mm, offcut.proposed_length_mm)
            offcut.deviation_pct = (
                100.0 * (offcut.area_m2 - proposed) / proposed if proposed else 0.0)

    @api.depends("width_mm", "length_mm", "thickness_mm", "sheet_type")
    def _compute_display_name(self):
        for offcut in self:
            offcut.display_name = _("Обрезок %(w).0fx%(l).0f, %(type)s %(thick)g мм") % {
                "w": offcut.width_mm, "l": offcut.length_mm,
                "type": (offcut.sheet_type or "лист").lower(), "thick": offcut.thickness_mm,
            }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Запоминаем предложение в момент создания: дальше технолог правит
            # размеры, и без этого снимка сравнивать будет не с чем.
            vals.setdefault("proposed_width_mm", vals.get("width_mm", 0.0))
            vals.setdefault("proposed_length_mm", vals.get("length_mm", 0.0))
        return super().create(vals_list)

    def action_confirm(self):
        """Технолог посмотрел на лист и подтвердил размер."""
        for offcut in self:
            if offcut.state == "confirmed":
                raise UserError(_("Обрезок «%s» уже подтверждён") % offcut.display_name)
            offcut.state = "confirmed"
        return True

    def action_scrap(self):
        """Куска не вышло — уходит в лом вместе с остальным отходом."""
        self.write({"state": "scrap"})
        return True
