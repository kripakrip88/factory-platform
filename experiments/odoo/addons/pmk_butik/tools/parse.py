# -*- coding: utf-8 -*-
"""Наименование строки Бутика — что это: лист, метиз или прокат (без базы).

Бутов пишет наименование одной ячейкой, как в своих файлах Excel:
  «Лист 10х60» + длина 180 — лист толщиной 10 мм, деталь 60 × 180 мм;
  «Болт М10х40», «Гайка М24», «Петля …» — штучное (метизы, покупное);
  остальное — прокат: «Уголок 63х4», «Швеллер 80х50х4», «Труба ВГП 40х3.5».
Прокат и лист дальше ищутся умным поиском справочников pmk_calc (size_search).
"""
import re

SHEET_WORD_RE = re.compile(r"^\s*(?:лист|пластина|полоса)\b", re.IGNORECASE)
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
PIECE_WORDS = ("болт", "гайка", "шайба", "шпилька", "анкер", "винт", "саморез", "заклепка",
               "заклёпка", "петля", "замок", "отвод", "заглушка", "дюбель")
COATING_WORDS = ("грунт", "эмаль", "краска", "горячее цинкование", "порошковая окраска", "покрытие")


def _num(text):
    return float(text.replace(",", "."))


def classify(name):
    """→ {"kind": "sheet"|"piece"|"linear"|"empty", "thickness", "width", "length"}.

    Лист: «Лист 10х60» — толщина 10, ширина 60 (длина — из колонки «Длина»);
    три числа («Пластина 3100х85х0,7») — толщина самое малое, два других — размеры
    детали целиком (длина колонки не нужна)."""
    text = (name or "").strip()
    out = {"kind": "empty", "thickness": None, "width": None, "length": None}
    if not text:
        return out
    if SHEET_WORD_RE.match(text):
        nums = [_num(n) for n in NUM_RE.findall(text)]
        if len(nums) >= 3:
            a, b, c = nums[:3]
            t = min(a, b, c)
            rest = [a, b, c]
            rest.remove(t)
            return dict(out, kind="sheet", thickness=t, width=min(rest), length=max(rest))
        if len(nums) == 2:
            return dict(out, kind="sheet", thickness=nums[0], width=nums[1])
        if len(nums) == 1:
            return dict(out, kind="sheet", thickness=nums[0])
    low = text.lower()
    if any(low.startswith(word) for word in COATING_WORDS):
        return dict(out, kind="coating")
    if any(low.startswith(word) for word in PIECE_WORDS):
        return dict(out, kind="piece")
    return dict(out, kind="linear")


SIZE_X_RE = re.compile(r"(\d)\s*[xхXХ*×]\s*(\d)")
LATIN_M_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё])[MmМм](?=\d)")


def piece_query(name):
    """Метиз для поиска по справочнику: там «Болт М10×40» — знак умножения и русская М.

    Бутов пишет «Болт М10х40», «болт M10x40» (русская х, латинские x и M) — приводим."""
    text = SIZE_X_RE.sub(r"\1×\2", (name or "").strip())
    return LATIN_M_RE.sub("М", text)


# ─── Короткая запись одной строкой (16.10.2026) ──────────────────────────────
# Антон: «расшифровку как в зонтах»:
#   «д1 шв10 1200мм 10шт 09г»       → поз. Д1, Швеллер 10, длина 1200, 10 шт, 09Г2С
#   «пл2 200х140х20мм ст3 10шт»     → поз. Пл2, Пластина 20, 140 × 200, 10 шт, Ст3
#   «болт 10х110 8.8»               → Болт М10×110, класс 8.8
#   «гф21 60мкм»                    → покрытие: грунт ГФ-021, 60 мкм

PROFILE_ABBR = {
    "шв": "Швеллер", "швел": "Швеллер", "уг": "Уголок", "дв": "Двутавр", "двут": "Двутавр",
    "тр": "Труба", "тп": "Труба профильная", "кр": "Круг", "кв": "Квадрат", "арм": "Арматура",
    "шг": "Шестигранник",
}
SHEET_ABBR = {"пл": "Пластина", "лист": "Лист", "л": "Лист", "пол": "Полоса", "п": "Пластина"}
PIECE_ABBR = {"болт": "Болт", "гайка": "Гайка", "шайба": "Шайба", "анкер": "Анкер", "шпилька": "Шпилька",
              "винт": "Винт"}
GRADES = {
    "09г": "09Г2С", "09г2с": "09Г2С", "ст3": "Ст3", "ст3сп": "Ст3сп", "ст3пс": "Ст3пс", "ст20": "Ст20",
    "10хснд": "10ХСНД", "15хснд": "15ХСНД", "17г1с": "17Г1С", "40х": "40Х", "ст45": "Ст45",
    "с235": "С235", "с245": "С245", "с255": "С255", "с345": "С345", "с355": "С355",
    "aisi304": "AISI 304", "aisi430": "AISI 430", "оц": "оцинк.",
}
COATINGS = {
    "гф21": "Грунт ГФ-021", "гф021": "Грунт ГФ-021", "гф-021": "Грунт ГФ-021",
    "пф115": "Эмаль ПФ-115", "пф-115": "Эмаль ПФ-115", "хв124": "Эмаль ХВ-124",
    "цинк": "Горячее цинкование", "гц": "Горячее цинкование", "порошок": "Порошковая окраска",
}
_X = r"\s*[xхXХ*×]\s*"
NUM = r"\d+(?:[.,]\d+)?"
POS_RE = re.compile(r"^([а-яё]{1,4})(\d+[а-яё]?)$", re.IGNORECASE)
ABBR_RE = re.compile(r"^([а-яё]{1,5})-?(\d.*)?$", re.IGNORECASE)
QTY_RE = re.compile(r"^(\d+)\s*шт\.?$", re.IGNORECASE)
LEN_RE = re.compile(r"^(?:l=)?(%s)\s*мм$" % NUM, re.IGNORECASE)
DIMS_RE = re.compile(r"^(%s)(?:%s(%s))(?:%s(%s))?(?:мм)?$" % (NUM, _X, NUM, _X, NUM), re.IGNORECASE)
CLASS_RE = re.compile(r"^(\d{1,2}\.\d)$")
MKM_RE = re.compile(r"^(\d+)\s*мкм$", re.IGNORECASE)


def _tokens(text):
    text = re.sub(r"(\d)\s*(шт|мм|мкм)\b", r"\1\2", text, flags=re.IGNORECASE)
    text = re.sub(r"(%s)%s(%s)" % (NUM, _X, NUM), r"\1х\2", text)
    text = re.sub(r"(%s)%s(%s)" % (NUM, _X, NUM), r"\1х\2", text)
    return [t for t in re.split(r"[\s;]+", text.strip()) if t]


def _dims(token):
    m = DIMS_RE.match(token)
    if not m:
        return None
    return [_num(g) for g in m.groups() if g]


def _g(value):
    return ("%g" % value).replace(".", ",")


def decode(line):
    """Короткая строка → поля строки Бутика или None (строка обычная, не трогаем).

    → {"pos", "name", "width", "length_mm", "qty", "grade", "coating"} — только найденное."""
    tokens = _tokens(line or "")
    if not tokens:
        return None
    out, words, base, kind, sizes, series = {}, [], None, None, [], ""
    lowered = [t.lower() for t in tokens]
    # Первое слово «д1», «пл2», «поз5» — позиция, если дальше ещё что-то есть.
    first = POS_RE.match(lowered[0])
    if (first and len(tokens) > 1 and first.group(1) not in PROFILE_ABBR and first.group(1) not in PIECE_ABBR
            and lowered[0] not in COATINGS and lowered[0] not in GRADES):
        out["pos"] = first.group(1).capitalize() + first.group(2)
        if first.group(1) in ("пл", "п", "лист", "л"):
            base, kind = SHEET_ABBR[first.group(1)], "sheet"
        tokens, lowered = tokens[1:], lowered[1:]
    for token, low in zip(tokens, lowered):
        if low in COATINGS:
            out["coating"] = COATINGS[low]
            continue
        if MKM_RE.match(low):
            out["mkm"] = int(MKM_RE.match(low).group(1))
            continue
        if low.rstrip(".") in GRADES:
            out["grade"] = GRADES[low.rstrip(".")]
            continue
        if CLASS_RE.match(low) and kind == "piece":
            out["grade"] = "кл. " + low
            continue
        m = QTY_RE.match(low)
        if m:
            out["qty"] = float(m.group(1))
            continue
        m = LEN_RE.match(low)
        if m and not low.startswith("l=") or (m and low.startswith("l=")):
            out["length_mm"] = _num(m.group(1))
            continue
        dims = _dims(low)
        if dims:
            sizes = dims
            continue
        m = ABBR_RE.match(low)
        if m and base is None:
            word, rest = m.group(1), m.group(2) or ""
            if word in PROFILE_ABBR:
                base, kind = PROFILE_ABBR[word], "linear"
                if rest:
                    one = re.match(r"^(%s)([а-яё]*)$" % NUM, rest, re.IGNORECASE)
                    if one:  # «шв10», «шв10п» — номер и серия
                        sizes, series = [_num(one.group(1))], one.group(2).upper()
                    else:
                        sizes = _dims(rest) or sizes
                continue
            if word in SHEET_ABBR:
                base, kind = SHEET_ABBR[word], "sheet"
                if rest:
                    sizes = _dims(rest) or sizes
                continue
            if word in PIECE_ABBR:
                base, kind = PIECE_ABBR[word], "piece"
                continue
        if re.match(r"^%s$" % NUM, low) and kind in ("linear", "piece", "sheet") and len(sizes) < 3:
            sizes.append(_num(low))  # «уг 63 4» — размеры через пробел
            continue
        words.append(token)
    if "coating" in out:
        name = out.pop("coating")
        if "mkm" in out:
            name += ", %d мкм" % out.pop("mkm")
        if words:
            name += ", " + " ".join(words)
        out["name"] = name
        out["kind"] = "coating"
        return out
    out.pop("mkm", None)
    if base is None and not out:
        return None
    if kind == "sheet":
        if len(sizes) >= 3:
            t = min(sizes[:3])
            rest = sorted(sizes[:3])[1:]
            out.update(width=rest[0], length_mm=rest[1])
            out["name"] = "%s %s" % (base, _g(t))
        elif len(sizes) == 2:
            out["name"] = "%s %s" % (base, _g(sizes[0]))
            out["width"] = sizes[1]
        else:
            out["name"] = " ".join([base] + [_g(s) for s in sizes] + words)
    elif kind == "piece":
        if len(sizes) >= 2:
            out["name"] = "%s М%s×%s" % (base, _g(sizes[0]), _g(sizes[1]))
        elif len(sizes) == 1:
            out["name"] = "%s М%s" % (base, _g(sizes[0]))
        else:
            out["name"] = " ".join([base] + words)
        words = []
    elif kind == "linear":
        size = "х".join(_g(s) for s in sizes) + series
        out["name"] = " ".join(p for p in [base, size] + words if p)
    else:
        out["name"] = " ".join(words)
    if kind != "piece" and kind != "linear" and words and kind == "sheet" and len(sizes) >= 2:
        out["name"] += " " + " ".join(words)
    out["kind"] = kind or "linear"
    return out


def decode_for_cell(line):
    """Расшифровка для ячейки: только если в строке есть короткая запись.

    «Лист 10х60», «Болт М10х40», «Уголок 63х4» — обычная запись Бутова, оставляем как
    написано (ширину листа и метиз и так найдёт справочник). Расшифровываем, когда
    раскрыто сокращение («шв», «пл», «гф21») или в строке есть позиция, количество,
    длина или марка."""
    dec = decode(line)
    if not dec or not dec.get("name"):
        return None
    typed = (line or "").split()
    expanded = typed and dec["name"].split()[0].lower() != typed[0].lower()
    extra = any(k in dec for k in ("pos", "qty", "length_mm", "grade"))
    return dec if (expanded or extra) else None
