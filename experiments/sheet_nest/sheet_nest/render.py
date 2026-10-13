# -*- coding: utf-8 -*-
"""Картинка раскладок по прочитанной программе: рез — чёрный, гравировка — синий, холостые переходы — красный,
старт головки — зелёная точка. Масштаб общий для всех раскладок."""
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


def png_model(raw, path, title="", px_per_mm=0.2, cols=6):
    """Картинка по разобранной программе (spec_rebuild): холостые переходы — от точки врезки с учётом sp (у групп
    общего реза замкнутый контур режется не от вершины 0 — расшифровщик отчётов этого не знает)."""
    from PIL import Image, ImageDraw
    from .libpath import vn
    from . import geom as G
    M = vn.spec_rebuild.decompile(raw)
    bn = {b["name"]: b for b in M["blocks"]}
    plates = {p["handle"]: p for p in M["plates"]}
    res = M["results"]
    Wm = max(plates[r["plate"]]["W"] for r in res); Lm = max(plates[r["plate"]]["L"] for r in res)
    W, H = int(Wm * px_per_mm), int(Lm * px_per_mm)
    cols = min(cols, len(res))
    pad, top, head = 24, 58, 50 if title else 0
    rows = (len(res) + cols - 1) // cols
    img = Image.new("RGB", (cols * (W + pad) + pad, head + rows * (H + top + pad) + pad), "white")
    dr = ImageDraw.Draw(img)
    F, Fb = _font(15), _font(16, True)
    if title:
        dr.text((pad, 14), title, fill=(0, 0, 0), font=_font(20, True))
    for n, r in enumerate(res):
        pl = plates[r["plate"]]
        ox, oy = pad + (n % cols) * (W + pad), head + pad + top + (n // cols) * (H + top + pad)
        h = pl["L"] * px_per_mm
        P = lambda p: (ox + p[0] * px_per_mm, oy + h - p[1] * px_per_mm)
        dr.rectangle([ox, oy, ox + pl["W"] * px_per_mm, oy + h], outline=(150, 150, 150), fill=(250, 250, 247))
        pos, idle, ng = (0.0, 0.0), 0.0, 0
        for ins in r["inserts"]:
            ng += ins["ref"][0] == "NestGroup"
            for s in bn[ins["block"]]["shapes"]:
                a, b = G.ends(s)
                dr.line([P(pos), P(a)], fill=(225, 45, 30), width=1)
                idle += math.dist(pos, a)
                pts = G.points(s, 0.5)
                if G.is_closed(s):
                    pts = pts + pts[:1]
                col = (40, 90, 210) if s["layer"] == 2 else ((150, 70, 0) if s.get("coedge") else (20, 20, 20))
                dr.line([P(p) for p in pts], fill=col, width=1)
                pos = b
        x, y = P((0, 0)); dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(0, 160, 60))
        dr.text((ox, oy - top + 6), "№%d  ×%d лист.  %g×%g" % (r["index"], r["plate_amount"], pl["W"], pl["L"]), fill=(0, 0, 0), font=Fb)
        dr.text((ox, oy - top + 26), "холостой %.1f м%s" % (idle / 1000, ("  · групп общего реза %d" % ng) if ng else ""), fill=(60, 60, 60), font=F)
    img.save(path)
    return path
