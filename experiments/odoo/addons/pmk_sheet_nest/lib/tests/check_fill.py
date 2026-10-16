# -*- coding: utf-8 -*-
"""Добивка остатков листа складскими позициями и разрыв внешнего контура (16.10.2026). Только синтетика: геометрии
деталей завода в репозитории нет (он открытый).

    python3 tests/check_fill.py

1) разрыв: geom.heal_open — продолжение крайнего участка, нахлёст в начале и в конце (лишний кусок срезается), край
   габарита; косой, больше допуска, на дуге — нет. Программа CypCut (синтетическая, открытый внешний контур): без
   допуска — LxdsError с разрывом и координатами, с допуском — закрыт, предупреждение, внешний — закрытый, хотя
   OutlineID блока указывает на отверстие; больше допуска и косой — ошибка. DXF: разрыв на кромке закрыт, прорезь-язычок
   внутри с концами рядом — не тронута, косой — ошибка; run(heal_gap_mm) — сквозной, все проверки программы;
2) добивка: листов столько же, детали заказа на тех же местах, добивка — в свободном месте (все проверки программы ✓,
   «добивка не добавила листов» ✓), количество = поставлено (и Amount в программе), per_layout × листов = placed;
   max на все листы (0 — не ставить); места нет — 0 шт, причина и предупреждение, в программе её нет; предел деталей
   прогона; общий рез; сводка по стратегиям; порядок добивки; ошибки («*», нет такой детали, дважды, все — добивка,
   max < 0, допуск разрыва < 0) — без флагов в тексте; детерминизм; командная строка --fill, --fill-max, --heal-gap;
3) после разбора 16.10: замыкающая прямая, задевающая сам контур, — нет; концы совпали — замкнут и без допуска (и
   подсказка «до 0 мм» не появляется); max меньше листов раскладки — причина «меньше, чем листов в раскладке»; позиция
   из нескольких контуров — одна строка fill, max на все её детали; qty у позиции добивки — 0 или не задан; дуги у
   добивки: загрузка в файле = своя (точные площади), до края — по точному габариту; поджатие — точный сдвиг до
   касания (= бисекции, скольжение вдоль соседа не держит); ход по раскладкам в progress; подвод по кромке соседа —
   lead_room и ⚠ проверки программы;
4) общий рез с добивкой (16.10, «нужен общий рез в раскрое»): правила касания (_pair_ok: кромкой ≥ 10 мм, угол к углу,
   щель, наложение, фаска), карманы, group_buildable; столбцы стоек у лотка — группа, общие кромки, проверки программы,
   сближений нет, добивки не меньше, чем с зазором; узкая полоса — только вплотную; большая группа — сводка, скорость,
   «Безопасный» и «Горкой»; детерминизм; проверка ловит щель и наложение; решётка с фасками — клиньев нет; много мелкой
   добивки — группы ≤ CO_GROUP_MAX; сводка — с вариантом «добивка с зазором» (= прогон с fill_gap), предупреждение,
   когда с зазором опасных меньше; fill_gap — добивка с зазором, как до 0.12.0; ноги торец к торцу — цепочка к
   следующей, над освобождёнными 0.
"""
import sys, os, io, math, json, zipfile, hashlib, tempfile, contextlib, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import dxf_writer as DW
from sheet_nest import geom as G, cli as CLI, write_lxds as WL, fill as F, SheetNestError
from sheet_nest.cli import run
from sheet_nest.read_lxds import parts_from_lxds, LxdsError
from sheet_nest.read_dxf import parts_from_dxf, DxfError

fails = []
quiet = lambda *a: None


def check(name, cond, detail=""):
    print("%s %-78s %s" % ("✓" if cond else "✗", name, detail))
    if not cond:
        fails.append(name)


def poly(v, flag, outer=0, layer=1):
    return dict(kind="LwPolyline", verts=[(float(x), float(y), float(b)) for x, y, b in v], flag=flag, sp=0.0, layer=layer,
                layer_name="0", coedge=0, flag64=0, outer=outer, lead=None)


def hole(x, y, r=5.0):
    return dict(kind="Circle", c=(x, y), r=r, a0=math.pi / 4, layer=1, layer_name="0", coedge=0, flag64=0, outer=0, lead=None)


def area(v):
    return abs(G.poly_area(v))


# ============================================================================================ 1) разрыв
def heal_unit():
    rect = [(0, 0, 0), (100, 0, 0), (100, 50, 0), (0, 50, 0)]
    v, g = G.heal_open([(10, 0, 0), (100, 0, 0), (100, 50, 0), (0, 50, 0), (0, 0, 0)], 20)
    check("heal_open: разрыв продолжает первый участок — закрыт прямой", v is not None and abs(g - 10) < 1e-9 and abs(area(v) - 5000) < 1e-6
          and len(v) == 5, str(v))
    v, g = G.heal_open([(116, 0, 0), (0, 0, 0), (0, 50, 0), (100, 50, 0), (100, 0, 0)], 20)     # как у решётки 16.10: начато на 16 мм дальше
    check("heal_open: конец лежит на первом участке (нахлёст 16 мм) — начало срезано, прямоугольник из 4 вершин",
          v is not None and abs(g - 16) < 1e-9 and len(v) == 4 and abs(area(v) - 5000) < 1e-6 and (116.0, 0.0, 0.0) not in v, str(v))
    v, g = G.heal_open([(0, 0, 0), (100, 0, 0), (100, 50, 0), (0, 50, 0), (0, -16, 0)], 20)
    check("heal_open: начало лежит на последнем участке — конец срезан", v is not None and len(v) == 4 and abs(area(v) - 5000) < 1e-6, str(v))
    v, g = G.heal_open([(0, 0, 0), (100, 0, 0), (100, 50, 0), (0, 50, 0), (0, 12, 0)], 20)
    check("heal_open: разрыв продолжает последний участок — закрыт", v is not None and abs(area(v) - 5000) < 1e-6, str(v))
    notch = [(0, 30, 0), (10, 50, 0), (100, 50, 0), (100, 0, 0), (10, 0, 0), (0, 20, 0)]
    v, g = G.heal_open(notch, 20)
    check("heal_open: концы на краю габарита (участки у концов косые) — закрыт по краю", v is not None and abs(g - 10) < 1e-9
          and abs(area(v) - (90 * 50 + 10 * 10 + 2 * 0.5 * 10 * 20)) < 1e-6, "%s %s" % (v, v and area(v)))
    v, g = G.heal_open([(10, 0, 0), (100, 0, 0), (100, 50, 0), (0, 50, 0), (0, 10, 0)], 20)
    check("heal_open: косой разрыв (через угол) — нет", v is None and abs(g - math.hypot(10, 10)) < 1e-9, str(v))
    v, g = G.heal_open([(30, 0, 0), (100, 0, 0), (100, 50, 0), (0, 50, 0), (0, 0, 0)], 20)
    check("heal_open: разрыв 30 мм при допуске 20 — нет (разрыв в ответе)", v is None and abs(g - 30) < 1e-9)
    arc = [(60, 10, 0.4), (100, 30, 0), (100, 50, 0), (0, 50, 0), (0, 30, 0.4), (40, 10, 0)]
    v, g = G.heal_open(arc, 30)
    check("heal_open: участки у концов — дуги, разрыв не на краю габарита — нет", v is None, str(v))
    v, g = G.heal_open(rect + [(0, 0, 0)], 1)
    check("heal_open: концы совпали — замкнут без нового участка", v is not None and len(v) == 4 and g == 0)


def syn_program(order, extra=()):
    """Синтетическая программа CypCut: детали order (раскладка — по одной на лист) + extra (не разложены)."""
    parts = list(order) + list(extra)
    lays = [dict(W=1250.0, L=2500.0, amount=1, seq=[(k, [G.translate(s, 10, 10) for s in p["shapes"]])]) for k, p in enumerate(order)]
    raw, M = WL.build(parts, lays, "syn")
    return raw


def heal_lxds(td):
    ov = [(20, 0, 0), (300, 0, 0), (300, 200, 0), (0, 200, 0), (0, 0, 0), (10, 0, 0)]
    tongue = poly([(100, 100, 0), (100, 80, 0), (112, 80, 0), (112, 100, 0)], 0)          # язычок: концы в 12 мм
    gap = dict(name="Пластина", qty=1, shapes=[hole(50, 50), tongue, poly(ov, 0, outer=1)], src="x")
    raw = syn_program([gap])
    try:
        parts_from_lxds(raw, "syn.lxds")
        msg, flag = "принято", None
    except LxdsError as e:
        msg, flag = str(e), e.flag
    check(".lxds: открытый внешний контур без допуска — LxdsError: разрыв, координаты от угла, подсказка (без флага в тексте)",
          "внешний контур не замкнут" in msg and "разрыв 10 мм" in msg and "(20; 0)" in msg and "(10; 0)" in msg and "--" not in msg
          and flag == "--heal-gap", msg[:200])
    ps, info = parts_from_lxds(raw, "syn.lxds", 20)
    o = ps[0]["shapes"][-1]
    check(".lxds с допуском 20: закрыт, внешний — он (а не отверстие по OutlineID), прорезь-язычок — открыта, предупреждение",
          G.is_closed(o) and o["outer"] == 1 and abs(G.area(o) - 300 * 200) < 1e-6 and
          any(s["kind"] == "LwPolyline" and not G.is_closed(s) for s in ps[0]["shapes"][:-1]) and
          info["warnings"] == ["деталь «Пластина»: внешний контур не замкнут, разрыв 10 мм на кромке — закрыт прямой (проверьте чертёж)"],
          str(info["warnings"]))
    for v, word, what in (([(40, 0, 0), (300, 0, 0), (300, 200, 0), (0, 200, 0), (0, 0, 0)], "больше допустимого", "разрыв 40 мм"),
                          ([(10, 0, 0), (300, 0, 0), (300, 200, 0), (0, 200, 0), (0, 10, 0)], "не на прямой", "косой разрыв")):
        raw2 = syn_program([dict(name="Б", qty=1, shapes=[hole(50, 50), poly(v, 0, outer=1)], src="x")])
        try:
            parts_from_lxds(raw2, "b.lxds", 20)
            msg = "принято"
        except LxdsError as e:
            msg = str(e)
        check(".lxds: %s при допуске 20 — ошибка «%s»" % (what, word), word in msg, msg[:160])
    # сквозной прогон: детали из программы, разрыв закрыт, программа собрана, все проверки
    p = os.path.join(td, "разрыв.lxds")
    open(p, "wb").write(raw)
    res, raw3, pl, parts = run([p], 1250, 2500, 2, 2, 1.5, qty={"Пластина": 5}, log=quiet, heal_gap_mm=20)
    check("run(heal_gap_mm=20) на программе с разрывом: 5 деталей, все проверки, предупреждение в отчёте",
          res["ok"] and sum(sum(l["parts"].values()) * l["amount"] for l in res["layouts"]) == 5 and
          any("закрыт прямой" in w for w in res["warnings"]), "; ".join(c[0] for c in res["checks"] if c[1] is False))
    try:
        run([p], 1250, 2500, 2, 2, 1.5, log=quiet)
        msg = "принято"
    except SheetNestError as e:
        msg = str(e)
    check("run() без допуска — ошибка входа (как раньше: программу с разрывом не раскладывать молча)", "не замкнут" in msg, msg[:120])


def heal_dxf(td):
    def doc(outer, tongue=True):
        d = DW.DxfDoc(version="AC1015", insunits=4)
        d.entities.lwpolyline(outer, closed=False)
        d.entities.circle((50, 50), 6)
        if tongue:
            d.entities.lwpolyline([(100, 100), (100, 80), (112, 80), (112, 100)], closed=False)
        return d.dxf_bytes()
    ok = doc([(10, 0), (300, 0), (300, 200), (0, 200), (0, 0)])
    try:
        parts_from_dxf(ok, "п.dxf", 1)
        msg = "принято"
    except DxfError as e:
        msg = str(e)
    check("DXF: разрыв 10 мм без допуска — DxfError «не замкнут» (как раньше)", "не замкнут" in msg, msg[:120])
    ps = parts_from_dxf(ok, "п.dxf", 1, heal_gap_mm=20)
    o = ps[0]["shapes"][-1]
    opn = [s for s in ps[0]["shapes"][:-1] if s["kind"] == "LwPolyline" and not G.is_closed(s)]
    check("DXF с допуском 20: одна деталь, внешний закрыт (300×200), язычок с концами в 12 мм — прорезь, предупреждение",
          len(ps) == 1 and G.is_closed(o) and abs(G.area(o) - 60000) < 1e-6 and len(opn) == 1 and
          any("закрыт прямой" in w for w in ps[0]["warnings"]), str(ps[0]["warnings"]))
    try:
        parts_from_dxf(doc([(10, 0), (300, 0), (300, 200), (0, 200), (0, 10)]), "к.dxf", 1, heal_gap_mm=20)
        msg = "принято"
    except DxfError as e:
        msg = str(e)
    check("DXF: косой разрыв с допуском — ошибка «не замкнут»; язычок внутри незакрытого контура не закрыт (цепочек 2)",
          "не замкнут" in msg and "вне деталей — 2;" in msg, msg[:120])


# ============================================================================================ 2) добивка
def dxf_rect(path, w, h, holes=()):
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], closed=True)
    for x, y, r in holes:
        d.entities.circle((x, y), r)
    open(path, "wb").write(d.dxf_bytes())
    return path


def order_sig(pl):
    return [(l["amount"], sorted((q["part"], q["rot"], round(q["dx"], 6), round(q["dy"], 6)) for q in l["placed"] if not q.get("fill")))
            for l in pl["layouts"]]


def check_names(res):
    return {c[0]: c for c in res["checks"]}


def fill_basic(td):
    plate = dxf_rect(os.path.join(td, "plate.dxf"), 1000, 1100, [(100, 100, 10), (900, 1000, 10)])
    post = dxf_rect(os.path.join(td, "post.dxf"), 70, 1000, [(35, 50 + 100 * k, 6) for k in range(9)])
    leg = dxf_rect(os.path.join(td, "leg.dxf"), 50, 400, [(25, 50, 5), (25, 350, 5)])
    order = [dict(path=plate, name="Плита", qty=5, key="p")]
    stock = [dict(path=post, name="Стойка", qty=1, key="s"), dict(path=leg, name="Нога", qty=1, key="n")]
    res0, raw0, pl0, parts0 = run(order, 1250, 2500, 2, 2, 1.5, log=quiet)
    res, raw, pl, parts = run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, fill=["Стойка", "Нога"])
    C = check_names(res)
    fr = {r["name"]: r for r in res["fill"]}
    check("добивка: листов столько же, сколько без неё; детали заказа на тех же местах",
          res["sheets"] == res0["sheets"] and order_sig(pl) == order_sig(pl0), "%d / %d листов" % (res["sheets"], res0["sheets"]))
    check("добивка: поставлены обе позиции, все проверки программы ✓",
          res["ok"] and fr["Стойка"]["placed"] > 0 and fr["Нога"]["placed"] > 0, "; ".join(c[0] for c in res["checks"] if c[1] is False)
          or "стоек %d, ног %d" % (fr["Стойка"]["placed"], fr["Нога"]["placed"]))
    check("проверка «добивка не добавила листов» ✓, «количество деталей = заказ + добивка» ✓",
          C.get("добивка не добавила листов", (0, False))[1] is True and C.get("количество деталей = заказ + добивка", (0, False))[1] is True,
          str(C.get("добивка не добавила листов")))
    check("per_layout × листов раскладки = поставлено; у детали программы qty = поставлено, fill = true, ключ на месте",
          all(sum(n * l["amount"] for n, l in zip(r["per_layout"], pl["layouts"])) == r["placed"] for r in res["fill"]) and
          all(p["qty"] == fr[p["name"]]["placed"] and p.get("fill") and p.get("key") in ("s", "n") for p in parts if p["name"] in fr)
          and [p["name"] for p in parts if not p.get("fill")] == ["Плита"] and next(p for p in parts if p["name"] == "Плита")["qty"] == 5)
    ps, info = parts_from_lxds(raw, "x.lxds")
    check("в программе: Amount детали добивки = поставлено, заказа — как было", {p["name"]: p["qty"] for p in ps} ==
          {"Плита": 5, "Стойка": fr["Стойка"]["placed"], "Нога": fr["Нога"]["placed"]}, str({p["name"]: p["qty"] for p in ps}))
    lay_cnt = [sum(1 for q in l["placed"] if q.get("fill")) for l in pl["layouts"]]
    check("отчёт раскладок: детали добивки в layouts[].parts", all(sum(v for k, v in L["parts"].items() if k != "Плита") == n
                                                                  for L, n in zip(res["layouts"], lay_cnt)))
    # ход: стойка первой, затем нога; наоборот — ног больше
    res2, *_ = run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, fill=["Нога", "Стойка"])
    f2 = {r["name"]: r for r in res2["fill"]}
    check("порядок добивки: первая позиция занимает место первой (нога первой — ног больше, стоек меньше)",
          [r["name"] for r in res2["fill"]] == ["Нога", "Стойка"] and f2["Нога"]["placed"] > fr["Нога"]["placed"] and
          f2["Стойка"]["placed"] <= fr["Стойка"]["placed"] and res2["ok"], "%s / %s" % (f2, fr))
    # max на все листы и 0
    res3, raw3, pl3, parts3 = run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, fill=[dict(name="Стойка", max=3), dict(name="Нога", max=0)])
    f3 = {r["name"]: r for r in res3["fill"]}
    check("max: стоек не больше 3 на все листы, ног 0 (предел 0) — и нет их в программе",
          0 < f3["Стойка"]["placed"] <= 3 and f3["Нога"]["placed"] == 0 and "Нога" not in [p["name"] for p in parts3] and res3["ok"]
          and f3["Стойка"]["why"], str(f3))
    # детерминизм
    res4, raw4, *_ = run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, fill=["Стойка", "Нога"])
    md5 = lambda r: hashlib.md5(zipfile.ZipFile(io.BytesIO(r)).read("Geometry2D/data.bin")).hexdigest()
    check("детерминизм: повторный прогон — та же геометрия программы и та же добивка", md5(raw) == md5(raw4) and res4["fill"] == res["fill"])
    # сводка по стратегиям
    res5, *_ = run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, fill=["Стойка", "Нога"], compare=True, strategy="safe")
    S = res5["strategies"]
    check("сводка по стратегиям с добивкой: 4 строки построены, листов столько же, ok",
          res5["ok"] and all(S[n]["error"] is None and S[n]["sheets"] == res0["sheets"] for n in ("short", "safe", "safe0", "hill")),
          str({n: S[n]["sheets"] for n in S}))
    return order, stock


def fill_edge(td, order, stock):
    full = dxf_rect(os.path.join(td, "full.dxf"), 1246, 2496)
    res, raw, pl, parts = run([dict(path=full, name="Лист", qty=2)] + stock, 1250, 2500, 2, 2, 1.5, log=quiet, fill=["Стойка", "Нога"])
    check("места нет: добивка 0 шт с причиной, предупреждение, в программе её нет, ok",
          res["ok"] and all(r["placed"] == 0 and "нет места" in (r["why"] or "") for r in res["fill"]) and
          sum(1 for w in res["warnings"] if w.startswith("добивка «")) == 2 and [p["name"] for p in parts] == ["Лист"] and
          res["sheets"] == 2, str(res["fill"]))
    big = dxf_rect(os.path.join(td, "big.dxf"), 1300, 2600)
    res, raw, pl, parts = run(order + [dict(path=big, name="Огромная", qty=1)], 1250, 2500, 2, 2, 1.5, log=quiet, fill=["Огромная"])
    check("деталь добивки больше листа — 0 шт «не помещается», а не ошибка «деталь больше листа»",
          res["ok"] and res["fill"][0]["placed"] == 0 and "не помещается" in (res["fill"][0]["why"] or ""), str(res["fill"]))
    # предел деталей прогона
    old = CLI.QTY_MAX
    CLI.QTY_MAX = 5 + 4
    try:
        res, *_ = run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, fill=["Стойка", "Нога"])
    finally:
        CLI.QTY_MAX = old
    tot = sum(r["placed"] for r in res["fill"])
    check("предел деталей прогона: добивки не больше остатка до предела, причина «предел деталей»",
          0 < tot <= 4 and any("предел деталей" in (r["why"] or "") for r in res["fill"]) and res["ok"], "%d шт, %s" % (tot, res["fill"]))
    # круглая позиция (маска — не прямоугольник: свёртка БПФ) и уголок
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.circle((0, 0), 40)
    d.entities.circle((0, 0), 10)
    wash = os.path.join(td, "wash.dxf"); open(wash, "wb").write(d.dxf_bytes())
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.lwpolyline([(0, 0), (200, 0), (200, 40), (40, 40), (40, 200), (0, 200)], closed=True)
    ang = os.path.join(td, "ang.dxf"); open(ang, "wb").write(d.dxf_bytes())
    res, raw, pl, parts = run(order + [dict(path=ang, name="Уголок", qty=1), dict(path=wash, name="Шайба", qty=1)], 1250, 2500, 2, 2, 1.5,
                              log=quiet, fill=["Уголок", "Шайба"])
    fr = {r["name"]: r["placed"] for r in res["fill"]}
    check("уголок и шайба (не прямоугольники): поставлены, все проверки (зазоры по контуру)", res["ok"] and fr["Уголок"] > 0 and fr["Шайба"] > 0,
          "%s; %s" % (fr, "; ".join(c[0] for c in res["checks"] if c[1] is False)))
    # общий рез
    co = dxf_rect(os.path.join(td, "co.dxf"), 400, 300, [(50, 50, 8)])
    res0, *_ = run([dict(path=co, name="Плита", qty=6)], 1250, 2500, 2, 2, 3.0, log=quiet, coedge=True)
    res, raw, pl, parts = run([dict(path=co, name="Плита", qty=6)] + stock, 1250, 2500, 2, 2, 3.0, log=quiet, coedge=True, fill=["Стойка", "Нога"])
    C = check_names(res)
    check("общий рез + добивка: общий рез применён, добивка стоит, листов столько же, все проверки (группы, кромки)",
          res["ok"] and res["applied"]["coedge"] and sum(r["placed"] for r in res["fill"]) > 0 and res["sheets"] == res0["sheets"]
          and C.get("добивка не добавила листов", (0, False))[1] is True, "; ".join(c[0] for c in res["checks"] if c[1] is False))
    # ошибки — тексты без флагов
    bad = []
    for kw, word in ((dict(fill=["*"]), "«*» нельзя"), (dict(fill=["Нет такой"]), "нет такой детали"), (dict(fill=["Стойка", "Стойка"]), "дважды"),
                     (dict(fill=[dict(name="Стойка", max=-1)]), "предел"), (dict(fill=[dict(name="Стойка", max=1.5)]), "предел"),
                     (dict(fill=["Плита", "Стойка", "Нога"]), "все детали"), (dict(fill=[dict(name="Стойка", lim=2)]), "лишние поля"),
                     (dict(heal_gap_mm=-1), "не меньше 0"), (dict(heal_gap_mm="abc"), "не меньше 0")):
        try:
            run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, **kw)
            bad.append("принято: %s" % kw)
        except SheetNestError as e:
            if word not in str(e) or re.search(r"--[a-z]", str(e)) or re.search(r"\{'|None\b|\bError\b", str(e)):
                bad.append("%s → %s" % (kw, e))
    check("ошибки добивки и допуска разрыва — SheetNestError с понятным текстом, без флагов командной строки", not bad, "; ".join(bad)[:300])


def fill_unit():
    m = F.scan([(0, 0), (10, 0), (10, 5), (0, 5)], 12, 7)
    check("fill.scan: прямоугольник 10×5 на растре 1 мм — 50 клеток в углу", int(m.sum()) == 50 and m[:5, :10].all())
    circ = [(50 + 30 * math.cos(2 * math.pi * k / 400), 50 + 30 * math.sin(2 * math.pi * k / 400)) for k in range(400)]
    m = F.scan(circ, 100, 100)
    check("fill.scan: круг R30 — площадь по клеткам ±1 %", abs(m.sum() - math.pi * 900) / (math.pi * 900) < 0.01, str(int(m.sum())))
    O = (__import__("numpy").random.RandomState(1).rand(60, 80) < 0.03)
    import numpy as np
    mk = np.ones((5, 7), bool)
    a = F._counts(O, mk, True)
    b = F._counts(O, mk, False)
    check("fill: суммы по окну (прямоугольник) = свёртке БПФ", (a > 0).tolist() == (b > 0).tolist() and a.shape == (56, 74))
    rs = np.random.RandomState(5)
    O = rs.rand(700, 120) < 0.004
    L = np.zeros((40, 30), bool); L[:20] = True; L[:, :10] = True             # уголок
    old = F.BAND
    try:
        F.BAND = 97
        c1 = F._counts(O, L, False)
        F.BAND = 10 ** 6
        c2 = F._counts(O, L, False)
    finally:
        F.BAND = old
    brute = all(((O[i:i + 40, j:j + 30] & L).any()) == (c1[i, j] > 0) for i, j in zip(rs.randint(0, c1.shape[0], 400), rs.randint(0, c1.shape[1], 400)))
    check("fill: свёртка полосами = свёртке целиком = перебору (уголок)", (c1 == c2).all() and brute)


def cli_flags(td, order, stock):
    out = os.path.join(td, "cli")
    args = [order[0]["path"], stock[0]["path"], stock[1]["path"], "--qty", "plate=5", "--thickness", "1.5", "--fill", "post",
            "--fill", "leg", "--fill-max", "post=2", "--heal-gap", "20", "--out", out, "--name", "1,5мм добивка"]
    try:
        with contextlib.redirect_stdout(io.StringIO()) as so:
            CLI.main(args)
        code = None
    except SystemExit as e:
        code = e.code
    rep = [f for f in os.listdir(out) if f.endswith(".json")] if os.path.isdir(out) else []
    r = json.load(open(os.path.join(out, rep[0]), encoding="utf-8")) if rep else {}
    check("командная строка: --fill post --fill leg --fill-max post=2 --heal-gap 20 — выход 0, в отчёте fill, стоек ≤ 2",
          code == 0 and [f["name"] for f in r.get("fill", [])] == ["post", "leg"] and r["fill"][0]["placed"] <= 2 and r["fill"][1]["placed"] > 0,
          "код %s, %s" % (code, r.get("fill")))
    check("командная строка: строка «добивка: post N шт, leg M шт» в выводе", "добивка: post" in so.getvalue())
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            CLI.main(args[:-4] + ["--fill-max", "нет=1", "--out", out])
        code = None
    except SystemExit as e:
        code = e.code
    check("командная строка: --fill-max для позиции не из --fill — «ошибка: …»", isinstance(code, str) and code.startswith("ошибка:"), str(code)[:120])


# ============================================================================================ 3) после разбора 16.10
def heal_more(td):
    V = [(30, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0), (0, -20, 0), (25, -20, 0), (25, 5, 0), (15, 5, 0), (15, 0, 0)]
    v, g = G.heal_open(V, 20)
    check("heal_open: замыкающая прямая на прямой кромки, но пересекает сам контур — нет", v is None and abs(g - 15) < 1e-9, str(v))
    v, g = G.heal_open([(0, 0, 0), (300, 0, 0), (300, 200, 0), (0, 200, 0), (0, 0.004, 0)], 0)
    check("heal_open: концы ближе 0,01 мм — замкнут и при допуске 0", v is not None and len(v) == 4 and abs(area(v) - 60000) < 1e-6, str(v))
    zero = dict(name="Ноль", qty=1, shapes=[hole(50, 50), poly([(0, 0, 0), (300, 0, 0), (300, 200, 0), (0, 200, 0), (0, 0, 0)], 0, outer=1)],
                src="x")
    ps, info = parts_from_lxds(syn_program([zero]), "z.lxds")
    o = ps[0]["shapes"][-1]
    check(".lxds: внешний не помечен замкнутым, концы совпали — замкнут без допуска, внешний — он (а не отверстие), предупреждение",
          G.is_closed(o) and abs(G.area(o) - 60000) < 1e-6 and any("концы совпадают" in w for w in info["warnings"]), str(info["warnings"]))
    small = dict(name="Малый", qty=1, shapes=[hole(50, 50), poly([(0.4, 0, 0), (300, 0, 0), (300, 200, 0), (0, 200, 0), (0, 0, 0)], 0, outer=1)],
                 src="x")
    try:
        parts_from_lxds(syn_program([small]), "s.lxds")
        msg = "принято"
    except LxdsError as e:
        msg = str(e)
    check(".lxds: разрыв 0,4 мм без допуска — подсказка «до 1 мм», а не «до 0 мм»", "до 1 мм" in msg and "до 0 мм" not in msg, msg[:200])


def lead_unit(td):
    from sheet_nest.route import lead_room, lead_free
    from sheet_nest import verify as V, risk as RK
    st = dict(kind="LwPolyline", verts=[(77.5, 1200, 0), (0, 1200, 0), (0, 0, 0), (77.5, 0, 0)], flag=1)
    nb = [(0, 1202.02), (77.5, 1202.02), (77.5, 2402.02), (0, 2402.02)]
    q = (nb, (0, 1202.02, 77.5, 2402.02))
    fr, fs = lead_room(st, 1250, 2500, [q])
    g = RK.Grid()
    g.add(q, q[1])
    check("lead_room: луч от угла по кромке соседа сверху — свободно 20 (как lead_free), с отступом — до соседа (≈2 мм)",
          fr == 20.0 == lead_free(st, 1250, 2500, [q]) and 1.0 < fs < 2.1 and lead_room(st, 1250, 2500, g) == (fr, fs), "%s %s" % (fr, fs))
    nb2 = [(x - 0.6, y) for x, y in nb]
    check("lead_room: сосед на 0,6 мм в стороне — свободно и с отступом", lead_room(st, 1250, 2500, [(nb2, (-0.6, 1202.02, 76.9, 2402.02))]) == (20.0, 20.0))
    # мост: свой общий контур — препятствие только «внутри» (начало луча на нём)
    lead = dict(kind="LwPolyline", verts=[(30, 0, 0), (0, 30, 0), (-30, 0, 0)], flag=1, _lead=((130.0, 100.0), (1.0, 0.0)))
    own = G.Poly([(70, 70), (130, 70), (130, 130), (70, 130)], [("c", 100.0, 100.0, 30.0)])
    check("lead_room: свой общий контур моста (начало луча на нём) — не «кромка соседа»",
          lead_room(lead, 1250, 2500, [(own, (70, 70, 130, 130))]) == (20.0, 20.0))
    # программа: две стойки стопкой, у нижней начало реза — правый верхний угол (луч вверх по кромке верхней)
    part = dict(name="Стойка", qty=2, src="x", shapes=[hole(38.75, 600, 6), poly([(77.5, 1200, 0), (0, 1200, 0), (0, 0, 0), (77.5, 0, 0)], 1 | 2 * 0, outer=1)])
    lay = dict(W=1250.0, L=2500.0, amount=1, seq=[(0, [G.translate(s, 10, 10) for s in part["shapes"]]),
                                                (0, [G.translate(s, 10, 1212.02) for s in part["shapes"]])],
               placed=[dict(part=0, rot=0, dx=10.0, dy=10.0), dict(part=0, rot=0, dx=10.0, dy=1212.02)])
    raw, M = WL.build([part], [lay], "lead")
    rep, rr, ctx = V.check(raw, [part], [lay], 2.0, 2.0, 1.5)
    c = next((x for x in rep if x[0].startswith("место под подвод внешнего")), None)
    check("проверка программы: подвод по кромке соседней детали — ⚠ «по кромке соседней детали — 1 шт», не ✓",
          c is not None and c[1] is None and "по кромке соседней детали" in c[2] and "— 1 шт" in c[2], str(c))
    lay2 = dict(lay, seq=[lay["seq"][0], (0, [G.translate(s, 9.3, 1212.02) for s in part["shapes"]])],
                placed=[lay["placed"][0], dict(part=0, rot=0, dx=9.3, dy=1212.02)])
    raw2, M2 = WL.build([part], [lay2], "lead2")
    rep2, rr2, ctx2 = V.check(raw2, [part], [lay2], 2.0, 2.0, 1.5)
    c2 = next((x for x in rep2 if x[0].startswith("место под подвод внешнего")), None)
    check("проверка программы: верхняя сдвинута влево на 0,7 мм — луч в 0,7 мм от её кромки, подвод свободен, ✓",
          c2 is not None and c2[1] is True, str(c2))


def slide_unit():
    import numpy as np
    sq = lambda x, y, w, h: np.array([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], float)
    B = sq(0, 0, 100, 50)
    b0, b1 = B, np.roll(B, -1, axis=0)
    t = F._slide(sq(110, 10, 30, 30), b0, b1, 2.0, 0)
    check("_slide: прямоугольник справа на 10 мм — влево до зазора 2: 8 мм", abs(t - 8.0) < 1e-9, str(t))
    t = F._slide(sq(20, 52, 30, 30), b0, b1, 2.0, 0)
    check("_slide: на зазоре над соседом — влево скольжение вдоль него не держит (∞)", t == np.inf, str(t))
    t = F._slide(sq(20, 60, 30, 30), b0, b1, 2.0, 1)
    check("_slide: над соседом на 10 мм — вниз 8 мм", abs(t - 8.0) < 1e-9, str(t))
    circ = lambda cx, cy, r, n=400: np.array([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)])
    C = circ(0, 0, 30)
    t = F._slide(circ(70, 20, 25), C, np.roll(C, -1, axis=0), 2.0, 0)
    A = circ(70 - t, 20, 25)
    from sheet_nest.libpath import vn
    d = vn.nest.poly_dist((A, np.roll(A, -1, axis=0)), (C, np.roll(C, -1, axis=0)))
    check("_slide: круг к кругу наискосок — после сдвига расстояние ровно зазор (по многоугольникам)", abs(d - 2.0) < 1e-6, "%.6f" % d)
    # поджатие = первому касанию по оси (шаг 0,05 мм до отказа exact_ok, затем бисекция), на случайных соседях;
    # бисекция по всему ходу, как было, иногда «проскакивает» мимо соседа наискосок — тоже допустимо, но не первое касание
    rs = np.random.RandomState(3)
    sh = F.Sheet(600, 600, 2.0, 2.0)
    for k in range(25):
        x, y, r = rs.uniform(40, 560), rs.uniform(40, 560), rs.uniform(8, 30)
        sh.add([(x + r * math.cos(2 * math.pi * j / 60), y + r * math.sin(2 * math.pi * j / 60)) for j in range(60)])
    shp = F.shapes_of(dict(shapes=[dict(kind="Circle", c=(0.0, 0.0), r=12.0, a0=0.0, layer=1)]))[0]
    bad, n = [], 0
    for k in range(200):
        x, y = rs.uniform(5, 560), rs.uniform(5, 560)
        if not sh.exact_ok(shp, x, y):
            continue
        n += 1
        a = sh.snug(shp, x, y)
        bx, by = x, y
        for axis in (1, 0, 1):
            cur = by if axis else bx
            room = min(cur - sh.edge, F.SNUG)
            if room <= 1e-9:
                continue
            mv = (lambda d: (bx, by - d)) if axis else (lambda d: (bx - d, by))
            lo, hi = 0.0, None
            d = 0.05
            while d < room + 0.05:
                if not sh.exact_ok(shp, *mv(min(d, room))):
                    hi = min(d, room)
                    break
                lo = min(d, room)
                d += 0.05
            if hi is not None:
                for _ in range(30):
                    mid = (lo + hi) / 2
                    if sh.exact_ok(shp, *mv(mid)):
                        lo = mid
                    else:
                        hi = mid
            bx, by = mv(lo)
        if not sh.exact_ok(shp, *a) or abs(a[0] - bx) > 1e-4 or abs(a[1] - by) > 1e-4:
            bad.append((round(x, 2), round(y, 2), a, (bx, by)))
    check("поджатие: точный сдвиг до касания допустим и = первому касанию (мест %d)" % n, n > 50 and not bad, str(bad[:3]))


def fill_more(td, order, stock):
    import time
    # max меньше листов раскладки
    plate = dxf_rect(os.path.join(td, "plate8.dxf"), 1000, 1100)
    res, raw, pl, parts = run([dict(path=plate, name="Плита", qty=8)] + stock[:1], 1250, 2500, 2, 2, 1.5, log=quiet,
                              fill=[dict(name="Стойка", max=3)])
    r = res["fill"][0]
    check("max 3 при раскладке на 4 листа: 0 шт, причина «меньше, чем листов в раскладке (×4)», предупреждение",
          [l["amount"] for l in pl["layouts"]] == [4] and r["placed"] == 0 and "меньше, чем листов в раскладке (×4)" in (r["why"] or "")
          and any("меньше, чем листов" in w for w in res["warnings"]) and res["ok"], str(r))
    # позиция из нескольких контуров: одна строка, max — на все её детали
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.lwpolyline([(0, 0), (60, 0), (60, 600), (0, 600)], closed=True)
    d.entities.lwpolyline([(100, 0), (160, 0), (160, 600), (100, 600)], closed=True)
    d.entities.circle((130, 300), 6)
    two = os.path.join(td, "two.dxf")
    open(two, "wb").write(d.dxf_bytes())
    for mx in (5, None):
        res, raw, pl, parts = run(order + [dict(path=two, name="Две", qty=1, key="s,2")], 1250, 2500, 2, 2, 1.5, log=quiet,
                                  fill=[dict(name="Две", max=mx)])
        fp = [p for p in parts if p.get("fill")]
        check("позиция из двух контуров (max %s): одна строка fill «Две», поставлено = сумме её деталей%s" % (mx, ", не больше 5" if mx else ""),
              [f["name"] for f in res["fill"]] == ["Две"] and res["fill"][0]["placed"] == sum(p["qty"] for p in fp) and
              (mx is None or 0 < res["fill"][0]["placed"] <= 5) and all(p["name"].startswith("Две #") for p in fp) and res["ok"],
              "%s; %s" % (res["fill"], [(p["name"], p["qty"]) for p in fp]))
    # qty у позиции добивки: 0 и не задан — можно, «количество не указано» не пишется
    res, raw, pl, parts = run(order + [dict(stock[0], qty=0), {k: v for k, v in stock[1].items() if k != "qty"}], 1250, 2500, 2, 2, 1.5,
                              log=quiet, fill=["Стойка", "Нога"])
    check("qty у позиции добивки — 0 или не задан: принято, добивка стоит, «количество не указано» в предупреждениях нет",
          res["ok"] and all(r["placed"] > 0 for r in res["fill"]) and not any("количество не указано" in w for w in res["warnings"]),
          str(res["warnings"])[:200])
    try:
        run(order + [dict(stock[0], qty=0)], 1250, 2500, 2, 2, 1.5, log=quiet)
        msg = "принято"
    except SheetNestError as e:
        msg = str(e)
    check("qty 0 у детали заказа (не добивки) — ошибка, как было", "не меньше 1" in msg, msg[:120])
    # дуги у добивки: загрузка в файле = своя (точные площади), до края — по точному габариту; ход по раскладкам
    ob = os.path.join(td, "obround.dxf")
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.lwpolyline([(0, 0, 0), (200, 0, 1), (200, 30, 0), (0, 30, 1)], closed=True)       # концы — полуокружности
    d.entities.circle((15, 15), 5)
    d.entities.circle((185, 15), 5)
    open(ob, "wb").write(d.dxf_bytes())
    stages = []
    t0 = time.time()
    res, raw, pl, parts = run([dict(path=plate, name="Плита", qty=5), dict(path=ob, name="Обраунд", qty=1)], 1250, 2500, 2, 2, 1.5,
                              log=quiet, fill=["Обраунд"], progress=lambda s, t: stages.append((s, t)))
    C = check_names(res)
    ob_part = next(p for p in parts if p["name"] == "Обраунд")
    edge_min = min(min(x0, y0, l["W"] - x1, l["L"] - y1) for l in pl["layouts"] for q in l["placed"] if q.get("fill")
                   for x0, y0, x1, y1 in [G.bbox([G.transform(ob_part["shapes"][-1], q["rot"], (q["dx"], q["dy"]))])])
    check("обраунды (дуги) добивкой: сотни шт, «загрузка в файле = своя» ✓, res ok, до края по точному габариту ≥ 2 мм",
          res["fill"][0]["placed"] > 200 and C["загрузка в файле = своя по геометрии"][1] is True and res["ok"] and edge_min >= 2 - 1e-9,
          "%d шт, %s, край %.4f, %.1f с" % (res["fill"][0]["placed"], C["загрузка в файле = своя по геометрии"], edge_min, time.time() - t0))
    fills = [t for s, t in stages if s == "pack" and t.startswith("добивка остатков листа: раскладка")]
    check("ход добивки в progress: «добивка остатков листа: раскладка k из N» на каждую раскладку",
          len(fills) == len(pl["layouts"]) and fills[0] == "добивка остатков листа: раскладка 1 из %d" % len(pl["layouts"]), str(fills[:3]))
    # скорость: шайбы R20 на листе с одной плитой (было 135 с на 1659 шт)
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.circle((0, 0), 20)
    d.entities.circle((0, 0), 5)
    wsh = os.path.join(td, "w20.dxf")
    open(wsh, "wb").write(d.dxf_bytes())
    small = dxf_rect(os.path.join(td, "p600.dxf"), 600, 400)
    ps, _, _ = CLI.load_parts([dict(path=small, name="П", qty=1), dict(path=wsh, name="Ш", qty=1)])
    o_, f_ = CLI.split_fill(ps, [("Ш", None)])
    from sheet_nest.pack import plan
    pl_ = plan(o_, 1250, 2500, 2.0, 2.0, ("rect", "raster"))
    t0 = time.time()
    rep_, placed_ = F.fill_plan(pl_["layouts"], o_, f_, 2.0, 2.0, qty_left=20000)
    dt = time.time() - t0
    check("скорость: шайбы R20 на одном листе — больше 1500 шт быстрее 60 с", rep_[0]["placed"] > 1500 and dt < 60,
          "%d шт за %.1f с" % (rep_[0]["placed"], dt))


# ============================================================================================ 4) общий рез: добивка вплотную
def co_unit():
    """fill._pair_ok, pockets, route.group_buildable — на прямоугольниках."""
    import numpy as np
    from sheet_nest import route as RT
    def ob(R):
        s0, s1 = F.CoSheet.rect_edges(R)
        return s0, s1, np.ones(4, bool), tuple(R)
    G_, g = 2.02, 2.0
    A = (0, 0, 100, 50)
    cases = [("вплотную по кромке 50 мм", (100, 0, 160, 50), 50.0),
             ("вплотную частью кромки 30 мм (Т-примыкание)", (100, 20, 160, 80), 30.0),
             ("общий участок 5 мм < 10", (100, 45, 160, 95), None),
             ("угол к углу (сетка)", (100, 50, 160, 100), 0.0),
             ("щель 1 мм вдоль кромки", (101, 0, 161, 50), None),
             ("ступенька 1 мм у точки касания", (100, 1, 160, 51), 49.0),
             ("наложение 0,5 мм", (99.5, 0, 160, 50), None),
             ("дальше зазора", (102.5, 0, 160, 50), 0.0)]
    bad = []
    for nm, R, want in cases:
        got = F._pair_ok(R, *ob(A), G_, g)
        if (got is None) != (want is None) or (want is not None and abs(got - want) > 1e-6):
            bad.append("%s: %s, ждали %s" % (nm, got, want))
    # фаска 45° у конца прямой кромки: «вплотную» только прямые вдоль осей, фаска — не ближе зазора
    V = np.array([(0, 0), (900, 0), (970, 70), (970, 1000), (0, 1000)], float)
    s0, s1 = V, np.roll(V, -1, axis=0)
    tm = np.array([True, False, True, True, True])
    for nm, R, ok in (("к прямой кромке, угол до фаски дальше зазора", (970, 100, 1030, 800), True),
                      ("к прямой кромке через начало фаски (клин 45°)", (970, 50, 1030, 800), False),
                      ("угол ровно в начале фаски (до неё 0 < зазора)", (970, 70, 1030, 800), False),
                      ("снизу по кромке, угол в 3 мм от начала фаски", (100, -60, 897, 0), True)):
        r = F._pair_ok(R, s0, s1, tm, (0, 0, 970, 1000), G_, g)
        if (r is not None) != ok:
            bad.append("%s: %s" % (nm, r))
    check("fill._pair_ok: вплотную — общей кромкой ≥ 10 мм или углом к углу; щель, наложение, короткий участок, фаска — нет",
          not bad, "; ".join(bad))
    sq = lambda x, y, w, h: [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    ring = [sq(0, 0, 100, 20), sq(0, 80, 100, 20), sq(0, 20, 20, 60), sq(80, 20, 20, 60)]
    u = [sq(0, 0, 100, 20), sq(0, 20, 20, 60), sq(80, 20, 20, 60)]
    check("fill.pockets: кольцо из четырёх добивок замыкает карман 60×60 (площадь кармана), «П» — нет",
          abs(F.pockets([], ring, (0, 0, 100, 100)) - 3600) < 200 and F.pockets([], u, (0, 0, 100, 100)) == 0,
          "%s / %s" % (F.pockets([], ring, (0, 0, 100, 100)), F.pockets([], u, (0, 0, 100, 100))))
    part = lambda w, h, fill: dict(name="R%gx%g" % (w, h), qty=1, fill=fill, shapes=[poly([(0, 0, 0), (w, 0, 0), (w, h, 0), (0, h, 0)], 1, outer=1)])
    ps = [part(60, 300, True)]
    grid = [dict(part=0, rot=0, dx=10 + 60 * c, dy=10 + 300 * r) for r in range(3) for c in range(3)]
    ps2 = ps + [dict(name="Круг", qty=1, fill=True, shapes=[hole(0, 0, 30)])]
    check("route.group_buildable: сетка 3×3 добивки (9 деталей — обходами от крайних) строится; с круглой деталью — нет",
          RT.group_buildable(ps, grid, list(range(9))) and not RT.group_buildable(ps2, grid[:2] + [dict(part=1, rot=0, dx=100, dy=500)], [0, 1, 2]))


def co_fill(td):
    """Столбцы прямоугольников с отверстиями (стойки) у длинной прямоугольной детали заказа (лоток), общий рез."""
    from sheet_nest import coedge as CE, verify as V
    tray = dxf_rect(os.path.join(td, "co_tray.dxf"), 2495, 348, [(100 + 200 * k, 174, 10) for k in range(12)])
    post = dxf_rect(os.path.join(td, "co_post.dxf"), 77.45, 1200, [(38, 60 + 120 * k, 6) for k in range(10)])
    leg = dxf_rect(os.path.join(td, "co_leg.dxf"), 57.45, 765, [(28, 30, 5), (28, 735, 5)])
    order = [dict(path=tray, name="Лоток", qty=3)]
    stock = [dict(path=post, name="Стойка", qty=1), dict(path=leg, name="Нога", qty=1)]
    t0 = __import__("time").time()
    res, raw, pl, parts = run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, coedge=True, fill=["Стойка", "Нога"], strategy="safe")
    dt = __import__("time").time() - t0
    C = check_names(res)
    l = pl["layouts"][0]
    fills = [k for k, q in enumerate(l["placed"]) if q.get("fill")]
    gf = [g for g in l["groups"] if any(k in fills for k in g)]
    outs = [G.transform(parts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"])) for q in l["placed"]]
    sh = sum(CE.shared_length(outs[a]["verts"], outs[b]["verts"]) for a in range(len(outs)) for b in range(a + 1, len(outs)) if b in fills)
    want = 2 * 1200 + 2 * 1200 + 2 * 77.45                 # к лотку 2 × 1200, между столбцами 2 × 1200, торцы 2 × 77,45
    check("общий рез + добивка: стойки сеткой 2×2 вплотную к лотку и друг к другу — одна группа с лотками, общие кромки %.2f м" % (want / 1000),
          res["ok"] and res["applied"]["coedge"] and len(fills) == 4 and len(gf) == 1 and all(k in gf[0] for k in fills) and
          abs(sh - want) < 1e-3 and abs(res["fill_coedge"]["shared_m"] * 1000 - want) < 1.0,
          "%s, общих %.2f мм, %.1f с" % (l["groups"], sh, dt))
    check("общий рез + добивка: проверки программы — группы, длина реза минус общие кромки, добивка вплотную ✓",
          C["группы общего реза: детали, контуры по одному разу, цепочки от вырезанного, отверстия раньше контура"][1] is True and
          C["длина реза = детали × количество − общие кромки"][1] is True and
          next(c for c in res["checks"] if c[0].startswith("добивка под общий рез"))[1] is True and
          C["добивка не добавила листов"][1] is True, str([c for c in res["checks"] if c[1] is not True]))
    # каждая пара «добивка — сосед»: вплотную по кромке ≥ 10 мм (или угол к углу) или не ближе зазора
    pairs_bad = []
    for i in fills:
        for j in range(len(outs)):
            if j == i:
                continue
            A_ = [(x, y) for x, y, b in outs[i]["verts"]]
            B_ = [(x, y) for x, y, b in outs[j]["verts"]]
            d = min(min(G.seg_point_dist(p, B_[k - 1], B_[k]) for k in range(len(B_))) for p in A_ + [((A_[k - 1][0] + A_[k][0]) / 2, (A_[k - 1][1] + A_[k][1]) / 2) for k in range(len(A_))])
            d = min(d, min(G.seg_point_dist(p, A_[k - 1], A_[k]) for k in range(len(A_)) for p in B_))
            s_ = CE.shared_length(outs[i]["verts"], outs[j]["verts"])
            if not (d >= 2.0 - 1e-6 or (d < 1e-6 and (s_ >= 10 or s_ < 1e-6))):
                pairs_bad.append((i, j, round(d, 3), round(s_, 3)))
    check("добивка под общий рез: сближений 0 < d < зазора нет, касания — кромкой ≥ 10 мм", not pairs_bad, str(pairs_bad[:3]))
    # без общего реза — то же число (с зазором) и программа другая; деталей добивки не меньше, чем с зазором
    fc = res["fill_coedge"]
    check("добивки не меньше, чем с зазором (отчёт fill_coedge: с зазором / поставлено по позициям)",
          all(r["placed"] >= r["gap"] and r["diff"] == r["placed"] - r["gap"] for r in fc["by_name"]) and fc["in_groups"] == 4, str(fc["by_name"]))
    # узкая полоса: место под стойку есть только вплотную к лотку (с зазором не помещается) — добор вплотную
    res2, raw2, pl2, parts2 = run(order + stock[:1], 1126.45, 2500, 2, 2, 1.5, log=quiet, coedge=True, fill=["Стойка"], strategy="safe")
    res3, *_ = run(order + stock[:1], 1126.45, 2500, 2, 2, 1.5, log=quiet, fill=["Стойка"], strategy="safe")
    check("полоса 78,45 мм у лотка: с зазором стойка не встаёт (0 шт), вплотную — 2 шт (столбец к лотку), все проверки",
          res3["fill"][0]["placed"] == 0 and res2["fill"][0]["placed"] == 2 and res2["ok"] and res2["fill_coedge"]["by_name"][0]["diff"] == 2,
          "%s / %s" % (res3["fill"], res2["fill"]))
    # большая группа (столбцы из 10–14 деталей): маршрут быстрый, порядки — обходами, все проверки; безопасные и «Горкой»
    t0 = __import__("time").time()
    res4, raw4, pl4, parts4 = run([dict(path=tray, name="Лоток", qty=2)] + stock, 1250, 2500, 2, 2, 1.5, log=quiet, coedge=True,
                                  fill=["Стойка", "Нога"], strategy="safe", compare=True)
    dt4 = __import__("time").time() - t0
    big = max((len(g) for l_ in pl4["layouts"] for g in l_.get("groups") or []), default=0)
    S = res4["strategies"]
    check("большая группа с добивкой (%d деталей): сводка по 4 стратегиям построена, все проверки, быстрее 60 с" % big,
          big >= 8 and res4["ok"] and all(S[n]["error"] is None for n in ("short", "safe", "safe0", "hill")) and dt4 < 60,
          "%.1f с; над мелкими: %s" % (dt4, {n: S[n]["danger"]["small"] for n in S}))
    tiers = lambda n: tuple(S[n]["danger"][c] for c in ("tongues", "small", "parts", "holes"))
    check("с добивкой в группах: «Безопасный» по опасным не хуже «Минимум холостого», «Горкой» не хуже «Безопасного» по (полоса, опасные)",
          tiers("safe") <= tiers("short") and (S["hill"]["strip"]["sheets"],) + tiers("hill") <= (S["safe"]["strip"]["sheets"],) + tiers("safe"),
          str({n: (S[n]["strip"]["sheets"],) + tiers(n) for n in S}))
    # сравнение с добивкой с зазором (разбор 16.10): в сводке — вариант fill_gap той же стратегией; он же — прогон с fill_gap
    from sheet_nest import risk as RK
    gv = res4["fill_coedge"].get("gap_variant")
    resg, rawg, plg, partsg = run([dict(path=tray, name="Лоток", qty=2)] + stock, 1250, 2500, 2, 2, 1.5, log=quiet, coedge=True,
                                  fill=["Стойка", "Нога"], strategy="safe", fill_gap=True)
    check("сводка с добивкой вплотную: вариант «добивка с зазором» (fill_coedge.gap_variant) — то же, что прогон с fill_gap "
          "(опасные по классам, рез, холостой, добивка)",
          gv is not None and gv["strategy"] == "safe" and all(gv["danger"][c] == resg["risk"][c] for c in RK.CLASSES)
          and abs(gv["cut_m"] - resg["risk"]["cut_m"]) < 0.01 and abs(gv["idle_m"] - resg["idle_m"]) < 0.01
          and gv["fill_n"] == sum(r["placed"] for r in resg["fill"]),
          "%s / %s" % (gv and {c: gv["danger"][c] for c in ("small", "parts", "holes")}, {c: resg["risk"][c] for c in ("small", "parts", "holes")}))
    in_g = [q.get("fill") for l_ in plg["layouts"] for g in l_.get("groups") or [] for q in (l_["placed"][i] for i in g)]
    check("fill_gap: добивка с общим резом — с зазором (как до 0.12.0): в группах её нет, столько же, сколько «с зазором» в отчёте, "
          "fill_coedge — нет, все проверки", resg["ok"] and resg["fill_coedge"] is None and not any(in_g) and
          [r["placed"] for r in resg["fill"]] == [r["gap"] for r in res4["fill_coedge"]["by_name"]],
          "%s / %s" % ([r["placed"] for r in resg["fill"]], [r["gap"] for r in res4["fill_coedge"]["by_name"]]))
    mk = tuple(res4["risk"][c] for c in ("tongues", "small", "parts", "holes"))
    gk = tuple(gv["danger"][c] for c in ("tongues", "small", "parts", "holes")) if gv else None
    warned = any("опасных переходов больше, чем с добивкой с зазором" in w for w in res4["warnings"])
    check("предупреждение «опасных больше, чем с добивкой с зазором» — тогда и только тогда, когда так и есть",
          gv is not None and warned == (gk < mk), "%s против %s, предупреждение %s" % (mk, gk, warned))
    # детерминизм
    res5, raw5, *_ = run(order + stock, 1250, 2500, 2, 2, 1.5, log=quiet, coedge=True, fill=["Стойка", "Нога"], strategy="safe")
    md5 = lambda r: hashlib.md5(zipfile.ZipFile(io.BytesIO(r)).read("Geometry2D/data.bin")).hexdigest()
    check("общий рез + добивка: повторный прогон — та же программа", md5(raw) == md5(raw5) and res5["fill_coedge"] == res["fill_coedge"])
    # проверка ловит порчу: добивку сдвинуть на 1 мм от соседа (щель уже зазора) и на фаску
    lay = dict(pl["layouts"][0], placed=[dict(q) for q in pl["layouts"][0]["placed"]])
    k = fills[-1]
    lay["placed"][k]["dx"] += 1.0
    b_, e_, n_ = V._fill_clearance(parts, lay, 2.0)
    check("verify: добивка в 1 мм от соседа — нарушение «сближение не у общей кромки»", b_ > 0 and "сближение" in e_, e_)
    lay2 = dict(pl["layouts"][0], placed=[dict(q) for q in pl["layouts"][0]["placed"]] + [dict(pl["layouts"][0]["placed"][fills[0]])])
    b_, e_, n_ = V._fill_clearance(parts, lay2, 2.0)
    check("verify: добивка точно поверх другой (совпали контуры) — нарушение «наложилась»", b_ > 0 and "наложилась" in e_, e_)
    return order, stock


def co_chamfer(td):
    """Деталь заказа со срезанными углами (как решётка): добивка вплотную только к прямой кромке, не через фаску."""
    from sheet_nest import verify as V
    d = DW.DxfDoc(version="AC1015", insunits=4)
    d.entities.lwpolyline([(70, 0), (930, 0), (1000, 70), (1000, 1056), (930, 1126), (70, 1126), (0, 1056), (0, 70)], closed=True)
    d.entities.circle((500, 563), 20)
    gr = os.path.join(td, "co_grate.dxf"); open(gr, "wb").write(d.dxf_bytes())
    post = dxf_rect(os.path.join(td, "co_post2.dxf"), 77.45, 1200, [(38, 60 + 120 * k, 6) for k in range(10)])
    leg = dxf_rect(os.path.join(td, "co_leg2.dxf"), 57.45, 765, [(28, 30, 5), (28, 735, 5)])
    res, raw, pl, parts = run([dict(path=gr, name="Решётка", qty=2), dict(path=post, name="Стойка", qty=1), dict(path=leg, name="Нога", qty=1)],
                              1250, 2500, 2, 2, 1.5, log=quiet, coedge=True, fill=["Стойка", "Нога"], strategy="safe")
    l = pl["layouts"][0]
    outs = [G.transform(parts[q["part"]]["shapes"][-1], q["rot"], (q["dx"], q["dy"])) for q in l["placed"]]
    fills = [k for k, q in enumerate(l["placed"]) if q.get("fill")]
    grates = [k for k, q in enumerate(l["placed"]) if not q.get("fill")]
    wedge = []
    for i in fills:
        for j in grates:
            for E in V._shared_ends(outs[i]["verts"], outs[j]["verts"]):
                w = V._free_arc(E, [G.points(o, 0.01) and __import__("numpy").asarray(G.points(o, 0.01)) for o in outs],
                                [G.bbox([o]) for o in outs], 0.5)
                if 0 < w < 85:
                    wedge.append((i, j, E, w))
    C = next(c for c in res["checks"] if c[0].startswith("добивка под общий рез"))
    check("решётка с фасками: добивка вплотную друг к другу (группы), у решёток — не через фаску: клиньев < 90° нет, все проверки",
          res["ok"] and C[1] is True and not wedge and sum(r["placed"] for r in res["fill"]) > 0 and res["fill_coedge"]["in_groups"] > 0,
          "%s; %s; %s" % (res["fill"], C, wedge[:2]))


def co_many(td):
    """Много мелкой добивки-прямоугольников у плиты: группы не больше CO_GROUP_MAX, деталей не меньше, чем с зазором."""
    import time
    plate = dxf_rect(os.path.join(td, "co_plate.dxf"), 1000, 2000, [(500, 1000, 50)])
    small = dxf_rect(os.path.join(td, "co_small.dxf"), 60, 100, [(30, 50, 5)])
    t0 = time.time()
    res, raw, pl, parts = run([dict(path=plate, name="Плита", qty=1), dict(path=small, name="М", qty=1)], 1250, 2500, 2, 2, 1.5,
                              log=quiet, coedge=True, fill=["М"], strategy="safe")
    dt = time.time() - t0
    gs = [len(g) for g in pl["layouts"][0].get("groups") or []]
    fc = res["fill_coedge"]
    check("мелкая добивка 60×100 у плиты: группы ≤ %d деталей, добивки не меньше, чем с зазором, карманов нет, все проверки, < 60 с"
          % F.CO_GROUP_MAX, res["ok"] and gs and max(gs) <= F.CO_GROUP_MAX and fc["by_name"][0]["diff"] >= 0 and not fc["gap_only"]
          and dt < 60, "группы %s, %s, %.1f с" % (gs, fc["by_name"], dt))


def co_review(td):
    """Разбор 16.10 (общий рез с добивкой): сторона цепочки по «взгляду вперёд» у каждой детали группы."""
    # ноги торец к торцу вдоль лотка: путь по двум отверстиям ноги к любому концу кончается у одного и того же, и цепочка
    # «от ближнего конца» уводила головку вдоль только что освобождённой ноги к следующей (лист №5 заказа: ×8)
    tray = dxf_rect(os.path.join(td, "rv_tray.dxf"), 2495, 348, [(40 + 24 * k, 174 + (60 if k % 2 else -60), 4) for k in range(100)])
    W = 2 + 348 + 57.45 + 2 + 30                       # полоса у лотка: ноги встают только вплотную
    got = {}
    for hx in (12.0, 45.45):
        leg = dxf_rect(os.path.join(td, "rv_leg_%g.dxf" % hx), 57.45, 765, [(hx, 20, 5), (hx, 745, 5)])
        for st in ("safe", "hill"):
            res, raw, pl, parts = run([dict(path=tray, name="Лоток", qty=1), dict(path=leg, name="Нога", qty=1)], W, 2500, 2, 2, 1.5,
                                      log=quiet, coedge=True, fill=["Нога"], strategy=st)
            got[(hx, st)] = (res["ok"], res["fill"][0]["placed"], len((pl["layouts"][0].get("groups") or [[]])[0]),
                             res["risk"]["small"], res["risk"]["parts"], round(res["risk"]["over_parts_m"], 3))
    check("ноги торец к торцу у лотка (общий рез): цепочка каждой ноги кончается со стороны следующей — над освобождёнными 0 "
          "(отверстия у любого края; «Безопасный» и «Горкой»)",
          all(v[0] and v[1] == 3 and v[2] == 4 and v[3:] == (0, 0, 0.0) for v in got.values()), str(got))


def main():
    with tempfile.TemporaryDirectory() as td:
        heal_unit()
        heal_lxds(td)
        heal_dxf(td)
        heal_more(td)
        fill_unit()
        slide_unit()
        lead_unit(td)
        order, stock = fill_basic(td)
        fill_edge(td, order, stock)
        fill_more(td, order, stock)
        cli_flags(td, order, stock)
        co_unit()
        co_fill(td)
        co_chamfer(td)
        co_many(td)
        co_review(td)
    print("ВСЁ ВЕРНО" if not fails else "ОШИБКИ: %s" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
