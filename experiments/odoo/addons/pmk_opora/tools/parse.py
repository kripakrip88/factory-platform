# -*- coding: utf-8 -*-
"""Опора строкой, как болт в Бутике.

Понимает короткую запись и названия из счетов МоегоСклада:
- «кх а12 219 09г2с 20шт», «кх неподв а22 219 64шт», «кп ас13 530 ст3пс»;
- «кх а12 89 н50 10шт» / «Н=50мм» — своя высота (не по ОСТ);
- «Опора корпусная хомутовая КХ Дн 630 мм А12 ОСТ 36-146-88 Н=100мм»;
- «Опора неподвижная 219-КХ-А22 Ду 219 (с упорами) ОСТ 36-146-88»;
- «Опора 57-КХ-А11 ОСТ 36-146-88 09Г2С», «Опора-КХ-219-А12 (ОСТ 36-146-88) без покраски».

Неподвижная — «неподв» или «с упорами»; иначе подвижная. Возвращает (поля, заметки, ошибка).
"""
import re

from . import ost

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


def parse(text):
    """→ (vals, notes, error)."""
    src = (text or "").strip()
    if not src:
        return {}, [], "пустая строка"
    low = OST_RE.sub(" ", src.lower().replace("ё", "е"))
    vals, notes = {}, []

    code, m = _type_code(low)
    if not code:
        return {}, [], "не указан тип (КП или КХ)"
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
    m = QTY_RE.search(low)
    if m:
        vals["qty"] = int(m.group(1))
        low = low[:m.start()] + " " + low[m.end():]
    else:
        notes.append("количество не указано")

    if re.search(r"09\s*г\s*2\s*с", low):
        vals["steel"] = "09Г2С"
        low = re.sub(r"09\s*г\s*2\s*с(-\d+)?", " ", low)
    elif re.search(r"10\s*г\s*2", low):
        vals["steel"] = "10Г2"
        low = re.sub(r"10\s*г\s*2", " ", low)
    elif re.search(r"в?ст\.?\s*3\s*сп", low):
        vals["steel"] = "Ст3сп"
        low = re.sub(r"в?ст\.?\s*3\s*сп\d*", " ", low)
    elif re.search(r"в?ст\.?\s*3", low):
        vals["steel"] = "Ст3пс"
        low = re.sub(r"в?ст\.?\s*3\w*", " ", low)
    elif re.search(r"(?:ст\.?|сталь)\s*20(?!\d)", low):
        vals["steel"] = "20"
        low = re.sub(r"(?:ст\.?|сталь)\s*20", " ", low)
    else:
        notes.append("сталь не указана")

    dns = ost.diameters(vals["opora_type"])
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

    problem = ost.check(vals["opora_type"], dn, vals["execution"])
    if problem:
        return {}, [], problem
    if vals.get("height"):
        # В счетах пишут «Н=100» у А1х и «Н=150» у А2х — это высота по ОСТ (у КХ в таблице 100–109).
        nominal = 100 if vals["execution"][-2] == "1" else 150
        std = ost.standard_h(vals["opora_type"], dn, vals["execution"])
        if vals["height"] == nominal or abs(vals["height"] - std) <= 5:
            vals["height"] = 0
        else:
            problem = ost.check_height(vals["opora_type"], dn, vals["execution"], vals["height"])
            if problem:
                return {}, [], problem
    return vals, notes, ""
