# -*- coding: utf-8 -*-
"""Подписи деталей гравировкой (шрифт «GOST type A (plotter)», файл GOST.FON).

    python3 tests/check_labels.py [КАТАЛОГ_ОБРАЗЦОВ]

1) шрифт: тот самый (имя, высота прописных и цифр = заданной), кириллица и цифры есть;
2) разрывы: на всех цифрах и буквах — куски не ближе 1 мм друг к другу, ни один кусок не замкнут и не пересекает
   сам себя; срезано немного (длина ≥ 80 % исходной);
3) место: синтетические детали — подпись внутри, ≥ 3 мм от отверстий, края, гравировки и язычков (проверка verify —
   независимая от расстановки), у центра, вдоль длинной стороны; узкое место — буквы меньше, но не меньше минимума;
   не помещается — без подписи и с причиной;
4) проверка программы ловит испорченные подписи (на отверстии, за краем, штрихи касаются);
5) правила ввода: своё имя важнее «*», чужое имя и знак не из шрифта — ошибка;
6) сквозные: DXF-плита, решётки (77 листов, 11 подписей), m3 с общим резом — все проверки программы ✓.
"""
import sys, os, math, copy, tempfile, io, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from sheet_nest import labels as LB, geom as G, verify as V
from sheet_nest.cli import run, main

SAMPLES = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/vent_nesting/samples")
fails = []


def check(name, cond, detail=""):
    print("%s %-74s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def rect(x0, y0, w, h, layer=1):
    v = [(x0, y0, 0.0), (x0 + w, y0, 0.0), (x0 + w, y0 + h, 0.0), (x0, y0 + h, 0.0)]
    return dict(kind="LwPolyline", verts=v, flag=1, sp=0.0, layer=layer, layer_name="0", coedge=0, flag64=0, outer=0, lead=None)


def hole(x, y, r=5):
    return dict(kind="Circle", c=(x, y), r=r, a0=0.0, layer=1, layer_name="0", coedge=0, flag64=0, outer=0, lead=None)


def opened(pts, layer=1):
    return dict(kind="LwPolyline", verts=[(x, y, 0.0) for x, y in pts], flag=0, sp=0.0, layer=layer, layer_name="0",
                coedge=0, flag64=0, outer=0, lead=None)


def part(name, outer, inner=()):
    o = dict(outer, outer=1)
    return dict(name=name, qty=1, shapes=list(inner) + [o], src=name + ".dxf", warnings=[])


def seg_cross(a, b, c, d):
    r = LB._cross(a, b, c, d)
    return r is not None and 1e-6 < r[1] < 1 - 1e-6 and 1e-6 < r[2] < 1 - 1e-6


def pieces_min_dist(pieces):
    best = 1e9
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            for a, b in zip(pieces[j], pieces[j][1:]):
                for p in pieces[i]:
                    best = min(best, G.seg_point_dist(p, a, b))
            for a, b in zip(pieces[i], pieces[i][1:]):
                for p in pieces[j]:
                    best = min(best, G.seg_point_dist(p, a, b))
    return best


def plen(P):
    return sum(math.dist(a, b) for a, b in zip(P, P[1:]))


# ============================================================================================ 1) шрифт
def font():
    try:
        F = LB.load_font()
    except LB.LabelError as e:
        print("— нет шрифта (%s): тесты подписей пропущены" % e)
        return False
    check("шрифт — «GOST type A (plotter)»", F["face"] == LB.FACE, F["face"])
    need = "0123456789АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯABCDEFGHIJKLMNOPQRSTUVWXYZ-./"
    miss = [c for c in need if c.encode("cp1251")[0] not in F["glyphs"] or not F["glyphs"][c.encode("cp1251")[0]]["strokes"]]
    check("цифры, кириллица, латиница, «-./» в шрифте", not miss, "".join(miss))
    bad = []
    for c in "0123456789НЕШ":
        ys = [y for st in LB.text_strokes(c, 15.0, F) for x, y in st]
        if abs(max(ys) - min(ys) - 15.0) > 0.05:
            bad.append("%s: %.2f" % (c, max(ys) - min(ys)))
    check("высота цифр и прописных = заданной (15 мм)", not bad, ", ".join(bad))
    return True


# ============================================================================================ 2) разрывы
def gaps():
    F = LB.load_font()
    worst, closed, selfx, short, bad = 1e9, [], [], [], []
    for c in "0123456789АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ-":
        src = LB.text_strokes(c, 15.0, F)
        pcs = LB.gapify(src, 1.0)
        d = pieces_min_dist(pcs)
        worst = min(worst, d)
        if d < 1.0 - 0.02:
            bad.append("%s %.2f" % (c, d))
        for P in pcs:
            if len(P) > 2 and math.dist(P[0], P[-1]) < 1.0 - 0.02:
                closed.append(c)
            S = list(zip(P, P[1:]))
            if any(seg_cross(*S[i], *S[j]) for i in range(len(S)) for j in range(i + 2, len(S))):
                selfx.append(c)
        if sum(map(plen, pcs)) < 0.8 * sum(map(plen, src)):
            short.append(c)
    check("разрывы: куски каждого знака не ближе 1 мм друг к другу", not bad, "наименьшее %.2f мм %s" % (worst, " ".join(bad)))
    check("разрывы: ни один кусок не замкнут («8», «0», «О» — с разрывом)", not closed, "".join(sorted(set(closed))))
    check("разрывы: куски не пересекают сами себя", not selfx, "".join(sorted(set(selfx))))
    check("разрывы: срезано немного (длина ≥ 80 %)", not short, "".join(short))
    n8 = len(LB.gapify(LB.text_strokes("8", 15.0, F), 1.0))
    check("«8» — не одним замкнутым штрихом", n8 >= 2, "%d кусков" % n8)
    pcs, bb = LB.label_pieces("ВЗ-00003", 15.0, 1.0)
    check("подпись целиком: соседние знаки не касаются (≥ 1 мм)", pieces_min_dist([list(p) for p in pcs]) >= 1.0 - 0.02)


# ============================================================================================ 3) место
def placed(p):
    return [s for s in p["shapes"] if s.get("label")]


def label_box(p):
    P = [(x, y) for s in placed(p) for x, y, _ in s["verts"]]
    return min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P)


def placement():
    # плита 300×150, отверстия по углам — подпись в центре, вдоль длинной стороны, 15 мм
    p = part("плита", rect(0, 0, 300, 150), [hole(20, 20), hole(280, 20), hole(20, 130), hole(280, 130)])
    rep = LB.apply_labels([p], {"*": "А-17"})
    b = label_box(p)
    check("плита: подпись 15 мм, вдоль длинной стороны", rep[0][2] == 15.0 and p["label"]["rot"] == 0, str(rep[0]))
    check("плита: у центра детали", abs((b[0] + b[2]) / 2 - 150) < 10 and abs((b[1] + b[3]) / 2 - 75) < 10, "%.1f; %.1f" % ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
    check("плита: проверка подписи (внутри, ≥ 3 мм, штрихи ≥ 1 мм)", V._check_label(p) == "", V._check_label(p))
    check("плита: внешний контур остался последним", p["shapes"][-1]["outer"] == 1 and not p["shapes"][-1].get("label"))

    # высокая узкая полоса — подпись поперёк (rot 90)
    p = part("полоса", rect(0, 0, 40, 400))
    LB.apply_labels([p], {"*": "А-17"})
    check("узкая полоса 40×400: подпись повёрнута вдоль длинной стороны", p.get("label", {}).get("rot") == 90, str(p.get("label")))
    check("узкая полоса: проверка подписи", V._check_label(p) == "", V._check_label(p))

    # в середине — большое окно, свободна только рамка 19 мм: буквы меньше (15 + 2·3 > 19), но не меньше 10
    p = part("рамка", rect(0, 0, 300, 138), [rect(19, 19, 262, 100)])
    rep = LB.apply_labels([p], {"*": "А-17"})
    h = rep[0][2]
    check("рамка 19 мм: буквы уменьшены до 10…13 мм", h is not None and 10 <= h <= 13, "высота %s" % h)
    check("рамка: проверка подписи", h is not None and V._check_label(p) == "", h and V._check_label(p))

    # маленькая деталь — без подписи, с причиной
    p = part("малая", rect(0, 0, 30, 20))
    rep = LB.apply_labels([p], {"*": "ВЗ-00003"})
    check("деталь 30×20: без подписи, причина в отчёте", rep[0][2] is None and "не помещается" in rep[0][3] and not placed(p), rep[0][3])

    # жалюзи: открытые П-прорези (язычки) по всей середине — подпись не на язычке и не у линии гиба
    sl = [opened([(x, 40), (x, 160), (x + 20, 160), (x + 20, 40)]) for x in range(40, 260, 30)]
    p = part("жалюзи", rect(0, 0, 300, 200), sl)
    LB.apply_labels([p], {"*": "А-17"})
    tongues = [G.points(s, 0.05) for s in sl]
    on_tongue = any(G.inside((x, y), T) for s in placed(p) for x, y, _ in s["verts"] for T in tongues)
    check("жалюзи: подпись есть, не на язычке", bool(placed(p)) and not on_tongue)
    check("жалюзи: проверка подписи (язычки и хорды)", V._check_label(p) == "", V._check_label(p))

    # своя гравировка детали (номер) у центра — подпись не ближе 3 мм к ней
    eng = [opened([(140, 60), (160, 90)], layer=2), opened([(150, 60), (170, 90)], layer=2)]
    p = part("с номером", rect(0, 0, 300, 150), eng)
    LB.apply_labels([p], {"*": "А-17"})
    check("гравировка детали: подпись ≥ 3 мм от неё (проверка)", bool(placed(p)) and V._check_label(p) == "", V._check_label(p))


# ============================================================================================ 4) проверка ловит
def mutants():
    base = part("плита", rect(0, 0, 300, 150), [hole(150, 40, 8)])
    LB.apply_labels([base], {"*": "А-17"})
    lab0 = placed(base)
    b = label_box(base)

    def moved(dx, dy, only=None):
        p = copy.deepcopy(base)
        k = 0
        for s in p["shapes"]:
            if s.get("label"):
                if only is None or k == only:
                    s["verts"] = [(x + dx, y + dy, z) for x, y, z in s["verts"]]
                k += 1
        return p
    cx = (b[0] + b[2]) / 2
    cy = (b[1] + b[3]) / 2
    cases = [("подпись на отверстии", moved(150 - cx, 40 - cy)),
             ("подпись за краем детали", moved(0, 150 - b[1] - 5)),
             ("подпись ближе 3 мм к краю", moved(0, 150 - b[3] - 1.5)),
             ("кусок подписи касается соседнего", moved(lab0[1]["verts"][0][0] - lab0[0]["verts"][-1][0],
                                                       lab0[1]["verts"][0][1] - lab0[0]["verts"][-1][1], only=0))]
    for name, p in cases:
        why = V._check_label(p)
        check("проверка ловит: " + name, why != "", why)


# ============================================================================================ 5) правила ввода
def inputs():
    a, b = part("A", rect(0, 0, 300, 150)), part("B", rect(0, 0, 300, 150))
    rep = LB.apply_labels([a, b], {"*": "ОБЩ", "B": "СВОЙ"})
    check("своё имя важнее «*»", [r[1] for r in rep] == ["ОБЩ", "СВОЙ"], str(rep))
    a = part("A", rect(0, 0, 300, 150))
    rep = LB.apply_labels([a], {os.path.splitext(a["src"])[0]: "ПО ФАЙЛУ"})
    check("имя файла без расширения — тоже имя детали", rep and rep[0][1] == "ПО ФАЙЛУ")
    for name, texts, kw in (("чужое имя детали", {"НЕТ": "Х"}, {}), ("знак не из шрифта", {"*": "★"}, {}),
                            ("минимум больше высоты", {"*": "Х"}, dict(H=10, H_min=15))):
        try:
            LB.apply_labels([part("A", rect(0, 0, 300, 150))], texts, **kw)
            check("ошибка: " + name, False, "нет ошибки")
        except LB.LabelError as e:
            check("ошибка: " + name, isinstance(e, ValueError), str(e)[:60])


# ============================================================================================ 6) сквозные
def end2end():
    sys.path.insert(0, os.path.join(HERE, "fixtures"))
    import dxf_writer as DW
    with tempfile.TemporaryDirectory() as td:
        doc = DW.DxfDoc(version="AC1015", insunits=4)
        doc.entities.lwpolyline([(0, 0), (400, 0), (400, 300), (0, 300)], closed=True)
        for x, y in ((40, 40), (360, 40), (40, 260), (360, 260), (200, 150)):
            doc.entities.circle((x, y), 15)
        path = os.path.join(td, "плита_6шт.dxf")
        open(path, "wb").write(doc.dxf_bytes())
        res, raw, pl, parts = run([path], 1250, 2500, 2, 2, 3, None, "lab", td, log=lambda *a: None, labels={"*": "ВЗ-00003"})
        check("DXF-плита с подписью: все проверки программы", res["ok"], "; ".join(c[0] for c in res["checks"] if c[1] is False))
        check("DXF-плита: подпись 15 мм в отчёте", [l["height"] for l in res["labels"]] == [15.0], str(res["labels"]))
        lc = [c for c in res["checks"] if c[0].startswith("подписи")]
        check("DXF-плита: проверка подписей в программе есть и ✓", len(lc) == 1 and lc[0][1] is True)
        # командная строка: подпись чужой детали — ошибка, а не тихо без подписи
        try:
            main([path, "--label", "нет_такой=Х", "--out", td])
            check("командная строка: чужое имя в --label — ошибка", False, "нет ошибки")
        except SystemExit as e:
            check("командная строка: чужое имя в --label — ошибка", "нет такой детали" in str(e.code), str(e.code)[:80])
    for nm, W, L, t, ce, sheets in (("reshetki_bez_listov", 1250, 2500, 1.5, False, 77), ("m3_grpsh", 1500, 3000, 3, True, 1)):
        path = os.path.join(SAMPLES, nm + ".lxds")
        if not os.path.exists(path):
            print("— %s: нет образца, пропуск" % nm)
            continue
        res, raw, pl, parts = run([path], W, L, 2, 2, t, None, nm, None, log=lambda *a: None, coedge=ce, labels={"*": "ВЗ-00003"})
        n = sum(1 for p in parts if p.get("label"))
        check("%s%s с подписями: %d листов, все проверки" % (nm, ", общий рез" if ce else "", sheets),
              res["ok"] and res["sheets"] == sheets, "%d листов; %s" % (res["sheets"], "; ".join(c[0] for c in res["checks"] if c[1] is False)))
        check("%s: подписаны все детали" % nm, n == len(parts) and all(l["height"] == 15.0 for l in res["labels"]), "%d из %d" % (n, len(parts)))
        if ce:
            check("%s: группы общего реза на месте" % nm,
                  b"CoedgePart" in zipfile.ZipFile(io.BytesIO(raw)).read("Nest2D/Parts/Groups/content.xml"))


if font():
    gaps()
    placement()
    mutants()
    inputs()
    end2end()
print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
sys.exit(1 if fails else 0)
