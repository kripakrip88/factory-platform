# -*- coding: utf-8 -*-
"""ТПР 902-09-22.84, альбом VII «Строительные изделия» (ЦНИИЭП инженерного оборудования, 1983).

Источник — скан meganorm 4293846357 (~/Projects/kolodcy/normy/902-09-22.84_alb7.pdf),
PDF-страницы 12–14. Документация — docs/TPR_902-09-22.84.md.

- Стремянка С1 (КЖИ.С1СБ, КЖИ.С1; стр. 11–12): две стойки — уголок 50×5 длиной A, ступени —
  ⌀18 A-I l = 485, шаг 300, от верха до первой ступени 45, от последней до низа 255.
  Таблица: A = 300·n, n — число ступеней; спецификация исполнений -00…-12 даёт столько же
  ступеней, масса таблицы сходится с ней (два источника согласны).
- Звено ограждения ЗО (КЖИ.ЗО; стр. 11): полосы 30×4 (2), квадрат 20 (3), полоса 100×4.
  Полоса у нас — лист, режем лазером (Антон 25.10.2026): цена по листу той же толщины.
- Крышка металлическая К1 (КЖИ.К1; стр. 13): две половины ⌀610 из листа 5, накладка
  50×5 l = 600, две ручки из полосы 10×30 l = 330 на болтах М6.
"""
import math

from .common import ANGLE, DENSITY, metres, part, round_kg, square_kg, strip_kg

ALBUM = "ТПР 902-09-22.84"
ALBUM_FULL = "ТПР 902-09-22.84, альбом VII"

TYPES = {
    "st902": dict(code="С1", label="Стремянка С1 (канализационные колодцы)", album=ALBUM_FULL),
    "zo": dict(code="ЗО", label="Звено ограждения ЗО", album=ALBUM_FULL),
    "k1": dict(code="К1", label="Крышка металлическая К1", album=ALBUM_FULL),
}

# Стремянка: исполнение → (A, n ступеней, масса альбома, кг). -13…-18 — вне альбома:
# продолжение ряда A = 300·n (в счетах МС были С-1-16 «5,4 м» и С-1-18 «6 м»).
ST = {"%02d" % i: (600 + 300 * i, 2 + i, m) for i, m in enumerate(
    (6.6, 9.7, 12.9, 16.2, 19.5, 22.7, 25.9, 29.2, 32.4, 35.7, 38.9, 42.1, 45.4, 0, 0, 0, 0, 0, 0))}
ST_ALBUM_LAST = 12
ST_TOP, ST_BOTTOM, ST_STEP = 45, 255, 300
ST_WIDTH, ST_RUNG, ST_RUNG_D = 500, 485, 18

ANGLE_MAT = [("profile", "Уголок равнополочный", "50x50x5")]
RUNG_MAT = [("profile", "Круг", "d18")]


def marks(kind):
    if kind == "st902":
        return ["С1-%s" % k for k in ST]
    return [TYPES[kind]["code"]]


def check(kind, mark):
    if mark not in marks(kind):
        if kind == "st902":
            return "Стремянки %s нет — бывают С1-00…С1-12 по альбому (0,6–4,2 м через 0,3) и С1-13…С1-18 вне альбома (до 6 м)" % mark
        return "Не понял марку %s" % mark
    return ""


def outside_album(kind, mark):
    """Исполнение не из альбома — продолжение ряда. → пометка или ""."""
    if kind == "st902" and int(mark[3:]) > ST_ALBUM_LAST:
        return "вне альбома: продолжение ряда A = 300·n (в альбоме до С1-12, 4,2 м)"
    return ""


def dims(kind, mark):
    if kind == "st902":
        a, n, _m = ST[mark[3:]]
        return dict(length=a, rungs=n, width=ST_WIDTH)
    if kind == "zo":
        return dict(length=1000, height=1150, width=0)
    return dict(length=610, width=610)


def parts(kind, mark, bend_k=None):
    if kind == "st902":
        a, n, _m = ST[mark[3:]]
        return [
            part("angle", 1, "Стойка — уголок 50×5 L=%s" % a, 2, ANGLE["50x50x5"] * a / 1000.0, ANGLE_MAT),
            part("rung", 2, "Ступень — круг ⌀18 L=%s" % ST_RUNG, n, round_kg(ST_RUNG_D) * ST_RUNG / 1000.0, RUNG_MAT),
        ]
    if kind == "zo":
        return [
            part("strip", 1, "Поручень и средняя полоса 30×4×1000 — лист 4", 2, strip_kg(4, 30, 1000), [("sheet", 4)]),
            part("post", 2, "Стойка — квадрат 20 L=1150", 3, square_kg(20) * 1.15, [("profile", "Квадрат", "20")]),
            part("plate", 3, "Нижняя полоса 100×4×1000 — лист 4", 1, strip_kg(4, 100, 1000), [("sheet", 4)]),
        ]
    half = math.pi * 305 ** 2 / 2 * 5 * DENSITY
    return [
        part("half", 1, "Половина крышки ⌀610 — лист 5", 2, half, [("sheet", 5)]),
        part("strip", 2, "Накладка 50×5×600 — лист 5", 1, strip_kg(5, 50, 600), [("sheet", 5)]),
        part("handle", 3, "Ручка — заготовка 330×30 из листа 10, гнутая", 2, strip_kg(10, 30, 330), [("sheet", 10)]),
        part("bolt", 4, "Болт М6×25 ГОСТ 7796-70, гайка М6 ГОСТ 5915-70, шайба ГОСТ 11371-78 — комплект", 4, 0.04),
    ]


def album_mass(kind, mark):
    if kind == "st902":
        return ST[mark[3:]][2]
    return {"zo": 15.8, "k1": 17.5}[kind]


def designation(kind, mark):
    if kind == "st902":
        return "902-09-22.84-КЖИ.%s" % mark
    return "902-09-22.84-КЖИ.%s" % mark


def name(kind, mark, steel):
    if kind == "st902":
        a = ST[mark[3:]][0]
        return "Стремянка колодца %s (длина лестницы %s м) %s" % (mark, metres(a), ALBUM)
    if kind == "zo":
        return "Звено ограждения ЗО %s" % ALBUM
    return "Крышка металлическая К1 ⌀610 %s" % ALBUM


def short(kind, mark, steel):
    if kind == "st902":
        a, n, _m = ST[mark[3:]]
        return "Стремянка %s · %s м · %s ступ. · 902" % (mark, metres(a), n)
    return "%s · 902" % TYPES[kind]["label"]


def history_patterns(kind, mark):
    """Регулярки для строк счетов МС (должны совпасть все) и что исключить."""
    if kind == "st902":
        nn = mark[3:]
        if nn == "00":  # базовое исполнение в счетах — просто «С1»
            return [r"стремянк", r"с\s*-?\s*1\s*([-.]\s*00|\s+тпр|\s*$)"], r"901-09"
        return [r"стремянк", r"с\s*-?\s*1\s*[-.]\s*%s(\D|$)" % nn], r"901-09"
    if kind == "zo":
        return [r"звен\w*\s+огражд", r"902-09-22|\(?зо\)?"], None
    return [r"крышк\w*\s+металл", r"к\s*-?\s*1(\D|$)"], None
