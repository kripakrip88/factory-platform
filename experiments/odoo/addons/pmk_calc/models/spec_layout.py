# -*- coding: utf-8 -*-
"""Черновая раскладка в спецификации: сколько листов покупать под заказ.

ЗАЧЕМ КНОПКА, А НЕ АВТОМАТИЧЕСКИЙ ПЕРЕСЧЁТ. Замысел владельца: «менеджер нажал
сделать черновую раскладку и понял что надо либо идти к технологу и думать как
сэкономить либо вносит расчётную себестоимость в заказ». То есть раскладка —
это шаг решения, а не фоновая арифметика. Нажал — увидел число листов и долю
металла, и дальше выбирает сам.

Геометрия живёт отдельно, в sheeting.py: там чистые функции без базы, их
проверяют тесты без стенда. Здесь только поля документа и применение.

⚠️ ДЕТАЛИ ОДНОГО ЛИСТА РАСКЛАДЫВАЮТСЯ ВМЕСТЕ (шаг З-13, 09.10.2026). До него
раскладка шла по каждой строке отдельно, и прогон Кытмановой показал цену:
93 листа вместо 76. Теперь детали одного листа (толщина, вид), одной марки
стали и одного габарита — группа «Лист раскладки» (pmk.metal.spec.sheet.group,
spec_sheet_group.py): сколько листов купить на группу, вместе или отдельно,
использование, схема. Вместе — только если листов строго меньше, чем
раздельно (sheeting.plan_group): никогда не хуже прежнего. Это всё ещё
верхняя оценка: технолог в CypCut уложит плотнее — в техническом расчёте
он вписывает «Листов по факту» (pmk_tech).

У строки детали поля прежние: «Листов купить» — её ДОЛЯ листов группы (по
площади), сумма долей = листы группы. Поэтому история, итог вкладки и
«Заявка на металл» (складывает листы строк) листов не задваивают. «В листе»
и «Схема» строки — свои, «если резать эту деталь отдельно». Легла ли деталь
на общие листы — layout_joint (от него «Вместе с»).
"""

import hashlib
from collections import Counter

from markupsafe import Markup, escape

from odoo import Command, api, fields, models

from .sheeting import (
    DEFAULT_KERF_MM, SHEET_USE_COUNTED, group_scheme_text, part_label,
    plan_group, plan_sheets, sheet_use_label)

# Габариты листа: у строки детали (layout_sheet_size) и у группы раскладки.
# ⚠️ Мина шага 57: цены заведены на 1500×6000 — список не трогаем.
SHEET_SIZES = [("1500x6000", "1500 × 6000"),
               ("1500x3000", "1500 × 3000"),
               ("1000x4000", "1000 × 4000")]
DEFAULT_SHEET_SIZE = "1500x6000"


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
# Марка стали (шаг З-13) — ключ группы: Ст3 и 09Г2С на один лист не лягут.
LAYOUT_INPUTS = ("a_mm", "b_mm", "qty", "sheet_id", "grade_id", "calc_mode",
                 "layout_sheet_size", "product_id")
LAYOUT_RESULTS = ("layout_state", "layout_per_sheet", "layout_sheets",
                  "layout_scheme", "layout_utilization_pct", "layout_joint")
# «Не считалась» — то же, что у новой строки.
LAYOUT_RESET = {
    "layout_state": "none",
    "layout_per_sheet": 0,
    "layout_sheets": 0,
    "layout_scheme": False,
    "layout_utilization_pct": 0.0,
    "layout_joint": False,
}
# Группа раскладки (шаг З-13) гаснет вместе со своими деталями. «Листов по
# факту» технического расчёта (pmk_tech) — число инженера из CypCut, его не
# трогаем: заявка его берёт, а плашка «Раскладка устарела» зовёт сверить.
# Режим («вместе» / «отдельно») не сбрасываем: погашенная совместная группа
# остаётся совместной — правка её соседа гасит и её соседей, а в колонке
# «Как» стоит «не считалась» (mode_label), а не неверное «отдельно».
GROUP_RESET = {
    "state": "none",
    "sheets": 0,
    "sheets_separate": 0,
    "scheme": False,
    "utilization_pct": 0.0,
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
# оставшихся верны (кроме совместной группы шага З-13: там доли соседей
# посчитаны вместе с удалённой — unlink гасит их, и сигнал горит по
# состоянию «Не считалась»). Цена листа в ключ не входит — числа раскладки от цены не
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

    # ─── Листы раскладки (шаг З-13) ──────────────────────────────────────
    # Группа на каждую пару «лист × габарит»: сколько листов купить, вместе
    # или отдельно. Не копируется — как результаты строк (R4): копию
    # раскладывают кнопкой заново. В технический расчёт группы переносит
    # pmk_tech (_pmk_copy_layout_groups).
    layout_group_ids = fields.One2many(
        "pmk.metal.spec.sheet.group", "spec_id", "Листы по раскладке", copy=False,
        help="Детали одного листа (толщина, вид) и габарита раскладываются "
             "вместе: сколько листов купить на каждый лист.")
    layout_legacy = fields.Boolean(
        "Разложено по деталям отдельно", compute="_compute_layout_legacy",
        help="Раскладка посчитана до шага З-13 — каждой деталью отдельно. "
             "«Разложить листы (черновик)» сложит детали одного листа вместе.")

    @api.depends("sheet_line_ids.layout_state", "sheet_line_ids.layout_group_id")
    def _compute_layout_legacy(self):
        """Старые расчёты сами не пересчитываются: строки разложены, а групп
        нет — на вкладке серая строка-подсказка."""
        for spec in self:
            spec.layout_legacy = any(
                line.layout_state != "none" and not line.layout_group_id
                for line in spec.sheet_line_ids)

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

        Шаг З-13: детали одного листа и габарита раскладываются ВМЕСТЕ
        (_pmk_layout_groups). Старые расчёты сами не пересчитываются — только
        этой кнопкой.
        """
        for spec in self:
            lines = spec.mapped("product_ids.line_sheet_ids")
            spec._pmk_layout_groups(lines)
            # Шаг 56: отпечаток — после раскладки строк, плашка «Раскладка
            # устарела» гаснет.
            spec._pmk_store_layout_fingerprint()
            spec._log_draft_layout(lines)
        return True

    def _pmk_layout_groups(self, lines):
        """Разложить листовые детали расчёта группами «лист × марка × габарит».

        Марка стали — в ключе (доработка З-13): Ст3 и 09Г2С одной толщины
        на общий лист не лягут. Детали без выбранного листа (толщина
        неизвестна) — одна группа «Лист не выбран», но раскладываются только
        раздельно (plan_group joint=False), как до З-13.

        Группа ключа, которая уже есть, используется заново (write), а не
        пересоздаётся: на ней может стоять «Листов по факту» инженера
        (pmk_tech). Группы исчезнувших ключей удаляются.
        """
        self.ensure_one()
        Group = self.env["pmk.metal.spec.sheet.group"]
        buckets = {}
        ordered = lines.sorted(lambda line: (
            line.product_id.sequence, line.product_id.id, line.sequence, line.id))
        for line in ordered:
            key = (line.sheet_id.id or False, line.grade_id.id or False,
                   line.layout_sheet_size or DEFAULT_SHEET_SIZE)
            buckets.setdefault(key, []).append(line)
        existing = {}
        for group in self.layout_group_ids:
            existing.setdefault(group._pmk_layout_key(), group)
        kept = Group
        for sequence, (key, group_lines) in enumerate(buckets.items(), 1):
            width, length = group_lines[0]._layout_sheet_dims()
            parts = [(line.id, line.a_mm or 0.0, line.b_mm or 0.0,
                      (line.qty or 0) * (line.product_id.qty or 0))
                     for line in group_lines]
            plan = plan_group(width, length, parts, kerf_mm=DEFAULT_KERF_MM,
                              joint=bool(key[0]))
            labels = {line.id: part_label(line.a_mm, line.b_mm) for line in group_lines}
            vals = {
                "sequence": sequence,
                "line_count": len(group_lines),
                "sheets": plan["sheets"],
                "sheets_separate": plan["sheets_separate"],
                "mode": plan["mode"],
                "state": "ok",
                "utilization_pct": plan["utilization_pct"],
                "scheme": group_scheme_text(plan["patterns"], labels) or False,
                "parts_label": ", ".join(
                    "%s ×%s" % (labels[key_], qty) for key_, _a, _b, qty in parts),
            }
            group = existing.get(key)
            if group:
                group.write(vals)
            else:
                group = Group.create(dict(vals, spec_id=self.id, sheet_id=key[0],
                                          grade_id=key[1], sheet_size=key[2]))
            kept |= group
            for line in group_lines:
                result = plan["lines"][line.id]
                # Результаты раскладки (LAYOUT_RESULTS) в записи — write
                # строки раскладку не гасит.
                line.write({
                    "layout_group_id": group.id,
                    "layout_per_sheet": result["per_sheet"],
                    "layout_sheets": result["sheets"],
                    "layout_scheme": result["scheme"],
                    "layout_state": result["state"],
                    "layout_utilization_pct": result["utilization_pct"],
                    "layout_joint": result["joint"],
                })
        (self.layout_group_ids - kept).unlink()
        return kept

    def _pmk_copy_layout_groups(self, source, line_pairs):
        """Группы раскладки source — в этот расчёт (технический, pmk_tech).

        line_pairs — [(деталь source, деталь здесь)], результаты строк
        переносит вызывающий. Здесь — группы и ссылки строк на них."""
        self.ensure_one()
        fields_to_copy = ("sequence", "sheet_id", "grade_id", "sheet_size", "line_count", "sheets",
                          "sheets_separate", "mode", "state", "utilization_pct",
                          "scheme", "parts_label")
        groups = {}
        paired = {}
        for old_line, _new_line in line_pairs:
            paired.setdefault(old_line.layout_group_id, set()).add(old_line.id)
        for old_line, new_line in line_pairs:
            old_group = old_line.layout_group_id
            if not old_group:
                continue
            if old_group.mode == "joint" and set(old_group.line_ids.ids) - paired[old_group]:
                # Не все детали совместной группы нашли пару — доли без
                # соседей неверны: такую деталь раскладывают заново.
                new_line.write(dict(LAYOUT_RESET))
                continue
            if old_group not in groups:
                vals = old_group._convert_to_write(
                    {name: old_group[name] for name in fields_to_copy})
                vals["spec_id"] = self.id
                groups[old_group] = self.env["pmk.metal.spec.sheet.group"].create(vals)
            # layout_group_id не вход раскладки — запись её не гасит.
            new_line.write({"layout_group_id": groups[old_group].id})
        return groups

    def _pmk_layout_log_tail(self):
        """Строки после записи о раскладке — для наследников (pmk_tech:
        «Листов по факту оставлено»). Список текстов."""
        return []

    def _log_draft_layout(self, lines):
        """Запись в историю: что насчитала кнопка.

        Результат раскладки живёт на вкладке и переписывается при следующем
        нажатии. В истории он остаётся: по ней видно, из какой цифры исходили,
        когда называли клиенту срок и цену.

        Шаг З-13: есть группы «вместе» — «купить 76 листов (раздельно было
        93)», пункт на группу; детали групп «отдельно» — пунктами, как раньше.
        Нет ни одной группы «вместе» — прежний текст.
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
        sizes = dict(SHEET_SIZES)
        joint = done.mapped("layout_group_id").filtered(lambda g: g.mode == "joint")
        # Использование — той же подписью, что в колонке вкладки: «4,7 % ·
        # очень мало». В истории должно стоять то же слово, что на экране.
        rows = []
        for group in joint:
            # «N детали вместе» — только легшие на общие листы (layout_joint):
            # деталь «в размер листа» или «больше листа» в группе есть, но
            # режется на своих листах или не режется вовсе.
            together = len(group.line_ids.filtered("layout_joint"))
            rows.append("<li>%s: %s %s — %s %s вместе (раздельно %s), использование %s</li>" % (
                escape(group.display_name), group.sheets,
                _plural(group.sheets, "лист", "листа", "листов"),
                together, _plural(together, "деталь", "детали", "деталей"),
                group.sheets_separate,
                sheet_use_label(group.utilization_pct, "ok")[0]))
        for line in done.filtered(lambda l: l.layout_group_id not in joint):
            rows.append("<li>%s: %s %s %s, по %s %s в листе, использование %s</li>" % (
                escape(line.display_name), line.layout_sheets,
                _plural(line.layout_sheets, "лист", "листа", "листов"),
                sizes.get(line.layout_sheet_size, line.layout_sheet_size),
                line.layout_per_sheet,
                _plural(line.layout_per_sheet, "заготовка", "заготовки", "заготовок"),
                sheet_use_label(line.layout_utilization_pct, line.layout_state)[0]))
        total = sum(done.mapped("layout_sheets"))
        head = "Раскладка листов (черновик): купить %s %s" % (
            total, _plural(total, "лист", "листа", "листов"))
        if joint:
            separate = total + sum(joint.mapped("sheets_separate")) - sum(joint.mapped("sheets"))
            head += " (раздельно было %s)" % separate
        tail = "".join("<p>%s</p>" % escape(text) for text in self._pmk_layout_log_tail())
        self.message_post(body=Markup(
            "<p>%s. Верхняя оценка, технолог уплотнит.</p><ul>%s</ul>%s" % (
                head, "".join(rows), tail)))


class MetalSpecLineLayout(models.Model):
    _inherit = "pmk.metal.spec.line"

    # Габарит листа у КАЖДОЙ строки свой: деталь 3 мм режут из одного листа,
    # деталь 10 мм — из другого, и размер проката может отличаться.
    layout_sheet_size = fields.Selection(
        SHEET_SIZES, "Габарит листа", default=DEFAULT_SHEET_SIZE,
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
             "изделии. Неполный лист считается целым: купить половину нельзя. "
             "Если деталь разложена вместе с другими деталями того же листа "
             "(колонка «Вместе с») — её доля листов группы по площади: "
             "«В листе» × «Листов» тогда меньше количества, доля может быть "
             "и нулём (деталь уже в листах соседей). Сумма долей = листы "
             "группы.")
    # Доработка З-13: деталь легла на общие листы с соседями (а не просто
    # состоит в группе «вместе»: деталь в размер листа или больше листа в
    # группе есть, но на общих листах её нет). От неё — «Вместе с» и «N
    # деталей вместе» в ленте.
    layout_joint = fields.Boolean(
        "Разложена вместе", readonly=True, copy=False,
        help="Деталь легла на общие листы с другими деталями того же листа: "
             "«Листов» у неё — доля общих листов.")
    # Шаг З-13: группа «лист × габарит», в которой деталь разложена. Не
    # копируется (как результаты строки, R4). Правка детали гасит и группу.
    layout_group_id = fields.Many2one(
        "pmk.metal.spec.sheet.group", "Лист раскладки", readonly=True, copy=False,
        index=True, ondelete="set null")
    layout_group_note = fields.Char(
        "Вместе с", compute="_compute_layout_group_note",
        help="С какими деталями того же листа эта деталь разложена вместе. "
             "Пусто — разложена отдельно.")
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

    @api.depends("layout_joint", "layout_group_id.line_ids.layout_joint",
                 "layout_group_id.line_ids.a_mm", "layout_group_id.line_ids.b_mm")
    def _compute_layout_group_note(self):
        """«560×3000», «560×3000, 90×460 и ещё 2» — размеры соседей по
        совместной раскладке (до двух, остальные числом). Только те, кто
        реально лёг на общие листы (layout_joint) — и сама деталь, и соседи:
        у детали «в размер листа» в группе «вместе» колонка пуста."""
        for line in self:
            group = line.layout_group_id
            if not group or not line.layout_joint:
                line.layout_group_note = False
                continue
            labels = []
            for other in group.line_ids:
                if other == line or other._origin == line._origin or not other.layout_joint:
                    continue
                label = part_label(other.a_mm, other.b_mm)
                if label not in labels:
                    labels.append(label)
            text = ", ".join(labels[:2])
            if len(labels) > 2:
                text += " и ещё %s" % (len(labels) - 2)
            line.layout_group_note = text or False

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

    @api.onchange("a_mm", "b_mm", "qty", "sheet_id", "grade_id", "layout_sheet_size")
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
            stale._pmk_reset_layout()
        return result

    def _pmk_reset_layout(self):
        """Погасить раскладку этих деталей — и их групп (шаг З-13).

        Совместная группа («вместе»): доли соседей посчитаны вместе с этой
        деталью и без неё неверны (Z одна потребует 67 листов, а её доля в
        группе — 51) — гасим всю группу. Группа «отдельно»: числа соседей
        свои и верны, гаснет только итог группы. Запись LAYOUT_RESET содержит
        результаты раскладки — write выше её не перехватывает."""
        groups = self.mapped("layout_group_id")
        lines = self | groups.filtered(lambda g: g.mode == "joint").mapped("line_ids")
        lines = lines.filtered(lambda l: l.layout_state != "none")
        if lines:
            lines.write(dict(LAYOUT_RESET))
        groups = groups.filtered(lambda g: g.state != "none")
        if groups:
            groups.write(dict(GROUP_RESET))

    def unlink(self):
        """Удалённая деталь совместной группы уносит часть листов группы —
        доли соседей больше не про заказ. Гасим соседей и группу: плашка
        «Раскладка устарела» загорится (шаг 56 удаление не ловил — тогда
        числа соседей от удалённой не зависели)."""
        groups = self.mapped("layout_group_id")
        neighbours = groups.filtered(lambda g: g.mode == "joint").mapped("line_ids") - self
        result = super().unlink()
        self.env["pmk.metal.spec.line"]._pmk_layout_after_unlink(groups, neighbours)
        return result

    @api.model
    def _pmk_layout_after_unlink(self, groups, neighbours):
        """После удаления деталей: опустевшая группа удаляется (её листа в
        расчёте больше нет); соседи по совместной группе гаснут (см. unlink);
        у группы «отдельно» итог пересчитывается по оставшимся деталям — их
        числа свои и верны, сигнала нет (как в шаге 56)."""
        groups = groups.exists()
        empty = groups.filtered(lambda g: not g.line_ids)
        if empty:
            empty.unlink()
        groups -= empty
        neighbours = neighbours.exists()
        if neighbours:
            neighbours._pmk_reset_layout()
        groups.filtered(lambda g: g.mode == "separate" and g.state == "ok")._pmk_refresh_separate()


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
            stale._pmk_reset_layout()
        return result

    def unlink(self):
        """Изделие удаляют вместе с деталями (каскад базы — unlink деталей не
        вызывается): соседей по совместной раскладке гасим здесь."""
        lines = self.mapped("line_sheet_ids")
        groups = lines.mapped("layout_group_id")
        neighbours = groups.filtered(lambda g: g.mode == "joint").mapped("line_ids") - lines
        result = super().unlink()
        self.env["pmk.metal.spec.line"]._pmk_layout_after_unlink(groups, neighbours)
        return result
