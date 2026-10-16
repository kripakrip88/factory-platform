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

Общий рез (16.10.2026, Антон: «нужен общий рез в раскрое»; co_layout): добивка с внешним контуром-прямоугольником
встаёт ВПЛОТНУЮ — к другой добивке и к прямым кромкам деталей заказа вдоль осей листа длиной ≥ CO_TOUCH_MIN — общим
прямым участком ≥ CO_CONTACT_MIN; со всем прочим (дуги, фаски, вырезы углов, короткие кромки, круглая добивка) — не
ближе зазора. Сначала раскладка с зазором (как без общего реза — столько же деталей), затем поджатие вплотную (точный
сдвиг вниз и влево до касания прямых кромок, до зазора — от прочих), проверка каждого касания (общий участок, нет
сближения 0 < d < зазора вне 3 мм от точек касания — coedge.near_contact; клин у конца общего участка всегда ≥ 90°:
кромки вдоль осей, а фаска у конца — дальше зазора), затем добор в освободившееся место (вплотную к стоящей добивке и
с зазором — растром). Деталей не меньше, чем с зазором. Группы общего реза листа пересчитываются (pack.coedge_groups);
группа с добивкой должна строиться (route.group_buildable) и не замыкать «карманов» остатка листа (pockets) — иначе на
этой раскладке без касаний деталей заказа, затем — с зазором, как было.
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


def fill_plan(layouts, parts, fillers, gap, edge, qty_left=None, log=None, progress=None, coedge=False, co_stats=None):
    """Добивка всех раскладок плана. layouts — раскладки (в placed добавляются детали добивки: part = len(parts) + j);
    parts — детали заказа; fillers — [{"part": Part, "max": int | None, "name": позиция}] по порядку добивки (детали
    одной позиции — подряд, у них один name и один max: cli.split_fill; без name — позиция = деталь). qty_left — сколько
    деталей ещё можно добавить в прогон (предел cli.QTY_MAX); progress — fn(текст) по раскладкам.
    coedge — раскрой под общий рез (у раскладок groups): добивка-прямоугольник вплотную (co_layout), группы раскладки
    пересчитываются; co_stats — словарь: сюда сведения (по позициям — сколько с зазором и сколько вышло, касания, общие
    кромки, раскладки без касаний и почему). У такой раскладки — ещё fill_gap: {placed — добивка с зазором (как без
    общего реза), groups — группы деталей заказа}: вариант для сравнения в сводке (cli.gap_variant).
    Вернуть (отчёт [{name, placed, per_layout, max, why}] по позициям в порядке fillers — placed на все листы,
    per_layout на лист каждой раскладки; поставлено по деталям fillers [шт])."""
    n0 = len(parts)
    allparts = list(parts) + [dict(f["part"], fill=True) for f in fillers]   # как в программе (route: группы с добивкой)
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
        if coedge and (got or any(rect_part(it[2]) for it in items)):
            got0 = got
            # добивка с зазором при тех же деталях заказа — для сравнения в сводке (cli, --compare: «добивка с зазором»)
            l["fill_gap"] = dict(placed=[dict(part=n0 + j, rot=rot, dx=dx, dy=dy, fill=True) for j, rot, dx, dy in got0],
                                 groups=[list(g) for g in l.get("groups") or []])
            got, groups, ci = co_layout(l, parts, allparts, items, got, gap, edge, caps, tcap, n0)
            l["groups"] = groups
            if co_stats is not None:
                _co_note(co_stats, li, a, ci, got0, got, fillers, eby)
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
            ci_ = (co_stats or {}).get("layouts", {}).get(li + 1)
            log("  добивка, раскладка №%d (×%d): %s%s" % (li + 1, a, ", ".join(
                "%s %d" % (r["name"], r["per_layout"][li]) for r in rep if r["per_layout"][li]), _co_line(ci_) if ci_ else ""))
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


# ============================================================================================ общий рез (16.10.2026)
CO_TOUCH_MIN = 50.0     # мм: прямая кромка детали заказа вдоль оси листа не короче — к ней добивку можно вплотную
CO_CONTACT_MIN = 10.0   # мм: общий прямой участок добивки с соседом не короче (короче, касание углом — нельзя)
CO_END_R = 3.0          # мм: сближение у точек касания не в счёт (как coedge.near_contact: там контуры и сходятся)
CO_TOL = 1e-6           # мм: «вплотную» — места считаются точным сдвигом до касания
CO_STEP = 0.1           # мм: шаг точек при проверке сближения (как coedge.near_contact)
CO_PASSES = 4           # проходов поджатия
CO_ROUNDS = 3           # кругов «поджатие → добор»
POCKET_RES = 1.0        # мм: растр поиска «карманов» остатка листа, замкнутых группой
POCKET_MIN = 4.0        # мм²: карман меньше — шум растра на углах
CO_POCKET_WIN = 300.0   # мм вокруг добивки: окно проверки «не замкнула ли карман» при касании двух и более соседей
CO_GROUP_MAX = 30       # деталей в группе общего реза с добивкой не больше (маршрут большой группы — O(n²…n³)): касание,
                        # которое растит группу дальше, — нет (добивка остаётся с зазором; деталей не меньше)


def rect_part(part):
    """Внешний контур детали — прямоугольник: замкнутая полилиния из прямых участков вдоль осей, площадь = габарит
    (лишние вершины на сторонах допустимы)."""
    o = part["shapes"][-1]
    if o["kind"] != "LwPolyline" or not o["flag"] & 1 or len(o["verts"]) < 4 or any(abs(v[2]) > 1e-12 for v in o["verts"]):
        return False
    V, n = o["verts"], len(o["verts"])
    for i in range(n):
        (x1, y1, _), (x2, y2, _) = V[i], V[(i + 1) % n]
        if abs(x2 - x1) > 1e-9 and abs(y2 - y1) > 1e-9:
            return False
    x0, y0, x1, y1 = G.bbox([o])
    A = (x1 - x0) * (y1 - y0)
    return A > 0 and abs(abs(G.poly_area(V)) - A) <= 1e-6 * A


def _edges(outer, sag=SAG):
    """Рёбра контура (у дуг — хорды с прогибом ≤ sag) и признак «прямой участок» у каждого: (начала, концы, прямой)."""
    if outer["kind"] == "Circle":
        P = np.asarray(G.points(outer, sag), float)
        return P, np.roll(P, -1, axis=0), np.zeros(len(P), bool)
    V, n = outer["verts"], len(outer["verts"])
    pts, st = [], []
    for i in range(n):
        x1, y1, b = V[i]
        x2, y2, _ = V[(i + 1) % n]
        pts.append((x1, y1))
        if abs(b) > 1e-12 and math.hypot(x2 - x1, y2 - y1) > 1e-12:
            (cx, cy), r, th = G.bulge_center((x1, y1), (x2, y2), b)
            a1 = math.atan2(y1 - cy, x1 - cx)
            m = G.arc_steps(r, th, sag)
            for k in range(1, m):
                a = a1 + th * k / m
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            st += [False] * m
        else:
            st.append(True)
    P = np.asarray(pts, float)
    return P, np.roll(P, -1, axis=0), np.asarray(st, bool)


def _axis_edges(s0, s1):
    """Рёбра вдоль осей листа (вертикальные или горизонтальные)."""
    return (np.abs(s1[:, 0] - s0[:, 0]) <= 1e-9) | (np.abs(s1[:, 1] - s0[:, 1]) <= 1e-9)


def _pt_rect(P, R):
    """Расстояние от точек P (N×2) до прямоугольника R = (x0, y0, x1, y1) (сплошного: внутри — 0)."""
    dx = np.maximum(np.maximum(R[0] - P[:, 0], 0.0), P[:, 0] - R[2])
    dy = np.maximum(np.maximum(R[1] - P[:, 1], 0.0), P[:, 1] - R[3])
    return np.hypot(dx, dy)


def _seg_in_rect(s0, s1, R):
    """Отрезки s0 → s1, задевающие замкнутый прямоугольник R (отсечение Лианга — Барски)."""
    d = s1 - s0
    lo, hi = np.zeros(len(s0)), np.ones(len(s0))
    ok = np.ones(len(s0), bool)
    for ax, (a, b) in ((0, (R[0], R[2])), (1, (R[1], R[3]))):
        dd, pp = d[:, ax], s0[:, ax]
        z = np.abs(dd) < 1e-15
        ok &= ~z | ((pp >= a) & (pp <= b))
        dds = np.where(z, 1.0, dd)
        t1, t2 = (a - pp) / dds, (b - pp) / dds
        lo = np.maximum(lo, np.where(z, -np.inf, np.minimum(t1, t2)))
        hi = np.minimum(hi, np.where(z, np.inf, np.maximum(t1, t2)))
    return ok & (lo <= hi)


def _seg_rect_dist(s0, s1, R):
    """Расстояние от каждого отрезка до сплошного прямоугольника R (точно: у выпуклых — от концов отрезка до R или от
    углов R до отрезка)."""
    if not len(s0):
        return np.zeros(0)
    d = np.minimum(_pt_rect(s0, R), _pt_rect(s1, R))
    C = np.array([(R[0], R[1]), (R[2], R[1]), (R[2], R[3]), (R[0], R[3])], float)
    e = s1 - s0
    L2 = (e * e).sum(1)
    t = np.clip(((C[:, None, :] - s0[None]) * e[None]).sum(2) / np.where(L2 > 0, L2, 1.0)[None], 0, 1)
    q = s0[None] + t[..., None] * e[None]
    dc = np.sqrt(((C[:, None, :] - q) ** 2).sum(2)).min(0)
    return np.where(_seg_in_rect(s0, s1, R), 0.0, np.minimum(d, dc))


def _pt_segs(P, s0, s1):
    """Расстояние от точек P (N×2) до ближайшего из отрезков s0 → s1."""
    e = s1 - s0
    L2 = (e * e).sum(1)
    t = np.clip(((P[:, None, :] - s0[None]) * e[None]).sum(2) / np.where(L2 > 0, L2, 1.0)[None], 0, 1)
    q = s0[None] + t[..., None] * e[None]
    return np.sqrt(((P[:, None, :] - q) ** 2).sum(2)).min(1)


def _sweep(R, a0, a1, axis):
    """Наибольший сдвиг прямоугольника R влево (axis 0) или вниз (1) до касания рёбер a0 → a1 вдоль осей: ребро
    задерживает, если входит во внутренность R (касание по линии — скольжение вдоль соседа — не держит). inf — не
    встретятся."""
    if axis:
        R = (R[1], R[0], R[3], R[2])
        a0, a1 = a0[:, ::-1], a1[:, ::-1]
    x0, y0, x1, y1 = R
    t = np.inf
    vert = np.abs(a1[:, 0] - a0[:, 0]) <= 1e-9
    if vert.any():
        e = a0[vert, 0]
        ya, yb = np.minimum(a0[vert, 1], a1[vert, 1]), np.maximum(a0[vert, 1], a1[vert, 1])
        hit = (np.maximum(ya, y0) < np.minimum(yb, y1) - 1e-9) & (e <= x0 + 1e-9)
        if hit.any():
            t = min(t, float(np.max([0.0, (x0 - e[hit]).min()])))
    hor = ~vert
    if hor.any():
        c = a0[hor, 1]
        xb = np.maximum(a0[hor, 0], a1[hor, 0])
        hit = (c > y0 + 1e-9) & (c < y1 - 1e-9) & (xb <= x0 + 1e-9)
        if hit.any():
            t = min(t, float(np.max([0.0, (x0 - xb[hit]).min()])))
    return t


class CoSheet:
    """Лист для добивки под общий рез: препятствия — рёбра деталей (у каждого признак «можно вплотную»), точные
    сдвиги до касания и проверка места прямоугольника добивки (вплотную — общим участком, иначе не ближе зазора)."""

    def __init__(self, W, L, gap, edge):
        self.W, self.L, self.gap, self.edge = float(W), float(L), float(gap), float(edge)
        self.G = self.gap + EPS
        self.obs = []                                   # [начала, концы, вплотную, габарит, вид]
        self.B = np.zeros((0, 4))

    def add(self, s0, s1, touch, kind):
        box = (float(min(s0[:, 0].min(), s1[:, 0].min())), float(min(s0[:, 1].min(), s1[:, 1].min())),
               float(max(s0[:, 0].max(), s1[:, 0].max())), float(max(s0[:, 1].max(), s1[:, 1].max())))
        self.obs.append([s0, s1, np.asarray(touch, bool), box, kind])
        self.B = np.vstack([self.B, [box]])
        return len(self.obs) - 1

    @staticmethod
    def rect_edges(R):
        s0 = np.array([(R[0], R[1]), (R[2], R[1]), (R[2], R[3]), (R[0], R[3])], float)
        return s0, np.roll(s0, -1, axis=0)

    def add_rect(self, R, kind="fill"):
        s0, s1 = self.rect_edges(R)
        return self.add(s0, s1, np.ones(4, bool), kind)

    def move(self, k, R):
        s0, s1 = self.rect_edges(R)
        self.obs[k][0], self.obs[k][1], self.obs[k][3] = s0, s1, tuple(R)
        self.B[k] = R

    def near(self, box, d, skip=()):
        B = self.B
        if not len(B):
            return []
        m = (B[:, 0] < box[2] + d) & (B[:, 2] > box[0] - d) & (B[:, 1] < box[3] + d) & (B[:, 3] > box[1] - d)
        return [int(k) for k in np.nonzero(m)[0] if int(k) not in skip]

    def slide(self, R, axis, room, skip=()):
        """На сколько прямоугольник R можно сдвинуть влево (0) или вниз (1), не дальше room: до касания рёбер «вплотную»,
        до зазора + EPS — от прочих (_slide, капсулы)."""
        if room <= 1e-12:
            return 0.0
        g = self.G
        x0, y0, x1, y1 = R
        sw = (x0 - room - g, y0 - g, x1 + g, y1 + g) if axis == 0 else (x0 - g, y0 - room - g, x1 + g, y1 + g)
        t = room
        PA = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], float)
        for k in self.near(sw, 0.0, skip):
            s0, s1, tm, box, kind = self.obs[k]
            nt = ~tm
            if nt.any():
                a0, a1 = s0[nt], s1[nt]
                kb = _near(a0, a1, sw, 0.0)
                if kb.any():
                    t = min(t, _slide(PA, a0[kb], a1[kb], g, axis) - 1e-9)
            if tm.any():
                t = min(t, _sweep(R, s0[tm], s1[tm], axis))
            if t <= 0:
                return 0.0
        return max(0.0, t)

    def ok(self, R, skip=(), stat=None, touched=None):
        """Место прямоугольника добивки R: внутри края; с каждым соседом — вплотную общим участком ≥ CO_CONTACT_MIN по
        рёбрам «вплотную» (нет наложения, нет сближения 0 < d < зазора вне CO_END_R от точек касания), иначе не ближе
        зазора (+ EPS — от рёбер не «вплотную»: дуги по хордам). stat — {вид соседа: общая длина} касаний."""
        x0, y0, x1, y1 = R
        e = self.edge
        if x0 < e - 1e-9 or y0 < e - 1e-9 or x1 > self.W - e + 1e-9 or y1 > self.L - e + 1e-9:
            return False
        for k in self.near(R, self.G, skip):
            s0, s1, tm, box, kind = self.obs[k]
            sl = _pair_ok(R, s0, s1, tm, box, self.G, self.gap)
            if sl is None:
                return False
            if stat is not None and sl > 0:
                stat[kind] = stat.get(kind, 0.0) + sl
            if touched is not None and sl > 0:
                touched.append(k)
        return True


def _pair_ok(R, s0, s1, tm, box, Gc, gap):
    """Прямоугольник R и сосед (рёбра, «вплотную», габарит): общая длина касаний (0 — не касается) или None — нельзя."""
    x0, y0, x1, y1 = R
    eps = 1e-7
    if _seg_in_rect(s0, s1, (x0 + eps, y0 + eps, x1 - eps, y1 - eps)).any():
        return None                                     # наложение: ребро соседа проходит внутри
    if _pip(((x0 + x1) / 2, (y0 + y1) / 2), s0, s1):
        return None                                     # R внутри соседа (и совпал с ним: рёбра — по краю R)
    d = _seg_rect_dist(s0, s1, R)
    if (d[~tm] < Gc - 1e-9).any():
        return None                                     # дуга, фаска, вырез угла, короткая кромка — ближе зазора
    ti = tm & (d < gap - 1e-9)
    if not ti.any():
        return 0.0
    touch = ti & (d <= CO_TOL)
    near = ti & (d > CO_TOL)
    shared, pts = 0.0, []
    for p, q in zip(s0[touch], s1[touch]):
        if abs(p[0] - q[0]) <= 1e-9:                    # вертикальное ребро
            ex, ya, yb = p[0], min(p[1], q[1]), max(p[1], q[1])
            if abs(ex - x0) <= CO_TOL or abs(ex - x1) <= CO_TOL:
                lo, hi = max(ya, y0), min(yb, y1)
                if hi - lo > CO_TOL:
                    shared += hi - lo
                pts += [(ex, lo), (ex, hi)]
                continue
        else:                                           # горизонтальное
            cy, xa, xb = p[1], min(p[0], q[0]), max(p[0], q[0])
            if abs(cy - y0) <= CO_TOL or abs(cy - y1) <= CO_TOL:
                lo, hi = max(xa, x0), min(xb, x1)
                if hi - lo > CO_TOL:
                    shared += hi - lo
                pts += [(lo, cy), (hi, cy)]
                continue
        pts += [tuple(v) for v in (p, q) if _pt_rect(np.asarray([v], float), R)[0] <= CO_TOL]   # Т-примыкание концом
    if 0 < shared < CO_CONTACT_MIN:
        return None                                     # слишком короткий общий участок
    # касание только точкой — угол к углу (кромки вдоль осей): так сходятся четыре детали сетки — можно
    if near.any():
        if not pts:
            return None                                 # щель уже зазора без касания
        T = np.asarray(pts, float)
        a0, a1 = s0[near], s1[near]
        for p, q in zip(a0, a1):                        # точки рёбер соседа у R
            n = max(2, int(math.hypot(q[0] - p[0], q[1] - p[1]) / CO_STEP) + 1)
            P = p[None] + (q - p)[None] * np.linspace(0.0, 1.0, n)[:, None]
            dd = _pt_rect(P, R)
            m = (dd > CO_TOL) & (dd < gap - 1e-9)
            if m.any() and (np.sqrt(((P[m][:, None, :] - T[None]) ** 2).sum(2)).min(1) > CO_END_R).any():
                return None
        rs0, rs1 = CoSheet.rect_edges(R)                # точки сторон R у этих рёбер
        bx = (min(a0[:, 0].min(), a1[:, 0].min()) - gap, min(a0[:, 1].min(), a1[:, 1].min()) - gap,
              max(a0[:, 0].max(), a1[:, 0].max()) + gap, max(a0[:, 1].max(), a1[:, 1].max()) + gap)
        for p, q in zip(rs0, rs1):
            lo = np.maximum(np.minimum(p, q), (bx[0], bx[1]))
            hi = np.minimum(np.maximum(p, q), (bx[2], bx[3]))
            if (hi < lo - 1e-12).any():
                continue
            n = max(2, int(max(hi - lo) / CO_STEP) + 1)
            P = lo[None] + (hi - lo)[None] * np.linspace(0.0, 1.0, n)[:, None]
            dd = _pt_segs(P, a0, a1)
            m = (dd > CO_TOL) & (dd < gap - 1e-9)
            if m.any() and (np.sqrt(((P[m][:, None, :] - T[None]) ** 2).sum(2)).min(1) > CO_END_R).any():
                return None
    return shared


def pockets(polys, fill_polys, box, res=POCKET_RES):
    """«Карманы» остатка листа, замкнутые деталями (polys — все детали около группы, fill_polys — добивка в ней):
    свободные клетки растра в габарите box, не связанные с его краем, рядом с добивкой (≤ 2 клеток). Вернуть площадь
    таких карманов, мм² (0 — нет). Растр сдвинут на доли клетки: стык двух деталей по линии центров клеток не даёт
    ложной щели."""
    ox, oy = box[0] - 3 * res + 0.3141 * res, box[1] - 3 * res + 0.2718 * res
    nx, ny = int(math.ceil((box[2] - ox) / res)) + 4, int(math.ceil((box[3] - oy) / res)) + 4
    occ = np.zeros((ny, nx), bool)
    fil = np.zeros((ny, nx), bool)
    for P, tgt in [(P, occ) for P in polys] + [(P, fil) for P in fill_polys]:
        A = np.asarray(P, float)
        j0, i0 = max(0, int(math.floor((A[:, 0].min() - ox) / res))), max(0, int(math.floor((A[:, 1].min() - oy) / res)))
        j1, i1 = min(nx, int(math.ceil((A[:, 0].max() - ox) / res)) + 1), min(ny, int(math.ceil((A[:, 1].max() - oy) / res)) + 1)
        if j1 > j0 and i1 > i0:
            tgt[i0:i1, j0:j1] |= scan(A, j1 - j0, i1 - i0, ox + j0 * res, oy + i0 * res, res)
    occ |= fil
    free = ~occ
    seed = np.zeros_like(free)
    seed[0, :], seed[-1, :], seed[:, 0], seed[:, -1] = free[0, :], free[-1, :], free[:, 0], free[:, -1]
    pocket = free & ~_spread(free, seed)
    if not pocket.any():
        return 0.0
    near = pocket & dilate(fil, 2)[2:-2, 2:-2]
    if near.sum() * res * res < POCKET_MIN:
        return 0.0
    return float(_spread(pocket, near).sum()) * res * res     # карманы у добивки — целиком


def _spread(mask, seed):
    """Клетки mask, связанные с seed (по строкам и столбцам): отрезок клеток mask в строке (столбце), где есть
    достигнутая, — весь достигнут; повторять, пока растёт (проходов — по числу поворотов пути, а не по его длине)."""
    reach = seed & mask
    for _ in range(10000):
        before = int(reach.sum())
        for T in (False, True):
            f, r = (mask.T, reach.T) if T else (mask, reach)
            prev = np.zeros_like(f)
            prev[:, 1:] = f[:, :-1]
            sid = np.cumsum((f & ~prev).reshape(-1)).reshape(f.shape)
            hit = np.bincount(sid[f], weights=r[f].astype(float), minlength=int(sid.max()) + 1) > 0
            r[f] = hit[sid[f]]
        if int(reach.sum()) == before:
            break
    return reach


def _co_try(layout, parts, allparts, items, got, gap, edge, caps, total, n0, order_touch):
    """Добивка раскладки под общий рез от раскладки с зазором got: поджатие вплотную, добор, проверка групп. Вернуть
    (got, группы, сведения) или (None, None, причина)."""
    from . import pack as PK, route as RT, coedge as CE
    shp, rect = {}, {}
    for j, e, part, rots in items:
        rect[j] = rect_part(part)
        for s in rots:
            shp[(j, s.rot)] = s
    ejs = {j: e for j, e, part, rots in items}
    sh = CoSheet(layout["W"], layout["L"], gap, edge)
    for q in layout["placed"]:
        o = G.transform(parts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"]))
        s0, s1, st = _edges(o)
        L = np.hypot(*(s1 - s0).T)
        sh.add(s0, s1, (st & _axis_edges(s0, s1) & (L >= CO_TOUCH_MIN)) if order_touch else np.zeros(len(s0), bool), "order")
    adj = {}                                            # касания общей кромкой: препятствие → препятствия (группы)
    for g in layout.get("groups") or []:
        for a in g:
            adj.setdefault(a, set()).update(b for b in g if b != a)

    def grows_ok(k, touched):
        """Касания touched не растят группу (без k) больше CO_GROUP_MAX деталей."""
        seen, stack = {k}, [t for t in touched if t != k]
        seen.update(stack)
        while stack:
            a = stack.pop()
            for b in adj.get(a, ()):
                if b not in seen:
                    seen.add(b); stack.append(b)
                    if len(seen) > CO_GROUP_MAX:
                        return False
        return len(seen) <= CO_GROUP_MAX

    def closes_pocket(R, k, touched, pts_all):
        """Касание двух и более соседей может замкнуть карман остатка: растр окна около R (все детали; R — добивка)."""
        if len(touched) + pts_all < 2:
            return False
        m = CO_POCKET_WIN
        box = (R[0] - m, R[1] - m, R[2] + m, R[3] + m)
        polys = [sh.obs[o][0] for o in sh.near(box, 0.0, {k})]
        return pockets(polys, [CoSheet.rect_edges(R)[0]], box) > 0

    def link(k, touched):
        for b in adj.pop(k, set()):
            adj.get(b, set()).discard(k)
        adj[k] = set(touched)
        for b in touched:
            adj.setdefault(b, set()).add(k)
    F = []                                              # [номер детали добивки, поворот, R, препятствие, прямоугольник]
    for j, rot, dx, dy in got:
        s = shp[(j, rot)]
        R = (dx + s.mx, dy + s.my, dx + s.mx + s.w, dy + s.my + s.h)
        if rect[j]:
            k = sh.add_rect(R)
        else:
            P = np.asarray(s.P, float) + (R[0], R[1])
            k = sh.add(P, np.roll(P, -1, axis=0), np.zeros(len(P), bool), "other")
        F.append([j, rot, R, k, rect[j]])
    n_gap = len(F)
    used = {}
    for f in F:
        used[ejs[f[0]]] = used.get(ejs[f[0]], 0) + 1

    def room_for(e):
        c = None if caps.get(e) is None else caps[e] - used.get(e, 0)
        if total is not None:
            c = total - len(F) if c is None else min(c, total - len(F))
        return c is None or c > 0

    def place(j, rot, R, touched=()):
        s = shp[(j, rot)]
        k = sh.add_rect(R) if rect[j] else sh.add(*(lambda P: (P, np.roll(P, -1, axis=0)))(np.asarray(s.P, float) + (R[0], R[1])),
                                                    np.zeros(len(s.P), bool), "other")
        F.append([j, rot, R, k, rect[j]])
        used[ejs[j]] = used.get(ejs[j], 0) + 1
        link(k, touched)

    def compact():
        moved_any = False
        for _ in range(CO_PASSES):
            moved = False
            for f in sorted((f for f in F if f[4]), key=lambda f: (f[2][1], f[2][0])):
                R, sk = f[2], {f[3]}
                tries = []
                cur = R
                for axis in (1, 0, 1):
                    t = sh.slide(cur, axis, cur[axis] - edge, sk)
                    if t > 1e-12:
                        cur = (cur[0] - t, cur[1], cur[2] - t, cur[3]) if axis == 0 else (cur[0], cur[1] - t, cur[2], cur[3] - t)
                tries.append(cur)
                for axis in (1, 0):                     # не вышло вместе — по одной оси
                    t = sh.slide(R, axis, R[axis] - edge, sk)
                    if t > 1e-12:
                        tries.append((R[0] - t, R[1], R[2] - t, R[3]) if axis == 0 else (R[0], R[1] - t, R[2], R[3] - t))
                for c in tries:
                    tch = []
                    if max(abs(a - b) for a, b in zip(c, R)) > 1e-9 and sh.ok(c, sk, touched=tch) and grows_ok(f[3], tch) \
                            and not closes_pocket(c, f[3], tch, len(sh.near(c, CO_TOL, sk)) - len(tch)):
                        f[2] = c
                        sh.move(f[3], c)
                        link(f[3], tch)
                        moved = moved_any = True
                        break
            if not moved:
                break
        return moved_any

    edge_slots = []                                     # кромки деталей заказа «вплотную»: (ось, линия, от, до, наружу +1/−1)
    for s0, s1, tm, box, kind in sh.obs:
        if kind != "order" or not tm.any():
            continue
        for p, q in zip(s0[tm], s1[tm]):
            vert = abs(p[0] - q[0]) <= 1e-9
            mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            probe = (mid[0] + 0.01, mid[1]) if vert else (mid[0], mid[1] + 0.01)
            out = -1 if _pip(np.asarray(probe), s0, s1) else 1
            if vert:
                edge_slots.append((0, p[0], min(p[1], q[1]), max(p[1], q[1]), out))
            else:
                edge_slots.append((1, p[1], min(p[0], q[0]), max(p[0], q[0]), out))

    def touch_topup():
        """Добор вплотную: к стоящей добивке-прямоугольнику (сторона соседа, по одному из его углов) и к кромкам деталей
        заказа «вплотную» (по концу кромки или в зазоре от него — у конца бывает фаска); ниже-левее."""
        n = 0
        for j, e, part, rots in items:
            if not rect[j]:
                continue
            while room_for(e):
                cands = []
                for s in rots:
                    w, h = s.w, s.h
                    g = sh.G
                    for ax, c, lo, hi, out in edge_slots:
                        if ax == 0:
                            x = c if out > 0 else c - w
                            for y in (lo, hi - h, lo + g, hi - h - g):
                                cands.append((y, x, s.rot, (x, y, x + w, y + h)))
                        else:
                            y = c if out > 0 else c - h
                            for x in (lo, hi - w, lo + g, hi - w - g):
                                cands.append((y, x, s.rot, (x, y, x + w, y + h)))
                for f in F:
                    if not f[4]:
                        continue
                    x0, y0, x1, y1 = f[2]
                    for s in rots:
                        w, h = s.w, s.h
                        for x, y in ((x1, y0), (x1, y1 - h), (x0 - w, y0), (x0 - w, y1 - h),
                                     (x0, y1), (x1 - w, y1), (x0, y0 - h), (x1 - w, y0 - h)):
                            cands.append((y, x, s.rot, (x, y, x + w, y + h)))
                cands.sort(key=lambda c: (round(c[0], 6), round(c[1], 6), c[2]))
                hit = None
                seen = set()
                for y, x, rot, R in cands:
                    key = (round(x, 6), round(y, 6), rot)
                    if key in seen:
                        continue
                    seen.add(key)
                    tch = []
                    if sh.ok(R, touched=tch) and grows_ok(-1, tch) and not closes_pocket(R, -1, tch, len(sh.near(R, CO_TOL)) - len(tch)):
                        hit = (rot, R, tch)
                        break
                if hit is None:
                    break
                place(j, hit[0], hit[1], hit[2])
                n += 1
        return n

    def raster_topup():
        """Добор с зазором (как раскладка добивки) в освободившееся место."""
        rest = {}
        for e in caps:
            rest[e] = None if caps[e] is None else caps[e] - used.get(e, 0)
        tl = None if total is None else total - len(F)
        if tl is not None and tl <= 0:
            return 0
        tmp = dict(W=layout["W"], L=layout["L"], placed=list(layout["placed"]) + [
            dict(part=n0 + f[0], rot=f[1], dx=f[2][0] - shp[(f[0], f[1])].mx, dy=f[2][1] - shp[(f[0], f[1])].my) for f in F])
        add, _ = fill_layout(tmp, allparts, items, gap, edge, rest, tl)
        for j, rot, dx, dy in add:
            s = shp[(j, rot)]
            place(j, rot, (dx + s.mx, dy + s.my, dx + s.mx + s.w, dy + s.my + s.h))
        return len(add)

    if not any(rect.values()):
        return None, None, "нет добивки-прямоугольника"
    compact()
    for _ in range(CO_ROUNDS):
        a = touch_topup()
        b = raster_topup()
        if b:
            compact()
        if not a and not b:
            break
    out = [(f[0], f[1], f[2][0] - shp[(f[0], f[1])].mx, f[2][1] - shp[(f[0], f[1])].my) for f in F]
    placed_all = list(layout["placed"]) + [dict(part=n0 + j, rot=rot, dx=dx, dy=dy) for j, rot, dx, dy in out]
    groups, unsafe = PK.coedge_groups(allparts, placed_all)
    m0 = len(layout["placed"])
    bad = [u for u in unsafe if u[0] >= m0 or u[1] >= m0]
    if bad:
        return None, None, "сближение не по кромке у добивки"
    polys = [G.points(G.transform(allparts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"])), SAG) for q in placed_all]
    info = dict(n_gap=n_gap, n=len(F), groups=0, members=0, order_contacts=0, shared_mm=0.0)
    for g in groups:
        if not any(i >= m0 for i in g):
            continue
        if not RT.group_buildable(allparts, placed_all, g):
            return None, None, "группу с добивкой не построить общим резом"
        bx = [G.bbox([dict(kind="LwPolyline", verts=[(x, y, 0.0) for x, y in polys[i]], flag=1)]) for i in g]
        box = (min(b[0] for b in bx), min(b[1] for b in bx), max(b[2] for b in bx), max(b[3] for b in bx))
        if pockets([polys[i] for i in g if i < m0], [polys[i] for i in g if i >= m0], box):
            return None, None, "группа с добивкой замыкает карман остатка листа"
        info["groups"] += 1
        info["members"] += sum(1 for i in g if i >= m0)
        outs = {i: G.transform(allparts[placed_all[i]["part"]]["shapes"][-1], placed_all[i]["rot"],
                               (placed_all[i]["dx"], placed_all[i]["dy"]))["verts"] for i in g}
        for a in g:
            for b in g:
                if a < b and b >= m0:
                    sl = CE.shared_length(outs[a], outs[b])
                    info["shared_mm"] += sl
                    info["order_contacts"] += int(a < m0 and sl > 0)
    return out, groups, info


def _co_note(st, li, a, ci, got0, got, fillers, eby):
    """Сведения о добивке под общий рез (co_stats): по раскладке и итог по позициям — с зазором было, вышло (× листов)."""
    nm = lambda j: fillers[j].get("name") or fillers[j]["part"]["name"]
    st.setdefault("layouts", {})[li + 1] = dict(amount=a, n_gap=len(got0), n=len(got), groups=ci["groups"], members=ci["members"],
                                                order_contacts=ci["order_contacts"], shared_m=round(ci["shared_mm"] / 1000, 3),
                                                order_touch=ci["order_touch"], why=list(ci["why"]))
    by = st.setdefault("by_name", {})
    for j, *_ in got0:
        by.setdefault(nm(j), dict(gap=0, placed=0))["gap"] += a
    for j, *_ in got:
        by.setdefault(nm(j), dict(gap=0, placed=0))["placed"] += a
    st["shared_m"] = round(st.get("shared_m", 0.0) + ci["shared_mm"] * a / 1000, 3)
    st["members"] = st.get("members", 0) + ci["members"] * a
    st["order_contacts"] = st.get("order_contacts", 0) + ci["order_contacts"] * a


def _co_line(ci):
    """Хвост строки лога раскладки: добивка под общий рез."""
    if ci["order_touch"] is None:
        return "; общий рез: добивка с зазором (%s)" % "; ".join(ci["why"])
    return "; общий рез: вплотную %d шт в %d группах, общих кромок %.2f м%s%s%s" % (
        ci["members"], ci["groups"], ci["shared_m"], ", к деталям заказа %d" % ci["order_contacts"] if ci["order_contacts"] else "",
        (", добор +%d" % (ci["n"] - ci["n_gap"])) if ci["n"] > ci["n_gap"] else "",
        (" (к деталям заказа — нельзя: %s)" % "; ".join(ci["why"])) if not ci["order_touch"] else "")


def co_layout(layout, parts, allparts, items, got, gap, edge, caps, total, n0):
    """Раскладка под общий рез: добивка вплотную (_co_try) — сперва и к деталям заказа, не вышло — только друг к другу,
    не вышло и так — с зазором (got как есть, группы раскладки прежние). Вернуть (got, группы, сведения)."""
    why = []
    for order_touch in (True, False):
        out, groups, info = _co_try(layout, parts, allparts, items, got, gap, edge, caps, total, n0, order_touch)
        if out is not None:
            info["order_touch"] = order_touch
            info["why"] = why
            return out, groups, info
        why.append(("к деталям заказа: " if order_touch else "друг к другу: ") + info)
    return got, layout.get("groups") or [], dict(n_gap=len(got), n=len(got), groups=0, members=0, order_contacts=0,
                                                   shared_mm=0.0, order_touch=None, why=why)
