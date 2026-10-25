# -*- coding: utf-8 -*-
"""ТПР 901-09-11.84, альбом VI.88 «Дополнительные мероприятия для строительства
в сейсмических районах (7–9 баллов)» (ЦНИИЭП, 1988).

Источник — скан meganorm 4293845913 (~/Projects/kolodcy/normy/901-09-11.84_alb6.88.pdf),
PDF-страницы 31–32. Документация — docs/TPR_901-09-11.84.md.

Те же МС-1…МС-8 лист в лист есть в ТПР 902-09-22.84 ал. VIII.88 (КЖИ.10.0.0 / 11.0.0, PDF стр.
29–30; скан meganorm 4293845924) — вид «ms902»: детали общие, другие шифр и название (в счетах МС
чаще «… ТПР 902-09-22.84»).

Элемент соединительный — связывает соседние кольца рабочей части колодца:
- МС-1…МС-4 (КЖИ.10.0.0): две пластины 8×80 l = 160 по краям, между ними пластина
  6×80 длиной B (90/100/110/120) по оси — тавр с двух сторон (ГОСТ 5264-80-Т3-Δ6);
- МС-5…МС-8 (КЖИ.11.0.0): пластина 8×80 l = 160 с одной стороны, с другой — 8×80 l = 84
  угловым швом (У5-Δ6), средняя 6×80 длиной B — у короткой пластины заподлицо с её краем.
Масса таблицы сходится с деталями (МС-1: 2·0,80 + 0,34 = 1,94).

В альбоме — полосы ГОСТ 103 (8×80, 6×80). Полоса у нас — это лист, режем лазером (Антон
25.10.2026) — цена по листу той же толщины.
"""
from .common import part, strip_kg

ALBUM = "ТПР 901-09-11.84"
ALBUM_FULL = "ТПР 901-09-11.84, альбом VI.88"

ALBUM_902 = "ТПР 902-09-22.84"
ALBUM_902_FULL = "ТПР 902-09-22.84, альбом VIII.88"

TYPES = {
    "ms": dict(code="МС", label="Элемент соединительный МС (901)", album=ALBUM_FULL),
    "ms902": dict(code="МС", label="Элемент соединительный МС (902)", album=ALBUM_902_FULL),
}

# Марка → (обозначение, B, масса альбома).
MS = {
    "МС-1": ("КЖИ.10.0.0", 90, 1.94), "МС-2": ("КЖИ.10.0.0-01", 100, 1.98),
    "МС-3": ("КЖИ.10.0.0-02", 110, 2.01), "МС-4": ("КЖИ.10.0.0-03", 120, 2.05),
    "МС-5": ("КЖИ.11.0.0", 90, 1.56), "МС-6": ("КЖИ.11.0.0-01", 100, 1.60),
    "МС-7": ("КЖИ.11.0.0-02", 110, 1.63), "МС-8": ("КЖИ.11.0.0-03", 120, 1.67),
}
PLATE_W, END_L, SHORT_L, END_T, MID_T = 80, 160, 84, 8, 6
MAT8 = [("sheet", 8)]
MAT6 = [("sheet", 6)]


def marks(kind):
    return list(MS)


def check(kind, mark):
    return "" if mark in MS else "Элемента %s в альбоме VI.88 нет — бывают МС-1…МС-8" % mark


def symmetric(mark):
    return int(mark[3:]) <= 4


def outside_album(kind, mark):
    return ""


def dims(kind, mark):
    return dict(length=MS[mark][1] + 2 * END_T, width=PLATE_W, height=END_L)


def parts(kind, mark, bend_k=None):
    b = MS[mark][1]
    mid = part("mid", 2, "Пластина средняя 6×80×%s — лист 6" % b, 1, strip_kg(MID_T, PLATE_W, b), MAT6)
    if symmetric(mark):
        return [part("end", 1, "Пластина торцевая 8×80×%s — лист 8" % END_L, 2, strip_kg(END_T, PLATE_W, END_L), MAT8), mid]
    return [
        part("end", 1, "Пластина торцевая 8×80×%s — лист 8" % END_L, 1, strip_kg(END_T, PLATE_W, END_L), MAT8),
        part("short", 3, "Пластина торцевая 8×80×%s — лист 8" % SHORT_L, 1, strip_kg(END_T, PLATE_W, SHORT_L), MAT8),
        mid,
    ]


def album_mass(kind, mark):
    return MS[mark][2]


def designation(kind, mark):
    return "%s-%s (%s)" % ("902-09-22.84" if kind == "ms902" else "901-09-11.84", MS[mark][0], mark)


def name(kind, mark, steel):
    return "Элемент соединительный %s (B=%s мм) %s" % (mark, MS[mark][1], ALBUM_902_FULL if kind == "ms902" else ALBUM_FULL)


def short(kind, mark, steel):
    return "%s · B %s · %s · %s" % (mark, MS[mark][1], "две пластины 160" if symmetric(mark) else "160 + 84",
                                    "902" if kind == "ms902" else "901")


def history_patterns(kind, mark):
    """Изделие одно — продажи под обоими шифрами."""
    return [r"соедин", r"мс\s*-?\s*%s(\D|$)" % mark[3:]], None
