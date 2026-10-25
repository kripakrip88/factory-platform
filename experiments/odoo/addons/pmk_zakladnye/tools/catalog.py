# -*- coding: utf-8 -*-
"""Справочник закладных изделий и короткая запись строки.

Источник — генератор lib/generate.py (сессия «Закладные МН», 25.10.2026): серия 1.400-15
(мн_izdeliya1_ALL.json, 901 запись сайта) и 1.400-6/76 (оцифровка альбома, data/s676).
Odoo берёт из генератора только модель изделия и массы — без рисования (PyMuPDF есть
только в образе фонового процесса, worker/).

    parse("мн 201-5 12шт")       → {"mark": "МН 201-5", "qty": 12, ...}
    parse("мн 104-1 1200 10шт")  → погонное: длина 1200, 10 шт
    parse("м1-9-7 4шт")          → серия 1.400-6/76
    model("15", "МН 201-5")      → (M, ms, None) | (None, None, причина)
"""
import importlib.util
import json
import os
import re
import sys
import threading

LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
SERIES = [("15", "1.400-15"), ("676", "1.400-6/76")]
# Версия рисунка генератора: правка чертежа (не модели) → новая версия, и нарисованные
# раньше чертежи становятся «устарел» — «Подготовить чертежи» перерисует их.
# 2 — технологические отверстия на изометрии (25.10.2026); 3 — вырезом, а не тёмной наклейкой.
DRAW_VERSION = "3"

_lock = threading.RLock()
_gen = None
_index = None


def gen():
    """Генератор как модуль (своё имя — не путать с чужими generate.py)."""
    global _gen
    if _gen is None:
        with _lock:
            if _gen is None:
                if LIB_DIR not in sys.path:
                    sys.path.insert(0, LIB_DIR)
                spec = importlib.util.spec_from_file_location("pmk_zk_generate", os.path.join(LIB_DIR, "generate.py"))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _gen = mod
    return _gen


def _norm_key(mark):
    return re.sub(r"\s+", "", (mark or "").upper().replace("Ё", "Е"))


def index():
    """{ключ марки: (серия, запись, погонное)} — серия «15»: запись сайта, «676»: (изделие, лист)."""
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                g = gen()
                out = {}
                with open(g.DATA / "mn_izdeliya1_ALL.json", encoding="utf-8") as f:
                    for r in json.load(f):
                        pogon = g.num(r.get("Размер пластины, мм [B]")) is None
                        out[_norm_key(r["Изделие"])] = ("15", r, pogon)
                for it, page in g.load_676():
                    out.setdefault(_norm_key(it["mark"]), ("676", (it, page), False))
                _index = out
    return _index


def series_of(mark):
    found = index().get(_norm_key(mark))
    return found[0] if found else None


def is_pogon(mark):
    found = index().get(_norm_key(mark))
    return bool(found and found[2])


def series_label(code):
    return dict(SERIES).get(code, "")


# Латиница, набранная вместо кириллицы (раскладка), — в кириллицу: «mh 201-5», «M1-9-7».
_LAT = str.maketrans({"M": "М", "H": "Н", "C": "С", "m": "М", "h": "Н", "c": "С"})
QTY_RE = re.compile(r"(?:(?<=\s)|^)(?:[xх×*]\s*(\d+)|(\d+)\s*(?:шт\.?|штук|pcs))(?=\s|$)", re.I)
LEN_RE = re.compile(r"(?:(?<=\s)|^)(?:[LlЛл]\s*=?\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*мм)(?=\s|$)", re.I)
MARK_RE = re.compile(r"^\s*(МН|МС|М)\s*-?\s*(\d+(?:-\d+)*)", re.I)


def parse(text):
    """Короткая запись → {"mark", "series", "length", "qty", "pogon"} или {"error"}.
    Марка — первой; количество — «12шт», «x12»; длина погонного — «L1200», «1200мм» или
    первое голое число. У обычного изделия голое число после марки — количество."""
    src = (text or "").strip()
    if not src:
        return {"error": "пустая строка"}
    s = src.translate(_LAT).replace("Ё", "Е")
    m = MARK_RE.match(s)
    if not m:
        return {"error": "не вижу марку: начните с «МН 201-5», «М1-9-7»"}
    head = m[1].upper()
    mark = ("МН " + m[2]) if head == "МН" else (head + m[2] if head == "М" else "МС-" + m[2].lstrip("-"))
    rest = " " + s[m.end():].strip() + " "
    # «МН 104-1 L1200» — пробел перед L обязателен для LEN_RE; «МН 104-1L1200» — тоже.
    rest = re.sub(r"(?<=\d)([LlЛл])(?=\d)", r" \1", rest)
    found = index().get(_norm_key(mark))
    if not found:
        return {"error": "нет в сериях 1.400-15 и 1.400-6/76: %s" % mark, "mark": mark}
    series, _rec, pogon = found
    qty = length = None
    mq = QTY_RE.search(rest)
    if mq:
        qty = int(mq[1] or mq[2])
        rest = rest[:mq.start()] + " " + rest[mq.end():]
    ml = LEN_RE.search(rest)
    if ml:
        length = float((ml[1] or ml[2]).replace(",", "."))
        rest = rest[:ml.start()] + " " + rest[ml.end():]
    bare = re.findall(r"(?<!\S)(\d+(?:[.,]\d+)?)(?!\S)", rest)
    for value in bare:
        v = float(value.replace(",", "."))
        if pogon and length is None:
            length = v
        elif qty is None and v.is_integer():
            qty = int(v)
        else:
            return {"error": "лишнее число «%s»: количество — «12шт», длина — «L1200»" % value, "mark": mark}
    leftover = re.sub(r"(?<!\S)(\d+(?:[.,]\d+)?)(?!\S)", " ", rest).strip(" ,;")
    if leftover:
        return {"error": "не понял «%s»" % leftover, "mark": mark}
    if pogon and not length:
        return {"error": "%s — погонное: укажите длину, например «%s L1200»" % (mark, mark), "mark": mark}
    if not pogon and length:
        return {"error": "%s — не погонное, длина не нужна" % mark, "mark": mark}
    return {"mark": mark, "series": series, "length": length or 0.0, "qty": qty, "pogon": pogon}


def model(series, mark, length=0.0):
    """Модель изделия и массы генератора. Не поддержано — (None, None, причина)."""
    g = gen()
    found = index().get(_norm_key(mark))
    if not found or found[0] != series:
        return None, None, "нет в серии %s" % series_label(series)
    _s, rec, pogon = found
    if series == "15":
        M, why = g.build_15(rec, {rec["Изделие"]: length} if pogon else None)
    else:
        M, why = g.build_676(*rec)
    if not M:
        return None, None, why
    try:
        if not g.layout(M):
            return None, None, "не помещается на А3 — чертёж не построить"
    except Exception as e:  # noqa: BLE001 — компоновка: деление на ноль у кривых записей
        return None, None, "компоновка листа: %s" % e
    return M, g.masses(M), None


def composition(M, ms):
    """Состав на 1 шт — как спецификация листа 1: [{pos, name, qty, mass, material}]."""
    g = gen()
    rods, wpos = g.positions(M)
    A, B, t = M["A"], M["B"], M["t"]
    tech = "".join(", %d отв. %s×%s" % (len(h["pts"]), g.fmt(h["w"]), g.fmt(h["h"])) for h in M["tech"])
    rows = [dict(pos=1, name="Пластина —%s×%s×%s%s" % (g.fmt(t), g.fmt(B), g.fmt(A), tech), qty=1,
                 mass=ms["plate_n"], material=g.STEEL, kind="sheet", thickness=t)]
    if g.holed(M):
        G0 = M["groups"][0]
        rows.append(dict(pos=2, name="Пластина —%s×%s×%s, %d отв. Ø%s" % (g.fmt(t), g.fmt(B), g.fmt(A), M["n"], G0["d0"]),
                         qty=1, mass=ms["plate2_n"], material=g.STEEL, kind="sheet", thickness=t))
    for (d, rod), pp in rods.items():
        q = sum(len(G["pts"]) for G in M["groups"] if G["p"] == pp)
        rows.append(dict(pos=pp, name="Стержень %s-%s, L = %s" % (d, g.CLS, g.fmt(rod)), qty=q,
                         mass=g.KG_M[d] * rod / 1000, material="%s ГОСТ 34028-2016" % g.CLS, kind="rebar", d=d))
    if M["bents"]:
        b = M["bents"]
        rows.append(dict(pos=b["p"], name="Стержень гнутый %s-%s, L = %s, h = %s" % (b["d"], g.CLS, g.fmt(b["L"]), g.fmt(b["h"])),
                         qty=b["n"], mass=ms["bent_m"], material="%s ГОСТ 34028-2016" % g.CLS, kind="rebar", d=b["d"]))
    for key, q in g.washer_types(M).items():
        c, wt = key
        rows.append(dict(pos=wpos[key], name="Шайба —%s×%s×%s" % (g.fmt(wt), g.fmt(c), g.fmt(c)), qty=q,
                         mass=ms["washers"][key], material=g.STEEL, kind="sheet", thickness=wt))
    return sorted(rows, key=lambda r: r["pos"])


def summary(M, ms):
    """Пластина, анкеры, шов — для строки таблицы."""
    g = gen()
    plate = "%s×%s×%s" % (g.fmt(M["A"]), g.fmt(M["B"]), g.fmt(M["t"]))
    if g.holed(M):
        plate = "2 × " + plate
    anchors = "; ".join("%d×Ø%s L%s" % (len(G["pts"]), G["d"], g.fmt(G["rod"])) for G in M["groups"])
    if M["bents"]:
        anchors += "; гн. %d×Ø%s" % (M["bents"]["n"], M["bents"]["d"])
    G0 = M["main"]
    weld = "%s %s k%s" % (g.FILLET_TAG, g.FILLET, G0["k"])
    if g.holed(M):
        weld += "; поз. 2 — %s" % g.WELD
    if M["bents"]:
        weld += "; гнутые — %s" % g.WELD_LAP
    return {"plate": plate, "anchors": anchors, "weld": weld, "mass": ms["all"],
            "site_mass": M.get("site_mass"), "warn": list(M["warn"]), "unc": list(M["unc"]),
            "series_name": M["series"], "full_mark": M["mark"]}
