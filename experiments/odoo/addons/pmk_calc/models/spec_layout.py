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

import hashlib
from collections import Counter

from markupsafe import Markup, escape

from odoo import Command, api, fields, models

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


# ─── Сигнал «Раскладка устарела» (разбор UX, шаг 56) ──────────────────────
#
# Антон 07.10: «Сделаем сигнализацию внутри системы что нужна перераскладка?»
# Гашение строк (выше) говорит про одну деталь и только на вкладке
# «Раскладка». Расчёту нужен свой признак, видный сразу на форме: детали
# добавили, поменяли размер или количество изделий после раскладки — число
# листов уже не про этот заказ. Признак показывает, а не запрещает: КП
# печатается и отправляется как раньше (сначала наблюдать, потом
# контролировать).
#
# КАК. В момент «Разложить листы» расчёт запоминает отпечаток своих листовых
# деталей — по ключу на деталь из того, от чего зависит её раскладка
# (layout_fingerprint). Ключ детали, которого нет в отпечатке, — деталь новая
# или изменилась после раскладки. Ключи считаются с повторами (мультимножество):
# две одинаковые детали — два ключа, и деталь, ставшая «как соседняя»,
# всё равно лишняя против отпечатка. Удалённая деталь сигнала не даёт: числа
# оставшихся верны. Цена листа в ключ не входит — числа раскладки от цены не
# зависят (см. MetalSpecLineLayout); сам лист (sheet_id: толщина, вид) — входит.
#
# Версия ключа меняется вместе с алгоритмом sheeting.py: после смены все
# разложенные расчёты станут «устарела» — так и должно быть.
LAYOUT_KEY_VERSION = 1
# Отпечаток расчётов, разложенных до 30.09.2026: тогда правка деталей ещё не
# гасила раскладку (доводка шага 32, коммит 2e189a8), и числа могли отстать
# от деталей. Ставит миграция 19.0.1.0.6; «Разложить листы» его заменяет.
LEGACY_FINGERPRINT = "до-исправления-30.09"


def _layout_key(sheet_id, a_mm, b_mm, qty_total, sheet_size):
    """Ключ одной листовой детали: 12 знаков sha1 от входов раскладки."""
    raw = repr((LAYOUT_KEY_VERSION, sheet_id or 0, round(a_mm or 0.0, 1),
                round(b_mm or 0.0, 1), int(qty_total or 0), sheet_size or "1500x6000"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _is_create(command):
    """Команда x2many «создать запись»: (0, virtual_id, vals)."""
    return (isinstance(command, (list, tuple)) and len(command) == 3
            and command[0] == Command.CREATE)


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

    # ─── Списки-зеркала деталей (исправление 08.10.2026) ──────────────────
    #
    # sheet_line_ids (и price_line_ids моста) — ВТОРОЙ ВЗГЛЯД на те же детали,
    # что лежат в изделиях. Деталь рождается только в изделии: без изделия её
    # не бывает (product_id обязателен).
    #
    # ⚠️ ПОЧЕМУ НОВЫЙ РАСЧЁТ НЕ СОХРАНЯЛСЯ. Новая листовая деталь в изделии
    # нового расчёта. Onchange расчёта считает себестоимость (мост) — читает
    # у детали spec_id, и ORM вписывает несохранённую деталь в зеркала
    # расчёта: в ответ уходит sheet_line_ids = [Command.create(...)] с
    # product_id = False (у нового изделия ещё нет номера). Браузер не знает,
    # что это та же деталь, что в изделии, и заводит у себя вторую запись.
    # Вкладка «Раскладка» редактируемая (габарит), поэтому при «Сохранить»
    # web_save присылает её создание: {layout_sheet_size: '1500x6000'} без
    # изделия — INSERT падает на NOT NULL product_id («Отсутствует
    # обязательное значение для поля 'Изделие'»). Каждый следующий onchange
    # добавлял ещё одну такую копию. Дефект с 25.09 (653c5f7, вкладка
    # «Раскладка»), всплыл 07.10 на первом новом расчёте с листом из окна.
    #
    # Лечение в два слоя:
    # 1) onchange не отдаёт в редактируемое зеркало новых деталей — они
    #    появятся на вкладке после сохранения (так и написано на вкладке);
    # 2) создание и запись расчёта отбрасывают «создать деталь» через
    #    зеркало без изделия — на случай открытой до исправления вкладки
    #    браузера или любого другого клиента.
    # Сама деталь без изделия не создаётся никаким путём — понятная ошибка
    # в MetalSpecLine.create (metal_spec.py).
    _pmk_line_mirrors = ("sheet_line_ids",)

    def onchange(self, values, field_names, fields_spec):
        result = super().onchange(values, field_names, fields_spec)
        value = result.get("value") or {}
        commands = value.get("sheet_line_ids")
        if isinstance(commands, list):
            kept = [cmd for cmd in commands if not _is_create(cmd)]
            if kept:
                value["sheet_line_ids"] = kept
            else:
                value.pop("sheet_line_ids")
        return result

    @api.model
    def _pmk_drop_mirror_creates(self, vals):
        """Копия vals без «создать деталь без изделия» в зеркалах."""
        clean = None
        for name in self._pmk_line_mirrors:
            commands = vals.get(name)
            if not isinstance(commands, list):
                continue
            kept = [cmd for cmd in commands
                    if not (_is_create(cmd) and not (cmd[2] or {}).get("product_id"))]
            if len(kept) != len(commands):
                clean = clean if clean is not None else dict(vals)
                clean[name] = kept
        return vals if clean is None else clean

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._pmk_drop_mirror_creates(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._pmk_drop_mirror_creates(vals))

    # Отпечаток листовых деталей на момент последней раскладки (шаг 56): ключи
    # через пробел, см. _layout_key. Пусто — не раскладывали (или копия:
    # раскладка в копию не переносится, R4). Служебное поле, на форме его нет.
    layout_fingerprint = fields.Text(
        "Отпечаток раскладки", copy=False, readonly=True,
        help="Чем были листовые детали, когда последний раз раскладывали "
             "листы. Отличаются сейчас — раскладка устарела.")
    layout_stale = fields.Boolean(
        "Раскладка устарела", compute="_compute_layout_stale",
        help="Листовые детали изменились после «Разложить листы»: число листов "
             "уже не про этот заказ. Ничего не блокирует — КП печатается.")
    layout_stale_text = fields.Char(
        "Почему раскладка устарела", compute="_compute_layout_stale")
    # Для списка расчётов: слово, а не галочка (цвет повторён словом).
    layout_stale_label = fields.Char(
        "Раскладка", compute="_compute_layout_stale")

    def _pmk_layout_lines(self):
        """Листовые детали расчёта — через изделия, а не зеркало sheet_line_ids:
        onchange не отдаёт в зеркало новых деталей (см. выше), а сигнал нужен
        и до сохранения."""
        self.ensure_one()
        return self.product_ids.line_sheet_ids

    def _pmk_layout_keys(self):
        """Ключи листовых деталей расчёта сейчас — список с повторами: две
        одинаковые детали дают два одинаковых ключа (сравнение — Counter).

        Габарит берётся из зеркала «Раскладка», если деталь там есть: габарит
        правят на вкладке, а на экране до сохранения зеркало и деталь в
        изделии — разные записи формы."""
        self.ensure_one()
        sizes = {line._origin.id: line.layout_sheet_size
                 for line in self.sheet_line_ids if line._origin.id}
        keys = []
        # Через изделие, а не line.product_id: на экране до сохранения
        # количество изделия — то, что набрано в строке «Состава».
        for product in self.product_ids:
            for line in product.line_sheet_ids:
                size = sizes.get(line._origin.id) or line.layout_sheet_size
                keys.append(_layout_key(
                    line.sheet_id._origin.id, line.a_mm, line.b_mm,
                    (line.qty or 0) * (product.qty or 0), size))
        return keys

    @api.depends(
        "layout_fingerprint",
        "product_ids.qty",
        "product_ids.line_sheet_ids.a_mm",
        "product_ids.line_sheet_ids.b_mm",
        "product_ids.line_sheet_ids.qty",
        "product_ids.line_sheet_ids.sheet_id",
        "product_ids.line_sheet_ids.layout_sheet_size",
        "product_ids.line_sheet_ids.layout_state",
        "sheet_line_ids.layout_sheet_size",
        "sheet_line_ids.layout_state",
    )
    def _compute_layout_stale(self):
        """Устарела: после раскладки появилась деталь, которой нет в
        отпечатке, или деталь погашена (layout_state «Не считалась» — так её
        гасят правка размера, количества, листа, габарита и количества
        изделий; spec_layout выше). Без отпечатка — не раскладывали, сигнала
        нет. Без листовых деталей — тоже нет."""
        for spec in self:
            stale, text, label = False, False, False
            saved = spec.layout_fingerprint
            lines = spec._pmk_layout_lines() if saved else spec.env["pmk.metal.spec.line"]
            if saved and lines:
                if saved == LEGACY_FINGERPRINT:
                    # Детали могли и не меняться — «могла устареть», а не
                    # «устарела»: и в плашке, и на вкладке, и в списке.
                    stale, label = True, "могла устареть"
                    text = ("Раскладка посчитана до исправления 30.09 и могла "
                            "устареть — нажмите «Разложить листы (черновик)»")
                else:
                    states = lines.mapped("layout_state") + spec.sheet_line_ids.mapped("layout_state")
                    # Мультимножества: новая деталь, совпавшая ключом с
                    # другой деталью отпечатка, — всё равно лишняя.
                    stale = ("none" in states
                             or bool(Counter(spec._pmk_layout_keys()) - Counter(saved.split())))
                    if stale:
                        label = "устарела"
                        text = ("Раскладка устарела: листовые детали изменились "
                                "после раскладки — нажмите «Разложить листы "
                                "(черновик)»")
            spec.layout_stale = stale
            spec.layout_stale_text = text
            spec.layout_stale_label = label

    def _pmk_store_layout_fingerprint(self):
        """Запомнить, из чего разложены листы (после «Разложить листы»)."""
        for spec in self:
            spec.layout_fingerprint = " ".join(sorted(spec._pmk_layout_keys())) or False

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
            # Шаг 56: отпечаток — после раскладки строк, плашка «Раскладка
            # устарела» гаснет.
            spec._pmk_store_layout_fingerprint()
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
