# -*- coding: utf-8 -*-
"""Проверка генератора (или его порта, например в модуль Odoo) по эталонным результатам.

    python3 tests/check_golden.py                      # проверить vent_hood.py из корня папки
    python3 tests/check_golden.py --module путь/к/port.py   # проверить порт: нужны hood(W,L), to_dxf(g), spec(g,t,color)
    python3 tests/check_golden.py --regen              # пересобрать эталоны (ТОЛЬКО при сознательной смене правил)

Сравнивается геометрия DXF (каждый отрезок, дуга, отверстие; допуск 0.02 мм) и спецификация
(лапки, клёпки, детали/габариты/кол-во, металл, расход листа, масса, материал).
Порт может писать DXF в любом виде (LINE/ARC или LWPOLYLINE с bulge) — читается одинаково.
"""
import sys, os, json, math, argparse, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GOLD = os.path.join(HERE, "golden")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dxfread

TOL = 0.02


def load_module(path):
    spec = importlib.util.spec_from_file_location("hood_under_test", path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def cases():
    return json.load(open(os.path.join(GOLD, "cases.json")))


def entities(path):
    holes, segs, _ = dxfread.load(path)
    out = [("C", h[0], h[1], h[2]) for h in holes]
    for s in segs:
        a, b = sorted([tuple(s["p0"]), tuple(s["p1"])])
        if s["t"] == "L":
            out.append(("L", a[0], a[1], b[0], b[1]))
        else:
            out.append(("A", s["c"][0], s["c"][1], s["r"], a[0], a[1], b[0], b[1], s["pm"][0], s["pm"][1]))
    return out


def match(ga, gb):
    """Каждой сущности из ga — пара в gb того же типа с отклонением ≤ TOL. -> (лишние, недостающие, макс.откл.)"""
    used = [False] * len(gb); worst = 0.0; missing = []
    idx = {}
    for j, e in enumerate(gb):
        idx.setdefault((e[0], round(e[1] / 5), round(e[2] / 5)), []).append(j)
    for e in ga:
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in idx.get((e[0], round(e[1] / 5) + dx, round(e[2] / 5) + dy), []):
                    if used[j]:
                        continue
                    d = max(abs(u - v) for u, v in zip(e[1:], gb[j][1:]))
                    if d <= TOL and (best is None or d < best[0]):
                        best = (d, j)
        if best is None:
            missing.append(e)
        else:
            used[best[1]] = True; worst = max(worst, best[0])
    extra = [gb[j] for j in range(len(gb)) if not used[j]]
    return extra, missing, worst


def spec_diff(a, b):
    errs = []
    for k in ("lapki", "lapki_holes_d7", "klepki", "panels", "layout"):
        if a.get(k) != b.get(k):
            errs.append("%s: эталон %s, получено %s" % (k, a.get(k), b.get(k)))
    pa = sorted((p["name"], round(p["size_mm"][0], 1), round(p["size_mm"][1], 1), p["qty"]) for p in a["parts"])
    pb = sorted((p["name"], round(p["size_mm"][0], 1), round(p["size_mm"][1], 1), p["qty"]) for p in b["parts"])
    if pa != pb:
        errs.append("детали: эталон %s, получено %s" % (pa, pb))
    for k, tol in (("metal_net_m2", 0.002), ("metal_blanks_m2", 0.002), ("sheet_1250_m", 0.011),
                   ("mass_net_kg", 0.11), ("mass_sheet_kg", 0.11)):
        if (k in a) != (k in b) or (k in a and abs(a[k] - b[k]) > tol):
            errs.append("%s: эталон %s, получено %s" % (k, a.get(k), b.get(k)))
    if a["material"]["full_name"] != b["material"]["full_name"]:
        errs.append("материал: эталон «%s», получено «%s»" % (a["material"]["full_name"], b["material"]["full_name"]))
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default=os.path.join(ROOT, "vent_hood.py"))
    ap.add_argument("--regen", action="store_true")
    a = ap.parse_args()
    M = load_module(a.module)
    tmp = os.path.join(HERE, "_out"); os.makedirs(tmp, exist_ok=True)
    ok = bad = 0
    for c in cases():
        g = M.hood(c["W"], c["L"])
        sp = M.spec(g, c.get("t"), c.get("color"))
        gold_dxf = os.path.join(GOLD, c["file"]); gold_spec = gold_dxf[:-4] + ".spec.json"
        if a.regen:
            open(gold_dxf, "w").write(M.to_dxf(g))
            json.dump(sp, open(gold_spec, "w"), ensure_ascii=False, indent=1)
            continue
        out = os.path.join(tmp, c["file"]); open(out, "w").write(M.to_dxf(g))
        extra, missing, worst = match(entities(out), entities(gold_dxf))
        errs = spec_diff(json.load(open(gold_spec)), json.loads(json.dumps(sp, ensure_ascii=False)))
        if extra or missing or errs:
            bad += 1
            print("✗ Ш%d Д%d %s" % (c["W"], c["L"], c.get("color") or ""))
            if missing: print("   в эталоне нет %d сущн., пример: %s" % (len(missing), missing[0][:5]))
            if extra: print("   не получено %d сущн. эталона, пример: %s" % (len(extra), extra[0][:5]))
            for e in errs: print("   " + e)
        else:
            ok += 1
    if a.regen:
        print("эталоны пересобраны: %d случаев" % len(cases()))
    else:
        print("совпало %d из %d (допуск геометрии %.2f мм)" % (ok, ok + bad, TOL))
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
