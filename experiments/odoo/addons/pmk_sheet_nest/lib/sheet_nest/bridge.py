# -*- coding: utf-8 -*-
"""Мост (Bridge CypCut): соседние круглые детали соединяются перемычками и режутся одной врезкой — общим контуром.

Формат разобран по программе, где мост сделал сам CypCut 6.3.907.11 (Антон, 14.10.2026, m14: 5 шайб, перемычки 2 мм;
`~/Downloads/vent_nesting/bridge_research/`):
  • вставка группы — без NestPart и NestGroup (ChannelPort="1"); блок с числовым именем, OutlineID — общий контур,
    без Flags; в блоке общий контур и отверстия деталей (у CypCut — контур первым; у нас — порядок резки: отверстия,
    контур последним);
  • общий контур — ОДНА замкнутая полилиния: flag 5 (1|4), sp 0, outer 0, coedge 0, flag64 0, без LeadParam, против
    часовой; дуги окружностей деталей и у каждой перемычки две параллельные прямые через зазор на расстоянии ширины
    перемычки; детали группы — дерево (у Антона — крест), длина контура ≈ сумма окружностей;
  • NestPart AmountUsed и PartCount раскладки — без деталей мостов (704 → 699), Amount — заказ (704); загрузка та же.
Перемычки CypCut Антон рисовал рукой — их оси наклонены на 2,6…16,5° к линии центров; ширина у всех ровно 2,000 мм.
Наши перемычки — по линии центров (ось может быть любой: Contour(axes=…), так сверяется контур CypCut).

Объём (решение 14.10): детали с внешним контуром-окружностью (Circle или замкнутая полилиния из дуг одной окружности),
соседи по раскладке через зазор (расстояние между окружностями = зазор ± 0,01 мм), группы до N деталей (--bridge-group,
по умолчанию 5, как у Антона). Детали с микроперемычками не соединяются (держатся сами). Остальные детали — позже.

Резка: группа — одна единица: все отверстия всех деталей, общий контур последним, одна врезка — на дуге (дуга
разбивается вершиной), ≥ 10 мм свободно под подвод по радиусу, не в перемычке; вершина 0 — врезка (sp 0, как у CypCut).
Маршрут видит группу как одну деталь (синтетическая деталь в координатах листа: отверстия + общий контур с кандидатами
врезки), поэтому все стратегии работают как есть; освобождается группа целиком (размер для правила мелких — габарит
группы).
"""
import math, collections
from . import geom as G

TWO_PI = 2 * math.pi
GAP_TOL = 0.01              # мм: соседи через зазор — расстояние между окружностями = зазор ± столько
CIRCLE_TOL = 1e-5           # мм: полилиния из дуг — одна окружность (центр и радиус у всех дуг одни)
PIERCE_CLEAR = 2.0          # мм по дуге от перемычки — врезка не ближе
STRIP_CLEAR = 0.5           # мм: перемычка не ближе к чужой детали (доля зазора не нужна — зазор ≥ 2 мм по раскрою)
UNITS_SLACK = 0.01          # группы: вариант компактнее, если единиц резки больше не более чем на 1 % (хотя бы на одну)


class BridgeError(ValueError):
    pass


# ============================================================================================ геометрия
def circle_of(s):
    """Внешний контур-окружность: (cx, cy, r) или None. Circle; замкнутая полилиния из дуг одной окружности."""
    if s["kind"] == "Circle":
        return (float(s["c"][0]), float(s["c"][1]), float(s["r"]))
    if s["kind"] != "LwPolyline" or not s["flag"] & 1:
        return None
    V = s["verts"]
    n = len(V)
    c0, tot = None, 0.0
    for i in range(n):
        p, q, b = V[i][:2], V[(i + 1) % n][:2], V[i][2]
        if math.dist(p, q) < 1e-9:
            continue
        if abs(b) < 1e-12:
            return None
        (cx, cy), r, th = G.bulge_center(p, q, b)
        if c0 is None:
            c0 = (cx, cy, r)
        elif abs(cx - c0[0]) > CIRCLE_TOL or abs(cy - c0[1]) > CIRCLE_TOL or abs(r - c0[2]) > CIRCLE_TOL:
            return None
        tot += th
    if c0 is None or abs(abs(tot) - TWO_PI) > 1e-6:
        return None
    return c0


class Contour:
    """Общий контур группы: окружности circles [(cx, cy, r)], перемычки edges [(a, b)] (дерево), ширина w; оси
    перемычек axes — [(точка, единичное направление a→b)] (по умолчанию линия центров). Обход Эйлера вокруг дерева
    против часовой: на окружности — дуга до ближайшей по ходу перемычки, по её правой стороне — к соседке, обход
    соседки и т.д.; точки перемычки на окружности — пересечения прямых ±w/2 от оси с окружностью (у линии центров —
    угол оси ± asin(w/2 / r)). Граница объединения окружностей и полос перемычек — точно (дуги — bulge = tan(угол/4))."""

    def __init__(self, circles, edges, w, axes=None):
        self.circles = [tuple(float(x) for x in c) for c in circles]
        self.edges = [tuple(e) for e in edges]
        self.w = float(w)
        n = len(self.circles)
        if n < 2 or len(self.edges) != n - 1:
            raise BridgeError("группа моста: перемычек должно быть на одну меньше, чем деталей (дерево)")
        seen = {0}
        adj = collections.defaultdict(list)
        for a, b in self.edges:
            adj[a].append(b); adj[b].append(a)
        stack = [0]
        while stack:
            k = stack.pop()
            for m in adj[k]:
                if m not in seen:
                    seen.add(m); stack.append(m)
        if len(seen) != n:
            raise BridgeError("группа моста: детали не связаны перемычками")
        self.axes = []
        self.att = {}                                   # (окружность, перемычка) → (lo, точка lo, hi, точка hi)
        self.inc = collections.defaultdict(list)
        for k, (a, b) in enumerate(self.edges):
            (ax, ay, ra), (bx, by, rb) = self.circles[a], self.circles[b]
            if axes is None:
                D = math.dist((ax, ay), (bx, by))
                p0, u = (ax, ay), ((bx - ax) / D, (by - ay) / D)
            else:
                p0, u = axes[k]
                L = math.hypot(u[0], u[1])
                u = (u[0] / L, u[1] / L)
            self.axes.append((tuple(p0), u))
            for c, sg in ((a, 1.0), (b, -1.0)):
                uc = (u[0] * sg, u[1] * sg)
                nc = (-uc[1], uc[0])
                cx, cy, r = self.circles[c]
                if self.w / 2 >= r:
                    raise BridgeError("перемычка %g мм не меньше радиуса детали (%g мм)" % (self.w, r))

                def hit(d, cx=cx, cy=cy, r=r, uc=uc, nc=nc):
                    qx, qy = p0[0] + d * nc[0] - cx, p0[1] + d * nc[1] - cy
                    bq = qx * uc[0] + qy * uc[1]
                    disc = bq * bq - (qx * qx + qy * qy - r * r)
                    if disc <= 0:
                        raise BridgeError("перемычка не попадает на окружность детали")
                    t = -bq + math.sqrt(disc)               # дальняя по направлению к соседке точка окружности
                    return (cx + qx + t * uc[0], cy + qy + t * uc[1])
                lo_p, hi_p = hit(-self.w / 2), hit(self.w / 2)
                self.att[(c, k)] = (math.atan2(lo_p[1] - cy, lo_p[0] - cx), lo_p, math.atan2(hi_p[1] - cy, hi_p[0] - cx), hi_p)
                self.inc[c].append(k)
        for c, ks in self.inc.items():                  # зоны перемычек на окружности не перекрываются
            z = sorted((self.att[(c, k)][0] % TWO_PI, (self.att[(c, k)][2] - self.att[(c, k)][0]) % TWO_PI) for k in ks)
            for (a0, s0), (a1, _) in zip(z, z[1:] + [(z[0][0] + TWO_PI, 0)]):
                if a0 + s0 >= a1 - 1e-9:
                    raise BridgeError("перемычки на детали перекрываются")
        # обход: от окружности 0, с точки hi первой (по углу) её перемычки
        k0 = min(self.inc[0], key=lambda k: (self.att[(0, k)][2] % TWO_PI, k))
        c, ang, pt = 0, self.att[(0, k0)][2], self.att[(0, k0)][3]
        self.pieces = []                                # ("arc", окр., угол от, угол до, точка от, точка до) | ("line", от, до, перемычка)
        for _ in range(2 * len(self.edges)):
            def ccw(k, c=c, ang=ang):
                d = (self.att[(c, k)][0] - ang) % TWO_PI
                return (d if d > 1e-12 else TWO_PI, k)
            k = min(self.inc[c], key=ccw)
            lo, lo_p = self.att[(c, k)][:2]
            self.pieces.append(("arc", c, ang, lo, pt, lo_p))
            a, b = self.edges[k]
            m = b if c == a else a
            hi_m, hi_mp = self.att[(m, k)][2:]
            self.pieces.append(("line", lo_p, hi_mp, k))
            c, ang, pt = m, hi_m, hi_mp
        if c != 0 or abs(((ang - self.att[(0, k0)][2]) + math.pi) % TWO_PI - math.pi) > 1e-9:
            raise BridgeError("обход контура моста не замкнулся")
        self.cands = self._candidates()

    # ------------------------------------------------------------------ вершины
    @staticmethod
    def _sweep(a0, a1):
        d = (a1 - a0) % TWO_PI
        return d if d > 1e-12 else TWO_PI

    def _point(self, c, a):
        cx, cy, r = self.circles[c]
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    def verts(self):
        """Вершины контура (x, y, bulge) от начала обхода (точка hi перемычки на окружности 0)."""
        out = []
        for pc in self.pieces:
            if pc[0] == "arc":
                out.append((pc[4][0], pc[4][1], math.tan(self._sweep(pc[2], pc[3]) / 4)))
            else:
                out.append((pc[1][0], pc[1][1], 0.0))
        return out

    def length(self):
        """Длина контура аналитически: дуги r·угол + прямые."""
        t = 0.0
        for pc in self.pieces:
            if pc[0] == "arc":
                t += self.circles[pc[1]][2] * self._sweep(pc[2], pc[3])
            else:
                t += math.dist(pc[1], pc[2])
        return t

    def parts(self):
        """Части объединения — для внутри/глубины/препятствия (geom.Poly, risk): окружности ("c", cx, cy, r) и перемычки —
        четырёхугольники между окружностями по точкам на них ("r", [lo_a, hi_b, lo_b, hi_a])."""
        out = [("c",) + c for c in self.circles]
        for k, (a, b) in enumerate(self.edges):
            out.append(("r", [self.att[(a, k)][1], self.att[(b, k)][3], self.att[(b, k)][1], self.att[(a, k)][3]]))
        return out

    def shape(self, verts=None, lead=None):
        s = dict(handle=None, kind="LwPolyline", verts=verts or self.verts(), flag=5, sp=0.0, layer=1, layer_name="0", coedge=0,
                 flag64=0, outer=1, lead=None, _bridge=self)
        if lead is not None:
            s["_lead"] = lead
        return s

    # ------------------------------------------------------------------ врезка
    def _candidates(self):
        """Точки врезки: на дугах (не на перемычках), углы через 45° (как у окружности-детали) и середины дуг, не ближе
        PIERCE_CLEAR мм по дуге к перемычке. Вернуть [(номер дуги в обходе, угол)]."""
        out, seen = [], set()
        for i, pc in enumerate(self.pieces):
            if pc[0] != "arc":
                continue
            c, a0, a1 = pc[1], pc[2], pc[3]
            r = self.circles[c][2]
            sw = self._sweep(a0, a1)
            clear = PIERCE_CLEAR / r
            if sw <= 2 * clear:
                continue
            angs = [k * math.pi / 4 for k in range(8)] + [a0 + sw / 2]
            for th in angs:
                d = (th - a0) % TWO_PI
                if clear <= d <= sw - clear:
                    key = (i, round(d, 9))
                    if key not in seen:
                        seen.add(key)
                        out.append((i, a0 + d))
        out.sort(key=lambda v: (v[0], (v[1] - self.pieces[v[0]][2]) % TWO_PI))
        return out

    def started(self, j):
        """Контур с врезкой в кандидате j: дуга разбита точкой врезки, она — вершина 0 (sp 0); _lead — (точка, наружная
        нормаль по радиусу) для места под подвод (route.lead_free)."""
        i, th = self.cands[j]
        _, c, a0, a1, p0, p1 = self.pieces[i]
        pt = self._point(c, th)
        V = [(pt[0], pt[1], math.tan(self._sweep(th, a1) / 4))]
        n = len(self.pieces)
        for k in range(1, n):
            pc = self.pieces[(i + k) % n]
            if pc[0] == "arc":
                V.append((pc[4][0], pc[4][1], math.tan(self._sweep(pc[2], pc[3]) / 4)))
            else:
                V.append((pc[1][0], pc[1][1], 0.0))
        V.append((p0[0], p0[1], math.tan(self._sweep(a0, th) / 4)))
        return self.shape(V, lead=(pt, (math.cos(th), math.sin(th))))


# ============================================================================================ группы на раскладке
def _seg_seg(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if orient(q1, q2, p1) * orient(q1, q2, p2) < 0 and orient(p1, p2, q1) * orient(p1, p2, q2) < 0:
        return 0.0
    return min(G.seg_point_dist(p1, q1, q2), G.seg_point_dist(p2, q1, q2), G.seg_point_dist(q1, p1, p2), G.seg_point_dist(q2, p1, p2))


def plan(parts, placed, gap, width, nmax, head=(0.0, 0.0)):
    """Группы мостов раскладки. Вернуть dict(width, groups=[dict(members=[номер размещения…], edges=[(a, b)…])],
    skipped=[причины]). Порядок деталей группы — порядок роста (у каждой новой — перемычка к первой из соседок в группе)."""
    width, nmax = float(width), int(nmax)
    circ, skipped, polys = {}, [], {}
    for i, q in enumerate(placed):
        p = parts[q["part"]]
        o = G.transform(p["shapes"][-1], q["rot"], (q["dx"], q["dy"]))
        P = G.points(o, 0.2)
        polys[i] = (P, (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P)))
        c = circle_of(o)
        if c is None or p.get("microjoints"):
            continue
        if width >= c[2]:
            skipped.append("деталь %s: перемычка %g мм не меньше половины диаметра (%g мм) — без моста" % (p["name"], width, 2 * c[2]))
            continue
        if c[2] * (TWO_PI - 2 * math.asin(width / 2 / c[2])) <= 2 * PIERCE_CLEAR + 1e-6:
            # даже у крайней детали группы (одна перемычка) на дуге нет места под врезку (PIERCE_CLEAR от перемычки)
            skipped.append("деталь %s: Ø%g мм — на дуге нет места под врезку (%g мм от перемычки) — без моста"
                           % (p["name"], 2 * c[2], PIERCE_CLEAR))
            continue
        circ[i] = c
    # соседи через зазор (сетка по центрам)
    cell = 2 * max((c[2] for c in circ.values()), default=1.0) + gap + 1.0
    grid = collections.defaultdict(list)
    for i, (x, y, r) in circ.items():
        grid[(int(math.floor(x / cell)), int(math.floor(y / cell)))].append(i)
    pgrid = collections.defaultdict(list)                # все детали — для проверки, что перемычка не задевает чужую
    for i, (P, bx) in polys.items():
        for gx in range(int(math.floor(bx[0] / 100.0)), int(math.floor(bx[2] / 100.0)) + 1):
            for gy in range(int(math.floor(bx[1] / 100.0)), int(math.floor(bx[3] / 100.0)) + 1):
                pgrid[(gx, gy)].append(i)
    adj = {i: [] for i in circ}
    for i, (x, y, r) in sorted(circ.items()):
        gx, gy = int(math.floor(x / cell)), int(math.floor(y / cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if j <= i:
                        continue
                    xj, yj, rj = circ[j]
                    d = math.dist((x, y), (xj, yj)) - r - rj
                    if abs(d - gap) > GAP_TOL:
                        continue
                    if _strip_clear(circ, polys, pgrid, i, j, width):
                        adj[i].append(j); adj[j].append(i)
    for i in adj:
        adj[i].sort()
    # варианты: меньше единиц резки (групп + одиночек среди круглых); при отличии не больше UNITS_SLACK (1 %, хотя бы
    # одна единица) — компактнее (сумма габаритов групп): m14 — 143 единицы крестами и «2×2+1» вместо 142 с прямыми по 5
    vs = []
    for vi, (seeds, mode) in enumerate(_variants(circ, adj, head)):
        groups = _post(_grow(seeds, adj, circ, nmax, mode), adj, circ, nmax)
        inside = {i for g, _ in groups for i in g}
        units = len(groups) + sum(1 for i in circ if i not in inside)
        vs.append((units, round(sum(_bbox_perim(g, circ) for g, _ in groups), 3), vi, groups))
    groups = []
    if vs:
        u0 = min(v[0] for v in vs)
        best = min((v for v in vs if v[0] <= u0 + max(1, int(UNITS_SLACK * u0))), key=lambda v: (v[1], v[0], v[2]))
        groups = [dict(members=list(g), edges=[tuple(e) for e in ed]) for g, ed in best[3] if len(g) >= 2]
    # предохранитель: группа, у которой общий контур не строится или на нём нет точки врезки, — детали без моста
    ok_groups = []
    for g in groups:
        try:
            C = Contour([circ[i] for i in g["members"]], [(g["members"].index(a), g["members"].index(b)) for a, b in g["edges"]], width)
            why = "" if C.cands else "на общем контуре нет места под врезку"
        except BridgeError as e:
            why = str(e)
        if why:
            skipped.append("группа из %d деталей (%s): %s — без моста" % (
                len(g["members"]), ", ".join(sorted({parts[placed[i]["part"]]["name"] for i in g["members"]})), why))
        else:
            ok_groups.append(g)
    return dict(width=width, group=nmax, groups=ok_groups, skipped=skipped)


def _strip_clear(circ, polys, pgrid, i, j, w):
    """Полоса перемычки i–j (по линии центров) не ближе STRIP_CLEAR мм к чужим деталям."""
    try:
        C = Contour([circ[i], circ[j]], [(0, 1)], w)
    except BridgeError:
        return False
    L1 = (C.att[(0, 0)][1], C.att[(1, 0)][3])           # правая сторона: lo на i → hi на j
    L2 = (C.att[(1, 0)][1], C.att[(0, 0)][3])
    xs = [p[0] for p in L1 + L2]; ys = [p[1] for p in L1 + L2]
    bx = (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)
    near = set()
    for gx in range(int(math.floor(bx[0] / 100.0)), int(math.floor(bx[2] / 100.0)) + 1):
        for gy in range(int(math.floor(bx[1] / 100.0)), int(math.floor(bx[3] / 100.0)) + 1):
            near.update(pgrid.get((gx, gy), ()))
    for k in sorted(near):
        if k in (i, j):
            continue
        P, pb = polys[k]
        if pb[2] < bx[0] or pb[0] > bx[2] or pb[3] < bx[1] or pb[1] > bx[3]:
            continue
        mid = ((L1[0][0] + L2[1][0]) / 2, (L1[0][1] + L2[1][1]) / 2)
        if G.inside(mid, P):
            return False
        for a, b in (L1, L2):
            for e in range(len(P)):
                if _seg_seg(a, b, P[e - 1], P[e]) < STRIP_CLEAR:
                    return False
    return True


def _variants(circ, adj, head):
    """Порядки затравок и правила роста группы: от начала листа (ближние к головке первыми) — компактно (ближе к
    центру группы) и «сперва зажатые» (меньше свободных соседей); полосами по 2 детали змейкой — вдоль Y и вдоль X."""
    pos = [i for i in sorted(circ, key=lambda i: (round(math.dist(circ[i][:2], head), 6), i)) if adj[i]]
    out = [(pos, "compact"), (pos, "tight")]
    rs = sorted(c[2] for c in circ.values())
    if rs:
        step = 2 * rs[len(rs) // 2] + 1.0
        for ax in (1, 0):
            band = 2 * step

            def key(i, ax=ax):
                x, y = circ[i][0], circ[i][1]
                b = int(math.floor((y if ax else x) / band))
                c = (x if ax else y)
                c = c if b % 2 == 0 else -c
                col = int(math.floor(c / step))
                v = (y if ax else x)
                return (b, col, v if col % 2 == 0 else -v, i)
            out.append(([i for i in sorted(circ, key=key) if adj[i]], "chain"))
    return out


def _grow(seeds, adj, circ, nmax, mode):
    free = set(seeds)
    pos = {i: k for k, i in enumerate(seeds)}
    groups = []
    if mode == "chain":                                 # подряд по порядку, пока очередная — соседка группы
        g, ed = [], []
        for i in seeds:
            m = next((m for m in g if i in adj[m]), None) if g else None
            if g and (m is None or len(g) >= nmax):
                groups.append((g, ed)); g, ed = [], []
            if g:
                ed.append((m, i))
            g.append(i)
        if g:
            groups.append((g, ed))
        return groups
    for s in seeds:
        if s not in free:
            continue
        free.discard(s)
        g, ed = [s], []
        while len(g) < nmax:
            cand = sorted({j for m in g for j in adj[m] if j in free})
            if not cand:
                break
            cx = sum(circ[m][0] for m in g) / len(g)
            cy = sum(circ[m][1] for m in g) / len(g)

            def key(j):
                dc = round(math.dist(circ[j][:2], (cx, cy)), 6)
                nf = sum(1 for x in adj[j] if x in free)
                return (dc, nf, pos[j]) if mode == "compact" else (nf, dc, pos[j])
            j = min(cand, key=key)
            m = next(m for m in g if j in adj[m])
            g.append(j); ed.append((m, j)); free.discard(j)
        groups.append((g, ed))
    return groups


def _post(groups, adj, circ, nmax):
    """Одиночки — к соседней неполной группе; две соседние группы, вместе не больше nmax, — в одну."""
    groups = [(list(g), list(e)) for g, e in groups]
    changed = True
    while changed:
        changed = False
        where = {i: k for k, (g, _) in enumerate(groups) for i in g}
        for k, (g, ed) in enumerate(groups):
            if not g or len(g) >= nmax:
                continue
            best = None
            for i in g:
                for j in adj[i]:
                    k2 = where.get(j)
                    if k2 is None or k2 == k or not groups[k2][0] or len(groups[k2][0]) + len(g) > nmax:
                        continue
                    key = (len(groups[k2][0]), round(math.dist(circ[i][:2], circ[j][:2]), 6), k2, i, j)
                    if best is None or key < best[0]:
                        best = (key, k2, i, j)
            if best:
                _, k2, i, j = best
                g2, e2 = groups[k2]
                a, b = (g2, g) if len(g2) >= len(g) else (g, g2)
                ia, ib = (j, i) if a is g2 else (i, j)
                ea, eb = (e2, ed) if a is g2 else (ed, e2)
                groups[k2 if a is g2 else k] = (a + b, ea + eb + [(ia, ib)])
                groups[k if a is g2 else k2] = ([], [])
                changed = True
                break
        groups = [x for x in groups if x[0]]
    return groups


def _bbox_perim(g, circ):
    xs = [circ[i][0] for i in g]; ys = [circ[i][1] for i in g]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


# ============================================================================================ маршрут
def contour_of(parts, placed, grp, width):
    """Общий контур группы grp (dict(members, edges)) по раскладке."""
    idx = {i: k for k, i in enumerate(grp["members"])}
    circles = [circle_of(G.transform(parts[placed[i]["part"]]["shapes"][-1], placed[i]["rot"], (placed[i]["dx"], placed[i]["dy"])))
               for i in grp["members"]]
    return Contour(circles, [(idx[a], idx[b]) for a, b in grp["edges"]], width)


def bridged(parts, layout):
    """Раскладка для маршрута: группы мостов — синтетические детали (отверстия всех деталей в координатах листа + общий
    контур с кандидатами врезки, поворот 0, сдвиг 0) на месте первой своей детали. Вернуть (placed2, parts2, back), back[k] —
    для синтетической детали k (номер в parts2) — номера деталей группы в parts."""
    br = layout.get("bridges")
    placed = layout["placed"]
    first, member = {}, {}
    for gi, g in enumerate(br["groups"]):
        first[g["members"][0]] = gi
        for i in g["members"]:
            member[i] = gi
    parts2, placed2, back = list(parts), [], {}
    for i, q in enumerate(placed):
        if i in first:
            g = br["groups"][first[i]]
            C = contour_of(parts, placed, g, br["width"])
            inner = []
            for m in g["members"]:
                qm = placed[m]
                inner += [G.transform(s, qm["rot"], (qm["dx"], qm["dy"])) for s in parts[qm["part"]]["shapes"][:-1]]
            names = collections.Counter(parts[placed[m]["part"]]["name"] for m in g["members"])
            parts2.append(dict(name="мост: " + ", ".join("%s×%d" % (n, c) for n, c in names.items()), qty=1,
                               shapes=inner + [C.shape()], src="мост", warnings=[], microjoints=False,
                               bridge=dict(members=[placed[m]["part"] for m in g["members"]], group=first[i],
                                           widths=[2 * c[2] for c in C.circles])))
            back[len(parts2) - 1] = [placed[m]["part"] for m in g["members"]]
            placed2.append(dict(part=len(parts2) - 1, rot=0, dx=0.0, dy=0.0))
        elif i not in member:
            placed2.append(dict(q))
    return placed2, parts2, back


def unmap(seq, back):
    """Маршрут по раскладке bridged() → элементы программы: ("bridge", [детали группы], фигуры) — общий контур как у CypCut
    (outer 0, flag 5, sp 0); остальное — как было (деталь, фигуры)."""
    out = []
    for e in seq:
        pi, sh = e
        if pi in back:
            sh = list(sh[:-1]) + [{k: v for k, v in dict(sh[-1], outer=0, flag=5, sp=0.0).items() if not k.startswith("_")}]
            out.append(("bridge", list(back[pi]), sh))
        else:
            out.append(e)
    return out


def stats(layouts):
    """Сводка мостов: групп, перемычек, деталей в мостах, врезок сбережено (× листы)."""
    g = b = n = 0
    for l in layouts:
        br = l.get("bridges")
        if not br:
            continue
        for gr in br["groups"]:
            g += l["amount"]; b += len(gr["edges"]) * l["amount"]; n += len(gr["members"]) * l["amount"]
    return dict(groups=g, bridges=b, parts=n, pierces_saved=n - g)
