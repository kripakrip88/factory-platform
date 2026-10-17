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
    if s["flag"] & 1:
        # замкнутая полилиния режется от вершины sp (у контуров групп общего реза sp ≠ 0; у остальных 0)
        k = int(round(s.get("sp") or 0)) % len(s["verts"])
        a = tuple(s["verts"][k][:2])
        return a, a
    return tuple(s["verts"][0][:2]), tuple(s["verts"][-1][:2])


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
    # бит 2 флага у открытой полилинии следит за её ориентацией (заводские прорези: 120/132) — разворот его меняет
    t["flag"] = s["flag"] ^ 2
    return t


def rotate_start(s, k):
    """Замкнутый контур с точкой врезки в вершине k (полилиния) или под углом k (окружность, рад)."""
    t = dict(s)
    if s["kind"] == "Circle":
        t["a0"] = float(k) % (2 * math.pi)
    else:
        t["verts"] = s["verts"][k:] + s["verts"][:k]
        t["sp"] = 0.0
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


class Poly(list):
    """Объединение частей — общий контур моста: точки контура (хордами, для габарита и картинки) и части: окружности
    деталей ("c", cx, cy, r) и прямоугольники перемычек между окружностями ("r", [4 точки]). Внутри, глубина и
    препятствие (risk) считаются по частям — окружности точно, как у отдельной шайбы (по хордам пять окружностей —
    ~180 рёбер на каждый переход: m14 с мостами считался в 6 раз дольше)."""

    def __init__(self, pts, parts):
        super().__init__(pts)
        self.parts = parts


def _part_depth(pt, q):
    if q[0] == "c":
        return q[3] - math.hypot(pt[0] - q[1], pt[1] - q[2])
    P = q[1]
    d = min(seg_point_dist(pt, P[i - 1], P[i]) for i in range(len(P)))
    return d if inside(pt, P) else -d


def far_from_edges(pt, poly, m):
    """Точка дальше m от кромки многоугольника (после inside — глубже m внутри: min(расстояние до рёбер) > m); у
    объединения (Poly) — глубже m в одной из частей."""
    if type(poly) is Poly:
        return any(_part_depth(pt, q) > m for q in poly.parts)
    return min(seg_point_dist(pt, poly[i - 1], poly[i]) for i in range(len(poly))) > m


def inside(pt, poly):
    """Точка внутри многоугольника (чётность пересечений); объединение (Poly) — внутри одной из частей."""
    x, y = pt
    c = False
    if not poly:
        return c
    if type(poly) is Poly:
        return any((math.hypot(x - q[1], y - q[2]) < q[3]) if q[0] == "c" else inside(pt, q[1]) for q in poly.parts)
    x2, y2 = poly[-1]                                   # те же пары (i, i − 1) в том же порядке — без индексов
    for x1, y1 in poly:
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
        x2, y2 = x1, y1
    return c


def seg_point_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    L2 = ax * ax + ay * ay
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / L2))
    return math.dist(p, (a[0] + t * ax, a[1] + t * ay))


# ============================================================================== разрыв внешнего контура (16.10.2026)
HEAL_TOL = 0.02             # мм: замыкающий участок «на прямой самого контура» — конец на этой прямой с таким допуском
HEAL_ZERO = 0.01            # мм: концы ближе — совпали (контур замкнут, не помечен только признак): замкнуть всегда


def _closing_clear(R):
    """Замкнутый контур R (вершины, последний участок R[-1] → R[0] — замыкающая прямая): замыкающая прямая не касается
    и не пересекает остальные участки контура (кроме двух соседних) — контур остаётся простым."""
    P = points(dict(kind="LwPolyline", verts=R, flag=1), 0.05)
    a, b = P[-1], P[0]
    n = len(P)
    for i in range(1, n - 2):                           # участки P[i] → P[i+1], не соседние с замыкающим
        if _seg_seg_dist(a, b, P[i], P[i + 1]) < 1e-6:
            return False
    return True


def _seg_seg_dist(a, b, c, d):
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    if o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0:
        return 0.0
    return min(seg_point_dist(a, c, d), seg_point_dist(b, c, d), seg_point_dist(c, a, b), seg_point_dist(d, a, b))


def heal_open(verts, gap_max, tol=HEAL_TOL):
    """Внешний контур, который не замкнули (открытая полилиния, вершины [(x, y, bulge)]): закрыть прямой, если концы не
    дальше gap_max мм и замыкающий участок лежит на прямой самого контура — продолжает первый или последний прямой
    участок (или наезжает на него: конец лежит на первом участке — тогда лишний кусок начала срезается, и наоборот), либо
    идёт по краю габарита контура — и не задевает остальной контур (контур остаётся простым). Решётки 16.10: у одной
    решётки нижняя кромка начата на 16 мм дальше конца (конец лежит на первом участке) — срез начала даёт тот же контур,
    что у остальных решёток. Концы ближе HEAL_ZERO — совпали: замкнуть без нового участка при любом gap_max (и 0).
    Вернуть (вершины замкнутого контура | None, разрыв мм). None — закрыть прямой нельзя (разрыв больше, косой, на дуге,
    замыкающая прямая задевает контур)."""
    V = [(float(v[0]), float(v[1]), float(v[2])) for v in verts]
    n = len(V)
    if n < 3:
        return None, None
    a, z = V[0][:2], V[-1][:2]
    g = math.dist(a, z)
    if g <= HEAL_ZERO:                                  # концы совпали — замкнуть без нового участка
        return V[:-1], g
    if g > gap_max + 1e-9:
        return None, g
    R = _heal_line(V, a, z, tol)
    return (R if R is not None and _closing_clear(R) else None), g


def _on_line(p, q, r, tol):
    """r на прямой pq (с допуском tol)."""
    L = math.dist(p, q)
    return L > 1e-9 and abs((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])) / L <= tol


def _t_of(p, q, r):
    """Место проекции r на pq (0 — p, 1 — q)."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    return ((r[0] - p[0]) * dx + (r[1] - p[1]) * dy) / (dx * dx + dy * dy)


def simple(P, eps=1e-6):
    """Замкнутая ломаная P (точки) без самопересечений и касаний несоседних звеньев (сетка — не все пары)."""
    n = len(P)
    if n < 3:
        return False
    E = [(P[i], P[(i + 1) % n]) for i in range(n)]
    x0, y0 = min(p[0] for p in P), min(p[1] for p in P)
    span = max(max(p[0] for p in P) - x0, max(p[1] for p in P) - y0, 1e-9)
    cs = max(span / max(1, int(math.sqrt(n))), 1e-6)
    grid = {}
    for i, (a, b) in enumerate(E):
        for gx in range(int((min(a[0], b[0]) - x0) / cs), int((max(a[0], b[0]) - x0) / cs) + 1):
            for gy in range(int((min(a[1], b[1]) - y0) / cs), int((max(a[1], b[1]) - y0) / cs) + 1):
                grid.setdefault((gx, gy), []).append(i)
    seen = set()
    for ids in grid.values():
        for u in range(len(ids)):
            for v in range(u + 1, len(ids)):
                i, j = ids[u], ids[v]
                if abs(i - j) in (0, 1, n - 1) or (i, j) in seen:
                    continue
                seen.add((i, j))
                if _seg_seg_dist(E[i][0], E[i][1], E[j][0], E[j][1]) < eps:
                    return False
    return True


def heal_ring(chains, gap_max, tol=HEAL_TOL):
    """Внешний контур из кусков (17.10.2026, «склейка кусков»): куски по кругу — вершины [(x, y, bulge)], конец i-го
    куска → начало (i+1)-го через промежуток. Каждый промежуток закрыть — по правилам heal_open: не больше gap_max и на
    прямой самого контура: продолжает прямой участок у одного из концов (закрыть прямой), идёт по краю габарита контура
    (прямой) или внахлёст — конец лежит на прямом участке соседа (у зольника 31.10.25 кромка корпуса заходит на 2 мм за
    угол отбортовки): контур обрезается по этой точке, а заходящий кусочек возвращается отдельным резом (его не
    теряем: внутри детали он режется, как в программе; на самом контуре — дубль, его отбросит вызывающий). Концы ближе
    HEAL_ZERO — совпали, без нового участка. Контур после этого простой (прямые и куски не задевают друг друга).
    Вернуть (вершины замкнутого контура | None, [промежутки, мм], почему нет | None, [кусочки внахлёст (p, q)],
    [как закрыт каждый промежуток: "zero" | "line" | "trim_end" | "trim_start"]):
    ("line", i) — i-й промежуток не на прямой контура, ("big", i) — все на прямой, i-й (наибольший) больше gap_max,
    ("cross", None) — прямые задели бы контур."""
    n = len(chains)
    C = [[(float(v[0]), float(v[1]), float(v[2])) for v in c] for c in chains]
    gaps = [math.dist(C[i][-1][:2], C[(i + 1) % n][0][:2]) for i in range(n)]
    x0, y0, x1, y1 = bbox([dict(kind="LwPolyline", verts=c, flag=0) for c in C])
    mode, rest = [None] * n, []
    for i in range(n):
        c, nxt = C[i], C[(i + 1) % n]
        z, a = c[-1][:2], nxt[0][:2]
        if gaps[i] <= HEAL_ZERO:
            mode[i] = "zero"
            continue
        last = len(c) >= 2 and abs(c[-2][2]) < 1e-12 and _on_line(c[-2][:2], z, a, tol)
        first = len(nxt) >= 2 and abs(nxt[0][2]) < 1e-12 and _on_line(a, nxt[1][:2], z, tol)
        if last and _t_of(c[-2][:2], z, a) >= 1 or first and _t_of(a, nxt[1][:2], z) <= 0 or \
                any(abs(z[k] - e) <= tol and abs(a[k] - e) <= tol for k, e in ((0, x0), (0, x1), (1, y0), (1, y1))):
            mode[i] = "line"
        elif last and 0 < _t_of(c[-2][:2], z, a) < 1:             # начало соседа — на последнем участке: обрезать конец
            mode[i] = "trim_end"
        elif first and 0 < _t_of(a, nxt[1][:2], z) < 1:           # конец — на первом участке соседа: обрезать его начало
            mode[i] = "trim_start"
    bad = [i for i in range(n) if mode[i] is None]
    if bad:
        return None, gaps, ("line", bad[0]), [], mode
    i = max(range(n), key=lambda k: gaps[k])
    if gaps[i] > max(gap_max, HEAL_ZERO) + 1e-9:
        return None, gaps, ("big", i), [], mode
    for i in range(n):
        c, nxt = C[i], C[(i + 1) % n]
        z, a = c[-1][:2], nxt[0][:2]
        if mode[i] == "trim_end":
            c[-1] = (a[0], a[1], 0.0)
            rest.append((a, z))
        elif mode[i] == "trim_start":
            nxt[0] = (z[0], z[1], nxt[0][2])
            rest.append((a, z))
    V = []
    for i in range(n):
        c = C[i]
        if mode[i] == "line":
            V += c[:-1] + [(c[-1][0], c[-1][1], 0.0)]   # замыкающая прямая — от конца куска к началу следующего
        else:
            V += c[:-1]                                 # конец совпал с началом следующего (или обрезан до него)
    if len(V) < 3 or not simple(points(dict(kind="LwPolyline", verts=V, flag=1), 0.05)):
        return None, gaps, ("cross", None), [], mode
    return V, gaps, None, rest, mode


def _heal_line(V, a, z, tol):
    """heal_open: замкнутый контур с замыкающей прямой на прямой самого контура или None."""

    def on_line(p, q, r):                               # r на прямой pq
        L = math.dist(p, q)
        return L > 1e-9 and abs((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])) / L <= tol

    def t_of(p, q, r):                                  # место проекции r на pq (0 — p, 1 — q)
        dx, dy = q[0] - p[0], q[1] - p[1]
        return ((r[0] - p[0]) * dx + (r[1] - p[1]) * dy) / (dx * dx + dy * dy)
    closed = V[:-1] + [(z[0], z[1], 0.0)]                # замыкающий участок z → a — прямая
    if abs(V[0][2]) < 1e-12 and on_line(a, V[1][:2], z):            # на прямой первого участка a → v1
        t = t_of(a, V[1][:2], z)
        if 0 < t < 1:                                   # конец на первом участке — нахлёст: начало срезается
            return V[1:-1] + [(z[0], z[1], 0.0)]
        if t <= 0:                                      # продолжает первый участок
            return closed
    if abs(V[-2][2]) < 1e-12 and on_line(V[-2][:2], z, a):          # на прямой последнего участка v(n−2) → z
        t = t_of(V[-2][:2], z, a)
        if 0 < t < 1:                                   # начало на последнем участке — нахлёст: конец срезается
            return V[:-1]
        if t >= 1:                                      # продолжает последний участок
            return closed
    x0, y0, x1, y1 = bbox([dict(kind="LwPolyline", verts=V, flag=0)])
    for k, e in ((0, x0), (0, x1), (1, y0), (1, y1)):  # по краю габарита
        if abs(a[k] - e) <= tol and abs(z[k] - e) <= tol:
            return closed
    return None
