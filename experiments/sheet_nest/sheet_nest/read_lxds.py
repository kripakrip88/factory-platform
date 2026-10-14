# -*- coding: utf-8 -*-
"""Детали из программы CypCut (.lxds) — с раскладками или без (например, когда раскладка CypCut не дала: у него
предел 20 листов на свой раскрой). Блок детали берётся как есть: все контуры, технологические слои (1 — рез,
2 — гравировка), открытые прорези; количество — Amount детали. Внешний контур — последним.

    parts, info = parts_from_lxds(data, filename)
    info: technical (байты Technical/content.xml — параметры резки инженера), groups (пары общего реза CypCut),
          app (версия CypCut), plates (размеры листов программы), bridges (вставок мостов CypCut — без ссылки на деталь;
          количество деталей всё равно из Amount — у CypCut это заказ, детали моста в него входят), warnings
"""
import io, zipfile, math
import xml.etree.ElementTree as ET
from .libpath import vn
from . import geom as G

BAD_NAME = str.maketrans({c: "" for c in "&<>\"'"})


class LxdsError(Exception):
    pass


def parts_from_lxds(data, filename="программа.lxds"):
    SR = vn.spec_rebuild
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        X = lambda n: ET.fromstring(zf.read(n))
        gb, sb = zf.read("Geometry2D/data.bin"), zf.read("Shapes2D/data.bin")
        shapes = {int(e.get("Handle")): SR.read_shape(e, gb, sb) for e in X("Shapes2D/content.xml") if e.tag != "MD5"}
        parts_x = X("Nest2D/Parts/content.xml")
        blocks = {b.get("Name"): b for b in X("Blocks/content.xml")}
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as e:
        raise LxdsError("%s: не программа CypCut или повреждена (%s)" % (filename, e))
    info = dict(technical=zf.read("Technical/content.xml") if "Technical/content.xml" in zf.namelist() else None,
                app=None, groups=[], plates=[], warnings=[])
    try:
        info["app"] = ET.fromstring(zf.read("info.xml")).find("Application").get("AppVer")
    except Exception:
        pass
    by_handle = {}
    parts = []
    for p in parts_x:
        bn = p.find("Insert").findtext("BlockName")
        if bn not in blocks:
            raise LxdsError("%s: у детали %s нет блока %s" % (filename, p.get("Name"), bn))
        b = blocks[bn]
        sh = [dict(shapes[int(s.get("Handle"))]) for s in b.find("Shapes")]
        sh = [s for s in sh if s["kind"] in ("Line", "Circle", "LwPolyline")]
        oid = b.get("OutlineID")
        closed1 = [s for s in sh if G.is_closed(s) and s["layer"] == 1]
        if not closed1:
            raise LxdsError("%s: у детали %s нет замкнутого контура реза" % (filename, p.get("Name")))
        outer = next((s for s in sh if oid is not None and s["handle"] == int(oid)), None) or max(closed1, key=G.area)
        if outer is not max(closed1, key=G.area):
            info["warnings"].append("деталь %s: внешний контур по OutlineID не самый большой" % p.get("Name"))
        inner = [s for s in sh if s is not outer]
        for s in inner:
            s["outer"] = 0
        outer = dict(outer, outer=1)
        x0, y0, _, _ = G.bbox([outer])
        out_shapes = [G.translate(dict(s, handle=None, lead=None), -x0, -y0) for s in inner + [outer]]
        name = (p.get("Name") or "деталь").translate(BAD_NAME)
        part = dict(name=name, qty=int(p.get("Amount") or 0), shapes=out_shapes, src=filename, warnings=[])
        if part["qty"] <= 0:
            part["qty"] = 1
            part["warnings"].append("количество в программе 0 — взято 1")
        parts.append(part)
        by_handle[int(p.get("Handle"))] = len(parts) - 1
    if "Nest2D/Parts/Groups/content.xml" in zf.namelist():
        for g in X("Nest2D/Parts/Groups/content.xml"):
            info["groups"].append(dict(name=g.get("Name"), parts=[by_handle.get(int(o.get("Handle"))) for o in g]))
    try:
        for p in X("Nest2D/Plates/content.xml"):
            pts = [(float(q.get("X", 0)), float(q.get("Y", 0))) for q in p.find("LwPolyline").findall("Point")]
            info["plates"].append((pts[2][0], pts[2][1], int(p.get("Amount") or 0)))
    except Exception:
        pass
    # мосты CypCut: вставка раскладки без NestPart/NestGroup (детали моста в AmountUsed не входят, Amount — заказ)
    info["bridges"] = 0
    try:
        for r in X("Nest2D/Results/content.xml"):
            rc = X("Nest2D/Results/%s/content.xml" % r.get("Index"))
            info["bridges"] += sum(1 for s in rc.iter("Shape") if s.get("Class") == "Insert" and s.get("NestPart") is None
                                   and s.get("NestGroup") is None)
    except Exception:
        pass
    if info["bridges"]:
        info["warnings"].append("в программе мостов CypCut: %d (вставки без ссылки на деталь) — количество деталей взято из "
                                "Amount (заказ, с деталями мостов)" % info["bridges"])
    if not parts:
        raise LxdsError("%s: в программе нет деталей" % filename)
    return parts, info
