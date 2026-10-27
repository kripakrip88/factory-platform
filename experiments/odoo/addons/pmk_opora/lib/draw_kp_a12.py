# -*- coding: utf-8 -*-
"""Чертёж опоры КП исполнения А12 (ОСТ 36-146-88, черт. 3) по правилам в.2 (чертежи И. Бутова).

Два листа А3: 1 — сборочный (вид вдоль оси трубы, вид сбоку, спецификация, ТТ, штамп),
2 — детали (корпус в разрезе и развёртка, ребро). Корпус и ребро рисуются теми же функциями, что
у КХ (draw_kx_a12). Труба — условно: целиком, если она не шире корпуса заметно, иначе нижняя дуга
над корпусом (Дн 1420 на опоре B 500 — иначе корпус на листе мельчает до 1:15).
"""
import os

from _common import View, corpus_section, dxf_name, g, lab, lead, num, pick, pipe_runs, rv, save, stamp, text_block
from draw_kx_a12 import BASE_Y, TT_W, TT_X, corpus_dxf, detail_corpus, detail_rib, rib_dxf, rib_pts


def draw(geo, steel, out_dir):
    dn, exe, mark = geo["dn"], geo["exe"], geo["mark"]
    A, R = geo["axis"], geo["R"]
    B, S, h1, L = geo["B"], geo["S"], geo["h1"], geo["L"]
    c, rib = geo["corpus"], geo["rib"]
    angles = c["angles"]
    code = "ОПР.%s" % mark
    parts = {p["key"]: p for p in geo["parts"]}

    xlim = B / 2.0 + max(20.0, 0.06 * B)
    full = R <= xlim
    top_nat = A + R if full else max(h1, A - (R * R - xlim * xlim) ** 0.5) + 10
    half_w = max(B / 2.0, R if full else xlim)

    g.new_sheet()
    SCF = pick(2 * half_w, top_nat, 116, BASE_Y - 26 - 28)
    fv = View(105, BASE_Y, SCF)
    g.text(105, 22, "Вид вдоль оси трубы (%s)" % lab(SCF), h=3.5, align="c")
    g.text(105, 27.5, "труба Ø%s показана условно%s" % (dn, "" if full else " (низ)"), h=3, align="c")
    pipe_runs(fv, 0, A, R, xlim=None if full else xlim, lower_only=not full, dash=g.AXIS)
    if full:
        fv.line(-R - fv.mm(3), A, R + fv.mm(3), A, dash=g.AXIS)
    fv.line(0, -fv.mm(2), 0, top_nat + fv.mm(3), dash=g.AXIS)
    corpus_section(fv, B, h1, S, c["r"], seam=angles)
    fv.poly(rib_pts(rib, S), w=g.THIN)
    yb = fv.y(0)
    xl, xr = fv.x(-B / 2.0), fv.x(B / 2.0)
    g.dim_h(xl, xr, yb, yb + 8, num(B))
    g.dim_v(fv.y(geo["pipe_bottom"]), yb, xl, xl - 8, num(geo["h"]))
    g.dim_v(fv.y(h1), yb, xl, xl - 16, num(h1))
    y2 = BASE_Y - 2.5
    y1 = min(fv.y(h1 * 0.6), y2 - 7)
    lead(fv, B / 2.0, fv.sc * (BASE_Y - y1) - fv.mm(2), 0, 0, "1", to=(xr + 10, y1))
    lead(fv, rib["w"] * 0.25, S + rib["edge"] * 0.25, 0, 0, "2", to=(xr + 10, y2))

    SCS = pick(L, top_nat, 88, BASE_Y - 26 - 22)
    sv = View(210, BASE_Y, SCS)
    g.text(sv.x(L / 2.0), 22, "Вид сбоку (%s)" % lab(SCS), h=3.5, align="c")
    sv.poly([(0, 0), (L, 0), (L, h1), (0, h1)])
    sv.line(0, S, L, S, dash=g.HIDDEN)
    off = rib["offset"]
    for x0 in (off, L - off - S):
        sv.poly([(x0, S), (x0 + S, S), (x0 + S, rib["edge_abs"]), (x0, rib["edge_abs"])], w=g.THIN, dash=g.HIDDEN)
    ext = sv.mm(4)
    sv.line(-ext, A - R, L + ext, A - R, w=g.THIN, dash=g.AXIS)
    if full:
        sv.line(-ext, A, L + ext, A, dash=g.AXIS)
        sv.line(-ext, A + R, L + ext, A + R, w=g.THIN, dash=g.AXIS)
    yb = sv.y(0)
    g.dim_h(sv.x(0), sv.x(L), yb, yb + 8, num(L))

    corpus_name = ("Корпус — уголок гнутый, лист %s %s" if angles else "Корпус гнутый — лист %s %s") % (num(S), steel)
    rows = [("1", (corpus_name,), str(parts["corpus"]["qty"]), g.num(parts["corpus"]["unit_mass"], 2)),
            ("2", ("Ребро торцевое — лист %s %s" % (num(S), steel),), "2", g.num(parts["rib"]["unit_mass"], 2))]
    g.text(TT_X, 22, "Спецификация", h=3.5)
    g.table(TT_X, 25, [("Поз.", 10), ("Наименование", 72), ("Кол.", 11), ("Масса\n1 шт, кг", 17)], rows, 9, 7,
            hdr_size=2.5, size=3)
    tt = [
        "1. Изготовить по ОСТ 36-146-88, тип КП, исполнение %s, Дн %s. %s. Детали — сталь %s."
        % (exe, dn, rv.RULES_TITLE, steel),
        ("2. Корпус поз. 1 — два гнутых уголка, сварить встык по оси дна (ГОСТ 14771-76-С2). "
         if angles else "2. Корпус поз. 1 — гнутый. ") + "Гибы 90°, R%s внутр. (1,5S)." % num(c["r"]),
        "3. Рёбра поз. 2 — в %s мм от торцов корпуса, сварка ГОСТ 14771-76-Т3, катет %s. Приварка к трубе — "
        "при монтаже." % (num(rib["offset"]), num(S)),
        "4. Высота до низа трубы %s мм; стенка корпуса %s мм (по ОСТ %s)." % (num(geo["h"]), num(h1),
                                                                             num(geo["h1_ost"])),
        "5. Развёртки — нейтральный слой K = %s; риски гибов и разметка рёбер — в DXF (слои BEND, MARK)."
        % rv.fmt(rv.K),
        "6. Масса по деталям %s кг (по ОСТ — не более %s кг)." % (g.num(geo["mass"], 1), g.num(geo["mass_ost"], 1)),
        "7. Допущения — открытые вопросы к Игорю:",
    ] + ["   – " + a for a in geo["assumptions"]]
    text_block(TT_X, 25 + 9 + 7 * len(rows) + 9, 233, TT_W, tt)
    stamp(code + " СБ", "Опора корпусная приварная", "%s ОСТ 36-146-88" % mark, g.num(geo["mass"], 1), lab(SCF),
          sheets=2)

    g.next_sheet(code, 2, "")
    detail_corpus(geo, steel, (20, 18, 140, 268), (146, 18, 306, 268))
    detail_rib(geo, steel, (310, 18, 414, 268), kx=False)

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
    return dict(pdf=pdf, png=pngs, dxf=files)
