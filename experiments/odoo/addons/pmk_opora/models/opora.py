# -*- coding: utf-8 -*-
"""Калькулятор опор трубопроводов по ОСТ 36-146-88 (Антон 25.10.2026).

Устроен как калькулятор фундаментных болтов (pmk_bolt): отдельный документ в
«Калькуляторах», строка — одна опора, под ней состав деталей.

- Начинаем с КП и КХ («почти все заказы»), подвижная и неподвижная — разные
  категории изделия (Антон 25.10.2026: «без галочек, просто делим на разные
  категории изделия»).
- Масса — по фактическим деталям, не по таблице ОСТ (там есть ошибки — Игорь
  находил при подготовке чертежей); масса ОСТ — рядом, для сверки.
- Корпус по умолчанию гнутый, «С» в исполнении — сварной.
- Себестоимость — сумма состава: лист по прайсам (₽/т, марка стали опоры),
  болты и гайки — покупные, цену вписывают. Только материалы, как у болтов.
- Наценку ставит менеджер (Антон 25.10.2026: «наценку устанавливает менеджер, 45 % — это очень
  мало»): в строке или в «Ценовой политике» (вид «Опоры трубопроводов»); готовой наценки модуль
  не заводит. Пока наценки нет — цены нет, под строкой «впишите наценку».
"""
from odoo import _, api, fields, models

from odoo.addons.pmk_bridge.tools import spec_text

from ..tools import catalog

STEELS = [(s, s) for s in catalog.STEELS]
TYPES = [(k, "%s — %s" % (v["label"], v["standard"])) for k, v in catalog.TYPES.items()]
PRICE_GRADE = {"09Г2С": "09Г2С", "10Г2": "10Г2", "20": "20"}  # Ст3пс/Ст3сп — самая дешёвая, как в расчёте


class OporaCalc(models.Model):
    _name = "pmk.opora.calc"
    _description = "Расчёт опор трубопроводов"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one("res.partner", "Контрагент", tracking=True)
    opportunity_id = fields.Many2one("crm.lead", "Сделка", tracking=True)
    user_id = fields.Many2one("res.users", "Ответственный", default=lambda self: self.env.user, tracking=True)
    note = fields.Char("Объект, примечание")
    line_ids = fields.One2many("pmk.opora.line", "calc_id", "Опоры", copy=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    total_qty = fields.Integer("Опор, шт", compute="_compute_totals", store=True)
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
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.opora.calc") or "Черновик"
        return super().create(vals_list)


class OporaLine(models.Model):
    _name = "pmk.opora.line"
    _description = "Опора трубопровода"
    _order = "calc_id, sequence, id"

    calc_id = fields.Many2one("pmk.opora.calc", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(related="calc_id.currency_id")
    # Не обязательные: пустая строка таблицы (Enter в конце) — ещё не опора.
    opora_type = fields.Selection(TYPES, "Тип")
    dn = fields.Float("Дн трубы, мм", digits=(6, 1))
    execution = fields.Char("Исполнение", help="ОСТ 36-146-88: А12, АС13 (С — сварной корпус), Б22 (с подушкой, только КП). ОСТ 36-94-83: высота марки — 100 или 70.")
    height = fields.Integer("Своя высота Н, мм", help="Пусто — по ОСТ. В счетах встречается «Н=50» у А12.")
    steel = fields.Selection(STEELS, "Сталь", default="Ст3пс")
    qty = fields.Integer("Кол-во, шт", required=True, default=1)
    markup_pct = fields.Float("Наценка, %", compute="_compute_markup", store=True, readonly=False,
                              digits=(6, 1), help="Ставит менеджер: в строке или в ценовой политике на дату расчёта.")
    part_ids = fields.One2many("pmk.opora.part", "line_id", "Состав", copy=True)

    name = fields.Char("Наименование", compute="_compute_calc", store=True)
    short_name = fields.Char("Опора", compute="_compute_calc", store=True)
    warning = fields.Char("Внимание", compute="_compute_calc", store=True)
    mass_one = fields.Float("Масса шт, кг", compute="_compute_calc", store=True, digits=(10, 2))
    ost_mass = fields.Float("Масса по ОСТ, кг", compute="_compute_calc", store=True, digits=(10, 1),
                            help="«Не более» по таблице ОСТ (у КХ — без упоров) — для сверки.")
    cost_one = fields.Float("Себестоимость шт", digits=(12, 2), compute="_compute_calc", store=True)
    price_unit = fields.Float("Цена шт", digits=(12, 2), compute="_compute_price", store=True, readonly=False)
    price_total = fields.Float("Сумма", digits=(12, 2), compute="_compute_total", store=True)
    margin_pct = fields.Float("Маржа, %", compute="_compute_total", store=True, digits=(5, 1))
    history = fields.Char("Прошлые продажи", compute="_compute_history")

    OPORA_FIELDS = ("opora_type", "dn", "execution", "height", "steel")

    @api.depends("calc_id.date")
    def _compute_markup(self):
        Policy = self.env["pmk.price.policy"]
        for line in self:
            line.markup_pct = Policy._pmk_markup("opora", line.calc_id.date) or 0.0

    def _pmk_ok(self):
        self.ensure_one()
        return bool(self.opora_type and self.dn and self.execution
                    and not catalog.check(self.opora_type, self.dn, self.execution)
                    and not catalog.check_height(self.opora_type, self.dn, self.execution, self.height))

    # ─── Состав по ОСТ ──────────────────────────────────────────────────
    def _pmk_sheet_price_ton(self, thickness):
        """₽/т листа толщиной thickness — тем же правилом, что строка расчёта (pmk_bridge
        _pmk_find_seller): самая низкая цена прайсов на дату; марка 09Г2С и др. — только своя.
        Нет цены — 0 («в городе нет»), соседнюю не подставляем."""
        sheet = self.env["pmk.metal.sheet"].search(
            [("sheet_type", "=", "Гладкий"), ("thickness_mm", "=", thickness)], limit=1)
        tmpl = sheet.product_tmpl_id if sheet else False
        if not tmpl:
            return 0.0
        seller = tmpl._pmk_find_seller(self.calc_id.date or fields.Date.context_today(self),
                                       grade=PRICE_GRADE.get(self.steel))
        if not seller:
            return 0.0
        return spec_text.per_ton(seller.price_discounted, sheet._pmk_mass_per_unit(tmpl))

    def _pmk_auto_parts(self):
        """{auto_key: значения} — детали по ОСТ, только материалы."""
        self.ensure_one()
        out, prices = {}, {}
        for part in catalog.parts(self.opora_type, self.dn, self.execution, self.height or None):
            vals = dict(sequence=part["sequence"], name=part["name"], qty=float(part["qty"]),
                        unit_mass=part["unit_mass"], thickness=part["thickness"],
                        a_mm=part.get("a") or 0.0, b_mm=part.get("b") or 0.0)
            if part["metal"]:
                t = part["thickness"]
                if t not in prices:
                    prices[t] = self._pmk_sheet_price_ton(t)
                vals.update(name="%s %s" % (part["name"], self.steel or ""), price_ton=prices[t])
            else:
                vals["price_unit"] = 0.0
            out[part["key"]] = vals
        return out

    def _pmk_sync_parts(self):
        """Состав по ОСТ. Поправленные руками строки: имя и масса — по опоре, количество и
        цены — как поправили. Свои строки не трогаем. Не опора — строк из ОСТ нет."""
        Part = self.env["pmk.opora.part"]
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
                    vals = {k: v for k, v in vals.items() if k in ("name", "unit_mass", "sequence", "thickness",
                                                                   "a_mm", "b_mm")}
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
        if set(self.OPORA_FIELDS) & set(vals) and not self.env.context.get("pmk_opora_no_sync"):
            self._pmk_sync_parts()
        return res

    # ─── Расчёт ─────────────────────────────────────────────────────────
    @api.depends("opora_type", "dn", "execution", "height", "steel", "part_ids.cost", "part_ids.mass",
                 "part_ids.qty", "part_ids.price_unit", "part_ids.price_ton", "markup_pct")
    def _compute_calc(self):
        for line in self:
            empty = dict(mass_one=0, ost_mass=0, cost_one=0, name="", short_name="")
            if not (line.opora_type and line.dn and line.execution):
                line.update(dict(empty, warning=""))
                continue
            problem = (catalog.check(line.opora_type, line.dn, line.execution)
                       or catalog.check_height(line.opora_type, line.dn, line.execution, line.height))
            if problem:
                line.update(dict(empty, warning=problem))
                continue
            parts = line.part_ids
            notes = []
            if line.height:
                notes.append(_("высота не по ОСТ: Н=%(h)s вместо %(std)s — корпус и рёбра пересчитаны",
                               h=line.height, std=catalog.standard_h(line.opora_type, line.dn, line.execution)))
            no_sheet = sorted({p.thickness for p in parts if p.price_ton == 0 and p.unit_mass and p.thickness})
            if no_sheet:
                notes.append(_("нет цены листа %(t)s мм %(steel)s в прайсах — впишите в строке",
                               t=", ".join("%g" % t for t in no_sheet), steel=line.steel or ""))
            if parts.filtered(lambda p: p.auto_key in ("bolt", "nut") and not p.price_unit):
                notes.append(_("впишите цену болтов и гаек"))
            if not line.markup_pct:
                notes.append(_("впишите наценку — её ставит менеджер"))
            line.update(dict(
                name=catalog.name(line.opora_type, line.dn, line.execution, line.steel, line.height or None),
                short_name=catalog.short(line.opora_type, line.dn, line.execution, line.steel, line.height or None),
                warning="; ".join(notes),
                mass_one=sum(parts.mapped("mass")),
                ost_mass=catalog.ost_mass(line.opora_type, line.dn, line.execution),
                cost_one=sum(parts.mapped("cost")),
            ))

    @api.depends("cost_one", "markup_pct")
    def _compute_price(self):
        for line in self:
            if not line.markup_pct:
                line.price_unit = 0.0  # без наценки менеджера цены нет — не продаём по себестоимости
                continue
            raw = line.cost_one * (1 + line.markup_pct / 100.0)
            line.price_unit = float(int(raw) + (1 if raw > int(raw) else 0)) if raw else 0.0

    @api.depends("price_unit", "qty", "cost_one")
    def _compute_total(self):
        for line in self:
            line.price_total = line.price_unit * line.qty
            line.margin_pct = ((line.price_unit - line.cost_one) / line.price_unit * 100.0
                               if line.price_unit else 0.0)

    def _pmk_buy_hint(self, key):
        """Последняя вписанная цена болта/гайки того же размера — подсказка."""
        self.ensure_one()
        part = self.part_ids.filtered(lambda p: p.auto_key == key)[:1]
        if not part:
            return ""
        prev = self.env["pmk.opora.part"].search(
            [("auto_key", "=", key), ("price_unit", ">", 0), ("name", "=", part.name), ("id", "!=", part.id)],
            order="write_date desc, id desc", limit=1)
        if not prev:
            return ""
        return _("было %(price)s ₽ — %(doc)s, %(date)s", price=("%g" % prev.price_unit).replace(".", ","),
                 doc=prev.line_id.calc_id.name, date=prev.line_id.calc_id.date.strftime("%d.%m.%Y"))

    @api.depends("opora_type", "dn", "execution")
    def _compute_history(self):
        for line in self:
            line.history = line._pmk_history_text() if line._pmk_ok() else ""

    def _pmk_history_text(self, limit=3):
        """Прошлые продажи этой опоры по строкам счетов (из МоегоСклада — свои названия):
        шаблоны — у стандарта (tools/<стандарт>.history_patterns); неподвижные — отдельно."""
        self.ensure_one()
        if "sale.order.line" not in self.env:
            return ""
        patterns, fixed = catalog.history_patterns(self.opora_type, self.dn, self.execution)
        where = " AND ".join(["l.name ~* %s"] * len(patterns))
        if fixed is not None:
            where += " AND " + ("" if fixed else "NOT ") + "(l.name ~* '(неподв|с\\s*упор)')"
        self.env.cr.execute("""
            SELECT l.price_unit, o.date_order, p.name
              FROM sale_order_line l JOIN sale_order o ON o.id = l.order_id
              LEFT JOIN res_partner p ON p.id = o.partner_id
             WHERE o.state != 'cancel' AND l.price_unit > 0 AND l.name ~* 'опор' AND """ + where + """
             ORDER BY o.date_order DESC LIMIT %s
        """, tuple(patterns) + (limit,))
        rows = self.env.cr.fetchall()
        if not rows:
            return _("Такую опору раньше не продавали — сверить цену")
        return "; ".join("%s ₽ — %s, %s" % ("{:,.0f}".format(price).replace(",", " "), (partner or "")[:30],
                                             date.strftime("%m.%Y")) for price, date, partner in rows)
