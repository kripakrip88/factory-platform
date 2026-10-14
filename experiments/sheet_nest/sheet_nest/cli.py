# -*- coding: utf-8 -*-
"""Командная строка: детали (DXF и/или программы CypCut) → раскрой на листы → программа CypCut.

    python3 -m sheet_nest.cli ВХОД... [--sheet 1250x2500] [--gap 2] [--edge 2] [--thickness 1.5] [--qty ИМЯ=N] [--out DIR] [--name ИМЯ]
                              [--coedge] [--bridge [--bridge-width 2] [--bridge-group 5]]
                              [--strategy short|safe|safe0|hill] [--compare] [--small 100] [--microjoints ИМЯ|*]
                              [--machine ПРОФИЛЬ.json ...]

ВХОД — .dxf (одна или несколько деталей; гравировка — слой «ГРАВИРОВКА»; количество — из имени «…_12шт.dxf»
или --qty) и/или .lxds (детали с количеством из программы; раскладки в ней не важны).
В DIR: <имя>_<дата>.lxds (одна программа на все листы), картинка раскладок .png, отчёт .json.
Порядок резки — по стратегии (route.STRATEGIES), --compare — сводка по всем стратегиям (текст и отчёт).
"""
import sys, os, json, argparse, datetime, collections
from . import geom as G


def load_parts(inputs, qty_over=None, engrave_layers=None):
    parts, technical, warns = [], None, []
    for path in inputs:
        data = open(path, "rb").read()
        name = os.path.basename(path)
        if name.lower().endswith(".lxds"):
            from .read_lxds import parts_from_lxds
            ps, info = parts_from_lxds(data, name)
            technical = technical or info["technical"]
            warns += info["warnings"]
        elif name.lower().endswith(".dxf"):
            from .read_dxf import parts_from_dxf
            ps = parts_from_dxf(data, name, None, engrave_layers)
        else:
            raise ValueError("%s: нужен .dxf или .lxds" % name)
        parts += ps
    # имена — уникальные (по ним в программе считаются количества)
    seen = collections.Counter()
    for p in parts:
        seen[p["name"]] += 1
        if seen[p["name"]] > 1:
            p["name"] = "%s (%d)" % (p["name"], seen[p["name"]])
    for k, v in (qty_over or {}).items():
        hit = [p for p in parts if p["name"] == k or os.path.splitext(p["src"])[0] == k]
        if not hit:
            raise ValueError("--qty %s: нет такой детали (есть: %s)" % (k, ", ".join(p["name"] for p in parts)))
        for p in hit:
            p["qty"] = v
    for p in parts:
        warns += ["%s: %s" % (p["name"], w) for w in p.get("warnings", [])]
    return parts, technical, warns


def mark_microjoints(parts, names):
    """Детали с микроперемычками (держатся в листе): ИМЯ детали или файла без расширения; «*» — все."""
    for k in names or ():
        hit = parts if k == "*" else [p for p in parts if p["name"] == k or os.path.splitext(p["src"])[0] == k]
        if not hit:
            raise ValueError("--microjoints %s: нет такой детали (есть: %s)" % (k, ", ".join(p["name"] for p in parts)))
        for p in hit:
            p["microjoints"] = True
    for p in parts:
        p.setdefault("microjoints", False)


def _cut_len(l):
    """По маршруту раскладки: (длина реза, гравировки, врезок, начал гравировки, переходов), мм."""
    cut = mark = 0.0
    pierces = marks = n = 0
    for e in l["seq"]:
        for s in (e[1] if len(e) == 2 else e[2]):
            n += 1
            if s["layer"] == 2:
                mark += G.length(s); marks += 1
            else:
                cut += G.length(s); pierces += 1
    return cut, mark, pierces, marks, n


def summary_row(pl, rs, name, title, secs, thickness=None, machines=(), warnings=()):
    """Строка сводки стратегии: листы, рез, холостой, возврат, врезки, опасные переходы по классам, время станков
    (machine_s — {станок: секунды или None}; без профилей — пусто)."""
    from . import risk as RK, machine as MC, bridge as BR
    amounts = [l["amount"] for l in pl["layouts"]]
    tot = RK.total([r["risk"] for r in rs], amounts)
    cut = mark = 0.0
    pierces = marks = moves = 0
    for l, r in zip(pl["layouts"], rs):
        c, m, p_, m_, n = _cut_len(dict(seq=r["seq"]))
        cut += c * l["amount"]; mark += m * l["amount"]; pierces += p_ * l["amount"]; marks += m_ * l["amount"]
        moves += n * l["amount"]
    ms = {}
    for prof in machines or ():
        t = MC.estimate(prof, thickness, cut, mark, tot["idle_m"] * 1000, tot["ret"]["m"] * 1000, pierces, moves)
        ms[prof["name"]] = round(t, 1) if t is not None else None
    # конец листа (risk.end_strip): листов с узкой полосой в конце; худший остаток — полоса, затем самый вытянутый
    strips = [(r.get("strip"), l["amount"]) for l, r in zip(pl["layouts"], rs)]
    worst = max((s for s, a in strips if s), key=lambda s: (s["strip"], s["aspect"]), default=None)
    return dict(name=name, title=title, sheets=pl["sheets"], cut_m=round(cut / 1000, 2), mark_m=round(mark / 1000, 2),
                idle_m=round(tot["idle_m"], 2), return_m=round(tot["ret"]["m"], 2), pierces=pierces, marks=marks,
                danger={c: tot[c] for c in RK.CLASSES}, over_parts_m=tot["over_parts_m"],
                ret=dict(over_m=tot["ret"]["over_m"], tongues_crossed=tot["ret"]["tongues_crossed"], over=tot["ret"]["over"]),
                strip=dict(sheets=sum(a for s, a in strips if s and s["strip"]), worst=worst),
                bridges=BR.stats(pl["layouts"]) if any(l.get("bridges") for l in pl["layouts"]) else None,
                warnings=list(warnings), route_s=round(secs, 2), machine_s=ms)


def summary_text(rows):
    """Сводка по стратегиям текстом: строки — показатели, столбцы — стратегии."""
    from . import risk as RK
    lines = [("", ["%s (%s)" % (r["title"], r["name"]) for r in rows]),
             ("листов", [str(r["sheets"]) for r in rows]),
             ("рез, м", ["%.2f" % r["cut_m"] for r in rows]),
             ("холостой, м", ["%.2f" % r["idle_m"] for r in rows]),
             ("возврат в ноль, м", ["%.2f" % r["return_m"] for r in rows]),
             ("врезок", [str(r["pierces"]) for r in rows])]
    if any(r.get("bridges") for r in rows):             # мост — кнопка, у всех стратегий одни и те же группы
        lines.append(("мосты: групп / перемычек / деталей", ["%d / %d / %d" % (r["bridges"]["groups"], r["bridges"]["bridges"],
                                                                              r["bridges"]["parts"]) if r.get("bridges") else "—" for r in rows]))
    lines += [(RK.TITLES[c], [str(r["danger"][c]) for r in rows]) for c in RK.CLASSES]
    lines += [("конец листа: остаток, мм", ["—" if not r["strip"]["worst"] else "%.0f×%.0f" % (r["strip"]["worst"]["w"], r["strip"]["worst"]["l"])
                                            for r in rows]),
              ("узкая полоса в конце, листов", [str(r["strip"]["sheets"]) for r in rows])]
    lines += [("возврат над деталями, м", ["%.2f" % r["ret"]["over_m"] for r in rows]),
              ("предупреждений", [str(len(r["warnings"])) for r in rows]),
              ("маршрут, с", ["%.1f" % r["route_s"] for r in rows])]
    names = list(rows[0]["machine_s"]) if rows else []
    if not names:
        lines.append(("станок, мин", ["—" for r in rows]))
    for nm in names:                                    # строка на каждый станок
        lines.append(("станок «%s», мин" % nm, ["—" if r["machine_s"].get(nm) is None else "%.1f" % (r["machine_s"][nm] / 60)
                                                for r in rows]))
    w0 = max(len(k) for k, v in lines)
    ws = [max(len(v[j]) for k, v in lines) for j in range(len(rows))]
    return "\n".join(k.ljust(w0) + " | " + " | ".join((x.ljust if not k else x.rjust)(w) for x, w in zip(v, ws)) for k, v in lines)


def bridge_options(bridge):
    """--bridge: None | True | dict(width=2, group=5) → dict(width, group) или None; плохие значения — ValueError с текстом."""
    if not bridge:
        return None
    b = dict(width=2.0, group=5)
    if isinstance(bridge, dict):
        b.update({k: v for k, v in bridge.items() if v is not None})
    try:
        b["width"], g = float(b["width"]), float(b["group"])
    except (TypeError, ValueError):
        raise ValueError("мост: ширина перемычки и число деталей в группе — числа (дано %r)" % (bridge,))
    if not b["width"] > 0:
        raise ValueError("мост: ширина перемычки должна быть больше 0 мм (дано %g)" % b["width"])
    if g != int(g) or g < 2:
        raise ValueError("мост: в группе не меньше 2 деталей (--bridge-group, дано %g)" % g)
    b["group"] = int(g)
    return b


def run(inputs, W=1250.0, L=2500.0, gap=2.0, edge=2.0, thickness=None, qty=None, title=None, out=None, methods=("rect", "raster"),
        engrave_layers=None, log=print, coedge=False, labels=None, label_opts=None, strategy=None, compare=False, small=None,
        microjoints=None, machine=None, bridge=None):
    """strategy — порядок резки (route.STRATEGIES: short | safe | safe0 | hill; по умолчанию short); compare — посчитать
    сводку по всем стратегиям (res["strategies"]); small — «мелкая» деталь, мм (100); microjoints — имена деталей с
    микроперемычками («*» — все); machine — профиль станка (словарь или путь к JSON) или список профилей (станков два —
    время в сводке по каждому); bridge — мост (кнопка, как общий рез; от стратегии не зависит): None | dict(width=2 мм,
    group=5 деталей) — соседние круглые детали через зазор соединяются перемычками и режутся одной врезкой (bridge.py)."""
    import time
    from .pack import plan, plan_coedge
    from .route import route_sheet, route_sheet_coedge, STRATEGIES, options
    from .write_lxds import build
    from .verify import check_safe as check
    from . import render, risk as RK
    from . import machine as MC
    from . import bridge as BR
    o = options(strategy)
    br = bridge_options(bridge)
    if br and coedge:
        raise ValueError("мост и общий рез вместе пока нельзя: перемычке нужен зазор между деталями, а общий рез ставит их "
                         "вплотную — выберите что-то одно")
    small = RK.SMALL if small is None else float(small)
    machines = [MC.load(m) for m in (machine if isinstance(machine, (list, tuple)) else [machine] if machine else [])]
    if len({m["name"] for m in machines}) < len(machines):
        raise ValueError("профили станков: имена повторяются (%s) — задайте name в профиле" % ", ".join(m["name"] for m in machines))
    parts, technical, warns = load_parts(inputs, qty, engrave_layers)
    mark_microjoints(parts, microjoints)
    for w in warns:
        log("  ⚠ " + w)
    log("деталей: %d видов, %d шт" % (len(parts), sum(p["qty"] for p in parts)))
    lab_rep = []
    if labels:
        from .labels import apply_labels
        lo = dict(H=15.0, H_min=10.0, margin=3.0, gap=1.0, font_path=None)
        lo.update(label_opts or {})
        lab_rep = apply_labels(parts, labels, **lo)
        for name, text, h, why in lab_rep:
            log("  подпись %-30s «%s» %s" % (name, text, ("%g мм" % h) if h else "⚠ " + why))
            if not h:
                warns.append("%s: %s — деталь без подписи" % (name, why))
    pl = None
    if coedge:
        pl, why = plan_coedge(parts, W, L, edge)
        if pl is None:
            log("  ⚠ общий рез не применён: %s — раскладываю с зазором %g мм" % (why, gap))
    if pl is None:
        pl = plan(parts, W, L, gap, edge, methods)
    for t in pl["tried"]:
        log("  раскрой %-40s %s" % (t["method"], ("%d листов, %d раскладок" % (t["sheets"], t["layouts"])) if "sheets" in t
                                    else ("пропущен: " + t["skipped"]) if "skipped" in t else t.get("error")))
    log("раскрой: %s — %d листов %g×%g (нижняя граница %d %s%s)" % (pl["method"], pl["sheets"], W, L, pl["lower_bound"],
                                                                     pl["bound_kind"], ", минимум" if pl["optimal"] else ""))
    from .route import CoedgeRouteError
    bwarn = []
    if br:
        for l in pl["layouts"]:
            l["bridges"] = BR.plan(parts, l["placed"], gap, br["width"], br["group"])
            bwarn += l["bridges"]["skipped"]
        bwarn = sorted(set(bwarn))
        st_ = BR.stats(pl["layouts"])
        log("мост %g мм, до %d деталей в группе: групп %d, перемычек %d, деталей в мостах %d — врезок меньше на %d" % (
            br["width"], br["group"], st_["groups"], st_["bridges"], st_["parts"], st_["pierces_saved"]))
        if not st_["groups"]:
            bwarn.append("мост не применён: нет соседних круглых деталей через зазор %g мм%s" % (
                gap, " (детали с микроперемычками в мост не идут)" if any(p.get("microjoints") for p in parts) else ""))
        for w in bwarn:
            log("  ⚠ " + w)

    def route_all(pl, st, caches):
        """Маршруты всех раскладок по стратегии st: ([результат раскладки], секунд). Раскладка с мостами — маршрут по
        группам (bridge.bridged: группа — одна деталь), элементы группы в маршруте — ("bridge", [детали], фигуры)."""
        t0, rs = time.time(), []
        for l, c in zip(pl["layouts"], caches):
            if l.get("groups"):
                rs.append(route_sheet_coedge(l["placed"], l["groups"], parts, l["W"], l["L"], strategy=st, small=small, cache=c))
            elif l.get("bridges") and l["bridges"]["groups"]:
                if "_bridged" not in l:
                    l["_bridged"] = BR.bridged(parts, l)
                placed2, parts2, back = l["_bridged"]
                r = route_sheet(placed2, parts2, l["W"], l["L"], strategy=st, small=small, cache=c)
                r["seq"] = BR.unmap(r["seq"], back)
                rs.append(r)
            else:
                rs.append(route_sheet(l["placed"], parts, l["W"], l["L"], strategy=st, small=small, cache=c))
        return rs, time.time() - t0

    def route_plan(pl):
        # у каждой стратегии свой кэш листа (планы деталей, пути оптимизатора) — время в сводке честное
        res_ = {o["name"]: route_all(pl, o["name"] if strategy is None or isinstance(strategy, str) else strategy,
                                     [{} for _ in pl["layouts"]])}
        if compare:
            for name in STRATEGIES:
                if name not in res_:
                    res_[name] = route_all(pl, name, [{} for _ in pl["layouts"]])
        return res_
    try:
        by = route_plan(pl)
    except CoedgeRouteError as e:
        log("  ⚠ общий рез не применён: %s — раскладываю с зазором %g мм" % (e, gap))
        pl = plan(parts, W, L, gap, edge, methods)
        log("раскрой: %s — %d листов %g×%g (нижняя граница %d %s%s)" % (pl["method"], pl["sheets"], W, L, pl["lower_bound"],
                                                                         pl["bound_kind"], ", минимум" if pl["optimal"] else ""))
        by = route_plan(pl)
    rs, secs = by[o["name"]]
    for l, r in zip(pl["layouts"], rs):
        l["seq"], l["idle"] = r["seq"], r["idle"]
    route_warn = [w for r in rs for w in r["warnings"]]
    amounts = [l["amount"] for l in pl["layouts"]]

    def opt(n):                                         # переключатели стратегии по имени (своя — из strategy)
        return options(n) if n in STRATEGIES else o

    def risk_warn(name, rs_, safe):
        """Опасные переходы, которые стратегия не обошла (только у безопасных — у «short» безопасность не цель). Обход —
        поиск, а не доказательство: «не удалось обойти»; с --compare — у какой стратегии на этой раскладке их меньше
        (ступени ключа: язычки → мелкие → детали → отверстия)."""
        out_ = []
        for k, (l, r) in enumerate(zip(pl["layouts"], rs_)):
            m = r["risk"]
            bad = ["%s %d" % (RK.TITLES[c], m[c]) for c in ("tongues", "small", "parts", "holes") if m[c]]
            if bad and safe:
                better = [n for n, (rs2, _) in by.items() if n != name and tuple(rs2[k]["risk"]["key"][:4]) < tuple(m["key"][:4])]
                out_.append("раскладка №%d (×%d): опасные переходы остались — %s; эта стратегия их обойти не смогла%s "
                            "(иначе — микроперемычки или другой раскрой)" % (
                                k + 1, l["amount"], ", ".join(bad),
                                ("; меньше у %s" % ", ".join("«%s»" % opt(n)["title"] for n in better)) if better else ""))
        return out_

    def strip_warn(name, rs_):
        """«Узкая полоса в конце» (risk.end_strip) — у любой стратегии; с --compare — у какой стратегии на этой раскладке её
        нет."""
        out_ = []
        for k, (l, r) in enumerate(zip(pl["layouts"], rs_)):
            s = r.get("strip")
            if s and s["strip"]:
                fine = [n for n, (rs2, _) in by.items() if n != name and rs2[k].get("strip") and not rs2[k]["strip"]["strip"]]
                hills = [n for n in by if opt(n).get("hill")]
                if fine:
                    tip = "; без неё — %s" % ", ".join("«%s» (%.0f×%.0f)" % (opt(n)["title"], by[n][0][k]["strip"]["w"],
                                                                           by[n][0][k]["strip"]["l"]) for n in fine)
                elif hills:                             # «Горкой» посчитан и полосу не убрал — совет был бы неверным
                    tip = "; у «Горкой» (ступенька и порядки безопасных) она тоже есть — убрать её может другой раскрой"
                else:
                    tip = "; против неё — попробовать порядок «Горкой» (--strategy hill)"
                out_.append("раскладка №%d (×%d): к концу резки остаётся узкая полоса %.0f×%.0f мм (последние %d из %d деталей; "
                            "не больше %d деталей поперёк, длиннее половины листа) — её может повести от нагрева%s" % (
                                k + 1, l["amount"], s["w"], s["l"], s["parts"], s["of"], RK.STRIP_PARTS, tip))
        return out_
    rwarn = risk_warn(o["name"], rs, o["key"] != "short") + strip_warn(o["name"], rs)
    x_tongue = sum(r["crossings"] * a for r, a in zip(rs, amounts))
    x_parts = sum(r["crossings_parts"] * a for r, a in zip(rs, amounts))
    tot = RK.total([r["risk"] for r in rs], amounts)
    idle = sum(l["idle"] * l["amount"] for l in pl["layouts"])
    log("порядок резки (%s «%s»): холостой ход %.1f м, возврат в ноль %.1f м; переходов над вырезанными язычками %d, "
        "над вырезанными деталями %d" % (o["name"], o["title"], idle / 1000, tot["ret"]["m"], x_tongue, x_parts))
    log("  опасные переходы: " + ", ".join("%s %d" % (RK.TITLES[c], tot[c]) for c in RK.CLASSES) +
        "; возврат над деталями %.2f м, под ним язычков %d" % (tot["ret"]["over_m"], tot["ret"]["tongues_crossed"]))
    for w in sorted(set(route_warn)) + rwarn:
        log("  ⚠ " + w)
    rows = None
    if compare:
        rows = []
        for name, (rs_, secs_) in by.items():
            oo = opt(name)
            rows.append(summary_row(pl, rs_, name, oo["title"], secs_, thickness, machines,
                                    sorted(set(w for r in rs_ for w in r["warnings"])) + risk_warn(name, rs_, oo["key"] != "short")
                                    + strip_warn(name, rs_)))
        order_ = list(STRATEGIES) + [n for n in by if n not in STRATEGIES]
        rows.sort(key=lambda r: order_.index(r["name"]))
        log("сводка по стратегиям (%s):" % ("общий рез" if pl.get("coedge") else "с зазором"))
        for line in summary_text(rows).split("\n"):
            log("  " + line)
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=10))).strftime("%Y-%m-%d_%H%M")
    title = title or os.path.splitext(os.path.basename(inputs[0]))[0]
    tag = "" if (gap, edge) == (2.0, 2.0) else "_зазор%g_край%g" % (gap, edge)
    if pl.get("coedge"):
        tag += "_общий_рез"
    bst = BR.stats(pl["layouts"]) if br else None
    if bst and bst["groups"]:
        tag += "_мост"
    fname = "%s_лист%gx%g%s_%s" % (title, W, L, tag, stamp)
    raw, M = build(parts, pl["layouts"], fname, technical)
    rep, rr, ctx = check(raw, parts, pl["layouts"], gap, edge, thickness)
    ok = all(x[1] is not False for x in rep)
    for n, o_, d in rep:
        log("  %s %-62s %s" % ("✓" if o_ else "⚠" if o_ is None else "✗", n, d))
    main_row = rows[[r["name"] for r in rows].index(o["name"])] if rows else \
        summary_row(pl, rs, o["name"], o["title"], secs, thickness, machines, sorted(set(route_warn)) + rwarn)
    res = dict(file=fname + ".lxds", ok=ok, sheets=pl["sheets"], lower_bound=pl["lower_bound"], optimal=pl["optimal"],
               method=pl["method"], tried=pl["tried"], idle_m=round(idle / 1000, 2),
               # tongues, parts — как было (маршрут: над вырезанными язычками; заходы в деталь над вырезанной — с зазором,
               # все переходы — с общим резом); остальное — счёт risk.measure (классы опасных переходов)
               crossings=dict(tongues=x_tongue, parts=x_parts, holes=tot["holes"], holes_small=tot["holes_s"],
                              freed_small=tot["small"], freed_parts=tot["parts"], freed_mj=tot["mj"], near=tot["near"],
                              short=tot["short"], cut_tongues=tot["tongues"]),
               strategy=o["name"], strategy_title=o["title"], coedge=bool(pl.get("coedge")), small_mm=small,
               microjoints=[p["name"] for p in parts if p.get("microjoints")],
               risk=dict({c: tot[c] for c in RK.CLASSES}, moves=tot["moves_n"], over_parts_m=tot["over_parts_m"], ret=tot["ret"],
                         cut_m=main_row["cut_m"], mark_m=main_row["mark_m"], pierces=main_row["pierces"], route_s=main_row["route_s"],
                         machine_s=main_row["machine_s"]),
               layouts=[dict(index=k + 1, amount=l["amount"], parts=dict(collections.Counter(parts[q["part"]]["name"] for q in l["placed"])),
                             idle_m=round(l["idle"] / 1000, 3),
                             # то же, что в итогах (res["risk"]), по раскладке: ret_m, ret_over_m — как были; ret —
                             # возврат целиком (длина, метры над деталями, язычков под ним, классы перехода)
                             risk=dict({c: r["risk"][c] for c in RK.CLASSES}, ret_m=round(r["risk"]["ret"]["m"], 3),
                                       ret_over_m=round(r["risk"]["ret"]["over_m"], 3), over_parts_m=round(r["risk"]["over_parts_m"], 3),
                                       ret={k_: (round(v_, 3) if isinstance(v_, float) else v_) for k_, v_ in r["risk"]["ret"].items()},
                                       key=list(r["risk"]["key"]), key0=list(r["risk"]["key0"])),
                             # остаток к концу резки (risk.end_strip): последние 20 % деталей — габарит, узкая ли полоса
                             strip=r.get("strip"),
                             **({"bridges": BR.stats([l])} if l.get("bridges") else {}))
                        for k, (l, r) in enumerate(zip(pl["layouts"], rs))],
               totals={k: v for k, v in rr["totals"].items()} if rr else {}, checks=[(n, o_, d) for n, o_, d in rep],
               warnings=warns + bwarn + route_warn + rwarn, strip=main_row["strip"],
               labels=[dict(part=n, text=tx, height=h, rot=next((p["label"]["rot"] for p in parts if p["name"] == n and p.get("label")), None),
                            why=why) for n, tx, h, why in lab_rep])
    if rows is not None:
        res["strategies"] = {r["name"]: r for r in rows}
    if br:
        res["bridge"] = dict(br, **bst)
    if out:
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, fname + ".lxds"), "wb").write(raw)
        json.dump(res, open(os.path.join(out, fname + ".json"), "w"), ensure_ascii=False, indent=1)
        try:
            what = (", общий рез" if pl.get("coedge") else "") + ((", мост %g мм: групп %d" % (br["width"], bst["groups"])) if bst and bst["groups"] else "")
            render.png_model(raw, os.path.join(out, fname + ".png"), "%s — %d листов %g×%g%s, «%s»: холостой ход %.0f м, врезок %d" % (
                title, pl["sheets"], W, L, what, o["title"], idle / 1000, main_row["pierces"]),
                moves=[r["risk"]["moves"] for r in rs])
            render.png_order(raw, os.path.join(out, fname + "_порядок.png"), "%s — порядок резки «%s»%s: цвет — от первой детали "
                             "(синий) к последней (красный)" % (title, o["title"], what), strips=[r.get("strip") for r in rs],
                             done_polys=[r.get("done_polys") for r in rs])
        except ImportError:
            pass
        log("→ %s" % os.path.join(out, fname + ".lxds"))
    return res, raw, pl, parts


def main(argv=None):
    from .route import STRATEGIES, DEFAULT
    ap = argparse.ArgumentParser(prog="python3 -m sheet_nest.cli")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--sheet", default="1250x2500", help="лист ШxД, мм (1250x2500)")
    ap.add_argument("--gap", type=float, default=2.0)
    ap.add_argument("--edge", type=float, default=2.0)
    ap.add_argument("--thickness", type=float, default=None)
    ap.add_argument("--qty", action="append", default=[], help="ИМЯ=N (имя детали или файла без расширения)")
    ap.add_argument("--name", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--method", choices=("auto", "rect", "raster"), default="auto")
    ap.add_argument("--coedge", action="store_true", help="общий рез: детали вплотную, общие кромки режутся один раз (группы CypCut)")
    ap.add_argument("--bridge", action="store_true", help="мост: соседние круглые детали через зазор — перемычками в группы, "
                                                          "группа режется одной врезкой (Bridge CypCut)")
    ap.add_argument("--bridge-width", type=float, default=2.0, help="ширина перемычки моста, мм (2)")
    ap.add_argument("--bridge-group", type=int, default=5, help="деталей в группе моста, не больше (5)")
    ap.add_argument("--strategy", choices=list(STRATEGIES), default=DEFAULT,
                    help="порядок резки: " + "; ".join("%s — %s" % (k, v["title"]) for k, v in STRATEGIES.items()))
    ap.add_argument("--compare", action="store_true", help="сводка по всем стратегиям (программа — по --strategy)")
    ap.add_argument("--small", type=float, default=100.0, help="мелкая деталь: меньше стольких мм по одной из сторон (100)")
    ap.add_argument("--microjoints", action="append", default=[], help="ИМЯ детали с микроперемычками (* — все; повторяется)")
    ap.add_argument("--machine", action="append", default=[], help="профиль станка (JSON) — время в сводке (повторяется: "
                                                                   "строка на каждый станок)")
    ap.add_argument("--label", action="append", default=[], help="подпись гравировкой: ИМЯ=ТЕКСТ (имя детали; * — всем)")
    ap.add_argument("--label-height", type=float, default=15.0, help="высота букв, мм (15)")
    ap.add_argument("--label-min", type=float, default=10.0, help="наименьшая высота, если не помещается (10)")
    ap.add_argument("--label-margin", type=float, default=3.0, help="отступ подписи от отверстий, прорезей и края, мм (3)")
    ap.add_argument("--font", default=None, help="файл шрифта GOST.FON (GOST type A plotter)")
    a = ap.parse_args(argv)
    try:
        W, L = (float(x) for x in a.sheet.lower().replace("х", "x").split("x"))
    except ValueError:
        sys.exit("ошибка: --sheet ШxД, например 1250x2500")
    qty = {}
    for q in a.qty:
        k, _, v = q.rpartition("=")
        qty[k] = int(v)
    methods = ("rect", "raster") if a.method == "auto" else (a.method,)
    try:
        labels = {}
        for q in a.label:
            k, _, v = q.partition("=")
            if not v.strip() or not k.strip():
                raise ValueError("--label %r: нужно ИМЯ=ТЕКСТ (или *=ТЕКСТ)" % q)
            labels[k.strip()] = v
        res, *_ = run(a.inputs, W, L, a.gap, a.edge, a.thickness, qty, a.name, a.out or os.getcwd(), methods, coedge=a.coedge,
                      labels=labels or None, label_opts=dict(H=a.label_height, H_min=a.label_min, margin=a.label_margin,
                                                             font_path=a.font),
                      strategy=a.strategy, compare=a.compare, small=a.small, microjoints=a.microjoints or None,
                      machine=a.machine or None,
                      bridge=dict(width=a.bridge_width, group=a.bridge_group) if a.bridge else None)
    except ValueError as e:
        sys.exit("ошибка: %s" % e)
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
