# -*- coding: utf-8 -*-
"""Детали из программы CypCut (.lxds) — с раскладками или без (например, когда раскладка CypCut не дала: у него
предел 20 листов на свой раскрой). Блок детали берётся как есть: все контуры, технологические слои (1 — рез,
2 — гравировка), открытые прорези; количество — Amount детали. Внешний контур — последним.

    parts, info = parts_from_lxds(data, filename, heal_gap_mm=0)
    info: technical (байты Technical/content.xml — параметры резки инженера), groups (пары общего реза CypCut),
          app (версия CypCut), plates (размеры листов программы), bridges (вставок мостов CypCut — без ссылки на деталь;
          количество деталей всё равно из Amount — у CypCut это заказ, детали моста в него входят), warnings

Внешний контур, который не замкнули (16.10.2026, решётки: открытая полилиния слоя реза, в габарите которой все
остальные фигуры детали; концы в 16 мм друг от друга на нижней кромке): heal_gap_mm > 0 — закрыть прямой, если разрыв
не больше и лежит на прямой самого контура (geom.heal_open), с предупреждением «деталь «…»: внешний контур не замкнут,
разрыв N мм на кромке — закрыт прямой (проверьте чертёж)»; иначе (и по умолчанию, 0) — LxdsError с разрывом и
координатами. Прежде такой контур молча шёл прорезью, а внешним брался самый большой замкнутый (отверстие) или, если
замкнутых не было, — «нет замкнутого контура реза».
"""
import io, zipfile, math, struct, zlib
import xml.etree.ElementTree as ET
from .libpath import vn
from . import geom as G
from .errors import SheetNestError

BAD_NAME = str.maketrans({c: "" for c in "&<>\"'"})


class LxdsError(SheetNestError):
    """Плохая программа CypCut (не .lxds, повреждена, нет деталей) — текст для человека."""
    kind = "input"


def parts_from_lxds(data, filename="программа.lxds", heal_gap_mm=0.0):
    """Программа CypCut (байты) → (детали, info). Плохой файл — LxdsError с текстом для человека (и там, где разбор
    упал на испорченных данных глубже первой проверки: не KeyError/AttributeError из середины разбора). heal_gap_mm —
    закрывать прямой разрыв внешнего контура до стольких мм (0 — не закрывать: ошибка, как раньше)."""
    try:
        return _parts_from_lxds(data, filename, float(heal_gap_mm or 0.0))
    except LxdsError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError, AttributeError, TypeError, IndexError, struct.error,
            zlib.error, EOFError) as e:
        # текст — человеку (без питоновских исключений по-английски); само исключение — в цепочке (трассировка)
        raise LxdsError("%s: не программа CypCut или файл повреждён%s" % (filename, _why(e))) from e


def _why(e):
    """Чем программа плоха — по-русски, коротко: не zip-архив, нет части архива; прочее — без подробностей."""
    if isinstance(e, zipfile.BadZipFile):
        return " (не zip-архив)"
    if isinstance(e, KeyError) and e.args and isinstance(e.args[0], str) and "no item named" in e.args[0]:
        part = e.args[0].split("named", 1)[1].split(" in the archive")[0].strip(" '\"")
        return " (в архиве нет %s)" % part
    if isinstance(e, ET.ParseError):
        return " (испорчен XML внутри архива)"
    return ""


def _fmt(v):
    return "%g" % round(v, 2)


def open_outer(sh, tol=0.01):
    """Внешний контур, который не замкнули: открытая полилиния слоя реза (≥ 3 вершин), в габарите которой — все остальные
    фигуры детали, и габарит больше, чем у любого замкнутого контура реза (иначе это прорезь или дубль). Нет — None."""
    cands = [s for s in sh if s["kind"] == "LwPolyline" and s["layer"] == 1 and not G.is_closed(s) and len(s["verts"]) >= 3]
    if not cands:
        return None
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    c = max(cands, key=lambda s: area(G.bbox([s])))
    x0, y0, x1, y1 = G.bbox([c])
    for s in sh:
        if s is c:
            continue
        a = G.bbox([s])
        if a[0] < x0 - tol or a[1] < y0 - tol or a[2] > x1 + tol or a[3] > y1 + tol:
            return None
        if s["layer"] == 1 and G.is_closed(s) and area(a) >= 0.999 * area((x0, y0, x1, y1)):
            return None
    return c


def heal_outer(sh, name, filename, heal_gap_mm, info):
    """Фигуры детали: внешний контур не замкнут (open_outer) — закрыть прямой (geom.heal_open, предупреждение в info)
    или LxdsError с разрывом и координатами (от угла габарита детали). Вернуть (фигуры, закрытый контур | None) — сам
    список не меняется; закрытый контур — внешний, какой бы OutlineID ни был в блоке (у CypCut он мог указать на
    отверстие: открытый контур внешним не бывает)."""
    c = open_outer(sh)
    if c is None:
        return sh, None
    V = c["verts"]
    g = math.dist(V[0][:2], V[-1][:2])
    healed, _ = G.heal_open(V, heal_gap_mm)             # концы совпали (≤ HEAL_ZERO) — замыкается и без допуска
    if healed is None:
        x0, y0, _, _ = G.bbox([c])
        at = "между (%s; %s) и (%s; %s) от угла габарита детали" % (_fmt(V[0][0] - x0), _fmt(V[0][1] - y0), _fmt(V[-1][0] - x0),
                                                                    _fmt(V[-1][1] - y0))
        can = G.heal_open(V, g + 1.0)[0] is not None    # закрылся бы прямой при большем допуске?
        if heal_gap_mm > 0 and can:
            why = " — больше допустимого %s мм; закройте контур в CypCut или в чертеже" % _fmt(heal_gap_mm)
        elif can:
            why = " — разрыв на прямой кромки: его можно закрыть прямой, если разрешить закрывать разрывы до %s мм, или " \
                  "закройте контур в CypCut или в чертеже" % _fmt(max(1, math.ceil(g)))
        else:
            why = " — не на прямой кромки (косой разрыв, на дуге или прямая задела бы сам контур): закрыть прямой нельзя, " \
                  "закройте контур в CypCut или в чертеже"
        raise LxdsError("%s: у детали «%s» внешний контур не замкнут: разрыв %s мм %s%s" % (filename, name, _fmt(g), at, why),
                        flag="--heal-gap")
    flag = (int(c["flag"]) | 1) & ~2 | (2 if G.poly_area(healed) < 0 else 0)    # бит 2 — по часовой (как у замкнутых)
    if g <= G.HEAL_ZERO:
        info["warnings"].append("деталь «%s»: внешний контур не помечен замкнутым, концы совпадают — замкнут (разрыва "
                                "нет)" % name)
    else:
        info["warnings"].append("деталь «%s»: внешний контур не замкнут, разрыв %s мм на кромке — закрыт прямой (проверьте "
                                "чертёж)" % (name, _fmt(g)))
    h = dict(c, verts=healed, flag=flag, sp=0.0)
    return [h if s is c else s for s in sh], h


def _parts_from_lxds(data, filename, heal_gap_mm=0.0):
    SR = vn.spec_rebuild
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        X = lambda n: ET.fromstring(zf.read(n))
        gb, sb = zf.read("Geometry2D/data.bin"), zf.read("Shapes2D/data.bin")
        shapes = {int(e.get("Handle")): SR.read_shape(e, gb, sb) for e in X("Shapes2D/content.xml") if e.tag != "MD5"}
        parts_x = X("Nest2D/Parts/content.xml")
        blocks = {b.get("Name"): b for b in X("Blocks/content.xml")}
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as e:
        raise LxdsError("%s: не программа CypCut или файл повреждён%s" % (filename, _why(e))) from e
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
        sh, healed = heal_outer(sh, (p.get("Name") or "деталь").translate(BAD_NAME), filename, heal_gap_mm, info)
        oid = b.get("OutlineID") if healed is None else healed["handle"]
        closed1 = [s for s in sh if G.is_closed(s) and s["layer"] == 1]
        if not closed1:
            raise LxdsError("%s: у детали %s нет замкнутого контура реза" % (filename, p.get("Name")))
        outer = (healed or next((s for s in sh if oid is not None and s["handle"] == int(oid)), None)
                 or max(closed1, key=G.area))
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
