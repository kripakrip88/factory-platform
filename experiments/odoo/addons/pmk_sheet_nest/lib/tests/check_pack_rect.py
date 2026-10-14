# -*- coding: utf-8 -*-
"""Проверка pack_rect: решётки (77 листов, доказанный минимум), случайные задачи, крайние случаи.

Запуск: python3 tests/check_pack_rect.py   (код выхода 0 — всё прошло)
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from sheet_nest.pack_rect import pack_rect  # noqa: E402

TOL = 1e-6
FAILS = []


def fail(msg):
    FAILS.append(msg)
    print("  ОШИБКА: " + msg)


def check(res, items, W, L, gap, edge, rotations=(0, 90), label=""):
    """Проверка раскладки: всё внутри поля, зазоры, размеры по повороту, каждая деталь ровно qty раз."""
    ok = True
    byid = {}
    for it in items:
        byid.setdefault(it["id"], []).append(it)
    want = {}
    for it in items:
        want[it["id"]] = want.get(it["id"], 0) + int(it["qty"])
    got = {}
    allowed = set(int(r) % 360 for r in rotations)
    for si, sheet in enumerate(res["sheets"]):
        if not sheet:
            fail("%s: лист %d пустой" % (label, si + 1))
            ok = False
        for p in sheet:
            got[p["id"]] = got.get(p["id"], 0) + 1
            if p["rot"] not in allowed:
                fail("%s: лист %d, %s — поворот %r не разрешён" % (label, si + 1, p["id"], p["rot"]))
                ok = False
            dims_ok = False
            for it in byid.get(p["id"], []):
                ww, hh = (it["w"], it["h"]) if (p["rot"] // 90) % 2 == 0 else (it["h"], it["w"])
                if abs(ww - p["w"]) <= TOL and abs(hh - p["h"]) <= TOL:
                    dims_ok = True
            if not dims_ok:
                fail("%s: лист %d, %s — габарит %gx%g не совпадает с деталью при повороте %d"
                     % (label, si + 1, p["id"], p["w"], p["h"], p["rot"]))
                ok = False
            if (p["x"] < edge - TOL or p["y"] < edge - TOL or p["x"] + p["w"] > W - edge + TOL
                    or p["y"] + p["h"] > L - edge + TOL):
                fail("%s: лист %d, %s (%g,%g %gx%g) за краем поля" % (label, si + 1, p["id"], p["x"], p["y"],
                                                                     p["w"], p["h"]))
                ok = False
        n = len(sheet)
        for a in range(n):
            pa = sheet[a]
            for b in range(a + 1, n):
                pb = sheet[b]
                sep = (pa["x"] + pa["w"] + gap <= pb["x"] + TOL or pb["x"] + pb["w"] + gap <= pa["x"] + TOL or
                       pa["y"] + pa["h"] + gap <= pb["y"] + TOL or pb["y"] + pb["h"] + gap <= pa["y"] + TOL)
                if not sep:
                    fail("%s: лист %d — %s и %s ближе зазора %g" % (label, si + 1, pa["id"], pb["id"], gap))
                    ok = False
    if got != want:
        fail("%s: количества не сходятся: нужно %r, разложено %r" % (label, want, got))
        ok = False
    if res["lower_bound"] > len(res["sheets"]):
        fail("%s: нижняя граница %d больше числа листов %d" % (label, res["lower_bound"], len(res["sheets"])))
        ok = False
    if res["optimal"] and res["lower_bound"] != len(res["sheets"]):
        fail("%s: optimal=True, но листов %d ≠ границе %d" % (label, len(res["sheets"]), res["lower_bound"]))
        ok = False
    for key in ("sheets", "lower_bound", "optimal", "method", "proof"):
        if key not in res:
            fail("%s: в результате нет ключа %s" % (label, key))
            ok = False
    return ok


# --------------------------------------------------------------------------- (a) решётки

def test_grates():
    print("(a) решётки 1,5 цинк, лист 1250×2500, зазор 2, кромка 2")
    spec = [("A", 1006, 8), ("B", 1000, 16), ("C", 986, 8), ("D", 971, 16), ("E", 950, 24), ("F", 946, 24),
            ("G", 887, 8), ("H", 871, 4), ("I", 857, 28), ("J", 841, 8), ("K", 797, 24)]
    items = [{"id": i, "w": w, "h": 1126, "qty": q} for i, w, q in spec]
    t0 = time.time()
    res = pack_rect(items, 1250, 2500, 2, 2, rotations=(0, 90))
    dt = time.time() - t0
    n = len(res["sheets"])
    print("  листов %d, граница %d, optimal %s, метод %s, %.2f с" % (n, res["lower_bound"], res["optimal"],
                                                                    res["method"], dt))
    for line in res["proof"]:
        print("    · " + line)
    check(res, items, 1250, 2500, 2, 2, (0, 90), "решётки")
    if n != 77:
        fail("решётки: листов %d, нужно 77" % n)
    if res["lower_bound"] != 77:
        fail("решётки: нижняя граница %d, нужно 77" % res["lower_bound"])
    if res["optimal"] is not True:
        fail("решётки: optimal не True")
    mx = max(len(s) for s in res["sheets"])
    if mx > 3:
        fail("решётки: на листе %d деталей (больше 3)" % mx)
    if sum(len(s) for s in res["sheets"]) != 168:
        fail("решётки: разложено не 168 деталей")
    if dt >= 10:
        fail("решётки: %.1f с (нужно < 10 с)" % dt)
    # хвост: на каждом листе детали подряд от кромки вдоль Y, x = кромка
    for si, s in enumerate(res["sheets"]):
        ys = sorted(s, key=lambda p: p["y"])
        y = 2.0
        for p in ys:
            if abs(p["x"] - 2) > TOL or abs(p["y"] - y) > TOL:
                fail("решётки: лист %d — детали не идут подряд от кромки" % (si + 1))
                break
            y = p["y"] + p["h"] + 2
        lens = [p["h"] for p in ys]
        if lens != sorted(lens, reverse=True):
            fail("решётки: лист %d — длины не по убыванию" % (si + 1))
    used = [sum(p["h"] + 2 for p in s) for s in res["sheets"]]
    if used[-1] != min(used):
        fail("решётки: последний лист не самый свободный")
    print("  свободно на последнем листе: %.0f мм вдоль Y" % (2498 - used[-1]))


# --------------------------------------------------------------------------- (b) случайные

def random_instance(rng, kind):
    W, L = rng.choice([(1250, 2500), (1500, 3000), (1000, 2000)])
    gap = rng.choice([0, 2, 5])
    edge = rng.choice([0, 2, 10])
    rotations = rng.choice([(0, 90), (0, 90), (0,)])
    Wc, Lc = W - 2 * edge, L - 2 * edge
    items = []
    ntypes = rng.randint(3, 12)
    for k in range(ntypes):
        if kind == "small":
            w, h = rng.randint(20, 300), rng.randint(20, 400)
        elif kind == "mixed":
            if rng.random() < 0.3:
                w, h = rng.randint(300, Wc), rng.randint(200, min(Lc, 1500))
            else:
                w, h = rng.randint(30, 400), rng.randint(30, 600)
        elif kind == "wide":  # широкие — случай «одна полоса»
            w, h = rng.randint(Wc // 2 + 5, Wc), rng.randint(100, Lc // 2)
            rotations = (0,)
        else:  # дробные размеры
            w, h = round(rng.uniform(15, 500), 2), round(rng.uniform(15, 700), 2)
        if rotations == (0,) and (w > Wc or h > Lc):
            w, h = min(w, Wc), min(h, Lc)
        items.append({"id": "P%d" % k, "w": w, "h": h, "qty": rng.randint(1, 12)})
    return items, W, L, gap, edge, rotations


def test_random():
    print("(b) 30 случайных задач")
    rng = random.Random(20261012)
    kinds = ["small", "mixed", "wide", "frac"]
    total_gap = 0
    t_all = time.time()
    for k in range(30):
        kind = kinds[k % len(kinds)]
        items, W, L, gap, edge, rot = random_instance(rng, kind)
        t0 = time.time()
        res = pack_rect(items, W, L, gap, edge, rotations=rot)
        dt = time.time() - t0
        n = len(res["sheets"])
        lb = res["lower_bound"]
        total_gap += n - lb
        ok = check(res, items, W, L, gap, edge, rot, "случай %d" % (k + 1))
        print("  %2d %-5s %4dx%-4d зазор %d кромка %2d пов %-7s дет %3d: листов %3d, граница %3d, разрыв %d%s, %-22s %.2f с%s"
              % (k + 1, kind, W, L, gap, edge, "/".join(map(str, rot)), sum(i["qty"] for i in items), n, lb,
                 n - lb, " (opt)" if res["optimal"] else "", res["method"], dt, "" if ok else "  ← ОШИБКА"))
    print("  суммарный разрыв с нижней границей: %d листов; время %.1f с" % (total_gap, time.time() - t_all))


def test_perf():
    print("(b2) производительность: 200 случайных деталей")
    rng = random.Random(7)
    for label, ntypes, qmax in (("200 типов по 1 шт", 200, 1), ("40 типов, 200 шт", 40, None)):
        items = []
        left = 200
        for k in range(ntypes):
            if qmax == 1:
                q = 1
            else:
                q = 5
            left -= q
            items.append({"id": "R%d" % k, "w": rng.randint(20, 900), "h": rng.randint(20, 1200), "qty": q})
        t0 = time.time()
        res = pack_rect(items, 1250, 2500, 2, 2)
        dt = time.time() - t0
        check(res, items, 1250, 2500, 2, 2, (0, 90), label)
        print("  %s: листов %d, граница %d, метод %s, %.1f с" % (label, len(res["sheets"]), res["lower_bound"],
                                                              res["method"], dt))
        if dt >= 30:
            fail("%s: %.1f с (нужно < 30 с)" % (label, dt))
    # одна полоса на лист, много типов (точный перебор с пределом узлов)
    items = [{"id": "S%d" % k, "w": rng.randint(630, 1240), "h": rng.randint(150, 1100), "qty": rng.randint(1, 3)}
             for k in range(80)]
    t0 = time.time()
    res = pack_rect(items, 1250, 2500, 2, 2, rotations=(0,))
    dt = time.time() - t0
    check(res, items, 1250, 2500, 2, 2, (0,), "полоса, 80 типов")
    print("  полоса, 80 типов (%d шт): листов %d, граница %d, optimal %s, метод %s, %.1f с"
          % (sum(i["qty"] for i in items), len(res["sheets"]), res["lower_bound"], res["optimal"], res["method"], dt))
    if res["method"] != "1d-exact-y":
        fail("полоса, 80 типов: ожидался 1d-exact-y, получен %s" % res["method"])
    if dt >= 30:
        fail("полоса, 80 типов: %.1f с" % dt)


# --------------------------------------------------------------------------- (c) крайние случаи

def test_edges():
    print("(c) крайние случаи")
    W, L, gap, edge = 1250, 2500, 2, 2
    # одна деталь
    items = [{"id": "один", "w": 300, "h": 200, "qty": 1}]
    res = pack_rect(items, W, L, gap, edge)
    check(res, items, W, L, gap, edge, (0, 90), "одна деталь")
    if len(res["sheets"]) != 1 or not res["optimal"] or res["lower_bound"] != 1:
        fail("одна деталь: %d листов, граница %d, optimal %s" % (len(res["sheets"]), res["lower_bound"],
                                                               res["optimal"]))
    p = res["sheets"][0][0]
    if abs(p["x"] - edge) > TOL or abs(p["y"] - edge) > TOL:
        fail("одна деталь: не у кромки (%g, %g)" % (p["x"], p["y"]))
    print("  одна деталь: ок (%s)" % res["method"])

    # ровно во всю ширину поля
    items = [{"id": "полоса", "w": W - 2 * edge, "h": 500, "qty": 5}]
    res = pack_rect(items, W, L, gap, edge)
    check(res, items, W, L, gap, edge, (0, 90), "во всю ширину")
    # 5 штук по 500+2 при ёмкости 2498 → 4 на лист → 2 листа
    if len(res["sheets"]) != 2 or not res["optimal"]:
        fail("во всю ширину: %d листов (нужно 2), optimal %s" % (len(res["sheets"]), res["optimal"]))
    print("  во всю ширину поля (1246): %d листа, %s, optimal %s" % (len(res["sheets"]), res["method"],
                                                                    res["optimal"]))

    # во всю длину и ширину
    items = [{"id": "весь", "w": W - 2 * edge, "h": L - 2 * edge, "qty": 3}]
    res = pack_rect(items, W, L, gap, edge)
    check(res, items, W, L, gap, edge, (0, 90), "во всё поле")
    if len(res["sheets"]) != 3 or not res["optimal"]:
        fail("во всё поле: %d листов" % len(res["sheets"]))
    print("  во всё поле: %d листа, optimal %s" % (len(res["sheets"]), res["optimal"]))

    # не влезает
    for items, rot, label in (([{"id": "большая", "w": 1300, "h": 2600, "qty": 1}], (0, 90), "больше листа"),
                              ([{"id": "поперёк", "w": 2000, "h": 500, "qty": 1}], (0,), "без поворота")):
        try:
            pack_rect(items, W, L, gap, edge, rotations=rot)
            fail("%s: нет ValueError" % label)
        except ValueError as e:
            if items[0]["id"] not in str(e):
                fail("%s: в сообщении нет id детали: %s" % (label, e))
            else:
                print("  %s → ValueError: %s" % (label, e))
    # с поворотом та же деталь влезает
    items = [{"id": "поперёк", "w": 2000, "h": 500, "qty": 2}]
    res = pack_rect(items, W, L, gap, edge, rotations=(0, 90))
    check(res, items, W, L, gap, edge, (0, 90), "поперёк с поворотом")
    if any(p["rot"] != 90 for s in res["sheets"] for p in s):
        fail("поперёк с поворотом: ожидался поворот 90")
    print("  2000×500 с поворотом: %d лист(а), поворот 90" % len(res["sheets"]))

    # зазор 0
    items = [{"id": "кв", "w": 625, "h": 625, "qty": 8}]
    res = pack_rect(items, 1250, 2500, 0, 0)
    check(res, items, 1250, 2500, 0, 0, (0, 90), "зазор 0")
    if len(res["sheets"]) != 1 or not res["optimal"]:
        fail("зазор 0: 8 квадратов 625 должны лечь на один лист 1250×2500, получено %d" % len(res["sheets"]))
    print("  зазор 0: 8×625² на одном листе — %d лист, %s" % (len(res["sheets"]), res["method"]))

    # только поворот 0
    items = [{"id": "a", "w": 400, "h": 100, "qty": 30}, {"id": "b", "w": 250, "h": 300, "qty": 10}]
    res = pack_rect(items, W, L, gap, edge, rotations=(0,))
    check(res, items, W, L, gap, edge, (0,), "только 0")
    if any(p["rot"] != 0 for s in res["sheets"] for p in s):
        fail("только 0: встретился поворот")
    print("  только поворот 0: %d лист(а), граница %d, %s" % (len(res["sheets"]), res["lower_bound"], res["method"]))

    # одна полоса вдоль X (строка): длинные детали, две вдоль Y не встают
    items = [{"id": "дл%d" % k, "w": 300 + 37 * k, "h": 1500, "qty": 2} for k in range(4)]
    res = pack_rect(items, W, L, gap, edge, rotations=(0,))
    check(res, items, W, L, gap, edge, (0,), "строка вдоль X")
    if res["method"] != "1d-exact-x":
        fail("строка вдоль X: ожидался 1d-exact-x, получен %s" % res["method"])
    print("  строка вдоль X: %d листов, граница %d, %s, optimal %s" % (len(res["sheets"]), res["lower_bound"],
                                                                     res["method"], res["optimal"]))

    # пустой список, нулевое количество
    res = pack_rect([{"id": "z", "w": 10, "h": 10, "qty": 0}], W, L, gap, edge)
    if res["sheets"] != [] or res["lower_bound"] != 0:
        fail("пусто: ожидался пустой результат")
    # дробные размеры
    items = [{"id": "др", "w": 123.45, "h": 67.891, "qty": 40}]
    res = pack_rect(items, W, L, 1.5, 3.25)
    check(res, items, W, L, 1.5, 3.25, (0, 90), "дробные")
    print("  дробные размеры: %d лист(а), %s" % (len(res["sheets"]), res["method"]))
    # неверные аргументы
    for args, label in (((W, L, -1, 0), "зазор < 0"), ((W, L, 0, 700), "кромка больше листа")):
        try:
            pack_rect([{"id": "x", "w": 10, "h": 10, "qty": 1}], *args)
            fail("%s: нет ValueError" % label)
        except ValueError:
            pass
    try:
        pack_rect([{"id": "x", "w": 10, "h": 10, "qty": 1}], W, L, 2, 2, rotations=(45,))
        fail("поворот 45: нет ValueError")
    except ValueError:
        pass
    # детерминированность
    rng = random.Random(5)
    items = [{"id": "d%d" % k, "w": rng.randint(30, 600), "h": rng.randint(30, 900), "qty": rng.randint(1, 6)}
             for k in range(25)]
    r1 = pack_rect(items, W, L, gap, edge)
    r2 = pack_rect(items, W, L, gap, edge)
    if r1 != r2:
        fail("повторный запуск дал другой результат")
    print("  повторный запуск: результат тот же")


# --------------------------------------------------------------------------- (d) одномерный решатель

def _brute_bins(sizes, C):
    """Минимум листов полным перебором (динамика по подмножествам), n ≤ 11."""
    n = len(sizes)
    INF = (1 << 30, 0)
    dp = [INF] * (1 << n)
    dp[0] = (1, 0)
    for m in range(1 << n):
        b, f = dp[m]
        if b >= INF[0]:
            continue
        for i in range(n):
            if m >> i & 1:
                continue
            nb = (b, f + sizes[i]) if f + sizes[i] <= C else (b + 1, sizes[i])
            if nb < dp[m | 1 << i]:
                dp[m | 1 << i] = nb
    return dp[-1][0] if n else 0


def test_1d_solver():
    from sheet_nest import pack_rect as P
    print("(d) одномерный решатель: границы и перебор против полного перебора")
    rng = random.Random(1)
    bad = 0
    for _ in range(400):
        C = rng.choice([10, 17, 50, 100, 101])
        n = rng.randint(1, 10)
        lo = rng.choice([1, C // 5, C // 4, C // 3])
        sizes = [rng.randint(max(1, lo), C) for _ in range(n)]
        opt = _brute_bins(sizes, C)
        res = P._bpp([(s, 1) for s in sizes], C, 200000)
        used = {}
        for b in res["bins"]:
            if sum(sizes[i] * m for i, m in b.items()) > C:
                bad += 1
            for i, m in b.items():
                used[i] = used.get(i, 0) + m
        if used != {i: 1 for i in range(n)} or len(res["bins"]) < opt or res["lb"] > opt or \
                (res["optimal"] and len(res["bins"]) != opt):
            bad += 1
            print("  расхождение: C=%d %r: перебор %d, решатель %d, граница %d" % (C, sizes, opt, len(res["bins"]),
                                                                                res["lb"]))
        ss, cc = P._merge([(s, 1) for s in sizes])
        for name, v in (("L2", P._l2(ss, cc, C)), ("DFF", P._dff_bound(ss, cc, C)[0]),
                        ("LP", P._lp_bound(ss, cc, C)[0])):
            if v > opt:
                bad += 1
                print("  граница %s = %d больше оптимума %d: C=%d %r" % (name, v, opt, C, sizes))
        if opt >= 1:
            sol, _, st = P._bin_completion(ss, cc, C, opt, 10 ** 6)
            if st != "found" or len(sol) > opt:
                bad += 1
                print("  перебор не нашёл %d листов: C=%d %r" % (opt, C, sizes))
        if opt >= 2:
            _, _, st = P._bin_completion(ss, cc, C, opt - 1, 10 ** 6)
            if st == "found":
                bad += 1
                print("  перебор «нашёл» %d листов при оптимуме %d: C=%d %r" % (opt - 1, opt, C, sizes))
    if bad:
        fail("одномерный решатель: %d расхождений с полным перебором" % bad)
    else:
        print("  400 случайных задач: расхождений нет")

    # решётки — точный перебор сам по себе (без округления LP) находит 77
    sizes = [1008, 1002, 988, 973, 952, 948, 889, 873, 859, 843, 799]
    counts = [8, 16, 8, 16, 24, 24, 8, 4, 28, 8, 24]
    sol, nodes, st = P._bin_completion(sizes, counts, 2498, 77, 2000000)
    if st != "found" or len(sol) != 77 or max(sum(b.values()) for b in sol) > 3:
        fail("решётки: перебор bin completion не нашёл 77 листов (%s)" % st)
    else:
        print("  решётки перебором bin completion: 77 листов за %d узлов" % nodes)

    # предел узлов: трудная задача «тройки» в полосе — результат верный, optimal False, граница не выше листов
    rng = random.Random(4)
    lens = []
    while len(lens) < 90:
        a, b = rng.randint(250, 499), rng.randint(250, 499)
        c = 1000 - a - b
        if 250 <= c <= 499:
            lens += [a, b, c]
    items = [{"id": "T%d" % i, "w": 1000, "h": h, "qty": 1} for i, h in enumerate(lens)]
    res = pack_rect(items, 1250, 1000, 0, 0, rotations=(0,), node_limit=2000)
    check(res, items, 1250, 1000, 0, 0, (0,), "тройки, предел узлов")
    if res["method"] != "1d-exact-y" or res["optimal"] or len(res["sheets"]) <= res["lower_bound"]:
        fail("тройки: ожидался 1d-exact-y без доказанного минимума, получено %s, %d листов, граница %d, optimal %s"
             % (res["method"], len(res["sheets"]), res["lower_bound"], res["optimal"]))
    print("  тройки (90 шт), предел 2000 узлов: %d листов, граница %d, optimal %s — «%s»"
          % (len(res["sheets"]), res["lower_bound"], res["optimal"], res["proof"][-2]))


# --------------------------------------------------------------------------- (e) регрессии

def test_regressions():
    print("(e) регрессии: сетка дробных заготовок, полосы разной ориентации, вырожденный ввод, время на 0,01 мм")
    # лист, разрезанный ровно на 3×5 заготовок 414×497,6 (x = 2, 418, 834; y = 2, 501,6 … 2000,4 → 2498):
    # рюкзак полосы не должен терять ряд на округлении дробных длин
    for items, rot, want in (
            ([{"id": "заг", "w": 414, "h": 497.6, "qty": 15}], (0,), 1),
            ([{"id": "заг", "w": 414, "h": 497.6, "qty": 150}], (0,), 10),
            ([{"id": "заг", "w": 247.6, "h": 310.25, "qty": 40}], (0,), 1),
            # два типа, точная сумма длин в полосе: 2·(609,3+2) + 2·(635,7+2) = 2498
            ([{"id": "a", "w": 414, "h": 609.3, "qty": 6}, {"id": "b", "w": 414, "h": 635.7, "qty": 6}], (0,), 1)):
        res = pack_rect(items, 1250, 2500, 2, 2, rotations=rot)
        label = "сетка %s" % ", ".join("%g×%g×%d" % (i["w"], i["h"], i["qty"]) for i in items)
        check(res, items, 1250, 2500, 2, 2, rot, label)
        print("  %s: %d лист(ов), граница %d, %s" % (label, len(res["sheets"]), res["lower_bound"], res["method"]))
        if len(res["sheets"]) != want:
            fail("%s: нужно %d листов, получено %d" % (label, want, len(res["sheets"])))
    # широкая полоса + узкая из повёрнутых деталей в одном листе
    items = [{"id": "п", "w": 510, "h": 300, "qty": 4}]
    res = pack_rect(items, 1000, 1000, 0, 0)
    check(res, items, 1000, 1000, 0, 0, (0, 90), "510×300 ×4")
    print("  510×300 ×4 на 1000×1000: %d лист(ов), %s" % (len(res["sheets"]), res["method"]))
    if len(res["sheets"]) != 1:
        fail("510×300 ×4 на 1000×1000: нужен 1 лист (полоса 510 из трёх + полоса 300 из повёрнутой)")
    # детали чуть шире половины листа 600×600: в листе полоса из двух неповёрнутых + полоса из повёрнутой → 15
    rng = random.Random(0)
    items, left = [], 45
    for k in range(4):
        q = left if k == 3 else rng.randint(5, 15)
        left -= q
        items.append({"id": "h%d" % k, "w": round(rng.uniform(299.6, 301), 1), "h": round(rng.uniform(210, 255), 1),
                      "qty": q})
    res = pack_rect(items, 600, 600, 2.5, 0.5)
    check(res, items, 600, 600, 2.5, 0.5, (0, 90), "600×600 полуширинные")
    print("  600×600, 45 деталей ~300×230: %d листов, граница %d, %s" % (len(res["sheets"]), res["lower_bound"],
                                                                       res["method"]))
    if len(res["sheets"]) > 15:
        fail("600×600 полуширинные: %d листов, есть раскладка в 15 (по 3 на лист)" % len(res["sheets"]))
    # вырожденный ввод: пылинки — раскладка или ValueError, но не падение; qty = inf — ValueError
    for label, items, rot in (("пылинка 1e-9", [{"id": "пыль", "w": 1e-9, "h": 1e-9, "qty": 3}], (0, 90)),
                              ("нить 1000×1e-9", [{"id": "нить", "w": 1000, "h": 1e-9, "qty": 3}], (0,))):
        try:
            res = pack_rect(items, 1250, 2500, 0, 0, rotations=rot)
            check(res, items, 1250, 2500, 0, 0, rot, label)
            if res["lower_bound"] < 1:
                fail("%s: нижняя граница %d при непустом заказе" % (label, res["lower_bound"]))
            print("  %s: %d лист, граница %d" % (label, len(res["sheets"]), res["lower_bound"]))
        except ValueError as e:
            print("  %s → ValueError: %s" % (label, e))
        except Exception as e:  # noqa: BLE001
            fail("%s: падение %s: %s" % (label, type(e).__name__, e))
    try:
        pack_rect([{"id": "беск", "w": 5, "h": 5, "qty": float("inf")}], 1250, 2500, 2, 2)
        fail("qty = inf: нет ValueError")
    except ValueError as e:
        print("  qty = inf → ValueError: %s" % e)
    except Exception as e:  # noqa: BLE001
        fail("qty = inf: %s вместо ValueError" % type(e).__name__)
    # время: 200 деталей с размерами до 0,01 мм (как из DXF) — граница LP по ширинам полос не должна
    # считаться в 0,01 мм на каждом варианте
    rng = random.Random(8)
    items = [{"id": k, "w": round(rng.uniform(20, 1240), 2), "h": round(rng.uniform(20, 2490), 2), "qty": 1}
             for k in range(200)]
    t0 = time.time()
    res = pack_rect(items, 1250, 2500, 2, 2)
    dt = time.time() - t0
    check(res, items, 1250, 2500, 2, 2, (0, 90), "200 деталей 0,01 мм")
    print("  200 деталей 0,01 мм: %d листов, граница %d, %s, %.1f с" % (len(res["sheets"]), res["lower_bound"],
                                                                       res["method"], dt))
    if dt >= 30:
        fail("200 деталей 0,01 мм: %.1f с (нужно < 30 с)" % dt)


def main():
    t0 = time.time()
    test_grates()
    test_edges()
    test_random()
    test_perf()
    test_1d_solver()
    test_regressions()
    print("—" * 60)
    if FAILS:
        print("НЕ ПРОШЛО: %d ошибок (%.1f с)" % (len(FAILS), time.time() - t0))
        return 1
    print("ВСЁ ПРОШЛО (%.1f с)" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
