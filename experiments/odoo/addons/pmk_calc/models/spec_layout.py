# -*- coding: utf-8 -*-
"""Черновая раскладка в спецификации: сколько листов покупать под заказ.

ЗАЧЕМ КНОПКА, А НЕ АВТОМАТИЧЕСКИЙ ПЕРЕСЧЁТ. Замысел владельца: «менеджер нажал
сделать черновую раскладку и понял что надо либо идти к технологу и думать как
сэкономить либо вносит расчётную себестоимость в заказ». То есть раскладка —
это шаг решения, а не фоновая арифметика. Нажал — увидел число листов и долю
металла, и дальше выбирает сам.

Геометрия живёт отдельно, в sheeting.py: там чистые функции без базы, их
проверяют тесты без стенда. Здесь только поля документа и применение.

⚠️ РАСКЛАДКА СЧИТАЕТСЯ ПО КАЖДОЙ СТРОКЕ ОТДЕЛЬНО. Технолог кладёт на один лист
детали из разных позиций и за счёт этого выигрывает ещё. Наш расчёт так не
умеет и не должен: он даёт верхнюю оценку закупки, а экономия — работа цеха.
Поэтому сумма листов по строкам всегда не меньше того, что выйдет у технолога.
"""

from markupsafe import Markup, escape

from odoo import api, fields, models

from .sheeting import (
    DEFAULT_KERF_MM, SHEET_USE_COUNTED, plan_sheets, sheet_use_label)


def _plural(number, one, few, many):
    """Русское склонение при числе: 1 лист, 2 листа, 5 листов.

    В истории документа число листов встречается в каждой записи, и «1 листов»
    выдаёт машину. Мелочь, но читать такое каждый день.
    """
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


# ─── Черновая раскладка устаревает (доводка шага 32) ───────────────────────
#
# От чего зависит раскладка строки: размеры и количество детали, лист, вид,
# габарит, изделие (его количество множит заготовки). Поменялось одно из
# них — прежние «В листе / Листов / Использование» уже не про эту деталь.
LAYOUT_INPUTS = ("a_mm", "b_mm", "qty", "sheet_id", "calc_mode",
                 "layout_sheet_size", "product_id")
LAYOUT_RESULTS = ("layout_state", "layout_per_sheet", "layout_sheets",
                  "layout_scheme", "layout_utilization_pct")
# «Не считалась» — то же, что у новой строки.
LAYOUT_RESET = {
    "layout_state": "none",
    "layout_per_sheet": 0,
    "layout_sheets": 0,
    "layout_scheme": False,
    "layout_utilization_pct": 0.0,
}


def _mm_text(value):
    """Миллиметры без лишнего: 100.0 → «100», 120.5 → «120,5»."""
    text = "%.1f" % float(value or 0.0)
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",")


class MetalSpecLayout(models.Model):
    _inherit = "pmk.metal.spec"

    # Листовые детали всего документа одним списком — для вкладки «Раскладка».
    # Через изделия их не собрать в один список: строки лежат по изделиям, а
    # решение о закупке листа принимается по заказу целиком.
    sheet_line_ids = fields.One2many(
        "pmk.metal.spec.line", "spec_id", string="Листовые детали",
        domain=[("calc_mode", "=", "sheet")],
        help="Детали из листа по всему расчёту. Габарит листа меняется прямо "
             "здесь: у разных деталей он разный.")

    # ШИРИНЫ РЕЗА НА ФОРМЕ НЕТ. Она была, и владелец убрал её как лишнюю —
    # справедливо: рез лазера 0,2 мм тонет в допуске на ряд (5 мм), и на число
    # листов почти не влияет. Значение берётся константой из sheeting.py.
    # Появится станок с заметным резом — плазма режет до 2 мм — поле вернём.

    def action_draft_layout(self):
        """Кнопка «Разложить листы (черновик)»: сколько листов покупать.

        Разбор UX, шаг 32: прежнее название «Предварительный расчёт металла»
        не говорило, что делает кнопка, а стояла она в шапке документа —
        далеко от вкладки «Раскладка», где появляется результат. Теперь
        кнопка на самой вкладке. Имя метода прежнее: на него ссылаются
        вид и тесты.

        ⚠️ ГАБАРИТ БЕРЁТСЯ ИЗ СТРОКИ, А НЕ ИЗ ДОКУМЕНТА. Сначала он стоял на
        документе — один на весь заказ, и владелец сразу указал, что так
        неверно: в заказе листы разной толщины и разного размера, и резать их
        будут из разного проката.

        ⚠️ РЕЗУЛЬТАТ НЕ ИДЁТ В СЕБЕСТОИМОСТЬ. Она считается по чистому весу
        справочника. Этот расчёт — заготовка для технолога: он проверяет,
        подтверждает и отдаёт в закупку.
        """
        for spec in self:
            lines = spec.mapped("product_ids.line_sheet_ids")
            for line in lines:
                line._apply_draft_layout()
            spec._log_draft_layout(lines)
        return True

    def _log_draft_layout(self, lines):
        """Запись в историю: что насчитала кнопка.

        Результат раскладки живёт на вкладке и переписывается при следующем
        нажатии. В истории он остаётся: по ней видно, из какой цифры исходили,
        когда называли клиенту срок и цену.
        """
        self.ensure_one()
        # «Деталь в размер листа» (exact) — тоже посчитанная раскладка: лист
        # на каждую заготовку. Раньше такие строки в историю не попадали, и
        # расчёт из одних таких деталей писал «считать нечего».
        done = lines.filtered(lambda l: l.layout_state in SHEET_USE_COUNTED)
        if not done:
            self.message_post(body="Раскладка листов (черновик): считать "
                                   "нечего — листовых деталей с размерами нет.")
            return
        # Использование — той же подписью, что в колонке вкладки: «4,7 % ·
        # очень мало». В истории должно стоять то же слово, что на экране.
        rows = "".join(
            "<li>%s: %s %s %s, по %s %s в листе, использование %s</li>" % (
                escape(line.display_name), line.layout_sheets,
                _plural(line.layout_sheets, "лист", "листа", "листов"),
                dict(line._fields["layout_sheet_size"].selection).get(
                    line.layout_sheet_size, line.layout_sheet_size),
                line.layout_per_sheet,
                _plural(line.layout_per_sheet, "заготовка", "заготовки", "заготовок"),
                sheet_use_label(line.layout_utilization_pct, line.layout_state)[0])
            for line in done)
        total = sum(done.mapped("layout_sheets"))
        self.message_post(body=Markup(
            "<p>Раскладка листов (черновик): купить %s %s. "
            "Верхняя оценка, технолог уплотнит.</p><ul>%s</ul>" % (
                total, _plural(total, "лист", "листа", "листов"), rows)))


class MetalSpecLineLayout(models.Model):
    _inherit = "pmk.metal.spec.line"

    # Габарит листа у КАЖДОЙ строки свой: деталь 3 мм режут из одного листа,
    # деталь 10 мм — из другого, и размер проката может отличаться.
    layout_sheet_size = fields.Selection(
        [("1500x6000", "1500 × 6000"),
         ("1500x3000", "1500 × 3000"),
         ("1000x4000", "1000 × 4000")],
        "Габарит листа", default="1500x6000",
        help="Из какого листа режем эту деталь. По умолчанию 1500×6000 — "
             "на него заведены цены поставщика.")

    # Результаты раскладки не копируются (приёмка 01.10.2026, R4): копия
    # расчёта — новый расчёт, и раскладку в нём считают кнопкой заново. Числа
    # от цен не зависят (только от размеров, количеств, листа и габарита — они
    # копируются), но в ленте копии записи о раскладке нет, и «Листов купить»
    # без неё — цифра неизвестного происхождения. Габарит листа (вход) — копируется.
    layout_per_sheet = fields.Integer(
        "Заготовок в листе", readonly=True, copy=False,
        help="Сколько таких заготовок помещается в один лист при укладке "
             "рядами. Технолог обычно кладёт плотнее.")
    layout_sheets = fields.Integer(
        "Листов купить", readonly=True, copy=False,
        help="Сколько листов нужно под это количество заготовок во всём "
             "изделии. Неполный лист считается целым: купить половину нельзя.")
    layout_scheme = fields.Char(
        "Схема укладки", readonly=True, copy=False,
        help="Как легли заготовки: рядов на лист и поворот. «+ полосой» — "
             "остаток листа отрезан полосой и заполнен поперёк.")
    layout_state = fields.Selection(
        [("none", "Не считалась"),
         ("ok", "Посчитана"),
         ("no_size", "Нет габарита детали"),
         ("no_qty", "Нет количества"),
         ("too_big", "Деталь больше листа"),
         ("exact", "Деталь в размер листа")],
        "Состояние раскладки", default="none", readonly=True, copy=False)
    layout_utilization_pct = fields.Float(
        "Использование по раскладке, %", readonly=True, digits=(5, 1), copy=False,
        help="Площадь нужных заготовок к площади купленных листов. "
             "На малом заказе доля низкая честно: лист покупается целиком.")

    # ─── Вкладка «Раскладка»: 11 колонок → 8 (разбор UX, шаг 32) ──────────
    #
    # Не хранятся: это подписи к уже хранимым числам, а не новые данные.
    # Размер — «100×100» одной колонкой вместо двух «A, мм» и «B, мм»
    # (закрывает П-25): габарит детали читается как пара, а не как два числа.
    detail_size_label = fields.Char(
        "Размер, мм", compute="_compute_detail_size_label",
        help="Габарит заготовки: A × B. Круг Ø100 записывается квадратом "
             "100×100 — так его и выкраивают.")
    # Использование — подписью со словом: цвет в списке повторён словом
    # «мало» / «очень мало» (правило «цвет всегда повторён словом»).
    layout_use_label = fields.Char(
        "Использование", compute="_compute_layout_use",
        help="Какая доля купленных листов уйдёт в заготовки. Меньше 50 % — "
             "жёлтым: больше половины листа уйдёт в остаток. Меньше 20 % — "
             "красным: лист покупается ради малой детали, деньги замёрзнут в "
             "остатке. Верхняя оценка — технолог уложит плотнее.")
    layout_use_level = fields.Selection(
        [("none", "Не считалась"), ("ok", "Норма"),
         ("low", "Мало"), ("bad", "Очень мало")],
        "Уровень использования", compute="_compute_layout_use")

    @api.depends("calc_mode", "a_mm", "b_mm")
    def _compute_detail_size_label(self):
        for line in self:
            if line.calc_mode != "sheet" or not (line.a_mm or line.b_mm):
                line.detail_size_label = False
                continue
            line.detail_size_label = "%s×%s" % (
                _mm_text(line.a_mm), _mm_text(line.b_mm))

    @api.depends("layout_state", "layout_utilization_pct")
    def _compute_layout_use(self):
        for line in self:
            label, level = sheet_use_label(
                line.layout_utilization_pct, line.layout_state)
            line.layout_use_label = label
            line.layout_use_level = level

    def _layout_sheet_dims(self):
        """Габарит листа этой строки числами: (ширина, длина) в миллиметрах."""
        self.ensure_one()
        raw = (self.layout_sheet_size or "1500x6000").split("x")
        return float(raw[0]), float(raw[1])

    def _apply_draft_layout(self, kerf_mm=None):
        """Посчитать раскладку одной строки и записать результат."""
        self.ensure_one()
        if self.calc_mode != "sheet":
            return
        width, length = self._layout_sheet_dims()

        # Количество заготовок — на ВСЕ изделия: qty в строке задано на одно
        # изделие, а лист покупается под заказ целиком.
        total_qty = (self.qty or 0) * (self.product_id.qty or 0)
        plan = plan_sheets(
            width, length, self.a_mm, self.b_mm, total_qty,
            kerf_mm=kerf_mm or DEFAULT_KERF_MM)

        self.layout_per_sheet = plan["per_sheet"]
        self.layout_sheets = plan["sheets"]
        self.layout_scheme = plan["scheme"]
        self.layout_state = plan["state"]
        self.layout_utilization_pct = plan["utilization_pct"]

    @api.onchange("a_mm", "b_mm", "qty", "sheet_id", "layout_sheet_size")
    def _onchange_layout_stale(self):
        """Размеры поменяли — прежняя раскладка больше не про эту деталь.

        Гасим её, а не пересчитываем молча: число листов, посчитанное под
        другие размеры, опаснее отсутствующего — на него уже посмотрели и
        поверили.

        ⚠️ ЭТО ТОЛЬКО ВИД ДО СОХРАНЕНИЯ. Поля раскладки readonly, а браузер
        Odoo 19 не отправляет на сервер readonly-поля без force_save
        (record.js, _getChanges): после «Сохранить» возвращались старые
        числа рядом с новым размером. В базе раскладку гасит write() ниже.
        """
        for line in self:
            if line.layout_state != "none":
                line.update(LAYOUT_RESET)

    def _layout_inputs_changed(self, vals):
        """Меняет ли запись vals то, от чего зависит раскладка этой строки.

        Сравниваем со значением в базе через convert_to_cache: число
        округляется до точности поля, ссылка приходит id — запись того же
        значения («сохранили, ничего не меняя») раскладку не гасит.
        """
        self.ensure_one()
        for name in LAYOUT_INPUTS:
            if name not in vals:
                continue
            field = self._fields[name]
            try:
                new = field.convert_to_record(
                    field.convert_to_cache(vals[name], self), self)
            except ValueError:
                # Непонятное значение — считаем, что поменялось: ошибку
                # записи всё равно покажет сама запись ниже.
                return True
            if new != self[name]:
                return True
        return False

    def write(self, vals):
        """Гасим черновую раскладку В БАЗЕ, когда поменялось то, от чего она
        зависит (доводка шага 32).

        Сброс только через onchange не доходил до базы (см. выше): после
        смены габарита на вкладке «Раскладка» или размера детали в окне
        изделия и «Сохранить» рядом с новым размером стояли старые «В листе
        / Листов» и красное «очень мало». Сама раскладка пишет поля layout_*
        — такую запись не трогаем.
        """
        stale = self.browse()
        if (any(name in vals for name in LAYOUT_INPUTS)
                and not any(name in vals for name in LAYOUT_RESULTS)):
            stale = self.filtered(
                lambda l: l.layout_state != "none" and l._layout_inputs_changed(vals))
        result = super().write(vals)
        if stale:
            stale.write(dict(LAYOUT_RESET))
        return result


class MetalSpecProductLayout(models.Model):
    _inherit = "pmk.metal.spec.product"

    def write(self, vals):
        """Количество изделий множит заготовки: сменили его — раскладка листов
        этого изделия устарела (доводка шага 32). Гасим в базе: окно изделия
        полей раскладки не показывает, и onchange здесь не помог бы."""
        stale = self.env["pmk.metal.spec.line"]
        if "qty" in vals:
            qty = int(vals["qty"] or 0)
            stale = self.filtered(lambda p: p.qty != qty).mapped(
                "line_sheet_ids").filtered(lambda l: l.layout_state != "none")
        result = super().write(vals)
        if stale:
            stale.write(dict(LAYOUT_RESET))
        return result
