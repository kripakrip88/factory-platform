# -*- coding: utf-8 -*-
"""Порядок резки листа: стратегии (раскрой один и тот же, меняется только маршрут).

Внутри детали — отверстия, открытые резы (прорези), гравировка — путём к точке врезки внешнего контура;
внешний контур режется последним (иначе деталь выпадет раньше). Открытый контур можно развернуть (врезка на
другом конце). Два способа обхода, берётся лучший:
  • «змейка по рядам» — если в детали ряды параллельных открытых резов (жалюзи): ряд = риска → прорезь → риска,
    следующий ряд — обратно; переходы по кромке, над вырезанными язычками головка не ходит (решётки 12.10);
  • оптимизатор — ближайший сосед + 2-opt с разворотом участков + перенос участков (1–3 элемента).
Точка врезки внешнего контура — выпуклая вершина между прямыми участками (у окружности — 8 углов), под подвод
свободно ≥ LEAD_FREE по наружной нормали к первому участку (край листа, соседние детали). Детали листа —
ближайший сосед + 2-opt по центрам, затем динамика по точкам врезки.

Стратегии (решение Антона 13.10.2026: инженер выбирает по опыту, программа показывает сводку по каждой) — STRATEGIES:
  • short «Минимум холостого» — как было (штрафы: язычок CROSS_PENALTY, заход над вырезанной деталью
    PART_CROSS_PENALTY) + то, что холостой только сокращает: начало отверстий по ходу пути (вход + выход короче),
    у детали без места под подвод — любой из одинаково свободных углов, порядок деталей — ещё и змейкой по рядам и
    замкнутым обходом (берётся, только если дешевле по той же цене), в группах общего реза — «взгляд вперёд»
    (строятся оба варианта, берётся лучший по тому же ключу);
  • safe «Безопасный» — ключ листа по порядку (risk.safe_key): переходы над язычками, над освобождёнными мелкими
    деталями, над прочими освобождёнными, над отверстиями ≥ 10 мм, затем холостой + NEAR_COST за впритирку;
  • safe0 «Безопасный, конец у нуля» — тот же ключ, но с возвратом головки в (0,0) после листа (настройка станка, в
    программе его нет): он входит и в холостой, и в ступени опасных (risk key0).
safe и safe0 выбирают из ОДНИХ кандидатов (_safe_pool; общий рез — _coedge_pool), каждая — лучший по своему ключу:
safe поэтому не хуже safe0 по ключу без возврата, safe0 не хуже safe по ключу с возвратом, обе — не хуже «short»
(его маршрут тоже кандидат). Кандидаты: динамика по порядкам деталей (ближайший сосед, замкнутый обход от нуля в обе
стороны), в каждой — лучший конец без возврата и с возвратом; маршрут «short»; остались опасные переходы — порядки
«ближайший без опасных», «мелкие последними», змейкой по колонкам и по рядам, правка порядка деталей около опасных
переходов (_repair), на листе до EXACT_ORDERS деталей — все порядки. Начало отверстия — язычки строго выше отверстий
≥ 10 мм (как в ключе), выход не над самим отверстием; заход в деталь над освобождённой — другой первый элемент
(разворот начала пути).
Общий рез (кнопка) — отдельный переключатель, сочетается с любой стратегией. Выбор между кандидатами — всегда по
счёту risk.measure готового маршрута, тем же, что в отчёте.
"""
import math, itertools, collections
from . import geom as G
from . import risk as RK

D = math.dist
LEAD_FREE = 10.0            # мм свободно под подвод внешнего контура
MAX_CAND = 16               # точек врезки внешнего контура на деталь (больше — по секторам вокруг центра)
EXACT_N = 14                # до стольких внутренних элементов — точный путь от головки для каждой пары (голова, врезка)
CROSS_PENALTY = 2000.0      # мм штрафа за переход над вырезанным (язычок прорези) — чтобы такой путь выбирался последним
PART_CROSS_PENALTY = 500.0  # мм штрафа за переход к следующей детали над уже вырезанной деталью
GROUP_PERM_MAX = 6          # группу общего реза до стольких деталей перебирать всеми порядками (6! = 720)
HOLE_STARTS = 16            # углов начала у отверстия-окружности (и исходное)
ALT_STATES = 3              # безопасные: другой первый элемент детали — от стольких лучших состояний динамики
LOOK_POOL = 3               # «взгляд вперёд» в группе: путей по детали к каждой точке начала её контура (лучших)
SAFE_POOL = 60              # безопасные, деталь группы: самых коротких путей по ней — с полным счётом опасных
EXACT_ORDERS = 6            # безопасные, лист из стольких деталей с оставшимися опасными — все порядки деталей
SAFE_NN = 12                # безопасные, порядок «ближайший сосед без опасных»: из стольких ближайших деталей
REPAIR_WINDOW = 3           # безопасные, правка порядка около опасного перехода: мест в обе стороны
REPAIR_WORK = 4             # … и не больше стольких проходов динамики по листу (в шагах-деталях: вариант с изменением
REPAIR_MIN = 80             # с места a стоит n − a шагов — динамика продолжается от состояний до a), у опасных в
                            # программе — не меньше REPAIR_MIN шагов (малый лист: шаг дешёвый, а вариантов — много)
START_CELL = 50.0           # мм: ячейка сетки вырезанного своей детали при выборе начала отверстий

# Стратегии: имя → переключатели (новая стратегия — новая строка):
#   key — ключ сравнения: "short" — штрафы как было, "safe" — risk.safe_key;
#   hole_starts — начало отверстий по ходу пути; lead_ties — у детали без места под подвод все одинаково свободные
#   углы (свобода та же, что у угла «как было»), а не первый из них; look — «взгляд вперёд» в группах общего реза;
#   orders — маршрут «short» ещё и по другим порядкам деталей (змейкой по рядам, замкнутый обход), лучший
#   по цене «как было» (_short_route); ret — возврат в (0,0) в ключе (risk key0); pool — кандидаты безопасных
#   (_safe_pool / _coedge_pool, общие для всех стратегий с этим переключателем: маршрут «short», замкнутый обход, другие
#   порядки, правка порядка).
STRATEGIES = {
    "short": dict(title="Минимум холостого", key="short", hole_starts=True, lead_ties=True, look=True, orders=True, ret=False,
                  pool=False),
    "safe": dict(title="Безопасный", key="safe", hole_starts=True, lead_ties=True, look=True, orders=True, ret=False, pool=True),
    "safe0": dict(title="Безопасный, конец у нуля", key="safe", hole_starts=True, lead_ties=True, look=True, orders=True, ret=True,
                  pool=True),
}
DEFAULT = "short"
ZERO4 = (0, 0, 0, 0)
_TIERS = (RK.TONGUE, RK.SMALLP, RK.PART, RK.HOLE)   # ступени опасных в ключе безопасных (risk.safe_key), по порядку


def options(strategy=None):
    """Имя стратегии или словарь переключателей → полный словарь переключателей (name, title, key, …)."""
    if isinstance(strategy, dict):
        o = dict(name="custom", title="своя", key="short", hole_starts=False, look=False, ret=False, pool=False, lead_ties=False,
                 orders=False)
        o.update(strategy)
        return o
    name = strategy or DEFAULT
    if name not in STRATEGIES:
        raise ValueError("стратегия «%s»: есть %s" % (name, ", ".join(STRATEGIES)))
    return dict(STRATEGIES[name], name=name)


# =========================================================================== оптимизатор
def order(shapes, head, tail):
    """Внутренние элементы: (фигуры в порядке и направлении резки, холостой ход head → … → tail).
    head=None — начало пути свободно (стоимость считается от первого элемента)."""
    n = len(shapes)
    if n == 0:
        return [], (D(head, tail) if head is not None and tail is not None else 0.0)
    E = [G.ends(s) for s in shapes]
    op = [G.is_open(s) for s in shapes]

    def pin(x):
        return E[x[0]][1] if x[1] else E[x[0]][0]

    def pout(x):
        return E[x[0]][0] if x[1] else E[x[0]][1]

    def dist(a, b):
        return 0.0 if a is None or b is None else D(a, b)

    def total(seq):
        pos, t = head, 0.0
        for x in seq:
            t += dist(pos, pin(x)); pos = pout(x)
        return t + dist(pos, tail)

    def flip(x):
        return (x[0], 1 - x[1]) if op[x[0]] else x

    # жадно: от головки (или от ближайшего к врезке, если головка свободна — строим с конца)
    rest, seq = set(range(n)), []
    pos = head if head is not None else tail
    while rest:
        best = None
        for i in sorted(rest):
            for r in ((0, 1) if op[i] else (0,)):
                a = (E[i][1] if r else E[i][0]) if head is not None else (E[i][0] if r else E[i][1])
                d = D(pos, a) if pos is not None else 0.0
                if best is None or d < best[0] - 1e-9:
                    best = (d, i, r)
        _, i, r = best
        rest.remove(i); seq.append((i, r))
        pos = pout((i, r)) if head is not None else pin((i, r))
    if head is None:
        seq = seq[::-1]
    # улучшения; pin/pout/flip подставлены в циклы (то же самое: у замкнутого контура начало = конец, поэтому
    # pin(flip(b)) = pout(b), pout(flip(a)) = pin(a) — те же точки, те же расстояния). FI/FO — pin/pout по местам seq,
    # ADJ[t] — переход к t-му месту (от головки или от предыдущего); пересчёт — только после изменения seq. Те же числа
    # в том же порядке, что и в прямом счёте: результат тот же (проверено на случайных и деталях образцов).
    FI = [E[x[0]][x[1]] for x in seq]
    FO = [E[x[0]][1 - x[1]] for x in seq]
    improved = True
    while improved:
        improved = False
        for i in range(n):                                   # 2-opt: развернуть seq[i..j]
            prev = FO[i - 1] if i else head
            j0 = i
            while j0 < n:                                     # первое j ≥ j0, где разворот выгоден; после разворота —
                pa = FI[i]                                    # дальше с j + 1 (как в прямом цикле по j)
                o1 = 0.0 if prev is None else D(prev, pa)
                j = next((j for j, qb, nxt in zip(range(j0, n), FO[j0:], FI[j0 + 1:] + [tail])
                          if (0.0 if prev is None else D(prev, qb)) + (0.0 if nxt is None else D(pa, nxt)) <
                          o1 + (0.0 if nxt is None else D(qb, nxt)) - 1e-9), None)
                if j is None:
                    break
                seq[i:j + 1] = [flip(x) for x in reversed(seq[i:j + 1])]
                FI[i:j + 1], FO[i:j + 1] = FO[i:j + 1][::-1], FI[i:j + 1][::-1]
                improved = True
                j0 = j + 1
        def stubs():
            """Стыки по местам seq: t-й — (откуда, куда, длина) перед t-м элементом; n-й — уход к врезке."""
            P_ = [head] + FO
            Q_ = FI + [tail]
            return [(p, q, 0.0 if p is None or q is None else D(p, q)) for p, q in zip(P_, Q_)]
        for L in (1, 2, 3):                                  # перенос участка
            TR = stubs()
            i = 0
            while i + L <= n:
                prev = FO[i - 1] if i else head
                nxt = FI[i + L] if i + L < n else tail
                gain = dist(prev, FI[i]) + dist(FO[i + L - 1], nxt) - dist(prev, nxt)
                a0, z0 = FI[i], FO[i + L - 1]                 # вход/выход участка как есть; развёрнутого — наоборот
                # места вставки j = 0…n−L в seq без участка: до i — прежние стыки, i — новый стык на месте участка,
                # после — прежние стыки за участком
                trip = TR[:i] + [(prev, nxt, 0.0 if prev is None or nxt is None else D(prev, nxt))] + TR[i + L + 1:]
                vals0 = [gain - ((0.0 if p is None else D(p, a0)) + (0.0 if q is None else D(z0, q)) - pq) for p, q, pq in trip]
                vals1 = [gain - ((0.0 if p is None else D(p, z0)) + (0.0 if q is None else D(a0, q)) - pq) for p, q, pq in trip] \
                    if a0 != z0 else ()
                best = None
                for rv, vals in ((0, vals0), (1, vals1)):     # как в прямом счёте: сперва без разворота, по местам
                    for j, g in enumerate(vals):
                        if g > 1e-9 and (best is None or g > best[0]):
                            best = (g, j, rv)
                if best:
                    _, j, rv = best
                    seg = seq[i:i + L]
                    rest_ = seq[:i] + seq[i + L:]
                    s2 = [flip(x) for x in reversed(seg)] if rv else seg
                    seq = rest_[:j] + s2 + rest_[j:]
                    FO = [E[x[0]][1 - x[1]] for x in seq]
                    FI = [E[x[0]][x[1]] for x in seq]
                    TR = stubs()
                    improved = True
                i += 1
    out = [G.reverse(shapes[i]) if r else shapes[i] for i, r in seq]
    return out, total(seq)


def path_eval(sh, head, tail):
    """Холостой ход head → фигуры sh → tail (head None — от начала первой; tail None — до конца последней)."""
    t, pos = 0.0, head
    for s in sh:
        a, b = G.ends(s)
        if pos is not None:
            t += D(pos, a)
        pos = b
    return t + (D(pos, tail) if pos is not None and tail is not None else 0.0)


# =========================================================================== змейка по рядам
def _proj(p, u):
    return p[0] * u[0] + p[1] * u[1]


def analyze_rows(inner):
    """Ряды параллельных открытых резов одной длины + риски у их концов. None — не тот случай."""
    slits = [s for s in inner if s["kind"] == "LwPolyline" and s["layer"] == 1 and not s["flag"] & 1]
    if len(slits) < 2:
        return None
    a, b = G.ends(slits[0])
    Ls = D(a, b)
    if Ls < 1:
        return None
    u = ((b[0] - a[0]) / Ls, (b[1] - a[1]) / Ls)
    n = (-u[1], u[0])
    rows = []
    for s in slits:
        e1, e2 = G.ends(s)
        if abs(abs(_proj((e2[0] - e1[0], e2[1] - e1[1]), u)) - Ls) > 1.0 or abs(_proj((e2[0] - e1[0], e2[1] - e1[1]), n)) > 1.0:
            return None
        lo, hi = (e1, e2) if _proj(e1, u) < _proj(e2, u) else (e2, e1)
        rows.append(dict(slit=s, lo=lo, hi=hi, pos=_proj(lo, n), tick={}))
    other = []
    for s in inner:
        if any(s is r["slit"] for r in rows):
            continue
        if s["kind"] == "Line" and s["layer"] == 2:
            p1, p2 = G.ends(s)
            best = None
            for r in rows:
                for side in ("lo", "hi"):
                    d = min(D(p1, r[side]), D(p2, r[side]))
                    if d < 80 and (best is None or d < best[0]):
                        best = (d, r, side)
            if best and best[2] not in best[1]["tick"] and D(p1, p2) < 80:
                best[1]["tick"][best[2]] = s
                continue
        other.append(s)
    rows.sort(key=lambda r: r["pos"])
    return dict(rows=rows, other=other)


def _tick(t, near, inward):
    p1, p2 = G.ends(t)
    first_far = D(p1, near) > D(p2, near)
    return t if inward == first_far else G.reverse(t)


def _seq_idle(seq):
    t, pos = 0.0, G.ends(seq[0])[1]
    for s in seq[1:]:
        a, b = G.ends(s)
        t += D(pos, a); pos = b
    return t


def snake_options(inner):
    A = analyze_rows(inner)
    if A is None:
        return None
    cores = []
    for rows in (A["rows"], A["rows"][::-1]):
        for start in ("lo", "hi"):
            seq, side = [], start
            for r in rows:
                other = "hi" if side == "lo" else "lo"
                if side in r["tick"]:
                    seq.append(_tick(r["tick"][side], r[side], True))
                s = r["slit"]
                seq.append(s if D(G.ends(s)[0], r[side]) < 1e-6 else G.reverse(s))
                if other in r["tick"]:
                    seq.append(_tick(r["tick"][other], r[other], False))
                side = other
            cores.append(seq)
    macros = [None]
    if len(A["other"]) > 4:
        # много прочих фигур (подпись из десятков штрихов): одним куском — путь оптимизатора, в обе стороны
        sh, c = order(A["other"], None, None)
        rv = [G.reverse(s) if G.is_open(s) else s for s in reversed(sh)]
        macros = [(G.ends(sh[0])[0], G.ends(sh[-1])[1], _seq_idle(sh) if len(sh) > 1 else 0.0, sh),
                  (G.ends(rv[0])[0], G.ends(rv[-1])[1], _seq_idle(rv) if len(rv) > 1 else 0.0, rv)]
    elif A["other"]:
        macros = []
        for perm in itertools.permutations(A["other"]):
            for dirs in itertools.product(*[((0, 1) if G.is_open(s) else (0,)) for s in perm]):
                sh = [G.reverse(s) if r else s for s, r in zip(perm, dirs)]
                macros.append((G.ends(sh[0])[0], G.ends(sh[-1])[1], _seq_idle(sh) if len(sh) > 1 else 0.0, sh))
    opts = []
    for core in cores:
        cin, cout, cint = G.ends(core[0])[0], G.ends(core[-1])[1], _seq_idle(core)
        gaps = [(i, G.ends(core[i - 1])[1], G.ends(core[i])[0]) for i in range(1, len(core))]
        for m in macros:
            o = dict(core=core, macro=m, cin=cin, cout=cout, cint=cint)
            if m is not None:
                mi, mo = m[0], m[1]
                o["mid"] = min(((-D(p, q) + D(p, mi) + D(mo, q), i) for i, p, q in gaps), default=(None, None))
            opts.append(o)
    return opts


def snake_cost(o, head, tail):
    h = (lambda a: 0.0) if head is None else (lambda a: D(head, a))
    if o["macro"] is None:
        return h(o["cin"]) + o["cint"] + D(o["cout"], tail), None
    mi, mo, mint, _ = o["macro"]
    best = min((h(mi) + mint + D(mo, o["cin"]) + o["cint"] + D(o["cout"], tail), 0),
               (h(o["cin"]) + o["cint"] + D(o["cout"], mi) + mint + D(mo, tail), len(o["core"])))
    if o["mid"][1] is not None:
        best = min(best, (h(o["cin"]) + o["cint"] + o["mid"][0] + mint + D(o["cout"], tail), o["mid"][1]))
    return best


def snake_shapes(o, where):
    if o["macro"] is None:
        return list(o["core"])
    return o["core"][:where] + o["macro"][3] + o["core"][where:]


# =========================================================================== переходы над вырезанным
def tongue_polys(shapes):
    """Язычки открытых резов слоя 1 (открытый контур, замкнутый по хорде) — над ними головке не ходить."""
    out = []
    for s in shapes:
        # цепочки общего реза (coedge) — не прорези: это кромки деталей, язычков у них нет
        if s["kind"] == "LwPolyline" and s["layer"] == 1 and not s["flag"] & 1 and len(s["verts"]) >= 3 and not s.get("coedge"):
            P = G.points(s, 0.2)
            out.append((P, (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P))))
    return out


def _over_tongue(pos, a, cut):
    """1 — переход pos → a проходит над одним из язычков cut ([(точки, габарит)]) глубже 0,5 мм (точки через ~1 мм)."""
    # только те, чей габарит задевает переход (то же, что проверять все: точки перехода — в его габарите)
    lo_x, hi_x = min(pos[0], a[0]) - 1e-6, max(pos[0], a[0]) + 1e-6
    lo_y, hi_y = min(pos[1], a[1]) - 1e-6, max(pos[1], a[1]) + 1e-6
    near = [(P, bx) for P, bx in cut if not (bx[2] < lo_x or bx[0] > hi_x or bx[3] < lo_y or bx[1] > hi_y)]
    if not near:
        return 0
    L = D(pos, a)
    steps = int(L) + 1
    for k in range(1, steps):
        t = k / steps
        pt = (pos[0] + (a[0] - pos[0]) * t, pos[1] + (a[1] - pos[1]) * t)
        for P, bx in near:
            if bx[0] < pt[0] < bx[2] and bx[1] < pt[1] < bx[3] and G.inside(pt, P) \
                    and min(G.seg_point_dist(pt, P[i - 1], P[i]) for i in range(len(P))) > 0.5:
                return 1
    return 0


def crossings(seq_shapes, head, extra_polys=(), trace=None):
    """Сколько холостых переходов проходят над уже вырезанными язычками (и над extra_polys — вырезанными деталями).
    trace — dict: туда флаги переходов (flags[k] — переход к k-й фигуре), все язычки по порядку (cut) и сколько их до
    k-й фигуры (cnt) — для пересчёта пути с другими началами отверстий (crossings_like)."""
    cut, n, pos = list(extra_polys), 0, head
    flags, cnt = [], []
    for s in seq_shapes:
        a, b = G.ends(s)
        hit = _over_tongue(pos, a, cut) if pos is not None and cut and D(pos, a) > 1.0 else 0
        n += hit
        flags.append(hit); cnt.append(len(cut))
        cut += tongue_polys([s])
        pos = b
    if trace is not None:
        trace.update(flags=flags, cut=cut, cnt=cnt)
    return n


def crossings_like(sh2, sh, tr):
    """crossings(sh2, None) для пути sh2, который отличается от sh (trace tr, без головки) только замкнутыми фигурами
    (начала отверстий): язычки те же (их дают только открытые резы), флаг перехода меняется, только если поменялась
    одна из двух фигур у него — остальные берутся из tr. Иначе — полный счёт."""
    if len(sh2) != len(sh) or any(x is not y and not G.is_closed(x) for x, y in zip(sh2, sh)):
        return crossings(sh2, None)
    n, flags, cut, cnt = 0, tr["flags"], tr["cut"], tr["cnt"]
    for k in range(1, len(sh2)):
        if sh2[k - 1] is sh[k - 1] and sh2[k] is sh[k]:
            n += flags[k]
        elif cnt[k]:
            pos, a = G.ends(sh2[k - 1])[1], G.ends(sh2[k])[0]
            n += _over_tongue(pos, a, cut[:cnt[k]]) if D(pos, a) > 1.0 else 0
    return n


# =========================================================================== начало отверстий
def hole_starts(s):
    """Варианты начала замкнутого внутреннего контура; первым — как в детали. Окружность — HOLE_STARTS углов;
    полилиния — вершины, где контур не поворачивает внутрь острее прямого угла (место под подвод внутри); если их
    больше HOLE_STARTS (окружность ломаной из CAD) — HOLE_STARTS из них через равные промежутки по списку."""
    if s["kind"] == "Circle":
        return [s] + [dict(s, a0=2 * math.pi * j / HOLE_STARTS) for j in range(HOLE_STARTS)]
    V = s["verts"]
    n = len(V)
    if n < 3 or s.get("sp"):
        return [s]
    sg = 1 if G.poly_area(V) > 0 else -1

    def heading(i, at_end):
        (x1, y1, b), (x2, y2, _) = V[i], V[(i + 1) % n]
        return math.atan2(y2 - y1, x2 - x1) + (2 if at_end else -2) * math.atan(b)     # касательная: хорда ± дуга/2
    ks = []
    for k in range(1, n):
        turn = (heading(k, False) - heading(k - 1, True) + math.pi) % (2 * math.pi) - math.pi
        if sg * turn <= math.pi / 2 + 1e-6:
            ks.append(k)
    if len(ks) > HOLE_STARTS:
        ks = [ks[int(j * len(ks) / HOLE_STARTS)] for j in range(HOLE_STARTS)]
    return [s] + [G.rotate_start(s, k) for k in ks]


def _ubox(p, bx):
    """Габарит точки p и прямоугольника bx (x0, y0, x1, y1)."""
    return min(p[0], bx[0]), min(p[1], bx[1]), max(p[0], bx[2]), max(p[1], bx[3])


def _start_pick(cands, prev, nxt, f, grid, mode):
    """Номер лучшего начала отверстия из cands (prev → начало → nxt). Ступени: "short" — (переход над вырезанным
    язычком своей детали — штраф «как было», вход + выход, выход над самим отверстием); "safe" — (над язычками, над
    отверстиями ≥ HOLE_MIN своей детали — и над самим собой, вход + выход, выход над самим отверстием < HOLE_MIN):
    язычки строго выше отверстий, как в ключе безопасных. Переход засчитан, если над одной фигурой ≥ MIN_OVER мм глубже
    DEEP_CUT; препятствия — из сетки grid, только с габаритом у перехода."""
    big = mode == "safe" and f is not None and f[0] == "holes"
    hb = f[1][1] if f else G.bbox([cands[0]])
    near1 = grid.query(*_ubox(prev, hb)) if prev is not None and len(grid) else ()
    near2 = grid.query(*_ubox(nxt, hb)) if nxt is not None and len(grid) else ()

    def flags(a, b, items):
        t = h = 0
        if D(a, b) <= 1.0:
            return 0, 0
        x0, x1, y0, y1 = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
        for cls, ob in items:
            if (t if cls == "tongues" else h):
                continue
            bx = ob[1]
            if bx[2] < x0 or bx[0] > x1 or bx[3] < y0 or bx[1] > y1:
                continue
            if RK.deep_len(a, b, ob, RK.DEEP_CUT) >= RK.MIN_OVER:
                if cls == "tongues":
                    t = 1
                else:
                    h = 1
        return t, h
    rows = []
    for j, c in enumerate(cands):
        p = G.ends(c)[0]
        rows.append((round((D(prev, p) if prev is not None else 0.0) + (D(p, nxt) if nxt is not None else 0.0), 6), j, p))
    rows.sort()
    best = None
    # по возрастанию пути: ключ варианта ≥ (0, 0, путь) — лучший уже не хуже, дальше не смотреть; ступени (переходы
    # над вырезанным, выход над собой) считаются только у тех, кто ещё может быть лучше
    for dist, j, p in rows:
        if best is not None and best[:3] < (0, 0, dist):
            break
        t1, h1 = flags(prev, p, near1) if near1 else (0, 0)
        t2, h2 = flags(p, nxt, near2) if near2 else (0, 0)
        t, h = t1 + t2, (h1 + h2 if mode == "safe" else 0)
        if best is not None and (t, h, dist) > best[:3]:
            continue
        sx = 1 if f and nxt is not None and D(p, nxt) > 1.0 and RK.deep_len(p, nxt, f[1], RK.DEEP_CUT) >= RK.MIN_OVER else 0
        if big and sx and not h2:
            h += 1                                      # выход над самим отверстием ≥ HOLE_MIN — ступень отверстий
        key = (t, h, dist, sx, j)
        if best is None or key < best:
            best = key
    return best[-1]


def choose_starts(sh, head, tail, mode, feat=RK.feature, starts=hole_starts, memo=None):
    """Начала отверстий (замкнутых контуров слоя реза) пути sh (head → … → tail) по очереди (_start_pick). Исходное начало —
    среди вариантов, поэтому холостой не растёт (при тех же ступенях). memo — словарь плана детали (фигуры с номером
    _i): выбор у отверстия зависит только от него, соседних точек и того, что из ступеней вырезано до него, — ключ
    (отверстие, вход, выход, режим, номера вырезанного). Ничего не поменялось — тот же список."""
    if not any(G.is_closed(s) and s["layer"] == 1 for s in sh):
        return sh
    out, changed = list(sh), False
    own, grid = [], None                       # вырезанное своей детали до текущей фигуры (что в ступенях): (класс, препятствие)
    ids = []                                   # их номера в детали (_i) — для memo
    for n, s in enumerate(out):
        if G.is_closed(s) and s["layer"] == 1:               # отверстия; замкнутая гравировка — как в детали
            cands = starts(s)
            if len(cands) > 1:
                prev = G.ends(out[n - 1])[1] if n else head
                nxt = G.ends(out[n + 1])[0] if n + 1 < len(out) else tail
                mk = (s.get("_i"), prev, nxt, mode, frozenset(ids)) if memo is not None and s.get("_i") is not None and \
                    None not in ids else None
                j = memo.get(mk) if mk is not None else None
                if j is None:
                    if grid is None:
                        grid = RK.Grid(START_CELL)
                        for x in own:
                            grid.add(x, x[1][1])
                    j = _start_pick(cands, prev, nxt, feat(s), grid, mode)
                    if mk is not None:
                        memo[mk] = j
                if cands[j] is not s:
                    out[n] = s = cands[j]
                    changed = True
        f = feat(s)
        if f and (f[0] == "tongues" or (mode == "safe" and f[0] == "holes")):
            own.append(f)
            ids.append(s.get("_i"))
            if grid is not None:
                grid.add(f, f[1][1])
    return out if changed else sh


# =========================================================================== точка врезки внешнего контура
def outer_candidates(outer):
    """Кандидаты точки врезки: индексы вершин (полилиния) или углы (окружность)."""
    if outer["kind"] == "Circle":
        return [k * math.pi / 4 for k in range(8)]
    V = outer["verts"]
    n = len(V)
    sg = 1 if G.poly_area(V) > 0 else -1
    cand = []
    for k in range(n):
        p0, p1, p2 = V[k - 1], V[k], V[(k + 1) % n]
        if abs(p0[2]) > 1e-12 or abs(p1[2]) > 1e-12:            # по обе стороны — прямые
            continue
        ax, ay = p1[0] - p0[0], p1[1] - p0[1]
        bx, by = p2[0] - p1[0], p2[1] - p1[1]
        if math.hypot(bx, by) < 2.0 or math.hypot(ax, ay) < 1e-9:
            continue
        cr = ax * by - ay * bx
        if sg * cr <= 1e-9:                                      # только выпуклые углы
            continue
        cand.append(k)
    if not cand:
        cand = [k for k in range(n) if abs(V[k][2]) < 1e-12] or [0]
    if len(cand) > MAX_CAND:                                     # по секторам вокруг центра — разнести по контуру
        cx = sum(v[0] for v in V) / n; cy = sum(v[1] for v in V) / n
        sect = {}
        for k in cand:
            a = int((math.atan2(V[k][1] - cy, V[k][0] - cx) + math.pi) / (2 * math.pi) * MAX_CAND) % MAX_CAND
            d = math.hypot(V[k][0] - cx, V[k][1] - cy)
            if a not in sect or d > sect[a][0]:
                sect[a] = (d, k)
        cand = sorted(k for d, k in sect.values())
    return cand


def lead_free(outer_started, W, L, polys, limit=20.0, step=0.05, skip=None):
    """Свободно по наружной нормали к началу реза внешнего контура, мм (до limit). polys — [(точки, габарит)] или
    risk.Grid таких; skip — свой многоугольник (не препятствие)."""
    if outer_started["kind"] == "Circle":
        cx, cy = outer_started["c"]; a = outer_started["a0"]
        x1, y1 = cx + outer_started["r"] * math.cos(a), cy + outer_started["r"] * math.sin(a)
        nx, ny = math.cos(a), math.sin(a)
    else:
        V = outer_started["verts"]
        (x1, y1), (x2, y2) = V[0][:2], V[1][:2]
        Lg = math.hypot(x2 - x1, y2 - y1)
        sg = 1 if G.poly_area(V) > 0 else -1
        nx, ny = sg * (y2 - y1) / Lg, -sg * (x2 - x1) / Lg
    # препятствия — только те, чей габарит задевает луч (точки луча — в его габарите; результат тот же)
    ex, ey = x1 + nx * limit, y1 + ny * limit
    lo_x, hi_x, lo_y, hi_y = min(x1, ex) - 1e-6, max(x1, ex) + 1e-6, min(y1, ey) - 1e-6, max(y1, ey) + 1e-6
    if hasattr(polys, "query"):
        polys = [q for q in polys.query(lo_x, lo_y, hi_x, hi_y) if q is not skip]
    else:
        polys = [(P, bx) for P, bx in polys if not (bx[2] < lo_x or bx[0] > hi_x or bx[3] < lo_y or bx[1] > hi_y)]
    for i in range(1, int(limit / step) + 1):
        pt = (x1 + nx * i * step, y1 + ny * i * step)
        if not (0 <= pt[0] <= W and 0 <= pt[1] <= L):
            return i * step
        for P, bx in polys:
            if bx[0] <= pt[0] <= bx[2] and bx[1] <= pt[1] <= bx[3] and G.inside(pt, P):
                return i * step
    return limit


def _grid(polys):
    g = RK.Grid()
    for q in polys:
        g.add(q, q[1])
    return g


# =========================================================================== маршрут листа
class _PartPlan:
    """Варианты обхода одной детали (в координатах листа)."""

    def __init__(self, part, rot, d, small=RK.SMALL):
        self.part = part
        sh = [G.transform(s, rot, d) for s in part["shapes"]]
        self.inner = [dict(s, _i=j) for j, s in enumerate(sh[:-1])]      # _i — номер в детали (вырезанное, кэш)
        self.outer = sh[-1]
        self.snake = snake_options(self.inner)
        self.cands = outer_candidates(self.outer)
        self.tongues = tongue_polys(self.inner)
        self._segx, self._intx = {}, {}
        P = G.points(self.outer, 0.2)
        self.poly = (P, (min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P)))
        self.center = ((self.poly[1][0] + self.poly[1][2]) / 2, (self.poly[1][1] + self.poly[1][3]) / 2)
        self.kind = RK.part_kind(part, small)
        self._ob, self._feat, self._ord, self._free, self._hs, self._cs = None, {}, {}, {}, {}, {}
        self._hz, self._memo, self._core, self._bs = None, {}, {}, {}
        ib = G.bbox(self.inner) if self.inner else None    # где ходит головка внутри детали (+ впритирку) — для кэша
        self.inner_box = (ib[0] - RK.NEAR - 1, ib[1] - RK.NEAR - 1, ib[2] + RK.NEAR + 1, ib[3] + RK.NEAR + 1) if ib else None

    def hole_starts(self, s):
        j = s.get("_i")
        if j is None:
            return hole_starts(s)
        if j not in self._hs:
            self._hs[j] = hole_starts(s)
        return self._hs[j]

    def choose(self, sh, head, tail, mode):
        """choose_starts с кэшем; без язычков и отверстий ≥ HOLE_MIN оба ключа выбирают одинаково — кэш общий. Головка
        (хвост) влияет на выбор, только если первая (последняя) фигура — отверстие: иначе в ключе её нет."""
        if self._hz is None:
            self._hz = any(f and f[0] in ("tongues", "holes") for f in (self.feat(s) for s in self.inner))
        h = head if sh and G.is_closed(sh[0]) and sh[0]["layer"] == 1 else None
        t = tail if sh and G.is_closed(sh[-1]) and sh[-1]["layer"] == 1 else None
        key = (id(sh), h, t, mode if self._hz else "")
        if key not in self._cs:
            self._cs[key] = (choose_starts(sh, head, tail, mode if self._hz else "short", self.feat, self.hole_starts, self._memo), sh)
        return self._cs[key][0]

    def snake_path(self, oi, o, where):
        """Путь змейки (вариант oi, прочие фигуры на месте where): [фигуры, переходов над язычками (по запросу), есть
        отверстия, след счёта переходов (по запросу)] — кэш."""
        ik = (oi, where)
        if ik not in self._intx:
            sh = snake_shapes(o, where)
            self._intx[ik] = [sh, None, any(G.is_closed(s) and s["layer"] == 1 for s in sh), None]
        return self._intx[ik]

    def snake_x(self, v):
        if v[1] is None:
            v[3] = {}
            v[1] = crossings(v[0], None, trace=v[3])
        return v[1]

    @property
    def ob(self):
        if self._ob is None:
            self._ob = RK.obstacle(self.outer)
        return self._ob

    def feat(self, s, i=None):
        j = s.get("_i")
        if j is None:
            return RK.feature(s)
        if j not in self._feat:
            self._feat[j] = RK.feature(s)
        return self._feat[j]

    def started(self, k):
        return G.rotate_start(self.outer, k)

    def order_path(self, head, k):
        """Точный путь оптимизатора от головки до врезки k (кэш: стратегии и порядки деталей с теми же точками)."""
        key = (head, k)
        if key not in self._ord:
            self._ord[key] = order(self.inner, head, G.ends(self.started(k))[0])
        return self._ord[key]

    def order_to(self, head, tail):
        """Путь оптимизатора от head к точке tail (группы общего реза: tail — начало внешней части), с кэшем."""
        key = ("to", head, tail)
        if key not in self._ord:
            self._ord[key] = order(self.inner, head, tail)
        return self._ord[key]

    def free_path(self, k, hs=None, x=True):
        """Путь от свободного начала до врезки k (для деталей с большим числом элементов): (фигуры, холостой, начало,
        переходов над язычками — если x); hs — начала отверстий."""
        key = (k, hs)
        if key not in self._free:
            tail = G.ends(self.started(k))[0]
            sh, c = self.free_path(k, None, False)[:2] if hs else order(self.inner, None, tail)
            if hs:
                sh2 = self.choose(sh, None, tail, hs)
                if sh2 is not sh:
                    sh, c = sh2, path_eval(sh2, None, tail)
            self._free[key] = [sh, c, (G.ends(sh[0])[0] if sh else tail), None]
        f = self._free[key]
        if x and f[3] is None:
            f[3] = crossings(f[0], None)
        return tuple(f)

    def seg_x(self, a, b):
        """1 — переход a→b проходит над язычком этой детали (все прорези к этому моменту вырезаны)."""
        if not self.tongues or D(a, b) <= 1.0:
            return 0
        key = (round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2))
        if key not in self._segx:
            self._segx[key] = 1 if _seg_hits(a, b, self.tongues, margin=0.5) else 0
        return self._segx[key]

    def cost(self, head, k, hs=False):
        """(холостой ход от head до конца внешнего контура при врезке k, фигуры в порядке резки, переходов над язычками) —
        ключ «как было»; hs — начала отверстий по ходу пути (вход + выход короче)."""
        ok = self.started(k)
        tail = G.ends(ok)[0]
        best = None
        if self.snake:
            for oi, o in enumerate(self.snake):
                c, where = snake_cost(o, head, tail)
                v = self.snake_path(oi, o, where)            # переходы внутри змейки от головки не зависят
                sh, xi, closed = v[0], self.snake_x(v), v[2]
                if hs and closed:
                    sh2 = self.choose(sh, head, tail, "short")
                    if sh2 is not sh:
                        sh, c, xi = sh2, path_eval(sh2, head, tail), crossings_like(sh2, sh, v[3])
                x = xi + self.seg_x(G.ends(sh[-1])[1], tail)
                if best is None or c + CROSS_PENALTY * x < best[0] + CROSS_PENALTY * best[2]:
                    best = (c, sh, x)
            best = (best[0], best[1] + [ok], best[2])
        if len(self.inner) <= EXACT_N and (best is None or best[2]):
            sh, c = self.order_path(head, k)
            if hs:
                sh2 = self.choose(sh, head, tail, "short")
                if sh2 is not sh:
                    sh, c = sh2, path_eval(sh2, head, tail)
            x = crossings(sh, head) + (self.seg_x(G.ends(sh[-1])[1], tail) if sh else 0)
            if best is None or c + CROSS_PENALTY * x < best[0] + CROSS_PENALTY * best[2]:
                best = (c, sh + [ok], x)
        elif best is None or best[2]:
            sh, c, start, xi = self.free_path(k, "short" if hs else None)
            c += (D(head, start) if head is not None else 0.0)
            x = xi + (self.seg_x(G.ends(sh[-1])[1], tail) if sh else 0)
            if best is None or c + CROSS_PENALTY * x < best[0] + CROSS_PENALTY * best[2]:
                best = (c, sh + [ok], x)
        return best

    # ------------------------------------------------------------------ безопасные стратегии
    def evaluate(self, head, sh, ev, sid=None):
        """(вектор опасностей, холостой) пути sh (внутренние + внешний последним) от head; ev — {"sheet": вырезанное
        листа до детали, "cache": переходы между внутренними от головки и врезки не зависят — кэш по пути (sid — имя
        пути внутренних)}. Отдельно: заход от головки и переход к врезке внешнего контура."""
        inner, ok = sh[:-1], sh[-1]
        tail = G.ends(ok)[0]
        sheet, cache = ev["sheet"], ev["cache"]

        def entry(a):                                   # заход: от головки, общий для всех врезок
            if head is None:
                return RK.ZERO
            key = ("in", head, a)
            if key not in cache:
                cache[key] = RK.move(head, a, sheet)
            return cache[key]
        if not inner:
            return entry(tail), (D(head, tail) if head is not None else 0.0)
        a = G.ends(inner[0])[0]
        if sid is None:
            sid = tuple((s.get("_i"), G.ends(s)[0], G.ends(s)[1]) for s in inner)
        core = cache.get(sid)
        if core is None:
            # путь внутри детали зависит только от вырезанного листа рядом (inner_box: все его переходы и «впритирку»)
            # — кэш плана на все прогоны динамики: (путь, что вырезано рядом)
            sig = ev.get("sig")
            if sig is None:
                sig = ev["sig"] = tuple(sorted(id(ob) for _, ob in sheet.query(*self.inner_box)))
            ck = (sid, sig)
            core = self._core.get(ck)
            if core is None:
                v, c, end, _, own = RK.walk([(s, 0) for s in inner], a, sheet, {}, {}, lambda s, i: self.feat(s))
                core = self._core[ck] = (v, c, end, own)
            cache[sid] = core
        v, c, end, own = core
        key = ("out", sid, tail)
        if key not in cache:
            cache[key] = RK.move(end, tail, sheet, own)
        return RK.vadd(RK.vadd(entry(a), v), cache[key]), (D(head, a) if head is not None else 0.0) + c + D(end, tail)

    def _entry(self, head, sh, ev):
        """Вектор захода от головки в путь sh (из кэша evaluate)."""
        if head is None:
            return RK.ZERO
        a = G.ends(sh[0])[0]
        key = ("in", head, a)
        if key not in ev["cache"]:
            ev["cache"][key] = RK.move(head, a, ev["sheet"])
        return ev["cache"][key]

    def _pick(self, head, pool, ev, best=None):
        """Лучший по ключу безопасных из [(холостой, фигуры, имя пути | None)]; по возрастанию холостого — дальше,
        пока может быть лучше. Вернуть (ключ, вектор, холостой, фигуры)."""
        for c, sh, sid in sorted(pool, key=lambda v: v[0]):
            if best is not None and best[0] <= (0, 0, 0, 0, c - 1e-6):
                break
            v, idle = self.evaluate(head, sh, ev, sid)
            kk = RK.safe_key(v, idle)
            if best is None or kk < best[0]:
                best = (kk, v, idle, sh)
        return best

    def best_safe_cached(self, head, k, ev, hs="safe", more=True):
        """best_safe с кэшем на все прогоны динамики: результат зависит только от головки, угла, переключателей и того,
        что вырезано на листе в габарите (головка + деталь) ± NEAR — там все его переходы и «впритирку»; ключ —
        (головка, угол, переключатели, что вырезано там)."""
        sigs = ev.setdefault("sigs", {})
        sig = sigs.get(head)
        if sig is None:
            bx = self.poly[1] if head is None else _ubox(head, self.poly[1])
            m = RK.NEAR + 1.0
            sig = sigs[head] = tuple(sorted(id(ob) for _, ob in ev["sheet"].query(bx[0] - m, bx[1] - m, bx[2] + m, bx[3] + m)))
        ck = (head, k, hs, more, sig)
        r = self._bs.get(ck)
        if r is None:
            r = self._bs[ck] = self.best_safe(head, k, ev, hs, more)
        return r

    def best_safe(self, head, k, ev, hs="safe", more=True):
        """Лучший по ключу безопасных путь по детали при врезке k: (ключ, вектор, холостой, фигуры). Варианты: змейка,
        путь оптимизатора (точный от головки или со свободным началом); начала отверстий — без выхода над отверстием.
        more — лучшее состояние динамики: путь оптимизатора точный от головки (иначе — со свободным началом, он от головки
        не зависит), а если остался опасный переход — у змейки ещё и путь оптимизатора, затем другой первый элемент."""
        ok = self.started(k)
        tail = G.ends(ok)[0]
        pool = []
        if self.snake:
            for oi, o in enumerate(self.snake):
                c, where = snake_cost(o, head, tail)
                v = self.snake_path(oi, o, where)
                sh, closed = v[0], v[2]
                sid = ("s", oi, where)
                if hs and closed:
                    sh2 = self.choose(sh, head, tail, hs)
                    if sh2 is not sh:
                        sh, c, sid = sh2, path_eval(sh2, head, tail), None
                pool.append((c, sh + [ok], sid))
        best = self._pick(head, pool, ev) if pool else None
        inner_x = best is not None and more and best[0][:4] != (0, 0, 0, 0) and \
            RK.safe_key(RK.vsub(best[1], self._entry(head, best[3], ev)), 0.0)[:4] != (0, 0, 0, 0)
        if best is None or inner_x:                    # у змейки опасно внутри — и путь оптимизатора
            if len(self.inner) <= EXACT_N and (more or not self.inner):    # точный от головки — только для лучших состояний
                sh, c = self.order_path(head, k)
                sid = None
                if hs:
                    sh2 = self.choose(sh, head, tail, hs)
                    if sh2 is not sh:
                        sh, c = sh2, path_eval(sh2, head, tail)
            else:
                sh, c, start, _ = self.free_path(k, hs, False)
                c += (D(head, start) if head is not None else 0.0)
                sid = ("f", k, hs)
            best = self._pick(head, [(c, sh + [ok], sid)], ev, best)
        if more and best[0][:4] != (0, 0, 0, 0) and len(self.inner) >= 2 and not self.snake:
            best = self.alt_safe(head, k, ev, best)    # змейку разворачивать бессмысленно: у неё 4 угла начала
        return best

    def alt_safe(self, head, k, ev, best, top=3):
        """Опасный переход остался — другой первый элемент: начало пути развёрнуто до j-го элемента (тот же путь, без
        оптимизатора). Сперва дёшево — заход в новый первый элемент без опасных и холостой (переходы развёрнутого
        начала — те же расстояния, суммы по порядку); полностью — top лучших."""
        sh = best[3][:-1]
        n = len(sh)
        if n < 2:
            return best
        ok = best[3][-1]
        tail = G.ends(ok)[0]
        E = [G.ends(s) for s in sh]
        pre = [0.0]
        for t in range(1, n):
            pre.append(pre[-1] + D(E[t - 1][1], E[t][0]))   # pre[j] — переходы внутри пути до j-го элемента
        pool = []
        for j in range(1, n):
            a = E[j][1]                                   # развёрнутый j-й начинается с его конца
            if j + 1 < n:
                idle = D(head, a) + pre[j] + D(E[0][0], E[j + 1][0]) + (pre[-1] - pre[j + 1]) + D(E[-1][1], tail)
            else:
                idle = D(head, a) + pre[j] + D(E[0][0], tail)
            pool.append((idle, j))
        pool.sort()
        cache, safe = ev["cache"], []
        for idle, j in pool:                              # по возрастанию холостого — первые top с безопасным заходом
            a = E[j][1]
            key = ("in", head, a)
            if key not in cache:
                cache[key] = RK.move(head, a, ev["sheet"])
            if cache[key][:4] == (0, 0, 0, 0):
                safe.append((idle, j))
                if len(safe) >= top:
                    break
        pool = safe
        alts = []
        for idle, j in pool:
            alt = [G.reverse(s) if G.is_open(s) else s for s in reversed(sh[:j + 1])] + sh[j + 1:]
            alts.append((idle, alt + [ok], None))
        return self._pick(head, alts, ev, best)


def _nn_order(plans, head, closed=False):
    """Ближайший сосед от головки по центрам + 2-opt (closed — обход замкнутый: после последней — к головке)."""
    rest, seq, pos = list(range(len(plans))), [], head
    while rest:
        i = min(rest, key=lambda i: (D(pos, plans[i].center), i)); rest.remove(i); seq.append(i); pos = plans[i].center
    improved = True
    while improved and len(seq) > 3:
        improved = False
        for i in range(len(seq) - 1):
            for j in range(i + 1, len(seq)):
                a = plans[seq[i - 1]].center if i else head
                b, c = plans[seq[i]].center, plans[seq[j]].center
                dd = plans[seq[j + 1]].center if j + 1 < len(seq) else (head if closed else None)
                old = D(a, b) + (D(c, dd) if dd else 0)
                new = D(a, c) + (D(b, dd) if dd else 0)
                if new < old - 1e-9:
                    seq[i:j + 1] = seq[i:j + 1][::-1]; improved = True
    return seq


def _small_last(plans, head):
    """Мелкие детали — последними: крупные ближайшим соседом + 2-opt от головки, затем мелкие так же от последней
    крупной (над мелкими после их освобождения головке ходить почти некуда)."""
    big = [i for i, p in enumerate(plans) if p.kind != "small"]
    sm = [i for i, p in enumerate(plans) if p.kind == "small"]
    if not big or not sm:
        return None
    a = [big[j] for j in _nn_order([plans[i] for i in big], head)]
    b = [sm[j] for j in _nn_order([plans[i] for i in sm], plans[a[-1]].center)]
    return a + b


def _safe_nn(C, head, near=SAFE_NN):
    """Ближайший сосед «без опасных»: следующая — из near ближайших та, к которой переход от точки врезки предыдущей не
    идёт над освобождёнными (ступени ключа, как в risk.move), при равенстве — ближайшая. Заход в деталь — в её центр, если
    внутри есть что резать (обычно отверстия у центра), иначе в точку врезки; уход — от точки врезки (у детали без места
    под подвод — первый из одинаково свободных углов): плотные ряды мелких деталей, где угол один."""
    plans, cands = C["plans"], C["cands_t"]
    out_ = [G.ends(plans[i].started(cands[i][0]))[0] for i in range(len(plans))]
    in_ = [plans[i].center if plans[i].inner else out_[i] for i in range(len(plans))]
    sheet, rest, seq, pos = RK.Sheet(), list(range(len(plans))), [], head
    while rest:
        near_ = sorted(rest, key=lambda i: (D(pos, in_[i]), i))[:near]
        i = min(near_, key=lambda i: (tuple(RK.move(pos, in_[i], sheet)[c] for c in _TIERS), D(pos, in_[i]), i))
        rest.remove(i); seq.append(i)
        _commit(sheet, plans[i])
        pos = out_[i]
    return seq


def _sweep(plans, axis):
    """Полосами от начала листа змейкой: axis 1 — ряды по Y (в ряду — по X), 0 — колонки по X. Ширина полосы —
    медианный размер детали поперёк (ряд мелких деталей — сперва нижний, затем верхний обратно: над только что
    вырезанными головка не возвращается)."""
    ext = sorted(p.poly[1][2 + axis] - p.poly[1][axis] for p in plans)
    band = max(1.0, ext[len(ext) // 2])
    rows = collections.defaultdict(list)
    for i, p in enumerate(plans):
        rows[int(p.center[axis] // band)].append(i)
    out, flip = [], False
    for k in sorted(rows):
        out += sorted(rows[k], key=lambda i: (plans[i].center[1 - axis], i), reverse=flip); flip = not flip
    return out


def _repair_cands(C, seq, route, m, kn, window=REPAIR_WINDOW):
    """Варианты порядка деталей около опасных переходов маршрута route (порядок seq), по важности: сперва ступень ключа
    (язычки → мелкие → детали → отверстия), в ступени — от конца листа (динамика продолжается с места изменения —
    поздние дешевле). Для перехода над освобождёнными деталями — прицельно: вырезать деталь, к которой шёл переход,
    раньше пересечённой; пересечённую — после неё; развернуть участок между ними. Затем окно ±window: развернуть
    участок или переставить деталь. kn = "key0" — и возврат в ноль (переход после последней детали)."""
    plans = C["plans"]
    n = len(seq)
    owner = [t for t, (i, sh) in enumerate(route) for s in sh]
    moves = m["moves"]
    bad = []
    for k, (a, b, v) in enumerate(moves):
        if k >= len(owner) and kn != "key0":
            break
        tier = next((z for z, c in enumerate(_TIERS) if v[c]), None)
        if tier is not None:
            bad.append((tier, -(owner[k] if k < len(owner) else n), a, b, v))
    bad.sort(key=lambda x: (x[0], x[1]))
    out, seen = [], {tuple(seq)}

    def put(c):
        if tuple(c) not in seen:
            seen.add(tuple(c)); out.append(c)
    for tier, nt, a, b, v in bad:
        t = -nt                                        # место детали, к которой шёл переход (n — возврат в ноль)
        if v[RK.SMALLP] or v[RK.PART]:
            x0, x1, y0, y1 = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
            U = []
            for u in range(min(t, n) - 1, -1, -1):     # освобождённые до перехода, над которыми он прошёл
                p = plans[seq[u]]
                bx = p.ob[1]
                if p.kind in ("small", "parts") and not (bx[2] < x0 or bx[0] > x1 or bx[3] < y0 or bx[1] > y1) and \
                        RK.deep_len(a, b, p.ob, RK.DEEP_PART) >= RK.MIN_OVER:
                    U.append(u)
                    if len(U) >= 3:
                        break
            for u in U:
                if t < n:
                    put(seq[:u] + [seq[t]] + seq[u:t] + seq[t + 1:])          # деталь t — до пересечённой
                    put(seq[:u] + seq[u + 1:t + 1] + [seq[u]] + seq[t + 1:])  # пересечённая — после t
                    put(seq[:u] + seq[u:t + 1][::-1] + seq[t + 1:])
                put(seq[:u] + seq[u + 1:] + [seq[u]])         # пересечённая — последней (её угол врезки смотрит прочь
                if t >= n:                                    # от остальных; возврат над ней — тоже)
                    put(seq[:u] + seq[u:][::-1])
        t = min(t, n - 1)
        lo, hi = max(0, t - window), min(n - 1, t + window)
        for i in range(lo, hi + 1):
            if i != t:
                r = seq[:t] + seq[t + 1:]
                put(r[:i] + [seq[t]] + r[i:])
        for i in range(lo, t + 1):
            for j in range(max(i + 1, t), hi + 1):
                put(seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:])
    return out


def _repair(C, route, m, run, head, o, kn, budget, add):
    """Остались опасные переходы (ступени ключа kn: "key" — без возврата, "key0" — с ним) — правка порядка деталей около
    них (_repair_cands). Каждый вариант — той же динамикой, но с места первого изменения (состояния до него — из трассы
    прогона run = (порядок, трасса)); оба конца прогона — кандидаты (add); вариант принят, если ступени опасных kn
    строго лучше; пока лучше и хватает budget (шагов-деталей, общий на все правки листа)."""
    if run is None:                                    # маршрут «short»: прогон динамики по его порядку, с трассой
        seq = [i for i, _ in route]
        tr = []
        rk, rk0 = _dp_safe(C, seq, head, o, trace=tr)
        budget[0] -= len(seq)
        run = (seq, tr)
        m1, m2 = add(rk, run), add(rk0, run)
        m, route = min(((m1, rk), (m2, rk0)), key=lambda v: v[0][kn])
    seq, tr = run
    n = len(seq)
    while m[kn][:4] != ZERO4 and budget[0] > 0:
        improved = False
        for c in _repair_cands(C, seq, route, m, kn):
            a = next(t for t in range(n) if c[t] != seq[t])
            if n - a > budget[0]:
                continue
            budget[0] -= n - a
            tr2 = tr[:a]
            rk, rk0 = _dp_safe(C, c, head, o, trace=tr2, start=a, init=tr[a])
            run2 = (c, tr2)
            m1 = add(rk, run2)
            m2 = add(rk0, run2) if rk0 is not rk else m1
            m_, r_ = (m1, rk) if m1[kn] <= m2[kn] else (m2, rk0)
            if m_[kn][:4] < m[kn][:4]:
                seq, tr, m, route, improved = c, tr2, m_, r_, True
                break
            if budget[0] <= 0:
                break
        if not improved:
            break


def _prep(placed, parts, W, L, head, small, cache):
    """Общее для всех стратегий листа (кэш между стратегиями): планы деталей, точки врезки с местом под подвод, порядок."""
    if cache is not None and cache.get("prep") is not None and cache.get("prep_key") == (small, head):
        return cache["prep"]
    plans = [_PartPlan(parts[q["part"]], q["rot"], (q["dx"], q["dy"]), small) for q in placed]
    polys = [p.poly for p in plans]
    allg = _grid(polys)
    seq = _nn_order(plans, head)
    warnings, cands, frs, ties = [], {}, {}, {}
    for i in seq:
        p = plans[i]
        fr = {k: lead_free(p.started(k), W, L, allg, skip=p.poly) for k in p.cands}
        ok = [k for k in p.cands if fr[k] >= LEAD_FREE]
        if not ok:
            k = max(p.cands, key=lambda k: fr[k]); ok = [k]
            warnings.append("деталь %s: под подвод свободно только %.1f мм" % (p.part["name"], fr[k]))
            # такой же свободы у других углов — тоже годятся (правило то же: самый свободный угол), выбор — маршруту
            ties[i] = [c for c in p.cands if fr[c] >= fr[k] - 1e-9]
        cands[i], frs[i] = ok, fr
    C = dict(plans=plans, polys=polys, seq=seq, cands=cands, frs=frs, warnings=warnings, closed={}, ties=ties)
    C["cands_t"] = {i: ties.get(i, c) for i, c in cands.items()}
    if cache is not None:
        cache["prep"], cache["prep_key"] = C, (small, head)
    return C


def _dp_short(C, seq, head, hs, ties=False, with_cost=False):
    """Динамика «как было»: состояние — точка врезки предыдущей детали. Переход к детали над уже вырезанной деталью —
    штраф PART_CROSS_PENALTY (вырезанная деталь может приподняться), над язычком — CROSS_PENALTY. ties — у деталей без
    места под подвод все самые свободные углы (иначе — первый из них, как было)."""
    plans, cands = C["plans"], C["cands_t" if ties else "cands"]
    states = {None: (0.0, head, [], 0)}
    done = RK.Grid()
    for i in seq:
        p = plans[i]
        new = {}
        for key, (cost, hpos, acc, xs) in states.items():
            for k in cands[i]:
                c, sh, x = p.cost(hpos, k, hs)
                xp = 1 if done and _seg_hits(hpos, G.ends(sh[0])[0], done) else 0
                tot = cost + c + CROSS_PENALTY * x + PART_CROSS_PENALTY * xp
                if k not in new or tot < new[k][0] - 1e-9:
                    new[k] = (tot, G.ends(sh[-1])[0], acc + [(i, sh)], xs + x)
        states = new
        done.add(p.poly, p.poly[1])
    cost, _, best, xs = min(states.values(), key=lambda v: v[0])
    if with_cost:
        return best, cost
    return best


def _short_route(C, head, o):
    """Маршрут «short»: динамика «как было» по порядку деталей ближайшим соседом; с переключателем orders — ещё по
    порядкам змейкой по рядам и замкнутым обходом, лучший по той же цене динамики (холостой + штрафы; змейка по
    колонкам на образцах не выигрывала ни разу — не считается):
    порядок соседями берётся первым, другой — только если дешевле (m30: 90,6 → 83,4 м, ряды мелких деталей — меньше
    переходов над ними). Кэш в C — общий с пулом безопасных (их кандидат — этот же маршрут)."""
    hs, ties = bool(o["hole_starts"]), bool(o.get("lead_ties"))
    ck = ("short", hs, ties, bool(o.get("orders")))
    if ck not in C:
        plans, seq = C["plans"], C["seq"]
        seqs = [seq]
        if o.get("orders") and len(seq) > 1:
            if "seq0" not in C["closed"]:
                C["closed"]["seq0"] = _nn_order(plans, head, closed=True)
            for s in (_sweep(plans, 1), C["closed"]["seq0"]):
                if s not in seqs:
                    seqs.append(s)
        runs = [_dp_short(C, s, head, hs, ties, with_cost=True) for s in seqs]
        C[ck] = min(((c, n, b) for n, (b, c) in enumerate(runs)), key=lambda v: (v[0], v[1]))[2]
    return C[ck]


def _commit(sheet, p):
    """Деталь вырезана: в состояние листа — она (по классу) и, если держится перемычками, её вырезанное."""
    sheet.add(p.kind, p.ob)
    if p.kind == "mj":
        for s in p.inner:
            f = p.feat(s)
            if f:
                sheet.add(*f)


def _dp_safe(C, seq, head, o, alt_states=None, trace=None, start=0, init=None, keys=False):
    """Динамика по ключу безопасных (risk.safe_key): состояние — точка врезки предыдущей детали; вырезанное к детали от
    состояния не зависит (порядок деталей задан). Остался опасный переход — путь оптимизатора у змейки и другой первый
    элемент детали — от ALT_STATES лучших состояний (от всех — решётки втрое дольше при тех же числах). Вернуть два
    маршрута: лучший по ключу без возврата и лучший с возвратом в ноль (key0; конец листа — точка врезки последней
    детали, так что возврат зависит только от последнего состояния). trace — список, куда состояния перед каждым местом
    порядка (для _repair); start, init — продолжить с места start от состояний init (порядок до него тот же); keys — и их
    ключи (без возврата, с возвратом)."""
    plans, cands = C["plans"], C["cands_t" if o.get("lead_ties") else "cands"]
    hs = "safe" if o["hole_starts"] else None
    sheet = RK.Sheet()
    for i in seq[:start]:
        _commit(sheet, plans[i])
    states = init if init is not None else {None: ((0, 0, 0, 0, 0.0), RK.ZERO, 0.0, head, [])}
    for t in range(start, len(seq)):
        if trace is not None:
            trace.append(states)
        i = seq[t]
        p = plans[i]
        ev = dict(sheet=sheet, cache={})
        new = {}
        alt_from = {id(v) for v in sorted(states.values(), key=lambda v: v[0])[:alt_states or ALT_STATES]}
        for st in states.values():
            key, vec, idle, hpos, acc = st
            for k in cands[i]:
                b = p.best_safe_cached(hpos, k, ev, hs, id(st) in alt_from)
                tv, ti = RK.vadd(vec, b[1]), idle + b[2]
                kk = RK.safe_key(tv, ti)
                if k not in new or kk < new[k][0]:
                    new[k] = (kk, tv, ti, G.ends(b[3][-1])[0], acc + [(i, b[3])])
        states = new
        _commit(sheet, p)
    b = min(states.values(), key=lambda v: v[0])
    fin = []
    for kk, tv, ti, pos, acc in states.values():
        rv = RK.move(pos, head, sheet)
        fin.append((RK.safe_key(RK.vadd(tv, rv), ti + D(pos, head)), acc))
    b0 = min(fin, key=lambda v: v[0])
    if keys:
        return b[4], b0[1], b[0], b0[0]
    return b[4], b0[1]


def _all_orders(C, head, o, kn, add):
    """Малый лист (≤ EXACT_ORDERS деталей), опасные остались — все порядки деталей той же динамикой: перестановки по
    порядку, у соседних общее начало — динамика продолжается от его состояний (720 порядков из 6 деталей — 1956 шагов,
    не 4320). Кандидат — лучший по ключу kn (счёт динамики тот же, что у measure; в пул — с проверкой measure)."""
    seq = sorted(C["seq"])
    best, prev, tr = None, None, None
    for perm in itertools.permutations(seq):
        a = 0 if prev is None else next(t for t in range(len(perm)) if perm[t] != prev[t])
        tr2 = [] if prev is None else tr[:a]
        r = _dp_safe(C, list(perm), head, o, trace=tr2, start=a, init=None if prev is None else tr[a], keys=True)
        k = r[2] if kn == "key" else r[3]
        if best is None or k < best[0]:
            best = (k, r[0] if kn == "key" else r[1], (list(perm), tr2))
        prev, tr = perm, tr2
    add(best[1], best[2])


def _measure(C, best, head):
    tagged = [(s, i) for i, sh in best for s in sh]
    plans = C["plans"]
    if "obs" not in C:
        C["obs"] = {i: p.ob for i, p in enumerate(plans)}
    return RK.measure(tagged, [p.kind for p in plans], [p.outer for p in plans], head, feat=lambda s, i: plans[i].feat(s),
                      obs=C["obs"])


def _safe_pool(C, head, o):
    """Кандидаты маршрута листа безопасных стратегий — общие для safe и safe0 (каждая берёт лучший по своему ключу):
    динамика по порядкам деталей — ближайший сосед и замкнутый обход от нуля в обе стороны (у каждой — оба конца: без
    возврата и с ним); маршрут «short»; остались опасные переходы (лучший без возврата или лучший с возвратом) —
    порядки «ближайший без опасных», «мелкие последними», змейкой по колонкам и по рядам (пока не уйдут), затем правка
    порядка около опасных переходов (_repair: REPAIR_WORK проходов на лист, не меньше REPAIR_MIN шагов), на листе до
    EXACT_ORDERS деталей с опасными в программе — все порядки. Вернуть [(счёт measure, номер, маршрут, прогон)]; кэш в C
    (по переключателям пула — safe и safe0 с общим кэшем листа считают его один раз). Работа ограничена: 3 прогона +
    «short» + до 4 порядков + правка ≤ max(REPAIR_WORK·n, REPAIR_MIN) шагов на ключ (прежде — до 80 полных прогонов)."""
    pk = ("pool", bool(o["hole_starts"]), bool(o.get("lead_ties")), bool(o.get("orders")))
    if pk in C:
        return C[pk]
    plans, seq = C["plans"], C["seq"]
    ms, tried = [], set()

    def add(route, run=None):
        m = _measure(C, route, head)
        ms.append((m, len(ms), route, run))
        return m

    def dp(s):
        if not s or tuple(s) in tried:
            return
        tried.add(tuple(s))
        tr = []
        rk, rk0 = _dp_safe(C, s, head, o, trace=tr)
        run = (list(s), tr)
        add(rk, run)
        if rk0 is not rk:
            add(rk0, run)

    def top(kn):
        return min(ms, key=lambda v: (v[0][kn], v[1]))

    def danger(kn):
        return top(kn)[0][kn][:4] != ZERO4
    sr = _short_route(C, head, o)                      # маршрут «short» (те же переключатели) — тоже кандидат; первым —
    dp(seq)                                            # его динамика заполняет кэш путей по деталям (дешевле остальное)
    if "seq0" not in C["closed"]:
        C["closed"]["seq0"] = _nn_order(plans, head, closed=True)
    s0 = C["closed"]["seq0"]
    dp(s0)
    dp(s0[::-1])
    add(sr)
    if danger("key") or danger("key0"):               # опасные остались — другие порядки деталей
        for f in (lambda: _safe_nn(C, head), lambda: _small_last(plans, head), lambda: _sweep(plans, 0), lambda: _sweep(plans, 1)):
            dp(f())
            if not (danger("key") or danger("key0")):
                break
    for kn in ("key", "key0"):                         # и правка порядка (с возвратом — у конца листа, дёшево)
        if danger(kn):
            m, _, b, run = top(kn)
            budget = [max(REPAIR_WORK * len(seq), REPAIR_MIN if kn == "key" else 0)]
            _repair(C, b, m, run, head, o, kn, budget, add)
    if len(seq) <= EXACT_ORDERS and danger("key"):    # малый лист, опасные в программе — все порядки (только возврат
        _all_orders(C, head, o, "key", add)            # над деталью — не повод: его решают обход и правка у конца)
    C[pk] = ms
    return ms


def route_sheet(placed, parts, W, L, head=(0.0, 0.0), strategy=DEFAULT, small=RK.SMALL, cache=None):
    """placed: [{"part": i, "rot", "dx", "dy"}] → dict(seq=[(part_i, [фигуры в порядке резки])], order, idle, crossings
    (переходов над язычками — как было), crossings_parts (заходов в деталь над вырезанной — как было), risk (счёт
    risk.measure), lead_min, warnings). strategy — имя из STRATEGIES или словарь переключателей; cache — словарь листа
    (планы деталей, пути оптимизатора, кандидаты безопасных: safe и safe0 с одним кэшем считают их один раз)."""
    o = options(strategy)
    C = _prep(placed, parts, W, L, head, small, cache)
    plans, seq = C["plans"], C["seq"]
    if o["key"] == "short":
        best = _short_route(C, head, o)
        m = _measure(C, best, head)
    else:
        kk = "key0" if o["ret"] else "key"
        if o.get("pool"):
            ms = _safe_pool(C, head, o)
        else:
            ms = [(_measure(C, b, head), n, b, None) for n, b in enumerate(_dp_safe(C, seq, head, o))]
        m, _, best, _ = min(ms, key=lambda v: (v[0][kk], v[1]))
    shapes = [s for _, sh in best for s in sh]
    idle = 0.0
    pos = head
    for s in shapes:
        a, b = G.ends(s); idle += D(pos, a); pos = b
    lead_min = min(C["frs"][i][k] for (i, _), k in zip(best, _chosen_k(best, plans))) if best else None
    # переходы над вырезанными язычками и заходы в деталь над уже вырезанными деталями (как было)
    cut_parts, x_parts, pos = RK.Grid(), 0, head
    for i, sh in best:
        a = G.ends(sh[0])[0]
        if cut_parts and _seg_hits(pos, a, cut_parts):
            x_parts += 1
        pos = G.ends(sh[-1])[1]
        cut_parts.add(plans[i].poly, plans[i].poly[1])
    return dict(seq=[(placed[i]["part"], sh) for i, sh in best], order=[i for i, _ in best], idle=idle,
                crossings=crossings(shapes, head), crossings_parts=x_parts, risk=m, lead_min=lead_min,
                warnings=list(C["warnings"]), strategy=o["name"])


def _chosen_k(best, plans):
    """Индекс кандидата врезки, который выбран для каждой детали (по совпадению начала внешнего контура)."""
    out = []
    for i, sh in best:
        p = plans[i]
        st = G.ends(sh[-1])[0]
        out.append(min(p.cands, key=lambda k: D(G.ends(p.started(k))[0], st)))
    return out


def _seg_hits(a, b, polys, margin=1.0):
    """Отрезок a→b проходит внутри какого-то из многоугольников глубже margin мм. polys — список или risk.Grid."""
    L = D(a, b)
    lo_x, hi_x, lo_y, hi_y = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
    src = polys.query(lo_x, lo_y, hi_x, hi_y) if hasattr(polys, "query") else polys
    near = [(P, bx) for P, bx in src if not (bx[2] < lo_x or bx[0] > hi_x or bx[3] < lo_y or bx[1] > hi_y)]
    if not near:
        return False
    steps = int(L / 2) + 1
    for k in range(1, steps):
        t = k / steps
        pt = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        for P, bx in near:
            if bx[0] < pt[0] < bx[2] and bx[1] < pt[1] < bx[3] and G.inside(pt, P) \
                    and min(G.seg_point_dist(pt, P[i - 1], P[i]) for i in range(len(P))) > margin:
                return True
    return False


# =========================================================================================== лист с общим резом
class CoedgeRouteError(ValueError):
    """Группу общего реза не удалось разрезать ни одним порядком деталей — раскладывать без общего реза."""


def _part_crossings(tagged, polys, head):
    """Переходы над уже вырезанными деталями: деталь вырезана после последней своей фигуры.
    tagged — [(фигура, индекс размещения)]."""
    last = {}
    for k, (s, i) in enumerate(tagged):
        last[i] = k
    done, n, pos = RK.Grid(), 0, head
    for k, (s, i) in enumerate(tagged):
        a, b = G.ends(s)
        if done and D(pos, a) > 1.0 and _seg_hits(pos, a, done):
            n += 1
        pos = b
        if last[i] == k:
            done.add(polys[i], polys[i][1])
    return n


def _unit_order(plans, units, head, closed=False):
    def ucenter(u):
        xs = [plans[i].center for i in u[1]]
        return (sum(x for x, y in xs) / len(xs), sum(y for x, y in xs) / len(xs))
    C = [ucenter(u) for u in units]
    rest, seq_u, pos = list(range(len(units))), [], head
    while rest:
        k = min(rest, key=lambda k: (D(pos, C[k]), k)); rest.remove(k); seq_u.append(k); pos = C[k]
    improved = True
    while improved and len(seq_u) > 3:
        improved = False
        for i in range(len(seq_u) - 1):
            for j in range(i + 1, len(seq_u)):
                a = C[seq_u[i - 1]] if i else head
                b, c = C[seq_u[i]], C[seq_u[j]]
                dd = C[seq_u[j + 1]] if j + 1 < len(seq_u) else (head if closed else None)
                if D(a, c) + (D(b, dd) if dd else 0) < D(a, b) + (D(c, dd) if dd else 0) - 1e-9:
                    seq_u[i:j + 1] = seq_u[i:j + 1][::-1]; improved = True
    return seq_u


def _ref_points(m):
    """Куда головка пойдёт в детали группы первым: начала (и концы открытых) её внутренних контуров; нет их —
    вершины внешнего контура."""
    if m["inner"]:
        return [G.ends(s)[0] for s in m["inner"]] + [G.ends(s)[1] for s in m["inner"] if G.is_open(s)]
    return [(v[0], v[1]) for v in m["outer"]["verts"]]


def route_sheet_coedge(placed, groups, parts, W, L, head=(0.0, 0.0), strategy=DEFAULT, small=RK.SMALL, cache=None):
    """Лист с группами общего реза. Единицы резки — группы (блок CypCut «CoedgePart») и одиночные детали.
    Порядок единиц — ближайший сосед по центрам + 2-opt. Порядок деталей группы — лучший из кандидатов по ключу
    стратегии («short» — (переходы над вырезанными язычками, над вырезанными деталями, холостой ход), как было;
    безопасные — risk.safe_key): малые группы — все порядки, большие — обходы (соседями от ближней к головке; от
    крайних деталей; по центрам; полосами змейкой); каждый — без «взгляда вперёд» и с ним (look). Порядок, при котором у
    первой детали нет свободного угла или деталь целиком лежит на вырезанном, CypCut не строит — пропускается; если не
    подошёл ни один — CoedgeRouteError (раскладывать с зазором). Безопасные — кандидаты _coedge_pool (общие для safe и
    safe0), лучший по своему ключу.
    Вернуть dict(seq=[("part", i, фигуры) | ("group", [i…], фигуры)], idle, crossings, crossings_parts, risk,
    lead_min, warnings)."""
    o = options(strategy)
    if cache is not None and cache.get("prep") is not None and cache.get("prep_key") == (small, head):
        P = cache["prep"]
    else:
        plans = [_PartPlan(parts[q["part"]], q["rot"], (q["dx"], q["dy"]), small) for q in placed]
        in_group = {i for g in groups for i in g}
        units = [("group", list(g)) for g in groups] + [("part", [i]) for i in range(len(placed)) if i not in in_group]
        P = dict(plans=plans, units=units, seq=_unit_order(plans, units, head), allg=_grid([p.poly for p in plans]))
        if cache is not None:
            cache["prep"], cache["prep_key"] = P, (small, head)
    plans = P["plans"]
    kinds, outs = [p.kind for p in plans], [p.outer for p in plans]
    feat = lambda s, i: plans[i].feat(s)

    def meas(rr):
        return [(RK.measure(r["tagged"], kinds, outs, head, feat=feat), n, r) for n, r in enumerate(rr)]
    if o["key"] == "short":
        ms = meas(_coedge_run(P, P["seq"], placed, W, L, head, o, "short"))
    elif o.get("pool"):
        ms = _coedge_pool(P, placed, W, L, head, o, meas)
    else:
        ms = meas(_coedge_run(P, P["seq"], placed, W, L, head, o, "safe", ret=o["ret"]))
    kk = "key0" if o["ret"] else "key"
    m, _, r = min(ms, key=lambda v: (v[0][kk], v[1]))
    polys = [p.poly for p in plans]
    shapes = [s for s, i in r["tagged"]]
    idle, p0 = 0.0, head
    for s in shapes:
        a, b = G.ends(s); idle += D(p0, a); p0 = b
    return dict(seq=r["out"], idle=idle, crossings=crossings(shapes, head), crossings_parts=_part_crossings(r["tagged"], polys, head),
                risk=m, lead_min=None, warnings=r["warnings"], strategy=o["name"])


def _coedge_pool(P, placed, W, L, head, o, meas):
    """Кандидаты листа с общим резом у безопасных стратегий — общие для safe и safe0: проходы по порядкам единиц
    (ближайший сосед, замкнутый обход в обе стороны — без повторов; у последней единицы — лучшая без возврата и лучшая
    с возвратом в ноль, у последней большой группы — ещё и обходы в обратную сторону) и проход «short». Кэш в P."""
    pk = ("pool", bool(o["hole_starts"]), bool(o["look"]))
    if pk not in P:
        seqs = [P["seq"]]
        s0 = _unit_order(P["plans"], P["units"], head, closed=True)
        for s in (s0, s0[::-1]):
            if s not in seqs:
                seqs.append(s)
        rr = []
        for s in seqs:
            rr += _coedge_run(P, s, placed, W, L, head, o, "safe", ret=True)
        rr += _coedge_run(P, P["seq"], placed, W, L, head, o, "short")
        P[pk] = meas(rr)
    return P[pk]


def _coedge_run(P, seq_u, placed, W, L, head, o, mode, ret=False):
    """Один проход по единицам листа с общим резом: mode "short" — ключи как было (+ начала отверстий и «взгляд
    вперёд» по переключателям), "safe" — risk.safe_key по вырезанному к этому моменту. ret (только "safe") — у последней
    единицы ещё и вариант, лучший с возвратом в ноль (у большой группы — и обходы в обратную сторону: конец у нуля).
    Вернуть список проходов [dict(out, tagged, warnings)] — один или два (лучший без возврата, лучший с ним)."""
    from . import coedge as CE
    plans, units = P["plans"], P["units"]
    hs = bool(o["hole_starts"])
    polys = [p.poly for p in plans]
    kinds = [p.kind for p in plans]
    obs = {}
    ret = ret and mode == "safe"
    alt0 = None                           # последняя единица, лучшая с возвратом: (out, tagged) — если не та же

    def ob(i):
        if i not in obs:
            obs[i] = plans[i].ob
        return obs[i]
    out, tagged, warnings, pos = [], [], [], head
    cut_tongues = []                      # язычки всего вырезанного на листе (tongue_polys вырезанного — по мере резки)
    cut_parts = []                        # многоугольники вырезанных деталей
    sheet = RK.Sheet()                    # то же для безопасного ключа: освобождённые по классам и т.д.

    def feat(s, i):
        return plans[i].feat(s)

    def inner_order(inner, h, targets, done=(), after=None, member_of=None, plan=None):
        """Путь по внутренним контурам детали группы от h к одной из точек начала её внешней части: змейка или
        оптимизатор. Как было (short): лучший по (переходы над вырезанными язычками — с учётом уже вырезанного,
        холостой ход); безопасный: по risk.safe_key с вырезанным листа и освобождёнными деталями группы. after(p) —
        «взгляд вперёд» из coedge.build_group: (начало внешней части, ключ ухода к следующей детали, путь туда)."""
        snake = plan.snake if plan is not None else snake_options(inner)
        by_tg = []
        for tg in targets[:24]:
            cs = []
            if snake:
                for o_ in snake:
                    c, where = snake_cost(o_, h, tg)
                    cs.append((c, snake_shapes(o_, where), tg))
            if len(inner) <= EXACT_N or not snake:
                sh, c = plan.order_to(h, tg) if plan is not None else order(inner, h, tg)
                cs.append((c, sh, tg))
            by_tg.append(cs)
        if mode == "short":
            extra = cut_tongues + tongue_polys(list(done))
            if after is None and not hs:          # как было, без изменений
                cands = sorted((v for cs in by_tg for v in cs), key=lambda v: v[0])
                best = None
                for c, sh, tg in cands[:40]:                     # самые короткие — с проверкой язычков
                    x = crossings(sh, h, extra)
                    own = tongue_polys(sh)
                    if sh and _seg_hits(G.ends(sh[-1])[1], tg, extra + own, margin=0.5):
                        x += 1
                    key = (x, c)
                    if best is None or key < best[0]:
                        best = (key, sh)
                sh = best[1]
                return sh, (G.ends(sh[-1])[1] if sh else h)
            if after is None:
                pool = sorted((v for cs in by_tg for v in cs), key=lambda v: v[0])[:40]
            else:
                pool = [v for cs in by_tg for v in sorted(cs, key=lambda v: v[0])[:LOOK_POOL]]
            best = None
            for c, sh, tg in pool:
                if hs:
                    sh2 = choose_starts(sh, h, tg, "short")
                    if sh2 is not sh:
                        sh, c = sh2, path_eval(sh2, h, tg)
                end = G.ends(sh[-1])[1] if sh else h
                x = crossings(sh, h, extra)
                if after is None:
                    dest, xa, ca = tg, (), D(end, tg)
                else:
                    dest, xa, ca = after(end)
                if sh and _seg_hits(end, dest, extra + tongue_polys(sh), margin=0.5):
                    x += 1
                key = (x, xa, path_eval(sh, h, None) + ca)
                if best is None or key < best[0]:
                    best = (key, sh)
            sh = best[1]
            return sh, (G.ends(sh[-1])[1] if sh else h)
        # безопасный: вырезанное к этому моменту — лист + освобождённые детали группы (done — фигуры группы до этой детали)
        extra0, cur = member_of(done)
        ft = plan.feat
        pool = sorted(((c, sh, tg) for cs in by_tg for c, sh, tg in cs), key=lambda v: v[0])
        best = None
        for c, sh, tg in pool[:SAFE_POOL]:
            if best is not None and best[0] <= (0, 0, 0, 0, c - 1e-6):
                break
            if hs:
                sh = choose_starts(sh, h, tg, "safe", ft)
            v, idle, end, ex, own = RK.walk([(s, -1) for s in sh], h, sheet, {}, {}, lambda s, i: ft(s), extra0=extra0)
            if after is None:
                dest, ta, ca = tg, (0, 0, 0, 0), D(end, tg)
            else:
                # уход к следующей детали: (ступени ключа, путь + впритирку); путь — уже с переходом end → dest
                dest, ta, ca = after(end)
            kk = RK.safe_key(RK.vadd(v, RK.move(end, dest, sheet, own, ex)), idle + ca)
            kk = tuple(x + y for x, y in zip(kk[:4], ta)) + kk[4:]
            if best is None or kk < best[0]:
                best = (kk, sh)
        sh = best[1]
        return sh, (G.ends(sh[-1])[1] if sh else h)

    for k in seq_u:
        kind, idx = units[k]
        if kind == "part":
            i = idx[0]
            p = plans[i]
            fr = {c: lead_free(p.started(c), W, L, P["allg"], skip=p.poly) for c in p.cands}
            ok = [c for c in p.cands if fr[c] >= LEAD_FREE] or [max(p.cands, key=lambda c: fr[c])]
            if fr[ok[0]] < LEAD_FREE:
                warnings.append("деталь %s: под подвод свободно только %.1f мм" % (p.part["name"], fr[ok[0]]))
            best = None
            if mode == "short":
                for c in ok:
                    cost, sh, x = p.cost(pos, c, hs)
                    xp = 1 if cut_parts and _seg_hits(pos, G.ends(sh[0])[0], cut_parts) else 0
                    key = (x, xp, cost)
                    if best is None or key < best[0]:
                        best = (key, sh)
            else:
                ev = dict(sheet=sheet, cache={})
                last = ret and k == seq_u[-1]
                if last:                          # возврат в ноль — над этой деталью уже освобождённой
                    ex0 = [(p.kind, p.ob)] + ([f for f in (p.feat(s) for s in p.inner) if f] if p.kind == "mj" else [])
                best0 = None
                for c in ok:
                    b = p.best_safe(pos, c, ev, "safe" if hs else None)
                    if best is None or b[0] < best[0]:
                        best = (b[0], b[3])
                    if last:                      # конец детали — её точка врезки: возврат зависит только от угла c
                        e = G.ends(b[3][-1])[1]
                        k0 = RK.safe_key(RK.vadd(b[1], RK.move(e, head, sheet, (), ex0)), b[2] + D(e, head))
                        if best0 is None or k0 < best0[0]:
                            best0 = (k0, b[3])
                if last and best0[1] is not best[1]:
                    alt0 = (out + [("part", placed[i]["part"], best0[1])], tagged + [(s, i) for s in best0[1]])
            sh = best[1]
            out.append(("part", placed[i]["part"], sh))
            tagged += [(s, i) for s in sh]
            cut_tongues += tongue_polys(sh)
            cut_parts.append(polys[i])
            _commit(sheet, p)
            pos = G.ends(sh[-1])[1]
            continue
        last_unit = ret and k == seq_u[-1]
        outs = {i: plans[i].outer for i in idx}
        split = dict(zip(idx, CE.split_all([outs[i] for i in idx])))
        nb = {i: set() for i in idx}
        for a in idx:
            for b in idx:
                if a < b and CE.shared_length(outs[a]["verts"], outs[b]["verts"]) > 1e-3:
                    nb[a].add(b); nb[b].add(a)

        def build(order_m, h, look):
            members = [dict(outer=plans[i].outer, inner=plans[i].inner) for i in order_m]

            def member_of(done):
                """(освобождённые детали группы — все, чьи фигуры уже в блоке: [(класс, препятствие)] + вырезанное
                деталей с перемычками; номер размещения текущей детали группы)."""
                ms = sorted({s["member"] for s in done if "member" in s})
                ex = [(kinds[order_m[m]], ob(order_m[m])) for m in ms]
                for m in ms:
                    if kinds[order_m[m]] == "mj":
                        ex += [f for f in (feat(s, order_m[m]) for s in plans[order_m[m]].inner) if f]
                return ex, order_m[len(ms)]

            def io(inner, h_, targets, done=(), after=None):
                return inner_order(inner, h_, targets, done, after, member_of, plans[member_of(done)[1]])

            lookf = None
            if look:
                def lookf(e, k_, nxt):
                    """Уход от конца контура детали k_ к ближайшему началу следующей: (ступени ключа, путь)."""
                    q = min(nxt, key=lambda q: D(e, q))
                    if mode == "short":
                        return ((1 if _seg_hits(e, q, cut_parts + [polys[order_m[m]] for m in range(k_ + 1)]) else 0),), D(e, q)
                    ex = [(kinds[order_m[m]], ob(order_m[m])) for m in range(k_ + 1)]
                    v = RK.move(e, q, sheet, (), ex)
                    return (v[RK.TONGUE], v[RK.SMALLP], v[RK.PART], v[RK.HOLE]), D(e, q) + RK.NEAR_COST * v[RK.NEARP]
            try:
                sh, end = CE.build_group(members, head=h, inner_order=io, look=lookf, ref_points=_ref_points,
                                         split=[split[i] for i in order_m], final=[head] if last_unit else None)
            except ValueError:
                return None                       # такой порядок CypCut не строит (нет свободного угла и т.п.)
            tg = [(s, order_m[s["member"]]) for s in sh]
            if mode == "short":
                idle_g, p0 = 0.0, h
                for s in sh:
                    a, b = G.ends(s); idle_g += D(p0, a); p0 = b
                xt = crossings(sh, h, cut_tongues)
                xp = 0
                # переходы над деталями: уже вырезанные на листе + детали группы после своего последнего куска
                last = {}
                for n_, (s, m) in enumerate(tg):
                    last[m] = n_
                done_p, p0 = list(cut_parts), h
                for n_, (s, m) in enumerate(tg):
                    a, b = G.ends(s)
                    if done_p and D(p0, a) > 1.0 and _seg_hits(p0, a, done_p):
                        xp += 1
                    p0 = b
                    if last[m] == n_:
                        done_p.append(polys[m])
                key, key0 = (xt, xp, idle_g), None
            else:
                v, idle_g, _, ex, _ = RK.walk(tg, h, sheet, kinds, {m: ob(m) for m in order_m}, feat)
                key, key0 = RK.safe_key(v, idle_g), None
                if last_unit:                     # с возвратом в ноль — над освобождёнными деталями группы
                    key0 = RK.safe_key(RK.vadd(v, RK.move(end, head, sheet, (), ex)), idle_g + D(end, head))
            return key, sh, end, tuple(order_m), key0

        def grow(start):
            """Соседями по общей кромке от детали start, каждый раз ближайшая к последней вырезанной."""
            done, order_m, cur = {start}, [start], plans[start].center
            while len(done) < len(idx):
                cand = [i for i in idx if i not in done and nb[i] & done] or [i for i in idx if i not in done]
                i = min(cand, key=lambda i: (D(cur, plans[i].center), i))
                done.add(i); order_m.append(i); cur = plans[i].center
            return order_m
        orders = []
        if len(idx) <= GROUP_PERM_MAX:
            orders = [list(p_) for p_ in itertools.permutations(idx)]
        else:
            orders.append(grow(min(idx, key=lambda i: (D(pos, plans[i].center), i))))
            for f in ((lambda b: (b[1], b[0])), (lambda b: (b[1], -b[2])), (lambda b: (-b[3], b[0])), (lambda b: (-b[3], -b[2]))):
                orders.append(grow(min(idx, key=lambda i: (f(plans[i].poly[1]), i))))   # от крайних деталей группы
            rest_, tour, cur = set(idx), [], pos
            while rest_:
                i = min(rest_, key=lambda i: (D(cur, plans[i].center), i)); rest_.remove(i); tour.append(i); cur = plans[i].center
            imp = True
            while imp:
                imp = False
                for a_ in range(len(tour) - 1):
                    for b_ in range(a_ + 1, len(tour)):
                        pa = plans[tour[a_ - 1]].center if a_ else pos
                        nx = plans[tour[b_ + 1]].center if b_ + 1 < len(tour) else None
                        old_ = D(pa, plans[tour[a_]].center) + (D(plans[tour[b_]].center, nx) if nx else 0)
                        new_ = D(pa, plans[tour[b_]].center) + (D(plans[tour[a_]].center, nx) if nx else 0)
                        if new_ < old_ - 1e-9:
                            tour[a_:b_ + 1] = tour[a_:b_ + 1][::-1]; imp = True
            orders.append(tour)
            for axis in (0, 1):
                band = max(1.0, min(plans[i].poly[1][2 + (1 - axis)] - plans[i].poly[1][1 - axis] for i in idx))
                rows = collections.defaultdict(list)
                for i in idx:
                    rows[int(plans[i].center[1 - axis] // band)].append(i)
                o_, flip = [], False
                for key_ in sorted(rows):
                    o_ += sorted(rows[key_], key=lambda i: plans[i].center[axis], reverse=flip); flip = not flip
                orders.append(o_)
        looks = (False, True) if o["look"] else (False,)
        builds = [(o_, lk) for o_ in orders for lk in looks]
        if last_unit and len(idx) > GROUP_PERM_MAX:       # конец у нуля: те же обходы в обратную сторону — со «взглядом
            builds += [(o_[::-1], looks[-1]) for o_ in orders]   # вперёд» (он и выбирает конец блока по возврату)
        cands = [c for c in (build(o_, pos, lk) for o_, lk in builds) if c is not None]
        if not cands:
            raise CoedgeRouteError("группу из %d деталей не удалось разрезать общим резом ни одним порядком" % len(idx))
        _, sh, end_, perm, _ = min(cands, key=lambda v: (v[0], v[3]))
        if last_unit:
            _, sh0, _, perm0, _ = min(cands, key=lambda v: (v[4], v[3]))
            if sh0 is not sh:
                alt0 = (out + [("group", [placed[i]["part"] for i in perm0], sh0)], tagged + [(s, perm0[s["member"]]) for s in sh0])
        pos = end_
        out.append(("group", [placed[i]["part"] for i in perm], sh))
        tagged += [(s, perm[s["member"]]) for s in sh]
        cut_tongues += tongue_polys(sh)
        cut_parts += [polys[i] for i in perm]
        for i in perm:
            _commit(sheet, plans[i])
    res = [dict(out=out, tagged=tagged, warnings=warnings)]
    if alt0 is not None:
        res.append(dict(out=alt0[0], tagged=alt0[1], warnings=warnings))
    return res
