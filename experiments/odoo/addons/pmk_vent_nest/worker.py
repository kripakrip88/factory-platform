# -*- coding: utf-8 -*-
"""Расчётчик раскроя — отдельный контейнер (16.10.2026), без Odoo и без базы.

    python3 worker.py [папка очереди]      # по умолчанию /var/lib/odoo/vent_nest

Антон 16.10: «вынести расчёт в отдельный контейнер — звучит хорошо». Раньше раскрой
шёл внутри контейнера Odoo (2 ядра и 2,5 ГБ на всё): перебор свеса занимал ядро у
пользователей, а несколько процессов сразу грозили нехваткой памяти и падением Odoo.

Обмен — только файлами в общей папке данных Odoo (тот же путь в обоих контейнерах):
    <папка>/.worker_alive        — расчётчик жив (обновляет каждые 2–3 с);
    <папка>/<база>/<id>/queued   — Odoo поставил задание в очередь;
    …/claimed                    — расчётчик взял (переименование — атомарно: второй не возьмёт);
    …/heartbeat                  — расчёт идёт (обновляется каждые 3 с);
    …/cancel                     — Odoo просит остановить (предел времени).
Задания — строго по одному, в порядке постановки; внутри задания раскладки идут
в NEST_PROCS процессов (runner.py, «раскрой и свес»).
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
    """Самое старое задание в очереди, уже взятое — None."""
    queued = glob.glob(os.path.join(root, "*", "*", "queued"))
    for path in sorted(queued, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0):
        workdir = os.path.dirname(path)
        try:
            os.rename(path, os.path.join(workdir, "claimed"))
        except OSError:
            continue  # взял кто-то другой или Odoo забрал считать у себя
        return workdir
    return None


def run_job(root, workdir, procs):
    env = dict(os.environ, TMPDIR=os.path.join(workdir, "tmp"), OMP_NUM_THREADS="1",
               PYTHONDONTWRITEBYTECODE="1", NEST_PROCS=str(procs))
    os.makedirs(env["TMPDIR"], exist_ok=True)
    with open(os.path.join(workdir, "run.log"), "ab") as log:
        proc = subprocess.Popen([sys.executable, RUNNER, workdir], env=env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        while proc.poll() is None:
            if not os.path.isdir(workdir):
                break  # Odoo закрыл задание и убрал папку
            _touch(os.path.join(workdir, "heartbeat"))
            _touch(os.path.join(root, ALIVE))
            if _stop or os.path.exists(os.path.join(workdir, "cancel")):
                break
            time.sleep(3)
        if proc.poll() is None:
            # Вся группа: у раскроя дочерние процессы-раскладки.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()


def main(root):
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    procs = int(os.environ.get("NEST_PROCS") or 3)
    os.makedirs(root, exist_ok=True)
    print("расчётчик раскроя: очередь %s, процессов на задание %d" % (root, procs), flush=True)
    while not _stop:
        _touch(os.path.join(root, ALIVE))
        workdir = _next(root)
        if workdir:
            started = time.time()
            print("задание %s — начато" % workdir, flush=True)
            run_job(root, workdir, procs)
            print("задание %s — %.0f с" % (workdir, time.time() - started), flush=True)
        else:
            time.sleep(2)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/var/lib/odoo/vent_nest")
