# -*- coding: utf-8 -*-
"""Мост (Bridge CypCut, решение Антона 14.10.2026 «делай мост»).

    python3 tests/check_bridge.py [КАТАЛОГ_ОБРАЗЦОВ] [--quick]      (--quick — без m14 целиком)

1) эталон: группа Антона из 5 шайб (~/Downloads/vent_nesting/bridge_research): по осям его перемычек контур совпадает с
   полилинией CypCut (вершины ± 1e-3 мм, bulge ± 1e-4, с точностью до начала списка, то же направление, длина ± 0,01 мм);
   по линии центров (наши перемычки) — та же топология (16 вершин, те же окружности по порядку), длина ± 0,01 мм;
   у CypCut ширина перемычек — ровно 2,000 мм, оси нарисованы рукой (наклон 2,6…16,5° к линии центров);
2) геометрия: случайные деревья окружностей (сетка, «соты», разные радиусы, ширина 0,5…5 мм) — контур против часовой,
   длина = аналитической, граница объединения окружностей и перемычек (verify._check_bridge — независимо от построения);
   врезка в каждом кандидате — та же площадь и длина, вершина 0 на дуге не ближе 2 мм по дуге к перемычке; окружность
   полилинией из дуг — тоже окружность, прямоугольник — нет;
3) группы: на сетке шайб m14 — деревья ≤ N деталей, перемычки только между соседями через зазор, одиночек мало; N = 2…8;
4) формат (синтетика DXF): вставка моста без NestPart/NestGroup (ChannelPort=1), блок — число, OutlineID — общий
   контур, без Flags; контур flag 5, sp 0, outer 0, coedge 0, flag64 0, без LeadParam; отверстия раньше контура;
   Amount — заказ, AmountUsed и PartCount — без деталей мостов, загрузка — как без моста; висячих блоков нет; все
   проверки программы ✓ у всех стратегий; врезок меньше на (деталей в мостах − групп);
5) порча: контур не по CypCut (flag), сдвинутая на 0,05 мм прямая перемычки, вставка моста без группы в раскрое — проверка
   программы даёт ✗, а не падение;
6) чтение: программа CypCut с мостом — детали из неё (шайбы, 704 = Amount), разбор (decompile_free) и картинка не падают;
   наша программа с мостами — тоже 704;
7) кнопки: мост + общий рез — понятная ошибка; ширина 0, группа 1 — ошибка; ширина ≥ радиуса — без моста, с причиной;
8) m14 целиком (не в --quick): мост + «Горкой» — все проверки ✓, врезок 1408 → 847, время ≤ 2× «Безопасного» без моста;
9) диски без отверстий (у всех групп отверстия одинаково пустые — вставка сверяется с группой по окружностям контура, а
   не по отверстиям) и вперемешку с шайбами — все проверки ✓ у всех стратегий; вставка моста — копия другой — ✗;
   окружности, на дуге которых нет места под врезку (Ø1,4 мм), — без моста с причиной,
   маршрут не падает.
"""
import sys, os, io, math, random, zipfile, tempfile, time, collections, copy
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
from sheet_nest import geom as G, bridge as BR, route as R, verify as V
from sheet_nest.cli import run
from sheet_nest.libpath import vn
from sheet_nest.write_lxds import build, decompile_free, FREE

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SAMPLES = ARGS[0] if ARGS else os.path.expanduser("~/Downloads/vent_nesting/samples")
RESEARCH = os.path.expanduser("~/Downloads/vent_nesting/bridge_research")
QUICK = "--quick" in sys.argv
fails = []


def check(name, cond, detail=""):
    print("%s %-82s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def cyc_dev(A, B):
    """Наименьшее по сдвигу начала списка расхождение вершин (мм) и bulge."""
    n = len(A)
    best = None
    for s in range(n):
        dp = max(math.dist(A[(s + i) % n][:2], B[i][:2]) for i in range(n))
        db = max(abs(A[(s + i) % n][2] - B[i][2]) for i in range(n))
        if best is None or dp < best[0]:
            best = (dp, db)
    return best


# ============================================================================================ 1) эталон CypCut
W5 = [(54.5, 54.5, 52.5), (54.5, 161.5, 52.5), (54.5, 268.5, 52.5), (161.5, 54.5, 52.5), (161.5, 161.5, 52.5)]
E5 = [(0, 1), (1, 2), (0, 3), (1, 4)]


def cypcut_contour():
    """Общий контур моста из программы CypCut (блок с числовым именем) — пакетом, как данные."""
    import xml.etree.ElementTree as ET
    raw = open(os.path.join(RESEARCH, "m14_most_cypcut.lxds"), "rb").read()
    M = decompile_free(raw)
    ins = [i for r in M["results"] for i in r["inserts"] if i["ref"] == FREE]
    blk = {b["name"]: b for b in M["blocks"]}[ins[0]["block"]]
    zf = zipfile.ZipFile(io.BytesIO(raw))
    oid = next(b for b in ET.fromstring(zf.read("Blocks/content.xml")) if b.get("Name") == ins[0]["block"]).get("OutlineID")
    return raw, M, ins, blk, next(s for s in blk["shapes"] if s["handle"] == int(oid))


def golden():
    if not os.path.exists(os.path.join(RESEARCH, "m14_most_cypcut.lxds")):
        print("— эталон CypCut: нет %s, пропуск" % RESEARCH)
        return
    raw, M, ins, blk, cyp = cypcut_contour()
    V_ = cyp["verts"]
    check("CypCut: одна вставка моста, блок — число, контур flag 5, sp 0, outer 0, coedge 0, без LeadParam",
          len(ins) == 1 and ins[0]["block"].isdigit() and cyp["flag"] == 5 and cyp["sp"] == 0 and cyp["outer"] == 0 and
          cyp["coedge"] == 0 and cyp["lead"] is None, "блок %s, %d вершин" % (ins[0]["block"], len(V_)))

    def on(p):
        return min(range(5), key=lambda k: abs(math.dist(p, W5[k][:2]) - 52.5))
    lines = [(V_[i][:2], V_[(i + 1) % len(V_)][:2]) for i in range(len(V_)) if V_[i][2] == 0]
    axes, widths, slants = [], [], []
    for a, b in E5:
        ls = [(p, q) if on(p) == a else (q, p) for p, q in lines if {on(p), on(q)} == {a, b}]
        dirs = [((q[0] - p[0]) / math.dist(p, q), (q[1] - p[1]) / math.dist(p, q)) for p, q in ls]
        u = ((dirs[0][0] + dirs[1][0]) / 2, (dirs[0][1] + dirs[1][1]) / 2)
        Lu = math.hypot(*u)
        u = (u[0] / Lu, u[1] / Lu)
        n = (-u[1], u[0])
        widths.append(abs((ls[0][0][0] - ls[1][0][0]) * n[0] + (ls[0][0][1] - ls[1][0][1]) * n[1]))
        cu = ((W5[b][0] - W5[a][0]) / 107, (W5[b][1] - W5[a][1]) / 107)
        slants.append(math.degrees(math.acos(max(-1.0, min(1.0, u[0] * cu[0] + u[1] * cu[1])))))
        pts = [x for l in ls for x in l]
        axes.append(((sum(x for x, y in pts) / 4, sum(y for x, y in pts) / 4), u))
    check("CypCut: перемычки 2,000 мм, оси нарисованы рукой (наклон к линии центров)", all(abs(w - 2) < 1e-5 for w in widths),
          "ширины %s; наклон %s°" % ([round(w, 6) for w in widths], [round(s, 1) for s in slants]))
    C = BR.Contour(W5, E5, 2.0, axes)
    ours = C.verts()
    dp, db = cyc_dev(ours, V_)
    check("эталон: по осям CypCut — те же вершины (± 1e-3 мм) и bulge (± 1e-4), то же направление, длина ± 0,01 мм",
          len(ours) == len(V_) and dp < 1e-3 and db < 1e-4 and (G.poly_area(ours) > 0) == (G.poly_area(V_) > 0) and
          abs(G.length(dict(kind="LwPolyline", verts=ours, flag=1)) - G.length(cyp)) < 0.01,
          "вершины %.1e мм, bulge %.1e; длина %.4f против %.4f" % (dp, db, C.length(), G.length(cyp)))
    C0 = BR.Contour(W5, E5, 2.0)
    o0 = C0.verts()
    seq = lambda VV: [(on(v[:2]), abs(v[2]) > 1e-12) for v in VV]
    s0, sc = seq(o0), seq(V_)
    same_topo = any(s0[k:] + s0[:k] == sc for k in range(len(s0)))
    dp0, _ = cyc_dev(o0, V_)
    check("по линии центров: та же топология (16 вершин, окружности по порядку), длина ± 0,01 мм, против часовой",
          len(o0) == 16 and same_topo and abs(C0.length() - G.length(cyp)) < 0.01 and G.poly_area(o0) > 0,
          "длина %.4f против %.4f; вершины отличаются до %.2f мм (наклон осей CypCut)" % (C0.length(), G.length(cyp), dp0))
    check("длина общего контура ≈ 5 окружностей (± 0,2 мм)", abs(C0.length() - 5 * 2 * math.pi * 52.5) < 0.2,
          "%.3f против %.3f" % (C0.length(), 5 * 2 * math.pi * 52.5))
    # формат CypCut — проверка моста по смыслу (verify._check_bridge) принимает контур CypCut? его оси не по линии центров —
    # граница объединения та же? нет: перемычки наклонены — проверка должна сказать, что не по линии центров
    sh = [s for s in blk["shapes"] if s is not cyp] + [cyp]
    wb = [dict(circles=W5, edges=E5, members=set(range(5)), names=["ш"] * 5, used=False,
               inner=collections.Counter(V.canon(s) for s in sh[:-1]))]
    ok, why = V._check_bridge(sh, wb, 2.0)
    check("проверка моста отличает перемычки CypCut (наклонные) от наших (по линии центров) — ✗ с причиной, не падение",
          not ok and why, why)


# ============================================================================================ 2) геометрия
def tree(rnd, kind):
    """Случайное дерево окружностей: сетка или «соты», зазор 2 мм; радиусы одинаковые или разные (по соседям)."""
    r0 = rnd.uniform(15, 60)
    n = rnd.randint(2, 8)
    if kind == "grid":
        cells = [(0, 0)]
        while len(cells) < n:
            x, y = rnd.choice(cells)
            c = rnd.choice([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
            if c not in cells:
                cells.append(c)
        pitch = 2 * r0 + 2
        circ = [(100 + x * pitch, 100 + y * pitch, r0) for x, y in cells]
    else:
        circ = [(100.0, 100.0, r0)]
        while len(circ) < n:
            b = rnd.choice(circ)
            r = rnd.uniform(15, 60) if kind == "mixed" else r0
            a = rnd.uniform(0, 2 * math.pi)
            c = (b[0] + (b[2] + r + 2) * math.cos(a), b[1] + (b[2] + r + 2) * math.sin(a), r)
            if all(math.dist(c[:2], q[:2]) >= c[2] + q[2] + 2 - 1e-9 for q in circ):
                circ.append(c)
    edges, seen = [], {0}
    while len(seen) < len(circ):                        # дерево по соседям через зазор
        cand = [(a, b) for a in seen for b in range(len(circ)) if b not in seen and
                abs(math.dist(circ[a][:2], circ[b][:2]) - circ[a][2] - circ[b][2] - 2) < 1e-6]
        if not cand:
            return None
        a, b = rnd.choice(cand)
        edges.append((a, b)); seen.add(b)
    return circ, edges


def geometry():
    rnd = random.Random(14)
    n_ok = n_tot = n_st = 0
    bad = []
    for case in range(60 if QUICK else 200):
        t = tree(rnd, ("grid", "hex", "mixed")[case % 3])
        if t is None:
            continue
        circ, edges = t
        w = rnd.uniform(0.5, min(5.0, min(c[2] for c in circ) * 0.9))
        try:
            C = BR.Contour(circ, edges, w)
        except BR.BridgeError as e:                     # перемычки на детали перекрылись (мало места) — честный отказ
            continue
        n_tot += 1
        V_ = C.verts()
        s = dict(C.shape(), outer=0, flag=5)
        s = {k: v for k, v in s.items() if not k.startswith("_")}
        holes = [dict(kind="Circle", c=c[:2], r=c[2] / 3, a0=0.0, layer=1, layer_name="0", coedge=0, flag64=0, outer=0, lead=None)
                 for c in circ]
        wb = [dict(circles=circ, edges=edges, members=set(), names=["д"] * len(circ), used=False,
                   inner=collections.Counter(V.canon(h) for h in holes))]
        s0 = dict(s, verts=C.started(0)["verts"]) if C.cands else None
        ok, why = V._check_bridge(holes + [s0], wb, w) if s0 else (False, "нет кандидатов врезки")
        an = sum(2 * math.pi * c[2] for c in circ) - sum(2 * circ[a][2] * math.asin(w / 2 / circ[a][2]) + 2 * circ[b][2] *
                                                          math.asin(w / 2 / circ[b][2]) - 2 * (math.dist(circ[a][:2], circ[b][:2]) -
                                                          math.sqrt(circ[a][2] ** 2 - w * w / 4) - math.sqrt(circ[b][2] ** 2 - w * w / 4))
                                                          for a, b in edges)
        if ok and G.poly_area(V_) > 0 and abs(C.length() - an) < 1e-6 and abs(G.length(s) - an) < 1e-6:
            n_ok += 1
        else:
            bad.append((case, why or "длина/направление"))
        A0, L0 = G.poly_area(V_), G.length(s)
        for j, (i, th) in enumerate(C.cands):
            st = C.started(j)
            Vs = st["verts"]
            c = circ[C.pieces[i][1]]
            gap_ok = all(min((th - C.att[(C.pieces[i][1], k)][x]) % (2 * math.pi), (C.att[(C.pieces[i][1], k)][x] - th) % (2 * math.pi))
                         * c[2] >= BR.PIERCE_CLEAR - 1e-9 for k in C.inc[C.pieces[i][1]] for x in (0, 2))
            if not (abs(G.poly_area(Vs) - A0) < 1e-6 and abs(G.length(dict(st, flag=1)) - L0) < 1e-6 and abs(Vs[0][2]) > 1e-12 and
                    abs(Vs[-1][2]) > 1e-12 and abs(math.dist(Vs[0][:2], c[:2]) - c[2]) < 1e-9 and gap_ok and len(Vs) == len(V_) + 1):
                n_st += 1
    check("случайные деревья (%d): контур против часовой, длина = аналитической, граница объединения (независимо)" % n_tot,
          n_tot >= 40 and n_ok == n_tot, "%d из %d %s" % (n_ok, n_tot, bad[:3]))
    check("врезка в каждом кандидате: та же площадь и длина, вершина 0 на дуге, ≥ 2 мм по дуге от перемычки", n_st == 0,
          "нарушений %d" % n_st)
    two = dict(kind="LwPolyline", verts=[(10.0, 0.0, 1.0), (-10.0, 0.0, 1.0)], flag=1, sp=0.0)
    four = dict(kind="LwPolyline", verts=[(10.0, 0.0, math.tan(math.pi / 8)), (0.0, 10.0, math.tan(math.pi / 8)),
                                          (-10.0, 0.0, math.tan(math.pi / 8)), (0.0, -10.0, math.tan(math.pi / 8))], flag=1, sp=0.0)
    sq = dict(kind="LwPolyline", verts=[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], flag=1, sp=0.0)
    half = dict(kind="LwPolyline", verts=[(10.0, 0.0, 1.0), (-10.0, 0.0, 0.0)], flag=1, sp=0.0)
    check("окружность полилинией из 2 и 4 дуг — окружность; квадрат и полукруг — нет",
          BR.circle_of(two) is not None and BR.circle_of(four) is not None and abs(BR.circle_of(four)[2] - 10) < 1e-9
          and BR.circle_of(sq) is None and BR.circle_of(half) is None)


# ============================================================================================ 3) группы на m14
def grouping():
    path = os.path.join(SAMPLES, "m14.lxds")
    if not os.path.exists(path):
        print("— группы m14: нет образца, пропуск")
        return
    from sheet_nest.cli import load_parts
    from sheet_nest.pack import plan
    parts, _, _ = load_parts([path])
    lay = plan(parts, 1500, 6000, 2, 2)["layouts"][0]
    P = lay["placed"]
    circ = [BR.circle_of(G.transform(parts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"]))) for q in P]
    for N in (2, 3, 5, 8):
        t0 = time.time()
        b = BR.plan(parts, P, 2.0, 2.0, N)
        bad, sizes = [], collections.Counter()
        seen = set()
        for g in b["groups"]:
            m = g["members"]
            sizes[len(m)] += 1
            if not (2 <= len(m) <= N and len(g["edges"]) == len(m) - 1 and not (set(m) & seen)):
                bad.append(("размер/дерево", m))
            seen.update(m)
            for a, c in g["edges"]:
                d = math.dist(circ[a][:2], circ[c][:2]) - circ[a][2] - circ[c][2]
                if abs(d - 2.0) > BR.GAP_TOL or a not in m or c not in m:
                    bad.append(("не соседи", a, c, d))
            BR.contour_of(parts, P, g, 2.0)             # строится
        single = len(P) - len(seen)
        units = len(b["groups"]) + single
        ideal = math.ceil(len(P) / N)
        check("m14, группы до %d: деревья, перемычки только между соседями через зазор 2 мм; единиц резки ≤ 1,03 × ⌈704/%d⌉"
              % (N, N), not bad and units <= 1.03 * ideal + 1,
              "групп %d %s, одиночек %d, единиц %d (≥ %d), %.2f с %s" % (len(b["groups"]), dict(sizes), single, units, ideal,
                                                                       time.time() - t0, bad[:2]))


# ============================================================================================ 4–5) формат, порча
def washer_dxf(td, n=12, name="шайба"):
    import dxf_writer as DW
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.circle((52.5, 52.5), 52.5)
    d.entities.circle((52.5, 52.5), 25)
    p = os.path.join(td, "%s_%dшт.dxf" % (name, n))
    open(p, "wb").write(d.dxf_bytes())
    return p


def plate_dxf(td, n=3):
    import dxf_writer as DW
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.lwpolyline([(0, 0), (300, 0), (300, 200), (0, 200)], closed=True)
    d.entities.circle((150, 100), 20)
    p = os.path.join(td, "плита_%dшт.dxf" % n)
    open(p, "wb").write(d.dxf_bytes())
    return p


def fmt():
    import xml.etree.ElementTree as ET
    with tempfile.TemporaryDirectory() as td:
        paths = [washer_dxf(td, 23), plate_dxf(td, 3)]
        # прямоугольный раскрой: шайбы сеткой через зазор 2 мм (растровый v1 ставит их не ровно через зазор — моста нет)
        base, raw0, pl0, parts0 = run(paths, 600, 900, 2, 2, 3.0, None, "ф", None, ("rect",), log=lambda *a: None, strategy="safe")
        for st in R.STRATEGIES:
            res, raw, pl, parts = run(paths, 600, 900, 2, 2, 3.0, None, "ф", None, ("rect",), log=lambda *a: None, strategy=st,
                                      bridge=dict(width=2, group=5))
            b = res["bridge"]
            check("синтетика (23 шайбы + 3 плиты), %s, мост: все проверки программы, те же листы" % st,
                  base["ok"] and res["ok"] and res["sheets"] == base["sheets"] and b["groups"] > 0,
                  "групп %d, перемычек %d, деталей в мостах %d; %s" % (b["groups"], b["bridges"], b["parts"],
                                                                      "; ".join(c[0] + ": " + c[2] for c in res["checks"] if c[1] is False)[:200]))
            check("  %s: врезок меньше на (деталей в мостах − групп)" % st,
                  res["risk"]["pierces"] == base["risk"]["pierces"] - (b["parts"] - b["groups"]) and b["pierces_saved"] == b["parts"] - b["groups"],
                  "%d → %d" % (base["risk"]["pierces"], res["risk"]["pierces"]))
        zf = zipfile.ZipFile(io.BytesIO(raw))
        X = lambda n: ET.fromstring(zf.read(n))
        nres = len(X("Nest2D/Results/content.xml"))
        ins = [s for k in range(1, nres + 1) for s in X("Nest2D/Results/%d/content.xml" % k).iter("Shape") if s.get("Class") == "Insert"]
        free = [s for s in ins if s.get("NestPart") is None]
        blocks = {b_.get("Name"): b_ for b_ in X("Blocks/content.xml")}
        fb = [blocks[s.findtext("BlockName")] for s in free]
        check("вставка моста: без NestPart и NestGroup, ChannelPort=1, XScale=YScale=1",
              free and all(s.get("NestGroup") is None and s.get("ChannelPort") == "1" and s.findtext("XScale") == "1" for s in free),
              "вставок моста %d из %d" % (len(free), len(ins)))
        M = decompile_free(raw)
        bn = {b_["name"]: b_ for b_ in M["blocks"]}
        ok_b = True
        for b_ in fb:
            sh = bn[b_.get("Name")]["shapes"]
            c = sh[-1]
            ok_b &= (b_.get("Name").isdigit() and b_.get("Flags") is None and b_.get("OutlineID") == str(c["handle"]) and
                     c["kind"] == "LwPolyline" and c["flag"] == 5 and c["sp"] == 0 and c["outer"] == 0 and c["coedge"] == 0 and
                     c["flag64"] == 0 and c["lead"] is None and all(s["kind"] == "Circle" and s["outer"] == 0 for s in sh[:-1]))
        check("блок моста: имя — число, OutlineID — общий контур, без Flags; контур flag 5, sp 0, outer 0, coedge 0, flag64 0, "
              "без LeadParam; отверстия раньше контура (порядок резки)", ok_b, ", ".join(b_.get("Name") for b_ in fb[:3]))
        parts_x = {p.get("Name"): p for p in X("Nest2D/Parts/content.xml")}
        w = next(v for k, v in parts_x.items() if k.startswith("шайба"))
        sm = list(X("Nest2D/Results/content.xml"))
        sm0 = list(ET.fromstring(zipfile.ZipFile(io.BytesIO(raw0)).read("Nest2D/Results/content.xml")))
        nb = res["bridge"]["parts"]
        pc = sum(int(x.get("PartCount")) * int(x.get("PlanCount")) for x in sm)
        check("Amount — заказ (23), AmountUsed — без деталей мостов; PartCount — без них; загрузка — как без моста",
              w.get("Amount") == "23" and w.get("AmountUsed") == str(23 - nb) and pc == 26 - nb and
              [x.get("Utilization") for x in sm] == [x.get("Utilization") for x in sm0],
              "Amount %s, AmountUsed %s, PartCount %s, загрузка %s (без моста %s)" % (
                  w.get("Amount"), w.get("AmountUsed"), [x.get("PartCount") for x in sm], [x.get("Utilization") for x in sm],
                  [x.get("Utilization") for x in sm0]))
        check("висячих блоков нет (блоки = детали + вставки)", len(blocks) == len(parts_x) + len(ins), "%d блоков" % len(blocks))
        from sheet_nest.read_lxds import parts_from_lxds
        ps, _ = parts_from_lxds(raw, "наша.lxds")
        check("наша программа с мостами читается: детали и количества = заказ", sorted((p["name"], p["qty"]) for p in ps) ==
              sorted((p["name"], p["qty"]) for p in parts), str([(p["name"], p["qty"]) for p in ps]))
        # порча: проверка программы — ✗, а не падение
        lay = pl["layouts"]

        def corrupt(f):
            L2 = copy.deepcopy([{k: v for k, v in l.items() if k != "_bridged"} for l in lay])
            f(L2)
            raw2, _ = build(parts, L2, "порча")
            rep, _, _ = V.check_safe(raw2, parts, L2, 2.0, 2.0, 3.0)
            return [r_ for r_ in rep if r_[1] is False]

        def flag1(L2):
            e = next(e for e in L2[0]["seq"] if e[0] == "bridge")
            e[2][-1]["flag"] = 1

        def shift(L2):
            e = next(e for e in L2[0]["seq"] if e[0] == "bridge")
            V_ = e[2][-1]["verts"]
            k = next(k for k in range(len(V_)) if abs(V_[k][2]) < 1e-12)
            V_[k] = (V_[k][0] + 0.05, V_[k][1] + 0.05, 0.0)

        def extra(L2):
            L2[0]["bridges"]["groups"] = L2[0]["bridges"]["groups"][1:]
        for nm, f in (("контур flag 1 вместо 5", flag1), ("прямая перемычки сдвинута на 0,05 мм", shift),
                      ("мост, которого нет в раскрое", extra)):
            try:
                bad = corrupt(f)
                check("порча — %s: проверка программы ✗" % nm, bool(bad), "; ".join(b_[0] for b_ in bad)[:150])
            except Exception as e:
                check("порча — %s: проверка программы ✗, а не падение" % nm, False, "%s: %s" % (type(e).__name__, e))


# ============================================================================================ 6) чтение CypCut
def reading():
    path = os.path.join(RESEARCH, "m14_most_cypcut.lxds")
    if not os.path.exists(path):
        print("— чтение CypCut: нет образца, пропуск")
        return
    from sheet_nest.read_lxds import parts_from_lxds
    from sheet_nest import render
    raw = open(path, "rb").read()
    ps, info = parts_from_lxds(raw, "m14_most_cypcut.lxds")
    check("программа CypCut с мостом: детали — шайбы, 704 шт (Amount; 5 в мосту + 699)", len(ps) == 1 and ps[0]["qty"] == 704 and
          ps[0]["shapes"][-1]["kind"] == "Circle", "%s × %d" % (ps[0]["name"], ps[0]["qty"]))
    try:
        M = decompile_free(raw)
        nfree = sum(1 for r in M["results"] for i in r["inserts"] if i["ref"] == FREE)
        with tempfile.TemporaryDirectory() as td:
            render.png_model(raw, os.path.join(td, "x.png"))
            render.png_order(raw, os.path.join(td, "y.png"))
        check("программа CypCut с мостом: разбор и картинки не падают, вставка моста одна", nfree == 1, "вставок моста %d" % nfree)
    except Exception as e:
        check("программа CypCut с мостом: разбор и картинки не падают", False, "%s: %s" % (type(e).__name__, e))


# ============================================================================================ 7) кнопки
def buttons():
    with tempfile.TemporaryDirectory() as td:
        p = [washer_dxf(td, 6)]
        msgs = []
        for kw in (dict(coedge=True, bridge=dict(width=2, group=5)), dict(bridge=dict(width=0, group=5)),
                   dict(bridge=dict(width=2, group=1)), dict(bridge=dict(width=-1, group=5))):
            try:
                run(p, 600, 900, 2, 2, 3.0, None, "к", None, log=lambda *a: None, **kw)
                msgs.append("принято: %s" % kw)
            except ValueError as e:
                if not str(e).startswith("мост"):
                    msgs.append("текст: %s" % e)
            except Exception as e:
                msgs.append("%s: %s" % (type(e).__name__, e))
        check("мост + общий рез, ширина 0 и < 0, группа 1 — понятная ошибка «мост…»", not msgs, "; ".join(msgs))
        res, *_ = run(p, 600, 900, 2, 2, 3.0, None, "к", None, log=lambda *a: None, bridge=dict(width=60, group=5))
        check("ширина ≥ радиуса — без моста, причина в предупреждениях, программа ✓",
              res["ok"] and res["bridge"]["groups"] == 0 and any("половины диаметра" in w for w in res["warnings"]),
              "; ".join(w for w in res["warnings"] if "мост" in w or "диаметр" in w)[:160])
        from sheet_nest.cli import main
        import contextlib
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                main(p + ["--sheet", "600x900", "--thickness", "3", "--bridge", "--bridge-width", "1.5", "--bridge-group", "3",
                          "--strategy", "hill", "--out", td, "--name", "кс"])
        except SystemExit as e:
            code = e.code
        fs = os.listdir(td)
        check("командная строка --bridge --bridge-width --bridge-group: программа «…_мост», картинки (и порядок резки)",
              code == 0 and any(f.endswith(".lxds") and "_мост" in f for f in fs) and any(f.endswith("_порядок.png") for f in fs),
              ", ".join(sorted(f for f in fs if f.startswith("кс")))[:160])


# ============================================================================================ 8) m14 целиком
def m14():
    path = os.path.join(SAMPLES, "m14.lxds")
    if QUICK or not os.path.exists(path):
        print("— m14 целиком: пропуск")
        return
    t0 = time.time()
    base, *_ = run([path], 1500, 6000, 2, 2, 14, None, "m14", None, log=lambda *a: None, strategy="safe")
    t_safe = time.time() - t0
    t0 = time.time()
    res, raw, pl, parts = run([path], 1500, 6000, 2, 2, 14, None, "m14", None, log=lambda *a: None, strategy="hill",
                              bridge=dict(width=2, group=5))
    t_b = time.time() - t0
    b = res["bridge"]
    check("m14, мост + «Горкой»: все проверки программы, 1 лист", res["ok"] and res["sheets"] == 1,
          "; ".join(c[0] for c in res["checks"] if c[1] is False))
    check("m14: врезок 1408 → 1408 − (деталей в мостах − групп)", base["risk"]["pierces"] == 1408 and
          res["risk"]["pierces"] == 1408 - b["pierces_saved"],
          "групп %d, перемычек %d, деталей в мостах %d, врезок %d" % (b["groups"], b["bridges"], b["parts"], res["risk"]["pierces"]))
    check("m14: время мост + «Горкой» ≤ 2 × «Безопасный» без моста", t_b <= 2 * t_safe, "%.1f с против %.1f с" % (t_b, t_safe))


# ============================================================================================ 9) диски, мелкие окружности
def disc_dxf(td, n, d, name="диск"):
    import dxf_writer as DW
    doc = DW.DxfDoc(version="AC1015", insunits=4)
    doc.entities.circle((d / 2, d / 2), d / 2)
    p = os.path.join(td, "%s%g_%dшт.dxf" % (name, d, n))
    open(p, "wb").write(doc.dxf_bytes())
    return p


def solid():
    with tempfile.TemporaryDirectory() as td:
        for paths, W, L, meth, tag in (([disc_dxf(td, 60, 80)], 600, 900, ("rect",), "60 дисков Ø80, лист 600×900"),
                                       ([disc_dxf(td, 18, 161.2)], 1500, 3000, ("rect", "raster"), "18 дисков Ø161,2, лист 1500×3000"),
                                       ([disc_dxf(td, 30, 80), washer_dxf(td, 30)], 900, 1200, ("rect",), "30 дисков + 30 шайб")):
            bad = []
            for st in R.STRATEGIES:
                res, raw, pl, parts = run(paths, W, L, 2, 2, 3.0, None, "д", None, meth, log=lambda *a: None, strategy=st,
                                          bridge=dict(width=2, group=5))
                if not (res["ok"] and res["bridge"]["groups"] > 0) or any("подвод" in c[0] and c[1] is None for c in res["checks"]):
                    bad.append("%s: групп %d; %s" % (st, res["bridge"]["groups"], "; ".join(
                        c[0][:40] + " " + c[2][:60] for c in res["checks"] if c[1] is not True)[:200]))
            check("%s, мост, все стратегии: все проверки ✓ (вставка ↔ группа по окружностям контура)" % tag, not bad, " | ".join(bad))
        # порча: вставка моста — копия другой (те же окружности дважды, одна группа раскроя без вставки) — ✗, а не ✓
        res, raw, pl, parts = run([disc_dxf(td, 60, 80)], 600, 900, 2, 2, 3.0, None, "д", None, ("rect",), log=lambda *a: None,
                                  strategy="safe", bridge=dict(width=2, group=5))
        L2 = copy.deepcopy([{k: v for k, v in l.items() if k != "_bridged"} for l in pl["layouts"]])
        seq = L2[0]["seq"]
        ia = [k for k, e in enumerate(seq) if e[0] == "bridge" and len(e[1]) == len(seq[next(
            k_ for k_, e_ in enumerate(seq) if e_[0] == "bridge")][1])]
        seq[ia[1]] = (seq[ia[1]][0], seq[ia[1]][1], copy.deepcopy(seq[ia[0]][2]))
        raw2, _ = build(parts, L2, "порча")
        rep, _, _ = V.check_safe(raw2, parts, L2, 2.0, 2.0, 3.0)
        bad = [x[0] for x in rep if x[1] is False]
        check("порча — диски: вставка моста — копия другой: проверка ✗ (мосты), а не ✓", any(b_.startswith("мосты") for b_ in bad),
              "; ".join(b_[:40] for b_ in bad)[:200])
        # мелкие окружности: на дуге нет места под врезку — без моста, причина, маршрут не падает
        out = dict(handle=None, kind="Circle", c=(0.7, 0.7), r=0.7, a0=0.0, layer=1, layer_name="0", coedge=0, flag64=0, outer=1, lead=None)
        parts_t = [dict(name="d", qty=4, shapes=[out], src="t", warnings=[], microjoints=False)]
        placed = [dict(part=0, rot=0, dx=50 + i * 3.4, dy=50.0) for i in range(4)]
        b = BR.plan(parts_t, placed, 2.0, 0.5, 5)
        try:
            R.route_sheet(placed, parts_t, 300.0, 300.0, strategy="safe")
            crash = ""
        except Exception as e:
            crash = "%s: %s" % (type(e).__name__, e)
        check("окружности Ø1,4 мм, перемычка 0,5: без моста (на дуге нет места под врезку), причина, маршрут не падает",
              not b["groups"] and any("нет места под врезку" in w for w in b["skipped"]) and not crash,
              "; ".join(sorted(set(b["skipped"])))[:160] + crash)
        ok_r = True
        for r_ in (0.8, 3.0):
            o2 = dict(out, c=(r_, r_), r=r_)
            pt = [dict(parts_t[0], shapes=[o2])]
            pl_ = [dict(part=0, rot=0, dx=50 + i * (2 * r_ + 2), dy=50.0) for i in range(4)]
            l_ = dict(W=300.0, L=300.0, amount=1, placed=pl_, bridges=BR.plan(pt, pl_, 2.0, 0.5, 5))
            if not l_["bridges"]["groups"]:
                ok_r = False
                continue
            p2, parts2, back = BR.bridged(pt, l_)
            try:
                R.route_sheet(p2, parts2, 300.0, 300.0, strategy="safe")
            except Exception:
                ok_r = False
        check("окружности Ø1,6 и Ø6 мм — мост есть, маршрут строится", ok_r)


golden()
geometry()
grouping()
fmt()
reading()
buttons()
solid()
m14()
print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
sys.exit(1 if fails else 0)
