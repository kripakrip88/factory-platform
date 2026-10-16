# -*- coding: utf-8 -*-
"""Добивка остатков листа складскими позициями (16.10.2026, Антон: «в остатки листа хочу добавить наши складские
позиции опорная нога и опорная стойка»).

Детали заказа раскладываются как всегда (pack.plan / plan_coedge) — листов ровно столько же, сколько без добивки:
добивка только дополняет готовые раскладки и листа не добавляет никогда. Затем на каждой раскладке свободное место
(лист минус край, минус детали, раздутые на зазор) заполняется деталями добивки жадно:
  • по порядку добивки (как заданы; у одной позиции из нескольких контуров — сперва крупные): каждая — пока есть место;
  • повороты 0/90/180/270 (одинаковые по форме — один раз);
  • место — ниже-левее (наименьший Y листа, затем X) по растру RES мм: занятость листа (край, детали — центр клетки
    внутри контура, раздутые на зазор с запасом), допустимые места детали — суммами по окну (деталь-прямоугольник) или
    свёрткой БПФ (любой контур), после каждой установки — пересчёт только около неё;
  • место растра проверяется точно — по контурам (расстояние между многоугольниками ≥ зазора + EPS, точный габарит —
    с дугами — внутри края листа; рядом — небольшие сдвиги, если растр ошибся на клетку), затем деталь поджимается вниз
    и влево ровно до зазора (сдвиг до первого касания считается точно: вершина одного контура входит в полосу шириной
    зазор вокруг ребра другого — как доводка exact_fix пакета, но без бисекции): следующей остаётся больше места.
Предел max позиции — на все листы: на раскладке не больше (max − уже поставлено) // листов раскладки. Позиция из
нескольких деталей (DXF из нескольких контуров «#k») — одна позиция: max — на все её детали вместе, отчёт — одной
строкой с именем позиции, как во входе.
Детали добивки — обычные детали для маршрута, программы, подписей и проверок; количество в программе = поставлено.
"""
import math
import numpy as np
from . import geom as G

RES = 1.0           # мм — шаг растра свободного места
SAG = 0.01          # мм — прогиб хорды дуги у точных контуров (дуга ближе хорды не больше чем на SAG)
EPS = 0.02          # мм — сверх зазора при точной проверке: дуги по хордам (SAG) и допуск проверки зазора в verify
SNUG = 4.0          # мм — поджатие вниз/влево не дальше (растр ошибается на клетку-две)
FAIL_MAX = 400      # мест растра, не прошедших точную проверку, на позицию и раскладку — дальше позиция на ней кончилась
SHIFTS = ((0, 0), (-0.5, 0), (0, -0.5), (-0.5, -0.5), (0.5, 0), (0, 0.5), (0.5, 0.5), (-1, 0), (0, -1), (1, 0), (0, 1))


# ============================================================================================ растр
def scan(P, nx, ny, ox=0.0, oy=0.0, res=RES):
    """Клетки растра ny × nx (клетка (i, j) — центр (ox + (j + ½)·res, oy + (i + ½)·res)), центр которых внутри
    многоугольника P (чётность пересечений по строкам)."""
    out = np.zeros((ny, nx), bool)
    if ny <= 0 or nx <= 0:
        return out
    A = np.asarray(P, float)
    x1, y1 = A[:, 0], A[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    keep = y1 != y2
    x1, y1, x2, y2 = x1[keep], y1[keep], x2[keep], y2[keep]
    if not len(x1):
        return out
    yc = oy + (np.arange(ny) + 0.5) * res
    hit = (y1[None, :] > yc[:, None]) != (y2[None, :] > yc[:, None])
    xs = x1[None, :] + (yc[:, None] - y1[None, :]) * ((x2 - x1) / (y2 - y1))[None, :]
    xs = np.where(hit, xs, np.inf)
    xs.sort(axis=1)
    npair = hit.sum(1) // 2
    diff = np.zeros((ny, nx + 1), np.int32)
    rows = np.arange(ny)
    for k in range(int(npair.max()) if len(npair) else 0):
        ok = npair > k
        a = np.ceil((xs[ok, 2 * k] - ox) / res - 0.5)
        b = np.floor((xs[ok, 2 * k + 1] - ox) / res - 0.5)
        a = np.clip(a, 0, nx).astype(np.int64)
        b = np.clip(b + 1, 0, nx).astype(np.int64)
        good = b > a
        r = rows[ok][good]
        np.add.at(diff, (r, a[good]), 1)
        np.add.at(diff, (r, b[good]), -1)
    return np.cumsum(diff, 1)[:, :nx] > 0


def dilate(a, k):
    """Квадратное расширение на k клеток (по строкам, затем по столбцам); размер растёт на k с каждой стороны."""
    if k <= 0:
        return a.copy()
    h, w = a.shape
    b = np.zeros((h, w + 2 * k), bool)
    for d in range(2 * k + 1):
        b[:, d:d + w] |= a
    c = np.zeros((h + 2 * k, w + 2 * k), bool)
    for d in range(2 * k + 1):
        c[d:d + h, :] |= b
    return c


BAND = 1024         # строк растра на одну свёртку БПФ (маска не прямоугольник): память — полосами, а не весь лист сразу


def _counts(O, mask, rect):
    """Сколько занятых клеток O под маской в каждом её положении (для маски-не-прямоугольника — 0 или 1): [i, j] — левый
    нижний угол маски в клетке (i, j); размер (H − h + 1) × (W − w + 1). Прямоугольник — суммами по окну, иначе —
    свёрткой БПФ полосами по BAND строк (лист 1500×6000 целиком — сотни МБ комплексных чисел)."""
    H, W = O.shape
    h, w = mask.shape
    if h > H or w > W:
        return np.ones((max(0, H - h + 1), max(0, W - w + 1)), np.int32)
    if rect:
        S = np.zeros((H + 1, W + 1), np.int32)
        np.cumsum(np.cumsum(O, 0, dtype=np.int32), 1, out=S[1:, 1:])
        return S[h:, w:] - S[:-h, w:] - S[h:, :-w] + S[:-h, :-w]
    out = np.empty((H - h + 1, W - w + 1), np.int32)
    spec = {}
    for r0 in range(0, H - h + 1, BAND):
        r1 = min(H - h + 1, r0 + BAND)                  # строки ответа r0 … r1 − 1 ← строки O r0 … r1 + h − 2
        sub = O[r0:r1 + h - 1]
        s = (sub.shape[0] + h - 1, W + w - 1)
        if s not in spec:
            spec[s] = np.fft.rfft2(mask[::-1, ::-1].astype(np.float32), s=s)
        conv = np.fft.irfft2(np.fft.rfft2(sub.astype(np.float32), s=s) * spec[s], s=s)
        out[r0:r1] = conv[h - 1:sub.shape[0], w - 1:W] > 0.5
    return out


def _segs(P):
    A = np.asarray(P, float)
    return A, np.roll(A, -1, axis=0)


def _pip(p, s0, s1):
    """Точка p внутри многоугольника (рёбра s0 → s1; чётность пересечений, как geom.inside)."""
    y0, y1 = s0[:, 1], s1[:, 1]
    hit = (y0 > p[1]) != (y1 > p[1])
    if not hit.any():
        return False
    a0, a1 = s0[hit], s1[hit]
    xs = a0[:, 0] + (p[1] - a0[:, 1]) * (a1[:, 0] - a0[:, 0]) / (a1[:, 1] - a0[:, 1])
    return bool(np.count_nonzero(p[0] < xs) & 1)


def _near(s0, s1, box, d):
    """Рёбра, чей габарит ближе d к габариту box (x0, y0, x1, y1)."""
    return ((np.minimum(s0[:, 0], s1[:, 0]) <= box[2] + d) & (np.maximum(s0[:, 0], s1[:, 0]) >= box[0] - d) &
            (np.minimum(s0[:, 1], s1[:, 1]) <= box[3] + d) & (np.maximum(s0[:, 1], s1[:, 1]) >= box[1] - d))


def _pt_seg(p, s0, s1):
    d = s1 - s0
    L2 = (d * d).sum(1)
    L2[L2 == 0] = 1.0
    t = np.clip(((p[:, None, :] - s0[None]) * d[None]).sum(2) / L2[None], 0, 1)
    q = s0[None] + t[..., None] * d[None]
    return float(np.sqrt(((p[:, None, :] - q) ** 2).sum(2)).min())


def poly_dist(A, Abox, B, Bbox, cut):
    """Расстояние между многоугольниками A и B (рёбра (начала, концы)), точно, если оно меньше cut; иначе — число не
    меньше cut. 0 — пересекаются или один внутри другого. Как nest.poly_dist пакета, но по рёбрам не дальше cut от
    габарита другого (ближайшие точки пары — только там) и без цикла Python по вершинам: поджатие считает его десятки
    раз на деталь (шайбы R50 — 270 шт за 40 с)."""
    a0, a1 = A
    b0, b1 = B
    if _pip(a0[0], b0, b1) or _pip(b0[0], a0, a1):     # нет пересечений рёбер — вложенность видна по одной вершине
        return 0.0
    ka, kb = _near(a0, a1, Bbox, cut), _near(b0, b1, Abox, cut)
    if not ka.any() or not kb.any():
        return float(cut)
    a0, a1, b0, b1 = a0[ka], a1[ka], b0[kb], b1[kb]

    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    o1 = orient(a0[:, None], a1[:, None], b0[None]); o2 = orient(a0[:, None], a1[:, None], b1[None])
    o3 = orient(b0[None], b1[None], a0[:, None]); o4 = orient(b0[None], b1[None], a1[:, None])
    if np.any((o1 * o2 < 0) & (o3 * o4 < 0)):
        return 0.0
    return min(_pt_seg(np.vstack([a0, a1]), b0, b1), _pt_seg(np.vstack([b0, b1]), a0, a1))


# ============================================================================================ позиция добивки
class _Shape:
    """Поворот детали добивки: точный контур (от левого нижнего угла габарита), маска растра (центры клеток внутри)."""

    def __init__(self, outer, rot):
        t = G.transform(outer, rot, (0.0, 0.0))
        P = G.points(t, SAG)
        # габарит — точный (дуги по крайним точкам): у хорд он меньше до SAG, и шайба у края листа выходила за край
        # на 0,01 мм
        x0, y0, x1, y1 = G.bbox([t])
        self.mx, self.my = x0, y0
        self.P = [(x - x0, y - y0) for x, y in P]
        self.w, self.h = x1 - x0, y1 - y0
        self.rot = rot
        self.segs = _segs(self.P)
        nx, ny = max(1, int(math.ceil(self.w / RES))), max(1, int(math.ceil(self.h / RES)))
        m = scan(self.P, nx, ny)
        if not m.any():                                 # тоньше клетки — хотя бы клетка
            m[:, :] = True
        rows, cols = np.nonzero(m.any(1))[0], np.nonzero(m.any(0))[0]
        self.mask = m[:rows[-1] + 1, :cols[-1] + 1]
        self.rect = bool(self.mask.all())


def shapes_of(part):
    """Повороты 0/90/180/270 детали, разные по форме маски (у прямоугольника — два)."""
    out, seen = [], set()
    for rot in (0, 90, 180, 270):
        s = _Shape(part["shapes"][-1], rot)
        sig = (s.mask.shape, s.mask.tobytes(), round(s.w, 3), round(s.h, 3))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(s)
    return out


# ============================================================================================ лист
class Sheet:
    """Свободное место раскладки: растр занятости и точные контуры уже стоящих деталей."""

    def __init__(self, W, L, gap, edge):
        self.W, self.L, self.gap, self.edge = float(W), float(L), float(gap), float(edge)
        self.nx, self.ny = int(math.ceil(self.W / RES)), int(math.ceil(self.L / RES))
        self.O = np.ones((self.ny, self.nx), bool)
        j0, j1 = int(math.ceil(self.edge / RES - 1e-9)), int(math.floor((self.W - self.edge) / RES + 1e-9))
        i0, i1 = int(math.ceil(self.edge / RES - 1e-9)), int(math.floor((self.L - self.edge) / RES + 1e-9))
        self.O[i0:i1, j0:j1] = False
        self.k = int(math.ceil((self.gap + EPS) / RES))
        self.obst = []                                  # (сегменты, габарит)
        self.boxes = np.zeros((0, 4))

    def add(self, P):
        """Деталь (точный контур в координатах листа) — препятствие: в точные контуры и в растр (раздутой на зазор)."""
        x0, y0 = min(x for x, y in P), min(y for x, y in P)
        x1, y1 = max(x for x, y in P), max(y for x, y in P)
        self.obst.append(_segs(P))
        self.boxes = np.vstack([self.boxes, [[x0, y0, x1, y1]]])
        j0, i0 = int(math.floor(x0 / RES)), int(math.floor(y0 / RES))
        j1, i1 = int(math.ceil(x1 / RES)) + 1, int(math.ceil(y1 / RES)) + 1
        m = dilate(scan(P, j1 - j0, i1 - i0, j0 * RES, i0 * RES), self.k)
        a0, b0 = i0 - self.k, j0 - self.k
        r0, r1 = max(0, a0), min(self.ny, a0 + m.shape[0])
        c0, c1 = max(0, b0), min(self.nx, b0 + m.shape[1])
        if r1 > r0 and c1 > c0:
            self.O[r0:r1, c0:c1] |= m[r0 - a0:r1 - a0, c0 - b0:c1 - b0]
        return (r0, r1, c0, c1)

    def exact_ok(self, s, x, y):
        """Деталь-поворот s с левым нижним углом габарита в (x, y): внутри края листа и не ближе зазора (+ EPS) ко всем
        стоящим деталям (точно, по контурам)."""
        e = self.edge
        if x < e - 1e-9 or y < e - 1e-9 or x + s.w > self.W - e + 1e-9 or y + s.h > self.L - e + 1e-9:
            return False
        if not len(self.boxes):
            return True
        g = self.gap + EPS
        B = self.boxes
        near = np.nonzero((B[:, 0] < x + s.w + g) & (B[:, 2] > x - g) & (B[:, 1] < y + s.h + g) & (B[:, 3] > y - g))[0]
        A = (s.segs[0] + (x, y), s.segs[1] + (x, y))
        box = (x, y, x + s.w, y + s.h)
        return all(poly_dist(A, box, self.obst[k], B[k], g) >= g for k in near)

    def slide(self, s, x, y, axis, room):
        """На сколько деталь-поворот s из (x, y) можно сдвинуть влево (axis 0) или вниз (1), не дальше room, чтобы
        не подойти к стоящим деталям ближе зазора + EPS (точно: первое касание — вершина одного контура входит в полосу
        шириной зазор вокруг ребра другого, _slide)."""
        if room <= 0 or not len(self.boxes):
            return max(0.0, room)
        g = self.gap + EPS
        B = self.boxes
        if axis:
            sw = (x - g, y - room - g, x + s.w + g, y + s.h + g)
        else:
            sw = (x - room - g, y - g, x + s.w + g, y + s.h + g)
        near = np.nonzero((B[:, 0] < sw[2]) & (B[:, 2] > sw[0]) & (B[:, 1] < sw[3]) & (B[:, 3] > sw[1]))[0]
        t = room
        PA = s.segs[0] + (x, y)
        for k in near:
            b0, b1 = self.obst[k]
            kb = _near(b0, b1, sw, 0.0)
            if kb.any():
                t = min(t, _slide(PA, b0[kb], b1[kb], g, axis))
                if t <= 0:
                    return 0.0
        return t

    def snug(self, s, x, y):
        """Поджать вниз, влево, ещё раз вниз — до зазора, не дальше SNUG мм (точный сдвиг до первого касания, как
        бисекция exact_fix пакета, но за один расчёт на ось)."""
        for axis in (1, 0, 1):
            room = min((y if axis else x) - self.edge, SNUG)
            if room <= 1e-9:
                continue
            t = self.slide(s, x, y, axis, room)
            t = max(0.0, t - 1e-9)                      # касание ровно на зазоре — без ошибки округления внутрь
            if axis:
                y -= t
            else:
                x -= t
        return x, y


def _cap_span(py, c0, c1, g):
    """Пересечение прямой y = py с полосой шириной g вокруг рёбер c0 → c1 (капсула: отрезок ⊕ круг g): [xmin, xmax]
    по рёбрам (nan — не пересекает). Края капсулы — две окружности у концов и две прямые, параллельные ребру."""
    shape = np.broadcast_shapes(np.shape(py), c0.shape[:-1], c1.shape[:-1])
    lo, hi = np.full(shape, np.inf), np.full(shape, -np.inf)
    for c in (c0, c1):
        dy = py - c[..., 1]
        h2 = g * g - dy * dy
        ok = h2 > 1e-9                                  # касание прямой (скольжение по кругу на зазоре) — не вход
        h = np.sqrt(np.where(ok, h2, 0.0))
        lo = np.where(ok, np.minimum(lo, c[..., 0] - h), lo)
        hi = np.where(ok, np.maximum(hi, c[..., 0] + h), hi)
    e = c1 - c0
    L = np.hypot(e[..., 0], e[..., 1])
    Ls = np.where(L > 0, L, 1.0)
    nx, ny = -e[..., 1] / Ls, e[..., 0] / Ls
    ey = e[..., 1]
    eys = np.where(np.abs(ey) > 1e-12, ey, 1.0)
    for sg in (-1.0, 1.0):
        sp = (py - c0[..., 1] - sg * g * ny) / eys
        ok = (np.abs(ey) > 1e-12) & (L > 0) & (sp >= 0) & (sp <= 1)
        xs = c0[..., 0] + sg * g * nx + sp * e[..., 0]
        lo = np.where(ok, np.minimum(lo, xs), lo)
        hi = np.where(ok, np.maximum(hi, xs), hi)
    return lo, hi


def _slide(PA, b0, b1, g, axis):
    """Наибольший сдвиг многоугольника PA (вершины N×2; рёбра — по кругу) влево (axis 0) или вниз (1) до расстояния g
    до рёбер b0 → b1: первое касание — вершина PA входит в капсулу ребра B или вершина B (навстречу) — в капсулу ребра
    PA (наименьшее расстояние двух ломаных — всегда у вершины одной из них). inf — не встретятся."""
    if axis:                                            # вниз — то же влево в осях (y, x)
        PA, b0, b1 = PA[:, ::-1], b0[:, ::-1], b1[:, ::-1]
    a0, a1 = PA, np.roll(PA, -1, axis=0)
    t = np.inf
    # вершины A влево ← капсулы рёбер B: вход — правый край пересечения
    lo, hi = _cap_span(PA[:, None, 1], b0[None], b1[None], g)
    px = PA[:, None, 0]
    hit = np.isfinite(hi) & (lo <= px)
    if hit.any():
        t = min(t, float(np.maximum(0.0, px - hi)[hit].min()))
    # вершины B вправо (навстречу) ← капсулы рёбер A: вход — левый край
    V = np.vstack([b0, b1])
    lo, hi = _cap_span(V[:, None, 1], a0[None], a1[None], g)
    px = V[:, None, 0]
    hit = np.isfinite(lo) & (hi >= px)
    if hit.any():
        t = min(t, float(np.maximum(0.0, lo - px)[hit].min()))
    return t


def _placed_poly(part, q):
    return G.points(G.transform(part["shapes"][-1], q["rot"], (q["dx"], q["dy"])), SAG)


def fill_layout(layout, parts, items, gap, edge, caps, total=None):
    """Одна раскладка: добивка items ([(номер детали добивки, номер позиции, деталь, [повороты])]) в свободное место.
    caps — сколько каждой позиции (всех её деталей вместе) можно поставить на лист (None — сколько влезет), total — всех
    позиций вместе на лист (None — без предела). Вернуть [(номер детали добивки, поворот, dx, dy)] и сколько мест растра
    не прошли точную проверку."""
    sh = Sheet(layout["W"], layout["L"], gap, edge)
    for q in layout["placed"]:
        sh.add(_placed_poly(parts[q["part"]], q))
    out, fails, used = [], 0, {}
    for j, e, part, rots in items:
        cap = None if caps.get(e) is None else caps[e] - used.get(e, 0)
        if total is not None:
            cap = total - len(out) if cap is None else min(cap, total - len(out))
        if cap is not None and cap <= 0:
            continue
        maps = []                                       # [поворот, карта «свободно», указатель, запреты]
        for s in rots:
            C = _counts(sh.O, s.mask, s.rect)
            maps.append([s, C == 0, 0, set()])
        n, nfail = 0, 0
        while (cap is None or n < cap) and nfail < FAIL_MAX:
            best = None
            for m in maps:
                s, F, ptr, ban = m
                if not F.size:
                    continue
                flat = F.reshape(-1)
                k = ptr + int(np.argmax(flat[ptr:])) if ptr < flat.size else flat.size
                if k >= flat.size or not flat[k]:
                    m[2] = flat.size
                    continue
                m[2] = k
                i, c = divmod(k, F.shape[1])
                if best is None or (i, c) < best[0]:
                    best = ((i, c), m, k)
            if best is None:
                break
            (i, c), m, k = best
            s = m[0]
            pos = None
            for dx, dy in SHIFTS:
                x, y = c * RES + dx, i * RES + dy
                if sh.exact_ok(s, x, y):
                    pos = (x, y)
                    break
            if pos is None:                             # растр ошибся — это место запретить, искать дальше
                m[1].reshape(-1)[k] = False
                m[3].add(k)
                nfail += 1
                continue
            x, y = sh.snug(s, *pos)
            P = [(px + x, py + y) for px, py in s.P]
            r0, r1, c0, c1 = sh.add(P)
            out.append((j, s.rot, x - s.mx, y - s.my))
            n += 1
            for mm in maps:                             # пересчёт карт около новой детали
                ss, F, ptr, ban = mm
                h, w = ss.mask.shape
                a0, a1 = max(0, r0 - h + 1), min(F.shape[0], r1)
                b0, b1 = max(0, c0 - w + 1), min(F.shape[1], c1)
                if a1 <= a0 or b1 <= b0:
                    continue
                Cl = _counts(sh.O[a0:a1 + h - 1, b0:b1 + w - 1], ss.mask, ss.rect)
                F[a0:a1, b0:b1] = Cl == 0
                for kb in ban:
                    bi, bc = divmod(kb, F.shape[1])
                    if a0 <= bi < a1 and b0 <= bc < b1:
                        F[bi, bc] = False
        used[e] = used.get(e, 0) + n
        fails += nfail
    return out, fails


def fill_plan(layouts, parts, fillers, gap, edge, qty_left=None, log=None, progress=None):
    """Добивка всех раскладок плана. layouts — раскладки (в placed добавляются детали добивки: part = len(parts) + j);
    parts — детали заказа; fillers — [{"part": Part, "max": int | None, "name": позиция}] по порядку добивки (детали
    одной позиции — подряд, у них один name и один max: cli.split_fill; без name — позиция = деталь). qty_left — сколько
    деталей ещё можно добавить в прогон (предел cli.QTY_MAX); progress — fn(текст) по раскладкам.
    Вернуть (отчёт [{name, placed, per_layout, max, why}] по позициям в порядке fillers — placed на все листы,
    per_layout на лист каждой раскладки; поставлено по деталям fillers [шт])."""
    n0 = len(parts)
    ents, eby = [], {}                                  # позиции: [{name, max, js}] по первому появлению
    for j, f in enumerate(fillers):
        nm = f.get("name") or f["part"]["name"]
        if nm not in eby:
            eby[nm] = len(ents)
            ents.append(dict(name=nm, max=f.get("max"), js=[]))
        ents[eby[nm]]["js"].append(j)
    rep = [dict(name=e["name"], placed=0, per_layout=[0] * len(layouts), max=e["max"], why=None) for e in ents]
    placed = [0] * len(fillers)
    items = []
    for e, en in enumerate(ents):
        if en["max"] == 0:
            rep[e]["why"] = "предел 0 шт"
            continue
        it = []
        for j in en["js"]:
            p = fillers[j]["part"]
            fits = [s for s in shapes_of(p) if s.w <= float(min(l["W"] for l in layouts)) - 2 * edge + 1e-9
                    and s.h <= float(min(l["L"] for l in layouts)) - 2 * edge + 1e-9] if layouts else []
            if fits:
                it.append((j, e, p, fits))
        if not it:
            x0, y0, x1, y1 = G.bbox([fillers[en["js"][0]]["part"]["shapes"][-1]])
            rep[e]["why"] = "деталь %.1f×%.1f мм не помещается на лист с отступом от края %g мм" % (x1 - x0, y1 - y0, edge)
            continue
        items += it
    left = None if qty_left is None else max(0, int(qty_left))
    stopped = False                                     # упёрлись в предел деталей прогона
    capped = {}                                         # позиция → наименьшая раскладка (листов), куда не хватило max
    for li, l in enumerate(layouts):
        if not items:
            break
        if progress:
            progress("добивка остатков листа: раскладка %d из %d" % (li + 1, len(layouts)))
        a = int(l["amount"])
        caps = {}
        for e in sorted({it[1] for it in items}):
            mx = ents[e]["max"]
            if mx is None:
                caps[e] = None
                continue
            rest = max(0, int(mx) - rep[e]["placed"])
            caps[e] = rest // a
            if 0 < rest < a:                            # остаток предела меньше листов раскладки — ни одной
                capped[e] = min(capped.get(e, a), a)
        tcap = None if left is None else left // a
        if tcap == 0:
            stopped = True                              # предел деталей прогона: на все листы раскладки не хватает
            continue
        if all(c == 0 for c in caps.values()):
            continue                                    # пределы max: на все листы этой раскладки уже не хватает
        got, _ = fill_layout(l, parts, items, gap, edge, caps, tcap)
        for j, rot, dx, dy in got:
            l["placed"].append(dict(part=n0 + j, rot=rot, dx=dx, dy=dy, fill=True))
            placed[j] += a
            rep[eby[fillers[j].get("name") or fillers[j]["part"]["name"]]]["per_layout"][li] += 1
        for e in {eby[fillers[g[0]].get("name") or fillers[g[0]]["part"]["name"]] for g in got}:
            rep[e]["placed"] += rep[e]["per_layout"][li] * a
        if left is not None:
            left -= len(got) * a
            stopped = stopped or len(got) >= tcap
        if log and got:
            log("  добивка, раскладка №%d (×%d): %s" % (li + 1, a, ", ".join(
                "%s %d" % (r["name"], r["per_layout"][li]) for r in rep if r["per_layout"][li])))
    for e, r in enumerate(rep):
        if r["why"]:                                    # не помещается на лист, предел 0
            continue
        mx = r["max"]
        if mx is not None and r["placed"] >= mx:
            r["why"] = "поставлено до предела %d шт" % mx
        elif stopped:
            r["why"] = "достигнут предел деталей в прогоне (%d вместе с заказом)" % (int(qty_left) + sum(p["qty"] for p in parts))
        elif not r["placed"] and e in capped:
            r["why"] = ("предел %d шт меньше, чем листов в раскладке (×%d): деталь добивки ставится сразу на все листы "
                        "раскладки" % (mx, capped[e]))
        elif not r["placed"]:
            r["why"] = "на листах нет места: свободные участки меньше детали с зазором %g мм" % gap
        elif mx is not None:
            r["why"] = ("поставлено %d из предела %d шт: на остальных раскладках места нет или на лист раскладки до предела "
                        "не хватает (у раскладки на N листов деталь ставится сразу на все N)" % (r["placed"], mx))
    return rep, placed
