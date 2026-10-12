# -*- coding: utf-8 -*-
"""Раскрой (nest.scenarios) → модель программы для лазера: детали, листы, раскладки.

Модель не зависит от формата CypCut — из неё пишется .lxds (lxds_write.py).
    parts:   [{id, name, amount, contours}]       контуры детали в её координатах (от угла габарита)
    results: [{size: (1250, L), amount, placements: [{part, rot, contours}]}]
             одинаковые листы сливаются в одну раскладку × amount (как «3 листа» у инженера)
"""
import json, hashlib
from . import contours as C

ROLE_ORDER = {"панель торц.": 0, "панель сред.": 1, "крышка": 2}
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _hood_key(h):
    w, l = h.split("×")
    return (int(w), int(l))


def part_key(it):
    """Деталь = зонт + ВСЕ контуры, не только внешний: у средних панелей контур одинаковый, а лапки на разных
    местах; одинаковые по форме крышки разных зонтов — разные детали (как у инженера в CypCut)."""
    c = C.part_contours(it)
    sig = [it["hood"], [[round(v, 3) for v in p] for p in c["outer"]],
           sorted([[round(v, 3) for v in p] for p in s] for s in c["slots"]),
           sorted([round(v, 3) for v in h] for h in c["holes"])]
    return hashlib.md5(json.dumps(sig).encode()).hexdigest()


def build(sc, rot_pt, rotated, which, name_suffix=""):
    """sc — результат nest.scenarios() для одного материала; which — 'stock' | 'coil'.
    name_suffix — пометка к имени детали (например « с145» для варианта со свесом), чтобы не спутать с обычными."""
    x = sc[which]
    by_key, kof = {}, {}
    for s in x["_sheets"]:
        for it, r, ox, oy in s.placed:
            kof[id(it)] = k = part_key(it)
            by_key.setdefault(k, it)
    # имена как у CypCut при импорте DXF: «вш 500х1000» + буква на каждую разную деталь зонта
    names, per_hood = {}, {}
    for k, it in sorted(by_key.items(), key=lambda kv: (_hood_key(kv[1]["hood"]), ROLE_ORDER.get(kv[1]["role"], 9), kv[0])):
        n = per_hood.get(it["hood"], 0); per_hood[it["hood"]] = n + 1
        names[k] = "вш %s%s%s" % (it["hood"].replace("×", "х"), LETTERS[n], name_suffix)
    parts = {k: {"id": k, "name": names[k], "role": it["role"], "hood": it["hood"], "amount": 0,
                 "contours": C.part_contours(it),
                 # независимый источник для самопроверки: середины дуг и отверстия прямо из разбора DXF
                 "src_arc_mids": [tuple(e["pm"]) for e in it["edges"] + it["slot_edges"] if e["t"] == "A"],
                 "src_holes": [tuple(h) for h in it["holes"]]} for k, it in by_key.items()}
    results, sig_index = [], {}
    for sheet_no, (s, L) in enumerate(zip(x["_sheets"], x["_lens"]), 1):
        pl = []
        for it, r, cc in C.placed(s, rot_pt, rotated):
            pl.append({"part": kof[id(it)], "rot": r, "contours": cc})
        sig = (round(L), tuple(sorted((p["part"], p["rot"], round(p["contours"]["outer"][0][0], 1), round(p["contours"]["outer"][0][1], 1)) for p in pl)))
        if sig in sig_index:
            results[sig_index[sig]]["amount"] += 1
            results[sig_index[sig]]["sheet_nos"].append(sheet_no)
        else:
            sig_index[sig] = len(results)
            results.append({"size": (1250.0, float(L)), "amount": 1, "placements": pl, "sheet_nos": [sheet_no]})
    # раскладки одного листа подряд (как список листов в CypNest), внутри — порядок раскроя
    first = {}
    for r in results:
        first.setdefault(r["size"], len(first))
    results.sort(key=lambda r: first[r["size"]])
    for res in results:
        for p in res["placements"]:
            parts[p["part"]]["amount"] += res["amount"]
    order = sorted(parts.values(), key=lambda p: (_hood_key(p["hood"]), p["name"]))
    return {"material": "%s %s" % (sc["color"], sc["thickness"]), "source": which, "parts": order, "results": results}
