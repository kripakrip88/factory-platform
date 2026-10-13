# -*- coding: utf-8 -*-
"""Общий рез (CypCut «CoedgePart»): построение блока группы из деталей, стоящих вплотную.

Правило восстановлено по 29 блокам групп заводских программ (зонты, m30, m3, m8, решётки; разбор 13.10.2026,
`~/Downloads/vent_nesting/coedge_research/`), проверено независимо; стиль CypCut 6.3.907.8 (m3, m8) воспроизводится
точно (вершины, начало, направление, флаги, sp, LeadParam):

  • детали группы режутся по очереди; у каждой — сначала свои внутренние контуры (копии, flag64 = 0), затем её
    внешний контур «за вычетом уже вырезанного»;
  • контуры деталей разбиваются в точках, где вершина другой детали лежит на ребре (Т-примыкания);
  • если у детали ещё ничего не вырезано — ОДИН ЗАМКНУТЫЙ контур: флаг 1 | 2·(по часовой), outer = 1, coedge = 0,
    вершина 0 — та из вершин у общего участка, у которой больше X (затем Y), sp — номер вершины врезки (свободный
    угол, ни разу не 0), LeadParam = 5 нулевых u32 + f64 sp + 4 нулевых f64;
  • иначе — по ОТКРЫТОЙ ЦЕПОЧКЕ на каждый непрерывный кусок невырезанных участков: флаг 4 | 2·(по часовой),
    coedge = 1, outer = 1, sp = 0, без LeadParam; начало — на том конце, что ближе к концу предыдущего реза;
  • общий участок режется один раз — с той деталью, что идёт раньше; последний контур блока — цепочка.
Направление замкнутого контура: от вершины 0 вдоль общего участка (если общие оба соседних — по часовой).

Общие участки — только прямые (дуг на общих кромках в образцах нет; детали с дугами на кромке в группу не идут).
"""
import math, struct
from . import geom as G

TOL = 1e-4          # мм: вершина другой детали «лежит на ребре»; участок «на уже вырезанном»
LEAD_FMT = "<5I5d"


def lead_payload(sp):
    """LeadParam замкнутого контура группы: 5 нулевых u32, f64 sp, 4 нулевых f64 (29/29 в заводских)."""
    return struct.pack(LEAD_FMT, 0, 0, 0, 0, 0, float(sp), 0.0, 0.0, 0.0, 0.0)


# ------------------------------------------------------------------------------------------------ геометрия участков
def _arc_of(p, q, b):
    (cx, cy), r, th = G.bulge_center(p, q, b)
    return (cx, cy), r, math.atan2(p[1] - cy, p[0] - cx), th


def _seg_sample(p, q, b, n):
    if not b:
        return [(p[0] + (q[0] - p[0]) * i / n, p[1] + (q[1] - p[1]) * i / n) for i in range(n + 1)]
    c, r, a0, sw = _arc_of(p, q, b)
    return [(c[0] + r * math.cos(a0 + sw * i / n), c[1] + r * math.sin(a0 + sw * i / n)) for i in range(n + 1)]


def _pt_seg(x, p, q, b):
    if not b:
        return G.seg_point_dist(x, p, q)
    c, r, a0, sw = _arc_of(p, q, b)
    a = math.atan2(x[1] - c[1], x[0] - c[0])
    da = (a - a0) % (2 * math.pi) if sw > 0 else (a0 - a) % (2 * math.pi)
    if da <= abs(sw) + 1e-12:
        return abs(math.dist(x, c) - r)
    return min(math.dist(x, p), math.dist(x, q))


def _project(x, p, q, b):
    if not b:
        dx, dy = q[0] - p[0], q[1] - p[1]
        t = ((x[0] - p[0]) * dx + (x[1] - p[1]) * dy) / (dx * dx + dy * dy)
        return (p[0] + t * dx, p[1] + t * dy), t
    c, r, a0, sw = _arc_of(p, q, b)
    a = math.atan2(x[1] - c[1], x[0] - c[0])
    da = (a - a0) % (2 * math.pi) if sw > 0 else (a0 - a) % (2 * math.pi)
    return (c[0] + r * math.cos(a), c[1] + r * math.sin(a)), da / abs(sw)


def _segs(verts):
    n = len(verts)
    return [((verts[i][0], verts[i][1]), (verts[(i + 1) % n][0], verts[(i + 1) % n][1]), verts[i][2]) for i in range(n)]


def split_outline(verts, other_pts, tol=TOL):
    """Вставить в замкнутый контур точки Т-примыканий (проекции вершин других деталей, лежащих на его рёбрах)."""
    n = len(verts)
    out = []
    for i in range(n):
        p, q, b = (verts[i][0], verts[i][1]), (verts[(i + 1) % n][0], verts[(i + 1) % n][1]), verts[i][2]
        ts = []
        for x in other_pts:
            if math.dist(x, p) <= tol or math.dist(x, q) <= tol or _pt_seg(x, p, q, b) > tol:
                continue
            f, t = _project(x, p, q, b)
            if 0 < t < 1:
                ts.append((t, f))
        ts.sort()
        pts = []
        for t, f in ts:
            if not pts or math.dist(pts[-1][1], f) > tol:
                pts.append((t, f))
        chain = [(0.0, p)] + pts + [(1.0, q)]
        th = 4 * math.atan(b) if b else 0.0
        for j in range(len(chain) - 1):
            (t0, a), (t1, _) = chain[j], chain[j + 1]
            out.append((a[0], a[1], math.tan(th * (t1 - t0) / 4) if b else b))
    return out


def _on(p, q, b, segs, tol=TOL):
    for x in _seg_sample(p, q, b, 4):
        if min((_pt_seg(x, *s) for s in segs), default=1e9) > tol:
            return False
    return True


def _runs(flags):
    n = len(flags)
    start = next(i for i in range(n) if flags[i - 1] and not flags[i])
    runs, cur = [], None
    for step in range(n):
        j = (start + step) % n
        if not flags[j]:
            cur = (cur or []) + [j]
        elif cur:
            runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    return runs


def _piece(sv, idx, reverse):
    n = len(sv)
    if not reverse:
        vs = [(sv[i][0], sv[i][1], sv[i][2]) for i in idx]
        j = (idx[-1] + 1) % n
        vs.append((sv[j][0], sv[j][1], 0.0))
        return vs
    vs = []
    j = (idx[-1] + 1) % n
    vs.append((sv[j][0], sv[j][1], -sv[idx[-1]][2]))
    for k in range(len(idx) - 1, -1, -1):
        i = idx[k]
        vs.append((sv[i][0], sv[i][1], -sv[idx[k - 1]][2] if k > 0 else 0.0))
    return vs


def _shape(role, verts, flag, sp, member, lead=None):
    return dict(handle=None, kind="LwPolyline", verts=verts, flag=flag, sp=float(sp), layer=1, layer_name="0",
                coedge=1 if role == "chain" else 0, outer=1, flag64=0, lead=lead, member=member, role=role)


# ------------------------------------------------------------------------------------------------ контакты деталей
def shared_length(A, B, tol=TOL):
    """Длина общих прямых участков двух замкнутых контуров (вершины (x, y, bulge)), мм."""
    tot = 0.0
    for p, q, b in _segs(A):
        if b:
            continue
        for r, s, c in _segs(B):
            if c:
                continue
            # коллинеарны и перекрываются
            if G.seg_point_dist(r, p, q) > tol and G.seg_point_dist(s, p, q) > tol and \
                    G.seg_point_dist(p, r, s) > tol and G.seg_point_dist(q, r, s) > tol:
                continue
            L = math.dist(p, q)
            if L < 1e-9:
                continue
            ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
            if abs(ux * (s[1] - r[1]) - uy * (s[0] - r[0])) > tol * max(1.0, math.dist(r, s)):
                continue
            if abs(-uy * (r[0] - p[0]) + ux * (r[1] - p[1])) > tol:
                continue
            t1, t2 = sorted(((r[0] - p[0]) * ux + (r[1] - p[1]) * uy, (s[0] - p[0]) * ux + (s[1] - p[1]) * uy))
            ov = min(L, t2) - max(0.0, t1)
            if ov > tol:
                tot += ov
    return tot


def near_contact(A, B, safe=1.0, end_r=3.0, tol=TOL):
    """Небезопасное сближение двух контуров: точки ближе safe мм, но не на общем участке и не у его концов
    (там цепочка общего реза и так расходится). Вернуть (расстояние, точка) или None."""
    # общие участки — по контурам, разбитым в точках Т-примыканий (как строит CypCut): угол одной детали на кромке
    # другой даёт общий кусок ребра, а не всё ребро
    A = split_outline(A, [(v[0], v[1]) for v in B], tol)
    B = split_outline(B, [(v[0], v[1]) for v in A], tol)
    PA = G.points(dict(kind="LwPolyline", verts=A, flag=1), 0.05)
    shared_pts = []
    for p, q, b in _segs(A):
        if not b and _on(p, q, 0, _segs(B), tol):
            shared_pts += [p, q]
    # касание в точке (углы встык, угол на кромке): вершины одного контура на другом — там контуры и сходятся в ноль
    SB0 = _segs(B)
    shared_pts += [(v[0], v[1]) for v in A if min(_pt_seg((v[0], v[1]), *s) for s in SB0) <= tol]
    SA0 = _segs(A)
    shared_pts += [(v[0], v[1]) for v in B if min(_pt_seg((v[0], v[1]), *s) for s in SA0) <= tol]

    def dens(P, step=0.5):
        out = []
        for a, c in zip(P, P[1:] + P[:1]):
            n = max(1, int(math.dist(a, c) / step))
            out += [(a[0] + (c[0] - a[0]) * k / n, a[1] + (c[1] - a[1]) * k / n) for k in range(n)]
        return out
    SA, SB = _segs(A), _segs(B)
    for x in dens(PA):
        d = min(_pt_seg(x, *s) for s in SB)
        if d <= tol or d >= safe:
            continue
        if any(math.dist(x, e) <= end_r for e in shared_pts):
            continue
        return d, x
    return None


# ------------------------------------------------------------------------------------------------ блок группы
def build_group(members, head=(0.0, 0.0), inner_order=None, tol=TOL, sp_ref=None):
    """members — детали группы в порядке резки: [{"outer": внешний контур (LwPolyline) в координатах листа,
    "inner": [внутренние фигуры в координатах листа]}]. inner_order(inner, head, targets) → (фигуры в порядке, конец пути) —
    порядок внутренних контуров детали (по умолчанию — как даны). sp_ref — точка, к которой ближе всего выбирается
    угол врезки замкнутого контура (CypCut 6.3.907.8: начало листа); по умолчанию — текущее положение головки.
    Вернуть (фигуры блока по порядку, конец резки)."""
    outers = [m["outer"] for m in members]
    for o in outers:
        if o["kind"] != "LwPolyline" or not o["flag"] & 1:
            raise ValueError("в группу общего реза идут только детали с внешним контуром-полилинией")
    pts = [[(v[0], v[1]) for v in o["verts"]] for o in outers]
    split = []
    for k, o in enumerate(outers):
        others = [p for j in range(len(outers)) if j != k for p in pts[j]]
        split.append(split_outline(o["verts"], others, tol))
    out, cut, pos = [], [], head
    for k, m in enumerate(members):
        sv = split[k]
        n = len(sv)
        ccw = G.poly_area(outers[k]["verts"]) > 0
        flags = [_on((sv[i][0], sv[i][1]), (sv[(i + 1) % n][0], sv[(i + 1) % n][1]), sv[i][2], cut, tol) for i in range(n)]
        # куда может прийти путь по внутренним контурам: концы невырезанных кусков (цепочки) или свободные углы
        if any(flags) and not all(flags):
            targets = []
            for r in _runs(flags):
                targets += [(sv[r[0]][0], sv[r[0]][1]), (sv[(r[-1] + 1) % n][0], sv[(r[-1] + 1) % n][1])]
        else:
            other = [p for j in range(len(outers)) if j != k for p in pts[j]]
            targets = [(v[0], v[1]) for v in sv if min((math.dist((v[0], v[1]), q) for q in other), default=1e9) > tol] or \
                [(v[0], v[1]) for v in sv]
        inner = list(m["inner"])
        if inner_order is not None and inner:
            inner, pos = inner_order(inner, pos, targets)
        elif inner:
            pos = G.ends(inner[-1])[1]
        for s in inner:
            t = dict(s, flag64=0, member=k, role="inner")
            out.append(t)
        if not any(flags):
            other_segs = [s for j in range(len(members)) if j != k for s in _segs(split[j])]
            shared = [_on((sv[i][0], sv[i][1]), (sv[(i + 1) % n][0], sv[(i + 1) % n][1]), sv[i][2], other_segs, tol)
                      for i in range(n)]
            adj = [i for i in range(n) if shared[i] or shared[i - 1]] or [0]
            i0 = max(adj, key=lambda i: (round(sv[i][0], 3), round(sv[i][1], 3)))
            fwd_sh, bwd_sh = shared[i0], shared[(i0 - 1) % n]
            rev = bwd_sh if fwd_sh != bwd_sh else ccw          # вдоль общего участка; оба общие — по часовой
            if not rev:
                vs = [(sv[(i0 + j) % n][0], sv[(i0 + j) % n][1], sv[(i0 + j) % n][2]) for j in range(n)]
            else:
                order = [(i0 - j) % n for j in range(n)]
                vs = [(sv[i][0], sv[i][1], -sv[(i - 1) % n][2]) for i in order]
            cw = (not ccw) != rev
            touch = [min((_pt_seg(v[:2], *s) for s in other_segs), default=1e9) <= tol for v in vs]
            A = G.poly_area(vs)

            def convex(i):
                p0, p1, p2 = vs[i - 1], vs[i], vs[(i + 1) % n]
                cr = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
                return (cr > 0) == (A > 0) and abs(cr) > 1e-9
            free = [i for i in range(1, n) if not touch[i]]      # sp ≠ 0 (40/40 у CypCut)
            if not free:
                raise ValueError("у детали группы нет свободного угла для врезки")
            conv = [i for i in free if convex(i)] or free
            ref = sp_ref if sp_ref is not None else pos
            sp = min((free if sp_ref is not None else conv), key=lambda i: (math.dist(ref, vs[i][:2]), i))
            out.append(_shape("closed", vs, 1 | (2 if cw else 0), sp, k, lead_payload(sp)))
            pos = vs[sp][:2]
        elif not all(flags):
            for r in _runs(flags):
                a = (sv[r[0]][0], sv[r[0]][1])
                z = (sv[(r[-1] + 1) % n][0], sv[(r[-1] + 1) % n][1])
                rev = math.dist(pos, z) < math.dist(pos, a)
                vs = _piece(sv, r, rev)
                pos = vs[-1][:2]
                cw = (not ccw) != rev
                out.append(_shape("chain", vs, 4 | (2 if cw else 0), 0, k))
        else:
            raise ValueError("контур детали группы целиком лежит на уже вырезанном — деталь внутри соседей?")
        cut += _segs(sv)
    if out[-1]["role"] != "chain":
        raise ValueError("последний контур группы не цепочка — в группе нет общих кромок")
    return out, pos


def start_point(s):
    """Точка врезки фигуры с учётом sp (у замкнутой полилинии группы врезка в вершине sp)."""
    if s["kind"] == "LwPolyline" and s["flag"] & 1 and s.get("sp"):
        k = int(round(s["sp"])) % len(s["verts"])
        return tuple(s["verts"][k][:2])
    return G.ends(s)[0]


def end_point(s):
    if s["kind"] == "LwPolyline" and s["flag"] & 1:
        return start_point(s)
    return G.ends(s)[1]
