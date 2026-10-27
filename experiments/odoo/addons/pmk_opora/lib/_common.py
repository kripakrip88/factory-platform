# -*- coding: utf-8 -*-
"""Общее для чертежей опор в.2: вид в масштабе, подбор масштаба, выноски, текст ТТ, штамп,
сохранение PDF/PNG, запись DXF R12 (слои CUT — рез, BEND — риски гибов, MARK — разметка).

Рисование — pmk_zakladnye/lib/gost_draw.py (лист А3, размеры, таблицы, основная надпись).
Его не правим: всё, чего там нет, — здесь.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ZK_LIB = os.path.normpath(os.path.join(HERE, "..", "..", "pmk_zakladnye", "lib"))
for _p in (ZK_LIB, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gost_draw as g  # noqa: E402
import rules_v2 as rv  # noqa: E402

PNG_DPI = 110
SCALES = [1, 2, 2.5, 4, 5, 10, 15, 20, 25]


class View:
    """Вид в масштабе 1:sc: x вправо, y вверх (натура, мм) → мм листа от точки (ox, oy)."""

    def __init__(self, ox, oy, sc):
        self.ox, self.oy, self.sc = ox, oy, sc

    def p(self, x, y):
        return (self.ox + x / self.sc, self.oy - y / self.sc)

    def x(self, x):
        return self.ox + x / self.sc

    def y(self, y):
        return self.oy - y / self.sc

    def poly(self, pts, w=g.MAIN, close=True, dash=None):
        g.poly([self.p(*q) for q in pts], w, close=close, dash=dash)

    def line(self, x1, y1, x2, y2, w=g.THIN, dash=None):
        g.line(*self.p(x1, y1), *self.p(x2, y2), w=w, dash=dash)

    def circle(self, x, y, r, lw=g.MAIN, dash=None):
        g.circle(*self.p(x, y), r / self.sc, lw=lw, dash=dash)

    def mm(self, sheet_mm):
        """Отступ в мм листа → натура (выноски и оси не зависят от масштаба)."""
        return sheet_mm * self.sc


def pick(w, h, bw, bh, least=1):
    """Стандартный масштаб ГОСТ 2.302: вид w×h мм натуры влезает в место bw×bh мм листа."""
    for sc in SCALES:
        if sc >= least and w / sc <= bw and h / sc <= bh:
            return sc
    return SCALES[-1]


def lab(sc):
    return "1:%s" % ("%g" % sc).replace(".", ",")


def arc_pts(cx, cy, r, a0, a1, n=None):
    """Точки дуги от угла a0 до a1 (градусы, против часовой при a1 > a0)."""
    n = n or max(6, int(abs(a1 - a0) / 4))
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def wrap(s, h, width):
    out, cur = [], ""
    for word in s.split(" "):
        test = (cur + " " + word).strip()
        if g.tlen(test, h) > width and cur:
            out.append(cur)
            cur = word
        else:
            cur = test
    out.append(cur)
    return out


def lead(view, x, y, dx, dy, label, h=3.5, dot=True, to=None):
    """Выноска от точки детали (натура) к полке; отступ полки — в мм листа (не зависит от масштаба)."""
    x0, y0 = view.p(x, y)
    x1, y1 = to if to else (x0 + dx, y0 + dy)
    g.shelf(x0, y0, x1, y1, label, h=h, dot=dot)


def text_block(x, y0, y1, width, paras, sizes=(2.8, 2.6, 2.4, 2.2, 2.0)):
    """Технические требования: самый крупный шрифт, при котором абзацы влезают между y0 и y1."""
    for h in sizes:
        step = h * 1.64
        lines = []
        for para in paras:
            prefix = para[:len(para) - len(para.lstrip(" "))]
            for i, ln in enumerate(wrap(para.strip(), h, width - g.tlen(prefix + "  ", h))):
                lines.append(((prefix if i == 0 else prefix + "  ") + ln, step))
            lines.append(("", step * 0.18))
        if y0 + sum(s for _, s in lines) <= y1 or h == sizes[-1]:
            y = y0
            for ln, s in lines:
                if ln:
                    g.text(x, y, ln, h=h)
                y += s
            return y
    return y0


def stamp(code, name1, name2, mass, scale, sheets):
    """Основная надпись (форма 1): в графе материала — какие правила (их проверяет окно марки)."""
    g.stamp(code, name1, name2, mass, scale, material="", sheets=sheets, name_h=3.5)
    mh = 3.5
    while g.tlen(rv.RULES_TITLE, mh) > 66 and mh > 2.2:
        mh -= 0.25
    g.text(230 + 100, 237 + 49, rv.RULES_TITLE, h=mh, align="c")


def save(pdf_path, png_base):
    g.doc.save(pdf_path)
    pngs = []
    for i, pg in enumerate(g.doc):
        path = "%s — лист%s.png" % (png_base, i + 1)
        pg.get_pixmap(dpi=PNG_DPI).save(path)
        pngs.append(path)
    return pngs


def pipe_runs(view, cx, cy, r, xlim=None, lower_only=False, w=g.THIN, dash=None):
    """Труба условно: окружность или её нижняя часть в пределах |x| ≤ xlim (большие Дн у КП)."""
    pts = arc_pts(cx, cy, r, -90, 270, 180)
    run = []
    for q in pts:
        ok = (xlim is None or abs(q[0] - cx) <= xlim) and (not lower_only or q[1] <= cy + 1e-6)
        if ok:
            run.append(q)
        elif run:
            if len(run) > 1:
                view.poly(run, w=w, close=False, dash=dash)
            run = []
    if len(run) > 1:
        view.poly(run, w=w, close=(xlim is None and not lower_only), dash=dash)


# ─── Корпус «П» в разрезе ────────────────────────────────────────────────
def corpus_section(view, B, h1, S, r, seam=False, w=g.MAIN):
    """Сечение корпуса: наружный и внутренний контур с гибами r (внутр.) и r + S (наруж.).
    seam — корпус из двух уголков: стык по оси дна."""
    hb = B / 2.0
    ro, ri = r + S, r
    outer = ([(-hb, h1)] + arc_pts(-hb + ro, ro, ro, 180, 270, 12) + arc_pts(hb - ro, ro, ro, 270, 360, 12)
             + [(hb, h1)])
    inner = ([(hb - S, h1)] + arc_pts(hb - ro, ro, ri, 360, 270, 12) + arc_pts(-hb + ro, ro, ri, 270, 180, 12)
             + [(-hb + S, h1)])
    view.poly(outer + inner, w=w)
    if seam:
        view.line(0, 0, 0, S, w=g.MAIN)


# ─── DXF R12 ─────────────────────────────────────────────────────────────
class Dxf:
    """Минимальный DXF R12 (ENTITIES): LINE, CIRCLE, ARC. Слои: CUT — контур реза, BEND — риски
    гибов, MARK — разметка (рёбра, середина полосы). Единицы — мм, начало — левый нижний угол."""

    def __init__(self):
        self.ents = []

    def line(self, x1, y1, x2, y2, layer="CUT"):
        self.ents.append(("LINE", layer, x1, y1, x2, y2))

    def poly(self, pts, layer="CUT", close=True):
        n = len(pts)
        for i in range(n if close else n - 1):
            self.line(*pts[i], *pts[(i + 1) % n], layer=layer)

    def circle(self, cx, cy, r, layer="CUT"):
        self.ents.append(("CIRCLE", layer, cx, cy, r))

    def arc(self, cx, cy, r, a0, a1, layer="CUT"):
        """Дуга против часовой от a0 до a1, градусы."""
        self.ents.append(("ARC", layer, cx, cy, r, a0 % 360, a1 % 360))

    def risk(self, x, width, layer="BEND"):
        """Риски гиба поперёк полосы шириной width: по MARK_LEN мм у обеих кромок, отступ 1 мм."""
        n = rv.MARK_LEN
        self.line(x, 1, x, 1 + n, layer)
        self.line(x, width - 1, x, width - 1 - n, layer)

    def hline_broken(self, y, x0, x1, gaps, layer="MARK"):
        """Разметка вдоль y от x0 до x1, прерванная на ±MARK_GAP у осей гибов gaps."""
        cuts = sorted(gaps)
        cur = x0
        for c in cuts:
            if c - rv.MARK_GAP > cur:
                self.line(cur, y, c - rv.MARK_GAP, y, layer)
            cur = max(cur, c + rv.MARK_GAP)
        if x1 > cur:
            self.line(cur, y, x1, y, layer)

    def write(self, path):
        out = ["0", "SECTION", "2", "ENTITIES"]
        for e in self.ents:
            if e[0] == "LINE":
                _, layer, x1, y1, x2, y2 = e
                out += ["0", "LINE", "8", layer, "10", "%.3f" % x1, "20", "%.3f" % y1, "11", "%.3f" % x2,
                        "21", "%.3f" % y2]
            elif e[0] == "CIRCLE":
                _, layer, cx, cy, r = e
                out += ["0", "CIRCLE", "8", layer, "10", "%.3f" % cx, "20", "%.3f" % cy, "40", "%.3f" % r]
            elif e[0] == "ARC":
                _, layer, cx, cy, r, a0, a1 = e
                out += ["0", "ARC", "8", layer, "10", "%.3f" % cx, "20", "%.3f" % cy, "40", "%.3f" % r,
                        "50", "%.4f" % a0, "51", "%.4f" % a1]
        out += ["0", "ENDSEC", "0", "EOF"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        return path


def dxf_name(mark, pos, name, S, qty):
    """«219-КХ-А12 поз1 Корпус гнутый S3 - 1шт.dxf» — как у Игоря: толщина и штук на опору."""
    return "%s поз%s %s S%s - %sшт.dxf" % (mark, pos, name, rv.fmt(S), qty)


def num(v, nd=1):
    """Размер на чертеже: целое — без запятой, иначе nd знаков."""
    return rv.fmt(round(v, nd), nd)
