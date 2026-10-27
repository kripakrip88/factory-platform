# -*- coding: utf-8 -*-
"""Проверка генератора в.2 — отдельный скрипт (не тест Odoo): python3 -I test_v2.py [папка]

(а) rules_v2 повторяет все 19 развёрток Игоря до 0,01 мм: 8 полухомутов, 8 корпусов КХ, корпус КП 57,
    2 корпуса ОПП1 (числа — из DXF Игоря, ~/Projects/opory_ost36-146/razvertki_2710/RULES.md и rules.py),
    плюс участки (прямые/гибы/дуга), отверстия хомута, ширина и фаски рёбер;
(б) рисует каждую марку, которую умеет генератор (КХ А12 и КП А12 всех Дн, ОПП1 Н 100 и 70 всех Дн),
    проверяет PDF/PNG/DXF и что размеры развёрток в DXF (слой CUT) равны rules_v2.
Нужны только Python 3 и PyMuPDF. Выход с кодом 1 при любой ошибке.
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import drawings  # noqa: E402
import rules_v2 as rv  # noqa: E402

TOL = 0.01

# ── Игорь, DXF 26.10.2026 (RULES.md, разделы 2–4; fit_clamp.py IG; corpus_rib.py IGC/IGR) ──
# Полухомут: Дн → (прямой участок лапки, зона гиба, дуга, развёртка, отверстие от торца)
IG_CLAMP = {57: (33.794, 9.784, 71.976, 159.131, 20), 108: (33.547, 14.012, 143.125, 238.243, 20),
            159: (45.065, 14.748, 217.792, 337.418, 25), 219: (56.523, 18.718, 303.502, 453.984, 30),
            325: (54.983, 19.679, 468.086, 617.410, 30), 426: (56.439, 20.184, 625.690, 778.936, 30),
            530: (65.751, 24.291, 780.210, 960.294, 35), 630: (65.417, 24.602, 936.631, 1116.669, 35)}
# Корпус: (вид, Дн) → (стенка прямая, зона гиба, дно прямое, развёртка U, h1, уголок или None)
IG_CORP = {("kx", 57): (95.5, 8.953, 35.0, 243.907, 103, 121.954), ("kx", 108): (99.5, 8.953, 65.0, 281.907, 107, 140.954),
           ("kx", 159): (93.5, 8.953, 65.0, 269.907, 101, 134.954), ("kx", 219): (140.5, 8.954, 185.0, 483.907, 148, None),
           ("kx", 325): (111.0, 11.938, 180.0, 425.876, 121, None), ("kx", 426): (96.0, 17.907, 170.0, 397.814, 111, None),
           ("kx", 530): (116.0, 17.907, 270.0, 537.814, 131, None), ("kx", 630): (108.0, 17.907, 270.0, 521.814, 123, None),
           ("kp", 57): (102.5, 8.953, 35.0, 257.907, 110, 128.954)}
# ОПП1: Дн → (развёртка, стенка прямая, зона гиба, дно, ребро длина × высота, фаска)
IG_OPP1 = {18: (301.907, 99.5, 8.954, 85.0, 91, 57, 5), 32: (315.907, 106.5, 8.954, 85.0, 91, 57, 5)}
# Рёбра: (вид, Дн) → (ширина, фаска)
IG_RIB = {("kp", 57): (43, 5), ("kx", 57): (43, 5), ("kx", 108): (73, 5), ("kx", 159): (73, 5), ("kx", 219): (191, 5),
          ("kx", 325): (189, 6), ("kx", 426): (185, 8), ("kx", 530): (284, 8), ("kx", 630): (284, 8)}

errors = []


def near(name, got, want, tol=TOL):
    if abs(got - want) > tol:
        errors.append("%s: %.3f вместо %.3f (Δ %+.3f)" % (name, got, want, got - want))
        return False
    return True


# ─── (а) 19 развёрток Игоря ──────────────────────────────────────────────
def part_a():
    ok = 0
    for dn, (flat, zone, arc, total, hole) in IG_CLAMP.items():
        cl = drawings.geometry("kx", dn, "А12")["clamp"]
        good = near("полухомут %s: развёртка" % dn, cl["total"], total)
        for nm, got, want in (("лапка", cl["flat"], flat), ("гиб", cl["zone"], zone), ("дуга", cl["arc"], arc),
                              ("отв. от торца", cl["hole"], hole)):
            near("полухомут %s: %s" % (dn, nm), got, want)
        ok += good
    for (kind, dn), (wall, zone, bottom, total, h1, angle) in IG_CORP.items():
        if kind == "kx" and rv.H_TO != "pipe":
            print("  пропуск КХ %s: H_TO = %r — у Игоря h до низа трубы" % (dn, rv.H_TO))
            continue
        geo = drawings.geometry(kind, dn, "А12")
        c = geo["corpus"]
        if geo["h1"] != h1:
            errors.append("корпус %s %s: h1 %s вместо %s" % (kind, dn, geo["h1"], h1))
        good = near("корпус %s %s: развёртка" % (kind, dn), c["total"], total)
        for nm, got, want in (("стенка", c["wall"], wall), ("гиб", c["zone"], zone), ("дно", c["bottom"], bottom)):
            near("корпус %s %s: %s" % (kind, dn, nm), got, want)
        if angle:
            good &= near("корпус %s %s: уголок" % (kind, dn), c["angle"], angle) and c["angles"]
        elif c["angles"]:
            errors.append("корпус %s %s: уголки при B %s" % (kind, dn, geo["B"]))
        ok += good
    for dn, (total, wall, zone, bottom, rl, rh, ch) in IG_OPP1.items():
        geo = drawings.geometry("opp1", dn, "100")
        c = geo["corpus"]
        good = near("ОПП1-100.%s: развёртка" % dn, c["total"], total)
        for nm, got, want in (("стенка", c["wall"], wall), ("гиб", c["zone"], zone), ("дно", c["bottom"], bottom),
                              ("ребро L", geo["rib"]["l"], rl), ("ребро H", geo["rib"]["h"], rh),
                              ("ребро фаска", geo["rib"]["ch"], ch)):
            near("ОПП1-100.%s: %s" % (dn, nm), got, want)
        ok += good
    for (kind, dn), (w, ch) in IG_RIB.items():
        rib = drawings.geometry(kind, dn, "А12")["rib"]
        near("ребро %s %s: ширина" % (kind, dn), rib["w"], w)
        near("ребро %s %s: фаска" % (kind, dn), rib["ch"], ch)
    return ok


# ─── (б) все марки: файлы и размеры в DXF ────────────────────────────────
def read_dxf(path):
    """Сущности DXF R12: [(тип, слой, {код: значение})]."""
    with open(path, encoding="utf-8") as f:
        lines = [x.strip() for x in f.read().split("\n")]
    ents, cur = [], None
    for i in range(0, len(lines) - 1, 2):
        code, val = lines[i], lines[i + 1]
        if code == "0":
            if cur:
                ents.append(cur)
            cur = [val, None, {}] if val in ("LINE", "CIRCLE", "ARC") else None
        elif cur is not None:
            if code == "8":
                cur[1] = val
            else:
                cur[2][code] = float(val)
    return [tuple(e) for e in ents]


def bbox(ents, layer="CUT"):
    xs, ys = [], []
    for t, lay, d in ents:
        if lay != layer:
            continue
        if t == "LINE":
            xs += [d["10"], d["11"]]
            ys += [d["20"], d["21"]]
        elif t == "CIRCLE":
            xs += [d["10"] - d["40"], d["10"] + d["40"]]
            ys += [d["20"] - d["40"], d["20"] + d["40"]]
        elif t == "ARC":
            a0, a1 = d["50"], d["51"]
            if a1 < a0:
                a1 += 360
            for i in range(721):
                a = math.radians(a0 + (a1 - a0) * i / 720.0)
                xs.append(d["10"] + d["40"] * math.cos(a))
                ys.append(d["20"] + d["40"] * math.sin(a))
    return min(xs), min(ys), max(xs), max(ys)


def check_mark(kind, dn, exe, root):
    out = os.path.join(root, "%s_%s_%s" % (kind, dn, exe))
    r = drawings.draw(kind, dn, exe, "Ст3пс", out)
    tag = "%s %s %s" % (kind, dn, exe)
    n_err = len(errors)
    for p in [r["pdf"]] + r["png"] + [d["file"] for d in r["dxf"]]:
        if not os.path.isfile(p) or os.path.getsize(p) == 0:
            errors.append("%s: нет файла %s" % (tag, p))
    if r["rules"] != "v2":
        errors.append("%s: rules %r" % (tag, r["rules"]))
    sheets = 1 if kind == "opp1" else 2
    if len(r["png"]) != sheets:
        errors.append("%s: листов %s вместо %s" % (tag, len(r["png"]), sheets))
    geo = drawings.geometry(kind, dn, exe)
    c = geo["corpus"]
    for d in r["dxf"]:
        ents = read_dxf(d["file"])
        x0, y0, x1, y1 = bbox(ents)
        W, H = x1 - x0, y1 - y0
        nm = "%s поз.%s" % (tag, d["pos"])
        if d["pos"] == "1":
            want = c["angle"] if c["angles"] else c["total"]
            near(nm + " развёртка", W, want)
            near(nm + " ширина", H, geo["W0"] if kind == "opp1" else geo["L"])
            bends = sorted({round(e[2]["10"], 3) for e in ents if e[1] == "BEND"})
            want_b = [c["bend_mark"]] if c["angles"] else [c["bend_mark"], c["total"] - c["bend_mark"]]
            if len(bends) != len(want_b) or any(abs(a - b) > TOL for a, b in zip(bends, want_b)):
                errors.append("%s риски гибов %s вместо %s" % (nm, bends, [round(b, 3) for b in want_b]))
        elif d["pos"] == "2":
            rib = geo["rib"]
            near(nm + " ребро ширина", W, rib["l"] if kind == "opp1" else rib["w"])
            near(nm + " ребро высота", H, rib["h"] if kind == "opp1" else rib["edge"])
        elif d["pos"] == "3":
            cl = geo["clamp"]
            near(nm + " полухомут развёртка", W, cl["total"])
            near(nm + " полухомут ширина", H, cl["m"])
            holes = sorted(e[2]["10"] for e in ents if e[0] == "CIRCLE")
            if len(holes) != 2:
                errors.append("%s отверстий %s" % (nm, len(holes)))
            else:
                near(nm + " отв. 1", holes[0], cl["hole"])
                near(nm + " отв. 2", holes[1], cl["total"] - cl["hole"])
            bends = sorted({round(e[2]["10"], 3) for e in ents if e[1] == "BEND"})
            if len(bends) != 2 or abs(bends[0] - cl["bend_mark"]) > TOL:
                errors.append("%s риски лапок %s" % (nm, bends))
    bad = [k for k, v in r["checks"].items() if not v["ok"]]
    return len(errors) == n_err, bad


def part_b(root):
    ok, warn = 0, []
    marks = drawings.marks()
    for kind, dn, exe in marks:
        try:
            good, bad = check_mark(kind, dn, exe, root)
        except Exception as e:  # noqa: BLE001
            errors.append("%s %s %s: %s: %s" % (kind, dn, exe, type(e).__name__, e))
            continue
        ok += good
        if bad:
            warn.append("%s %s %s: %s" % (kind, dn, exe, "; ".join(bad)))
    try:
        drawings.draw("kx", 219, "А11", "Ст3пс", root)
        errors.append("КХ А11 должна давать ValueError")
    except ValueError as e:
        if not str(e).startswith("пока нет"):
            errors.append("КХ А11: текст ошибки %s" % e)
    return ok, len(marks), warn


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="opora_v2_")
    n_a = part_a()
    print("(а) развёрток Игоря сошлось до %s мм: %s из 19" % (rv.fmt(TOL, 2), n_a))
    n_b, total, warn = part_b(root)
    print("(б) марок нарисовано и сверено: %s из %s → %s" % (n_b, total, root))
    for w in warn:
        print("  сверка не прошла (не ошибка генератора, смотреть):", w)
    for e in errors:
        print("ОШИБКА:", e)
    print("ИТОГ:", "OK" if not errors and n_a == 19 and n_b == total else "есть ошибки (%s)" % len(errors))
    sys.exit(0 if not errors and n_a == 19 and n_b == total else 1)
