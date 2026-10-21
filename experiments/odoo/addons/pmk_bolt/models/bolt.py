# -*- coding: utf-8 -*-
"""Калькулятор фундаментных болтов (Антон 21.10.2026).

Отдельный документ в «Калькуляторах», как зонты: сначала считаем болты сами
по себе, потом встраиваем в счёт и расчёт («сначала собрал отдельный
калькулятор… а потом ввёл его в документы»).

Строка — один болт: тип, М, длина, резьба, сталь, количество, гайки.
- Название — одним видом, с длиной резьбы («часто просят удлинённую»).
- Масса — по приложению А ГОСТ; длина не из ряда — по формуле, с пометкой.
- Себестоимость — сумма СОСТАВА болта (models/part.py), как детали изделия в
  «Конструкциях»: круг (заготовка, 2d на гиб), гайки, шайба, плита — только
  материалы, работу не считаем (как в остальных изделиях). Состав заполняет калькулятор по ГОСТ; строку можно поправить или
  добавить свою («доп. гайки») — правку пересчёт не затрёт. Цену гайки вписывает
  Владимир («угадай мелодию»), подсказка — последняя цена гайки того же М и вида.
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
                 "line_ids.warning", "line_ids.name")
    def _compute_totals(self):
        for calc in self:
            # Только распознанные болты: пустая строка таблицы и непонятая запись — не болт.
            lines = calc.line_ids.filtered("name")
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
    # Не обязательные: пустая строка таблицы (Enter в конце) — ещё не болт.
    bolt_type = fields.Selection([(k, v["label"]) for k, v in gost.TYPES.items()], "Тип")
    diameter = fields.Selection(DIAMETERS, "Диаметр")
    length = fields.Integer("Длина L, мм")
    thread_len = fields.Integer("Резьба, мм", compute="_compute_thread_len", store=True, readonly=False,
                                help="По ГОСТ — по диаметру; можно длиннее («удлинённая резьба»).")
    steel = fields.Selection(STEELS, "Сталь", default="09Г2С")
    qty = fields.Integer("Кол-во, шт", required=True, default=1)
    nut_kind = fields.Selection(NUT_KINDS, "Гайки", required=True, default="plain")
    markup_pct = fields.Float("Наценка, %", compute="_compute_markup", store=True, readonly=False,
                              digits=(6, 1), help="Из ценовой политики на дату расчёта; можно поправить.")
    part_ids = fields.One2many("pmk.bolt.part", "line_id", "Состав", copy=True)

    name = fields.Char("Наименование", compute="_compute_calc", store=True)
    short_name = fields.Char("Болт", compute="_compute_calc", store=True,
                             help="Коротко для списка: тип, М×L, сталь, резьба.")
    warning = fields.Char("Внимание", compute="_compute_calc", store=True)
    blank_mm = fields.Float("Заготовка, мм", compute="_compute_calc", store=True, digits=(10, 0))
    mass_one = fields.Float("Масса шт, кг", compute="_compute_calc", store=True, digits=(10, 2))
    cost_one = fields.Float("Себестоимость шт", digits=(12, 2), compute="_compute_calc", store=True)
    price_unit = fields.Float("Цена шт", digits=(12, 2), compute="_compute_price", store=True, readonly=False)
    price_total = fields.Float("Сумма", digits=(12, 2), compute="_compute_total", store=True)
    margin_pct = fields.Float("Маржа, %", compute="_compute_total", store=True, digits=(5, 1))
    history = fields.Char("Прошлые продажи", compute="_compute_history")

    BOLT_FIELDS = ("bolt_type", "diameter", "length", "thread_len", "steel", "nut_kind")

    # ─── Подстановки ────────────────────────────────────────────────────
    @api.depends("diameter")
    def _compute_thread_len(self):
        for line in self:
            line.thread_len = gost.SIZES[int(line.diameter)]["l0"] if line.diameter else 0

    @api.depends("calc_id.date")
    def _compute_markup(self):
        Policy = self.env["pmk.price.policy"]
        for line in self:
            markup = Policy._pmk_markup("bolt", line.calc_id.date)
            line.markup_pct = markup or 0.0

    def _pmk_ok(self):
        self.ensure_one()
        d = int(self.diameter or 0)
        return bool(self.bolt_type and d and self.length and not gost.check(self.bolt_type, d))

    # ─── Состав по ГОСТ ─────────────────────────────────────────────────
    def _pmk_auto_parts(self):
        """{auto_key: значения} для этого болта. Цены — из «Металла для болтов»."""
        self.ensure_one()
        d = int(self.diameter)
        spec, s = gost.TYPES[self.bolt_type], gost.SIZES[d]
        norm = self.env["pmk.bolt.norm"]._pmk_for(d)
        sheet_ton = norm.sheet_ton if norm else 0.0
        blank = gost.blank_mm(self.bolt_type, d, self.length)
        kind = {"plain": "", "hardened": " калёные", "special": " спецсталь"}[self.nut_kind or "plain"]
        out = {
            "stud": dict(sequence=1, name=_("Круг %(d1)s %(steel)s — шпилька поз. %(pos)s, заготовка %(blank)s мм",
                                            d1=s["d1"], steel=self.steel or "", pos=spec["pos"], blank=round(blank)),
                         qty=1.0, unit_mass=round(gost.stud_kg(self.bolt_type, d, self.length), 3),
                         price_ton=(norm.round_09g2s_ton if self.steel == "09Г2С" else norm.round_st3_ton) if norm else 0.0),
            "nut": dict(sequence=2, name=_("Гайка М%(d)s %(gost)s%(kind)s", d=d, gost=gost.NUT_GOST[d], kind=kind),
                        qty=float(spec["nuts"]), unit_mass=gost.NUT_KG[d], price_unit=0.0),
            "washer": dict(sequence=3, name=_("Шайба М%s ГОСТ 24379.1") % d, qty=1.0, unit_mass=s["w"],
                           price_unit=round(s["w"] * sheet_ton / 1000.0, 2)),
        }
        if spec["plate"]:
            b, t, kg = s["plate"]
            out["plate"] = dict(sequence=4, name=_("Плита %(b)s×%(b)s×%(t)s ГОСТ 24379.1", b=b, t=t), qty=1.0,
                                unit_mass=kg, price_unit=round(kg * sheet_ton / 1000.0, 2))
        return out

    def _pmk_sync_parts(self):
        """Состав по ГОСТ. Поправленные руками строки: имя и масса — по болту, количество
        и цены — как поправили. Свои строки не трогаем. Не болт — строк из ГОСТ нет."""
        Part = self.env["pmk.bolt.part"]
        for line in self:
            autos = line.part_ids.filtered("auto_key")
            if not line._pmk_ok():
                autos.unlink()
                continue
            want = line._pmk_auto_parts()
            for part in autos:
                vals = want.pop(part.auto_key, None)
                if vals is None:
                    part.unlink()
                    continue
                if part.edited:
                    vals = {k: v for k, v in vals.items() if k in ("name", "unit_mass", "sequence")}
                part.write(vals)
            for key, vals in want.items():
                Part.create(dict(vals, line_id=line.id, auto_key=key))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._pmk_sync_parts()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if set(self.BOLT_FIELDS) & set(vals) and not self.env.context.get("pmk_bolt_no_sync"):
            self._pmk_sync_parts()
        return res

    # ─── Расчёт ─────────────────────────────────────────────────────────
    @api.depends("bolt_type", "diameter", "length", "thread_len", "steel", "part_ids.cost", "part_ids.mass",
                 "part_ids.qty", "part_ids.price_unit", "part_ids.price_ton")
    def _compute_calc(self):
        for line in self:
            d = int(line.diameter or 0)
            empty = dict(blank_mm=0, mass_one=0, cost_one=0, name="", short_name="")
            if not (line.bolt_type and d and line.length):
                line.update(dict(empty, warning=""))
                continue
            problem = gost.check(line.bolt_type, d)
            if problem:
                line.update(dict(empty, warning=problem))
                continue
            spec, s = gost.TYPES[line.bolt_type], gost.SIZES[d]
            thread = line.thread_len or s["l0"]
            parts = line.part_ids
            notes = []
            if gost.table_mass(line.bolt_type, d, line.length) is None:
                notes.append(_("длина не из ряда ГОСТ — масса по соседним длинам"))
            if thread > s["l0"]:
                notes.append(_("удлинённая резьба: +%s мм к ГОСТ") % (thread - s["l0"]))
            if not self.env["pmk.bolt.norm"]._pmk_for(d):
                notes.append(_("нет цен металла для М%s — заполните «Металл для болтов»") % d)
            if parts.filtered(lambda p: p.auto_key == "stud" and not p.price_ton):
                notes.append(_("нет цены круга"))
            if parts.filtered(lambda p: p.auto_key == "nut" and not p.price_unit):
                notes.append(_("впишите цену гайки"))
            # Масса: по ГОСТ + то, что сверх комплекта (доп. гайки, свои строки).
            standard = {"stud": 1, "nut": spec["nuts"], "washer": 1, "plate": 1}
            extra = sum(p.mass if not p.auto_key else max(0.0, p.qty - standard[p.auto_key]) * p.unit_mass
                        for p in parts)
            line.update(dict(
                name=gost.name(line.bolt_type, d, line.length, thread, line.steel),
                short_name="%s М%s×%s · %s · резьба %s" % (line.bolt_type, d, line.length, line.steel, thread),
                warning="; ".join(notes),
                blank_mm=round(gost.blank_mm(line.bolt_type, d, line.length)),
                mass_one=gost.mass(line.bolt_type, d, line.length) + extra,
                cost_one=sum(parts.mapped("cost")),
            ))

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

    def _pmk_nut_hint(self):
        """Последняя вписанная цена гайки того же М и вида — подсказка («накопим статистику»)."""
        self.ensure_one()
        if not self.diameter:
            return ""
        prev = self.env["pmk.bolt.part"].search([
            ("auto_key", "=", "nut"), ("price_unit", ">", 0), ("line_id.diameter", "=", self.diameter),
            ("line_id.nut_kind", "=", self.nut_kind), ("line_id", "!=", self.id)],
            order="write_date desc, id desc", limit=1)
        if not prev:
            return ""
        return _("было %(price)s ₽ — %(doc)s, %(date)s", price=("%g" % prev.price_unit).replace(".", ","),
                 doc=prev.line_id.calc_id.name, date=prev.line_id.calc_id.date.strftime("%d.%m.%Y"))

    @api.depends("bolt_type", "diameter", "length", "steel")
    def _compute_history(self):
        for line in self:
            line.history = line._pmk_history_text() if line.bolt_type and line.diameter and line.length else ""

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
