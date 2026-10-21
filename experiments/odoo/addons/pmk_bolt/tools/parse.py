# -*- coding: utf-8 -*-
"""Болт строкой, как в Бутике (Антон 21.10.2026: «бф 2.1 м30 640мм ст3 10шт»).

Понимает и короткую запись, и полное название из счёта МоегоСклада:
- «бф 2.1 м30 640мм ст3 10шт», «болт 1.1 М24х1000 09г2с 48 шт»;
- «2.1 м30*600 р250 09г2с 896шт» — р250 / «резьба 250» — длина резьбы;
- «тип 5 м36 800 ст3 20шт», «бф 5 м36 800»;
- «… калён гайка 120» — вид гайки и её цена;
- «Болт фундаментный (анкерный) тип 1.1 М-30х900 09Г2С ГОСТ 24379.1-2012».

Возвращает словарь полей строки и заметки (что подставили по умолчанию)
или текст ошибки — строку тогда не заводим, она остаётся в поле ввода.
"""
import re

from . import gost

TYPE_RE = re.compile(r"(?<![\d.,])([12])[.,]([12])(?![\d.,])")
TYPE5_RE = re.compile(r"(?:тип\s*|\bт\s*)5\b|(?<![\d.,])5(?=\s*[мm]\s*-?\s*\d)", re.I)
SIZE_RE = re.compile(r"[мm]\s*-?\s*(\d{2})\s*[хx×*]\s*(\d{3,4})", re.I)
DIAM_RE = re.compile(r"(?<![а-яa-z])[мm]\s*-?\s*(\d{2})(?!\d)", re.I)
THREAD_RE = re.compile(r"(?:резьб\w*|рез\.?|\bр)\s*=?\s*(\d{2,4})", re.I)
QTY_RE = re.compile(r"(\d+)\s*шт", re.I)
LEN_MM_RE = re.compile(r"(?:\bl\s*=?\s*|длин\w*\s*)?(\d{3,4})\s*мм", re.I)
NUT_PRICE_RE = re.compile(r"гайк\w*\s*(\d+(?:[.,]\d+)?)", re.I)
GOST_RE = re.compile(r"гост\s*\d+(?:\.\d+)?(?:\s*[-–]\s*\d{2,4})?", re.I)


def parse(text):
    """→ (vals, notes, error)."""
    src = (text or "").strip()
    if not src:
        return {}, [], "пустая строка"
    low = GOST_RE.sub(" ", src.lower().replace("ё", "е"))
    vals, notes = {}, []

    m = TYPE_RE.search(low)
    if m:
        vals["bolt_type"] = "%s.%s" % (m.group(1), m.group(2))
        low = low[:m.start()] + " " + low[m.end():]
    elif TYPE5_RE.search(low):
        vals["bolt_type"] = "5"
        low = TYPE5_RE.sub(" ", low, count=1)
    else:
        return {}, [], "не указан тип (1.1, 1.2, 2.1, 2.2 или 5)"

    m = SIZE_RE.search(low)
    if m:
        vals["diameter"], vals["length"] = m.group(1), int(m.group(2))
        low = low[:m.start()] + " " + low[m.end():]
    else:
        m = DIAM_RE.search(low)
        if not m:
            return {}, [], "не указан диаметр (М30)"
        vals["diameter"] = m.group(1)
        low = low[:m.start()] + " " + low[m.end():]

    m = THREAD_RE.search(low)
    if m:
        vals["thread_len"] = int(m.group(1))
        low = low[:m.start()] + " " + low[m.end():]
    m = QTY_RE.search(low)
    if m:
        vals["qty"] = int(m.group(1))
        low = low[:m.start()] + " " + low[m.end():]
    else:
        vals["qty"] = 1
        notes.append("количество не указано — 1 шт")
    m = NUT_PRICE_RE.search(low)
    if m:
        vals["nut_price"] = float(m.group(1).replace(",", "."))
        low = low[:m.start()] + " " + low[m.end():]
    if re.search(r"кал[её]н|кл\.?\s*8|\b8[.,]8\b", low):
        vals["nut_kind"] = "hardened"
    elif re.search(r"спец", low):
        vals["nut_kind"] = "special"

    if re.search(r"09\s*г\s*2\s*с", low):
        vals["steel"] = "09Г2С"
        low = re.sub(r"09\s*г\s*2\s*с(-\d)?", " ", low)
    elif re.search(r"в?ст\.?\s*3", low):
        vals["steel"] = "Ст3"
        low = re.sub(r"в?ст\.?\s*3\w*", " ", low)
    else:
        vals["steel"] = "09Г2С"
        notes.append("сталь не указана — 09Г2С")

    if "length" not in vals:
        m = LEN_MM_RE.search(low)
        if m:
            vals["length"] = int(m.group(1))
        else:
            nums = [int(n) for n in re.findall(r"(?<![\d.,])(\d{3,4})(?![\d.,])", low)]
            if not nums:
                return {}, [], "не указана длина (640мм)"
            vals["length"] = nums[0]

    d = int(vals["diameter"])
    if d not in gost.SIZES:
        return {}, [], "М%s в ГОСТ 24379.1 нет" % d
    problem = gost.check(vals["bolt_type"], d)
    if problem:
        return {}, [], problem
    return vals, notes, ""
