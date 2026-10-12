# -*- coding: utf-8 -*-
"""Состязательная проверка pack_rect (независимо от tests/check_pack_rect.py).

Проверяет модуль ТОЛЬКО через открытый вызов pack_rect(...) и сверяет с независимыми решателями:
  • строгая проверка раскладки (поле, зазоры, габарит по повороту, разрешённый поворот, количества, типы полей);
  • независимый точный одномерный решатель (перебор по векторам количеств с запоминанием) — случай «одна полоса»;
  • независимая эвристика MaxRects — если она укладывает в меньше листов, чем lower_bound, граница неверна;
  • условие «одна полоса на лист» из договора, посчитанное независимо;
  • раскладка «сеткой» деталей, нарезанных из листа ровно (лист делится на kx×ky равных заготовок);
  • ошибки ввода (ValueError по-русски, без падений другими исключениями);
  • детерминированность (повтор, другой PYTHONHASHSEED);
  • время (решётки < 10 с, 200 случайных деталей < 30 с).

Запуск: python3 tests/adv_pack_rect.py         (код выхода 0 — всё прошло)
        ADV_SKIP_SLOW=1 python3 tests/adv_pack_rect.py   — без долгой проверки времени на 200 деталях
"""
import functools
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import Counter

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from sheet_nest.pack_rect import pack_rect  # noqa: E402

TOL = 1e-6
FAILS = []


def fail(section, msg):
    FAILS.append((section, msg))
    print("  ОШИБКА [%s]: %s" % (section, msg))


# --------------------------------------------------------------------------- независимые инструменты

def validate(res, items, W, L, gap, edge, rotations):
    """Строгая проверка результата. Возвращает список нарушений."""
    errs = []
    for key in ("sheets", "lower_bound", "optimal", "method", "proof"):
        if key not in res:
            errs.append("нет ключа %s" % key)
    if errs:
        return errs
    allowed = set(int(round(float(r))) % 360 for r in rotations)
    want, dims = {}, {}
    for it in items:
        q = it.get("qty", 1)
        if q:
            want[it["id"]] = want.get(it["id"], 0) + q
            dims[it["id"]] = (float(it["w"]), float(it["h"]))
    got = {}
    for si, sh in enumerate(res["sheets"]):
        if not sh:
            errs.append("лист %d пустой" % si)
        for p in sh:
            for k in ("id", "rot", "x", "y", "w", "h"):
                if k not in p:
                    errs.append("в размещении нет %s" % k)
                    return errs
            got[p["id"]] = got.get(p["id"], 0) + 1
            if p["rot"] not in allowed:
                errs.append("поворот %r не разрешён (%r)" % (p["rot"], sorted(allowed)))
            w, h = dims[p["id"]]
            if p["rot"] % 180 == 90:
                w, h = h, w
            if abs(p["w"] - w) > TOL or abs(p["h"] - h) > TOL:
                errs.append("габарит не по повороту: %r" % p)
            if (p["x"] < edge - TOL or p["y"] < edge - TOL or p["x"] + p["w"] > W - edge + TOL
                    or p["y"] + p["h"] > L - edge + TOL):
                errs.append("за полем, лист %d: %r" % (si, p))
        order = sorted(range(len(sh)), key=lambda i: sh[i]["x"])
        for ii in range(len(order)):
            a = sh[order[ii]]
            for jj in range(ii + 1, len(order)):
                b = sh[order[jj]]
                if b["x"] >= a["x"] + a["w"] + gap - TOL:
                    break
                sep = (a["x"] + a["w"] + gap <= b["x"] + TOL or b["x"] + b["w"] + gap <= a["x"] + TOL or
                       a["y"] + a["h"] + gap <= b["y"] + TOL or b["y"] + b["h"] + gap <= a["y"] + TOL)
                if not sep:
                    errs.append("ближе зазора, лист %d: %r и %r" % (si, a, b))
    if got != want:
        errs.append("количества: нужно %r, разложено %r" % (want, got))
    lb = res["lower_bound"]
    if not isinstance(lb, int) or isinstance(lb, bool):
        errs.append("lower_bound не int: %r" % type(lb))
    if not isinstance(res["optimal"], bool):
        errs.append("optimal не bool")
    if not isinstance(res["method"], str):
        errs.append("method не str")
    if not isinstance(res["proof"], list) or not all(isinstance(s, str) for s in res["proof"]):
        errs.append("proof не список строк")
    n = len(res["sheets"])
    if lb > n:
        errs.append("нижняя граница %d больше числа листов %d" % (lb, n))
    if res["optimal"] != (n == lb):
        errs.append("optimal=%s, а листов %d при границе %d" % (res["optimal"], n, lb))
    return errs


def exact_bins(sizes, counts, C):
    """Независимый точный минимум одномерной упаковки: запоминание по векторам количеств,
    лист открывается первой оставшейся деталью, перебор всех дополнений."""
    T = len(sizes)

    @functools.lru_cache(maxsize=None)
    def f(state):
        if not any(state):
            return 0
        i = next(k for k in range(T) if state[k])
        best = [10 ** 9]
        cur = list(state)
        cur[i] -= 1

        def rec(j, cap):
            if j == T:
                v = f(tuple(cur))
                if v < best[0]:
                    best[0] = v
                return
            for m in range(min(cur[j], cap // sizes[j]), -1, -1):
                cur[j] -= m
                rec(j + 1, cap - m * sizes[j])
                cur[j] += m

        rec(i, C - sizes[i])
        return 1 + best[0]

    return f(tuple(counts))


def maxrects(items, W, L, gap, edge, rotations):
    """Независимая эвристика MaxRects (лучшая короткая сторона): число листов допустимой раскладки."""
    Wf, Lf = W - 2 * edge + gap, L - 2 * edge + gap
    par = sorted(set((int(round(float(r))) % 360 // 90) % 2 for r in rotations))
    lst = []
    for it in items:
        lst += [(float(it["w"]) + gap, float(it["h"]) + gap)] * it["qty"]
    lst.sort(key=lambda d: (-max(d), -min(d)))
    sheets = []

    def place(free, w, h):
        best = None
        for fx, fy, fw, fh in free:
            for p in par:
                ww, hh = (w, h) if p == 0 else (h, w)
                if ww <= fw + 1e-9 and hh <= fh + 1e-9:
                    sc = (min(fw - ww, fh - hh), max(fw - ww, fh - hh))
                    if best is None or sc < best[0]:
                        best = (sc, fx, fy, ww, hh)
        return best

    def split(free, x, y, w, h):
        out = []
        for fx, fy, fw, fh in free:
            if x >= fx + fw - 1e-9 or x + w <= fx + 1e-9 or y >= fy + fh - 1e-9 or y + h <= fy + 1e-9:
                out.append((fx, fy, fw, fh))
                continue
            if x > fx + 1e-9:
                out.append((fx, fy, x - fx, fh))
            if x + w < fx + fw - 1e-9:
                out.append((x + w, fy, fx + fw - x - w, fh))
            if y > fy + 1e-9:
                out.append((fx, fy, fw, y - fy))
            if y + h < fy + fh - 1e-9:
                out.append((fx, y + h, fw, fy + fh - y - h))
        res = []
        for i, a in enumerate(out):
            inside = any(i != j and a[0] >= b[0] - 1e-9 and a[1] >= b[1] - 1e-9 and a[0] + a[2] <= b[0] + b[2] + 1e-9
                         and a[1] + a[3] <= b[1] + b[3] + 1e-9 and (a != b or i > j) for j, b in enumerate(out))
            if not inside:
                res.append(a)
        return res

    for w, h in lst:
        for s in sheets:
            b = place(s, w, h)
            if b:
                s[:] = split(s, b[1], b[2], b[3], b[4])
                break
        else:
            s = [(0.0, 0.0, Wf, Lf)]
            b = place(s, w, h)
            s[:] = split(s, b[1], b[2], b[3], b[4])
            sheets.append(s)
    return len(sheets)


def strip_condition(items, W, L, gap, edge, rotations, across):
    """Условие договора: никакие две детали не встают рядом поперёк оси across ('x' или 'y')."""
    Wc, Lc = W - 2 * edge, L - 2 * edge
    par = set((int(round(float(r))) % 360 // 90) % 2 for r in rotations)
    acr = []
    for it in items:
        if not it["qty"]:
            continue
        ors = []
        for p in par:
            w, h = (it["w"], it["h"]) if p == 0 else (it["h"], it["w"])
            if w <= Wc + 1e-9 and h <= Lc + 1e-9:
                ors.append(w if across == "x" else h)
        acr.append((min(ors), it["qty"]))
    span = Wc if across == "x" else Lc
    for i, (a, qa) in enumerate(acr):
        if qa >= 2 and 2 * a + gap <= span + 1e-9:
            return False
        for j in range(i + 1, len(acr)):
            if a + acr[j][0] + gap <= span + 1e-9:
                return False
    return True


# --------------------------------------------------------------------------- A. решётки и их варианты

GRATES = [("A", 1006, 8), ("B", 1000, 16), ("C", 986, 8), ("D", 971, 16), ("E", 950, 24), ("F", 946, 24),
          ("G", 887, 8), ("H", 871, 4), ("I", 857, 28), ("J", 841, 8), ("K", 797, 24)]


def test_grates():
    S = "A решётки"
    print("A. Решётки и их варианты (симметрия, поворот, шум в габаритах)")
    base = [{"id": i, "w": w, "h": 1126, "qty": q} for i, w, q in GRATES]
    rng = random.Random(11)
    noisy = [{"id": i, "w": w + rng.uniform(-2e-6, 2e-6), "h": 1126 + rng.uniform(-2e-6, 2e-6), "qty": q}
             for i, w, q in GRATES]
    swapped = [{"id": i, "w": 1126, "h": w, "qty": q} for i, w, q in GRATES]
    cases = [
        ("как есть", base, 1250, 2500, (0, 90), 77, "1d-exact-y"),
        ("лист повёрнут 2500×1250", base, 2500, 1250, (0, 90), 77, "1d-exact-x"),
        ("детали повёрнуты, повороты 0/90", swapped, 1250, 2500, (0, 90), 77, "1d-exact-y"),
        ("габариты с шумом ±2e-6 (как из DXF)", noisy, 1250, 2500, (0, 90), 77, "1d-exact-y"),
        ("порядок поворотов (90, 0)", base, 1250, 2500, (90, 0), 77, "1d-exact-y"),
    ]
    for label, items, W, L, rot, want, method in cases:
        t0 = time.time()
        res = pack_rect(items, W, L, 2, 2, rotations=rot)
        dt = time.time() - t0
        errs = validate(res, items, W, L, 2, 2, rot)
        n = len(res["sheets"])
        print("  %-40s листов %d, граница %d, optimal %s, %s, %.2f с"
              % (label, n, res["lower_bound"], res["optimal"], res["method"], dt))
        for e in errs[:3]:
            fail(S, "%s: %s" % (label, e))
        if n != want or res["lower_bound"] != want or not res["optimal"]:
            fail(S, "%s: ожидалось %d листов (доказанный минимум), получено %d, граница %d, optimal %s"
                 % (label, want, n, res["lower_bound"], res["optimal"]))
        if res["method"] != method:
            fail(S, "%s: ожидался метод %s, получен %s" % (label, method, res["method"]))
        if dt >= 10:
            fail(S, "%s: %.1f с (договор: < 10 с)" % (label, dt))


# --------------------------------------------------------------------------- B. случайные задачи

def random_case(seed):
    rng = random.Random(seed)
    W, L = rng.choice([(1250, 2500), (2500, 1250), (1500, 3000), (1000, 2000), (1500, 6000), (600, 600),
                       (1250.5, 2500.25)])
    gap = rng.choice([0, 1, 2, 2.5, 5, 0.3])
    edge = rng.choice([0, 2, 5, 10, 0.5])
    rotations = rng.choice([(0, 90), (0,), (90,), (0, 180), (0, 90, 180, 270), (270,), (-90, 0)])
    prec = rng.choice([0, 0, 1, 2, 3, None])
    Wc, Lc = W - 2 * edge, L - 2 * edge
    kind = rng.choice(["small", "mixed", "wide", "long", "half", "tight"])

    def r(a, b):
        v = rng.uniform(a, b)
        return v if prec is None else (round(v, prec) if prec else int(round(v)))

    par = set((int(x) % 360 // 90) % 2 for x in rotations)
    items = []
    for k in range(rng.randint(1, 9)):
        if kind == "small":
            w, h = r(5, Wc / 4), r(5, Lc / 4)
        elif kind == "mixed":
            w, h = r(5, Wc), r(5, Lc)
        elif kind == "wide":
            w, h = r(Wc / 2 + 1, Wc), r(5, Lc / 2)
        elif kind == "long":
            w, h = r(5, Wc / 2), r(Lc / 2 + 1, Lc)
        elif kind == "half":
            w, h = r(Wc / 2 - 3, Wc / 2 + 3), r(Lc / 3 - 3, Lc / 2 + 3)
        else:
            kx, ky = rng.randint(1, 5), rng.randint(1, 6)
            w, h = (Wc + gap) / kx - gap, (Lc + gap) / ky - gap
            if prec is not None:
                w, h = math.floor(w * 10 ** prec) / 10 ** prec, math.floor(h * 10 ** prec) / 10 ** prec
        if w <= 0 or h <= 0:
            continue
        if not any(((w, h) if p == 0 else (h, w))[0] <= Wc and ((w, h) if p == 0 else (h, w))[1] <= Lc
                   for p in par):
            continue
        items.append({"id": "d%d" % k, "w": w, "h": h, "qty": rng.randint(1, 12)})
    return items, W, L, gap, edge, rotations, kind


def test_random(n=400):
    S = "B случайные"
    print("B. %d случайных задач: строгая проверка, граница против MaxRects, условие «одна полоса»" % n)
    bad = mr_better = 0
    gaps = 0
    t_all = time.time()
    for seed in range(n):
        items, W, L, gap, edge, rot, kind = random_case(seed)
        if not items:
            continue
        try:
            res = pack_rect(items, W, L, gap, edge, rotations=rot)
        except Exception as e:  # noqa: BLE001
            fail(S, "случай %d: исключение %s: %s" % (seed, type(e).__name__, e))
            bad += 1
            continue
        errs = validate(res, items, W, L, gap, edge, rot)
        total = sum(i["qty"] for i in items)
        ys = strip_condition(items, W, L, gap, edge, rot, "x")
        xs = strip_condition(items, W, L, gap, edge, rot, "y")
        if total >= 2 and ys and res["method"] != "1d-exact-y":
            errs.append("условие «одна полоса вдоль Y» выполнено, а метод %s" % res["method"])
        if total >= 2 and not ys and xs and res["method"] != "1d-exact-x":
            errs.append("условие «одна полоса вдоль X» выполнено, а метод %s" % res["method"])
        if res["method"].startswith("1d") and not (ys or xs):
            errs.append("метод %s, но две детали встают рядом поперёк" % res["method"])
        if res["method"].startswith("1d") and total <= 40 and not res["optimal"]:
            errs.append("малая одномерная задача (%d шт.) без доказанного минимума" % total)
        mr = maxrects(items, W, L, gap, edge, rot)
        if mr < res["lower_bound"]:
            errs.append("MaxRects уложил в %d листов < нижней границы %d — граница неверна" % (mr, res["lower_bound"]))
        if mr < len(res["sheets"]):
            mr_better += 1
        gaps += len(res["sheets"]) - res["lower_bound"]
        if errs:
            bad += 1
            for e in errs[:3]:
                fail(S, "случай %d (%s, %s×%s, зазор %s, кромка %s, повороты %s): %s"
                     % (seed, kind, W, L, gap, edge, rot, e))
    print("  нарушений: %d; MaxRects лучше в %d задачах; суммарный разрыв с границей %d листов; %.1f с"
          % (bad, mr_better, gaps, time.time() - t_all))


# --------------------------------------------------------------------------- C. «одна полоса» против точного решателя

def test_strip_exact():
    S = "C одна полоса"
    print("C. «Одна полоса на лист» против независимого точного решателя (повороты, зазор, кромка, предел узлов)")
    rng = random.Random(9)
    checked = bad = 0
    for _ in range(700):
        W, L = rng.choice([(1250, 2500), (1000, 2000), (1500, 3000)])
        gap, edge = rng.choice([0, 2, 3]), rng.choice([0, 2, 10])
        Wc, Lc = W - 2 * edge, L - 2 * edge
        rot = rng.choice([(0, 90), (0,), (90,)])
        items = []
        for k in range(rng.randint(2, 5)):
            a, b = rng.randint(Wc // 2 + 1, Wc), rng.randint(Lc // 7, min(Lc, Wc))
            w, h = (a, b) if rng.random() < .5 else (b, a)
            items.append({"id": k, "w": w, "h": h, "qty": rng.randint(1, 5)})
        lens = {}
        for it in items:
            c = [((it["w"], it["h"]) if r % 180 == 0 else (it["h"], it["w"])) for r in rot]
            lens[it["id"]] = [x for x in c if x[0] <= Wc and x[1] <= Lc]
        if any(not v for v in lens.values()) or any(2 * min(x[0] for x in v) + gap <= Wc for v in lens.values()):
            continue
        cnt = Counter()
        for it in items:
            cnt[min(x[1] for x in lens[it["id"]]) + gap] += it["qty"]
        sizes = sorted(cnt, reverse=True)
        opt = exact_bins(sizes, [cnt[s] for s in sizes], Lc + gap)
        checked += 1
        for nl in (2_000_000, 40, 0):
            res = pack_rect(items, W, L, gap, edge, rotations=rot, node_limit=nl)
            errs = validate(res, items, W, L, gap, edge, rot)
            n = len(res["sheets"])
            if res["method"] != "1d-exact-y":
                errs.append("метод %s" % res["method"])
            if res["lower_bound"] > opt:
                errs.append("граница %d больше точного минимума %d" % (res["lower_bound"], opt))
            if res["optimal"] and n != opt:
                errs.append("optimal, но листов %d при минимуме %d" % (n, opt))
            if nl == 2_000_000 and (n != opt or not res["optimal"]):
                errs.append("полный предел: листов %d (optimal %s), точный минимум %d" % (n, res["optimal"], opt))
            for sh in res["sheets"]:
                y = edge
                ps = sorted(sh, key=lambda p: p["y"])
                for p in ps:
                    if abs(p["x"] - edge) > TOL or abs(p["y"] - y) > TOL:
                        errs.append("детали не подряд от кромки")
                        break
                    y = p["y"] + p["h"] + gap
                if [p["h"] for p in ps] != sorted((p["h"] for p in ps), reverse=True):
                    errs.append("длины не по убыванию")
            if errs:
                bad += 1
                fail(S, "W=%s L=%s зазор %s кромка %s пов %s предел %d %r: %s" % (W, L, gap, edge, rot, nl, items, errs[:2]))
                break
    # строка вдоль X: детали длинные вдоль Y — подряд вдоль X от кромки, y = кромка
    items = [{"id": "дл%d" % k, "w": 200 + 61 * k, "h": 1400 + 13 * k, "qty": 3} for k in range(5)]
    res = pack_rect(items, 1250, 2500, 2, 2, rotations=(0,))
    errs = validate(res, items, 1250, 2500, 2, 2, (0,))
    if res["method"] != "1d-exact-x":
        errs.append("ожидался 1d-exact-x, получен %s" % res["method"])
    for sh in res["sheets"]:
        x = 2
        for p in sorted(sh, key=lambda p: p["x"]):
            if abs(p["y"] - 2) > TOL or abs(p["x"] - x) > TOL:
                errs.append("строка вдоль X не подряд от кромки")
                break
            x = p["x"] + p["w"] + 2
    for e in errs[:3]:
        fail(S, "строка вдоль X: " + e)
    print("  проверено задач: %d, расхождений: %d" % (checked, bad))


# --------------------------------------------------------------------------- D. ошибки ввода

def has_cyr(s):
    return any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in s)


def test_input():
    S = "D ввод"
    print("D. Ошибки ввода: ValueError по-русски, без падений другими исключениями")
    W, L = 1250, 2500
    one = [{"id": "x", "w": 100, "h": 50, "qty": 1}]
    must_raise = [
        ("деталь больше листа", [{"id": "Ребро-7", "w": 3000, "h": 3000, "qty": 1}], (W, L, 2, 2), {}, "Ребро-7"),
        ("не влезает без поворота", [{"id": "Полоса", "w": 2000, "h": 100, "qty": 1}], (W, L, 2, 2),
         {"rotations": (0,)}, "Полоса"),
        ("ширина 0", [{"id": "z", "w": 0, "h": 5, "qty": 1}], (W, L, 2, 2), {}, None),
        ("ширина NaN", [{"id": "z", "w": float("nan"), "h": 5, "qty": 1}], (W, L, 2, 2), {}, None),
        ("количество 2,5", [{"id": "z", "w": 5, "h": 5, "qty": 2.5}], (W, L, 2, 2), {}, None),
        ("количество −1", [{"id": "z", "w": 5, "h": 5, "qty": -1}], (W, L, 2, 2), {}, None),
        ("количество бесконечность", [{"id": "z", "w": 5, "h": 5, "qty": float("inf")}], (W, L, 2, 2), {}, None),
        ("нет поля w", [{"id": "z", "h": 5, "qty": 1}], (W, L, 2, 2), {}, None),
        ("зазор < 0", one, (W, L, -1, 2), {}, None),
        ("кромка съедает лист", one, (W, L, 2, 625), {}, None),
        ("поворот 45", one, (W, L, 2, 2), {"rotations": (45,)}, None),
        ("пустой список поворотов", one, (W, L, 2, 2), {"rotations": ()}, None),
    ]
    for label, items, args, kw, must_name in must_raise:
        try:
            pack_rect(items, *args, **kw)
            fail(S, "%s: нет ValueError" % label)
        except ValueError as e:
            if not has_cyr(str(e)):
                fail(S, "%s: сообщение не по-русски: %s" % (label, e))
            elif must_name and must_name not in str(e):
                fail(S, "%s: в сообщении нет id «%s»: %s" % (label, must_name, e))
            else:
                print("  %-28s → ValueError: %s" % (label, e))
        except Exception as e:  # noqa: BLE001
            fail(S, "%s: %s вместо ValueError: %s" % (label, type(e).__name__, e))
    # вырожденно малые габариты (шум геометрии): допустимы ValueError по-русски или верная раскладка — не падение
    for label, items, args in (
            ("деталь 1e-9×1e-9, зазор 0", [{"id": "пыль", "w": 1e-9, "h": 1e-9, "qty": 3}], (W, L, 0, 0)),
            ("полоса 1000×1e-9, зазор 0", [{"id": "нить", "w": 1000, "h": 1e-9, "qty": 3}], (W, L, 0, 0))):
        try:
            res = pack_rect(items, *args, rotations=(0,))
            for e in validate(res, items, args[0], args[1], args[2], args[3], (0,))[:2]:
                fail(S, "%s: %s" % (label, e))
            print("  %-28s → раскладка, листов %d" % (label, len(res["sheets"])))
        except ValueError as e:
            print("  %-28s → ValueError: %s" % (label, e))
        except Exception as e:  # noqa: BLE001
            fail(S, "%s: падение %s: %s" % (label, type(e).__name__, e))
    # допустимые формы ввода
    for label, items, kw in (
            ("количество 2.0", [{"id": "a", "w": 10, "h": 10, "qty": 2.0}], {}),
            ("количество 0 у большой детали", [{"id": "a", "w": 9000, "h": 10, "qty": 0}], {}),
            ("повороты (−90,)", [{"id": "a", "w": 100, "h": 30, "qty": 3}], {"rotations": (-90,)}),
            ("повороты (0,90,180,270)", [{"id": "a", "w": 100, "h": 30, "qty": 3}], {"rotations": (0, 90, 180, 270)}),
            ("повороты (180,)", [{"id": "a", "w": 100, "h": 30, "qty": 3}], {"rotations": (180,)}),
    ):
        try:
            res = pack_rect(items, W, L, 2, 2, **kw)
            rot = kw.get("rotations", (0, 90))
            for e in validate(res, items, W, L, 2, 2, rot)[:2]:
                fail(S, "%s: %s" % (label, e))
        except Exception as e:  # noqa: BLE001
            fail(S, "%s: %s: %s" % (label, type(e).__name__, e))


# --------------------------------------------------------------------------- E. сетка заготовок, нарезанных из листа ровно

def test_exact_grid():
    S = "E сетка"
    print("E. Лист, разрезанный на kx×ky равных заготовок (детали ровно по полю с зазором) — 1 лист")
    # минимальный пример: 3×5 заготовок 414×497,6 на листе 1250×2500, зазор 2, кромка 2:
    # x = 2, 418, 834 (834+414 = 1248 = W−кромка); y = 2, 501,6, 1001,2, 1500,8, 2000,4 (+497,6 = 2498 = L−кромка)
    for w, h, n, want in ((414, 497.6, 15, 1), (414, 497.6, 150, 10), (414, 497, 15, 1)):
        items = [{"id": "заг", "w": w, "h": h, "qty": n}]
        res = pack_rect(items, 1250, 2500, 2, 2, rotations=(0,))
        errs = validate(res, items, 1250, 2500, 2, 2, (0,))
        print("  %g×%g × %d: листов %d (по листам %s), граница %d, %s"
              % (w, h, n, len(res["sheets"]), [len(s) for s in res["sheets"]][:4], res["lower_bound"], res["method"]))
        for e in errs[:2]:
            fail(S, e)
        if len(res["sheets"]) != want:
            fail(S, "%g×%g × %d шт.: сетка 3×5 = 15 шт. на лист, нужно %d листов, получено %d"
                 % (w, h, n, want, len(res["sheets"])))
    total = bad = 0
    examples = []
    for W, L, gap, edge in ((1250, 2500, 2, 2), (1250, 2500, 0, 0), (1500, 3000, 2, 2), (1250, 2500, 1.5, 2),
                            (1500, 6000, 2, 2), (1000, 2000, 3, 5)):
        Wc, Lc = W - 2 * edge, L - 2 * edge
        for kx in range(1, 6):
            for ky in range(1, 9):
                w, h = (Wc + gap) / kx - gap, (Lc + gap) / ky - gap
                if abs(round(w, 3) - w) > 1e-9 or abs(round(h, 3) - h) > 1e-9:
                    continue  # не кратно 0,001 мм — пропуск
                w, h = round(w, 3), round(h, 3)
                total += 1
                res = pack_rect([{"id": "g", "w": w, "h": h, "qty": kx * ky}], W, L, gap, edge, rotations=(0,))
                if len(res["sheets"]) != 1:
                    bad += 1
                    if len(examples) < 4:
                        examples.append("%s×%s зазор %s кромка %s: %g×%g ×%d → %d листа"
                                        % (W, L, gap, edge, w, h, kx * ky, len(res["sheets"])))
    print("  сеток проверено %d, не уложено в 1 лист: %d" % (total, bad))
    if bad:
        fail(S, "%d из %d сеток не уложены в 1 лист, напр.: %s" % (bad, total, "; ".join(examples)))


# --------------------------------------------------------------------------- F. полосы разной ориентации

def test_mixed_strips():
    S = "F полосы"
    print("F. Двухэтапная раскладка с полосами разной ориентации")
    # 4 детали 510×300 на 1000×1000 (зазор 0, кромка 0): полоса x 0…510 — три детали 510×300 (y 0, 300, 600),
    # полоса x 510…810 — одна деталь повёрнута (300×510). Это двухэтапный гильотинный раскрой — 1 лист.
    items = [{"id": "п", "w": 510, "h": 300, "qty": 4}]
    res = pack_rect(items, 1000, 1000, 0, 0)
    for e in validate(res, items, 1000, 1000, 0, 0, (0, 90))[:2]:
        fail(S, e)
    print("  510×300 × 4 на 1000×1000: листов %d %s, граница %d, %s"
          % (len(res["sheets"]), [len(s) for s in res["sheets"]], res["lower_bound"], res["method"]))
    if len(res["sheets"]) != 1:
        fail(S, "510×300 × 4 на 1000×1000: двухэтапная раскладка в 1 лист существует, получено %d листа"
             % len(res["sheets"]))


# --------------------------------------------------------------------------- G. детерминированность

DET_SNIPPET = r"""
import sys, json, random, hashlib
sys.path.insert(0, %r)
from sheet_nest.pack_rect import pack_rect
out = []
for s in range(15):
    rng = random.Random(s)
    items = [{"id": "дет-%%d-%%s" %% (k, rng.choice("абв")), "w": round(rng.uniform(20, 1200), rng.choice([0, 1, 2])),
              "h": round(rng.uniform(20, 2400), rng.choice([0, 1])), "qty": rng.randint(1, 8)} for k in range(rng.randint(1, 10))]
    out.append(pack_rect(items, 1250, 2500, 2, 2, rotations=rng.choice([(0, 90), (0,)])))
print(hashlib.md5(json.dumps(out, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
""" % ROOT


def test_determinism():
    S = "G детерминированность"
    print("G. Детерминированность: повтор и разные PYTHONHASHSEED")
    items, W, L, gap, edge, rot, _ = random_case(12345)
    r1 = pack_rect(items, W, L, gap, edge, rotations=rot)
    r2 = pack_rect(items, W, L, gap, edge, rotations=rot)
    if r1 != r2:
        fail(S, "повторный вызов дал другой результат")
    hashes = set()
    for hs in ("0", "1", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=hs)
        out = subprocess.run([sys.executable, "-c", DET_SNIPPET], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
        if out.returncode != 0:
            fail(S, "подпроцесс упал: %s" % out.stderr[-300:])
            return
        hashes.add(out.stdout.strip())
    if len(hashes) != 1:
        fail(S, "результат зависит от PYTHONHASHSEED: %r" % hashes)
    else:
        print("  одинаково при PYTHONHASHSEED 0/1/4242")


# --------------------------------------------------------------------------- H. время

def test_time():
    S = "H время"
    print("H. Время: 200 случайных деталей < 30 с")
    # 200 деталей с размерами до 0,01 мм (как из DXF), равномерно по листу, повороты 0/90
    rng = random.Random(8)
    items = []
    for k in range(200):
        w = round(rng.uniform(20, 1240), 2)
        h = round(rng.uniform(20, 2490), 2)
        items.append({"id": k, "w": w, "h": h, "qty": 1})
    t0 = time.time()
    res = pack_rect(items, 1250, 2500, 2, 2, rotations=(0, 90))
    dt = time.time() - t0
    for e in validate(res, items, 1250, 2500, 2, 2, (0, 90))[:2]:
        fail(S, e)
    print("  200 деталей (0,01 мм, Random(8)): листов %d, граница %d, %s, %.1f с"
          % (len(res["sheets"]), res["lower_bound"], res["method"], dt))
    if dt >= 30:
        fail(S, "200 случайных деталей: %.1f с (договор: < 30 с)" % dt)


def main():
    t0 = time.time()
    test_grates()
    test_random()
    test_strip_exact()
    test_input()
    test_exact_grid()
    test_mixed_strips()
    test_determinism()
    if os.environ.get("ADV_SKIP_SLOW") != "1":
        test_time()
    else:
        print("H. Время — пропущено (ADV_SKIP_SLOW=1)")
    print("—" * 60)
    if FAILS:
        secs = Counter(s for s, _ in FAILS)
        print("НЕ ПРОШЛО: %d ошибок (%s), %.1f с" % (len(FAILS), ", ".join("%s: %d" % kv for kv in sorted(secs.items())),
                                                     time.time() - t0))
        return 1
    print("ВСЁ ПРОШЛО (%.1f с)" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
