# -*- coding: utf-8 -*-
"""Общее для альбомов: масса проката, материалы состава, форматирование.

Материал детали — ключ для цены по прайсам (models/kolodec.py _pmk_price_ton):
- ("profile", вид проката, типоразмер) — pmk.metal.profile, как в расчёте («Уголок
  равнополочный», «50x50x5»);
- ("sheet", толщина) — pmk.metal.sheet «Гладкий»: детали, которые режем из листа
  (плиты МС, фланцы, половины крышки);
- None — покупное (шпильки, гайки, уплотнение): цену вписывают в строке.

Масса — по фактическим деталям (решение Антона по опорам 25.10.2026: в справочниках есть
ошибки); масса альбома — рядом, для сверки.
"""
import math

DENSITY = 7.85e-6          # кг/мм³
ANGLE = {"50x50x5": 3.77}  # кг/м, ГОСТ 8509-93
STEELS = ("Ст3пс", "09Г2С")


def round_kg(d):
    """Круг/квадрат d: кг на метр (ГОСТ 2590: d18 = 1,998)."""
    return round(math.pi / 4 * d * d * DENSITY * 1000, 3)


def square_kg(a):
    return round(a * a * DENSITY * 1000, 3)


def strip_kg(t, b, length):
    return t * b * length * DENSITY


def pipe_kg_m(dn, s):
    """Труба круглая Дн×S: кг/м (как ГОСТ 10704: 0,02466·S·(Дн−S))."""
    return math.pi * s * (dn - s) * DENSITY * 1000


def ring_kg(d_out, d_in, t, holes=0, d_hole=0):
    area = math.pi / 4 * (d_out ** 2 - d_in ** 2) - holes * math.pi / 4 * d_hole ** 2
    return area * t * DENSITY


def num(value):
    """1,8 / 2,25 / 90 — без «.0», с запятой."""
    return ("%g" % value).replace(".", ",")


def metres(mm):
    return num(mm / 1000.0)


def part(key, sequence, name, qty, unit_mass, material=None):
    return dict(key=key, sequence=sequence, name=name, qty=qty, unit_mass=round(unit_mass, 3),
                material=material, metal=material is not None)
