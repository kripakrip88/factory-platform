# -*- coding: utf-8 -*-
"""Порядок «Горкой» (hill) и «узкая полоса в конце» (решение Антона 14.10.2026: к концу резки не должна оставаться узкая
полоса во всю длину листа — её ведёт от перегрева).

    python3 tests/check_hill.py [КАТАЛОГ_ОБРАЗЦОВ] [--quick]      (--quick — без m14 целиком, зонтов и решёток)

1) порядок: сетка 13×56 (как шайбы m14) — полосы по порядку не убывают, шаги — между соседями (ступенька), поворот у
   края листа — к соседке (не через ряд над вырезанной); на листе 1250×2500 и квадрате — то же;
2) метрика: колонками вдоль длины — в конце полоса (✓ узкая), рядами поперёк и «Горкой» — нет; на листе меньше 10 деталей
   — не полоса; остаток — последние 20 % деталей (группа моста — своими деталями); три длинных бруса рядом в конце — не
   полоса (это сами детали, порядком не убрать);
3) синтетика DXF: «Горкой» — все проверки программы, порядок деталей — по полосам (правка порядка только внутри полосы)
   или, если ступенька опаснее, — кандидат безопасных (без узкой полосы, опасных меньше); с общим резом и с мостом — тоже;
   общий рез: конец листа — по деталям в порядке освобождения (не группой целиком), картинка — цвет по деталям;
4) m14 (не в --quick): «Безопасный» оставляет в конце полосу ~3 шайбы × 6 м (предупреждение в сводке), «Горкой» —
   компактный остаток (меньшая сторона ≥ 1000 мм) и без опасных переходов над деталями; с мостом — то же; --compare
   показывает строки «конец листа» и «узкая полоса»; время «Горкой» ≤ «Безопасного»;
5) образцы (не в --quick): решётки, зонты, m30, m3 — «Горкой» — те же листы, все проверки ✓ (с зазором и общим резом), на
   каждой раскладке не хуже «Безопасного» по (узкая полоса, ступени опасных); m30 — 0 переходов над плитами и без полос;
   m3 с общим резом (одна группа) — как «Безопасный»; общий рез m30 — остаток не весь лист.
"""
import sys, os, math, tempfile, time, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
from sheet_nest import route as R, risk as RK
from sheet_nest.cli import run, main

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SAMPLES = ARGS[0] if ARGS else os.path.expanduser("~/Downloads/vent_nesting/samples")
QUICK = "--quick" in sys.argv
fails = []


def check(name, cond, detail=""):
    print("%s %-84s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def grid(nx, ny, pitch=107.0, d=105.0):
    return [((54.5 + i * pitch, 54.5 + j * pitch), (2 + i * pitch, 2 + j * pitch, 2 + i * pitch + d, 2 + j * pitch + d))
            for j in range(ny) for i in range(nx)]


# ============================================================================================ 1) порядок
def order():
    for nx, ny in ((13, 56), (11, 23), (12, 12)):
        items = grid(nx, ny)
        for fl in (False, True):
            seq, bands = R._hill(items, fl)
            mono = all(bands[seq[t]] <= bands[seq[t + 1]] for t in range(len(seq) - 1))
            steps = [math.dist(items[a][0], items[b][0]) for a, b in zip(seq, seq[1:])]
            adj = sum(1 for s in steps if s <= 107 * 1.01 * math.sqrt(2))     # соседи — в т.ч. по диагонали
            # «через ряд над вырезанной»: шаг длиннее соседнего, на пути — уже вырезанная деталь
            done, over = set(), 0
            for a, b in zip(seq, seq[1:]):
                done.add(a)
                pa, pb = items[a][0], items[b][0]
                for c in done:
                    if c != a and math.dist(pa, pb) > 107.5:
                        q = items[c][0]
                        t = max(0.0, min(1.0, ((q[0] - pa[0]) * (pb[0] - pa[0]) + (q[1] - pa[1]) * (pb[1] - pa[1])) / math.dist(pa, pb) ** 2))
                        if math.dist(q, (pa[0] + t * (pb[0] - pa[0]), pa[1] + t * (pb[1] - pa[1]))) < 50:
                            over += 1
                            break
            check("сетка %d×%d, фаза %d: полосы не убывают, все шаги — к соседке (и по диагонали), над вырезанной 0" % (nx, ny, fl),
                  sorted(seq) == list(range(len(items))) and mono and adj == len(steps) and over == 0,
                  "соседних %d из %d (по стороне %d), над вырезанной %d, полос %d" % (
                      adj, len(steps), sum(1 for s in steps if s <= 107 * 1.01), over, len(set(bands.values()))))


# ============================================================================================ 2) метрика
def metric():
    items = grid(14, 56)
    unit = lambda i: (items[i][1], 1, [105.0])
    cols = sorted(range(len(items)), key=lambda i: (items[i][0][0], items[i][0][1]))
    rows = sorted(range(len(items)), key=lambda i: (items[i][0][1], items[i][0][0]))
    hill, _ = R._hill(items)
    sc = RK.end_strip([unit(i) for i in cols], 1500, 6000)
    sr = RK.end_strip([unit(i) for i in rows], 1500, 6000)
    sh = RK.end_strip([unit(i) for i in hill], 1500, 6000)
    check("колонками вдоль 6 м: в конце узкая полоса (≤ 3 детали поперёк, во всю длину)", sc["strip"] and sc["l"] > 5000,
          "%.0f×%.0f, деталей %d из %d" % (sc["w"], sc["l"], sc["parts"], sc["of"]))
    check("рядами поперёк и «Горкой» — остаток компактный (не полоса)", not sr["strip"] and not sh["strip"] and sh["w"] >= 1000,
          "рядами %.0f×%.0f, «Горкой» %.0f×%.0f" % (sr["w"], sr["l"], sh["w"], sh["l"]))
    few = RK.end_strip([unit(i) for i in cols[:8]], 1500, 6000)
    check("на листе меньше %d деталей — не полоса" % RK.STRIP_MIN, not few["strip"], str(few))
    g = RK.end_strip([((0, 0, 100, 100), 5, [50.0] * 5), ((0, 200, 100, 300), 1, [50.0])] * 3, 1500, 6000)
    check("остаток — последние 20 % деталей (группа — своими деталями: 1 + 5 ≥ 3,6 из 18)", g["parts"] == 6 and g["of"] == 18 and
          g["box"] == [0, 0, 100, 300], str(g))
    # m3_grpsh: 12 брусьев, в конце — три бруса 200×2105 рядом: остаток 604×2105 у любого порядка — это сами детали
    bars = [((x, 0, x + 200, 1000), 1, [200.0], [1000.0]) for x in range(0, 1800, 202)][:9] + \
        [((x, 1100, x + 200, 3205), 1, [200.0], [2105.0]) for x in (0, 202, 404)]
    sb = RK.end_strip(bars, 1500, 3000)
    check("три длинных бруса рядом в конце — не полоса (длиннее %g длин детали — только полоса из деталей вдоль)" % RK.STRIP_ALONG,
          not sb["strip"] and sb["w"] < 700 and sb["l"] > 2000, "%.0f×%.0f, деталь %.0f" % (sb["w"], sb["l"], sb["part_l"]))


# ============================================================================================ 3) синтетика DXF
def dxf(td):
    import dxf_writer as DW
    out = []
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.lwpolyline([(0, 0), (300, 0), (300, 200), (0, 200)], closed=True); d.entities.circle((80, 100), 15)
    out.append(os.path.join(td, "плита_12шт.dxf")); open(out[-1], "wb").write(d.dxf_bytes())
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.circle((40, 40), 40); d.entities.circle((40, 40), 15)
    out.append(os.path.join(td, "шайба_30шт.dxf")); open(out[-1], "wb").write(d.dxf_bytes())
    return out


def synthetic():
    with tempfile.TemporaryDirectory() as td:
        paths = dxf(td)
        for kw, tag in ((dict(), "с зазором"), (dict(coedge=True), "общий рез (плиты)"), (dict(bridge=dict(width=2, group=5)), "мост")):
            p = paths[:1] if kw.get("coedge") else paths
            res, raw, pl, parts = run(p, 1250, 2500, 2, 2, 3.0, None, "г", None, ("rect",), log=lambda *a: None, strategy="hill",
                                      compare=not kw, **kw)
            check("синтетика, %s, «Горкой»: все проверки программы" % tag, res["ok"],
                  "; ".join(c[0] for c in res["checks"] if c[1] is False))
            if kw.get("coedge"):                       # конец листа и картинка — по деталям в порядке освобождения
                bad_c = []
                for l in pl["layouts"]:
                    if not l.get("groups"):
                        continue
                    r = R.route_sheet_coedge(l["placed"], l["groups"], parts, l["W"], l["L"], strategy="hill")
                    n_ = len(l["placed"])
                    if not (r["strip"]["of"] == n_ and r["strip"]["parts"] == max(1, math.ceil(RK.END_FRAC * n_ - 1e-9))
                            and len(r["done_polys"]) == n_):
                        bad_c.append((n_, r["strip"]["parts"], len(r["done_polys"])))
                check("синтетика, общий рез: остаток — последние 20 % деталей по освобождению (не группа целиком), цвет — по деталям",
                      not bad_c, str(bad_c[:3]))
            if not kw:
                S = res["strategies"]
                check("--compare: «Горкой» в сводке, строки конца листа у всех", "hill" in S and
                      all("strip" in v and "worst" in v["strip"] and "sheets" in v["strip"] for v in S.values()),
                      ", ".join("%s %s" % (k, v["strip"]["worst"] and (v["strip"]["worst"]["w"], v["strip"]["worst"]["l"])) for k, v in S.items()))
                check("в отчёте у раскладки — остаток к концу резки", all("strip" in l for l in res["layouts"]))
        # порядок «Горкой» в маршруте — полосы не убывают (правка — только внутри полосы)
        from sheet_nest.pack import plan
        res, raw, pl, parts = run(paths, 1250, 2500, 2, 2, 3.0, None, "г", None, ("rect",), log=lambda *a: None)
        bad, stair, pool = 0, 0, 0
        for l in pl["layouts"]:
            c = {}
            r = R.route_sheet(l["placed"], parts, l["W"], l["L"], strategy="hill", cache=c)
            C = c["prep"]
            orders = R._hill_orders([(p.center, p.poly[1]) for p in C["plans"]], (0.0, 0.0))
            if any(all(bands[a] <= bands[b] for a, b in zip(r["order"], r["order"][1:])) for _, bands in orders):
                stair += 1
                continue
            # не ступенька — только кандидат безопасных, и только если ступенька хуже по (полоса, опасные) или не нужна
            hp = C[("hill", True, True)]
            bh = min(hp, key=lambda v: (v[0]["key"], v[1]))
            sb = RK.end_strip([R._unit_of(C["plans"], [i]) for i, _ in bh[2]], l["W"], l["L"])
            pointless = len(C["plans"]) <= 1 or len(C["plans"]) < RK.STRIP_MIN
            pool += 1
            bad += not (pointless or (r["strip"]["strip"], tuple(r["risk"]["key"][:4])) < (sb["strip"], tuple(bh[0]["key"][:4])))
        check("маршрут «Горкой»: детали по полосам одного из порядков (правка не выводит деталь из её полосы), иначе — "
              "кандидат безопасных лучше ступеньки", bad == 0,
              "ступенькой %d, кандидатом безопасных %d, без причины %d" % (stair, pool, bad))


# ============================================================================================ 4) m14
def m14():
    path = os.path.join(SAMPLES, "m14.lxds")
    if QUICK or not os.path.exists(path):
        print("— m14: пропуск")
        return
    t0 = time.time()
    res, raw, pl, parts = run([path], 1500, 6000, 2, 2, 14, None, "m14", None, log=lambda *a: None, strategy="hill", compare=True)
    S = res["strategies"]
    sw, hw = S["safe"]["strip"]["worst"], S["hill"]["strip"]["worst"]
    check("m14 «Безопасный»: в конце узкая полоса во всю длину (как на станке 14.10), предупреждение в сводке",
          S["safe"]["strip"]["sheets"] == 1 and sw["l"] > 5000 and any("узкая полоса" in w for w in S["safe"]["warnings"]),
          "остаток %.0f×%.0f мм" % (sw["w"], sw["l"]))
    check("m14 «Горкой»: остаток компактный (≥ 1000 мм поперёк), без предупреждения о полосе, все проверки",
          S["hill"]["strip"]["sheets"] == 0 and hw["w"] >= 1000 and res["ok"] and not any("узкая полоса" in w for w in S["hill"]["warnings"]),
          "остаток %.0f×%.0f мм, вытянутость %.2f" % (hw["w"], hw["l"], hw["aspect"]))
    check("m14 «Горкой»: над деталями и отверстиями 0, холостой не больше «Безопасного» + 5 %",
          S["hill"]["danger"]["parts"] == 0 and S["hill"]["danger"]["holes"] == 0 and S["hill"]["idle_m"] <= 1.05 * S["safe"]["idle_m"],
          "холостой %.1f против %.1f м; маршрут %.1f с против %.1f с" % (S["hill"]["idle_m"], S["safe"]["idle_m"], S["hill"]["route_s"],
                                                                     S["safe"]["route_s"]))
    check("m14: маршрут «Горкой» не дольше «Безопасного»", S["hill"]["route_s"] <= S["safe"]["route_s"])
    res, *_ = run([path], 1500, 6000, 2, 2, 14, None, "m14", None, log=lambda *a: None, strategy="hill", bridge=dict(width=2, group=5))
    s = res["strip"]
    check("m14, мост + «Горкой»: остаток компактный, все проверки", res["ok"] and s["sheets"] == 0 and s["worst"]["w"] >= 1000,
          "остаток %.0f×%.0f мм, врезок %d" % (s["worst"]["w"], s["worst"]["l"], res["risk"]["pierces"]))
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(out):
        try:
            main([path, "--sheet", "1500x6000", "--thickness", "14", "--compare", "--strategy", "hill", "--out", td, "--name", "m"])
        except SystemExit:
            pass
    txt = out.getvalue()
    check("--compare: строки «конец листа: остаток» и «узкая полоса в конце» в таблице", "конец листа: остаток" in txt and
          "узкая полоса в конце" in txt)
    print("    (%.0f с)" % (time.time() - t0))


# ============================================================================================ 5) решётки, зонты
def samples():
    if QUICK:
        print("— решётки и зонты: пропуск")
        return
    for nm, W, L, t, co in (("reshetki_bez_listov", 1250, 2500, 1.5, (False, True)), ("zonty", 1250, 2500, 0.65, (False,)),
                            ("m30", 1505, 6005, 30, (False, True)), ("m3_grpsh", 1500, 3000, 3, (False, True))):
        path = os.path.join(SAMPLES, nm + ".lxds")
        if not os.path.exists(path):
            print("— %s: нет образца" % nm)
            continue
        for coedge in co:
            tag = "%s%s" % (nm, ", общий рез" if coedge else "")
            t0 = time.time()
            r0, *_ = run([path], W, L, 2, 2, t, None, nm, None, log=lambda *a: None, strategy="safe", coedge=coedge)
            t1 = time.time()
            r1, *_ = run([path], W, L, 2, 2, t, None, nm, None, log=lambda *a: None, strategy="hill", coedge=coedge)
            t2 = time.time()
            s0, s1 = r0["strip"], r1["strip"]
            check("%s, «Горкой»: те же листы, все проверки" % tag,
                  r1["ok"] and r1["sheets"] == r0["sheets"],
                  "листов %d; полос в конце: «Безопасный» %d, «Горкой» %d; холостой %.1f / %.1f м; %.0f / %.0f с" % (
                      r1["sheets"], s0["sheets"], s1["sheets"], r0["idle_m"], r1["idle_m"], t1 - t0, t2 - t1))
            # «Горкой» не опаснее «Безопасного»: ступенька — пока не опаснее, иначе кандидат безопасных без полосы
            worse = [k + 1 for k, (a, b) in enumerate(zip(r1["layouts"], r0["layouts"]))
                     if (a["strip"]["strip"], tuple(a["risk"]["key"][:4])) > (b["strip"]["strip"], tuple(b["risk"]["key"][:4]))]
            check("%s: на каждой раскладке «Горкой» не хуже «Безопасного» по (узкая полоса, ступени опасных)" % tag, not worse,
                  "раскладки %s; над деталями %d / %d" % (worse, r1["crossings"]["freed_parts"], r0["crossings"]["freed_parts"]))
            if nm == "m30" and not coedge:
                check("m30, «Горкой»: над плитами 0, узкой полосы нет ни на одном листе (у «Безопасного» — на %d)" % s0["sheets"],
                      r1["crossings"]["freed_parts"] == 0 and s1["sheets"] == 0,
                      "над плитами %d, полос %d, холостой %.1f м" % (r1["crossings"]["freed_parts"], s1["sheets"], r1["idle_m"]))
            if nm == "m30" and coedge:
                rem = [(l["strip"]["parts"], l["strip"]["of"]) for l in r1["layouts"]]
                check("m30, общий рез: остаток — последние 20 % деталей по освобождению, не весь лист; полосы нет",
                      all(p_ < n_ for p_, n_ in rem) and s1["sheets"] == 0 and s0["sheets"] == 0, str(rem))
            if nm == "m3_grpsh" and coedge:
                check("m3, общий рез (одна группа — ступенька ничего не даёт): «Горкой» = «Безопасный» по опасным",
                      [tuple(l["risk"]["key"][:4]) for l in r1["layouts"]] == [tuple(l["risk"]["key"][:4]) for l in r0["layouts"]],
                      "над деталями %d / %d" % (r1["crossings"]["freed_parts"], r0["crossings"]["freed_parts"]))


order()
metric()
synthetic()
m14()
samples()
print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
sys.exit(1 if fails else 0)
