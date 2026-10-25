# -*- coding: utf-8 -*-
"""Металлоизделия колодцев — по альбому на файл (как опоры: «чтобы разные справочники можно
было править отдельно», Антон 25.10.2026). Модели работают только через этот диспетчер.

Новый альбом: файл tools/<альбом>.py с TYPES, ALBUM и функциями marks, check, dims, parts,
album_mass, designation, name, short, history_patterns + строка в ALBUMS + docs.
"""
from . import alb901_2, alb901_5, alb901_6, alb902_7
from .common import STEELS  # noqa: F401

ALBUMS = (alb902_7, alb901_5, alb901_6, alb901_2)
TYPES = {k: dict(v) for m in ALBUMS for k, v in m.TYPES.items()}
_BY_KIND = {k: m for m in ALBUMS for k in m.TYPES}


def album(kind):
    return _BY_KIND[kind]


def marks(kind):
    return album(kind).marks(kind)


def check(kind, mark):
    if kind not in _BY_KIND:
        return "Изделие не понято"
    return album(kind).check(kind, mark)


def dims(kind, mark):
    return album(kind).dims(kind, mark)


# Диаметр круга, гибы которого зависят от настройки «Поправка на гиб»: вид → ⌀.
BENT_ROUND = {"mn1": 18}


def parts(kind, mark, bend_k=None):
    """bend_k — вычет на гиб в диаметрах (настройка калькулятора); None — по умолчанию (2)."""
    return album(kind).parts(kind, mark, bend_k)


def mass(kind, mark, bend_k=None):
    return round(sum(p["qty"] * p["unit_mass"] for p in parts(kind, mark, bend_k)), 2)


def album_mass(kind, mark):
    return album(kind).album_mass(kind, mark)


def designation(kind, mark):
    return album(kind).designation(kind, mark)


def name(kind, mark, steel=None):
    return album(kind).name(kind, mark, steel)


def short(kind, mark, steel=None):
    return album(kind).short(kind, mark, steel)


def history_patterns(kind, mark):
    return album(kind).history_patterns(kind, mark)


def outside_album(kind, mark):
    return album(kind).outside_album(kind, mark)
