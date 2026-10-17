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

17.10.2026 (0.13.0, Антон: «склейка кусков, кривые безье»; приёмка — все 2104 программы архива завода, было прочитано
1171, стало 1951 (с heal_gap_mm 20 — 1953); остальное — 134 чертежа CypCut без раскроя и 19 программ с честной ошибкой;
длина реза каждой детали сверена с независимым подсчётом по записям файла — расхождений нет; 1106 программ, читавшихся
и раньше, — те же детали, 64 с молча потерянным резом — рез на месте):
- фигуры — свои декодеры (lxds_shapes): дуга, кривая Безье (ломаная ≤ 0,01 мм), надпись — предупреждение у детали,
  неизвестный класс и нечитаемая запись — ошибка с именем детали; записи признаков CypCut 2023; ничего не выбрасывается
  молча (прежде дуги роняли программу целиком — «повреждена», кривые Безье выбрасывались без слова);
- деталь из одной фигуры без блока (NestPart ShapeCls="LwPolyline" | "Circle" | "PolyBezier": 1907 деталей в 671
  программе — прежде каждая такая программа «повреждена»); чертёж CypCut (Model2D, без списка деталей) — своя ошибка;
- склейка: открытые куски, концы которых сходятся (≤ 0,01 мм), — один контур (lxds_shapes.glue), с предупреждением;
- внешний контур из нескольких кусков с промежутками (outer_ring): с heal_gap_mm каждый промежуток закрывается по
  правилам одного разрыва (geom.heal_ring), кусок внахлёст за угол соседа — контур по углу, заход — отдельным резом;
  иначе — ошибка со списком промежутков (прежде брался один кусок, и «разрыв» был расстоянием между его концами).
"""
import io, zipfile, math, struct, zlib
import xml.etree.ElementTree as ET
from . import geom as G, lxds_shapes as LS
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


def _open_cut(s):
    """Открытый кусок реза: Line или открытая LwPolyline слоя 1, не линия общего реза CypCut."""
    return s["kind"] in ("Line", "LwPolyline") and s["layer"] == 1 and not G.is_closed(s) and not s.get("coedge")


def outer_ring(sh, tol=0.01):
    """Внешний контур, который не замкнули: открытые куски реза по кругу → [(кусок, развернуть)] | None. Начало — открытый
    кусок реза с самым большим габаритом; от его конца — к ближайшему концу другого открытого куска, если тот ближе
    начала, и так, пока ближайшим не станет начало (17.10.2026: внешний контур бывает нарисован кусками с промежутками —
    перемычками или неточностью чертежа: 8 программ архива; до того брался один кусок, и разрыв в тексте ошибки был
    расстоянием между его концами — 1184 мм у бордюра). Кусок один — полилиния не меньше 3 вершин. В габарите кусков —
    все остальные фигуры детали, и он больше, чем у любого замкнутого контура реза (иначе это прорези или дубль)."""
    cands = [s for s in sh if _open_cut(s)]
    if not cands:
        return None
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    c = max(cands, key=lambda s: (area(G.bbox([s])), G.length(s)))
    ring = [(c, False)]
    a0, cur = G.ends(c)
    free = [s for s in cands if s is not c]
    while free:
        d0 = math.dist(cur, a0)
        best = None
        for s in free:
            a, z = G.ends(s)
            for rev, q in ((False, a), (True, z)):
                d = math.dist(cur, q)
                if d < d0 - 1e-9 and (best is None or d < best[0]):
                    best = (d, s, rev)
        if best is None:
            break
        _, s, rev = best
        ring.append((s, rev))
        free.remove(s)
        cur = G.ends(s)[0 if rev else 1]
    if len(ring) == 1 and (c["kind"] != "LwPolyline" or len(c["verts"]) < 3):
        return None
    x0, y0, x1, y1 = G.bbox([s for s, _ in ring])
    mine = set(id(s) for s, _ in ring)
    for s in sh:
        if id(s) in mine:
            continue
        a = G.bbox([s])
        if a[0] < x0 - tol or a[1] < y0 - tol or a[2] > x1 + tol or a[3] > y1 + tol:
            return None
        if s["layer"] == 1 and G.is_closed(s) and area(a) >= 0.999 * area((x0, y0, x1, y1)):
            return None
    return ring


def open_outer(sh, tol=0.01):
    """Внешний контур из одного открытого куска (outer_ring из одного куска) или None."""
    r = outer_ring(sh, tol)
    return r[0][0] if r is not None and len(r) == 1 else None


def heal_outer(sh, name, filename, heal_gap_mm, info):
    """Фигуры детали: внешний контур не замкнут (outer_ring) — закрыть прямой (один кусок — geom.heal_open; несколько —
    geom.heal_ring, каждый промежуток), предупреждение в info; или LxdsError с разрывом и координатами (от угла габарита
    детали). Вернуть (фигуры, закрытый контур | None) — закрытый контур встаёт на место первого куска, прочие куски
    контура уходят в него; закрытый контур — внешний, какой бы OutlineID ни был в блоке (у CypCut он мог указать на
    отверстие: открытый контур внешним не бывает)."""
    ring = outer_ring(sh)
    if ring is None:
        return sh, None
    if len(ring) > 1:
        return _heal_pieces(sh, ring, name, filename, heal_gap_mm, info)
    c = ring[0][0]
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


def _heal_pieces(sh, ring, name, filename, heal_gap_mm, info):
    """heal_outer, внешний контур из нескольких кусков: каждый промежуток — geom.heal_ring; нельзя — LxdsError со списком
    промежутков и местом того, который не закрыть."""
    pieces = [s for s, _ in ring]
    chains = [LS.verts_of(G.reverse(s) if rev else s) for s, rev in ring]
    V, gaps, bad, rest, mode = G.heal_ring(chains, heal_gap_mm)
    n = len(chains)
    big = sorted(g for g in gaps if g > G.HEAL_ZERO)
    lst = ", ".join(_fmt(g) for g in big[:6]) + (" …" if len(big) > 6 else "")
    if V is None:
        x0, y0, _, _ = G.bbox(pieces)
        how, i = bad
        if i is not None:
            z, a = chains[i][-1], chains[(i + 1) % n][0]
            at = "%s мм между (%s; %s) и (%s; %s) от угла габарита детали" % (
                _fmt(gaps[i]), _fmt(z[0] - x0), _fmt(z[1] - y0), _fmt(a[0] - x0), _fmt(a[1] - y0))
        if how == "line":
            why = "промежуток %s не на прямой кромки (косой, на дуге или внахлёст): закрыть прямой нельзя" % at
        elif how == "cross":
            why = "закрыть их прямыми нельзя: прямые задели бы сам контур"
        elif heal_gap_mm > 0:
            why = "промежуток %s больше допустимого %s мм" % (at, _fmt(heal_gap_mm))
        else:
            why = "все на прямой кромки: контур можно собрать, если разрешить закрывать разрывы до %s мм" % (
                _fmt(max(1, math.ceil(max(gaps)))))
        raise LxdsError("%s: у детали «%s» внешний контур не замкнут: он из %d кусков с промежутками %s мм (перемычки или "
                        "неточность чертежа) — %s; закройте контур в CypCut или в чертеже"
                        % (filename, name, n, lst, why), flag="--heal-gap")
    flag = 1 | (2 if G.poly_area(V) < 0 else 0)
    P = G.points(dict(kind="LwPolyline", verts=V, flag=1), 0.05)
    slits = []
    for p, q in rest:                                   # кусочки внахлёст: на контуре — дубль, внутри — рез, снаружи — нет
        m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        if min(G.seg_point_dist(m, P[k - 1], P[k]) for k in range(len(P))) <= 0.01:
            continue
        if not G.inside(m, P):
            raise LxdsError("%s: у детали «%s» внешний контур не замкнут: он из %d кусков, кусок заходит за угол соседа "
                            "наружу — закройте контур в CypCut или в чертеже" % (filename, name, len(chains)), flag="--heal-gap")
        slits.append(dict({k: v for k, v in pieces[0].items() if k not in ("verts", "flag", "sp")}, kind="Line",
                          p1=tuple(p), p2=tuple(q), outer=0, coedge=0, lead=None, handle=None))
    shut = sorted(g for g, m in zip(gaps, mode) if m == "line")
    if shut:
        info["warnings"].append("деталь «%s»: внешний контур из %d кусков, промежутки %s мм — закрыты прямыми (перемычки в "
                                "контуре теперь режутся; проверьте чертёж)" % (
                                    name, n, ", ".join(_fmt(g) for g in shut[:6]) + (" …" if len(shut) > 6 else "")))
    elif not rest:
        info["warnings"].append("деталь «%s»: внешний контур из %d кусков, концы сходятся — склеен" % (name, n))
    h = dict({k: v for k, v in pieces[0].items() if k not in ("p1", "p2")}, kind="LwPolyline", verts=V, flag=flag, sp=0.0)
    if slits:
        info["warnings"].append("деталь «%s»: внешний контур из %d кусков, кусок заходит за угол соседа (%s мм) — контур "
                                "собран по углу, заход оставлен резом внутри детали, как в программе (проверьте чертёж)" % (
                                    name, n, ", ".join(_fmt(math.dist(s["p1"], s["p2"])) for s in slits[:4])))
    elif rest:
        info["warnings"].append("деталь «%s»: внешний контур из %d кусков, кусок заходит за угол соседа по кромке — контур "
                                "собран по углу (заход — тот же рез по кромке)" % (name, n))
    mine = set(id(s) for s in pieces)
    return slits + [h if s is pieces[0] else s for s in sh if s is pieces[0] or id(s) not in mine], h


def _part_shapes(p, blocks, shapes, filename, pname):
    """Фигуры детали NestPart → (фигуры, OutlineID | None, заметки {вид: [...]}) — без молчаливых потерь: надпись и
    нулевая дуга — в заметки (предупреждение у детали), вложенный блок, неизвестный класс, нечитаемая запись — LxdsError
    с именем детали. Деталь — вставка блока (Insert → BlockName) или одна фигура без блока (ShapeCls="LwPolyline" |
    "Circle" | "PolyBezier": CypCut так хранит деталь из одного контура — 1907 деталей в 671 программе архива)."""
    ins = p.find("Insert")
    if ins is not None:
        bn = ins.findtext("BlockName")
        if bn not in blocks:
            raise LxdsError("%s: у детали %s нет блока %s" % (filename, p.get("Name"), bn))
        b = blocks[bn]
        refs = [(s.get("Class"), s.get("Handle")) for s in b.find("Shapes")]
        oid = b.get("OutlineID")
    else:
        refs = [(s.get("Class"), s.get("Handle")) for s in p.findall("Shape")]
        oid = None
        if not refs:
            raise LxdsError("%s: у детали «%s» нет ни блока, ни фигуры" % (filename, pname))
    sh, notes = [], {"text": [], "zero_arc": 0, "bezier": 0, "arc": 0}
    for cls, h in refs:
        got = shapes.get(int(h)) if h is not None and h.isdigit() else None
        if got is None:
            if cls == "Insert":
                raise LxdsError("%s: у детали «%s» внутри вложенный блок — программа раскроя его не читает; разбейте его в "
                                "CypCut (детали из простых контуров)" % (filename, pname))
            raise LxdsError("%s: у детали «%s» нет фигуры %s #%s — программа повреждена" % (filename, pname, cls, h))
        if not got and cls == "Arc":
            notes["zero_arc"] += 1
            continue
        for s in got:
            if s["kind"] == "Text":
                notes["text"].append(s["text"])
            elif s["kind"] == "?":
                raise LxdsError("%s: у детали «%s» фигура %s не читается (%s) — пересохраните программу в CypCut или "
                                "разбейте фигуру на линии и дуги" % (filename, pname, s["cls"], s["why"]))
            else:
                s = dict(s)
                if s.pop("bezier", False):
                    notes["bezier"] += 1
                if cls == "Arc":
                    notes["arc"] += 1
                sh.append(s)
    return sh, oid, notes


def _notes_warnings(notes, made):
    """Заметки чтения детали → предупреждения (у детали; командная строка допишет её имя)."""
    w = []
    if notes["text"]:
        t = notes["text"]
        w.append("надписи CypCut не перенесены (%d: %s) — их шрифт программа раскроя не читает; нанесите их в CypCut"
                 % (len(t), ", ".join("«%s»" % x for x in t[:5]) + (" …" if len(t) > 5 else "")))
    if notes["bezier"]:
        w.append("кривые Безье (%d) заменены ломаной с отклонением не больше %s мм" % (notes["bezier"], _fmt(LS.CURVE_TOL)))
    if notes["zero_arc"]:
        w.append("дуги нулевой длины пропущены: %d" % notes["zero_arc"])
    if made:
        closed = sum(1 for _, g in made if G.is_closed(g))
        w.append("контуры из кусков склеены (концы сходятся): %d из %d кусков%s" % (
            len(made), sum(len(h) for h, _ in made), (", замкнутых %d" % closed) if closed else ""))
    return w


def _parts_from_lxds(data, filename, heal_gap_mm=0.0):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = set(zf.namelist())
    except zipfile.BadZipFile as e:
        raise LxdsError("%s: не программа CypCut или файл повреждён%s" % (filename, _why(e))) from e
    if "Nest2D/Parts/content.xml" not in names and "Model2D/content.xml" in names:
        raise LxdsError("%s: это чертёж CypCut без раскроя — в нём нет списка деталей; добавьте детали в раскрой в CypCut "
                        "или пришлите чертёж DXF" % filename)
    try:
        X = lambda n: ET.fromstring(zf.read(n))
        gb, sb = zf.read("Geometry2D/data.bin"), zf.read("Shapes2D/data.bin")
        shapes = LS.read_shapes(X("Shapes2D/content.xml"), gb, sb)
        parts_x = X("Nest2D/Parts/content.xml")
        blocks = {b.get("Name"): b for b in X("Blocks/content.xml")} if "Blocks/content.xml" in names else {}
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as e:
        raise LxdsError("%s: не программа CypCut или файл повреждён%s" % (filename, _why(e))) from e
    info = dict(technical=zf.read("Technical/content.xml") if "Technical/content.xml" in names else None,
                app=None, groups=[], plates=[], warnings=[])
    try:
        info["app"] = ET.fromstring(zf.read("info.xml")).find("Application").get("AppVer")
    except Exception:
        pass
    by_handle = {}
    parts = []
    for p in parts_x:
        pname = (p.get("Name") or "деталь").translate(BAD_NAME)
        sh, oid, notes = _part_shapes(p, blocks, shapes, filename, pname)
        sh, made = LS.glue(sh)
        if oid is not None and oid.isdigit():           # OutlineID указывал на кусок — теперь на склеенный контур
            for hs, g in made:
                if int(oid) in hs:
                    g["handle"] = int(oid)
        if not sh:
            raise LxdsError("%s: у детали «%s» нет контуров реза%s" % (
                filename, pname, " — только надписи CypCut (%s)" % ", ".join("«%s»" % t for t in notes["text"][:5])
                if notes["text"] else ""))
        sh, healed = heal_outer(sh, pname, filename, heal_gap_mm, info)
        oid = oid if healed is None else healed["handle"]
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
        part = dict(name=pname, qty=int(p.get("Amount") or 0), shapes=out_shapes, src=filename,
                    warnings=_notes_warnings(notes, made))
        if part["qty"] <= 0:
            part["qty"] = 1
            part["warnings"].append("количество в программе 0 — взято 1")
        parts.append(part)
        by_handle[int(p.get("Handle"))] = len(parts) - 1
    if "Nest2D/Parts/Groups/content.xml" in names:
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
