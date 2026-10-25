# -*- coding: utf-8 -*-
"""ТПР 901-09-11.84, альбом V «Строительные изделия» (водопроводные колодцы, ЦНИИЭП, 1983).

Источник — скан meganorm 4293845914 (~/Projects/kolodcy/normy/901-09-11.84_alb5.pdf),
PDF-страницы 5–6. Документация — docs/TPR_901-09-11.84.md.

- Стремянка С-1…С-9 (КЖИ.С1СБ, КЖИ.С1): стойки — уголок 50×5 длиной A, ступени ⌀18 A-I
  l = 480, шаг 300. От верха до первой ступени 45, от последней до низа 255; у С-4
  (A = 2250, не кратно 300) — 120 и 330.
  ⚠ Ошибка альбома: в спецификации исполнений ступеней на одну больше, чем n в таблице
  (кроме С-4), и масса таблицы посчитана по спецификации. При шаге 300 и отступах 45/255
  в длину A входит ровно n ступеней (С-1: 45 + 3·300 + 255 = 1200) — так же в альбоме VII
  902-09-22.84 (A = 300·n). Принято n по таблице и чертежу; масса по деталям меньше
  альбомной на одну ступень (0,96 кг).
- Скоба ходовая МН1 (КЖИ.МН1): ⌀18 A-I, развёртка 850.
  ⚠ Масса в штампе 1,36 кг не сходится с ⌀18 × 850 (1,70 кг) — принята масса по детали.
"""
from .common import ANGLE, metres, part, round_kg

ALBUM = "ТПР 901-09-11.84"
ALBUM_FULL = "ТПР 901-09-11.84, альбом V"

TYPES = {
    "st901": dict(code="С", label="Стремянка С (водопроводные колодцы)", album=ALBUM_FULL),
    "mn1": dict(code="МН1", label="Скоба ходовая МН1", album=ALBUM_FULL),
}

# Марка → (исполнение КЖИ.С1, A, n ступеней, отступ сверху, снизу, масса альбома).
ST = {
    "С-1": ("", 1200, 4, 45, 255, 13.84),
    "С-2": ("-01", 1500, 5, 45, 255, 17.08),
    "С-3": ("-02", 1800, 6, 45, 255, 20.30),
    "С-4": ("-03", 2250, 7, 120, 330, 23.68),
    "С-5": ("-04", 2400, 8, 45, 255, 26.74),
    "С-6": ("-05", 2100, 7, 45, 255, 23.52),
    "С-7": ("-06", 2700, 9, 45, 255, 30.00),
    "С-8": ("-07", 4200, 14, 45, 255, 46.06),
    "С-9": ("-08", 4500, 15, 45, 255, 49.36),
}
ST_STEP, ST_WIDTH, ST_RUNG, ST_RUNG_D = 300, 500, 480, 18
MN1_D, MN1_DEV = 18, 850

ANGLE_MAT = [("profile", "Уголок равнополочный", "50x50x5")]
RUNG_MAT = [("profile", "Круг", "d18")]


def marks(kind):
    return list(ST) if kind == "st901" else ["МН1"]


def check(kind, mark):
    if mark not in marks(kind):
        return "Стремянки %s в альбоме V нет — бывают С-1…С-9" % mark if kind == "st901" else "Не понял марку %s" % mark
    return ""


def geometry(mark):
    _exe, a, n, top, bottom, _m = ST[mark]
    assert top + (n - 1) * ST_STEP + bottom == a, mark
    return dict(length=a, rungs=n, top=top, bottom=bottom, width=ST_WIDTH)


def outside_album(kind, mark):
    return ""


def dims(kind, mark):
    if kind == "st901":
        g = geometry(mark)
        return dict(length=g["length"], rungs=g["rungs"], width=ST_WIDTH)
    return dict(length=MN1_DEV, width=170, height=240)


def parts(kind, mark):
    if kind == "st901":
        g = geometry(mark)
        return [
            part("angle", 1, "Стойка — уголок 50×5 L=%s" % g["length"], 2, ANGLE["50x50x5"] * g["length"] / 1000.0, ANGLE_MAT),
            part("rung", 2, "Ступень — круг ⌀18 L=%s" % ST_RUNG, g["rungs"], round_kg(ST_RUNG_D) * ST_RUNG / 1000.0, RUNG_MAT),
        ]
    return [part("bar", 1, "Скоба — круг ⌀18, развёртка %s, 4 гиба" % MN1_DEV, 1,
                 round_kg(MN1_D) * MN1_DEV / 1000.0, RUNG_MAT)]


def album_mass(kind, mark):
    return ST[mark][5] if kind == "st901" else 1.36


def designation(kind, mark):
    if kind == "st901":
        return "901-09-11.84-КЖИ.С1%s (%s)" % (ST[mark][0], mark)
    return "901-09-11.84-КЖИ.МН1"


def name(kind, mark, steel):
    if kind == "st901":
        return "Стремянка колодца %s (длина лестницы %s м) %s" % (mark, metres(ST[mark][1]), ALBUM)
    return "Скоба ходовая МН1 %s" % ALBUM


def short(kind, mark, steel):
    if kind == "st901":
        g = geometry(mark)
        return "Стремянка %s · %s м · %s ступ. · 901" % (mark, metres(g["length"]), g["rungs"])
    return "Скоба ходовая МН1 · 901"


def history_patterns(kind, mark):
    if kind == "st901":
        return [r"стремянк", r"с\s*-\s*%s(\D|$)" % mark[2:], r"901-09"], None
    return [r"скоб\w*\s+ходов", r"мн\s*-?\s*1(\D|$)"], None
