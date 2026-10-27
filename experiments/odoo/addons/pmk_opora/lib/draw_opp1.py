# -*- coding: utf-8 -*-
"""Чертёж опоры ОПП1 (ОСТ 36-94-83, черт. 1, табл. 1) по правилам в.2 (чертежи И. Бутова).

Один лист А3: сечение 1–1 (вдоль трубы видна стенка с ложем R), вид сбоку (профиль «П» с ребром),
развёртка корпуса, ребро, спецификация, ТТ, штамп. Отличия от в.1: гиб корпуса R = 1,5S, стенка
сужается от 70 до B только на прямом участке (в зоне гиба и на дне — 70), ребро 91 без отверстий.
"""
import math
import os

from _common import Dxf, View, arc_pts, dxf_name, g, lead, num, rv, save, stamp, text_block

BASE_Y = 194


def wall_outline(geo):
    """Стенка спереди: 70 на высоте гиба (r + S), прямо сужается до B на верху H1, сверху ложе R."""
    W0, B, H1, R, S = geo["W0"], geo["B"], geo["H1"], geo["R"], geo["S"]
    yb = geo["corpus"]["r"] + S
    cy = geo["saddle_center"]
    a = math.degrees(math.asin((R - geo["depth"]) / R))
    saddle = arc_pts(0, cy, R, -a, -180 + a, 24)
    return [(-W0 / 2.0, 0), (W0 / 2.0, 0), (W0 / 2.0, yb), (B / 2.0, H1)] + saddle + [(-B / 2.0, H1), (-W0 / 2.0, yb)]


def dev_outline(geo, n=24):
    """Развёртка корпуса (x — вдоль развёртки, y — поперёк от оси): точки контура и дуги ложа."""
    c, B, W0, R, depth, chord = geo["corpus"], geo["B"], geo["W0"], geo["R"], geo["depth"], geo["chord"]
    D, wall = c["total"], c["wall"]
    al = math.degrees(math.asin(chord / 2.0 / R))
    right = arc_pts(D + R - depth, 0, R, 180 + al, 180 - al, n)
    left = arc_pts(-(R - depth), 0, R, al, -al, n)
    return ([(0, -B / 2.0), (wall, -W0 / 2.0), (D - wall, -W0 / 2.0), (D, -B / 2.0)] + right
            + [(D, B / 2.0), (D - wall, W0 / 2.0), (wall, W0 / 2.0), (0, B / 2.0)] + left)


def draw(geo, steel, out_dir):
    mark, dn, H = geo["mark"], geo["dn"], geo["H"]
    S, L, W0, B, R, H1, H2 = geo["S"], geo["L"], geo["W0"], geo["B"], geo["R"], geo["H1"], geo["H2"]
    c, rib = geo["corpus"], geo["rib"]
    r = c["r"]
    PC = geo["pipe_axis"]
    rp = dn / 2.0
    dn_t = rv.fmt(dn)
    parts = {p["key"]: p for p in geo["parts"]}
    top = max(PC + rp, H1)

    g.new_sheet()
    # ── 1–1: стенка с ложем, 1:1 ──
    v1 = View(88, BASE_Y, 1)
    g.text(88, 22, "1–1 (1:1)", h=3.5, align="c")
    g.text(88, 27.5, "труба Ø%s показана условно" % dn_t, h=3, align="c")
    v1.poly(wall_outline(geo))
    v1.circle(0, PC, rp, lw=g.THIN, dash=g.AXIS)
    v1.line(-W0 / 2.0 - 6, PC, W0 / 2.0 + 6, PC, dash=g.AXIS)
    v1.line(0, -4, 0, top + 6, dash=g.AXIS)
    v1.poly([(-S / 2.0, S), (S / 2.0, S), (S / 2.0, H2), (-S / 2.0, H2)], w=g.THIN)
    g.hatch([v1.p(-S / 2.0, S), v1.p(S / 2.0, S), v1.p(S / 2.0, H2), v1.p(-S / 2.0, H2)], step=0.8)
    v1.line(-W0 / 2.0, S, W0 / 2.0, S, dash=g.HIDDEN)
    yb = v1.y(0)
    g.dim_h(v1.x(-W0 / 2.0), v1.x(W0 / 2.0), yb, yb + 10, num(W0))
    g.dim_h(v1.x(-B / 2.0), v1.x(B / 2.0), v1.y(H1), v1.y(top) - 8, num(B))
    v1.line(-B / 2.0 - 1, H1, -W0 / 2.0 - 2, H1)
    v1.line(-1, H, -W0 / 2.0 - 2, H)
    g.dim_v(v1.y(H1), yb, v1.x(-W0 / 2.0), v1.x(-W0 / 2.0) - 20, num(H1))
    g.dim_v(v1.y(H), yb, v1.x(-W0 / 2.0), v1.x(-W0 / 2.0) - 11, num(H))
    g.dim_v(v1.y(H2), yb, v1.x(W0 / 2.0), v1.x(W0 / 2.0) + 9, num(H2))
    # R ложа — вниз-вправо в тело стенки (как у Игоря): снаружи над стенкой выносные размера B.
    cy = geo["saddle_center"]
    pr = (R * math.cos(math.radians(-60)), cy + R * math.sin(math.radians(-60)))
    g.shelf(*v1.p(*pr), v1.x(0) + 5, v1.y(H) + 12, "R%s" % num(R), h=3, dot=False)
    y1 = H2 + 0.45 * (H1 - H2)
    half = (W0 - (W0 - B) * (y1 - r - S) / c["wall"]) / 2.0
    lead(v1, half - 5, y1 - 4, 0, 0, "1", to=(v1.x(W0 / 2.0) + 14, v1.y(y1)))
    lead(v1, 0, H2 * 0.55, 0, 0, "2", to=(v1.x(-W0 / 2.0) - 3, v1.y(H2 * 0.75)))   # полка между стенкой и H

    # ── вид сбоку: профиль «П», ребро, 1:1 ──
    v2 = View(178, BASE_Y, 1)
    g.text(178 + L / 2.0, 22, "Вид сбоку (1:1)", h=3.5, align="c")
    ro = r + S
    outer = [(0, H1)] + arc_pts(ro, ro, ro, 180, 270, 8) + arc_pts(L - ro, ro, ro, 270, 360, 8) + [(L, H1)]
    inner = [(L - S, H1)] + arc_pts(L - ro, ro, r, 360, 270, 8) + arc_pts(ro, ro, r, 270, 180, 8) + [(S, H1)]
    v2.poly(outer + inner)
    x0 = S + rib["gap"]
    rl, ch = rib["l"], rib["ch"]
    v2.poly([(x0 + ch, S), (x0 + rl - ch, S), (x0 + rl, S + ch), (x0 + rl, H2), (x0, H2), (x0, S + ch)], w=g.THIN)
    for hx, hy in rib["holes"]:
        v2.circle(x0 + hx, S + hy, rib["hole_d"] / 2.0)
        v2.line(x0 + hx - 7, S + hy, x0 + hx + 7, S + hy, dash=g.AXIS)
        v2.line(x0 + hx, S + hy - 7, x0 + hx, S + hy + 7, dash=g.AXIS)
    v2.line(-10, PC, L + 10, PC, dash=g.AXIS)
    v2.line(-10, H, L + 10, H, w=g.THIN, dash=g.AXIS)
    v2.line(-10, H + dn, L + 10, H + dn, w=g.THIN, dash=g.AXIS)
    yb = v2.y(0)
    g.dim_h(v2.x(0), v2.x(L), yb, yb + 8, num(L))
    g.dim_h(v2.x(x0), v2.x(x0 + rl), v2.y(H2), v2.y(H2) - 6, num(rl))
    g.dim_v(v2.y(H2), yb, v2.x(0), v2.x(0) - 8, num(H2))
    ys = v2.y(H2 + 0.5 * (H - H2))           # толщина — поперёк стенки между ребром и трубой
    g.dim_h(v2.x(L - S), v2.x(L), ys + 0.01, ys, num(S), outside=True, side="right")
    g.shelf(*v2.p(L - S * 0.5, r * 0.6), v2.x(L) + 4, yb - 9, "R%s внутр." % num(r), h=3, dot=False)

    # ── развёртка корпуса, 1:2 ──
    D = c["total"]
    dv = View(36, 252, 2)
    g.text(36 + D / 4.0, 216, "Поз. 1. Развёртка корпуса (1:2) — лист %s %s" % (num(S), steel), h=3.5, align="c")
    dv.poly(dev_outline(geo))
    bm = c["bend_mark"]
    for x in (bm, D - bm):
        dv.line(x, -W0 / 2.0 - 4, x, W0 / 2.0 + 4, dash=g.AXIS)
    yb = dv.y(-W0 / 2.0)
    yt = dv.y(W0 / 2.0)
    g.dim_h(dv.x(0), dv.x(D), yb, yb + 8, num(D))
    g.dim_h(dv.x(0), dv.x(bm), yt, yt - 6, num(bm))
    g.dim_h(dv.x(D - c["wall"]), dv.x(D), yt, yt - 6, num(c["wall"]))
    g.dim_v(yt, yb, dv.x(D), dv.x(D) + 10, num(W0))
    g.dim_v(dv.y(B / 2.0), dv.y(-B / 2.0), dv.x(0), dv.x(0) - 8, num(B))
    g.text(dv.x(D / 2.0), dv.y(0) + 1, "гиб 90° R%s внутр. ×2" % num(r), h=2.8, align="c")

    # ── спецификация, ТТ ──
    rows = [("1", ("Корпус — лист %s %s" % (num(S), steel),), "1", g.num(parts["corpus"]["unit_mass"], 3)),
            ("2", ("Ребро — лист %s %s" % (num(S), steel),), "1", g.num(parts["rib"]["unit_mass"], 3))]
    g.text(305, 22, "Спецификация", h=3.5)
    g.table(305, 25, [("Поз.", 10), ("Наименование", 72), ("Кол.", 11), ("Масса\n1 шт, кг", 17)], rows, 9, 7,
            hdr_size=2.5, size=3)
    tt = [
        "1. Изготовить по ОСТ 36-94-83, опора %s: Дн %s, Н=%s. %s. Сталь %s." % (mark, dn_t, H, rv.RULES_TITLE, steel),
        "2. Корпус поз. 1 — гнутый «П», гибы 90° R%s внутр. (1,5S); стенки сужаются от %s до %s на прямом участке, "
        "в зоне гиба и на дне — %s." % (num(r), num(W0), num(B), num(W0)),
        "3. Ребро поз. 2 — по оси корпуса, зазор %s до стенок; приварить к дну с двух сторон: ГОСТ 14771-76-Т1, "
        "катет %s." % (num(rib["gap"]), num(S)),
        "4. Предельные отклонения размеров ±JT17/2 по ГОСТ 25346 (п. 7 ОСТ).",
        "5. Развёртка — K = %s; риски гибов и разметка ребра — в DXF (слои BEND, MARK)." % rv.fmt(rv.K),
        "6. Масса по деталям %s кг (по ОСТ — не более %s кг)." % (g.num(geo["mass"], 2), g.num(geo["mass_ost"], 2)),
        "7. Допущения — открытые вопросы к Игорю:",
    ] + ["   – " + a for a in geo["assumptions"]]
    text_block(305, 25 + 9 + 7 * len(rows) + 8, 134, 108, tt)

    # ── ребро, 1:1 ──
    rh = rib["h"]
    rx = 316
    rv_ = View(rx, 205, 1)
    g.text(rx + rl / 2.0, 142, "Поз. 2. Ребро (1:1) — лист %s %s" % (num(S), steel), h=3.5, align="c")
    rv_.poly([(ch, 0), (rl - ch, 0), (rl, ch), (rl, rh), (0, rh), (0, ch)])
    for hx, hy in rib["holes"]:
        rv_.circle(hx, hy, rib["hole_d"] / 2.0)
        rv_.line(hx - 7, hy, hx + 7, hy, dash=g.AXIS)
        rv_.line(hx, hy - 7, hx, hy + 7, dash=g.AXIS)
    yb = rv_.y(0)
    g.dim_h(rv_.x(0), rv_.x(rl), yb, yb + 8, num(rl))
    g.dim_v(rv_.y(rh), yb, rv_.x(0), rv_.x(0) - 8, num(rh))
    g.shelf(*rv_.p(rl - ch / 2.0, ch / 2.0), rv_.x(rl) - 4, yb - 5, "%s×45°" % num(ch), h=3, dot=False)
    g.text(rx + rl / 2.0, yb + 17, "Фаски %s×45° (2 места); %s" % (num(ch), "отв. Ø%s — по треб. заказчика" % rib["hole_d"]
                                                         if rib["holes"] else "отверстий нет (как у Игоря)"),
           h=2.8, align="c")

    stamp("ОПР.%s" % mark, "Опора подвижная корпусная", "%s ОСТ 36-94-83" % mark, g.num(geo["mass"], 2),
          "1:1; 1:2", sheets=1)

    base = os.path.join(out_dir, mark)
    pdf = base + ".pdf"
    pngs = save(pdf, base)

    # ── DXF ──
    d = Dxf()
    D2 = W0 / 2.0
    pts = [(0, -B / 2.0), (c["wall"], -D2), (D - c["wall"], -D2), (D, -B / 2.0), (D, -geo["chord"] / 2.0)]
    d.poly([(x, y + D2) for x, y in pts], close=False)
    al = math.degrees(math.asin(geo["chord"] / 2.0 / R))
    d.arc(D + R - geo["depth"], D2, R, 180 - al, 180 + al)
    pts = [(D, geo["chord"] / 2.0), (D, B / 2.0), (D - c["wall"], D2), (c["wall"], D2), (0, B / 2.0),
           (0, geo["chord"] / 2.0)]
    d.poly([(x, y + D2) for x, y in pts], close=False)
    d.arc(-(R - geo["depth"]), D2, R, -al, al)
    d.line(0, -geo["chord"] / 2.0 + D2, 0, -B / 2.0 + D2)
    for x in (bm, D - bm):
        d.risk(x, W0)
    for y in (D2 - S / 2.0, D2 + S / 2.0):
        d.line(H1 - H2, y, D - (H1 - H2), y, "MARK")
    p1 = d.write(os.path.join(out_dir, dxf_name(mark, 1, "Корпус", S, 1)))
    d = Dxf()
    d.poly([(ch, 0), (rl - ch, 0), (rl, ch), (rl, rh), (0, rh), (0, ch)])
    for hx, hy in rib["holes"]:
        d.circle(hx, hy, rib["hole_d"] / 2.0)
    p2 = d.write(os.path.join(out_dir, dxf_name(mark, 2, "Ребро", S, 1)))
    return dict(pdf=pdf, png=pngs, dxf=[dict(file=p1, pos="1", name="Корпус гнутый", thickness=S, qty=1),
                                         dict(file=p2, pos="2", name="Ребро", thickness=S, qty=1)])
