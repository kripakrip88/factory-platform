# -*- coding: utf-8 -*-
"""Опора строкой, как болт в Бутике.

Понимает короткую запись и названия из счетов МоегоСклада:
- «кх а12 219 09г2с 20шт», «кх неподв а22 219 64шт», «кп ас13 530 ст3пс»;
- «кх а12 89 н50 10шт» / «Н=50мм» — своя высота (не по ОСТ);
- «Опора корпусная хомутовая КХ Дн 630 мм А12 ОСТ 36-146-88 Н=100мм»;
- «Опора неподвижная 219-КХ-А22 Ду 219 (с упорами) ОСТ 36-146-88»;
- «Опора 57-КХ-А11 ОСТ 36-146-88 09Г2С», «Опора-КХ-219-А12 (ОСТ 36-146-88) без покраски»;
- ОСТ 36-94-83: «опп1-100.18», «опп1 70 21,3 10шт», «Опора корпусная ОПП1-100.18 ОСТ 36-94-83 Н=100мм».

Неподвижная — «неподв» или «с упорами»; иначе подвижная. Возвращает (поля, заметки, ошибка).
"""
import re

from . import catalog

OST94_RE = re.compile(r"ост\s*36\s*-\s*94\s*-\s*83", re.I)
MARK94_RE = re.compile(r"(?<![а-яa-z])[оo]\s*п\s*([пхб])\s*(\d)", re.I)
OPP1_RE = re.compile(r"[оo]\s*п\s*п\s*1\s*[-\s]\s*(100|70)\s*[.,\s]\s*(\d{2}(?:[.,]\d)?)(?![\d])", re.I)
OST_RE = re.compile(r"ост\s*36\s*-\s*146\s*-\s*88|ост\s*36[-\s.]*", re.I)
TYPE_RE = re.compile(r"(?<![а-яa-z])([кk]\s*[пpхx])(?![а-яa-z])", re.I)
TYPE_WORDS = (("хомутов", "КХ"), ("приварн", "КП"))
EXE_RE = re.compile(r"(?<![а-яa-z])([аaбb])\s*([сc]?)\s*-?\s*([12][123])(?!\d)", re.I)
HEIGHT_RE = re.compile(r"(?<![а-яa-z])[нh]\s*=?\s*(\d{2,3})\s*(?:мм)?(?!\d)", re.I)
QTY_RE = re.compile(r"(\d+)\s*шт", re.I)
NUM_RE = re.compile(r"(?<![\d.,])(\d{2,4})(?![\d.,])")


def _type_code(low):
    m = TYPE_RE.search(low)
    if m:
        return ("КХ" if m.group(1).lower()[-1] in "хx" else "КП"), m
    for word, code in TYPE_WORDS:
        if word in low:
            return code, None
    return "", None


def _steel(low):
    """→ (марка стали или "", остаток строки)."""
    for pattern, steel in ((r"09\s*г\s*2\s*с(-\d+)?", "09Г2С"), (r"10\s*г\s*2", "10Г2"),
                           (r"в?ст\.?\s*3\s*сп\d*", "Ст3сп"), (r"в?ст\.?\s*3\w*", "Ст3пс"),
                           (r"(?:ст\.?|сталь)\s*20(?!\d)", "20")):
        if re.search(pattern, low):
            return steel, re.sub(pattern, " ", low, count=1)
    return "", low


def _qty(low, vals, notes):
    m = QTY_RE.search(low)
    if m:
        vals["qty"] = int(m.group(1))
        return low[:m.start()] + " " + low[m.end():]
    notes.append("количество не указано")
    return low


def _parse_ost94(low):
    """ОСТ 36-94-83: ОПП1 — с составом; остальные марки — только справочник."""
    vals, notes = {}, []
    m = OPP1_RE.search(low)
    if not m:
        fam = MARK94_RE.search(low)
        code = "ОП%s%s" % (fam.group(1).upper(), fam.group(2))
        return {}, [], "%s по ОСТ 36-94-83 пока только в справочнике — состав не собран" % code
    vals.update(opora_type="opp1", execution=m.group(1), dn=float(m.group(2).replace(",", ".")), height=0)
    low = low[:m.start()] + " " + low[m.end():]
    low = HEIGHT_RE.sub(" ", low)              # «Н=100мм» в счетах — та же высота марки
    low = _qty(low, vals, notes)
    steel, low = _steel(low)
    if steel:
        vals["steel"] = steel
    else:
        notes.append("сталь не указана")
    problem = catalog.check("opp1", vals["dn"], vals["execution"])
    if problem:
        return {}, [], problem
    return vals, notes, ""


def parse(text):
    """→ (vals, notes, error)."""
    src = (text or "").strip()
    if not src:
        return {}, [], "пустая строка"
    low = src.lower().replace("ё", "е")
    if OST94_RE.search(low) or MARK94_RE.search(low):
        return _parse_ost94(OST94_RE.sub(" ", low))
    low = OST_RE.sub(" ", low)
    vals, notes = {}, []

    code, m = _type_code(low)
    if not code:
        return {}, [], "не указан тип (КП, КХ или ОПП1)"
    if m:
        low = low[:m.start()] + " " + low[m.end():]
    fixed = bool(re.search(r"неподв|с\s*упор", low))
    vals["opora_type"] = {"КП": "kp", "КХ": "kx"}[code] + ("_fix" if fixed else "")
    low = re.sub(r"(не)?подвижн\w*|неподв\w*|подв\.?|\(?с\s*упор\w*\)?", " ", low)

    m = EXE_RE.search(low)
    if not m:
        return {}, [], "не указано исполнение (А12, АС13, Б22)"
    letter = "А" if m.group(1).lower() in "аa" else "Б"
    vals["execution"] = letter + ("С" if m.group(2) else "") + m.group(3)
    low = low[:m.start()] + " " + low[m.end():]

    m = HEIGHT_RE.search(low)
    if m:
        vals["height"] = int(m.group(1))
        low = low[:m.start()] + " " + low[m.end():]
    low = _qty(low, vals, notes)

    steel, low = _steel(low)
    if steel:
        vals["steel"] = steel
    else:
        notes.append("сталь не указана")

    dns = catalog.diameters(vals["opora_type"])
    dn = 0
    m = re.search(r"(?:д[нуy]|dn)\s*\.?\s*(\d{2,4})", low)
    if m and int(m.group(1)) in dns:
        dn = int(m.group(1))
    else:
        found = [int(n) for n in NUM_RE.findall(low) if int(n) in dns]
        if found:
            dn = found[0]
    if not dn:
        return {}, [], "не указан диаметр трубы (Дн %s–%s)" % (dns[0], dns[-1])
    vals["dn"] = dn

    problem = catalog.check(vals["opora_type"], dn, vals["execution"])
    if problem:
        return {}, [], problem
    if vals.get("height"):
        # В счетах пишут «Н=100» у А1х и «Н=150» у А2х — это высота по ОСТ (у КХ в таблице 100–109).
        nominal = 100 if vals["execution"][-2] == "1" else 150
        std = catalog.standard_h(vals["opora_type"], dn, vals["execution"])
        if vals["height"] == nominal or abs(vals["height"] - std) <= 5:
            vals["height"] = 0
        else:
            problem = catalog.check_height(vals["opora_type"], dn, vals["execution"], vals["height"])
            if problem:
                return {}, [], problem
    return vals, notes, ""
