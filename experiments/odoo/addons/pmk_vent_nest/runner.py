# -*- coding: utf-8 -*-
"""Процесс раскроя — запускается Odoo отдельно, без Odoo внутри.

    python3 runner.py <папка задания>

В папке задания Odoo заранее кладёт input.json и dxf/<имя генератора>.dxf.
Процесс пишет:
    pid            — свой номер (Odoo по нему понимает, жив ли расчёт);
    progress.json  — что считается сейчас (строка для инженера);
    result.json    — итог (пишется последним, атомарно: сначала .tmp);
    error.json     — {message, user}: user=True — ошибка заказа (текст пакета по-русски,
                     показать как есть), False — сбой (хвост трассировки, для разработчика);
    plan.png, files/<n>.lxds — картинка раскроя и программы.

Почему отдельный процесс: у воркеров Odoo предел 240 с на запрос (limit_time_real),
а перебор свеса большого заказа — минуты; у пакета ещё и глобальное состояние раскроя.
Часовой пояс: пакет с d3ef363 сам пишет заводское время UTC+10 (раньше брал пояс машины,
и в контейнере в UTC все программы выходили «не выдавать»); окружение его больше не задаёт.
"""
import json
import os
import sys
import traceback

PLAN_KEYS_SUMMARY = ("sheets", "lengths_mm", "lengths", "length_m", "m2", "kg", "util_pct", "error")


def _write(workdir, name, data):
    path = os.path.join(workdir, name)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def _summary(variant):
    variant = variant or {}
    return {k: variant[k] for k in PLAN_KEYS_SUMMARY if k in variant}


def _procs():
    """Сколько раскладок считать одновременно (NEST_PROCS; расчётчик ставит 3). 1 — по очереди."""
    try:
        return max(1, int(os.environ.get("NEST_PROCS") or 1))
    except ValueError:
        return 1


def _rows_from_plan(p):
    """Строки таблицы свеса из готового раскроя — тот же вид, что у api.sves_table.

    Свес 150 раньше считался дважды: раскроем и первой строкой перебора (Антон 16.10:
    «повтор это точно лишнее»)."""
    rows = []
    for m in p["materials"]:
        for key in ("stock", "coil"):
            x = m[key]
            row = {"sves": p["sves"], "key": m["key"], "color": m["color"], "thickness": m["thickness"],
                   "source": key}
            if "error" in x:
                row["error"] = x["error"]
            else:
                row.update({"sheets": x["sheets"], "lengths": x["lengths"], "kg": x["kg"],
                            "util_pct": x["util_pct"]})
            rows.append(row)
    return rows


_ORDER = None   # заказ для процессов-раскладок (наследуют при fork)
_PARAMS = None


def _task(sves):
    """Одна раскладка в отдельном процессе: None — раскрой при 150 (с картинкой), иначе строка свеса."""
    from vent_nesting import api
    gap, edge = _PARAMS
    if sves is None:
        return api.plan(_ORDER, gap=gap, edge=edge, png=True)
    return api.sves_table(_ORDER, gap=gap, edge=edge, sves_list=[sves])


def _plan_and_sves(api, order, gap, edge, progress):
    """Раскрой при свесе 150 + перебор 145…125. NEST_PROCS > 1 — одновременно в процессах
    (у пакета глобальное состояние раскроя — потоки нельзя, процессы можно)."""
    global _ORDER, _PARAMS
    rest = [s for s in api.SVES_LIST if float(s) != 150.0]
    tasks = [None] + rest
    procs = min(_procs(), len(tasks))
    results = {}
    if procs == 1:
        for i, s_ in enumerate(tasks, 1):
            progress("раскрой и свес: %d из %d" % (i, len(tasks)))
            if s_ is None:
                results[None] = api.plan(order, gap=gap, edge=edge, png=True)
            else:
                results[s_] = api.sves_table(order, gap=gap, edge=edge, sves_list=[s_])
    else:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor, as_completed
        _ORDER, _PARAMS = order, (gap, edge)
        progress("раскрой и свес: %d вариантов в %d потока" % (len(tasks), procs))
        with ProcessPoolExecutor(max_workers=procs, mp_context=multiprocessing.get_context("fork")) as pool:
            futures = {pool.submit(_task, s_): s_ for s_ in tasks}
            for done, fut in enumerate(as_completed(futures), 1):
                results[futures[fut]] = fut.result()
                progress("раскрой и свес: готово %d из %d" % (done, len(tasks)))
    p = results[None]
    rows = _rows_from_plan(p)
    for s_ in rest:
        rows.extend(results[s_])
    return p, rows


def run(workdir):
    with open(os.path.join(workdir, "pid"), "w") as f:
        f.write(str(os.getpid()))
    with open(os.path.join(workdir, "input.json"), encoding="utf-8") as f:
        inp = json.load(f)
    sys.path.insert(0, inp["lib"])
    import vent_nesting
    from vent_nesting import api

    def progress(text):
        _write(workdir, "progress.json", {"text": text})

    try:
        progress("разбор заказа")
        files = []
        for name in inp["dxf"]:
            with open(os.path.join(workdir, "dxf", name), "rb") as f:
                files.append((name, f.read()))
        order = api.order_from_dxf(files, inp["qty"])
        out = {"version": vent_nesting.__version__, "hoods": order.hoods()}
        gap, edge = inp["gap"], inp["edge"]
        if inp["kind"] == "plan":
            p, rows = _plan_and_sves(api, order, gap, edge, progress)
            with open(os.path.join(workdir, "plan.png"), "wb") as f:
                f.write(p.get("png") or b"")
            out["materials"] = [{
                "key": m["key"], "color": m["color"], "thickness": m["thickness"],
                "stock": _summary(m.get("stock")), "coil": _summary(m.get("coil")),
                "saving": m.get("saving") or {}, "recommend": m.get("recommend"),
            } for m in p["materials"]]
            out["sves"] = rows
        else:
            os.makedirs(os.path.join(workdir, "files"), exist_ok=True)
            out["files"] = []
            for b in inp["builds"]:
                progress("программа: %s" % b["label"])
                sves = None if float(b["sves"]) >= 150 else float(b["sves"])
                for f_ in api.build_lxds(order, b["source"], gap=gap, edge=edge, sves=sves,
                                         material=b["key"], name=inp["name"]):
                    path = "files/%d.lxds" % len(out["files"])
                    with open(os.path.join(workdir, path), "wb") as f:
                        f.write(f_["bytes"])
                    out["files"].append({
                        "filename": f_["filename"], "key": f_["key"], "ok": bool(f_["ok"]),
                        "failed": [c[0] for c in f_.get("checks") or [] if not c[1]],
                        "layouts": f_.get("layouts") or [], "path": path,
                        "source": b["source"], "sves": b["sves"],
                    })
        _write(workdir, "result.json", out)
    except api.VentNestingError as e:
        _write(workdir, "error.json", {"message": str(e), "user": True})
    except BaseException:  # noqa: BLE001 — любой сбой должен дойти до Odoo, а не умереть молча
        _write(workdir, "error.json", {"message": traceback.format_exc()[-4000:], "user": False})


if __name__ == "__main__":
    run(sys.argv[1])
