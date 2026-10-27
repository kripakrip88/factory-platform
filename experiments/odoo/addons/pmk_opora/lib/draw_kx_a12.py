# -*- coding: utf-8 -*-
"""Чертёж опоры КХ исполнения А12 (ОСТ 36-146-88, черт. 5) по правилам в.2 (чертежи И. Бутова).

Два листа А3: 1 — сборочный (вид вдоль оси трубы, вид сбоку, спецификация, ТТ, штамп),
2 — детали (корпус в разрезе и развёртка, ребро, полухомут и развёртка). Размеры — только из
rules_v2 (geo), здесь только раскладка на листе. DXF деталей — R12, слои CUT/BEND/MARK.
Вид корпуса и ребра на листе 2 и их DXF общие с КП (draw_kp_a12 берёт функции отсюда).
"""
import math
import os

from _common import (Dxf, View, arc_pts, corpus_section, dxf_name, g, lab, lead, num, pick, rv, save,
                     stamp, text_block)

# Покупные: ГОСТ 5915-70 (гайка, высота m), ГОСТ 7798-70 (головка k), размер под ключ.
NUT_H = {12: 10, 16: 13, 20: 16, 24: 19}
HEAD_K = {12: 7.5, 16: 10, 20: 12.5, 24: 15}
HEX_S = {12: 19, 16: 24, 20: 30, 24: 36}
BASE_Y = 215          # основание видов листа 1 (мм листа)
TT_X, TT_W = 305, 108


# ─── Геометрия контуров ──────────────────────────────────────────────────
def clamp_pts(cl, axis, lower):
    """Полухомут на виде вдоль трубы: дуга R…R+S, гибы лапок r = S (внутр.) и 2S (наруж.),
    лапки — нижняя грань на f от оси. Верхний полухомут; lower — зеркально вниз."""
    R, S, f, r, xc, a = cl["R"], cl["S"], cl["f"], cl["r"], cl["xc"], cl["a"]
    rA, half = r + S, cl["B1"] / 2.0
    cy = f + rA
    pts = [(half, f), (xc, f)]
    pts += arc_pts(xc, cy, rA, -90, -180 + a, 8)[1:]
    pts += arc_pts(0, 0, R, a, 180 - a)[1:]
    pts += arc_pts(-xc, cy, rA, -a, -90, 8)[1:]
    pts += [(-half, f), (-half, f + S), (-xc, f + S)]
    pts += arc_pts(-xc, cy, r, -90, -a, 8)[1:]
    pts += arc_pts(0, 0, R + S, 180 - a, a)[1:]
    pts += arc_pts(xc, cy, r, 180 + a, 270, 8)[1:]
    pts += [(half, f + S)]
    sgn = -1 if lower else 1
    return [(x, axis + sgn * y) for x, y in pts]


def rib_pts(rib, base=0.0, x0=None):
    """Торцевое ребро: низ на base, фаски ch, верх — дуга R с центром на высоте cy (от низа ребра).
    x0 — левый край (по умолчанию ребро по центру x = 0)."""
    w, ch, R = rib["w"], rib["ch"], rib["R"]
    cy, edge = rib["cy"] + base, rib["edge"] + base
    x0 = -w / 2.0 if x0 is None else x0
    xm = x0 + w / 2.0
    top = []
    for i in range(41):
        x = x0 + w - w * i / 40.0
        top.append((x, min(edge, cy - math.sqrt(R * R - (x - xm) ** 2))))
    return [(x0 + ch, base), (x0 + w - ch, base), (x0 + w, base + ch)] + top + [(x0, base + ch)]


def bolt_front(v, x, axis, cl, bd, bl):
    """Болт снизу вверх: головка под нижней лапкой, гайка над верхней (вид вдоль трубы)."""
    f, cs = cl["f"], cl["S"]
    y0 = axis - f - cs
    hs, k, nh = HEX_S[bd] / 2.0, HEAD_K[bd], NUT_H[bd]
    v.poly([(x - hs, y0), (x + hs, y0), (x + hs, y0 - k), (x - hs, y0 - k)])
    yn = axis + f + cs
    v.poly([(x - hs, yn), (x + hs, yn), (x + hs, yn + nh), (x - hs, yn + nh)])
    top = y0 + bl
    v.poly([(x - bd / 2.0, axis - f), (x - bd / 2.0, axis + f)], close=False)
    v.poly([(x + bd / 2.0, axis - f), (x + bd / 2.0, axis + f)], close=False)
    if top > yn + nh:
        v.poly([(x - bd / 2.0, yn + nh), (x - bd / 2.0, top), (x + bd / 2.0, top), (x + bd / 2.0, yn + nh)],
               close=False)
    v.line(x, y0 - k - v.mm(1.5), x, max(top, yn + nh) + v.mm(1.5), dash=g.AXIS)


# ─── Лист 2: корпус и ребро (общие с КП) ─────────────────────────────────
def detail_corpus(geo, steel, sec_box, dev_box):
    """Поз. 1: сечение корпуса (U или два уголка) и развёртка (U или один уголок)."""
    c, B, S, h1, L = geo["corpus"], geo["B"], geo["S"], geo["h1"], geo["L"]
    angles = c["angles"]
    x0, y0, x1, y1 = sec_box
    sc = pick(B, h1, x1 - x0 - 40, y1 - y0 - 30)
    cx = (x0 + x1) / 2.0
    avail = y1 - y0 - 24
    s1 = View(cx, y0 + 10 + (avail - h1 / sc) / 2.0 + h1 / sc, sc)
    g.text(cx, y0 + 4, "Поз. 1. Корпус%s (%s)" % (" — 2 уголка" if angles else " гнутый", lab(sc)),
           h=3.5, align="c")
    corpus_section(s1, B, h1, S, c["r"], seam=angles)
    yb = s1.y(0)
    g.dim_h(s1.x(-B / 2.0), s1.x(B / 2.0), yb, yb + 8, num(B))
    g.dim_v(s1.y(h1), yb, s1.x(B / 2.0), s1.x(B / 2.0) + 8, num(h1))
    # Радиус — внутрь «П» вверх-вправо (снаружи слева рамка листа), толщина — влево, шов — вверх
    # по оси: размеры справа и снизу, выноски их не пересекают.
    ri = c["r"]
    xr = -B / 2.0 + S + ri - ri * math.cos(math.radians(45))
    yr = S + ri - ri * math.sin(math.radians(45))
    rlab = "R%s внутр." % num(ri)
    if g.tlen(rlab, 3) + 6 > (B - 2 * S) / sc / 2.0:
        rlab = "R%s" % num(ri)
    lead(s1, -xr, yr, 0, 0, rlab, h=3, dot=False, to=(s1.x(B / 2.0 - S) - 2.5, yb - 10))
    lead(s1, -B / 2.0 + S / 2.0, h1 * 0.7, 0, 0, "S%s" % num(S), h=3, dot=False,
         to=(s1.x(-B / 2.0) - 8, s1.y(h1 * 0.7) - 6))
    if angles:
        lead(s1, 0, S, 0, 0, "шов", h=3, dot=False, to=(s1.x(0) - 2, yb - 21))
    # Развёртка: x — поперёк гибов, y — длина корпуса L.
    W = c["angle"] if angles else c["total"]
    bms = [c["bend_mark"]] if angles else [c["bend_mark"], W - c["bend_mark"]]
    x0, y0, x1, y1 = dev_box
    scd = pick(W, L, x1 - x0 - 16, y1 - y0 - 34)
    dv = View(x0 + 4 + ((x1 - x0 - 16) - W / scd) / 2.0, y1 - 14 - ((y1 - y0 - 34) - L / scd) / 2.0, scd)
    g.text(dv.x(W / 2.0), y0 + 4, "Развёртка поз. 1%s (%s)" % (" — уголок, 2 шт" if angles else "", lab(scd)),
           h=3.5, align="c")
    dv.poly([(0, 0), (W, 0), (W, L), (0, L)])
    for x in bms:
        dv.line(x, -dv.mm(3), x, L + dv.mm(3), dash=g.AXIS)
    yb = dv.y(0)
    g.dim_h(dv.x(0), dv.x(W), yb, yb + 8, num(W))
    g.dim_h(dv.x(0), dv.x(bms[0]), dv.y(L), dv.y(L) - 6, num(bms[0]))
    g.dim_v(dv.y(L), yb, dv.x(W), dv.x(W) + 8, num(L))
    note = "гиб 90°, R%s внутр." % num(c["r"])
    lo, hi = (0, bms[0]) if angles else (bms[0], bms[1])
    if g.tlen(note, 2.8) < (hi - lo) / scd - 4:
        g.text(dv.x((lo + hi) / 2.0), dv.y(L / 2.0) + 1, note, h=2.8, align="c")
    else:
        g.text(dv.x((lo + hi) / 2.0) + 1, dv.y(L / 2.0), note, h=2.8, rot=90, align="c")
    if angles:
        g.text(dv.x(W) - 1.5, dv.y(L / 2.0), "к шву", h=2.5, rot=90, align="c")
    return dv


def detail_rib(geo, steel, box, kx=True):
    """Поз. 2: торцевое ребро — контур, размеры, фаски, дуга; заметки под видом."""
    rib, S = geo["rib"], geo["S"]
    w, edge, mid = rib["w"], rib["edge"], rib["mid"]
    x0, y0, x1, y1 = box
    sc = pick(w, edge, x1 - x0 - 30, y1 - y0 - 62)
    ox = x0 + 14 + ((x1 - x0 - 30) - w / sc) / 2.0
    base = y0 + 14 + edge / sc + 6
    rv_ = View(ox, base, sc)
    g.text((x0 + x1) / 2.0, y0 + 4, "Поз. 2. Ребро торцевое, 2 шт (%s)" % lab(sc), h=3.5, align="c")
    rv_.poly(rib_pts(rib, 0.0, 0.0))
    yb = rv_.y(0)
    g.dim_h(rv_.x(0), rv_.x(w), yb, yb + 8, num(w))
    g.dim_v(rv_.y(edge), yb, rv_.x(0), rv_.x(0) - 8, num(edge))
    g.dim_v(rv_.y(mid), yb, rv_.x(w / 2.0), rv_.x(w / 2.0), num(mid))
    # Дуга — выноска вверх-влево над деталью (над размером высоты); фаска — внутрь ребра.
    xr = w * 0.25
    yr = min(edge, rib["cy"] - math.sqrt(rib["R"] ** 2 - (xr - w / 2.0) ** 2))
    g.shelf(*rv_.p(xr, yr), rv_.x(w * 0.12), rv_.y(edge) - 6, "R%s" % num(rib["R"]), h=3, dot=False)
    clab = "%s×45°" % num(rib["ch"])
    if w / sc / 2.0 - 6 > g.tlen(clab, 3) + 2:        # широкое ребро — подпись внутри, мимо оси
        g.shelf(*rv_.p(w - rib["ch"] / 2.0, rib["ch"] / 2.0), rv_.x(w) - 4, yb - 5, clab, h=3, dot=False)
    else:                                               # узкое — снаружи справа, над размером ширины
        g.shelf(*rv_.p(w - rib["ch"] / 2.0, rib["ch"] / 2.0), rv_.x(w) + 3, yb - 8, clab, h=3, dot=False)
    cx, y = (x0 + x1) / 2.0, yb + 16
    notes = ["Лист %s %s, вырезать по контуру (DXF)." % (num(S), steel),
             "Фаски нижних углов %s×45° (S + %s), 2 места." % (num(rib["ch"]), rv.RIB_CHAMFER_ADD),
             "Ставить на дно корпуса в %s мм от торца." % num(rib["offset"]),
             ("Верх — R%s от оси трубы, ниже хомута на %s мм." % (num(rib["R"]), num(rv.RIB_CLEARANCE))
              if kx else "Верх — R%s, концентрично трубе (касание)." % num(rib["R"])),
             "Ширина — B − 2S − %s мм (зазор по ширине)." % num(geo["B"] - 2 * S - w)]
    for t in notes:
        g.text(cx, y, t, h=3, align="c")
        y += 5
    return rv_


def corpus_dxf(geo, path):
    """DXF корпуса: развёртка U (или уголка), риски гибов (BEND), разметка рёбер S…2S (MARK)."""
    c, S, L = geo["corpus"], geo["S"], geo["L"]
    W = c["angle"] if c["angles"] else c["total"]
    bms = [c["bend_mark"]] if c["angles"] else [c["bend_mark"], W - c["bend_mark"]]
    d = Dxf()
    d.poly([(0, 0), (W, 0), (W, L), (0, L)])
    for x in bms:
        d.line(x, 1, x, 1 + rv.MARK_LEN, "BEND")
        d.line(x, L - 1, x, L - 1 - rv.MARK_LEN, "BEND")
    off = geo["rib"]["offset"]
    for y in (off, off + S, L - off, L - off - S):
        d.hline_broken(y, 1, W - 1, bms)
    return d.write(path)


def rib_dxf(geo, path):
    """DXF ребра: фаски и дуга (ARC), метка середины дуги (MARK)."""
    rib = geo["rib"]
    w, ch, R, cy, edge = rib["w"], rib["ch"], rib["R"], rib["cy"], rib["edge"]
    d = Dxf()
    d.poly([(w, edge), (w, ch), (w - ch, 0), (ch, 0), (0, ch), (0, edge)], close=False)
    t = math.degrees(math.asin((w / 2.0) / R))
    if rib["clipped"]:          # дуга ниже верха стенки не дошла — верх по стенке, дуга посередине
        xi = math.sqrt(R * R - (cy - edge) ** 2)
        t = math.degrees(math.asin(xi / R))
        d.line(0, edge, w / 2.0 - xi, edge)
        d.line(w / 2.0 + xi, edge, w, edge)
    d.arc(w / 2.0, cy, R, 270 - t, 270 + t)
    mid = cy - R
    d.line(w / 2.0, mid - 0.5, w / 2.0, mid - 0.5 - rv.MARK_LEN, "MARK")
    return d.write(path)


def checks_table(checks):
    return {k: dict(value=v[0], ref=v[1], ok=bool(v[2])) for k, v in checks.items()}


# ─── Сборка листов ───────────────────────────────────────────────────────
def draw(geo, steel, out_dir):
    """Рисует 219-КХ-А12: PDF (2 листа), PNG листов, DXF деталей. Возвращает пути и состав DXF."""
    dn, exe, mark = geo["dn"], geo["exe"], geo["mark"]
    A, R, Ro = geo["axis"], geo["R"], geo["Ro"]
    B, S, h1, L = geo["B"], geo["S"], geo["h1"], geo["L"]
    c, cl, rib = geo["corpus"], geo["clamp"], geo["rib"]
    f, cs, B1, M = cl["f"], cl["S"], cl["B1"], cl["M"]
    bd, bl = geo["bolt"]["d"], geo["bolt"]["l"]
    nh, hk, hx = NUT_H[bd], HEAD_K[bd], HEX_S[bd]
    angles = c["angles"]
    code = "ОПР.%s" % mark
    parts = {p["key"]: p for p in geo["parts"]}

    g.new_sheet()
    # ── вид вдоль оси трубы ──
    top_nat = max(A + Ro, A - f - cs + bl)
    SCF = pick(max(B1, B), top_nat, 110, BASE_Y - 26 - 28)
    fv = View(105, BASE_Y, SCF)
    g.text(105, 22, "Вид вдоль оси трубы (%s)" % lab(SCF), h=3.5, align="c")
    g.text(105, 27.5, "труба Ø%s показана условно" % dn, h=3, align="c")
    fv.circle(0, A, R, lw=g.THIN, dash=g.AXIS)          # труба условно
    fv.line(-Ro - fv.mm(3), A, Ro + fv.mm(3), A, dash=g.AXIS)
    fv.line(0, -fv.mm(2), 0, top_nat + fv.mm(4), dash=g.AXIS)
    corpus_section(fv, B, h1, S, c["r"], seam=angles)
    fv.poly(rib_pts(rib, S), w=g.THIN)                   # торцевое ребро за торцом корпуса
    fv.poly(clamp_pts(cl, A, lower=True))
    fv.poly(clamp_pts(cl, A, lower=False))
    for x in (-M / 2.0, M / 2.0):
        bolt_front(fv, x, A, cl, bd, bl)
    yb = fv.y(0)
    xl, xr = fv.x(-B / 2.0), fv.x(B / 2.0)
    g.dim_h(xl, xr, yb, yb + 8, num(B))
    ytop = fv.y(top_nat)
    g.dim_h(fv.x(-B1 / 2.0), fv.x(B1 / 2.0), fv.y(A + f + cs), ytop - 14, num(B1))
    g.dim_h(fv.x(-M / 2.0), fv.x(M / 2.0), fv.y(A + f + cs + nh), ytop - 6, num(M))
    # Высоты — слева: h до низа трубы (ближе), h1 стенки (дальше). Справа — только выноски.
    g.dim_v(fv.y(geo["pipe_bottom"]), yb, xl, xl - 8, num(geo["h"]))
    g.dim_v(fv.y(h1), yb, xl, xl - 16, num(h1))
    y2 = BASE_Y - 2.5
    y1 = min(fv.y(h1 * 0.6), y2 - 7)
    lead(fv, B / 2.0, fv.sc * (BASE_Y - y1) - fv.mm(2), 0, 0, "1", to=(xr + 10, y1))
    lead(fv, rib["w"] * 0.25, S + (rib["edge"]) * 0.25, 0, 0, "2", to=(xr + 10, y2))
    lead(fv, -B1 / 2.0 + fv.mm(1.5), A - f - cs / 2.0, -6, 8, "3")         # конец нижней лапки
    lead(fv, M / 2.0, A - f - cs - hk / 2.0, 14, 8, "4")
    lead(fv, M / 2.0 + hx / 2.0, A + f + cs + nh / 2.0, 14, -8, "5")

    # ── вид сбоку: корпус L, хомуты у торцов (заподлицо), рёбра на S от торцов ──
    SCS = pick(L, top_nat, 88, BASE_Y - 26 - 22)
    sv = View(210, BASE_Y, SCS)
    m = cl["m"]
    g.text(sv.x(L / 2.0), 22, "Вид сбоку (%s)" % lab(SCS), h=3.5, align="c")
    sv.poly([(0, 0), (L, 0), (L, h1), (0, h1)])
    sv.line(0, S, L, S, dash=g.HIDDEN)
    off = rib["offset"]
    for x0 in (off, L - off - S):
        sv.poly([(x0, S), (x0 + S, S), (x0 + S, rib["edge_abs"]), (x0, rib["edge_abs"])], w=g.THIN, dash=g.HIDDEN)
    ext = sv.mm(4)
    sv.line(-ext, A, L + ext, A, dash=g.AXIS)
    sv.line(-ext, A - R, L + ext, A - R, w=g.THIN, dash=g.AXIS)
    sv.line(-ext, A + R, L + ext, A + R, w=g.THIN, dash=g.AXIS)
    for x0 in (0, L - m):
        sv.poly([(x0, h1), (x0 + m, h1), (x0 + m, A - f), (x0, A - f)])            # нижний: от стенки до лапки
        sv.line(x0, A - f - cs, x0 + m, A - f - cs, w=g.MAIN)
        sv.poly([(x0, A + f), (x0 + m, A + f), (x0 + m, A + Ro), (x0, A + Ro)])     # верхний
        sv.line(x0, A + f + cs, x0 + m, A + f + cs, w=g.MAIN)
        xc = x0 + m / 2.0
        sv.poly([(xc - hx / 2.0, A - f - cs), (xc + hx / 2.0, A - f - cs), (xc + hx / 2.0, A - f - cs - hk),
                 (xc - hx / 2.0, A - f - cs - hk)])
        sv.poly([(xc - hx / 2.0, A + f + cs), (xc + hx / 2.0, A + f + cs), (xc + hx / 2.0, A + f + cs + nh),
                 (xc - hx / 2.0, A + f + cs + nh)])
        sv.poly([(xc - bd / 2.0, A - f), (xc - bd / 2.0, A + f)], close=False)
        sv.poly([(xc + bd / 2.0, A - f), (xc + bd / 2.0, A + f)], close=False)
    yb = sv.y(0)
    g.dim_h(sv.x(0), sv.x(L), yb, yb + 8, num(L))
    g.dim_h(sv.x(0), sv.x(m), sv.y(A + Ro), sv.y(A + Ro) - 6, num(m), outside=True, side="left")
    g.dim_v(sv.y(A + f), sv.y(A - f), sv.x(0), sv.x(0) - 8, num(2 * f), outside=True, side="bottom")

    # ── спецификация ──
    corpus_name = ("Корпус — уголок гнутый, лист %s %s" if angles else "Корпус гнутый — лист %s %s") % (num(S), steel)
    rows = [
        ("1", (corpus_name,), str(parts["corpus"]["qty"]), g.num(parts["corpus"]["unit_mass"], 2)),
        ("2", ("Ребро торцевое — лист %s %s" % (num(S), steel),), "2", g.num(parts["rib"]["unit_mass"], 2)),
        ("3", ("Полухомут — лист %s %s" % (num(cs), steel),), "4", g.num(parts["clamp"]["unit_mass"], 2)),
        ("4", ("Болт М%s×%s ГОСТ 7798-70" % (bd, bl),), "4", g.num(parts["bolt"]["unit_mass"], 3)),
        ("5", ("Гайка М%s ГОСТ 5915-70" % bd,), "4", g.num(parts["nut"]["unit_mass"], 3)),
    ]
    g.text(TT_X, 22, "Спецификация", h=3.5)
    g.table(TT_X, 25, [("Поз.", 10), ("Наименование", 72), ("Кол.", 11), ("Масса\n1 шт, кг", 17)], rows, 9, 7,
            hdr_size=2.5, size=3)
    pipe_h = geo["h"] if geo["h_to"] == "pipe" else geo["h"] + cs
    tt = [
        "1. Изготовить по ОСТ 36-146-88, тип КХ, исполнение %s, Дн %s. %s. Детали поз. 1–3 — сталь %s."
        % (exe, dn, rv.RULES_TITLE, steel),
        ("2. Корпус поз. 1 — два гнутых уголка, сварить встык по оси дна (ГОСТ 14771-76-С2). "
         if angles else "2. Корпус поз. 1 — гнутый. ") +
        "Гибы 90°, R%s внутр. (1,5S)." % num(c["r"]),
        "3. Рёбра поз. 2 — в %s мм от торцов корпуса, сварка ГОСТ 14771-76-Т3, катет %s. Нижний полухомут "
        "поз. 3 к кромкам стенок — Т1, катет %s." % (num(rib["offset"]), num(S), num(S)),
        "4. Поз. 4, 5 — покупные. Затяжка болтов — при монтаже на трубе.",
        "5. Высота до низа трубы %s мм, до низа хомута %s мм; стенка корпуса %s мм."
        % (num(pipe_h), num(pipe_h - cs), num(h1)),
        "6. Развёртки — нейтральный слой K = %s; риски гибов и разметка рёбер — в DXF (слои BEND, MARK)."
        % rv.fmt(rv.K),
        "7. Масса по деталям %s кг (по ОСТ — не более %s кг)." % (g.num(geo["mass"], 1), g.num(geo["mass_ost"], 1)),
        "8. Допущения — открытые вопросы к Игорю:",
    ] + ["   – " + a for a in geo["assumptions"]]
    text_block(TT_X, 25 + 9 + 7 * len(rows) + 9, 233, TT_W, tt)
    stamp(code + " СБ", "Опора корпусная хомутовая", "%s ОСТ 36-146-88" % mark, g.num(geo["mass"], 1), lab(SCF),
          sheets=2)

    # ── лист 2: детали ──
    g.next_sheet(code, 2, "")
    detail_corpus(geo, steel, (20, 18, 140, 140), (146, 18, 306, 140))
    detail_rib(geo, steel, (310, 18, 414, 175), kx=True)
    # Поз. 3 — полухомут и развёртка
    SCC = pick(B1, Ro, 136, 46)
    cv = View(118, 228, SCC)
    g.text(118, 162, "Поз. 3. Полухомут, 4 шт (%s)" % lab(SCC), h=3.5, align="c")
    cv.poly(clamp_pts(cl, 0, lower=False))
    cv.line(-B1 / 2.0 - cv.mm(3), 0, B1 / 2.0 + cv.mm(3), 0, dash=g.AXIS)
    cv.line(0, -cv.mm(2), 0, Ro + cv.mm(3), dash=g.AXIS)
    for x in (-M / 2.0, M / 2.0):
        cv.line(x, f - cv.mm(2), x, f + cs + cv.mm(2), dash=g.AXIS)
    yb = cv.y(0)
    g.dim_h(cv.x(-B1 / 2.0), cv.x(B1 / 2.0), cv.y(f), yb + 14, num(B1))
    g.dim_h(cv.x(-M / 2.0), cv.x(M / 2.0), cv.y(f), yb + 7, num(M))
    arc_top = cv.y(Ro) - 5
    lug = cv.y(f + cs) - 7
    lead(cv, -R * math.cos(math.radians(55)), R * math.sin(math.radians(55)), 0, 0, "R%s внутр." % num(R), h=3,
         dot=False, to=(cv.x(-Ro) - 4, arc_top))
    lead(cv, (R + cs) * math.cos(math.radians(50)), (R + cs) * math.sin(math.radians(50)), 0, 0,
         "S%s, ширина %s" % (num(cs), num(m)), h=3, dot=False, to=(cv.x(Ro) + 4, arc_top))
    lead(cv, M / 2.0 + cl["d"] / 4.0, f + cs, 0, 0, "2 отв. Ø%s" % num(cl["d"]), h=3, dot=False,
         to=(cv.x(B1 / 2.0) + 5, lug))
    lead(cv, -B1 / 2.0 + cv.mm(2), f, 0, 0, "f=%s от оси" % num(f), h=3, dot=False, to=(cv.x(-B1 / 2.0) - 5, lug))
    g.text(118, yb + 23, "Лапки: гиб R%s внутр.; дуга R%s внутр." % (num(cl["r"]), num(R)), h=3, align="c")

    dev = cl["total"]
    PSC = pick(dev, m, 165, 34)
    pv = View(234 + (165 - dev / PSC) / 2.0, 236, PSC)
    pv.poly([(0, 0), (dev, 0), (dev, m), (0, m)])
    for x in (cl["hole"], dev - cl["hole"]):
        pv.circle(x, m / 2.0, cl["d"] / 2.0)
        pv.line(x - pv.mm(4), m / 2.0, x + pv.mm(4), m / 2.0, dash=g.AXIS)
        pv.line(x, m / 2.0 - pv.mm(4), x, m / 2.0 + pv.mm(4), dash=g.AXIS)
    for x in (cl["bend_mark"], dev - cl["bend_mark"]):
        pv.line(x, -pv.mm(2), x, m + pv.mm(2), dash=g.AXIS)
    pv.line(dev / 2.0, 0, dev / 2.0, m, w=g.THIN)
    yb = pv.y(0)
    ytop = pv.y(m)
    g.text(pv.x(dev / 2.0), ytop - 22, "Развёртка поз. 3 (%s) — лист %s %s" % (lab(PSC), num(cs), steel), h=3.5,
           align="c")
    g.dim_h(pv.x(0), pv.x(dev), yb, yb + 8, num(dev))
    g.dim_h(pv.x(0), pv.x(cl["hole"]), ytop, ytop - 5, num(cl["hole"]), outside=True, side="left")
    # Ось гиба лапки — от правого торца (слева размер отверстия), выноска отверстий выше обоих.
    g.dim_h(pv.x(dev - cl["bend_mark"]), pv.x(dev), ytop, ytop - 5, num(cl["bend_mark"]),
            outside=(cl["bend_mark"] / PSC < g.tlen(num(cl["bend_mark"]), 3.5) + 2), side="right")
    g.dim_v(ytop, yb, pv.x(dev), pv.x(dev) + 7, num(m), outside=True, side="bottom")
    g.dim_v(pv.y(m / 2.0), yb, pv.x(0), pv.x(0) - 7, num(m / 2.0), outside=True, side="bottom")
    # Выноска от левого отверстия вправо-вверх: мимо выносных линий размеров у обоих торцов.
    g.shelf(*pv.p(cl["hole"] + cl["d"] / 2.0 * 0.7, m / 2.0 + cl["d"] / 2.0 * 0.7),
            pv.x(cl["hole"]) + 22, ytop - 12, "2 отв. Ø%s" % num(cl["d"]), h=3)
    g.text(pv.x(dev / 2.0), yb + 17, "Отверстия — до гиба, в %s от торцов (межосевое после гиба %s). Риски гибов"
           % (num(cl["hole"]), num(M)), h=2.8, align="c")
    g.text(pv.x(dev / 2.0), yb + 21.5, "— штрихпунктир (в DXF по 10 мм у кромок), середина полосы — вершина дуги.",
           h=2.8, align="c")

    base = os.path.join(out_dir, mark)
    pdf = base + ".pdf"
    pngs = save(pdf, base)

    files = []
    n1 = "Корпус уголок" if angles else "Корпус"
    p = corpus_dxf(geo, os.path.join(out_dir, dxf_name(mark, 1, n1, S, parts["corpus"]["qty"])))
    files.append(dict(file=p, pos="1", name=("Корпус — уголок гнутый" if angles else "Корпус гнутый"),
                      thickness=S, qty=parts["corpus"]["qty"]))
    p = rib_dxf(geo, os.path.join(out_dir, dxf_name(mark, 2, "Ребро", S, 2)))
    files.append(dict(file=p, pos="2", name="Ребро торцевое", thickness=S, qty=2))
    d = Dxf()
    d.poly([(0, 0), (dev, 0), (dev, m), (0, m)])
    for x in (cl["hole"], dev - cl["hole"]):
        d.circle(x, m / 2.0, cl["d"] / 2.0)
    for x in (cl["bend_mark"], dev - cl["bend_mark"]):
        d.risk(x, m)
    d.line(dev / 2.0, 0.5, dev / 2.0, m - 0.5, "MARK")
    p = d.write(os.path.join(out_dir, dxf_name(mark, 3, "Полухомут", cs, 4)))
    files.append(dict(file=p, pos="3", name="Полухомут", thickness=cs, qty=4))
    return dict(pdf=pdf, png=pngs, dxf=files)
