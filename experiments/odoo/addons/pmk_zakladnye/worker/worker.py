# -*- coding: utf-8 -*-
"""Чертёжный процесс закладных — отдельный контейнер (odoo-zk-worker), без Odoo и без базы.

    python3 worker.py [папка очереди]      # по умолчанию /var/lib/odoo/zakladnye

Антон 25.10.2026: «да, делай через отдельный процесс». PDF рисует PyMuPDF — он есть только
в образе этого контейнера (worker/Dockerfile: python + pymupdf + fonts-liberation).
Обмен — файлами в общей папке данных Odoo (как у раскроя, pmk_vent_nest/worker.py):
    <папка>/.worker_alive        — процесс жив (обновляет каждые 2–3 с);
    <папка>/<база>/<id>/queued   — Odoo поставил задание;
    …/claimed                    — процесс взял (переименование атомарно);
    …/heartbeat                  — рисует (каждые 3 с);
    …/cancel                     — Odoo просит остановить.
Задания — по одному, в порядке постановки.
"""
import glob
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "runner.py")
ALIVE = ".worker_alive"
_stop = False


def _touch(path):
    with open(path, "a"):
        pass
    os.utime(path, None)


def _on_term(_signum, _frame):
    global _stop
    _stop = True


def _next(root):
    queued = glob.glob(os.path.join(root, "*", "*", "queued"))
    for path in sorted(queued, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0):
        workdir = os.path.dirname(path)
        try:
            os.rename(path, os.path.join(workdir, "claimed"))
        except OSError:
            continue
        return workdir
    return None


def run_job(root, workdir):
    env = dict(os.environ, TMPDIR=os.path.join(workdir, "tmp"), PYTHONDONTWRITEBYTECODE="1")
    os.makedirs(env["TMPDIR"], exist_ok=True)
    with open(os.path.join(workdir, "run.log"), "ab") as log:
        proc = subprocess.Popen([sys.executable, RUNNER, workdir], env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        while proc.poll() is None:
            if not os.path.isdir(workdir):
                break
            _touch(os.path.join(workdir, "heartbeat"))
            _touch(os.path.join(root, ALIVE))
            if _stop or os.path.exists(os.path.join(workdir, "cancel")):
                break
            time.sleep(3)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()


def main(root):
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    os.makedirs(root, exist_ok=True)
    print("чертежи закладных: очередь %s" % root, flush=True)
    while not _stop:
        _touch(os.path.join(root, ALIVE))
        workdir = _next(root)
        if workdir:
            started = time.time()
            print("задание %s — начато" % workdir, flush=True)
            run_job(root, workdir)
            print("задание %s — %.0f с" % (workdir, time.time() - started), flush=True)
        else:
            time.sleep(2)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/var/lib/odoo/zakladnye")
