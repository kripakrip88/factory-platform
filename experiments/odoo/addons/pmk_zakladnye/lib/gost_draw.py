"""Общие функции для чертежей А3 (PyMuPDF): линии, размеры, штриховка, таблицы, основная надпись.
Все координаты — мм листа, начало в левом верхнем углу."""
import math
import fitz

K = 72 / 25.4
# ПРАВКА ERP (pmk_zakladnye, 25.10.2026): шрифт — Liberation Sans Narrow Italic (свободный, метрически
# = Arial Narrow; решение Антона). В образе фонового процесса — пакет fonts-liberation. PMK_ZK_FONT
# переопределяет; на Mac без Liberation — прежний Arial Narrow (только для локального запуска, в репозиторий
# шрифт Microsoft не кладём).
import os as _os

FONT = next((f for f in (
    _os.environ.get("PMK_ZK_FONT"),
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Italic.ttf",
    "/usr/share/fonts/liberation/LiberationSansNarrow-Italic.ttf",
    "/System/Library/Fonts/Supplemental/Arial Narrow Italic.ttf",
) if f and _os.path.exists(f)), "LiberationSansNarrow-Italic.ttf")
MAIN, THIN = 0.5, 0.25
BLACK = (0, 0, 0)
AXIS = f"[{10*K:.2f} {1.5*K:.2f} {1*K:.2f} {1.5*K:.2f}] 0"
HIDDEN = f"[{3*K:.2f} {1.5*K:.2f}] 0"

doc = page = F = None


def new_sheet():
    global doc, page, F
    doc = fitz.open()
    page = doc.new_page(width=420 * K, height=297 * K)
    page.insert_font(fontname="gost", fontfile=FONT)
    F = fitz.Font(fontfile=FONT)
    rect(20, 5, 395, 287)
    text(415, 296, "Формат А3", h=2.5, align="r")


def next_sheet(code, sheet, title):
    """Следующий лист А3 того же документа: рамка + основная надпись по форме 2а (185×15)."""
    global page
    page = doc.new_page(width=420 * K, height=297 * K)
    page.insert_font(fontname="gost", fontfile=FONT)
    rect(20, 5, 395, 287)
    text(415, 296, "Формат А3", h=2.5, align="r")
    bx, by = 230, 277
    rect(bx, by, 185, 15)
    for x in (7, 17, 40, 55, 65, 175):
        line(bx + x, by, bx + x, by + 15, MAIN)
    for i in (1, 2):
        line(bx, by + i * 5, bx + 65, by + i * 5, THIN)
    line(bx + 175, by + 7, bx + 185, by + 7, MAIN)
    for x0, x1, s_ in ((0, 7, "Изм."), (7, 17, "Лист"), (17, 40, "№ докум."), (40, 55, "Подп."), (55, 65, "Дата")):
        text(bx + (x0 + x1) / 2, by + 14, s_, h=2.5, align="c")
    text(bx + 120, by + 10, code, h=7, align="c")
    text(bx + 180, by + 5, "Лист", h=2.5, align="c")
    text(bx + 180, by + 13, str(sheet), h=3.5, align="c")
    text(40, 16, title, h=5)


def save(path_pdf, path_png):
    doc.save(path_pdf)
    page.get_pixmap(dpi=110).save(path_png)


def P(x, y):
    return fitz.Point(x * K, y * K)


def num(v, nd=2):
    return f"{v:.{nd}f}".replace(".", ",")


def line(x1, y1, x2, y2, w=THIN, dash=None):
    sh = page.new_shape()
    sh.draw_line(P(x1, y1), P(x2, y2))
    sh.finish(width=w * K, color=BLACK, dashes=dash)
    sh.commit()


def poly(pts, w=MAIN, close=True, fill=None, dash=None):
    sh = page.new_shape()
    sh.draw_polyline([P(*p) for p in pts])
    sh.finish(width=w * K, color=BLACK, fill=fill, closePath=close, dashes=dash)
    sh.commit()


def rect(x, y, w, h, lw=MAIN, dash=None):
    poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], lw, dash=dash)


def circle(cx, cy, r, lw=THIN, fill=None, dash=None):
    sh = page.new_shape()
    sh.draw_circle(P(cx, cy), r * K)
    sh.finish(width=lw * K, color=BLACK, fill=fill, dashes=dash)
    sh.commit()


def tlen(s, h):
    return F.text_length(s, fontsize=h / 0.716 * K) / K


def text(x, y, s, h=3.5, rot=0, align="l"):
    ln = tlen(s, h)
    if align == "c":
        if rot == 0:
            x -= ln / 2
        else:
            y += ln / 2
    elif align == "r":
        x -= ln
    page.insert_text(P(x, y), s, fontsize=h / 0.716 * K, fontname="gost", rotate=rot)


def arrow(x, y, dx, dy, ln=2.5):
    bx, by = x - dx * ln, y - dy * ln
    poly([(x, y), (bx - dy * 0.45, by + dx * 0.45), (bx + dy * 0.45, by - dx * 0.45)], THIN, fill=BLACK)


def hatch(pts, step=1.2):
    s = [p[0] + p[1] for p in pts]
    c = min(s) + step / 2
    n = len(pts)
    while c < max(s):
        xs = []
        for i in range(n):
            (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
            f1, f2 = x1 + y1 - c, x2 + y2 - c
            if (f1 < 0) != (f2 < 0):
                xs.append(x1 + (x2 - x1) * f1 / (f1 - f2))
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            line(a, c - a, b, c - b)
        c += step


def dim_h(x1, x2, y0, yd, label, outside=False, h=3.5, side="right"):
    s = 1 if yd > y0 else -1
    for x in (x1, x2):
        line(x, y0 + s * 1, x, yd + s * 2)
    if outside:
        line(x1 - 5, yd, x2 + 5, yd)
        arrow(x1, yd, 1, 0)
        arrow(x2, yd, -1, 0)
    else:
        line(x1, yd, x2, yd)
        arrow(x1, yd, -1, 0)
        arrow(x2, yd, 1, 0)
    tx = (x1 + x2) / 2
    if outside and (x2 - x1) <= tlen(label, h) + 1:
        tx = x1 - 5 - tlen(label, h) / 2 if side == "left" else x2 + 5 + tlen(label, h) / 2
    text(tx, yd - 0.8, label, h=h, align="c")


def dim_v(y1, y2, x0, xd, label, outside=False, h=3.5, side="top"):
    s = 1 if xd > x0 else -1
    for y in (y1, y2):
        line(x0 + s * 1, y, xd + s * 2, y)
    if outside:
        line(xd, y1 - 5, xd, y2 + 5)
        arrow(xd, y1, 0, 1)
        arrow(xd, y2, 0, -1)
    else:
        line(xd, y1, xd, y2)
        arrow(xd, y1, 0, -1)
        arrow(xd, y2, 0, 1)
    ty = (y1 + y2) / 2
    if outside and (y2 - y1) <= tlen(label, h) + 1:
        ty = y2 + 5 + tlen(label, h) / 2 if side == "bottom" else y1 - 5 - tlen(label, h) / 2
    text(xd - 0.8, ty, label, h=h, rot=90, align="c")


def shelf(x0, y0, x1, y1, label, h=3.5, dot=True):
    """Выноска от точки (x0, y0) к полке в (x1, y1). Полка уходит в сторону от точки, чтобы линия-выноска
    не пересекала надпись: точка правее — полка влево."""
    if dot:
        circle(x0, y0, 0.45, fill=BLACK)
    w = tlen(label, h) + 2
    line(x0, y0, x1, y1)
    if x0 > x1 + 0.5:
        line(x1 - w, y1, x1, y1)
        text(x1 - w + 1, y1 - 0.8, label, h=h)
    else:
        line(x1, y1, x1 + w, y1)
        text(x1 + 1, y1 - 0.8, label, h=h)


def cut_mark(x, y, sx, sy, dx, dy, label, ln=7):
    """Разомкнутая линия разреза: штрих от (x, y) наружу по (sx, sy), стрелка взгляда (dx, dy) длиной ln, буква."""
    ex, ey = x + sx * 7, y + sy * 7
    line(x, y, ex, ey, 0.8)
    ax, ay = ex - sx * 1.5, ey - sy * 1.5
    line(ax, ay, ax + dx * (ln - 1), ay + dy * (ln - 1))
    arrow(ax + dx * ln, ay + dy * ln, dx, dy, ln=min(2.5, ln - 1))
    text(ax + dx * ln * 0.55 + sx * 2.5 - 1.2, ay + dy * ln * 0.55 + sy * 2.5 + 1.8, label, h=3.5)


def table(x, y, cols, rows, hdr_h, row_h, hdr_size=2.5, size=3):
    widths = [c[1] for c in cols]
    tw, th = sum(widths), hdr_h + row_h * len(rows)
    rect(x, y, tw, th)
    line(x, y + hdr_h, x + tw, y + hdr_h, MAIN)
    for i in range(1, len(rows)):
        line(x, y + hdr_h + row_h * i, x + tw, y + hdr_h + row_h * i)
    cx = x
    for (title, w) in cols:
        if cx > x:
            line(cx, y, cx, y + th, MAIN)
        parts = title.split("\n")
        y0 = y + hdr_h / 2 - (len(parts) - 1) * hdr_size * 0.8 + hdr_size / 2
        for j, pp in enumerate(parts):
            text(cx + w / 2, y0 + j * hdr_size * 1.6, pp, h=hdr_size, align="c")
        cx += w
    for i, r in enumerate(rows):
        cx = x
        for (val, w) in zip(r, widths):
            al = "l" if isinstance(val, tuple) else "c"
            v = val[0] if isinstance(val, tuple) else val
            text(cx + (1.5 if al == "l" else w / 2), y + hdr_h + row_h * i + row_h / 2 + size / 2, v, h=size, align=al)
            cx += w


def stamp(code, name1, name2, mass, scale, material="См. спецификацию", sheets=1, name_h=5):
    bx, by = 230, 237
    rect(bx, by, 185, 55)
    for x in (7, 17, 40, 55):
        line(bx + x, by, bx + x, by + 30 if x == 7 else by + 55, MAIN)
    line(bx + 65, by, bx + 65, by + 55, MAIN)
    line(bx + 135, by + 15, bx + 135, by + 55, MAIN)
    for i in range(1, 11):
        line(bx, by + i * 5, bx + 65, by + i * 5, MAIN if i in (5, 6) else THIN)
    for y in (15, 40):
        line(bx + 65, by + y, bx + 185, by + y, MAIN)
    for y in (20, 35):
        line(bx + 135, by + y, bx + 185, by + y, MAIN)
    for x in (150, 167):
        line(bx + x, by + 15, bx + x, by + 35, MAIN)
    line(bx + 160, by + 35, bx + 160, by + 40, MAIN)
    for x0, x1, s in ((0, 7, "Изм."), (7, 17, "Лист"), (17, 40, "№ докум."), (40, 55, "Подп."), (55, 65, "Дата")):
        text(bx + (x0 + x1) / 2, by + 29, s, h=2.5, align="c")
    for i, s in enumerate(("Разраб.", "Пров.", "Т.контр.", "Н.контр.", "Утв.")):
        text(bx + 1, by + 34 + i * 5, s, h=2.5)
    text(bx + 125, by + 10, code, h=7, align="c")
    text(bx + 100, by + 25, name1, h=name_h, align="c")
    text(bx + 100, by + 33, name2, h=name_h, align="c")
    text(bx + 100, by + 49, material, h=3.5, align="c")
    for x, s in ((142.5, "Лит."), (158.5, "Масса"), (176, "Масштаб")):
        text(bx + x, by + 19, s, h=2.5, align="c")
    text(bx + 158.5, by + 30, mass, h=5, align="c")
    text(bx + 176, by + 29, scale, h=3.5 if len(scale) <= 9 else 2.5, align="c")
    text(bx + 137, by + 39, "Лист 1", h=2.5)
    text(bx + 162, by + 39, f"Листов {sheets}", h=2.5)
