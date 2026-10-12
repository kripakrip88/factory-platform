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
Часовой пояс задаёт Odoo (TZ в окружении): пакет 1.0.0 при сборке программы берёт пояс
машины, а при самопроверке считает его +10 — в контейнере (UTC) все программы выходили
бы «не выдавать». Проверено на сервере 12.10.2026.
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
            progress("раскрой при свесе 150")
            p = api.plan(order, gap=gap, edge=edge, png=True)
            with open(os.path.join(workdir, "plan.png"), "wb") as f:
                f.write(p.get("png") or b"")
            out["materials"] = [{
                "key": m["key"], "color": m["color"], "thickness": m["thickness"],
                "stock": _summary(m.get("stock")), "coil": _summary(m.get("coil")),
                "saving": m.get("saving") or {}, "recommend": m.get("recommend"),
            } for m in p["materials"]]
            progress("перебор свеса 150…125")
            out["sves"] = api.sves_table(order, gap=gap, edge=edge)
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
