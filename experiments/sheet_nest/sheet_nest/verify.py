# -*- coding: utf-8 -*-
"""Проверки собранной программы — где можно, независимо от сборщика (расшифровщик отчётов писался по другим файлам).

    rep = check(raw, parts, layouts, gap, edge)    # [(название, ок, подробности)]; ок: True / False / None — предупреждение
"""
import io, math, os, tempfile, collections, copy, zipfile
from .libpath import vn
from . import geom as G
from .write_lxds import exact_coedge
from .route import LEAD_FREE, lead_free


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
    bad_ins, order_bad, cnt = 0, 0, collections.Counter()
    for r, lay in zip(M2["results"], layouts):
        want_pl = collections.Counter()
        for q in lay["placed"]:
            want_pl[tuple(sorted(collections.Counter(canon(G.transform(s, q["rot"], (q["dx"], q["dy"]))) for s in parts[q["part"]]["shapes"]).items()))] += 1
        got_pl = collections.Counter()
        for ins in r["inserts"]:
            sh = bn[ins["block"]]["shapes"]
            got_pl[tuple(sorted(collections.Counter(canon(s) for s in sh).items()))] += 1
            closed = [s for s in sh if G.is_closed(s) and s["layer"] == 1]
            order_bad += not (closed and sh[-1] is closed[-1] and sh[-1]["outer"] == 1 and G.area(sh[-1]) >= max(G.area(s) for s in closed) - 1e-6)
            cnt[pby[ins["ref"][1]]["name"]] += r["plate_amount"]
        bad_ins += want_pl != got_pl
    rep.append(("детали на листах = раскрой (поворот, место, все контуры)", bad_ins == 0, "раскладок с расхождением %d" % bad_ins))
    rep.append(("внешний контур режется последним", order_bad == 0, "нарушений %d" % order_bad))
    want_cnt = collections.Counter()
    for p in parts:
        want_cnt[p["name"]] += p["qty"]
    rep.append(("количество деталей = заказ", cnt == want_cnt, "%d шт" % sum(cnt.values())))

    r, ctx = LR.build(raw, name="программа", thickness=thickness or 1.0, min_side=300)
    rep.append(("расшифровщик: детали = заказ", collections.Counter(r["parts_total"]) == want_cnt, "%d шт" % sum(r["parts_total"].values())))
    rep.append(("листов = раскрой", r["sheets"] == sum(l["amount"] for l in layouts), "%d листов, %d раскладок" % (r["sheets"], len(r["layouts"]))))
    idle_lay = []
    for d in ctx["lays"]:
        pos, s_ = (d["_plate"]["x0"], d["_plate"]["y0"]), 0.0
        for e in d["_ents"]:
            s_ += math.dist(pos, e["pts"][0]); pos = e["pts"][0] if e["closed"] else e["pts"][-1]
        idle_lay.append(s_)
    dif = max((abs(a - l["idle"]) for a, l in zip(idle_lay, layouts) if "idle" in l), default=0.0)
    rep.append(("холостой ход по расшифровщику = расчёт (каждая раскладка)", dif < 1.0,
                "%.1f м, наибольшее расхождение %.0f мм" % (sum(a * d["sheets"] for a, d in zip(idle_lay, ctx["lays"])) / 1000, dif)))
    cut_e = sum(p["qty"] * sum(LR.elen(_rd_ent(s)) for s in p["shapes"] if s["layer"] != 2) for p in parts)
    eng_e = sum(p["qty"] * sum(LR.elen(_rd_ent(s)) for s in p["shapes"] if s["layer"] == 2) for p in parts)
    cut_p = sum(d["sheets"] * sum(LR.elen(e) for e in d["_ents"] if e["layer"] != 2) for d in ctx["lays"])
    eng_p = sum(d["sheets"] * sum(LR.elen(e) for e in d["_ents"] if e["layer"] == 2) for d in ctx["lays"])
    rep.append(("длина реза = детали × количество", abs(cut_p - cut_e) < 1, "%.2f м против %.2f м" % (cut_p / 1000, cut_e / 1000)))
    rep.append(("длина гравировки = детали × количество", abs(eng_p - eng_e) < 1, "%.2f м против %.2f м" % (eng_p / 1000, eng_e / 1000)))
    sizes = [tuple(map(float, l["plate_mm"])) for l in r["layouts"]]
    rep.append(("размеры листов = раскрой", sizes == [(float(l["W"]), float(l["L"])) for l in layouts], ", ".join("%g×%g" % s for s in sorted(set(sizes)))))
    e_min = min(l["edge_min_mm"] for l in r["layouts"])
    rep.append(("до края листа ≥ %g мм" % edge, e_min >= edge - 0.05, "%.2f мм" % e_min))
    gaps = [g for g in (vn.lxds_write.gap_min(ctx["prog"], d["index"], LR) for d in ctx["lays"]) if g is not None]
    rep.append(("зазор между деталями ≥ %g мм" % gap, all(g >= gap - 0.01 for g in gaps), ("мин %.3f мм" % min(gaps)) if gaps else "по одной детали"))
    # место под подвод: независимо от маршрутизатора — по прочитанной программе
    lay_by = {l["index"]: l for l in ctx["prog"].layouts}
    lead_min = None
    for d, l in zip(ctx["lays"], layouts):
        lay = lay_by[d["index"]]
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
                "наименьшее %.1f мм (до 20)%s" % (lead_min or 0, "" if (lead_min is None or lead_min >= LEAD_FREE - 1e-9)
                                                    else " — подвод у таких деталей проверить/укоротить в CypCut")))
    util_ok = all(abs(l["util_cypcut"] - l["util_calc_cypcut"]) < 0.01 for l in r["layouts"])
    rep.append(("загрузка в файле = своя по геометрии", util_ok, ", ".join("%.1f%%" % l["util_cypcut"] for l in r["layouts"])))
    warns = [w for w in r["warnings"] if "от края" not in w and "толщин" not in w]
    rep.append(("расшифровщик без предупреждений", not warns, "; ".join(warns)[:300]))
    return rep, r, ctx
