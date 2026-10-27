# -*- coding: utf-8 -*-
"""Чертежи опор (правила в.2) — одно задание: input.json → out/<key>/… → result.json.

    python3 runner.py <папка задания>

Запускает чертёжный процесс закладных (pmk_zakladnye/worker/worker.py, контейнер odoo-zk-worker):
в папке задания лежит файл «runner» с путём к этому файлу. Здесь нет Odoo и базы — только
Python, PyMuPDF и шрифт; рисует lib/drawings.py (27.10.2026, Антон: «справочник: Игорь выбрал
размер и исполнение — сразу PDF и DXF»).
"""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))   # генератор в.2: lib/drawings.py

import drawings  # noqa: E402


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _rel(workdir, path):
    return os.path.relpath(path, workdir)


def main(workdir):
    with open(os.path.join(workdir, "input.json"), encoding="utf-8") as f:
        inp = json.load(f)
    out = []
    for item in inp.get("items") or []:
        res = {"key": item["key"]}
        try:
            folder = os.path.join(workdir, "out", str(item["key"]))
            os.makedirs(folder, exist_ok=True)
            got = drawings.draw(item["kind"], item["dn"], item["exe"], item.get("steel") or "Ст3пс", folder)
            res.update(pdf=_rel(workdir, got["pdf"]), png=[_rel(workdir, p) for p in got.get("png") or []],
                       dxf=[dict(d, file=_rel(workdir, d["file"])) for d in got.get("dxf") or []],
                       rules=got.get("rules") or "v2")
        except Exception as e:  # noqa: BLE001 — сбой одной марки не роняет задание
            traceback.print_exc()
            res["error"] = "чертёж не построен: %s" % e
        out.append(res)
    _write(os.path.join(workdir, "result.json"), {"items": out})


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception:  # noqa: BLE001
        _write(os.path.join(sys.argv[1], "error.json"), {"message": traceback.format_exc()})
        raise
