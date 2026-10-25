# -*- coding: utf-8 -*-
"""ОСТ 36-94-83 «Детали стальных трубопроводов. Опоры подвижные. Типы и основные размеры».

Источник — присланная Антоном 25.10.2026 копия docload (~/Projects/opory_ost36-94/normy):
таблицы набраны текстом (размеры точные), чертежи — мелкие картинки. Документация —
docs/OST_36-94-83.md (что собрано, допущения, что ждёт чертежей Игоря).

С составом по деталям собрана ОПП1 (черт. 1, табл. 1) — по ней же сделан чертёж ОПП1-100.18
(0,56 кг по деталям против 0,60 по ОСТ). Остальные марки (ОПП2/3, ОПХ1/2/3, ОПБ1/2) — только
справочник: масса по приложению ОСТ, состав не собран (рёбра, хомуты, толщины на картинках
не читаются, в таблицах их нет).

ОПП1 (черт. 1): корпус — полоса S = 3, согнутая «П» вдоль трубы: дно 100 × 70, две стенки
поперёк трубы — трапеция 70 внизу → B вверху высотой H1, сверху ложе R, его низ на высоте H.
Ребро — S = 3 по оси трубы между стенками высотой H2. Отверстия 2×Ø10 — по требованию
заказчика (п. 5), в массу не входят. Исполнение — высота H: 100 или 70.
"""
import math

from .ost36_94_mass import MASS

STANDARD = "ОСТ 36-94-83"
DENSITY = 7.85e-6

TYPES = {
    "opp1": dict(code="ОПП1", label="ОПП1 подвижная (Дн 18–48)", fixed=False, standard=STANDARD),
}

# Табл. 1: Дн → (H1 при H=100, H1 при H=70, B, R); H2: 60 при H=100, 30 при H=70.
_T1 = (((18, 21.3, 25, 26.8), 107, 77, 40, 13), ((32, 33.5, 38, 42.3, 45, 48), 114, 84, 60, 24))
TABLE1 = {dn: (h100, h70, b, r) for dns, h100, h70, b, r in _T1 for dn in dns}
H2 = {100: 60, 70: 30}
S, L, W0 = 3, 100, 70          # толщина, длина вдоль трубы, ширина низа (черт. 1)
RB = S                         # внутренний радиус гиба — принят = S (в ОСТ нет)
RIB_CHAMFER_GAP = 2            # фаски ребра под радиус гиба: r + 2 (как у ОСТ 36-146-88)
BEND_K = 0.4

# Марки без состава — для справочника: семейство → подпись.
CATALOG_ONLY = {
    "ОПП2": "корпусная, Н 100/150, Дн 57–1620 (черт. 2, табл. 2)",
    "ОПП3": "корпусная двойной длины, Дн 57–1620 (черт. 2, табл. 2)",
    "ОПХ1": "хомутовая, Дн 18–48 (черт. 3, табл. 3)",
    "ОПХ2": "хомутовая, Дн 57–630 (черт. 4, табл. 4)",
    "ОПХ3": "хомутовая двойной длины, Дн 57–630 (черт. 4, табл. 4)",
    "ОПБ1": "бескорпусная — подушка, Дн 18–530 (черт. 5, табл. 5)",
    "ОПБ2": "бескорпусная хомутовая, Дн 18–530 (черт. 6, табл. 6)",
}


def _dn_text(dn):
    return ("%g" % dn).replace(".", ",")


def diameters(kind):
    return sorted(TABLE1)


def executions(kind, dn):
    return ["100", "70"]


def split_exe(exe):
    return str(exe or ""), False


def check(kind, dn, exe):
    if kind not in TYPES:
        return "Тип опоры не понят"
    if dn not in TABLE1:
        return "Дн %s для ОПП1 по ОСТ 36-94-83 нет — бывают %s" % (
            _dn_text(dn), ", ".join(_dn_text(d) for d in sorted(TABLE1)))
    if str(exe) not in ("100", "70"):
        return "Высота ОПП1 по ОСТ — 100 или 70 мм"
    return ""


def standard_h(kind, dn, exe):
    return int(exe)


def check_height(kind, dn, exe, h):
    if h and h != int(exe):
        return "У ОПП1 своей высоты нет — только 100 или 70 (ОПП1-%s.%s)" % (h, _dn_text(dn))
    return ""


def _dims(dn, exe):
    h = int(exe)
    h100, h70, b, r = TABLE1[dn]
    return dict(h=h, h1=h100 if h == 100 else h70, h2=H2[h], B=b, R=r)


def body(kind, dn, exe, h=None):
    d = _dims(dn, exe)
    return dict(h=d["h"], h1=d["h1"], h2=d["h2"], B=W0, S=S, L=L, r=RB, delta=0)


def _segment(r, depth):
    c = r - depth
    return r * r * math.acos(c / r) - c * math.sqrt(r * r - c * c)


def corpus_area(dn, exe):
    """Площадь развёртки корпуса: две трапеции-стенки с ложем + дно шириной 70 с гибами."""
    d = _dims(dn, exe)
    wall = (W0 + d["B"]) / 2.0 * d["h1"] - _segment(d["R"], d["h1"] - d["h"])
    bend = math.pi / 2 * (RB + BEND_K * S)
    return 2 * wall + W0 * (L - 2 * (RB + S)) + 2 * W0 * bend


def corpus_dev(dn, exe):
    d = _dims(dn, exe)
    bend = math.pi / 2 * (RB + BEND_K * S)
    return 2 * (d["h1"] - (RB + S)) + 2 * bend + (L - 2 * (RB + S))


def parts(kind, dn, exe, h=None):
    d = _dims(dn, exe)
    ch = RB + RIB_CHAMFER_GAP
    rib_l, rib_h = L - 2 * S, d["h2"] - S
    return [
        dict(key="corpus", sequence=1, thickness=S, qty=1, metal=True,
             name="Корпус гнутый П %s×%s — лист %s, развёртка %s×%s, ложе R%s, 2 гиба R%s"
                  % (L, d["h1"], S, round(corpus_dev(dn, exe)), W0, d["R"], RB),
             unit_mass=round(corpus_area(dn, exe) * S * DENSITY, 3),
             a=round(corpus_dev(dn, exe)), b=W0),         # заготовка — развёртка (ложе вырезается из неё)
        dict(key="rib", sequence=3, thickness=S, qty=1, metal=True,
             name="Ребро — лист %s, %s×%s, фаски %s×45°" % (S, rib_l, rib_h, ch),
             unit_mass=round((rib_l * rib_h - ch * ch) * S * DENSITY, 3), a=rib_l, b=rib_h),
    ]


def mark(kind, dn, exe):
    return "ОПП1-%s.%s" % (exe, _dn_text(dn))


def ost_mass(kind, dn, exe):
    return MASS.get(mark(kind, dn, exe), 0.0)


def designation(kind, dn, exe, steel=None):
    return mark(kind, dn, exe)


def name(kind, dn, exe, steel, h=None):
    return "Опора подвижная %s %s, %s" % (mark(kind, dn, exe), STANDARD, steel)


def short(kind, dn, exe, steel, h=None):
    return "ОПП1 Н%s Дн%s · подвижная · %s" % (exe, _dn_text(dn), steel or "")


def history_patterns(kind, dn, exe):
    """Регулярки для строк счетов МС (все должны совпасть) и нужна ли «неподвижная»."""
    return [r"(О|O)\s*П\s*П\s*1", r"%s\s*[.,]\s*%s(\D|$)" % (exe, _dn_text(dn).replace(",", "[.,]"))], None


def catalog_only():
    """Марки без состава для справочника: (марка, семейство, подпись, масса ОСТ)."""
    rows = []
    for m, mass in MASS.items():
        fam = m[:4]
        if fam in CATALOG_ONLY:
            rows.append((m, fam, CATALOG_ONLY[fam], mass))
    return rows
