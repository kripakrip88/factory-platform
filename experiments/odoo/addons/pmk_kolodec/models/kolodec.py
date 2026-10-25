# -*- coding: utf-8 -*-
"""Калькулятор металлоизделий колодцев по типовым альбомам (Антон 25.10.2026).

Устроен как калькуляторы болтов и опор (pmk_bolt, pmk_opora): отдельный документ в
«Калькуляторах», строка — одно изделие, под ним состав деталей.

- Изделия: стремянки С1 (902-09-22.84) и С (901-09-11.84), элементы соединительные МС,
  скоба ходовая МН1, проставки монтажные (эскиз), звено ограждения ЗО, крышка К1.
- Масса — по фактическим деталям; масса альбома — рядом, для сверки (в альбомах есть
  ошибки — см. docs/).
- Себестоимость — сумма состава: прокат и лист по прайсам (₽/т), покупное (шпильки, гайки,
  уплотнение) — цену вписывают. Только материалы, как у болтов и опор.
- Цена = себестоимость × (1 + наценка ценовой политики «Металлоизделия колодцев»).
"""
import json

from odoo import _, api, fields, models

from odoo.addons.pmk_bridge.tools import spec_text

from ..tools import catalog

STEELS = [(s, s) for s in catalog.STEELS]
TYPES = [(k, "%s — %s" % (v["label"], v["album"])) for k, v in catalog.TYPES.items()]
PRICE_GRADE = {"09Г2С": "09Г2С"}  # Ст3 — самая дешёвая марка, как в расчёте


class KolodecCalc(models.Model):
    _name = "pmk.kolodec.calc"
    _description = "Расчёт металлоизделий колодцев"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one("res.partner", "Контрагент", tracking=True)
    opportunity_id = fields.Many2one("crm.lead", "Сделка", tracking=True)
    user_id = fields.Many2one("res.users", "Ответственный", default=lambda self: self.env.user, tracking=True)
    note = fields.Char("Объект, примечание")
    line_ids = fields.One2many("pmk.kolodec.line", "calc_id", "Изделия", copy=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    total_qty = fields.Integer("Изделий, шт", compute="_compute_totals", store=True)
    total_weight = fields.Float("Вес, кг", compute="_compute_totals", store=True, digits=(12, 1))
    total_cost = fields.Float("Себестоимость", digits=(12, 2), compute="_compute_totals", store=True)
    amount_total = fields.Float("Сумма", digits=(12, 2), compute="_compute_totals", store=True)
    margin_pct = fields.Float("Маржа, %", compute="_compute_totals", store=True, digits=(5, 1))
    has_warnings = fields.Boolean(compute="_compute_totals", store=True)

    @api.depends("line_ids.qty", "line_ids.mass_one", "line_ids.cost_one", "line_ids.price_total",
                 "line_ids.warning", "line_ids.name")
    def _compute_totals(self):
        for calc in self:
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
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.kolodec.calc") or "Черновик"
        return super().create(vals_list)


class KolodecLine(models.Model):
    _name = "pmk.kolodec.line"
    _description = "Металлоизделие колодца"
    _order = "calc_id, sequence, id"

    calc_id = fields.Many2one("pmk.kolodec.calc", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(related="calc_id.currency_id")
    # Не обязательные: пустая строка таблицы (Enter в конце) — ещё не изделие.
    item_type = fields.Selection(TYPES, "Изделие")
    mark = fields.Char("Марка", help="С1-04, С-5, МС-5, МН1, Ду300, ЗО, К1")
    steel = fields.Selection(STEELS, "Сталь", default="Ст3пс")
    qty = fields.Integer("Кол-во, шт", required=True, default=1)
    markup_pct = fields.Float("Наценка, %", compute="_compute_markup", store=True, readonly=False,
                              digits=(6, 1), help="Из ценовой политики на дату расчёта; можно поправить.")
    part_ids = fields.One2many("pmk.kolodec.part", "line_id", "Состав", copy=True)

    name = fields.Char("Наименование", compute="_compute_calc", store=True)
    short_name = fields.Char("Изделие коротко", compute="_compute_calc", store=True)
    warning = fields.Char("Внимание", compute="_compute_calc", store=True)
    mass_one = fields.Float("Масса шт, кг", compute="_compute_calc", store=True, digits=(10, 2))
    album_mass = fields.Float("Масса по альбому, кг", compute="_compute_calc", store=True, digits=(10, 2),
                              help="Из таблицы или штампа альбома — для сверки.")
    cost_one = fields.Float("Себестоимость шт", digits=(12, 2), compute="_compute_calc", store=True)
    price_unit = fields.Float("Цена шт", digits=(12, 2), compute="_compute_price", store=True, readonly=False)
    price_total = fields.Float("Сумма", digits=(12, 2), compute="_compute_total", store=True)
    margin_pct = fields.Float("Маржа, %", compute="_compute_total", store=True, digits=(5, 1))
    history = fields.Char("Прошлые продажи", compute="_compute_history")

    ITEM_FIELDS = ("item_type", "mark", "steel")

    @api.depends("calc_id.date")
    def _compute_markup(self):
        Policy = self.env["pmk.price.policy"]
        for line in self:
            line.markup_pct = Policy._pmk_markup("kolodec", line.calc_id.date) or 0.0

    def _pmk_ok(self):
        self.ensure_one()
        return bool(self.item_type and self.mark and not catalog.check(self.item_type, self.mark))

    # ─── Состав по альбому ──────────────────────────────────────────────
    def _pmk_material_record(self, material):
        kind = material[0]
        if kind == "profile":
            return self.env["pmk.metal.profile"].search(
                [("profile_type", "=", material[1]), ("size_label", "=", material[2])], limit=1)
        return self.env["pmk.metal.sheet"].search(
            [("sheet_type", "=", "Гладкий"), ("thickness_mm", "=", material[1])], limit=1)

    def _pmk_price_ton(self, material):
        """₽/т позиции общего справочника — тем же правилом, что строка расчёта (pmk_bridge
        _pmk_find_seller): самая низкая цена прайсов на дату; 09Г2С — только своя.
        Нет позиции или цены — 0 («в городе нет»), соседний размер не подставляем."""
        record = self._pmk_material_record(material)
        tmpl = record.product_tmpl_id if record else False
        if not tmpl:
            return 0.0
        seller = tmpl._pmk_find_seller(self.calc_id.date or fields.Date.context_today(self),
                                       grade=PRICE_GRADE.get(self.steel))
        if not seller:
            return 0.0
        return spec_text.per_ton(seller.price_discounted, record._pmk_mass_per_unit(tmpl))

    def _pmk_pick_material(self, candidates, cache):
        """Первый материал из списка с ценой в прайсах: полоса 8×80, иначе лист 8. → (материал, ₽/т)."""
        for material in candidates:
            key = tuple(material)
            if key not in cache:
                cache[key] = self._pmk_price_ton(material)
            if cache[key]:
                return material, cache[key]
        return candidates[0], 0.0

    @staticmethod
    def _pmk_material_text(material):
        if material[0] == "sheet":
            return _("лист %s мм") % ("%g" % material[1]).replace(".", ",")
        return "%s %s" % (material[1].lower(), material[2])

    def _pmk_auto_parts(self):
        """{auto_key: значения} — детали по альбому, только материалы."""
        self.ensure_one()
        out, cache = {}, {}
        for part in catalog.parts(self.item_type, self.mark):
            vals = dict(sequence=part["sequence"], name=part["name"], qty=float(part["qty"]),
                        unit_mass=part["unit_mass"], metal=part["metal"])
            if part["metal"]:
                material, price = self._pmk_pick_material(part["material"], cache)
                name = part["name"]
                if len(part["material"]) > 1 and material != part["material"][0]:
                    name += _(" — из: %s") % self._pmk_material_text(material)
                vals.update(name="%s %s" % (name, self.steel or ""), price_ton=price,
                            material=json.dumps(material, ensure_ascii=False),
                            thickness=material[1] if material[0] == "sheet" else 0.0)
            else:
                vals["price_unit"] = 0.0
            out[part["key"]] = vals
        return out

    def _pmk_sync_parts(self):
        """Состав по альбому. Поправленные руками строки: имя и масса — по изделию, количество
        и цены — как поправили. Свои строки не трогаем. Не изделие — строк альбома нет."""
        Part = self.env["pmk.kolodec.part"]
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
                    vals = {k: v for k, v in vals.items()
                            if k in ("name", "unit_mass", "sequence", "thickness", "metal", "material")}
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
        if set(self.ITEM_FIELDS) & set(vals) and not self.env.context.get("pmk_kolodec_no_sync"):
            self._pmk_sync_parts()
        return res

    # ─── Расчёт ─────────────────────────────────────────────────────────
    @api.depends("item_type", "mark", "steel", "part_ids.cost", "part_ids.mass",
                 "part_ids.qty", "part_ids.price_unit", "part_ids.price_ton")
    def _compute_calc(self):
        for line in self:
            empty = dict(mass_one=0, album_mass=0, cost_one=0, name="", short_name="")
            if not (line.item_type and line.mark):
                line.update(dict(empty, warning=""))
                continue
            problem = catalog.check(line.item_type, line.mark)
            if problem:
                line.update(dict(empty, warning=problem))
                continue
            parts = line.part_ids
            notes = []
            outside = catalog.outside_album(line.item_type, line.mark)
            if outside:
                notes.append(outside)
            if line.item_type == "pr":
                notes.append(_("эскиз альбома: фланцы по ГОСТ 12815 Ру 1,0 — состав проверить"))
            no_price = sorted({p.name.split(" — ")[0] for p in parts
                               if p.metal and p.unit_mass and not p.price_ton})
            if no_price:
                notes.append(_("нет цены в прайсах: %(what)s — впишите в строке", what="; ".join(no_price)))
            if parts.filtered(lambda p: p.auto_key and not p.metal and p.unit_mass and not p.price_unit):
                notes.append(_("впишите цену покупных"))
            line.update(dict(
                name=catalog.name(line.item_type, line.mark, line.steel),
                short_name=catalog.short(line.item_type, line.mark, line.steel),
                warning="; ".join(notes),
                mass_one=sum(parts.mapped("mass")),
                album_mass=catalog.album_mass(line.item_type, line.mark),
                cost_one=sum(parts.mapped("cost")),
            ))

    @api.depends("cost_one", "markup_pct")
    def _compute_price(self):
        for line in self:
            raw = line.cost_one * (1 + (line.markup_pct or 0.0) / 100.0)
            line.price_unit = float(int(raw) + (1 if raw > int(raw) else 0)) if raw else 0.0

    @api.depends("price_unit", "qty", "cost_one")
    def _compute_total(self):
        for line in self:
            line.price_total = line.price_unit * line.qty
            line.margin_pct = ((line.price_unit - line.cost_one) / line.price_unit * 100.0
                               if line.price_unit else 0.0)

    def _pmk_buy_hint(self, part):
        """Последняя вписанная цена покупной строки с тем же названием — подсказка."""
        prev = self.env["pmk.kolodec.part"].search(
            [("auto_key", "=", part.auto_key), ("price_unit", ">", 0), ("name", "=", part.name),
             ("id", "!=", part.id)], order="write_date desc, id desc", limit=1)
        if not prev:
            return ""
        return _("было %(price)s ₽ — %(doc)s, %(date)s", price=("%g" % prev.price_unit).replace(".", ","),
                 doc=prev.line_id.calc_id.name, date=prev.line_id.calc_id.date.strftime("%d.%m.%Y"))

    @api.depends("item_type", "mark")
    def _compute_history(self):
        for line in self:
            line.history = line._pmk_history_text() if line._pmk_ok() else ""

    def _pmk_history_text(self, limit=3):
        """Прошлые продажи этого изделия по строкам счетов (из МоегоСклада — свои названия):
        шаблоны — у альбома (tools/<альбом>.history_patterns)."""
        self.ensure_one()
        if "sale.order.line" not in self.env:
            return ""
        patterns, exclude = catalog.history_patterns(self.item_type, self.mark)
        where = " AND ".join(["l.name ~* %s"] * len(patterns))
        params = list(patterns)
        if exclude:
            where += " AND l.name !~* %s"
            params.append(exclude)
        self.env.cr.execute("""
            SELECT l.price_unit, o.date_order, p.name
              FROM sale_order_line l JOIN sale_order o ON o.id = l.order_id
              LEFT JOIN res_partner p ON p.id = o.partner_id
             WHERE o.state != 'cancel' AND l.price_unit > 0 AND """ + where + """
             ORDER BY o.date_order DESC LIMIT %s
        """, tuple(params) + (limit,))
        rows = self.env.cr.fetchall()
        if not rows:
            return _("Такое изделие раньше не продавали — сверить цену")
        return "; ".join("%s ₽ — %s, %s" % ("{:,.0f}".format(price).replace(",", " "), (partner or "")[:30],
                                             date.strftime("%m.%Y")) for price, date, partner in rows)
