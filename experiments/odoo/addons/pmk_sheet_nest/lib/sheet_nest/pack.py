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
from .errors import SheetNestError

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


def check_fit(parts, W, L, edge):
    """Понятный отказ до раскроя: какая деталь не помещается на лист и почему (SheetNestError)."""
    for p in parts:
        x0, y0, x1, y1 = part_box(p)
        w, h = x1 - x0, y1 - y0
        if not ((w <= W - 2 * edge + 1e-6 and h <= L - 2 * edge + 1e-6) or (h <= W - 2 * edge + 1e-6 and w <= L - 2 * edge + 1e-6)):
            raise SheetNestError("деталь «%s» %.1f×%.1f мм не помещается на лист %g×%g с отступом от края %g мм"
                                 % (p["name"], w, h, W, L, edge), input=p.get("input"))


def plan(parts, W, L, gap, edge, methods=("rect", "raster")):
    """parts: [Part] → dict(layouts=[{"W","L","amount","placed"}], sheets, method, lower_bound, optimal, tried)."""
    tried = []
    best = None
    check_fit(parts, W, L, edge)
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


# =========================================================================================== общий рез
def _placed_outer(parts, q):
    return G.transform(parts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"]))


def coedge_groups(parts, placed, safe=1.0):
    """Группы общего реза на листе: детали, у которых совпали прямые участки контура (связные компоненты).
    Вернуть (группы — списки индексов размещений, ≥ 2; список небезопасных сближений)."""
    from . import coedge as CE
    outs = [_placed_outer(parts, q) for q in placed]
    boxes = [G.bbox([o]) for o in outs]
    n = len(placed)
    adj = {i: set() for i in range(n)}
    unsafe = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = boxes[i], boxes[j]
            if a[0] > b[2] + safe or b[0] > a[2] + safe or a[1] > b[3] + safe or b[1] > a[3] + safe:
                continue
            if outs[i]["kind"] != "LwPolyline" or outs[j]["kind"] != "LwPolyline":
                unsafe.append((i, j, None, "круглая деталь вплотную к соседу"))
                continue
            sl = CE.shared_length(outs[i]["verts"], outs[j]["verts"])
            nc = CE.near_contact(outs[i]["verts"], outs[j]["verts"], safe) or CE.near_contact(outs[j]["verts"], outs[i]["verts"], safe)
            if nc:
                unsafe.append((i, j, nc, "сближение %.2f мм не по общей кромке" % nc[0]))
            if sl > 1e-3:
                adj[i].add(j); adj[j].add(i)
    seen, groups = set(), []
    for i in range(n):
        if i in seen or not adj[i]:
            continue
        comp, stack = [], [i]
        seen.add(i)
        while stack:
            k = stack.pop(); comp.append(k)
            for m in adj[k]:
                if m not in seen:
                    seen.add(m); stack.append(m)
        groups.append(sorted(comp))
    return groups, unsafe


def plan_coedge(parts, W, L, edge, safe=1.0):
    """Раскрой под общий рез: прямоугольный упаковщик с зазором 0 — соседние детали встают кромка к кромке.
    Годится, если нигде нет опасного сближения (0 < d < safe не по общей кромке: рез заденет соседа) и у всех
    деталей внешний контур — полилиния. Вернуть план (как plan(), + layouts[i]["groups"]) или (None, причина)."""
    from .pack_rect import pack_rect
    for p in parts:
        if p["shapes"][-1]["kind"] != "LwPolyline":
            return None, "деталь «%s» круглая — общий рез только для деталей с прямыми кромками" % p["name"]
    items = []
    for i, p in enumerate(parts):
        x0, y0, x1, y1 = part_box(p)
        items.append(dict(id=i, w=x1 - x0, h=y1 - y0, qty=p["qty"]))
    res = pack_rect(items, W, L, 0.0, edge, rotations=(0, 90))
    sheets = [[_rect_to_place(parts[r["id"]], r) for r in sh] for sh in res["sheets"]]
    lays = group_sheets(sheets)
    for l in lays:
        groups, unsafe = coedge_groups(parts, l["placed"], safe)
        if unsafe:
            i, j, nc, why = unsafe[0]
            return None, "детали «%s» и «%s»: %s — общий рез для такой пары небезопасен" % (
                parts[l["placed"][i]["part"]]["name"], parts[l["placed"][j]["part"]]["name"], why)
        l["groups"] = groups
    lb_true = area_bound(parts, W, L, 0.0, edge)
    rect_like = min(rectangularity(p) for p in parts) >= RECT_LIKE
    lb = max(lb_true, res.get("lower_bound") or 0) if rect_like else lb_true
    layouts = [dict(W=float(W), L=float(L), amount=l["amount"], placed=l["placed"], groups=l["groups"]) for l in lays]
    tried = [dict(method="прямоугольный, общий рез (%s)" % res.get("method", ""), sheets=len(sheets), layouts=len(lays),
                  lower_bound=res.get("lower_bound"), optimal=res.get("optimal"))]
    return dict(layouts=layouts, sheets=len(sheets), method=tried[0]["method"], lower_bound=lb, lower_bound_area=lb_true,
                lower_bound_rect=res.get("lower_bound"), bound_kind="по габаритам" if (rect_like and (res.get("lower_bound") or 0) > lb_true) else "по площади",
                optimal=len(sheets) <= lb, tried=tried, coedge=True), None
