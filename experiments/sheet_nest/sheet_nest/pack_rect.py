# -*- coding: utf-8 -*-
"""Прямоугольный раскрой листа по габаритам деталей (см. DESIGN.md, раздел «pack_rect.py»).

    pack_rect(items, W, L, gap, edge, rotations=(0, 90), node_limit=2_000_000) -> dict

items: [{"id", "w", "h", "qty"}] — габарит детали при повороте 0 (w — вдоль X листа, h — вдоль Y).
Лист: X 0…W, Y 0…L; рабочее поле [edge, W−edge]×[edge, L−edge]; между габаритами ≥ gap.
Поворот 90 — деталь занимает h по X и w по Y (180/270 дают тот же габарит, что 0/90).

Результат: {"sheets": [[{"id", "rot", "x", "y", "w", "h"}]], "lower_bound", "optimal", "method", "proof"};
x, y — левый нижний угол повёрнутого габарита, w, h — его размеры по X и по Y.

Два режима:
  • «одна полоса на лист» — никакие две детали не встают рядом поперёк X (или, симметрично, вдоль Y):
    каждый лист — столбик деталей, задача = одномерная упаковка, решается ТОЧНО. Нижние границы:
    L2 Мартелло–Тота, двойственно-допустимые функции Фекете–Шеперса, линейная релаксация
    Гилмора–Гомори (генерация столбцов, оценка Фарли). Верхняя оценка — лучшая из FFD, BFD, MBS′ и
    округления LP; если она выше границы — перебор bin completion (Корф) по ТИПАМ деталей (одинаковые
    длины взаимозаменяемы — считаем количества, без симметрии), с отсечением по границам, отходу и
    запоминанием проигранных состояний; предел узлов node_limit (не хватило — лучшее найденное, optimal False).
  • общий случай — двухэтапный гильотинный раскрой: полосы вдоль Y (ширина — по X) заполняются рюкзаком
    по длине (ряды одинаковых деталей поперёк полосы; веса рядов в целых единицах, делятся на общий
    делитель, при огрублении — точная доливка остатка, так что ровно нарезанная сетка заготовок не теряет
    ряд), полосы раскладываются по листам точной одномерной упаковкой ширин. Затем последние листы
    разбираются: их детали в любых поворотах идут рядами в свободные концы полос и новыми полосами
    в свободную ширину остальных листов — так в листе сходятся полосы разной ориентации. То же в обратной
    ориентации (полосы вдоль X) и при разных правилах поворота; берётся лучший вариант (листов меньше,
    затем больше свободный хвост последнего листа); вариант, равный нижней границе, — сразу итог.
Всё детерминировано: ни случайности, ни ограничений по времени (пределы работы — в узлах и ячейках).
"""
import math

import numpy as np

__all__ = ["pack_rect"]

_TOL = 1e-6
_DFF_K = (2, 3, 4, 5)


# --------------------------------------------------------------------------- единицы

class _Q(object):
    """Перевод мм в целые единицы. Размеры округляются вверх, ёмкости — вниз: раскладка по целым
    единицам никогда не даёт нахлёста в настоящих миллиметрах. Если все размеры кратны единице
    (1, 0,5, 0,1 … 0,001 мм) — перевод точный (exact)."""

    UNITS = (1.0, 0.5, 0.1, 0.05, 0.01, 0.005, 0.001)

    def __init__(self, values):
        for u in self.UNITS:
            # положительный размер меньше единицы (пылинка) точным не считается — нужна единица мельче
            if all(abs(v / u - round(v / u)) <= 1e-6 and (v <= 0 or round(v / u) >= 1) for v in values):
                self.u, self.exact = u, True
                break
        else:
            self.u, self.exact = 0.001, False

    def up(self, v):
        """Вверх; положительный размер — не меньше одной единицы (иначе пылинка 1e-9 мм стала бы нулём)."""
        q = int(math.ceil(v / self.u - _TOL))
        return q if q > 0 or v <= 0 else 1

    def down(self, v):
        return int(math.floor(v / self.u + _TOL))


def _f(v):
    """Число для текста: без лишних нулей."""
    return ("%.3f" % v).rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- одномерные границы

def _merge(entries):
    """[(размер, кол-во)] → размеры по убыванию без повторов и их количества. Нулевые размеры
    отбрасываются (для нижней границы это допустимо: без деталей граница не выше)."""
    acc = {}
    for s, c in entries:
        if c > 0 and s > 0:
            acc[s] = acc.get(s, 0) + c
    sizes = sorted(acc, reverse=True)
    return sizes, [acc[s] for s in sizes]


def _l2(sizes, counts, C):
    """Граница L2 Мартелло–Тота. sizes — по убыванию (целые), C — ёмкость."""
    act = [(s, c) for s, c in zip(sizes, counts) if c]
    if not act:
        return 0
    n = len(act)
    pc, ps = [0], [0]
    for s, c in act:
        pc.append(pc[-1] + c)
        ps.append(ps[-1] + s * c)
    best = -(-ps[n] // C)
    h = 0
    while h < n and 2 * act[h][0] > C:
        h += 1
    # пороги k: 0 и все размеры ≤ C/2 по возрастанию
    ks = [(0, n)] + [(act[j][0], j + 1) for j in range(n - 1, h - 1, -1)]
    i1 = 0
    for k, j in ks:
        while i1 < h and act[i1][0] > C - k:
            i1 += 1
        n1 = pc[i1]
        n2 = pc[h] - pc[i1]
        s2 = ps[h] - ps[i1]
        s3 = ps[j] - ps[h]
        extra = s3 - (n2 * C - s2)
        val = n1 + n2 + (-(-extra // C) if extra > 0 else 0)
        if val > best:
            best = val
    return best


def _dff_num(s, C, k):
    """Числитель функции Фекете–Шеперса u^(k) при знаменателе k·C (целочисленно)."""
    q = (k + 1) * s
    if q % C == 0:
        return k * s
    return (q // C) * C


def _dff_bound(sizes, counts, C, ks=(2, 3, 4, 5, 6, 7, 8, 9, 10)):
    best, bk = 0, None
    for k in ks:
        num = sum(_dff_num(s, C, k) * c for s, c in zip(sizes, counts))
        v = -(-num // (k * C))
        if v > best:
            best, bk = v, k
    return best, bk


def _knap_max(p, sizes, ub, C, node_cap):
    """max Σ p_t·x_t при Σ s_t·x_t ≤ C, 0 ≤ x_t ≤ ub_t: при умеренной ёмкости — точная динамика по ёмкости
    (numpy), иначе ветви и границы. Возвращает (значение, x, работа); значение None — предел узлов.
    Работа — в «узлах»: узел перебора или ~1000 ячеек динамики (для детерминированного предела)."""
    idx = [t for t in range(len(sizes)) if p[t] > 1e-12 and ub[t] > 0]
    units = []
    for t in idx:
        left, k = min(ub[t], C // sizes[t]), 1
        while left > 0:
            m = min(k, left)
            units.append((m * sizes[t], m * float(p[t]), t, m))
            left -= m
            k *= 2
    if C <= 200000 and len(units) * (C + 1) <= 30000000:
        dp = np.zeros(C + 1)
        keeps = []
        for w, v, _, _ in units:
            cand = dp[:C + 1 - w] + v
            mask = cand > dp[w:] + 1e-12
            if mask.any():
                dp[w:] = np.where(mask, cand, dp[w:])
            keeps.append(mask)
        x = np.zeros(len(sizes))
        c = C
        for q in range(len(units) - 1, -1, -1):
            w, _, t, m = units[q]
            if c >= w and keeps[q][c - w]:
                x[t] += m
                c -= w
        return float(dp[C]), x, len(units) * (1 + C // 1000)
    idx.sort(key=lambda t: (-p[t] / sizes[t], t))
    n = len(idx)
    S = [sizes[t] for t in idx]
    P = [float(p[t]) for t in idx]
    U = [ub[t] for t in idx]
    cur = [0] * n
    st = {"best": 0.0, "x": [0] * n, "nodes": 0}

    def bound(j, cap):
        v = 0.0
        for q in range(j, n):
            w = U[q] * S[q]
            if w <= cap:
                v += U[q] * P[q]
                cap -= w
            else:
                v += P[q] * cap / S[q]
                break
        return v

    def rec(j, cap, val):
        st["nodes"] += 1
        if st["nodes"] > node_cap:
            raise _Abort()
        if val > st["best"] + 1e-12:
            st["best"] = val
            st["x"] = list(cur)
        if j == n or val + bound(j, cap) <= st["best"] + 1e-12:
            return
        top = min(U[j], cap // S[j])
        for m in range(top, -1, -1):
            cur[j] = m
            rec(j + 1, cap - m * S[j], val + m * P[j])
        cur[j] = 0

    try:
        rec(0, C, 0.0)
    except _Abort:
        return None, None, st["nodes"]
    x = np.zeros(len(sizes))
    for q, t in enumerate(idx):
        x[t] = st["x"][q]
    return st["best"], x, st["nodes"]


class _Abort(Exception):
    pass


def _lp_bound(sizes, counts, C, max_iter=None, knap_nodes=200000, total_knap_nodes=1500000, primal=False):
    """Граница Гилмора–Гомори: линейная релаксация по раскройным схемам (генерация столбцов,
    модифицированный симплекс). На каждом шаге — оценка Фарли c·π⁺ / max(1, max_a a·π⁺): она верна при
    любом π, поэтому граница корректна и без сходимости. Возвращает (целая граница, значение);
    primal=True — ещё дробное покрытие [(схема, λ)] последнего базиса (для округления), работа и итерации.
    Работа ограничена числом итераций (по умолчанию 300 + 20·типов) и суммарной работой total_knap_nodes:
    узлы рюкзака, ячейки динамики (÷1000) и решение систем на каждой итерации (~типов³/2000) —
    детерминированно, без часов."""
    T = len(sizes)
    if T == 0:
        return (0, 0.0, [], 0, 0) if primal else (0, 0.0)
    it_cost = 1 + T * T * T // 2000
    if max_iter is None:
        max_iter = 300 + 20 * T
    cnt = np.array(counts, dtype=float)
    ub = [min(counts[t], C // sizes[t]) for t in range(T)]
    cols = []
    for t in range(T):
        a = np.zeros(T)
        a[t] = ub[t]
        cols.append(a)
    eye = np.eye(T)
    basis = list(range(T))  # ≥ 0 — схема из cols, < 0 — избыток −(t+1)

    def col(j):
        return cols[j] if j >= 0 else -eye[-j - 1]

    best, best_val = 0, 0.0
    spent = iters = 0
    for _ in range(max_iter):
        if spent >= total_knap_nodes:
            break
        spent += it_cost
        iters += 1
        B = np.column_stack([col(j) for j in basis])
        cB = np.array([1.0 if j >= 0 else 0.0 for j in basis])
        try:
            pi = np.linalg.solve(B.T, cB)
            xB = np.linalg.solve(B, cnt)
        except np.linalg.LinAlgError:
            break
        pip = np.maximum(pi, 0.0)
        val, pat, used = _knap_max(pip, sizes, ub, C, max(0, min(knap_nodes, total_knap_nodes - spent)))
        spent += used
        if val is None:
            break
        z = float(cnt @ pip) / max(val, 1.0)
        if z > best_val:
            best_val = z
            best = max(best, int(math.ceil(z - 1e-6)))
        enter = None
        for t in range(T):
            if pi[t] < -1e-9 and -(t + 1) not in basis:
                enter = -(t + 1)
                break
        if enter is None:
            if val <= 1.0 + 1e-9:
                break
            cols.append(pat)
            enter = len(cols) - 1
        d = np.linalg.solve(B, col(enter))
        r_idx, rmin = None, None
        for r in range(T):
            if d[r] > 1e-10:
                ratio = max(xB[r], 0.0) / d[r]
                if rmin is None or ratio < rmin - 1e-12 or (abs(ratio - rmin) <= 1e-12 and basis[r] < basis[r_idx]):
                    r_idx, rmin = r, ratio
        if r_idx is None:
            break
        basis[r_idx] = enter
    if not primal:
        return best, best_val
    prim = []
    try:
        xB = np.linalg.solve(np.column_stack([col(j) for j in basis]), cnt)
    except np.linalg.LinAlgError:
        return best, best_val, prim, spent, iters
    for r, j in enumerate(basis):
        if j >= 0 and xB[r] > 1e-9:
            prim.append((tuple(int(round(v)) for v in cols[j]), float(xB[r])))
    return best, best_val, prim, spent, iters


def _lp_dive(sizes, counts, C, rounds=60, iters=4000, budget=1500000):
    """Округление линейной релаксации («ныряние»): решить LP по остатку, взять ⌊λ⌋ копий каждой схемы
    (если все λ < 1 — одну копию схемы с наибольшим λ), повторить; хвост — FFD. Сильная эвристика для
    немногих типов с большими количествами. Работа ограничена числом шагов, суммарным числом итераций
    симплекса и суммарной работой (см. _lp_bound; детерминированно)."""
    T = len(sizes)
    res = list(counts)
    bins = []
    spent = done = 0
    for _ in range(rounds):
        act = [t for t in range(T) if res[t] > 0]
        if not act or spent >= budget or done >= iters:
            break
        sub_s = [sizes[t] for t in act]
        sub_c = [res[t] for t in act]
        _, _, prim, used, it = _lp_bound(sub_s, sub_c, C, max_iter=min(300 + 20 * len(act), iters - done),
                                         total_knap_nodes=budget - spent, primal=True)
        spent += used
        done += it
        if not prim:
            break
        prim.sort(key=lambda p: (-p[1], tuple(-x for x in p[0])))
        picks = [(a, int(math.floor(lam + 1e-9))) for a, lam in prim if lam >= 1 - 1e-9]
        if not picks:
            picks = [(prim[0][0], 1)]
        for a, k in picks:
            for _ in range(k):
                b = {}
                for q, m in enumerate(a):
                    t = act[q]
                    m = min(m, res[t])
                    if m > 0:
                        b[t] = m
                        res[t] -= m
                if b:
                    bins.append(b)
    if any(res):
        bins.extend(_ffd(sizes, res, C))
    return bins


def _lb_1d(sizes, counts, C, lp=True):
    """Нижние границы одномерной упаковки: {"L1", "L2", "DFF", "LP"} и максимум."""
    parts = {}
    tot = sum(s * c for s, c in zip(sizes, counts))
    parts["L1"] = -(-tot // C) if tot else 0
    parts["L2"] = _l2(sizes, counts, C)
    parts["DFF"] = _dff_bound(sizes, counts, C)[0]
    lb = max(parts.values())
    if lp and len(sizes) <= 150:
        v, z = _lp_bound(sizes, counts, C)
        if v > 0:  # 0 — релаксацию решить не удалось (пределы), границы нет
            parts["LP"], parts["LPz"] = v, z
            lb = max(lb, v)
    return lb, parts


def _bounds_text(parts):
    s = "L1 (длина) = %d, L2 (Мартелло–Тот) = %d, DFF (Фекете–Шеперс) = %d" % (
        parts["L1"], parts["L2"], parts["DFF"])
    if "LP" in parts:
        s += ", LP (Гилмор–Гомори) = %d (%.4f)" % (parts["LP"], parts["LPz"])
    return s


# --------------------------------------------------------------------------- одномерные эвристики

def _ffd(sizes, counts, C, best_fit=False):
    free, bins = [], []
    for t, s in enumerate(sizes):
        for _ in range(counts[t]):
            jb = None
            for j in range(len(free)):
                if free[j] >= s:
                    if not best_fit:
                        jb = j
                        break
                    if jb is None or free[j] < free[jb]:
                        jb = j
            if jb is None:
                free.append(C - s)
                bins.append({t: 1})
            else:
                free[jb] -= s
                bins[jb][t] = bins[jb].get(t, 0) + 1
    return bins


def _max_fill(sizes, counts, start, r, node_cap):
    """Набор из оставшихся деталей (типы ≥ start) с наибольшей суммой ≤ r."""
    act = [t for t in range(start, len(sizes)) if counts[t] > 0 and sizes[t] <= r]
    n = len(act)
    suf = [0] * (n + 1)
    for p in range(n - 1, -1, -1):
        suf[p] = suf[p + 1] + sizes[act[p]] * counts[act[p]]
    st = {"best": 0, "set": [], "nodes": 0}
    cur = []

    def rec(p, rr, val):
        st["nodes"] += 1
        if val > st["best"]:
            st["best"] = val
            st["set"] = list(cur)
        if p == n or st["best"] == r or st["nodes"] > node_cap or val + min(rr, suf[p]) <= st["best"]:
            return
        t = act[p]
        s = sizes[t]
        for m in range(min(counts[t], rr // s), -1, -1):
            if m:
                cur.append((t, m))
            rec(p + 1, rr - m * s, val + m * s)
            if m:
                cur.pop()
            if st["best"] == r or st["nodes"] > node_cap:
                return

    rec(0, r, 0)
    return st["set"]


def _mbs(sizes, counts, C, node_cap=3000):
    """MBS′ (Флешар–Хинди): лист за листом — крупнейшая деталь + наилучшее дополнение."""
    cnt = list(counts)
    bins = []
    i, T = 0, len(sizes)
    while True:
        while i < T and cnt[i] == 0:
            i += 1
        if i == T:
            break
        cnt[i] -= 1
        b = {i: 1}
        for t, m in _max_fill(sizes, cnt, i, C - sizes[i], node_cap):
            b[t] = b.get(t, 0) + m
            cnt[t] -= m
        bins.append(b)
    return bins


# --------------------------------------------------------------------------- точный перебор

def _completions(sizes, cnt, i, r, waste_cap, max_out, max_steps):
    """Все МАКСИМАЛЬНЫЕ дополнения листа (после крупнейшей детали типа i) с отходом ≤ waste_cap.
    Возвращает (список (отход, ((тип, кол-во), …)), шагов, обрезано ли)."""
    T = len(sizes)
    act = [j for j in range(i, T) if cnt[j] > 0]
    n = len(act)
    suf = [0] * (n + 1)
    for p in range(n - 1, -1, -1):
        suf[p] = suf[p + 1] + sizes[act[p]] * cnt[act[p]]
    out = []
    choose = [0] * n
    st = {"steps": 0, "trunc": False}
    big = 1 << 62

    def rec(p, rr, min_unused):
        st["steps"] += 1
        if st["trunc"]:
            return
        if st["steps"] > max_steps:
            st["trunc"] = True
            return
        need = rr - waste_cap
        if rr - min_unused + 1 > need:
            need = rr - min_unused + 1
        if need > suf[p]:
            return
        if p == n:
            out.append((rr, tuple((act[q], choose[q]) for q in range(n) if choose[q])))
            if len(out) >= max_out:
                st["trunc"] = True
            return
        j = act[p]
        s = sizes[j]
        c = cnt[j]
        for m in range(min(c, rr // s), -1, -1):
            choose[p] = m
            rec(p + 1, rr - m * s, s if m < c else min_unused)
            if st["trunc"]:
                break
        choose[p] = 0

    rec(0, r, big)
    out.sort()
    return out, st["steps"], st["trunc"]


def _bin_completion(sizes, counts, C, target, budget, memo_cap=400000, comp_cap=3000, step_cap=200000):
    """Bin completion (Корф) по типам: ищет раскладку не больше чем в target листов. Лист открывается
    крупнейшей оставшейся деталью, дополнения — только максимальные, от лучшего (меньше отход) к худшему.
    Отсечения: L1, L2, функции Фекете–Шеперса по остатку, суммарный отход, запомненные проигрышные состояния.
    Возвращает (листы | None, узлов, статус): "found", "infeasible" (доказано — нельзя), "truncated" (не нашли,
    но перебор дополнений был урезан — не доказательство), "budget" (исчерпан предел узлов)."""
    T = len(sizes)
    cnt = list(counts)
    rem = sum(s * c for s, c in zip(sizes, cnt))
    max_waste = target * C - rem
    if max_waste < 0:
        return None, 0, "infeasible"
    F = [[_dff_num(s, C, k) for s in sizes] for k in _DFF_K]
    D = [k * C for k in _DFF_K]
    sumF = [sum(f[t] * cnt[t] for t in range(T)) for f in F]
    nk = len(_DFF_K)
    st = {"rem": rem, "nodes": 0, "trunc": False}
    failed = {}  # состояние (остаток по типам) → число листов, с которым из него не вышло

    def apply(t, m):
        cnt[t] -= m
        st["rem"] -= m * sizes[t]
        for q in range(nk):
            sumF[q] -= m * F[q][t]

    def expand(bins_used, waste_used):
        st["nodes"] += 1
        if st["rem"] == 0:
            return "done"
        left = target - bins_used
        if st["rem"] > left * C:
            return None
        for q in range(nk):
            if sumF[q] > left * D[q]:
                return None
        if _l2(sizes, cnt, C) > left:
            return None
        key = tuple(cnt)
        f = failed.get(key)
        if f is not None and f <= bins_used:
            return None
        i = 0
        while cnt[i] == 0:
            i += 1
        apply(i, 1)
        comps, steps, tr = _completions(sizes, cnt, i, C - sizes[i], max_waste - waste_used, comp_cap, step_cap)
        apply(i, -1)
        st["nodes"] += steps
        if tr:
            st["trunc"] = True
        return [i, comps, 0, key, bins_used, waste_used]

    def unapply(i, comp):
        apply(i, -1)
        for t, m in comp:
            apply(t, -m)

    root = expand(0, 0)
    if root == "done":
        return [], st["nodes"], "found"
    stack = [] if root is None else [root]
    applied = []
    while stack:
        if st["nodes"] > budget:
            return None, st["nodes"], "budget"
        fr = stack[-1]
        i, comps, idx, key, bu, wu = fr
        if idx >= len(comps):
            if len(failed) < memo_cap:
                failed[key] = bu
            stack.pop()
            if applied:
                unapply(*applied.pop())
            continue
        fr[2] = idx + 1
        waste, comp = comps[idx]
        apply(i, 1)
        for t, m in comp:
            apply(t, m)
        applied.append((i, comp))
        ch = expand(bu + 1, wu + waste)
        if ch == "done":
            bins = []
            for pi, pc in applied:
                b = {pi: 1}
                for t, m in pc:
                    b[t] = b.get(t, 0) + m
                bins.append(b)
            return bins, st["nodes"], "found"
        if ch is None:
            unapply(*applied.pop())
            continue
        stack.append(ch)
    return None, st["nodes"], ("truncated" if st["trunc"] else "infeasible")


def _consolidate(bins, sizes, C):
    """Листы по убыванию загрузки; из последнего (наименее загруженного) детали переносятся в свободные
    остатки других листов — отход собирается в один хвост на последнем листе."""
    def load(b):
        return sum(sizes[t] * m for t, m in b.items())

    bins = [dict(b) for b in bins]
    bins.sort(key=lambda b: -load(b))
    if len(bins) < 2:
        return bins
    loads = [load(b) for b in bins]
    last = bins[-1]
    moved = True
    while moved and last:
        moved = False
        for t in sorted(last, key=lambda t: (-sizes[t], t)):
            s = sizes[t]
            jb = None
            for j in range(len(bins) - 1):
                if C - loads[j] >= s and (jb is None or loads[j] > loads[jb]):
                    jb = j
            if jb is not None:
                bins[jb][t] = bins[jb].get(t, 0) + 1
                loads[jb] += s
                last[t] -= 1
                loads[-1] -= s
                if last[t] == 0:
                    del last[t]
                moved = True
                break
    if not last:
        bins.pop()
    bins.sort(key=lambda b: -load(b))
    return bins


def _coarse_dive(sizes, counts, C, lp_cap, budget):
    """Округление LP (_lp_dive) при большой ёмкости — на огрублённых размерах: ⌈s/m⌉ (не больше ⌊C/m⌋),
    ёмкость ⌊C/m⌋. Σ⌈s/m⌉ ≤ ⌊C/m⌋ ⇒ Σs ≤ C, так что листы годятся и для точных размеров."""
    if not lp_cap or C <= lp_cap:
        return _lp_dive(sizes, counts, C, budget=budget)
    m = -(-C // lp_cap)
    Cc = C // m
    groups = {}
    for t, x in enumerate(sizes):
        groups.setdefault(min(-(-x // m), Cc), []).append(t)
    csz = sorted(groups, reverse=True)
    ccnt = [sum(counts[t] for t in groups[x]) for x in csz]
    left = list(counts)
    bins = []
    for cb in _lp_dive(csz, ccnt, Cc, budget=budget):
        b = {}
        for ct, k in cb.items():
            for t in groups[csz[ct]]:
                if k == 0:
                    break
                q = min(k, left[t])
                if q:
                    b[t] = b.get(t, 0) + q
                    left[t] -= q
                    k -= q
        if b:
            bins.append(b)
    return bins


def _bpp(entries, C, node_limit, lb_entries=None, lb_C=None, use_lp=True, exact=True, dive_types=60,
         lp_cap=None, lp_budget=1500000, lp_types=150):
    """Одномерная упаковка (точно, с пределом узлов).
    entries: [(размер, кол-во)] — целые размеры ≤ C, индекс записи = исходный индекс.
    lb_entries/lb_C — те же размеры, округлённые для НИЖНЕЙ границы (по умолчанию = entries);
    dive_types — до скольких разных размеров пробовать округление LP (оно решает LP на каждом шаге);
    lp_types — до скольких разных размеров считать границу LP;
    lp_cap — наибольшая ёмкость для LP: при большей размеры огрубляются (для границы — вниз, для округления —
    вверх, ёмкость вниз; обе стороны остаются допустимыми); lp_budget — предел работы LP (см. _lp_bound).
    Возвращает {"bins": [{исх. индекс: кол-во}], "lb", "optimal", "nodes", "notes", "ub_heur"}."""
    pools = {}
    for i, (s, c) in enumerate(entries):
        if c > 0:
            if s > C:
                raise ValueError("внутренняя ошибка: размер %d больше ёмкости %d" % (s, C))
            pools.setdefault(s, []).append([i, c])
    sizes, counts = _merge(entries)
    notes = []
    if not sizes:
        return {"bins": [], "lb": 0, "optimal": True, "nodes": 0, "notes": notes, "ub_heur": 0}
    if lb_entries is None:
        lsz, lct, lC = sizes, counts, C
    else:
        lsz, lct = _merge(lb_entries)
        lC = lb_C
    lb, parts = _lb_1d(lsz, lct, lC, lp=False)
    heur = [("FFD", _ffd(sizes, counts, C)), ("BFD", _ffd(sizes, counts, C, best_fit=True)),
            ("MBS", _mbs(sizes, counts, C))]
    best = min(heur, key=lambda x: len(x[1]))[1]
    ub = ub_heur = len(best)
    if ub > lb and use_lp and len(lsz) <= lp_types:
        s2, c2, C2 = lsz, lct, lC
        if lp_cap and lC > lp_cap:
            # Σ⌊s/m⌋ ≤ ⌊C/m⌋ для любого допустимого листа — граница по огрублённым размерам верна
            m = -(-lC // lp_cap)
            s2, c2 = _merge([(x // m, c) for x, c in zip(lsz, lct)])
            C2 = lC // m
        v, z = _lp_bound(s2, c2, C2, total_knap_nodes=lp_budget)
        if v > 0:  # 0 — релаксацию решить не удалось (пределы), границы нет
            parts["LP"], parts["LPz"] = v, z
            lb = max(lb, v)
    if ub > lb and use_lp and len(sizes) <= dive_types:
        dive = _coarse_dive(sizes, counts, C, lp_cap, lp_budget)
        heur.append(("LP-округление", dive))
        if len(dive) < ub:
            best, ub = dive, len(dive)
    notes.append("Нижние границы: " + _bounds_text(parts) + " → %d." % lb)
    notes.append("Эвристики: " + ", ".join("%s %d" % (nm, len(b)) for nm, b in heur) + ".")
    optimal = ub <= lb
    nodes = 0
    if not optimal:
        # цели lb, lb+1, … ub−1; каждой — половина оставшегося предела (последней — весь остаток), чтобы при
        # трудной нижней цели перебор всё равно попробовал улучшить эвристику на следующих
        proven = True  # все цели ниже текущей доказанно недостижимы
        t = lb
        while t < ub:
            remaining = node_limit - nodes
            if remaining <= 0:
                proven = False
                notes.append("Перебор: предел %d узлов исчерпан — минимум не доказан." % node_limit)
                break
            share = remaining if t == ub - 1 else max(1, remaining // 2)
            sol, used, status = _bin_completion(sizes, counts, C, t, share)
            nodes += used
            if status == "found":
                best, ub = sol, len(sol)
                optimal = proven
                notes.append("Перебор bin completion: найдена раскладка в %d листов (%d узлов)%s." % (
                    ub, nodes, "" if optimal else ", минимум не доказан"))
                break
            if status == "infeasible" and exact:
                # полный перебор: в t листов нельзя — значит, и в меньшее число тоже
                lb = max(lb, t + 1)
                proven = True
                notes.append("Перебор доказал: в %d листов не уложить (%d узлов) → граница %d." % (t, nodes, lb))
            elif status == "budget":
                proven = False
                notes.append("Перебор: на цели %d листов исчерпана доля предела (%d узлов)." % (t, share))
            elif status == "infeasible":
                proven = False
                notes.append("Перебор: в %d листов не уложить при размерах, округлённых с запасом, — для точных "
                             "размеров не доказательство." % t)
            else:
                proven = False
                notes.append("Перебор на %d листов урезан (слишком много вариантов дополнения) — не доказательство."
                             % t)
            t += 1
        else:
            optimal = proven and ub <= lb
    best = _consolidate(best, sizes, C)
    # распределение по исходным записям
    left = {s: [list(x) for x in v] for s, v in pools.items()}
    out = []
    for b in best:
        ob = {}
        for t in sorted(b):
            m = b[t]
            pool = left[sizes[t]]
            while m:
                e = pool[0]
                k = min(m, e[1])
                ob[e[0]] = ob.get(e[0], 0) + k
                e[1] -= k
                m -= k
                if e[1] == 0:
                    pool.pop(0)
        out.append(ob)
    return {"bins": out, "lb": lb, "optimal": bool(optimal) or len(out) <= lb,
            "nodes": nodes, "notes": notes, "ub_heur": ub_heur}


# --------------------------------------------------------------------------- подготовка

def _norm_rotations(rotations):
    rots, seen = [], set()
    for r in rotations:
        try:
            rf = float(r)
        except (TypeError, ValueError):
            raise ValueError("Поворот %r: нужно число градусов, кратное 90" % (r,))
        if not math.isfinite(rf) or abs(rf / 90.0 - round(rf / 90.0)) > 1e-9:
            raise ValueError("Поворот %r° не кратен 90" % (r,))
        ri = int(round(rf)) % 360
        par = (ri // 90) % 2
        if par not in seen:
            seen.add(par)
            rots.append((ri, par))
    if not rots:
        raise ValueError("Не задано ни одного допустимого поворота")
    return rots


def _frame(types, rots, Wf, Lf, gap, Q, transposed):
    """Ориентации деталей в системе «поперёк (a) × вдоль (b)». transposed — полосы вдоль X исходного листа
    (оси меняются местами)."""
    Wg, Lg = Q.down(Wf + gap), Q.down(Lf + gap)
    out = []
    for ti, t in enumerate(types):
        ors, seen = [], set()
        for rot, par in rots:
            if (par == 0) != transposed:
                a, b = t["w"], t["h"]
            else:
                a, b = t["h"], t["w"]
            if Q.up(a + gap) <= Wg and Q.up(b + gap) <= Lg and (a, b) not in seen:
                seen.add((a, b))
                ors.append((rot, a, b))
        out.append({"t": ti, "qty": t["qty"], "orients": ors})
    return out


def _column_set(ft, Wf, gap):
    """Детали, никакие две из которых не встают рядом поперёк: [(индекс в ft, кол-во)], все ли это детали,
    и две самые узкие поперёк (для текста)."""
    amin = [min(a for _, a, _ in x["orients"]) for x in ft]
    big = [(i, ft[i]["qty"]) for i in range(len(ft)) if 2 * amin[i] + gap > Wf + 1e-9]
    total = sum(x["qty"] for x in ft)
    if not big:
        return None
    nb = sum(c for _, c in big)
    amin_big = min(amin[i] for i, _ in big)
    extra = [i for i in range(len(ft)) if 2 * amin[i] + gap <= Wf + 1e-9 and amin[i] + amin_big + gap > Wf + 1e-9]
    if extra:
        bmin = lambda i: min(b for _, _, b in ft[i]["orients"])
        e = max(extra, key=lambda i: (bmin(i), -i))
        big.append((e, 1))
        nb += 1
    phys = sorted(a for i, x in enumerate(ft) for a in [amin[i]] * min(x["qty"], 2))[:2]
    return big, nb == total, phys


# --------------------------------------------------------------------------- одна полоса на лист (точно)

def _solve_columns(ft, Wf, Lf, gap, edge, Q, node_limit):
    """Лист = один столбик вдоль b. Возвращает (листы в системе ft, результат _bpp)."""
    lens = []
    for x in ft:
        o = min(x["orients"], key=lambda o: (o[2], x["orients"].index(o)))
        lens.append(o)
    entries = [(Q.up(o[2] + gap), x["qty"]) for o, x in zip(lens, ft)]
    lb_entries = [(Q.down(o[2] + gap), x["qty"]) for o, x in zip(lens, ft)]
    res = _bpp(entries, Q.down(Lf + gap), node_limit, lb_entries=lb_entries, lb_C=Q.up(Lf + gap),
               use_lp=True, exact=Q.exact)
    sheets = []
    for b in res["bins"]:
        seq = []
        for i in sorted(b, key=lambda i: (-lens[i][2], i)):
            seq.extend([i] * b[i])
        y = edge
        pl = []
        for i in seq:
            rot, a, bb = lens[i]
            pl.append((ft[i]["t"], rot, edge, y, a, bb))
            y += bb + gap
        sheets.append(pl)
    return sheets, res


# --------------------------------------------------------------------------- общий случай: двухэтапный

def _pick(orients, mode):
    if mode == "wide":
        return min(orients, key=lambda o: (-o[1], o[2], orients.index(o)))
    if mode == "narrow":
        return min(orients, key=lambda o: (o[1], o[2], orients.index(o)))
    want = 0 if mode == "r0" else 1
    for o in orients:
        if (o[0] // 90) % 2 == want:
            return o
    return orients[0]


def _fill_orient(orients, open_o, WSg, gap, Q, mode):
    best = None
    for o in orients:
        rot, a, b = o
        if mode == "fixed" and o != open_o:
            continue
        Ag = Q.up(a + gap)
        if Ag > WSg:
            continue
        k = WSg // Ag
        key = (-(k * a * b / (b + gap)), o != open_o, b, orients.index(o))
        if best is None or key < best[0]:
            best = (key, (rot, a, b, k))
    return None if best is None else best[1]


def _knap01(units, cap):
    """0/1-рюкзак (numpy): units — [(вес, ценность, …)]; возвращает индексы взятых."""
    if not units or cap <= 0:
        return []
    if sum(u[0] for u in units) <= cap:
        return list(range(len(units)))
    dp = np.zeros(cap + 1)
    keeps = []
    for u in units:
        w, v = u[0], u[1]
        if w > cap:
            keeps.append(None)
            continue
        cand = dp[:cap + 1 - w] + v
        mask = cand > dp[w:] + 1e-9
        if mask.any():
            dp[w:] = np.where(mask, cand, dp[w:])
        keeps.append(mask)
    c = cap
    chosen = []
    for k in range(len(units) - 1, -1, -1):
        mask = keeps[k]
        if mask is None:
            continue
        w = units[k][0]
        if c >= w and mask[c - w]:
            chosen.append(k)
            c -= w
    chosen.reverse()
    return chosen


_KNAP_CAP = 6000  # ёмкость рюкзака полосы (в долях общего делителя весов), допустимая всегда…
_KNAP_CELLS = 600000  # …и больше — пока предметов × ёмкость не больше этого (тогда огрубления нет)
_ABSORB_ROUNDS = 400  # сколько последних листов вариант пробует разобрать по свободным местам


def _strip_fill(ft, rem, order, opens, WSg, WSup, cap, gap, Q, fill_mode):
    """Ряды деталей в полосу ширины WSg (= ⌊ширина + зазор⌋ в единицах) на свободную длину cap (единицы):
    рюкзак по площади (ряд — k одинаковых деталей поперёк полосы). Веса рядов делятся на их общий делитель —
    при одинаковых или кратных длинах рюкзак точный. Если ёмкость всё равно велика, она огрубляется
    (вес вверх, ёмкость вниз — раскладка остаётся допустимой), а потерянный на огрублении остаток
    дозаполняется рядами по точным длинам. Уменьшает rem; возвращает ряды [(i, rot, a, b, k)]."""
    cands = []
    for i in order:
        if rem[i] == 0:
            continue
        o = _fill_orient(ft[i]["orients"], opens[i], WSg, gap, Q, fill_mode)
        if o is None:
            continue
        rot, a, b, k = o
        wf = Q.up(b + gap)
        if wf > cap:
            continue
        bonus = 1.001 if Q.up(a + gap) * k == WSup else 1.0
        cands.append((i, rot, a, b, k, wf, bonus))
    if not cands:
        return []
    rows = []
    used = 0
    if sum(-(-rem[c[0]] // c[4]) * c[5] for c in cands) <= cap:
        for i, rot, a, b, k, wf, _ in cands:
            nf, pr = divmod(rem[i], k)
            rows.extend([(i, rot, a, b, k)] * nf)
            if pr:
                rows.append((i, rot, a, b, pr))
            rem[i] = 0
        return rows
    g = 0
    est = 0  # оценка числа предметов рюкзака (двоичное дробление рядов)
    for i, rot, a, b, k, wf, _ in cands:
        g = math.gcd(g, wf)
        nf, pr = divmod(rem[i], k)
        est += nf.bit_length() + (1 if pr else 0)
    lim = max(_KNAP_CAP, _KNAP_CELLS // max(1, est))
    unit = g * max(1, -(-(cap // g) // lim))
    capq = cap // unit
    units = []
    for ci, (i, rot, a, b, k, wf, bonus) in enumerate(cands):
        wq = -(-wf // unit)
        if wq > capq:
            continue
        nf, pr = divmod(rem[i], k)
        maxrows = capq // wq
        vrow = k * a * b * bonus
        nfe = min(nf, maxrows)
        j = 1
        while nfe > 0:
            take = min(j, nfe)
            units.append((wq * take, vrow * take, ci, k, take))
            nfe -= take
            j *= 2
        if pr and nf < maxrows:
            units.append((wq, pr * a * b * bonus, ci, pr, 1))
    for u in (units[q] for q in _knap01(units, capq)):
        _, _, ci, kk, take = u
        i, rot, a, b, _, wf, _ = cands[ci]
        rows.extend([(i, rot, a, b, kk)] * take)
        rem[i] -= kk * take
        used += wf * take
    # доливка по точным длинам: остаток, потерянный на огрублении весов (длинные ряды сначала)
    for i, rot, a, b, k, wf, _ in sorted(cands, key=lambda c: (-c[5], -c[4] * c[2] * c[3])):
        while rem[i] > 0 and used + wf <= cap:
            kk = min(k, rem[i])
            rows.append((i, rot, a, b, kk))
            rem[i] -= kk
            used += wf
    return rows


def _row_key(r):
    return (-r[2], -r[3], r[0], -r[4])


def _best_strip(ft, pool, order, R, Lcap, gap, Q):
    """Новая полоса шириной не больше R (единицы) из деталей pool в любых поворотах: перебор открывающей
    детали и её поворота, наполнение рюкзаком; берётся наибольшая площадь (затем уже). pool уменьшается.
    Возвращает (ширина, ряды) или None."""
    flex = [None] * len(ft)
    best = None
    for i in order:
        if pool[i] == 0:
            continue
        for oi, (rot, a, b) in enumerate(ft[i]["orients"]):
            Wup = Q.up(a + gap)
            if Wup > R:
                continue
            tmp = list(pool)
            tmp[i] -= 1
            rows = [(i, rot, a, b, 1)] + _strip_fill(ft, tmp, order, flex, Wup, Wup,
                                                     Lcap - Q.up(b + gap), gap, Q, "flex")
            area = sum(r[2] * r[3] * r[4] for r in rows)
            key = (-area, Wup, order.index(i), oi)
            if best is None or key < best[0]:
                best = (key, (a, rows), tmp)
    if best is None:
        return None
    pool[:] = best[2]
    a, rows = best[1]
    return a, [rows[0]] + sorted(rows[1:], key=_row_key)


def _absorb(sheets, ft, order, Wf, Lf, gap, Q, max_rounds):
    """Разбор последнего листа: его детали (в любых поворотах) — рядами в свободные концы полос и новыми
    полосами в свободную ширину остальных листов. Удалось целиком — лист убран, повтор; иначе всё как было.
    Так в одном листе сходятся полосы разной ориентации (широкая полоса + узкая из повёрнутых деталей).
    sheets — [[(ширина, ряды)]] в системе «поперёк a × вдоль b». Возвращает (листы, сколько убрано)."""
    n = len(ft)
    Wcap, Lcap = Q.down(Wf + gap), Q.down(Lf + gap)
    flex = [None] * n
    removed = 0

    def slen(rows):
        return sum(Q.up(r[3] + gap) for r in rows)

    def swidth(sh):
        return sum(Q.up(ws + gap) for ws, _ in sh)

    while len(sheets) >= 2 and removed < max_rounds:
        pool = [0] * n
        for _, rows in sheets[-1]:
            for r in rows:
                pool[r[0]] += r[4]
        act = [i for i in range(n) if pool[i]]
        min_a = min(Q.up(a + gap) for i in act for _, a, _ in ft[i]["orients"])
        min_b = min(Q.up(b + gap) for i in act for _, _, b in ft[i]["orients"])
        trial = [[(ws, list(rows)) for ws, rows in sh] for sh in sheets[:-1]]
        left = sum(pool)
        for j in sorted(range(len(trial)), key=lambda j: (swidth(trial[j]), j)):
            sh = trial[j]
            for si in range(len(sh)):
                ws, rows = sh[si]
                free = Lcap - slen(rows)
                if free < min_b:
                    continue
                add = _strip_fill(ft, pool, order, flex, Q.up(ws + gap), Q.up(ws + gap), free, gap, Q, "flex")
                if add:
                    sh[si] = (ws, rows + add)
                    left -= sum(r[4] for r in add)
                    if not left:
                        break
            R = Wcap - swidth(sh)
            while left and R >= min_a:
                st = _best_strip(ft, pool, order, R, Lcap, gap, Q)
                if st is None:
                    break
                sh.append(st)
                R -= Q.up(st[0] + gap)
                left -= sum(r[4] for r in st[1])
            if not left:
                break
        if left:
            break
        sheets = trial
        removed += 1
    return sheets, removed


def _two_stage(ft, Wf, Lf, gap, edge, Q, open_mode, fill_mode, bpp_nodes, absorb_rounds):
    """Полосы вдоль b (ширина — по a), ряды одинаковых деталей поперёк полосы, полосы — по листам точной
    одномерной упаковкой ширин; затем разбор последних листов в свободные места (_absorb)."""
    n = len(ft)
    rem = [x["qty"] for x in ft]
    opens = [_pick(x["orients"], open_mode) for x in ft]
    order = sorted(range(n), key=lambda i: (-opens[i][1], -opens[i][2], i))
    Lcap = Q.down(Lf + gap)
    strips = []
    ptr = 0
    while True:
        while ptr < n and rem[order[ptr]] == 0:
            ptr += 1
        if ptr >= n:
            break
        t0 = order[ptr]
        rot0, ws, b0 = opens[t0]
        rem[t0] -= 1
        rows = [(t0, rot0, ws, b0, 1)]
        extra = _strip_fill(ft, rem, order, opens, Q.up(ws + gap), Q.up(ws + gap), Lcap - Q.up(b0 + gap),
                            gap, Q, fill_mode)
        extra.sort(key=_row_key)
        strips.append((ws, rows + extra))
    entries = [(Q.up(ws + gap), 1) for ws, _ in strips]
    # граница LP здесь только ускоряет перебор: огрублённая ёмкость и малый предел работы
    res = _bpp(entries, Q.down(Wf + gap), bpp_nodes, use_lp=True, exact=Q.exact, dive_types=25,
               lp_cap=2000, lp_budget=60000, lp_types=60)
    fsheets = [[strips[s] for s in sorted(b, key=lambda s: (-strips[s][0], s))] for b in res["bins"]]
    fsheets, removed = _absorb(fsheets, ft, order, Wf, Lf, gap, Q, absorb_rounds)
    Wcap = Q.down(Wf + gap)

    def free_tail(sh):
        fa = Wcap - sum(Q.up(ws + gap) for ws, _ in sh)
        fb = Lcap - max(sum(Q.up(r[3] + gap) for r in rows) for _, rows in sh)
        return max(fa * Lcap, fb * Wcap)

    fsheets.sort(key=free_tail)  # самый свободный лист — последним (хвост — деловой остаток)
    sheets = []
    for sh in fsheets:
        x = edge
        pl = []
        for ws, rows in sh:
            y = edge
            for (i, rot, a, bb, k) in rows:
                for j in range(k):
                    pl.append((ft[i]["t"], rot, x + j * (a + gap), y, a, bb))
                y += bb + gap
            x += Q.up(ws + gap) * Q.u
        sheets.append(pl)
    return sheets, res, len(strips), removed


# --------------------------------------------------------------------------- сборка результата

def _to_out(sheets, types, transposed):
    out = []
    for pl in sheets:
        row = []
        for (t, rot, x, y, a, b) in pl:
            if transposed:
                x, y, a, b = y, x, b, a
            row.append({"id": types[t]["id"], "rot": rot, "x": round(x, 9), "y": round(y, 9),
                        "w": a, "h": b})
        out.append(row)
    return out


def _tail(sheet, W, L, edge):
    """Площадь свободного хвоста последнего листа (полоса у дальнего края по X или по Y, большая)."""
    Wc, Lc = W - 2 * edge, L - 2 * edge
    if not sheet:
        return Wc * Lc
    mx = max(p["x"] + p["w"] for p in sheet)
    my = max(p["y"] + p["h"] for p in sheet)
    return max((W - edge - mx) * Lc, (L - edge - my) * Wc, 0.0)


def pack_rect(items, W, L, gap, edge, rotations=(0, 90), node_limit=2_000_000):
    """Прямоугольный раскрой (см. описание модуля). Деталь, не влезающая на лист ни в одном допустимом
    повороте, — ValueError с её id."""
    try:
        W, L, gap, edge = float(W), float(L), float(gap), float(edge)
    except (TypeError, ValueError):
        raise ValueError("Размеры листа, зазор и кромка должны быть числами")
    if not all(math.isfinite(v) for v in (W, L, gap, edge)):
        raise ValueError("Размеры листа, зазор и кромка должны быть конечными числами")
    if gap < 0 or edge < 0:
        raise ValueError("Зазор (%s мм) и кромка (%s мм) не могут быть отрицательными" % (_f(gap), _f(edge)))
    Wc, Lc = W - 2 * edge, L - 2 * edge
    if Wc <= 0 or Lc <= 0:
        raise ValueError("Лист %s×%s мм не вмещает кромку %s мм" % (_f(W), _f(L), _f(edge)))
    rots = _norm_rotations(rotations)
    node_limit = int(node_limit)

    types = []
    for k, it in enumerate(items):
        try:
            iid = it["id"]
            w, h = float(it["w"]), float(it["h"])
            q = it.get("qty", 1)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("Деталь №%d: нужны поля id, w, h, qty (числа)" % (k + 1))
        try:
            qty = int(q)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Деталь «%s»: количество %r — не целое конечное число" % (iid, q))
        if qty != q or qty < 0:
            raise ValueError("Деталь «%s»: количество %r — нужно целое ≥ 0" % (iid, q))
        if not (math.isfinite(w) and math.isfinite(h) and w > 0 and h > 0):
            raise ValueError("Деталь «%s»: габарит %s×%s мм должен быть положительным" % (iid, w, h))
        if qty:
            types.append({"id": iid, "w": w, "h": h, "qty": qty})

    proof = []
    if not types:
        return {"sheets": [], "lower_bound": 0, "optimal": True, "method": "empty", "proof": ["Деталей нет."]}

    Q = _Q([W, L, gap, edge] + [t["w"] for t in types] + [t["h"] for t in types])
    fY = _frame(types, rots, Wc, Lc, gap, Q, transposed=False)
    fX = _frame(types, rots, Lc, Wc, gap, Q, transposed=True)
    rot_txt = ", ".join("%d°" % r for r, _ in rots)
    for x in fY:
        if not x["orients"]:
            t = types[x["t"]]
            raise ValueError("Деталь «%s» (%s×%s мм) не помещается на лист %s×%s мм с кромкой %s мм "
                             "ни в одном допустимом повороте (%s)" % (t["id"], _f(t["w"]), _f(t["h"]),
                                                                      _f(W), _f(L), _f(edge), rot_txt))

    n_items = sum(t["qty"] for t in types)
    proof.append("Лист %s×%s мм, кромка %s, зазор %s → рабочее поле %s×%s мм; деталей %d (%d типов), повороты %s%s."
                 % (_f(W), _f(L), _f(edge), _f(gap), _f(Wc), _f(Lc), n_items, len(types), rot_txt,
                    "" if Q.exact else "; размеры не кратны 0,001 мм — округление с запасом"))
    area = sum(t["qty"] * (t["w"] + gap) * (t["h"] + gap) for t in types)
    sheet_area = (Wc + gap) * (Lc + gap)
    area_lb = int(math.ceil(area / sheet_area - 1e-9))
    proof.append("Граница по площади: Σ(w+%s)(h+%s) = %.0f мм² / ((%s+%s)(%s+%s) = %.0f мм²) = %.3f → не меньше %d."
                 % (_f(gap), _f(gap), area, _f(Wc), _f(gap), _f(Lc), _f(gap), sheet_area, area / sheet_area,
                    area_lb))
    lb = max(area_lb, 1)  # деталь есть — хотя бы один лист (площадь пылинок округляется к нулю)

    # одна полоса на лист: вдоль Y (рамка Y) или вдоль X (рамка X)
    for fname, ft, Wf, Lf, transposed in (("Y", fY, Wc, Lc, False), ("X", fX, Lc, Wc, True)):
        cs = _column_set(ft, Wf, gap)
        if cs is None:
            continue
        cset, all_items, phys = cs
        across, along = ("X", "Y") if fname == "Y" else ("Y", "X")
        if all_items:
            if len(phys) >= 2:
                why = "две самые узкие поперёк %s: %s+%s+%s = %s > %s" % (
                    across, _f(phys[0]), _f(phys[1]), _f(gap), _f(phys[0] + phys[1] + gap), _f(Wf))
            else:
                why = "деталь одна"
            proof.append("Любые две детали рядом поперёк %s не встают (%s) → каждый лист — одна полоса вдоль %s: "
                         "одномерная упаковка, ёмкость %s+%s = %s мм, размер детали = наименьшая длина вдоль %s + %s."
                         % (across, why, along, _f(Lf), _f(gap), _f(Lf + gap), along, _f(gap)))
            sheets, res = _solve_columns(ft, Wf, Lf, gap, edge, Q, node_limit)
            proof.extend(res["notes"])
            lb = max(lb, res["lb"])
            out = _to_out(sheets, types, transposed)
            optimal = bool(res["optimal"]) or len(out) <= lb
            proof.append("Итог: %d листов, нижняя граница %d%s." % (
                len(out), lb, " → минимум доказан" if optimal else " — минимум не доказан"))
            return {"sheets": out, "lower_bound": int(lb), "optimal": optimal,
                    "method": "1d-exact-%s" % fname.lower(), "proof": proof}
        # частичная граница: эти детали в одном листе только друг за другом вдоль полосы
        lens = [(Q.down(min(b for _, _, b in ft[i]["orients"]) + gap), c) for i, c in cset]
        s1, c1 = _merge(lens)
        b1, parts = _lb_1d(s1, c1, Q.up(Lf + gap), lp=True)
        if b1 > 0:
            proof.append("Детали, никакие две из которых не встают рядом поперёк %s (%d шт.), идут в листе друг за "
                         "другом вдоль %s: %s → не меньше %d." % (across, sum(c1), along, _bounds_text(parts), b1))
        lb = max(lb, b1)

    # общий случай: двухэтапный гильотинный, все варианты (вариант, давший нижнюю границу, — сразу итог)
    multi = any(len(x["orients"]) > 1 for x in fY)
    bpp_nodes = min(node_limit, 20000)
    best, tried = None, 0
    for fname, ft, Wf, Lf, transposed in (("Y", fY, Wc, Lc, False), ("X", fX, Lc, Wc, True)):
        seen = set()
        for om in ("wide", "narrow", "r0", "r90"):
            opens = tuple(_pick(x["orients"], om) for x in ft)
            for fm in (("flex", "fixed") if multi else ("flex",)):
                key = (opens, fm)
                if key in seen or (best is not None and best[0][0] <= lb):
                    continue
                seen.add(key)
                sheets, res, nstrips, removed = _two_stage(ft, Wf, Lf, gap, edge, Q, om, fm, bpp_nodes,
                                                           _ABSORB_ROUNDS)
                out = _to_out(sheets, types, transposed)
                score = (len(out), -_tail(out[-1], W, L, edge) if out else 0.0, tried)
                tried += 1
                if best is None or score < best[0]:
                    best = (score, out, "2stage-%s-%s-%s" % (fname.lower(), om, fm), nstrips, res, removed)
    score, out, method, nstrips, res, removed = best
    optimal = len(out) <= lb
    tail = -score[1]
    proof.append("Двухэтапный гильотинный раскрой: %d вариантов (полосы вдоль Y и вдоль X × правило поворота × "
                 "заполнение полос); лучший — %s: %d полос → %d листов%s, свободный хвост последнего листа %.0f мм²."
                 % (tried, method, nstrips, len(out),
                    " (после разбора %d последних листов по свободным местам остальных)" % removed
                    if removed else "", tail))
    if optimal:
        proof.append("Итог: %d листов = нижней границе %d → минимум доказан." % (len(out), lb))
    else:
        proof.append("Итог: %d листов, нижняя граница %d (разрыв %d) — минимум не доказан."
                     % (len(out), lb, len(out) - lb))
    return {"sheets": out, "lower_bound": int(lb), "optimal": bool(optimal), "method": method, "proof": proof}
