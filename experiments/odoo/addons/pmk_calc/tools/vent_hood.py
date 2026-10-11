# -*- coding: utf-8 -*-
"""Генератор развёрток вентзонта v3 — по деталям, константы сняты с 25 эталонов КОМПАС.

Детали: 2 крышки (шеврон с вырезом кончика), торцевые панели (V-конец + пазы),
средние панели (фальц с двух сторон). Все мелкие элементы — постоянные мм,
с шириной меняются только длинные кромки.

Запуск:  python3 vent_hood.py 850 3650 [-t 0.5] [-c 8017] [out.dxf]
"""
import math, sys

# ---------- константы (разброс по 25 эталонам = 0) ----------
ACR_C   = 369.289            # across = (Ш + ACR_C) / cos30
TV      = 0.43328            # глубина V / (Hh - 40)
V_TOP   = 40.0               # V начинается в 40 мм от карниза (23 верт. + фаска 6x17)
CAP_A   = math.radians(52.66712)   # наклон диагонали крышки
TIP_DX, TIP_DY = 8.92639, 21.27548 # вырез кончика крышки
D_MINUS = 21.84062           # диагональ крышки = V-кромка - D_MINUS
CLIP_TIP, CLIP_OFF = 3.87238, 10.0   # клёпка Ø4.5: от конца диагонали у кончика / от кромки
SLOT_APEX, SLOT_OFF = 15.37570, 10.0 # паз: от апекса V / от V-кромки
SLOT_L, SLOT_R = 4.5, 2.25           # паз-овал: прямая 4.5, радиус 2.25
NEST    = 14.383             # апекс V − правый край крышки (крышка вложена в V)
CORNER = [(-22.17152, -3.90944), (-45.17152, -3.90944), (-62.17152, -9.90944)]  # угол крышки: фаска 17x6 + полка 23 (все ширины)
LAP_X   = (65.0, 105.0)      # пара лапок Ø7: от кромки (карниза тела / наружной кромки крышки)
SVES    = 150.0
FALC, FALC_CUT = 14.0, 42.0  # фальц +14 на сторону, вырез 42x14 у углов
RIDGE_N = 15.0               # V-вырез конька на стыке: глубина 15, высота 30
SHEET_LIM, BEND_LIM = 1240.0, 2500.0
GAP = 100.0                  # зазор раскладки между панелями
CLIP_MAX = 150.0             # клёпок на кромку столько, чтобы шаг ≤150 (совпало со всеми 25 эталонами)
LAP_MAX, LAP_JOINT = 350.0, 60.0   # лапки тела: шаг ≤350, не ближе 60 мм к стыку фальца
CAP_PAIR_W, CAP_CORNER, CAP_STEP = 310.0, 175.0, 400.0  # лапки крышки: пар = Ш/310, от угла шахты ≥175, шаг ≤400

# шаг клёпок известных ширин — ровно как в эталонах (чтобы новые детали стыковались со старыми);
# число клёпок совпадает с правилом CLIP_MAX. 1250 — по правилу (решение Антона 11.10: 8 шт, шаг 134)
CLIP_TABLE = {400: 134.0, 550: 125.0, 600: 132.5, 800: 130.0, 850: 137.0, 900: 144.0,
              1000: 130.0, 1100: 140.0, 1150: 146.0, 1300: 139.0}


W_TESTED = (200, 1350)           # ряд ширин, проверенный на геометрию и сверенный с эталонами


def geometry(W, L):
    if W <= 0 or L <= 0:
        raise ValueError("размеры шахты должны быть > 0")
    if W > L:
        raise ValueError("ширина шахты %d больше длины %d: «вш Ш×Д» — Ш короткая сторона, "
                         "конёк идёт вдоль длинной; поменяйте местами" % (W, L))
    g = {"W": W, "L": L, "flags": []}
    if not (W_TESTED[0] <= W <= W_TESTED[1]):
        g["flags"].append("ширина %d вне проверенного ряда %d–%d" % (W, *W_TESTED))
    across = (W + ACR_C) / (math.sqrt(3) / 2)
    Hh = across / 2
    cyV = Hh - V_TOP
    dV = TV * cyV
    vlen = math.hypot(dV, cyV)
    D = vlen - D_MINUS
    # клёпки: первая у кончика/апекса фиксирована, дальше равный шаг; крышка и тело — один шаг
    n = max(2, math.ceil((vlen - 37.38) / CLIP_MAX) + 1)
    if W in CLIP_TABLE:
        p = CLIP_TABLE[W]
    else:
        p = round((vlen - 37.38) / (n - 1) * 2) / 2
        g["flags"].append("шаг клёпок по правилу (нет эталона ширины)")
    caplaps = cap_laps_rule(W)
    body = L + 2 * SVES
    poperek = across > SHEET_LIM
    lim = SHEET_LIM if poperek else BEND_LIM
    N = max(1, math.ceil(body / lim))
    while N > 1 and body / N + 2 * FALC > lim:
        N += 1
    if N == 1 and body > lim:
        N = 2
    Pn = body / N
    g.update(across=across, Hh=Hh, cyV=cyV, dV=dV, vlen=vlen, D=D, n=n, p=p, caplaps=caplaps,
             body=body, poperek=poperek, lim=lim, N=N, Pn=Pn)
    g["cols"] = body_lap_columns(L, N, Pn)
    return g


def cap_laps_rule(W):
    """Пары лапок на крышке (по короткой стороне шахты): пар = Ш/310, равномерно,
    крайние не ближе 175 мм к углу шахты, шаг между парами ≤400."""
    c = max(1, int(W // CAP_PAIR_W))
    if c == 1:
        return [0.0]
    step = min(CAP_STEP, (W - 2 * CAP_CORNER) / (c - 1))
    return [(i - (c - 1) / 2) * step for i in range(c)]


def body_lap_columns(L, N, Pn):
    """Ряды лапок тела в координатах зонта, равномерно: крайние 150 от торцов шахты.
    Одна панель — шаг ≤350. Несколько — на каждой панели ряд на каждые ≤350 мм
    (без 50 мм у каждого стыка). Ряд ближе LAP_JOINT к шву фальца — добавить ряд и раздвинуть."""
    S = L - 2 * SVES
    if S <= 0:
        return [SVES + L / 2]
    joints = [Pn * i for i in range(1, N)]
    if N == 1:
        k = max(1, math.ceil(S / LAP_MAX - 1e-9))
    else:
        C = sum(math.ceil((Pn - 50.0 * ((i > 0) + (i < N - 1))) / LAP_MAX - 1e-9) for i in range(N))
        k = max(1, C - 1)
    while True:
        cols = [2 * SVES + S * i / k for i in range(k + 1)]
        if all(abs(c - j) >= LAP_JOINT for c in cols for j in joints):
            return cols
        k += 1


# ---------- построение деталей (локальные координаты, ось Y = конёк) ----------
def panel(g, i):
    """Панель i (0..N-1): контур, лапки, пазы. x=0 — номинальное начало панели."""
    Hh, dV, N, Pn = g["Hh"], g["dV"], g["N"], g["Pn"]
    X0, X1 = 0.0, Pn
    left_v, right_v = (i == 0), (i == N - 1)
    if left_v:
        left = [(X0 + 6, Hh), (X0, Hh - 17), (X0, Hh - V_TOP), (X0 + dV, 0.0),
                (X0, -Hh + V_TOP), (X0, -Hh + 17), (X0 + 6, -Hh)]
    else:
        left = [(X0, Hh), (X0, Hh - FALC_CUT), (X0 - FALC, Hh - FALC_CUT), (X0 - FALC, RIDGE_N),
                (X0 + 1.0, 0.0), (X0 - FALC, -RIDGE_N), (X0 - FALC, -Hh + FALC_CUT),
                (X0, -Hh + FALC_CUT), (X0, -Hh)]
    if right_v:
        right = [(X1 - 6, -Hh), (X1, -Hh + 17), (X1, -Hh + V_TOP), (X1 - dV, 0.0),
                 (X1, Hh - V_TOP), (X1, Hh - 17), (X1 - 6, Hh)]
    else:
        right = [(X1, -Hh), (X1, -Hh + FALC_CUT), (X1 + FALC, -Hh + FALC_CUT), (X1 + FALC, -RIDGE_N),
                 (X1 - 1.0, 0.0), (X1 + FALC, RIDGE_N), (X1 + FALC, Hh - FALC_CUT),
                 (X1, Hh - FALC_CUT), (X1, Hh)]
    poly = left + right
    holes = []
    x_from = i * Pn
    for c in g["cols"]:
        if x_from - 1e-6 <= c < x_from + Pn - 1e-6 or (i == N - 1 and abs(c - (x_from + Pn)) < 1e-6):
            for yy in (Hh - LAP_X[0], Hh - LAP_X[1], -Hh + LAP_X[0], -Hh + LAP_X[1]):
                holes.append((c - x_from, yy, 7.0))
    slots = []
    for side, on in (("L", left_v), ("R", right_v)):
        if not on:
            continue
        sx = 1 if side == "L" else -1
        xe = X0 if side == "L" else X1
        A = (xe + sx * dV, 0.0)
        for sy in (1, -1):
            C = (xe, sy * g["cyV"])
            ux, uy = (C[0] - A[0]) / g["vlen"], (C[1] - A[1]) / g["vlen"]
            nx, ny = sx * g["cyV"] / g["vlen"], sy * g["dV"] / g["vlen"]   # нормаль внутрь металла
            for k in range(g["n"]):
                s = SLOT_APEX + k * g["p"]
                cx = A[0] + ux * s + nx * SLOT_OFF
                cy = A[1] + uy * s + ny * SLOT_OFF
                slots.append(((cx, cy), (ux, uy)))
    return {"poly": poly, "holes": holes, "slots": slots}


def cap(g):
    """Левая крышка: x=0 — правый край (концы диагоналей у кончика), кончик смотрит вправо."""
    D, a = g["D"], CAP_A
    du = (-math.cos(a), math.sin(a))
    v3 = (0.0, TIP_DY)
    v2 = (v3[0] + du[0] * D, v3[1] + du[1] * D)
    up = [v2] + [(v2[0] + dx, v2[1] + dy) for dx, dy in CORNER]   # v2 → ... → верх наружной кромки
    lo = [(x, -y) for x, y in up]
    poly = [v3] + up + lo[::-1] + [(0.0, -TIP_DY), (-TIP_DX, 0.0)]
    holes = []
    xo = up[-1][0]
    for dy in g["caplaps"]:
        for lx in LAP_X:
            holes.append((xo + lx, dy, 7.0))
    nin = (-math.sin(a), -math.cos(a))
    for k in range(g["n"]):
        s = CLIP_TIP + k * g["p"]
        cx = v3[0] + du[0] * s + nin[0] * CLIP_OFF
        cy = v3[1] + du[1] * s + nin[1] * CLIP_OFF
        holes.append((cx, cy, 4.5))
        holes.append((cx, -cy, 4.5))
    return {"poly": poly, "holes": holes, "slots": []}


def mirror(part):
    return {"poly": [(-x, y) for x, y in part["poly"]][::-1],
            "holes": [(-x, y, d) for x, y, d in part["holes"]],
            "slots": [((-c[0], c[1]), (-u[0], u[1])) for c, u in part["slots"]]}


def shift(part, dx):
    return {"poly": [(x + dx, y) for x, y in part["poly"]],
            "holes": [(x + dx, y, d) for x, y, d in part["holes"]],
            "slots": [((c[0] + dx, c[1]), u) for c, u in part["slots"]]}


def bbox_x(part):
    xs = [x for x, _ in part["poly"]]
    return min(xs), max(xs)


def hood(W, L):
    g = geometry(W, L)
    layout = []
    x = 0.0
    panels = []
    for i in range(g["N"]):
        p = panel(g, i)
        lo, hi = bbox_x(p)
        p = shift(p, x - lo)
        panels.append((i, p, x - lo))
        x = x - lo + hi + GAP
    c = cap(g)
    # левая крышка вложена в V первой панели
    apexL = panels[0][2] + g["dV"]
    layout.append(("cap", shift(c, apexL - NEST)))
    for i, p, _ in panels:
        layout.append(("end" if i in (0, g["N"] - 1) else "mid", p))
    last_off = panels[-1][2]
    apexR = last_off + g["Pn"] - g["dV"]
    layout.append(("cap", shift(mirror(c), apexR + NEST)))
    g["parts"] = layout
    return g


# ---------- DXF (R12: LINE / ARC / CIRCLE) ----------
def slot_entities(c, u):
    ux, uy = u
    nx, ny = -uy, ux
    e1 = (c[0] + ux * SLOT_L / 2, c[1] + uy * SLOT_L / 2)
    e0 = (c[0] - ux * SLOT_L / 2, c[1] - uy * SLOT_L / 2)
    th = math.degrees(math.atan2(uy, ux))
    ents = [("L", (e0[0] + nx * SLOT_R, e0[1] + ny * SLOT_R), (e1[0] + nx * SLOT_R, e1[1] + ny * SLOT_R)),
            ("L", (e0[0] - nx * SLOT_R, e0[1] - ny * SLOT_R), (e1[0] - nx * SLOT_R, e1[1] - ny * SLOT_R)),
            ("A", e1, SLOT_R, th - 90, th + 90),
            ("A", e0, SLOT_R, th + 90, th + 270)]
    return ents


def to_dxf(g):
    s = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4",
         "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    def line(a, b):
        s.extend(["0", "LINE", "8", "0", "10", f"{a[0]:.4f}", "20", f"{a[1]:.4f}", "30", "0",
                  "11", f"{b[0]:.4f}", "21", f"{b[1]:.4f}", "31", "0"])
    for kind, part in g["parts"]:
        P = part["poly"]
        for i in range(len(P)):
            line(P[i], P[(i + 1) % len(P)])
        for x, y, d in part["holes"]:
            s.extend(["0", "CIRCLE", "8", "0", "10", f"{x:.4f}", "20", f"{y:.4f}", "30", "0", "40", f"{d / 2:.4f}"])
        for c, u in part["slots"]:
            for e in slot_entities(c, u):
                if e[0] == "L":
                    line(e[1], e[2])
                else:
                    _, cc, r, a0, a1 = e
                    s.extend(["0", "ARC", "8", "0", "10", f"{cc[0]:.4f}", "20", f"{cc[1]:.4f}", "30", "0",
                              "40", f"{r:.4f}", "50", f"{a0 % 360:.4f}", "51", f"{a1 % 360:.4f}"])
    s += ["0", "ENDSEC", "0", "EOF"]
    return "\n".join(s) + "\n"


def _area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2


# ---------- материал: толщина и цвет ----------
RHO = 7.85                       # кг/м² на 1 мм толщины стали
SHEET_W, KERF = 1250.0, 10.0     # лист 1250 (полезно SHEET_LIM=1240), зазор между деталями в раскладке
T_MIN, T_MAX = 0.4, 1.0          # толщины, для которых годятся шаблоны тонкой оцинковки


def material(t=None, color=None):
    """t — толщина, мм (None = не задана); color — None/'оцинковка' или код RAL ('8017', 'RAL 8017')."""
    import re
    m = {"t_mm": t, "coating": None, "warnings": []}
    c = (color or "").strip()
    if c.lower() in ("", "оц", "оцинковка", "zn", "без покрытия"):
        m["name"] = "Лист оцинкованный"
    else:
        r = re.fullmatch(r"(?i)\s*(?:RAL)?\s*(\d{4})\s*", c)
        m["coating"] = ("RAL " + r.group(1)) if r else c
        m["name"] = "Лист оцинкованный с полимерным покрытием " + m["coating"]
        m["warnings"].append("окрашенный лист: все детали резать лицевой стороной в одну сторону, "
                             "НЕ переворачивать при раскладке — левая/правая крышки и торцевые панели зеркальные")
    if t is None:
        m["warnings"].append("толщина не задана — масса не считается")
    elif not (T_MIN <= t <= T_MAX):
        m["warnings"].append("толщина %.2f вне %.1f–%.1f мм: шаблоны развёрток сделаны под тонкую оцинковку, "
                             "проверить припуски на гиб" % (t, T_MIN, T_MAX))
    m["full_name"] = m["name"] + (" %.2g мм" % t if t else "")
    return m


def _bbox(p):
    xs = [x for x, _ in p["poly"]]; ys = [y for _, y in p["poly"]]
    return max(xs) - min(xs), max(ys) - min(ys)


def strip_layout(g):
    """Расход листа 1250 при простой раскладке без вложения (зазор KERF): панели — по одной в ряд,
    крышки — парой (рядом или друг за другом, что короче). Возвращает длину ленты, мм, и ряды."""
    along = 0.0; rows = []
    for kind, p in g["parts"]:
        if kind == "cap":
            continue
        w, h = _bbox(p)
        a, b = (w, h) if w <= SHEET_LIM else (h, w)
        rows.append(("панель", a, b)); along += b + KERF
    cw, ch = _bbox([p for k, p in g["parts"] if k == "cap"][0])
    opts = [(2 * cw + KERF, ch),        # две рядом
            (ch, 2 * cw + KERF),        # повёрнуты, друг за другом
            (cw, 2 * ch + KERF),        # по одной в ряд (широкие крышки)
            (2 * ch + KERF, cw)]        # повёрнуты, рядом
    opts = [o for o in opts if o[0] <= SHEET_LIM]
    if not opts:
        raise ValueError("крышка %.0f×%.0f не помещается на лист %d" % (cw, ch, SHEET_W))
    best = min(opts, key=lambda o: o[1])
    rows.append(("крышки ×2", best[0], best[1])); along += best[1]
    return along, rows


def spec(g, t=None, color=None):
    """Спецификация на один зонт: материал, детали, лапки, клёпки, металл, масса."""
    names = {"cap": "Крышка торцевая", "end": "Панель торцевая", "mid": "Панель средняя"}
    if g["N"] == 1:
        names["end"] = "Тело зонта"
    rows = {}
    slot_area = SLOT_L * 2 * SLOT_R + math.pi * SLOT_R ** 2
    metal = 0.0
    for kind, p in g["parts"]:
        xs = [x for x, _ in p["poly"]]; ys = [y for _, y in p["poly"]]
        size = (round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1))
        net = _area(p["poly"]) - sum(math.pi * (d / 2) ** 2 for *_, d in p["holes"]) - slot_area * len(p["slots"])
        metal += net
        key = (names[kind], size)
        rows.setdefault(key, {"name": names[kind], "size_mm": list(size), "qty": 0, "area_m2_each": round(net / 1e6, 4)})
        rows[key]["qty"] += 1
    n7 = sum(1 for _, p in g["parts"] for h in p["holes"] if h[2] == 7.0)
    n45 = sum(1 for _, p in g["parts"] for h in p["holes"] if h[2] == 4.5)
    mat = material(t, color)
    along, rows_l = strip_layout(g)
    strip_m2 = along * SHEET_W / 1e6
    gross = sum(w * h for w, h in (_bbox(p) for _, p in g["parts"])) / 1e6
    s = {"hood": "вш %dх%d" % (g["W"], g["L"]), "material": mat, "parts": list(rows.values()),
         "lapki": n7 // 2, "lapki_holes_d7": n7, "klepki": n45,
         "metal_net_m2": round(metal / 1e6, 3), "metal_blanks_m2": round(gross, 3),
         "sheet_1250_m": round(along / 1000, 2), "sheet_1250_m2": round(strip_m2, 2),
         "sheet_layout": [{"what": w, "across_mm": round(a), "along_mm": round(b)} for w, a, b in rows_l],
         "panels": g["N"], "layout": "поперёк листа" if g["poperek"] else "вдоль листа",
         "rule_flags": g["flags"]}
    if t:
        s["mass_net_kg"] = round(metal / 1e6 * RHO * t, 1)        # масса деталей
        s["mass_sheet_kg"] = round(strip_m2 * RHO * t, 1)         # масса листа по расходу
    return s


def summary(g, t=None, color=None):
    s = spec(g, t, color)
    parts = "; ".join("%s %s×%s — %d шт" % (r["name"], r["size_mm"][0], r["size_mm"][1], r["qty"]) for r in s["parts"])
    mass = (" | масса деталей %.1f кг, листа по расходу %.1f кг" % (s["mass_net_kg"], s["mass_sheet_kg"])) if t else ""
    return ("%s — %s (%s, панелей %d): %s | лапок %d шт, клёпок %d шт | металл нетто %.3f м², лист 1250: %.2f м%s"
            % (s["hood"], s["material"]["full_name"], s["layout"], s["panels"], parts, s["lapki"], s["klepki"],
               s["metal_net_m2"], s["sheet_1250_m"], mass))


def out_name(W, L, t=None, color=None):
    mat = material(t, color)
    tag = ("_t%g" % t if t else "") + ("_" + mat["coating"].replace(" ", "") if mat["coating"] else "_оц")
    return "vsh_%dx%d%s.dxf" % (W, L, tag)


if __name__ == "__main__":
    import json, argparse
    ap = argparse.ArgumentParser(description="Развёртка вентзонта: DXF + спецификация")
    ap.add_argument("W", type=int, help="ширина шахты, мм")
    ap.add_argument("L", type=int, help="длина шахты, мм")
    ap.add_argument("out", nargs="?", help="файл DXF (по умолчанию vsh_ШxД_t<толщ>_<цвет>.dxf)")
    ap.add_argument("-t", "--thickness", type=float, help="толщина листа, мм (например 0.55)")
    ap.add_argument("-c", "--color", help="цвет: оцинковка (по умолчанию) или код RAL, например 8017")
    a = ap.parse_intermixed_args()
    try:
        g = hood(a.W, a.L)
    except ValueError as e:
        print("ОШИБКА:", e)
        sys.exit(2)
    out = a.out or out_name(a.W, a.L, a.thickness, a.color)
    open(out, "w").write(to_dxf(g))
    sp = spec(g, a.thickness, a.color)
    json.dump(sp, open(out[:-4] + ".spec.json", "w"), ensure_ascii=False, indent=1)
    print(summary(g, a.thickness, a.color))
    for f in g["flags"] + sp["material"]["warnings"]:
        print("  ⚠", f)
