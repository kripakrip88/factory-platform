# -*- coding: utf-8 -*-
"""Процесс раскроя листа — запускается Odoo отдельно, без Odoo внутри.

    python3 runner.py <папка прогона>

Весь обмен с Odoo — контракт sheet_nest.job/1 (experiments/sheet_nest/ERP.md):
Odoo кладёт input.json и входы в in/, процесс пишет pid, progress.json, run.log,
result.json (последним, атомарно) или error.json.

Движок — lib/sheet_nest (job.main), его ведёт чат sheet_nest; правки lib/ — только
веткой feature/sheet-nest-lib. Пока движка в lib/ нет — заглушка stub/stub_job.py
по тому же контракту (экран и путь проверяются, программа не собирается).
"""
import json
import os
import sys
import traceback

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def _engine_dir(inp):
    lib = inp.get("engine_lib") or os.path.join(MODULE_DIR, "lib")
    return lib if os.path.isdir(os.path.join(lib, "sheet_nest")) else None


def run(workdir):
    """Код выхода движка (0 итог, 1 ошибка, 2 ничего не записано, 3 сторож) — для журнала;
    Odoo итог берёт из файлов."""
    inp = {}
    try:
        with open(os.path.join(workdir, "input.json"), encoding="utf-8") as f:
            inp = json.load(f)
        lib = _engine_dir(inp)
        if lib:
            sys.path.insert(0, lib)
            from sheet_nest import job
        else:
            sys.path.insert(0, os.path.join(MODULE_DIR, "stub"))
            import stub_job as job
        return job.main(workdir) or 0
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 — сбой должен дойти до Odoo, а не умереть молча
        path = os.path.join(workdir, "error.json")
        if not os.path.exists(path) and not os.path.exists(os.path.join(workdir, "result.json")):
            run_id = inp.get("run_id") if isinstance(inp, dict) else None
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"contract": "sheet_nest.job/1", "kind": "engine", "user": False,
                           "message": ("%s: %s" % (type(e).__name__, e))[:1000],
                           "trace": traceback.format_exc()[-4000:], "run_id": run_id, "input": None},
                          f, ensure_ascii=False)
            os.replace(path + ".tmp", path)
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
