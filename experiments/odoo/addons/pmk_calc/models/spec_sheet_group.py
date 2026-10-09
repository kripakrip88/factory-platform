# -*- coding: utf-8 -*-
"""«Лист раскладки» — группа листовых деталей расчёта (шаг З-13, 09.10.2026).

Детали одного листа (позиция справочника: толщина, вид), одной марки стали
и одного габарита режут из одного проката — значит, их можно класть на лист
вместе. Детали без выбранного листа — своя группа «Лист не выбран», но
только «отдельно»: толщина неизвестна. Группа
хранит ответ «сколько листов этого листа купить»: вместе или отдельно,
использование, схема словами. Детали группы — строки расчёта со ссылкой
layout_group_id; у каждой своя доля листов (spec_layout.py).

Группы заводит и переписывает только кнопка «Разложить листы (черновик)»
(MetalSpecLayout._pmk_layout_groups); правка детали гасит группу
(_pmk_reset_layout). Вручную группу не создают и не удаляют — на вкладке
«Раскладка» у таблицы нет ни «Добавить», ни корзины. В техническом расчёте
инженер вписывает в группу «Листов по факту» (pmk_tech).

Цена листа сюда не входит: числа раскладки от цен не зависят. Себестоимость
по-прежнему по чистому весу (карточка 12 отложена: обрезки листа идут в
дело).
"""

from odoo import api, fields, models

from .sheeting import SHEET_USE_COUNTED, group_scheme_text, part_label, sheet_use_label
from .spec_layout import SHEET_SIZES


class MetalSpecSheetGroup(models.Model):
    _name = "pmk.metal.spec.sheet.group"
    _description = "Лист раскладки"
    _order = "sequence, id"

    spec_id = fields.Many2one(
        "pmk.metal.spec", "Расчёт", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer("Порядок", default=10)
    sheet_id = fields.Many2one(
        "pmk.metal.sheet", "Лист", ondelete="set null", readonly=True,
        help="Позиция справочника: вид и толщина листа.")
    # Доработка З-13: марка — в ключе группы. Ст3 и 09Г2С одной толщины на
    # общий лист не лягут. Пусто — марка у деталей не выбрана.
    grade_id = fields.Many2one(
        "pmk.metal.grade", "Марка стали", ondelete="set null", readonly=True,
        help="Марка стали деталей группы. Детали разных марок на общий лист "
             "не кладём.")
    sheet_size = fields.Selection(
        SHEET_SIZES, "Габарит", readonly=True,
        help="Из какого листа режем детали группы.")
    line_ids = fields.One2many(
        "pmk.metal.spec.line", "layout_group_id", "Детали", readonly=True)
    line_count = fields.Integer(
        "Деталей", readonly=True,
        help="Сколько листовых деталей расчёта режется из этого листа.")
    sheets = fields.Integer(
        "Листов", readonly=True,
        help="Сколько листов купить под все детали группы — черновая "
             "раскладка, верхняя оценка: технолог уложит плотнее.")
    sheets_separate = fields.Integer(
        "Раздельно", readonly=True,
        help="Сколько листов вышло бы, если резать каждую деталь на своих "
             "листах (так считалось до 09.10.2026).")
    mode = fields.Selection(
        [("joint", "вместе"), ("separate", "отдельно")], "Как",
        default="separate", readonly=True,
        help="«вместе» — детали лягут на общие листы, и это дало меньше "
             "листов; «отдельно» — совместная укладка не дала выигрыша.")
    # На экране — словом с учётом состояния: погашенная совместная группа
    # не «отдельно», а «не считалась» (доработка З-13; цвет серой строки
    # повторён словом).
    mode_label = fields.Char(
        "Как", compute="_compute_mode_label",
        help="«вместе» — детали лягут на общие листы; «отдельно» — каждая "
             "на своих; «не считалась» — деталь группы правили после "
             "раскладки: нажмите «Разложить листы (черновик)».")
    state = fields.Selection(
        [("none", "Не считалась"), ("ok", "Посчитана")], "Состояние",
        default="none", readonly=True,
        help="«Не считалась» — деталь группы правили после раскладки: "
             "нажмите «Разложить листы (черновик)».")
    utilization_pct = fields.Float(
        "Использование, %", digits=(5, 1), readonly=True,
        help="Площадь деталей группы к площади купленных листов.")
    scheme = fields.Char(
        "Схема", readonly=True,
        help="Что лежит на листе: сколько листов какого варианта, деталь — "
             "штук на лист.")
    parts_label = fields.Char(
        "Детали группы", readonly=True,
        help="Размеры и количество деталей группы на весь заказ.")
    use_label = fields.Char(
        "Использование", compute="_compute_use",
        help="Меньше 50 % — жёлтым («мало»), меньше 20 % — красным («очень "
             "мало»): лист покупается ради малой детали.")
    use_level = fields.Selection(
        [("none", "Не считалась"), ("ok", "Норма"),
         ("low", "Мало"), ("bad", "Очень мало")],
        "Уровень использования", compute="_compute_use")

    @api.depends("state", "mode")
    def _compute_mode_label(self):
        modes = dict(self._fields["mode"].selection)
        for group in self:
            group.mode_label = (modes.get(group.mode, "") if group.state == "ok"
                                else "не считалась")

    def _pmk_layout_key(self):
        """Ключ группы — тот же, что у деталей в _pmk_layout_groups:
        (лист, марка, габарит)."""
        self.ensure_one()
        return (self.sheet_id.id or False, self.grade_id.id or False, self.sheet_size)

    @api.depends("state", "utilization_pct", "sheets")
    def _compute_use(self):
        for group in self:
            state = "ok" if group.state == "ok" and group.sheets else "none"
            label, level = sheet_use_label(group.utilization_pct, state)
            group.use_label = label
            group.use_level = level

    def _pmk_refresh_separate(self):
        """Итог группы «отдельно» по её деталям — после удаления детали.

        Числа деталей в такой группе свои (каждая на своих листах), поэтому
        итог — их сумма; детали не пересчитываем («гасим, а не пересчитываем
        молча» — здесь и гасить нечего)."""
        for group in self:
            lines = group.line_ids
            counted = lines.filtered(lambda l: l.layout_state in SHEET_USE_COUNTED)
            sheets = sum(lines.mapped("layout_sheets"))
            width, length = (lines[:1]._layout_sheet_dims() if lines else (0.0, 0.0))
            area = sum((line.a_mm or 0.0) * (line.b_mm or 0.0)
                       * (line.qty or 0) * (line.product_id.qty or 0) for line in counted)
            whole = sheets * width * length
            labels = {line.id: part_label(line.a_mm, line.b_mm) for line in lines}
            patterns = {}
            for line in counted:
                if line.layout_sheets:
                    pattern = ((line.id, line.layout_per_sheet),)
                    patterns[pattern] = patterns.get(pattern, 0) + line.layout_sheets
            group.write({
                "line_count": len(lines),
                "sheets": sheets,
                "sheets_separate": sheets,
                "utilization_pct": round(area / whole * 100.0, 1) if whole else 0.0,
                "scheme": group_scheme_text(
                    sorted(patterns.items(), key=lambda item: -item[1]), labels) or False,
                "parts_label": ", ".join(
                    "%s ×%s" % (labels[line.id], (line.qty or 0) * (line.product_id.qty or 0))
                    for line in lines),
            })

    @api.depends("sheet_id.display_name", "grade_id.display_name", "sheet_size")
    def _compute_display_name(self):
        """«Лист гладкий 3 мм, 1500 × 6000» (с маркой — «…, 09Г2С, 1500 ×
        6000») — для истории и ссылок."""
        sizes = dict(SHEET_SIZES)
        for group in self:
            parts = [group.sheet_id.display_name or "Лист не выбран"]
            if group.grade_id:
                parts.append(group.grade_id.display_name)
            if group.sheet_size:
                parts.append(sizes.get(group.sheet_size, group.sheet_size))
            group.display_name = ", ".join(parts)
