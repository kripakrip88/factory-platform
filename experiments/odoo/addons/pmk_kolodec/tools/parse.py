# -*- coding: utf-8 -*-
"""Изделие строкой, как болт и опора в Бутике.

Понимает короткую запись и названия из счетов МоегоСклада:
- стремянки 902-09-22.84: «с1-04 10шт», «С-1-04», «Стремянка водопроводного колодца С-1-04
  (длина лестницы 1,8 м) ТПР 902-09-22.84», «Стремянка С1 ТПР 902-09-22.84» (= С1-00);
- стремянки 901-09-11.84: «с-5 901», «с5», «Стремянка … С-4 (длина лестницы 2,25 м) ТПР 901-09-11.84»;
- по длине: «стремянка 1,8 м», «стремянка 2400» — серия 902, если длина есть в обеих
  (допишите «901», чтобы взять альбом V); 2,25 и 4,5 м — только 901;
- «мс-5 100шт», «Соединительный элемент колодец МС-5 (ширина90) ТПР 901-09-11.84» — МС с шифром
  901 или 902 (без шифра — 902);
- «мн1», «скоба ходовая»; «проставка ду300», «1219.01.000-02»; «зо», «звено ограждения»;
  «к1», «крышка металлическая».

Возвращает (поля, заметки, ошибка).
"""
import re

from . import alb901_2, alb901_5, alb902_7, catalog

QTY_RE = re.compile(r"(\d+)\s*шт", re.I)
ALB_RE = re.compile(r"(тпр|т\.?\s*п\.?)?\s*90([12])\s*-\s*09\s*-\s*(?:11|22)\s*\.\s*84[\w.\-]*", re.I)
ST902_RE = re.compile(r"(?<![а-яa-z])[сc]\s*-?\s*1\s*[-.]\s*(\d{1,2})(?!\d)", re.I)
ST_RE = re.compile(r"(?<![а-яa-zм])[сc]\s*(-)?\s*([1-9])(?![\d.,])", re.I)
MS_RE = re.compile(r"(?<![а-яa-z])м\s*[сc]\s*-?\s*([1-8])(?!\d)", re.I)
MN1_RE = re.compile(r"(?<![а-яa-z])мн\s*-?\s*1(?!\d)|скоб\w*\s+ходов", re.I)
PR_RE = re.compile(r"проставк|1219\s*\.\s*01\s*\.\s*000", re.I)
LEN_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(м(?![мa-zа-я])|мм)?")


def _steel(low):
    if re.search(r"09\s*г\s*2\s*с", low):
        return "09Г2С", re.sub(r"09\s*г\s*2\s*с(-\d+)?", " ", low)
    low = re.sub(r"в?ст\.?\s*3\w*", " ", low)
    return "", low


def _qty(low, vals, notes):
    m = QTY_RE.search(low)
    if m:
        vals["qty"] = int(m.group(1))
        return low[:m.start()] + " " + low[m.end():]
    notes.append("количество не указано")
    return low


def _ladder_by_length(low, series):
    """«стремянка 1,8 м» → марка по длине. → (вид, марка, заметка) или ошибка строкой."""
    found = []
    for m in LEN_RE.finditer(low):
        value = float(m.group(1).replace(",", "."))
        unit = m.group(2) or ("м" if value < 10 else "мм")
        found.append(round(value * 1000) if unit == "м" else round(value))
    for length in found:
        st902 = [k for k, v in alb902_7.ST.items() if v[0] == length]
        st901 = [k for k, v in alb901_5.ST.items() if v[1] == length]
        if series != "1" and st902:
            note = "" if series == "2" or not st901 else "по длине — серия 902; для альбома 901 допишите «901»"
            return "st902", "С1-" + st902[0], note
        if st901:
            return "st901", st901[0], ""
    if found:
        return None, None, "стремянки длиной %s мм в альбомах нет: 902 — 600…4200 через 300, 901 — С-1…С-9" % found[0]
    return None, None, "не указана марка или длина стремянки (с1-04, с-5 901, стремянка 1,8 м)"


def parse(text):
    """→ (vals, notes, error)."""
    src = (text or "").strip()
    if not src:
        return {}, [], "пустая строка"
    low = src.lower().replace("ё", "е")
    vals, notes = {}, []
    series = ""
    m = ALB_RE.search(low)
    if m:
        series = m.group(2)
        low = low[:m.start()] + " " + low[m.end():]
    if re.search(r"(?<!\d)901(?!\d)", low):
        series, low = "1", re.sub(r"(?<!\d)901(?!\d)", " ", low)
    elif re.search(r"(?<!\d)902(?!\d)", low):
        series, low = "2", re.sub(r"(?<!\d)902(?!\d)", " ", low)
    low = re.sub(r"альбом\w*\s*[ivx.\d]*|вып\w*\s*[ivx\d.]*|кжи[\w.\-]*|\bсб\b", " ", low)
    low = _qty(low, vals, notes)
    steel, low = _steel(low)
    vals["steel"] = steel or "Ст3пс"

    kind = mark = None
    if re.search(r"нтс\s*62|(?<![а-яa-z])лс\s*-?\s*\d", low):
        return {}, [], "это не альбом 901/902: стремянки НТС 62-91-111А и ЛС1–ЛС3 — своё изделие, в калькуляторе их нет"
    if PR_RE.search(low):
        m = re.search(r"1219\s*\.\s*01\s*\.\s*000\s*(?:-\s*0?(\d))?", low)
        if m:
            index = int(m.group(1) or 0)
            dy = list(alb901_2.PR)[index] if index < len(alb901_2.PR) else 0
        else:
            m = re.search(r"(?:д[уy]\s*)?(\d{3})(?!\d)", re.sub(r"проставк\w*|монтажн\w*", " ", low))
            dy = int(m.group(1)) if m else 0
        if not dy:
            return {}, [], "не указан Ду проставки (100, 150, 300, 400, 500, 600)"
        kind, mark = "pr", "Ду%s" % dy
    elif MS_RE.search(low) or re.search(r"соединит\w*\s+элемент|элемент\w*\s+соединит", low):
        m = MS_RE.search(low)
        if not m:
            return {}, [], "не указана марка элемента (МС-1…МС-8)"
        # Одно изделие в 901 ал. VI.88 и 902 ал. VIII.88; без шифра — 902 (так чаще в счетах).
        kind, mark = ("ms" if series == "1" else "ms902"), "МС-%s" % m.group(1)
    elif MN1_RE.search(low):
        kind, mark = "mn1", "МН1"
    elif re.search(r"звен\w*\s+огражд|(?<![а-яa-z])зо(?![а-яa-z])", low):
        kind, mark = "zo", "ЗО"
    elif re.search(r"крышк|(?<![а-яa-z])к\s*-?\s*1(?!\d)", low):
        kind, mark = "k1", "К1"
    else:
        is_ladder = "стремянк" in low or "лестниц" in low
        m = ST902_RE.search(low)
        if m and series != "1":
            kind, mark = "st902", "С1-%02d" % int(m.group(1))
        else:
            m = ST_RE.search(re.sub(r"\(.*?\)", " ", low))
            if m:
                dash, digit = m.group(1), m.group(2)
                if digit == "1" and not dash and series != "1":
                    kind, mark = "st902", "С1-00"
                elif digit == "1" and series == "2":
                    kind, mark = "st902", "С1-00"
                else:
                    kind, mark = "st901", "С-%s" % digit
                    if series == "2":
                        notes.append("в записи 902-09-22.84, а %s — марка альбома 901-09-11.84" % mark)
            elif is_ladder:
                kind, mark, note = _ladder_by_length(low, series)
                if not kind:
                    return {}, [], note
                if note:
                    notes.append(note)
            else:
                return {}, [], "не понял изделие: стремянка (с1-04, с-5), мс-5, мн1, проставка ду300, зо, к1"
    problem = catalog.check(kind, mark)
    if problem:
        return {}, [], problem
    vals.update(item_type=kind, mark=mark)
    return vals, notes, ""
