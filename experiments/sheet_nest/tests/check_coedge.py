# -*- coding: utf-8 -*-
"""Общий рез (группы CypCut «CoedgePart»).

    python3 tests/check_coedge.py [КАТАЛОГ_ОБРАЗЦОВ]

1) заводские блоки групп (если есть разбор ~/Downloads/vent_nesting/coedge_research и образцы): построение
   coedge.build_group по деталям инженера даёт блоки CypCut 6.3.907.8 (m3, m8) ТОЧНО — вершины, порядок, флаг, sp,
   coedge, LeadParam (7/7); набор контуров — у всех 29 (кроме 2 блоков зонтов, где детали у инженера наезжают на 3e-6 мм);
2) синтетика: пара, ряд из трёх, Г из трёх — правила кусков (замкнутый первый, цепочки от вырезанного к вырезанному,
   флаги, sp ≠ 0, LeadParam), опасное сближение — отказ, касание углом — допустимо;
3) сквозные: решётки и m3 с общим резом — программа, все проверки ✓.
"""
import sys, os, math, struct, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from sheet_nest import coedge as CE, geom as G
from sheet_nest.cli import run
from sheet_nest.pack import plan_coedge, coedge_groups

SAMPLES = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/vent_nesting/samples")
RESEARCH = os.path.expanduser("~/Downloads/vent_nesting/coedge_research/geometry")
fails = []


def check(name, cond, detail=""):
    print("%s %-70s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def rect(x0, y0, w, h, ccw=True):
    v = [(x0, y0, 0.0), (x0 + w, y0, 0.0), (x0 + w, y0 + h, 0.0), (x0, y0 + h, 0.0)]
    if not ccw:
        v = v[::-1]
    return dict(kind="LwPolyline", verts=v, flag=1, sp=0.0, layer=1, layer_name="0", coedge=0, flag64=0, outer=1, lead=None)


def hole(x, y, r=5):
    return dict(kind="Circle", c=(x, y), r=r, a0=math.pi / 4, layer=1, layer_name="0", coedge=0, flag64=0, outer=0, lead=None)


def invariants(name, sh, members):
    pieces = [s for s in sh if s.get("outer")]
    # первый внешний кусок — замкнутый; последний контур блока — цепочка
    check(name + ": первый кусок замкнутый, последний контур — цепочка", G.is_closed(pieces[0]) and not G.is_closed(sh[-1]))
    ok_flags = all((s["flag"] & 1 and not s["coedge"] and s["sp"] != 0 and s["lead"] == CE.lead_payload(s["sp"])) if G.is_closed(s)
                   else (s["flag"] & 4 and s["coedge"] == 1 and s["sp"] == 0 and s["lead"] is None) for s in pieces)
    check(name + ": флаги, coedge, sp, LeadParam по правилу CypCut", ok_flags)
    done = []
    chain_ok = True
    for s in pieces:
        if not G.is_closed(s):
            for e in G.ends(s):
                if not done or min(G.seg_point_dist(e, a, b) for a, b in done) > 1e-6:
                    chain_ok = False
        P = G.points(s, 0.01)
        done += list(zip(P, P[1:] + (P[:1] if G.is_closed(s) else [])))
    check(name + ": каждая цепочка — от вырезанного к вырезанному", chain_ok)
    total = sum(G.length(s) for s in pieces)
    outs = [m["outer"] for m in members]
    want = sum(G.length(o) for o in outs) - sum(CE.shared_length(outs[a]["verts"], outs[b]["verts"]) for a in range(len(outs)) for b in range(a + 1, len(outs)))
    check(name + ": длина реза = контуры − общие кромки (каждая кромка один раз)", abs(total - want) < 1e-6, "%.3f против %.3f" % (total, want))


def synthetic():
    # пара: два прямоугольника 100×50 бок о бок, у каждого отверстие
    m = [dict(outer=rect(0, 0, 100, 50), inner=[hole(50, 25)]), dict(outer=rect(100, 0, 100, 50), inner=[hole(150, 25)])]
    sh, end = CE.build_group(m)
    invariants("пара", sh, m)
    check("пара: 1 замкнутый + 1 цепочка (П-образная)", [G.is_closed(s) for s in sh if s.get("outer")] == [True, False] and
          len([s for s in sh if s.get("outer")][1]["verts"]) == 4)
    # ряд из трёх, средняя — по часовой (направление контура детали не важно)
    m = [dict(outer=rect(0, 0, 100, 50), inner=[]), dict(outer=rect(100, 0, 100, 50, ccw=False), inner=[]),
         dict(outer=rect(200, 0, 100, 50), inner=[])]
    sh, _ = CE.build_group(m)
    invariants("ряд из трёх", sh, m)
    # порядок «крайние, затем средняя»: средняя — две цепочки по бокам
    sh, _ = CE.build_group([m[0], m[2], m[1]])
    invariants("ряд из трёх (крайние, затем средняя)", sh, [m[0], m[2], m[1]])
    check("средняя последней — две цепочки", sum(1 for s in sh if s.get("outer") and not G.is_closed(s)) == 2)
    # Г: угол одной детали на кромке другой (Т-примыкание)
    m = [dict(outer=rect(0, 0, 200, 50), inner=[]), dict(outer=rect(0, 50, 50, 100), inner=[]), dict(outer=rect(50, 50, 50, 50), inner=[])]
    sh, _ = CE.build_group(m)
    invariants("Г из трёх (Т-примыкания)", sh, m)
    # опасное сближение: 0,5 мм между кромками — не общая кромка
    A, B = rect(0, 0, 100, 50)["verts"], rect(100.5, 0, 100, 50)["verts"]
    check("сближение 0,5 мм — опасно", CE.near_contact(A, B, 1.0) is not None)
    A, B = rect(0, 0, 100, 50)["verts"], rect(100, 50, 100, 50)["verts"]
    check("касание углом — безопасно, общих кромок нет", CE.near_contact(A, B, 1.0) is None and CE.shared_length(A, B) == 0)


def factory():
    if not os.path.isdir(RESEARCH):
        print("— заводские блоки: нет разбора %s, пропуск" % RESEARCH)
        return
    sys.path.insert(0, RESEARCH)
    try:
        from objorder import all_group_blocks, object_order_members, part_block_of, split_part
        import rebuild_groups as RG
    except Exception as e:
        print("— заводские блоки: помощники разбора не загрузились (%s), пропуск" % e)
        return
    T = collections.Counter()
    for g in all_group_blocks():
        if g["group"] is None:
            continue
        D, b = g["D"], g["block"]
        ver8 = D["name"] in ("m3_grpsh", "m8_plates")
        pl, note = object_order_members(g)
        members = []
        for p in pl:
            outer, inner = split_part(part_block_of(D, p["part"]))
            members.append(dict(outer=G.transform(outer, p["th"], p["d"]), inner=[G.transform(s, p["th"], p["d"]) for s in inner]))
        built, _ = CE.build_group(members, head=(0.0, 0.0), sp_ref=(0.0, 0.0) if ver8 else None)
        M = RG._match_block(built, b["shapes"], 1e-6)
        T["all"] += 1
        T["set"] += M["pieces_ok"] and M["inner_ok"]
        if ver8:
            fo = [s for s in b["shapes"] if s["outer"]]
            bo = [s for s in built if s.get("outer")]
            T["v8"] += 1
            T["v8 exact"] += len(fo) == len(bo) and all(
                len(a["verts"]) == len(f["verts"]) and all(abs(x[0] - y[0]) < 1e-6 and abs(x[1] - y[1]) < 1e-6 and abs(x[2] - y[2]) < 1e-9
                                                           for x, y in zip(a["verts"], f["verts"]))
                and a["flag"] == f["flag"] and abs(a["sp"] - f["sp"]) < 1e-9 and a["coedge"] == f["coedge"] and a["lead"] == f["lead"]
                for a, f in zip(bo, fo))
    check("заводские блоки CypCut 6.3.907.8 (m3, m8) — точно", T["v8"] == 7 and T["v8 exact"] == 7, "%d из %d" % (T["v8 exact"], T["v8"]))
    check("все заводские блоки — тот же набор контуров (≥ 27 из 29)", T["all"] == 29 and T["set"] >= 27, "%d из %d" % (T["set"], T["all"]))


def end2end():
    for nm, W, L, t, want_sheets in (("reshetki_bez_listov", 1250, 2500, 1.5, 76), ("m3_grpsh", 1500, 3000, 3, 1)):
        path = os.path.join(SAMPLES, nm + ".lxds")
        if not os.path.exists(path):
            print("— %s: нет образца, пропуск" % nm)
            continue
        res, raw, pl, parts = run([path], W, L, 2, 2, t, None, nm, None, log=lambda *a: None, coedge=True)
        check("%s, общий рез: %d листов, все проверки программы" % (nm, want_sheets), res["sheets"] == want_sheets and res["ok"],
              "%d листов; %s" % (res["sheets"], "; ".join(c[0] for c in res["checks"] if c[1] is False)))
        check("%s, общий рез: в программе есть группы" % nm, b"CoedgePart" in __import__("zipfile").ZipFile(__import__("io").BytesIO(raw)).read("Nest2D/Parts/Groups/content.xml"))


synthetic()
factory()
end2end()
print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
sys.exit(1 if fails else 0)
