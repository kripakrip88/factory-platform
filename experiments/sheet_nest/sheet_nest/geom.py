# -*- coding: utf-8 -*-
"""Геометрия фигур CypCut (формат spec_rebuild): концы, разворот, точки по контуру, габарит, площадь, повороты."""
import math

ROT = {0: lambda x, y: (x, y), 90: lambda x, y: (-y, x), 180: lambda x, y: (-x, -y), 270: lambda x, y: (y, -x)}


def is_closed(s):
    return s["kind"] == "Circle" or (s["kind"] == "LwPolyline" and bool(s["flag"] & 1))


def is_open(s):
    return not is_closed(s)


def ends(s):
    """(точка врезки, точка выхода) в порядке записи. У замкнутого контура совпадают."""
    if s["kind"] == "Line":
        return tuple(s["p1"]), tuple(s["p2"])
    if s["kind"] == "Circle":
        p = (s["c"][0] + s["r"] * math.cos(s["a0"]), s["c"][1] + s["r"] * math.sin(s["a0"]))
        return p, p
    a = tuple(s["verts"][0][:2])
    return (a, a) if s["flag"] & 1 else (a, tuple(s["verts"][-1][:2]))


def reverse(s):
    """Открытый контур, пройденный в обратную сторону (дуга: bulge сегмента меняет знак)."""
    t = dict(s)
    if s["kind"] == "Line":
        t["p1"], t["p2"] = s["p2"], s["p1"]
        return t
    if s["kind"] != "LwPolyline" or s["flag"] & 1:
        raise ValueError("разворачивается только открытый контур")
    v = s["verts"]
    n = len(v)
    t["verts"] = [(v[n - 1 - k][0], v[n - 1 - k][1], (-v[n - 2 - k][2] if k < n - 1 else 0.0)) for k in range(n)]
    return t


def rotate_start(s, k):
    """Замкнутый контур с точкой врезки в вершине k (полилиния) или под углом k (окружность, рад)."""
    t = dict(s)
    if s["kind"] == "Circle":
        t["a0"] = float(k) % (2 * math.pi)
    else:
        t["verts"] = s["verts"][k:] + s["verts"][:k]
    return t


def bulge_center(p1, p2, b):
    """Центр, радиус, угол дуги со знаком для сегмента p1→p2 с bulge b (b ≠ 0)."""
    th = 4 * math.atan(b)
    ch = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    r = ch / (2 * math.sin(abs(th) / 2))
    dd = ch / 2 * (1 - b * b) / (2 * b)
    cx = (p1[0] + p2[0]) / 2 - (p2[1] - p1[1]) / ch * dd
    cy = (p1[1] + p2[1]) / 2 + (p2[0] - p1[0]) / ch * dd
    return (cx, cy), r, th


def arc_steps(r, th, sag=0.02):
    """Число хорд для дуги радиуса r и угла th с прогибом не больше sag мм."""
    if r <= sag:
        return 1
    a = 2 * math.acos(max(-1.0, 1 - sag / r))
    return max(1, int(math.ceil(abs(th) / a)))


def points(s, sag=0.02):
    """Точки по контуру (дуги — хордами с прогибом ≤ sag). Замкнутый — без повтора первой точки."""
    if s["kind"] == "Line":
        return [tuple(s["p1"]), tuple(s["p2"])]
    if s["kind"] == "Circle":
        n = max(8, arc_steps(s["r"], 2 * math.pi, sag))
        return [(s["c"][0] + s["r"] * math.cos(s["a0"] + 2 * math.pi * k / n), s["c"][1] + s["r"] * math.sin(s["a0"] + 2 * math.pi * k / n))
                for k in range(n)]
    v = s["verts"]
    closed = bool(s["flag"] & 1)
    out = []
    m = len(v) if closed else len(v) - 1
    for i in range(m):
        x1, y1, b = v[i]
        x2, y2, _ = v[(i + 1) % len(v)]
        out.append((x1, y1))
        if abs(b) > 1e-12 and math.hypot(x2 - x1, y2 - y1) > 1e-12:
            (cx, cy), r, th = bulge_center((x1, y1), (x2, y2), b)
            a1 = math.atan2(y1 - cy, x1 - cx)
            n = arc_steps(r, th, sag)
            for k in range(1, n):
                a = a1 + th * k / n
                out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    if not closed:
        out.append(tuple(v[-1][:2]))
    return out


def _arc_extremes(p1, p2, b):
    """Крайние по осям точки дуги p1→p2 (bulge b): концы + точки 0°/90°/180°/270°, попавшие в дугу."""
    (cx, cy), r, th = bulge_center(p1, p2, b)
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    out = [p1, p2]
    for k in range(4):
        a = k * math.pi / 2
        d = (a - a1) % (2 * math.pi) if th > 0 else (a1 - a) % (2 * math.pi)
        if d <= abs(th) + 1e-12:
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def bbox(shapes, sag=None):
    """Точный габарит (окружность — по радиусу, дуга — по крайним точкам; не по хордам)."""
    P = []
    for s in shapes:
        if s["kind"] == "Line":
            P += [tuple(s["p1"]), tuple(s["p2"])]
        elif s["kind"] == "Circle":
            P += [(s["c"][0] - s["r"], s["c"][1] - s["r"]), (s["c"][0] + s["r"], s["c"][1] + s["r"])]
        else:
            v = s["verts"]
            m = len(v) if s["flag"] & 1 else len(v) - 1
            P += [tuple(q[:2]) for q in v]
            for i in range(m):
                x1, y1, b = v[i]
                x2, y2, _ = v[(i + 1) % len(v)]
                if abs(b) > 1e-12 and math.hypot(x2 - x1, y2 - y1) > 1e-12:
                    P += _arc_extremes((x1, y1), (x2, y2), b)
    if not P:
        raise ValueError("пустая деталь")
    return min(p[0] for p in P), min(p[1] for p in P), max(p[0] for p in P), max(p[1] for p in P)


def poly_area(verts):
    """Площадь со знаком замкнутой полилинии с дугами (+ — против часовой)."""
    n = len(verts)
    A = 0.0
    for i in range(n):
        x1, y1, b = verts[i]
        x2, y2, _ = verts[(i + 1) % n]
        A += (x1 * y2 - x2 * y1) / 2
        if b:
            th = 4 * math.atan(b)
            ch = math.hypot(x2 - x1, y2 - y1)
            if ch > 0:
                r = ch / (2 * math.sin(abs(th) / 2))
                A += math.copysign(r * r / 2 * (abs(th) - math.sin(abs(th))), b)
    return A


def area(s):
    if s["kind"] == "Circle":
        return math.pi * s["r"] ** 2
    if s["kind"] == "LwPolyline" and s["flag"] & 1:
        return abs(poly_area(s["verts"]))
    return 0.0


def length(s):
    if s["kind"] == "Line":
        return math.dist(s["p1"], s["p2"])
    if s["kind"] == "Circle":
        return 2 * math.pi * s["r"]
    v = s["verts"]
    m = len(v) if s["flag"] & 1 else len(v) - 1
    t = 0.0
    for i in range(m):
        a, c = v[i], v[(i + 1) % len(v)]
        ch = math.hypot(c[0] - a[0], c[1] - a[1])
        if abs(a[2]) > 1e-12 and ch > 1e-12:
            th = abs(4 * math.atan(a[2]))
            t += ch / (2 * math.sin(th / 2)) * th
        else:
            t += ch
    return t


def transform(s, rot, d):
    """Поворот на rot (0/90/180/270, против часовой вокруг начала координат детали) и сдвиг d."""
    t = dict(s)
    f = ROT[rot]
    if s["kind"] == "Line":
        a, b = f(*s["p1"]), f(*s["p2"])
        t.update(p1=(a[0] + d[0], a[1] + d[1]), p2=(b[0] + d[0], b[1] + d[1]))
    elif s["kind"] == "Circle":
        c = f(*s["c"])
        t.update(c=(c[0] + d[0], c[1] + d[1]), a0=(s["a0"] + math.radians(rot)) % (2 * math.pi) if rot else s["a0"])
    else:
        t["verts"] = [(f(x, y)[0] + d[0], f(x, y)[1] + d[1], b) for x, y, b in s["verts"]]
    return t


def translate(s, dx, dy):
    return transform(s, 0, (dx, dy))


def inside(pt, poly):
    """Точка внутри многоугольника (чётность пересечений)."""
    x, y = pt
    c = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def seg_point_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    L2 = ax * ax + ay * ay
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L2))
    return math.dist(p, (a[0] + t * ax, a[1] + t * ay))
