# -*- coding: utf-8 -*-
"""Станок лазерной резки.

ПОЧЕМУ СВОЙ СПРАВОЧНИК, А НЕ НАСЛЕДОВАНИЕ mrp.workcenter.

Соблазн был: у рабочего центра уже есть time_start и time_stop, и на словах это
«загрузка и разгрузка». Смотрим, что это на самом деле (Odoo 19,
mrp/models/mrp_workcenter.py, строки 42–43 и 631–632):

    time_start = fields.Float('Setup Time')
    time_stop  = fields.Float('Cleanup Time')
    ...
    time_start = fields.Float('Setup Time (minutes)', ...)  # mrp.workcenter.capacity

Это наладка и уборка НА РАБОЧЕЕ ЗАДАНИЕ: mrp прибавляет их к операции один раз,
а между ними умножает штучное время на количество. У нас другая физика — стол
загружают и разгружают на КАЖДЫЙ ЛИСТ. В задании на 8 листов это восемь
загрузок и восемь разгрузок, а не одна наладка. Положить наши минуты в чужие
поля значит либо занизить время в восемь раз, либо молча сломать арифметику
mrp тому, кто заведёт на этом же центре рабочее задание.

Второй довод — область действия. `_inherit = "mrp.workcenter"` добавляет поля
«мощность лазера» и «максимальная толщина» ВСЕМ рабочим центрам: сварке,
покраске, сборке. Пять лазерных полей в карточке покрасочной камеры — это не
мелочь, это то, из-за чего потом никто не может найти нужное поле.

Поэтому справочник свой, а связь с рабочим центром — необязательным полем.
Когда участок заведут в производственные заказы, станок будет привязан к своему
рабочему центру, и ни одна цифра не переедет в чужие поля.
"""

from odoo.exceptions import UserError
from odoo import api, fields, models
from odoo.fields import Domain

from . import labels


def table_size_label(width_mm, length_mm):
    """«1500×6000» из ширины и длины стола; не задана хоть одна — пусто.

    Целые миллиметры без хвоста нулей: у стола дробных размеров не бывает,
    а «1500,0×6000,0» читается хуже. Разряды без пробела — как в габарите
    листа («1500x6000»), иначе подпись разъезжается на два слова.
    """
    if not width_mm or not length_mm:
        return False
    return "%g×%g" % (width_mm, length_mm)


class LaserMachine(models.Model):
    _name = "pmk.laser.machine"
    _description = "Лазерный станок"
    _order = "sequence, name"

    name = fields.Char("Станок", required=True)
    sequence = fields.Integer("Порядок", default=10)
    active = fields.Boolean("Активен", default=True)

    # Мощность — то, чем два наших станка и отличаются. В арифметику норматива
    # она не входит НАМЕРЕННО: скорость выводится из замеров этого станка, а не
    # из его киловатт. Поле нужно технологу, чтобы выбрать, куда отдать десятку.
    # aggregator=None у характеристик станка (разбор UX, шаг 24): сумма
    # киловатт, минут загрузки или габаритов стола двух станков в строке
    # группы ничего не значит. «Минут в смене» сумму оставляет: это ёмкость
    # участка на день.
    power_kw = fields.Float("Мощность, кВт", digits=(6, 1), aggregator=None)

    load_min = fields.Float(
        "Загрузка стола, мин/лист", digits=(6, 2), required=True, default=2.0, aggregator=None,
        help="Константа станка: сколько занимает положить лист на стол. "
             "Умножается на число листов задания, а не берётся один раз.")
    unload_min = fields.Float(
        "Разгрузка стола, мин/лист", digits=(6, 2), required=True, default=3.0, aggregator=None,
        help="Снять детали и убрать остаток. Тоже на каждый лист.")

    max_thickness_mm = fields.Float(
        "Максимальная толщина, мм", digits=(6, 1), aggregator=None,
        help="Рамка для технолога: задание толще этого станок не возьмёт.")
    # Антон 15.10.2026: «3 кВт до 20 мм, до 6 мм на воздухе; 20 кВт до 60 мм, до 20 мм на
    # воздухе — воздух приоритет, он дешевле кислорода». Станок новой программы раскроя
    # выбирается сначала по воздуху (_for_thickness).
    air_max_thickness_mm = fields.Float(
        "Воздухом до, мм", digits=(6, 1), aggregator=None,
        help="До этой толщины станок режет на воздухе — дешевле кислорода. Новая программа раскроя "
             "берёт станок, который режет её толщину на воздухе.")
    # «В раскроях иногда листы 1505×3005 — это допустимо для маленького станка» (15.10.2026).
    sheet_tolerance_mm = fields.Float(
        "Лист больше стола на, мм", digits=(6, 0), default=0.0, aggregator=None,
        help="Насколько лист может быть больше стола по каждой стороне: 5 мм — лист 1505×3005 "
             "проходит на стол 1500×3000.")
    max_width_mm = fields.Float("Стол, ширина мм", digits=(8, 0), aggregator=None)
    max_length_mm = fields.Float("Стол, длина мм", digits=(8, 0), aggregator=None)
    # Разбор UX, шаг 25: габарит стола одной колонкой списка — «1500×6000»,
    # как пишут габарит листа (ширина × длина, характеристика «1500x6000»
    # у листа в номенклатуре): технолог сверяет лист со столом глазами.
    # Не хранится — это подпись из двух полей выше, не новое значение.
    table_size_label = fields.Char(
        "Стол, мм", compute="_compute_table_size_label",
        help="Ширина × длина стола. Пусто — размеры стола не заданы.")

    shift_minutes = fields.Integer(
        "Минут в смене", default=480,
        help="Ёмкость станка на день. Нужна на экране загрузки участка: "
             "480 минут — восьмичасовая смена без обеда.")

    workcenter_id = fields.Many2one(
        "mrp.workcenter", "Рабочий центр", ondelete="set null",
        help="Необязательная связь. Заполняется, когда участок заводят в "
             "производственные заказы: тогда станок один и тот же, а не два "
             "разных справочника с похожими названиями.")

    note = fields.Text("Примечание")

    @api.depends("max_width_mm", "max_length_mm")
    def _compute_table_size_label(self):
        for machine in self:
            machine.table_size_label = table_size_label(
                machine.max_width_mm, machine.max_length_mm)

    # ------------------------------------------------------------------
    # Короткое имя в колонках списков (разбор UX, шаг 36)
    # ------------------------------------------------------------------
    # В списке заданий «Лазер №1» и «Лазер №2» обрезались и ничего не
    # говорили: станки отличаются мощностью, по ней технолог и выбирает,
    # куда отдать десятку. В колонке списка — мощность («6 кВт»), в формах и
    # строках групп — полное имя. Включает короткое имя контекст поля в
    # списке: context="{'pmk_machine_short': True}". Отдельного поля
    # «Короткое имя» не заводим: мощность заполнена у обоих станков и разная.

    @api.depends("name", "power_kw")
    @api.depends_context("pmk_machine_short")
    def _compute_display_name(self):
        short = self._short_labels() if self.env.context.get("pmk_machine_short") else {}
        for machine in self:
            machine.display_name = short.get(machine.id) or machine.name

    def _fits_sheet(self, width_mm, length_mm):
        """Лист помещается на стол с допуском станка (1505×3005 на 1500×3000 при 5 мм)."""
        self.ensure_one()
        if not (self.max_width_mm and self.max_length_mm):
            return True
        a, b = sorted((width_mm, length_mm))
        c, d = sorted((self.max_width_mm, self.max_length_mm))
        tol = self.sheet_tolerance_mm or 0.0
        return a <= c + tol and b <= d + tol

    def _short_labels(self):
        """{id станка: «6 кВт»} — только у станков с мощностью, которой нет у
        другого активного станка. Два «6 кВт» в одной колонке не различить —
        у таких остаётся полное имя."""
        count = {}
        for machine in self.with_context(active_test=True).search([]):
            key = round(machine.power_kw or 0.0, 1)
            count[key] = count.get(key, 0) + 1
        result = {}
        for machine in self:
            label = labels.power_label(machine.power_kw)
            if label and count.get(round(machine.power_kw or 0.0, 1), 0) <= 1:
                result[machine.id] = label
        return result

    # Поиск понимает и короткое имя (доводка шага 36). Колонка списка
    # показывает «6 кВт», а поиск по станку шёл только по имени («Лазер №2»):
    # набрал «6 кВт» в поиске заданий, загрузки, замеров, нормативов или
    # «Очереди листов» — пусто, и выпадашка выбора станка тоже пуста. Короткие
    # имена считаются тем же правилом, что в колонке (_short_labels): станков
    # два-три, перебор их в памяти дешевле отдельного хранимого поля.
    # Сравнение — без пробелов и регистра (labels.search_key): «6кВт»,
    # «6 квт» и «6 к» на полпути набора находят «6 кВт».

    @api.model
    def _search_display_name(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            # Ядро возьмёт положительный оператор и само построит отрицание
            # (orm/domains.py, _optimize_field_search_method) — короткое имя
            # учтётся и в «не содержит».
            return NotImplemented
        domain = Domain(super()._search_display_name(operator, value))
        hits = self._short_label_hits(operator, value)
        if hits:
            domain |= Domain("id", "in", hits)
        return domain

    @api.model
    def _short_label_hits(self, operator, value):
        """id станков, чьё короткое имя подходит под условие поиска."""
        if operator in ("ilike", "like") and isinstance(value, str) and value.strip():
            needle = labels.search_key(value)
            match = lambda label: needle in labels.search_key(label)  # noqa: E731
        elif operator == "in" and isinstance(value, (list, tuple, set, frozenset)):
            wanted = {labels.search_key(v) for v in value if isinstance(v, str) and v.strip()}
            match = lambda label: labels.search_key(label) in wanted  # noqa: E731
        else:
            return []
        short = self.search([])._short_labels()
        return [machine_id for machine_id, label in short.items() if match(label)]

    @api.model
    def _for_thickness(self, thickness_mm):
        """Станок для новой программы раскроя: тянет толщину; сначала те, что режут её на воздухе
        (дешевле кислорода), из них — младший (меньше мощность). Технолог сменит в программе."""
        machines = self.search([])
        fit = machines.filtered(lambda m: not m.max_thickness_mm or m.max_thickness_mm >= thickness_mm)
        fit = fit.sorted(lambda m: (not (m.air_max_thickness_mm and m.air_max_thickness_mm >= thickness_mm),
                                    m.power_kw or 1e9, m.max_thickness_mm or 1e9))
        if not (fit or machines):
            raise UserError("Нет ни одного станка — заведите его в «Лазерная резка → Настройка → Станки».")
        return (fit or machines)[:1]

    _load_positive = models.Constraint(
        "CHECK(load_min >= 0 AND unload_min >= 0)",
        "Загрузка и разгрузка стола не могут быть отрицательными.",
    )
    _shift_positive = models.Constraint(
        "CHECK(shift_minutes > 0)",
        "В смене должно быть больше нуля минут.",
    )
