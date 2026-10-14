# -*- coding: utf-8 -*-
"""Опасные холостые переходы головки (решения Антона 13.10.2026): классы, счёт по маршруту листа, ключ стратегии.

Переход (от конца реза к следующей врезке) опасен, если идёт:
  • «язычки»     — над вырезанным язычком прорези (открытый рез, замкнутый по хорде): может отогнуться вверх;
  • «мелкие»     — над освобождённой мелкой деталью: меньше SMALL мм по одной из сторон габарита — встаёт между
                   ламелями при любой толщине (лист проваливается и при 0,5, и при 30 мм между ламелями);
  • «детали»     — над другой освобождённой деталью (может встать на ребро);
  • «отверстия»  — над вырезанным отверстием, куда проваливается сопло: диаметр вписанной окружности ≥ HOLE_MIN
                   (у паза — его ширина, не 4·площадь/периметр); меньше — «отверстия < 10», только в отчёт;
  • «впритирку»  — ближе NEAR к освобождённой детали, но не над ней (без первых и последних NEAR_SKIP мм перехода:
                   уход от только что вырезанного контура и подход к врезке у соседки — не в счёт).
В отчёт также: «короткие» (< SHORT_MOVE: CypCut может идти без подъёма — «Short move unlift»), «с перемычками»
(над освобождённой деталью с микроперемычками) и возврат головки в ноль после листа (настройка станка, не в .lxds).
Переход программы в каждом классе — 0/1 (move); возврат в ноль идёт над всем готовым листом — в классе число объектов
под ним (ret_move, решение инженера 14.10.2026).
Детали с микроперемычками (part["microjoints"]) держатся в листе — правила освобождённых деталей к ним не применяются;
их отверстия и язычки опасны, как у невырезанных. Деталь освобождена после последнего куска своего внешнего контура
(в группе общего реза — после своей последней цепочки).
«Над» = на пути ≥ MIN_OVER мм глубже DEEP_PART (детали) / DEEP_CUT (отверстия, язычки) от кромки внутри фигуры.
Модуль не знает устройства маршрута: на входе — фигуры в порядке резки с номером размещения.
"""
import math, heapq, functools, collections, itertools
from . import geom as G

HOLE_MIN = 10.0      # мм: отверстие, куда проваливается сопло (диаметр вписанной окружности)
SMALL = 100.0        # мм: деталь меньше по одной из сторон габарита — «мелкая» (встаёт между ламелями)
NEAR = 5.0           # мм: ближе к освобождённой детали — сопло над её кромкой
NEAR_SKIP = 10.0     # мм: начало и конец перехода в «впритирку» не считаются
NEAR_COST = 500.0    # мм холостого, которые «стоит» один переход впритирку в ключе безопасных стратегий
SHORT_MOVE = 10.0    # мм: короткий переход
DEEP_PART = 1.0      # мм глубже кромки освобождённой детали — «над ней» (как маршрут: _seg_hits margin 1)
DEEP_CUT = 0.5       # мм глубже кромки отверстия или язычка (как маршрут: crossings margin 0.5)
MIN_OVER = 0.5       # мм пути глубже — переход засчитан
TONGUE_AREA = 1.0    # мм²: открытый рез с площадью «по хорде» меньше — прямая прорезь, язычка нет

# классы перехода: индексы в векторе
TONGUE, SMALLP, PART, HOLE, HOLE_S, NEARP, SHORT, MJ = range(8)
CLASSES = ("tongues", "small", "parts", "holes", "holes_s", "near", "short", "mj")
TITLES = dict(tongues="над язычками", small="над мелкими деталями", parts="над деталями", holes="над отверстиями ≥ %g" % HOLE_MIN,
              holes_s="над отверстиями < %g" % HOLE_MIN, near="впритирку (< %g мм)" % NEAR, short="короткие (< %g мм)" % SHORT_MOVE,
              mj="над деталями с перемычками")
ZERO = (0,) * 8
D = math.dist


def safe_key(v, idle):
    """Ключ безопасных стратегий (по порядку): язычки, мелкие детали, прочие детали, отверстия ≥ HOLE_MIN,
    холостой ход + NEAR_COST за каждый переход впритирку."""
    return (v[TONGUE], v[SMALLP], v[PART], v[HOLE], idle + NEAR_COST * v[NEARP])


def vadd(a, b):
    return tuple(x + y for x, y in zip(a, b))


def vsub(a, b):
    return tuple(x - y for x, y in zip(a, b))


# ================================================================================ фигуры-препятствия
def _bbox(P):
    return (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P))


def obstacle(s, sag=0.2):
    """Фигура → препятствие (точки, габарит, окружность (cx, cy, r) | None). Окружность считается точно."""
    if s["kind"] == "Circle":
        cx, cy, r = s["c"][0], s["c"][1], s["r"]
        return (None, (cx - r, cy - r, cx + r, cy + r), (cx, cy, r))
    P = G.points(s, sag)
    if s.get("_bridge") is not None:                    # общий контур моста — объединение окружностей и перемычек
        P = G.Poly(P, s["_bridge"].parts())
    return (P, _bbox(P), None)


def _subs(P):
    """Части объединения (G.Poly) — препятствия: окружности точно, перемычки — прямоугольники (кэш в объекте)."""
    sub = getattr(P, "_subs", None)
    if sub is None:
        sub = []
        for q in P.parts:
            if q[0] == "c":
                sub.append((None, (q[1] - q[3], q[2] - q[3], q[1] + q[3], q[2] + q[3]), (q[1], q[2], q[3])))
            else:
                sub.append((q[1], _bbox(q[1]), None))
        P._subs = sub
    return sub


def _area(P):
    return abs(sum(P[i - 1][0] * P[i][1] - P[i][0] * P[i - 1][1] for i in range(len(P)))) / 2


@functools.lru_cache(maxsize=8192)
def _inscribed(rel):
    """Диаметр вписанной окружности многоугольника (точки относительно первой) — «полюс недоступности»
    (ячейки квадродерева, как polylabel), точность 0,02 мм."""
    P = list(rel)
    x0, y0, x1, y1 = _bbox(P)
    size = min(x1 - x0, y1 - y0)
    if size <= 0:
        return 0.0
    edges = list(zip(P, P[1:] + P[:1]))

    def sd(x, y):                                            # + внутри, − снаружи
        d = min(G.seg_point_dist((x, y), a, b) for a, b in edges)
        return d if G.inside((x, y), P) else -d
    h = size / 2
    heap, best = [], None
    x = x0
    while x < x1:
        y = y0
        while y < y1:
            c = (x + h, y + h); d = sd(*c)
            heapq.heappush(heap, (-(d + h * math.sqrt(2)), d, c, h))
            y += size
        x += size
    cx, cy = sum(p[0] for p in P) / len(P), sum(p[1] for p in P) / len(P)
    best = (sd(cx, cy), (cx, cy))
    while heap:
        negmax, d, c, h = heapq.heappop(heap)
        if d > best[0]:
            best = (d, c)
        if -negmax - best[0] <= 0.01:
            continue
        h /= 2
        for dx in (-h, h):
            for dy in (-h, h):
                cc = (c[0] + dx, c[1] + dy); dd = sd(*cc)
                heapq.heappush(heap, (-(dd + h * math.sqrt(2)), dd, cc, h))
    return 2 * max(0.0, best[0])


def inscribed_d(s):
    """Диаметр вписанной окружности замкнутого контура (окружность — 2r; паз — его ширина). Для отчёта и тестов: у
    длинного паза поиск идёт по всей длине (секунды) — классу отверстия он не нужен (wide)."""
    if s["kind"] == "Circle":
        return 2 * s["r"]
    P = G.points(s, 0.02)
    x0, y0 = P[0]
    return _inscribed(tuple((round(x - x0, 5), round(y - y0, 5)) for x, y in P))


@functools.lru_cache(maxsize=8192)
def _wide(rel, r, tol=0.005):
    """Помещается ли в многоугольник (точки относительно первой) круг радиуса r: ячейки квадродерева (как polylabel)
    только до ответа — нашлась точка внутри дальше r − tol от кромки — да; у всех ячеек верхняя граница меньше r + tol —
    нет. Ответ точен до ±tol по радиусу; у паза — несколько ячеек на миллиметр длины, а не до 0,01 мм по всей длине."""
    P = list(rel)
    x0, y0, x1, y1 = _bbox(P)
    size = min(x1 - x0, y1 - y0)
    if size < 2 * (r - tol):
        return False
    edges = list(zip(P, P[1:] + P[:1]))

    def sd(x, y):                                            # + внутри, − снаружи
        d = min(G.seg_point_dist((x, y), a, b) for a, b in edges)
        return d if G.inside((x, y), P) else -d
    lo, hi = r - tol, r + tol
    heap = []
    h = size / 2
    x = x0
    while x < x1:
        y = y0
        while y < y1:
            c = (x + h, y + h); d = sd(*c)
            if d >= lo:
                return True
            if d + h * math.sqrt(2) >= hi:
                heapq.heappush(heap, (-(d + h * math.sqrt(2)), c, h))
            y += size
        x += size
    while heap:
        _, c, h = heapq.heappop(heap)
        h /= 2
        for dx in (-h, h):
            for dy in (-h, h):
                cc = (c[0] + dx, c[1] + dy); dd = sd(*cc)
                if dd >= lo:
                    return True
                if dd + h * math.sqrt(2) >= hi:
                    heapq.heappush(heap, (-(dd + h * math.sqrt(2)), cc, h))
    return False


def _shape_key(s):
    """Форма замкнутого контура без положения и начала: вершины (с выпуклостями) от наименьшей, относительно неё."""
    V = s["verts"]
    k0 = min(range(len(V)), key=lambda k: (V[k][0], V[k][1]))
    x0, y0 = V[k0][0], V[k0][1]
    return tuple((round(V[(k0 + j) % len(V)][0] - x0, 5), round(V[(k0 + j) % len(V)][1] - y0, 5), round(V[(k0 + j) % len(V)][2], 9))
                 for j in range(len(V)))


_BIG = {}


def hole_big(s):
    """Отверстие ≥ HOLE_MIN (сопло проваливается): вписанная окружность ≥ HOLE_MIN − 0,05 мм. Окружность — по радиусу;
    многоугольник — сперва меньшая сторона габарита (вписанная не больше), затем поиск до ответа (_wide). Кэш — по
    форме (поворот начала и сдвиг детали — та же форма)."""
    if s["kind"] == "Circle":
        return 2 * s["r"] >= HOLE_MIN - 0.05
    bx = G.bbox([s])                                                 # точный габарит (дуги — по крайним точкам)
    if min(bx[2] - bx[0], bx[3] - bx[1]) < HOLE_MIN - 0.05:
        return False
    k = _shape_key(s)
    if k not in _BIG:
        P = G.points(s, 0.02)
        x0, y0 = P[0]
        if len(_BIG) > 20000:
            _BIG.clear()
        _BIG[k] = _wide(tuple((round(x - x0, 5), round(y - y0, 5)) for x, y in P), (HOLE_MIN - 0.05) / 2)
    return _BIG[k]


def feature(s):
    """Что остаётся вырезанным внутри детали после фигуры s: ("holes" | "holes_s" | "tongues", препятствие) или None.
    Отверстие — замкнутый внутренний контур слоя реза; язычок — открытый рез слоя реза (не цепочка общего реза),
    замкнутый по хорде, площадью ≥ TONGUE_AREA (дуговая прорезь из двух вершин — тоже)."""
    if s.get("layer") != 1 or s.get("outer"):
        return None
    if G.is_closed(s):
        return ("holes" if hole_big(s) else "holes_s", obstacle(s))
    if s["kind"] == "LwPolyline" and not s.get("coedge"):
        P = G.points(s, 0.2)
        if len(P) >= 3 and _area(P) >= TONGUE_AREA:
            return ("tongues", (P, _bbox(P), None))
    return None


def part_kind(part, small=SMALL):
    """Класс детали после освобождения: "mj" (микроперемычки — держится), "small" (меньше small по одной из сторон
    габарита), "parts"."""
    if part.get("microjoints"):
        return "mj"
    x0, y0, x1, y1 = G.bbox([part["shapes"][-1]])
    return "small" if min(x1 - x0, y1 - y0) < small else "parts"


# ================================================================================ сетка для быстрого поиска
class Grid:
    """Препятствия по ячейкам листа: запрос по прямоугольнику — те, чей габарит в него попадает (порядок добавления)."""

    def __init__(self, cell=100.0):
        self.cell, self.cells, self.items = cell, collections.defaultdict(list), []

    def __len__(self):
        return len(self.items)

    def add(self, item, bx):
        k = len(self.items)
        self.items.append((item, bx))
        c = self.cell
        for i in range(int(math.floor(bx[0] / c)), int(math.floor(bx[2] / c)) + 1):
            for j in range(int(math.floor(bx[1] / c)), int(math.floor(bx[3] / c)) + 1):
                self.cells[(i, j)].append(k)

    def query(self, x0, y0, x1, y1):
        if not self.items:
            return []
        c, cells, items = self.cell, self.cells, self.items
        i0, i1, j0, j1 = int(math.floor(x0 / c)), int(math.floor(x1 / c)), int(math.floor(y0 / c)), int(math.floor(y1 / c))
        if i0 == i1 and j0 == j1:
            ks = cells.get((i0, j0), ())                     # одна ячейка — уже по порядку добавления
        else:
            ks = set()
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    v = cells.get((i, j))
                    if v:
                        ks.update(v)
            ks = sorted(ks)
        out = []
        for k in ks:
            item, bx = items[k]
            if not (bx[2] < x0 or bx[0] > x1 or bx[3] < y0 or bx[1] > y1):
                out.append(item)
        return out


# ================================================================================ один переход
def _inside_runs(a, b, P):
    """Участки отрезка a→b внутри многоугольника P: [(t0, t1)] в мм от a."""
    L = D(a, b)
    dx, dy = b[0] - a[0], b[1] - a[1]
    ts = [0.0, L]
    n = len(P)
    for i in range(n):
        p, q = P[i - 1], P[i]
        ex, ey = q[0] - p[0], q[1] - p[1]
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        t = ((p[0] - a[0]) * ey - (p[1] - a[1]) * ex) / den
        u = ((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / den
        if 0.0 < t < 1.0 and -1e-12 <= u <= 1.0 + 1e-12:
            ts.append(t * L)
    ts.sort()
    out = []
    for t0, t1 in zip(ts, ts[1:]):
        if t1 - t0 < 1e-9:
            continue
        m = (t0 + t1) / 2 / L
        if G.inside((a[0] + dx * m, a[1] + dy * m), P):
            if out and abs(out[-1][1] - t0) < 1e-9:
                out[-1] = (out[-1][0], t1)
            else:
                out.append((t0, t1))
    return out


def _capsule(a, u, p, q, m):
    """Участок прямой a + t·u (t в мм, u — единичный) ближе m к отрезку p–q: (t0, t1) или None. Капсула выпуклая —
    участок один: объединение участков двух кругов у концов и полосы вдоль отрезка."""
    ivs = []
    for c in (p, q):
        wx, wy = a[0] - c[0], a[1] - c[1]
        bb = wx * u[0] + wy * u[1]
        disc = bb * bb - (wx * wx + wy * wy - m * m)
        if disc >= 0:
            r = math.sqrt(disc)
            ivs.append((-bb - r, -bb + r))
    ex, ey = q[0] - p[0], q[1] - p[1]
    L = math.hypot(ex, ey)
    if L > 1e-12:
        ex, ey = ex / L, ey / L
        lo, hi = -math.inf, math.inf
        for dx, dy, v0, v1 in ((ex, ey, 0.0, L), (-ey, ex, -m, m)):
            s0 = (a[0] - p[0]) * dx + (a[1] - p[1]) * dy
            s1 = u[0] * dx + u[1] * dy
            if abs(s1) < 1e-12:
                if not (v0 <= s0 <= v1):
                    lo, hi = 1.0, 0.0
            else:
                ta, tb = (v0 - s0) / s1, (v1 - s0) / s1
                if ta > tb:
                    ta, tb = tb, ta
                lo, hi = max(lo, ta), min(hi, tb)
        if lo <= hi:
            ivs.append((lo, hi))
    if not ivs:
        return None
    return min(i[0] for i in ivs), max(i[1] for i in ivs)


def deep_len(a, b, ob, margin):
    """Длина пути a→b глубже margin внутри препятствия — точно: окружность — по хорде круга радиуса r − margin;
    многоугольник — участки внутри минус участки ближе margin к его рёбрам (капсулы)."""
    P, bx, circ = ob
    L = D(a, b)
    if L < 1e-9:
        return 0.0
    if type(P) is G.Poly:                               # объединение (мост): по частям — окружности не пересекаются,
        return sum(deep_len(a, b, q, margin) for q in _subs(P))    # перемычки между ними (наложение < 0,01 мм)
    if circ:
        cx, cy, r = circ
        rr = r - margin
        if rr <= 0:
            return 0.0
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        t0 = (cx - a[0]) * ux + (cy - a[1]) * uy
        d2 = (cx - a[0]) ** 2 + (cy - a[1]) ** 2 - t0 * t0
        if d2 >= rr * rr:
            return 0.0
        h = math.sqrt(rr * rr - d2)
        return max(0.0, min(L, t0 + h) - max(0.0, t0 - h))
    runs = _inside_runs(a, b, P)
    if not runs:
        return 0.0
    u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    tot = 0.0
    edges = list(zip(P, P[1:] + P[:1]))
    for t0, t1 in runs:
        # глубина 0 на кромке и 1-липшицева: глубже margin — только дальше margin от концов участка
        if (t1 - (margin if t1 < L - 1e-9 else 0.0)) - (t0 + (margin if t0 > 1e-9 else 0.0)) <= 0:
            continue
        cuts = []
        for p, q in edges:
            c = _capsule(a, u, p, q, margin)
            if c is not None and c[1] > t0 and c[0] < t1:
                cuts.append(c)
        cuts.sort()
        pos = t0
        for c0, c1 in cuts:
            if c0 > pos:
                tot += min(c0, t1) - pos
            pos = max(pos, c1)
            if pos >= t1:
                break
        if pos < t1:
            tot += t1 - pos
    return tot


def inside_len(a, b, ob):
    """Длина пути a→b внутри препятствия (без отступа)."""
    P, bx, circ = ob
    L = D(a, b)
    if L < 1e-9:
        return 0.0
    if type(P) is G.Poly:
        return sum(inside_len(a, b, q) for q in _subs(P))
    if circ:
        return deep_len(a, b, ob, 0.0)
    return sum(t1 - t0 for t0, t1 in _inside_runs(a, b, P))


def _seg_seg(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if orient(q1, q2, p1) * orient(q1, q2, p2) < 0 and orient(p1, p2, q1) * orient(p1, p2, q2) < 0:
        return 0.0
    return min(G.seg_point_dist(p1, q1, q2), G.seg_point_dist(p2, q1, q2), G.seg_point_dist(q1, p1, p2), G.seg_point_dist(q2, p1, p2))


def near_to(a2, b2, ob, near=NEAR):
    """Отрезок a2→b2 ближе near к препятствию (к кромке или внутри)."""
    P, bx, circ = ob
    if type(P) is G.Poly:
        return any(near_to(a2, b2, q, near) for q in _subs(P))
    if circ:
        return G.seg_point_dist((circ[0], circ[1]), a2, b2) < circ[2] + near
    if G.inside(a2, P):
        return True
    lo_x, hi_x = min(a2[0], b2[0]) - near, max(a2[0], b2[0]) + near
    lo_y, hi_y = min(a2[1], b2[1]) - near, max(a2[1], b2[1]) + near
    for i in range(len(P)):
        e1, e2 = P[i - 1], P[i]
        if max(e1[0], e2[0]) < lo_x or min(e1[0], e2[0]) > hi_x or max(e1[1], e2[1]) < lo_y or min(e1[1], e2[1]) > hi_y:
            continue
        if _seg_seg(a2, b2, e1, e2) < near:
            return True
    return False


class Sheet:
    """Вырезанное на листе к данному моменту: освобождённые детали по классам (small, parts, mj) и вырезанное внутри
    не освобождённых, которое там и останется (holes, holes_s, tongues деталей с перемычками). Одна сетка на всё."""

    def __init__(self, cell=100.0):
        self.g = Grid(cell)

    def add(self, kind, ob):
        self.g.add((kind, ob), ob[1])

    def query(self, x0, y0, x1, y1):
        return self.g.query(x0, y0, x1, y1)


IDX = dict(tongues=TONGUE, small=SMALLP, parts=PART, holes=HOLE, holes_s=HOLE_S, mj=MJ)
_MARGIN = dict(small=DEEP_PART, parts=DEEP_PART, mj=DEEP_PART, tongues=DEEP_CUT, holes=DEEP_CUT, holes_s=DEEP_CUT)


def _near(a, b, L, sheet, extra):
    """1 — переход a→b (длиннее 2·NEAR_SKIP) без первых и последних NEAR_SKIP мм ближе NEAR к освобождённой детали."""
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    a2, b2 = (a[0] + ux * NEAR_SKIP, a[1] + uy * NEAR_SKIP), (b[0] - ux * NEAR_SKIP, b[1] - uy * NEAR_SKIP)
    qx0, qx1 = min(a2[0], b2[0]) - NEAR, max(a2[0], b2[0]) + NEAR
    qy0, qy1 = min(a2[1], b2[1]) - NEAR, max(a2[1], b2[1]) + NEAR
    for kind, ob in itertools.chain(sheet.query(qx0, qy0, qx1, qy1), extra):
        if kind not in ("small", "parts"):
            continue
        bx = ob[1]
        if bx[2] < qx0 or bx[0] > qx1 or bx[3] < qy0 or bx[1] > qy1:
            continue
        if near_to(a2, b2, ob):
            return 1
    return 0


def move(a, b, sheet, own=(), extra=()):
    """Вектор классов перехода a→b (8 чисел 0/1). sheet — Sheet; own — [(класс, препятствие)] вырезанного внутри
    ещё не освобождённых деталей; extra — то, чего ещё нет в sheet (освобождённые детали группы и т.п.)."""
    L = D(a, b)
    if L <= 1.0:
        return ZERO if L <= 0.01 else (0, 0, 0, 0, 0, 0, 1, 0)
    v = [0] * 8
    if L < SHORT_MOVE:
        v[SHORT] = 1
    x0, x1 = min(a[0], b[0]), max(a[0], b[0])
    y0, y1 = min(a[1], b[1]), max(a[1], b[1])
    tot = [0.0] * 8
    for kind, ob in itertools.chain(sheet.query(x0, y0, x1, y1), own, extra):
        i = IDX[kind]
        if v[i]:
            continue
        bx = ob[1]
        if bx[2] < x0 or bx[0] > x1 or bx[3] < y0 or bx[1] > y1:
            continue
        tot[i] += deep_len(a, b, ob, _MARGIN[kind])
        if tot[i] >= MIN_OVER - 1e-9:
            v[i] = 1
    if not v[SMALLP] and not v[PART] and L > 2 * NEAR_SKIP + 1e-9:   # середина перехода есть (20 мм + 1e-13 — нет)
        v[NEARP] = _near(a, b, L, sheet, extra)
    return tuple(v)


def ret_move(a, b, sheet, own=(), extra=()):
    """Вектор классов возврата головки в ноль a→b после листа (решение инженера 14.10.2026): возврат идёт над всем
    готовым листом, поэтому у вырезанного (язычки, освобождённые мелкие и прочие детали, отверстия ≥ и < HOLE_MIN,
    детали с перемычками) — не 0/1, как у переходов программы (move), а ЧИСЛО разных объектов, над которыми он прошёл:
    каждый — по тому же правилу глубины (≥ MIN_OVER мм пути глубже _MARGIN). Над несколькими объектами по чуть-чуть,
    но вместе ≥ MIN_OVER — как move, один. Класс ненулевой ровно там, где у move; впритирку и короткий — как у move
    (0/1). Аргументы — как у move; на нём считают и маршрут (динамика, общий рез), и measure (key0)."""
    L = D(a, b)
    if L <= 1.0:
        return ZERO if L <= 0.01 else (0, 0, 0, 0, 0, 0, 1, 0)
    v = [0] * 8
    if L < SHORT_MOVE:
        v[SHORT] = 1
    x0, x1 = min(a[0], b[0]), max(a[0], b[0])
    y0, y1 = min(a[1], b[1]), max(a[1], b[1])
    tot, seen = [0.0] * 8, set()
    for kind, ob in itertools.chain(sheet.query(x0, y0, x1, y1), own, extra):
        if id(ob) in seen:                               # разные объекты: одно препятствие — один раз
            continue
        seen.add(id(ob))
        bx = ob[1]
        if bx[2] < x0 or bx[0] > x1 or bx[3] < y0 or bx[1] > y1:
            continue
        i = IDX[kind]
        d = deep_len(a, b, ob, _MARGIN[kind])
        tot[i] += d
        if d >= MIN_OVER - 1e-9:
            v[i] += 1
    for i in IDX.values():
        if not v[i] and tot[i] >= MIN_OVER - 1e-9:
            v[i] = 1
    if not v[SMALLP] and not v[PART] and L > 2 * NEAR_SKIP + 1e-9:   # середина перехода есть (20 мм + 1e-13 — нет)
        v[NEARP] = _near(a, b, L, sheet, extra)
    return tuple(v)


def ret_once(v):
    """Вектор ret_move → возврат «одним переходом» (0/1 в классе — ровно то, что дал бы move; правило до 14.10.2026). Не
    для счёта: ключ с возвратом — key0 по ret_move. Маршрут строит по нему ещё одних кандидатов, как прежде, — пул
    безопасных стратегий остаётся надмножеством прежнего (safe на любой раскладке не хуже, чем был)."""
    return tuple(min(x, 1) for x in v)


def walk(tagged, head, sheet, kinds, obs, feat=None, extra0=(), rec=None, commit=False):
    """Пройти фигуры tagged ([(фигура, номер размещения)]) по порядку резки от head по вырезанному sheet (commit —
    освобождённое вносить в sheet; иначе sheet не меняется). kinds[i] / obs[i] — класс и препятствие размещения
    (список или словарь; размещения без класса не освобождаются — путь внутри детали до её контура); feat(s, i) — что
    оставляет вырезанным фигура (по умолчанию feature); extra0 — вырезанное, которого ещё нет в sheet. rec — список,
    куда (откуда, куда, вектор) каждого перехода. Вернуть (вектор, холостой, конец, освобождённое + extra0 — [(класс,
    препятствие)], пусто при commit; вырезанное не освобождённых)."""
    last = {}
    for k, (s, i) in enumerate(tagged):
        last[i] = k
    own = collections.defaultdict(list)
    extra = list(extra0)
    vec, idle, pos = ZERO, 0.0, head
    for k, (s, i) in enumerate(tagged):
        a, b = G.ends(s)
        if pos is not None:
            v = move(pos, a, sheet, [x for lst in own.values() for x in lst], extra)
            vec = vadd(vec, v)
            idle += D(pos, a)
            if rec is not None:
                rec.append((pos, a, v))
        f = feat(s, i) if feat else feature(s)
        if f:
            own[i].append(f)
        if last[i] == k:
            kd = kinds.get(i) if isinstance(kinds, dict) else kinds[i]
            if kd:
                put = sheet.add if commit else (lambda kind, ob: extra.append((kind, ob)))
                put(kd, obs[i])
                for x in own.pop(i, []):
                    if kd == "mj":
                        put(*x)                    # деталь держится — её отверстия и язычки опасны и дальше
        pos = b
    return vec, idle, pos, extra, [x for lst in own.values() for x in lst]


# ================================================================================ лист целиком
def measure(tagged, kinds, polys, head=(0.0, 0.0), ret=True, feat=None, obs=None):
    """Счёт по маршруту листа. tagged — [(фигура, номер размещения)] в порядке резки; kinds[i] — класс размещения
    ("small" | "parts" | "mj", part_kind); polys[i] — внешний контур размещения (фигура). feat(s, i) — что оставляет
    вырезанным фигура (по умолчанию feature; маршрут передаёт кэш своих деталей — то же самое), obs — готовые
    препятствия внешних контуров {i: препятствие}. Вернуть dict: число переходов по классам, холостой ход, метры пути
    над освобождёнными деталями, возврат в ноль (длина, метры над деталями, язычков под ним, классы, число объектов
    под ним по ступеням), key — ключ безопасных стратегий, key0 — он же с возвратом (ret_move: в ступенях — число
    объектов под возвратом, в холостом — его длина), moves — классы каждого перехода (у возврата — числа ret_move)."""
    obs = dict(obs or {})
    for s, i in tagged:
        if i not in obs:
            obs[i] = obstacle(polys[i])
    moves = []
    sheet = Sheet()
    vec, idle, pos, extra, own = walk(tagged, head, sheet, kinds, obs, feat, rec=moves, commit=True)
    over_m = 0.0
    if vec[SMALLP] or vec[PART]:
        freed, last = [], {}
        for k, (s, i) in enumerate(tagged):
            last[i] = k
        for k, (s, i) in enumerate(tagged):          # метры над освобождёнными: по каждому такому переходу
            a, b, v = moves[k]
            if v[SMALLP] or v[PART]:
                x0, x1, y0, y1 = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
                over_m += sum(inside_len(a, b, ob) for kd, ob in freed if kd in ("small", "parts") and
                              not (ob[1][2] < x0 or ob[1][0] > x1 or ob[1][3] < y0 or ob[1][1] > y1))
            if last[i] == k:
                freed.append((kinds[i], obs[i]))
    out = {c: vec[n] for n, c in enumerate(CLASSES)}
    out.update(moves_n=len(moves), idle=idle, over_parts_m=over_m / 1000, key=safe_key(vec, idle))
    rv = ret_move(pos, head, sheet, own, extra)
    rl = D(pos, head)
    bx = (min(pos[0], head[0]), min(pos[1], head[1]), max(pos[0], head[0]), max(pos[1], head[1]))

    def hit(o):
        return not (o[1][2] < bx[0] or o[1][0] > bx[2] or o[1][3] < bx[1] or o[1][1] > bx[3])
    r_over = sum(inside_len(pos, head, o) for o in obs.values() if hit(o))
    tongues = [f[1] for s, i in tagged for f in [feat(s, i) if feat else feature(s)] if f and f[0] == "tongues"]
    r_tongues = sum(1 for o in tongues if hit(o) and deep_len(pos, head, o, DEEP_CUT) >= MIN_OVER - 1e-9)
    # возврат: длина, метры над вырезанными деталями (всеми — к концу листа вырезано всё), сколько язычков под ним;
    # классы перехода 0/1 (как у всех: over — над освобождёнными деталями, мелкими или прочими); в ключе (key0) —
    # число объектов под ним по ступеням (ret_move): n_tongues, n_small, n_parts, n_holes
    out["ret"] = dict(m=rl / 1000, over_m=r_over / 1000, tongues_crossed=r_tongues, over=int(bool(rv[SMALLP] or rv[PART])),
                      near=rv[NEARP], holes=int(bool(rv[HOLE])), n_tongues=rv[TONGUE], n_small=rv[SMALLP], n_parts=rv[PART],
                      n_holes=rv[HOLE])
    out["key0"] = safe_key(vadd(vec, rv), idle + rl)
    out["moves"] = moves + [(pos, head, rv)] if ret else moves
    return out


# ================================================================================ конец листа: узкая полоса
END_FRAC = 0.2       # «конец листа» — последние 20 % деталей по порядку резки (остаток при 80 % готовности)
STRIP_PARTS = 3      # узкая полоса — не больше стольких деталей поперёк (уже STRIP_PARTS + 0,5 ширины детали — медиана меньшей
                     # стороны габарита детали на листе; m14: три колонки шайб — 319 мм при ширине 104,6)…
STRIP_MIN = 10       # …на листе хотя бы из стольких деталей (у листа из трёх решёток «конец» — одна решётка)
STRIP_ALONG = 2.5    # …и полоса — из деталей вдоль неё: длиннее стольких длин детали остатка (хотя бы три; три бруса 200×2105 рядом —
                     # не полоса, которую можно убрать порядком: это сами детали; m3_grpsh, разбор 14.10)


def end_strip(units, W, L, frac=END_FRAC):
    """«Узкая полоса в конце» (решение Антона 14.10.2026: к концу резки не должна оставаться узкая полоса во всю длину
    листа — её ведёт от перегрева). units — детали или единицы резки в порядке освобождения: [(габарит (x0, y0, x1, y1),
    деталей, [меньшая сторона габарита каждой детали][, [большая сторона]])] (группа моста освобождается целиком — одна
    единица из нескольких деталей; у общего реза — каждая деталь отдельно, по последнему своему куску). Остаток —
    последние единицы, в которых frac деталей (не меньше одной единицы): его габарит, меньшая (w) и большая (l)
    сторона, вытянутость; strip — полоса не больше STRIP_PARTS деталей поперёк (уже STRIP_PARTS + 0,5 ширины детали),
    длиннее половины большей стороны листа и длиннее STRIP_ALONG длин детали остатка (медиана большей стороны) — полоса
    из деталей вдоль неё, а не сами длинные детали (на листе ≥ STRIP_MIN деталей). None — на листе ничего нет."""
    if not units:
        return None
    tot = sum(u[1] for u in units)
    acc, k = 0, len(units)
    while k > 0 and (acc < frac * tot - 1e-9 or k == len(units)):
        k -= 1
        acc += units[k][1]
    rest = units[k:]
    x0, y0 = min(u[0][0] for u in rest), min(u[0][1] for u in rest)
    x1, y1 = max(u[0][2] for u in rest), max(u[0][3] for u in rest)
    a, b = sorted((x1 - x0, y1 - y0))
    ws = sorted(w for u in units for w in u[2])
    pw = ws[len(ws) // 2]
    ls = sorted(x for u in rest for x in (u[3] if len(u) > 3 else u[2]))
    pl = ls[len(ls) // 2]
    strip = tot >= STRIP_MIN and a < (STRIP_PARTS + 0.5) * pw and b > max(W, L) / 2 and b > STRIP_ALONG * pl
    return dict(w=round(float(a), 1), l=round(float(b), 1), aspect=round(float(b / max(a, 1e-9)), 2), parts=acc, of=tot,
                part_w=round(float(pw), 1), part_l=round(float(pl), 1), strip=bool(strip), box=[round(float(v), 1) for v in (x0, y0, x1, y1)])


def total(rs, amounts):
    """Сумма метрик листов × количество (без moves и ключей)."""
    out, ret = collections.Counter(), collections.Counter()
    for r, n in zip(rs, amounts):
        for c in CLASSES + ("moves_n",):
            out[c] += r[c] * n
        out["idle"] += r["idle"] * n
        out["over_parts_m"] += r["over_parts_m"] * n
        for c, v in r["ret"].items():
            ret[c] += v * n
    o = {c: out[c] for c in CLASSES + ("moves_n",)}
    o["idle_m"] = round(out["idle"] / 1000, 3)
    o["over_parts_m"] = round(out["over_parts_m"], 3)
    o["ret"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in ret.items()}
    return o
