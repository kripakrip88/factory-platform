# -*- coding: utf-8 -*-
"""Детали раскроя → замкнутые контуры, как их хранит CypCut: полилиния с дугами (bulge) и окружности.

Деталь из nest.load_order хранит рёбра вразнобой (отрезки L и дуги A с p0/p1/pm/c/r); здесь они
сцепляются в обход. Внешний контур и пазы — полилинии (вершина = (x, y, bulge до следующей)),
отверстия — окружности (x, y, R).

bulge = tan(угол дуги / 4), знак + — дуга против часовой (как в DXF LWPOLYLINE).
"""
import math
from collections import defaultdict

TOL = 0.05


def _key(p):
    return (round(p[0] / TOL), round(p[1] / TOL))


def _norm(a):
    return a % (2 * math.pi)


def _sweep(e, fwd):
    """Знаковый угол дуги при обходе a→b (через pm)."""
    cx, cy = e["c"]
    a, b = (e["p0"], e["p1"]) if fwd else (e["p1"], e["p0"])
    a0 = math.atan2(a[1] - cy, a[0] - cx)
    a1 = math.atan2(b[1] - cy, b[0] - cx)
    am = math.atan2(e["pm"][1] - cy, e["pm"][0] - cx)
    span = _norm(a1 - a0)
    return span if _norm(am - a0) <= span else -(2 * math.pi - span)


NODE_TOL = 0.01     # концы рёбер ближе 0,01 мм — один узел (DXF пишет 4 знака; дуга и отрезок паза расходятся на 1e-4)


def _node_ids(points, tol=NODE_TOL):
    """Точки → номера узлов: ближе tol — один узел. По расстоянию, а не по клетке округления
    (клетка рвёт пары вроде 1405.525 / 1405.52508 — так падали Ш=1310/1350, 750x2300 и др.)."""
    grid, reps, ids = {}, [], []
    for p in points:
        cx, cy = int(math.floor(p[0] / tol)), int(math.floor(p[1] / tol))
        found = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for nid in grid.get((cx + dx, cy + dy), ()):
                    if math.dist(reps[nid], p) <= tol:
                        found = nid; break
                if found is not None: break
            if found is not None: break
        if found is None:
            found = len(reps); reps.append(p); grid.setdefault((cx, cy), []).append(found)
        ids.append(found)
    return ids


def chain(edges):
    """Рёбра одного замкнутого контура → [(x, y, bulge)], обход по связности. Ошибка, если контур не замкнут."""
    ids = _node_ids([q for e in edges for q in (e["p0"], e["p1"])])
    n0 = {i: ids[2 * i] for i in range(len(edges))}; n1 = {i: ids[2 * i + 1] for i in range(len(edges))}
    adj = defaultdict(list)
    for i in range(len(edges)):
        adj[n0[i]].append(i)
        adj[n1[i]].append(i)
    bad = [k for k, v in adj.items() if len(v) != 2]
    if bad:
        raise ValueError("контур не замкнут или ветвится: %d узлов" % len(bad))
    if any(e.get("virtual") for e in edges):
        raise ValueError("в контуре достроенные отрезки — исходник с разрывом")
    used, out = set(), []
    node = start = n0[0]
    while True:
        cand = [j for j in adj[node] if j not in used]
        if not cand:
            break
        j = cand[0]; used.add(j); e = edges[j]
        fwd = n0[j] == node
        a, b = (e["p0"], e["p1"]) if fwd else (e["p1"], e["p0"])
        bulge = math.tan(_sweep(e, fwd) / 4) if e["t"] == "A" else 0.0
        out.append((a[0], a[1], bulge))
        node = n1[j] if fwd else n0[j]
        if node == start:
            break
    if len(used) != len(edges):
        raise ValueError("контур распался: обойдено %d рёбер из %d" % (len(used), len(edges)))
    return out


def area(poly):
    """Знаковая площадь полилинии с дугами (+ против часовой)."""
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1, b = poly[i]
        x2, y2, _ = poly[(i + 1) % n]
        s += (x1 * y2 - x2 * y1) / 2
        if b:
            th = 4 * math.atan(b)                  # знаковый угол дуги
            c = math.hypot(x2 - x1, y2 - y1)
            r = c / (2 * math.sin(abs(th) / 2))
            seg = r * r * (abs(th) - math.sin(abs(th))) / 2
            s += seg if th > 0 else -seg
    return s


def length(poly):
    t = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1, b = poly[i]
        x2, y2, _ = poly[(i + 1) % n]
        c = math.hypot(x2 - x1, y2 - y1)
        if b:
            th = abs(4 * math.atan(b))
            t += c / (2 * math.sin(th / 2)) * th
        else:
            t += c
    return t


def orient(poly, ccw):
    """Тот же контур с нужным направлением обхода (bulge меняет знак и сдвигается на ребро)."""
    if (area(poly) > 0) == ccw:
        return list(poly)
    n = len(poly)
    return [(poly[(n - i) % n][0], poly[(n - i) % n][1], -poly[(n - i - 1) % n][2]) for i in range(n)]


def components(edges):
    ids = _node_ids([q for e in edges for q in (e["p0"], e["p1"])])
    parent = {}

    def f(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for i in range(len(edges)):
        parent[f(ids[2 * i])] = f(ids[2 * i + 1])
    comp = defaultdict(list)
    for i, e in enumerate(edges):
        comp[f(ids[2 * i])].append(e)
    return list(comp.values())


def part_contours(item):
    """Контуры детали в её собственных координатах (как в nest.load_order: от левого-нижнего угла габарита)."""
    outer = chain(item["edges"])
    slots = [chain(es) for es in components(item["slot_edges"])]
    holes = [(x, y, d / 2) for x, y, d in item["holes"]]
    return {"outer": outer, "slots": slots, "holes": holes}


def transform(c, r, ox, oy, rot_pt, off):
    """Поворот на r (0/90/180/270, без зеркала) и перенос — по тем же правилам, что nest.sheet_dxf."""
    def T(x, y):
        X, Y = rot_pt((x, y), r)
        return X - off[0] + ox, Y - off[1] + oy
    tp = lambda poly: [T(x, y) + (b,) for x, y, b in poly]    # поворот без зеркала bulge не меняет
    return {"outer": tp(c["outer"]), "slots": [tp(s) for s in c["slots"]],
            "holes": [T(x, y) + (R,) for x, y, R in c["holes"]]}


def placed(sheet, rot_pt, rotated):
    """Все детали листа в координатах листа: [(item, r, contours)]."""
    out = []
    for it, r, ox, oy in sheet.placed:
        _, off = rotated(it["poly"], r)
        out.append((it, r, transform(part_contours(it), r, ox, oy, rot_pt, off)))
    return out
