# -*- coding: utf-8 -*-
"""Калькулятор фундаментных болтов (Антон 21.10.2026).

Отдельный документ в «Калькуляторах», как зонты: сначала считаем болты сами
по себе, потом встраиваем в счёт и расчёт («сначала собрал отдельный
калькулятор… а потом ввёл его в документы»).

Строка — один болт: тип, М, длина, резьба, сталь, количество, гайки.
- Название — одним видом, с длиной резьбы («часто просят удлинённую»).
- Масса — по приложению А ГОСТ; длина не из ряда — по формуле, с пометкой.
- Себестоимость: круг (заготовка по правилу цеха, 2d на гиб) + плита и шайба
  из листа + работа по нормам (резьба, гиб, проточка) + гайки — цену гайки
  вписывает Владимир («угадай мелодию»), рядом — последняя вписанная цена
  гайки того же М и вида («накопим статистику и сможем предлагать цену»).
- Цена = себестоимость × (1 + наценка ценовой политики); правится руками.
- Подсказка — прошлые продажи этого размера (строки счетов МоегоСклада).
"""
import re

from odoo import _, api, fields, models

from ..tools import gost

STEELS = [("Ст3", "Ст3"), ("09Г2С", "09Г2С")]
NUT_KINDS = [("plain", "обычные"), ("hardened", "калёные"), ("special", "спецсталь")]
DIAMETERS = [(str(d), "М%s" % d) for d in sorted(gost.SIZES)]


class BoltCalc(models.Model):
    _name = "pmk.bolt.calc"
    _description = "Расчёт фундаментных болтов"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one("res.partner", "Контрагент", tracking=True)
    opportunity_id = fields.Many2one("crm.lead", "Сделка", tracking=True)
    user_id = fields.Many2one("res.users", "Ответственный", default=lambda self: self.env.user, tracking=True)
    note = fields.Char("Объект, примечание")
    line_ids = fields.One2many("pmk.bolt.line", "calc_id", "Болты", copy=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    total_qty = fields.Integer("Болтов, шт", compute="_compute_totals", store=True)
    total_weight = fields.Float("Вес, кг", compute="_compute_totals", store=True, digits=(12, 1))
    total_cost = fields.Float("Себестоимость", digits=(12, 2), compute="_compute_totals", store=True)
    amount_total = fields.Float("Сумма", digits=(12, 2), compute="_compute_totals", store=True)
    margin_pct = fields.Float("Маржа, %", compute="_compute_totals", store=True, digits=(5, 1))
    has_warnings = fields.Boolean(compute="_compute_totals", store=True)

    @api.depends("line_ids.qty", "line_ids.mass_one", "line_ids.cost_one", "line_ids.price_total",
                 "line_ids.warning")
    def _compute_totals(self):
        for calc in self:
            lines = calc.line_ids
            calc.total_qty = sum(lines.mapped("qty"))
            calc.total_weight = sum(l.mass_one * l.qty for l in lines)
            calc.total_cost = sum(l.cost_one * l.qty for l in lines)
            calc.amount_total = sum(lines.mapped("price_total"))
            calc.margin_pct = ((calc.amount_total - calc.total_cost) / calc.amount_total * 100.0
                               if calc.amount_total else 0.0)
            calc.has_warnings = any(lines.mapped("warning"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.bolt.calc") or "Черновик"
        return super().create(vals_list)


class BoltLine(models.Model):
    _name = "pmk.bolt.line"
    _description = "Фундаментный болт"
    _order = "calc_id, sequence, id"

    calc_id = fields.Many2one("pmk.bolt.calc", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(related="calc_id.currency_id")
    bolt_type = fields.Selection([(k, v["label"]) for k, v in gost.TYPES.items()], "Тип", required=True,
                                 default="1.1")
    diameter = fields.Selection(DIAMETERS, "Диаметр", required=True, default="24")
    length = fields.Integer("Длина L, мм", required=True, default=1000)
    thread_len = fields.Integer("Резьба, мм", compute="_compute_thread_len", store=True, readonly=False,
                                help="По ГОСТ — по диаметру; можно длиннее («удлинённая резьба»).")
    steel = fields.Selection(STEELS, "Сталь", required=True, default="09Г2С")
    qty = fields.Integer("Кол-во, шт", required=True, default=1)
    nut_kind = fields.Selection(NUT_KINDS, "Гайки", required=True, default="plain")
    nut_price = fields.Float("Гайка, ₽/шт", digits=(12, 2), help="Вписывает менеджер: гайки бывают разные.")
    nut_hint = fields.Char("Прошлая цена гайки", compute="_compute_nut_hint")
    metal_ton = fields.Float("Круг, ₽/т", compute="_compute_metal_ton", store=True, readonly=False,
                             digits=(12, 0), help="Из «Норм для болтов» по марке; можно поправить в строке.")
    markup_pct = fields.Float("Наценка, %", compute="_compute_markup", store=True, readonly=False,
                              digits=(6, 1), help="Из ценовой политики на дату расчёта; можно поправить.")

    name = fields.Char("Наименование", compute="_compute_calc", store=True)
    short_name = fields.Char("Болт", compute="_compute_calc", store=True,
                             help="Коротко для списка: тип, М×L, сталь, резьба.")
    warning = fields.Char("Внимание", compute="_compute_calc", store=True)
    blank_mm = fields.Float("Заготовка, мм", compute="_compute_calc", store=True, digits=(10, 0))
    mass_one = fields.Float("Масса шт, кг", compute="_compute_calc", store=True, digits=(10, 2))
    metal_rub = fields.Float("Круг", digits=(12, 2), compute="_compute_calc", store=True)
    plate_rub = fields.Float("Плита", digits=(12, 2), compute="_compute_calc", store=True)
    washer_rub = fields.Float("Шайба", digits=(12, 2), compute="_compute_calc", store=True)
    nuts_rub = fields.Float("Гайки", digits=(12, 2), compute="_compute_calc", store=True)
    thread_rub = fields.Float("Резьба", digits=(12, 2), compute="_compute_calc", store=True)
    work_rub = fields.Float("Гиб, проточка", digits=(12, 2), compute="_compute_calc", store=True)
    cost_one = fields.Float("Себестоимость шт", digits=(12, 2), compute="_compute_calc", store=True)
    price_unit = fields.Float("Цена шт", digits=(12, 2), compute="_compute_price", store=True, readonly=False)
    price_total = fields.Float("Сумма", digits=(12, 2), compute="_compute_total", store=True)
    margin_pct = fields.Float("Маржа, %", compute="_compute_total", store=True, digits=(5, 1))
    kit_text = fields.Text("Комплект", compute="_compute_kit")
    history = fields.Char("Прошлые продажи", compute="_compute_history")

    # ─── Подстановки ────────────────────────────────────────────────────
    @api.depends("diameter")
    def _compute_thread_len(self):
        for line in self:
            line.thread_len = gost.SIZES[int(line.diameter)]["l0"] if line.diameter else 0

    @api.depends("diameter", "steel")
    def _compute_metal_ton(self):
        Norm = self.env["pmk.bolt.norm"]
        for line in self:
            norm = Norm._pmk_for(int(line.diameter)) if line.diameter else Norm
            line.metal_ton = (norm.round_09g2s_ton if line.steel == "09Г2С" else norm.round_st3_ton) if norm else 0.0

    @api.depends("calc_id.date")
    def _compute_markup(self):
        Policy = self.env["pmk.price.policy"]
        for line in self:
            markup = Policy._pmk_markup("bolt", line.calc_id.date)
            line.markup_pct = markup or 0.0

    # ─── Расчёт ─────────────────────────────────────────────────────────
    @api.depends("bolt_type", "diameter", "length", "thread_len", "steel", "qty", "nut_price", "metal_ton")
    def _compute_calc(self):
        Norm = self.env["pmk.bolt.norm"]
        for line in self:
            d = int(line.diameter or 0)
            problem = gost.check(line.bolt_type, d) if d else _("Выберите диаметр")
            empty = dict(blank_mm=0, mass_one=0, metal_rub=0, plate_rub=0, washer_rub=0, nuts_rub=0,
                         thread_rub=0, work_rub=0, cost_one=0)
            if problem or not line.length:
                line.update(dict(empty, name="", short_name="", warning=problem or _("Укажите длину")))
                continue
            spec, s = gost.TYPES[line.bolt_type], gost.SIZES[d]
            l0 = s["l0"]
            thread = line.thread_len or l0
            norm = Norm._pmk_for(d)
            notes = []
            if gost.table_mass(line.bolt_type, d, line.length) is None:
                notes.append(_("длина не из ряда ГОСТ — масса по соседним длинам"))
            if thread > l0:
                notes.append(_("удлинённая резьба: +%s мм к ГОСТ") % (thread - l0))
            if not norm:
                notes.append(_("нет норм для М%s — заполните «Нормы для болтов»") % d)
            if not line.metal_ton:
                notes.append(_("нет цены круга"))
            if not line.nut_price:
                notes.append(_("впишите цену гайки"))
            sheet_ton = norm.sheet_ton if norm else 0.0
            plate_kg = s["plate"][2] if spec["plate"] else 0.0
            thread_rub = norm.thread_rub * (thread / l0 + spec["thread_ends"] - 1) if norm else 0.0
            work_rub = (norm.bend_rub * spec["bends"] + norm.turn_rub * spec["turn_ends"]) if norm else 0.0
            vals = dict(
                name=gost.name(line.bolt_type, d, line.length, thread, line.steel),
                short_name="%s М%s×%s · %s · резьба %s" % (line.bolt_type, d, line.length, line.steel, thread),
                warning="; ".join(notes),
                blank_mm=round(gost.blank_mm(line.bolt_type, d, line.length)),
                mass_one=gost.mass(line.bolt_type, d, line.length),
                metal_rub=gost.stud_kg(line.bolt_type, d, line.length) * line.metal_ton / 1000.0,
                plate_rub=(plate_kg * sheet_ton / 1000.0 + (norm.plate_rub if norm else 0.0)) if spec["plate"] else 0.0,
                washer_rub=s["w"] * sheet_ton / 1000.0 + (norm.washer_rub if norm else 0.0),
                nuts_rub=spec["nuts"] * (line.nut_price or 0.0),
                thread_rub=thread_rub,
                work_rub=work_rub,
            )
            vals["cost_one"] = sum(vals[k] for k in ("metal_rub", "plate_rub", "washer_rub", "nuts_rub",
                                                     "thread_rub", "work_rub"))
            line.update(vals)

    @api.depends("cost_one", "markup_pct")
    def _compute_price(self):
        for line in self:
            # До рубля вверх: копейки в цене болта никто не пишет.
            raw = line.cost_one * (1 + (line.markup_pct or 0.0) / 100.0)
            line.price_unit = float(int(raw) + (1 if raw > int(raw) else 0)) if raw else 0.0

    @api.depends("price_unit", "qty", "cost_one")
    def _compute_total(self):
        for line in self:
            line.price_total = line.price_unit * line.qty
            line.margin_pct = ((line.price_unit - line.cost_one) / line.price_unit * 100.0
                               if line.price_unit else 0.0)

    @api.depends("bolt_type", "diameter", "length")
    def _compute_kit(self):
        for line in self:
            d = int(line.diameter or 0)
            if not d or gost.check(line.bolt_type, d) or not line.length:
                line.kit_text = ""
                continue
            spec, s = gost.TYPES[line.bolt_type], gost.SIZES[d]
            rows = [_("Шпилька поз. %(pos)s, заготовка %(blank)s мм (круг %(d1)s)", pos=spec["pos"],
                      blank=round(gost.blank_mm(line.bolt_type, d, line.length)), d1=s["d1"]),
                    _("Гайка М%(d)s %(gost)s × %(n)s", d=d, gost=gost.NUT_GOST[d], n=spec["nuts"]),
                    _("Шайба М%(d)s ГОСТ 24379.1 (%(kg)s кг)", d=d, kg=str(s["w"]).replace(".", ","))]
            if spec["plate"]:
                b, t, kg = s["plate"]
                rows.append(_("Плита %(b)s×%(b)s×%(t)s мм (%(kg)s кг)", b=b, t=t, kg=str(kg).replace(".", ",")))
            line.kit_text = "\n".join(rows)

    @api.depends("diameter", "nut_kind")
    def _compute_nut_hint(self):
        for line in self:
            prev = self.search([("diameter", "=", line.diameter), ("nut_kind", "=", line.nut_kind),
                                ("nut_price", ">", 0), ("id", "!=", line._origin.id or 0)],
                               order="write_date desc, id desc", limit=1) if line.diameter else self.browse()
            line.nut_hint = (_("М%(d)s %(kind)s: %(price)s ₽ — %(doc)s, %(date)s", d=line.diameter,
                               kind=dict(NUT_KINDS)[line.nut_kind], price=round(prev.nut_price),
                               doc=prev.calc_id.name, date=prev.calc_id.date.strftime("%d.%m.%Y"))
                             if prev else _("цен гаек М%s этого вида ещё не вписывали") % (line.diameter or ""))

    @api.depends("bolt_type", "diameter", "length", "steel")
    def _compute_history(self):
        for line in self:
            line.history = line._pmk_history_text() if line.diameter and line.length else ""

    def _pmk_history_text(self, limit=3):
        """Прошлые продажи этого размера по строкам счетов (из МоегоСклада — свои названия)."""
        self.ensure_one()
        if "sale.order.line" not in self.env:
            return ""
        size = r"М-?\s*%s\s*[хx×*]\s*%s(\D|$)" % (int(self.diameter), int(self.length))
        steel = "09Г2С" if self.steel == "09Г2С" else r"(ВСт3|Ст3)"
        self.env.cr.execute("""
            SELECT l.price_unit, o.date_order, p.name
              FROM sale_order_line l JOIN sale_order o ON o.id = l.order_id
              LEFT JOIN res_partner p ON p.id = o.partner_id
             WHERE o.state != 'cancel' AND l.price_unit > 0
               AND l.name ~* '(болт|анкер).{0,30}фундамент|фундамент.{0,20}(болт|анкер)'
               AND l.name ~* %s AND l.name ~* %s AND l.name ~* %s
             ORDER BY o.date_order DESC LIMIT %s
        """, (size, r"(тип\s*)?" + re.escape(self.bolt_type) + r"\.?\s*М", steel, limit))
        rows = self.env.cr.fetchall()
        if not rows:
            return _("Этот размер раньше не продавали — сверить цену")
        return "; ".join("%s ₽ — %s, %s" % ("{:,.0f}".format(price).replace(",", " "), (partner or "")[:30],
                                             date.strftime("%m.%Y")) for price, date, partner in rows)
