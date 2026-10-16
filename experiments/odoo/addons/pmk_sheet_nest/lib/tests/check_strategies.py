# -*- coding: utf-8 -*-
"""Стратегии порядка резки (short / safe / safe0 / hill) и счёт опасных переходов (risk). «Горкой» (hill) — ещё
tests/check_hill.py (ступенька, конец листа).

    python3 tests/check_strategies.py [КАТАЛОГ_ОБРАЗЦОВ] [--quick]     (--quick — без m14 и зонтов, синтетики меньше)

1) счёт: вписанная окружность (окружность, паз, квадрат), отверстие ≥ 10 мм — поиск до ответа совпадает с вписанной
   окружностью и быстрый у длинного паза, классы вырезанного, «мелкая» деталь при любой толщине, глубина перехода
   внутри многоугольника — точно (против перебора точек); профиль станка — время только по данным профиля, плохой
   профиль — понятная ошибка; возврат в ноль (решение инженера 14.10): ret_move — число объектов под ним (против
   перебора точек), класс там же, где у move; в ключе с возвратом возврат над тремя плитами — 3, над одной — 1;
2) синтетика: плотные ряды мелких деталей у крупных (до 6 деталей) — на КАЖДОЙ раскладке safe не хуже short и safe0 по
   ключу без возврата, safe0 не хуже safe и short по ключу с возвратом (то же на сетках плит, где возврат идёт над
   несколькими; key0 конца динамики safe0 = key0 счёта measure); где перебор всех порядков той же динамикой
   обходится без переходов над освобождёнными мелкими — safe обходится (все такие раскладки); микроперемычки — правила
   освобождённых к детали не применяются; шайба с отверстием Ø50 — выход не над отверстием; язычки жалюзи — над ними
   не ходит; плита с прорезями и отверстиями — язычки строго выше отверстий (ревизия 14.10: safe0 менял язычок на
   отверстие); работа безопасных ограничена (шаги динамики на лист с неустранимыми переходами);
3) DXF: плиты с отверстиями и пазом, мелкие детали, решётка с жалюзи, подписи — все стратегии, все проверки ✓,
   сводка --compare (текст и JSON), возврат по раскладкам в JSON, предупреждения без «не обойти», два профиля станка,
   плохой профиль — сообщение, а не трассировка;
4) образцы инженера (если есть): с зазором и с общим резом — у всех стратегий (и «Горкой») те же листы, все проверки
   программы ✓, подвод внешнего контура как было, на каждой раскладке safe ≤ short и safe ≤ safe0 (без возврата), safe0 ≤ safe и
   safe0 ≤ short (с возвратом), hill не хуже safe по (узкая полоса, ступени опасных), счёт = независимый пересчёт по
   программе (tests/recount_lxds.py, и возврат в ноль: длина, метры, язычки, число объектов под ним по ступеням;
   key0 − key = это число), m14 — 0 переходов над вырезанными отверстиями Ø50.
"""
import sys, os, math, random, itertools, tempfile, json, io, contextlib, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, HERE)
from sheet_nest import geom as G, risk as RK, route as R
from sheet_nest.cli import run, main
from sheet_nest.write_lxds import build
from sheet_nest.verify import check_safe

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SAMPLES = ARGS[0] if ARGS else os.path.expanduser("~/Downloads/vent_nesting/samples")
QUICK = "--quick" in sys.argv
fails = []
H0 = (0.0, 0.0)


def check(name, cond, detail=""):
    print("%s %-78s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def rect(w, h, x=0.0, y=0.0, outer=1, layer=1):
    return dict(kind="LwPolyline", verts=[(x, y, 0.0), (x + w, y, 0.0), (x + w, y + h, 0.0), (x, y + h, 0.0)], flag=1, sp=0.0,
                layer=layer, layer_name="0", coedge=0, flag64=0, outer=outer, lead=None)


def circ(x, y, r):
    return dict(kind="Circle", c=(x, y), r=r, a0=math.pi / 4, layer=1, layer_name="0", coedge=0, flag64=0, outer=0, lead=None)


def opened(pts, layer=1):
    return dict(kind="LwPolyline", verts=[(x, y, 0.0) for x, y in pts], flag=0, sp=0.0, layer=layer, layer_name="0", coedge=0,
                flag64=0, outer=0, lead=None)


def obround(x, y, L, w):
    r = w / 2
    return dict(kind="LwPolyline", verts=[(x + r, y, 0.0), (x + L - r, y, 1.0), (x + L - r, y + w, 0.0), (x + r, y + w, 1.0)], flag=1,
                sp=0.0, layer=1, layer_name="0", coedge=0, flag64=0, outer=0, lead=None)


def part(name, w, h, inner=(), qty=1):
    return dict(name=name, qty=qty, shapes=list(inner) + [rect(w, h)], src=name + ".dxf", warnings=[])


def keys_ok(rs, where):
    """Порядок стратегий на раскладке: (нарушения) safe ≤ short, safe ≤ safe0 по ключу; safe0 ≤ safe, safe0 ≤ short по
    ключу с возвратом."""
    bad = []
    if rs["safe"]["key"] > rs["short"]["key"]:
        bad.append("%s: safe хуже short по ключу" % where)
    if rs["safe"]["key"] > rs["safe0"]["key"]:
        bad.append("%s: safe хуже safe0 по ключу" % where)
    if rs["safe0"]["key0"] > rs["safe"]["key0"]:
        bad.append("%s: safe0 хуже safe по ключу с возвратом" % where)
    if rs["safe0"]["key0"] > rs["short"]["key0"]:
        bad.append("%s: safe0 хуже short по ключу с возвратом" % where)
    return bad


# ============================================================================================ 1) счёт
def unit():
    check("вписанная окружность: круг Ø50 = 50", abs(RK.inscribed_d(circ(0, 0, 25)) - 50) < 1e-9)
    slot = dict(kind="LwPolyline", verts=[(0, -4, 0), (60, -4, 1), (60, 4, 0), (0, 4, 1)], flag=1, sp=0.0, layer=1, outer=0)
    d = RK.inscribed_d(slot)
    check("вписанная окружность: паз 8×68 = 8 (не 4·S/P ≈ 15)", abs(d - 8) < 0.05, "%.3f мм" % d)
    d = RK.inscribed_d(rect(25, 25, outer=0))
    check("вписанная окружность: квадрат 25 = 25", abs(d - 25) < 0.05, "%.3f мм" % d)
    check("паз 8 мм — отверстие < 10 (в ключ не входит)", RK.feature(slot)[0] == "holes_s")
    check("круг Ø20 — отверстие ≥ 10", RK.feature(circ(0, 0, 10))[0] == "holes")
    # отверстие ≥ 10: поиск до ответа = вписанная окружность (случайные многоугольники у порога), паз — быстро
    rnd, bad = random.Random(5), []
    for k in range(60):
        n = rnd.randint(3, 9)
        ang = sorted(rnd.uniform(0, 2 * math.pi) for _ in range(n))
        rr = rnd.uniform(4.0, 9.0)
        P = [(rr * rnd.uniform(0.7, 1.3) * math.cos(t), rr * rnd.uniform(0.7, 1.3) * math.sin(t)) for t in ang]
        s = dict(kind="LwPolyline", verts=[(x, y, 0.0) for x, y in P], flag=1, sp=0.0, layer=1, outer=0)
        d = RK.inscribed_d(s)
        if abs(d - (R.RK.HOLE_MIN - 0.05)) > 0.03 and RK.hole_big(s) != (d >= RK.HOLE_MIN - 0.05):
            bad.append(round(d, 3))
    check("отверстие ≥ 10 мм: поиск до ответа = по вписанной окружности (60 случайных у порога)", not bad, str(bad[:5]))
    t = time.process_time()
    long_ok = RK.hole_big(obround(0, 0, 600, 14)) and not RK.hole_big(obround(0, 0, 600, 8)) and RK.hole_big(rect(20, 500, outer=0))
    dt = time.process_time() - t
    check("паз 14×600, 8×600, окно 20×500: класс верный и быстро (прежде — секунды на паз)", long_ok and dt < 0.5, "%.3f с" % dt)
    sh = obround(100, 50, 300, 12)
    check("класс отверстия не зависит от начала контура и места детали (кэш по форме)",
          RK.hole_big(G.rotate_start(sh, 2)) == RK.hole_big(sh) == RK.hole_big(G.transform(sh, 0, (500, 700))) is True)
    check("гравировка и внешний контур — не отверстие", RK.feature(rect(30, 30, layer=2, outer=0)) is None and RK.feature(rect(30, 30)) is None)
    check("прорезь жалюзи (П) — язычок; прямая прорезь — нет",
          RK.feature(opened([(0, 30), (0, 0), (300, 0), (300, 30)]))[0] == "tongues" and RK.feature(opened([(0, 0), (300, 0)])) is None)
    arc = dict(kind="LwPolyline", verts=[(0, 0, 0.5), (60, 0, 0)], flag=0, sp=0.0, layer=1, outer=0, coedge=0)
    check("дуговая прорезь из двух вершин — тоже язычок", (RK.feature(arc) or ("",))[0] == "tongues")
    check("«мелкая» — по меньшей стороне габарита < 100 (толщина не важна)",
          RK.part_kind(part("a", 60, 400)) == "small" and RK.part_kind(part("b", 105, 105)) == "parts" and
          RK.part_kind(dict(part("c", 60, 40), microjoints=True)) == "mj")
    from sheet_nest import machine as MC                  # профиль станка — заготовка: считает только по данным профиля
    prof = MC.load(dict(name="тест", travel_mm_s=1000, lift_s=0.5, return_to_zero=True, mark_mm_s=500, cut=[dict(t=1.5, mm_s=100, pierce_s=1)]))
    t = MC.estimate(prof, 1.5, 10000, 500, 20000, 2000, 30, 40)
    check("профиль станка: время = рез/скорость + врезки + гравировка + (холостой + возврат)/скорость + подъёмы",
          t is not None and abs(t - (100 + 30 + 1 + 22 + 20)) < 1e-9, "%s с" % t)
    check("профиль станка: толщины нет в профиле или профиля нет — времени нет (не выдумывается)",
          MC.estimate(prof, 2.0, 1, 0, 1, 0, 1, 1) is None and MC.estimate(None, 1.5, 1, 0, 1, 0, 1, 1) is None)
    p2 = dict(prof); p2.pop("mark_mm_s")
    check("профиль станка: есть гравировка, а скорости гравировки нет — времени нет; без гравировки — есть",
          MC.estimate(p2, 1.5, 1, 5, 1, 0, 1, 1) is None and MC.estimate(p2, 1.5, 1, 0, 1, 0, 1, 1) is not None)
    errs = []
    with tempfile.TemporaryDirectory() as td:
        arr = os.path.join(td, "arr.json"); open(arr, "w").write("[1, 2]")
        bad = os.path.join(td, "bad.json"); open(bad, "w").write("{не json")
        for src in (os.path.join(td, "нет.json"), arr, bad, dict(travel_mm_s=1000, cut=[dict(t=3, mm_s=0)]),
                    dict(travel_mm_s=0, cut=[dict(t=3, mm_s=1)]), dict(travel_mm_s=1000), dict(travel_mm_s=1000, cut=["x"])):
            try:
                MC.load(src)
                errs.append("принят: %r" % (src,))
            except ValueError:
                pass
            except Exception as e:
                errs.append("%s: %s" % (type(e).__name__, e))
    check("профиль станка: нет файла, не объект, не JSON, скорость 0, без cut — ValueError с текстом", not errs, "; ".join(errs))
    rnd, bad = random.Random(7), 0
    for _ in range(150):                                  # точная глубина против перебора точек
        n = rnd.randint(3, 8)
        ang = sorted(rnd.uniform(0, 2 * math.pi) for _ in range(n))
        P = [(50 + rnd.uniform(10, 40) * math.cos(t), 50 + rnd.uniform(10, 40) * math.sin(t)) for t in ang]
        a, b = (rnd.uniform(0, 100), rnd.uniform(0, 100)), (rnd.uniform(0, 100), rnd.uniform(0, 100))
        m = rnd.choice([0.5, 1.0, 3.0])
        L, N = math.dist(a, b), 4000
        edges = list(zip(P, P[1:] + P[:1]))
        bf = sum(L / N for k in range(N) for pt in [(a[0] + (b[0] - a[0]) * (k + 0.5) / N, a[1] + (b[1] - a[1]) * (k + 0.5) / N)]
                 if G.inside(pt, P) and min(G.seg_point_dist(pt, p, q) for p, q in edges) > m)
        bad += abs(RK.deep_len(a, b, (P, RK._bbox(P), None), m) - bf) > 0.02 + 2 * L / N
    check("глубина перехода внутри многоугольника — точно (150 случайных)", bad == 0, "расхождений %d" % bad)
    ret_unit()


def ret_unit():
    """Возврат в ноль (решение инженера 14.10.2026): в ключе с возвратом — число объектов под ним, переходы программы —
    0/1."""
    sh = RK.Sheet()
    for k in range(4):                                    # 4 плиты на диагонали, мелкая — в стороне
        sh.add("parts", RK.obstacle(rect(150, 150, 20 + 200 * k, 20 + 200 * k)))
    sh.add("small", RK.obstacle(rect(60, 40, 700, 300)))
    v1, v0 = RK.move((900.0, 900.0), H0, sh), RK.ret_move((900.0, 900.0), H0, sh)
    check("возврат: ret_move — число деталей под ним (4 плиты на диагонали — 4), переход программы (move) — 1",
          v0[RK.PART] == 4 and v1[RK.PART] == 1 and v0[RK.SMALLP] == v1[RK.SMALLP] == 0, "ret_move %s, move %s" % (v0, v1))
    # случайные: число объектов — по перебору точек (глубина у прямоугольника и круга — аналитически, не risk.deep_len);
    # класс ненулевой там же, где у move; впритирку и короткий — как у move
    rnd, bad, multi, amb = random.Random(11), [], 0, 0
    for case in range(150):
        sh, objs = RK.Sheet(), []
        for k in range(rnd.randint(6, 14)):
            kind = rnd.choice(["small", "parts", "holes", "tongues"])
            x, y = rnd.uniform(0, 380), rnd.uniform(0, 380)
            if kind == "holes" and rnd.random() < 0.5:
                r = rnd.uniform(5, 40)
                ob, dep = RK.obstacle(circ(x, y, r)), (lambda p, x=x, y=y, r=r: r - math.dist(p, (x, y)))
            else:
                w, h = rnd.uniform(8, 110), rnd.uniform(8, 110)
                ob = RK.obstacle(rect(w, h, x, y, outer=0))
                dep = (lambda p, x=x, y=y, w=w, h=h: min(p[0] - x, x + w - p[0], p[1] - y, y + h - p[1]))
            sh.add(kind, ob); objs.append((kind, dep))
        a, b = (rnd.uniform(0, 500), rnd.uniform(0, 500)), (rnd.uniform(0, 500), rnd.uniform(0, 500))
        L, N = math.dist(a, b), 3000
        pts = [(a[0] + (b[0] - a[0]) * (k + 0.5) / N, a[1] + (b[1] - a[1]) * (k + 0.5) / N) for k in range(N)]
        lens = [(kind, sum(L / N for p in pts if dep(p) > RK._MARGIN[kind])) for kind, dep in objs]
        if any(abs(x - RK.MIN_OVER) < 0.05 for _, x in lens):
            amb += 1                                      # у порога перебор точек не решает — пропуск
            continue
        v1, v0 = RK.move(a, b, sh), RK.ret_move(a, b, sh)
        for kind in ("small", "parts", "holes", "tongues"):
            i = RK.IDX[kind]
            n = sum(1 for k_, x in lens if k_ == kind and x >= RK.MIN_OVER)
            multi += n >= 2
            if v0[i] != max(n, v1[i]) or bool(v0[i]) != bool(v1[i]):
                bad.append((case, kind, v0[i], n, v1[i]))
        if v0[RK.NEARP] != v1[RK.NEARP] or v0[RK.SHORT] != v1[RK.SHORT]:
            bad.append((case, "near/short", v0, v1))
    check("возврат: ret_move = число объектов по перебору точек, класс там же, где у move (150 случайных, из них по ≥ 2 "
          "объекта в классе — %d)" % multi, not bad and multi >= 10, "расхождений %d %s; у порога пропущено %d" % (len(bad), bad[:3], amb))
    # ключ с возвратом (measure key0): четыре плиты на диагонали, два порядка — у X возврат над тремя плитами, у Y — над
    # одной; по холостому с возвратом X короче (правило «возврат — один переход» выбрало бы его), по числу — Y лучше
    P = [rect(150, 150, 20 + 200 * k, 20 + 200 * k) for k in range(4)]
    tr = lambda i: G.rotate_start(P[i], 2)                # врезка в правом верхнем углу
    mx = RK.measure([(tr(0), 0), (tr(1), 1), (tr(2), 2), (P[3], 3)], ["parts"] * 4, P)
    my = RK.measure([(P[3], 3), (P[2], 2), (tr(0), 0), (P[1], 1)], ["parts"] * 4, P)
    ok = (mx["key"][:4] == my["key"][:4] == (0, 0, 0, 0) and mx["ret"]["n_parts"] == 3 and my["ret"]["n_parts"] == 1 and
          mx["key0"][:4] == (0, 0, 3, 0) and my["key0"][:4] == (0, 0, 1, 0) and mx["ret"]["over"] == my["ret"]["over"] == 1 and
          abs(mx["key0"][4] - mx["key"][4] - mx["ret"]["m"] * 1000) < 1e-6 and mx["key0"][4] < my["key0"][4] and
          my["key0"] < mx["key0"] and mx["moves"][-1][2][RK.PART] == 3)
    check("ключ с возвратом: возврат над тремя плитами — 3 в ступени деталей (не 1), над одной — 1; по ключу лучше Y, "
          "хотя холостой с возвратом короче у X", ok, "X: key0 %s, Y: key0 %s" % (
              [round(x, 1) for x in mx["key0"]], [round(x, 1) for x in my["key0"]]))


# ============================================================================================ 2) синтетика
def dense(seed):
    """Плотно, как упаковщик: ряды снизу вверх, зазор 2 мм; 5–6 деталей (крупная с отверстиями, мелкие, планки)."""
    rnd = random.Random(seed)
    parts = [part("крупная", 300, 200, [circ(60, 60, 15), circ(240, 140, 4)]), part("мелкая", 60, 40, [circ(30, 20, 3)]),
             part("планка", 30, 90), part("мелкая2", 80, 50)]
    dims = {0: (300, 200), 1: (60, 40), 2: (30, 90), 3: (80, 50)}
    n, W = rnd.randint(5, 6), rnd.choice([200, 260, 340])
    placed, x, y, rowh = [], 2.0, 2.0, 0.0
    while len(placed) < n:
        pi = rnd.choice([0, 1, 1, 2, 3, 1])
        w, h = dims[pi]
        if w > W - 4:
            continue
        if x + w > W - 2:
            x, y, rowh = 2.0, y + rowh + 2.0, 0.0
        placed.append(dict(part=pi, rot=0, dx=x, dy=y)); x += w + 2.0; rowh = max(rowh, h)
    return parts, placed, W, y + rowh + 2.0


def grid(seed):
    """Сетка плит и мелких деталей с отверстиями (зазор 2 мм): возврат от дальней детали идёт над несколькими."""
    rnd = random.Random(seed)
    parts = [part("плита", 220, 160, [circ(60, 50, 12), circ(160, 110, 6)]), part("мелкая", 80, 60, [circ(40, 30, 8)]),
             part("полоса", 300, 90)]
    dims = {0: (220, 160), 1: (80, 60), 2: (300, 90)}
    cols, rows = rnd.randint(3, 5), rnd.randint(2, 4)
    placed, y = [], 2.0
    for j in range(rows):
        x, rowh = 2.0, 0.0
        for i in range(cols):
            pi = rnd.choice([0, 0, 1, 2])
            w, h = dims[pi]
            placed.append(dict(part=pi, rot=0, dx=x, dy=y)); x += w + 2.0; rowh = max(rowh, h)
        y += rowh + 2.0
    W = max(q["dx"] + dims[q["part"]][0] for q in placed) + 2.0
    return parts, placed, W, y


def plate406():
    """Плита из ревизии 14.10 (прорези-язычки и отверстия ≥ 10 мм рядом): safe0 шёл над язычком ради отверстия."""
    inner = [circ(x, y, r) for (x, y), r in [((274.47, 180.66), 7.81), ((142.35, 235.11), 6.77), ((188.74, 204.8), 16.67),
                                            ((137.35, 70.7), 9.61), ((44.92, 154.93), 11.79)]]
    inner += [opened(p) for p in [[(131.7, 147.05), (131.7, 112.05), (191.26, 112.05), (191.26, 147.05)],
                                  [(259.95, 156.49), (239.28, 156.49), (239.28, 189.86), (259.95, 189.86)],
                                  [(154.1, 55.37), (154.1, 16.97), (199.57, 16.97), (199.57, 55.37)],
                                  [(145.8, 169.43), (129.53, 169.43), (129.53, 187.81), (145.8, 187.81)]]]
    for s in inner:
        if s["kind"] == "Circle":
            s["a0"] = 0.0                                 # как из DXF: начало окружности — угол 0
    return [dict(name="плита", qty=1, shapes=inner + [rect(289.27, 267.57)], src="плита.dxf", warnings=[])]


def synthetic():
    seeds = range(0, 60 if QUICK else 200)
    bad, n_av, n_ok, miss = [], 0, 0, []
    o = R.options("safe")
    for seed in seeds:
        parts, placed, W, L = dense(seed)
        rs = {st: R.route_sheet(placed, parts, W, L, strategy=st)["risk"] for st in R.STRATEGIES}
        bad += keys_ok(rs, "сид %d" % seed)
        if not rs["short"]["small"]:
            continue
        if rs["safe"]["small"]:                           # перебор всех порядков той же динамикой: можно ли без них
            C = R._prep(placed, parts, W, L, H0, RK.SMALL, None)
            best = min(R._measure(C, r, H0)["key"] for p in itertools.permutations(range(len(placed))) for r in R._dp_safe(C, list(p), H0, o))
            if best[1] == 0:
                n_av += 1
                miss.append(seed)
        else:
            n_av += 1
            n_ok += 1
    check("плотные ряды (%d раскладок): safe ≤ short и ≤ safe0 по ключу, safe0 ≤ safe и ≤ short с возвратом" % len(seeds), not bad,
          "; ".join(bad[:4]))
    check("плотные ряды: где перебор порядков обходится без переходов над мелкими — safe тоже (все)", n_av > 0 and not miss,
          "%d из %d; не обошёл: %s" % (n_ok, n_av, miss or "—"))
    # возврат по числу объектов под ним: динамика safe0 оптимизирует тот же ключ, что считает measure (key0 конца динамики
    # = key0 счёта готового маршрута) — порядок «от нуля к дальней», возврат от дальней детали идёт над несколькими;
    # и порядок стратегий на сетках
    o0, bad0, bad1, multi = R.options("safe0"), [], [], 0
    for seed in range(10 if QUICK else 30):
        parts, placed, W, L = grid(seed)
        C = R._prep(placed, parts, W, L, H0, RK.SMALL, None)
        s = sorted(range(len(placed)), key=lambda i: (math.dist(C["plans"][i].center, H0), i))
        rk, rk0, k, k0 = R._dp_safe(C, s, H0, o0, keys=True)
        m0 = R._measure(C, rk0, H0)
        multi += m0["ret"]["n_small"] + m0["ret"]["n_parts"] >= 2
        if m0["key0"][:4] != k0[:4] or abs(m0["key0"][4] - k0[4]) > 1e-6:
            bad0.append((seed, k0, m0["key0"]))
        rs = {st: R.route_sheet(placed, parts, W, L, strategy=st)["risk"] for st in R.STRATEGIES}
        bad1 += keys_ok(rs, "сетка %d" % seed)
    check("возврат: key0 динамики safe0 = key0 счёта measure (одна ret_move; сеток %d, возврат над ≥ 2 деталями — %d)" % (
        10 if QUICK else 30, multi), not bad0 and multi > 0, str(bad0[:3]))
    check("сетки плит: safe ≤ short и ≤ safe0 по ключу, safe0 ≤ safe и ≤ short с возвратом (по числу под ним)", not bad1,
          "; ".join(bad1[:4]))
    # микроперемычки: те же раскладки — правила освобождённых не применяются, переход над такой деталью — «с перемычками»
    parts, placed, W, L = dense(27)                       # у «short» здесь переходы над мелкими есть (2)
    r0 = R.route_sheet(placed, parts, W, L, strategy="short")["risk"]
    pm = [dict(p, microjoints=True) for p in parts]
    r1 = R.route_sheet(placed, pm, W, L, strategy="short")["risk"]
    check("микроперемычки: над мелкой с перемычками — не «мелкие», а «с перемычками»", r0["small"] > 0 and r1["small"] == 0 and
          r1["mj"] >= r0["small"], "без: мелких %d; с: мелких %d, с перемычками %d" % (r0["small"], r1["small"], r1["mj"]))
    rs1 = R.route_sheet(placed, pm, W, L, strategy="safe")
    check("микроперемычки: в ключе безопасного их нет (мелких 0, деталей 0)", rs1["risk"]["small"] == 0 and rs1["risk"]["parts"] == 0)
    # шайбы с отверстием Ø50 (как m14): выход из отверстия не над ним — у всех стратегий
    wp = [dict(name="шайба", qty=1, shapes=[circ(52.5, 52.5, 25), dict(circ(52.5, 52.5, 52.5), outer=1)], src="w", warnings=[])]
    placed = [dict(part=0, rot=0, dx=2 + 107 * (k % 5), dy=2 + 107 * (k // 5)) for k in range(25)]
    leg = R.route_sheet(placed, wp, 540, 540, strategy=dict(key="short"))["risk"]
    for st in R.STRATEGIES:
        r = R.route_sheet(placed, wp, 540, 540, strategy=st)["risk"]
        check("шайбы Ø105/Ø50, %s: над вырезанными отверстиями ≥ 10 мм — 0 (как было: %d)" % (st, leg["holes"]), r["holes"] == 0,
              "отверстий %d, холостой %.0f мм (было %.0f)" % (r["holes"], r["idle"], leg["idle"]))
    # язычки жалюзи: деталь с П-прорезями между двумя мелкими — над язычками не ходит никто
    lv = part("жалюзи", 500, 300, [opened([(60, y + 30), (60, y), (440, y), (440, y + 30)]) for y in (60, 140, 220)])
    sm = part("мелкая", 60, 40)
    parts = [lv, sm]
    placed = [dict(part=1, rot=0, dx=2, dy=2), dict(part=0, rot=0, dx=64, dy=2), dict(part=1, rot=0, dx=566, dy=2),
              dict(part=1, rot=0, dx=2, dy=44)]
    for st in R.STRATEGIES:
        r = R.route_sheet(placed, parts, 700, 400, strategy=st)
        check("жалюзи между мелкими, %s: над язычками 0" % st, r["risk"]["tongues"] == 0 and r["crossings"] == 0,
              "язычки %d (как было %d)" % (r["risk"]["tongues"], r["crossings"]))
    # язычки строго выше отверстий: плита ревизии — у всех стратегий 0 переходов над язычками
    pp = plate406()
    placed = [dict(part=0, rot=0, dx=2, dy=2)]
    xs = {st: R.route_sheet(placed, pp, 900, 272, strategy=st)["risk"] for st in R.STRATEGIES}
    check("плита с прорезями и отверстиями: над язычками 0 у всех (язычок не меняется на отверстие)",
          all(v["tongues"] == 0 for v in xs.values()), ", ".join("%s: язычки %d, отверстия %d" % (k, v["tongues"], v["holes"]) for k, v in xs.items()))
    # работа безопасных ограничена: ряд мелких деталей с местом под подвод с одной стороны — переходы над ними не уходят
    parts = [dict(name="small", qty=1, shapes=[circ(30, 20, 7), rect(60, 40)], src="s.dxf", warnings=[]),
             dict(name="big", qty=1, shapes=[circ(100, 100, 20), circ(300, 100, 20), rect(400, 200)], src="b.dxf", warnings=[])]
    placed = [dict(part=1, rot=0, dx=2 + k * 402, dy=2) for k in range(3)]
    placed += [dict(part=0, rot=0, dx=2 + i * 62, dy=204 + j * 42) for j in range(4) for i in range(10)]
    steps = [0]
    f = R._dp_safe

    def counted(C, seq, head, o, *a, **k):
        steps[0] += len(seq) - k.get("start", 0)
        return f(C, seq, head, o, *a, **k)
    R._dp_safe = counted
    try:
        r = R.route_sheet(placed, parts, 1250, 380, strategy="safe")
    finally:
        R._dp_safe = f
    n = len(placed)
    # правка по ключам: key — max(REPAIR_WORK·n, REPAIR_MIN), key1 (прежний конец) и key0 (возврат по числу) — по REPAIR_WORK·n
    lim = (3 + 4 + 2 * R.REPAIR_WORK + 2) * n + max(R.REPAIR_WORK * n, R.REPAIR_MIN)
    check("безопасный: работа на лист ограничена (шагов динамики ≤ %d при %d деталях; прежде — до 80 прогонов)" % (lim, n),
          steps[0] <= lim, "шагов %d, осталось над мелкими %d, над деталями %d" % (steps[0], r["risk"]["small"], r["risk"]["parts"]))


# ============================================================================================ 3) DXF + сводка
def dxf_files(td):
    import dxf_writer as DW
    out = []

    def doc():
        d = DW.DxfDoc(version="AC1015", insunits=4); d.layer("ГРАВИРОВКА"); return d
    d = doc(); e = d.entities
    e.lwpolyline([(0, 0), (400, 0), (400, 300), (0, 300)], closed=True)
    e.circle((80, 80), 10); e.circle((320, 80), 4)
    e.lwpolyline([(150, 146, 0), (210, 146, 1), (210, 154, 0), (150, 154, 1)], closed=True)
    e.lwpolyline([(300, 200), (325, 200), (325, 225), (300, 225)], closed=True)
    out.append(os.path.join(td, "плита_6шт.dxf")); open(out[-1], "wb").write(d.dxf_bytes())
    d = doc(); e = d.entities
    e.lwpolyline([(0, 0), (60, 0), (60, 40), (0, 40)], closed=True); e.circle((30, 20), 3)
    out.append(os.path.join(td, "мелкая_16шт.dxf")); open(out[-1], "wb").write(d.dxf_bytes())
    d = doc(); e = d.entities
    e.lwpolyline([(0, 0), (30, 0), (30, 90), (0, 90)], closed=True)
    out.append(os.path.join(td, "планка_10шт.dxf")); open(out[-1], "wb").write(d.dxf_bytes())
    d = doc(); e = d.entities
    e.lwpolyline([(0, 0), (500, 0), (500, 300), (0, 300)], closed=True)
    for k in range(3):
        y = 60 + 80 * k
        e.lwpolyline([(60, y + 30), (60, y), (440, y), (440, y + 30)], closed=False)
        e.line((5, y + 29), (40, y + 29), layer="ГРАВИРОВКА"); e.line((460, y + 29), (495, y + 29), layer="ГРАВИРОВКА")
    out.append(os.path.join(td, "решётка_3шт.dxf")); open(out[-1], "wb").write(d.dxf_bytes())
    return out


def dxf_run():
    from sheet_nest import labels as LB
    try:
        LB.load_font()
        labels = {"плита": "П-1", "решётка": "Р-2"}
    except LB.LabelError:
        labels = None
        print("— нет шрифта подписей: синтетика без подписей")
    with tempfile.TemporaryDirectory() as td:
        paths = dxf_files(td)
        sheets = set()
        for st in R.STRATEGIES:
            res, raw, pl, parts = run(paths, 1000, 2000, 2, 2, 1.0, None, "синт", None, log=lambda *a: None, strategy=st,
                                      labels=labels, compare=(st == "safe"), microjoints=["планка"])
            sheets.add(res["sheets"])
            check("DXF (плиты, пазы, мелкие, жалюзи%s), %s: все проверки программы" % (", подписи" if labels else "", st), res["ok"],
                  "; ".join(c[0] for c in res["checks"] if c[1] is False))
            if st == "safe":
                S = res.get("strategies") or {}
                check("--compare: сводка по всем стратегиям (%d), листы одинаковые" % len(R.STRATEGIES), sorted(S) == sorted(R.STRATEGIES) and
                      len({v["sheets"] for v in S.values()}) == 1, str(sorted(S)))
                check("--compare: в сводке рез, холостой, возврат, врезки, классы, время маршрута, станков нет — пусто",
                      all({"cut_m", "idle_m", "return_m", "pierces", "danger", "route_s", "machine_s"} <= set(v) and v["machine_s"] == {}
                          for v in S.values()))
                check("микроперемычки: в отчёте детали и переходы над ними — отдельно", res["microjoints"] == ["планка"])
                check("старые ключи crossings — как были, новые — рядом", {"tongues", "parts"} <= set(res["crossings"]) and
                      res["crossings"]["holes"] == res["risk"]["holes"])
                lr = res["layouts"][0]["risk"]
                check("раскладка в отчёте: возврат целиком (длина, над деталями, язычков под ним, объектов под ним по ступеням), "
                      "метры над деталями, ключи",
                      {"ret_m", "ret_over_m", "ret", "over_parts_m", "key", "key0"} <= set(lr) and
                      {"m", "over_m", "tongues_crossed", "over", "n_tongues", "n_small", "n_parts", "n_holes"} <= set(lr["ret"]) and
                      sum(l["risk"]["ret"]["tongues_crossed"] * l["amount"] for l in res["layouts"]) == res["risk"]["ret"]["tongues_crossed"])
                w = [x for x in res["warnings"] if "раскладка" in x]
                check("предупреждение об оставшихся опасных — «не смогла», без «не обойти»", all("не обойти" not in x for x in res["warnings"]),
                      w[0] if w else "нет оставшихся")
        check("DXF: у всех стратегий одно число листов", len(sheets) == 1, str(sheets))
        # командная строка: --compare, два профиля станка (у второго нет толщины — «—»)
        p1, p2 = os.path.join(td, "станок1.json"), os.path.join(td, "станок2.json")
        json.dump(dict(name="Станок 1", travel_mm_s=1000, lift_s=0.2, return_to_zero=True, mark_mm_s=300,
                       cut=[dict(t=1, mm_s=300, pierce_s=0.2)]), open(p1, "w"), ensure_ascii=False)
        json.dump(dict(name="Станок 2", travel_mm_s=800, cut=[dict(t=3, mm_s=100, pierce_s=0.5)]), open(p2, "w"), ensure_ascii=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                main(paths + ["--sheet", "1000x2000", "--thickness", "1", "--compare", "--strategy", "safe0", "--out", td, "--name", "cmp",
                              "--machine", p1, "--machine", p2])
            except SystemExit as e:
                code = e.code
        txt = out.getvalue()
        js = [f for f in os.listdir(td) if f.startswith("cmp") and f.endswith(".json")]
        js = json.load(open(os.path.join(td, js[0]))) if js else {}
        check("командная строка --compare: таблица и JSON, программа — по --strategy", code == 0 and "сводка по стратегиям" in txt and
              all(v["title"] in txt for v in R.STRATEGIES.values()) and js.get("strategy") == "safe0" and
              len(js.get("strategies", {})) == len(R.STRATEGIES))
        ms = [v["machine_s"] for v in js.get("strategies", {}).values()]
        check("два профиля станка: строка на каждый; толщины нет в профиле — «—»", "станок «Станок 1»" in txt and "станок «Станок 2»" in txt
              and ms and all(m.get("Станок 1") and m.get("Станок 2", 0) is None for m in ms), str(ms[:1]))
        check("командная строка: картинка с легендой опасных переходов", any(f.startswith("cmp") and f.endswith(".png") for f in os.listdir(td)))
        bad = os.path.join(td, "плохой.json"); open(bad, "w").write('{"travel_mm_s": 1000, "cut": [{"t": 1, "mm_s": 0}]}')
        for prof in (bad, os.path.join(td, "нет.json")):
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    main(paths[:1] + ["--sheet", "1000x2000", "--thickness", "1", "--machine", prof, "--out", td])
                msg = "выход без ошибки"
            except SystemExit as e:
                msg = str(e.code)
            except Exception as e:
                msg = "трассировка: %s" % type(e).__name__
            check("плохой профиль станка (%s) — сообщение, а не трассировка" % os.path.basename(prof),
                  msg.startswith("ошибка:") and "профиль станка" in msg, msg[:90])


# ============================================================================================ 4) образцы
def samples():
    from recount_lxds import recount
    cfg = [("m3_grpsh", 1500, 3000, 3), ("m30", 1505, 6005, 30), ("reshetki_bez_listov", 1250, 2500, 1.5)]
    if not QUICK:
        cfg += [("zonty", 1250, 2500, 0.65), ("m14", 1500, 6000, 14)]
    for nm, W, L, t in cfg:
        path = os.path.join(SAMPLES, nm + ".lxds")
        if not os.path.exists(path):
            print("— %s: нет образца, пропуск" % nm)
            continue
        for coedge in (False, True):
            tag = "%s, %s" % (nm, "общий рез" if coedge else "с зазором")
            t0 = time.time()
            res, raw, pl, parts = run([path], W, L, 2, 2, t, None, nm, None, log=lambda *a: None, coedge=coedge, compare=True)
            if coedge and not pl.get("coedge"):
                print("— %s: общий рез не раскладывается — то же, что с зазором" % tag)
                continue
            S = res["strategies"]
            check("%s: у всех стратегий одни листы (%d)" % (tag, res["sheets"]), len({v["sheets"] for v in S.values()}) == 1)
            lay = pl["layouts"]
            risks, lead, strips = {}, {}, {}
            for st in list(R.STRATEGIES) + ["как было"]:
                strat = st if st in R.STRATEGIES else dict(key="short")
                rs = []
                for l in lay:
                    r = (R.route_sheet_coedge(l["placed"], l["groups"], parts, l["W"], l["L"], strategy=strat) if l.get("groups")
                         else R.route_sheet(l["placed"], parts, l["W"], l["L"], strategy=strat))
                    rs.append(r)
                L2 = [dict(l, seq=r["seq"], idle=r["idle"]) for l, r in zip(lay, rs)]
                raw2, _ = build(parts, L2, "x")
                rep, rr, ctx = check_safe(raw2, parts, L2, 2.0, 2.0, t)
                ok = all(x[1] is not False for x in rep)
                lead[st] = next(((x[1], x[2]) for x in rep if "подвод" in x[0]), (True, ""))
                risks[st] = [r["risk"] for r in rs]
                strips[st] = [r["strip"] for r in rs]
                if st in R.STRATEGIES:
                    check("%s, %s: все проверки программы" % (tag, st), ok, "; ".join(x[0] for x in rep if x[1] is False))
                    rc = recount(raw2, parts, L2)
                    diff = [(k, c, r["risk"][c], rc[k][c]) for k, r in enumerate(rs) for c in RK.CLASSES if r["risk"][c] != rc[k][c]]
                    diff += [(k, "ret", r["risk"]["ret"]["m"], rc[k]["ret_m"]) for k, r in enumerate(rs) if abs(r["risk"]["ret"]["m"] - rc[k]["ret_m"]) > 1e-6]
                    # метры над деталями: пересчёт — точками через 0,1 мм по многоугольникам (окружность — ломаной),
                    # ~0,1 мм на каждую пересечённую кромку: m14 — возврат над ~45 шайбами, расхождение 4 мм на 4,7 м
                    diff += [(k, "ret_over", r["risk"]["ret"]["over_m"], rc[k]["ret_over_m"]) for k, r in enumerate(rs)
                             if abs(r["risk"]["ret"]["over_m"] - rc[k]["ret_over_m"]) > 0.002 + 0.002 * rc[k]["ret_over_m"]]
                    diff += [(k, "ret_tg", r["risk"]["ret"]["tongues_crossed"], rc[k]["ret_tongues"]) for k, r in enumerate(rs)
                             if r["risk"]["ret"]["tongues_crossed"] != rc[k]["ret_tongues"]]
                    # возврат в ключе с возвратом — число объектов под ним по ступеням (ret_move) = пересчёт точками
                    diff += [(k, "ret_n_" + c, r["risk"]["ret"]["n_" + c], rc[k]["ret_n_" + c]) for k, r in enumerate(rs)
                             for c in ("tongues", "small", "parts", "holes") if r["risk"]["ret"]["n_" + c] != rc[k]["ret_n_" + c]]
                    diff += [(k, "key0-key", r["risk"]["key0"][:4], r["risk"]["key"][:4]) for k, r in enumerate(rs)
                             if tuple(a - b for a, b in zip(r["risk"]["key0"][:4], r["risk"]["key"][:4])) !=
                             tuple(r["risk"]["ret"]["n_" + c] for c in ("tongues", "small", "parts", "holes"))]
                    check("%s, %s: счёт и возврат в ноль (и число объектов под ним) = независимый пересчёт по программе" % (tag, st),
                          not diff, str(diff[:4]) if diff else
                          ", ".join("%s %d" % (c, sum(r["risk"][c] * l["amount"] for r, l in zip(rs, lay))) for c in RK.CLASSES))
                    if nm == "m14" and st == "safe":
                        check("m14, безопасный: над вырезанными отверстиями Ø50 — 0", sum(r["risk"]["holes"] for r in rs) == 0)
            bad = [b for k in range(len(lay)) for b in keys_ok({st: risks[st][k] for st in R.STRATEGIES}, "раскладка %d" % (k + 1))]
            check("%s: на каждой раскладке safe ≤ short, safe ≤ safe0; с возвратом safe0 ≤ safe, safe0 ≤ short" % tag, not bad,
                  "; ".join(bad[:3]))
            # «Горкой» — ступенька, пока не опаснее; иначе кандидат безопасных без узкой полосы: не хуже safe по (полоса, опасные)
            hb = [k + 1 for k in range(len(lay)) if (bool(strips["hill"][k]["strip"]), tuple(risks["hill"][k]["key"][:4])) >
                  (bool(strips["safe"][k]["strip"]), tuple(risks["safe"][k]["key"][:4]))]
            check("%s: на каждой раскладке «Горкой» не хуже safe по (узкая полоса в конце, ступени опасных)" % tag, not hb,
                  "раскладки %s" % hb[:5])

            def lmin(v):
                import re
                m_ = re.search(r"наименьшее ([0-9.]+)", v[1])
                return float(m_.group(1)) if m_ else None
            # правило выбора точки врезки — «свободно» (lead_free), как было; подвод по кромке соседа (⚠ с 16.10, lead_room)
            # у разных маршрутов разный — в сравнение не входит (только в текст)
            base_ = lmin(lead["как было"])
            same = all((lmin(v) is None) == (base_ is None) for v in lead.values()) and (base_ is None or all(
                lmin(v) >= min(base_, R.LEAD_FREE) - 1e-9 for v in lead.values()))
            check("%s: подвод внешнего контура — правило как было (≥ %g мм или не меньше, чем было)" % (tag, R.LEAD_FREE), same,
                  "; ".join("%s: %s" % (k, v[1]) for k, v in lead.items()))
            print("    (%.0f с)" % (time.time() - t0))


unit()
synthetic()
dxf_run()
samples()
print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
sys.exit(1 if fails else 0)
