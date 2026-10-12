# -*- coding: utf-8 -*-
"""Раскрой: портфель из двух раскройщиков, берётся лучший.

  • прямоугольный (pack_rect): детали габаритами; точный, когда поперёк листа встаёт одна деталь (решётки: 77 листов
    — доказанный минимум). Для любых деталей допустим (зазор между габаритами ⇒ зазор между деталями), но для
    фигурных деталей расточителен;
  • растровый v1 пакета (pack_raster): настоящий контур, повороты 0/90/180/270.
Лучший — меньше листов; при равенстве — меньше разных раскладок (оператору проще), затем прямоугольный.
Одинаковые листы склеиваются в одну раскладку с количеством.
"""
import math, collections
from . import geom as G

RASTER_MAX_ITEMS = 250      # растровый v1 на 700 шайбах считал > 20 мин (без бюджета времени) — пропускать большие партии


def part_box(p):
    x0, y0, x1, y1 = G.bbox([p["shapes"][-1]])
    return x0, y0, x1, y1


def _rect_to_place(p, r):
    """Прямоугольник упаковщика (левый нижний угол повёрнутого габарита) → поворот и сдвиг детали."""
    x0, y0, x1, y1 = part_box(p)
    w, h = x1 - x0, y1 - y0
    rot = r["rot"]
    # габарит детали после поворота вокруг начала координат: найти его левый нижний угол и совместить с (x, y)
    corners = [G.ROT[rot](x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    mx, my = min(c[0] for c in corners), min(c[1] for c in corners)
    return dict(part=r["id"], rot=rot, dx=r["x"] - mx, dy=r["y"] - my)


def group_sheets(sheets):
    """Одинаковые листы → раскладка с количеством (порядок первого появления)."""
    out, index = [], {}
    for pl in sheets:
        sig = tuple(sorted((q["part"], q["rot"], round(q["dx"], 3), round(q["dy"], 3)) for q in pl))
        if sig in index:
            out[index[sig]]["amount"] += 1
        else:
            index[sig] = len(out)
            out.append(dict(amount=1, placed=pl))
    return out


def plan(parts, W, L, gap, edge, methods=("rect", "raster")):
    """parts: [Part] → dict(layouts=[{"W","L","amount","placed"}], sheets, method, lower_bound, optimal, tried)."""
    tried = []
    best = None
    for p in parts:                                    # понятный отказ до раскроя: какая деталь и почему
        x0, y0, x1, y1 = part_box(p)
        w, h = x1 - x0, y1 - y0
        if not ((w <= W - 2 * edge + 1e-6 and h <= L - 2 * edge + 1e-6) or (h <= W - 2 * edge + 1e-6 and w <= L - 2 * edge + 1e-6)):
            raise ValueError("деталь «%s» %.1f×%.1f мм не помещается на лист %g×%g с отступом от края %g мм"
                             % (p["name"], w, h, W, L, edge))
    if "rect" in methods:
        from .pack_rect import pack_rect
        items = []
        for i, p in enumerate(parts):
            x0, y0, x1, y1 = part_box(p)
            items.append(dict(id=i, w=x1 - x0, h=y1 - y0, qty=p["qty"]))
        res = pack_rect(items, W, L, gap, edge, rotations=(0, 90))
        sheets = [[_rect_to_place(parts[r["id"]], r) for r in sh] for sh in res["sheets"]]
        lays = group_sheets(sheets)
        tried.append(dict(method="прямоугольный (%s)" % res.get("method", ""), sheets=len(sheets), layouts=len(lays),
                          lower_bound=res.get("lower_bound"), optimal=res.get("optimal")))
        best = (len(sheets), len(lays), 0, lays, tried[-1])
    if "raster" in methods and best is not None and best[0] <= max(best[4].get("lower_bound") or 0, area_bound(parts, W, L, gap, edge)):
        tried.append(dict(method="растровый v1", skipped="прямоугольный уже дал нижнюю границу"))
    elif "raster" in methods and sum(p["qty"] for p in parts) > RASTER_MAX_ITEMS:
        tried.append(dict(method="растровый v1", skipped="%d деталей — растровый v1 считает слишком долго (больше %d; быстрый "
                          "раскрой больших партий — v2, шаг 3)" % (sum(p["qty"] for p in parts), RASTER_MAX_ITEMS)))
    elif "raster" in methods:
        from .pack_raster import pack_raster
        try:
            sheets, oname = pack_raster(parts, W, L, gap, edge)
            lays = group_sheets(sheets)
            tried.append(dict(method="растровый v1 (%s)" % oname, sheets=len(sheets), layouts=len(lays), lower_bound=None, optimal=None))
            cand = (len(sheets), len(lays), 1, lays, tried[-1])
            if best is None or cand[:3] < best[:3]:
                best = cand
        except ValueError as e:
            tried.append(dict(method="растровый v1", error=str(e)))
    if best is None:
        raise ValueError("раскрой не удался: %s" % tried)
    # нижние границы: по площади настоящих деталей — строгая; по габаритам (прямоугольный упаковщик) — строгая только
    # для прямоугольных деталей (фигурные растровый может уложить плотнее: зонты — 10 листов при «границе» 11)
    lb_true = area_bound(parts, W, L, gap, edge)
    lb_rect = max([t.get("lower_bound") or 0 for t in tried if "lower_bound" in t] + [0])
    rect_like = min(rectangularity(p) for p in parts) >= RECT_LIKE
    lb = max(lb_true, lb_rect) if rect_like else lb_true
    layouts = [dict(W=float(W), L=float(L), amount=l["amount"], placed=l["placed"]) for l in best[3]]
    return dict(layouts=layouts, sheets=best[0], method=best[4]["method"], lower_bound=lb, lower_bound_area=lb_true,
                lower_bound_rect=lb_rect, bound_kind="по габаритам" if (rect_like and lb_rect > lb_true) else "по площади",
                optimal=best[0] <= lb, tried=tried)


RECT_LIKE = 0.98            # деталь почти прямоугольник (площадь / габарит): граница по габаритам к ней применима


def rectangularity(p):
    x0, y0, x1, y1 = part_box(p)
    return G.area(p["shapes"][-1]) / max(1e-9, (x1 - x0) * (y1 - y0))


def area_bound(parts, W, L, gap, edge):
    """Нижняя граница по площади деталей (настоящей, с отверстиями — нет: по внешнему контуру)."""
    a = sum(G.area(p["shapes"][-1]) * p["qty"] for p in parts)
    return int(math.ceil(a / ((W - 2 * edge) * (L - 2 * edge)) - 1e-9))
