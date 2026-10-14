# -*- coding: utf-8 -*-
"""Сквозной тест: детали → раскрой → порядок резки → программа → 18 проверок.

    python3 tests/check_end2end.py [КАТАЛОГ_ОБРАЗЦОВ]     (по умолчанию ~/Downloads/vent_nesting/samples; нет — пропуск)

1) синтетика (всегда): DXF с прямоугольными деталями, отверстиями, прорезями и гравировкой (fixtures/dxf_writer) —
   программа собирается, все проверки ✓, количество и длины реза сходятся;
2) решётки 12.10 (если есть reshetki_bez_listov.lxds): 77 листов = нижней границе, холостой ход ≤ 510 м,
   0 переходов над вырезанными язычками, все проверки ✓;
3) детерминизм: два прогона — одинаковые раскрой, порядок резки и геометрия программы.
"""
import sys, os, io, zipfile, tempfile, hashlib, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
from sheet_nest.cli import run

SAMPLES = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/vent_nesting/samples")
fails = []


def check(name, cond, detail=""):
    print("%s %-60s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def geo_md5(raw):
    return hashlib.md5(zipfile.ZipFile(io.BytesIO(raw)).read("Geometry2D/data.bin")).hexdigest()


def synthetic_dxf(td):
    """Две детали DXF: пластина 600×400 с 4 отверстиями и пазом, 5 шт; решётка 500×300 с 3 прорезями и рисками, 7 шт."""
    import dxf_writer as DW
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    e = doc.entities
    e.lwpolyline([(0, 0), (600, 0), (600, 400), (0, 400)], closed=True)
    for x, y in ((50, 50), (550, 50), (550, 350), (50, 350)):
        e.circle((x, y), 9)
    e.lwpolyline([(250, 190, 0), (350, 190, 1), (350, 210, 0), (250, 210, 1)], closed=True)
    e.text((10, 10), "ПЛАСТИНА")
    p1 = os.path.join(td, "пластина_5шт.dxf"); open(p1, "wb").write(doc.dxf_bytes())
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    doc.layer("ГРАВИРОВКА")
    e = doc.entities
    e.lwpolyline([(0, 0), (500, 0), (500, 300), (0, 300)], closed=True)
    for k in range(3):
        y = 60 + 80 * k
        e.lwpolyline([(60, y + 30), (60, y), (440, y), (440, y + 30)], closed=False)
        e.line((5, y + 29), (40, y + 29), layer="ГРАВИРОВКА")
        e.line((460, y + 29), (495, y + 29), layer="ГРАВИРОВКА")
    p2 = os.path.join(td, "решётка_7шт.dxf"); open(p2, "wb").write(doc.dxf_bytes())
    return [p1, p2]


def main():
    with tempfile.TemporaryDirectory() as td:
        try:
            paths = synthetic_dxf(td)
        except Exception as e:
            paths = None
            check("синтетика: DXF-писатель фикстур", False, repr(e))
        if paths:
            log = []
            res, raw, pl, parts = run(paths, 1250, 2500, 2, 2, 2.0, None, "синтетика", None, log=log.append)
            check("синтетика: детали 2 вида, 12 шт", len(parts) == 2 and sum(p["qty"] for p in parts) == 12,
                  ", ".join("%s×%d" % (p["name"], p["qty"]) for p in parts))
            check("синтетика: все проверки программы", res["ok"], "; ".join(c[0] for c in res["checks"] if c[1] is False))
            check("синтетика: гравировка на слое 2", any(s["layer"] == 2 for p in parts for s in p["shapes"]))
            check("синтетика: прорези открытые на слое 1",
                  sum(1 for p in parts for s in p["shapes"] if s["kind"] == "LwPolyline" and not s["flag"] & 1 and s["layer"] == 1) == 3)
            check("синтетика: переходов над язычками 0", res["crossings"]["tongues"] == 0, str(res["crossings"]))
    gr = os.path.join(SAMPLES, "reshetki_bez_listov.lxds")
    if os.path.exists(gr):
        log = []
        res, raw, pl, parts = run([gr], 1250, 2500, 2, 2, 1.5, None, "решётки", None, log=log.append)
        check("решётки: 77 листов = нижняя граница", res["sheets"] == 77 and res["lower_bound"] == 77 and res["optimal"],
              "%d листов, граница %d, %s" % (res["sheets"], res["lower_bound"], res["method"]))
        check("решётки: холостой ход ≤ 510 м", res["idle_m"] <= 510, "%.1f м" % res["idle_m"])
        check("решётки: переходов над язычками 0", res["crossings"]["tongues"] == 0, str(res["crossings"]))
        check("решётки: все проверки программы", res["ok"], "; ".join(c[0] for c in res["checks"] if c[1] is False))
        res2, raw2, *_ = run([gr], 1250, 2500, 2, 2, 1.5, None, "решётки", None, log=lambda *_: None)
        check("решётки: повторный прогон — та же геометрия программы", geo_md5(raw) == geo_md5(raw2) and res2["idle_m"] == res["idle_m"])
    else:
        print("— решётки: нет %s, пропуск" % gr)
    print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
