# -*- coding: utf-8 -*-
"""Прогон раскроя листа: отдельный процесс и сбор его результата.

Копия устройства pmk_vent_nest (models/nest_job.py): Odoo движок не импортирует —
у движка глобальное состояние и подмены функций пакета, а у воркера предел 240 с.
Одно задание = один процесс (runner.py), обмен — контракт sheet_nest.job/1
(experiments/sheet_nest/ERP.md).

Жизнь прогона: queued → running → done | error. Очередь ОБЩАЯ с раскроем вентзонтов:
одновременно считается один раскрой на весь сервер (2 ядра, 2,5 ГБ на два воркера,
крон и расчёт). Решение «запускать или ждать» — под advisory-блокировкой
(QUEUE_LOCK), иначе две кнопки в двух воркерах запустили бы два процесса.
"""
import base64
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import config

_logger = logging.getLogger(__name__)

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(MODULE_DIR, "lib")
RUNNER = os.path.join(MODULE_DIR, "runner.py")
CONTRACT = "sheet_nest.job/1"
# Образцы ERP.md: до ~30 с на Mac, сервер ~3 раза медленнее. Предел с большим запасом;
# выставить по замеру на сервере ×3 (пункт 9 задания).
TIMEOUT = timedelta(minutes=45)
# Предел движка (time_limit_s): SIGALRM → сторож → faulthandler (ERP.md); TIMEOUT с SIGKILL — страховка сверх.
TIME_LIMIT_S = 1800
NO_PID_GRACE = timedelta(minutes=2)
# Общий ключ очереди раскроя (лист + вентзонты): pg_advisory_xact_lock.
QUEUE_LOCK = 774201
USER_KINDS = ("input", "params", "cancelled", "timeout")
STRATEGIES = [("short", "Минимум холостого"), ("safe", "Безопасный"),
              ("safe0", "Безопасный, конец у нуля"), ("hill", "Горкой")]


def _alive(pid):
    """Жив ли процесс. Зомби (отработал, но не прибран родителем) — не жив."""
    try:
        with open("/proc/%d/status" % pid) as f:
            for line in f:
                if line.startswith("State:"):
                    return "Z" not in line.split()[1]
    except (OSError, ValueError):
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _log_tail(workdir, limit=1500):
    try:
        with open(os.path.join(workdir, "run.log"), encoding="utf-8", errors="replace") as f:
            return f.read()[-limit:]
    except OSError:
        return ""


def nest_queue_busy(env):
    """Считается ли сейчас хоть один раскрой — листа или вентзонтов."""
    busy = env["pmk.sheet.nest.run"].sudo().search_count([("state", "=", "running")])
    if "pmk.vent.nest.job" in env:
        busy += env["pmk.vent.nest.job"].sudo().search_count([("state", "=", "running")])
    return bool(busy)


def nest_queue_lock(env):
    env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (QUEUE_LOCK,))


class SheetNestRun(models.Model):
    _name = "pmk.sheet.nest.run"
    _description = "Раскрой листа — прогон"
    _order = "id desc"

    laser_job_id = fields.Many2one("pmk.laser.job", "Задание лазеру", required=True,
                                   ondelete="cascade", index=True)
    kind = fields.Selection([("plan", "Раскрой и сводка"), ("build", "Программа CypCut")],
                            "Что считается", required=True, default="plan")
    state = fields.Selection([("queued", "В очереди"), ("running", "Считается"),
                              ("done", "Готово"), ("error", "Ошибка")],
                             "Состояние", required=True, default="queued", index=True)
    user_id = fields.Many2one("res.users", "Запустил", default=lambda self: self.env.user)
    params_json = fields.Text("Параметры (JSON)", help="Лист, зазор, край, общий рез, мост, стратегия — "
                                                       "как ушло в движок.")
    strategy = fields.Selection(STRATEGIES, "Стратегия")
    fingerprint = fields.Char("Отпечаток", help="Детали, чертежи, программа-источник и параметры на момент "
                                                 "запуска: по нему видно, что раскрой устарел.")
    progress = fields.Char("Сейчас")
    pid = fields.Integer("Процесс")
    workdir = fields.Char("Папка прогона")
    started_at = fields.Datetime("Запущено")
    finished_at = fields.Datetime("Закончено")
    error = fields.Text("Ошибка")
    error_kind = fields.Char("Вид ошибки")
    error_user = fields.Boolean("Ошибка во входе", help="Показать как есть (плохой DXF, деталь больше листа), "
                                                         "а не сбой движка.")
    result_json = fields.Text("Результат (JSON)")
    ok = fields.Boolean("Проверки пройдены", help="ok движка: false — программу в цех не выдавать.")
    sheets = fields.Integer("Листов")
    png_layouts = fields.Binary("Раскладки", attachment=True)
    png_order = fields.Binary("Порядок резки", attachment=True)
    lxds = fields.Binary("Программа CypCut", attachment=True)
    lxds_name = fields.Char("Имя программы")
    engine_version = fields.Char("Версия движка")

    # ------------------------------------------------------------ запуск
    def _workroot(self):
        return os.path.join(config["data_dir"], "sheet_nest", self.env.cr.dbname)

    def _start(self):
        """Запустить сейчас, если раскрой никто не считает; иначе — в очередь."""
        self.ensure_one()
        nest_queue_lock(self.env)
        if not nest_queue_busy(self.env):
            self._launch()
        for xmlid in ("pmk_sheet_nest.cron_sheet_nest", "pmk_vent_nest.cron_vent_nest"):
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            if cron:
                cron._trigger()

    def _launch(self, sync=False):
        """Подготовить папку и запустить процесс. Ошибка подготовки — сразу error.
        sync=True — ждать процесс здесь же (тесты): тот же runner, то же окружение."""
        self.ensure_one()
        workdir = os.path.join(self._workroot(), str(self.id))
        shutil.rmtree(workdir, ignore_errors=True)
        for sub in ("in", "out", "tmp"):
            os.makedirs(os.path.join(workdir, sub))
        try:
            inp = self.laser_job_id._nest_input(self, workdir)
        except Exception as e:  # noqa: BLE001 — UserError «нет деталей» и т.п.
            self._finish("error", str(e), user_error=True, kind="params")
            return
        with open(os.path.join(workdir, "input.json"), "w", encoding="utf-8") as f:
            json.dump(inp, f, ensure_ascii=False)
        self.write({"state": "running", "workdir": workdir, "started_at": fields.Datetime.now(),
                    "pid": 0, "progress": "запуск", "error": False})
        if sync:
            with open(os.path.join(workdir, "run.log"), "wb") as log:
                subprocess.run([sys.executable, RUNNER, workdir], env=self._env(workdir),
                               stdout=log, stderr=subprocess.STDOUT, timeout=900, check=False)
            self._poll()
        else:
            self._spawn(workdir)

    @staticmethod
    def _env(workdir):
        return dict(os.environ, TMPDIR=os.path.join(workdir, "tmp"),
                    OMP_NUM_THREADS="2", PYTHONDONTWRITEBYTECODE="1")

    @classmethod
    def _spawn(cls, workdir):
        env = cls._env(workdir)

        def _limits():
            # Потолки процессора и памяти воркера Odoo — до жёстких: иначе процесс
            # раскроя унаследовал бы limit_time_cpu и умер посреди расчёта.
            import resource
            for res in (resource.RLIMIT_CPU, resource.RLIMIT_AS):
                _soft, hard = resource.getrlimit(res)
                resource.setrlimit(res, (hard, hard))
            os.nice(10)

        # sh с «&»: процесс сразу уходит от воркера; смерть или перезапуск воркера
        # расчёт не обрывает (как у pmk_vent_nest).
        cmd = ["sh", "-c", 'nohup "$0" "$1" "$2" > "$2/run.log" 2>&1 < /dev/null &',
               sys.executable, RUNNER, workdir]
        subprocess.Popen(cmd, env=env, preexec_fn=_limits, start_new_session=True,
                         close_fds=True).wait(timeout=30)

    # ------------------------------------------------------------ сбор
    @api.model
    def _cron_collect(self):
        for run in self.search([("state", "=", "running")]):
            try:
                run._poll()
            except Exception:  # noqa: BLE001 — один сломанный прогон не держит остальные
                _logger.exception("раскрой листа: не удалось забрать прогон %s", run.id)
                run._finish("error", "Не удалось забрать результат — передано разработчику.", kind="engine")
        nest_queue_lock(self.env)
        if not nest_queue_busy(self.env):
            nxt = self.search([("state", "=", "queued")], order="id", limit=1)
            if nxt:
                nxt._launch()

    def _poll(self):
        self.ensure_one()
        wd = self.workdir or ""
        result = _read_json(os.path.join(wd, "result.json"))
        if result is not None:
            return self._apply(result)
        err = _read_json(os.path.join(wd, "error.json"))
        if err is not None:
            return self._apply_error(err)
        now = fields.Datetime.now()
        pid_txt = ""
        try:
            with open(os.path.join(wd, "pid")) as f:
                pid_txt = f.read().strip()
        except OSError:
            pass
        if not pid_txt:
            if now - (self.started_at or now) > NO_PID_GRACE:
                _logger.error("раскрой листа %s: процесс не запустился\n%s", self.id, _log_tail(wd))
                self._finish("error", "Процесс раскроя не запустился — передано разработчику.", kind="engine")
            return
        pid = int(pid_txt)
        if self.pid != pid:
            self.pid = pid
        if not _alive(pid):
            result = _read_json(os.path.join(wd, "result.json"))
            if result is not None:
                return self._apply(result)
            err = _read_json(os.path.join(wd, "error.json"))
            if err is not None:
                return self._apply_error(err)
            _logger.error("раскрой листа %s: процесс прервался\n%s", self.id, _log_tail(wd))
            if (now - self.started_at).total_seconds() > TIME_LIMIT_S:
                # Третья ступень предела (faulthandler) снимает процесс без итога.
                return self._finish("error", "Расчёт не уложился в предел %d мин — остановлен."
                                    % (TIME_LIMIT_S // 60), user_error=True, kind="timeout")
            return self._finish("error", "Расчёт прервался (например, перезапуск сервера). Запустите ещё раз.",
                                kind="engine")
        if now - self.started_at > TIMEOUT:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            return self._finish("error", "Расчёт идёт дольше %d мин — остановлен."
                                % (TIMEOUT.total_seconds() // 60), user_error=True, kind="timeout")
        prog = _read_json(os.path.join(wd, "progress.json")) or {}
        if prog.get("text") and prog["text"] != self.progress:
            self.progress = prog["text"]

    def _read_file(self, rel):
        if not rel:
            return False
        path = os.path.normpath(os.path.join(self.workdir, rel))
        if not path.startswith(os.path.normpath(self.workdir) + os.sep) or not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            return f.read()

    def _apply(self, result):
        self.ensure_one()
        if result.get("contract") != CONTRACT:
            return self._finish("error", "Движок ответил не по контракту — передано разработчику.", kind="engine")
        files = result.get("files") or {}
        summary = result.get("summary") or {}
        vals = {"result_json": json.dumps(result, ensure_ascii=False), "ok": bool(result.get("ok")),
                "sheets": int(summary.get("sheets") or 0),
                "engine_version": (result.get("engine") or {}).get("sheet_nest")}
        # Файлы забираем в базу ДО _finish: он удаляет папку прогона.
        png = self._read_file(files.get("png_layouts"))
        if png:
            vals["png_layouts"] = base64.b64encode(png)
        png = self._read_file(files.get("png_order"))
        if png:
            vals["png_order"] = base64.b64encode(png)
        lxds = self._read_file(files.get("lxds"))
        if lxds and result.get("ok"):
            vals["lxds"] = base64.b64encode(lxds)
            vals["lxds_name"] = os.path.basename(files["lxds"])
        self.write(vals)
        self.laser_job_id._nest_apply(self, result)
        self._finish("done")

    def _apply_error(self, err):
        kind = err.get("kind") or "engine"
        user = kind in USER_KINDS
        if not user:
            _logger.error("раскрой листа %s: %s\n%s", self.id, err.get("message"), err.get("trace") or "")
        message = err.get("message") if user else (
            "Раскрой не настроен — передано администратору." if kind == "config"
            else "Сбой раскроя — передано разработчику.")
        return self._finish("error", message, user_error=user, kind=kind)

    def _finish(self, state, message=None, user_error=False, kind=False):
        self.ensure_one()
        self.write({"state": state, "finished_at": fields.Datetime.now(), "progress": False,
                    "error": message if state == "error" else False, "error_user": user_error,
                    "error_kind": kind if state == "error" else False})
        if self.workdir and self.workdir.startswith(self._workroot()):
            shutil.rmtree(self.workdir, ignore_errors=True)
        self.laser_job_id._nest_notify(self)

    def _duration_text(self):
        if not (self.started_at and self.finished_at):
            return ""
        sec = int((self.finished_at - self.started_at).total_seconds())
        return "%d мин %02d с" % (sec // 60, sec % 60) if sec >= 60 else "%d с" % sec

    def action_stop(self):
        """«Остановить»: SIGTERM — движок пишет error.json kind=cancelled."""
        for run in self.filtered(lambda r: r.state in ("queued", "running")):
            if run.state == "queued":
                run._finish("error", "Расчёт отменён.", user_error=True, kind="cancelled")
            elif run.pid:
                try:
                    os.kill(run.pid, signal.SIGTERM)
                except OSError:
                    pass
        return True


class VentNestJobQueue(models.Model):
    """Раскрой вентзонтов ждёт, пока считается раскрой листа (очередь общая)."""
    _inherit = "pmk.vent.nest.job"

    def _launch(self, sync=False):
        if not sync:
            nest_queue_lock(self.env)
            if self.env["pmk.sheet.nest.run"].sudo().search_count([("state", "=", "running")]):
                return  # остаётся «В очереди»; запустит крон, когда освободится
        return super()._launch(sync=sync)
