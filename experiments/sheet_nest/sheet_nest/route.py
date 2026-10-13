# -*- coding: utf-8 -*-
"""Порядок резки листа с наименьшим холостым ходом.

Внутри детали — отверстия, открытые резы (прорези), гравировка — путём к точке врезки внешнего контура;
внешний контур режется последним (иначе деталь выпадет раньше). Открытый контур можно развернуть (врезка на
другом конце). Два способа обхода, берётся лучший:
  • «змейка по рядам» — если в детали ряды параллельных открытых резов (жалюзи): ряд = риска → прорезь → риска,
    следующий ряд — обратно; переходы по кромке, над вырезанными язычками головка не ходит (решётки 12.10);
  • оптимизатор — ближайший сосед + 2-opt с разворотом участков + перенос участков (1–3 элемента).
Точка врезки внешнего контура — выпуклая вершина между прямыми участками (у окружности — 8 углов), под подвод
свободно ≥ LEAD_FREE по наружной нормали к первому участку (край листа, соседние детали). Детали листа —
ближайший сосед + 2-opt по центрам, затем динамика по точкам врезки.
"""
import math, itertools, functools, collections
from . import geom as G

D = math.dist
LEAD_FREE = 10.0            # мм свободно под подвод внешнего контура
MAX_CAND = 16               # точек врезки внешнего контура на деталь (больше — по секторам вокруг центра)
EXACT_N = 14                # до стольких внутренних элементов — точный путь от головки для каждой пары (голова, врезка)
CROSS_PENALTY = 2000.0      # мм штрафа за переход над вырезанным (язычок прорези) — чтобы такой путь выбирался последним
PART_CROSS_PENALTY = 500.0  # мм штрафа за переход к следующей детали над уже вырезанной деталью
GROUP_PERM_MAX = 6          # группу общего реза до стольких деталей перебирать всеми порядками (6! = 720)


# =========================================================================== оптимизатор
def order(shapes, head, tail):
    """Внутренние элементы: (фигуры в порядке и направлении резки, холостой ход head → … → tail).
    head=None — начало пути свободно (стоимость считается от первого элемента)."""
    n = len(shapes)
    if n == 0:
        return [], (D(head, tail) if head is not None and tail is not None else 0.0)
    E = [G.ends(s) for s in shapes]
    op = [G.is_open(s) for s in shapes]

    def pin(x):
        return E[x[0]][1] if x[1] else E[x[0]][0]

    def pout(x):
        return E[x[0]][0] if x[1] else E[x[0]][1]

    def dist(a, b):
        return 0.0 if a is None or b is None else D(a, b)

    def total(seq):
        pos, t = head, 0.0
        for x in seq:
            t += dist(pos, pin(x)); pos = pout(x)
        return t + dist(pos, tail)

    def flip(x):
        return (x[0], 1 - x[1]) if op[x[0]] else x

    # жадно: от головки (или от ближайшего к врезке, если головка свободна — строим с конца)
    rest, seq = set(range(n)), []
    pos = head if head is not None else tail
    while rest:
        best = None
        for i in sorted(rest):
            for r in ((0, 1) if op[i] else (0,)):
                a = (E[i][1] if r else E[i][0]) if head is not None else (E[i][0] if r else E[i][1])
                d = D(pos, a) if pos is not None else 0.0
                if best is None or d < best[0] - 1e-9:
                    best = (d, i, r)
        _, i, r = best
        rest.remove(i); seq.append((i, r))
        pos = pout((i, r)) if head is not None else pin((i, r))
    if head is None:
        seq = seq[::-1]
    cur = total(seq)
    improved = True
    while improved:
        improved = False
        for i in range(n):                                   # 2-opt: развернуть seq[i..j]
            prev = pout(seq[i - 1]) if i else head
            for j in range(i, n):
                nxt = pin(seq[j + 1]) if j + 1 < n else tail
                a, b = seq[i], seq[j]
                old = dist(prev, pin(a)) + dist(pout(b), nxt)
                new = dist(prev, pin(flip(b))) + dist(pout(flip(a)), nxt)
                if new < old - 1e-9:
                    seq[i:j + 1] = [flip(x) for x in reversed(seq[i:j + 1])]
                    improved = True
                    prev = pout(seq[i - 1]) if i else head
        for L in (1, 2, 3):                                  # перенос участка
            i = 0
            while i + L <= n:
                seg = seq[i:i + L]
                prev = pout(seq[i - 1]) if i else head
                nxt = pin(seq[i + L]) if i + L < n else tail
                gain = dist(prev, pin(seg[0])) + dist(pout(seg[-1]), nxt) - dist(prev, nxt)
                rest_ = seq[:i] + seq[i + L:]
                best = None
                for rv in (0, 1):
                    s2 = [flip(x) for x in reversed(seg)] if rv else seg
                    a_in, a_out = pin(s2[0]), pout(s2[-1])
                    for j in range(len(rest_) + 1):
                        p_ = pout(rest_[j - 1]) if j else head
                        q_ = pin(rest_[j]) if j < len(rest_) else tail
                        cost = dist(p_, a_in) + dist(a_out, q_) - dist(p_, q_)
                        if gain - cost > 1e-9 and (best is None or gain - cost > best[0]):
                            best = (gain - cost, j, s2)
                if best:
                    _, j, s2 = best
                    seq = rest_[:j] + s2 + rest_[j:]
                    improved = True
                i += 1
    out = [G.reverse(shapes[i]) if r else shapes[i] for i, r in seq]
    return out, total(seq)


# =========================================================================== змейка по рядам
def _proj(p, u):
    return p[0] * u[0] + p[1] * u[1]


def analyze_rows(inner):
    """Ряды параллельных открытых резов одной длины + риски у их концов. None — не тот случай."""
    slits = [s for s in inner if s["kind"] == "LwPolyline" and s["layer"] == 1 and not s["flag"] & 1]
    if len(slits) < 2:
        return None
    a, b = G.ends(slits[0])
    Ls = D(a, b)
    if Ls < 1:
        return None
    u = ((b[0] - a[0]) / Ls, (b[1] - a[1]) / Ls)
    n = (-u[1], u[0])
    rows = []
    for s in slits:
        e1, e2 = G.ends(s)
        if abs(abs(_proj((e2[0] - e1[0], e2[1] - e1[1]), u)) - Ls) > 1.0 or abs(_proj((e2[0] - e1[0], e2[1] - e1[1]), n)) > 1.0:
            return None
        lo, hi = (e1, e2) if _proj(e1, u) < _proj(e2, u) else (e2, e1)
        rows.append(dict(slit=s, lo=lo, hi=hi, pos=_proj(lo, n), tick={}))
    other = []
    for s in inner:
        if any(s is r["slit"] for r in rows):
            continue
        if s["kind"] == "Line" and s["layer"] == 2:
            p1, p2 = G.ends(s)
            best = None
            for r in rows:
                for side in ("lo", "hi"):
                    d = min(D(p1, r[side]), D(p2, r[side]))
                    if d < 80 and (best is None or d < best[0]):
                        best = (d, r, side)
            if best and best[2] not in best[1]["tick"] and D(p1, p2) < 80:
                best[1]["tick"][best[2]] = s
                continue
        other.append(s)
    if len(other) > 4:
        return None
    rows.sort(key=lambda r: r["pos"])
    return dict(rows=rows, other=other)


def _tick(t, near, inward):
    p1, p2 = G.ends(t)
    first_far = D(p1, near) > D(p2, near)
    return t if inward == first_far else G.reverse(t)


def _seq_idle(seq):
    t, pos = 0.0, G.ends(seq[0])[1]
    for s in seq[1:]:
        a, b = G.ends(s)
        t += D(pos, a); pos = b
    return t


def snake_options(inner):
    A = analyze_rows(inner)
    if A is None:
        return None
    cores = []
    for rows in (A["rows"], A["rows"][::-1]):
        for start in ("lo", "hi"):
            seq, side = [], start
            for r in rows:
                other = "hi" if side == "lo" else "lo"
                if side in r["tick"]:
                    seq.append(_tick(r["tick"][side], r[side], True))
                s = r["slit"]
                seq.append(s if D(G.ends(s)[0], r[side]) < 1e-6 else G.reverse(s))
                if other in r["tick"]:
                    seq.append(_tick(r["tick"][other], r[other], False))
                side = other
            cores.append(seq)
    macros = [None]
    if A["other"]:
        macros = []
        for perm in itertools.permutations(A["other"]):
            for dirs in itertools.product(*[((0, 1) if G.is_open(s) else (0,)) for s in perm]):
                sh = [G.reverse(s) if r else s for s, r in zip(perm, dirs)]
                macros.append((G.ends(sh[0])[0], G.ends(sh[-1])[1], _seq_idle(sh) if len(sh) > 1 else 0.0, sh))
    opts = []
    for core in cores:
        cin, cout, cint = G.ends(core[0])[0], G.ends(core[-1])[1], _seq_idle(core)
        gaps = [(i, G.ends(core[i - 1])[1], G.ends(core[i])[0]) for i in range(1, len(core))]
        for m in macros:
            o = dict(core=core, macro=m, cin=cin, cout=cout, cint=cint)
            if m is not None:
                mi, mo = m[0], m[1]
                o["mid"] = min(((-D(p, q) + D(p, mi) + D(mo, q), i) for i, p, q in gaps), default=(None, None))
            opts.append(o)
    return opts


def snake_cost(o, head, tail):
    h = (lambda a: 0.0) if head is None else (lambda a: D(head, a))
    if o["macro"] is None:
        return h(o["cin"]) + o["cint"] + D(o["cout"], tail), None
    mi, mo, mint, _ = o["macro"]
    best = min((h(mi) + mint + D(mo, o["cin"]) + o["cint"] + D(o["cout"], tail), 0),
               (h(o["cin"]) + o["cint"] + D(o["cout"], mi) + mint + D(mo, tail), len(o["core"])))
    if o["mid"][1] is not None:
        best = min(best, (h(o["cin"]) + o["cint"] + o["mid"][0] + mint + D(o["cout"], tail), o["mid"][1]))
    return best


def snake_shapes(o, where):
    if o["macro"] is None:
        return list(o["core"])
    return o["core"][:where] + o["macro"][3] + o["core"][where:]


# =========================================================================== переходы над вырезанным
def tongue_polys(shapes):
    """Язычки открытых резов слоя 1 (открытый контур, замкнутый по хорде) — над ними головке не ходить."""
    out = []
    for s in shapes:
        # цепочки общего реза (coedge) — не прорези: это кромки деталей, язычков у них нет
        if s["kind"] == "LwPolyline" and s["layer"] == 1 and not s["flag"] & 1 and len(s["verts"]) >= 3 and not s.get("coedge"):
            P = G.points(s, 0.2)
            out.append((P, (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P))))
    return out


def crossings(seq_shapes, head, extra_polys=()):
    """Сколько холостых переходов проходят над уже вырезанными язычками (и над extra_polys — вырезанными деталями)."""
    cut, n, pos = list(extra_polys), 0, head
    for s in seq_shapes:
        a, b = G.ends(s)
        if pos is not None and cut and D(pos, a) > 1.0:
            L = D(pos, a)
            steps = int(L) + 1
            hit = False
            for k in range(1, steps):
                t = k / steps
                pt = (pos[0] + (a[0] - pos[0]) * t, pos[1] + (a[1] - pos[1]) * t)
                for P, bx in cut:
                    if bx[0] < pt[0] < bx[2] and bx[1] < pt[1] < bx[3] and G.inside(pt, P) \
                            and min(G.seg_point_dist(pt, P[i - 1], P[i]) for i in range(len(P))) > 0.5:
                        hit = True; break
                if hit:
                    break
            n += hit
        cut += tongue_polys([s])
        pos = b
    return n


# =========================================================================== точка врезки внешнего контура
def outer_candidates(outer):
    """Кандидаты точки врезки: индексы вершин (полилиния) или углы (окружность)."""
    if outer["kind"] == "Circle":
        return [k * math.pi / 4 for k in range(8)]
    V = outer["verts"]
    n = len(V)
    sg = 1 if G.poly_area(V) > 0 else -1
    cand = []
    for k in range(n):
        p0, p1, p2 = V[k - 1], V[k], V[(k + 1) % n]
        if abs(p0[2]) > 1e-12 or abs(p1[2]) > 1e-12:            # по обе стороны — прямые
            continue
        ax, ay = p1[0] - p0[0], p1[1] - p0[1]
        bx, by = p2[0] - p1[0], p2[1] - p1[1]
        if math.hypot(bx, by) < 2.0 or math.hypot(ax, ay) < 1e-9:
            continue
        cr = ax * by - ay * bx
        if sg * cr <= 1e-9:                                      # только выпуклые углы
            continue
        cand.append(k)
    if not cand:
        cand = [k for k in range(n) if abs(V[k][2]) < 1e-12] or [0]
    if len(cand) > MAX_CAND:                                     # по секторам вокруг центра — разнести по контуру
        cx = sum(v[0] for v in V) / n; cy = sum(v[1] for v in V) / n
        sect = {}
        for k in cand:
            a = int((math.atan2(V[k][1] - cy, V[k][0] - cx) + math.pi) / (2 * math.pi) * MAX_CAND) % MAX_CAND
            d = math.hypot(V[k][0] - cx, V[k][1] - cy)
            if a not in sect or d > sect[a][0]:
                sect[a] = (d, k)
        cand = sorted(k for d, k in sect.values())
    return cand


def lead_free(outer_started, W, L, polys, limit=20.0, step=0.05):
    """Свободно по наружной нормали к началу реза внешнего контура, мм (до limit)."""
    if outer_started["kind"] == "Circle":
        cx, cy = outer_started["c"]; a = outer_started["a0"]
        x1, y1 = cx + outer_started["r"] * math.cos(a), cy + outer_started["r"] * math.sin(a)
        nx, ny = math.cos(a), math.sin(a)
    else:
        V = outer_started["verts"]
        (x1, y1), (x2, y2) = V[0][:2], V[1][:2]
        Lg = math.hypot(x2 - x1, y2 - y1)
        sg = 1 if G.poly_area(V) > 0 else -1
        nx, ny = sg * (y2 - y1) / Lg, -sg * (x2 - x1) / Lg
    for i in range(1, int(limit / step) + 1):
        pt = (x1 + nx * i * step, y1 + ny * i * step)
        if not (0 <= pt[0] <= W and 0 <= pt[1] <= L):
            return i * step
        for P, bx in polys:
            if bx[0] <= pt[0] <= bx[2] and bx[1] <= pt[1] <= bx[3] and G.inside(pt, P):
                return i * step
    return limit


# =========================================================================== маршрут листа
class _PartPlan:
    """Варианты обхода одной детали (в координатах листа)."""

    def __init__(self, part, rot, d):
        self.part = part
        sh = [G.transform(s, rot, d) for s in part["shapes"]]
        self.inner, self.outer = sh[:-1], sh[-1]
        self.snake = snake_options(self.inner)
        self.cands = outer_candidates(self.outer)
        self.tongues = tongue_polys(self.inner)
        self._segx, self._intx = {}, {}
        P = G.points(self.outer, 0.2)
        self.poly = (P, (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P)))
        self.center = ((self.poly[1][0] + self.poly[1][2]) / 2, (self.poly[1][1] + self.poly[1][3]) / 2)
        self._free = {}

    def started(self, k):
        return G.rotate_start(self.outer, k)

    @functools.lru_cache(maxsize=None)
    def free_path(self, k):
        """Путь от свободного начала до врезки k (для деталей с большим числом элементов)."""
        tail = G.ends(self.started(k))[0]
        sh, c = order(self.inner, None, tail)
        return sh, c, (G.ends(sh[0])[0] if sh else tail), crossings(sh, None)

    def seg_x(self, a, b):
        """1 — переход a→b проходит над язычком этой детали (все прорези к этому моменту вырезаны)."""
        if not self.tongues or D(a, b) <= 1.0:
            return 0
        key = (round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2))
        if key not in self._segx:
            self._segx[key] = 1 if _seg_hits(a, b, self.tongues, margin=0.5) else 0
        return self._segx[key]

    def cost(self, head, k):
        """(холостой ход от head до конца внешнего контура при врезке k, фигуры в порядке резки, переходов над язычками)."""
        ok = self.started(k)
        tail = G.ends(ok)[0]
        best = None
        if self.snake:
            for oi, o in enumerate(self.snake):
                c, where = snake_cost(o, head, tail)
                ik = (oi, where)
                if ik not in self._intx:                     # переходы внутри змейки от головки не зависят
                    sh = snake_shapes(o, where)
                    self._intx[ik] = (sh, crossings(sh, None))
                sh, xi = self._intx[ik]
                x = xi + self.seg_x(G.ends(sh[-1])[1], tail)
                if best is None or c + CROSS_PENALTY * x < best[0] + CROSS_PENALTY * best[2]:
                    best = (c, sh, x)
            best = (best[0], best[1] + [ok], best[2])
        if len(self.inner) <= EXACT_N and (best is None or best[2]):
            sh, c = order(self.inner, head, tail)
            x = crossings(sh, head) + (self.seg_x(G.ends(sh[-1])[1], tail) if sh else 0)
            if best is None or c + CROSS_PENALTY * x < best[0] + CROSS_PENALTY * best[2]:
                best = (c, sh + [ok], x)
        elif best is None or best[2]:
            sh, c, start, xi = self.free_path(k)
            c += (D(head, start) if head is not None else 0.0)
            x = xi + (self.seg_x(G.ends(sh[-1])[1], tail) if sh else 0)
            if best is None or c + CROSS_PENALTY * x < best[0] + CROSS_PENALTY * best[2]:
                best = (c, sh + [ok], x)
        return best


def route_sheet(placed, parts, W, L, head=(0.0, 0.0)):
    """placed: [{"part": i, "rot", "dx", "dy"}] → dict(seq=[(part_i, [фигуры в порядке резки])], idle, crossings, lead_min, warnings)."""
    plans = [_PartPlan(parts[q["part"]], q["rot"], (q["dx"], q["dy"])) for q in placed]
    polys = [p.poly for p in plans]
    # порядок деталей: ближайший сосед от головки по центрам + 2-opt
    rest, seq, pos = list(range(len(plans))), [], head
    while rest:
        i = min(rest, key=lambda i: (D(pos, plans[i].center), i)); rest.remove(i); seq.append(i); pos = plans[i].center
    improved = True
    while improved and len(seq) > 3:
        improved = False
        for i in range(len(seq) - 1):
            for j in range(i + 1, len(seq)):
                a = plans[seq[i - 1]].center if i else head
                b, c = plans[seq[i]].center, plans[seq[j]].center
                dd = plans[seq[j + 1]].center if j + 1 < len(seq) else None
                old = D(a, b) + (D(c, dd) if dd else 0)
                new = D(a, c) + (D(b, dd) if dd else 0)
                if new < old - 1e-9:
                    seq[i:j + 1] = seq[i:j + 1][::-1]; improved = True
    # точки врезки с местом под подвод
    warnings, lead_min = [], None
    cands = []
    for i in seq:
        p = plans[i]
        others = [polys[j] for j in range(len(plans)) if j != i]
        fr = {k: lead_free(p.started(k), W, L, others) for k in p.cands}
        ok = [k for k in p.cands if fr[k] >= LEAD_FREE]
        if not ok:
            k = max(p.cands, key=lambda k: fr[k]); ok = [k]
            warnings.append("деталь %s: под подвод свободно только %.1f мм" % (p.part["name"], fr[k]))
        cands.append((ok, fr))
    # динамика: состояние — точка врезки предыдущей детали. Переход к детали над уже вырезанной деталью — штраф
    # PART_CROSS_PENALTY (вырезанная деталь может приподняться; CypCut поднимает голову, но лучше не рисковать)
    states = {None: (0.0, head, [], 0)}
    for idx, i in enumerate(seq):
        p = plans[i]
        done = [polys[j] for j in seq[:idx]]
        new = {}
        for key, (cost, hpos, acc, xs) in states.items():
            for k in cands[idx][0]:
                c, sh, x = p.cost(hpos, k)
                xp = 1 if done and _seg_hits(hpos, G.ends(sh[0])[0], done) else 0
                tot = cost + c + CROSS_PENALTY * x + PART_CROSS_PENALTY * xp
                if k not in new or tot < new[k][0] - 1e-9:
                    new[k] = (tot, G.ends(sh[-1])[0], acc + [(i, sh)], xs + x)
        states = new
    _, _, best, xs = min(states.values(), key=lambda v: v[0])
    shapes = [s for _, sh in best for s in sh]
    idle = 0.0
    pos = head
    for s in shapes:
        a, b = G.ends(s); idle += D(pos, a); pos = b
    lead_min = min(cands[idx][1][G_k] for idx, G_k in enumerate(_chosen_k(best, plans)) ) if best else None
    # переходы над вырезанными язычками и над уже вырезанными деталями
    cut_parts, x_parts, pos = [], 0, head
    for i, sh in best:
        a = G.ends(sh[0])[0]
        if cut_parts and _seg_hits(pos, a, cut_parts):
            x_parts += 1
        pos = G.ends(sh[-1])[1]
        cut_parts.append(plans[i].poly)
    return dict(seq=[(placed[i]["part"], sh) for i, sh in best], order=[i for i, _ in best], idle=idle,
                crossings=crossings(shapes, head), crossings_parts=x_parts, lead_min=lead_min, warnings=warnings)


def _chosen_k(best, plans):
    """Индекс кандидата врезки, который выбран для каждой детали (по совпадению начала внешнего контура)."""
    out = []
    for i, sh in best:
        p = plans[i]
        st = G.ends(sh[-1])[0]
        out.append(min(p.cands, key=lambda k: D(G.ends(p.started(k))[0], st)))
    return out


def _seg_hits(a, b, polys, margin=1.0):
    """Отрезок a→b проходит внутри какого-то из многоугольников глубже margin мм."""
    L = D(a, b)
    lo_x, hi_x, lo_y, hi_y = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
    near = [(P, bx) for P, bx in polys if not (bx[2] < lo_x or bx[0] > hi_x or bx[3] < lo_y or bx[1] > hi_y)]
    if not near:
        return False
    steps = int(L / 2) + 1
    for k in range(1, steps):
        t = k / steps
        pt = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        for P, bx in near:
            if bx[0] < pt[0] < bx[2] and bx[1] < pt[1] < bx[3] and G.inside(pt, P) \
                    and min(G.seg_point_dist(pt, P[i - 1], P[i]) for i in range(len(P))) > margin:
                return True
    return False


# =========================================================================================== лист с общим резом
class CoedgeRouteError(ValueError):
    """Группу общего реза не удалось разрезать ни одним порядком деталей — раскладывать без общего реза."""


def _part_crossings(tagged, polys, head):
    """Переходы над уже вырезанными деталями: деталь вырезана после последней своей фигуры.
    tagged — [(фигура, индекс размещения)]."""
    last = {}
    for k, (s, i) in enumerate(tagged):
        last[i] = k
    done, n, pos = [], 0, head
    for k, (s, i) in enumerate(tagged):
        a, b = G.ends(s)
        if done and D(pos, a) > 1.0 and _seg_hits(pos, a, done):
            n += 1
        pos = b
        if last[i] == k:
            done.append(polys[i])
    return n


def route_sheet_coedge(placed, groups, parts, W, L, head=(0.0, 0.0)):
    """Лист с группами общего реза. Единицы резки — группы (блок CypCut «CoedgePart») и одиночные детали.
    Порядок единиц — ближайший сосед по центрам + 2-opt. Порядок деталей группы — лучший из кандидатов по
    (переходы над вырезанными язычками, над вырезанными деталями, холостой ход): малые группы — все порядки, большие —
    обходы (соседями от ближней к головке; от крайних деталей; по центрам; полосами змейкой). Порядок, при котором у
    первой детали нет свободного угла или деталь целиком лежит на вырезанном, CypCut не строит — пропускается; если
    не подошёл ни один — CoedgeRouteError (раскладывать с зазором).
    Вернуть dict(seq=[("part", i, фигуры) | ("group", [i…], фигуры)], idle, crossings, crossings_parts, lead_min, warnings)."""
    from . import coedge as CE
    plans = [_PartPlan(parts[q["part"]], q["rot"], (q["dx"], q["dy"])) for q in placed]
    in_group = {i for g in groups for i in g}
    units = [("group", list(g)) for g in groups] + [("part", [i]) for i in range(len(placed)) if i not in in_group]

    def ucenter(u):
        xs = [plans[i].center for i in u[1]]
        return (sum(x for x, y in xs) / len(xs), sum(y for x, y in xs) / len(xs))
    C = [ucenter(u) for u in units]
    rest, seq_u, pos = list(range(len(units))), [], head
    while rest:
        k = min(rest, key=lambda k: (D(pos, C[k]), k)); rest.remove(k); seq_u.append(k); pos = C[k]
    improved = True
    while improved and len(seq_u) > 3:
        improved = False
        for i in range(len(seq_u) - 1):
            for j in range(i + 1, len(seq_u)):
                a = C[seq_u[i - 1]] if i else head
                b, c = C[seq_u[i]], C[seq_u[j]]
                dd = C[seq_u[j + 1]] if j + 1 < len(seq_u) else None
                if D(a, c) + (D(b, dd) if dd else 0) < D(a, b) + (D(c, dd) if dd else 0) - 1e-9:
                    seq_u[i:j + 1] = seq_u[i:j + 1][::-1]; improved = True
    polys = [p.poly for p in plans]
    out, tagged, warnings, pos = [], [], [], head
    cut_shapes = []                       # всё вырезанное на листе (язычки прорезей)
    cut_parts = []                        # многоугольники вырезанных деталей

    def inner_order(inner, h, targets, done=()):
        """Путь по внутренним контурам детали группы от h к одной из точек начала её внешней части: змейка или
        оптимизатор; лучший по (переходы над вырезанными язычками — с учётом уже вырезанного, холостой ход)."""
        extra = tongue_polys(cut_shapes + list(done))
        best = None
        snake = snake_options(inner)
        cands = []
        for tg in targets[:24]:
            if snake:
                for o in snake:
                    c, where = snake_cost(o, h, tg)
                    cands.append((c, snake_shapes(o, where), tg))
            if len(inner) <= EXACT_N or not snake:
                sh, c = order(inner, h, tg)
                cands.append((c, sh, tg))
        cands.sort(key=lambda v: v[0])
        for c, sh, tg in cands[:40]:                     # самые короткие — с проверкой язычков
            x = crossings(sh, h, extra)
            own = tongue_polys(sh)
            if sh and _seg_hits(G.ends(sh[-1])[1], tg, extra + own, margin=0.5):
                x += 1
            key = (x, c)
            if best is None or key < best[0]:
                best = (key, sh)
        sh = best[1]
        return sh, (G.ends(sh[-1])[1] if sh else h)

    for k in seq_u:
        kind, idx = units[k]
        if kind == "part":
            i = idx[0]
            p = plans[i]
            others = [polys[j] for j in range(len(plans)) if j != i]
            fr = {c: lead_free(p.started(c), W, L, others) for c in p.cands}
            ok = [c for c in p.cands if fr[c] >= LEAD_FREE] or [max(p.cands, key=lambda c: fr[c])]
            if fr[ok[0]] < LEAD_FREE:
                warnings.append("деталь %s: под подвод свободно только %.1f мм" % (p.part["name"], fr[ok[0]]))
            best = None
            for c in ok:
                cost, sh, x = p.cost(pos, c)
                xp = 1 if cut_parts and _seg_hits(pos, G.ends(sh[0])[0], cut_parts) else 0
                key = (x, xp, cost)
                if best is None or key < best[0]:
                    best = (key, sh)
            sh = best[1]
            out.append(("part", placed[i]["part"], sh))
            tagged += [(s, i) for s in sh]
            cut_shapes += sh
            cut_parts.append(polys[i])
            pos = G.ends(sh[-1])[1]
            continue
        outs = {i: plans[i].outer for i in idx}
        nb = {i: set() for i in idx}
        for a in idx:
            for b in idx:
                if a < b and CE.shared_length(outs[a]["verts"], outs[b]["verts"]) > 1e-3:
                    nb[a].add(b); nb[b].add(a)

        def build(order_m, h):
            members = [dict(outer=plans[i].outer, inner=plans[i].inner) for i in order_m]
            try:
                sh, end = CE.build_group(members, head=h, inner_order=inner_order)
            except ValueError:
                return None                       # такой порядок CypCut не строит (нет свободного угла и т.п.)
            idle_g, p0 = 0.0, h
            for s in sh:
                a, b = G.ends(s); idle_g += D(p0, a); p0 = b
            xt = crossings(sh, h, tongue_polys(cut_shapes))
            tg = [(s, order_m[s["member"]]) for s in sh]
            xp = 0
            # переходы над деталями: уже вырезанные на листе + детали группы после своего последнего куска
            last = {}
            for n_, (s, m) in enumerate(tg):
                last[m] = n_
            done_p, p0 = list(cut_parts), h
            for n_, (s, m) in enumerate(tg):
                a, b = G.ends(s)
                if done_p and D(p0, a) > 1.0 and _seg_hits(p0, a, done_p):
                    xp += 1
                p0 = b
                if last[m] == n_:
                    done_p.append(polys[m])
            return (xt, xp, idle_g), sh, end, tuple(order_m)

        def grow(start):
            """Соседями по общей кромке от детали start, каждый раз ближайшая к последней вырезанной."""
            done, order_m, cur = {start}, [start], plans[start].center
            while len(done) < len(idx):
                cand = [i for i in idx if i not in done and nb[i] & done] or [i for i in idx if i not in done]
                i = min(cand, key=lambda i: (D(cur, plans[i].center), i))
                done.add(i); order_m.append(i); cur = plans[i].center
            return order_m
        orders = []
        if len(idx) <= GROUP_PERM_MAX:
            orders = [list(p_) for p_ in itertools.permutations(idx)]
        else:
            orders.append(grow(min(idx, key=lambda i: (D(pos, plans[i].center), i))))
            for f in ((lambda b: (b[1], b[0])), (lambda b: (b[1], -b[2])), (lambda b: (-b[3], b[0])), (lambda b: (-b[3], -b[2]))):
                orders.append(grow(min(idx, key=lambda i: (f(plans[i].poly[1]), i))))   # от крайних деталей группы
            rest_, tour, cur = set(idx), [], pos
            while rest_:
                i = min(rest_, key=lambda i: (D(cur, plans[i].center), i)); rest_.remove(i); tour.append(i); cur = plans[i].center
            imp = True
            while imp:
                imp = False
                for a_ in range(len(tour) - 1):
                    for b_ in range(a_ + 1, len(tour)):
                        pa = plans[tour[a_ - 1]].center if a_ else pos
                        nx = plans[tour[b_ + 1]].center if b_ + 1 < len(tour) else None
                        old_ = D(pa, plans[tour[a_]].center) + (D(plans[tour[b_]].center, nx) if nx else 0)
                        new_ = D(pa, plans[tour[b_]].center) + (D(plans[tour[a_]].center, nx) if nx else 0)
                        if new_ < old_ - 1e-9:
                            tour[a_:b_ + 1] = tour[a_:b_ + 1][::-1]; imp = True
            orders.append(tour)
            for axis in (0, 1):
                band = max(1.0, min(plans[i].poly[1][2 + (1 - axis)] - plans[i].poly[1][1 - axis] for i in idx))
                rows = collections.defaultdict(list)
                for i in idx:
                    rows[int(plans[i].center[1 - axis] // band)].append(i)
                o_, flip = [], False
                for key_ in sorted(rows):
                    o_ += sorted(rows[key_], key=lambda i: plans[i].center[axis], reverse=flip); flip = not flip
                orders.append(o_)
        cands = [c for c in (build(o_, pos) for o_ in orders) if c is not None]
        if not cands:
            raise CoedgeRouteError("группу из %d деталей не удалось разрезать общим резом ни одним порядком" % len(idx))
        _, sh, pos, perm = min(cands, key=lambda v: (v[0], v[3]))
        out.append(("group", [placed[i]["part"] for i in perm], sh))
        tagged += [(s, perm[s["member"]]) for s in sh]
        cut_shapes += sh
        cut_parts += [polys[i] for i in perm]
    shapes = [s for s, i in tagged]
    idle, p0 = 0.0, head
    for s in shapes:
        a, b = G.ends(s); idle += D(p0, a); p0 = b
    return dict(seq=out, idle=idle, crossings=crossings(shapes, head), crossings_parts=_part_crossings(tagged, polys, head),
                lead_min=None, warnings=warnings)
