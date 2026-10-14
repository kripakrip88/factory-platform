# -*- coding: utf-8 -*-
"""Проверка read_dxf: python3 tests/check_read_dxf.py (код выхода 0 — всё прошло).

Фикстуры DXF пишутся тут же писателем tests/fixtures/dxf_writer.py; дымовая проверка — DXF генератора зонтов из
../odoo/addons/pmk_vent_nest/lib/tests/data/*.zip (сверка с разбором пакета vn.dxfread / vn.parts).
"""
import glob
import math
import os
import sys
import tempfile
import traceback
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "fixtures"))

import numpy as np                                    # noqa: E402

from sheet_nest.libpath import vn, LIB                # noqa: E402
from sheet_nest.read_dxf import (parts_from_dxf, DxfError, is_engrave_layer, qty_from_filename,  # noqa: E402
                                 ENGRAVE_LAYERS)
from dxf_writer import DxfDoc, u_escape               # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# =====================================================================================  помощники
def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


def pclose(p, q, tol=1e-6):
    return math.hypot(p[0] - q[0], p[1] - q[1]) <= tol


def check_attrs(s, outer=0):
    assert s["handle"] is None and s["layer_name"] == "0" and s["coedge"] == 0 and s["flag64"] == 0, s
    assert s["lead"] is None and s["outer"] == outer and s["layer"] in (1, 2), s
    assert s["kind"] in ("Line", "Circle", "LwPolyline"), s
    if s["kind"] == "LwPolyline":
        assert s["sp"] == 0.0 and s["flag"] in (0, 1), s
        assert all(len(v) == 3 for v in s["verts"])
    if s["kind"] == "Circle":
        assert close(s["a0"], math.pi / 4, 1e-15)


def check_part(p):
    """Общий контракт детали: внешний последним, атрибуты, сдвиг в (0, 0)."""
    assert set(p) == {"name", "qty", "shapes", "src", "warnings"}, p.keys()
    assert isinstance(p["qty"], int) and p["qty"] >= 1
    assert not any(ch in p["name"] for ch in "&<>\"'"), p["name"]
    sh = p["shapes"]
    assert sh and sh[-1]["outer"] == 1 and sh[-1]["layer"] == 1, sh[-1]
    assert sum(s["outer"] for s in sh) == 1
    for s in sh[:-1]:
        check_attrs(s, 0)
    check_attrs(sh[-1], 1)
    o = sh[-1]
    if o["kind"] == "LwPolyline":
        assert o["flag"] == 1 and vn.spec_rebuild.poly_area(o["verts"]) > 0, "внешний — против часовой"
        bb = sampled_bbox(o["verts"], True)
        assert close(bb[0], 0.0, 1e-3) and close(bb[1], 0.0, 1e-3), bb
    else:
        assert o["kind"] == "Circle" and pclose((o["c"][0] - o["r"], o["c"][1] - o["r"]), (0, 0), 1e-9)
    for s in sh[:-1]:
        if s["kind"] == "LwPolyline" and s["flag"] == 1:
            assert vn.spec_rebuild.poly_area(s["verts"]) < 0, "внутренний замкнутый — по часовой"
    return o


def arc_info(p0, p1, b):
    """Центр, радиус, середина дуги bulge — по разбору ПАКЕТА (независимо от read_dxf)."""
    c, r, pm = vn.dxfread.bulge_arc(list(p0), list(p1), b)
    return c, r, pm


def poly_points(verts, closed, step=0.05):
    """Плотные точки полилинии с дугами (для проверок)."""
    out = []
    n = len(verts)
    for k in range(n if closed else n - 1):
        x0, y0, b = verts[k]
        x1, y1, _ = verts[(k + 1) % n]
        if not b:
            m = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
            out += [(x0 + (x1 - x0) * j / m, y0 + (y1 - y0) * j / m) for j in range(m)]
        else:
            c, r, pm = arc_info((x0, y0), (x1, y1), b)
            th = 4 * math.atan(b)
            a0 = math.atan2(y0 - c[1], x0 - c[0])
            m = max(4, int(abs(th) * r / step))
            out += [(c[0] + r * math.cos(a0 + th * j / m), c[1] + r * math.sin(a0 + th * j / m)) for j in range(m)]
    if not closed:
        out.append(tuple(verts[-1][:2]))
    return out


def sampled_bbox(verts, closed):
    P = np.array(poly_points(verts, closed, step=0.01))
    return (P[:, 0].min(), P[:, 1].min(), P[:, 0].max(), P[:, 1].max())


def seg_dist(points, verts, closed):
    """Для каждой точки — расстояние до ломаной (вершины verts, bulge не учитывается — для приближённых кривых)."""
    V = np.array([v[:2] for v in verts] + ([verts[0][:2]] if closed else []), dtype=float)
    A, B = V[:-1], V[1:]
    D = B - A
    L2 = (D ** 2).sum(1)
    L2[L2 == 0] = 1e-30
    P = np.array(points, dtype=float)
    out = np.empty(len(P))
    for i in range(0, len(P), 2000):
        Q = P[i:i + 2000, None, :]
        t = np.clip(((Q - A) * D).sum(2) / L2, 0, 1)
        X = A + t[..., None] * D
        out[i:i + 2000] = np.sqrt(((X - Q) ** 2).sum(2)).min(1)
    return out


def bezier(P, t):
    t = np.asarray(t)[:, None]
    P = np.array(P, dtype=float)
    return ((1 - t) ** 3 * P[0] + 3 * (1 - t) ** 2 * t * P[1] + 3 * (1 - t) * t ** 2 * P[2] + t ** 3 * P[3])


def cox_de_boor(P, K, p, ts):
    """Независимая оценка B-сплайна через базисные функции (рекурсия Кокса — де Бура)."""
    P = np.array(P, dtype=float)
    n = len(P)

    def N(i, k, t):
        if k == 0:
            last = (t == K[-1]) and K[i] < K[i + 1] and K[i + 1] == K[-1]
            return 1.0 if (K[i] <= t < K[i + 1]) or last else 0.0
        a = 0.0 if K[i + k] == K[i] else (t - K[i]) / (K[i + k] - K[i]) * N(i, k - 1, t)
        b = 0.0 if K[i + k + 1] == K[i + 1] else (K[i + k + 1] - t) / (K[i + k + 1] - K[i + 1]) * N(i + 1, k - 1, t)
        return a + b
    return np.array([sum(N(i, p, t) * P[i] for i in range(n)) for t in ts])


def rect(e, x0, y0, x1, y1, layer="0"):
    e.line((x0, y0), (x1, y0), layer).line((x1, y0), (x1, y1), layer)
    e.line((x1, y1), (x0, y1), layer).line((x0, y0), (x0, y1), layer)       # последний — задом наперёд


def kinds(shapes):
    return sorted((s["kind"], s["layer"], s.get("flag", -1)) for s in shapes)


def expect_error(data, name, *needles):
    try:
        parts_from_dxf(data, name)
    except DxfError as ex:
        msg = str(ex)
        for nd in needles:
            assert nd in msg, "нет «%s» в сообщении: %s" % (nd, msg)
        return msg
    raise AssertionError("ожидалась DxfError")


def mat(rot_deg=0.0, sx=1.0, sy=1.0, at=(0, 0), base=(0, 0)):
    a = math.radians(rot_deg)
    c, s = math.cos(a), math.sin(a)

    def f(p):
        x, y = (p[0] - base[0]) * sx, (p[1] - base[1]) * sy
        return (at[0] + c * x - s * y, at[1] + s * x + c * y)
    return f


# =====================================================================================  тесты
@test
def t01_rect_holes_slot_line_arc():
    d = DxfDoc()
    e = d.entities
    rect(e, 50, 30, 250, 130)
    e.circle((80, 80), 5).circle((220, 80), 5)
    e.line((130, 74), (170, 74)).line((170, 86), (130, 86))
    e.arc((170, 80), 6, -90, 90).arc((130, 80), 6, 90, 270)
    e.point((10, 10))
    parts = parts_from_dxf(d.dxf_bytes(), "Пластина_3шт.dxf")
    assert len(parts) == 1
    p = parts[0]
    o = check_part(p)
    assert p["name"] == "Пластина" and p["qty"] == 3 and p["src"] == "Пластина_3шт.dxf"
    assert o["kind"] == "LwPolyline" and len(o["verts"]) == 4
    assert close(vn.spec_rebuild.poly_area(o["verts"]), 20000.0, 1e-9)
    assert sorted((v[0], v[1]) for v in o["verts"]) == [(0, 0), (0, 100), (200, 0), (200, 100)]
    circ = sorted([s for s in p["shapes"] if s["kind"] == "Circle"], key=lambda s: s["c"])
    assert [s["c"] for s in circ] == [(30.0, 50.0), (170.0, 50.0)] and all(s["r"] == 5 for s in circ)
    slot = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and not s["outer"]]
    assert len(slot) == 1 and slot[0]["flag"] == 1 and len(slot[0]["verts"]) == 4
    bs = sorted(v[2] for v in slot[0]["verts"])
    assert bs == [-1.0, -1.0, 0.0, 0.0], bs                 # точные полуокружности (ARC 180° → bulge ровно 1)
    assert close(vn.spec_rebuild.poly_area(slot[0]["verts"]), -(40 * 12 + math.pi * 36), 1e-9)
    assert not any("POINT" in w for w in p["warnings"])


@test
def t02_lwpolyline_bulges_same_part():
    tb = math.tan(math.pi / 8)
    ccw = [(10, 0, 0), (190, 0, tb), (200, 10, 0), (200, 90, tb), (190, 100, 0), (10, 100, tb), (0, 90, 0), (0, 10, tb)]
    # то же в обратную сторону (по часовой), со сдвигом (1000, -500)
    n = len(ccw)
    cw = [(ccw[(n - i) % n][0] + 1000, ccw[(n - i) % n][1] - 500, -ccw[(n - i - 1) % n][2]) for i in range(n)]
    d = DxfDoc()
    e = d.entities
    e.lwpolyline(cw, closed=True, width=0.5)
    e.lwpolyline([(1130, -426, 0), (1170, -426, 1), (1170, -414, 0), (1130, -414, 1)], closed=True)   # паз против часовой
    e.circle((1030, -450), 5).circle((1170, -450), 5)
    p = parts_from_dxf(d.dxf_bytes(), "Пластина.dxf", qty=2)[0]
    o = check_part(p)
    assert p["qty"] == 2 and p["name"] == "Пластина"
    assert close(vn.spec_rebuild.poly_area(o["verts"]), 20000 - (4 - math.pi) * 100, 1e-9)
    assert len(o["verts"]) == 8 and sum(1 for v in o["verts"] if close(v[2], tb, 1e-15)) == 4   # дуги — точные bulge
    bb = sampled_bbox(o["verts"], True)
    assert close(bb[2], 200, 1e-3) and close(bb[3], 100, 1e-3)
    slot = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and not s["outer"]][0]
    assert sorted(v[2] for v in slot["verts"]) == [-1.0, -1.0, 0.0, 0.0]
    assert close(vn.spec_rebuild.poly_area(slot["verts"]), -(480 + math.pi * 36), 1e-9)
    assert sorted(s["c"] for s in p["shapes"] if s["kind"] == "Circle") == [(30.0, 50.0), (170.0, 50.0)]
    assert not any("количество не указано" in w for w in p["warnings"])


@test
def t03_r12_polyline_vertex_crlf_padded():
    d = DxfDoc(version="AC1009", insunits=None)
    e = d.entities
    e.polyline([(0, 0), (120, 0), (120, 60, 1.0), (120, 80), (0, 80)], closed=True)   # полукруг-выступ справа
    e.polyline([(30, 40, 1.0), (50, 40, 1.0)], closed=True)                          # окружность из 2 дуг → Circle
    e.polyline([(70, 20), (70, 50), (90, 50)], closed=False)                         # открытый рез
    data = d.dxf_bytes(crlf=True, pad=True)
    assert b"\r\n  0\r\nPOLYLINE" in data
    p = parts_from_dxf(data, "r12.dxf")[0]
    o = check_part(p)
    area = 120 * 80 + math.pi * 10 * 10 / 2
    assert close(vn.spec_rebuild.poly_area(o["verts"]), area, 1e-9)
    bb = sampled_bbox(o["verts"], True)
    assert close(bb[2], 130, 1e-3), bb
    c = [s for s in p["shapes"] if s["kind"] == "Circle"]
    assert len(c) == 1 and pclose(c[0]["c"], (40, 40), 1e-9) and close(c[0]["r"], 10, 1e-9)
    op = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and s["flag"] == 0]
    assert len(op) == 1 and op[0]["layer"] == 1 and len(op[0]["verts"]) == 3
    assert any("$INSUNITS" in w for w in p["warnings"])


@test
def t04_nested_insert_rotation_scale_mirror():
    d = DxfDoc()
    hole = d.block("HOLE", base=(0, 0))
    hole.circle((0, 0), 3)
    hole.lwpolyline([(8, 0, math.tan(math.pi / 8)), (0, 8, 0)])        # открытая четверть окружности против часовой
    hole.arc((0, 0), 12, 180, 270)                                       # открытая дуга
    plate = d.block("PLATE", base=(10, 10))
    plate.lwpolyline([(10, 10), (210, 10), (210, 110), (10, 110)], closed=True)
    plate.insert("HOLE", (60, 60), sx=2, sy=2, rot=30)
    plate.insert("HOLE", (160, 60), sx=-1, sy=1, rot=30)                 # зеркало
    d.entities.insert("PLATE", (500, 300), sx=-1, sy=1)                  # зеркало всей детали
    p = parts_from_dxf(d.dxf_bytes(), "insert.dxf")[0]
    o = check_part(p)
    assert close(vn.spec_rebuild.poly_area(o["verts"]), 20000, 1e-9)
    main = mat(sx=-1, at=(500, 300), base=(10, 10))
    h1, h2 = mat(30, 2, 2, at=(60, 60)), mat(30, -1, 1, at=(160, 60))
    off = (300.0, 300.0)

    def W(f, q):
        x, y = main(f(q))
        return (x - off[0], y - off[1])
    circ = sorted([s for s in p["shapes"] if s["kind"] == "Circle"], key=lambda s: -s["r"])
    assert len(circ) == 2
    assert pclose(circ[0]["c"], W(h1, (0, 0))) and close(circ[0]["r"], 6)
    assert pclose(circ[1]["c"], W(h2, (0, 0))) and close(circ[1]["r"], 3)
    opens = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and s["flag"] == 0]
    assert len(opens) == 4
    s45 = math.sqrt(0.5)
    expect = [(h1, (8, 0), (0, 8), (8 * s45, 8 * s45)), (h1, (-12, 0), (0, -12), (-12 * s45, -12 * s45)),
              (h2, (8, 0), (0, 8), (8 * s45, 8 * s45)), (h2, (-12, 0), (0, -12), (-12 * s45, -12 * s45))]
    for f, a, b, m in expect:
        A, B, Mid = W(f, a), W(f, b), W(f, m)
        hit = [s for s in opens if {tuple(round(x, 6) for x in s["verts"][0][:2]), tuple(round(x, 6) for x in s["verts"][1][:2])}
               == {tuple(round(x, 6) for x in A), tuple(round(x, 6) for x in B)}]
        assert len(hit) == 1, (A, B)
        v = hit[0]["verts"]
        assert len(v) == 2 and close(abs(v[0][2]), math.tan(math.pi / 8), 1e-12)
        _, _, pm = arc_info(v[0][:2], v[1][:2], v[0][2])
        assert pclose(pm, Mid, 1e-6), (pm, Mid)                           # знак bulge верен после зеркал


@test
def t05_spline_bezier_outer():
    P = [(0, 0), (30, 60), (70, 60), (100, 0)]
    d = DxfDoc()
    d.entities.spline(P, [0, 0, 0, 0, 1, 1, 1, 1], degree=3)
    d.entities.line((100, 0), (0, 0))
    p = parts_from_dxf(d.dxf_bytes(), "spline.dxf")[0]
    o = check_part(p)
    assert any("SPLINE" in w and "0,01" in w for w in p["warnings"]), p["warnings"]
    curve = bezier(P, np.linspace(0, 1, 40001))
    ymin = curve[:, 1].min()
    dev = seg_dist(curve - [0, ymin], o["verts"], True)
    assert dev.max() <= 0.01, dev.max()
    # вершины лежат на кривой
    vd = seg_dist([v[:2] for v in o["verts"]], [(x, y - ymin, 0) for x, y in curve[::1]], False)
    assert vd.max() <= 1e-3, vd.max()
    assert len(o["verts"]) < 400


@test
def t06_spline_multispan_and_rational():
    P = [(0, 0), (20, 40), (50, -10), (80, 50), (110, 0), (140, 30)]
    K = [0, 0, 0, 0, 1, 2, 3, 3, 3, 3]
    d = DxfDoc()
    d.entities.spline(P, K, degree=3)
    d.entities.line((140, 30), (140, -40)).line((140, -40), (0, -40)).line((0, -40), (0, 0))
    w = math.sqrt(0.5)
    d.entities.spline([(250, 0), (250, 50), (200, 50)], [0, 0, 0, 1, 1, 1], degree=2, weights=[1, w, 1])
    d.entities.line((200, 50), (200, 0)).line((200, 0), (250, 0))
    parts = parts_from_dxf(d.dxf_bytes(), "spl2.dxf")
    assert len(parts) == 2 and [p["name"] for p in parts] == ["spl2 #1", "spl2 #2"]
    a, b = check_part(parts[0]), check_part(parts[1])
    ts = np.linspace(0, 3, 6001)
    curve = cox_de_boor(P, K, 3, ts)
    dev = seg_dist(curve - [0, -40], a["verts"], True)
    assert dev.max() <= 0.01, dev.max()
    # рациональная четверть окружности R50 с центром (200, 0) → после сдвига (0, 0): вершины на окружности,
    # стрелка ≤ 0,01
    on_arc = [v for v in b["verts"] if not (close(v[0], 0) and close(v[1], 0))]
    rr = [math.hypot(v[0], v[1]) for v in on_arc]
    assert max(abs(r - 50) for r in rr) < 1e-9, max(abs(r - 50) for r in rr)
    ang = np.linspace(0, math.pi / 2, 20001)
    dev = seg_dist(np.c_[50 * np.cos(ang), 50 * np.sin(ang)], b["verts"], True)
    assert dev.max() <= 0.01, dev.max()


@test
def t07_spline_closed_periodic_and_fit_points():
    # периодический замкнутый кубический сплайн: AutoCAD-вид (первые 3 точки повторены) и без повтора (флаг closed)
    Q = [(0, 0), (60, -10), (100, 30), (70, 80), (10, 70), (-20, 30)]
    p = 3
    wrapped = Q + Q[:p]
    K = list(range(len(wrapped) + p + 1))
    for ctrl in (wrapped, Q):
        K = list(range(len(ctrl) + p + 1))
        d = DxfDoc()
        rect(d.entities, -100, -100, 200, 200)                     # габарит задаёт прямоугольник: сдвиг (100, 100)
        d.entities.spline(ctrl, K, degree=3, closed=True, periodic=True)
        part = parts_from_dxf(d.dxf_bytes(), "per.dxf")[0]
        check_part(part)
        hole = [s for s in part["shapes"] if not s["outer"]]
        assert len(hole) == 1 and hole[0]["kind"] == "LwPolyline" and hole[0]["flag"] == 1
        ts = np.linspace(p, len(wrapped), 8001)
        Kw = list(range(len(wrapped) + p + 1))
        curve = cox_de_boor(wrapped, Kw, p, ts)
        dev = seg_dist(curve + 100, hole[0]["verts"], True)
        assert dev.max() <= 0.01, dev.max()
    # сплайн только по опорным точкам: проходит через точки
    F = [(0, 0), (30, 25), (60, 10), (90, 40)]
    d = DxfDoc()
    d.entities.spline([], [], degree=3, fit=F)
    d.entities.line((90, 40), (90, -20)).line((90, -20), (0, -20)).line((0, -20), (0, 0))
    part = parts_from_dxf(d.dxf_bytes(), "fit.dxf")[0]
    o = check_part(part)
    vv = [(v[0], v[1] - 20) for v in o["verts"]]
    for q in F:
        assert min(math.hypot(q[0] - x, q[1] - y) for x, y in vv) < 1e-9, q
    assert any("опорным точкам" in w for w in part["warnings"])


@test
def t08_ellipse_hole_full_and_partial():
    d = DxfDoc()
    e = d.entities
    rect(e, 0, 0, 200, 100)
    e.ellipse((100, 50), (40, 0), 0.5)                                         # полный эллипс — отверстие
    e.ellipse((40, 30), (10, 0), 0.6, 0.0, math.pi / 2, layer="Гравировка")   # дуга эллипса — гравировка
    e.ellipse((160, 30), (10, 0), 0.6, 0.0, math.pi / 2, layer="Гравировка", extrusion=(0, 0, -1))
    e.ellipse((40, 75), (0, 8), 1.0)                                           # оси равны → точная окружность
    p = parts_from_dxf(d.dxf_bytes(), "ell.dxf")[0]
    check_part(p)
    hole = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and s["layer"] == 1 and not s["outer"]]
    assert len(hole) == 1 and hole[0]["flag"] == 1
    v = hole[0]["verts"]
    assert max(abs(((x - 100) / 40) ** 2 + ((y - 50) / 20) ** 2 - 1) for x, y, b in v) < 1e-9
    a = vn.spec_rebuild.poly_area(v)
    assert a < 0 and math.pi * 800 - 3 < -a < math.pi * 800, a
    t = np.linspace(0, 2 * math.pi, 40001)
    dev = seg_dist(np.c_[100 + 40 * np.cos(t), 50 + 20 * np.sin(t)], v, True)
    assert dev.max() <= 0.01, dev.max()
    eng = [s for s in p["shapes"] if s["layer"] == 2]
    assert len(eng) == 2 and all(s["kind"] == "LwPolyline" and s["flag"] == 0 for s in eng)
    ends = sorted(tuple(sorted([tuple(round(x, 9) for x in s["verts"][0][:2]), tuple(round(x, 9) for x in s["verts"][-1][:2])]))
                  for s in eng)
    assert ends == sorted([tuple(sorted([(50.0, 30.0), (40.0, 36.0)])), tuple(sorted([(170.0, 30.0), (160.0, 24.0)]))]), ends
    circ = [s for s in p["shapes"] if s["kind"] == "Circle"]
    assert len(circ) == 1 and pclose(circ[0]["c"], (40, 75)) and close(circ[0]["r"], 8)
    assert any("ELLIPSE" in w for w in p["warnings"])


@test
def t09_engrave_layers_escapes_cp1251_utf8():
    def doc(version, layer_name, codepage=None, table=False):
        d = DxfDoc(version=version, codepage=codepage)
        if table:
            d.layer(layer_name)
        e = d.entities
        rect(e, 0, 0, 200, 100)
        e.line((90, 60), (100, 60), layer=layer_name).line((100, 60), (110, 60), layer=layer_name)
        e.line((100, 60), (100, 40), layer=layer_name)                       # «Т» — ветвление на гравировке
        e.lwpolyline([(20, 20), (60, 20), (60, 40), (20, 40)], closed=True, layer=layer_name)
        return d
    cases = [
        ("\\U+ в AC1015", doc("AC1015", u_escape("Гравировка")).dxf_bytes("ascii")),
        ("cp1251 в AC1015", doc("AC1015", "Гравировка", "ANSI_1251", table=True).dxf_bytes("cp1251", crlf=True)),
        ("cp1251 в R12", doc("AC1009", "ГРАВИРОВКА", "ANSI_1251").dxf_bytes("cp1251")),
        ("UTF-8 в AC1021", doc("AC1021", "Маркировка", "ANSI_1251").dxf_bytes("utf-8")),
        ("engrave_text", doc("AC1015", "engrave_text").dxf_bytes()),
    ]
    assert b"\\U+0413" in cases[0][1] and "Гравировка".encode("cp1251") in cases[1][1]
    for label, data in cases:
        p = parts_from_dxf(data, "eng.dxf")[0]
        check_part(p)
        eng = [s for s in p["shapes"] if s["layer"] == 2]
        assert kinds(eng) == [("Line", 2, -1)] * 3 + [("LwPolyline", 2, 1)], (label, kinds(eng))
        assert all(s["layer"] == 1 for s in p["shapes"] if s not in eng)
    # свой список слоёв: «Гравировка» становится резом → «Т» ветвится на резе → ошибка с координатами
    msg = None
    try:
        parts_from_dxf(cases[0][1], "eng.dxf", engrave_layers=["Метки"])
    except DxfError as ex:
        msg = str(ex)
    assert msg and "ветвится" in msg and "(100; 60)" in msg, msg
    # is_engrave_layer
    for nm in ENGRAVE_LAYERS + ["гравировка", "Grav", "mark", "Маркировка", "Слой гравировки 2", "ENGRAVING", "  Гравировка "]:
        assert is_engrave_layer(nm), nm
    for nm in ["0", "Контур", "MARKING", "CUT", "", None]:
        assert not is_engrave_layer(nm), nm
    assert is_engrave_layer("Метки", ["метки"]) and not is_engrave_layer("Гравировка", ["метки"])


@test
def t10_text_dimension_ignored():
    d = DxfDoc()
    dim = d.block("*D1", flags=1)
    dim.line((-50, -50), (-40, -50)).line((-40, -50), (-40, -40))            # линии размера вне детали
    e = d.entities
    rect(e, 0, 0, 100, 50)
    e.text((10, 10), "Деталь 1").text((10, 20), "t=2").mtext((10, 30), "M")
    e.dimension("*D1").hatch()
    e.insert("*D1", (0, 0))
    e.circle((300, 300), 5, paper=True)                                      # пространство листа
    e.line((0, 25), (100, 25), ltype="CENTER")                               # осевая
    p = parts_from_dxf(d.dxf_bytes(), "txt.dxf")[0]
    o = check_part(p)
    assert len(p["shapes"]) == 1 and len(o["verts"]) == 4
    W = p["warnings"]
    for needle in ("TEXT ×2", "MTEXT ×1", "DIMENSION ×1", "HATCH ×1", "CENTER", "пространства листа"):
        assert sum(needle in w for w in W) == 1, (needle, W)
    assert not any("*D1" in w for w in W)


@test
def t11_inches_and_other_units():
    d = DxfDoc(insunits=1)
    rect(d.entities, 0, 0, 2, 1)
    d.entities.circle((1, 0.5), 0.25)
    p = parts_from_dxf(d.dxf_bytes(), "inch.dxf")[0]
    o = check_part(p)
    xs = sorted(set(v[0] for v in o["verts"]))
    ys = sorted(set(v[1] for v in o["verts"]))
    assert xs == [0.0, 50.8] and ys == [0.0, 25.4], (xs, ys)
    c = [s for s in p["shapes"] if s["kind"] == "Circle"][0]
    assert pclose(c["c"], (25.4, 12.7)) and close(c["r"], 6.35)
    assert any("дюймы" in w for w in p["warnings"])
    for u, k in ((5, 10.0), (6, 1000.0), (4, 1.0), (0, 1.0)):
        d = DxfDoc(insunits=u)
        rect(d.entities, 0, 0, 2, 1)
        o = check_part(parts_from_dxf(d.dxf_bytes(), "u.dxf")[0])
        assert close(max(v[0] for v in o["verts"]), 2 * k), (u, o["verts"])


@test
def t12_two_parts_and_part_in_hole():
    d = DxfDoc()
    e = d.entities
    rect(e, 200, 0, 260, 80)
    e.circle((230, 40), 6)
    e.line((215, 10), (245, 10), layer="Гравировка")
    rect(e, 0, 0, 100, 50)
    e.circle((20, 25), 4)
    parts = parts_from_dxf(d.dxf_bytes(), "Две детали x5.dxf")
    assert [p["name"] for p in parts] == ["Две детали #1", "Две детали #2"], [p["name"] for p in parts]
    assert all(p["qty"] == 5 for p in parts)
    a, b = parts
    check_part(a)
    check_part(b)
    assert kinds(a["shapes"][:-1]) == [("Circle", 1, -1)] and pclose(a["shapes"][0]["c"], (20, 25))
    assert kinds(b["shapes"][:-1]) == [("Circle", 1, -1), ("Line", 2, -1)]
    assert pclose([s for s in b["shapes"] if s["kind"] == "Circle"][0]["c"], (30, 40))
    # кольцо и диск в его отверстии: по договорённости диск — внутренний рез кольца, с предупреждением
    d = DxfDoc()
    d.entities.circle((0, 0), 100).circle((0, 0), 80).circle((0, 0), 50)
    parts = parts_from_dxf(d.dxf_bytes(), "ring.dxf")
    assert len(parts) == 1
    o = check_part(parts[0])
    assert o["kind"] == "Circle" and close(o["r"], 100) and pclose(o["c"], (100, 100))
    assert sorted(s["r"] for s in parts[0]["shapes"][:-1]) == [50, 80]
    assert sum("контуров внутри отверстий: 1 " in w for w in parts[0]["warnings"]) == 1, parts[0]["warnings"]


@test
def t13_open_cut_slits():
    d = DxfDoc()
    e = d.entities
    rect(e, 0, 0, 200, 100)
    for k in range(3):
        y = 20 + 25 * k
        e.lwpolyline([(20, y), (20, y + 15), (80, y + 15), (80, y)])          # U-прорезь (жалюзи)
    e.line((120, 20), (180, 20))                                              # прямой прорез
    p = parts_from_dxf(d.dxf_bytes(), "louver.dxf")[0]
    check_part(p)
    inner = p["shapes"][:-1]
    assert kinds(inner) == [("Line", 1, -1)] + [("LwPolyline", 1, 0)] * 3, kinds(inner)
    for s in inner:
        if s["kind"] == "LwPolyline":
            assert len(s["verts"]) == 4 and s["outer"] == 0
    assert [s["kind"] for s in inner] == ["LwPolyline"] * 3 + ["Line"]          # порядок файла


@test
def t14_unclosed_outer_and_other_errors():
    d = DxfDoc()
    e = d.entities
    e.line((0, 0), (100, 0)).line((100, 0), (100, 50)).line((100, 50), (0, 50)).line((0, 50), (0, 0.5))
    msg = expect_error(d.dxf_bytes(), "gap.dxf", "не замкнут", "(0; 0)", "(0; 0.5)", "0.5")
    # разрыв меньше допуска — замыкается
    d = DxfDoc()
    d.entities.line((0, 0), (100, 0)).line((100, 0), (100, 50)).line((100, 50), (0, 50)).line((0, 50), (0, 0.004))
    assert len(parts_from_dxf(d.dxf_bytes(), "ok.dxf")) == 1
    # ветвление на резе: узел из 3 рёбер
    d = DxfDoc()
    d.entities.line((0, 0), (50, 0)).line((50, 0), (100, 0)).line((100, 0), (100, 50)).line((100, 50), (0, 50))
    d.entities.line((0, 50), (0, 0)).line((50, 0), (50, 20))
    expect_error(d.dxf_bytes(), "br.dxf", "ветвится", "(50; 0)")
    # Т-примыкание без узла (надрез от края; прорезь до разгрузочного отверстия) — не ошибка: открытый рез детали
    # + предупреждение с координатой (это может быть и рамка/выносная линия — пусть человек посмотрит)
    d = DxfDoc()
    rect(d.entities, 0, 0, 100, 50)
    d.entities.line((50, 0), (50, 20))
    p = parts_from_dxf(d.dxf_bytes(), "t.dxf")[0]
    check_part(p)
    assert kinds(p["shapes"][:-1]) == [("Line", 1, -1)], kinds(p["shapes"])
    assert sum("упираются" in w and "(50; 0)" in w and ": 1," in w for w in p["warnings"]) == 1, p["warnings"]
    d = DxfDoc()
    rect(d.entities, 0, 0, 100, 50)
    d.entities.circle((70, 25), 10).line((70, 35), (70, 45))
    d.entities.circle((20, 37), 2).line((20, 10), (20, 35))           # прорезь до разгрузочного отверстия R2
    p = parts_from_dxf(d.dxf_bytes(), "t2.dxf")[0]
    check_part(p)
    assert kinds(p["shapes"][:-1]) == [("Circle", 1, -1)] * 2 + [("Line", 1, -1)] * 2, kinds(p["shapes"])
    assert sum("упираются" in w and "(70; 35)" in w and ": 2," in w for w in p["warnings"]) == 1, p["warnings"]
    # элемент вне деталей
    d = DxfDoc()
    rect(d.entities, 0, 0, 100, 50)
    d.entities.circle((300, 20), 5, layer="Гравировка")
    expect_error(d.dxf_bytes(), "out.dxf", "вне контуров", "(305; 20)")
    # пересечение: отверстие вылезает за контур
    d = DxfDoc()
    rect(d.entities, 0, 0, 100, 50)
    d.entities.circle((98, 25), 5)
    expect_error(d.dxf_bytes(), "x.dxf", "пересекаются")
    # пусто / не DXF / двоичный / DWG
    expect_error(DxfDoc().dxf_bytes(), "empty.dxf", "нет контуров")
    expect_error(b"", "e.dxf", "пуст")
    expect_error(b"hello\nworld\n", "t.dxf", "код группы")
    expect_error(b"AutoCAD Binary DXF\r\n\x1a\x00....", "b.dxf", "двоичный")
    expect_error(b"AC1032\x00\x00\x00\x00\x00", "a.dwg", "DWG")
    only_eng = DxfDoc()
    rect(only_eng.entities, 0, 0, 10, 10, layer="Гравировка")
    expect_error(only_eng.dxf_bytes(), "g.dxf", "нет замкнутого контура")
    assert msg


@test
def t15_ocs_extrusion_minus_z():
    d = DxfDoc()
    e = d.entities
    e.line((0, 0), (90, 0)).line((100, 10), (100, 50)).line((100, 50), (0, 50)).line((0, 50), (0, 0))
    e.arc((-90, 10), 10, 180, 270, extrusion=(0, 0, -1))                      # скругление (90,10) R10 в OCS −Z
    e.circle((-50, 25), 5, extrusion=(0, 0, -1))                              # отверстие (50, 25)
    e.lwpolyline([(-20, 20, math.tan(math.pi / 8)), (-30, 30, 0)], extrusion=(0, 0, -1), elevation=0)
    p = parts_from_dxf(d.dxf_bytes(), "ocs.dxf")[0]
    o = check_part(p)
    assert close(vn.spec_rebuild.poly_area(o["verts"]), 5000 - (100 - 25 * math.pi), 1e-9)
    assert sum(1 for v in o["verts"] if close(abs(v[2]), math.tan(math.pi / 8), 1e-12)) == 1
    c = [s for s in p["shapes"] if s["kind"] == "Circle"][0]
    assert pclose(c["c"], (50, 25))
    op = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and s["flag"] == 0][0]
    # в OCS дуга против часовой от (−20,20) до (−30,30) с центром (−30,20); в мире: (20,20)→(30,30), центр (30,20)
    _, _, pm = arc_info(op["verts"][0][:2], op["verts"][1][:2], op["verts"][0][2])
    s45 = math.sqrt(0.5)
    want = (30 - 10 * s45, 20 + 10 * s45)
    assert {tuple(round(x, 9) for x in op["verts"][0][:2]), tuple(round(x, 9) for x in op["verts"][1][:2])} == {(20.0, 20.0), (30.0, 30.0)}
    assert pclose(pm, want, 1e-9), (pm, want)


@test
def t16_qty_from_filename():
    cases = {
        "Фланец_12шт.dxf": (12, "Фланец"), "Фланец 12 шт.dxf": (12, "Фланец"), "Фланец 12шт..DXF": (12, "Фланец"),
        "Фланец x12.dxf": (12, "Фланец"), "Фланец х12.dxf": (12, "Фланец"), "Фланец_Х7.DXF": (7, "Фланец"),
        "Фланец (12).dxf": (12, "Фланец"), "Фланец (5 шт).dxf": (5, "Фланец"), "Фланец-3шт.dxf": (3, "Фланец"),
        "vsh_500x1000_t0.65_RAL8017.dxf": (None, "vsh_500x1000_t0.65_RAL8017"),
        "Пластина 200x100.dxf": (None, "Пластина 200x100"), "Пластина 200x100 x4.dxf": (4, "Пластина 200x100"),
        "C:\\Заказы\\Деталь_3шт.dxf": (3, "Деталь"), "/tmp/a/Ребро_0шт.dxf": (None, "Ребро_0шт"),
        # размер через « х » с пробелами — не количество (перед « х» стоит отдельное число)
        "Лист 1500 х 3000.dxf": (None, "Лист 1500 х 3000"), "Лист 1500 x 3000.dxf": (None, "Лист 1500 x 3000"),
        "Пластина 200 х 100 х 8.dxf": (None, "Пластина 200 х 100 х 8"), "Лист 1,5 х 1250 х 2500.dxf":
            (None, "Лист 1,5 х 1250 х 2500"), "Уголок 50 x 50 x 5_4шт.dxf": (4, "Уголок 50 x 50 x 5"),
        "Пластина 200x100 х 3.dxf": (3, "Пластина 200x100"), "1500 х 3000.dxf": (None, "1500 х 3000"),
    }
    for fn, want in cases.items():
        assert qty_from_filename(fn) == want, (fn, qty_from_filename(fn), want)
    d = DxfDoc()
    rect(d.entities, 0, 0, 10, 10)
    data = d.dxf_bytes()
    p = parts_from_dxf(data, "Косынка х4.dxf")[0]
    assert p["qty"] == 4 and p["name"] == "Косынка" and not any("количество" in w for w in p["warnings"])
    p = parts_from_dxf(data, "Косынка х4.dxf", qty=6)[0]
    assert p["qty"] == 6 and any("взято переданное 6" in w for w in p["warnings"])
    p = parts_from_dxf(data, "Косынка.dxf")[0]
    assert p["qty"] == 1 and any("количество не указано" in w for w in p["warnings"])
    p = parts_from_dxf(data, 'Кронштейн "А" & <Б>_2шт.dxf')[0]
    assert p["qty"] == 2 and p["name"] == "Кронштейн А  Б", p["name"]
    p = parts_from_dxf(data, "Лист 1500 х 3000.dxf")[0]
    assert p["qty"] == 1 and p["name"] == "Лист 1500 х 3000" and any("количество не указано" in w for w in p["warnings"])
    for bad in (0, -1, 1.5, "x", float("nan"), float("inf"), float("-inf"), "nan", "inf", [3]):
        try:
            parts_from_dxf(data, "a.dxf", qty=bad)
            raise AssertionError("qty=%r должен дать ошибку" % (bad,))
        except DxfError:
            pass


@test
def t17_duplicates_zero_length_hidden_layers():
    d = DxfDoc()
    d.layer("Скрытый", color=-7).layer("Мороз", flags=1).layer("Оси", ltype="ОСЕВАЯ").ltype("ОСЕВАЯ", [10, -3, 1, -3])
    e = d.entities
    rect(e, 0, 0, 100, 50)
    e.line((0, 0), (100, 0))                                   # точный дубль
    e.line((100, 50), (0, 50), layer="Гравировка")             # дубль на гравировке — остаётся рез
    e.circle((20, 20), 5).circle((20, 20), 5)                  # дубль окружности
    e.line((50, 25), (50, 25))                                 # нулевая длина
    e.lwpolyline([(60, 30), (70, 30), (70, 40), (60, 40), (60, 30)], closed=True)   # повтор первой точки — не дубль
    e.circle((70, 20), 3, layer="Скрытый").circle((80, 20), 3, layer="Мороз")
    e.line((-10, 25), (110, 25), layer="Оси")                  # осевая по типу слоя
    e.circle((40, 40), 2, invisible=True)
    p = parts_from_dxf(d.dxf_bytes(), "dup.dxf")[0]
    o = check_part(p)
    assert len(o["verts"]) == 4 and kinds(p["shapes"][:-1]) == [("Circle", 1, -1), ("LwPolyline", 1, 1)], kinds(p["shapes"])
    sq = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and not s["outer"]][0]
    assert len(sq["verts"]) == 4 and close(vn.spec_rebuild.poly_area(sq["verts"]), -100)
    W = p["warnings"]
    assert any("дублирующиеся" in w and ": 3" in w for w in W), W
    assert any("нулевой длины — выброшено: 1" in w for w in W), W
    assert any("«Скрытый»" in w for w in W) and any("«Мороз»" in w for w in W), W
    assert any("«ОСЕВАЯ»" in w for w in W) and any("невидимые" in w for w in W), W


@test
def t18_nonuniform_scale_minsert_attribs_layer0_inherit():
    d = DxfDoc()
    b = d.block("H", base=(0, 0))
    b.circle((0, 0), 2)
    b.line((-1, 0), (1, 0))                                     # слой «0» → наследует слой вставки
    el = d.block("E", base=(0, 0))
    el.circle((0, 0), 10)
    e = d.entities
    rect(e, 0, 0, 200, 100)
    e.insert("H", (20, 20), cols=3, rows=2, col_sp=30, row_sp=40, layer="Гравировка", attribs=2)
    e.insert("E", (150, 50), sx=2, sy=1)                        # окружность → эллипс 20×10
    p = parts_from_dxf(d.dxf_bytes(), "mins.dxf")[0]
    check_part(p)
    eng = [s for s in p["shapes"] if s["layer"] == 2]
    assert kinds(eng) == [("Circle", 2, -1)] * 6 + [("Line", 2, -1)] * 6, kinds(eng)
    cs = sorted(s["c"] for s in eng if s["kind"] == "Circle")
    assert cs == sorted((20.0 + 30 * i, 20.0 + 40 * j) for i in range(3) for j in range(2)), cs
    ell = [s for s in p["shapes"] if s["layer"] == 1 and not s["outer"]]
    assert len(ell) == 1 and ell[0]["kind"] == "LwPolyline" and ell[0]["flag"] == 1
    v = ell[0]["verts"]
    assert max(abs(((x - 150) / 20) ** 2 + ((y - 50) / 10) ** 2 - 1) for x, y, _ in v) < 1e-9
    t = np.linspace(0, 2 * math.pi, 20001)
    assert seg_dist(np.c_[150 + 20 * np.cos(t), 50 + 10 * np.sin(t)], v, True).max() <= 0.01
    W = p["warnings"]
    assert any("ATTRIB ×2" in w for w in W) and any("разным масштабом" in w for w in W), W


@test
def t19_deterministic_and_text_input():
    d = DxfDoc()
    e = d.entities
    rect(e, 0, 0, 120, 60)
    e.spline([(10, 10), (30, 50), (60, -5), (90, 40)], [0, 0, 0, 0, 1, 1, 1, 1], layer="Гравировка")
    e.ellipse((60, 30), (20, 5), 0.3)
    data = d.dxf_bytes()
    a = parts_from_dxf(data, "det.dxf")
    b = parts_from_dxf(bytearray(data), "det.dxf")
    assert a == b
    assert parts_from_dxf(data.replace(b"\n", b"\r\n"), "det.dxf") == a


@test
def t20_smoke_vent_hood_generator_dxf():
    zips = sorted(glob.glob(os.path.join(LIB, "tests", "data", "*.zip")))
    assert zips, "нет архивов с DXF генератора"
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        for z in zips:
            with zipfile.ZipFile(z) as zf:
                for nm in zf.namelist():
                    if not nm.lower().endswith(".dxf"):
                        continue
                    data = zf.read(nm)
                    parts = parts_from_dxf(data, nm)
                    path = os.path.join(tmp, "x.dxf")
                    with open(path, "wb") as fh:
                        fh.write(data)
                    holes, segs, _ = vn.dxfread.load(path)
                    ref, small = vn.parts.analyze(path)
                    ref = sorted(ref, key=lambda r: r["bbox"][0])
                    assert len(parts) == len(ref), (nm, len(parts), len(ref))
                    tot_circ = 0
                    for p, r in zip(parts, ref):
                        o = check_part(p)
                        inner = p["shapes"][:-1]
                        circ = [s for s in inner if s["kind"] == "Circle"]
                        slots = [s for s in inner if s["kind"] == "LwPolyline" and s["flag"] == 1]
                        assert len(circ) == len(r["holes"]), (nm, len(circ), len(r["holes"]))
                        assert len(slots) == len(r["slots"]) + len(r["smalls"]), (nm, len(slots))
                        assert len(inner) == len(circ) + len(slots), (nm, kinds(inner))
                        assert o["kind"] == "LwPolyline" and len(o["verts"]) == len(r["edges"])
                        w = r["bbox"][1] - r["bbox"][0]
                        h = r["bbox"][3] - r["bbox"][2]
                        bb = sampled_bbox(o["verts"], True)
                        assert close(bb[2], w, 1e-3) and close(bb[3], h, 1e-3), (nm, bb, w, h)
                        ref_area = abs(vn.contours.area(vn.contours.chain(r["edges"])))
                        assert close(vn.spec_rebuild.poly_area(o["verts"]), ref_area, 1e-6)
                        for sl in slots:                            # пазы — точные дуги
                            assert sum(1 for v in sl["verts"] if v[2]) == 2
                        tot_circ += len(circ)
                    assert tot_circ == len(holes), (nm, tot_circ, len(holes))
                    n += 1
    assert n >= 7, n
    print("      DXF генератора зонтов проверено: %d" % n)


@test
def t21_duplicates_other_form_bad_numbers_near_uniform_scale():
    # окружность CIRCLE + та же окружность полилинией с двумя bulge = 1 → одна деталь, дубль с предупреждением
    d = DxfDoc()
    d.entities.circle((50, 50), 40).lwpolyline([(10, 50, 1.0), (90, 50, 1.0)], closed=True)
    ps = parts_from_dxf(d.dxf_bytes(), "disc.dxf")
    assert len(ps) == 1 and [s["kind"] for s in ps[0]["shapes"]] == ["Circle"], ps
    assert any("дублирующиеся" in w and ": 1" in w for w in ps[0]["warnings"]), ps[0]["warnings"]
    # отверстие: CIRCLE + две дуги ARC 0–180 / 180–360; и гравировка поверх реза в другой записи — остаётся рез
    d = DxfDoc()
    rect(d.entities, 0, 0, 200, 100)
    d.entities.circle((50, 50), 10).arc((50, 50), 10, 0, 180).arc((50, 50), 10, 180, 360)
    d.entities.circle((150, 50), 8, layer="Гравировка").lwpolyline([(142, 50, 1.0), (158, 50, 1.0)], closed=True)
    p = parts_from_dxf(d.dxf_bytes(), "hole.dxf")[0]
    check_part(p)
    assert kinds(p["shapes"][:-1]) == [("Circle", 1, -1)] * 2, kinds(p["shapes"])
    assert any("дублирующиеся" in w and ": 2" in w for w in p["warnings"]), p["warnings"]
    # не дубли: квадрат и вписанная окружность (габарит тот же), окружности того же радиуса в разных местах,
    # концентрические с разницей радиусов 0,02 мм
    d = DxfDoc()
    rect(d.entities, 0, 0, 200, 100)
    d.entities.lwpolyline([(40, 40), (60, 40), (60, 60), (40, 60)], closed=True).circle((50, 50), 10)
    d.entities.circle((120, 50), 10).circle((150, 50), 10).circle((150, 50), 9.98)
    p = parts_from_dxf(d.dxf_bytes(), "near.dxf")[0]
    assert kinds(p["shapes"][:-1]) == [("Circle", 1, -1)] * 4 + [("LwPolyline", 1, 1)], kinds(p["shapes"])
    assert not any("дублир" in w for w in p["warnings"]), p["warnings"]

    # испорченные числа — DxfError по-русски от проверок разбора (не страховка с именем чужого исключения)
    def bad_number(d, *needles):
        msg = expect_error(d.dxf_bytes(), "bad.dxf", *needles)
        assert "Error" not in msg, msg
    d = DxfDoc()
    rect(d.entities, 0, 0, 100, 50)
    d.entities.line((10, 10), (1e307, 10))
    bad_number(d, "вне допустимого диапазона")
    d = DxfDoc()
    d.entities.lwpolyline([(0, 0, 1e200), (100, 0), (100, 50), (0, 50)], closed=True)
    bad_number(d, "дуга", "испорчены")
    d = DxfDoc()
    rect(d.entities, 0, 0, 100, 50)
    d.entities.ellipse((60, 25), (10, 0), 0.5, 0.0, 1e308)
    bad_number(d, "ELLIPSE", "недопустимы")
    d = DxfDoc(insunits=6)
    rect(d.entities, 0, 0, 1e306, 1e306)
    bad_number(d, "вне допустимого диапазона")
    d = DxfDoc()
    d.block("B").circle((0, 0), 5)
    rect(d.entities, 0, 0, 100, 50)
    d.entities.insert("B", (50, 25), sx=1e308, sy=1e308)
    bad_number(d, "испорчены")
    d = DxfDoc()
    rect(d.entities, 0, 0, 100, 50)
    d.entities.circle((50, 25), 1e300)
    bad_number(d, "окружность", "испорчены")
    # почти прямая дуга огромного радиуса (bulge 1e-11, стрелка 5e-10 мм) — отрезок; bulge 1e-9 — точная дуга
    d = DxfDoc()
    d.entities.lwpolyline([(0, 0, 1e-11), (100, 0, 1e-9), (100, 50), (0, 50)], closed=True)
    o = check_part(parts_from_dxf(d.dxf_bytes(), "flat.dxf")[0])
    assert sorted(abs(v[2]) for v in o["verts"]) == [0.0, 0.0, 0.0, 1e-9], o["verts"]

    # масштаб вставки 1 / 1.0000001 (округление в CAD; искажение R10 — 5e-7 мм): окружность и дуги — точные
    d = DxfDoc()
    b = d.block("P")
    b.lwpolyline([(0, 0), (100, 0), (100, 40, 1.0), (100, 50), (0, 50)], closed=True)
    b.circle((30, 25), 10).arc((60, 25), 5, 0, 180).line((55, 25), (65, 25))
    d.entities.insert("P", (0, 0), sx=1.0, sy=1.0000001)
    p = parts_from_dxf(d.dxf_bytes(), "s.dxf")[0]
    o = check_part(p)
    assert kinds(p["shapes"][:-1]) == [("Circle", 1, -1), ("LwPolyline", 1, 1)], kinds(p["shapes"])
    c = [s for s in p["shapes"] if s["kind"] == "Circle"][0]
    assert close(c["r"], 10, 1e-5) and not any("разным масштабом" in w for w in p["warnings"]), p["warnings"]
    assert sum(1 for v in o["verts"] if close(abs(v[2]), 1.0, 1e-12)) == 1, o["verts"]
    # а заметное искажение (1 / 1.001: R10 → 0,005 мм) — по-прежнему ломаная с предупреждением
    d = DxfDoc()
    d.block("Q").circle((0, 0), 10)
    rect(d.entities, 0, 0, 100, 50)
    d.entities.insert("Q", (50, 25), sx=1.0, sy=1.001)
    p = parts_from_dxf(d.dxf_bytes(), "q.dxf")[0]
    assert kinds(p["shapes"][:-1]) == [("LwPolyline", 1, 1)] and any("разным масштабом" in w for w in p["warnings"])
    # ELLIPSE с почти равными осями (ratio 0.99999999) — окружность; дуга такого эллипса — точная дуга
    d = DxfDoc()
    rect(d.entities, 0, 0, 100, 50)
    d.entities.ellipse((30, 25), (10, 0), 0.99999999)
    d.entities.ellipse((70, 25), (0, 8), 0.99999999, 0.0, math.pi).line((70, 33), (70, 17))
    p = parts_from_dxf(d.dxf_bytes(), "e.dxf")[0]
    check_part(p)
    assert kinds(p["shapes"][:-1]) == [("Circle", 1, -1), ("LwPolyline", 1, 1)], kinds(p["shapes"])
    sl = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and not s["outer"]][0]
    assert len(sl["verts"]) == 2 and sum(1 for v in sl["verts"] if close(abs(v[2]), 1.0, 1e-6)) == 1, sl["verts"]
    assert not any("ELLIPSE" in w for w in p["warnings"]), p["warnings"]


def main():
    fails = 0
    for t in TESTS:
        try:
            t()
            print("ok    %s" % t.__name__)
        except Exception:
            fails += 1
            print("FAIL  %s" % t.__name__)
            traceback.print_exc()
    print("итого: %d из %d прошли" % (len(TESTS) - fails, len(TESTS)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
