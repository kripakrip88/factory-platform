"""Генератор рабочих чертежей (PDF, А3) и DXF деталей для лазера — закладные изделия.

Серии и семейства:
  1.400-15 вып. 1 (данные сайта mn_izdeliya1_ALL.json, проверены по альбому):
    A — пластина + прямые анкеры (± шайбы), МН 101–164; погонные МН 104, 127–132 — с длиной --length;
    B — две пластины, МН 201–228 (поставка разобранной, как в серии);
    C — пластина + прямые анкеры + гнутые анкеры внахлёстку (Н1-Мш), МН 301–325.
  Ошибки сайта, исправленные по альбому, — SITE_FIX_15; опечатки альбома и сайта — README, «Ошибки в источниках».
  1.400-6/76 вып. 1 (оцифровка листов альбома seriya_6_76_pages/digitized/*.json):
    A — пластина + прямые анкеры (± шайбы), любое число групп анкеров разной длины/диаметра.
Сварка — только полуавтомат: Т11-Мз по ГОСТ 14098-2014 для всех диаметров (решение завода 22.10.2026):
  отверстие d0 = ⌈d1 + 2⌉, раззенковка D0 = d0 + 10 на всю толщину, стержень заходит на 0,5 толщины.
DXF (R12, мм): слой CUT — рез (контур, отверстия d0, технологические отверстия), слой GRAV — гравировка
  (окружность D0 = внешний контур зенковки, риска «верх»). GRAV понимает sheet_nest (→ слой 2 CypCut).
Разрывы: длинные стержни в разрезе и погонная полоса на виде — с обрывом, если так виды крупнее.

Запуск:
  python3 generate.py                                   # серия 1.400-15
  python3 generate.py --series 6/76                     # серия 1.400-6/76
  python3 generate.py --only "МН 201-5" --png --out out_test
  python3 generate.py --only "МН 104-1" --length 1200   # погонные
"""
import argparse
import csv
import importlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

# ПРАВКА ERP (pmk_zakladnye, 25.10.2026) — только загрузка, логика генератора не тронута:
#  • данные — в ../data (PMK_ZK_DATA переопределяет): mn_izdeliya1_ALL.json, s676/p*.json;
#  • gost_draw / iso3d (PyMuPDF) импортируются при первом рисовании: Odoo берёт из этого файла
#    только модель и массы (build_*, finish, masses, positions, dxf_parts), PyMuPDF в его образе нет —
#    рисует фоновый процесс (worker.py, свой образ).
HERE = Path(__file__).parent
DATA = Path(os.environ.get("PMK_ZK_DATA") or HERE.parent / "data")
sys.path.insert(0, str(HERE))


class _Lazy:
    """Модуль, который импортируется при первом обращении к атрибуту."""

    def __init__(self, name):
        self._name, self._mod = name, None

    def __getattr__(self, attr):
        if self._mod is None:
            self._mod = importlib.import_module(self._name)
        return getattr(self._mod, attr)


g = _Lazy("gost_draw")
iso3d = _Lazy("iso3d")

RHO = 7.85e-6
D1 = {6: 6.75, 8: 9.0, 10: 11.3, 12: 13.5, 14: 15.5, 16: 18.0, 18: 20.0, 20: 22.0, 22: 24.0, 25: 27.0, 28: 30.5, 32: 34.5}
KG_M = {6: 0.222, 8: 0.395, 10: 0.617, 12: 0.888, 14: 1.208, 16: 1.578, 18: 1.998, 20: 2.466, 22: 2.984,
        25: 3.853, 28: 4.834, 32: 6.313}
STEEL = "С255 ГОСТ 27772-2021"
SHEET = "Лист ГОСТ 19903-2015"
REBAR = "Арматура ГОСТ 34028-2016"
CLS = "А400"
WELD = "Т11-Мз"                       # в раззенкованное отверстие — только там, где отверстие есть в серии (МН 201–228, поз. 2)
# Где в серии тавр под флюсом (Т1-Мф, сплошная пластина) — по решению завода полуавтомат угловым швом по контуру
# стержня, без отверстий (Антон, 25.10.2026). В ГОСТ 14098-2014 такого соединения нет — обозначение по ГОСТ 14771-76.
FILLET = "ГОСТ 14771-76-Т1-УП"
FILLET_TAG = "Ш1"


def leg(d, s):
    """Катет углового шва стержень–пластина: 0,5d, не менее 4 мм и не более толщины пластины (шайбы)."""
    return int(min(s, max(4, math.ceil(0.5 * d))))
SCALES = [(0.5, "1:2"), (0.4, "1:2,5"), (0.25, "1:4"), (0.2, "1:5"), (2 / 15, "1:7,5"), (0.1, "1:10"), (1 / 15, "1:15"), (0.05, "1:20")]
WELD_LAP = "Н1-Мш"
# Гнутые стержни 1.400-15.В1.004 рис. 1 (листы альбома стр. 189–190): прямой участок l2 по диаметру,
# L = l1 + l2, h — вылет конца наклонного участка l1 от оси прямого. Гиб — на KINK ниже верхней кромки пластины
# (узел «А» сборочных листов МН 301–325, стр. 100–117).
# Ошибки сайта серии 1.400-15, исправленные по альбому (поле сайта -> значение альбома)
SITE_FIX_15 = {m: {"Количество и диаметр прямых анкеров": q, "_src": src} for m, q, src in [
    ("МН 310-1", "6ф10AIII", "стр. 103: d2 = 10A-III"), ("МН 310-2", "6ф10AIII", "стр. 103: d2 = 10A-III"),
    ("МН 314-1", "8ф10AIII", "стр. 109: d2 = 10A-III"), ("МН 314-2", "8ф10AIII", "стр. 109: d2 = 10A-III"),
    ("МН 314-3", "8ф10AIII", "стр. 109: d2 = 10A-III"), ("МН 316-1", "8ф10AIII", "стр. 109: d2 = 10A-III"),
    ("МН 316-2", "8ф10AIII", "стр. 109: d2 = 10A-III"), ("МН 316-3", "8ф10AIII", "стр. 109: d2 = 10A-III")]}
BENT_L2 = {8: 50, 10: 70, 12: 100, 16: 120, 20: 150}
KINK = 30
STUB = 40        # мм натуры: выступ гнутых стержней над пластиной на виде с лица (дальше — обрыв)
GAP = 8          # мм листа на разрыв вида
SHOW = 40        # мм натуры, видимые у каждой стороны разрыва в разрезе


def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    v = (v or "").replace(",", ".").strip()
    return float(v) if re.fullmatch(r"\d+(\.\d+)?", v) else None


def fmt(v):
    return f"{v:g}".replace(".", ",")


def axis(L, edge, step):
    if L is None or edge is None:
        return None
    if step is None:
        return [edge] if abs(L - 2 * edge) < 0.1 else [edge, L - edge]
    k = (L - 2 * edge) / step
    return [edge + i * step for i in range(int(round(k)) + 1)] if abs(k - round(k)) < 1e-6 else None


# ---------------------------------------------------------------- модель изделия
def group(d, L, pts, washer=None, pos=None):
    d0 = math.ceil(D1[d] + 2)
    return dict(d=d, d0=d0, D0=d0 + 10, L=L, pts=[tuple(p) for p in pts], washer=washer, pos=pos)


def holed(M):
    """Есть ли отверстия под стержни: только у второй пластины МН 201–228 (поз. 2, как в серии)."""
    return M["fam"] == "B"


def rmark(G):
    """Радиус метки вокруг стержня на чертеже: зенковка (B) или наружный контур углового шва."""
    return G["D0"] / 2 if G.get("holed") else G["d"] / 2 + G["k"]


def finish(M):
    """Производные величины модели: оси, глубины, длины стержней, основная группа, проверки ГОСТ."""
    t = M["t"]
    for G in M["groups"]:
        G["k"] = leg(G["d"], t)
        if M["fam"] == "B":                          # поз. 1 — в тавр, поз. 2 — стержень заходит на t/2 в отверстие
            G.update(tb=t, depth=M["H"], rod=M["H"] - 1.5 * t, gap=M["H"] - 2 * t, holed=True)
        else:                                        # торцы стержня — в упор в пластину и шайбу
            tb = G["washer"]["t"] if G["washer"] else 0
            G.update(tb=tb, depth=t + G["L"] + tb, rod=G["L"], gap=G["L"], holed=False,
                     kw=leg(G["d"], tb) if tb else None)
    M["xs"] = sorted({p[0] for G in M["groups"] for p in G["pts"]})
    M["ys"] = sorted({p[1] for G in M["groups"] for p in G["pts"]})
    M["n"] = sum(len(G["pts"]) for G in M["groups"])
    M["main"] = max(M["groups"], key=lambda G: len(G["pts"]))
    M["depth"] = max(G["depth"] for G in M["groups"])
    M.setdefault("bents", None)
    M["top"] = 0
    if M["bents"]:
        b = M["bents"]
        M["depth"] = max(M["depth"], t + b["d"] + b["h"])
        M["top"] = max(0, b["rise"] - b["kink"])
    M["top_plan"] = min(M["top"], STUB)
    M.setdefault("tech", [])
    M.setdefault("risk_x", None)
    M.setdefault("unc", [])
    M.setdefault("strip", None)
    M["warn"] = checks(M)
    return M


def build_15(r, lengths=None):
    """Запись сайта серии 1.400-15 -> модель или (None, причина). lengths: {марка|"*": длина} для погонных."""
    grp = int(r["Группа"].split()[1])
    fam = "A" if 101 <= grp <= 164 else "B" if 201 <= grp <= 228 else "C" if 301 <= grp <= 325 else None
    if not fam:
        return None, "семейство пока не поддержано (см. README)"
    if fam == "C":
        return build_15_bent(r)
    A, B, t = (num(r.get(f"Размер пластины, мм [{k}]")) for k in "АBб")
    m = re.match(r"(\d+)ф(\d+)", r.get("Количество и диаметр анкеров", ""))
    strip = None
    if B is None:
        Lp = (lengths or {}).get(r["Изделие"], (lengths or {}).get("*"))
        if not Lp:
            return None, "погонное изделие (B = п.м.) — длина по заказу: --length"
        pitch = num(r.get("Привязки анкеров, мм [b1]"))
        ys = axis(A, num(r.get("Привязки анкеров, мм [а2]")), num(r.get("Привязки анкеров, мм [а1]")))
        k = int(Lp // pitch)
        if not (ys and m and k >= 1):
            return None, "погонное: не восстановить расстановку"
        e = (Lp - pitch * (k - 1)) / 2              # ряд по центру; при кратной длине — e = шаг/2
        xs = [e + i * pitch for i in range(k)]
        strip = dict(pitch=pitch, per_m=int(m[1]), e=e, width=A)
        A, B = Lp, A
        d = int(m[2])
        pts = [(x, y) for x in xs for y in ys]
    else:
        xs = axis(A, num(r.get("Привязки анкеров, мм [а2]")), num(r.get("Привязки анкеров, мм [а1]")))
        ys = axis(B, num(r.get("Привязки анкеров, мм [b2]")), num(r.get("Привязки анкеров, мм [b1]")))
        if not (xs and ys and m):
            return None, "не восстановить сетку анкеров"
        n, d = int(m[1]), int(m[2])
        pts = [(x, y) for x in xs for y in ys]
        if len(pts) == n + 1 and len(xs) == len(ys) == 3:
            pts.remove((xs[1], ys[1]))          # 3×3 без центра (МН 146–151, сверено по альбому)
        if len(pts) != n:
            return None, f"сетка {len(xs)}×{len(ys)} ≠ {n} анкеров"
    M = dict(series="1.400-15 вып. 1", mark=r["Изделие"] + (f" L{fmt(A)}" if strip else ""), base=r["Изделие"],
             strip=strip, fam=fam, code=r.get("Обозначение детали", "").replace("B1", "В1"),
             A=A, B=B, t=t, site_mass=None if strip else num(r.get("Итого, кг")), cut_x=None, cut_z=None)
    if fam == "A":
        L = num(r.get("Длина анкеров, мм [L]"))
        w = r.get("Размеры пластин усиления и кол-во, мм")
        washer = None
        if w:
            mw = re.match(r"(\d+)х(\d+)х(\d+) \(шт\.(\d+)\)", w)
            washer = dict(c=int(mw[1]), t=int(mw[3]))
        M["groups"] = [group(d, L, pts, washer)]
    else:
        M["H"] = num(r.get("Размер, мм [H]"))
        M["groups"] = [group(d, None, pts)]
    return finish(M), None


def build_15_bent(r):
    """МН 301–325: пластина + прямые анкеры (верхний ряд — с шайбами) + гнутые анкеры внахлёстку на тыльной стороне."""
    fix = SITE_FIX_15.get(r["Изделие"])
    if fix:
        r = {**r, **{k: v for k, v in fix.items() if not k.startswith("_")}}
    A, B, t = (num(r.get(f"Размер пластины, мм [{k}]")) for k in "АBб")
    ms = re.match(r"(\d+)ф(\d+)", r.get("Количество и диаметр прямых анкеров", ""))
    mb = re.match(r"(\d+)ф(\d+)", r.get("Количество и диаметр гнутых анкеров", ""))
    xs = axis(A, num(r.get("Привязки анкеров, мм [а2]")), num(r.get("Привязки анкеров, мм [а1]")))
    ys = axis(B, num(r.get("Привязки анкеров, мм [b2]")), num(r.get("Привязки анкеров, мм [b1]")))
    if not (ms and mb):
        return None, "не прочитаны анкеры"
    if not (xs and ys):
        return None, (f"привязки прямых анкеров не сходятся с пластиной: b2+b1+b2 = "
                      f"{r.get('Привязки анкеров, мм [b2]')}+{r.get('Привязки анкеров, мм [b1]')}+"
                      f"{r.get('Привязки анкеров, мм [b2]')} ≠ B = {fmt(B)} (так и в альбоме, стр. 100)")
    n, d = int(ms[1]), int(ms[2])
    pts = [(x, y) for x in xs for y in ys]
    if len(pts) == n + 1 and len(xs) == len(ys) == 3:
        pts.remove((xs[1], ys[1]))              # 3×3 без центра (МН 312–313, сверено по альбому, стр. 106)
    if len(pts) != n:
        return None, f"сетка прямых {len(xs)}×{len(ys)} ≠ {n} анкеров"
    nb, db = int(mb[1]), int(mb[2])
    c2, c1 = num(r.get("Привязки анкеров, мм [c2]")), num(r.get("Привязки анкеров, мм [c1]"))
    cx = axis(A, c2, c1)
    if (not cx or len(cx) != nb) and nb == 4:
        cx = [c2, c2 + c1, A - c2 - c1, A - c2]   # две пары зеркально (МН 318–321: 75/90/70/90/75, стр. 112)
    if not cx or len(cx) != nb:
        return None, "не восстановить раскладку гнутых анкеров (c1/c2)"
    l1, h = num(r.get("Длина гнутых анкеров, мм [l]")), num(r.get("Длина гнутых анкеров, мм [h]"))
    if db not in BENT_L2 or not l1 or not h or h >= l1:
        return None, "гнутый анкер: нет l2 для диаметра / нет l, h"
    l2 = BENT_L2[db]
    bents = dict(d=db, l1=l1, l2=l2, L=l1 + l2, h=h, rise=math.sqrt(l1 ** 2 - h ** 2), kink=KINK, xs=cx, n=nb)
    w = r.get("Размеры пластин усиления и кол-во, мм")
    top = [p for p in pts if p[1] == ys[0]]
    rest = [p for p in pts if p[1] != ys[0]]
    washer = None
    if w:
        mw = re.match(r"(\d+)х(\d+)х(\d+) \(шт\.(\d+)\)", w)
        if int(mw[4]) != len(top):
            return None, f"шайб {mw[4]} ≠ анкеров верхнего ряда {len(top)}"
        washer = dict(c=int(mw[1]), t=int(mw[3]))
    L = num(r.get("Длина прямых анкеров, мм [L]"))
    groups = [group(d, L, top, washer)] + ([group(d, L, rest)] if rest else [])
    M = dict(series="1.400-15 вып. 1", mark=r["Изделие"], base=r["Изделие"], fam="C",
             code=r.get("Обозначение детали", "").replace("B1", "В1"), A=A, B=B, t=t,
             site_mass=num(r.get("Итого, кг")), groups=groups, bents=bents, cut_x=None, cut_z=None)
    return finish(M), None


SUPPORTED_676 = {"plate_straight", "plate_straight_washers"}


def build_676(it, page):
    """Изделие из оцифровки листа альбома 1.400-6/76 -> модель или (None, причина)."""
    if it.get("family") == "plate_bent":
        return None, ("гнутые анкеры серии 6/76: на листах не задан подъём отгиба (поз. 347 — «100» или «180») "
                      "или направление наклона — нужна проверка листа")
    if it.get("family") not in SUPPORTED_676:
        return None, f"семейство «{it.get('family')}» пока не поддержано (см. README)"
    pl = it.get("plate") or {}
    A, B, t = num(pl.get("A")), num(pl.get("B")), num(pl.get("t"))
    if None in (A, B, t) or (pl.get("qty") or 1) != 1:
        return None, "пластина не прочитана (null) или их несколько"
    sp = next((r for r in it.get("spec") or [] if r.get("pos") == pl.get("pos")), None)
    if sp:
        ms_ = re.search(r"(\d+)\s*[×x]\s*(\d+)", str(sp.get("section") or ""))
        if ms_ and num(sp.get("length")) and {num(ms_[1]), num(sp["length"])} != {A, B}:
            return None, f"пластина {fmt(A)}×{fmt(B)} не сходится со спецификацией {sp['section']} L{sp['length']}"
        if ms_ and num(ms_[2]) != t:
            return None, f"толщина {fmt(t)} не сходится со спецификацией {sp['section']}"
    if it.get("extra_plates") or it.get("other"):
        return None, "есть доп. пластины / прочие элементы — пока не поддержано"
    wmap = {w["pos"]: w for w in it.get("washers") or []}
    groups = []
    for a in it.get("anchors") or []:
        d, L, pts = a.get("d"), num(a.get("L")), a.get("points") or []
        if a.get("kind") != "straight" or a.get("thread"):
            return None, "гнутые / с нарезкой анкеры — пока не поддержано"
        if not d or d not in D1 or L is None or len(pts) != a.get("qty") or any(None in p for p in pts):
            return None, "анкеры не прочитаны полностью (null)"
        washer = None
        if a.get("washer_pos"):
            w = wmap.get(a["washer_pos"])
            if not w or w.get("a") != w.get("b") or None in (w.get("a"), w.get("t")):
                return None, "шайба не квадратная или не прочитана"
            washer = dict(c=w["a"], t=w["t"])
        groups.append(group(int(d), L, pts, washer, a.get("pos")))
    if not groups:
        return None, "нет анкеров"
    tech = []
    for h in it.get("tech_holes") or []:
        mm = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*[x×х]\s*(\d+(?:[.,]\d+)?)\s*", str(h.get("size") or ""))
        pts = h.get("points") or []
        if not mm or not pts or any(None in q for q in pts):
            return None, f"технологическое отверстие «{h.get('size')}» — нестандартное или без привязки"
        tech.append(dict(w=num(mm[1]), h=num(mm[2]), pts=[tuple(q) for q in pts]))
    unc = list(it.get("uncertain") or [])
    M = dict(series="1.400-6/76 вып. 1", mark=it["mark"], base=it["mark"], fam="A", A=A, B=B, t=t,
             code=f"лист {page['sheet']}, стр. {page['page']} альбома", site_mass=num(it.get("mass_total")),
             groups=groups, tech=tech, risk_x=num(it.get("risk_top_x")), unc=unc, cut_x=None, cut_z=None)
    return finish(M), None


def checks(M):
    """Отступления от ГОСТ 14098-2014 табл. 16 (Т11-Мз) — для отчёта; по решению завода не блокируют."""
    w = []
    for G in M["groups"]:
        d = G["d"]
        if not G.get("holed"):
            continue
        if not 12 <= d <= 25:
            w.append(f"dн={d} вне 12–25")
        need = 8 if d <= 16 else 10 if d <= 20 else 12
        for nm, s in (("пластина", M["t"]), ("шайба", G["washer"]["t"] if G["washer"] else None)):
            if s is None:
                continue
            if s < need:
                w.append(f"{nm} s={fmt(s)} < {need} (Ø{d})")
            if s / d < 0.55:
                w.append(f"{nm} s/d={s / d:.2f} < 0,55 (Ø{d})")
        edge = min(min(x, M["A"] - x, y, M["B"] - y) for x, y in G["pts"])
        if edge < 1.5 * d:
            w.append(f"до кромки {fmt(edge)} < 1,5d={fmt(1.5 * d)}")
        if G["washer"] and G["washer"]["c"] / 2 < 1.5 * d:
            w.append(f"шайба c/2={fmt(G['washer']['c'] / 2)} < 1,5d")
        if G["washer"] and G.get("holed") and G["D0"] > G["washer"]["c"] - 4:
            w.append(f"D0={G['D0']} не помещается в шайбу {G['washer']['c']}")
    b = M.get("bents")
    if b:
        y0, y1 = b["kink"], b["kink"] + b["l2"]
        for G in M["groups"]:
            for x, y in G["pts"]:
                for xb in b["xs"]:
                    if y0 - G["d0"] / 2 - 5 < y < y1 + G["d0"] / 2 + 5 and abs(x - xb) < (b["d"] + G["d0"]) / 2 + 5:
                        w.append(f"нахлёст гнутого анкера x={fmt(xb)} близко к анкеру ({fmt(x)},{fmt(y)})")
        if b["l2"] - 2 * b["d"] < 4 * b["d"]:
            w.append(f"шов нахлёста {fmt(b['l2'] - 2 * b['d'])} < 4d (Н1-Мш)")
    allp = [(p, G["D0"]) for G in M["groups"] if G.get("holed") for p in G["pts"]]
    for i, (p, D) in enumerate(allp):
        for q, E in allp[i + 1:]:
            if math.dist(p, q) < (D + E) / 2 + 4:
                w.append(f"зенковки сближены: {fmt(math.dist(p, q))} мм")
                break
        else:
            continue
        break
    return list(dict.fromkeys(w))


def cone_v(s, r_in, r_out):
    return math.pi * s / 3 * (r_in ** 2 + r_in * r_out + r_out ** 2)


def washer_types(M):
    """Типы шайб: (c, t) -> кол-во. Шайбы сплошные, стержень приваривается к ним в тавр (как в серии)."""
    c = Counter()
    for G in M["groups"]:
        if G["washer"]:
            c[wkey(G)] += len(G["pts"])
    return c


def wkey(G):
    return (G["washer"]["c"], G["washer"]["t"])


def masses(M):
    t = M["t"]
    plate_g = M["A"] * M["B"] * t * RHO
    holes = sum(len(G["pts"]) * cone_v(t, G["d0"] / 2, G["D0"] / 2) for G in M["groups"] if G.get("holed"))
    tech = sum(len(h["pts"]) * h["w"] * h["h"] * t for h in M["tech"])
    out = dict(plate_g=plate_g, plate_n=plate_g - tech * RHO, plate2_n=plate_g - holes * RHO,
               sheets={}, rebar={}, washers={})
    nplates = 2 if M["fam"] == "B" else 1
    out["sheets"][t] = plate_g * nplates
    for (c, wt), q in washer_types(M).items():
        wg = c * c * wt * RHO
        out["washers"][(c, wt)] = wg
        out["sheets"][wt] = out["sheets"].get(wt, 0) + wg * q
    for G in M["groups"]:
        G["rod_m"] = KG_M[G["d"]] * G["rod"] / 1000
        out["rebar"][G["d"]] = out["rebar"].get(G["d"], 0) + G["rod_m"] * len(G["pts"])
    b = M.get("bents")
    if b:
        out["bent_m"] = KG_M[b["d"]] * b["L"] / 1000
        out["rebar"][b["d"]] = out["rebar"].get(b["d"], 0) + out["bent_m"] * b["n"]
    base = sum(out["sheets"].values()) + sum(out["rebar"].values())
    out["dep"] = base * 0.01
    out["all"] = base + out["dep"]
    return out


def positions(M):
    """Номера позиций: 1 — пластина, далее стержни по группам (одинаковые d и длина — одна позиция), затем шайбы."""
    rods, pos = {}, (3 if M["fam"] == "B" else 2)
    for G in M["groups"]:
        key = (G["d"], G["rod"])
        if key not in rods:
            rods[key] = pos
            pos += 1
        G["p"] = rods[key]
    if M.get("bents"):
        M["bents"]["p"] = pos
        pos += 1
    wpos = {}
    for key in washer_types(M):
        wpos[key] = pos
        pos += 1
    return rods, wpos


# ---------------------------------------------------------------- DXF (R12, мм)
def dxf_write(path, items):
    """items: [('LINE', layer, x1, y1, x2, y2) | ('CIRCLE', layer, cx, cy, r) | ('PLINE', layer, [(x, y), ...])]
    PLINE — замкнутая полилиния R12 (POLYLINE/VERTEX/SEQEND, флаг 1)."""
    L = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$DWGCODEPAGE", "3", "ANSI_1251",
         "9", "$INSUNITS", "70", "4",
         "0", "ENDSEC", "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", "2"]
    for name, color in (("CUT", 7), ("GRAV", 1)):
        L += ["0", "LAYER", "2", name, "70", "0", "62", str(color), "6", "CONTINUOUS"]
    L += ["0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    for it in items:
        if it[0] == "PLINE":
            _, lay, pts = it
            L += ["0", "POLYLINE", "8", lay, "66", "1", "10", "0.0", "20", "0.0", "30", "0.0", "70", "1"]
            for x, y in pts:
                L += ["0", "VERTEX", "8", lay, "10", f"{x:.4f}", "20", f"{y:.4f}", "30", "0.0"]
            L += ["0", "SEQEND", "8", lay]
        elif it[0] == "LINE":
            _, lay, x1, y1, x2, y2 = it
            L += ["0", "LINE", "8", lay, "10", f"{x1:.4f}", "20", f"{y1:.4f}", "11", f"{x2:.4f}", "21", f"{y2:.4f}"]
        else:
            _, lay, cx, cy, rr = it
            L += ["0", "CIRCLE", "8", lay, "10", f"{cx:.4f}", "20", f"{cy:.4f}", "40", f"{rr:.4f}"]
    L += ["0", "ENDSEC", "0", "EOF"]
    path.write_bytes(("\r\n".join(L) + "\r\n").encode("cp1251"))


def rect_pl(x, y, w, h, lay="CUT"):
    return ("PLINE", lay, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)])


def dxf_parts(M, folder):
    files = []
    B = M["B"]
    if holed(M):                                     # поз. 2 — с раззенкованными отверстиями (Пл-21а серии)
        ents = [rect_pl(0, 0, M["A"], B)]
        for G in M["groups"]:
            for x, y in G["pts"]:
                ents += [("CIRCLE", "CUT", x, B - y, G["d0"] / 2), ("CIRCLE", "GRAV", x, B - y, G["D0"] / 2)]
        f = folder / f"{M['mark']}_поз2_пластина_отв_t{fmt(M['t'])}_1шт.dxf"
        dxf_write(f, ents)
        files.append(f.name)
    ents = [rect_pl(0, 0, M["A"], B)]                # поз. 1 — сплошная
    for h in M["tech"]:
        for x, y in h["pts"]:
            ents.append(rect_pl(x - h["w"] / 2, B - y - h["h"] / 2, h["w"], h["h"]))
    if M["risk_x"] is not None:
        ents.append(("LINE", "GRAV", M["risk_x"], B, M["risk_x"], B - 10))
    f = folder / f"{M['mark']}_поз1_пластина_t{fmt(M['t'])}_1шт.dxf"
    dxf_write(f, ents)
    files.insert(0, f.name)
    _, wpos = positions(M)
    for (c, wt), q in washer_types(M).items():
        ents = [rect_pl(0, 0, c, c)]
        f = folder / f"{M['mark']}_поз{wpos[(c, wt)]}_шайба_t{fmt(wt)}_{q}шт.dxf"
        dxf_write(f, ents)
        files.append(f.name)
    return files


# ---------------------------------------------------------------- компоновка
def zigzag(x, y0, y1):
    """Линия обрыва (тонкая с изломом посередине) по вертикали x от y0 до y1."""
    ym = (y0 + y1) / 2
    g.poly([(x, y0), (x, ym - 3), (x - 1.5, ym - 1.5), (x + 1.5, ym + 1.5), (x, ym + 3), (x, y1)], g.THIN, close=False)


def chain_v(vals, y0, S, x_obj, x_dim, h):
    for i, (a, b) in enumerate(zip(vals[:-1], vals[1:])):
        g.dim_v(y0 + a * S, y0 + b * S, x_obj, x_dim, fmt(b - a), outside=(b - a) * S < 8, h=h,
                side="top" if i == 0 else "bottom")


def strip_section(y0, y1, holes, face, back):
    """Сечение пластины (y0..y1) с отверстиями holes = [(yc, r_in, r_out)] (r_out — со стороны face)."""
    holes = sorted(holes)
    pb = [y0] + [v for yc, ri, ro in holes for v in (yc - ri, yc + ri)] + [y1]
    pf = [y0] + [v for yc, ri, ro in holes for v in (yc - ro, yc + ro)] + [y1]
    return [[(face, pf[i]), (back, pb[i]), (back, pb[i + 1]), (face, pf[i + 1])] for i in range(0, len(pb), 2)]


def amap(cut, S):
    """Натура -> мм листа вдоль оси с разрывом cut=(c1, c2) (часть c1..c2 вырезана)."""
    if not cut:
        return lambda v: v * S
    c1, c2 = cut
    return lambda v: v * S if v <= c1 else c1 * S + GAP + (max(v, c2) - c2) * S


def span(total, cut, S):
    return amap(cut, S)(total)


def column(M):
    """Стержни в плоскости разреза 1-1 (x = первая ось анкеров): [(y, G)]."""
    x0 = M["xs"][0]
    return sorted([(p[1], G) for G in M["groups"] for p in G["pts"] if abs(p[0] - x0) < 0.01], key=lambda v: v[0])


def cuts(M):
    """Варианты разрывов: (cut_x вида с лица — только погонные, cut_z разреза — длинные стержни)."""
    cx = [None]
    if M["strip"] and len(M["xs"]) >= 3:
        p = M["strip"]["pitch"]
        cx.append((M["xs"][0] + p / 2, M["xs"][-1] - p / 2))
    cz = [None]
    col = column(M)
    z1 = M["t"] + SHOW
    z2 = min(M["t"] + G["gap"] for _, G in col) - SHOW
    if z2 - z1 > 60 and not M.get("bents"):
        cz.append((z1, z2))
    return [(a, b) for a in cx for b in cz]


def _node_h(M, k):
    if holed(M):
        return 18 + 10 + M["t"] * k + 12 * k + 19
    return 18 + 10 + (M["t"] + M["main"]["k"] + 14) * k + 7 + 5 * 4


def layout(M):
    """Масштаб видов и положение: вид с лица сверху, разрез 1-1 снизу, узел Б справа от вида (или разрез справа,
    узел снизу). Узел 2:1 или 1:1, разрывы — что даёт виды крупнее; при равенстве — без разрыва и 2:1."""
    if M["bents"]:
        return _layout_bent(M)
    cands = []
    for cx, cz in cuts(M):
        for k in (2.0, 1.0):
            for f in (_layout, _layout_side, _layout_wide):
                x = f(M, k, cx, cz)
                if x:
                    x.update(cut_x=cx, cut_z=cz)
                    cands.append(x)
    key = lambda x: (min(x["S"], x["Ss"]), -(x["cut_x"] is not None) - (x["cut_z"] is not None),
                     x["S"] + x["Ss"], x["node_scale"])
    return max(cands, key=key) if cands else None


def _layout_bent(M):
    """С гнутыми стержнями: вид с лица слева вверху, высокий разрез 1-1 справа от него на всю высоту поля,
    узел Б под видом. Масштабы вида и разреза — свои, крупнейшие из помещающихся."""
    A, B, t, depth = M["A"], M["B"], M["t"], M["depth"]
    best = None
    for k in (2.0, 1.0):
        hw = (rmark(M["main"]) + 6) * k
        nh = t * k + 12 * k + 43
        for Sp, lp in SCALES:
            PY = 30 + M["top_plan"] * Sp + 14
            NY = PY + B * Sp + 28 + 30
            if NY + nh > 288 or 2 * hw + 10 > max(A * Sp, 60):
                continue
            SX = 48 + A * Sp + 40
            for Ss, ls in SCALES:
                if SX + depth * Ss + 30 > 226:
                    continue
                SY = 36
                if SY + 8 + (M["top"] + B) * Ss + 50 > 288:
                    continue
                c = dict(S=Sp, label=lp, Ss=Ss, label_s=ls, PX=48, PY=PY, SX=SX, SY=SY + 8, side=True,
                         node_scale=k, NX=48 + hw + 4, NY=NY, cut_x=None, cut_z=None)
                key = lambda c_: (min(c_["S"], c_["Ss"]), c_["Ss"], c_["S"] + c_["Ss"], c_["node_scale"])
                if not best or key(c) > key(best):           # при равенстве — крупнее разрез
                    best = c
                break
    return best


def _layout_wide(M, k, cx, cz):
    """Вид А во всю ширину поля, разрез 1-1 под ним, узел Б — под разрезом слева."""
    A, B, depth = M["A"], M["B"], M["depth"]
    hw = (rmark(M["main"]) + 6) * k
    nh = _node_h(M, k) + 6 * len(M["groups"])
    lab_w = 22 if M["tech"] or M["risk_x"] is not None else 30
    extra = 7 * (len({G["depth"] for G in M["groups"]}) - 1)
    best = None
    for Sp, lp in SCALES:
        if span(A, cx, Sp) > 226 - 48 - 12 - lab_w:
            continue
        plan_bottom = 30 + B * Sp + 28
        for Ss, ls in SCALES:
            if span(depth, cz, Ss) > 150 or (Ss > Sp and B * Ss > 90):
                continue
            SY = plan_bottom + 24 + extra
            NY = SY + B * Ss + 18 + 30
            if NY + nh <= 288:
                c = dict(S=Sp, label=lp, Ss=Ss, label_s=ls, PX=48, PY=30, SX=48, SY=SY, node_scale=k,
                         NX=48 + hw + 8, NY=NY)
                if not best or Sp + Ss > best["S"] + best["Ss"]:
                    best = c
                break
    return best


def _layout_side(M, k, cx, cz):
    """Разрез справа от вида (одинаковый масштаб, общая горизонталь), узел Б — под ними.
    С гнутыми стержнями: пластины вида и разреза на одной горизонтали ниже выступа стержней, узел — над видом."""
    A, B, depth = M["A"], M["B"], M["depth"]
    hw = (rmark(M["main"]) + 6) * k
    for S, lab in SCALES:
        if span(A, cx, S) + span(depth, cz, S) > 110:
            continue
        if M["bents"]:
            PY = 58 + M["top"] * S
            nh = M["t"] * k + 12 * k + 34
            if PY + B * S + 50 > 288:
                continue
            if 52 + nh <= PY - M["top_plan"] * S - 12 and 48 + 2 * hw + 14 <= span(A, cx, S) + 12:
                NY = 52
            elif PY + B * S + 58 + nh <= 288:
                NY = PY + B * S + 58
            else:
                continue
            return dict(S=S, label=lab, Ss=S, label_s=lab, PX=48, PY=PY, SX=48 + span(A, cx, S) + 36,
                        SY=PY - M["top"] * S, side=True, node_scale=k, NX=48 + hw + 14, NY=NY)
        PY = 38
        bottom = PY + B * S + 28
        NY = bottom + 30
        if NY + M["t"] * k + 12 * k + 24 + 6 * (len(M["groups"]) - 1) <= 288:
            return dict(S=S, label=lab, Ss=S, label_s=lab, PX=48, PY=PY, SX=48 + span(A, cx, S) + 36,
                        SY=PY - M["top"] * S, side=True,
                        node_scale=k, NX=48 + hw + 14, NY=NY)
    return None


def _layout(M, node_scale, cx, cz):
    A, B, depth = M["A"], M["B"], M["depth"]
    node_h = _node_h(M, node_scale)
    best = None
    lab_w = 22 if M["tech"] or M["risk_x"] is not None else 0          # подписи справа от вида А
    plan_w = min(100, 226 - 48 - 12 - lab_w - (2 * (rmark(M["main"]) + 6) * node_scale + 16))
    extra = 0 if M["bents"] else 7 * (len({G["depth"] for G in M["groups"]}) - 1)   # доп. размеры над разрезом
    for Sp, lp in SCALES:
        if span(A, cx, Sp) > plan_w:
            continue
        PY = 30 + M["top_plan"] * Sp + (14 if M["bents"] else 0)
        plan_bottom = PY + B * Sp + 28
        for Ss, ls in SCALES:
            if span(depth, cz, Ss) > 150 or (Ss > Sp and B * Ss > 90):
                continue
            SY = plan_bottom + 24 + extra
            if span(depth, cz, Ss) + 50 > 102:
                SY = max(SY, 30 + node_h + 22 + extra)
            if SY + (B + M["top"]) * Ss + (50 if M["bents"] else 18) <= 288 and (not best or Sp + Ss > best["S"] + best["Ss"]):
                hw = (rmark(M["main"]) + 6) * node_scale
                best = dict(S=Sp, label=lp, Ss=Ss, label_s=ls, PX=48, PY=PY, SX=48, SY=SY, node_scale=node_scale,
                            NX=216 - hw, NY=52)
    return best


# ---------------------------------------------------------------- чертёж
def wtag(k):
    return f"{FILLET_TAG}, k={k}"


def fillet(s, zf, y, r, k, sg, S):
    """Угловой шов в разрезе: два залитых треугольника катетом k у грани zf (sg = +1 — шов в сторону +z)."""
    if not k:
        return
    for dy in (-1, 1):
        g.poly([s(zf, y + dy * r), s(zf + sg * k, y + dy * r), s(zf, y + dy * (r + k))], 0.1, fill=g.BLACK)


def node_hole(M, G0, k, NX, NY, t, wpos):
    """Узел Б: стержень во второй пластине (поз. 2) — раззенкованное отверстие, Т11-Мз."""
    r_rod, r_in, r_out = G0["d"] / 2, G0["d0"] / 2, G0["D0"] / 2
    HW = r_out + 6
    n = lambda u, v: (NX + u * k, NY - v * k)
    for pc in strip_section(-HW, HW, [(0, r_in, r_out)], 0, -t):
        q = [n(y, z) for (z, y) in pc]
        g.hatch(q, 1.5)
        g.poly(q)
    for dx in (-r_rod, r_rod):
        g.line(*n(dx, -t / 2), *n(dx, -t - 12), g.MAIN)
    g.line(*n(-r_rod, -t / 2), *n(r_rod, -t / 2), g.MAIN)
    g.poly([n(-r_rod + 2 * r_rod * i / 20, -t - 12 + 0.8 * math.sin(i / 20 * 2 * math.pi)) for i in range(21)],
           g.THIN, close=False)
    g.line(*n(0, 4), *n(0, -t - 12), dash=g.AXIS)
    g.text(NX, NY - 18, f"Б ({'2:1' if k == 2 else '1:1'})", h=5, align="c")
    g.dim_h(n(-r_out, 0)[0], n(r_out, 0)[0], NY, NY - 8, f"Ø{G0['D0']}")
    yb = n(0, -t)[1]
    g.dim_h(n(-r_in, -t)[0], n(r_in, -t)[0], yb, yb + 12 * k + 9, f"Ø{G0['d0']}")
    g.dim_v(NY, yb, n(-HW, 0)[0], n(-HW, 0)[0] - 6, fmt(t))
    g.dim_v(n(0, -t / 2)[1], yb, n(r_rod, 0)[0], n(HW, 0)[0] + 6, fmt(t / 2), outside=t / 2 * k < 8)
    px_, py_ = n(r_out * 0.8, -1)
    g.shelf(px_, py_, max(px_ + 2, min(n(HW, 0)[0] + 3, 226 - g.tlen(WELD, 3) - 2)), yb + 8, WELD, h=3)
    g.text(NX, yb + 12 * k + 17, "Пластина поз. 2 (наружная грань сверху)", h=2.5, align="c")


def node_fillet(M, G0, k, NX, NY, t, wpos):
    """Узел Б: стержень в тавр к сплошной пластине, угловой шов по контуру катетом k (полуавтомат)."""
    r, kk = G0["d"] / 2, G0["k"]
    HW = r + kk + 8
    n = lambda u, v: (NX + u * k, NY - v * k)
    q = [n(-HW, 0), n(HW, 0), n(HW, -t), n(-HW, -t)]
    g.hatch(q, 1.5)
    g.poly(q)
    for u in (-HW, HW):                              # линии обрыва пластины
        g.line(*n(u, 0.5), *n(u, -t - 0.5), g.THIN)
    for dx in (-r, r):
        g.line(*n(dx, -t), *n(dx, -t - kk - 14), g.MAIN)
    g.poly([n(-r + 2 * r * i / 20, -t - kk - 14 + 0.8 * math.sin(i / 20 * 2 * math.pi)) for i in range(21)],
           g.THIN, close=False)
    for sg in (-1, 1):
        g.poly([n(sg * r, -t), n(sg * (r + kk), -t), n(sg * r, -t - kk)], 0.1, fill=g.BLACK)
    g.line(*n(0, 4), *n(0, -t - kk - 14), dash=g.AXIS)
    g.text(NX, NY - 18, f"Б ({'2:1' if k == 2 else '1:1'})", h=5, align="c")
    yb = n(0, -t)[1]
    g.dim_v(NY, yb, n(-HW, 0)[0], n(-HW, 0)[0] - 6, fmt(t))
    g.dim_v(yb, n(0, -t - kk)[1], n(r, 0)[0], n(HW, 0)[0] + 6, str(kk), outside=kk * k < 8)
    px_, py_ = n(r + kk * 0.3, -t - kk * 0.3)
    lab = wtag(kk)
    x1 = min(n(r + kk, 0)[0] + 3, 226 - g.tlen(lab, 3) - 2)
    g.shelf(px_, py_, max(x1, px_ + 1), n(0, -t - kk)[1] + 10, lab, h=3)
    lines = [f"{FILLET_TAG} — по замкнутому контуру стержня", "Торец стержня — в упор, зазор не более 1 мм"]
    if washer_types(M):
        kws = sorted({G["kw"] for G in M["groups"] if G["washer"]})
        lines.append(f"Шайбы — то же, k={'/'.join(map(str, kws))}")
    if M["fam"] == "B":
        lines.append("Пластина поз. 1")
    yl = n(0, -t - kk - 14)[1] + 7
    for j, ln in enumerate(lines):
        g.text(NX, yl + 5 * j, ln, h=2.5, align="c")


def draw(M, ms, pdf_path, png_path=None):
    L = layout(M)
    if not L:
        raise ValueError("не помещается на А3")
    S, Ss, PX, PY, SX, SY = L["S"], L["Ss"], L["PX"], L["PY"], L["SX"], L["SY"]
    A, B, t, depth = M["A"], M["B"], M["t"], M["depth"]
    rods, wpos = positions(M)
    h = 3.5 if S >= 0.25 else 2.5
    hs = 3.5 if Ss >= 0.25 else 2.5
    g.new_sheet()

    # ---- вид с лица
    cx_, cz_ = L["cut_x"], L["cut_z"]
    fx = amap(cx_, S)
    vis_x = lambda x: not cx_ or x <= cx_[0] or x >= cx_[1]
    p = lambda x, y: (PX + fx(x), PY + y * S)
    W = fx(A)
    if cx_:
        a1, a2 = PX + fx(cx_[0]), PX + fx(cx_[1])
        for y in (PY, PY + B * S):
            g.line(PX, y, a1, y, g.MAIN)
            g.line(a2, y, PX + W, y, g.MAIN)
        g.line(PX, PY, PX, PY + B * S, g.MAIN)
        g.line(PX + W, PY, PX + W, PY + B * S, g.MAIN)
        zigzag(a1 + 1, PY - 3, PY + B * S + 3)
        zigzag(a2 - 1, PY - 3, PY + B * S + 3)
    else:
        g.rect(PX, PY, W, B * S)
    for x in M["xs"]:
        if vis_x(x):
            g.line(*p(x, -6), *p(x, B + 6), dash=g.AXIS)
    for y in M["ys"]:
        for xa, xb in ([(-6, cx_[0]), (cx_[1], A + 6)] if cx_ else [(-6, A + 6)]):
            g.line(*p(xa, y), *p(xb, y), dash=g.AXIS)
    for G in M["groups"]:
        for x, y in G["pts"]:
            if not vis_x(x):
                continue
            g.circle(*p(x, y), G["d"] / 2 * S, g.THIN, dash=g.HIDDEN)      # стержень за сплошной пластиной
            if G["washer"]:
                c = G["washer"]["c"]
                g.rect(*p(x - c / 2, y - c / 2), c * S, c * S, g.THIN, dash=g.HIDDEN)
    for hh in M["tech"]:
        for x, y in hh["pts"]:
            g.rect(*p(x - hh["w"] / 2, y - hh["h"] / 2), hh["w"] * S, hh["h"] * S, g.MAIN)
    tx = sorted({x for hh in M["tech"] for x, _ in hh["pts"]})
    ty = sorted({y for hh in M["tech"] for _, y in hh["pts"]})
    vx = sorted({0, A} | {x for x in M["xs"] + tx if vis_x(x)})
    pitch = M["strip"]["pitch"] if M["strip"] else None
    for i, (a, b) in enumerate(zip(vx[:-1], vx[1:])):
        crosses = cx_ and a <= cx_[0] and b >= cx_[1]
        lab = f"{round((b - a) / pitch)}×{fmt(pitch)}={fmt(b - a)}" if crosses and pitch else fmt(b - a)
        g.dim_h(PX + fx(a), PX + fx(b), PY + B * S, PY + B * S + 16, lab, outside=(fx(b) - fx(a)) < 8, h=h,
                side="left" if i == 0 else "right")
    g.dim_h(PX, PX + W, PY + B * S, PY + B * S + 24, fmt(A), h=h)
    chain_v(sorted({0, B} | set(M["ys"]) | set(ty)), PY, S, PX, PX - 8, h)
    g.dim_v(PY, PY + B * S, PX, PX - 16, fmt(B), h=h)
    cxp = p(M["xs"][0], 0)[0]
    vd = 1 if M["bents"] else -1                      # смотрим в сторону гнутых стержней — они видны за разрезом
    aln = 4 if M["bents"] else 7
    g.cut_mark(cxp, PY - 1, 0, -1, vd, 0, "1", ln=aln)
    g.cut_mark(cxp, PY + B * S + 1, 0, 1, vd, 0, "1", ln=aln)
    G0 = M["main"]
    hx, hy = p(G0["pts"][-1][0], G0["pts"][-1][1])
    cnt = Counter()
    for G in M["groups"]:
        cnt[G["d0"] if holed(M) else G["d"]] += len(G["pts"])
    holes_txt = ", ".join((f"{q} отв. Ø{dd} в поз. 2" if holed(M) else f"{q} ст. Ø{dd}") for dd, q in cnt.items())
    G0r = rmark(G0)
    if M["bents"]:
        xh, yh = max((q for G in M["groups"] for q in G["pts"]), key=lambda q: (q[0], q[1]))
        hx, hy = p(xh, yh)
        g.shelf(hx + G0r * S * 0.7, hy - G0r * S * 0.7, PX + W + 4, hy - 6, holes_txt, h=2.5)
    elif L.get("side"):                              # разрез справа — выноска вверх-вправо, над видом
        xh, yh = max((q for G in M["groups"] for q in G["pts"] if vis_x(q[0])), key=lambda q: (q[0], -q[1]))
        hx, hy = p(xh, yh)
        g.shelf(hx - G0r * S * 0.7, hy - G0r * S * 0.7, hx - G0r * S - 3, PY - 13,
                holes_txt + (" (узел Б)" if holed(M) else ""), h=2.5)   # полка влево, над видом: справа — разрез
    else:                                            # от правого нижнего отверстия вправо, за контур
        xh, yh = max((q for G in M["groups"] for q in G["pts"] if vis_x(q[0])), key=lambda q: (q[0], q[1]))
        hx, hy = p(xh, yh)
        g.shelf(hx + G0r * S * 0.7, hy + G0r * S * 0.7, PX + W + 4, PY + B * S + 4,
                holes_txt + (" (узел Б)" if holed(M) else ""), h=2.5)
    if M["tech"]:
        x, y = M["tech"][0]["pts"][-1]
        n_t = sum(len(hh["pts"]) for hh in M["tech"])
        g.shelf(*p(x + M["tech"][0]["w"] / 2, y), PX + W + 4, PY + B * S * 0.5 - 4,
                f"{n_t} отв. {fmt(M['tech'][0]['w'])}×{fmt(M['tech'][0]['h'])}", h=2.5)
    if M["risk_x"] is not None:
        rx, ry = p(M["risk_x"], 0)
        g.line(rx, ry, rx, ry + 10 * S, g.MAIN)
        g.shelf(rx, ry + 5 * S, rx + 6, PY - 5, "Риска «верх»", h=2.5)
    tip = PY - M["top_plan"] * S - (14 if M["bents"] else 0)
    g.text(PX, 14 if L.get("side") else tip - 14, f"А ({L['label']})", h=5)
    b = M["bents"]
    if b:
        r = b["d"] / 2
        st = M["top_plan"]
        for x in b["xs"]:
            g.line(*p(x, -st - 3), *p(x, b["kink"] + b["l2"] + 4), dash=g.AXIS)
            for dx in (-r, r):
                g.line(*p(x + dx, -st), *p(x + dx, 0), g.MAIN)
                g.line(*p(x + dx, 0), *p(x + dx, b["kink"] + b["l2"]), g.THIN, dash=g.HIDDEN)
            if st < M["top"]:                                   # обрыв выступающего стержня
                g.poly([p(x - r - 1 + (2 * r + 2) * i / 12, -st + 1.2 * math.sin(i / 12 * 2 * math.pi) / S * 0.6)
                        for i in range(13)], g.THIN, close=False)
            else:
                g.line(*p(x - r, -st), *p(x + r, -st), g.MAIN)
            g.line(*p(x - r, b["kink"] + b["l2"]), *p(x + r, b["kink"] + b["l2"]), g.THIN, dash=g.HIDDEN)
        yb = PY - st * S - 11
        cxs = [0] + b["xs"] + [A]
        for i, (a, c) in enumerate(zip(cxs[:-1], cxs[1:])):
            g.dim_h(PX + fx(a), PX + fx(c), PY, yb, fmt(c - a), outside=(fx(c) - fx(a)) < 8, h=h,
                    side="left" if i == 0 else "right")
        xb = b["xs"][-1]
        if len(b["xs"]) > 1 and (b["xs"][-1] - b["xs"][-2]) * S > 12:   # в промежуток между стержнями
            g.shelf(*p(xb - r, -st * 0.5), p(xb, 0)[0] - 4, p(0, -st * 0.5)[1] - 3, str(b["p"]))
        else:
            g.shelf(*p(xb + r, -st * 0.5), p(xb, 0)[0] + 5, p(0, -st * 0.5)[1] - 3, str(b["p"]))

    # ---- разрез 1-1 (по первой оси анкеров)
    S = Ss
    SY0 = SY + M["top"] * S
    fz = amap(cz_, S)
    s = lambda z, y: (SX + fz(z), SY0 + y * S)
    D = fz(depth)
    h = hs
    g.text(SX, (SY - 20 - (0 if M["bents"] else 7 * (len({G["depth"] for G in M["groups"]}) - 1))) if not L.get("side") else 14, f"1–1 ({L['label_s']})", h=3.5)
    ya = SY0 + B * S * 0.82                          # стрелка взгляда главного вида «А»
    g.line(SX - 16, ya, SX - 3.5, ya, g.THIN)
    g.arrow(SX - 1.5, ya, 1, 0, 3)
    g.text(SX - 12, ya - 1.5, "А", h=5)
    col = column(M)
    x0 = M["xs"][0]
    th = [(y, hh["h"] / 2, hh["h"] / 2) for hh in M["tech"] for x, y in hh["pts"] if abs(x - x0) < 0.01]
    for pc in strip_section(0, B, th, 0, t):
        q = [s(*pt) for pt in pc]
        g.hatch(q, 0.9)
        g.poly(q)
    if M["fam"] == "B":
        for pc in strip_section(0, B, [(y, G["d0"] / 2, G["D0"] / 2) for y, G in col], depth, depth - t):
            q = [s(*pt) for pt in pc]
            g.hatch(q, 0.9)
            g.poly(q)
    for y, G in col:
        if G["washer"] and M["fam"] in ("A", "C"):
            c, zf = G["washer"]["c"], G["depth"]
            for pc in strip_section(y - c / 2, y + c / 2, [], zf, zf - G["tb"]):
                q = [s(*pt) for pt in pc]
                g.hatch(q, 0.9)
                g.poly(q)
        z_end = G["depth"] - G["tb"] / 2 if M["fam"] == "B" else G["depth"] - G["tb"]
        r = G["d"] / 2
        for za, zb in ([(t, cz_[0]), (cz_[1], z_end)] if cz_ else [(t, z_end)]):
            for dy in (-r, r):
                g.line(*s(za, y + dy), *s(zb, y + dy), g.MAIN)
        for z in (t, z_end):
            g.line(*s(z, y - r), *s(z, y + r), g.MAIN)
        fillet(s, t, y, r, G["k"], 1, S)                       # угловой шов у пластины поз. 1
        if G["washer"] and M["fam"] != "B":
            fillet(s, G["depth"] - G["tb"], y, r, G["kw"], -1, S)
        for za, zb in ([(-5, cz_[0]), (cz_[1], G["depth"] + 5)] if cz_ else [(-5, G["depth"] + 5)]):
            g.line(*s(za, y), *s(zb, y), dash=g.AXIS)
    b = M["bents"]
    yb0_ = col[0][0]
    if b:
        r, zc = b["d"] / 2, t + b["d"] / 2
        yk, yt = b["kink"], b["kink"] - b["rise"]
        ux, uy = b["h"] / b["l1"], -b["rise"] / b["l1"]           # направление наклонного участка (z, y)
        nx, ny = -uy, ux                                          # нормаль
        for sgn in (-1, 1):
            g.poly([s(zc + sgn * r, yk + b["l2"]), s(zc + sgn * r, yk), s(zc + sgn * r * nx + b["h"], yt + sgn * r * ny)],
                   g.MAIN, close=False)
        g.line(*s(zc - r, yk + b["l2"]), *s(zc + r, yk + b["l2"]), g.MAIN)
        g.line(*s(zc - r * nx + b["h"], yt - r * ny), *s(zc + r * nx + b["h"], yt + r * ny), g.MAIN)
        g.poly([s(zc, yk + b["l2"] + 4), s(zc, yk), s(zc + b["h"] * 1.04, yt - b["rise"] * 0.04)], g.THIN, close=False,
               dash=g.AXIS)
        # размеры гнутого стержня: слева — над пластиной / до гиба / нахлёст; сверху — вылет h
        xl = SX - 8
        g.dim_v(SY0 + yt * S, SY0, SX, xl, fmt(round(b["rise"] - b["kink"])) + "*", h=h)
        g.dim_v(SY0, SY0 + yk * S, SX, xl, fmt(yk), outside=yk * S < 8, h=h, side="top")
        g.dim_v(SY0 + yk * S, SY0 + (yk + b["l2"]) * S, SX, xl, fmt(b["l2"]), outside=b["l2"] * S < 8, h=h, side="bottom")
        g.line(*s(zc, yk), SX + fz(zc), SY0 + yt * S - 8, g.THIN)
        g.dim_h(SX + fz(zc), SX + fz(zc + b["h"]), SY0 + yt * S, SY0 + yt * S - 6, f"h={fmt(b['h'])}", h=h)
        mz, my = zc + b["h"] * 0.55, yk - b["rise"] * 0.55
        g.shelf(*s(mz, my), SX + fz(zc + b["h"]) + 6, SY0 + my * S - 4, f"{b['p']}  (l1={fmt(b['l1'])})", h=3)
        ylap = yk + 2 * b["d"] + (b["l2"] - 2 * b["d"]) / 2
        rows_ = sorted({p[1] for G in M["groups"] for p in G["pts"]})
        ywl = (rows_[0] + rows_[1]) / 2 if len(rows_) > 1 else yk + b["l2"] + 20
        ysh = max(SY0 + (yk + b["l2"]) * S + 4, SY0 + yb0_ * S + 16)   # под концом нахлёста, ниже «Б»
        for yr in sorted({y for y, _ in col}):                     # не на оси ряда стержней
            yrs = SY0 + yr * S
            if yrs - 4 < ysh < yrs + 5.5:
                ysh = yrs - 4 if yrs - 4 >= SY0 + yb0_ * S + 16 else yrs + 5.5
        wl_ = f"{WELD_LAP}, l={fmt(b['l2'] - 2 * b['d'])}"
        g.shelf(*s(zc + r, ylap), SX + fz(t) + 14, ysh, wl_, h=3)
        lap_end_x = SX + fz(t) + 14 + g.tlen(wl_, 3) + 2
    if cz_:
        zigzag(SX + fz(cz_[0]) + 1, SY0 - 3, SY0 + B * S + 3)
        zigzag(SX + fz(cz_[1]) - 1, SY0 - 3, SY0 + B * S + 3)
    Gd = max((G for _, G in col), key=lambda G: G["depth"])
    zs = [0, t] + ([Gd["depth"] - Gd["tb"], Gd["depth"]] if Gd["tb"] else [Gd["depth"]])
    lbl = fmt(depth) + (" (+0; −5)" if M["fam"] == "B" else "")
    others = sorted({G["depth"] for _, G in col} - {Gd["depth"]})
    if M["bents"]:                                   # над разрезом — гнутый стержень, размеры глубины — снизу
        yo, sg = SY0 + B * S, 1
    else:
        yo, sg = SY0, -1
    yd = (lambda k: yo + sg * (8 + 7 * k)) if M["bents"] else (lambda k: SY - 7 - 7 * k)
    for i, (a, b) in enumerate(zip(zs[:-1], zs[1:])):
        g.dim_h(SX + fz(a), SX + fz(b), yo, yd(0), fmt(b - a), outside=(fz(b) - fz(a)) < 8, h=h,
                side="left" if i == 0 else "right")
    for j, dep in enumerate(others):                 # меньшие — ближе к изображению
        g.dim_h(SX, SX + fz(dep), yo, yd(1 + j), fmt(dep), h=h)
    g.dim_h(SX, SX + D if not M["bents"] else SX + fz(Gd["depth"]), yo, yd(1 + len(others)),
            lbl if not M["bents"] else fmt(Gd["depth"]), h=h)
    lb = SY0 + B * S + (8 + 7 * (2 + len(others)) + 4 if M["bents"] else 7)
    right = SX + D
    ycol = sorted({y for y, _ in col} | {y for y, _, _ in th})
    chain_v([0] + ycol + [B], SY0, S, right, right + 16, h)
    g.dim_v(SY0, SY0 + B * S, right, right + 24, fmt(B), h=h)
    # размер шайбы в разрезе не ставим: его центр лежит на оси ряда, и выносная линия цепочки перечёркивала бы
    # надпись. Размеры шайбы — в спецификации и DXF, соосность — в техтребованиях.
    yb0, Gb = col[0]
    bx, by = s(depth - t / 2, yb0) if holed(M) else s(t + Gb["k"] / 2, yb0 + Gb["d"] / 2)
    g.circle(bx, by, 4, g.THIN)
    if M["bents"]:
        g.text(bx + 7, by + 11, "Б", h=5)
    elif holed(M):                                   # справа от пластины поз. 2, под осью ряда
        g.text(SX + D + 2, by + 9, "Б", h=5)
    else:
        g.text(bx + 5, by - 6, "Б", h=5)
    ylast, Gl = col[-1]
    zmid = (t + cz_[0]) / 2 if cz_ else t + Gl["gap"] * 0.5
    yp1 = (col[0][0] + col[1][0]) / 2 if len(col) > 1 else B * 0.8
    if M["bents"]:
        g.shelf(*s(t / 2, yp1), SX - 18, SY0 + B * S * 0.5, "1")
    elif len(col) > 1:                               # вправо, в нижний промежуток между стержнями (вдали от «Б»)
        yp2 = col[-2][0] + (col[-1][0] - col[-2][0]) * 0.7
        g.shelf(*s(t / 2, yp2), SX + fz(t) + 5, SY0 + yp2 * S - 2, "1")
    else:                                            # один ряд — влево-вверх (внизу — шов)
        g.shelf(*s(t / 2, B * 0.15), SX - 10, SY0 - 4, "1")
    if M["bents"]:                                   # снизу — размеры глубины: выноски не через них
        if (B - ylast) * S >= 8:                     # под нижним рядом хватает места
            g.shelf(*s(zmid, ylast + Gl["d"] / 2), SX + fz(zmid) + 6, SY0 + (ylast + (B - ylast) * 0.75) * S, str(Gl["p"]))
        else:                                        # иначе — над дальним концом стержня (у пластины — шов Н1-Мш)
            zf = t + Gl["gap"] * 0.8
            xs_ = max(SX + fz(zf) + 3, lap_end_x + 2) if abs(ysh - (SY0 + ylast * S - 5)) < 6 else SX + fz(zf) + 3
            g.shelf(*s(zf, ylast - Gl["d"] / 2), xs_, SY0 + ylast * S - 5, str(Gl["p"]))
        g.shelf(*s(t + Gl["k"] * 0.3, ylast + Gl["d"] / 2 + Gl["k"] * 0.3), SX - 6, SY0 + B * S + 3, wtag(Gl["k"]), h=3)
    else:
        g.shelf(*s(zmid, ylast - Gl["d"] / 2), SX + max(D * 0.45, 22), lb, str(Gl["p"]))
        g.shelf(*s(t + Gl["k"] * 0.3, ylast + Gl["d"] / 2 + Gl["k"] * 0.3), SX + 2, lb, wtag(Gl["k"]), h=3)
    Gw = Gl if (M["fam"] == "B" or Gl["washer"]) else next((G for _, G in col if G["washer"]), None)
    if Gw:
        yw = ylast if Gw is Gl else next(y for y, G in col if G is Gw)
        xb2 = SX + max(D * 0.75, 34)
        wl = "2" if M["fam"] == "B" else str(wpos[wkey(Gw)])
        zb = Gw["depth"] - Gw["tb"] * 0.3
        if Gw is Gl:
            g.shelf(*s(zb, yw + Gw["d"] / 2 + 2), xb2, lb, wl, h=3.5)
            if M["fam"] == "B":
                g.shelf(*s(zb, yw + Gw["D0"] / 2 * 0.5), xb2 + 8, lb + 8, WELD, h=3)
            else:
                g.shelf(*s(Gw["depth"] - Gw["tb"] - Gw["kw"] * 0.3, yw + Gw["d"] / 2 + Gw["kw"] * 0.3), xb2 + 8, lb + 8,
                        wtag(Gw["kw"]), h=3)
        else:                                        # шайбы в верхнем ряду — выноски вправо-вверх
            cw = Gw["washer"]["c"]                   # выноска влево-вверх, мимо размерных линий справа
            g.shelf(*s(Gw["depth"] - Gw["tb"] * 0.5, yw - cw / 2 * 0.7), SX + fz(Gw["depth"] - Gw["tb"]) - 16,
                    SY0 + (yw - cw / 2) * S - 7, wl, h=3.5)

    # ---- узел Б (основная группа)
    k, NX, NY = L["node_scale"], L["NX"], L["NY"]
    if holed(M):
        node_hole(M, G0, k, NX, NY, t, wpos)
    else:
        node_fillet(M, G0, k, NX, NY, t, wpos)

    # ---- таблицы
    TX = 230
    g.text(TX + 92.5, 14, "Спецификация", h=5, align="c")
    tech_txt = "".join(f", {len(hh['pts'])} отв. {fmt(hh['w'])}×{fmt(hh['h'])}" for hh in M["tech"])
    rows = [["1", (f"Пластина —{fmt(t)}×{fmt(B)}×{fmt(A)}{tech_txt}",), "1", g.num(ms["plate_n"]), STEEL]]
    if holed(M):
        rows.append(["2", (f"Пластина —{fmt(t)}×{fmt(B)}×{fmt(A)}, {M['n']} отв. Ø{G0['d0']}",), "1",
                     g.num(ms["plate2_n"]), STEEL])
    for (d, rod), pp in rods.items():
        q = sum(len(G["pts"]) for G in M["groups"] if G["p"] == pp)
        rows.append([str(pp), (f"Стержень {d}-{CLS}, L = {fmt(rod)}",), str(q), g.num(KG_M[d] * rod / 1000),
                     f"{CLS} ГОСТ 34028-2016"])
    if M["bents"]:
        b = M["bents"]
        rows.append([str(b["p"]), (f"Стержень гнутый {b['d']}-{CLS}, L = {fmt(b['L'])}, h = {fmt(b['h'])}",),
                     str(b["n"]), g.num(ms["bent_m"]), f"{CLS} ГОСТ 34028-2016"])
    for key, q in washer_types(M).items():
        c, wt = key
        rows.append([str(wpos[key]), (f"Шайба —{fmt(wt)}×{fmt(c)}×{fmt(c)}",), str(q), g.num(ms["washers"][key]), STEEL])
    g.table(TX, 17, [("Поз.", 9), ("Наименование", 88), ("Кол.", 11), ("Масса\nед., кг", 17), ("Материал", 60)], rows, 10, 7)
    y = 17 + 10 + 7 * len(rows) + 10
    g.text(TX + 92.5, y, "Спецификация металлопроката", h=5, align="c")
    mrows, i = [], 1
    for thk, mass in sorted(ms["sheets"].items()):
        mrows.append([(SHEET,), STEEL, f"t = {fmt(thk)}", str(i), g.num(mass), g.num(mass)])
        i += 1
    tot = sum(ms["sheets"].values())
    mrows.append([("Итого",), "", "", str(i), g.num(tot), g.num(tot)])
    i += 1
    for dd, mass in sorted(ms["rebar"].items()):
        mrows.append([(REBAR,), CLS, f"Ø{dd}", str(i), g.num(mass), g.num(mass)])
        i += 1
    mrows.append([("Итого",), "", "", str(i), g.num(sum(ms["rebar"].values())), g.num(sum(ms["rebar"].values()))])
    mrows.append([("Наплавленный металл 1%",), "", "", str(i + 1), g.num(ms["dep"]), g.num(ms["dep"])])
    mrows.append([("Всего",), "", "", str(i + 2), g.num(ms["all"]), g.num(ms["all"])])
    g.table(TX, y + 3, [("Наименование\nпрофиля, ГОСТ", 54), ("Марка металла", 40), ("Размеры\nпрофиля, мм", 21),
                        ("№\nп.п.", 9), (f"Масса, кг\n{M['mark']}, 1 шт.", 31), ("Общая\nмасса, кг", 30)], mrows, 12, 6.5)
    y = y + 3 + 12 + 6.5 * len(mrows) + 10
    g.text(TX + 92.5, y, "Технические требования", h=5, align="c")
    nl = []
    for line_ in notes(M):                           # перенос строк, не влезающих в 181 мм
        while g.tlen(line_, 2.5) > 181:
            cut = line_.rfind(" ", 0, int(len(line_) * 181 / g.tlen(line_, 2.5)))
            nl.append(line_[:cut])
            line_ = "    " + line_[cut + 1:]
        nl.append(line_)
    step = 4.4 if y + 7 + len(nl) * 4.4 < 234 else (234 - y - 7) / len(nl)
    for j, line_ in enumerate(nl):
        g.text(TX + 2, y + 7 + j * step, line_, h=2.5 if step >= 4 else 2.2)
    scales = L["label"]                              # в штампе — масштаб главного вида, прочие — у обозначений видов
    g.stamp(M["mark"], "Изделие закладное" if M["series"].startswith("1.400-15") else "Деталь закладная",
            M["mark"], g.num(ms["all"], 1), scales, sheets=2)
    g.text(232, 233, "Изометрия (для сборки) — лист 2.", h=3)
    if png_path:
        g.page.get_pixmap(dpi=110).save(png_path)
    iso_sheet(M, rods, wpos)
    g.doc.save(pdf_path)
    if png_path:
        g.page.get_pixmap(dpi=110).save(str(png_path).replace(".png", "_лист2.png"))
    return L


def iso_sheet(M, rods, wpos):
    """Лист 2: изометрия изделия со стороны анкеров, выноски позиций."""
    A, B, t = M["A"], M["B"], M["t"]
    Y = lambda y: B - y
    sc = iso3d.Scene()
    step = max(A, B) / 25
    sc.box(0, 0, 0, A, B, t, step)
    balloons = [(1, (A * 0.82, B * 0.18, t))] + ([(2, (A * 0.82, B * 0.18, M["H"]))] if M["fam"] == "B" else [])
    if M["fam"] == "B":
        H = M["H"]
        sc.box(0, 0, H - t, A, B, H, step)
        for G in M["groups"]:
            for x, y in G["pts"]:
                sc.disk((x, Y(y), H), (0, 0, 1), G["D0"] / 2)
    seen = set()
    for G in M["groups"]:
        z_end = M["H"] - t / 2 if M["fam"] == "B" else G["depth"] - G["tb"]
        for x, y in G["pts"]:
            sc.rod((x, Y(y), t), (x, Y(y), z_end), G["d"] / 2, cap_b=not G["washer"] and M["fam"] != "B")
            if G["washer"]:
                c, wt, zf = G["washer"]["c"], G["tb"], G["depth"]
                sc.box(x - c / 2, Y(y) - c / 2, zf - wt, x + c / 2, Y(y) + c / 2, zf, max(c / 4, 5))
        if G["p"] not in seen:
            seen.add(G["p"])
            x, y = max(G["pts"], key=lambda q: q[0] - q[1])
            balloons.append((G["p"], (x, Y(y) + G["d"] / 2, t + (z_end - t) * 0.55)))
        if G["washer"]:
            key = wkey(G)
            if wpos[key] not in seen:
                seen.add(wpos[key])
                x, y = max(G["pts"], key=lambda q: q[0] - q[1])
                balloons.append((wpos[key], (x + G["washer"]["c"] / 2, Y(y), G["depth"] - G["tb"] / 2)))
    b = M["bents"]
    if b:
        zc = t + b["d"] / 2
        for xb in b["xs"]:
            k0 = (xb, Y(b["kink"]), zc)
            sc.rod((xb, Y(b["kink"] + b["l2"]), zc), k0, b["d"] / 2, cap_b=False)
            sc.rod(k0, (xb, Y(b["kink"]) + b["rise"], zc + b["h"]), b["d"] / 2, cap_a=False)
        xb = b["xs"][-1]
        balloons.append((b["p"], (xb, Y(b["kink"]) + b["rise"] * 0.6, zc + b["h"] * 0.6)))
    g.next_sheet(M["mark"], 2, "Изометрия (ГОСТ 2.317) — вид со стороны анкеров")
    sc.render((40, 28, 395, 268), balloons)
    g.text(40, 272, "Номера позиций — по спецификации листа 1. Масштаб изображения произвольный.", h=3)


def notes(M):
    st = M["strip"]
    s15 = M["series"].startswith("1.400-15")
    out = [f"1. Изделие {M['base']} по серии {M['series']} ({M['code']}) с изменением: приварка стержней втавр",
           "    под флюсом (Т1-Мф) заменена механизированной сваркой в CO2 (полуавтомат) угловым швом по контуру",
           "    стержня; пластины и шайбы — сплошные, без отверстий (по решению завода)."]
    if st:
        out += [f"    Погонное: длина {fmt(M['A'])} по заказу; анкеры шагом {fmt(st['pitch'])}, крайние — {fmt(st['e'])} мм от торцов",
                f"    (ряд по центру; в серии отступ не задан, по серии {st['per_m']} анкеров на 1 п.м.)."]
    ks = sorted({G["k"] for G in M["groups"]} | {G["kw"] for G in M["groups"] if G.get("kw")})
    out += [f"2. Шов {FILLET_TAG} — угловой тавровый по замкнутому контуру стержня, {FILLET}, катет k = "
            f"{'/'.join(map(str, ks))} мм ({'разрез 1–1' if M['fam'] == 'B' else 'узел Б'}).",
            "    Торцы стержней — в упор к пластине (шайбе), зазор не более 1 мм. Сварочная проволока — по технологии завода."]
    if M["fam"] == "B":
        G0 = M["groups"][0]
        out += [f"3. К пластине поз. 2 — в раззенкованные отверстия, как в серии: {WELD} ГОСТ 14098-2014, отв. Ø{G0['d0']},",
                f"    раззенковка Ø{G0['D0']} на всю толщину; стержень заходит на {fmt(M['t'] / 2)} мм. L = {fmt(G0['rod'])}."]
        if M["warn"]:
            out.append(f"    {WELD} вне области табл. 16 ГОСТ ({'; '.join(M['warn'][:2])}) — по решению завода.")
        out += ["4. Поставка — в разобранном виде, как в серии: стержни приварить к пластине поз. 1 на заводе,",
                f"    пластину поз. 2 — в комплекте, приварка при монтаже. Размер {fmt(M['H'])} (+0; −5) — после монтажа.",
                "    В DXF поз. 2 внешний контур зенковки — слой GRAV (гравировка), рез — слой CUT."]
    else:
        for G in M["groups"]:
            who = (" с шайбами" if G["washer"] else " без шайб") if M["fam"] == "C" else ""
            out.append(f"{'3' if G is M['groups'][0] else ' '}. Ø{G['d']}{who}: L = {fmt(G['rod'])} — как в серии.".replace(" . Ø", "    Ø"))
    if M["bents"]:
        b = M["bents"]
        k5 = len([x for x in out if x[0].isdigit()]) + 1
        out += [f"{k5}. Гнутые стержни поз. {b['p']} (1.400-15.В1.004, рис. 1): l1 = {fmt(b['l1'])}, l2 = {fmt(b['l2'])}, "
                f"h = {fmt(b['h'])}; гиб на {fmt(b['kink'])} ниже",
                f"    верхней кромки. Приварка к тыльной стороне внахлёстку: {WELD_LAP} ГОСТ 14098-2014, два фланговых",
                f"    шва l = l2 − 2d = {fmt(b['l2'] - 2 * b['d'])} мм от 2d ниже гиба (по серии); b ≥ 0,5d, не менее 8; "
                f"h ≥ 0,25d, не менее 4.",
                "    Радиус гиба в серии не задан — по технологии гибки (не менее 2d для А400)."]
    k = len([x for x in out if x[0].isdigit()]) + 1
    out.append(f"{k}. Сварку выполнять в кондукторе. Прямые стержни перпендикулярны пластине.")
    if s15:
        out.append(f"{k + 1}. Пластины и шайбы — из листа ГОСТ 19903-2015, сталь {STEEL}; стержни — {CLS} ГОСТ 34028-2016.")
    else:
        out += [f"{k + 1}. Марки стали и антикоррозионная защита — по проекту (указания к группе). Если не указано:",
                f"    пластины и шайбы — лист ГОСТ 19903-2015, {STEEL}; стержни — {CLS} ГОСТ 34028-2016."]
    out.append(f"{k + 2}. Изготовление, контроль и приёмка — по ГОСТ 10922-2012. Антикоррозионная защита — по заказу.")
    j = k + 3
    out.append(f"{j}. На виде А стержни и шайбы невидимы (штриховая линия). Шайбы — соосно стержню.")
    j += 1
    if M["tech"] or M["risk_x"] is not None:
        rtxt = f"; риска «верх» — {fmt(M['risk_x'])} мм от левой кромки, длина 10" if M["risk_x"] is not None else ""
        out.append(f"{j}. Технологические отверстия и риску выполнить при резке пластины (риска — гравировкой){rtxt}.")
        j += 1
    if any(("10×10" in u or "10x10" in u) and "привязк" in u for u in M["unc"]):
        out.append(f"{j}. Привязка отв. 10×10 на листе серии не образмерена — принята по осям анкеров, как на эскизе.")
    return out


# ---------------------------------------------------------------- запуск
def load_676():
    for f in sorted((DATA / "s676").glob("p*.json"), key=lambda p: int(p.stem[1:])):
        page = json.load(open(f, encoding="utf-8"))
        for it in page.get("items", []):
            yield it, page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="15", choices=["15", "6/76"], help="1.400-15 (по умолчанию) или 1.400-6/76")
    ap.add_argument("--only", help="марки через запятую")
    ap.add_argument("--out", help="папка результата (по умолчанию out_1.400-15 / out_1.400-6-76)")
    ap.add_argument("--png", action="store_true", help="картинки предпросмотра")
    ap.add_argument("--length", help='длина погонных изделий, мм: "1200" (всем) или "МН 104-1=1200,МН 127-3=2400"')
    a = ap.parse_args()
    lengths = {}
    for part in (a.length or "").split(","):
        if "=" in part:
            k, v = part.split("=")
            lengths[k.strip()] = float(v)
        elif part.strip():
            lengths["*"] = float(part)
    only = {x.strip() for x in a.only.split(",")} if a.only else None
    if a.series == "15":
        src = [(r["Изделие"], lambda r=r: build_15(r, lengths)) for r in json.load(open(DATA / "mn_izdeliya1_ALL.json", encoding="utf-8"))]
        out = Path(a.out or HERE / "out_1.400-15")
    else:
        src = [(it["mark"], lambda it=it, pg=pg: build_676(it, pg)) for it, pg in load_676()]
        out = Path(a.out or HERE / "out_1.400-6-76")
    out.mkdir(exist_ok=True)
    index, done, skipped, skip_list = [], 0, Counter(), []
    for mark, mk in src:
        if only and mark not in only:
            continue
        M, why = mk()
        if not M:
            skipped[why] += 1
            skip_list.append({"Изделие": mark, "Причина": why})
            if only:
                print("пропуск", mark, "—", why)
            continue
        ms = masses(M)
        folder = out / M["mark"]
        folder.mkdir(exist_ok=True)
        try:
            L = draw(M, ms, folder / f"{M['mark']}.pdf", folder / f"{M['mark']}.png" if a.png else None)
        except ValueError as e:
            skipped[str(e)] += 1
            skip_list.append({"Изделие": mark, "Причина": str(e)})
            continue
        files = dxf_parts(M, folder)
        done += 1
        G0 = M["main"]
        index.append({"Изделие": M["mark"], "Серия": M["series"], "Семейство": M["fam"],
                      "Пластина": f"{fmt(M['A'])}×{fmt(M['B'])}×{fmt(M['t'])}",
                      "Анкеры": "; ".join(f"{len(G['pts'])}×Ø{G['d']}" for G in M["groups"]),
                      "L стержня": "; ".join(fmt(G["rod"]) for G in M["groups"]), "Шов": f"{FILLET} k{G0['k']}" + (f"; {WELD} Ø{G0['d0']}/Ø{G0['D0']}" if holed(M) else ""),
                      "Шайба": "; ".join(f"{c}×{wt}×{q}" for (c, wt), q in washer_types(M).items()),
                      "Масса серия, кг": M["site_mass"], "Масса Т11-Мз, кг": round(ms["all"], 2),
                      "Масштаб": f"{L['label']} / {L['label_s']}",
                      "Разрыв": ", ".join(x for x, c in (("вид", L["cut_x"]), ("разрез", L["cut_z"])) if c),
                      "Вне ГОСТ (Т11-Мз)": "; ".join(M["warn"]), "Не подтверждено": "; ".join(M["unc"]),
                      "Файлы": "; ".join([f"{M['mark']}.pdf"] + files)})
    if index:
        with open(out / "index.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, list(index[0]), delimiter=";")
            w.writeheader()
            w.writerows(index)
    if skip_list:
        with open(out / "skipped.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, ["Изделие", "Причина"], delimiter=";")
            w.writeheader()
            w.writerows(skip_list)
    print(f"готово: {done} изделий -> {out}")
    for k, v in skipped.most_common():
        print(f"  пропущено {v}: {k}")


if __name__ == "__main__":
    main()
