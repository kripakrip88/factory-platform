# -*- coding: utf-8 -*-
"""Сравнение с программами инженера: детали и количества — из его программы, лист — его размер; наш раскрой и
порядок резки против его листов и холостого хода. Не тест «прошёл/упал» по числам (у инженера бывает общий рез с
нулевым зазором — у нас шаг 2), но все проверки нашей программы обязаны пройти.

    python3 tests/bench_engineer.py [КАТАЛОГ_ОБРАЗЦОВ]      (по умолчанию ~/Downloads/vent_nesting/samples)
Образцы: m3_grpsh, m8_plates, m14, m30, zonty (заводские), reshetki_bez_listov (решётки без листов: лист 1250×2500).
"""
import sys, os, json, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from sheet_nest.libpath import vn
from sheet_nest.cli import run
from sheet_nest.read_lxds import parts_from_lxds

SAMPLES = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/vent_nesting/samples")
THICK = {"m3_grpsh": 3, "m8_plates": 8, "m14": 14, "m30": 30, "zonty": 0.65, "reshetki_bez_listov": 1.5}


def main():
    rows, bad = [], 0
    for fn in sorted(os.listdir(SAMPLES)):
        if not fn.endswith(".lxds"):
            continue
        nm = fn[:-5]
        path = os.path.join(SAMPLES, fn)
        data = open(path, "rb").read()
        parts, info = parts_from_lxds(data, fn)
        if info["plates"]:
            W, L = info["plates"][0][0], info["plates"][0][1]
            eng, _ = vn.lxds_reader.build(data, name=fn, thickness=THICK.get(nm, 1.0), min_side=None)
            e_sheets, e_idle = eng["sheets"], eng["totals"]["idle_m"]
        else:
            W, L, e_sheets, e_idle = 1250.0, 2500.0, None, None
        log = []
        try:
            res, raw, pl, _ = run([path], W, L, 2.0, 2.0, THICK.get(nm), None, nm, None, log=log.append)
        except ValueError as e:
            rows.append((nm, "%g×%g" % (W, L), sum(p["qty"] for p in parts), e_sheets, e_idle, 0, 0, 0.0, "отказ: %s" % e, True, []))
            continue
        bad += not res["ok"]
        rows.append((nm, "%g×%g" % (W, L), sum(p["qty"] for p in parts), e_sheets, e_idle, res["sheets"], res["lower_bound"],
                     res["idle_m"], res["method"], res["ok"], [c[0] for c in res["checks"] if not c[1]]))
    print("%-20s %-11s %5s | %-8s %-9s | %-6s %-4s %-9s %-34s %s" % ("образец", "лист", "дет", "инж.лист", "инж.холост", "наши", "н.гр", "холост", "раскрой", "проверки"))
    for r in rows:
        print("%-20s %-11s %5d | %-8s %-9s | %-6d %-4d %-9.1f %-34s %s %s" % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8][:34], "✓" if r[9] else "✗", r[10] or ""))
        if r[8].startswith("отказ"):
            print("      " + r[8])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
