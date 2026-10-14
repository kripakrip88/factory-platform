# -*- coding: utf-8 -*-
"""Проверки собранной программы — где можно, независимо от сборщика (расшифровщик отчётов писался по другим файлам).

    rep = check(raw, parts, layouts, gap, edge)    # [(название, ок, подробности)]; ок: True / False / None — предупреждение
"""
import io, math, os, re, tempfile, collections, copy, zipfile, contextlib
from .libpath import vn
from . import geom as G
from .write_lxds import exact_coedge, decompile_free, compile_free, FREE
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


BRIDGE_RULES = ("F20", "G13", "G25", "G27", "G28")    # правила xml_validate, которые вставка моста нарушает «по букве»


@contextlib.contextmanager
def _xv_free_view(rep_handle):
    """xml_validate пакета ждёт у вставки раскладки NestPart или NestGroup и на вставке моста (CypCut пишет её без
    ссылки) падает (G28: parts[None]). На время проверки его нестрогий разбор XML (модель файла; строгий разбор B1 —
    «XML = serialize(parse)» — не трогается) видит у такой вставки NestPart первой детали программы; правила, которые
    от этого ложно падают (BRIDGE_RULES), проверяются в sheet_nest по смыслу моста (_bridge_rules)."""
    XM = vn.xml_validate.xml_model
    orig = XM.parse

    def parse(raw, strict=True):
        root = orig(raw, strict)
        if not strict and root.tag == "NestResult" and root.find("Shapes") is not None:
            for s in root.find("Shapes").children:
                if s.get("Class") == "Insert" and s.get("NestPart") is None and s.get("NestGroup") is None:
                    s.set("NestPart", rep_handle)
        return root
    XM.parse = parse
    try:
        yield
    finally:
        XM.parse = orig


def _free_inserts(raw):
    """Вставки мостов (без NestPart/NestGroup) по раскладкам и NestPart первой детали — по XML программы, без разбора
    пакетом (сломанная программа: проверки до разбора остаются в отчёте, как было)."""
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(io.BytesIO(raw))
    X = lambda n: ET.fromstring(z.read(n))
    n = collections.Counter()
    for r in X("Nest2D/Results/content.xml"):
        k = int(r.get("Index"))
        n[k] += sum(1 for s in X("Nest2D/Results/%d/content.xml" % k).iter("Shape")
                    if s.get("Class") == "Insert" and s.get("NestPart") is None and s.get("NestGroup") is None)
    n = +n
    first = next(iter(X("Nest2D/Parts/content.xml")), None) if n else None
    return n, (first.get("Handle") if first is not None else "0")


def check(raw, parts, layouts, gap, edge, thickness=None, rep=None):
    SR, LR, XV, SV = vn.spec_rebuild, vn.lxds_reader, vn.xml_validate, vn.spec_verify
    rep = [] if rep is None else rep
    nfree, rep_h = _free_inserts(raw)                    # мосты: вставки без ссылки — по раскладкам
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "x.lxds")
        open(path, "wb").write(raw)
        if nfree:
            with _xv_free_view(rep_h):
                R = XV.validate(path, quiet=True)
            with exact_coedge():
                rows = _bridge_rules(R.rows, raw, decompile_free(raw), parts, layouts, nfree)
        else:
            rows = XV.validate(path, quiet=True).rows
        fails = [(n, d) for s_, n, d in rows if s_ == "FAIL"]
        rep.append(("целостность (xml_validate)", not fails, "%d правил, ошибок %d %s%s" % (
            len(rows), len(fails), fails[:3], ("; мост: правила %s пакета — по смыслу моста (вставка без NestPart, как у CypCut)"
                                               % ", ".join(BRIDGE_RULES)) if nfree else "")))
        Gc = collections.defaultdict(collections.Counter); Gc["files"], Gc["geo"], Gc["attrs"] = {}, {}, {}
        SV.check(path, Gc)
        ok_bins = not Gc["geo_obj_match"][False] and not Gc["shp_obj_match"][False]
        rep.append(("двоичные данные, независимая сборка (spec_verify)", ok_bins,
                    "геометрия %s, атрибуты %s" % (dict(Gc["geo_obj_match"]), dict(Gc["shp_obj_match"]))))
    with exact_coedge():
        M2 = decompile_free(raw)
        raw2, _ = compile_free(copy.deepcopy(M2), collections.defaultdict(collections.Counter))
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
    gstat, bstat = collections.Counter(), collections.Counter()
    shared_total = 0.0                                  # общие кромки (режутся один раз) × листы — для длины реза
    bridge_cut = 0.0                                    # мосты: общие контуры (аналитически) − окружности их деталей, × листы
    bridged_by = collections.defaultdict(collections.Counter)    # раскладка → детали мостов (расшифровщик их не видит)
    bridge_ok = {}                                      # блок моста → итог проверки (контур, детали) — для подвода
    for r, lay in zip(M2["results"], layouts):
        groups = lay.get("groups") or []
        in_g = {i for g in groups for i in g}
        bgr = (lay.get("bridges") or {}).get("groups") or []
        in_b = {i for g in bgr for i in g["members"]}
        want_b = [_want_bridge(parts, lay, g) for g in bgr]
        want_pl = collections.Counter()
        for k, q in enumerate(lay["placed"]):
            if k in in_g or k in in_b:
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
            if ins["ref"] == FREE:                       # мост: вставка без ссылки — сверяется с группой раскроя по геометрии
                bstat["мостов"] += 1
                try:
                    ok, why = _check_bridge(sh, want_b, lay["bridges"]["width"]) if want_b else (False, "мост, которого нет в раскрое")
                except Exception as e:                      # сломанная программа — ✗, а не падение проверки
                    ok, why = False, "проверка моста упала: %s" % e
                if not ok:
                    bstat["мостов с ошибкой"] += 1
                    bstat["последняя причина: " + why] += 1
                    continue
                for nm in ok["names"]:
                    cnt[nm] += r["plate_amount"]
                    bridged_by[r["index"]][nm] += 1
                bridge_cut += (ok["length_an"] - ok["circles_len"]) * r["plate_amount"]
                bridge_ok[ins["block"]] = ok
                continue
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
        bad_ins += want_pl != got_pl or any(not w["used"] for w in want_g + want_b)
    rep.append(("детали на листах = раскрой (поворот, место, все контуры)", bad_ins == 0, "раскладок с расхождением %d" % bad_ins))
    rep.append(("внешний контур режется последним", order_bad == 0, "нарушений %d" % order_bad))
    n_bw = sum(len((l.get("bridges") or {}).get("groups") or []) for l in layouts)
    if bstat["мостов"] or n_bw:
        bad = [k for k in bstat if isinstance(k, str) and k.startswith("последняя причина")]
        rep.append(("мосты: вставка без ссылки, блок-число, общий контур = граница деталей и перемычек, перемычки по ширине, "
                    "отверстия раньше контура, врезка на дуге", bstat["мостов с ошибкой"] == 0 and bstat["мостов"] == n_bw,
                    "мостов %d (в раскрое %d), с ошибкой %d %s" % (bstat["мостов"], n_bw, bstat["мостов с ошибкой"],
                                                                 "; ".join(b[19:] for b in bad)[:200])))
    if gstat["групп"]:
        bad = [k for k in gstat if isinstance(k, str) and k.startswith("последняя причина")]
        rep.append(("группы общего реза: детали, контуры по одному разу, цепочки от вырезанного, отверстия раньше контура",
                    gstat["групп с ошибкой"] == 0, "групп %d, с ошибкой %d %s" % (gstat["групп"], gstat["групп с ошибкой"], "; ".join(b[19:] for b in bad)[:200])))
    want_cnt = collections.Counter()
    for p in parts:
        want_cnt[p["name"]] += p["qty"]
    rep.append(("количество деталей = заказ", cnt == want_cnt, "%d шт" % sum(cnt.values())))

    r, ctx = LR.build(raw, name="программа", thickness=thickness or 1.0, min_side=300)
    # расшифровщик пакета деталей моста не видит (у вставки нет ссылки) — они добавляются по проверенным мостам
    got_lr = collections.Counter(r["parts_total"])
    for d in r["layouts"]:
        for nm, n in bridged_by.get(d["index"], {}).items():
            got_lr[nm] += n * d["sheets"]
    rep.append(("расшифровщик: детали = заказ%s" % (" (+ детали мостов)" if bridged_by else ""), got_lr == want_cnt,
                "%d шт" % sum(got_lr.values())))
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
    cut_e = sum(p["qty"] * sum(LR.elen(_rd_ent(s)) for s in p["shapes"] if s["layer"] != 2) for p in parts) - shared_total + bridge_cut
    eng_e = sum(p["qty"] * sum(LR.elen(_rd_ent(s)) for s in p["shapes"] if s["layer"] == 2) for p in parts)
    cut_p = sum(d["sheets"] * sum(LR.elen(e) for e in d["_ents"] if e["layer"] != 2) for d in ctx["lays"])
    eng_p = sum(d["sheets"] * sum(LR.elen(e) for e in d["_ents"] if e["layer"] == 2) for d in ctx["lays"])
    rep.append(("длина реза = детали × количество%s%s" % (" − общие кромки" if shared_total else "",
                                                          " (мосты: общий контур вместо окружностей)" if bridge_ok else ""),
                abs(cut_p - cut_e) < 1,
                "%.2f м против %.2f м%s%s" % (cut_p / 1000, cut_e / 1000, (", общий рез сберёг %.2f м" % (shared_total / 1000)) if shared_total else "",
                                            (", мосты %+.3f м" % (bridge_cut / 1000)) if bridge_ok else "")))
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
    lead_min = lead_b = None
    for d, l, res_ in zip(ctx["lays"], layouts, M2["results"]):
        lay = lay_by[d["index"]]
        grp_blocks = {ins["block"] for ins in res_["inserts"] if ins["ref"][0] == "NestGroup"}
        free_blocks = {ins["block"] for ins in res_["inserts"] if ins["ref"] == FREE}   # мосты (не прошедшие — уже ✗ выше)
        plan_polys = []
        for q in l["placed"]:
            P = G.points(G.transform(parts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"])), 0.1)
            plan_polys.append((P, (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P))))
        for b in lay["inserts"]:
            if b in grp_blocks:
                continue                   # у групп общего реза врезка — в свободном углу первой детали, подвод CypCut
            if b in bridge_ok:             # мост: врезка — вершина 0 на дуге, подвод по нормали к дуге; препятствия — свой
                bo = bridge_ok[b]          # общий контур (луч может уйти на деталь своей группы) и чужие детали
                fr = lead_free(bo["lead_shape"], l["W"], l["L"], [pp for k_, pp in enumerate(plan_polys) if k_ not in bo["members"]]
                               + [bo["poly"]])
                lead_b = fr if lead_b is None else min(lead_b, fr)
                continue
            if b in free_blocks:
                continue
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
    if bridge_ok:
        rep.append(("мосты: место под подвод общего контура ≥ %g мм (по радиусу от точки врезки на дуге)" % LEAD_FREE,
                    True if lead_b is not None and lead_b >= LEAD_FREE - 1e-9 else None,
                    ("наименьшее %.1f мм (до 20)" % lead_b) if lead_b is not None else "врезки мостов не найдены в программе"))
    labelled = [p for p in parts if p.get("label")]
    if labelled:
        bad_l = [p["name"] + ": " + why for p in labelled for why in [_check_label(p)] if why]
        rep.append(("подписи: внутри детали, ≥ %g мм от отверстий, прорезей, язычков и края, штрихи не касаются (≥ %g мм)"
                    % (labelled[0]["label"]["margin"], labelled[0]["label"]["gap"]), not bad_l,
                    "; ".join(bad_l)[:300] if bad_l else "подписано деталей %d" % len(labelled)))
    # загрузка: расшифровщик считает её по деталям со ссылками — детали мостов добавляются (у CypCut после моста загрузка
    # та же, что без него); его предупреждение «не сошлась» у раскладки с мостами снимается, если с ними сошлась
    prog, util_c = ctx["prog"], {}
    hby = {p["name"]: h for h, p in prog.parts.items()}
    plo = {l_["index"]: l_ for l_ in prog.layouts}
    for d in ctx["lays"]:                              # тем же счётом, что расшифровщик (его util_calc_cypcut уже округлён)
        pl_ = d["_plate"]
        cnt_ = collections.Counter({h: n for h, n in plo[d["index"]]["counts"].items() if h in prog.parts})
        for nm, n in bridged_by.get(d["index"], {}).items():
            if nm in hby:
                cnt_[hby[nm]] += n
        cyp = sum(n * LR.part_areas(prog, h, ctx["eng"])[1] for h, n in cnt_.items())
        util_c[d["index"]] = round(100 * cyp / ((pl_["x1"] - pl_["x0"]) * (pl_["y1"] - pl_["y0"])), 2)
    util_ok = all(abs(l["util_cypcut"] - util_c[l["index"]]) < 0.01 for l in r["layouts"])
    rep.append(("загрузка в файле = своя по геометрии%s" % (" (+ детали мостов)" if bridged_by else ""), util_ok,
                ", ".join("%.1f%%" % l["util_cypcut"] for l in r["layouts"])))
    warns = [w for w in r["warnings"] if "от края" not in w and "толщин" not in w and not any(
        w.startswith("раскладка %d: загрузка не сошлась" % k) and abs(util_c[k] - next(l["util_cypcut"] for l in r["layouts"]
                                                                                       if l["index"] == k)) < 0.01
        for k in bridged_by)]
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


# ============================================================================================ мосты
def _circle(s):
    """Внешний контур-окружность детали — (cx, cy, r): Circle или полилиния из дуг (центр первой дуги)."""
    if s["kind"] == "Circle":
        return (float(s["c"][0]), float(s["c"][1]), float(s["r"]))
    V = s["verts"]
    (cx, cy), r, _ = G.bulge_center(V[0][:2], V[1][:2], V[0][2])
    return (cx, cy, r)


def _want_bridge(parts, lay, g):
    """Ожидаемая группа моста по раскрою: окружности деталей, перемычки (номера в группе), отверстия, имена деталей."""
    P = lay["placed"]
    idx = {k: n for n, k in enumerate(g["members"])}
    tr = lambda s, q: G.transform(s, q["rot"], (q["dx"], q["dy"]))
    return dict(circles=[_circle(tr(parts[P[k]["part"]]["shapes"][-1], P[k])) for k in g["members"]],
                edges=[(idx[a], idx[b]) for a, b in g["edges"]], members=set(g["members"]),
                inner=collections.Counter(canon(tr(s, P[k])) for k in g["members"] for s in parts[P[k]["part"]]["shapes"][:-1]),
                names=[parts[P[k]["part"]]["name"] for k in g["members"]], used=False)


def _exact_points(V, step=0.5):
    """Точки замкнутой полилинии не реже step мм — на дугах точно на окружности (не по хордам)."""
    import numpy as np
    out = []
    n = len(V)
    for i in range(n):
        (x1, y1, b), (x2, y2, _) = V[i], V[(i + 1) % n]
        if abs(b) > 1e-12:
            (cx, cy), r, th = G.bulge_center((x1, y1), (x2, y2), b)
            a1 = math.atan2(y1 - cy, x1 - cx)
            k = max(1, int(math.ceil(abs(th) * r / step)))
            t = a1 + th * np.arange(k) / k
            out.append(np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], 1))
        else:
            k = max(1, int(math.ceil(math.hypot(x2 - x1, y2 - y1) / step)))
            t = np.arange(k) / k
            out.append(np.stack([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t], 1))
    return np.concatenate(out)


def _check_bridge(sh, want_b, w):
    """Блок моста против группы раскроя — независимо от построения (bridge.Contour): отверстия — те же; общий контур
    последний и как у CypCut (полилиния, flag 5, sp 0, outer 0, coedge 0, flag64 0, без LeadParam, против часовой);
    каждая его точка (через 0,5 мм, на дугах — точно) — на границе объединения окружностей деталей и полос перемычек
    (полоса ±w/2 от линии центров); каждая точка этой границы (окружности через 0,5 мм, кромки перемычек через 0,1 мм) —
    на контуре; длина = граница аналитически (дуги без зон перемычек + по две прямые на перемычку) ± 0,01 мм; у каждой
    перемычки ровно две прямые от окружности к окружности, параллельные, в ±w/2 от линии центров (1e-6 мм); других
    прямых нет; врезка (вершина 0) — между двумя дугами. Вернуть (итог | False, причина)."""
    import numpy as np
    if not sh:
        return False, "пустой блок моста"
    cont, holes = sh[-1], sh[:-1]
    inner = collections.Counter(canon(s) for s in holes)
    same = [x for x in want_b if not x["used"] and x["inner"] == inner]
    if not same:
        return False, "отверстия моста не совпали ни с одной группой раскроя"
    # группа — по геометрии: окружности дуг общего контура = окружности деталей группы (у деталей без отверстий —
    # дисков — отверстия у всех групп одинаково пустые, и по ним одним вставка сверялась бы с чужой группой)
    arcs_c = _arc_circles(cont)
    wb = next((x for x in same if _same_circles(arcs_c, x["circles"])), None)
    if wb is None:
        return False, "окружности общего контура не совпали ни с одной группой раскроя"
    wb["used"] = True
    if cont["kind"] != "LwPolyline" or cont["flag"] != 5 or (cont.get("sp") or 0) != 0 or cont.get("outer") or cont.get("coedge") \
            or cont.get("flag64") or cont.get("lead") is not None or cont.get("layer") != 1:
        return False, "общий контур не как у CypCut (полилиния, flag 5, sp 0, outer 0, coedge 0, flag64 0, без LeadParam)"
    if any(s.get("outer") for s in holes) or any(G.is_closed(s) and G.area(s) >= G.area(cont) for s in holes):
        return False, "общий контур не последний в блоке"
    V = cont["verts"]
    if G.poly_area(V) <= 0:
        return False, "общий контур не против часовой"
    C = np.array([c[:2] for c in wb["circles"]], float)
    Rr = np.array([c[2] for c in wb["circles"]], float)
    strips = []
    for a, b in wb["edges"]:
        D = float(np.hypot(*(C[b] - C[a])))
        u = (C[b] - C[a]) / D
        strips.append((a, b, C[a], u, np.array([-u[1], u[0]]), D))

    def depth(Q):
        """Наибольшая глубина точек в объединении (+ внутри, 0 — на границе): окружности и прямоугольники перемычек."""
        dc = Rr[None, :] - np.hypot(Q[:, None, 0] - C[None, :, 0], Q[:, None, 1] - C[None, :, 1])
        best = dc.max(1)
        for a, b, p0, u, n, D in strips:
            t = (Q[:, 0] - p0[0]) * u[0] + (Q[:, 1] - p0[1]) * u[1]       # без @: matmul на macOS (Accelerate)
            d = (Q[:, 0] - p0[0]) * n[0] + (Q[:, 1] - p0[1]) * n[1]       # даёт ложные предупреждения переполнения
            best = np.maximum(best, np.minimum(np.minimum(w / 2 - np.abs(d), t), D - t))
        return best
    Q = _exact_points(V, 0.5)
    dev = float(np.abs(depth(Q)).max())
    if dev > 1e-6:
        return False, "точка общего контура не на границе деталей и перемычек (%.2e мм)" % dev
    # контур: дуги (центр, r, начало, угол) и прямые — для «точка на контуре»
    arcs, lines = [], []
    n = len(V)
    for i in range(n):
        (x1, y1, b), (x2, y2, _) = V[i], V[(i + 1) % n]
        if abs(b) > 1e-12:
            (cx, cy), r, th = G.bulge_center((x1, y1), (x2, y2), b)
            arcs.append((cx, cy, r, math.atan2(y1 - cy, x1 - cx), th))
        else:
            lines.append(((x1, y1), (x2, y2)))

    def on_contour(Q):
        ok = np.zeros(len(Q), bool)
        for cx, cy, r, a1, th in arcs:
            rad = np.hypot(Q[:, 0] - cx, Q[:, 1] - cy)
            ang = (np.arctan2(Q[:, 1] - cy, Q[:, 0] - cx) - a1) % (2 * math.pi) if th > 0 else (a1 - np.arctan2(Q[:, 1] - cy, Q[:, 0] - cx)) % (2 * math.pi)
            ok |= (np.abs(rad - r) < 1e-6) & ((ang <= abs(th) + 1e-9) | (ang >= 2 * math.pi - 1e-9))
        for p, q in lines:
            dx, dy = q[0] - p[0], q[1] - p[1]
            t = np.clip(((Q[:, 0] - p[0]) * dx + (Q[:, 1] - p[1]) * dy) / (dx * dx + dy * dy), 0, 1)
            ok |= np.hypot(Q[:, 0] - (p[0] + t * dx), Q[:, 1] - (p[1] + t * dy)) < 1e-6
        return ok
    pts = []
    for (cx, cy), r in zip(C, Rr):
        k = int(math.ceil(2 * math.pi * r / 0.5))
        t = 2 * math.pi * np.arange(k) / k
        pts.append(np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], 1))
    for a, b, p0, u, nn, D in strips:
        t = np.arange(0.0, D, 0.1)
        for sg in (-1, 1):
            pts.append(p0[None, :] + t[:, None] * u[None, :] + sg * (w / 2) * nn[None, :])
    P_ = np.concatenate(pts)
    bnd = P_[np.abs(depth(P_)) <= 1e-9]                 # точки границы объединения (не внутри соседних фигур)
    miss = int((~on_contour(bnd)).sum())
    if miss:
        return False, "граница деталей и перемычек не прорезана в %d точках" % miss
    L_an = float(sum(2 * math.pi * r for r in Rr))
    for a, b, p0, u, nn, D in strips:
        L_an -= 2 * Rr[a] * math.asin(w / 2 / Rr[a]) + 2 * Rr[b] * math.asin(w / 2 / Rr[b])
        L_an += 2 * (D - math.sqrt(Rr[a] ** 2 - w * w / 4) - math.sqrt(Rr[b] ** 2 - w * w / 4))
    L = G.length(cont)
    L_an = float(L_an)
    if abs(L - L_an) > 0.01:
        return False, "длина общего контура %.3f против %.3f мм (двойной обход?)" % (L, L_an)

    def on_circle(p, k):
        return abs(math.dist(p, C[k]) - Rr[k]) < 1e-6
    used = 0
    for a, b, p0, u, nn, D in strips:
        ls = [(p, q) for p, q in lines if (on_circle(p, a) and on_circle(q, b)) or (on_circle(p, b) and on_circle(q, a))]
        if len(ls) != 2:
            return False, "у перемычки не две прямые (%d)" % len(ls)
        offs = []
        for p, q in ls:
            d1 = (p[0] - p0[0]) * nn[0] + (p[1] - p0[1]) * nn[1]
            d2 = (q[0] - p0[0]) * nn[0] + (q[1] - p0[1]) * nn[1]
            if abs(d1 - d2) > 1e-6:
                return False, "прямая перемычки не параллельна линии центров"
            offs.append(d1)
        if abs(abs(offs[0] - offs[1]) - w) > 1e-6 or abs(offs[0] + offs[1]) > 1e-6:
            return False, "ширина перемычки %.6f мм вместо %g (или не по линии центров)" % (abs(offs[0] - offs[1]), w)
        used += 2
    if used != len(lines):
        return False, "в общем контуре лишние прямые (%d)" % (len(lines) - used)
    if abs(V[0][2]) < 1e-12 or abs(V[-1][2]) < 1e-12:
        return False, "врезка (вершина 0) не на дуге"
    t = _arc_start_normal(V)
    lead_shape = dict(kind="LwPolyline", verts=V, flag=5, sp=0.0, _lead=(tuple(V[0][:2]), t))
    Pp = G.points(cont, 0.1)
    return dict(names=wb["names"], members=wb["members"], length_an=float(L_an), circles_len=float(sum(2 * math.pi * float(r) for r in Rr)),
                lead_shape=lead_shape, poly=(Pp, (min(x for x, y in Pp), min(y for x, y in Pp), max(x for x, y in Pp), max(y for x, y in Pp)))), ""


def _arc_circles(s, tol=1e-4):
    """Разные окружности дуг замкнутой полилинии: [(cx, cy, r)] (у фигуры другого вида — пусто)."""
    out = []
    if s.get("kind") != "LwPolyline":
        return out
    V = s["verts"]
    for i in range(len(V)):
        (x1, y1, b), (x2, y2, _) = V[i], V[(i + 1) % len(V)]
        if abs(b) <= 1e-12 or math.hypot(x2 - x1, y2 - y1) < 1e-9:
            continue
        (cx, cy), r, _ = G.bulge_center((x1, y1), (x2, y2), b)
        if not any(abs(cx - c[0]) < tol and abs(cy - c[1]) < tol and abs(r - c[2]) < tol for c in out):
            out.append((cx, cy, r))
    return out


def _same_circles(got, want, tol=1e-4):
    """Окружности дуг контура — ровно окружности деталей группы (каждая — по одной, центр и радиус ± tol мм)."""
    if len(got) != len(want):
        return False
    rest = list(got)
    for c in want:
        k = next((k for k, g in enumerate(rest) if abs(g[0] - c[0]) < tol and abs(g[1] - c[1]) < tol and abs(g[2] - c[2]) < tol), None)
        if k is None:
            return False
        rest.pop(k)
    return True


def _arc_start_normal(V):
    """Наружная нормаль в вершине 0 контура против часовой: касательная первого участка (хорда − половина дуги),
    повёрнутая вправо."""
    (x1, y1, b), (x2, y2, _) = V[0], V[1]
    h = math.atan2(y2 - y1, x2 - x1) - 2 * math.atan(b)
    return (math.sin(h), -math.cos(h))


def _bridge_rules(rows, raw, M2, parts, layouts, nfree):
    """Строки xml_validate с мостами: правила BRIDGE_RULES пакета, которые вставка моста (без NestPart) нарушает «по
    букве», заменяются своими — по смыслу моста (как у CypCut): F20 — блоки вставок {GUID}, у моста — число, имена
    разные; G13 — Amount = заказ, AmountUsed = Amount − детали мостов = вставки со ссылкой; G25 — PartCount = детали со
    ссылкой (без мостов); G27 — копии блоков деталей у всех вставок со ссылкой (вставки мостов — не копии, их
    проверяет _check_bridge); G28 — загрузка с деталями мостов. Остальные — как у пакета."""
    XV, XM, SR = vn.xml_validate, vn.xml_model, vn.spec_rebuild
    z = zipfile.ZipFile(io.BytesIO(raw))
    out, done = [], set()
    pby = {p["handle"]: p for p in M2["parts"]}
    bn = {b["name"]: b for b in M2["blocks"]}
    want = collections.Counter()
    for p in parts:
        want[p["name"]] += p["qty"]
    bridged = collections.Counter()
    for l in layouts:
        for g in (l.get("bridges") or {}).get("groups") or []:
            for k in g["members"]:
                bridged[parts[l["placed"][k]["part"]]["name"]] += l["amount"]
    for st, name, det in rows:
        rule = name.split()[0]
        if rule not in BRIDGE_RULES:
            out.append((st, name, det))
            continue
        if rule == "F20":
            blk = [i for r in M2["results"] for i in r["inserts"]]
            names = [i["block"] for i in blk]
            ok = all((i["block"].isdigit() if i["ref"] == FREE else XV.GUID_RE.match(i["block"]) is not None) for i in blk) \
                and len(set(names)) == len(names)
            out.append(("PASS" if ok else "FAIL", "F20 result-insert blocks named {GUID}; bridge blocks — number (CypCut)", ""))
        elif rule == "G13":
            if "G13" in done:
                continue
            done.add("G13")
            used = collections.Counter()
            for r in M2["results"]:
                for i in r["inserts"]:
                    if i["ref"][0] == "NestPart":
                        used[i["ref"][1]] += r["plate_amount"]
                    elif i["ref"][0] == "NestGroup":
                        for o in next(g for g in M2["groups"] if g["handle"] == i["ref"][1])["objects"]:
                            used[o] += r["plate_amount"]
            bad = [p["name"] for p in M2["parts"] if not (int(p["given"]["Amount"]) == want[p["name"]] and
                                                           int(p["given"]["AmountUsed"]) == want[p["name"]] - bridged[p["name"]] == used[p["handle"]])]
            out.append(("FAIL" if bad else "PASS", "G13 Parts: Amount == order, AmountUsed == Amount - bridged == direct+groups (bridge, CypCut)",
                        "%s" % bad[:3]))
        elif rule == "G25":
            k = int(re.match(r"G25 R(\d+)", name).group(1))
            r = next(r for r in M2["results"] if r["index"] == k)
            rc = XM.parse(z.read("Nest2D/Results/content.xml"))
            pc = next(x for x in rc.children if x.get("Index") == str(k)).get("PartCount")
            want_pc = sum(1 if i["ref"][0] == "NestPart" else len(next(g for g in M2["groups"] if g["handle"] == i["ref"][1])["objects"])
                          for i in r["inserts"] if i["ref"] != FREE)
            out.append(("PASS" if pc == str(want_pc) else "FAIL", "G25 R%d: PartCount == parts with a reference (bridges not counted, CypCut)" % k,
                        "%s vs %d" % (pc, want_pc)))
        elif rule == "G27":
            k = int(re.match(r"G27 R(\d+)", name).group(1))
            m = re.match(r"(\d+)/(\d+)", det or "")
            ok = m is not None and int(m.group(1)) == int(m.group(2)) - nfree.get(k, 0)
            out.append(("PASS" if ok else "FAIL", "G27 R%d: NestPart insert block = copy of the part block (bridge inserts excluded)" % k,
                        "%s; bridges %d" % (det, nfree.get(k, 0))))
        elif rule == "G28":
            k = int(re.match(r"G28 R(\d+)", name).group(1))
            l = layouts[k - 1]
            r = next(r for r in M2["results"] if r["index"] == k)
            pl = next(p for p in M2["plates"] if p["handle"] == r["plate"])
            area = {p["name"]: SR.block_util_area(bn[p["block"]]["shapes"]) for p in M2["parts"]}
            tot = sum(area[parts[q["part"]]["name"]] for q in l["placed"])
            util = 100.0 * tot / (pl["W"] * pl["L"])
            rc = XM.parse(z.read("Nest2D/Results/content.xml"))
            stored = next(x for x in rc.children if x.get("Index") == str(k)).get("Utilization")
            ok = XM.fmt_num(util) == stored or abs(util - float(stored)) / float(stored) < 2e-5
            out.append(("PASS" if ok else "FAIL", "G28 R%d: Utilization = all parts of the layout incl. bridged (CypCut)" % k,
                        "stored %s calc %s" % (stored, XM.fmt_num(util))))
    return out
