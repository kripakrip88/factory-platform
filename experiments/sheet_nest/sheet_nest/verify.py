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


def check_safe(raw, parts, layouts, gap, edge, thickness=None):
    """Как check, но сломанная программа даёт ✗ «проверка не завершилась», а не падение: всё, что успели проверить,
    остаётся в отчёте. Вернуть (rep, отчёт расшифровщика | None, ctx | None)."""
    rep = []
    try:
        return check(raw, parts, layouts, gap, edge, thickness, rep=rep)
    except Exception as e:
        rep.append(("проверка программы не завершилась — программа повреждена", False, "%s: %s" % (type(e).__name__, e)))
        return rep, None, None


def check(raw, parts, layouts, gap, edge, thickness=None, rep=None):
    SR, LR, XV, SV = vn.spec_rebuild, vn.lxds_reader, vn.xml_validate, vn.spec_verify
    rep = [] if rep is None else rep
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
                               names=collections.Counter(parts[lay["placed"][k]["part"]]["name"] for k in g),
                               member_names=[parts[lay["placed"][k]["part"]]["name"] for k in g]))
        got_pl = collections.Counter()
        for ins in r["inserts"]:
            sh = bn[ins["block"]]["shapes"]
            if ins["ref"][0] == "NestGroup":
                grp = gby[ins["ref"][1]]
                for o in grp["objects"]:
                    cnt[pby[o]["name"] if o in pby else "?нет детали %s" % o] += r["plate_amount"]
                gstat["групп"] += 1
                try:
                    ok, why = _check_group(sh, want_g, collections.Counter(pby[o]["name"] for o in grp["objects"] if o in pby),
                                           [pby[o]["name"] for o in grp["objects"] if o in pby])
                except Exception as e:                      # сломанная программа — ✗, а не падение проверки
                    ok, why = False, "проверка группы упала: %s" % e
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
        badc, exc = 0, ""
        for l in layouts:
            b_, e_ = _plan_clearance(parts, l["placed"])
            badc += b_; exc = exc or e_
        rep.append(("общий рез: детали вплотную без наложений и без опасных сближений (< 1 мм не по кромке)", badc == 0,
                    exc or "нарушений нет"))
        bad_u, dmin = _units_apart(M2, bn)
        rep.append(("между группами и деталями нет общих кромок и пересечений (вплотную — допустимо)", bad_u == 0,
                    ("нарушений %d, наименьшее расстояние %.3f мм" % (bad_u, dmin)) if dmin is not None else "группы и детали дальше 1 мм друг от друга"))
    else:
        gaps = [g for g in (vn.lxds_write.gap_min(ctx["prog"], d["index"], LR) for d in ctx["lays"]) if g is not None]
        rep.append(("зазор между деталями ≥ %g мм" % gap, all(g >= gap - 0.01 for g in gaps), ("мин %.3f мм" % min(gaps)) if gaps else "по одной детали"))
    # место под подвод: точка врезки внешнего контура каждой ОТДЕЛЬНОЙ детали — по прочитанной программе;
    # препятствия — край листа и контуры всех деталей раскладки (и деталей групп общего реза) по плану
    lay_by = {l["index"]: l for l in ctx["prog"].layouts}
    lead_min = None
    for d, l, res_ in zip(ctx["lays"], layouts, M2["results"]):
        lay = lay_by[d["index"]]
        grp_blocks = {ins["block"] for ins in res_["inserts"] if ins["ref"][0] == "NestGroup"}
        plan_polys = []
        for q in l["placed"]:
            P = G.points(G.transform(parts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"])), 0.1)
            plan_polys.append((P, (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P))))
        for b in lay["inserts"]:
            if b in grp_blocks:
                continue                   # у групп общего реза врезка — в свободном углу первой детали, подвод CypCut
            cl = [ctx["prog"].shapes[h] for h in ctx["prog"].blocks[b] if h in ctx["prog"].shapes and ctx["prog"].shapes[h]["closed"]]
            o = max(cl, key=LR.earea)
            if o.get("circle"):
                cx, cy, rr, a0 = o["circle"]
                st = dict(kind="Circle", c=(cx, cy), r=rr, a0=a0)
            else:
                st = dict(kind="LwPolyline", verts=[(x, y, bb) for (x, y), bb in zip(o["pts"], o["bulge"])], flag=1)
            start = G.ends(st)[0]
            own = [pp for pp in plan_polys if not G.inside(start, pp[0]) and min(G.seg_point_dist(start, pp[0][i_ - 1], pp[0][i_]) for i_ in range(len(pp[0]))) <= 0.01]
            others = [pp for pp in plan_polys if pp not in own[:1]]
            fr = lead_free(st, l["W"], l["L"], others)
            lead_min = fr if lead_min is None else min(lead_min, fr)
    # предупреждение, а не ошибка: на плотной раскладке мелких деталей 10 мм у каждой детали может не найтись —
    # тогда подвод ставит/укорачивает оператор (у CypCut есть проверка подводов на пересечение)
    rep.append(("место под подвод внешнего контура ≥ %g мм" % LEAD_FREE, True if (lead_min is None or lead_min >= LEAD_FREE - 1e-9) else None,
                ("наименьшее %.1f мм (до 20)%s" % (lead_min, "" if lead_min >= LEAD_FREE - 1e-9
                                                    else " — подвод у таких деталей проверить/укоротить в CypCut"))
                if lead_min is not None else "отдельных деталей нет — у групп общего реза врезка в свободном углу, подвод CypCut"))
    labelled = [p for p in parts if p.get("label")]
    if labelled:
        bad_l = [p["name"] + ": " + why for p in labelled for why in [_check_label(p)] if why]
        rep.append(("подписи: внутри детали, ≥ %g мм от отверстий, прорезей, язычков и края, штрихи не касаются (≥ %g мм)"
                    % (labelled[0]["label"]["margin"], labelled[0]["label"]["gap"]), not bad_l,
                    "; ".join(bad_l)[:300] if bad_l else "подписано деталей %d" % len(labelled)))
    util_ok = all(abs(l["util_cypcut"] - l["util_calc_cypcut"]) < 0.01 for l in r["layouts"])
    rep.append(("загрузка в файле = своя по геометрии", util_ok, ", ".join("%.1f%%" % l["util_cypcut"] for l in r["layouts"])))
    warns = [w for w in r["warnings"] if "от края" not in w and "толщин" not in w]
    rep.append(("расшифровщик без предупреждений", not warns, "; ".join(warns)[:300]))
    return rep, r, ctx


def _dense(s, step=0.5):
    """Точки по фигуре не реже step мм (и внутри прямых участков — G.points даёт только вершины)."""
    P = G.points(s, 0.01)
    closed = G.is_closed(s)
    out = []
    for a, b in zip(P, P[1:] + (P[:1] if closed else [])):
        n = max(1, int(math.ceil(math.dist(a, b) / step)))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    if not closed:
        out.append(P[-1])
    return out


class _Segs:
    """Отрезки фигур с быстрым отбором по клеткам: расстояние от точки до ближайшего отрезка."""
    def __init__(self, shapes=(), cell=20.0):
        self.cell, self.grid, self.n = cell, collections.defaultdict(list), 0
        for s in shapes:
            self.add(s)

    def add(self, s):
        P = G.points(s, 0.01)
        for a, b in zip(P, P[1:] + (P[:1] if G.is_closed(s) else [])):
            x0, x1 = sorted((a[0], b[0])); y0, y1 = sorted((a[1], b[1]))
            for gx in range(int(math.floor(x0 / self.cell)), int(math.floor(x1 / self.cell)) + 1):
                for gy in range(int(math.floor(y0 / self.cell)), int(math.floor(y1 / self.cell)) + 1):
                    self.grid[(gx, gy)].append((a, b))
            self.n += 1

    def dist(self, x, r=1.0):
        gx, gy = int(math.floor(x[0] / self.cell)), int(math.floor(x[1] / self.cell))
        best = 1e9
        k = int(math.ceil(r / self.cell))
        for dx in range(-k, k + 1):
            for dy in range(-k, k + 1):
                for a, b in self.grid.get((gx + dx, gy + dy), ()):
                    d = G.seg_point_dist(x, a, b)
                    if d < best:
                        best = d
        return best


def _check_group(sh, want_g, names, obj_names):
    """Блок группы общего реза против ожидаемой группы (детали раскроя) — независимо от построения:
    • состав и внутренние контуры — те же; внутренние копии: outer 0, coedge 0, без бита 4, flag64 0;
    • каждая точка контура каждой детали прорезана (через 0,5 мм, и внутри прямых участков), каждая точка кусков
      лежит на контуре какой-то детали; длина кусков = контуры − общие кромки (двойного реза нет);
    • цепочка начинается и кончается на уже вырезанном; последний контур блока — цепочка;
    • отверстия детали режутся раньше, чем её контур будет прорезан целиком;
    • замкнутый кусок: флаг 1 без 4, coedge 0, бит 2 = по часовой, sp целое 0 < sp < n, врезка не на соседе,
      LeadParam = 5×u32 0 + f64 sp + 4×f64 0; цепочка: флаг 4 без 1, coedge 1, sp 0, без LeadParam, бит 2 = по часовой
      вокруг своей детали (по участку, где деталь с одной стороны);
    • порядок записей NestGroup = порядок деталей в блоке (по первому появлению)."""
    inner = collections.Counter(canon(s) for s in sh if not s["outer"])
    pieces = [(k, s) for k, s in enumerate(sh) if s["outer"]]
    if not pieces:
        return False, "в блоке группы нет внешних кусков"
    w = next((w for w in want_g if not w["used"] and w["inner"] == inner and w["names"] == names), None)
    if w is None:
        return False, "состав группы или её отверстия не совпали с раскроем"
    w["used"] = True
    outs = w["outs"]
    for k, s in enumerate(sh):
        if not s["outer"] and (s.get("coedge") or (s["kind"] == "LwPolyline" and s["flag"] & 4) or s.get("flag64")):
            return False, "внутренняя копия с признаком общего реза или flag64"
    P_segs = _Segs([s for k, s in pieces])
    O_segs = _Segs(outs)
    for o in outs:
        for x in _dense(o, 0.5):
            if P_segs.dist(x, 0.05) > 0.01:
                return False, "контур детали не прорезан у точки (%.1f; %.1f)" % x
    for k, s in pieces:
        for x in _dense(s, 0.5):
            if O_segs.dist(x, 0.05) > 0.01:
                return False, "кусок контура не на детали у точки (%.1f; %.1f)" % x
    plen = sum(G.length(s) for k, s in pieces)
    want = sum(G.length(o) for o in outs) - w["shared"]
    if abs(plen - want) > 0.05:
        return False, "длина кусков %.2f против %.2f мм — где-то двойной рез или пропуск" % (plen, want)
    if sh[-1]["outer"] != 1 or G.is_closed(sh[-1]):
        return False, "последний контур группы — не цепочка"
    done = _Segs()
    for k, s in pieces:
        if not G.is_closed(s):
            for e in G.ends(s):
                if done.n == 0 or done.dist(e, 0.05) > 1e-3:
                    return False, "цепочка начинается/кончается не на вырезанном (%.1f; %.1f)" % e
        done.add(s)
    polys = [[(v[0], v[1]) for v in o["verts"]] for o in outs]
    # флаги, sp, LeadParam
    for k, s in pieces:
        V = s["verts"]
        if G.is_closed(s):
            cw = G.poly_area(V) < 0
            if not (s["flag"] & 1) or s["flag"] & 4 or s.get("coedge") or bool(s["flag"] & 2) != cw:
                return False, "замкнутый кусок: флаг %d / coedge %s не по правилу" % (s["flag"], s.get("coedge"))
            sp = s.get("sp") or 0
            if sp != int(sp) or not (0 < sp < len(V)):
                return False, "замкнутый кусок: врезка sp=%s не номер вершины" % sp
            q = V[int(sp)][:2]
            own = [m for m, P in enumerate(polys) if min(G.seg_point_dist(q, P[i - 1], P[i]) for i in range(len(P))) <= 1e-3]
            if len(own) != 1:
                return False, "замкнутый кусок: врезка в углу, общем с соседней деталью (%.1f; %.1f)" % q
            if s.get("lead") not in (None, CE.lead_payload(sp)):
                return False, "замкнутый кусок: LeadParam не совпадает с sp"
        else:
            if s["flag"] & 1 or not (s["flag"] & 4) or s.get("coedge") != 1 or (s.get("sp") or 0) != 0 or s.get("lead") is not None:
                return False, "цепочка: флаг %d / coedge %s / sp / LeadParam не по правилу" % (s["flag"], s.get("coedge"))
            # бит 2: деталь справа по ходу — по часовой; судим по участку, у которого деталь только с одной стороны
            verdict = None
            for (x1, y1, b), (x2, y2, _) in zip(V, V[1:]):
                L = math.hypot(x2 - x1, y2 - y1)
                if L < 0.5 or b:
                    continue
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                nx, ny = (y2 - y1) / L * 0.05, -(x2 - x1) / L * 0.05
                right = [m for m, P in enumerate(polys) if G.inside((mx + nx, my + ny), P)]
                left = [m for m, P in enumerate(polys) if G.inside((mx - nx, my - ny), P)]
                if len(right) + len(left) == 1:
                    verdict = bool(right)
                    break
            if verdict is not None and bool(s["flag"] & 2) != verdict:
                return False, "цепочка: бит 2 (сторона детали) не по ходу"
    # отверстия — раньше, чем контур их детали прорезан целиком; порядок деталей в блоке
    dense_o = [_dense(o, 1.0) for o in outs]
    covered = [set() for _ in outs]
    complete = [None] * len(outs)
    acc = _Segs()
    first_seen, member_of = {}, {}
    for k, s in enumerate(sh):
        if s["outer"]:
            acc.add(s)
            for m, pts in enumerate(dense_o):
                if complete[m] is None:
                    for n_, x in enumerate(pts):
                        if n_ not in covered[m] and acc.dist(x, 0.05) <= 0.01:
                            covered[m].add(n_)
                    if len(covered[m]) == len(pts):
                        complete[m] = k
            continue
        x = tuple(s["c"]) if s["kind"] == "Circle" else _midpoint(_dense(s, 0.5))
        m = next((i for i, P in enumerate(polys) if G.inside(x, P)), None)
        if m is None:
            return False, "внутренний контур вне деталей группы"
        member_of[k] = m
        first_seen.setdefault(m, k)
    for k, m in member_of.items():
        if complete[m] is not None and complete[m] < k:
            return False, "отверстие детали режется после того, как её контур прорезан целиком"
    seen = sorted(first_seen, key=lambda m: first_seen[m])
    if obj_names is not None and seen:
        got = [w["member_names"][m] for m in seen]
        want_o = [n for n in obj_names]
        # детали без внутренних контуров в блоке не видны — сравниваем подпоследовательность
        it = iter(want_o)
        if not all(any(g == n for n in it) for g in got):
            return False, "порядок записей NestGroup не совпадает с порядком деталей в блоке"
    return dict(shared=w["shared"]), ""


def _plan_clearance(parts, placed, safe=1.0, step=0.5):
    """Детали раскроя под общий рез, вплотную: по общей кромке — можно; наложение — нельзя; сближение 0 < d < safe
    не у точек касания — нельзя (рез заденет соседа). Независимо от упаковщика. Вернуть (нарушений, пример)."""
    outs = [G.transform(parts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"])) for q in placed]
    boxes = [G.bbox([o]) for o in outs]
    polys = [G.points(o, 0.05) for o in outs]
    bad, ex = 0, ""
    for i in range(len(outs)):
        for j in range(len(outs)):
            if i == j:
                continue
            a, b = boxes[i], boxes[j]
            if a[0] > b[2] + safe or b[0] > a[2] + safe or a[1] > b[3] + safe or b[1] > a[3] + safe:
                continue
            Sb = _Segs([outs[j]])
            # точки касания: вершины одного контура на другом
            touch = [p for p in polys[i] if Sb.dist(p, 0.05) <= 1e-3] + [p for p in polys[j] if _Segs([outs[i]]).dist(p, 0.05) <= 1e-3]
            for x in _dense(outs[i], step):
                if not (b[0] - safe <= x[0] <= b[2] + safe and b[1] - safe <= x[1] <= b[3] + safe):
                    continue
                d = Sb.dist(x, safe)
                if d <= 1e-3:
                    continue
                if G.inside(x, polys[j]):
                    bad += 1; ex = ex or "наложение деталей у (%.1f; %.1f)" % x
                    break
                if d < safe and not any(math.dist(x, e) <= 3.0 for e in touch):
                    bad += 1; ex = ex or "сближение %.2f мм не по общей кромке у (%.1f; %.1f)" % (d, x[0], x[1])
                    break
    return bad, ex


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


def _units_apart(M2, bn):
    """Внешние куски разных вставок (групп и отдельных деталей) по прочитанной программе: общий участок длиннее 1 мм
    между разными вставками — двойной рез (такие детали должны быть одной группой). Вернуть (нарушений, наименьшее
    расстояние или None, если вставки дальше 1 мм друг от друга)."""
    bad, dmin = 0, None
    for r in M2["results"]:
        units = []
        for ins in r["inserts"]:
            blk = bn[ins["block"]]["shapes"]
            sh = [s for s in blk if s["outer"]] or [blk[-1]]
            pts = [p for s in sh for p in _dense(s, 0.5)]
            if not pts:
                continue
            bx = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
            units.append((sh, pts, bx))
        for i in range(len(units)):
            for j in range(i + 1, len(units)):
                a, b = units[i][2], units[j][2]
                if a[0] > b[2] + 1 or b[0] > a[2] + 1 or a[1] > b[3] + 1 or b[1] > a[3] + 1:
                    continue
                S = _Segs(units[j][0])
                on = 0
                for x in units[i][1]:
                    d = S.dist(x, 1.0)
                    if d < 1.0:
                        dmin = d if dmin is None else min(dmin, d)
                    on += d < 1e-3
                if on > 2:                      # больше 1 мм вплотную (точки через 0,5 мм) — общий участок
                    bad += 1
    return bad, dmin


def _check_label(p):
    """Подпись детали (фигуры с меткой label) — независимо от расстановки: все точки внутри внешнего контура, вне
    отверстий и язычков; не ближе отступа к любой другой фигуре детали и к хорде язычка; разные куски подписи не
    ближе разрыва друг к другу (CypCut не любит касаний). Вернуть причину или ""."""
    info = p["label"]
    m, gap = info["margin"], info["gap"]
    lab = [s for s in p["shapes"] if s.get("label")]
    rest = [s for s in p["shapes"] if not s.get("label")]
    outer = rest[-1]
    Po = G.points(outer, 0.02)
    holes = [G.points(s, 0.05) for s in rest[:-1] if G.is_closed(s)]
    tongues = [G.points(s, 0.05) for s in rest[:-1] if not G.is_closed(s) and s["layer"] == 1 and len(G.points(s, 0.05)) >= 3]
    S = _Segs(rest)
    for P in tongues:
        S.add(dict(kind="Line", p1=P[-1], p2=P[0]))
    for s in lab:
        for x in _dense(s, 0.25):
            if not G.inside(x, Po) or any(G.inside(x, h) for h in holes + tongues):
                return "подпись вне детали или на отверстии/язычке у (%.1f; %.1f)" % x
            if S.dist(x, m + 1) < m - 1e-3:
                return "подпись ближе %g мм к контуру у (%.1f; %.1f)" % (m, x[0], x[1])
    for i in range(len(lab)):
        Si = _Segs([lab[i]])
        for j in range(i + 1, len(lab)):
            for x in _dense(lab[j], 0.1):
                if Si.dist(x, gap + 1) < gap - 0.02:
                    return "штрихи подписи ближе %g мм у (%.1f; %.1f)" % (gap, x[0], x[1])
    return ""
