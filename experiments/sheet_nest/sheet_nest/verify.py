# -*- coding: utf-8 -*-
"""Проверки собранной программы — где можно, независимо от сборщика (расшифровщик отчётов писался по другим файлам).

    rep = check(raw, parts, layouts, gap, edge)    # [(название, ок, подробности)]; ок: True / False / None — предупреждение
"""
import io, math, os, tempfile, collections, copy, zipfile
from .libpath import vn
from . import geom as G
from .write_lxds import exact_coedge
from .route import LEAD_FREE, lead_free
from . import coedge as CE


def canon(s, tol=4):
    """Фигура без учёта направления (открытые) и точки врезки (замкнутые)."""
    r = lambda v: round(v + 0.0, tol)
    if s["kind"] == "Line":
        a, b = (r(s["p1"][0]), r(s["p1"][1])), (r(s["p2"][0]), r(s["p2"][1]))
        return ("L", s["layer"], tuple(sorted([a, b])))
    if s["kind"] == "Circle":
        return ("C", s["layer"], r(s["c"][0]), r(s["c"][1]), r(s["r"]))
    v = [(r(x), r(y), r(b)) for x, y, b in s["verts"]]
    if s["flag"] & 1:
        k = min(range(len(v)), key=lambda i: v[i])
        return ("P", s["layer"], tuple(v[k:] + v[:k]))
    fw = tuple(v[:-1] + [(v[-1][0], v[-1][1], 0.0)])
    w = [(r(x), r(y), r(b)) for x, y, b in G.reverse(s)["verts"]]
    bw = tuple(w[:-1] + [(w[-1][0], w[-1][1], 0.0)])
    return ("O", s["layer"], min(fw, bw))


def _rd_ent(s):
    if s["kind"] == "Line":
        return {"kind": "Line", "pts": [tuple(s["p1"]), tuple(s["p2"])], "bulge": [0.0, 0.0], "closed": False}
    if s["kind"] == "Circle":
        return {"kind": "Circle", "pts": [(0, 0)], "bulge": [0.0], "closed": True, "circle": (s["c"][0], s["c"][1], s["r"], s["a0"])}
    return {"kind": "LwPolyline", "pts": [(x, y) for x, y, b in s["verts"]], "bulge": [b for x, y, b in s["verts"]], "closed": bool(s["flag"] & 1)}


def check(raw, parts, layouts, gap, edge, thickness=None):
    SR, LR, XV, SV = vn.spec_rebuild, vn.lxds_reader, vn.xml_validate, vn.spec_verify
    rep = []
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "x.lxds")
        open(path, "wb").write(raw)
        R = XV.validate(path, quiet=True)
        fails = [(n, d) for s_, n, d in R.rows if s_ == "FAIL"]
        rep.append(("целостность (xml_validate)", not fails, "%d правил, ошибок %d %s" % (len(R.rows), len(fails), fails[:3])))
        Gc = collections.defaultdict(collections.Counter); Gc["files"], Gc["geo"], Gc["attrs"] = {}, {}, {}
        SV.check(path, Gc)
        ok_bins = not Gc["geo_obj_match"][False] and not Gc["shp_obj_match"][False]
        rep.append(("двоичные данные, независимая сборка (spec_verify)", ok_bins,
                    "геометрия %s, атрибуты %s" % (dict(Gc["geo_obj_match"]), dict(Gc["shp_obj_match"]))))
    with exact_coedge():
        M2 = SR.decompile(raw)
        raw2, _ = SR.compile_lxds(copy.deepcopy(M2), collections.defaultdict(collections.Counter))
    rep.append(("разбор → сборка даёт тот же файл", raw2 == raw, "%d Б" % len(raw)))

    # блоки деталей = детали (с точностью до сдвига); вставки = деталь, повёрнутая и сдвинутая как в раскрое
    bn = {b["name"]: b for b in M2["blocks"]}
    by_name = {}
    for i, p in enumerate(parts):
        by_name.setdefault(p["name"], i)
    bad_blocks = []
    for p in M2["parts"]:
        i = by_name.get(p["name"])
        g = bn[p["block"]]["shapes"]
        if i is None:
            bad_blocks.append(p["name"]); continue
        e = parts[i]["shapes"]
        x0, y0, _, _ = G.bbox([g[-1]])
        ok = len(e) == len(g) and collections.Counter(canon(G.translate(s, -x0, -y0)) for s in g) == collections.Counter(canon(s) for s in e)
        if not ok:
            bad_blocks.append(p["name"])
    rep.append(("блоки деталей = детали заказа (все контуры и слои)", not bad_blocks, "расхождения: %s" % bad_blocks if bad_blocks else "%d из %d" % (len(M2["parts"]), len(M2["parts"]))))
    pby = {p["handle"]: p for p in M2["parts"]}
    gby = {g["handle"]: g for g in M2["groups"]}
    bad_ins, order_bad, cnt = 0, 0, collections.Counter()
    gstat = collections.Counter()
    shared_total = 0.0                                  # общие кромки (режутся один раз) × листы — для длины реза
    for r, lay in zip(M2["results"], layouts):
        groups = lay.get("groups") or []
        in_g = {i for g in groups for i in g}
        want_pl = collections.Counter()
        for k, q in enumerate(lay["placed"]):
            if k in in_g:
                continue
            want_pl[tuple(sorted(collections.Counter(canon(G.transform(s, q["rot"], (q["dx"], q["dy"]))) for s in parts[q["part"]]["shapes"]).items()))] += 1
        want_g = []
        for g in groups:
            outs = [G.transform(parts[lay["placed"][k]["part"]]["shapes"][-1], lay["placed"][k]["rot"], (lay["placed"][k]["dx"], lay["placed"][k]["dy"])) for k in g]
            inner = collections.Counter(canon(G.transform(s, lay["placed"][k]["rot"], (lay["placed"][k]["dx"], lay["placed"][k]["dy"])))
                                        for k in g for s in parts[lay["placed"][k]["part"]]["shapes"][:-1])
            sh_len = sum(CE.shared_length(outs[a]["verts"], outs[b]["verts"]) for a in range(len(outs)) for b in range(a + 1, len(outs)))
            want_g.append(dict(outs=outs, inner=inner, shared=sh_len, used=False,
                               names=collections.Counter(parts[lay["placed"][k]["part"]]["name"] for k in g)))
        got_pl = collections.Counter()
        for ins in r["inserts"]:
            sh = bn[ins["block"]]["shapes"]
            if ins["ref"][0] == "NestGroup":
                grp = gby[ins["ref"][1]]
                for o in grp["objects"]:
                    cnt[pby[o]["name"]] += r["plate_amount"]
                gstat["групп"] += 1
                ok, why = _check_group(sh, want_g, collections.Counter(pby[o]["name"] for o in grp["objects"]))
                if not ok:
                    gstat["групп с ошибкой"] += 1
                    gstat["последняя причина: " + why] += 1
                else:
                    shared_total += ok["shared"] * r["plate_amount"]
                continue
            got_pl[tuple(sorted(collections.Counter(canon(s) for s in sh).items()))] += 1
            closed = [s for s in sh if G.is_closed(s) and s["layer"] == 1]
            order_bad += not (closed and sh[-1] is closed[-1] and sh[-1]["outer"] == 1 and G.area(sh[-1]) >= max(G.area(s) for s in closed) - 1e-6)
            cnt[pby[ins["ref"][1]]["name"]] += r["plate_amount"]
        bad_ins += want_pl != got_pl or any(not w["used"] for w in want_g)
    rep.append(("детали на листах = раскрой (поворот, место, все контуры)", bad_ins == 0, "раскладок с расхождением %d" % bad_ins))
    rep.append(("внешний контур режется последним", order_bad == 0, "нарушений %d" % order_bad))
    if gstat["групп"]:
        bad = [k for k in gstat if isinstance(k, str) and k.startswith("последняя причина")]
        rep.append(("группы общего реза: детали, контуры по одному разу, цепочки от вырезанного, отверстия раньше контура",
                    gstat["групп с ошибкой"] == 0, "групп %d, с ошибкой %d %s" % (gstat["групп"], gstat["групп с ошибкой"], "; ".join(b[19:] for b in bad)[:200])))
    want_cnt = collections.Counter()
    for p in parts:
        want_cnt[p["name"]] += p["qty"]
    rep.append(("количество деталей = заказ", cnt == want_cnt, "%d шт" % sum(cnt.values())))

    r, ctx = LR.build(raw, name="программа", thickness=thickness or 1.0, min_side=300)
    rep.append(("расшифровщик: детали = заказ", collections.Counter(r["parts_total"]) == want_cnt, "%d шт" % sum(r["parts_total"].values())))
    rep.append(("листов = раскрой", r["sheets"] == sum(l["amount"] for l in layouts), "%d листов, %d раскладок" % (r["sheets"], len(r["layouts"]))))
    # холостой ход — по разобранной программе (порядок записей), замкнутая полилиния — от вершины sp: расшифровщик
    # отчётов режет от вершины 0 и в группах общего реза ошибается (разбор 13.10)
    idle_lay = []
    for res_ in M2["results"]:
        pos, s_ = (0.0, 0.0), 0.0
        for ins in res_["inserts"]:
            for s in bn[ins["block"]]["shapes"]:
                a, b = G.ends(s)
                s_ += math.dist(pos, a); pos = b
        idle_lay.append(s_)
    dif = max((abs(a - l["idle"]) for a, l in zip(idle_lay, layouts) if "idle" in l), default=0.0)
    rep.append(("холостой ход по программе = расчёт (каждая раскладка)", dif < 1.0,
                "%.1f м, наибольшее расхождение %.0f мм" % (sum(a * res_["plate_amount"] for a, res_ in zip(idle_lay, M2["results"])) / 1000, dif)))
    cut_e = sum(p["qty"] * sum(LR.elen(_rd_ent(s)) for s in p["shapes"] if s["layer"] != 2) for p in parts) - shared_total
    eng_e = sum(p["qty"] * sum(LR.elen(_rd_ent(s)) for s in p["shapes"] if s["layer"] == 2) for p in parts)
    cut_p = sum(d["sheets"] * sum(LR.elen(e) for e in d["_ents"] if e["layer"] != 2) for d in ctx["lays"])
    eng_p = sum(d["sheets"] * sum(LR.elen(e) for e in d["_ents"] if e["layer"] == 2) for d in ctx["lays"])
    rep.append(("длина реза = детали × количество%s" % (" − общие кромки" if shared_total else ""), abs(cut_p - cut_e) < 1,
                "%.2f м против %.2f м%s" % (cut_p / 1000, cut_e / 1000, (", общий рез сберёг %.2f м" % (shared_total / 1000)) if shared_total else "")))
    rep.append(("длина гравировки = детали × количество", abs(eng_p - eng_e) < 1, "%.2f м против %.2f м" % (eng_p / 1000, eng_e / 1000)))
    sizes = [tuple(map(float, l["plate_mm"])) for l in r["layouts"]]
    rep.append(("размеры листов = раскрой", sizes == [(float(l["W"]), float(l["L"])) for l in layouts], ", ".join("%g×%g" % s for s in sorted(set(sizes)))))
    e_min = min(l["edge_min_mm"] for l in r["layouts"])
    rep.append(("до края листа ≥ %g мм" % edge, e_min >= edge - 0.05, "%.2f мм" % e_min))
    if any(l.get("groups") for l in layouts):
        bad_u, dmin = _units_apart(M2, bn)
        rep.append(("между группами и деталями нет общих кромок и пересечений (вплотную — допустимо)", bad_u == 0,
                    ("нарушений %d, наименьшее расстояние %.3f мм" % (bad_u, dmin)) if dmin is not None else "на листах по одной группе"))
    else:
        gaps = [g for g in (vn.lxds_write.gap_min(ctx["prog"], d["index"], LR) for d in ctx["lays"]) if g is not None]
        rep.append(("зазор между деталями ≥ %g мм" % gap, all(g >= gap - 0.01 for g in gaps), ("мин %.3f мм" % min(gaps)) if gaps else "по одной детали"))
    # место под подвод: независимо от маршрутизатора — по прочитанной программе
    lay_by = {l["index"]: l for l in ctx["prog"].layouts}
    lead_min = None
    for d, l in zip(ctx["lays"], layouts):
        lay = lay_by[d["index"]]
        if l.get("groups"):
            continue                       # у групп общего реза врезка — в свободном углу первой детали, подвод CypCut
        outs = []
        for b in lay["inserts"]:
            cl = [ctx["prog"].shapes[h] for h in ctx["prog"].blocks[b] if h in ctx["prog"].shapes and ctx["prog"].shapes[h]["closed"]]
            outs.append(max(cl, key=LR.earea))
        polys = []
        for o in outs:
            P = LR.points(o, 16)
            polys.append((P, (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P))))
        for j, o in enumerate(outs):
            if o.get("circle"):
                cx, cy, rr, a0 = o["circle"]
                st = dict(kind="Circle", c=(cx, cy), r=rr, a0=a0)
            else:
                st = dict(kind="LwPolyline", verts=[(x, y, b) for (x, y), b in zip(o["pts"], o["bulge"])], flag=1)
            fr = lead_free(st, l["W"], l["L"], [p for k, p in enumerate(polys) if k != j])
            lead_min = fr if lead_min is None else min(lead_min, fr)
    # предупреждение, а не ошибка: на плотной раскладке мелких деталей 10 мм у каждой детали может не найтись —
    # тогда подвод ставит/укорачивает оператор (у CypCut есть проверка подводов на пересечение)
    rep.append(("место под подвод внешнего контура ≥ %g мм" % LEAD_FREE, True if (lead_min is None or lead_min >= LEAD_FREE - 1e-9) else None,
                ("наименьшее %.1f мм (до 20)%s" % (lead_min, "" if lead_min >= LEAD_FREE - 1e-9
                                                    else " — подвод у таких деталей проверить/укоротить в CypCut"))
                if lead_min is not None else "отдельных деталей нет — у групп общего реза врезка в свободном углу, подвод CypCut"))
    util_ok = all(abs(l["util_cypcut"] - l["util_calc_cypcut"]) < 0.01 for l in r["layouts"])
    rep.append(("загрузка в файле = своя по геометрии", util_ok, ", ".join("%.1f%%" % l["util_cypcut"] for l in r["layouts"])))
    warns = [w for w in r["warnings"] if "от края" not in w and "толщин" not in w]
    rep.append(("расшифровщик без предупреждений", not warns, "; ".join(warns)[:300]))
    return rep, r, ctx


def _check_group(sh, want_g, names):
    """Блок группы общего реза против ожидаемой группы (детали раскроя): внутренние контуры — те же; внешние куски
    покрывают контуры всех деталей, без пропусков и без двойного реза; каждая цепочка начинается и кончается на уже
    вырезанном; у каждой детали отверстия режутся раньше, чем её контур замкнётся; последний контур — цепочка."""
    inner = collections.Counter(canon(s) for s in sh if not s["outer"])
    pieces = [(k, s) for k, s in enumerate(sh) if s["outer"]]
    w = next((w for w in want_g if not w["used"] and w["inner"] == inner and w["names"] == names), None)
    if w is None:
        return False, "состав группы или её отверстия не совпали с раскроем"
    w["used"] = True
    segs = []
    for k, s in pieces:
        P = G.points(s, 0.01)
        segs += [(a, b) for a, b in zip(P, P[1:] + (P[:1] if G.is_closed(s) else []))]
    # покрытие: точки контуров деталей лежат на кусках
    for o in w["outs"]:
        for x in G.points(o, 0.05)[::2]:
            if min(G.seg_point_dist(x, a, b) for a, b in segs) > 0.01:
                return False, "контур детали не прорезан у точки (%.1f; %.1f)" % x
    plen = sum(G.length(s) for k, s in pieces)
    want = sum(G.length(o) for o in w["outs"]) - w["shared"]
    if abs(plen - want) > 0.05:
        return False, "длина кусков %.2f против %.2f мм — где-то двойной рез или пропуск" % (plen, want)
    # цепочки — от вырезанного к вырезанному
    done = []
    for k, s in pieces:
        if not G.is_closed(s):
            for e in G.ends(s):
                if not done or min(G.seg_point_dist(e, a, b) for a, b in done) > 1e-3:
                    return False, "цепочка начинается/кончается не на вырезанном (%.1f; %.1f)" % e
        P = G.points(s, 0.01)
        done += [(a, b) for a, b in zip(P, P[1:] + (P[:1] if G.is_closed(s) else []))]
    if sh[-1]["outer"] != 1 or G.is_closed(sh[-1]):
        return False, "последний контур группы — не цепочка"
    # отверстия детали — раньше, чем её контур замкнётся (после внутреннего контура должен остаться кусок её контура)
    outs_pts = [[(v[0], v[1]) for v in o["verts"]] for o in w["outs"]]
    for k, s in enumerate(sh):
        if s["outer"]:
            continue
        # принадлежность детали — по точке посередине фигуры (риска может начинаться прямо на кромке)
        Ps = G.points(s, 0.05)
        if s["kind"] == "Circle":
            x = tuple(s["c"])
        else:
            x = _midpoint(Ps)
        m = next((i for i, P in enumerate(outs_pts) if G.inside(x, P)), None)
        if m is None:
            return False, "внутренний контур вне деталей группы"
        Pm = w["outs"][m]
        later = [s2 for k2, s2 in pieces if k2 > k]
        if not any(min(_dist_to_shape(q, Pm) for q in G.points(s2, 0.5)[:3]) < 1e-3 for s2 in later):
            return False, "отверстие детали режется после того, как её контур замкнут"
    return dict(shared=w["shared"]), ""


def _dist_to_shape(q, s):
    P = G.points(s, 0.01)
    return min(G.seg_point_dist(q, a, b) for a, b in zip(P, P[1:] + P[:1]))


def _units_apart(M2, bn):
    """Внешние куски разных вставок: общих участков быть не должно (иначе двойной рез — надо было в одну группу),
    пересечений — тоже. Вернуть (нарушений, наименьшее расстояние)."""
    bad, dmin = 0, 1e9
    for r in M2["results"]:
        units = []
        for ins in r["inserts"]:
            sh = [s for s in bn[ins["block"]]["shapes"] if s["outer"] or (G.is_closed(s) and s is bn[ins["block"]]["shapes"][-1])]
            pts = [p for s in sh for p in G.points(s, 0.05)]
            if not pts:
                continue
            bx = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
            units.append((sh, pts, bx))
        for i in range(len(units)):
            for j in range(i + 1, len(units)):
                a, b = units[i][2], units[j][2]
                if a[0] > b[2] + 1 or b[0] > a[2] + 1 or a[1] > b[3] + 1 or b[1] > a[3] + 1:
                    continue
                segsB = [(p, q) for s in units[j][0] for P in [G.points(s, 0.05)] for p, q in zip(P, P[1:] + (P[:1] if G.is_closed(s) else []))]
                on = 0
                for x in units[i][1]:
                    d = min(G.seg_point_dist(x, p, q) for p, q in segsB)
                    dmin = min(dmin, d)
                    on += d < 1e-3
                # больше пары точек вплотную (касание углом — 1–2 точки) — общий участок между разными вставками
                if on > 4:
                    bad += 1
    return bad, (dmin if dmin < 1e9 else None)


def _midpoint(P):
    """Точка посередине ломаной по длине (интерполяция внутри участка)."""
    L = [0.0]
    for a, b in zip(P, P[1:]):
        L.append(L[-1] + math.dist(a, b))
    half = L[-1] / 2
    for i in range(1, len(P)):
        if L[i] >= half - 1e-12:
            seg = L[i] - L[i - 1]
            t = 0.0 if seg == 0 else (half - L[i - 1]) / seg
            return (P[i - 1][0] + (P[i][0] - P[i - 1][0]) * t, P[i - 1][1] + (P[i][1] - P[i - 1][1]) * t)
    return P[0]
