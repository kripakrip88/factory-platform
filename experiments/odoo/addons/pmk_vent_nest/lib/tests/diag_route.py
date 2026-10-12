# -*- coding: utf-8 -*-
"""Диагностика расхождения маршрута резки между окружениями (Mac ↔ сервер).

    python3 tests/diag_route.py снять ДАМП.json        # снять: окружение, раскрой с полной точностью, порядок контуров
    python3 tests/diag_route.py сравнить A.json B.json  # где два дампа расходятся впервые

Заказ — ВЗ-00003, бухта (тот, где холостой ход на сервере 14,9 м против 13,7). Дамп по шагам конвейера:
  1) детали из DXF (контуры, полная точность);
  2) раскрой: листы, повороты, положения (полная точность);
  3) порядок контуров в собранной программе (точки врезки) и холостой ход.
Первое расхождение показывает, какой шаг зависит от окружения.
"""
import sys, os, json, platform, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
Q3 = {"750x4000": 1, "1000x1200": 1}


def snap(path):
    import numpy, PIL
    from vent_nesting import api, nest as N, model as LM, lxds_write as LW, lxds_reader as LR, contours as C
    o = api.order_from_zip(open(os.path.join(HERE, "data", "ВЗ-00003.zip"), "rb").read(), Q3)
    api._params(2, 2, None)
    items = o.items(None)
    out = {"env": {"python": sys.version.split()[0], "numpy": numpy.__version__, "pillow": PIL.__version__,
                   "platform": platform.platform(), "machine": platform.machine()},
           "items": [], "materials": []}
    for it in items:
        c = C.part_contours(it)
        out["items"].append({"hood": it["hood"], "role": it["role"], "key": it["key"],
                             "outer": [list(map(repr, v)) for v in c["outer"]], "holes": [list(map(repr, h)) for h in c["holes"]]})
    for mat, its in api._by_material(items).items():
        sc, errs = api._run_variants(its, ("coil",))
        x = sc["coil"]
        sheets = [{"L": L, "placed": [[it["hood"], it["role"], it["key"][:8], r, repr(ox), repr(oy)] for it, r, ox, oy in s.placed]}
                  for s, L in zip(x["_sheets"], x["_lens"])]
        model = LM.build(sc, N.rot_pt, N.rotated, "coil", "")
        raw, M = LW.to_lxds(model, "ВЗ-00003")
        r, ctx = LR.build(raw, name="x", thickness=0.65, min_side=None)
        route = [[[repr(v) for v in e["pts"][0]] for e in d["_ents"]] for d in ctx["lays"]]
        out["materials"].append({"material": list(map(str, mat)), "sheets": sheets, "idle_m": r["totals"]["idle_m"],
                                 "idle_by_layout": [d["idle_m"] for d in r["layouts"]], "route": route,
                                 "geometry_md5": hashlib.md5(M_bytes(raw)).hexdigest()})
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1)
    print("снято:", path, out["env"], [m["idle_m"] for m in out["materials"]])


def M_bytes(raw):
    import zipfile, io
    return zipfile.ZipFile(io.BytesIO(raw)).read("Geometry2D/data.bin")


def compare(a, b):
    A, B = json.load(open(a)), json.load(open(b))
    print("A:", A["env"]); print("B:", B["env"])
    if A["items"] != B["items"]:
        for i, (x, y) in enumerate(zip(A["items"], B["items"])):
            if x != y:
                print("1) ДЕТАЛИ расходятся с детали %d (%s %s)" % (i, x["hood"], x["role"])); return
    print("1) детали из DXF совпадают (полная точность)")
    for ma, mb in zip(A["materials"], B["materials"]):
        print("== %s: холостой ход %s против %s (по раскладкам %s / %s)" % (ma["material"], ma["idle_m"], mb["idle_m"],
                                                                          ma["idle_by_layout"], mb["idle_by_layout"]))
        if ma["sheets"] != mb["sheets"]:
            for i, (x, y) in enumerate(zip(ma["sheets"], mb["sheets"])):
                if x != y:
                    print("2) РАСКРОЙ расходится: лист %d" % (i + 1))
                    for p, q in zip(x["placed"], y["placed"]):
                        if p != q:
                            print("   A", p); print("   B", q); break
                    break
            continue
        print("2) раскрой совпадает (полная точность)")
        for k, (ra, rb) in enumerate(zip(ma["route"], mb["route"])):
            if ra != rb:
                i = next(i for i, (p, q) in enumerate(zip(ra, rb)) if p != q)
                print("3) МАРШРУТ расходится: раскладка %d, контур %d: A %s / B %s" % (k + 1, i + 1, ra[i], rb[i])); break
        else:
            print("3) маршрут совпадает")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "снять":
        snap(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "сравнить":
        compare(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
