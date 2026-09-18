# -*- coding: utf-8 -*-
"""Спецификация металлопроката: изделия и их детали.

Структура трёхуровневая, и это не украшение, а суть задачи. Считают не «сколько
всего уголка», а «сколько металла на партию изделий»: изделие Б в ста
экземплярах состоит из листа и трубы, и вес детали надо умножить и на её
количество в изделии, и на количество самих изделий. Плоский список такого
не считает — в нём пришлось бы перемножать в уме и вбивать итог руками.

Арифметика вся здесь: вес = табличная масса ГОСТ × длина или площадь.
Размеры вводятся в МИЛЛИМЕТРАХ, справочные массы даны в кг/м и кг/м²,
перевод делается явно — именно на этом месте ошибаются в тысячу раз.

Марка стали в арифметике НЕ участвует, только атрибут для документов.
"""

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import ValidationError

MM_IN_M = 1000.0


class MetalSpec(models.Model):
    _name = "pmk.metal.spec"
    _description = "Спецификация металлопроката"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one("res.partner", "Клиент", tracking=True)
    note = fields.Char("Примечание")
    product_ids = fields.One2many("pmk.metal.spec.product", "spec_id", "Изделия", copy=True)

    total_weight = fields.Float("Итого, кг", compute="_compute_totals", store=True, digits=(12, 3))
    total_weight_t = fields.Float("Итого, т", compute="_compute_totals", store=True, digits=(12, 4))
    total_products = fields.Integer("Изделий", compute="_compute_totals", store=True)

    # Итог спецификации складывается из весов изделий. Добавлены и
    # отфильтрованные наборы: без них правка во вкладке не доходила до
    # верхнего уровня — цепочка деталь → изделие → спецификация рвалась
    # на первом же звене.
    @api.depends(
        "product_ids.weight_total",
        "product_ids.qty",
        "product_ids.line_ids",
        "product_ids.line_linear_ids",
        "product_ids.line_sheet_ids",
        "product_ids.line_fastener_ids",
        "product_ids.line_paint_ids",
    )
    def _compute_totals(self):
        for spec in self:
            spec.total_weight = sum(spec.product_ids.mapped("weight_total"))
            # Тонны рядом с килограммами: на тридцатитонной спецификации
            # «30000 кг» глазом уже не читается.
            spec.total_weight_t = spec.total_weight / 1000.0
            spec.total_products = len(spec.product_ids)
            spec.total_details = sum(len(p.line_ids) for p in spec.product_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.metal.spec") or "Черновик"
        return super().create(vals_list)


class MetalSpecProduct(models.Model):
    """Изделие спецификации: название, количество и состав."""

    _name = "pmk.metal.spec.product"
    _description = "Изделие спецификации"
    _order = "sequence, id"

    spec_id = fields.Many2one("pmk.metal.spec", "Спецификация", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    name = fields.Char("Изделие", required=True)
    qty = fields.Integer("Количество, шт", required=True, default=1)
    note = fields.Char("Примечание")

    line_ids = fields.One2many("pmk.metal.spec.line", "product_id", "Детали", copy=True)
    # Две отдельные таблицы вместо одной: у проката спрашивают длину, у листа
    # две стороны, и в общей таблице половина колонок всегда пустует.
    line_linear_ids = fields.One2many(
        "pmk.metal.spec.line", "product_id", "Прокат",
        domain=[("calc_mode", "=", "linear")], context={"default_calc_mode": "linear"})
    line_sheet_ids = fields.One2many(
        "pmk.metal.spec.line", "product_id", "Лист",
        domain=[("calc_mode", "=", "sheet")], context={"default_calc_mode": "sheet"})
    line_fastener_ids = fields.One2many(
        "pmk.metal.spec.line", "product_id", "Метизы",
        domain=[("calc_mode", "=", "fastener")], context={"default_calc_mode": "fastener"})
    line_paint_ids = fields.One2many(
        "pmk.metal.spec.line", "product_id", "Покрытие",
        domain=[("calc_mode", "=", "paint")], context={"default_calc_mode": "paint"})

    weight_one = fields.Float("Вес изделия, кг", compute="_compute_weight", store=True, digits=(12, 3))
    weight_total = fields.Float("Вес всего, кг", compute="_compute_weight", store=True, digits=(12, 3))

    # Подписываемся на ВСЕ ТРИ поля деталей, а не только на общее.
    # Причина: детали правят во вкладках «Прокат» и «Лист», то есть через
    # line_linear_ids / line_sheet_ids, а вес был подписан на line_ids.
    # Для Odoo это разные поля, хоть и одна таблица, поэтому в браузере
    # пересчёт не срабатывал — вес обновлялся только после сохранения,
    # когда данные перечитываются из базы.
    @api.depends(
        "line_ids.weight_total",
        "line_linear_ids.weight_total",
        "line_sheet_ids.weight_total",
        "line_fastener_ids.weight_total",
        "line_paint_ids.weight_total",
        "qty",
    )
    def _compute_weight(self):
        for product in self:
            product.weight_one = sum(product.line_ids.mapped("weight_total"))
            product.weight_total = product.weight_one * (product.qty or 0)

    @api.constrains("qty")
    def _check_qty(self):
        for product in self:
            if product.qty <= 0:
                raise ValidationError("Количество изделий должно быть больше нуля.")


class MetalSpecLine(models.Model):
    """Деталь изделия. Количество — НА ОДНО изделие."""

    _name = "pmk.metal.spec.line"
    _description = "Деталь изделия"
    _order = "sequence, id"

    product_id = fields.Many2one("pmk.metal.spec.product", "Изделие", required=True, ondelete="cascade")
    spec_id = fields.Many2one(related="product_id.spec_id", store=True, string="Спецификация")
    sequence = fields.Integer("№", default=10)
    detail_name = fields.Char("Деталь")

    calc_mode = fields.Selection(
        [("linear", "Прокат"), ("sheet", "Лист"),
         ("fastener", "Метиз"), ("paint", "Покрытие")],
        "Вид", required=True, default="linear")

    # Каскад: сперва вид проката, типоразмер ищется уже внутри него.
    # В общем списке из 665 позиций поиск превращается в перебор.
    type_id = fields.Many2one("pmk.metal.profile.type", "Вид проката")
    profile_id = fields.Many2one("pmk.metal.profile", "Типоразмер")
    sheet_id = fields.Many2one("pmk.metal.sheet", "Лист")
    grade_id = fields.Many2one("pmk.metal.grade", "Марка стали")
    fastener_id = fields.Many2one("pmk.metal.fastener", "Метиз")
    paint_id = fields.Many2one("pmk.paint.coating", "Покрытие")

    # Площадь окраски считается из состава изделия по площади погонного метра
    # сортамента. Поле доступно и для ручного ввода: пока характеристика в
    # справочнике не заполнена, площадь можно задать напрямую.
    area_m2 = fields.Float(
        "Площадь окраски, м²", compute="_compute_paint_area", store=True,
        readonly=False, digits=(12, 4))

    # Требуемая толщина покрытия. Подставляется базовая из справочника, но
    # заказчик может потребовать другую — тогда расход пересчитывается
    # пропорционально: 120 г/м² при 20 мкм превращаются в 300 г/м² при 50 мкм.
    paint_thickness_um = fields.Float(
        "Толщина покрытия, мкм", digits=(8, 1),
        help="Толщина сухой плёнки по требованию заказчика. "
             "Пусто — берётся базовая из справочника.")

    length_mm = fields.Float("Длина, мм", digits=(12, 1))
    a_mm = fields.Float("A, мм", digits=(12, 1))
    b_mm = fields.Float("B, мм", digits=(12, 1))
    qty = fields.Integer("Кол-во на изделие", required=True, default=1)

    weight_one = fields.Float("Вес шт, кг", compute="_compute_weight", store=True, digits=(12, 3))
    weight_total = fields.Float("Вес в изделии, кг", compute="_compute_weight", store=True, digits=(12, 3))

    @api.depends("product_id.line_linear_ids.length_mm",
                 "product_id.line_linear_ids.qty",
                 "product_id.line_linear_ids.profile_id",
                 "product_id.line_sheet_ids.a_mm",
                 "product_id.line_sheet_ids.b_mm",
                 "product_id.line_sheet_ids.qty",
                 "calc_mode")
    def _compute_paint_area(self):
        """Площадь окраски изделия: сумма поверхностей его деталей.

        У проката берётся площадь погонного метра из справочника — она
        заполняется отдельно, и пока пуста, вклад такой детали равен нулю.
        У листа площадь считается из размеров и удваивается: красят обе стороны.
        """
        for line in self:
            if line.calc_mode != "paint":
                line.area_m2 = line.area_m2 or 0.0
                continue
            product = line.product_id
            area = 0.0
            for d in product.line_linear_ids:
                if d.profile_id.surface_per_meter:
                    area += d.profile_id.surface_per_meter * (d.length_mm / MM_IN_M) * (d.qty or 0)
            for d in product.line_sheet_ids:
                area += (d.a_mm / MM_IN_M) * (d.b_mm / MM_IN_M) * 2 * (d.qty or 0)
            line.area_m2 = area

    @api.depends("calc_mode", "profile_id", "sheet_id", "fastener_id", "paint_id",
                 "length_mm", "a_mm", "b_mm", "area_m2", "paint_thickness_um", "qty")
    def _compute_weight(self):
        for line in self:
            one = 0.0
            if line.calc_mode == "linear" and line.profile_id:
                one = line.profile_id.mass_per_meter * (line.length_mm / MM_IN_M)
            elif line.calc_mode == "sheet" and line.sheet_id:
                one = line.sheet_id.mass_per_sqm * (line.a_mm / MM_IN_M) * (line.b_mm / MM_IN_M)
            elif line.calc_mode == "fastener" and line.fastener_id:
                # Метиз считается штуками: масса задана на штуку, длины нет.
                one = line.fastener_id.weight_kg
            elif line.calc_mode == "paint" and line.paint_id:
                # Краска: расход пропорционален ТОЛЩИНЕ сухой плёнки.
                # Слои сознательно не умножаем: они лишь способ набрать нужную
                # толщину, и множить на них — считать краску дважды.
                base = line.paint_id.base_thickness_um or 0.0
                want = line.paint_thickness_um or base
                factor = (want / base) if base else 1.0
                one = line.paint_id.consumption * factor * (line.area_m2 or 0.0)
            line.weight_one = one
            line.weight_total = one * (line.qty or 0)

    @api.onchange("calc_mode")
    def _onchange_calc_mode(self):
        """Чистим поля других видов, чтобы в документе не оставалось мусора."""
        keep = {
            "linear": {"type_id", "profile_id", "length_mm"},
            "sheet": {"sheet_id", "a_mm", "b_mm"},
            "fastener": {"fastener_id"},
            "paint": {"paint_id", "area_m2"},
        }.get(self.calc_mode, set())
        for field in ("type_id", "profile_id", "sheet_id", "fastener_id", "paint_id"):
            if field not in keep:
                self[field] = False
        for field in ("length_mm", "a_mm", "b_mm"):
            if field not in keep:
                self[field] = 0.0
        if self.calc_mode == "paint":
            self.qty = 1

    @api.onchange("paint_id")
    def _onchange_paint_id(self):
        """Подставляем базовую толщину — её и правят, если требование иное."""
        if self.paint_id and not self.paint_thickness_um:
            self.paint_thickness_um = self.paint_id.base_thickness_um

    @api.onchange("type_id")
    def _onchange_type_id(self):
        """Сменили вид — типоразмер от прежнего вида больше не подходит."""
        if self.profile_id and self.profile_id.type_id != self.type_id:
            self.profile_id = False

    # Жёсткой проверки размеров здесь НЕТ намеренно. Она срабатывала на каждом
    # сохранении строки и ругалась «Длина должна быть больше нуля», пока
    # пользователь ещё не дописал строку. Незаполненный размер и так виден:
    # вес остаётся нулевым.
    @api.constrains("qty")
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError("Количество детали должно быть больше нуля.")
