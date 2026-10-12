# -*- coding: utf-8 -*-
"""Раскрой деталей вентзонтов на листы: «склад 2500» против «бухты» (длина кратно 50, до 3000).

Ядро раскроя; вызывать через vent_nesting.api (ERP) или python3 -m vent_nesting.cli (командная строка).
Материал (толщина, цвет) берётся из имени DXF генератора: vsh_ШxД_tТОЛЩ_ЦВЕТ.dxf.
Разные материалы раскладываются отдельно (краска и цинк на одном листе не режутся).

Раскладка: растр 2 мм, детали ставятся по одной в положение, где лист заполняется плотнее
(минимум занятой длины, затем ниже-левее); допустимые места ищутся сразу по всему листу (FFT).
Повороты 0/90/180/270°, зеркалить нельзя (окрашенный лист). Зазор между деталями и отступ от края — параметры
(по умолчанию 2 и 2 мм, как у инженера на 0,65 и 14 мм): --gap, --edge или set_spacing().
После раскладки лист доводится по настоящим контурам (exact_fix): детали поджимаются до зазора
ровно до зазора; не влезла в длину листа — последняя уходит на следующий. Затем независимая проверка
точной геометрией (зазоры, выход за лист).
"""
import sys, os, re, io, json, math, zipfile, argparse, contextlib, itertools, hashlib, collections
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
from . import parts as P

SHEET_W = 1250.0      # ширина листа (бухты)
L_MAX = 3000.0        # станок принимает лист до 3000
L_STEP = 50.0         # с бухты — кратно 50
STOCK_L = 2500.0      # на складе — только 2500
RES = 2.0             # шаг растра, мм
GAP = 2.0             # между деталями
EDGE = 2.0            # от края листа
RHO = 7.85            # кг/м² на 1 мм
PAD = 3               # клеток запаса вокруг маски детали


# ------------------------------------------------------------------ детали заказа
NAME_RE = re.compile(r"^vsh_(\d+)x(\d+)_t(\d+(?:[.,]\d+)?)_([^./\\]+)\.dxf$", re.I)


def material_of(fname):
    """vsh_ШxД_tТОЛЩ_ЦВЕТ.dxf → (Ш, Д, толщина, цвет); не то имя → None. Толщина обязательна (без неё нет кг)."""
    m = NAME_RE.match(fname.replace("\\", "/").split("/")[-1])
    if not m:
        return None
    W, L = int(m.group(1)), int(m.group(2))
    t = float(m.group(3).replace(",", "."))
    if W <= 0 or L <= 0 or t <= 0:
        return None
    col = m.group(4)
    col = "оцинковка" if col.lower() in ("оц", "zn") else re.sub(r"(?i)^ral", "RAL ", col)
    return W, L, t, col


def load_order(paths, qty):
    items = []
    for path, raw_name in paths:
        mat = material_of(raw_name)
        if not mat:
            print("пропуск (не DXF генератора):", raw_name); continue
        W, L, t, col = mat
        q = qty.get(raw_name, qty.get("%dx%d" % (W, L), 1))
        with contextlib.redirect_stdout(io.StringIO()):
            ps, _ = P.analyze(path)
        for p in ps:
            role = "крышка" if any(abs(h[2] - 4.5) < .6 for h in p["holes"]) else ("панель торц." if p["slots"] else "панель сред.")
            x0, y0 = p["bbox"][0], p["bbox"][2]
            loc = lambda q_: (q_[0] - x0, q_[1] - y0)
            part = {"hood": "%d×%d" % (W, L), "role": role, "material": (t, col),
                    "poly": [loc(q_) for q_ in p["poly"]],
                    "edges": [_shift_edge(e, -x0, -y0) for e in p["edges"]],
                    "holes": [(h[0] - x0, h[1] - y0, h[2]) for h in p["holes"]],
                    "slot_edges": [_shift_edge(e, -x0, -y0) for s in p["slots"] for e in s["edges"]]}
            part["key"] = hashlib.md5(json.dumps([[round(x, 2), round(y, 2)] for x, y in part["poly"]]).encode()).hexdigest()
            for k in range(q):
                items.append(dict(part, copy=k + 1))
    return items


def _shift_edge(e, dx, dy):
    out = dict(e)
    for k in ("p0", "p1", "pm", "c"):
        if k in e:
            out[k] = [e[k][0] + dx, e[k][1] + dy]
    return out


def _area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2


# ------------------------------------------------------------------ геометрия поворотов
def rot_pt(p, r):
    x, y = p
    return {0: (x, y), 90: (-y, x), 180: (-x, -y), 270: (y, -x)}[r]


def rotated(poly, r):
    pts = [rot_pt(p, r) for p in poly]
    mx, my = min(p[0] for p in pts), min(p[1] for p in pts)
    return [(x - mx, y - my) for x, y in pts], (mx, my)


def dilate(a, k):
    if k <= 0:
        return a
    out = a.copy()
    H, W = a.shape
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            if dx == 0 and dy == 0:
                continue
            ys, yd = (slice(0, H - dy), slice(dy, H)) if dy >= 0 else (slice(-dy, H), slice(0, H + dy))
            xs, xd = (slice(0, W - dx), slice(dx, W)) if dx >= 0 else (slice(-dx, W), slice(0, W + dx))
            out[yd, xd] |= a[ys, xs]
    return out


def raster(poly):
    """Маска детали: клетка [i,j] ↔ мм ((j-PAD)·RES, (i-PAD)·RES). Консервативно (+1 клетка)."""
    from PIL import Image, ImageDraw
    w, h = max(p[0] for p in poly), max(p[1] for p in poly)
    nx, ny = int(math.ceil(w / RES)) + 2 * PAD + 1, int(math.ceil(h / RES)) + 2 * PAD + 1
    img = Image.new("1", (nx, ny), 0)
    ImageDraw.Draw(img).polygon([(x / RES + PAD, y / RES + PAD) for x, y in poly], fill=1, outline=1)
    return np.array(img, dtype=bool)          # без запаса: точный зазор 2 мм обеспечит доводка exact_fix()


_cache = {}
_gcache = collections.OrderedDict()   # спектры масок деталей: (id маски, размер БПФ) → rfft2, complex64
_GCAP = 64 * 2 ** 20                   # потолок кэша спектров, байт. Без потолка заказ в 50 деталей занимал 1,1 ГБ;
                                       # 64 МБ → ~330 МБ на раскрой, +15% времени (у контейнера Odoo предел 2,5 ГБ)
_gbytes = [0]


def _gget(gk, m, S):
    G = _gcache.get(gk)
    if G is not None:
        _gcache.move_to_end(gk)
        return G
    G = np.fft.rfft2(m[::-1, ::-1].astype(np.float32), s=S).astype(np.complex64)   # маска 0/1: одинарной точности с запасом
    _gcache[gk] = G; _gbytes[0] += G.nbytes
    while _gbytes[0] > _GCAP and len(_gcache) > 1:
        _, old = _gcache.popitem(last=False); _gbytes[0] -= old.nbytes
    return G


def _fast(n):
    """ближайший сверху размер вида 2^a·3^b·5^c — на нём БПФ быстрый"""
    while True:
        m = n
        for p_ in (2, 3, 5):
            while m % p_ == 0:
                m //= p_
        if m == 1:
            return n
        n += 1


GAP_MIN = 0.5      # меньше — не раскладываем: общий рез CypCut сводит детали сам, нулевой зазор не нужен


def set_spacing(gap=None, edge=None):
    """Зазор между деталями и отступ от края листа, мм. Сбрасывает кэш масок (маски расширены на зазор)."""
    global GAP, EDGE
    if gap is not None:
        if not (GAP_MIN <= gap <= 50):
            raise ValueError("зазор %g мм: допустимо %g…50 (для общего реза CypCut сводит детали сам)" % (gap, GAP_MIN))
        GAP = float(gap)
    if edge is not None:
        if not (0 <= edge <= 100):
            raise ValueError("отступ от края %g мм: допустимо 0…100" % edge)
        EDGE = float(edge)
    _cache.clear(); _gcache.clear(); _gbytes[0] = 0
    return GAP, EDGE


def spacing_tag():
    """Пометка для имён файлов, если зазор/отступ не по умолчанию: «_зазор3_край5» (варианты не затирают друг друга)."""
    return "" if (GAP, EDGE) == (2.0, 2.0) else "_зазор%g_край%g" % (GAP, EDGE)


def shapes_for(item):
    """Повороты детали: [(r, поли, маска, маска с зазором)] (кэш по форме)."""
    key = item["key"]
    if key not in _cache:
        out, seen = [], set()
        for r in (0, 90, 180, 270):
            poly, _ = rotated(item["poly"], r)
            m = raster(poly)
            sig = (m.shape, hashlib.md5(m.tobytes()).hexdigest())
            if sig in seen:
                continue
            seen.add(sig)
            out.append((r, poly, m, dilate(m, int(math.ceil(GAP / RES)))))
        _cache[key] = out
    return _cache[key]


# ------------------------------------------------------------------ раскладка на один лист
class Sheet:
    def __init__(self, L):
        self.L = L
        self.ny, self.nx = int(math.ceil(L / RES)) + 2 * PAD, int(math.ceil(SHEET_W / RES)) + 2 * PAD
        occ = np.ones((self.ny, self.nx), dtype=bool)
        e = PAD + int(math.ceil(EDGE / RES))
        y1 = PAD + int(math.floor((L - EDGE) / RES)); x1 = PAD + int(math.floor((SHEET_W - EDGE) / RES))
        occ[e:y1, e:x1] = False
        self.occ = occ
        self.ext = 0.0                  # занятая длина, мм (от начала листа)
        self._F = None                  # спектр занятости (кэш до следующей установки)
        self.placed = []                # (item, r, ox, oy) — смещение повёрнутой детали, мм

    def try_place(self, item):
        best = None
        H, W = self.occ.shape
        S = (_fast(H), _fast(W))
        if self._F is None:
            self._F = np.fft.rfft2(self.occ.astype(np.float32), s=S)
        F = self._F
        for r, poly, m, md in shapes_for(item):
            h, w = m.shape
            if h > H or w > W:
                continue
            G = _gget((id(m), S), m, S)
            conv = np.fft.irfft2(F * G, s=S)
            C = conv[h - 1:H, w - 1:W]
            ok = np.argwhere(C < 0.5)                      # (iy, ix) — левый нижний угол маски
            if not len(ok):
                continue
            ph = max(p[1] for p in poly)
            # клетка маски PAD ↔ 0 мм детали, клетка листа PAD ↔ 0 мм листа ⇒ начало детали = iy·RES
            top = ok[:, 0] * RES + ph
            ext = np.maximum(self.ext, top)
            score = np.lexsort((ok[:, 1], ok[:, 0], ext))
            k = score[0]
            cand = (ext[k], ok[k, 0], ok[k, 1], r, poly, m, md)
            if best is None or cand[:3] < best[:3]:
                best = cand
        if best is None:
            return False
        ext, iy, ix, r, poly, m, md = best
        h, w = md.shape
        self.occ[iy:iy + h, ix:ix + w] |= md
        self._F = None
        self.ext = float(ext)
        self.placed.append((item, r, ix * RES, iy * RES))
        return True


# ------------------------------------------------------------------ доводка точной геометрией
def _segs(poly):
    P = np.asarray(poly, dtype=float)
    return P, np.roll(P, -1, axis=0)


def _pt_seg(p, s0, s1):
    d = s1 - s0
    L2 = (d * d).sum(1); L2[L2 == 0] = 1.0
    t = np.clip(((p[:, None, :] - s0[None]) * d[None]).sum(2) / L2[None], 0, 1)
    q = s0[None] + t[..., None] * d[None]
    return np.sqrt(((p[:, None, :] - q) ** 2).sum(2)).min()


def poly_dist(A, B):
    """Точное расстояние между контурами (0 — пересекаются или вложены)."""
    a0, a1 = A; b0, b1 = B
    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    o1 = orient(a0[:, None], a1[:, None], b0[None]); o2 = orient(a0[:, None], a1[:, None], b1[None])
    o3 = orient(b0[None], b1[None], a0[:, None]); o4 = orient(b0[None], b1[None], a1[:, None])
    if np.any((o1 * o2 < 0) & (o3 * o4 < 0)):
        return 0.0
    if inside(tuple(a0[0]), b0) or inside(tuple(b0[0]), a0):
        return 0.0
    return min(_pt_seg(a0, b0, b1), _pt_seg(b0, a0, a1))


def exact_fix(s):
    """Каждую деталь (в порядке установки) проверить по настоящим контурам: ближе GAP — отодвинуть
    (вдоль листа, затем поперёк), есть место — поджать к началу листа до ровно GAP. Меняет s.placed, s.ext."""
    fixed = []          # (сегменты, bbox)
    out = []
    s.fixed_ok = True
    def ok(segs0, w, h, x, y):
        if x < EDGE - 1e-6 or y < EDGE - 1e-6 or x + w > SHEET_W - EDGE + 1e-6:
            return False
        A = (segs0[0] + (x, y), segs0[1] + (x, y))
        for B, (bx0, bx1, by0, by1) in fixed:
            if x > bx1 + GAP or x + w < bx0 - GAP or y > by1 + GAP or y + h < by0 - GAP:
                continue
            if poly_dist(A, B) < GAP - 1e-6:
                return False
        return True
    def search_down(segs0, w, h, x, y, axis, dmax):
        lo, hi = 0.0, dmax                      # lo — допустимый сдвиг
        mv = (lambda d: (x - d, y)) if axis == "x" else (lambda d: (x, y - d))
        if hi <= 0 or not ok(segs0, w, h, *mv(min(hi, 0.25))):
            return 0.0
        for _ in range(18):
            mid = (lo + hi) / 2
            if ok(segs0, w, h, *mv(mid)): lo = mid
            else: hi = mid
        return lo
    for it, r, ox, oy in s.placed:
        poly, _ = rotated(it["poly"], r)
        segs0 = _segs(poly)
        w, h = max(p[0] for p in poly), max(p[1] for p in poly)
        x, y = max(ox, EDGE), max(oy, EDGE)
        if not ok(segs0, w, h, x, y):
            moved = False
            for d in np.arange(0.25, 30.01, 0.25):
                if ok(segs0, w, h, x, y + d): y += d; moved = True; break
                if ok(segs0, w, h, x + d, y): x += d; moved = True; break
            if not moved:
                s.fixed_ok = False
        for axis in ("y", "x", "y"):
            dmax = min((y if axis == "y" else x) - EDGE, 20.0)
            d = search_down(segs0, w, h, x, y, axis, dmax)
            if axis == "y": y -= d
            else: x -= d
        segs = (segs0[0] + (x, y), segs0[1] + (x, y))
        fixed.append((segs, (x, x + w, y, y + h)))
        out.append((it, r, x, y))
    s.placed = out
    s.ext = max((y + max(p[1] for p in rotated(it["poly"], r)[0])) for it, r, x, y in out) if out else 0.0


def pack(items, L, order):
    seq = [items[i] for i in order]
    sheets = []
    while seq:
        s = Sheet(L)
        rest, failed = [], set()
        for it in seq:
            if it["key"] in failed or not s.try_place(it):
                failed.add(it["key"]); rest.append(it)
        if not s.placed:
            raise ValueError("деталь %s %s не помещается на лист %dx%d" % (seq[0]["hood"], seq[0]["role"], SHEET_W, L))
        exact_fix(s)
        while s.placed and (s.ext + EDGE > L + 1e-6 or not s.fixed_ok):
            it, *_ = s.placed.pop()
            rest.insert(0, it)
            exact_fix(s)
        if not s.placed:
            raise ValueError("доводка не уложила деталь на лист")
        s.occ = s._F = None              # лист закончен: растр и спектр занятости больше не нужны (память)
        sheets.append(s)
        seq = rest
    return sheets


ORDERS = {
    "площадь": lambda it: -_area(it["poly"]),
    "длинная сторона": lambda it: -max(max(p[0] for p in it["poly"]), max(p[1] for p in it["poly"])),
    "ширина": lambda it: -max(p[0] for p in it["poly"]),
    "высота": lambda it: -max(p[1] for p in it["poly"]),
}


def best_pack(items, lengths, trim):
    """Перебор порядков и длин листа; trim — обрезать лист по раскладке кратно 50 (бухта)."""
    best, err = None, None
    for L in lengths:
        for oname, key in ORDERS.items():
            order = sorted(range(len(items)), key=lambda i: (key(items[i]), items[i]["hood"], items[i]["role"]))
            try:
                sheets = pack(items, L, order)
            except ValueError as e:
                err = e
                continue
            lens = [min(L, math.ceil((s.ext + EDGE) / L_STEP - 1e-9) * L_STEP) if trim else L for s in sheets]
            total = sum(lens)
            cand = (total, len(sheets), -L, oname)
            if best is None or cand < best[0]:
                best = (cand, sheets, lens, L, oname)
    if best is None:
        raise ValueError("%s (отступ от края %g мм, зазор %g мм)" % (err or "раскрой не удался", EDGE, GAP))
    return best


# ------------------------------------------------------------------ точная проверка
def place_poly(it, r, ox, oy):
    poly, (mx, my) = rotated(it["poly"], r)
    return [(x + ox, y + oy) for x, y in poly]


def seg_dist(a, b, c, d):
    def pd(p, s, e):
        sx, sy = e[0] - s[0], e[1] - s[1]; L2 = sx * sx + sy * sy
        t = 0 if L2 == 0 else max(0, min(1, ((p[0] - s[0]) * sx + (p[1] - s[1]) * sy) / L2))
        return math.hypot(p[0] - s[0] - t * sx, p[1] - s[1] - t * sy)
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    if cross(c, d, a) * cross(c, d, b) < 0 and cross(a, b, c) * cross(a, b, d) < 0:
        return 0.0
    return min(pd(a, c, d), pd(b, c, d), pd(c, a, b), pd(d, a, b))


def inside(pt, poly):
    x, y = pt; c = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def verify(sheet, Lsheet):
    polys = [place_poly(it, r, ox, oy) for it, r, ox, oy in sheet.placed]
    errs = []; dmin = 1e9; emin = 1e9
    for k, pl in enumerate(polys):
        for x, y in pl:
            emin = min(emin, x, SHEET_W - x, y, Lsheet - y)
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            A, B = polys[i], polys[j]
            if inside(A[0], B) or inside(B[0], A):
                errs.append("детали %d и %d вложены" % (i, j)); continue
            d = min(seg_dist(A[a], A[(a + 1) % len(A)], B[b], B[(b + 1) % len(B)])
                    for a in range(len(A)) for b in range(len(B)))
            dmin = min(dmin, d)
    if dmin < GAP - 0.05:
        errs.append("зазор %.2f < %.1f мм" % (dmin, GAP))
    if emin < EDGE - 0.05:
        errs.append("до края %.2f < %.1f мм" % (emin, EDGE))
    return errs, (round(dmin, 2) if dmin < 1e8 else None), round(emin, 2)


# ------------------------------------------------------------------ DXF листа
def sheet_dxf(sheet):
    s = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4",
         "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    def T(p, r, ox, oy, off):
        x, y = rot_pt(p, r); return (x - off[0] + ox, y - off[1] + oy)
    for it, r, ox, oy in sheet.placed:
        _, off = rotated(it["poly"], r)
        for e in it["edges"] + it["slot_edges"]:
            a, b = T(e["p0"], r, ox, oy, off), T(e["p1"], r, ox, oy, off)
            if e["t"] == "L":
                s += ["0", "LINE", "8", "0", "10", "%.4f" % a[0], "20", "%.4f" % a[1], "30", "0",
                      "11", "%.4f" % b[0], "21", "%.4f" % b[1], "31", "0"]
            else:
                c, m = T(e["c"], r, ox, oy, off), T(e["pm"], r, ox, oy, off)
                a0 = math.degrees(math.atan2(a[1] - c[1], a[0] - c[0])); a1 = math.degrees(math.atan2(b[1] - c[1], b[0] - c[0]))
                am = math.degrees(math.atan2(m[1] - c[1], m[0] - c[0]))
                ccw = (am - a0) % 360 <= (a1 - a0) % 360
                st, en = (a0, a1) if ccw else (a1, a0)
                s += ["0", "ARC", "8", "0", "10", "%.4f" % c[0], "20", "%.4f" % c[1], "30", "0", "40", "%.4f" % e["r"],
                      "50", "%.4f" % (st % 360), "51", "%.4f" % (en % 360)]
        for hx, hy, d in it["holes"]:
            c = T((hx, hy), r, ox, oy, off)
            s += ["0", "CIRCLE", "8", "0", "10", "%.4f" % c[0], "20", "%.4f" % c[1], "30", "0", "40", "%.4f" % (d / 2)]
    s += ["0", "ENDSEC", "0", "EOF"]
    return "\n".join(s) + "\n"


# ------------------------------------------------------------------ сценарии по материалу
def scenarios(items, which=("stock", "coil")):
    """Варианты раскроя одного материала. which — какие считать (сборке программы нужен только выбранный)."""
    t = items[0]["material"][0]
    kgm2 = RHO * t if t else None
    net = sum(_area(it["poly"]) for it in items) / 1e6
    runs = []
    if "stock" in which:
        runs.append(("склад", best_pack(items, [STOCK_L], trim=False)))
    if "coil" in which:
        coil_lengths = [L_MAX, L_MAX - 200, L_MAX - 400]      # 3000/2800/2600: длина листа потом обрезается кратно 50
        runs.append(("бухта", best_pack(items, coil_lengths, trim=True)))
    out = {}
    for name, res in runs:
        (total, n, _, oname), sheets, lens, Lb, _ = res
        chk = [verify(s, L) for s, L in zip(sheets, lens)]
        m2 = total * SHEET_W / 1e6
        out[name] = {"sheets": [{"length_mm": int(L), "parts": [(it["hood"], it["role"]) for it, *_ in s.placed],
                                 "used_mm": round(s.ext + EDGE, 1), "util_pct": round(100 * sum(_area(it["poly"]) for it, *_ in s.placed) / (L * SHEET_W), 1),
                                 "check": {"errors": c[0], "gap_min_mm": c[1], "edge_min_mm": c[2]}}
                                for s, L, c in zip(sheets, lens, chk)],
                     "n_sheets": n, "length_m": round(total / 1000, 2), "m2": round(m2, 3),
                     "kg": round(m2 * kgm2, 1) if kgm2 else None, "util_pct": round(100 * net / m2, 1),
                     "order": oname, "bin_mm": Lb, "_sheets": sheets, "_lens": lens}
    s, c = out.get("склад"), out.get("бухта")
    sav = None
    if s and c:
        sav = {"m": round(s["length_m"] - c["length_m"], 2), "m2": round(s["m2"] - c["m2"], 3),
               "kg": round(s["kg"] - c["kg"], 1) if kgm2 else None, "pct": round(100 * (s["m2"] - c["m2"]) / s["m2"], 1)}
    return {"thickness": t, "color": items[0]["material"][1], "gap_mm": GAP, "edge_mm": EDGE, "parts_net_m2": round(net, 3), "kg_per_m2": kgm2,
            "items": len(items), "stock": s, "coil": c, "saving": sav}


# ------------------------------------------------------------------ отчёт PNG
def group_lengths(lens):
    """[2550, 2550, 2400] → «2550 × 2 + 2400» (в порядке убывания)"""
    from collections import Counter
    c = Counter(int(x) for x in lens)
    return " + ".join(("%d × %d" % (L, n)) if n > 1 else str(L) for L, n in sorted(c.items(), reverse=True))


def render(res, title, out):
    from PIL import Image, ImageDraw, ImageFont
    def F(s, b=False):
        for p in (("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if b else "/System/Library/Fonts/Supplemental/Arial.ttf"),
                  ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if b else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
            if os.path.exists(p):
                return ImageFont.truetype(p, s)
        return ImageFont.load_default()
    IW = 1900; sc = 0.12; GAPX = 22; ROWH = int(SHEET_W * sc) + 34
    colors = [(52, 120, 220), (230, 120, 40), (40, 160, 90), (170, 70, 170), (200, 60, 60), (90, 90, 90), (20, 150, 160)]
    hoods = sorted({it["hood"] for m in res for k in ("stock", "coil") if m[k] for s_ in m[k]["_sheets"] for it, *_ in s_.placed})
    hcol = {h: colors[i % len(colors)] for i, h in enumerate(hoods)}
    def draw(d):
        return _draw_plan(d, res, title, F, IW, sc, GAPX, ROWH, hcol)
    probe = Image.new("RGB", (1, 1), "white")                # проход без холста: узнать высоту
    H = draw(ImageDraw.Draw(probe))
    img = Image.new("RGB", (IW, H), "white")
    draw(ImageDraw.Draw(img))
    img.save(out)


def _draw_plan(d, res, title, F, IW, sc, GAPX, ROWH, hcol):
    d.text((50, 20), title, fill=(0, 0, 0), font=F(30, True))
    d.text((50, 62), "Лист 1250 мм · зазор %g мм между деталями, %g мм от края · склад: только 2500 · бухта: длина кратно 50, до 3000 · детали не зеркалятся" % (GAP, EDGE),
           fill=(80, 80, 80), font=F(18))
    y = 105
    for m in res:
        mat = "%s %s мм" % (m["color"], ("%g" % m["thickness"]) if m["thickness"] else "?")
        sv = m["saving"]; st, co = m["stock"], m["coil"]
        hoodq = {}
        for k_ in [k for k in ("coil", "stock") if m[k]][:1]:
            for s_ in m[k_]["_sheets"]:
                for it, *_ in s_.placed:
                    hoodq.setdefault(it["hood"], set()).add(it["copy"])
        d.text((50, y), "%s — зонтов: %s · деталей %d · металл деталей %.2f м²" % (
            mat, ", ".join("%s ×%d" % (h_, len(q_)) for h_, q_ in sorted(hoodq.items())), m["items"], m["parts_net_m2"]), fill=(0, 0, 0), font=F(22, True))
        y += 34
        for lab, x_ in (("Склад 2500", st), ("Бухта", co)):
            if x_ is None:
                d.text((50, y), "%s: невозможно — деталь не помещается на этот лист" % lab, fill=(160, 60, 40), font=F(19))
                y += 28
                continue
            d.text((50, y), "%s: %d листов (%s) = %.2f м · %.2f м² · %s · загрузка %.0f%%" % (
                lab, x_["n_sheets"], group_lengths(x_["_lens"]), x_["length_m"], x_["m2"],
                ("%.1f кг" % x_["kg"]) if x_["kg"] else "", x_["util_pct"]), fill=(40, 40, 40), font=F(19))
            y += 28
        if sv is None:
            good = st is None
            msg = ("ТОЛЬКО БУХТА: деталь длиннее листа склада — закажите %s мм" % group_lengths(co["_lens"]) if st is None
                   else "Только склад 2500")
        else:
            good = sv["m2"] > 0
            msg = ("ВЫГОДНЕЕ БУХТА: закажите %s мм — экономия %.2f м · %.1f кг · %.0f%%" % (group_lengths(co["_lens"]), sv["m"], sv["kg"] or 0, sv["pct"])
                   if good else "Берите со склада 2500 — бухта не даёт экономии")
        d.text((50, y + 2), msg, fill=(20, 120, 40) if good else (60, 60, 60), font=F(21, True))
        y += 44
        for key, lab in (("coil", "Бухта (рекомендуется)" if good else "Бухта"), ("stock", "Склад 2500")):
            if not m[key]:
                continue
            d.text((50, y), lab, fill=(0, 0, 0), font=F(19, True)); y += 28
            x = 50
            for i, (s_, L) in enumerate(zip(m[key]["_sheets"], m[key]["_lens"]), 1):
                w, h = L * sc, SHEET_W * sc
                if x + w > IW - 40:
                    x = 50; y += ROWH
                d.rectangle([x, y, x + w, y + h], outline=(120, 120, 120), width=2, fill=(250, 250, 250))
                for it, r, ox, oy in s_.placed:
                    pl = place_poly(it, r, ox, oy)
                    d.polygon([(x + py * sc, y + (SHEET_W - px) * sc) for px, py in pl], outline=(20, 20, 20),
                              fill=tuple(int(c * 0.25 + 255 * 0.75) for c in hcol[it["hood"]]))
                d.text((x + 3, y + h + 3), "№%d · %d мм" % (i, L), fill=(60, 60, 60), font=F(14))
                x += w + GAPX
            y += ROWH + 12
        y += 20
    lx = 50
    for h_, c_ in hcol.items():
        if lx + 200 > IW - 40:
            lx = 50; y += 26
        d.rectangle([lx, y, lx + 22, y + 16], fill=tuple(int(c * 0.25 + 255 * 0.75) for c in c_), outline=(20, 20, 20))
        d.text((lx + 30, y - 2), "вш " + h_, fill=(0, 0, 0), font=F(17)); lx += 200
    return int(y + 40)
