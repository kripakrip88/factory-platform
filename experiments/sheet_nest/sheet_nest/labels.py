# -*- coding: utf-8 -*-
"""Подписи деталей гравировкой (слой 2) — шрифт «GOST type A (plotter)» (однолинейный, векторный шрифт Windows FON).

Решения Антона 13.10.2026: высота 15 мм, минимум 10 мм; шрифт прямой; разрывы 1 мм там, где штрихи замыкаются,
касаются или пересекаются (CypCut «ругается» на замкнутые и пересекающиеся штрихи — «8», «0», «4»…); у «4» палочка
рвётся вокруг перекладины. Текст — пока ручной (автоматическое правило и объединение заказов — позже).

Место на детали: свободная зона с отступом от отверстий, прорезей, гравировки и края (по умолчанию 3 мм), ближе к
центру детали; сначала вдоль длинной стороны, затем поперёк; не помещается — буквы меньше (до минимума);
не поместилось и так — деталь без подписи, причина в отчёте. Найденное место перепроверяется точно (по геометрии).

Шрифт: файл GOST.FON (из архива Антона fonts-GOST.zip; в КОМПАСе он есть) — путь: аргумент, переменная окружения
SHEET_NEST_FONT, иначе ~/Downloads/vent_nesting/labels/GOST.FON.
"""
import os, math, struct, functools
from . import geom as G

DEFAULT_FONT = os.environ.get("SHEET_NEST_FONT") or os.path.expanduser("~/Downloads/vent_nesting/labels/GOST.FON")
FACE = "GOST type A (plotter)"
CAP = 52            # высота прописных и цифр в единицах шрифта (от 18 до базовой линии 70)
EXTRA = (20.0, 12.0, 6.0, 0.0)   # мм запаса вокруг подписи сверх отступа — по убыванию: «самое большое свободное место»


class LabelError(ValueError):
    pass


# ============================================================================================ шрифт
def _fnt_resources(b):
    ne = struct.unpack_from("<I", b, 0x3C)[0]
    if b[ne:ne + 2] != b"NE":
        raise LabelError("файл шрифта не FON (нет заголовка NE)")
    rt = ne + struct.unpack_from("<H", b, ne + 0x24)[0]
    shift = struct.unpack_from("<H", b, rt)[0]
    p, out = rt + 2, []
    while True:
        typ = struct.unpack_from("<H", b, p)[0]
        if typ == 0:
            break
        cnt = struct.unpack_from("<H", b, p + 2)[0]
        p += 8
        for _ in range(cnt):
            off, ln = struct.unpack_from("<HH", b, p)
            if typ == 0x8008:
                out.append(b[off << shift:(off << shift) + (ln << shift)])
            p += 12
    return out


@functools.lru_cache(maxsize=4)
def load_font(path=None):
    """Векторный шрифт FON → {"ascent", "glyphs": {код cp1251: {"width", "strokes": [[(u, v), …]]}}}.
    Таблица символов векторного FNT 2.0 — с 0x75 (без dfReserved); байт −128 — подъём пера, затем пары dx, dy."""
    path = path or DEFAULT_FONT
    if not os.path.exists(path):
        raise LabelError("нет файла шрифта %s (GOST.FON — «GOST type A (plotter)»; путь — --font или SHEET_NEST_FONT)" % path)
    b = open(path, "rb").read()
    for f in _fnt_resources(b):
        if not (struct.unpack_from("<H", f, 0x42)[0] & 1):
            continue                                   # растровый — не годится
        face_off = struct.unpack_from("<I", f, 0x69)[0]
        face = f[face_off:f.index(b"\0", face_off)].decode("cp1251", "replace")
        ascent = struct.unpack_from("<H", f, 0x4A)[0]
        pixwidth = struct.unpack_from("<H", f, 0x56)[0]
        first, last = f[0x5F], f[0x60]
        bits_off = struct.unpack_from("<I", f, 0x71)[0]
        n = last - first + 2
        ents = [struct.unpack_from("<HH", f, 0x75 + 4 * i) if pixwidth == 0 else (struct.unpack_from("<H", f, 0x75 + 2 * i)[0], pixwidth)
                for i in range(n)]
        glyphs = {}
        for i in range(n - 1):
            o, w = ents[i]
            data = f[bits_off + o: bits_off + ents[i + 1][0]]
            strokes, cur, x, y, pen, k = [], None, 0, 0, True, 0
            while k < len(data):
                v = struct.unpack_from("b", data, k)[0]
                if v == -128:
                    pen = False; k += 1; continue
                if k + 1 >= len(data):
                    break
                dx, dy = struct.unpack_from("bb", data, k); k += 2
                nx, ny = x + dx, y + dy
                if pen:
                    if cur is None:
                        cur = [(x, y)]
                    cur.append((nx, ny))
                else:
                    if cur and len(cur) > 1:
                        strokes.append(cur)
                    cur = [(nx, ny)]
                    pen = True
                x, y = nx, ny
            if cur and len(cur) > 1:
                strokes.append(cur)
            glyphs[first + i] = dict(width=w, strokes=strokes)
        return dict(face=face, ascent=ascent, glyphs=glyphs)
    raise LabelError("в %s нет векторного шрифта" % path)


def text_strokes(text, H, font, shear=0.0):
    """Строка → штрихи в мм: базовая линия y = 0, начало x = 0; H — высота прописных/цифр."""
    S = H / CAP
    asc = font["ascent"]
    pen, out = 0.0, []
    for ch in text:
        try:
            code = ch.encode("cp1251")[0]
        except (UnicodeEncodeError, IndexError):
            raise LabelError("знака %r нет в шрифте (только cp1251)" % ch)
        g = font["glyphs"].get(code)
        if g is None:
            raise LabelError("знака %r нет в шрифте" % ch)
        for st in g["strokes"]:
            pts = []
            for u, v in st:
                y = S * (asc - v)
                p = (S * (pen + u) + shear * y, y)
                if not pts or math.dist(pts[-1], p) > 1e-9:
                    pts.append(p)
            if len(pts) > 1:
                out.append(pts)
        pen += g["width"]
    return out


# ============================================================================================ разрывы
def _seg_dist(p, a, b):
    return G.seg_point_dist(p, a, b)


def _cross(a, b, c, d):
    r = (b[0] - a[0], b[1] - a[1]); s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (a[0] + t * r[0], a[1] + t * r[1]), t, u
    return None


def _cum(P):
    c = [0.0]
    for a, b in zip(P, P[1:]):
        c.append(c[-1] + math.dist(a, b))
    return c


def _point_at(P, cum, s):
    s = max(0.0, min(cum[-1], s))
    for k in range(len(P) - 1):
        if cum[k + 1] >= s - 1e-12:
            L = cum[k + 1] - cum[k]
            t = 0 if L == 0 else (s - cum[k]) / L
            return (P[k][0] + (P[k + 1][0] - P[k][0]) * t, P[k][1] + (P[k + 1][1] - P[k][1]) * t)
    return P[-1]


def _sub(P, cum, s0, s1):
    out = [_point_at(P, cum, s0)]
    for k in range(1, len(P) - 1):
        if s0 < cum[k] < s1:
            out.append(P[k])
    out.append(_point_at(P, cum, s1))
    return out


def gapify(strokes, gap=1.0, eps=0.02):
    """Разрывы: касания, пересечения, замыкания и сближения ближе gap → штрих обрезается так, чтобы от обрезанного
    конца до остальных штрихов было ≥ gap (прототип 13.10: весь алфавит ≥ 1,00 мм, срез ≤ 13 % длины)."""
    touch = gap
    S = [list(s) for s in strokes]
    C = [_cum(s) for s in S]
    segs = [(i, k, s[k], s[k + 1], C[i][k], C[i][k + 1]) for i, s in enumerate(S) for k in range(len(s) - 1)]
    contacts = []
    for x in range(len(segs)):
        i, a, p1, p2, c1, _ = segs[x]
        for y in range(x + 1, len(segs)):
            j, b, q1, q2, d1, _ = segs[y]
            if i == j and abs(a - b) <= 1:
                continue
            r = _cross(p1, p2, q1, q2)
            if r is not None:
                pt = r[0]
                contacts.append((i, c1 + math.dist(p1, pt), j, d1 + math.dist(q1, pt), pt))
                continue
            if i == j and min(abs(segs[y][4] - segs[x][5]), abs(segs[x][4] - segs[y][5])) < 2.5 * gap:
                continue
            best = None
            for pt, own, other, s_own, s_oth0 in ((p1, i, (q1, q2), c1, d1), (p2, i, (q1, q2), segs[x][5], d1),
                                                  (q1, j, (p1, p2), d1, c1), (q2, j, (p1, p2), segs[y][5], c1)):
                dd = _seg_dist(pt, *other)
                if dd < touch and (best is None or dd < best[0]):
                    a_, b_ = other
                    ax, ay = b_[0] - a_[0], b_[1] - a_[1]; L2 = ax * ax + ay * ay
                    tt = 0 if L2 == 0 else max(0, min(1, ((pt[0] - a_[0]) * ax + (pt[1] - a_[1]) * ay) / L2))
                    best = (dd, own, s_own, s_oth0 + tt * math.sqrt(L2), pt)
            if best is None:
                continue
            dd, own, s_own, s_oth, pt = best
            contacts.append((own, s_own, j if own == i else i, s_oth, pt))
    for i, s in enumerate(S):
        if len(s) > 2 and math.dist(s[0], s[-1]) < eps:
            contacts.append((i, C[i][-1], i, 0.0, s[0]))
    cuts = {i: [] for i in range(len(S))}
    for i, si, j, sj, pt in contacts:
        Li, Lj = C[i][-1], C[j][-1]
        end_i = si < eps or si > Li - eps
        end_j = sj < eps or sj > Lj - eps
        if i == j and (end_i and end_j):
            k, s = i, (si if si > sj else sj)
        elif end_j and not end_i:
            k, s = j, sj
        elif end_i and not end_j:
            k, s = i, si
        else:
            k, s = (j, sj) if (j, sj) >= (i, si) else (i, si)
        cuts[k].append(s)
    R = 2.5 * gap

    def clear(i, s, lo, hi):
        q = _point_at(S[i], C[i], s); L = C[i][-1]; best = 1e9
        keep = [(0.0, lo - R), (hi, L)] if abs(s - lo) <= abs(s - hi) else [(0.0, lo), (hi + R, L)]
        for j, k, a, b, ca, cb in segs:
            if j != i:
                best = min(best, _seg_dist(q, a, b))
                continue
            for x0, x1 in keep:
                s0, s1 = max(ca, x0), min(cb, x1)
                if s1 - s0 > 1e-9:
                    best = min(best, _seg_dist(q, _point_at(S[i], C[i], s0), _point_at(S[i], C[i], s1)))
        return best
    removed = {i: [] for i in range(len(S))}
    step = 0.02
    for i, ss in cuts.items():
        L = C[i][-1]
        for s in ss:
            a = b = s
            for _ in range(int(4 * gap / step) + 200):
                ok_a = a <= 0 or clear(i, a, a, b) >= gap
                ok_b = b >= L or clear(i, b, a, b) >= gap
                if ok_a and ok_b:
                    break
                if not ok_a:
                    a = max(0.0, a - step)
                if not ok_b:
                    b = min(L, b + step)
            removed[i].append((a, b))
    out = []
    for i, s in enumerate(S):
        L = C[i][-1]
        keep, cur = [], 0.0
        for a, b in sorted(removed[i]):
            if a > cur + 1e-9:
                keep.append((cur, a))
            cur = max(cur, b)
        if cur < L - 1e-9:
            keep.append((cur, L))
        for a, b in keep:
            if b - a > 0.3:
                out.append(_simplify(_sub(s, C[i], a, b)))
    return out


def _simplify(P, tol=0.005):
    if len(P) < 3:
        return P
    a, b = P[0], P[-1]
    k, dm = 0, -1
    for i in range(1, len(P) - 1):
        d = _seg_dist(P[i], a, b)
        if d > dm:
            k, dm = i, d
    if dm <= tol:
        return [a, b]
    return _simplify(P[:k + 1], tol)[:-1] + _simplify(P[k:], tol)


@functools.lru_cache(maxsize=256)
def label_pieces(text, H, gap, font_path=None):
    """Подпись с разрывами: куски-ломаные в мм, габарит (x0, y0, x1, y1). Кэш — по тексту и высоте."""
    font = load_font(font_path)
    pieces = gapify(text_strokes(text, H, font), gap)
    pts = [p for s in pieces for p in s]
    if not pts:
        raise LabelError("подпись «%s» пустая" % text)
    return tuple(tuple(p) for p in pieces), (min(x for x, y in pts), min(y for x, y in pts), max(x for x, y in pts), max(y for x, y in pts))


# ============================================================================================ место на детали
def _blocked(part, margin, res):
    """Растр детали: True — нельзя (вне контура, ближе margin к кромке, отверстиям, прорезям, гравировке)."""
    import numpy as np
    from PIL import Image, ImageDraw
    outer = part["shapes"][-1]
    x0, y0, x1, y1 = G.bbox([outer])
    nx, ny = int(math.ceil((x1 - x0) / res)) + 3, int(math.ceil((y1 - y0) / res)) + 3
    img = Image.new("1", (nx, ny), 1)
    dr = ImageDraw.Draw(img)
    T = lambda p: ((p[0] - x0) / res + 1, (p[1] - y0) / res + 1)
    w = int(math.ceil(2 * margin / res)) + 2
    rr = margin / res + 1

    def stroke(P, closed):
        Q = [T(p) for p in P] + ([T(P[0])] if closed else [])
        dr.line(Q, fill=1, width=w)
        for q in Q:
            dr.ellipse([q[0] - rr, q[1] - rr, q[0] + rr, q[1] + rr], fill=1)
    P = G.points(outer, 0.05)
    dr.polygon([T(p) for p in P], fill=0)
    stroke(P, True)
    for s in part["shapes"][:-1]:
        Ps = G.points(s, 0.05)
        if G.is_closed(s):
            dr.polygon([T(p) for p in Ps], fill=1)
        elif s["layer"] == 1 and len(Ps) >= 3:
            # открытая прорезь (жалюзи): язычок — внутри П вместе с хордой — его выгибают; хорда — линия гиба.
            # Язычок занят целиком, от хорды — тот же отступ
            dr.polygon([T(p) for p in Ps], fill=1)
            stroke(Ps, True)
        stroke(Ps, G.is_closed(s))
    return np.array(img, dtype=bool), (x0, y0)


def _clear_exact(part, pieces, margin):
    """Точная проверка: все точки подписи внутри внешнего контура и не ближе margin к любой фигуре детали."""
    outer = part["shapes"][-1]
    Po = G.points(outer, 0.02)
    segs = []
    for s in part["shapes"]:
        P = G.points(s, 0.02)
        segs += list(zip(P, P[1:] + (P[:1] if G.is_closed(s) else [])))
    holes = [G.points(s, 0.05) for s in part["shapes"][:-1] if G.is_closed(s)]
    tongues = [G.points(s, 0.05) for s in part["shapes"][:-1] if not G.is_closed(s) and s["layer"] == 1 and len(G.points(s, 0.05)) >= 3]
    holes += tongues
    for P in tongues:                                  # хорда язычка (линия гиба) — как кромка
        segs.append((P[-1], P[0]))
    for pc in pieces:
        dense = []
        for a, b in zip(pc, pc[1:]):
            n = max(1, int(math.dist(a, b) / 0.5))
            dense += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]
        for x in dense:
            if not G.inside(x, Po) or any(G.inside(x, h) for h in holes):
                return False
            if min(G.seg_point_dist(x, a, b) for a, b in segs) < margin - 1e-6:
                return False
    return True


def place_label(part, text, H=15.0, H_min=10.0, margin=3.0, gap=1.0, font_path=None, res=0.5):
    """Найти место для подписи. Вернуть (фигуры подписи в координатах детали, сведения) или (None, причина)."""
    import numpy as np
    B, (ox, oy) = _blocked(part, margin, res)
    S = np.zeros((B.shape[0] + 1, B.shape[1] + 1), dtype=np.int64)
    S[1:, 1:] = np.cumsum(np.cumsum(B, 0), 1)
    x0, y0, x1, y1 = G.bbox([part["shapes"][-1]])
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    long_x = (x1 - x0) >= (y1 - y0)
    h = H
    while h >= H_min - 1e-9:
        pieces, (bx0, by0, bx1, by1) = label_pieces(text, round(h, 3), gap, font_path)
        # «в самом большом свободном месте»: сначала места с запасом вокруг подписи (20, 12, 6 мм сверх отступа),
        # среди них — ближе к центру детали; узкие щели между прорезями — в последнюю очередь
        for extra, rot in [(e, r) for e in EXTRA for r in ((0, 90) if long_x else (90, 0))]:
            w_mm, h_mm = (bx1 - bx0, by1 - by0) if rot == 0 else (by1 - by0, bx1 - bx0)
            ex = int(round(extra / res))
            rw, rh = int(math.ceil(w_mm / res)) + 1 + 2 * ex, int(math.ceil(h_mm / res)) + 1 + 2 * ex
            if rw >= B.shape[1] or rh >= B.shape[0]:
                continue
            tot = S[rh:, rw:] - S[:-rh, rw:] - S[rh:, :-rw] + S[:-rh, :-rw]
            iy, ix = np.nonzero(tot == 0)
            if not len(iy):
                continue
            # центр прямоугольника подписи в мм (запас — поровну со всех сторон); ближе к центру детали
            px = ox + (ix - 1 + ex) * res + w_mm / 2
            py = oy + (iy - 1 + ex) * res + h_mm / 2
            order = np.argsort((px - cx) ** 2 + (py - cy) ** 2, kind="stable")
            for k in order[:60]:
                # куски подписи: поворот вокруг начала, затем центр габарита — в найденный центр
                if rot == 0:
                    tp = lambda p: (p[0] - (bx0 + bx1) / 2 + px[k], p[1] - (by0 + by1) / 2 + py[k])
                else:
                    tp = lambda p: (-(p[1] - (by0 + by1) / 2) + px[k], (p[0] - (bx0 + bx1) / 2) + py[k])
                placed = [[tp(p) for p in pc] for pc in pieces]
                if _clear_exact(part, placed, margin):
                    ln = part["shapes"][-1].get("layer_name", "0")
                    shapes = [dict(handle=None, kind="LwPolyline", verts=[(x, y, 0.0) for x, y in pc], flag=0, sp=0.0, layer=2,
                                   layer_name=ln, coedge=0, flag64=0, outer=0, lead=None, label=True) for pc in placed]
                    return shapes, dict(text=text, height=round(h, 3), rot=rot, center=(float(px[k]), float(py[k])),
                                        margin=margin, gap=gap)
        h -= 1.0
    return None, "подпись «%s» не помещается даже высотой %g мм с отступом %g мм" % (text, H_min, margin)


def apply_labels(parts, texts, H=15.0, H_min=10.0, margin=3.0, gap=1.0, font_path=None):
    """texts: {имя детали (или файла без расширения) | "*": текст}; своё имя важнее «*». Подписи вставляются в детали
    перед внешним контуром (он остаётся последним). Вернуть отчёт [(имя, текст, высота | None, причина)]."""
    if H_min > H:
        raise LabelError("наименьшая высота подписи %g больше высоты %g" % (H_min, H))
    key = lambda p: (p["name"], os.path.splitext(p.get("src") or "")[0])
    unknown = [k for k in texts if k != "*" and not any(k in key(p) for p in parts)]
    if unknown:
        raise LabelError("подпись для %s: нет такой детали (есть: %s)" % (", ".join(unknown), ", ".join(p["name"] for p in parts)))
    rep = []
    for p in parts:
        text = next((texts[k] for k in key(p) if k in texts), texts.get("*"))
        if not text:
            continue
        shapes, info = place_label(p, text, H, H_min, margin, gap, font_path)
        if shapes is None:
            rep.append((p["name"], text, None, info))
            p.setdefault("warnings", []).append(info)
            continue
        p["shapes"] = p["shapes"][:-1] + shapes + p["shapes"][-1:]
        p["label"] = info
        rep.append((p["name"], text, info["height"], ""))
    return rep
