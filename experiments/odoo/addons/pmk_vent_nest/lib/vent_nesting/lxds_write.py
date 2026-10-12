# -*- coding: utf-8 -*-
"""Раскрой вентзонтов → программа для лазера CypCut (.lxds), готовая к открытию на ПК инженера.

Вызывать через vent_nesting.api.build_lxds (ERP) или python3 -m vent_nesting.cli lxds (командная строка).
Сначала решение, потом файл (Антон 11.10): собирается ТОЛЬКО выбранный вариант — по программе на материал.

Формат CypCut расшифрован (cypcut/, docs/LXDS_FORMAT.md): эталонный сборщик spec_rebuild пересобирает
5 заводских программ байт в байт. Здесь — перевод модели раскроя (model.py) в его модель: детали (внешний
контур — полилиния с дугами, отверстия — окружности, пазы — полилинии), листы 1250 × L (несколько длин в одном
файле — проверено на станке 12.10.2026), раскладки с поворотом 0/90/180/270 без зеркала. Подводы и параметры
резки ставит оператор на станке (параметры резки — шаблон из заводской программы).
"""
import sys, os, io, math, json, random, hashlib, datetime, collections, contextlib, copy

HERE = os.path.dirname(os.path.abspath(__file__))
from . import nest as N
from . import model as LM
from . import contours as C
from .cypcut import spec_rebuild as SR
from .cypcut import spec_verify as SV
from .cypcut import xml_validate as XV

TECHNICAL = os.path.join(HERE, "cypcut", "technical_template.xml")
BAD_NAME = str.maketrans({c: "" for c in "&<>\"'"})


# ------------------------------------------------------------------ контуры → фигуры CypCut
def _lw(pts, outer=0):
    return dict(handle=None, kind="LwPolyline", layer_name="0", verts=[(float(x), float(y), float(b)) for x, y, b in pts],
                flag=1, sp=0.0, layer=1, coedge=0, flag64=0, outer=outer, lead=None)


def _circ(x, y, r):
    return dict(handle=None, kind="Circle", layer_name="0", c=(float(x), float(y)), r=float(r), a0=math.pi / 4,
                layer=1, coedge=0, flag64=0, outer=0, lead=None)


def _start(s):
    """Точка врезки контура: у окружности — на окружности под углом a0, у полилинии — первая вершина.
    Замкнутый контур кончается там же, где начат."""
    if s["kind"] == "Circle":
        return (s["c"][0] + s["r"] * math.cos(s["a0"]), s["c"][1] + s["r"] * math.sin(s["a0"]))
    return s["verts"][0][:2]


def order_path(pts, start, end=None):
    """Порядок обхода точек: от start, (если задано) с концом поближе к end — ближайший сосед, затем улучшение
    2-opt (распрямить петли) и перестановка одиночных точек (or-opt), пока путь укорачивается.
    Простой «ближайший сосед» бросает точки и возвращается к ним через всю деталь (замечание Антона 12.10)."""
    n = len(pts)
    if n <= 1:
        return list(range(n))
    P = [start] + list(pts) + ([end] if end is not None else [])
    D = lambda a, b: math.dist(P[a], P[b])
    rest, tour, cur = set(range(1, n + 1)), [0], 0
    while rest:
        cur = min(rest, key=lambda k: (D(cur, k), k)); rest.remove(cur); tour.append(cur)
    if end is not None:
        tour.append(n + 1)
    last = len(tour) - (1 if end is not None else 0)          # подвижны tour[1:last]
    improved = True
    while improved:
        improved = False
        for i in range(1, last - 1):                           # 2-opt: развернуть отрезок tour[i..j]
            for j in range(i + 1, last):
                a, b = tour[i - 1], tour[i]
                c = tour[j]; d_ = tour[j + 1] if j + 1 < len(tour) else None
                old = D(a, b) + (D(c, d_) if d_ is not None else 0)
                new = D(a, c) + (D(b, d_) if d_ is not None else 0)
                if new < old - 1e-9:
                    tour[i:j + 1] = tour[i:j + 1][::-1]; improved = True
        for i in range(1, last):                               # or-opt: переставить одну точку в лучшее место
            k = tour[i]
            p_, n_ = tour[i - 1], (tour[i + 1] if i + 1 < len(tour) else None)
            gain = D(p_, k) + (D(k, n_) - D(p_, n_) if n_ is not None else 0)
            t2 = tour[:i] + tour[i + 1:]
            best, bj = 1e-9, None
            for j in range(1, last):                           # вставка между t2[j-1] и t2[j] (j = last-1 → в конец подвижных)
                a_, b_ = t2[j - 1], (t2[j] if j < len(t2) else None)
                cost = D(a_, k) + (D(k, b_) - D(a_, b_) if b_ is not None else 0)
                if gain - cost > best:
                    best, bj = gain - cost, j
            if bj is not None:
                tour = t2[:bj] + [k] + t2[bj:]; improved = True
    return [k - 1 for k in tour[1:last]]


def order_inner(shapes, head):
    """Внутренние контуры — путём от головки (head) к точке врезки внешнего контура; внешний — последним."""
    inner, outer = shapes[:-1], shapes[-1]
    idx = order_path([_start(s) for s in inner], head, _start(outer))
    return [inner[k] for k in idx] + [outer]


def part_shapes(cont):
    """Контуры детали: отверстия и пазы маршрутом от угла детали, внешний — последним (как CypCut)."""
    sh = [_circ(*h) for h in cont["holes"]] + [_lw(s) for s in cont["slots"]] + [_lw(cont["outer"], outer=1)]
    return order_inner(sh, (0.0, 0.0))


def _close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def check_placed(shapes, cont):
    """Фигуры размещения (повёрнутые сборщиком CypCut-правилом) против контуров раскроя (повёрнутых nest-правилом)."""
    want = collections.Counter()
    for x, y, r in cont["holes"]:
        want[("C", round(x, 4), round(y, 4), round(r, 4))] += 1
    for s in cont["slots"] + [cont["outer"]]:
        want[("P", tuple((round(x, 4), round(y, 4), round(b, 6)) for x, y, b in s))] += 1
    got = collections.Counter()
    for s in shapes:
        if s["kind"] == "Circle":
            got[("C", round(s["c"][0], 4), round(s["c"][1], 4), round(s["r"], 4))] += 1
        else:
            got[("P", tuple((round(x, 4), round(y, 4), round(b, 6)) for x, y, b in s["verts"]))] += 1
    return got == want


# ------------------------------------------------------------------ модель раскроя → модель сборщика
def to_lxds(model, title):
    seed = int(hashlib.md5(json.dumps([title, model["source"], [p["name"] for p in model["parts"]],
                                       [(r["size"], r["amount"], len(r["placements"])) for r in model["results"]]],
                                      ensure_ascii=False).encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    guid = lambda: "{%s}" % str(SR.uuid.UUID(int=rng.getrandbits(128), version=4)).upper()
    tmp = iter(range(-100, -10 ** 7, -1))
    blocks, nparts, shapes_of, idx = [], [], {}, {}
    for p in model["parts"]:
        sh = part_shapes(p["contours"])
        for s in sh:
            s["handle"] = next(tmp)
        bn = guid()
        blocks.append(dict(handle=next(tmp), name=bn, role="part", outline_override="derive",
                           given=dict(OutlineID=None, Flags=None, ShapesHandle=None), shapes=sh))
        nparts.append(dict(handle=next(tmp), insert_handle=next(tmp), name=p["name"].translate(BAD_NAME), guid=None, block=bn,
                           given=dict(Amount=None, AmountUsed=None)))
        shapes_of[p["id"]] = sh
        idx[p["id"]] = len(nparts) - 1
    plates = {}
    for r in model["results"]:
        L = float(r["size"][1])
        if L not in plates:
            plates[L] = dict(handle=next(tmp), poly_handle=next(tmp), guid=None, W=float(r["size"][0]), L=L, poly_has_nestplate=True,
                             given=dict(Amount=None, AmountUsed=None, pts=None))
    results, bad = [], 0
    for ri, r in enumerate(model["results"]):
        ins = []
        # порядок деталей на листе = порядок резки: ближайший сосед от угла листа (без возвратов через вырезанное)
        ctr = lambda q: ((min(v[0] for v in q["contours"]["outer"]) + max(v[0] for v in q["contours"]["outer"])) / 2,
                         (min(v[1] for v in q["contours"]["outer"]) + max(v[1] for v in q["contours"]["outer"])) / 2)
        rest, pls, cur = list(r["placements"]), [], (0.0, 0.0)
        while rest:
            q = min(rest, key=lambda q_: math.dist(cur, ctr(q_)))
            rest.remove(q); pls.append(q); cur = ctr(q)
        head = (0.0, 0.0)
        for q in pls:
            src = shapes_of[q["part"]]
            v0 = src[-1]["verts"][0]
            f = SR.ROT[q["rot"]]
            w0 = q["contours"]["outer"][0]
            d = (w0[0] - f(v0[0], v0[1])[0], w0[1] - f(v0[0], v0[1])[1])
            sh = order_inner([SR.transform_shape(s, q["rot"], d, next(tmp)) for s in src], head)
            head = _start(sh[-1])                    # внешний контур кончается в своей точке врезки
            if not check_placed(sh, q["contours"]):
                bad += 1
            bn = "{TMP-R%d-%d}" % (ri, len(ins))
            blocks.append(dict(handle=next(tmp), name=bn, role="insert", outline_override="derive",
                               given=dict(OutlineID=None, Flags=None, ShapesHandle=None), shapes=sh))
            ins.append(dict(handle=next(tmp), ref=("NestPart", nparts[idx[q["part"]]]["handle"]), block=bn, channelport=True, selected=None))
        results.append(dict(index=ri + 1, handle=next(tmp), id=None, flags=None, plate_amount=r["amount"], util_str=None, inserts=ins,
                            given=dict(PartCount=None, PlanCount=None, SizeX=None, SizeY=None, ExtMax=None),
                            plate=plates[float(r["size"][1])]["handle"], plate_shape_handle=next(tmp)))
    if bad:
        raise RuntimeError("размещения не совпали с раскроем: %d" % bad)
    now = datetime.datetime.now().astimezone()
    off_h = int(round(now.utcoffset().total_seconds() / 3600))
    save_utc = now.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    M = dict(app_ver="6.3.907.11", user="vent_nesting", computer="VENT-NESTING", header_id=None, org_app=None,
             vport=None, technical=open(TECHNICAL, "rb").read(), zip_order=None, zip_mtimes=[SR.XZ.filetime(save_utc)],
             utc_offset_h=off_h, emf=dict(device=(2560, 1440), mm=(600, 330), face_tail=b""),
             blocks=blocks, parts=nparts, groups=[], plates=list(plates.values()), results=results)
    SR.fresh_identity(M, rng)
    checks = collections.defaultdict(collections.Counter)
    raw, files = SR.compile_lxds(M, checks, util_mode="computed")
    return raw, M


# ------------------------------------------------------------------ проверки готового файла
def verify(raw, model, path, per_hood=None):
    rep = []
    R = XV.validate(path, quiet=True)
    fails = [(n, d) for s_, n, d in R.rows if s_ == "FAIL"]
    rep.append(("целостность (xml_validate)", not fails, "%d правил, ошибок %d %s" % (len(R.rows), len(fails), fails[:3])))
    G = collections.defaultdict(collections.Counter)
    G["files"], G["geo"], G["attrs"] = {}, {}, {}
    Rv = SV.check(path, G)
    ok_bins = all(v == 0 for k, v in G["geo_obj_match"].items() if k is False) and all(v == 0 for k, v in G["shp_obj_match"].items() if k is False)
    rep.append(("двоичные данные, независимая сборка (spec_verify)", ok_bins, "геометрия %s, атрибуты %s" % (dict(G["geo_obj_match"]), dict(G["shp_obj_match"]))))
    M2 = SR.decompile(raw)
    raw2, _ = SR.compile_lxds(copy.deepcopy(M2), collections.defaultdict(collections.Counter))
    rep.append(("разбор → сборка даёт тот же файл", raw2 == raw, "%d Б" % len(raw)))
    # независимый читатель — расшифровщик отчётов, писался по другим файлам
    from . import lxds_reader as LR
    r, ctx = LR.build(raw, name=os.path.basename(path), thickness=0.65, min_side=None)
    want_parts = {p["name"].translate(BAD_NAME): p["amount"] for p in model["parts"]}
    got_parts = r["parts_total"]
    rep.append(("детали по программе = раскрой", got_parts == want_parts, "%d шт" % sum(got_parts.values())))
    if per_hood is not None:                 # per_hood — из ЗАКАЗА (зонтов × деталей на зонт у генератора), не из раскроя
        got = collections.Counter()
        for p in model["parts"]:
            got[p["hood"]] += p["amount"]
        rep.append(("деталей по каждому зонту = заказ", dict(got) == per_hood,
                    "в программе %s; в заказе %s" % ("; ".join("%s: %d" % (h, n) for h, n in sorted(got.items())),
                                                    "; ".join("%s: %d" % (h, n) for h, n in sorted(per_hood.items())))))
    # контуры модели = исходный DXF (независимо от сцепки contours.chain): каждая дуга проходит через середину дуги DXF,
    # отверстия — те же центры и диаметры
    arc_bad = hole_bad = 0
    for p_ in model["parts"]:
        mids = p_.get("src_arc_mids", [])
        polys = [p_["contours"]["outer"]] + p_["contours"]["slots"]
        for poly in polys:
            for i_, (x1, y1, bu) in enumerate(poly):
                if not bu:
                    continue
                x2, y2, _ = poly[(i_ + 1) % len(poly)]
                mx, my = (x1 + x2) / 2 + bu / 2 * (y2 - y1), (y1 + y2) / 2 - bu / 2 * (x2 - x1)
                if not any(math.hypot(mx - q[0], my - q[1]) <= 0.05 for q in mids):
                    arc_bad += 1
        want_h = sorted((round(h[0], 2), round(h[1], 2), round(h[2], 3)) for h in p_.get("src_holes", []))
        got_h = sorted((round(h[0], 2), round(h[1], 2), round(2 * h[2], 3)) for h in p_["contours"]["holes"])
        if want_h != got_h:
            hole_bad += 1
    rep.append(("контуры деталей = исходный DXF (дуги, отверстия)", arc_bad == 0 and hole_bad == 0,
                "дуг не через DXF %d, деталей с другими отверстиями %d" % (arc_bad, hole_bad)))
    rep.append(("листов = раскрой", r["sheets"] == sum(x["amount"] for x in model["results"]), "%d листов, %d раскладок" % (r["sheets"], len(r["layouts"]))))
    cut_model = sum(x["amount"] * sum(C.length(q["contours"]["outer"]) + sum(C.length(s) for s in q["contours"]["slots"])
                                      + sum(2 * math.pi * h[2] for h in q["contours"]["holes"]) for q in x["placements"]) for x in model["results"])
    cut_prog = sum(d["sheets"] * sum(LR.elen(e) for e in d["_ents"] if e["layer"] != 2) for d in ctx["lays"])   # без округления отчёта
    rep.append(("длина реза = раскрой", abs(cut_prog - cut_model) < 0.5, "%.3f м против %.3f м" % (cut_prog / 1000, cut_model / 1000)))
    sizes_ok = [tuple(l["plate_mm"]) for l in r["layouts"]] == [tuple(x["size"]) for x in model["results"]]
    rep.append(("размеры листов раскладок = раскрой", sizes_ok, ", ".join("%g×%g" % tuple(l["plate_mm"]) for l in r["layouts"])))
    util_ok = all(abs(l["util_cypcut"] - l["util_calc_cypcut"]) < 0.01 for l in r["layouts"])
    rep.append(("загрузка в файле = своя по геометрии", util_ok, ", ".join("%.1f%%" % l["util_cypcut"] for l in r["layouts"])))
    edge = min(l["edge_min_mm"] for l in r["layouts"])
    rep.append(("до края листа ≥ %g мм" % N.EDGE, edge >= N.EDGE - 0.001, "%.2f мм" % edge))
    gaps = [g for g in (gap_min(ctx["prog"], d["index"], LR) for d in ctx["lays"]) if g is not None]
    rep.append(("зазор между деталями ≥ %g мм" % N.GAP, all(g >= N.GAP - 0.01 for g in gaps),
                "мин %.3f мм" % min(gaps) if gaps else "одна деталь на листе"))
    # контуры каждой детали по программе = контуры раскроя (площади: ловят дуги не той стороны, потерянные отверстия)
    # и внешний контур режется последним (иначе деталь выпадет раньше, чем вырежут отверстия)
    prog = ctx["prog"]
    shape_bad, order_bad = [], 0
    for k, x in enumerate(model["results"], 1):
        lay = next((l for l in prog.layouts if l["index"] == k), None)
        got = []
        for b_ in (lay["inserts"] if lay else []):
            areas = [_shape_area(prog.shapes[h]) for h in prog.blocks[b_] if h in prog.shapes and prog.shapes[h]["closed"]]
            if areas and abs(areas[-1] - max(areas)) > 1e-6:
                order_bad += 1
            got.append(sorted(areas))
        want = [sorted([abs(C.area(q["contours"]["outer"]))] + [abs(C.area(s_)) for s_ in q["contours"]["slots"]]
                       + [math.pi * h[2] ** 2 for h in q["contours"]["holes"]]) for q in x["placements"]]
        free = list(range(len(got)))
        for w in want:
            hit = next((i for i in free if len(got[i]) == len(w) and all(abs(a_ - b2) <= 0.01 + 1e-6 * b2 for a_, b2 in zip(got[i], w))), None)
            if hit is None:
                shape_bad.append(k)
            else:
                free.remove(hit)
        if free:
            shape_bad.append(k)
    rep.append(("контуры деталей = раскрой (площадь каждого контура)", not shape_bad,
                "раскладки с расхождением: %s" % sorted(set(shape_bad)) if shape_bad else "все детали совпали"))
    rep.append(("внешний контур режется последним", order_bad == 0, "нарушений %d" % order_bad))
    warns = [w for w in r["warnings"] if "от края" not in w]
    rep.append(("расшифровщик без предупреждений", not warns, "; ".join(warns)[:200]))
    return rep, r


def _shape_area(e):
    """Точная площадь замкнутого контура из прочитанной программы: окружность — πR², полилиния — с дугами (bulge)."""
    if e.get("circle"):
        return math.pi * e["circle"][2] ** 2
    return abs(C.area([(x, y, b) for (x, y), b in zip(e["pts"], e["bulge"])]))


def gap_min(prog, index, LR):
    """Наименьший зазор между внешними контурами соседних деталей раскладки — по прочитанной программе
    (независимо от сборщика). None — на листе одна деталь."""
    import numpy as np
    from . import geom as BG
    lay = next(l for l in prog.layouts if l["index"] == index)
    outs = []
    for b in lay["inserts"]:
        cl = [prog.shapes[h] for h in prog.blocks[b] if h in prog.shapes and prog.shapes[h]["closed"]]
        o = max(cl, key=LR.earea)
        P = np.array(LR.points(o, 64)[:-1])
        outs.append((P, (P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max())))
    best = None
    for i in range(len(outs)):
        for j in range(i + 1, len(outs)):
            (A, a), (B, b) = outs[i], outs[j]
            if a[0] > b[1] + 60 or b[0] > a[1] + 60 or a[2] > b[3] + 60 or b[2] > a[3] + 60:
                continue
            d = BG.seg_dist_min(A, B)
            best = d if best is None else min(best, d)
    return best
