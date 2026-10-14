# -*- coding: utf-8 -*-
"""ЗАГЛУШКА движка раскроя листа — только пока в lib/ нет sheet_nest.

Отвечает строго по контракту sheet_nest.job/1 (experiments/sheet_nest/ERP.md, ветка
feature/sheet-nest): читает input.json, пишет pid, progress.json, result.json или
error.json. Числа сводки — правдоподобные, но выдуманные: по ним проверяется экран и
путь «рассчитать → выбрать → собрать → принять», а не раскрой. Программу CypCut
заглушка НЕ собирает: сборка возвращает ok=false и предупреждение, «Принять в
задание» остаётся недоступной. Настоящий движок (lib/sheet_nest/job.py) пишет чат
sheet_nest; когда он приедет веткой feature/sheet-nest-lib, runner.py возьмёт его.

Без Odoo и без зависимостей, кроме стандартной библиотеки (Pillow — если есть,
для картинки «ЗАГЛУШКА»).
"""
import json
import math
import os
import signal
import sys
import time

CONTRACT = "sheet_nest.job/1"
STRATEGIES = ("short", "safe", "safe0", "hill")


def _write(workdir, name, data):
    path = os.path.join(workdir, name)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def _error(workdir, inp, kind, message, user=True):
    _write(workdir, "error.json", {"contract": CONTRACT, "run_id": inp.get("run_id"),
                                   "kind": kind, "user": user, "message": message, "trace": "", "input": None})


def _png(path, text):
    """Шрифт Pillow по умолчанию без кириллицы — надпись латиницей."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    img = Image.new("RGB", (640, 200), (245, 244, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle((10, 10, 630, 190), outline=(150, 150, 150), width=2)
    draw.text((30, 90), text, fill=(60, 60, 60))
    img.save(path)
    return True


def _dxf_ok(path):
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    return b"SECTION" in head


def main(workdir):
    with open(os.path.join(workdir, "pid"), "w") as f:
        f.write(str(os.getpid()))
    with open(os.path.join(workdir, "input.json"), encoding="utf-8") as f:
        inp = json.load(f)
    cancelled = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *a: cancelled.update(flag=True))

    def progress(stage, text):
        _write(workdir, "progress.json", {"stage": stage, "text": text})

    progress("read", "чтение деталей (заглушка)")
    if inp.get("contract") != CONTRACT:
        return _error(workdir, inp, "config", "Неизвестный контракт: %s" % inp.get("contract"), user=False)
    inputs = inp.get("inputs") or []
    if not inputs:
        return _error(workdir, inp, "params", "Нет деталей: приложите DXF к деталям или программу-источник.")
    qty_total = 0
    for item in inputs:
        path = os.path.join(workdir, item["file"])
        if item["file"].lower().endswith(".dxf"):
            if not _dxf_ok(path):
                return _error(workdir, inp, "input",
                              "Чертёж «%s» не читается как DXF — пересохраните его из КОМПАСа или AutoCAD."
                              % item.get("name", item["file"]))
            qty_total += int(item.get("qty") or 0)
        else:
            qty_total += 50  # программа-источник: детали и количества — из неё (заглушка не читает)
    if inp.get("coedge") and inp.get("bridge"):
        return _error(workdir, inp, "params", "Общий рез и мост вместе нельзя: мосту нужен зазор.")
    for stage, text in (("pack", "раскрой листов (заглушка)"), ("route", "порядок резки: 2/4 (заглушка)")):
        if cancelled["flag"]:
            return _error(workdir, inp, "cancelled", "Расчёт остановлен.")
        progress(stage, text)
        time.sleep(1)

    sheets = max(1, math.ceil(qty_total / 12.0))
    if inp.get("coedge") and sheets > 2:
        sheets -= 1
    rows = []
    titles = {"short": "Минимум холостого", "safe": "Безопасный", "safe0": "Безопасный, конец у нуля",
              "hill": "Горкой"}
    for i, key in enumerate(STRATEGIES):
        rows.append({
            "name": key, "title": titles[key], "sheets": sheets,
            "cut_m": round(22.6 * sheets, 1), "idle_m": round(7.8 * sheets + 3 * i, 1),
            "return_m": round(1.8 * sheets if key != "safe0" else 0.2 * sheets, 1),
            "pierces": 32 * sheets if not inp.get("bridge") else 19 * sheets, "bridges": None,
            "danger": {"tongues": 0, "small": [3, 0, 1, 2][i], "parts": [11, 0, 0, 1][i], "holes": 0,
                       "holes_s": 2, "near": 40, "short": 12, "mj": 0},
            "strip": {"sheets": 0, "worst": None},
            "ret": {"over_m": round([4.1, 1.2, 0.3, 2.2][i] * sheets, 1), "tongues_crossed": 0, "over": 0},
            "warnings": ["заглушка"] if key == "hill" else [], "machine_s": {}, "error": None,
        })
    files = {"lxds": None, "png_layouts": None, "png_order": None, "report": None}
    os.makedirs(os.path.join(workdir, "out"), exist_ok=True)
    if _png(os.path.join(workdir, "out", "layouts.png"), "STUB: %d sheets - real layout picture comes with the sheet_nest engine" % sheets):
        files["png_layouts"] = "out/layouts.png"
    warnings = ["Заглушка движка: числа выдуманы, раскрой не настоящий — подключим sheet_nest."]
    kind = inp.get("kind")
    ok = True
    if kind == "build":
        ok = False
        warnings.append("Заглушка не собирает программу CypCut — «Принять в задание» недоступна.")
    result = {
        "contract": CONTRACT, "kind": kind, "run_id": inp.get("run_id"),
        "engine": {"sheet_nest": "stub", "vent_nesting": None,
                   "python": "%d.%d" % sys.version_info[:2]},
        "ok": ok,
        "requested": {"strategy": inp.get("strategy"), "coedge": bool(inp.get("coedge")),
                      "bridge": inp.get("bridge"), "labels": inp.get("labels")},
        "applied": {"strategy": inp.get("strategy"), "coedge": bool(inp.get("coedge")),
                    "bridge_groups": 0, "labels_ok": 0, "labels_failed": 0},
        "files": files,
        "summary": dict(rows[1], lower_bound=sheets, optimal=True, method="stub", mark_m=0.0,
                        mass_kg=None),
        "strategies": rows if inp.get("compare") else None,
        "layouts": [{"index": 1, "amount": sheets, "parts": {}, "W": inp["sheet"]["W"],
                     "L": inp["sheet"]["L"], "util_pct": 78.0}],
        "checks": [{"name": "заглушка", "status": "warn", "detail": "движок не подключён"}],
        "warnings": warnings, "labels": [], "bridge": None,
        "parts": [{"name": i.get("name"), "qty": i.get("qty"), "key": i.get("key")} for i in inputs],
        "timing": {"total_s": 2.0, "route_s": 1.0},
    }
    progress("render", "отчёт (заглушка)")
    _write(workdir, "result.json", result)


if __name__ == "__main__":
    main(sys.argv[1])
