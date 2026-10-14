# -*- coding: utf-8 -*-
"""Растровый раскрой v1 пакета (растр 2 мм + БПФ, доводка точной геометрией до зазора) для деталей любой формы.

Пакет писался под лист шириной 1250 и длину из списка; ширина и зазоры там — переменные модуля nest. Здесь они
ставятся на время раскроя и возвращаются обратно. Повороты 0/90/180/270 без зеркала.
"""
import contextlib
from .libpath import vn
from . import geom as G


@contextlib.contextmanager
def _sheet(W, gap, edge):
    N = vn.nest
    old = (N.SHEET_W, N.GAP, N.EDGE)
    N.SHEET_W = float(W)
    N.set_spacing(gap, edge)
    try:
        yield N
    finally:
        N.SHEET_W = old[0]
        N.set_spacing(old[1], old[2])


def pack_raster(parts, W, L, gap, edge):
    """parts: [Part] → [[{"part", "rot", "dx", "dy"}]] (по листу), имя лучшего порядка."""
    items = []
    for i, p in enumerate(parts):
        poly = G.points(p["shapes"][-1], 0.02)
        for c in range(p["qty"]):
            # hood/role — поля пакета: по ним сортировка при равенстве и текст ошибки «деталь <hood> <role> не помещается»
            items.append(dict(poly=poly, key=("sheet_nest", i), hood="%05d %s" % (i, p["name"]), role="(%.0f×%.0f)" % (
                max(x for x, y in poly) - min(x for x, y in poly), max(y for x, y in poly) - min(y for x, y in poly)), copy=c, part=i))
    if not items:
        return [], None
    with _sheet(W, gap, edge) as N:
        (cand, sheets, lens, Lb, oname) = N.best_pack(items, [float(L)], False)
        out = []
        for s in sheets:
            pl = []
            for it, r, ox, oy in s.placed:
                _, (mx, my) = N.rotated(it["poly"], r)
                pl.append(dict(part=it["part"], rot=r, dx=ox - mx, dy=oy - my))
            out.append(pl)
    return out, oname
