# -*- coding: utf-8 -*-
"""Картинка раскладок по прочитанной программе: рез — чёрный, гравировка — синий, холостые переходы — красный
(по классам опасности risk — своими цветами, возврат в ноль — пунктир), старт головки — зелёная точка. Масштаб общий
для всех раскладок."""
import math


def _font(size, bold=False):
    from PIL import ImageFont
    for path in (("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf"),
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else "")):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def png(ctx, path, title="", px_per_mm=0.2, cols=6):
    from PIL import Image, ImageDraw
    from .libpath import vn
    LR = vn.lxds_reader
    lays = ctx["lays"]
    Wm = max(d["_plate"]["x1"] - d["_plate"]["x0"] for d in lays)
    Lm = max(d["_plate"]["y1"] - d["_plate"]["y0"] for d in lays)
    W, H = int(Wm * px_per_mm), int(Lm * px_per_mm)
    cols = min(cols, len(lays))
    pad, top, head = 24, 58, 50 if title else 0
    rows = (len(lays) + cols - 1) // cols
    img = Image.new("RGB", (cols * (W + pad) + pad, head + rows * (H + top + pad) + pad), "white")
    dr = ImageDraw.Draw(img)
    F, Fb = _font(15), _font(16, True)
    if title:
        dr.text((pad, 14), title, fill=(0, 0, 0), font=_font(20, True))
    for n, d in enumerate(lays):
        pl = d["_plate"]
        ox, oy = pad + (n % cols) * (W + pad), head + pad + top + (n // cols) * (H + top + pad)
        h = (pl["y1"] - pl["y0"]) * px_per_mm
        P = lambda p: (ox + (p[0] - pl["x0"]) * px_per_mm, oy + h - (p[1] - pl["y0"]) * px_per_mm)
        dr.rectangle([ox, oy, ox + (pl["x1"] - pl["x0"]) * px_per_mm, oy + h], outline=(150, 150, 150), fill=(250, 250, 247))
        pos = (pl["x0"], pl["y0"])
        for e in d["_ents"]:
            a = e["pts"][0]
            dr.line([P(pos), P(a)], fill=(225, 45, 30), width=1)
            dr.line([P(p) for p in LR.points(e, 8)], fill=(40, 90, 210) if e["layer"] == 2 else (20, 20, 20), width=1)
            pos = e["pts"][0] if e["closed"] else e["pts"][-1]
        x, y = P((pl["x0"], pl["y0"])); dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(0, 160, 60))
        names = ", ".join("%s×%d" % (p["name"], p["qty"]) for p in d["parts"])
        dr.text((ox, oy - top + 6), "№%d  ×%d лист.  %g×%g" % (d["index"], d["sheets"], pl["x1"] - pl["x0"], pl["y1"] - pl["y0"]), fill=(0, 0, 0), font=Fb)
        dr.text((ox, oy - top + 26), "холостой %.1f м" % d["idle_m"], fill=(60, 60, 60), font=F)
    img.save(path)
    return path


# цвета холостых переходов по классам опасности (risk.CLASSES), от сильного к слабому
C_PART = (215, 0, 0)          # над освобождённой деталью или язычком — ярко-красный, толще
C_HOLE = (140, 40, 190)       # над вырезанным отверстием (≥ 10 мм) — фиолетовый
C_NEAR = (245, 140, 0)        # впритирку к освобождённой детали — оранжевый
C_IDLE = (238, 160, 150)      # обычный холостой — тонкий светло-красный
C_RET = (120, 120, 120)       # возврат в ноль (настройка станка, в программе его нет) — серый пунктир
C_BRIDGE = (0, 125, 70)       # общий контур моста (детали с перемычками) — тёмно-зелёный, толще
C_FILL = (0, 120, 160)        # добивка остатков листа (складские позиции) — контуры сине-зелёные
C_FILL_BG = (205, 236, 242)   # … и бледная заливка детали


def _move_style(v):
    from . import risk as RK
    if v[RK.TONGUE] or v[RK.SMALLP] or v[RK.PART]:
        return C_PART, 3
    if v[RK.HOLE]:
        return C_HOLE, 2
    if v[RK.NEARP]:
        return C_NEAR, 2
    return C_IDLE, 1


def _dashed(dr, a, b, fill, width=1, dash=6.0, gap=4.0):
    L = math.dist(a, b)
    if L < 1e-6:
        return
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    t = 0.0
    while t < L:
        e = min(L, t + dash)
        dr.line([(a[0] + ux * t, a[1] + uy * t), (a[0] + ux * e, a[1] + uy * e)], fill=fill, width=width)
        t = e + gap


def png_model(raw, path, title="", px_per_mm=None, cols=6, moves=None, fill_names=None):
    """Картинка по разобранной программе (spec_rebuild): холостые переходы — от точки врезки с учётом sp (у групп
    общего реза замкнутый контур режется не от вершины 0 — расшифровщик отчётов этого не знает). moves — по раскладкам
    [(откуда, куда, вектор risk)] в порядке программы (последний — возврат в ноль): опасные переходы своими цветами,
    возврат — пунктиром; переходы сверяются с программой (не совпали — рисуются как обычные). fill_names — имена деталей
    добивки остатков листа: они залиты бледно, контуры — своим цветом (C_FILL), в легенде — «добивка»."""
    from PIL import Image, ImageDraw
    from . import geom as G
    from .write_lxds import decompile_free, FREE, BAD_NAME
    M = decompile_free(raw)                             # вставки мостов (без NestPart) пакет сам не разбирает
    bn = {b["name"]: b for b in M["blocks"]}
    fills = {n.translate(BAD_NAME) for n in fill_names or ()}
    fill_h = {p["handle"] for p in M["parts"] if p["name"] in fills}     # NestPart деталей добивки
    plates = {p["handle"]: p for p in M["plates"]}
    res = M["results"]
    Wm = max(plates[r["plate"]]["W"] for r in res); Lm = max(plates[r["plate"]]["L"] for r in res)
    cols = min(cols, len(res))
    if px_per_mm is None:                               # мало раскладок — крупнее (ширина картинки ~1200 px)
        px_per_mm = max(0.2, min(1.0, 1200.0 / (cols * Wm)))
    W, H = int(Wm * px_per_mm), int(Lm * px_per_mm)
    pad, top = 24, (78 if moves else 58)                # с опасными переходами — третья строка подписи раскладки
    F, Fb = _font(15), _font(16, True)
    width = cols * (W + pad) + pad
    legend = []                                         # (x, y, цвет, толщина, текст) — с переносом по ширине
    if moves or fill_h:
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        x, y = pad, 0
        items = ((C_PART, 3, "над освобождённой деталью / язычком"), (C_HOLE, 2, "над отверстием ≥ 10 мм"),
                 (C_NEAR, 2, "впритирку (< 5 мм)"), (C_IDLE, 1, "холостой"), (C_RET, 1, "возврат в ноль")) if moves else ()
        if fill_h:
            items += ((C_FILL, 2, "добивка (складские позиции)"),)
        for col, w, txt in items:
            tw = int(probe.textlength(txt, font=F)) if hasattr(probe, "textlength") else 8 * len(txt)
            if x > pad and x + 40 + tw > width - pad:
                x, y = pad, y + 22
            legend.append((x, y, col, w, txt))
            x += 60 + tw
    head = (50 if title else 8) + ((legend[-1][1] + 26) if legend else 0)
    rows = (len(res) + cols - 1) // cols
    img = Image.new("RGB", (width, head + rows * (H + top + pad) + pad), "white")
    dr = ImageDraw.Draw(img)
    if title:
        dr.text((pad, 14), title, fill=(0, 0, 0), font=_font(20, True))
    for x, y, col, w, txt in legend:
        y += 50 if title else 8
        if col == C_FILL:
            dr.rectangle([x, y + 2, x + 34, y + 14], fill=C_FILL_BG, outline=C_FILL, width=2)
        elif col == C_RET:
            _dashed(dr, (x, y + 8), (x + 34, y + 8), col, 2)
        else:
            dr.line([(x, y + 8), (x + 34, y + 8)], fill=col, width=w)
        dr.text((x + 40, y), txt, fill=(40, 40, 40), font=F)
    for n, r in enumerate(res):
        pl = plates[r["plate"]]
        ox, oy = pad + (n % cols) * (W + pad), head + pad + top + (n // cols) * (H + top + pad)
        h = pl["L"] * px_per_mm
        P = lambda p: (ox + p[0] * px_per_mm, oy + h - p[1] * px_per_mm)
        dr.rectangle([ox, oy, ox + pl["W"] * px_per_mm, oy + h], outline=(150, 150, 150), fill=(250, 250, 247))
        mv = moves[n] if moves and n < len(moves) else None
        pos, idle, ng, nb, k, danger = (0.0, 0.0), 0.0, 0, 0, 0, 0
        segs, shapes = [], []
        nf = 0
        for ins in r["inserts"]:
            ng += ins["ref"][0] == "NestGroup"
            nb += ins["ref"] == FREE
            blk = bn[ins["block"]]["shapes"]
            bo = max((x for x in blk if G.is_closed(x)), key=G.area, default=None) if ins["ref"] == FREE else None
            fo = None
            if ins["ref"][0] == "NestPart" and ins["ref"][1] in fill_h:     # добивка: бледная заливка под контурами
                nf += 1
                fo = max((x for x in blk if G.is_closed(x) and x["layer"] == 1), key=G.area, default=None)
                if fo is not None:
                    dr.polygon([P(p) for p in G.points(fo, 0.5)], fill=C_FILL_BG)
            for s in blk:
                a, b = G.ends(s)
                style = (C_IDLE, 1)
                if mv and k < len(mv) and math.dist(mv[k][0], pos) < 0.01 and math.dist(mv[k][1], a) < 0.01:
                    style = _move_style(mv[k][2])
                    danger += style[0] in (C_PART, C_HOLE)
                segs.append((P(pos), P(a), style))
                idle += math.dist(pos, a)
                shapes.append((s, s is bo, fo is not None))
                pos = b
                k += 1
        for s, bridge, filler in shapes:
            pts = G.points(s, 0.5)
            if G.is_closed(s):
                pts = pts + pts[:1]
            col = (40, 90, 210) if s["layer"] == 2 else ((150, 70, 0) if s.get("coedge") else C_BRIDGE if bridge else
                                                          C_FILL if filler else (20, 20, 20))
            dr.line([P(p) for p in pts], fill=col, width=2 if bridge else 1)
            if bridge and s["kind"] == "LwPolyline":    # перемычки (прямые общего контура, по две на мост) — метка
                V = s["verts"]
                for i in range(len(V)):
                    if abs(V[i][2]) < 1e-12:
                        x, y = P(((V[i][0] + V[(i + 1) % len(V)][0]) / 2, (V[i][1] + V[(i + 1) % len(V)][1]) / 2))
                        dr.ellipse([x - 2.5, y - 2.5, x + 2.5, y + 2.5], fill=C_BRIDGE)
        for a, b, (col, w) in sorted(segs, key=lambda v: v[2][1]):        # опасные — поверх
            dr.line([a, b], fill=col, width=w)
        if mv and len(mv) == k + 1 and math.dist(mv[-1][0], pos) < 0.01:   # возврат в ноль: над деталями — толще
            _dashed(dr, P(pos), P(mv[-1][1]), C_RET, 1 if _move_style(mv[-1][2])[0] == C_IDLE else 2)
        x, y = P((0, 0)); dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(0, 160, 60))
        dr.text((ox, oy - top + 6), "№%d  ×%d лист.  %g×%g" % (r["index"], r["plate_amount"], pl["W"], pl["L"]), fill=(0, 0, 0), font=Fb)
        # подпись — строками (в одну строку с общим резом налезала на соседнюю раскладку: 6 в ряд при 0,2 пикс/мм)
        dr.text((ox, oy - top + 26), "холостой %.1f м%s%s%s" % (idle / 1000, ("  · групп общего реза %d" % ng) if ng else "",
                                                               ("  · мостов %d" % nb) if nb else "", ("  · добивка %d" % nf) if nf else ""),
                fill=(60, 60, 60), font=F)
        if mv:
            dr.text((ox, oy - top + 46), "опасных переходов %d" % danger, fill=C_PART if danger else (60, 60, 60), font=F)
    img.save(path)
    return path


def order_color(t):
    """Цвет места в порядке резки t ∈ [0, 1]: синий → голубой → зелёный → жёлтый → красный."""
    stops = [(0.0, (40, 70, 200)), (0.25, (30, 170, 220)), (0.5, (60, 180, 75)), (0.75, (240, 200, 40)), (1.0, (215, 40, 30))]
    t = min(1.0, max(0.0, t))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(int(round(a + (b - a) * f)) for a, b in zip(c0, c1))
    return stops[-1][1]


def png_order(raw, path, title="", px_per_mm=None, cols=6, strips=None, done_polys=None):
    """Порядок резки цветом (решение 14.10: «Горкой» должно быть видно): каждая вставка программы (деталь, группа общего
    реза, мост) залита цветом своего места в программе — от синего (первая) к красному (последняя), отверстия — белые.
    strips — остаток к концу резки по раскладкам (risk.end_strip): его габарит — пунктиром, узкая полоса — красным.
    done_polys — по раскладкам контуры деталей в порядке освобождения (маршрут общего реза: группа — одна вставка, а
    детали в ней освобождаются по очереди): тогда цвет — у каждой детали по её месту, вставки групп не заливаются."""
    from PIL import Image, ImageDraw
    from . import geom as G
    from .write_lxds import decompile_free
    M = decompile_free(raw)
    bn = {b["name"]: b for b in M["blocks"]}
    plates = {p["handle"]: p for p in M["plates"]}
    res = M["results"]
    Wm = max(plates[r["plate"]]["W"] for r in res); Lm = max(plates[r["plate"]]["L"] for r in res)
    cols = min(cols, len(res))
    if px_per_mm is None:
        px_per_mm = max(0.2, min(1.0, 1200.0 / (cols * Wm)))
    W, H = int(Wm * px_per_mm), int(Lm * px_per_mm)
    pad, top = 24, 78
    F, Fb = _font(15), _font(16, True)
    width = cols * (W + pad) + pad
    head = (50 if title else 8) + 30
    rows = (len(res) + cols - 1) // cols
    img = Image.new("RGB", (width, head + rows * (H + top + pad) + pad), "white")
    dr = ImageDraw.Draw(img)
    if title:
        dr.text((pad, 14), title, fill=(0, 0, 0), font=_font(20, True))
    y = (50 if title else 8)
    for j in range(200):                                 # шкала порядка
        dr.line([(pad + j, y + 4), (pad + j, y + 18)], fill=order_color(j / 199))
    dr.text((pad + 210, y + 2), "первая → последняя", fill=(40, 40, 40), font=F)
    _dashed(dr, (pad + 420, y + 11), (pad + 460, y + 11), (215, 0, 0), 2)
    dr.text((pad + 466, y + 2), "остаток к концу резки (последние 20 % деталей)", fill=(40, 40, 40), font=F)
    for n, r in enumerate(res):
        pl = plates[r["plate"]]
        ox, oy = pad + (n % cols) * (W + pad), head + pad + top + (n // cols) * (H + top + pad)
        h = pl["L"] * px_per_mm
        P = lambda p: (ox + p[0] * px_per_mm, oy + h - p[1] * px_per_mm)
        dr.rectangle([ox, oy, ox + pl["W"] * px_per_mm, oy + h], outline=(150, 150, 150), fill=(250, 250, 247))
        ins = r["inserts"]
        dp = done_polys[n] if done_polys and n < len(done_polys) else None
        if dp:                                          # детали по порядку освобождения (общий рез)
            for k, Pp in enumerate(dp):
                pts = [P(p) for p in Pp]
                if len(pts) >= 3:
                    dr.polygon(pts, fill=order_color(k / max(1, len(dp) - 1)), outline=(60, 60, 60))
        for k, i in enumerate(ins):
            col = order_color(k / max(1, len(ins) - 1))
            blk = bn[i["block"]]["shapes"]
            cl = [s for s in blk if G.is_closed(s) and s["layer"] == 1]
            big = max(cl, key=G.area, default=None)
            # с done_polys детали уже залиты своим цветом — внешние контуры только обводятся
            outer = [s for s in cl if s.get("outer") or (s is big and not dp)]
            for s in outer:
                pts = [P(p) for p in G.points(s, 0.5)]
                if len(pts) >= 3:
                    dr.polygon(pts, fill=None if dp else col, outline=(60, 60, 60))
            for s in blk:
                if any(s is o for o in outer):
                    continue
                pts = [P(p) for p in G.points(s, 0.5)]
                if G.is_closed(s) and len(pts) >= 3 and s["layer"] == 1:
                    dr.polygon(pts, fill=(255, 255, 255), outline=(60, 60, 60))
                elif len(pts) >= 2:
                    th = s.get("outer") and not dp
                    dr.line(pts + (pts[:1] if G.is_closed(s) else []), fill=col if th else (60, 60, 60), width=3 if th else 1)
        st = strips[n] if strips and n < len(strips) else None
        if st:
            x0, y0, x1, y1 = st["box"]
            c = (215, 0, 0) if st["strip"] else (90, 90, 90)
            for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
                _dashed(dr, P(a), P(b), c, 3)
        x, y_ = P((0, 0)); dr.ellipse([x - 4, y_ - 4, x + 4, y_ + 4], fill=(0, 160, 60))
        dr.text((ox, oy - top + 6), "№%d  ×%d лист.  %g×%g" % (r["index"], r["plate_amount"], pl["W"], pl["L"]), fill=(0, 0, 0), font=Fb)
        dr.text((ox, oy - top + 26), "вставок %d%s" % (len(ins), (", цвет — по деталям (%d)" % len(dp)) if dp else ""),
                fill=(60, 60, 60), font=F)
        if st:
            dr.text((ox, oy - top + 46), "остаток %.0f×%.0f мм%s" % (st["w"], st["l"], " — узкая полоса" if st["strip"] else ""),
                    fill=(215, 0, 0) if st["strip"] else (60, 60, 60), font=F)
    img.save(path)
    return path
