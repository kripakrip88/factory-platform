# -*- coding: utf-8 -*-
"""Одно задание чертежей: input.json → out/<key>/<марка>.pdf + лист 1 картинкой → result.json.

    python3 runner.py <папка задания>

Запускает worker.py. Модель изделия — та же, что в Odoo (tools/catalog.py → lib/generate.py);
рисование — generate.draw (PyMuPDF, шрифт Liberation Sans Narrow Italic).
"""
import json
import os
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import catalog  # noqa: E402


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _safe(name):
    return re.sub(r"[^\w\-. ]+", "_", name or "izd").strip() or "izd"


def main(workdir):
    with open(os.path.join(workdir, "pid"), "w") as f:
        f.write(str(os.getpid()))
    with open(os.path.join(workdir, "input.json"), encoding="utf-8") as f:
        inp = json.load(f)
    items = inp.get("items") or []
    g = catalog.gen()
    out = []
    for i, item in enumerate(items, 1):
        _write(os.path.join(workdir, "progress.json"), {"text": "%d из %d" % (i, len(items))})
        res = {"key": item["key"], "for_key": item.get("for_key")}
        try:
            M, ms, why = catalog.model(item["series"], item["mark"], item.get("length") or 0.0)
            if not M:
                res["error"] = why
            else:
                folder = os.path.join(workdir, "out", str(item["key"]))
                os.makedirs(folder, exist_ok=True)
                name = _safe(M["mark"])
                pdf, png = os.path.join(folder, name + ".pdf"), os.path.join(folder, name + ".png")
                g.draw(M, ms, pdf, png)
                res["pdf"] = os.path.relpath(pdf, workdir)
                if os.path.exists(png):
                    res["png"] = os.path.relpath(png, workdir)
        except Exception as e:  # noqa: BLE001 — одна марка не роняет пачку
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
