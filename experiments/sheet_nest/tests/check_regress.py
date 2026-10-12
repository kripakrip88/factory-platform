# -*- coding: utf-8 -*-
"""Регрессии, найденные 12–13.10.2026 (каждая была ошибкой — больше не должна вернуться).

    python3 tests/check_regress.py
"""
import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
from sheet_nest import geom as G
from sheet_nest.pack_rect import pack_rect
from sheet_nest.read_dxf import qty_from_filename, parts_from_dxf, DxfError
import dxf_writer as DW

fails = []


def check(name, cond, detail=""):
    print("%s %-66s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


# 1) шайбы m14: ширина не кратна 0,001 мм — полоса округлялась вниз, деталь вверх → по одной шайбе в полосе, 13 листов
r = pack_rect([dict(id=0, w=104.99375330565526, h=104.99375330565526, qty=704)], 1500, 6000, 2, 2)
check("704 шайбы 104,99 мм на 1500×6000 — 1 лист (было 13)", len(r["sheets"]) == 1, "%d листов" % len(r["sheets"]))
r = pack_rect([dict(id=0, w=300.000002, h=200.000002, qty=100)], 1250, 2500, 2, 2, rotations=(0,))
check("100 деталей 300,000002×200,000002 — 3 листа (было 9)", len(r["sheets"]) == 3, "%d листов" % len(r["sheets"]))

# 2) габарит окружности — по радиусу, не по хордам (было 104,994 вместо 105 → детали ближе зазора)
b = G.bbox([dict(kind="Circle", c=(0, 0), r=52.5, a0=0.7)])
check("габарит окружности = диаметр", abs((b[2] - b[0]) - 105.0) < 1e-9, "%.6f" % (b[2] - b[0]))
b = G.bbox([dict(kind="LwPolyline", verts=[(10, 0, 1.0), (-10, 0, 1.0)], flag=1)])      # окружность из двух дуг
check("габарит дуг полилинии = точный", all(abs(v - w) < 1e-9 for v, w in zip(b, (-10, -10, 10, 10))), str(tuple(round(v, 6) for v in b)))

# 3) количество из имени: «(1)» браузера не перебивает «12шт»
check("«Фланец_12шт (1).dxf» → 12", qty_from_filename("Фланец_12шт (1).dxf")[0] == 12)
check("«Фланец x12 (3).dxf» → 12", qty_from_filename("Фланец x12 (3).dxf")[0] == 12)
check("«Фланец (12).dxf» → 12", qty_from_filename("Фланец (12).dxf")[0] == 12)
check("«Лист 1500 х 3000.dxf» → нет количества", qty_from_filename("Лист 1500 х 3000.dxf")[0] is None)


def dxf(build):
    d = DW.DxfDoc(); build(d); return d.dxf_bytes()


def err(build):
    try:
        parts_from_dxf(dxf(build), "x.dxf", 1)
        return None
    except DxfError as e:
        return str(e)


# 4) пересечения контуров ловятся по линиям, а не только по вершинам
e = err(lambda d: (d.entities.lwpolyline([(-50, -5), (50, -5), (50, 5), (-50, 5)], closed=True),
                   d.entities.lwpolyline([(-5, -50), (5, -50), (5, 50), (-5, 50)], closed=True)))
check("крест из двух прямоугольников — ошибка «пересекаются»", e is not None and "пересекаются" in e, (e or "")[:60])
e = err(lambda d: (d.entities.lwpolyline([(0, 0), (100, 0), (100, 40), (40, 40), (40, 100), (0, 100)], closed=True),
                   d.entities.circle((38, 38), 6)))
check("отверстие на внутреннем углу Г — ошибка", e is not None and "пересекает" in e, (e or "")[:60])
e = err(lambda d: (d.entities.lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], closed=True), d.entities.line((50, 0), (50, 50))))
check("рез от кромки до кромки — ошибка", e is not None and "от кромки до кромки" in e, (e or "")[:60])
e = err(lambda d: (d.entities.lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], closed=True),
                   d.entities.lwpolyline([(200, 0), (300, 0), (300, 50), (200, 50)], closed=True)))
check("две детали рядом — не ошибка", e is None, e or "")

# 5) штриховая линия на слое гравировки — гравировка (линия сгиба нарочно), не выбрасывается
ps = parts_from_dxf(dxf(lambda d: (d.ltype("DASHED", [5, -2.5]), d.layer("Гравировка", ltype="DASHED"),
                                   d.entities.lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], closed=True),
                                   d.entities.line((50, 1), (50, 99), layer="Гравировка"))), "x.dxf", 1)
check("штриховая на «Гравировка» — осталась гравировкой", sum(1 for s in ps[0]["shapes"] if s["layer"] == 2) == 1)

print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
sys.exit(1 if fails else 0)
