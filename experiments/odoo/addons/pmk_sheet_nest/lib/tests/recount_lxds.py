# -*- coding: utf-8 -*-
"""Независимый пересчёт опасных переходов по готовой программе (.lxds) — для проверки sheet_nest.risk.

Ничего из risk.py и route.py: программа разбирается сборщиком пакета (spec_rebuild.decompile), детали и их классы —
по плану раскроя, освобождение детали — когда её контур покрыт вырезанными кусками (точки контура через 1 мм ближе
0,05 мм к вырезанному), классы перехода — точками через STEP мм (numpy), вписанная окружность — перебором точек сетки.
Правила те же, что в DESIGN.md: «над» — ≥ 0,5 мм пути глубже 1 мм (деталь) / 0,5 мм (отверстие, язычок); впритирку —
ближе 5 мм без первых и последних 10 мм и не над деталью; короткий — 0,01…10 мм.

    from recount_lxds import recount
    per_layout = recount(raw, parts, layouts, small=100)   # [{tongues, small, parts, holes, holes_s, near, short, mj,
                                                           #   ret_m, ret_over_m, ret_tongues, ret_n_tongues,
                                                           #   ret_n_small, ret_n_parts, ret_n_holes}]
"""
import math
import numpy as np
from sheet_nest.libpath import vn
from sheet_nest import geom as G

STEP = 0.1
CLS = ("tongues", "small", "parts", "holes", "holes_s", "near", "short", "mj")


class Poly:
    def __init__(self, pts):
        self.P = np.asarray(pts, float)
        self.A, self.B = self.P, np.roll(self.P, -1, axis=0)
        self.bx = (self.P[:, 0].min(), self.P[:, 1].min(), self.P[:, 0].max(), self.P[:, 1].max())

    def bdist(self, Q):
        A, d = self.A[None], (self.B - self.A)[None]
        L2 = (d ** 2).sum(-1)
        t = np.clip(((Q[:, None, :] - A) * d).sum(-1) / np.where(L2 == 0, 1, L2), 0, 1)
        pr = A + t[..., None] * d
        return np.sqrt(((Q[:, None, :] - pr) ** 2).sum(-1)).min(1)

    def inside(self, Q):
        x, y = Q[:, 0:1], Q[:, 1:2]
        x1, y1, x2, y2 = self.A[:, 0][None], self.A[:, 1][None], self.B[:, 0][None], self.B[:, 1][None]
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        return ((((y1 > y) != (y2 > y)) & (x < xi)).sum(1) % 2) == 1

    def box_hit(self, Q, pad=0.0):
        return (Q[:, 0] > self.bx[0] - pad) & (Q[:, 0] < self.bx[2] + pad) & (Q[:, 1] > self.bx[1] - pad) & (Q[:, 1] < self.bx[3] + pad)

    def deep(self, Q, margin):
        """Длина пути (точки Q через STEP) глубже margin внутри."""
        m = self.box_hit(Q)
        if not m.any():
            return 0.0
        q = Q[m]
        ins = self.inside(q)
        if not ins.any():
            return 0.0
        return float((self.bdist(q[ins]) > margin).sum()) * STEP

    def near(self, Q, d):
        m = self.box_hit(Q, d)
        if not m.any():
            return False
        q = Q[m]
        return bool(self.inside(q).any() or (self.bdist(q) < d).any())


def samples(a, b, trim=0.0):
    L = math.dist(a, b)
    if L <= 2 * trim + 1e-9:
        return None
    n = max(2, int(math.ceil((L - 2 * trim) / STEP)))
    t = (trim + (np.arange(n) + 0.5) * (L - 2 * trim) / n) / L
    return np.stack([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], 1)


def start_end(s):
    if s["kind"] == "Line":
        return tuple(s["p1"]), tuple(s["p2"])
    if s["kind"] == "Circle":
        p = (s["c"][0] + s["r"] * math.cos(s["a0"]), s["c"][1] + s["r"] * math.sin(s["a0"]))
        return p, p
    v = s["verts"]
    if s["flag"] & 1:
        p = tuple(v[int(round(s.get("sp") or 0)) % len(v)][:2])
        return p, p
    return tuple(v[0][:2]), tuple(v[-1][:2])


def inscribed(P):
    """Диаметр вписанной окружности перебором: точки сетки 0,1 мм внутри, наибольшее расстояние до кромки × 2."""
    poly = Poly(P)
    x0, y0, x1, y1 = poly.bx
    xs, ys = np.arange(x0, x1, 0.1), np.arange(y0, y1, 0.1)
    if not len(xs) or not len(ys):
        return 0.0
    g = np.stack(np.meshgrid(xs, ys), -1).reshape(-1, 2)
    g = g[poly.inside(g)]
    best = 0.0
    for k in range(0, len(g), 4000):
        best = max(best, float(poly.bdist(g[k:k + 4000]).max()))
    return 2 * best


def hazard(s):
    """Вырезанное внутри детали: ("holes" | "holes_s" | "tongues", Poly) или None."""
    if s["layer"] != 1 or s.get("outer"):
        return None
    if G.is_closed(s):
        if s["kind"] == "Circle":
            d = 2 * s["r"]
            P = [(s["c"][0] + s["r"] * math.cos(2 * math.pi * k / 720), s["c"][1] + s["r"] * math.sin(2 * math.pi * k / 720)) for k in range(720)]
        else:
            P = G.points(s, 0.02)
            d = inscribed(P)
        return ("holes" if d >= 9.95 else "holes_s", Poly(P))
    if s["kind"] == "LwPolyline" and not s.get("coedge"):
        P = G.points(s, 0.05)
        a = abs(sum(P[i - 1][0] * P[i][1] - P[i][0] * P[i - 1][1] for i in range(len(P)))) / 2
        if len(P) >= 3 and a >= 1.0:
            return ("tongues", Poly(P))
    return None


def recount(raw, parts, layouts, small=100.0):
    M = vn.spec_rebuild.decompile(raw)
    bn = {b["name"]: b for b in M["blocks"]}
    out = []
    for r, lay in zip(M["results"], layouts):
        polys, kinds, outline = [], [], []
        for q in lay["placed"]:
            p = parts[q["part"]]
            o = G.transform(p["shapes"][-1], q["rot"], (q["dx"], q["dy"]))
            P = G.points(o, 0.05)
            polys.append(Poly(P))
            x0, y0, x1, y1 = G.bbox([o])
            kinds.append("mj" if p.get("microjoints") else ("small" if min(x1 - x0, y1 - y0) < small else "parts"))
            pts = []                                            # точки контура через ~1 мм
            for a, b in zip(P, P[1:] + P[:1]):
                n = max(1, int(math.dist(a, b)))
                pts += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
            outline.append(np.asarray(pts))
        covered = [np.zeros(len(o), bool) for o in outline]
        freed = [False] * len(polys)
        cut = []                                                # (класс, Poly, номер детали)
        cnt = dict.fromkeys(CLS, 0)
        pos = (0.0, 0.0)
        for ins in r["inserts"]:
            for s in bn[ins["block"]]["shapes"]:
                a, b = start_end(s)
                L = math.dist(pos, a)
                if L > 0.01:
                    if L < 10.0:
                        cnt["short"] += 1
                    if L > 1.0:
                        Q = samples(pos, a)
                        sb = (min(pos[0], a[0]) - 5, min(pos[1], a[1]) - 5, max(pos[0], a[0]) + 5, max(pos[1], a[1]) + 5)

                        def close(bx):                  # габариты рядом (с запасом 5 мм) — остальные не нужны
                            return not (bx[2] < sb[0] or bx[0] > sb[2] or bx[3] < sb[1] or bx[1] > sb[3])
                        fr = [j for j in range(len(polys)) if freed[j] and close(polys[j].bx)]
                        over = {}
                        for kd in ("small", "parts", "mj"):
                            over[kd] = sum(polys[j].deep(Q, 1.0) for j in fr if kinds[j] == kd) >= 0.5 - 1e-6
                        for kd in ("tongues", "holes", "holes_s"):
                            over[kd] = sum(pp.deep(Q, 0.5) for c, pp, j in cut
                                           if c == kd and (j is None or not freed[j] or kinds[j] == "mj") and close(pp.bx)) >= 0.5 - 1e-6
                        for kd, v in over.items():
                            cnt[kd] += v
                        if not over["small"] and not over["parts"]:
                            Qt = samples(pos, a, 10.0)
                            if Qt is not None and any(polys[j].near(Qt, 5.0) for j in fr if kinds[j] != "mj"):
                                cnt["near"] += 1
                # вырезано: внутреннее — к своей детали; кусок контура — покрывает контуры
                h = hazard(s)
                if h:
                    owner = next((j for j, pp in enumerate(polys) if pp.inside(np.asarray([a]))[0]), None)
                    cut.append((h[0], h[1], owner))
                if s["layer"] == 1 and s.get("outer"):
                    S = np.asarray(G.points(s, 0.02) + ([G.points(s, 0.02)[0]] if G.is_closed(s) else []))
                    seg = Poly(S)
                    for j in range(len(polys)):
                        if freed[j]:
                            continue
                        bx = polys[j].bx
                        if seg.bx[2] < bx[0] - 1 or seg.bx[0] > bx[2] + 1 or seg.bx[3] < bx[1] - 1 or seg.bx[1] > bx[3] + 1:
                            continue
                        A, d = S[:-1][None], (S[1:] - S[:-1])[None]
                        L2 = (d ** 2).sum(-1)
                        Q = outline[j][:, None, :]
                        t = np.clip(((Q - A) * d).sum(-1) / np.where(L2 == 0, 1, L2), 0, 1)
                        dist = np.sqrt(((Q - (A + t[..., None] * d)) ** 2).sum(-1)).min(1)
                        covered[j] |= dist < 0.05
                        if covered[j].all():
                            freed[j] = True
                pos = b
        # возврат в ноль после листа (настройка станка): длина; метры над вырезанными деталями (к концу листа вырезано
        # всё — над любой); сколько вырезанных язычков он пересекает глубже 0,5 мм (≥ 0,5 мм пути); в ключе — число
        # объектов под ним по ступеням (ret_n_*): освобождённые мелкие и прочие — каждая ≥ 0,5 мм пути глубже 1 мм,
        # язычки и отверстия ≥ 10 не освобождённых (и с перемычками) — глубже 0,5 мм; по чуть-чуть над несколькими, но
        # вместе ≥ 0,5 мм — один (как переход программы)
        Q = samples(pos, (0.0, 0.0))
        cnt["ret_m"] = math.dist(pos, (0.0, 0.0)) / 1000
        for kd in ("tongues", "small", "parts", "holes"):
            cnt["ret_n_" + kd] = 0
        if Q is None:
            cnt["ret_over_m"], cnt["ret_tongues"] = 0.0, 0
        else:
            ins = np.zeros(len(Q), bool)
            for pp in polys:
                m = pp.box_hit(Q)
                if m.any():
                    ins[np.where(m)[0][pp.inside(Q[m])]] = True
            cnt["ret_over_m"] = float(ins.sum()) * (math.dist(pos, (0.0, 0.0)) / len(Q)) / 1000
            cnt["ret_tongues"] = sum(1 for c, pp, j in cut if c == "tongues" and pp.deep(Q, 0.5) >= 0.5 - 1e-6)
            ds = {kd: [polys[j].deep(Q, 1.0) for j in range(len(polys)) if freed[j] and kinds[j] == kd] for kd in ("small", "parts")}
            for kd in ("tongues", "holes"):
                ds[kd] = [pp.deep(Q, 0.5) for c, pp, j in cut if c == kd and (j is None or not freed[j] or kinds[j] == "mj")]
            for kd, d in ds.items():
                cnt["ret_n_" + kd] = sum(1 for x in d if x >= 0.5 - 1e-6) or int(sum(d) >= 0.5 - 1e-6)
        out.append(cnt)
    return out
