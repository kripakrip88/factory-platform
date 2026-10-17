# -*- coding: utf-8 -*-
"""Читатель программ CypCut 0.13.0 (17.10.2026): дуги, кривые Безье, надписи, детали из одной фигуры, старые записи,
склейка кусков и внешний контур из кусков. Только синтетика: геометрии деталей завода в репозитории нет (он открытый);
программы собираются сборщиком (write_lxds), а фигуры-метки в них подменяются записями Arc / PolyBezier / Text в том
виде, какой выяснен по архиву завода (sheet_nest/lxds_shapes.py).

    python3 tests/check_read_lxds.py

1) дуга: против и по часовой (bulge ±), больше полуоборота — два участка, полный оборот — окружность, нулевая —
   пропуск; длина = r·размах;
2) кривая Безье: прямой участок — одно звено, кривой — ломаная с отклонением ≤ 0,01 мм (проверка по плотным точкам
   кривой в обе стороны), точка начала замкнутой — первой вершиной, разрыв между участками — два куска;
3) склейка: четыре отрезка — замкнутый прямоугольник; узел из трёх концов — цепочка там кончается; линии общего реза
   и разные слои — не склеиваются; кусок сам с собой — не трогается;
4) внешний контур из кусков (geom.heal_ring): промежутки на прямой — закрыты, больше допуска — ("big"), косой —
   ("line"), внахлёст — контур по углу, заход — отдельным резом;
5) программа: деталь с внешним контуром кривой Безье и пазом из двух дуг и двух отрезков — внешний замкнут, паз склеен
   в замкнутый контур, площади верные, предупреждения; надпись — предупреждение со словом; деталь из одной фигуры без
   блока (ShapeCls) — читается; неизвестный класс и нечитаемая запись в детали — ошибка с именем детали, вне деталей —
   нет; запись признаков CypCut 2023 (Shape версии 5) — читается, слой верный; внешний контур из 4 кусков с
   промежутками 4 мм — без допуска ошибка со списком промежутков и подсказкой, с допуском 5 — закрыт; чертёж CypCut
   (Model2D) — «это чертёж»; не zip — «повреждён»;
6) сквозной прогон run() на программе с кривыми и дугами: программа собрана, все проверки, длина реза в готовой
   программе = длина реза деталей × количество.
"""
import sys, os, io, math, struct, zipfile, tempfile
import xml.etree.ElementTree as ET
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from sheet_nest import geom as G, write_lxds as WL, lxds_shapes as LS
from sheet_nest.libpath import vn
from sheet_nest.cli import run
from sheet_nest.read_lxds import parts_from_lxds, LxdsError

SV = vn.spec_verify
PT = LS.PT
fails = []
quiet = lambda *a: None


def check(name, cond, detail=""):
    print("%s %-78s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def base(layer=1):
    return dict(layer=layer, layer_name="0", coedge=0, flag64=0, outer=0, lead=None)


def line(p, q, layer=1, coedge=0):
    return dict(base(layer), kind="Line", p1=tuple(map(float, p)), p2=tuple(map(float, q)), coedge=coedge)


def poly(v, flag, layer=1):
    return dict(base(layer), kind="LwPolyline", verts=[(float(x), float(y), float(b)) for x, y, b in v], flag=flag, sp=0.0)


def marker(k, layer=1):
    """Фигура-метка: отрезок с координатами, которых в детали нет (по ним её находит patch)."""
    return line((9000 + k, 9000), (9000 + k, 9001), layer)


def err(f):
    try:
        f()
        return "принято"
    except LxdsError as e:
        return str(e)


def bez_pts(P, t):
    b = ((1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3)
    return (sum(b[j] * P[j][0] for j in range(4)), sum(b[j] * P[j][1] for j in range(4)))


def straight(p, q):
    return [p, ((2 * p[0] + q[0]) / 3, (2 * p[1] + q[1]) / 3), ((p[0] + 2 * q[0]) / 3, (p[1] + 2 * q[1]) / 3), q]


K = 0.5522847498


def corner(c, r, a):
    """Четверть окружности кубической кривой: центр c, радиус r, от угла a (рад) против часовой."""
    p0 = (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
    p3 = (c[0] + r * math.cos(a + math.pi / 2), c[1] + r * math.sin(a + math.pi / 2))
    t0 = (-math.sin(a), math.cos(a))
    t3 = (-math.sin(a + math.pi / 2), math.cos(a + math.pi / 2))
    return [p0, (p0[0] + K * r * t0[0], p0[1] + K * r * t0[1]), (p3[0] - K * r * t3[0], p3[1] - K * r * t3[1]), p3]


def rounded_rect(w, h, r):
    """Прямоугольник со скруглёнными углами — 8 участков Безье (против часовой от низа)."""
    return [straight((r, 0), (w - r, 0)), corner((w - r, r), r, -math.pi / 2), straight((w, r), (w, h - r)),
            corner((w - r, h - r), r, 0), straight((w - r, h), (r, h)), corner((r, h - r), r, math.pi / 2),
            straight((0, h - r), (0, r)), corner((r, r), r, math.pi)]


# =============================================================================== записи CypCut, как в архиве завода
def geo_arc(c, r, ccw, a0, sweep, tag=PT):
    return SV.wobj("Arc", SV.wsub("Arc", 1, struct.pack("<I3dI2d", tag, c[0], c[1], r, 0 if ccw else 1, a0, sweep)))


def geo_bezier(segs, closed, sp=0.0):
    pl = struct.pack("<dIII", sp, 1 if closed else 0, 0, len(segs))
    for k, S in enumerate(segs):
        pl += struct.pack("<I", k + 1) + b"".join(struct.pack("<I2d", PT, x, y) for x, y in S) + struct.pack("<I", 0)
    return SV.wobj("PolyBezier", SV.wsub("PolyBezier", 1, pl + struct.pack("<I", 0)))


def attr_v5(handle, cls, layer, outer=0):
    """Запись признаков CypCut 2023: часть Shape версии 5 — 11 слов (у нынешней — 6, 13 слов)."""
    w = [0] * 11
    w[0] = layer
    body = SV.wsub("Object", 1, struct.pack("<I", handle)) + SV.wsub("Shape", 5, struct.pack("<11I", *w))
    body += struct.pack("<II", 0, 0) + SV.wsub("Curve", 2, struct.pack("<9I", outer, 0, 1, 0, 0, 0, 0, 0, 6))
    return SV.wobj(cls, body)


def _append(buf, rec):
    a = len(buf)
    buf += rec + bytes(SV.al8(len(rec)) - len(rec))
    struct.pack_into("<I", buf, 4, len(buf))
    return a


def patch(raw, repl, single=(), drop_parts=False, extra_unref=None):
    """Программа сборщика → та же программа, где фигуры-метки (marker k) в блоках деталей заменены: repl[k] =
    ("arc", c, r, ccw, a0, sweep) | ("bez", segs, closed, sp) | ("text", слово, слой) | ("unk", класс) |
    ("badarc",) | ("v5", p1, p2) — отрезок p1→p2 с записью признаков старой версии. single — имена деталей, которые
    станут деталями из одной фигуры (ShapeCls, без блока). extra_unref — запись Arc вне деталей (испорченная)."""
    zin = zipfile.ZipFile(io.BytesIO(raw))
    names = zin.namelist()
    files = {n: zin.read(n) for n in names}
    sx = ET.fromstring(files["Shapes2D/content.xml"])
    blocks = ET.fromstring(files["Blocks/content.xml"])
    parts = ET.fromstring(files["Nest2D/Parts/content.xml"])
    gb, sb = bytearray(files["Geometry2D/data.bin"]), bytearray(files["Shapes2D/data.bin"])
    in_parts = set()
    bl = {b.get("Name"): b for b in blocks}
    for p in parts:
        b = bl[p.find("Insert").findtext("BlockName")]
        in_parts |= set(s.get("Handle") for s in b.find("Shapes"))
    for e in list(sx):
        if e.tag != "Line" or e.get("Handle") not in in_parts:
            continue
        s = LS._read_basic(e, bytes(gb), bytes(sb))
        if s["p1"][1] != 9000 or s["p2"][1] != 9001:
            continue
        k = int(round(s["p1"][0] - 9000))
        if k not in repl:
            continue
        h, r = int(e.get("Handle")), repl[k]
        cls = {"arc": "Arc", "badarc": "Arc", "bez": "PolyBezier", "text": "Text", "unk": r[1] if r[0] == "unk" else None,
               "v5": "Line"}[r[0]]
        if r[0] == "text":
            for a in ("GeoAddr", "DataAddr", "LayerName"):
                e.attrib.pop(a, None)
            e.set("Text", r[1])
            e.set("ChannelPort", str(r[2]))
        elif r[0] == "v5":
            e.set("GeoAddr", str(_append(gb, SV.geo_line(r[1], r[2]))))
            e.set("DataAddr", str(_append(sb, attr_v5(h, "Line", s["layer"]))))
        else:
            rec = {"arc": lambda: geo_arc(*r[1:]), "badarc": lambda: geo_arc((0, 0), 5, True, 0, 1, tag=7),
                   "bez": lambda: geo_bezier(*r[1:]), "unk": lambda: SV.wobj(r[1], SV.wsub(r[1], 1, bytes(40)))}[r[0]]()
            e.set("GeoAddr", str(_append(gb, rec)))
            e.set("DataAddr", str(_append(sb, SV.attr_rec(h, cls, s["layer"], 0, 0, 0))))
        e.tag = cls
        for b in blocks:
            for ref in b.find("Shapes"):
                if ref.get("Handle") == str(h):
                    ref.set("Class", cls)
    if extra_unref:
        h = 99999
        el = ET.SubElement(sx, "Arc", Handle=str(h), LayerName="0")
        el.set("GeoAddr", str(_append(gb, geo_arc((0, 0), 5, True, 0, 1, tag=7))))
        el.set("DataAddr", str(_append(sb, SV.attr_rec(h, "Arc", 1, 0, 0, 0))))
    for p in parts:
        if p.get("Name") in single:
            ins = p.find("Insert")
            b = bl[ins.findtext("BlockName")]
            (ref,) = list(b.find("Shapes"))
            for c in list(p):
                if c.tag in ("Insert", "Shape"):
                    p.remove(c)
            p.set("ShapeCls", ref.get("Class"))
            p.insert(0, ET.Element("Shape", Class=ref.get("Class"), Handle=ref.get("Handle")))
    files["Shapes2D/content.xml"] = ET.tostring(sx, encoding="utf-8")
    files["Blocks/content.xml"] = ET.tostring(blocks, encoding="utf-8")
    files["Nest2D/Parts/content.xml"] = ET.tostring(parts, encoding="utf-8")
    files["Geometry2D/data.bin"], files["Shapes2D/data.bin"] = bytes(gb), bytes(sb)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, files[n])
    return out.getvalue()


def program(parts):
    lays = [dict(W=1250.0, L=2500.0, amount=1, seq=[(k, [G.translate(s, 10, 10) for s in p["shapes"]])]) for k, p in enumerate(parts)]
    return WL.build(parts, lays, "syn")[0]


# =================================================================================================== 1) дуга
def arc_unit():
    b = base()
    s = LS.arc_shape(b, (10, 20), 5, True, 0, math.pi / 2)
    v = s["verts"]
    check("дуга 90° против часовой: две вершины, bulge = tan(22,5°), концы на окружности", s["kind"] == "LwPolyline" and len(v) == 2
          and abs(v[0][2] - math.tan(math.pi / 8)) < 1e-12 and math.dist(v[0][:2], (15, 20)) < 1e-9 and math.dist(v[1][:2], (10, 25)) < 1e-9)
    s = LS.arc_shape(b, (10, 20), 5, False, math.pi / 2, math.pi / 2)
    v = s["verts"]
    check("дуга 90° по часовой (направление 1): bulge < 0, конец — по часовой", v[0][2] < 0 and math.dist(v[1][:2], (15, 20)) < 1e-9)
    s = LS.arc_shape(b, (0, 0), 10, True, 0, 1.5 * math.pi)
    check("дуга 270°: два участка (≤ полуоборота каждый), длина = r·размах", len(s["verts"]) == 3 and
          abs(G.length(s) - 10 * 1.5 * math.pi) < 1e-9 and abs(G.bbox([s])[1] + 10) < 1e-9, "%.6f" % G.length(s))
    s = LS.arc_shape(b, (3, 4), 7, True, 1.0, 2 * math.pi)
    check("дуга полного оборота — окружность", s["kind"] == "Circle" and s["r"] == 7 and abs(s["a0"] - 1.0) < 1e-12)
    check("дуга нулевого размаха — None", LS.arc_shape(b, (3, 4), 7, True, 1.0, 0.0) is None)


# =============================================================================================== 2) кривая Безье
def poly_dist(q, P):
    return min(G.seg_point_dist(q, P[k], P[k + 1]) for k in range(len(P) - 1))


def bezier_unit():
    P = corner((0, 0), 100, 0)
    (s,) = LS.bezier_shapes(base(), 0.0, False, [P])
    V = [v[:2] for v in s["verts"]]
    dense = [bez_pts(P, k / 2000) for k in range(2001)]
    d1 = max(poly_dist(q, V) for q in dense)
    d2 = max(poly_dist(v, dense) for v in V)
    check("кривая: ломаная не дальше 0,01 мм от кривой (и вершины — на кривой)", d1 <= LS.CURVE_TOL + 1e-9 and d2 < 1e-4
          and V[0] == P[0] and math.dist(V[-1], P[3]) < 1e-9, "откл. %.5f мм, вершин %d" % (d1, len(V)))
    (s,) = LS.bezier_shapes(base(), 0.0, False, [straight((0, 0), (100, 0))])
    check("прямой участок кривой — одно звено", len(s["verts"]) == 2)
    segs = rounded_rect(200, 100, 10)
    (s,) = LS.bezier_shapes(base(), 1.5, True, segs)
    p = bez_pts(segs[1], 0.5)
    check("замкнутая кривая: флаг 1, точка начала sp = 1,5 — первая вершина, площадь скруглённого прямоугольника",
          G.is_closed(s) and math.dist(s["verts"][0][:2], p) < 1e-9 and abs(G.area(s) - (20000 - (4 - math.pi) * 100)) < 0.5,
          "%.3f" % G.area(s))
    a = straight((0, 0), (10, 0))
    b = straight((20, 0), (30, 0))
    out = LS.bezier_shapes(base(), 0.0, False, [a, b])
    check("разрыв между участками — два куска", len(out) == 2 and all(not G.is_closed(x) for x in out))


# ==================================================================================================== 3) склейка
def glue_unit():
    sq = [line((0, 0), (10, 0)), line((10, 5), (10, 0)), line((10, 5), (0, 5)), line((0, 0), (0, 5))]
    out, made = LS.glue(sq)
    check("склейка: 4 отрезка (два развёрнуты) — замкнутый прямоугольник 10×5", len(out) == 1 and G.is_closed(out[0])
          and abs(G.area(out[0]) - 50) < 1e-9 and len(made) == 1 and len(made[0][0]) == 4)
    br = [line((0, 0), (10, 0)), line((10, 0), (20, 0)), line((10, 0), (10, 10))]
    out, made = LS.glue(br)
    check("склейка: узел из трёх концов — цепочки там кончаются (ничего не склеено)", len(out) == 3 and not made)
    co = [line((0, 0), (10, 0)), line((10, 0), (20, 0), coedge=1)]
    check("склейка: линия общего реза — не склеивается", len(LS.glue(co)[0]) == 2)
    ly = [line((0, 0), (10, 0)), line((10, 0), (20, 0), layer=2)]
    check("склейка: разные слои — не склеиваются", len(LS.glue(ly)[0]) == 2)
    ch = [line((0, 0), (10, 0)), poly([(10, 0, 0.4), (20, 0, 0), (20, 10, 0)], 0)]
    out, made = LS.glue(ch)
    check("склейка: отрезок + полилиния с дугой — одна открытая, bulge дуги сохранён",
          len(out) == 1 and not G.is_closed(out[0]) and out[0]["verts"][1][2] == 0.4 and abs(G.length(out[0]) - sum(G.length(x) for x in ch)) < 1e-9)
    lp = [poly([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 0.005, 0)], 0)]
    check("склейка: кусок сам с собой (концы в 0,005 мм) — не трогается (это heal_outer)", LS.glue(lp)[0] == lp)


# ======================================================================================= 4) внешний контур из кусков
def ring_unit():
    def rect_pieces(g):
        """Прямоугольник 100×50 из 4 кусков «уголком», промежутки g посередине сторон."""
        h = g / 2
        return [[(50 + h, 0, 0), (100, 0, 0), (100, 25 - h, 0)], [(100, 25 + h, 0), (100, 50, 0), (50 + h, 50, 0)],
                [(50 - h, 50, 0), (0, 50, 0), (0, 25 + h, 0)], [(0, 25 - h, 0), (0, 0, 0), (50 - h, 0, 0)]]
    V, gaps, why, rest, mode = G.heal_ring(rect_pieces(4), 5)
    check("heal_ring: 4 куска, промежутки 4 мм по краю габарита, допуск 5 — замкнут, площадь 5000",
          V is not None and abs(abs(G.poly_area(V)) - 5000) < 1e-6 and all(abs(g - 4) < 1e-9 for g in gaps) and not rest)
    check("heal_ring: допуск 3 — («big», наибольший)", G.heal_ring(rect_pieces(4), 3)[2][0] == "big")
    diag = [[(0, 0, 0), (100, 0, 0), (100, 50, 0), (10, 50, 0)], [(0, 40, 0), (0, 0, 0)]]
    check("heal_ring: косой промежуток через угол — («line», 0)", G.heal_ring(diag, 20)[2] == ("line", 0))
    # отбортовка, как у зольника: кромка корпуса заходит на 2 мм за угол отбортовки (внахлёст), с обеих сторон
    body = [(15, 100, 0), (0, 100, 0), (0, 0, 0), (300, 0, 0), (300, 100, 0), (283, 100, 0)]
    tab = [(285, 100, 0), (285, 120, 0), (13, 120, 0), (13, 100, 0)]
    V, gaps, why, rest, mode = G.heal_ring([body, tab], 5)
    area = 300 * 100 + 272 * 20
    check("heal_ring: внахлёст — контур по углу (площадь корпус + отбортовка), заходы по 2 мм — отдельно",
          V is not None and abs(abs(G.poly_area(V)) - area) < 1e-6 and len(rest) == 2 and
          sorted(round(math.dist(p, q), 6) for p, q in rest) == [2, 2], "%s %s" % (V and abs(G.poly_area(V)), mode))


# ======================================================================================================= 5) программа
def lxds_program(td):
    outer = marker(0)
    slot = [line((50, 45), (80, 45)), marker(1), line((80, 55), (50, 55)), marker(2)]
    engr = marker(3, layer=2)
    word = marker(4, layer=2)
    A = dict(name="Безье", qty=3, shapes=slot + [engr, word, outer], src="x")
    rect = dict(name="Одна фигура", qty=2, shapes=[poly([(0, 0, 0), (60, 0, 0), (60, 40, 0), (0, 40, 0)], 1)], src="x")
    old = dict(name="Старая запись", qty=1, shapes=[marker(5, layer=2), poly([(0, 0, 0), (50, 0, 0), (50, 50, 0), (0, 50, 0)], 1)], src="x")
    repl = {0: ("bez", rounded_rect(200, 100, 10), True, 0.0),
            1: ("arc", (80, 50), 5, True, -math.pi / 2, math.pi),
            2: ("arc", (50, 50), 5, True, math.pi / 2, math.pi),
            3: ("bez", [corner((150, 50), 20, 0)], False, 0.0),
            4: ("text", "AB", 2),
            5: ("v5", (10, 10), (40, 10))}
    raw0 = program([A, rect, old])
    raw = patch(raw0, repl, single=("Одна фигура",))
    ps, info = parts_from_lxds(raw, "syn.lxds")
    by = {p["name"]: p for p in ps}
    a = by.get("Безье")
    ok = a is not None
    if ok:
        o = a["shapes"][-1]
        holes = [s for s in a["shapes"][:-1] if G.is_closed(s) and s["layer"] == 1]
        eng = [s for s in a["shapes"] if s["layer"] == 2]
        check("деталь из кривой Безье: внешний замкнут, скруглённый прямоугольник 200×100 (площадь, габарит)",
              G.is_closed(o) and o["outer"] == 1 and abs(G.area(o) - (20000 - (4 - math.pi) * 100)) < 0.5 and
              abs(G.bbox([o])[2] - 200) < 1e-6 and abs(G.bbox([o])[3] - 100) < 1e-6, "%.3f" % G.area(o))
        check("паз из двух дуг и двух отрезков — склеен в один замкнутый контур (площадь 30×10 + π·25)",
              len(holes) == 1 and abs(G.area(holes[0]) - (300 + math.pi * 25)) < 1e-6, str([round(G.area(h), 3) for h in holes]))
        check("гравировка кривой Безье — открытая ломаная слоя 2; надпись — не фигура", len(eng) == 1 and not G.is_closed(eng[0])
              and abs(G.length(eng[0]) - 20 * math.pi / 2) < 0.05, "%.3f" % (G.length(eng[0]) if eng else -1))
        w = " | ".join(a["warnings"])
        check("предупреждения детали: надпись «AB», кривые Безье (2), склейка 1 контура из 4 кусков",
              "«AB»" in w and "кривые Безье (2)" in w and "склеены" in w and "из 4 кусков" in w, w)
        check("количество — Amount (у сборщика — сколько разложено: 1)", a["qty"] == 1)
    check("деталь «Безье» прочитана", ok)
    r = by.get("Одна фигура")
    check("деталь из одной фигуры без блока (ShapeCls) — прямоугольник 60×40, внешний",
          r is not None and len(r["shapes"]) == 1 and abs(G.area(r["shapes"][0]) - 2400) < 1e-9 and r["shapes"][0]["outer"] == 1)
    o = by.get("Старая запись")
    check("запись признаков CypCut 2023 (Shape версии 5) — читается, отрезок на месте, слой 2 сохранён",
          o is not None and any(s["kind"] == "Line" and s["layer"] == 2 and abs(G.length(s) - 30) < 1e-9 for s in o["shapes"]))
    # ошибки — с именем детали; вне деталей — нет
    raw2 = patch(raw0, {**repl, 1: ("badarc",)}, single=("Одна фигура",))
    msg = err(lambda: parts_from_lxds(raw2, "b.lxds"))
    check("нечитаемая дуга в детали — ошибка с именем детали и классом", "«Безье»" in msg and "Arc" in msg and "не читается" in msg, msg[:160])
    raw3 = patch(raw0, {**repl, 1: ("unk", "Spline")})
    msg = err(lambda: parts_from_lxds(raw3, "u.lxds"))
    check("неизвестный класс в детали — ошибка с именем детали и классом", "«Безье»" in msg and "Spline" in msg, msg[:160])
    raw4 = patch(raw0, repl, extra_unref=True)
    check("испорченная дуга вне деталей — программа читается", err(lambda: parts_from_lxds(raw4, "e.lxds")) == "принято")
    # внешний контур из 4 кусков «уголком» с промежутками 4 мм посередине сторон
    P = dict(name="Рамка", qty=1, shapes=[dict(kind="Circle", c=(50.0, 25.0), r=5.0, a0=0.0, **base())] +
             [poly(c, 0) for c in [[(52, 0, 0), (100, 0, 0), (100, 23, 0)], [(100, 27, 0), (100, 50, 0), (52, 50, 0)],
                                   [(48, 50, 0), (0, 50, 0), (0, 27, 0)], [(0, 23, 0), (0, 0, 0), (48, 0, 0)]]], src="x")
    rawp = program([P])
    msg = err(lambda: parts_from_lxds(rawp, "r.lxds"))
    check("внешний из 4 кусков с промежутками 4 мм, без допуска — ошибка: куски, промежутки, подсказка «до 4 мм»",
          "из 4 кусков" in msg and "4, 4, 4, 4 мм" in msg and "до 4 мм" in msg and "--" not in msg, msg[:220])
    ps, info = parts_from_lxds(rawp, "r.lxds", 5)
    o = ps[0]["shapes"][-1]
    check("с допуском 5 — закрыт: внешний 100×50, отверстие на месте, предупреждение о промежутках",
          G.is_closed(o) and abs(G.area(o) - 5000) < 1e-6 and len(ps[0]["shapes"]) == 2 and
          any("закрыты прямыми" in w for w in info["warnings"]), str(info["warnings"]))
    # чертёж CypCut и не zip
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("content.xml", '<PackData DocType="Model2D"/>')
        z.writestr("Model2D/content.xml", "<Model2D/>")
    msg = err(lambda: parts_from_lxds(b.getvalue(), "ч.lxds"))
    check("чертёж CypCut (Model2D, без списка деталей) — «это чертёж … без раскроя»", "это чертёж CypCut без раскроя" in msg, msg)
    msg = err(lambda: parts_from_lxds(b"not a zip", "x.lxds"))
    check("не zip — «повреждён (не zip-архив)»", "повреждён (не zip-архив)" in msg, msg)
    return raw


# ================================================================================================= 6) сквозной прогон
def end2end(td, raw):
    p = os.path.join(td, "кривые.lxds")
    open(p, "wb").write(raw)
    res, raw_out, pl, parts = run([p], 1250, 2500, 2, 2, 1.5, log=quiet)
    bad = [c[0] for c in res["checks"] if c[1] is False]
    check("run() на программе с кривыми и дугами: программа собрана, все проверки", res["ok"] and not bad, "; ".join(bad))
    want = sum(p_["qty"] * sum(G.length(s) for s in p_["shapes"] if s["layer"] == 1) for p_ in parts)
    ps2, _ = parts_from_lxds(raw_out, "out.lxds")
    cut2 = sum(q["qty"] * sum(G.length(s) for s in q["shapes"] if s["layer"] == 1) for q in ps2)
    check("готовая программа читается обратно: те же детали, длина реза деталей та же",
          sorted(q["name"] for q in ps2) == sorted(p_["name"] for p_ in parts) and abs(cut2 - want) < 0.01 * max(1, len(parts)),
          "%.2f / %.2f" % (cut2, want))


if __name__ == "__main__":
    arc_unit()
    bezier_unit()
    glue_unit()
    ring_unit()
    with tempfile.TemporaryDirectory() as td:
        raw = lxds_program(td)
        end2end(td, raw)
    print("\n%s" % ("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %d" % len(fails)))
    sys.exit(1 if fails else 0)
