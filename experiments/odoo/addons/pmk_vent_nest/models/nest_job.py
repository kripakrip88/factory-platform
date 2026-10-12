# -*- coding: utf-8 -*-
"""Задание раскроя: запуск отдельного процесса и сбор его результата.

Жизнь задания: queued → running → done | error. Запускает кнопка (если ничего не
считается) или cron; результат забирает cron раз в минуту (_cron_collect). Одновременно
считается одно задание — остальные ждут в очереди (раскрой ест ядро и ~0,25 ГБ).
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
# Заказ 30 зонтов: раскрой ~1,5 мин на Mac, сервер ~3 раза медленнее, перебор свеса ×6 —
# до ~25 мин. Предел с запасом; дольше — процесс завис.
TIMEOUT = timedelta(minutes=45)
NO_PID_GRACE = timedelta(minutes=2)


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


class VentNestJob(models.Model):
    _name = "pmk.vent.nest.job"
    _description = "Раскрой вентзонтов — задание"
    _order = "id desc"

    order_id = fields.Many2one("pmk.vent.hood.order", "Заказ вентзонтов", required=True,
                               ondelete="cascade", index=True)
    kind = fields.Selection([("plan", "Раскрой и свес"), ("build", "Программы CypCut")],
                            "Что считается", required=True, default="plan")
    state = fields.Selection([("queued", "В очереди"), ("running", "Считается"),
                              ("done", "Готово"), ("error", "Ошибка")],
                             "Состояние", required=True, default="queued", index=True)
    user_id = fields.Many2one("res.users", "Запустил", default=lambda self: self.env.user)
    gap = fields.Float("Зазор, мм", digits=(6, 1))
    edge = fields.Float("Отступ от края, мм", digits=(6, 1))
    fingerprint = fields.Char("Отпечаток заказа",
                              help="Размеры, цвета, количества, зазор и отступ на момент запуска: "
                                   "по нему видно, что раскрой устарел.")
    builds_json = fields.Text("Что собрать (JSON)")
    progress = fields.Char("Сейчас")
    pid = fields.Integer("Процесс")
    workdir = fields.Char("Папка задания")
    started_at = fields.Datetime("Запущено")
    finished_at = fields.Datetime("Закончено")
    error = fields.Text("Ошибка")
    error_user = fields.Boolean("Ошибка заказа", help="Ошибка во входе (показать как есть), а не сбой.")
    result_json = fields.Text("Результат (JSON)")
    png = fields.Binary("Картинка раскроя", attachment=True)
    version = fields.Char("Версия пакета раскроя")

    # ------------------------------------------------------------ запуск
    def _workroot(self):
        return os.path.join(config["data_dir"], "vent_nest", self.env.cr.dbname)

    def _input(self):
        """input.json и DXF: по одному файлу на «размер + цвет + толщина» (одинаковые строки
        заказа складываются — пакет не принимает один и тот же зонт дважды)."""
        self.ensure_one()
        order = self.order_id
        dxf, qty = {}, {}
        for line in order._vh_good_lines():
            name = line._vh_dxf_name()
            if name not in dxf:
                dxf[name] = line._vh_dxf()
            qty[name] = qty.get(name, 0) + line.qty
        return dxf, qty, {
            "kind": self.kind, "lib": LIB_DIR, "gap": self.gap, "edge": self.edge,
            "dxf": sorted(dxf), "qty": qty, "name": order.name,
            "builds": json.loads(self.builds_json or "[]"),
        }

    def _launch(self, sync=False):
        """Подготовить папку и запустить процесс. Ошибка подготовки — сразу error.
        sync=True — ждать процесс здесь же (тесты): тот же runner, то же окружение."""
        self.ensure_one()
        workdir = os.path.join(self._workroot(), str(self.id))
        shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(os.path.join(workdir, "dxf"))
        os.makedirs(os.path.join(workdir, "tmp"))
        try:
            dxf, _qty, inp = self._input()
        except Exception as e:  # noqa: BLE001 — UserError «нет размеров» и т.п.
            self._finish("error", str(e), user_error=True)
            return
        for name, data in dxf.items():
            with open(os.path.join(workdir, "dxf", name), "wb") as f:
                f.write(data)
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
            # Воркер Odoo ставит себе потолки процессора (limit_time_cpu) и памяти —
            # дочерний процесс их унаследовал бы и умер на долгом переборе свеса.
            import resource
            for res in (resource.RLIMIT_CPU, resource.RLIMIT_AS):
                _soft, hard = resource.getrlimit(res)
                resource.setrlimit(res, (hard, hard))
            os.nice(10)

        # sh с «&»: процесс-раскрой сразу уходит от воркера (его прибирает первый процесс
        # контейнера), и смерть или перезапуск воркера расчёт не обрывает.
        cmd = ["sh", "-c", 'nohup "$0" "$1" "$2" > "$2/run.log" 2>&1 < /dev/null &',
               sys.executable, RUNNER, workdir]
        subprocess.Popen(cmd, env=env, preexec_fn=_limits, start_new_session=True,
                         close_fds=True).wait(timeout=30)

    # ------------------------------------------------------------ сбор
    @api.model
    def _cron_collect(self):
        for job in self.search([("state", "=", "running")]):
            try:
                job._poll()
            except Exception:  # noqa: BLE001 — одно сломанное задание не держит остальные
                _logger.exception("раскрой: не удалось забрать задание %s", job.id)
                job._finish("error", "Не удалось забрать результат — передано разработчику.")
        if not self.search_count([("state", "=", "running")]):
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
            if not err.get("user"):
                _logger.error("раскрой %s: сбой пакета\n%s", self.id, err.get("message"))
            return self._finish("error", err.get("message") if err.get("user") else
                                "Сбой раскроя — передано разработчику.", user_error=bool(err.get("user")))
        now = fields.Datetime.now()
        pid_txt = ""
        try:
            with open(os.path.join(wd, "pid")) as f:
                pid_txt = f.read().strip()
        except OSError:
            pass
        if not pid_txt:
            if now - (self.started_at or now) > NO_PID_GRACE:
                _logger.error("раскрой %s: процесс не запустился\n%s", self.id, _log_tail(wd))
                self._finish("error", "Процесс раскроя не запустился — передано разработчику.")
            return
        pid = int(pid_txt)
        if self.pid != pid:
            self.pid = pid
        if not _alive(pid):
            # Результат мог появиться между проверками — ещё раз.
            result = _read_json(os.path.join(wd, "result.json"))
            if result is not None:
                return self._apply(result)
            _logger.error("раскрой %s: процесс прервался\n%s", self.id, _log_tail(wd))
            return self._finish("error", "Расчёт прервался (например, перезапуск сервера). "
                                         "Запустите ещё раз.")
        if now - self.started_at > TIMEOUT:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            return self._finish("error", "Расчёт идёт дольше %d мин — остановлен."
                                % (TIMEOUT.total_seconds() // 60))
        prog = _read_json(os.path.join(wd, "progress.json")) or {}
        if prog.get("text") and prog["text"] != self.progress:
            self.progress = prog["text"]

    def _apply(self, result):
        self.ensure_one()
        self.write({"result_json": json.dumps(result, ensure_ascii=False),
                    "version": result.get("version")})
        if self.kind == "plan":
            png_path = os.path.join(self.workdir, "plan.png")
            if os.path.exists(png_path):
                with open(png_path, "rb") as f:
                    self.png = base64.b64encode(f.read())
            self.order_id._nest_apply_plan(self, result)
        else:
            self.order_id._nest_apply_build(self, result)
        self._finish("done")

    def _finish(self, state, message=None, user_error=False):
        self.ensure_one()
        self.write({"state": state, "finished_at": fields.Datetime.now(), "progress": False,
                    "error": message if state == "error" else False, "error_user": user_error})
        if self.workdir and self.workdir.startswith(self._workroot()):
            shutil.rmtree(self.workdir, ignore_errors=True)
        self.order_id._nest_notify(self)

    def _duration_text(self):
        if not (self.started_at and self.finished_at):
            return ""
        sec = int((self.finished_at - self.started_at).total_seconds())
        return "%d мин %02d с" % (sec // 60, sec % 60) if sec >= 60 else "%d с" % sec
