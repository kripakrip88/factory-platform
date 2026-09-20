# -*- coding: utf-8 -*-
"""Задание на лазерную резку: файл раскроя, листы, детали, деньги.

Задание — главный документ участка. Из него берут знаменатель замеры, из него
же считается премия и баланс металла.

ЧТО БЕРЁТСЯ ИЗ ФАЙЛА И ЧЕМУ В НЁМ МОЖНО ВЕРИТЬ. Управляющий файл CypCut
(.lxds) разбирает tools/lxds.py; ему можно верить в составе заказа, числе
листов, габарите и использовании — это считает сама программа раскроя. Верить
НЕЛЬЗЯ разделу Technical: у технолога только демонстрационные режимы, и во всех
трёх присланных файлах (2, 3 и 10 мм) он побайтово одинаков, с Thickness="1.5"
и «чёрной сталью». Поэтому толщина берётся из ИМЕНИ файла — туда её пишут для
оператора станка, — а вид листа файл не знает вовсе: «3мм» не говорит, гладкий
он или рифлёный. По умолчанию гладкий, в задании — выбор.

ПОЧЕМУ ДЕТАЛИ И ЛИСТЫ — РАЗНЫЕ ТАБЛИЦЫ. Лист физически кладут на стол и
физически снимают, поэтому замер живёт на листе. Деталь физически режут, и
только у неё есть чертёж, из которого берётся длина реза и число проколов —
знаменатель, без которого замер непереносим на другой заказ. Какая деталь на
каком листе, файл открытым текстом не говорит (раскладка лежит в двоичном
Shapes2D/data.bin), поэтому знаменатель мы честно знаем по ЗАДАНИЮ целиком, а
не по отдельному листу. Отсюда правило норматива: в статистику идут только
задания, у которых замерены ВСЕ листы (см. norm.py).

ЧЕГО ЗДЕСЬ НЕТ. Складских движений. Баланс металла считается и показывается,
но списание листов и оприходование обрезков станет проводками тогда, когда
сортамент доедет до номенклатуры Odoo (этим занят pmk_bridge). Считать баланс
уже сейчас — не забегание вперёд: именно он показывает, что обрезки не
оприходуют, а этого сегодня не видит никто.
"""

import base64
import os
import tempfile

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import money, timing

# Вид листа по умолчанию. Из имени файла вид не виден, а режут обычно чёрную
# сталь гладким листом — решение владельца.
DEFAULT_SHEET_TYPE = "Гладкий"

# Допуск при поиске толщины в справочнике. Толщина приходит из имени файла
# строкой («3мм»), в справочнике лежит числом с плавающей точкой — сравнивать
# их на точное равенство нельзя.
THICKNESS_TOLERANCE_MM = 0.001


class LaserJob(models.Model):
    _name = "pmk.laser.job"
    _description = "Задание на лазерную резку"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    machine_id = fields.Many2one(
        "pmk.laser.machine", "Станок", required=True, tracking=True,
        help="На каком из двух станков режем. От него берутся минуты на "
             "загрузку и разгрузку стола и по нему же ищется норматив.")
    partner_id = fields.Many2one("res.partner", "Заказчик", tracking=True)
    sale_order_id = fields.Many2one(
        "sale.order", "Заказ", tracking=True,
        help="Необязательно. Нужен, чтобы полезный вес и время резки можно "
             "было отнести на конкретный заказ, а не на участок вообще.")
    note = fields.Char("Примечание")

    # ------------------------------------------------------------------
    # Файл раскроя
    # ------------------------------------------------------------------
    file = fields.Binary("Файл раскроя (.lxds)", attachment=True, copy=False)
    file_name = fields.Char(
        "Имя файла", copy=False,
        help="Имя важно: толщина листа берётся именно из него. Переименованный "
             "файл разобрать не получится, и это правильно — гадать нельзя.")

    file_app = fields.Char("Программа раскроя", readonly=True, copy=False)
    file_operator = fields.Char("Сохранил", readonly=True, copy=False)
    file_saved_text = fields.Char(
        "Сохранён", readonly=True, copy=False,
        help="Время, как его записал CypCut. Это местное время станка, "
             "поэтому оно показано текстом и никуда не пересчитывается: "
             "перевод «из UTC» увёл бы вечерние раскрои на следующие сутки.")
    contour_count = fields.Integer(
        "Контуров в файле", readonly=True, copy=False,
        help="Число замкнутых контуров в раскладке. Почти равно числу проколов "
             "и служит перекрёстной проверкой того, что дали чертежи.")
    technical_is_demo = fields.Boolean("Режимы демонстрационные", readonly=True, copy=False)
    technical_note = fields.Char("Что объявлено в файле", readonly=True, copy=False)
    parse_warning = fields.Text("Замечания разбора", readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Материал
    # ------------------------------------------------------------------
    sheet_id = fields.Many2one(
        "pmk.metal.sheet", "Лист по справочнику", tracking=True,
        help="Отсюда берётся масса квадратного метра — и только отсюда. "
             "Плотность не используется: у рифлёного листа квадрат на 5–7% "
             "тяжелее гладкого, у просечно-вытяжного металла 37–63% габарита, "
             "и справочник это уже знает, а формула по плотности — нет.")
    sheet_type = fields.Char(related="sheet_id.sheet_type", string="Вид листа", store=True, readonly=True)
    thickness_mm = fields.Float(related="sheet_id.thickness_mm", string="Толщина, мм", store=True, readonly=True)
    mass_per_sqm = fields.Float(related="sheet_id.mass_per_sqm", string="Масса, кг/м²", readonly=True)
    grade_id = fields.Many2one("pmk.metal.grade", "Марка стали")

    kerf_mm = fields.Float(
        "Ширина реза, мм", digits=(4, 2), default=money.DEFAULT_KERF_MM, required=True,
        help="Полоска металла, которую рез уносит в пыль на всю толщину. "
             "Значение своё, а не из файла: раздел с режимами у технолога "
             "демонстрационный. Без этой строки лом в балансе всегда "
             "«больше расчётного», и непонятно почему.")
    min_offcut_mm = fields.Float(
        "Обрезок от, мм", digits=(8, 0), default=money.DEFAULT_MIN_OFFCUT_MM, required=True,
        help="Короче этого остаток в реестр не заводится — место на стеллаже "
             "дороже металла.")

    part_ids = fields.One2many("pmk.laser.job.part", "job_id", "Детали", copy=True)
    sheet_ids = fields.One2many("pmk.laser.job.sheet", "job_id", "Листы", copy=False)
    operator_ids = fields.One2many("pmk.laser.job.operator", "job_id", "Операторы", copy=True)
    offcut_ids = fields.One2many("pmk.laser.offcut", "job_id", "Обрезки", copy=False)
    measure_ids = fields.One2many("pmk.laser.measure", "job_id", "Замеры", copy=False)

    # ------------------------------------------------------------------
    # Металл и деньги
    # ------------------------------------------------------------------
    sheet_count = fields.Integer("Листов", compute="_compute_metal", store=True)
    gross_area_m2 = fields.Float("Куплено, м²", compute="_compute_metal", store=True, digits=(12, 2))
    useful_area_m2 = fields.Float("Полезно, м²", compute="_compute_metal", store=True, digits=(12, 2))
    mass_kg = fields.Float("Списано металла, кг", compute="_compute_metal", store=True, digits=(12, 1))
    useful_mass_kg = fields.Float(
        "Полезный вес, кг", compute="_compute_metal", store=True, digits=(12, 1),
        help="Вес разложенных деталей. За него платит заказчик и от него "
             "считается премия — не от веса купленного листа.")
    utilization_pct = fields.Float("Использование, %", compute="_compute_metal", store=True, digits=(5, 1))

    premium_rate_rub = fields.Float(
        "Ставка премии, ₽/т", compute="_compute_premium", store=True, digits=(8, 0))
    premium_rub = fields.Float(
        "Премия, ₽", compute="_compute_premium", store=True, digits=(10, 2), tracking=True)

    cut_length_m = fields.Float("Длина реза, м", compute="_compute_denominator", store=True, digits=(12, 2))
    pierce_count = fields.Integer("Проколов", compute="_compute_denominator", store=True)
    parts_without_drawing = fields.Integer("Деталей без чертежа", compute="_compute_denominator", store=True)
    contour_gap_pct = fields.Float(
        "Расхождение с контурами, %", compute="_compute_denominator", store=True, digits=(6, 1),
        help="Насколько число проколов по чертежам расходится с числом "
             "контуров в файле раскроя. Большое расхождение значит, что "
             "к деталям приложены не те чертежи.")

    kerf_mass_kg = fields.Float("Пропил, кг", compute="_compute_balance", store=True, digits=(12, 2))
    offcut_mass_kg = fields.Float("Обрезки, кг", compute="_compute_balance", store=True, digits=(12, 1))
    scrap_mass_kg = fields.Float(
        "Лом, кг", compute="_compute_balance", store=True, digits=(12, 1),
        help="Не вводится, а получается вычитанием: списано минус детали, "
             "обрезки и пропил. Систематический перекос в лом означает либо "
             "что обрезки не оприходуют, либо что раскладка плохая.")
    balance_broken = fields.Boolean("Баланс не сходится", compute="_compute_balance", store=True)

    # ------------------------------------------------------------------
    # План и факт
    # ------------------------------------------------------------------
    plan_state = fields.Selection(
        [("ok", "Норматив выведен"),
         ("rough", "Грубо: рез и проколы не разделены"),
         ("no_norm", "Норматива нет"),
         ("no_drawing", "Длина реза не разобрана")],
        "Состояние плана", compute="_compute_plan", store=True, default="no_drawing")
    planned_minutes = fields.Float(
        "План, мин", compute="_compute_plan", store=True, digits=(10, 1),
        help="Загрузка и разгрузка стола на каждый лист плюс резка по "
             "нормативу. Пока по толщине нет ни одного замера, план остаётся "
             "пустым — среднее по соседним толщинам не подставляется.")
    actual_minutes = fields.Float("Факт, мин", compute="_compute_fact", store=True, digits=(10, 1))
    measure_state = fields.Selection(
        [("none", "Замеров нет"), ("partial", "Замерена часть листов"), ("done", "Все листы замерены")],
        "Замеры", compute="_compute_fact", store=True, default="none")

    # ==================================================================
    # Вычисления
    # ==================================================================

    @api.depends("sheet_ids.area_m2", "sheet_ids.useful_area_m2",
                 "sheet_ids.mass_kg", "sheet_ids.useful_mass_kg")
    def _compute_metal(self):
        for job in self:
            sheets = job.sheet_ids
            job.sheet_count = len(sheets)
            job.gross_area_m2 = sum(sheets.mapped("area_m2"))
            job.useful_area_m2 = sum(sheets.mapped("useful_area_m2"))
            job.mass_kg = sum(sheets.mapped("mass_kg"))
            job.useful_mass_kg = sum(sheets.mapped("useful_mass_kg"))
            job.utilization_pct = (
                100.0 * job.useful_area_m2 / job.gross_area_m2 if job.gross_area_m2 else 0.0)

    @api.depends("useful_mass_kg", "thickness_mm")
    def _compute_premium(self):
        for job in self:
            job.premium_rate_rub = money.premium_rate(job.thickness_mm) if job.thickness_mm else 0.0
            job.premium_rub = money.premium_rub(job.useful_mass_kg, job.thickness_mm)

    @api.depends("part_ids.cut_length_total_m", "part_ids.pierces_total",
                 "part_ids.cut_length_mm", "contour_count")
    def _compute_denominator(self):
        for job in self:
            parts = job.part_ids
            job.parts_without_drawing = len(parts.filtered(lambda p: p.cut_length_mm <= 0.0))
            # Знаменатель считаем ТОЛЬКО когда разобраны все детали. Половина
            # деталей дала бы половину метров — и норматив, посчитанный по
            # такому знаменателю, был бы вдвое быстрее настоящего.
            if parts and not job.parts_without_drawing:
                job.cut_length_m = sum(parts.mapped("cut_length_total_m"))
                job.pierce_count = sum(parts.mapped("pierces_total"))
            else:
                job.cut_length_m = 0.0
                job.pierce_count = 0
            job.contour_gap_pct = (
                100.0 * abs(job.pierce_count - job.contour_count) / job.contour_count
                if job.contour_count and job.pierce_count else 0.0)

    @api.depends("mass_kg", "useful_mass_kg", "cut_length_m", "kerf_mm", "mass_per_sqm",
                 "offcut_ids.mass_kg", "offcut_ids.state")
    def _compute_balance(self):
        for job in self:
            job.kerf_mass_kg = money.mass_kg(
                money.kerf_area_m2(job.cut_length_m, job.kerf_mm), job.mass_per_sqm)
            # В баланс идут только подтверждённые обрезки: предложение системы —
            # ещё не металл на стеллаже.
            confirmed = job.offcut_ids.filtered(lambda o: o.state == "confirmed")
            job.offcut_mass_kg = sum(confirmed.mapped("mass_kg"))
            job.scrap_mass_kg = money.scrap_mass_kg(
                job.mass_kg, job.useful_mass_kg, job.offcut_mass_kg, job.kerf_mass_kg)
            job.balance_broken = job.mass_kg > 0.0 and job.scrap_mass_kg < 0.0

    @api.depends("cut_length_m", "pierce_count", "sheet_count", "machine_id",
                 "machine_id.load_min", "machine_id.unload_min",
                 "sheet_type", "thickness_mm")
    def _compute_plan(self):
        norms = self.env["pmk.laser.norm"]
        for job in self:
            handling = job.sheet_count * (job.machine_id.load_min + job.machine_id.unload_min)
            if job.cut_length_m <= 0.0:
                job.plan_state = "no_drawing"
                job.planned_minutes = 0.0
                continue
            norm = norms._lookup(job.machine_id, job.sheet_type, job.thickness_mm)
            cutting = timing.estimate_minutes(
                norm.mode, norm.min_per_m, norm.speed_mm_min, norm.pierce_time_s,
                job.cut_length_m, job.pierce_count) if norm else None
            if cutting is None:
                # Ни одного замера на этой толщине. Показываем пусто, а не
                # среднее по соседним толщинам: выдуманный план хуже
                # отсутствующего — по нему поставят срок заказчику.
                job.plan_state = "no_norm"
                job.planned_minutes = 0.0
                continue
            job.plan_state = "ok" if norm.mode == timing.MODE_FULL else "rough"
            job.planned_minutes = handling + cutting

    @api.depends("sheet_ids.actual_minutes", "sheet_ids.measure_ids.state",
                 "sheet_ids.measure_ids.excluded")
    def _compute_fact(self):
        for job in self:
            sheets = job.sheet_ids
            job.actual_minutes = sum(sheets.mapped("actual_minutes"))
            measured = len(sheets.filtered(lambda s: s.actual_minutes > 0.0))
            if not sheets or not measured:
                job.measure_state = "none"
            elif measured < len(sheets):
                job.measure_state = "partial"
            else:
                job.measure_state = "done"

    # ==================================================================
    # Создание
    # ==================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.laser.job") or "Черновик"
        return super().create(vals_list)

    # ==================================================================
    # Разбор файла раскроя
    # ==================================================================

    def _read_layout(self):
        """Отдать разобранный .lxds.

        Файл кладём во временную папку ПОД ЕГО СОБСТВЕННЫМ ИМЕНЕМ: толщина
        берётся из имени, и под случайным именем tmp7xk разбор честно вернёт
        «толщины в имени нет».
        """
        self.ensure_one()
        from ..tools import lxds  # разбор живёт в tools/, Odoo ему не нужен

        if not self.file:
            raise UserError(_("Сначала приложите файл раскроя .lxds"))
        file_name = self.file_name or "raskroy.lxds"
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, file_name)
            with open(path, "wb") as handle:
                handle.write(base64.b64decode(self.file))
            return lxds.read_layout(path)

    def _sheet_from_reference(self, thickness_mm, sheet_type):
        """Найти лист в справочнике pmk_calc по толщине и виду."""
        self.ensure_one()
        if not thickness_mm:
            raise UserError(_(
                "В имени файла «%s» нет толщины листа. Толщину пишут в имя для "
                "оператора станка — верить разделу с режимами нельзя, он у "
                "технолога демонстрационный.") % (self.file_name or ""))
        domain = [
            ("sheet_type", "=", sheet_type),
            ("thickness_mm", ">=", thickness_mm - THICKNESS_TOLERANCE_MM),
            ("thickness_mm", "<=", thickness_mm + THICKNESS_TOLERANCE_MM),
        ]
        sheets = self.env["pmk.metal.sheet"].search(domain)
        if not sheets:
            raise UserError(_(
                "Листа «%(type)s» %(thick)g мм нет в справочнике. Без массы "
                "квадратного метра полезный вес не посчитать, а брать её через "
                "плотность нельзя: у рифлёного и просечно-вытяжного листа она "
                "другая.") % {"type": sheet_type, "thick": thickness_mm})
        if len(sheets) > 1:
            labels = ", ".join(sheets.mapped(lambda s: s.size_label or "без типоразмера"))
            raise UserError(_(
                "Лист «%(type)s» %(thick)g мм есть в нескольких исполнениях "
                "(%(labels)s) — выберите нужный вручную, масса квадрата у них "
                "разная.") % {"type": sheet_type, "thick": thickness_mm, "labels": labels})
        return sheets

    def action_parse_file(self):
        """Разобрать приложенный .lxds и разложить его по документу."""
        for job in self:
            if job.measure_ids:
                raise UserError(_(
                    "По заданию уже есть замеры — перечитывать файл нельзя: "
                    "листы пересоздадутся, и замеры операторов пропадут. "
                    "Если раскрой переделали, заведите новое задание."))
            layout = job._read_layout()
            if job.sheet_id:
                # Лист выбрали руками (например, рифлёный — из имени файла вид
                # не виден). Толщину всё равно сверяем: имя файла — пометка для
                # оператора станка, и расхождение с ней означает, что к заданию
                # приложили чужой раскрой.
                if layout.thickness_mm and abs(
                        job.thickness_mm - layout.thickness_mm) > THICKNESS_TOLERANCE_MM:
                    raise UserError(_(
                        "В задании выбран лист %(chosen)g мм, а в имени файла "
                        "«%(file)s» стоит %(file_thick)g мм. Толщину в имя пишут "
                        "для оператора станка — либо файл не тот, либо лист."
                    ) % {"chosen": job.thickness_mm, "file": job.file_name or "",
                         "file_thick": layout.thickness_mm})
                sheet = job.sheet_id
            else:
                sheet = job._sheet_from_reference(layout.thickness_mm, DEFAULT_SHEET_TYPE)

            declared = layout.technical_declared or {}
            values = {
                "sheet_id": sheet.id,
                "file_app": ("%s %s" % (layout.app_name, layout.app_version)).strip(),
                "file_operator": layout.operator,
                "file_saved_text": layout.saved_at_raw,
                "contour_count": layout.contours,
                "technical_is_demo": layout.demo_modes,
                "technical_note": _("в файле объявлено: толщина %(thick)s, материал %(mat)s") % {
                    "thick": declared.get("thickness") or "—",
                    "mat": declared.get("material") or "—",
                },
                "parse_warning": "\n".join(layout.warnings),
                "part_ids": job._part_commands(layout),
                "sheet_ids": job._sheet_commands(layout),
            }
            if layout.saved_at:
                # Берём только ДАТУ: время в файле местное, и переводить его в
                # UTC значит сдвинуть вечерние раскрои на сутки вперёд.
                values["date"] = layout.saved_at.date()
            job.write(values)

            message = _(
                "Файл разобран: %(sheets)s листов, %(parts)s деталей, "
                "%(contours)s контуров.") % {
                    "sheets": layout.sheet_count,
                    "parts": layout.parts_declared,
                    "contours": layout.contours,
            }
            if layout.demo_modes:
                message += _(
                    "<br/>Параметры резки в файле демонстрационные — толщина взята "
                    "из имени файла (%s).") % layout.thickness_source
            if layout.warnings:
                message += "<br/>" + "<br/>".join(layout.warnings)
            job.message_post(body=message)
        return True

    def _part_commands(self, layout):
        """Команды на пересоздание деталей с сохранением уже разобранных чертежей.

        Чертёж прикладывает технолог руками, и терять его при повторном разборе
        файла нельзя. Сопоставляем по имени детали — это то же имя, которым она
        названа в раскрое («Крайняя часть отвода - 12шт»).
        """
        self.ensure_one()
        kept = {
            part.name: {
                "drawing": part.drawing,
                "drawing_name": part.drawing_name,
                "cut_length_mm": part.cut_length_mm,
                "pierce_count": part.pierce_count,
                "preview_svg": part.preview_svg,
            }
            for part in self.part_ids
        }
        commands = [fields.Command.clear()]
        for part in layout.parts:
            values = {"name": part.name, "qty": part.amount, "qty_used": part.amount_used}
            values.update(kept.get(part.name, {}))
            commands.append(fields.Command.create(values))
        return commands

    def _sheet_commands(self, layout):
        """Развернуть раскладки в физические листы.

        В файле кронштейнов одна раскладка на 89,2% повторена семь раз — это
        семь листов, а не один. Считать раскладки вместо листов значит занизить
        полезный вес в семь раз, а вместе с ним и премию.
        """
        self.ensure_one()
        commands = [fields.Command.clear()]
        number = 0
        for nest in layout.nests:
            for _copy in range(nest.plate_amount):
                number += 1
                commands.append(fields.Command.create({
                    "number": number,
                    "nest_index": nest.index,
                    "width_mm": nest.width_mm,
                    "length_mm": nest.height_mm,
                    "utilization_pct": nest.utilization_pct,
                }))
        return commands

    def action_parse_drawings(self):
        """Разобрать чертежи деталей: длина реза, проколы, эскиз."""
        for job in self:
            without = job.part_ids.filtered(lambda p: not p.drawing)
            if without:
                raise UserError(_(
                    "Нет чертежей у деталей: %s. Без них у замера не будет "
                    "знаменателя — «лист резался 47 минут» не переносится на "
                    "другой заказ.") % ", ".join(without.mapped("name")))
            job.part_ids.action_parse_drawing()
        return True

    # ==================================================================
    # Обрезки
    # ==================================================================

    def action_propose_offcuts(self):
        """Предложить обрезки по листам, где остался цельный кусок.

        Кнопка обязана всегда делать что-то осмысленное. Раньше повторное
        нажатие выдавало «всё в лом», хотя обрезок уже был предложен первым
        нажатием: лист с готовым обрезком пропускался, счётчик оставался
        нулём, и человек видел отказ вместо своего же результата. Теперь
        «уже предложено» и «нечего предлагать» — разные исходы, и в обоих
        случаях открывается список: в первом с тем, что есть, во втором
        пустой, чтобы завести обрезок руками.
        """
        offcuts = self.env["pmk.laser.offcut"]
        created = 0
        already = 0
        small_sheets = []
        smallest = min(self.mapped("min_offcut_mm") or [money.DEFAULT_MIN_OFFCUT_MM])
        for job in self:
            for sheet in job.sheet_ids:
                if sheet.offcut_ids:
                    already += len(sheet.offcut_ids)
                    continue
                proposal = money.propose_offcut(
                    sheet.width_mm, sheet.length_mm, sheet.utilization_pct,
                    min_length_mm=job.min_offcut_mm)
                if not proposal:
                    small_sheets.append(sheet.number)
                    continue
                width, length = proposal
                offcuts.create({
                    "job_id": job.id,
                    "sheet_line_id": sheet.id,
                    "width_mm": width,
                    "length_mm": length,
                })
                created += 1

        # Что сказать человеку. Предложение ГРУБОЕ — точный свободный
        # прямоугольник считается по геометрии раскладки, а она в двоичной
        # части файла. Поэтому про правку размера говорим всегда, а не только
        # когда предложить не вышло.
        if created:
            msg = _("Предложено обрезков: %(n)s. Размер прикидочный — "
                    "посмотрите на лист и поправьте.") % {"n": created}
        elif already:
            msg = _("Обрезки по этому заданию уже предложены (%(n)s). "
                    "Ниже — то, что есть; размер можно поправить.") % {"n": already}
        else:
            msg = _("Свободного куска длиннее %(mm)g мм не нашлось — по расчёту "
                    "всё уходит в лом. Если на листе цельный остаток есть, "
                    "заведите обрезок кнопкой «Новое»: точный прямоугольник "
                    "по файлу пока не считается.") % {"mm": smallest}

        action = self.env["ir.actions.actions"]._for_xml_id("pmk_laser.action_laser_offcut")
        action["domain"] = [("job_id", "in", self.ids)]
        action["context"] = dict(self.env.context, default_job_id=self[:1].id)
        action["help"] = "<p class='o_view_nocontent_smiling_face'>%s</p>" % msg
        return action

    # ==================================================================
    # Нормативы
    # ==================================================================

    def action_update_norms(self):
        """Пересчитать нормативы по замерам — после того, как задание закрыто."""
        self.env["pmk.laser.norm"]._sync_from_measures()
        return True


class LaserJobPart(models.Model):
    """Деталь задания: сколько штук и что говорит её чертёж.

    Чертёж нужен не для красоты. Он даёт знаменатель: метры реза и проколы.
    Без него замер оператора остаётся числом «47 минут», которое нельзя
    перенести ни на один другой заказ.
    """

    _name = "pmk.laser.job.part"
    _description = "Деталь задания на резку"
    _order = "job_id, id"

    job_id = fields.Many2one("pmk.laser.job", "Задание", required=True, ondelete="cascade", index=True)
    name = fields.Char("Деталь", required=True)
    qty = fields.Integer("Заявлено", required=True, default=1)
    qty_used = fields.Integer(
        "Разложено", help="Отличается от заявленного, когда в раскладку влезли "
                          "не все детали — часть заказа уедет на следующий лист.")

    drawing = fields.Binary("Чертёж (.dxf)", attachment=True)
    drawing_name = fields.Char("Имя чертежа")

    cut_length_mm = fields.Float("Рез на деталь, мм", digits=(12, 1), readonly=True)
    pierce_count = fields.Integer("Проколов на деталь", readonly=True)
    preview_svg = fields.Text("Эскиз", readonly=True)

    cut_length_total_m = fields.Float("Рез всего, м", compute="_compute_totals", store=True, digits=(12, 2))
    pierces_total = fields.Integer("Проколов всего", compute="_compute_totals", store=True)

    @api.depends("qty", "cut_length_mm", "pierce_count")
    def _compute_totals(self):
        for part in self:
            part.cut_length_total_m = part.qty * part.cut_length_mm / 1000.0
            part.pierces_total = part.qty * part.pierce_count

    def action_parse_drawing(self):
        """Прочитать чертёж: длина реза, число замкнутых контуров, эскиз.

        Разбор живёт в tools/drawing.py и Odoo не требует — здесь только
        единственная точка вызова. Ожидаемый ответ: объект с полями
        cut_length_mm, pierces, preview_svg.
        """
        from ..tools import drawing  # разбор DXF, Odoo ему не нужен

        for part in self:
            if not part.drawing:
                raise UserError(_("У детали «%s» не приложен чертёж") % part.name)
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, part.drawing_name or "part.dxf")
                with open(path, "wb") as handle:
                    handle.write(base64.b64decode(part.drawing))
                parsed = drawing.read_drawing(path)
            part.write({
                "cut_length_mm": parsed.cut_length_mm,
                "pierce_count": parsed.pierces,
                "preview_svg": parsed.preview_svg,
            })
        return True


class LaserJobSheet(models.Model):
    """Физический лист на столе станка.

    Отдельная строка на каждый лист, даже когда раскладка одна и та же: лист
    кладут, режут и снимают поштучно, и замер оператора привязан именно к
    листу. Семь одинаковых листов — семь строк и семь замеров.
    """

    _name = "pmk.laser.job.sheet"
    _description = "Лист задания на резку"
    _order = "job_id, number"
    _rec_name = "number"

    job_id = fields.Many2one("pmk.laser.job", "Задание", required=True, ondelete="cascade", index=True)
    number = fields.Integer("Лист №", required=True)
    nest_index = fields.Integer(
        "Раскладка", help="Номер раскладки в файле. У листов одной раскладки "
                          "картинка одна и та же — их время должно совпадать, "
                          "и расхождение сразу видно в замерах.")
    width_mm = fields.Float("Ширина, мм", digits=(8, 0), required=True)
    length_mm = fields.Float("Длина, мм", digits=(8, 0), required=True)
    utilization_pct = fields.Float("Использование, %", digits=(5, 1), required=True)

    area_m2 = fields.Float("Габарит, м²", compute="_compute_metal", store=True, digits=(10, 3))
    useful_area_m2 = fields.Float("Полезно, м²", compute="_compute_metal", store=True, digits=(10, 3))
    mass_kg = fields.Float("Масса листа, кг", compute="_compute_metal", store=True, digits=(12, 1))
    useful_mass_kg = fields.Float("Полезный вес, кг", compute="_compute_metal", store=True, digits=(12, 1))

    measure_ids = fields.One2many("pmk.laser.measure", "sheet_line_id", "Замеры")
    offcut_ids = fields.One2many("pmk.laser.offcut", "sheet_line_id", "Обрезки")
    actual_minutes = fields.Float("Факт, мин", compute="_compute_actual", store=True, digits=(8, 1))

    @api.depends("width_mm", "length_mm", "utilization_pct", "job_id.mass_per_sqm")
    def _compute_metal(self):
        for sheet in self:
            mass_per_sqm = sheet.job_id.mass_per_sqm
            sheet.area_m2 = money.sheet_area_m2(sheet.width_mm, sheet.length_mm)
            sheet.useful_area_m2 = money.useful_area_m2(sheet.area_m2, sheet.utilization_pct)
            sheet.mass_kg = money.mass_kg(sheet.area_m2, mass_per_sqm)
            sheet.useful_mass_kg = money.mass_kg(sheet.useful_area_m2, mass_per_sqm)

    @api.depends("measure_ids.duration_minutes", "measure_ids.state", "measure_ids.excluded")
    def _compute_actual(self):
        for sheet in self:
            # По листу считаем ПОЛНОЕ время: оператор нажал «начал», когда взялся
            # за лист, и «закончил», когда снял детали. Чистую резку из этого
            # вычитает сам замер — она нужна нормативу, а не сменному заданию.
            usable = sheet.measure_ids.filtered(lambda m: m.state == "done" and not m.excluded)
            sheet.actual_minutes = sum(usable.mapped("duration_minutes"))

    def action_start_cut(self):
        """Первое касание оператора: «начал». Всё остальное берётся из задания."""
        measures = self.env["pmk.laser.measure"]
        for sheet in self:
            running = sheet.measure_ids.filtered(lambda m: m.state == "running")
            if running:
                raise UserError(_("По листу %s замер уже идёт") % sheet.number)
            measures |= measures.create({
                "job_id": sheet.job_id.id,
                "sheet_line_id": sheet.id,
                "operator_id": self.env.user.employee_id.id,
                "started_at": fields.Datetime.now(),
            })
        return True

    def action_finish_cut(self):
        """Второе касание оператора: «закончил»."""
        for sheet in self:
            running = sheet.measure_ids.filtered(lambda m: m.state == "running")
            if not running:
                raise UserError(_("По листу %s никто не начинал резку") % sheet.number)
            running.action_finish()
        return True


class LaserJobOperator(models.Model):
    """Оператор смены и его доля премии.

    Список, а не одно поле: операторы делят премию пополам, но смена бывает и
    из одного, и из троих. Списком состав меняется в задании, а не в коде —
    это требование владельца.
    """

    _name = "pmk.laser.job.operator"
    _description = "Оператор в задании на резку"
    _order = "job_id, sequence, id"
    _rec_name = "employee_id"

    job_id = fields.Many2one("pmk.laser.job", "Задание", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer("Порядок", default=10)
    employee_id = fields.Many2one("hr.employee", "Оператор", required=True)
    amount_rub = fields.Float("Премия, ₽", compute="_compute_amount", store=True, digits=(10, 2))

    _employee_once = models.UniqueIndex(
        "(job_id, employee_id)",
        "Оператор уже есть в этом задании — вторая строка удвоила бы его долю.",
    )

    @api.depends("job_id.premium_rub", "job_id.operator_ids", "sequence")
    def _compute_amount(self):
        self.amount_rub = 0.0
        for job in self.mapped("job_id"):
            lines = job.operator_ids
            shares = money.split_rub(job.premium_rub, len(lines))
            for line, share in zip(lines, shares):
                if line in self:
                    line.amount_rub = share
