# -*- coding: utf-8 -*-
"""Вентзонты: развёртки для лазера (DXF) и спецификация на зонт.

Вся геометрия и все числа — в tools/vent_hood.py. Это генератор Антона,
перенесённый КАК ЕСТЬ, файл в файл (11.10.2026): правила сняты с 25 шаблонов
КОМПАС и сверены до 0.01 мм, по DXF режет лазер. Здесь формул нет — модель
только передаёт генератору размер шахты, толщину и цвет и показывает ответ.
Сверка переноса — тест test_vent_hood.py (51 эталон, tests/vent_hood_golden).
Правила меняются только в генераторе и только через его --regen и сверку с
шаблонами (README генератора, раздел 6).

Толщина и цвет — из тех же справочников, что у доборки (решение Антона
11.10.2026: «справочник для доборки и вентзонтов один и тот же»): металл —
оцинкованный лист справочника «Лист», цвет — «Цвета доборки (RAL)». Толщина
и цвет геометрию не меняют (DXF байт в байт тот же), меняют материал, массу
и предупреждения.
"""

import json

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.pmk_calc.tools import vent_hood as V


class VentHood(models.Model):
    _name = "pmk.vent.hood"
    _description = "Вентзонт"
    _inherit = ["mail.thread"]
    _order = "order_date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    partner_id = fields.Many2one("res.partner", "Клиент", tracking=True)
    customer = fields.Char("Изделие / объект", tracking=True,
                           help="На какой объект (адрес, дом). Клиент — полем «Клиент».")
    order_date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    state = fields.Selection(
        [("draft", "Черновик"), ("confirmed", "В работе"), ("done", "Изготовлен")],
        "Статус", default="draft", tracking=True)

    width = fields.Integer(
        "Ширина шахты, мм", tracking=True,
        help="Короткая сторона шахты: в обозначении «вш Ш×Д» Ш ≤ Д, конёк идёт "
             "вдоль длинной стороны.")
    length = fields.Integer("Длина шахты, мм", tracking=True)
    qty = fields.Integer("Количество, шт", default=1, tracking=True)

    # Тот же справочник и тот же отбор, что у доборки (pmk.dobor.order.line):
    # только оцинковка. Толщина приходит из металла.
    sheet_id = fields.Many2one(
        "pmk.metal.sheet", "Металл", tracking=True,
        domain=[("sheet_type", "=", "Оцинкованный")],
        help="Оцинкованный лист из справочника «Лист» — тот же список, что у доборки.")
    thickness = fields.Float("Толщина, мм", related="sheet_id.thickness_mm", store=True,
                             digits=(6, 2))
    coating_id = fields.Many2one(
        "pmk.dobor.coating", "Цвет", tracking=True,
        default=lambda self: self._default_coating(),
        help="Цинк или RAL — справочник «Цвета доборки (RAL)», общий с доборкой.")

    # Ответ генератора. Хранится: список и итоги считаются без генератора.
    spec_json = fields.Text("Спецификация (JSON)", compute="_compute_spec", store=True)
    spec_error = fields.Char("Ошибка размера", compute="_compute_spec", store=True)
    hood_label = fields.Char("Зонт", compute="_compute_spec", store=True)
    material_name = fields.Char("Материал", compute="_compute_spec", store=True)
    panels = fields.Integer("Панелей", compute="_compute_spec", store=True)
    layout = fields.Char("Раскладка", compute="_compute_spec", store=True)
    lapki = fields.Integer("Лапок на зонт", compute="_compute_spec", store=True)
    klepki = fields.Integer("Клёпок на зонт", compute="_compute_spec", store=True)
    metal_net_m2 = fields.Float("Металл нетто, м²", compute="_compute_spec", store=True,
                                digits=(12, 3))
    sheet_1250_m = fields.Float("Лист 1250, пог. м", compute="_compute_spec", store=True,
                                digits=(12, 2))
    mass_net_kg = fields.Float("Вес деталей, кг", compute="_compute_spec", store=True,
                               digits=(12, 1))
    mass_sheet_kg = fields.Float("Вес листа по расходу, кг", compute="_compute_spec",
                                 store=True, digits=(12, 1))
    total_mass_net_kg = fields.Float("Вес деталей всего, кг", compute="_compute_spec",
                                     store=True, digits=(12, 1))
    total_sheet_1250_m = fields.Float("Лист 1250 всего, пог. м", compute="_compute_spec",
                                      store=True, digits=(12, 2))

    subtitle = fields.Char("Зонт и материал", compute="_compute_subtitle")
    spec_html = fields.Html("Детали", compute="_compute_spec_html", sanitize=False)
    warnings_text = fields.Text("Предупреждения", compute="_compute_spec_html")

    def _default_coating(self):
        zinc = self.env.ref("pmk_calc.coating_zinc", raise_if_not_found=False)
        if zinc:
            return zinc.id
        return self.env["pmk.dobor.coating"].search([("name", "=ilike", "Цинк")], limit=1).id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.vent.hood") or "Черновик"
        return super().create(vals_list)

    # ── генератор ────────────────────────────────────────────────────────

    def _vh_color(self):
        """Цвет для генератора: None — оцинковка, иначе код RAL."""
        self.ensure_one()
        return (self.coating_id.ral_code or "").strip() or None

    def _vh_thickness(self):
        self.ensure_one()
        return self.thickness or None

    def _vh_geometry(self):
        """hood() генератора; ValueError — размер невозможен (Ш > Д, ≤ 0)."""
        self.ensure_one()
        return V.hood(self.width, self.length)

    def _vh_spec(self):
        self.ensure_one()
        return json.loads(self.spec_json) if self.spec_json else {}

    @api.depends("width", "length", "qty", "thickness", "coating_id.ral_code")
    def _compute_spec(self):
        empty = dict(spec_json=False, hood_label=False, material_name=False, panels=0,
                     layout=False, lapki=0, klepki=0, metal_net_m2=0.0, sheet_1250_m=0.0,
                     mass_net_kg=0.0, mass_sheet_kg=0.0, total_mass_net_kg=0.0,
                     total_sheet_1250_m=0.0)
        for rec in self:
            rec.update(dict(empty, spec_error=False))
            if not rec.width or not rec.length:
                continue
            try:
                g = rec._vh_geometry()
                s = V.spec(g, rec._vh_thickness(), rec._vh_color())
            except ValueError as e:
                rec.spec_error = str(e)
                continue
            qty = rec.qty or 0
            rec.update({
                "spec_json": json.dumps(s, ensure_ascii=False),
                "hood_label": s["hood"],
                "material_name": s["material"]["full_name"],
                "panels": s["panels"],
                "layout": s["layout"],
                "lapki": s["lapki"],
                "klepki": s["klepki"],
                "metal_net_m2": s["metal_net_m2"],
                "sheet_1250_m": s["sheet_1250_m"],
                "mass_net_kg": s.get("mass_net_kg", 0.0),
                "mass_sheet_kg": s.get("mass_sheet_kg", 0.0),
                "total_mass_net_kg": s.get("mass_net_kg", 0.0) * qty,
                "total_sheet_1250_m": s["sheet_1250_m"] * qty,
            })

    @api.depends("hood_label", "material_name")
    def _compute_subtitle(self):
        for rec in self:
            rec.subtitle = " · ".join(filter(None, [rec.hood_label, rec.material_name])) or False

    @api.depends("spec_json", "spec_error", "qty")
    def _compute_spec_html(self):
        for rec in self:
            s = rec._vh_spec()
            if not s:
                rec.spec_html = False
                rec.warnings_text = False
                continue
            qty = rec.qty or 0
            rows = Markup("").join(
                Markup("<tr><td>%s</td><td class='text-end'>%s × %s</td>"
                       "<td class='text-end'>%s</td><td class='text-end'>%s</td>"
                       "<td class='text-end'>%s</td></tr>") % (
                    p["name"], _num(p["size_mm"][0]), _num(p["size_mm"][1]), p["qty"],
                    p["qty"] * qty, _num(p["area_m2_each"], 4))
                for p in s["parts"])
            head = Markup(
                "<thead><tr><th>Деталь</th><th class='text-end'>Заготовка, мм</th>"
                "<th class='text-end'>На зонт, шт</th><th class='text-end'>Всего, шт</th>"
                "<th class='text-end'>Площадь шт, м²</th></tr></thead>")
            rec.spec_html = Markup(
                "<table class='table table-sm o_pmk_vh_parts'>%s<tbody>%s</tbody></table>"
            ) % (head, rows)
            rec.warnings_text = "\n".join(s["rule_flags"] + s["material"]["warnings"]) or False

    # ── действия ─────────────────────────────────────────────────────────

    def action_download_dxf(self):
        """DXF развёрток для лазера — файлом во вложениях и сразу скачать."""
        self.ensure_one()
        if not self.width or not self.length:
            raise UserError("Укажите ширину и длину шахты.")
        try:
            g = self._vh_geometry()
        except ValueError as e:
            raise UserError("Размер не подходит: %s" % e) from None
        fname = V.out_name(self.width, self.length, self._vh_thickness(), self._vh_color())
        data = V.to_dxf(g).encode("utf-8")
        Attachment = self.env["ir.attachment"]
        old = Attachment.search([("res_model", "=", self._name), ("res_id", "=", self.id),
                                 ("name", "=", fname)])
        old.unlink()
        att = Attachment.create({
            "name": fname, "raw": data, "mimetype": "application/dxf",
            "res_model": self._name, "res_id": self.id,
        })
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/web/content/%s?download=true" % att.id}


def _num(value, digits=1):
    """Число по-русски: запятая, без хвостовых нулей до digits знаков."""
    text = ("%.*f" % (digits, value)).rstrip("0").rstrip(".")
    return escape(text.replace(".", ","))
