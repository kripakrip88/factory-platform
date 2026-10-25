# -*- coding: utf-8 -*-
"""Чертежи закладных — отдельным процессом (Антон 25.10.2026: «да, делай через отдельный процесс»).

PDF рисует PyMuPDF (≈0,5–1 с на изделие); в образе Odoo его нет, и страница ждать не должна
(правило «доработка не замедляет систему»). Обмен — файлами в общей папке данных, как у
раскроя вентзонтов (pmk_vent_nest/worker.py):

    <data_dir>/zakladnye/.worker_alive          — процесс жив (обновляет каждые 2–3 с);
    <data_dir>/zakladnye/<база>/<id>/input.json  — что рисовать: [{key, series, mark, length}];
    …/queued → claimed                           — Odoo поставил / процесс взял;
    …/heartbeat, progress.json                   — идёт, «3 из 12»;
    …/result.json                                — готово: [{key, pdf, png | error}].

Жизнь задания: queued → running → done | error. Результат забирает cron раз в минуту;
кнопка дёргает его сразу. Процесса нет дольше 2 мин — задание ошибкой с понятной причиной
(рисовать в Odoo нечем — PyMuPDF только в образе процесса).
"""
import base64
import json
import logging
import os
import shutil
import time
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.tools import config

_logger = logging.getLogger(__name__)

WORKER_ALIVE = ".worker_alive"
WORKER_FRESH = timedelta(seconds=30)
WORKER_STALE = timedelta(minutes=2)
# 100 изделий × ~1 с на сервере — пара минут; предел с большим запасом.
TIMEOUT = timedelta(minutes=30)


def _age(path):
    try:
        return timedelta(seconds=max(0.0, time.time() - os.path.getmtime(path)))
    except OSError:
        return None


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class ZkJob(models.Model):
    _name = "pmk.zk.job"
    _description = "Закладные — задание на чертежи"
    _order = "id desc"

    calc_id = fields.Many2one("pmk.zk.calc", "Документ", required=True, ondelete="cascade", index=True)
    line_ids = fields.Many2many("pmk.zk.line", string="Изделия")
    state = fields.Selection([("queued", "В очереди"), ("running", "Рисуется"),
                              ("done", "Готово"), ("error", "Ошибка")],
                             "Состояние", required=True, default="queued", index=True)
    user_id = fields.Many2one("res.users", "Запустил", default=lambda self: self.env.user)
    progress = fields.Char("Сейчас")
    workdir = fields.Char("Папка задания")
    started_at = fields.Datetime("Запущено")
    finished_at = fields.Datetime("Закончено")
    error = fields.Text("Ошибка")

    # ------------------------------------------------------------ очередь
    @staticmethod
    def _queue_root():
        return os.environ.get("PMK_ZK_QUEUE") or os.path.join(config["data_dir"], "zakladnye")

    def _workroot(self):
        return os.path.join(self._queue_root(), self.env.cr.dbname)

    @classmethod
    def _worker_alive(cls, fresh=WORKER_FRESH):
        age = _age(os.path.join(cls._queue_root(), WORKER_ALIVE))
        return age is not None and age < fresh

    def _launch(self):
        """Папка задания и метка «в очереди» для процесса."""
        self.ensure_one()
        workdir = os.path.join(self._workroot(), str(self.id))
        shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir)
        items = [{"key": str(line.id), "series": line.series, "mark": line.mark,
                  "length": line.length or 0.0, "name": line.full_mark or line.mark,
                  "for_key": line._zk_key()}
                 for line in self.line_ids if line._zk_ok()]
        with open(os.path.join(workdir, "input.json"), "w", encoding="utf-8") as f:
            json.dump({"items": items, "name": self.calc_id.name}, f, ensure_ascii=False)
        with open(os.path.join(workdir, "queued"), "w") as f:
            f.write(str(self.id))
        self.write({"state": "running", "workdir": workdir, "started_at": fields.Datetime.now(),
                    "progress": _("в очереди"), "error": False})

    # ------------------------------------------------------------ сбор
    @api.model
    def _cron_collect(self):
        for job in self.search([("state", "=", "running")]):
            try:
                job._poll()
            except Exception:  # noqa: BLE001 — одно сломанное задание не держит остальные
                _logger.exception("закладные: не удалось забрать задание %s", job.id)
                job._finish("error", _("Не удалось забрать чертежи — передано разработчику."))
        for job in self.search([("state", "=", "queued")], order="id"):
            job._launch()

    def _poll(self):
        self.ensure_one()
        wd = self.workdir or ""
        result = _read_json(os.path.join(wd, "result.json"))
        if result is not None:
            return self._apply(result)
        err = _read_json(os.path.join(wd, "error.json"))
        if err is not None:
            _logger.error("закладные %s: сбой процесса\n%s", self.id, err.get("message"))
            return self._finish("error", _("Сбой при рисовании чертежей — передано разработчику."))
        now = fields.Datetime.now()
        if os.path.exists(os.path.join(wd, "queued")):
            alive = _age(os.path.join(self._queue_root(), WORKER_ALIVE))
            if (alive is None or alive > WORKER_STALE) and now - (self.started_at or now) > WORKER_STALE:
                return self._finish("error", _(
                    "Чертёжный процесс не отвечает — чертежи не нарисованы. Скажите разработчику "
                    "(контейнер odoo-zk-worker)."))
            return
        beat = _age(os.path.join(wd, "heartbeat"))
        if beat is not None and beat > WORKER_STALE:
            return self._finish("error", _("Рисование прервалось (например, перезапуск сервера). Запустите ещё раз."))
        if now - (self.started_at or now) > TIMEOUT:
            with open(os.path.join(wd, "cancel"), "w") as f:
                f.write("timeout")
            return self._finish("error", _("Чертежи рисуются дольше %d мин — остановлено.")
                                % (TIMEOUT.total_seconds() // 60))
        prog = _read_json(os.path.join(wd, "progress.json")) or {}
        if prog.get("text") and prog["text"] != self.progress:
            self.progress = prog["text"]

    def _apply(self, result):
        """Чертежи — в строки. Строку за время рисования поменяли — её чертёж не берём."""
        self.ensure_one()
        lines = {str(l.id): l for l in self.line_ids.exists()}
        bad = 0
        for item in result.get("items") or []:
            line = lines.get(str(item.get("key")))
            if not line:
                continue
            if item.get("error") or line._zk_key() != item.get("for_key"):
                line.write({"draw_queued": False, "draw_error": item.get("error") or _("строку изменили")})
                bad += 1
                continue
            vals = {"draw_queued": False, "draw_error": False, "drawing_key": line._zk_key()}
            for field, name in (("pdf", item.get("pdf")), ("png", item.get("png"))):
                if name:
                    with open(os.path.join(self.workdir, name), "rb") as f:
                        vals[field] = base64.b64encode(f.read())
            line.write(vals)
        (self.line_ids.exists().filtered("draw_queued")).write({"draw_queued": False})
        msg = _("Ошибок: %d") % bad if bad else False
        self._finish("done", msg)

    def _finish(self, state, message=None):
        self.ensure_one()
        self.write({"state": state, "finished_at": fields.Datetime.now(), "progress": False,
                    "error": message or False})
        if state == "error":
            self.line_ids.exists().filtered("draw_queued").write({"draw_queued": False, "draw_error": message})
        if self.workdir and self.workdir.startswith(self._workroot()):
            shutil.rmtree(self.workdir, ignore_errors=True)
        calc = self.calc_id
        if self.user_id.partner_id:
            if state == "done":
                text = _("%(doc)s: чертежи готовы (%(n)d).", doc=calc.name, n=len(self.line_ids))
                kind = "success" if not message else "warning"
            else:
                text = _("%(doc)s: %(msg)s", doc=calc.name, msg=message)
                kind = "danger"
            self.user_id._bus_send("simple_notification", {"type": kind, "message": text, "sticky": state == "error"})


class ZkCalcDraw(models.Model):
    _inherit = "pmk.zk.calc"

    def action_zk_draw(self):
        """«Подготовить чертежи»: изделия без свежего чертежа — в очередь фоновому процессу."""
        self.ensure_one()
        self.check_access("write")
        lines = self.line_ids.filtered(lambda l: l._zk_ok() and l.draw_state != "done")
        if not lines:
            if not self.line_ids.filtered(lambda l: l._zk_ok()):
                return self._zk_notify(_("Нет изделий, для которых можно нарисовать чертёж."), "warning")
            return self._zk_notify(_("Все чертежи уже готовы."), "info")
        if self.job_ids.filtered(lambda j: j.state in ("queued", "running")):
            return self._zk_notify(_("Чертежи уже готовятся — дождитесь."), "info")
        lines.write({"draw_queued": True, "draw_error": False})
        job = self.env["pmk.zk.job"].create({"calc_id": self.id, "line_ids": [(6, 0, lines.ids)]})
        job._launch()
        self.env.ref("pmk_zakladnye.cron_zk_collect")._trigger(fields.Datetime.now() + timedelta(seconds=20))
        if not job._worker_alive(WORKER_STALE):
            return self._zk_notify(_("Чертёжный процесс сейчас не запущен — задание в очереди. "
                                     "Если за 2 минуты не начнётся, скажите разработчику."), "warning")
        return self._zk_notify(_("Чертежи готовятся: %d шт. Придёт уведомление.") % len(lines), "info")

    def _zk_notify(self, message, kind):
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": message, "type": kind, "sticky": False,
                           "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}
