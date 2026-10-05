# -*- coding: utf-8 -*-
"""Расчёт металлопроката: изделия и их детали.

Слово — «расчёт» (разбор UX, шаг 39, 05.10.2026: одно понятие — одно слово).
«Спецификация» на заводе — только чертёж клиента; в коде модель по-прежнему
pmk.metal.spec, поля spec_id — техническое имя не меняется.

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
from odoo.exceptions import MissingError, ValidationError

from . import deleted_names

MM_IN_M = 1000.0


class MetalSpec(models.Model):
    _name = "pmk.metal.spec"
    _description = "Расчёт металлопроката"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one("res.partner", "Клиент", tracking=True)
    # Разбор UX, шаг 11 (Антон, 28.09.2026: «подставлять компанию контакта;
    # человек остаётся контактным лицом — делаем»). Клиент расчёта — всегда
    # компания: по нему список, поиск и группировка «Клиент», по нему
    # реквизиты в КП. Человек, с которым ведём заявку, — отдельно; КП
    # печатает его строкой «Контактное лицо».
    contact_id = fields.Many2one(
        "res.partner", "Контактное лицо", tracking=True,
        domain="[('parent_id', '=', partner_id)]",
        help="С кем ведём заявку у клиента. Печатается в КП.")
    # Разбор UX, шаг 11 (CA-03): поле печатается в КП строкой «Предмет», а
    # подпись «Примечание» звала писать туда для себя («уточнить толщину у
    # технолога»). Пометки для себя — в ленту внизу, «Внутренняя заметка».
    note = fields.Char(
        "Предмет КП (видит клиент)",
        help="Печатается в КП строкой «Предмет». Пометки для себя — в ленту "
             "внизу документа, кнопкой «Внутренняя заметка».")
    product_ids = fields.One2many("pmk.metal.spec.product", "spec_id", "Изделия", copy=True)

    total_weight = fields.Float("Итого, кг", compute="_compute_totals", store=True, digits=(12, 3))
    total_weight_t = fields.Float("Итого, т", compute="_compute_totals", store=True, digits=(12, 4))
    total_products = fields.Integer("Изделий", compute="_compute_totals", store=True)
    total_details = fields.Integer("Деталей", compute="_compute_totals", store=True)

    # Итог спецификации складывается из весов изделий. Добавлены и
    # отфильтрованные наборы: без них правка во вкладке не доходила до
    # верхнего уровня — цепочка деталь → изделие → спецификация рвалась
    # на первом же звене.
    @api.onchange("partner_id")
    def _onchange_partner_company(self):
        """Выбрали человека — клиентом становится его компания, сам он —
        контактным лицом. Частное лицо без компании остаётся клиентом."""
        for spec in self:
            person = spec.partner_id
            if person and not person.is_company and person.parent_id:
                spec.contact_id = person
                spec.partner_id = person.commercial_partner_id

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
            # Считаем по тем же четырём наборам: len(line_ids) не видел
            # несохранённых строк, и «Деталей» отставало до сохранения.
            spec.total_details = sum(
                len(p.line_linear_ids) + len(p.line_sheet_ids)
                + len(p.line_fastener_ids) + len(p.line_paint_ids)
                for p in spec.product_ids
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.metal.spec") or "Черновик"
        return super().create(vals_list)

    def copy_data(self, default=None):
        """Копия расчёта — новый расчёт на сегодня (приёмка 01.10.2026, R4).

        «Дублировать» делают, чтобы посчитать заявку заново. Копия со старой
        датой вставала в списке и в сделке ниже оригинала, хотя она новее.
        Цены на сегодня ставит мост (pmk_bridge, spec_cost.py).
        """
        default = dict(default or {})
        default.setdefault("date", fields.Date.context_today(self))
        return super().copy_data(default)


class MetalSpecProduct(models.Model):
    """Изделие расчёта: название, количество и состав."""

    _name = "pmk.metal.spec.product"
    _description = "Изделие расчёта"
    _order = "sequence, id"

    spec_id = fields.Many2one("pmk.metal.spec", "Расчёт", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    name = fields.Char("Изделие", required=True)
    qty = fields.Integer("Количество, шт", required=True, default=1)
    # Разбор UX, шаг 34: «Примечание» звало написать что-то для клиента, а
    # поле в КП не печатается (pmk_bridge/report/quotation_report.xml берёт
    # у изделия только название, цену и количество; письмо и тема КП — «Предмет
    # КП» расчёта). Поле рабочее, для себя — так и называется. В окне изделия
    # подпись длиннее: «Заметка для себя (в КП не идёт)».
    note = fields.Char(
        "Заметка для себя",
        help="В КП не идёт: как считали, что уточнить у технолога, откуда "
             "взяли размеры. Клиент видит название изделия, цену и количество.")

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
    # Разбор UX, шаг 34: новая строка проката берёт вид предыдущей — двутавры
    # вводят подряд, и подсказка типоразмера показывает их первыми. Окно
    # изделия передаёт его в default_type_id контекстом списка «Прокат»
    # (views/metal_spec_views.xml); редактор под строкой изделия берёт вид
    # прямо из строк (static/src/js/product_lines_field.js, addLine). Не
    # хранится: это подсказка экрану, а не свойство изделия.
    next_type_id = fields.Many2one(
        "pmk.metal.profile.type", "Вид для новой строки проката",
        compute="_compute_next_type_id",
        help="Вид последней строки проката, у которой он есть.")

    @api.depends("line_linear_ids.type_id", "line_linear_ids.sequence")
    def _compute_next_type_id(self):
        for product in self:
            typed = product.line_linear_ids.sorted("sequence").filtered("type_id")
            product.next_type_id = typed[-1:].type_id

    weight_one = fields.Float("Вес изделия, кг", compute="_compute_weight", store=True, digits=(12, 3))
    weight_total = fields.Float("Вес всего, кг", compute="_compute_weight", store=True, digits=(12, 3))

    @api.depends("name")
    def _compute_display_name(self):
        """Имя изделия — его название, как у ядра (поле name).

        Своё вычисление — только ради изделия, удалённого в этой же записи
        (доводка шага 30): ядро mail читает имена прежних изделий поля
        «Изделия» перед фиксацией, а названия в базе уже нет. MissingError
        выбрасывала из ленты ВСЕ отметки сохранения — удалили изделие и
        поменяли дату или «Предмет КП», а в ленте только «Удалено: …»
        (СМ-00024, 01.10.2026). См. deleted_names.py.
        """
        convert = self._fields["name"].convert_to_display_name
        for product in self:
            try:
                product.display_name = convert(product.name, product)
            except MissingError:
                product.display_name = deleted_names.recall(product, "удалённое изделие")

    def unlink(self):
        # Имя — до удаления: после него его не прочитать (deleted_names.py).
        deleted_names.remember(self)
        return super().unlink()

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
            # Складываем ЧЕТЫРЕ отфильтрованных набора, а не общий line_ids.
            # Причина та же, что и у подписки выше, но проявляется позже:
            # подписка срабатывает, а тело читает line_ids, который при
            # пересчёте в браузере ещё не знает о только что добавленной
            # строке — она пришла в line_linear_ids. Вес изделия оставался
            # прежним, хотя итог документа уже менялся.
            # Наборы не пересекаются и покрывают все виды деталей, поэтому
            # сумма та же, что по line_ids.
            product.weight_one = sum(
                product.line_linear_ids.mapped("weight_total")
                + product.line_sheet_ids.mapped("weight_total")
                + product.line_fastener_ids.mapped("weight_total")
                + product.line_paint_ids.mapped("weight_total")
            )
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
    spec_id = fields.Many2one(related="product_id.spec_id", store=True, string="Расчёт")

    def _compute_display_name(self):
        """Человеческое имя детали — для истории документа и ссылок.

        ⚠️ БЕЗ ЭТОГО ИСТОРИЯ НЕЧИТАЕМА. Odoo сам пишет в чаттер, что состав
        изменился, и подставляет имена записей. Без своего имени он печатает
        служебное представление — «pmk.metal.spec.line(56, 57, 58)», и по
        такой записи невозможно понять, что именно поменяли. Замечание
        владельца 27.09.2026: «хранение ревизий документа, кто и что в нём
        поменял понятным языком».
        """
        for line in self:
            item = (line.profile_id or line.sheet_id
                    or line.fastener_id or line.paint_id)
            parts = []
            if line.detail_name:
                parts.append(line.detail_name)
            if item:
                parts.append(item.display_name)
            size = line._size_label()
            if size:
                parts.append(size)
            if line.qty:
                parts.append("%s шт" % line.qty)
            line.display_name = ", ".join(parts) or "деталь"

    def _size_label(self):
        """Размеры детали одной строкой, как их вводил менеджер."""
        self.ensure_one()
        if self.calc_mode == "linear" and self.length_mm:
            return "%g мм" % self.length_mm
        if self.calc_mode == "sheet" and (self.a_mm or self.b_mm):
            return "%g×%g мм" % (self.a_mm or 0, self.b_mm or 0)
        return ""
    sequence = fields.Integer("№", default=10)
    detail_name = fields.Char("Деталь")

    calc_mode = fields.Selection(
        [("linear", "Прокат"), ("sheet", "Лист"),
         ("fastener", "Метиз"), ("paint", "Покрытие")],
        "Вид", required=True, default="linear")

    # Вид проката подставляется сам из типоразмера (разбор UX, шаг 34). Было
    # два списка на деталь — сперва вид, потом типоразмер внутри вида («Двутавр»
    # / «Двутавр 12Б2»). Теперь поле одно — «Типоразмер»: его поиск понимает
    # сокращения вида («уг 50х5», «двут 20ш»; size_search.py), а вид строки
    # берётся из выбранной позиции.
    #
    # Вычисляемое с правкой, а не related: у новой строки вид приходит раньше
    # типоразмера — от предыдущей строки (default_type_id, см. next_type_id
    # изделия), и по нему подсказка показывает свои типоразмеры первыми.
    # Без типоразмера вид остаётся каким был. Колонка в базе прежняя: при
    # обновлении модуля Odoo не пересчитывает существующую колонку, старые
    # строки не меняются. Выбрать вид руками можно колонкой «Вид проката» в
    # меню колонок окна изделия (скрыта по умолчанию) — тогда чужой
    # типоразмер очищается (_onchange_type_id).
    type_id = fields.Many2one(
        "pmk.metal.profile.type", "Вид проката",
        compute="_compute_type_id", store=True, readonly=False, copy=True,
        help="Подставляется сам из типоразмера. У новой строки — вид "
             "предыдущей: подсказка типоразмера показывает его первым.")
    # Отбора по виду у поля больше нет (шаг 34): вид предыдущей строки
    # прятал бы все прочие типоразмеры, и «уг 50х5» после двутавров не
    # находил бы ничего. Вместо отбора — порядок: свой вид первым
    # (контекст pmk_prefer_type_id в виде, name_search справочника).
    profile_id = fields.Many2one("pmk.metal.profile", "Типоразмер")

    @api.depends("profile_id")
    def _compute_type_id(self):
        for line in self:
            # Без типоразмера — вид как был (у новой строки — от предыдущей).
            # Прежнее значение читать здесь можно: ядро на время вычисления
            # отдаёт его из кэша или базы (fields.py, compute_value).
            line.type_id = line.profile_id.type_id if line.profile_id else line.type_id

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
    # Вычисляемое с возможностью правки: базовая толщина подставляется сама,
    # но её переопределяют, когда заказчик требует другую плёнку. Через
    # onchange так не сделать — он срабатывает только в интерфейсе, и при
    # создании документа из кода или импортом поле осталось бы пустым.
    paint_thickness_um = fields.Float(
        "Толщина покрытия, мкм", compute="_compute_paint_thickness",
        store=True, readonly=False, digits=(8, 1),
        help="Толщина сухой плёнки. По умолчанию базовая из справочника; "
             "измените, если заказчик требует другую — расход пересчитается.")

    @api.depends("paint_id")
    def _compute_paint_thickness(self):
        for line in self:
            if line.calc_mode == "paint" and line.paint_id and not line.paint_thickness_um:
                line.paint_thickness_um = line.paint_id.base_thickness_um
            elif line.calc_mode != "paint":
                line.paint_thickness_um = 0.0

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
