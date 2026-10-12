# -*- coding: utf-8 -*-
"""Состязательная проверка read_dxf (независимо от tests/check_read_dxf.py и его писателя фикстур).

    python3 tests/adv_read_dxf.py        # код выхода 0 — дефектов не найдено, 1 — есть провалы

Свой минимальный писатель DXF (ниже), своя оценка B-сплайнов (базис Кокса — де Бура, векторно по numpy), свои
ожидаемые преобразования вставок. Все случайные данные — с фиксированным зерном, без зависимостей от часов
(время замеряется только для порога производительности, на результат не влияет).
Каждая проверка печатает ok / FAIL с коротким описанием; провал = найденный дефект договора.
"""
import math
import os
import random
import re
import sys
import time
import traceback
import zipfile
import glob
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np                                     # noqa: E402

from sheet_nest.libpath import vn, LIB                 # noqa: E402
from sheet_nest.read_dxf import parts_from_dxf, DxfError, qty_from_filename, is_engrave_layer   # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


# =====================================================================================  мини-писатель DXF
def dxf(ents, ver="AC1015", units=4, header=(), tables=(), blocks=(), enc="utf-8", nl="\n"):
    T = [(0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, ver)]
    if units is not None:
        T += [(9, "$INSUNITS"), (70, units)]
    T += list(header) + [(0, "ENDSEC")]
    if tables:
        T += [(0, "SECTION"), (2, "TABLES")] + list(tables) + [(0, "ENDSEC")]
    if blocks:
        T += [(0, "SECTION"), (2, "BLOCKS")] + list(blocks) + [(0, "ENDSEC")]
    T += [(0, "SECTION"), (2, "ENTITIES")] + list(ents) + [(0, "ENDSEC"), (0, "EOF")]
    return (nl.join("%d%s%s" % (c, nl, repr(v) if isinstance(v, float) else v) for c, v in T) + nl).encode(enc)


def LINE(a, b, layer="0"):
    return [(0, "LINE"), (8, layer), (10, float(a[0])), (20, float(a[1])), (30, 0.0),
            (11, float(b[0])), (21, float(b[1])), (31, 0.0)]


def CIRCLE(c, r, layer="0", extra=()):
    return [(0, "CIRCLE"), (8, layer)] + list(extra) + [(10, float(c[0])), (20, float(c[1])), (30, 0.0), (40, float(r))]


def ARC(c, r, a0, a1, layer="0", extra=()):
    return [(0, "ARC"), (8, layer)] + list(extra) + [(10, float(c[0])), (20, float(c[1])), (30, 0.0), (40, float(r)),
                                                      (50, float(a0)), (51, float(a1))]


def LW(verts, closed, layer="0", extra=()):
    t = [(0, "LWPOLYLINE"), (8, layer), (90, len(verts)), (70, 1 if closed else 0)] + list(extra)
    for v in verts:
        t += [(10, float(v[0])), (20, float(v[1]))]
        if len(v) > 2 and v[2]:
            t += [(42, float(v[2]))]
    return t


def RECT(x0, y0, x1, y1, layer="0"):
    return LW([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True, layer)


def SPLINE(ctrl, knots, deg, weights=None, closed=False, layer="0"):
    fl = 8 | (1 if closed else 0) | (4 if weights else 0)
    t = [(0, "SPLINE"), (8, layer), (70, fl), (71, deg), (72, len(knots)), (73, len(ctrl)), (74, 0)]
    t += [(40, float(k)) for k in knots]
    if weights:
        t += [(41, float(w)) for w in weights]
    for p in ctrl:
        t += [(10, float(p[0])), (20, float(p[1])), (30, 0.0)]
    return t


def ELLIPSE(c, maj, ratio, s0=0.0, s1=2 * math.pi, layer="0"):
    return [(0, "ELLIPSE"), (8, layer), (10, float(c[0])), (20, float(c[1])), (30, 0.0), (11, float(maj[0])),
            (21, float(maj[1])), (31, 0.0), (40, float(ratio)), (41, float(s0)), (42, float(s1))]


def BLOCK(name, ents, base=(0, 0)):
    return ([(0, "BLOCK"), (8, "0"), (2, name), (70, 0), (10, float(base[0])), (20, float(base[1])), (30, 0.0),
             (3, name)] + list(ents) + [(0, "ENDBLK"), (8, "0")])


def INSERT(name, at, sx=1.0, sy=1.0, rot=0.0, layer="0", extra=()):
    return ([(0, "INSERT"), (8, layer), (2, name), (10, float(at[0])), (20, float(at[1])), (30, 0.0),
             (41, float(sx)), (42, float(sy)), (50, float(rot))] + list(extra))


def ENT(typ, layer="0"):
    return [(0, typ), (8, layer), (10, 10.0), (20, 10.0), (30, 0.0)]


# =====================================================================================  помощники проверок
def has_cyr(s):
    return bool(re.search("[А-Яа-яЁё]", s))


def err_of(data, name="t.dxf", **kw):
    """→ текст DxfError или None (если прочиталось). Иные исключения пробрасываются."""
    try:
        parts_from_dxf(data, name, **kw)
    except DxfError as ex:
        return str(ex)
    return None


def area(verts):
    return vn.spec_rebuild.poly_area(verts)


def arc_mid(v0, v1):
    """Середина дуги сегмента v0→v1 (bulge в v0): от середины хорды вправо на b·d/2 (b > 0 — против часовой)."""
    x0, y0, b = v0
    x1, y1 = v1[0], v1[1]
    dx, dy = x1 - x0, y1 - y0
    d = math.hypot(dx, dy)
    return ((x0 + x1) / 2 + dy / d * (b * d / 2), (y0 + y1) / 2 - dx / d * (b * d / 2))


def dense(verts, closed, step=0.05):
    """Плотные точки контура с дугами (своя реализация, не из модуля)."""
    out = []
    n = len(verts)
    for k in range(n if closed else n - 1):
        x0, y0, b = verts[k]
        x1, y1 = verts[(k + 1) % n][:2]
        if not b:
            m = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
            out += [(x0 + (x1 - x0) * j / m, y0 + (y1 - y0) * j / m) for j in range(m)]
        else:
            th = 4 * math.atan(b)
            d = math.hypot(x1 - x0, y1 - y0)
            r = d / (2 * math.sin(abs(th) / 2))
            mx, my = arc_mid((x0, y0, b), (x1, y1))
            # центр: от середины дуги к середине хорды на r
            hx, hy = (x0 + x1) / 2, (y0 + y1) / 2
            L = math.hypot(hx - mx, hy - my)
            if L < 1e-12:                                 # полуокружность: центр = середина хорды
                cx, cy = hx, hy
            else:
                cx, cy = mx + (hx - mx) / L * r, my + (hy - my) / L * r
            a0 = math.atan2(y0 - cy, x0 - cx)
            m = max(8, int(abs(th) * r / step))
            out += [(cx + r * math.cos(a0 + th * j / m), cy + r * math.sin(a0 + th * j / m)) for j in range(m)]
    if not closed:
        out.append(tuple(verts[-1][:2]))
    return np.array(out)


def bbox_min(verts, closed):
    P = dense(verts, closed, 0.01)
    return P[:, 0].min(), P[:, 1].min()


def basis_eval(P, W, K, p, ts):
    """Независимая NURBS: базисные функции Кокса — де Бура, векторно по параметрам."""
    P = np.asarray(P, float)
    W = np.asarray(W, float)
    K = np.asarray(K, float)
    ts = np.asarray(ts, float)
    n, m = len(P), len(K) - 1
    N = ((K[:-1][None, :] <= ts[:, None]) & (ts[:, None] < K[1:][None, :])).astype(float)
    last = max(i for i in range(m) if K[i] < K[i + 1] and K[i + 1] <= K[n])
    N[ts >= K[n], :] = 0.0
    N[ts >= K[n], last] = 1.0
    for k in range(1, p + 1):
        N2 = np.zeros((len(ts), m - k))
        for i in range(m - k):
            a = 0.0 if K[i + k] == K[i] else (ts - K[i]) / (K[i + k] - K[i]) * N[:, i]
            b = 0.0 if K[i + k + 1] == K[i + 1] else (K[i + k + 1] - ts) / (K[i + k + 1] - K[i + 1]) * N[:, i + 1]
            N2[:, i] = a + b
        N = N2
    Nw = N[:, :n] * W[None, :]
    with np.errstate(all="ignore"):
        return (Nw @ P) / Nw.sum(1)[:, None]


def dist_to_poly(Q, V, closed):
    V = np.array([v[:2] for v in V] + ([V[0][:2]] if closed else []), float)
    A, B = V[:-1], V[1:]
    D = B - A
    L2 = (D ** 2).sum(1)
    L2[L2 == 0] = 1e-30
    Q = np.asarray(Q, float)
    out = np.empty(len(Q))
    for i in range(0, len(Q), 400):
        q = Q[i:i + 400, None, :]
        t = np.clip(((q - A) * D).sum(2) / L2, 0, 1)
        X = A + t[..., None] * D
        out[i:i + 400] = np.sqrt(((X - q) ** 2).sum(2)).min(1)
    return out


def contract(p):
    """Договор Part/shape (DESIGN.md); → внешний контур."""
    assert set(p) == {"name", "qty", "shapes", "src", "warnings"}, sorted(p)
    assert isinstance(p["qty"], int) and p["qty"] >= 1 and isinstance(p["warnings"], list)
    assert not any(ch in p["name"] for ch in "&<>\"'"), p["name"]
    sh = p["shapes"]
    assert sh and sum(s["outer"] for s in sh) == 1 and sh[-1]["outer"] == 1 and sh[-1]["layer"] == 1
    for s in sh:
        assert s["handle"] is None and s["layer_name"] == "0" and s["coedge"] == 0 and s["flag64"] == 0, s
        assert s["lead"] is None and s["layer"] in (1, 2) and s["kind"] in ("Line", "Circle", "LwPolyline"), s
        if s["kind"] == "Circle":
            assert s["a0"] == math.pi / 4 and s["r"] > 0
        if s["kind"] == "LwPolyline":
            assert s["sp"] == 0.0 and s["flag"] in (0, 1) and all(len(v) == 3 for v in s["verts"])
            if s["flag"] == 1 and s is not sh[-1] and s["layer"] == 1:
                assert area(s["verts"]) < 0, "отверстие должно быть по часовой"
    o = sh[-1]
    if o["kind"] == "Circle":
        assert abs(o["c"][0] - o["r"]) < 1e-9 and abs(o["c"][1] - o["r"]) < 1e-9, o
    else:
        assert o["kind"] == "LwPolyline" and o["flag"] == 1 and area(o["verts"]) > 0, "внешний — против часовой"
        bx, by = bbox_min(o["verts"], True)
        assert abs(bx) < 2e-3 and abs(by) < 2e-3, (bx, by)
    return o


# =====================================================================================  проверки: договор и геометрия
@check
def a01_contract_variety():
    """Договор Part на разных входах: дуги наружу влево/вниз, зеркальная вставка, внешний-окружность, R12 CRLF."""
    part = LW([(0, 0, 0), (100, 0, 0), (100, 50, 0), (0, 50, 1.0)], True)       # полукруг наружу слева
    cases = [
        dxf(part + CIRCLE((60, 25), 5)),
        dxf(INSERT("P", (500, 500), sx=-1, rot=90), blocks=BLOCK("P", part + CIRCLE((60, 25), 5))),
        dxf(CIRCLE((-300, 40), 50) + CIRCLE((-300, 40), 10)),
        dxf(LW([(0, 0, -0.4), (80, 0, 0), (80, 40, 0), (0, 40, 0)], True) + ARC((40, 20), 6, 350, 10) +
            LINE((40 + 6 * math.cos(math.radians(10)), 20 + 6 * math.sin(math.radians(10))),
                 (40 + 6 * math.cos(math.radians(-10)), 20 + 6 * math.sin(math.radians(-10)))),
            ver="AC1009", units=None, nl="\r\n"),
    ]
    for data in cases:
        ps = parts_from_dxf(data, "a.dxf")
        assert len(ps) == 1
        contract(ps[0])
    # площадь полукруга наружу сохраняется и после зеркала+поворота
    o = parts_from_dxf(cases[1], "a.dxf")[0]["shapes"][-1]
    assert abs(area(o["verts"]) - (5000 + math.pi * 625 / 2)) < 1e-6, area(o["verts"])


@check
def a02_insert_transforms_independent():
    """Вставки: база, поворот, масштаб с зеркалом, OCS −Z — сверка с независимым преобразованием."""
    blk = BLOCK("K", CIRCLE((5, 7), 2) + ARC((5, 7), 4, 0, 90, layer="Гравировка"), base=(3, 4))
    cases = [((300, 200), -1.5, 1.5, 37.0, False), ((300, 200), 2.0, -2.0, 200.0, False),
             ((-300, 200), 1.0, 1.0, 30.0, True)]
    for at, sx, sy, rot, neg in cases:
        extra = [(210, 0.0), (220, 0.0), (230, -1.0)] if neg else []
        p = parts_from_dxf(dxf(RECT(0, 0, 600, 400) + INSERT("K", at, sx, sy, rot, extra=extra), blocks=blk), "k.dxf")[0]
        contract(p)
        a = math.radians(rot)

        def f(q):
            x, y = (q[0] - 3) * sx, (q[1] - 4) * sy
            X, Y = at[0] + math.cos(a) * x - math.sin(a) * y, at[1] + math.sin(a) * x + math.cos(a) * y
            return (-X, Y) if neg else (X, Y)
        c = [s for s in p["shapes"] if s["kind"] == "Circle"][0]
        assert math.dist(c["c"], f((5, 7))) < 1e-6 and abs(c["r"] - 2 * abs(sx)) < 1e-9
        e = [s for s in p["shapes"] if s["layer"] == 2][0]
        v = e["verts"]
        assert {tuple(round(q, 6) for q in v[0][:2]), tuple(round(q, 6) for q in v[1][:2])} == \
            {tuple(round(q, 6) for q in f((9, 7))), tuple(round(q, 6) for q in f((5, 11)))}
        m = arc_mid(v[0], v[1])
        want = f((5 + 4 * math.cos(math.pi / 4), 7 + 4 * math.sin(math.pi / 4)))
        assert math.dist(m, want) < 1e-6, (m, want)


@check
def a03_ocs_closed_lwpolyline_hole():
    """Замкнутая LWPOLYLINE с bulge в OCS −Z: x → −x, дуги зеркалятся, отверстие по часовой, площадь точная."""
    tb = math.tan(math.pi / 8)
    hole = LW([(-20, 10, 0), (-40, 10, tb), (-50, 20, 0), (-50, 30, 0), (-20, 30, 0)], True,
              extra=[(210, 0.0), (220, 0.0), (230, -1.0)])
    p = parts_from_dxf(dxf(RECT(0, 0, 100, 50) + hole), "o.dxf")[0]
    contract(p)
    h = p["shapes"][0]
    # в мире: (20,10)→(40,10)→четверть, против часовой в OCS = по часовой в мире, центр (50,10) →(50,20)→(50,30)→(20,30)
    # многоугольник 550 мм² минус сегмент R10 90° (дуга внутрь)
    want_area = 550 - 100 * (math.pi / 2 - 1) / 2
    assert abs(abs(area(h["verts"])) - want_area) < 1e-9, (area(h["verts"]), want_area)
    arcs = [(v, h["verts"][(i + 1) % len(h["verts"])]) for i, v in enumerate(h["verts"]) if v[2]]
    assert len(arcs) == 1 and abs(abs(arcs[0][0][2]) - tb) < 1e-12
    m = arc_mid(*arcs[0])
    assert math.dist(m, (50 - 10 * math.cos(math.pi / 4), 10 + 10 * math.sin(math.pi / 4))) < 1e-9, m


@check
def a04_spline_accuracy_independent():
    """SPLINE: случайные кубические (зерно 7), рациональные с крайними весами, степень 5 — отклонение ≤ 0,01 мм."""
    rng = random.Random(7)
    worst = 0.0
    for trial in range(4):
        n = 9
        P = [(i * 250.0, rng.uniform(0, 400)) for i in range(n)]
        K = [0] * 4 + sorted(rng.uniform(0.1, 0.9) for _ in range(n - 4)) + [1] * 4
        ents = SPLINE(P, K, 3) + LINE(P[-1], (P[-1][0], -100)) + LINE((P[-1][0], -100), (0, -100)) + LINE((0, -100), P[0])
        p = parts_from_dxf(dxf(ents), "s.dxf")[0]
        o = contract(p)
        C = basis_eval(P, [1] * n, K, 3, np.linspace(0, 1, 40001)) - [0, -100]
        d = dist_to_poly(C, o["verts"], True).max()
        worst = max(worst, d)
        assert d <= 0.01, ("кубический", trial, d)
        assert any("SPLINE" in w for w in p["warnings"])
    P = [(0, 0), (500, 800), (1000, 0)]
    for w in (50.0, 0.05):
        p = parts_from_dxf(dxf(SPLINE(P, [0, 0, 0, 1, 1, 1], 2, weights=[1, w, 1]) + LINE((1000, 0), (0, 0))), "r.dxf")[0]
        o = contract(p)
        C = basis_eval(P, [1, w, 1], [0, 0, 0, 1, 1, 1], 2, np.linspace(0, 1, 80001))
        d = dist_to_poly(C, o["verts"], True).max()
        worst = max(worst, d)
        assert d <= 0.01, ("рациональный", w, d)
    P = [(0, 0), (100, 300), (200, -300), (300, 300), (400, -300), (500, 300), (600, 0)]
    K = [0] * 6 + [0.5] + [1] * 6
    p = parts_from_dxf(dxf(SPLINE(P, K, 5) + LINE((600, 0), (600, -200)) + LINE((600, -200), (0, -200)) +
                           LINE((0, -200), (0, 0))), "d5.dxf")[0]
    o = contract(p)
    C = basis_eval(P, [1] * 7, K, 5, np.linspace(0, 1, 40001)) - [0, -200]
    d = dist_to_poly(C, o["verts"], True).max()
    assert d <= 0.01, ("степень 5", d)
    print("      худшее отклонение сплайна %.4f мм" % max(worst, d))


@check
def a05_ellipse_accuracy_flat():
    """ELLIPSE: плоские и крупные — отклонение ≤ 0,01 мм, отверстие по часовой."""
    for a, ratio in ((1000, 0.05), (600, 0.3), (1500, 0.002)):
        p = parts_from_dxf(dxf(RECT(-2000, -2000, 2000, 2000) + ELLIPSE((0, 0), (a, 0), ratio)), "e.dxf")[0]
        contract(p)
        h = [s for s in p["shapes"] if s["kind"] == "LwPolyline" and not s["outer"]][0]
        t = np.linspace(0, 2 * math.pi, 80001)
        C = np.c_[a * np.cos(t) + 2000, a * ratio * np.sin(t) + 2000]
        d = dist_to_poly(C, h["verts"], True).max()
        assert d <= 0.01, (a, ratio, d)


@check
def a06_encodings_and_engrave_layers():
    """Слой гравировки: cp1251 (R12 без кодовой страницы, AC1018 ANSI_1251), UTF-8 AC1024, \\u+ строчными, DOS866, BOM."""
    def eng(layer):
        return RECT(0, 0, 100, 50) + LINE((10, 10), (40, 10), layer)
    cases = [
        dxf(eng("Гравировка"), ver="AC1009", units=None, enc="cp1251"),
        dxf(eng("ГРАВИРОВКА"), ver="AC1018", header=[(9, "$DWGCODEPAGE"), (3, "ANSI_1251")], enc="cp1251"),
        dxf(eng("гравировка_1"), ver="AC1024"),
        dxf(eng("\\u+0433\\u+0440\\u+0430\\u+0432"), ver="AC1015"),
        dxf(eng("Гравировка"), ver="AC1009", header=[(9, "$DWGCODEPAGE"), (3, "DOS866")], enc="cp866"),
        b"\xef\xbb\xbf" + dxf(eng("Маркировка"), ver="AC1015"),
        dxf(eng("mark"), nl="\r"),
        dxf(eng("Engrave")),
    ]
    for k, data in enumerate(cases):
        p = parts_from_dxf(data, "g.dxf")[0]
        contract(p)
        assert [(s["kind"], s["layer"]) for s in p["shapes"]] == [("Line", 2), ("LwPolyline", 1)], k
    for nm in ("ГРАВИРОВКА", "гравировка", "GRAV", "grav", "ENGRAVE", "MARK", "МАРКИРОВКА", "маркировка",
               "Гравировка 2", "engraving"):
        assert is_engrave_layer(nm), nm
    for nm in ("0", "Контур", "CUT", "MARKING", "МАРКА"):
        assert not is_engrave_layer(nm), nm


@check
def a07_ignored_entities_one_warning_per_type():
    """TEXT/MTEXT/DIMENSION/HATCH/LEADER/MLEADER/ATTRIB/ATTDEF/SOLID/3DFACE/VIEWPORT — по одному предупреждению с числом;
    POINT — молча."""
    ents = RECT(0, 0, 100, 50)
    types = ["TEXT", "MTEXT", "DIMENSION", "HATCH", "LEADER", "MLEADER", "ATTRIB", "ATTDEF", "SOLID", "3DFACE",
             "VIEWPORT"]
    for t in types + ["TEXT", "POINT"]:
        ents += ENT(t)
    W = parts_from_dxf(dxf(ents), "w.dxf")[0]["warnings"]
    for t in types:
        n = 2 if t == "TEXT" else 1
        hits = [w for w in W if w.startswith(t + " ")]
        assert len(hits) == 1 and ("×%d" % n) in hits[0] and has_cyr(hits[0]), (t, W)
    assert not any("POINT" in w for w in W), W


@check
def a08_units_scale_arcs():
    """$INSUNITS: дюйм/см/м — масштаб точек, радиусов окружностей и дуг; bulge не меняется."""
    for u, k in ((1, 25.4), (5, 10.0), (6, 1000.0), (2, 304.8)):
        part = LW([(0, 0, 0), (4, 0, 0), (4, 2, 0), (0, 2, 0.5)], True) + CIRCLE((1, 1), 0.25)
        p = parts_from_dxf(dxf(part, units=u), "u.dxf")[0]
        o = contract(p)
        c = [s for s in p["shapes"] if s["kind"] == "Circle"][0]
        assert abs(c["r"] - 0.25 * k) < 1e-9 * k
        assert abs(area(o["verts"]) - k * k * (8 + (4 * math.atan(0.5) - math.sin(4 * math.atan(0.5))) *
                                               (2 * (1 + 0.25) / (4 * 0.5)) ** 2 / 2)) < 1e-6 * k * k
        assert [v[2] for v in o["verts"]].count(0.5) == 1 or [abs(v[2]) for v in o["verts"]].count(0.5) == 1


@check
def a09_node_tolerance_boundary():
    """Допуск узла 0,01 мм: 0,0099 и 0,01 замыкаются, 0,0101 — ошибка с координатами разрыва."""
    def gap(g):
        return dxf(LINE((0, 0), (100, 0)) + LINE((100, 0), (100, 50)) + LINE((100, 50), (0, 50)) + LINE((0, 50), (0, g)))
    for g in (0.0099, 0.01):
        assert len(parts_from_dxf(gap(g), "g.dxf")) == 1, g
    msg = err_of(gap(0.0101))
    assert msg and "не замкнут" in msg and "(0; 0)" in msg, msg


@check
def a10_errors_russian_with_coordinates():
    """Ошибки — DxfError, по-русски, с координатами где положено."""
    cases = [
        (dxf(LINE((0, 0), (100, 0)) + LINE((100, 0), (100, 50)) + LINE((100, 50), (0, 50))), ["(0; 0)", "(0; 50)"]),
        (dxf(RECT(0, 0, 100, 50) + LINE((0, 0), (-20, -20))), ["(0; 0)"]),                          # ветвление
        (dxf(RECT(0, 0, 100, 50) + CIRCLE((300, 300), 5, layer="Гравировка")), ["(305; 300)"]),     # вне детали
        (b"", []), (b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n", []), (b"garbage\n", []),
        (b"AC1027\x00\x00", []), (dxf(RECT(0, 0, 10, 10, layer="Гравировка")), []),
    ]
    for data, needles in cases:
        msg = err_of(data)
        assert msg and has_cyr(msg), (data[:40], msg)
        for nd in needles:
            assert nd in msg, (nd, msg)


@check
def a11_multi_parts_naming_and_slits():
    """Несколько деталей: имена « #k» по левому краю, открытые U-прорези слоя реза → LwPolyline flag 0 слой 1."""
    ents = RECT(300, 0, 400, 80) + RECT(0, 0, 200, 100)
    ents += LW([(20, 20), (20, 35), (80, 35), (80, 20)], False) + LINE((320, 10), (380, 10))
    ps = parts_from_dxf(dxf(ents), "Ребро_7шт.dxf")
    assert [p["name"] for p in ps] == ["Ребро #1", "Ребро #2"] and all(p["qty"] == 7 for p in ps)
    for p in ps:
        contract(p)
    a, b = ps
    assert [(s["kind"], s["layer"], s.get("flag")) for s in a["shapes"][:-1]] == [("LwPolyline", 1, 0)]
    assert [(s["kind"], s["layer"]) for s in b["shapes"][:-1]] == [("Line", 1)]


@check
def a12_determinism_and_order_independence():
    """Повтор — тот же результат; перестановка сущностей (зерно 3) — та же геометрия."""
    items = [RECT(0, 0, 200, 100), CIRCLE((30, 30), 5), ARC((150, 50), 10, 0, 180), LINE((140, 50), (160, 50)),
             LW([(60, 60), (60, 80), (90, 80)], False), ELLIPSE((100, 30), (20, 0), 0.4),
             LINE((20, 80), (40, 80), "Гравировка"), LINE((40, 80), (40, 90), "Гравировка")]
    data = dxf(sum(items, []))
    a = parts_from_dxf(data, "d.dxf")
    assert a == parts_from_dxf(data, "d.dxf")

    def canon(ps):
        out = []
        for p in ps:
            for s in p["shapes"]:
                if s["kind"] == "Circle":
                    out.append(("C", s["layer"], round(s["c"][0], 6), round(s["c"][1], 6), round(s["r"], 6)))
                elif s["kind"] == "Line":
                    out.append(("L", s["layer"], tuple(sorted([tuple(round(q, 6) for q in s["p1"]),
                                                               tuple(round(q, 6) for q in s["p2"])]))))
                else:
                    out.append(("P", s["layer"], s["flag"], s["outer"], round(abs(area(s["verts"])), 4) if s["flag"] else 0,
                                tuple(sorted(tuple(round(q, 5) for q in v[:2]) for v in s["verts"]))))
        return sorted(out)
    rng = random.Random(3)
    for _ in range(3):
        it = list(items)
        rng.shuffle(it)
        assert canon(parts_from_dxf(dxf(sum(it, [])), "d.dxf")) == canon(a)


@check
def a13_performance():
    """Производительность: 20 000 отверстий, 5000 U-прорезей, MINSERT 300×300, экспоненциальная вложенность — быстро."""
    ents = RECT(0, 0, 2500, 1250)
    for i in range(200):
        for j in range(100):
            ents += CIRCLE((10 + i * 12.4, 10 + j * 12.3), 4)
    t = time.time()
    p = parts_from_dxf(dxf(ents), "perf.dxf")
    assert len(p) == 1 and len(p[0]["shapes"]) == 20001 and time.time() - t < 15
    ents = RECT(0, 0, 2500, 1250)
    for i in range(100):
        for j in range(50):
            x, y = 10 + i * 24.5, 10 + j * 24.5
            ents += LW([(x, y), (x, y + 15), (x + 15, y + 15), (x + 15, y)], False)
    t = time.time()
    p = parts_from_dxf(dxf(ents), "perf.dxf")
    assert len(p[0]["shapes"]) == 5001 and time.time() - t < 15
    blocks = BLOCK("B0", CIRCLE((0, 0), 0.1))
    for k in range(1, 25):
        blocks += BLOCK("B%d" % k, INSERT("B%d" % (k - 1), (0, 0)) + INSERT("B%d" % (k - 1), (0.3 * 2 ** (k // 2), 0.3 * 2 ** (k // 2))))
    t = time.time()
    assert err_of(dxf(RECT(-10, -10, 1e6, 1e6) + INSERT("B24", (0, 0)), blocks=blocks)) and time.time() - t < 15


@check
def a14_smoke_vent_hood_dxf():
    """DXF генератора зонтов: каждая деталь — 1 внешний, все окружности = отверстия vn.dxfread.load.
    (В этих файлах по 3–6 деталей — боковины и средние панели; «ровно 1 деталь» в задаче неверно.)"""
    zips = sorted(glob.glob(os.path.join(LIB, "tests", "data", "*.zip")))
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        for z in zips:
            with zipfile.ZipFile(z) as zf:
                for nm in zf.namelist():
                    if not nm.lower().endswith(".dxf"):
                        continue
                    data = zf.read(nm)
                    ps = parts_from_dxf(data, nm)
                    path = os.path.join(tmp, "x.dxf")
                    with open(path, "wb") as fh:
                        fh.write(data)
                    holes, _, _ = vn.dxfread.load(path)
                    circ = 0
                    for p in ps:
                        contract(p)
                        circ += sum(1 for s in p["shapes"] if s["kind"] == "Circle")
                    assert circ == len(holes), (nm, circ, len(holes))
                    n += 1
    assert n >= 7, n


# =====================================================================================  проверки: найденные дефекты
@check
def d01_qty_spaced_dimensions_not_quantity():
    """Размеры через « х » с пробелами (обычная запись по-русски) не должны читаться как количество."""
    bad = {}
    for fn in ("Лист 1500 х 3000.dxf", "Лист 1500 x 3000.dxf", "Пластина 200 х 100 х 8.dxf", "Уголок 50 x 50 x 5.dxf"):
        q, _ = qty_from_filename(fn)
        if q is not None:
            bad[fn] = q
    assert not bad, "размер прочитан как количество: %s" % bad


@check
def d02_duplicate_circle_other_representation():
    """Окружность CIRCLE + та же окружность полилинией с bulge (или двумя дугами): дубль должен выброситься
    (или ошибка), а не дать две одинаковые детали / два реза одного отверстия без предупреждения."""
    ps = parts_from_dxf(dxf(CIRCLE((50, 50), 40) + LW([(10, 50, 1.0), (90, 50, 1.0)], True)), "disc.dxf")
    assert len(ps) == 1, "диск: деталей %d (одна и та же окружность дважды)" % len(ps)
    p = parts_from_dxf(dxf(RECT(0, 0, 200, 100) + CIRCLE((50, 50), 10) + ARC((50, 50), 10, 0, 180) +
                           ARC((50, 50), 10, 180, 360)), "hole.dxf")[0]
    holes = [s for s in p["shapes"] if s["kind"] == "Circle"]
    assert len(holes) == 1, "отверстие режется %d раза" % len(holes)


def _robust(data, **kw):
    try:
        parts_from_dxf(data, "f.dxf", **kw)
        return None
    except DxfError:
        return None
    except Exception as ex:                              # noqa: BLE001 — это и есть дефект
        return "%s: %s" % (type(ex).__name__, ex)


@check
def d03_malformed_numbers_raise_dxferror():
    """Испорченные числа (огромные координаты, bulge, параметры эллипса) — только DxfError, не падение."""
    cases = {
        "LINE x=1e307": dxf(RECT(0, 0, 100, 50) + LINE((10, 10), (1e307, 10))),
        "LWPOLYLINE bulge=1e200": dxf(LW([(0, 0, 1e200), (100, 0), (100, 50), (0, 50)], True)),
        "ELLIPSE end=1e308": dxf(RECT(0, 0, 100, 50) + ELLIPSE((60, 25), (10, 0), 0.5, 0.0, 1e308)),
        "$INSUNITS=6, 1e306": dxf(RECT(0, 0, 1e306, 1e306), units=6),
    }
    bad = {k: r for k, r in ((k, _robust(d)) for k, d in cases.items()) if r}
    assert not bad, bad


@check
def d04_qty_nan_inf_raise_dxferror():
    """qty=nan / inf — DxfError (как 0, −1, 1.5), а не ValueError/OverflowError."""
    data = dxf(RECT(0, 0, 10, 10))
    bad = {repr(q): r for q, r in ((q, _robust(data, qty=q)) for q in (float("nan"), float("inf"), "nan")) if r}
    assert not bad, bad


@check
def d05_fuzz_no_foreign_exceptions():
    """1500 порч корректного DXF (зерно 12345): только DxfError или детали."""
    base = dxf(RECT(0, 0, 100, 50) + CIRCLE((20, 20), 5) + ARC((80, 25), 5, 0, 180, layer="Гравировка") +
               LW([(30, 30, 0.5), (40, 30), (40, 40, -0.3)], False) +
               SPLINE([(10, 10), (20, 40), (40, 40), (50, 10)], [0, 0, 0, 0, 1, 1, 1, 1], 3) +
               ELLIPSE((60, 25), (10, 0), 0.5) + INSERT("H", (70, 10), 1.0, -1.0, 30.0),
               blocks=BLOCK("H", CIRCLE((0, 0), 2) + LINE((-1, 0), (1, 0), "Гравировка"))).decode()
    lines = base.split("\n")
    num = [i for i in range(1, len(lines), 2) if re.fullmatch(r"-?[\d.]+(e[-+]?\d+)?", lines[i])]
    ext = ["1e308", "-1e308", "1e307", "1e200", "1e-320", "0", "1e160", "nan", "inf", "", "abc", "-1", "1e15"]
    rng = random.Random(12345)
    kinds = {}
    for _ in range(1500):
        L = list(lines)
        m = rng.randrange(3)
        if m == 0:
            for _k in range(rng.randint(1, 3)):
                L[rng.choice(num)] = rng.choice(ext)
        elif m == 1:
            del L[rng.randrange(len(L))]
        else:
            L = L[:rng.randrange(len(L))]
        r = _robust("\n".join(L).encode())
        if r:
            k = r.split(":")[0]
            kinds[k] = kinds.get(k, 0) + 1
    assert not kinds, "чужие исключения: %s" % kinds


@check
def d06_near_uniform_block_scale_keeps_exact_circles():
    """Вставка с масштабом 1 / 1.0000001 (шум записи; искажение окружности R10 — 1e-6 мм) — окружность должна
    остаться Circle, дуги — точными, а не ломаной из 128 отрезков."""
    blk = BLOCK("P", RECT(0, 0, 100, 50) + CIRCLE((30, 25), 10))
    p = parts_from_dxf(dxf(INSERT("P", (0, 0), 1.0, 1.0000001), blocks=blk), "s.dxf")[0]
    kinds = [s["kind"] for s in p["shapes"][:-1]]
    assert kinds == ["Circle"], "отверстие стало %s (%d вершин)" % (kinds, len(p["shapes"][0].get("verts", [])))


@check
def d07_slit_ending_on_relief_hole_accepted():
    """Прорезь, упёртая в разгрузочное отверстие (типовой элемент листовой детали), — внутренний открытый рез,
    а не DxfError «Т-образное примыкание» (договор: открытые резы внутри детали → LwPolyline/Line слоя 1)."""
    msg = err_of(dxf(RECT(0, 0, 200, 100) + CIRCLE((50, 72), 2) + LINE((50, 20), (50, 70))))
    assert msg is None, msg


def main():
    fails = 0
    t0 = time.time()
    for fn in CHECKS:
        try:
            fn()
            print("ok    %s" % fn.__name__)
        except Exception as ex:                          # noqa: BLE001
            fails += 1
            print("FAIL  %s — %s" % (fn.__name__, (fn.__doc__ or "").strip().splitlines()[0]))
            print("      %s: %s" % (type(ex).__name__, str(ex)[:400]))
            if not isinstance(ex, AssertionError):
                traceback.print_exc()
    print("итого: %d из %d прошли (%.1f с)" % (len(CHECKS) - fails, len(CHECKS), time.time() - t0))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
