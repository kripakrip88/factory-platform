# -*- coding: utf-8 -*-
"""Автотесты раскроя и сборки CypCut по эталонам (заказы ВЗ-00002 и ВЗ-00003 в tests/data).

    python3 tests/check_golden.py            # всё (≈2,5 мин на Mac M-серии)
    python3 tests/check_golden.py --quick    # без раскроя ВЗ-00002 (≈40 с)
    python3 tests/check_golden.py --regen    # пересобрать эталоны — ТОЛЬКО при сознательной смене алгоритма

Раскрой детерминирован: тот же заказ → те же листы. Снимок результата сравнивается с эталоном ЦЕЛИКОМ
(любой отличающийся ключ — ошибка), кроме картинки (только что она PNG) и холостого хода (не хуже эталона).
Набор «inputs» — плохие входы и параметры: каждый обязан дать VentNestingError с понятным текстом, а не
трассировку и не «годную» программу.
"""
import sys, os, io, json, time, math, zipfile, argparse, contextlib, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from vent_nesting import api
from vent_nesting import lxds_reader as LR

GOLD = os.path.join(HERE, "golden")
DATA = os.path.join(HERE, "data")
Q3 = {"750x4000": 1, "1000x1200": 1}           # в ВЗ-00003.zip нет ведомости — количество задаётся явно


def zip_bytes(name):
    return open(os.path.join(DATA, name + ".zip"), "rb").read()


def snap_plan(p):
    d = {k: v for k, v in p.items() if k not in ("png", "dxf")}
    d["png"] = (p["png"] is not None and p["png"][:8] == b"\x89PNG\r\n\x1a\n" and len(p["png"]) > 10000) if p["png"] is not None else None
    d["dxf"] = sorted(p["dxf"]) if p["dxf"] is not None else None
    return d


def snap_lxds(files):
    out = []
    for f in files:
        with contextlib.redirect_stdout(io.StringIO()):
            r, _ = LR.build(f["bytes"], name=f["filename"], thickness=0.65, min_side=None)
        out.append({"filename": f["filename"], "key": f["key"], "ok": f["ok"], "layouts": f["layouts"],
                    "checks": [c[0] for c in f["checks"]], "failed": [c[0] for c in f["checks"] if not c[1]],
                    "parts": r["parts_total"], "sheets": r["sheets"], "plates_mm": [list(x) for x in r["plates_mm"]],
                    "pierces": r["totals"]["pierces"], "cut_m": r["totals"]["cut_m"], "idle_m": r["totals"]["idle_m"]})
    return out


def inputs_case():
    """Плохие входы: [(что, результат)] — результат «VentNestingError: …» или описание провала."""
    z2, z3 = zip_bytes("ВЗ-00002"), zip_bytes("ВЗ-00003")
    zf = zipfile.ZipFile(io.BytesIO(z3))
    dxf = {n: zf.read(n) for n in zf.namelist() if n.endswith(".dxf")}
    d750 = dxf["vsh_750x4000_t0.65_RAL8017.dxf"]; d1000 = [v for k, v in dxf.items() if k.startswith("vsh_1000x1200")][0]
    n1000 = [k for k in dxf if k.startswith("vsh_1000x1200")][0]
    o3 = api.order_from_zip(z3, qty=Q3)

    def mkzip(entries):
        b = io.BytesIO(); z = zipfile.ZipFile(b, "w")
        for n, d in entries:
            z.writestr(n, d)
        z.close(); return b.getvalue()
    cases = [
        ("пустые байты вместо zip", lambda: api.order_from_zip(b"")),
        ("мусор вместо zip", lambda: api.order_from_zip(b"PK\x03\x04garbage")),
        ("zip без DXF", lambda: api.order_from_zip(mkzip([("a.txt", "x")]))),
        ("DXF в подпапке", lambda: api.order_from_zip(mkzip([("папка/vsh_750x4000_t0.65_RAL8017.dxf", d750)]), qty={"750x4000": 1})),
        ("zip без ведомости и без qty", lambda: api.order_from_zip(z3)),
        ("имя DXF не генератора", lambda: api.order_from_dxf([("зонт.dxf", d750)], {"зонт.dxf": 1})),
        ("имя без толщины", lambda: api.order_from_dxf([("vsh_750x4000_RAL8017.dxf", d750)], {"750x4000": 1})),
        ("DXF дважды", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d750)] * 2, {"750x4000": 1})),
        ("qty 0", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d750)], {"750x4000": 0})),
        ("qty дробное", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d750)], {"750x4000": 2.5})),
        ("qty строкой", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d750)], {"750x4000": "2"})),
        ("qty неизвестный размер", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d750)], {"999x999": 1})),
        ("qty не на все DXF", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d750), (n1000, d1000)], {"750x4000": 1})),
        ("один размер в двух цветах, qty по размеру", lambda: api.order_from_dxf(
            [("vsh_750x4000_t0.65_RAL8017.dxf", d750), ("vsh_750x4000_t0.65_оц.dxf", d750)], {"750x4000": 1})),
        ("DXF обрезан на 75%", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d750[:len(d750) * 3 // 4])], {"750x4000": 1})),
        ("DXF обрезан на 97%", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d750[:len(d750) * 97 // 100])], {"750x4000": 1})),
        ("DXF другого размера под чужим именем", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", d1000)], {"750x4000": 1})),
        ("пустой DXF", lambda: api.order_from_dxf([("vsh_750x4000_t0.65_RAL8017.dxf", b"")], {"750x4000": 1})),
        ("зазор 0,4", lambda: api.plan(o3, gap=0.4, png=False)),
        ("зазор 51", lambda: api.plan(o3, gap=51, png=False)),
        ("зазор NaN", lambda: api.plan(o3, gap=float("nan"), png=False)),
        ("зазор строкой", lambda: api.plan(o3, gap="2", png=False)),
        ("отступ −1", lambda: api.plan(o3, edge=-1, png=False)),
        ("отступ 100 (деталь не лезет)", lambda: api.plan(o3, edge=100, png=False)),
        ("свес 124", lambda: api.plan(o3, sves=124, png=False)),
        ("свес 151", lambda: api.plan(o3, sves=151, png=False)),
        ("свес 1000", lambda: api.plan(o3, sves=1000, png=False)),
        ("свес NaN", lambda: api.plan(o3, sves=float("nan"), png=False)),
        ("вариант 'бухта'", lambda: api.build_lxds(o3, "бухта")),
        ("материал не из заказа", lambda: api.build_lxds(o3, "coil", material="ral9999|0.65")),
    ]
    out = []
    for what, fn in cases:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fn()
            out.append([what, "НЕТ ОШИБКИ"])
        except api.VentNestingError:
            out.append([what, "VentNestingError"])
        except Exception as e:
            out.append([what, "ДРУГАЯ ОШИБКА %s: %s" % (type(e).__name__, str(e)[:80])])
    # имя заказа со «/» и «..» — сборка идёт, имя файла очищено
    f = api.build_lxds(o3, "stock", material="оц|0.65", name="../ВЗ/2026/0001")
    out.append(["имя заказа со / и ..", f[0]["filename"]])
    return out


def order_case():
    o = api.order_from_zip(zip_bytes("ВЗ-00002"))
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes("ВЗ-00002")))
    files = [(n, zf.read(n)) for n in zf.namelist() if n.endswith(".dxf")]
    o2 = api.order_from_dxf(files, {h["dxf"]: h["qty"] for h in o.hoods()})
    # один размер в двух цветах: ведомость RAL ×1, оцинковка ×2 → каждому своё (раньше суммировалось в 3 и 3)
    import openpyxl
    z3 = zipfile.ZipFile(io.BytesIO(zip_bytes("ВЗ-00003")))
    d750 = z3.read("vsh_750x4000_t0.65_RAL8017.dxf")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Сборка"
    ws.append(["№", "Зонт", "Цвет", "Металл, мм", "Зонтов, шт", "Деталь", "Заготовка, мм", "Деталей на зонт"])
    ws.append([1, "вш 750х4000", "RAL 8017 Шоколад", 0.65, 1, "Крышка торцевая", "", 2])
    ws.append([None, None, None, None, None, "Панель", "", 4])
    ws.append([2, "вш 750х4000", "Оцинковка", 0.65, 2, "Крышка торцевая", "", 2])
    ws.append([None, None, None, None, None, "Панель", "", 4])
    xb = io.BytesIO(); wb.save(xb)
    b = io.BytesIO(); z = zipfile.ZipFile(b, "w")
    z.writestr("vsh_750x4000_t0.65_RAL8017.dxf", d750); z.writestr("vsh_750x4000_t0.65_оц.dxf", d750)
    z.writestr("X_сборка.xlsx", xb.getvalue()); z.close()
    o3 = api.order_from_zip(b.getvalue())
    return {"from_zip": o.hoods(), "from_dxf_same": o2.hoods() == o.hoods(),
            "two_colors_one_size": [(h["dxf"], h["qty"], h["parts_per_hood"]) for h in o3.hoods()]}


CASES = [   # (имя, быстрый?, функция)
    ("inputs", True, inputs_case),
    ("ВЗ-00002_order", True, order_case),
    ("ВЗ-00003_plan", True, lambda: snap_plan(api.plan(api.order_from_zip(zip_bytes("ВЗ-00003"), Q3), png=True, sheet_dxf=True))),
    ("ВЗ-00003_plan_gap10_edge10", True, lambda: snap_plan(api.plan(api.order_from_zip(zip_bytes("ВЗ-00003"), Q3), gap=10, edge=10, png=False))),
    ("ВЗ-00003_lxds_coil", True, lambda: snap_lxds(api.build_lxds(api.order_from_zip(zip_bytes("ВЗ-00003"), Q3), "coil", name="ВЗ-00003"))),
    ("ВЗ-00003_lxds_coil_gap10_edge10", True, lambda: snap_lxds(api.build_lxds(api.order_from_zip(zip_bytes("ВЗ-00003"), Q3), "coil", gap=10, edge=10, name="ВЗ-00003"))),
    ("ВЗ-00003_lxds_stock_оц", True, lambda: snap_lxds(api.build_lxds(api.order_from_zip(zip_bytes("ВЗ-00003"), Q3), "stock", material="оц|0.65", name="ВЗ-00003"))),
    ("ВЗ-00003_sves_table", True, lambda: api.sves_table(api.order_from_zip(zip_bytes("ВЗ-00003"), Q3), sves_list=(150, 140))),
    ("ВЗ-00002_plan", False, lambda: snap_plan(api.plan(api.order_from_zip(zip_bytes("ВЗ-00002")), png=False))),
    ("ВЗ-00002_plan_sves145", False, lambda: snap_plan(api.plan(api.order_from_zip(zip_bytes("ВЗ-00002")), sves=145, png=False))),
    ("ВЗ-00002_lxds_coil", False, lambda: snap_lxds(api.build_lxds(api.order_from_zip(zip_bytes("ВЗ-00002")), "coil", name="ВЗ-00002"))),
    ("ВЗ-00002_lxds_stock_sves145", False, lambda: snap_lxds(api.build_lxds(api.order_from_zip(zip_bytes("ВЗ-00002")), "stock", sves=145, name="ВЗ-00002"))),
]


def diff(a, b, path="", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append("%s.%s: %s" % (path, k, "нет в результате" if k not in a else "нет в эталоне"))
            else:
                diff(a[k], b[k], "%s.%s" % (path, k), out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, "%s[%d]" % (path, i), out)
    elif a != b:
        out.append("%s: получено %s, эталон %s" % (path, str(a)[:90], str(b)[:90]))
    return out


def compare(name, got, want):
    if name.endswith(("lxds_coil", "lxds_stock_оц", "lxds_coil_gap10_edge10", "lxds_stock_sves145")):
        errs = []
        for g, w in zip(got, want):
            if not g["ok"] or g["failed"]:
                errs.append("%s: не прошли самопроверки %s" % (g["filename"], g["failed"]))
            if g["idle_m"] > w["idle_m"] + 0.5:
                errs.append("%s: холостой ход %.1f м хуже эталона %.1f" % (g["filename"], g["idle_m"], w["idle_m"]))
            if abs(g["cut_m"] - w["cut_m"]) > 0.05:
                errs.append("%s: рез %.2f м вместо %.2f" % (g["filename"], g["cut_m"], w["cut_m"]))
        strip = lambda L: [{k: v for k, v in x.items() if k not in ("idle_m", "cut_m")} for x in L]
        return errs + diff(strip(got), strip(want))
    return diff(got, want)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regen", action="store_true")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    bad = n = 0
    for name, quick, fn in CASES:
        if a.quick and not quick:
            continue
        n += 1
        t = time.time()
        try:
            got = json.loads(json.dumps(fn(), ensure_ascii=False))
        except Exception:
            print("✗ %-34s УПАЛ\n%s" % (name, traceback.format_exc()[-800:])); bad += 1; continue
        gp = os.path.join(GOLD, name + ".json")
        if a.regen:
            json.dump(got, open(gp, "w"), ensure_ascii=False, indent=1)
            print("эталон записан: %s (%.0f с)" % (name, time.time() - t)); continue
        if not os.path.exists(gp):
            print("✗ %-34s нет эталона" % name); bad += 1; continue
        errs = compare(name, got, json.load(open(gp)))
        print("%s %-34s %5.0f с" % ("✓" if not errs else "✗", name, time.time() - t))
        for e in errs[:12]:
            print("    " + e)
        bad += bool(errs)
    if not a.regen:
        print("\nпроверок %d, с ошибками %d" % (n, bad))
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
