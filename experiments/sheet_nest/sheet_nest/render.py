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


def png_model(raw, path, title="", px_per_mm=None, cols=6, moves=None):
    """Картинка по разобранной программе (spec_rebuild): холостые переходы — от точки врезки с учётом sp (у групп
    общего реза замкнутый контур режется не от вершины 0 — расшифровщик отчётов этого не знает). moves — по раскладкам
    [(откуда, куда, вектор risk)] в порядке программы (последний — возврат в ноль): опасные переходы своими цветами,
    возврат — пунктиром; переходы сверяются с программой (не совпали — рисуются как обычные)."""
    from PIL import Image, ImageDraw
    from .libpath import vn
    from . import geom as G
    M = vn.spec_rebuild.decompile(raw)
    bn = {b["name"]: b for b in M["blocks"]}
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
    if moves:
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        x, y = pad, 0
        for col, w, txt in ((C_PART, 3, "над освобождённой деталью / язычком"), (C_HOLE, 2, "над отверстием ≥ 10 мм"),
                            (C_NEAR, 2, "впритирку (< 5 мм)"), (C_IDLE, 1, "холостой"), (C_RET, 1, "возврат в ноль")):
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
        if col == C_RET:
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
        pos, idle, ng, k, danger = (0.0, 0.0), 0.0, 0, 0, 0
        segs, shapes = [], []
        for ins in r["inserts"]:
            ng += ins["ref"][0] == "NestGroup"
            for s in bn[ins["block"]]["shapes"]:
                a, b = G.ends(s)
                style = (C_IDLE, 1)
                if mv and k < len(mv) and math.dist(mv[k][0], pos) < 0.01 and math.dist(mv[k][1], a) < 0.01:
                    style = _move_style(mv[k][2])
                    danger += style[0] in (C_PART, C_HOLE)
                segs.append((P(pos), P(a), style))
                idle += math.dist(pos, a)
                shapes.append(s)
                pos = b
                k += 1
        for s in shapes:
            pts = G.points(s, 0.5)
            if G.is_closed(s):
                pts = pts + pts[:1]
            col = (40, 90, 210) if s["layer"] == 2 else ((150, 70, 0) if s.get("coedge") else (20, 20, 20))
            dr.line([P(p) for p in pts], fill=col, width=1)
        for a, b, (col, w) in sorted(segs, key=lambda v: v[2][1]):        # опасные — поверх
            dr.line([a, b], fill=col, width=w)
        if mv and len(mv) == k + 1 and math.dist(mv[-1][0], pos) < 0.01:   # возврат в ноль: над деталями — толще
            _dashed(dr, P(pos), P(mv[-1][1]), C_RET, 1 if _move_style(mv[-1][2])[0] == C_IDLE else 2)
        x, y = P((0, 0)); dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(0, 160, 60))
        dr.text((ox, oy - top + 6), "№%d  ×%d лист.  %g×%g" % (r["index"], r["plate_amount"], pl["W"], pl["L"]), fill=(0, 0, 0), font=Fb)
        # подпись — строками (в одну строку с общим резом налезала на соседнюю раскладку: 6 в ряд при 0,2 пикс/мм)
        dr.text((ox, oy - top + 26), "холостой %.1f м%s" % (idle / 1000, ("  · групп общего реза %d" % ng) if ng else ""),
                fill=(60, 60, 60), font=F)
        if mv:
            dr.text((ox, oy - top + 46), "опасных переходов %d" % danger, fill=C_PART if danger else (60, 60, 60), font=F)
    img.save(path)
    return path
