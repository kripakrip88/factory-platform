# -*- coding: utf-8 -*-
"""Задание на резку по заказу (ЗР) и его детали (переделка лазера, 15.10.2026).

ЗАЧЕМ ДВА ДОКУМЕНТА. Антон: «задание на резку — это фактически задание с заказа, в
заказе может быть несколько листов разной толщины» и «объединять резку деталей с
нескольких заказов в один раскрой — мы часто это делаем, это важно». Поэтому:

- ЗАДАНИЕ НА РЕЗКУ (pmk.laser.task, ЗР) — что заказ просит порезать: детали любой
  толщины, чертёж, количество. Отсюда прогресс заказа: штуки, килограммы, листы.
- РАСКРОЙ (pmk.laser.job, РС) — одна толщина, один вид листа, один станок, одна
  программа CypCut. Строки раскроя ссылаются на детали заданий — в одном раскрое
  детали нескольких заказов, деталь может уйти в два раскроя частями. Вся прежняя
  математика участка (листы, замеры, норматив, премия, баланс, деньги) — у раскроя.
- «ДЕТАЛИ К РАСКРОЮ» — список неразложенных деталей всех заданий по толщинам:
  отметить → «Создать раскрой» / «Добавить в раскрой».

ВЕС ДЕТАЛИ. Площади детали разбор чертежа пока не даёт (контуры без многоугольников),
поэтому килограммы прогресса — доля полезного веса раскроя, поделённого между его
строками по штукам × габарит детали. Это прикидка, а не взвешивание; станет точной,
когда движок раскроя отдаст площадь детали.
"""
import base64
import hashlib
import os
import re
import tempfile

from odoo import _, api, fields, models
from odoo.exceptions import UserError

THICKNESS_TOLERANCE_MM = 0.001
DEFAULT_SHEET_TYPE = "Гладкий"

# «пл1 10мм 20шт», «0,45мм шаблон 6шт», «2мм Лоток 284х260х2 L=1250мм - 269шт».
# Толщина — отдельное слово «Nмм» (не «L=1250мм», не «284х260х2»), количество —
# «Nшт» в любом месте. Остаток — имя детали.
_THICK = re.compile(r"(?<![\w=,.])(\d+(?:[.,]\d+)?)\s*мм(?![\w])", re.I)
_QTY = re.compile(r"(?<![\w])(\d+)\s*шт\.?(?![\w])", re.I)
_QTY_PAREN = re.compile(r"\((\d+)\)\s*$")


def parse_file_name(file_name):
    """Имя файла чертежа → (имя детали, толщина мм | None, штук | None).

    Толщина — первое отдельное «Nмм»; «L=1250мм» и размеры «284х260х2» не трогаем.
    Количество — «Nшт» где угодно или «(N)» в конце. Дефисы и подчёркивания по краям
    остатка срезаются: «2мм Лоток - 269шт» → «Лоток».
    """
    stem = os.path.splitext(os.path.basename(file_name or ""))[0]
    text = stem.replace("_", " ")
    thickness = qty = None
    m = _THICK.search(text)
    if m:
        thickness = float(m.group(1).replace(",", "."))
        text = text[:m.start()] + " \x00 " + text[m.end():]
    m = _QTY.search(text)
    if m:
        qty = int(m.group(1))
        text = text[:m.start()] + " \x00 " + text[m.end():]
    else:
        m = _QTY_PAREN.search(text)
        if m:
            qty = int(m.group(1))
            text = text[:m.start()]
    # Дефис, стоявший у вырезанного «269шт»/«2мм» («Лоток - 269шт Раскрой»), уходит вместе
    # с ним; дефис внутри имени («Полка - левая») остаётся.
    text = re.sub(r"[-–—]\s*\x00|\x00\s*[-–—]", "\x00", text).replace("\x00", " ")
    name = re.sub(r"\s+", " ", text).strip(" -–—_.,;")
    return name or stem, thickness, qty


def thumbnail_svg(svg):
    """Эскиз в строку таблицы. Отрисовщик ezdxf даёт чёрный лист в натуральную величину
    («810mm») с белыми линиями толщиной в доли пикселя — в ячейке он невидим. Здесь:
    без чёрного фона, размер ячейки, линия постоянной толщины."""
    if not svg:
        return svg
    svg = re.sub(r"<\?xml[^>]*>\s*", "", svg)
    svg = re.sub(r'<rect fill="#000000"[^>]*/>', "", svg, count=1)
    svg = re.sub(r'(<svg[^>]*?)\swidth="[^"]*"\s+height="[^"]*"', r'\1 width="72" height="48" '
                 r'preserveAspectRatio="xMidYMid meet"', svg, count=1)
    # Белым: виджет эскиза (pmk_calc, .pmk-sketch) инвертирует картинку — линия станет
    # тёмной, как у эскизов доборки.
    svg = re.sub(r"stroke:\s*#[0-9a-fA-F]{6}", "stroke: #ffffff", svg)
    svg = re.sub(r"stroke-width:\s*[\d.]+;", "stroke-width: 1.2px; vector-effect: non-scaling-stroke;", svg)
    return svg


def drawing_metrics(data_b64, file_name):
    """Разобрать DXF: рез, проколы, габарит детали, эскиз. Ошибка — UserError с именем."""
    from ..tools import drawing  # разбор DXF, Odoo ему не нужен

    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, os.path.basename(file_name or "part.dxf") or "part.dxf")
        with open(path, "wb") as handle:
            handle.write(base64.b64decode(data_b64))
        try:
            metrics = drawing.analyze(path)
            svg = drawing.render_svg(path)
        except Exception as e:  # noqa: BLE001 — битый файл: текст инженеру, не трейсбек
            raise UserError(_("Чертёж «%(name)s» не читается: %(err)s") % {
                "name": file_name, "err": str(e)[:200]})
    return {
        "cut_length_mm": metrics.cut_length_mm,
        "pierce_count": metrics.pierce_count,
        "part_width_mm": metrics.part_width_mm or metrics.width_mm,
        "part_height_mm": metrics.part_height_mm or metrics.height_mm,
        "preview_svg": thumbnail_svg(svg),
    }


class LaserTask(models.Model):
    _name = "pmk.laser.task"
    _description = "Задание на резку"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    active = fields.Boolean("Активен", default=True)
    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    date_due = fields.Date("Нужно к", tracking=True)
    partner_id = fields.Many2one("res.partner", "Заказчик", tracking=True)
    spec_id = fields.Many2one("pmk.metal.spec", "Расчёт металлопроката", index=True, ondelete="set null",
                              tracking=True, help="По какому расчёту режем — задание появится на схеме связей.")
    sale_order_id = fields.Many2one("sale.order", "Заказ", tracking=True)
    note = fields.Char("Примечание")
    part_ids = fields.One2many("pmk.laser.task.part", "task_id", "Детали", copy=True)
    job_ids = fields.Many2many("pmk.laser.job", string="Раскрои", compute="_compute_progress")
    job_count = fields.Integer("Раскроев", compute="_compute_progress")

    qty_total = fields.Integer("Деталей, шт", compute="_compute_progress", store=True)
    qty_nested = fields.Integer("В раскроях, шт", compute="_compute_progress", store=True)
    qty_cut = fields.Integer("Порезано, шт", compute="_compute_progress", store=True)
    mass_kg = fields.Float("Вес, кг", compute="_compute_progress", store=True, digits=(12, 1),
                           help="Прикидка по раскроям: доля полезного веса раскроя по штукам × габарит детали.")
    mass_cut_kg = fields.Float("Порезано, кг", compute="_compute_progress", store=True, digits=(12, 1))
    sheets_total = fields.Integer("Листов", compute="_compute_progress", store=True,
                                  help="Листы раскроев, в которых есть детали этого задания. Раскрой нескольких "
                                       "заказов считается целиком у каждого — лист режут один.")
    sheets_cut = fields.Integer("Порезано листов", compute="_compute_progress", store=True)
    progress_pct = fields.Float("Порезано, %", compute="_compute_progress", store=True, digits=(5, 0),
                                aggregator=None)
    progress_text = fields.Char("Прогресс", compute="_compute_progress")
    thickness_text = fields.Char("Толщины", compute="_compute_progress", store=True)
    state = fields.Selection([("new", "Новое"), ("nest", "Раскладывается"), ("work", "Режется"),
                              ("done", "Порезано")], "Состояние", compute="_compute_progress", store=True)

    @api.depends("part_ids.qty", "part_ids.qty_nested", "part_ids.qty_cut", "part_ids.mass_kg",
                 "part_ids.mass_cut_kg", "part_ids.thickness_mm",
                 "part_ids.line_ids.job_id.sheet_count", "part_ids.line_ids.job_id.sheet_ids.cut_state")
    def _compute_progress(self):
        for task in self:
            parts = task.part_ids
            jobs = parts.line_ids.job_id
            task.job_ids = jobs
            task.job_count = len(jobs)
            task.qty_total = sum(parts.mapped("qty"))
            task.qty_nested = sum(parts.mapped("qty_nested"))
            task.qty_cut = sum(parts.mapped("qty_cut"))
            task.mass_kg = sum(parts.mapped("mass_kg"))
            task.mass_cut_kg = sum(parts.mapped("mass_cut_kg"))
            sheets = jobs.sheet_ids
            task.sheets_total = len(sheets)
            task.sheets_cut = len(sheets.filtered(lambda s: s.cut_state == "done"))
            task.progress_pct = 100.0 * task.qty_cut / task.qty_total if task.qty_total else 0.0
            task.progress_text = "Порезано %d из %d шт · %s из %s кг · %d из %d листов" % (
                task.qty_cut, task.qty_total, _kg(task.mass_cut_kg), _kg(task.mass_kg),
                task.sheets_cut, task.sheets_total)
            thick = sorted({round(t, 2) for t in parts.mapped("thickness_mm") if t})
            task.thickness_text = ", ".join("%s мм" % _mm(t) for t in thick) or False
            if task.qty_total and task.qty_cut >= task.qty_total:
                task.state = "done"
            elif task.qty_cut or task.sheets_cut:
                task.state = "work"
            elif task.qty_nested:
                task.state = "nest"
            else:
                task.state = "new"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.laser.task") or "Черновик"
        return super().create(vals_list)

    @api.onchange("spec_id")
    def _onchange_spec_id(self):
        for task in self:
            if task.spec_id and not task.partner_id:
                task.partner_id = task.spec_id.partner_id

    def action_open_jobs(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("pmk_laser.action_laser_job")
        action["domain"] = [("id", "in", self.job_ids.ids)]
        return action

    def action_parts_to_nest(self):
        """Детали задания, которые ещё не в раскрое, — в «Детали к раскрою»."""
        action = self.env["ir.actions.actions"]._for_xml_id("pmk_laser.action_laser_parts_to_nest")
        action["domain"] = [("task_id", "in", self.ids), ("qty_left", ">", 0)]
        action["context"] = {"search_default_group_thickness": 1}
        return action

    # ------------------------------------------------------------ загрузка пачкой
    def pmk_upload_preview(self, files):
        """Окно «Загружено N файлов»: что получится из каждого файла (ничего не пишет).

        files — [{name, size, sha1, folder}]. Ответ — строки окна с решением по умолчанию.
        Тот же файл (совпадение содержимого) — «повтор, пропустить»; имя то же, чертёж другой —
        «новой строкой» с подстановкой папки или «(2)»: решает инженер.
        """
        self.ensure_one()
        known = {}
        for part in self.part_ids:
            known.setdefault(part.name.strip().lower(), part)
        checks = self._drawing_checksums()
        by_sum = {checks.get(p.id): p for p in self.part_ids if checks.get(p.id)}
        rows, taken = [], set(known)
        for f in files:
            name = f.get("name") or ""
            if not name.lower().endswith(".dxf"):
                rows.append({"file": name, "skip": True, "reason": "не чертёж .dxf — пропущен"})
                continue
            part_name, thick, qty = parse_file_name(name)
            row = {"file": name, "name": part_name, "thickness": thick, "qty": qty or 1,
                   "qty_missing": qty is None, "action": "new", "conflict": False}
            same = by_sum.get(f.get("sha1"))
            if same:
                row.update(conflict="same", action="skip", existing=same.name,
                           reason="тот же чертёж уже есть — «%s»" % same.name)
            elif part_name.strip().lower() in taken:
                folder = (f.get("folder") or "").strip()
                alt = "%s · %s" % (folder, part_name) if folder else part_name
                n = 2
                while alt.strip().lower() in taken:
                    alt = "%s (%d)" % (part_name, n)
                    n += 1
                row.update(conflict="name", action="new", alt_name=alt,
                           existing=known.get(part_name.strip().lower(), self.env["pmk.laser.task.part"]).name,
                           reason="«%s» уже есть, чертёж другой" % part_name)
                taken.add(alt.strip().lower())
            else:
                taken.add(part_name.strip().lower())
            rows.append(row)
        return rows

    def pmk_upload_apply(self, rows):
        """Записать решения окна: rows — [{file, data(b64), name, thickness, qty, action, alt_name}].

        action: new — новая деталь (alt_name при совпадении имени), replace — заменить чертёж
        детали с этим именем (количество не трогаем), skip — ничего. Чертёж разбирается сразу;
        не читается — деталь всё равно создаётся, ошибка — в ответе."""
        self.ensure_one()
        Part = self.env["pmk.laser.task.part"]
        created, replaced, errors = 0, 0, []
        for row in rows:
            action = row.get("action")
            if action == "skip" or not row.get("data"):
                continue
            name = (row.get("alt_name") or row.get("name") or "").strip()
            vals = {"drawing": row["data"], "drawing_name": row.get("file")}
            if action == "replace":
                part = self.part_ids.filtered(lambda p, n=(row.get("name") or "").strip().lower():
                                              p.name.strip().lower() == n)[:1]
                if not part:
                    errors.append(_("«%s»: заменять нечего — детали с таким именем нет") % row.get("name"))
                    continue
                part.write(vals)
                replaced += 1
            else:
                if not row.get("thickness"):
                    errors.append(_("«%s»: толщина не указана — впишите в строке детали") % name)
                part = Part.create(dict(vals, task_id=self.id, name=name,
                                        thickness_mm=row.get("thickness") or 0.0,
                                        qty=max(1, int(row.get("qty") or 1))))
                created += 1
            try:
                part.action_parse_drawing()
            except UserError as e:
                errors.append(str(e.args[0] if e.args else e))
        msg = _("Добавлено деталей: %(c)d, заменено чертежей: %(r)d.") % {"c": created, "r": replaced}
        self.message_post(body=msg + ("<br/>" + "<br/>".join(errors) if errors else ""),
                          subtype_xmlid="mail.mt_note")
        return {"created": created, "replaced": replaced, "errors": errors}

    def _drawing_checksums(self):
        att = self.env["ir.attachment"].sudo().search_read(
            [("res_model", "=", "pmk.laser.task.part"), ("res_field", "=", "drawing"),
             ("res_id", "in", self.part_ids.ids)], ["res_id", "checksum"])
        return {a["res_id"]: a["checksum"] for a in att}


def _kg(v):
    return ("%.0f" % v) if v >= 100 else ("%.1f" % v).replace(".", ",").replace(",0", "")


def _mm(v):
    return ("%g" % v).replace(".", ",")


class LaserTaskPart(models.Model):
    _name = "pmk.laser.task.part"
    _description = "Деталь задания на резку"
    _order = "task_id, thickness_mm, id"

    task_id = fields.Many2one("pmk.laser.task", "Задание на резку", required=True, ondelete="cascade",
                              index=True)
    partner_id = fields.Many2one(related="task_id.partner_id", store=True, string="Заказчик")
    name = fields.Char("Деталь", required=True)
    thickness_mm = fields.Float("Толщина, мм", digits=(6, 2), aggregator=None,
                                help="Из имени файла «пл1 10мм 20шт» или вручную. Раскрой — одной толщины.")
    sheet_type = fields.Char("Вид листа", default=DEFAULT_SHEET_TYPE,
                             help="Гладкий, рифлёный… — вместе с толщиной выбирает лист справочника.")
    # Лист справочника по толщине и виду — группа «Деталей к раскрою» («Лист гладкий 2 мм»,
    # по порядку справочника; группа по числу толщины подписывалась бы «2.0»). Раскрой —
    # одного листа. Нет такого листа в справочнике — группа «не указан».
    sheet_id = fields.Many2one("pmk.metal.sheet", "Лист", compute="_compute_sheet", store=True, index=True)
    qty = fields.Integer("Штук", required=True, default=1)
    drawing = fields.Binary("Чертёж (.dxf)", attachment=True)
    drawing_name = fields.Char("Имя чертежа")
    cut_length_mm = fields.Float("Рез на деталь, мм", digits=(12, 1), readonly=True)
    pierce_count = fields.Integer("Проколов на деталь", readonly=True)
    part_width_mm = fields.Float("Габарит, ширина", digits=(10, 1), readonly=True, aggregator=None)
    part_height_mm = fields.Float("Габарит, длина", digits=(10, 1), readonly=True, aggregator=None)
    preview_svg = fields.Text("Эскиз", readonly=True)
    drawing_error = fields.Char("Чертёж не читается", readonly=True)

    line_ids = fields.One2many("pmk.laser.job.part", "task_part_id", "В раскроях")
    qty_nested = fields.Integer("В раскроях", compute="_compute_nest", store=True)
    qty_left = fields.Integer("Осталось разложить", compute="_compute_nest", store=True)
    qty_cut = fields.Integer("Порезано", compute="_compute_nest", store=True)
    mass_kg = fields.Float("Вес, кг", compute="_compute_nest", store=True, digits=(12, 2))
    mass_cut_kg = fields.Float("Порезано, кг", compute="_compute_nest", store=True, digits=(12, 2))
    nest_text = fields.Char("Раскрои", compute="_compute_nest_text")
    size_text = fields.Char("Габарит", compute="_compute_nest_text")

    _qty_positive = models.Constraint("CHECK(qty > 0)", "Штук должно быть больше нуля.")

    @api.depends("thickness_mm", "sheet_type")
    def _compute_sheet(self):
        Sheet = self.env["pmk.metal.sheet"]
        for part in self:
            t = part.thickness_mm
            part.sheet_id = t and Sheet.search([
                ("sheet_type", "=ilike", (part.sheet_type or DEFAULT_SHEET_TYPE).strip()),
                ("thickness_mm", ">=", t - THICKNESS_TOLERANCE_MM),
                ("thickness_mm", "<=", t + THICKNESS_TOLERANCE_MM)], limit=1)

    @api.depends("qty", "line_ids.qty", "line_ids.qty_cut", "line_ids.mass_kg", "line_ids.mass_cut_kg")
    def _compute_nest(self):
        for part in self:
            part.qty_nested = sum(part.line_ids.mapped("qty"))
            part.qty_left = max(0, part.qty - part.qty_nested)
            part.qty_cut = sum(part.line_ids.mapped("qty_cut"))
            nested_mass = sum(part.line_ids.mapped("mass_kg"))
            # Вес неразложенного остатка — по весу штуки в раскроях (если были).
            per_piece = nested_mass / part.qty_nested if part.qty_nested else 0.0
            part.mass_kg = nested_mass + per_piece * part.qty_left
            part.mass_cut_kg = sum(part.line_ids.mapped("mass_cut_kg"))

    @api.depends("line_ids.job_id.name", "line_ids.job_id.nest_state_text", "part_width_mm", "part_height_mm")
    def _compute_nest_text(self):
        for part in self:
            part.nest_text = " · ".join("%s × %d — %s" % (l.job_id.name, l.qty, l.job_id.nest_state_text or "")
                                        for l in part.line_ids) or False
            part.size_text = ("%s × %s" % (_mm(round(part.part_width_mm)), _mm(round(part.part_height_mm)))
                              if part.part_width_mm and part.part_height_mm else False)

    @api.constrains("qty")
    def _check_nested(self):
        for part in self:
            if part.qty_nested > part.qty:
                raise UserError(_("«%(n)s»: в раскроях %(a)d шт, а в задании %(b)d — уменьшите количество "
                                  "в раскрое.") % {"n": part.name, "a": part.qty_nested, "b": part.qty})

    def write(self, vals):
        res = super().write(vals)
        if "drawing" in vals:
            for part in self:
                # Чертёж заменили — прежний разбор не про него.
                if part.drawing:
                    try:
                        part.action_parse_drawing()
                    except UserError:
                        pass
                part.line_ids.filtered(lambda l: l.drawing != part.drawing)._sync_from_task_part()
        elif {"name", "thickness_mm"} & set(vals):
            self.line_ids._sync_from_task_part()
        return res

    def action_parse_drawing(self):
        for part in self:
            if not part.drawing:
                raise UserError(_("У детали «%s» не приложен чертёж") % part.name)
            try:
                vals = drawing_metrics(part.drawing, part.drawing_name or part.name + ".dxf")
            except UserError as e:
                super(LaserTaskPart, part).write({"drawing_error": str(e.args[0])[:250]})
                raise
            super(LaserTaskPart, part).write(dict(vals, drawing_error=False))
        return True

    def action_view_drawing(self):
        """Окно просмотра DXF (pmk_drawing) — тот же приём, что у строки раскроя."""
        self.ensure_one()
        return self.env["pmk.laser.job.part"]._pmk_view_drawing_of(self)

    def _sha1(self):
        self.ensure_one()
        return hashlib.sha1(base64.b64decode(self.drawing or b"")).hexdigest()

    # ------------------------------------------------------------ в раскрой
    def _check_for_nest(self, mixed=False):
        """mixed — раскрой-документ: толщины любые (программы по толщинам сами)."""
        if not self:
            raise UserError(_("Отметьте детали для раскроя."))
        thick = {round(p.thickness_mm or 0.0, 3) for p in self}
        kinds = {(p.sheet_type or DEFAULT_SHEET_TYPE).strip().lower() for p in self}
        if 0.0 in thick:
            raise UserError(_("У деталей не указана толщина: %s — впишите её в задании.")
                            % ", ".join(self.filtered(lambda p: not p.thickness_mm).mapped("name")))
        no_sheet = self.filtered(lambda p: not p.sheet_id)
        if no_sheet:
            raise UserError(_("Нет листа в справочнике для: %s — заведите лист этой толщины и вида "
                              "(Калькуляторы → справочник листа).")
                            % ", ".join("%s (%s мм %s)" % (p.name, _mm(p.thickness_mm), (p.sheet_type or "").lower())
                                        for p in no_sheet))
        if not mixed and (len(thick) > 1 or len(kinds) > 1):
            raise UserError(_("Раскрой бывает одной толщины и одного вида листа, а отмечено: %s.")
                            % ", ".join(sorted({"%s мм %s" % (_mm(p.thickness_mm), (p.sheet_type or "").lower())
                                                for p in self})))
        missing = self.filtered(lambda p: not p.drawing)
        if missing:
            raise UserError(_("Нет чертежа у деталей: %s — без него раскрой не построить.")
                            % ", ".join(missing.mapped("name")))
        done = self.filtered(lambda p: p.qty_left <= 0)
        if done == self:
            raise UserError(_("Эти детали уже разложены целиком."))

class LaserAddToNest(models.TransientModel):
    _name = "pmk.laser.add.to.nest"
    _description = "Добавить детали в раскрой"

    part_ids = fields.Many2many("pmk.laser.task.part", string="Детали")
    nest_id = fields.Many2one("pmk.laser.nest", "Раскрой", required=True, domain="[('state', '=', 'draft')]",
                              help="Раскрои, у которых программы ещё не приняты.")

    def action_apply(self):
        self.ensure_one()
        self.part_ids._check_for_nest(mixed=True)
        self.nest_id._add_task_parts(self.part_ids)
        return {"type": "ir.actions.act_window", "res_model": "pmk.laser.nest", "res_id": self.nest_id.id,
                "views": [[False, "form"]], "target": "current"}
