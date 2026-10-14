# -*- coding: utf-8 -*-
"""Вкладка «Раскрой листа» в задании лазеру (ERP.md, «Экран»).

Одно задание = один лист и толщина = одна программа CypCut = листы в «Очередь листов».
«Рассчитать раскрой» (plan, сводка по 4 стратегиям) → щелчок по столбцу (стратегия) →
«Собрать программу» (build) → «Принять в задание» (job.file + разбор pmk_laser).
"""
import base64
import hashlib
import json
import os
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .run import CONTRACT, LIB_DIR, STRATEGIES

BAD_NAME = re.compile(r"[&<>\"']")
# Хвосты, которые движок принимает за количество: «_12шт», «(2)», « x12».
QTY_TAIL = re.compile(r"(_\d+\s*шт\.?|\(\d+\)|\s[xх×]\s*\d+)\s*$", re.I)
TITLE_BAD = re.compile(r"[/\\:*?\"<>|]")
CUT_WARN = "Автосортировку в CypCut не запускать — она затрёт порядок резки."


def _mm(value):
    return ("%g" % value).replace(".", ",")


class LaserJobPart(models.Model):
    _inherit = "pmk.laser.job.part"

    nest_label = fields.Char("Подпись", help="Текст гравировки на детали (шрифт ГОСТ тип А). Пусто — без подписи.")
    nest_microjoint = fields.Boolean("На перемычках", help="Деталь держится в листе перемычками: движок не "
                                                            "считает её выпавшей и не берёт в мост.")


class LaserJob(models.Model):
    _inherit = "pmk.laser.job"

    nest_sheet_w = fields.Integer("Лист: ширина, мм", default=1250)
    nest_sheet_l = fields.Integer("Лист: длина, мм", default=2500)
    nest_gap = fields.Float("Зазор, мм", default=2.0, digits=(6, 1), help="Между деталями.")
    nest_edge = fields.Float("Край, мм", default=2.0, digits=(6, 1), help="От детали до края листа.")
    nest_coedge = fields.Boolean("Общий рез", help="Детали вплотную: общая кромка режется один раз. "
                                                   "Вместе с мостом нельзя.")
    nest_bridge = fields.Boolean("Мост", help="Круглые детали связками: одна врезка на связку. "
                                              "Вместе с общим резом нельзя. На станке ещё не проверен.")
    nest_bridge_width = fields.Float("Перемычка моста, мм", default=2.0, digits=(6, 1))
    nest_bridge_group = fields.Integer("Деталей в связке", default=5)
    nest_small_mm = fields.Float("Мелкая деталь, мм", default=100.0, digits=(6, 0),
                                 help="Меньше этого по одной из сторон — проваливается между ламелями: "
                                      "такие детали считаются в опасных переходах.")
    nest_label_all = fields.Char("Подпись всем деталям", help="Если у детали своей подписи нет.")
    nest_strategy = fields.Selection(STRATEGIES, "Порядок резки",
                                     help="Выбирается щелчком по столбцу сводки.")
    nest_source_file = fields.Binary("Программа-источник (.lxds)", attachment=True, copy=False,
                                     help="Программа CypCut без раскладки: детали и количества — из неё, "
                                          "параметры резки инженера переносятся. Не путать с «Файлом раскроя».")
    nest_source_name = fields.Char("Имя программы-источника", copy=False)
    nest_run_ids = fields.One2many("pmk.sheet.nest.run", "laser_job_id", "Прогоны раскроя", copy=False)

    nest_busy = fields.Boolean("Раскрой считается", compute="_compute_nest")
    nest_status = fields.Char("Состояние раскроя", compute="_compute_nest")
    nest_status_kind = fields.Selection([("none", ""), ("busy", ""), ("done", ""), ("stale", ""),
                                         ("error", "")], compute="_compute_nest")
    nest_summary_json = fields.Text("Сводка по стратегиям", compute="_compute_nest")
    nest_png_layouts = fields.Binary("Раскладки", compute="_compute_nest")
    nest_png_order = fields.Binary("Порядок резки", compute="_compute_nest")
    nest_can_build = fields.Boolean(compute="_compute_nest")
    nest_can_accept = fields.Boolean(compute="_compute_nest")
    nest_program = fields.Char("Программа раскроя", compute="_compute_nest")
    nest_warnings = fields.Text("Предупреждения раскроя", compute="_compute_nest")

    @api.constrains("nest_coedge", "nest_bridge")
    def _check_nest_modes(self):
        for job in self:
            if job.nest_coedge and job.nest_bridge:
                raise ValidationError("Общий рез и мост вместе нельзя: мосту нужен зазор между деталями.")

    @api.onchange("nest_coedge")
    def _onchange_nest_coedge(self):
        if self.nest_coedge:
            self.nest_bridge = False

    @api.onchange("nest_bridge")
    def _onchange_nest_bridge(self):
        if self.nest_bridge:
            self.nest_coedge = False

    # ------------------------------------------------------------ состояние
    def _nest_params(self):
        self.ensure_one()
        return {
            "sheet": {"W": self.nest_sheet_w, "L": self.nest_sheet_l}, "gap": self.nest_gap,
            "edge": self.nest_edge, "coedge": bool(self.nest_coedge),
            "bridge": {"width": self.nest_bridge_width, "group": self.nest_bridge_group} if self.nest_bridge else None,
            "small_mm": self.nest_small_mm, "label_all": self.nest_label_all or "",
        }

    def _nest_checksums(self, records, fname):
        """Контрольные суммы вложений поля: форма читает двоичные поля с bin_size —
        «12,3 Кб» вместо файла, — поэтому сравниваем вложения, а не содержимое."""
        ids = [r._origin.id for r in records if r._origin.id]
        if not ids:
            return {}
        rows = self.env["ir.attachment"].sudo().search_read(
            [("res_model", "=", records._name), ("res_field", "=", fname), ("res_id", "in", ids)],
            ["res_id", "checksum"])
        return {row["res_id"]: row["checksum"] for row in rows}

    def _nest_fingerprint(self):
        self.ensure_one()
        sums = self._nest_checksums(self.part_ids, "drawing")
        parts = sorted((p.name or "", p.qty, sums.get(p._origin.id) or "", p.nest_label or "",
                        bool(p.nest_microjoint)) for p in self.part_ids if p.drawing)
        source = self._nest_checksums(self, "nest_source_file").get(self._origin.id) or ""
        raw = json.dumps([parts, source, self.thickness_mm, self._nest_params()], ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()

    @api.depends("nest_run_ids.state", "nest_run_ids.progress", "part_ids", "part_ids.qty", "part_ids.drawing",
                 "part_ids.nest_label", "part_ids.nest_microjoint", "nest_source_file", "nest_sheet_w",
                 "nest_sheet_l", "nest_gap", "nest_edge", "nest_coedge", "nest_bridge", "nest_bridge_width",
                 "nest_bridge_group", "nest_small_mm", "nest_label_all", "nest_strategy", "sheet_id")
    def _compute_nest(self):
        for job in self:
            runs = job.nest_run_ids.sorted("id", reverse=True)
            busy = runs.filtered(lambda r: r.state in ("queued", "running"))[:1]
            plan = runs.filtered(lambda r: r.kind == "plan" and r.state == "done")[:1]
            build = runs.filtered(lambda r: r.kind == "build" and r.state == "done")[:1]
            last = runs.filtered(lambda r: r.state in ("done", "error"))[:1]
            fp = job._nest_fingerprint() if (plan or build) else False
            stale = bool(plan) and plan.fingerprint != fp
            job.nest_busy = bool(busy)
            job.nest_png_layouts = plan.png_layouts if plan else False
            build_fresh = bool(build) and build.fingerprint == fp and build.strategy == job.nest_strategy \
                and (not plan or build.id > plan.id)
            job.nest_png_order = build.png_order if build_fresh else False
            job.nest_summary_json = plan.result_json if plan else False
            job.nest_can_build = bool(plan) and not stale and not busy and bool(job.nest_strategy)
            job.nest_can_accept = build_fresh and build.ok and bool(build.lxds) and not busy
            job.nest_program = ("%s %s" % (build.lxds_name, "✓" if build.ok else "✗")) if build_fresh and \
                build.lxds_name else False
            warn = []
            for run in (plan, build if build_fresh else job.env["pmk.sheet.nest.run"]):
                if run:
                    res = json.loads(run.result_json or "{}")
                    warn += res.get("warnings") or []
                    warn += ["%s: %s" % (c.get("name"), c.get("detail") or "") for c in res.get("checks") or []
                             if c.get("status") in ("warn", "fail")]
            job.nest_warnings = "\n".join(dict.fromkeys(warn)) or False
            if busy:
                what = "раскрой и сводка" if busy.kind == "plan" else "программа CypCut"
                if busy.state == "queued":
                    text = "В очереди: %s — ждёт, пока досчитается другой раскрой." % what
                else:
                    text = "Считается %s%s. Можно уйти с экрана — по готовности придёт уведомление." % (
                        what, " · %s" % busy.progress if busy.progress else "")
                job.nest_status, job.nest_status_kind = text, "busy"
            elif last.state == "error":
                job.nest_status, job.nest_status_kind = "Ошибка: %s" % (last.error or ""), "error"
            elif plan:
                when = fields.Datetime.context_timestamp(job, plan.finished_at).strftime("%d.%m %H:%M")
                if stale:
                    job.nest_status = "Устарело — детали или параметры менялись после раскроя %s. " \
                                      "Нажмите «Рассчитать раскрой»." % when
                    job.nest_status_kind = "stale"
                else:
                    job.nest_status = "Раскрой посчитан %s за %s · %s листов · зазор %s, край %s мм." % (
                        when, plan._duration_text(), plan.sheets, _mm(job.nest_gap), _mm(job.nest_edge))
                    job.nest_status_kind = "done"
            else:
                job.nest_status, job.nest_status_kind = "Раскрой ещё не считали.", "none"

    # ------------------------------------------------------------ вход движка
    def _nest_title(self):
        """«1,5мм ЛР-00012 Решётки» — толщина первой (так её читает разбор pmk_laser)."""
        self.ensure_one()
        words = ["%sмм" % _mm(self.thickness_mm), self.name or ""]
        if self.note:
            words.append(self.note)
        return TITLE_BAD.sub(" ", " ".join(w for w in words if w)).strip()[:120]

    def _nest_check(self):
        self.ensure_one()
        if not self.sheet_id or not self.thickness_mm:
            raise UserError("Выберите лист задания — толщина нужна раскрою (масса, время, программа).")
        if self.nest_coedge and self.nest_bridge:
            raise UserError("Общий рез и мост вместе нельзя: мосту нужен зазор между деталями.")
        if self.nest_sheet_w <= 0 or self.nest_sheet_l <= 0:
            raise UserError("Укажите размер листа.")
        machine = self.machine_id
        if machine and machine.max_width_mm and machine.max_length_mm:
            a, b = sorted((self.nest_sheet_w, self.nest_sheet_l))
            c, d = sorted((machine.max_width_mm, machine.max_length_mm))
            if a > c or b > d:
                raise UserError("Лист %d×%d не помещается на стол «%s» (%d×%d)." % (
                    self.nest_sheet_w, self.nest_sheet_l, machine.name, machine.max_width_mm, machine.max_length_mm))
        if not (0.0 <= self.nest_gap <= 50 and 0.0 <= self.nest_edge <= 100):
            raise UserError("Зазор — от 0 до 50 мм, край — от 0 до 100 мм.")
        parts = self.part_ids.filtered("drawing")
        if not parts and not self.nest_source_file:
            raise UserError("Нечего раскладывать: приложите чертежи .dxf к деталям (вкладка «Детали и чертежи») "
                            "или программу-источник CypCut.")
        names = [p.name for p in parts]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise UserError("У деталей одинаковые имена: %s. Имя детали должно быть уникальным — по нему "
                            "чертёж находит свою деталь после разбора программы." % ", ".join(dup))
        bad = [p.name for p in parts if BAD_NAME.search(p.name or "") or QTY_TAIL.search(p.name or "")]
        if bad:
            raise UserError("Переименуйте детали: %s. В имени нельзя & < > \" ' и хвосты вида «_12шт», «(2)», "
                            "« x12» — движок примет их за количество." % ", ".join(bad))
        if any(p.qty <= 0 for p in parts):
            raise UserError("У каждой детали с чертежом должно быть количество больше нуля.")

    def _nest_input(self, run, workdir):
        """input.json по контракту sheet_nest.job/1 и файлы в in/."""
        self.ensure_one()
        self = self.with_context(bin_size=False)
        self._nest_check()
        inputs = []
        for i, part in enumerate(self.part_ids.filtered("drawing").sorted("id"), 1):
            rel = "in/%d.dxf" % i
            with open(os.path.join(workdir, rel), "wb") as f:
                f.write(base64.b64decode(part.drawing))
            inputs.append({"file": rel, "name": part.name, "qty": part.qty,
                           "key": "pmk.laser.job.part,%d" % part.id})
        if self.nest_source_file:
            with open(os.path.join(workdir, "in/source.lxds"), "wb") as f:
                f.write(base64.b64decode(self.nest_source_file))
            inputs.append({"file": "in/source.lxds"})
        params = json.loads(run.params_json or "{}")
        labels = {p.name: p.nest_label for p in self.part_ids if p.nest_label}
        if params.get("label_all"):
            labels["*"] = params["label_all"]
        vent_lib = os.path.join(os.path.dirname(os.path.dirname(LIB_DIR)), "pmk_vent_nest", "lib")
        return {
            "contract": CONTRACT, "run_id": run.id, "kind": run.kind,
            "engine_lib": LIB_DIR, "vent_nesting_lib": vent_lib,
            "title": self._nest_title(), "inputs": inputs,
            "sheet": params["sheet"], "gap": params["gap"], "edge": params["edge"],
            "thickness": self.thickness_mm,
            "strategy": run.strategy or "safe", "compare": run.kind == "plan",
            "coedge": params["coedge"], "bridge": params["bridge"], "small_mm": params["small_mm"],
            "microjoints": [p.name for p in self.part_ids if p.nest_microjoint],
            "labels": labels or None, "label_opts": {"H": 15, "H_min": 10, "margin": 3},
            "font": None, "machines": [], "time_limit_s": 1800,
        }

    # ------------------------------------------------------------ кнопки
    def _nest_start(self, kind, strategy=None):
        self.ensure_one()
        if self.nest_busy:
            raise UserError("Раскрой этого задания уже считается — дождитесь уведомления.")
        self._nest_check()
        run = self.env["pmk.sheet.nest.run"].create({
            "laser_job_id": self.id, "kind": kind, "strategy": strategy,
            "params_json": json.dumps(self._nest_params(), ensure_ascii=False),
            "fingerprint": self._nest_fingerprint(),
        })
        run._start()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "info", "title": "Раскрой считается в фоне",
            "message": "Можно работать дальше — по готовности придёт уведомление. "
                       "Выкладка обновления обрывает идущий расчёт — тогда запустите ещё раз.",
            "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def action_nest_plan(self):
        return self._nest_start("plan")

    def action_nest_build(self):
        self.ensure_one()
        plan = self.nest_run_ids.filtered(lambda r: r.kind == "plan" and r.state == "done").sorted("id")[-1:]
        if not plan:
            raise UserError("Сначала нажмите «Рассчитать раскрой».")
        if plan.fingerprint != self._nest_fingerprint():
            raise UserError("Детали или параметры менялись после раскроя — пересчитайте раскрой.")
        if not self.nest_strategy:
            raise UserError("Выберите порядок резки — щёлкните по столбцу сводки.")
        return self._nest_start("build", self.nest_strategy)

    def action_nest_stop(self):
        self.nest_run_ids.filtered(lambda r: r.state in ("queued", "running")).action_stop()
        return True

    def action_nest_accept(self):
        """«Принять в задание»: программа → «Файл раскроя», разбор pmk_laser → листы в очередь."""
        self.ensure_one()
        if not self.nest_can_accept:
            raise UserError("Нечего принимать: соберите программу заново (она устарела или не прошла проверки).")
        build = self.with_context(bin_size=False).nest_run_ids.filtered(
            lambda r: r.kind == "build" and r.state == "done" and r.ok and r.lxds).sorted("id")[-1:]
        self.write({"file": build.lxds, "file_name": build.lxds_name})
        result = self.action_parse_file()
        self.message_post(body="Программа раскроя принята в задание: %s (%s листов, порядок «%s»). %s" % (
            build.lxds_name, build.sheets, dict(STRATEGIES).get(build.strategy, build.strategy), CUT_WARN),
            subtype_xmlid="mail.mt_note")
        return result

    # ------------------------------------------------------------ результат
    def _nest_apply(self, run, result):
        """Картинки и программа — вложения задания (вкладка «Файлы»); ok=false — программу не прикладывать."""
        self.ensure_one()
        run = run.with_context(bin_size=False)
        Att = self.env["ir.attachment"]
        stamp = fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime("%Y-%m-%d_%H%M")
        if run.kind == "build" and run.lxds and result.get("ok"):
            Att.create({"name": run.lxds_name, "datas": run.lxds, "res_model": self._name, "res_id": self.id,
                        "mimetype": "application/octet-stream"})
        for field, label in (("png_layouts", "раскладки"), ("png_order", "порядок резки")):
            if run[field] and (run.kind == "plan" or field == "png_order"):
                Att.create({"name": "%s_%s_%s.png" % (self.name, label, stamp), "datas": run[field],
                            "res_model": self._name, "res_id": self.id, "mimetype": "image/png"})

    def _nest_notify(self, run):
        """Заметка в историю задания и всплывашка тому, кто запускал."""
        self.ensure_one()
        title = "%s: %s" % (self.name, "раскрой листа" if run.kind == "plan" else "программа CypCut")
        res = json.loads(run.result_json or "{}")
        if run.state == "error":
            body, kind = "Раскрой не получился: %s" % (run.error or ""), "danger"
        elif run.kind == "plan":
            body = "Раскрой готов (%s): %s листов, нижняя граница %s. Выберите порядок резки щелчком по " \
                   "столбцу сводки во вкладке «Раскрой листа»." % (
                       run._duration_text(), run.sheets, (res.get("summary") or {}).get("lower_bound", "—"))
            kind = "success"
        elif run.ok and run.lxds:
            body = "Программа CypCut собрана: %s (%s листов). Во вкладке «Раскрой листа» — «Принять в задание». " \
                   "%s" % (run.lxds_name, run.sheets, CUT_WARN)
            kind = "success"
        else:
            body = "Программа не выдана — не прошла проверки: %s" % ("; ".join(res.get("warnings") or []) or
                                                                     "передано разработчику")
            kind = "warning"
        self.message_post(body=body, subtype_xmlid="mail.mt_note")
        if run.user_id:
            run.user_id._bus_send("simple_notification", {"title": title, "message": body,
                                                          "sticky": True, "type": kind})

    def _part_commands(self, layout):
        """Разбор программы пересоздаёт детали — подпись и «на перемычках» переносим по имени,
        как pmk_laser переносит чертёж (ERP.md, «Поля на pmk.laser.job.part»)."""
        commands = super()._part_commands(layout)
        kept = {p.name: {"nest_label": p.nest_label, "nest_microjoint": p.nest_microjoint} for p in self.part_ids}
        for command in commands:
            if command[0] == fields.Command.CREATE:
                command[2].update(kept.get(command[2].get("name"), {}))
        return commands
