# -*- coding: utf-8 -*-
"""Время работы станка по профилю — заготовка (решение Антона 13.10.2026: станков два, скорости — из их .fsm, пришлёт
с каждого отдельно). Пока профилей нет, время в сводке стратегий — «—»: выдумывать скорости нельзя.

Профиль станка — JSON, один файл на станок (`--machine` повторяется — столбец времени на каждый станок):

    {"name": "Станок 1",
     "travel_mm_s": 1000,          холостой ход, мм/с
     "lift_s": 0.3,                подъём и опускание головки на каждый переход, с (нет — 0)
     "return_to_zero": true,       после листа головка возвращается в (0,0) (настройка CypCut)
     "mark_mm_s": 300,             гравировка, мм/с
     "cut": [{"t": 1.5, "mm_s": 466.7, "pierce_s": 0.1},     рез и врезка по толщинам (из .fsm слоя)
             {"t": 3,   "mm_s": 133.3, "pierce_s": 0.5}]}

Времени нет (None), а не «примерно»: толщины нет в профиле (не «ближайшая»); в программе есть гравировка, а скорости
гравировки в профиле нет.
"""
import json, os, numbers


def _num(v, name, where, zero_ok=False):
    if isinstance(v, bool) or not isinstance(v, numbers.Real) or v != v or v < 0 or (v == 0 and not zero_ok) or v == float("inf"):
        raise ValueError("%s: %s — нужно число %s, а не %r" % (where, name, "≥ 0" if zero_ok else "> 0", v))
    return float(v)


def load(src):
    """Профиль станка: путь к JSON или словарь → проверенный словарь (ошибка — ValueError с понятным текстом)."""
    if isinstance(src, dict):
        p, where, name = dict(src), "профиль станка", "станок"
    else:
        where, name = "профиль станка %s" % src, os.path.splitext(os.path.basename(str(src)))[0]
        try:
            with open(src, encoding="utf-8") as f:
                p = json.load(f)
        except OSError as e:
            raise ValueError("%s: не открывается (%s)" % (where, e.strerror or e))
        except ValueError as e:
            raise ValueError("%s: не JSON (%s)" % (where, e))
    if not isinstance(p, dict):
        raise ValueError("%s: нужен объект {…}, а не %s" % (where, type(p).__name__))
    _num(p.get("travel_mm_s"), "travel_mm_s", where)
    cut = p.get("cut")
    if not isinstance(cut, list) or not cut:
        raise ValueError("%s: нужен cut — список [{t, mm_s, pierce_s}] по толщинам" % where)
    for r in cut:
        if not isinstance(r, dict):
            raise ValueError("%s: строка cut %r — нужен объект {t, mm_s, pierce_s}" % (where, r))
        _num(r.get("t"), "cut.t", where)
        _num(r.get("mm_s"), "cut.mm_s (t=%s)" % r.get("t"), where)
        if "pierce_s" in r:
            _num(r["pierce_s"], "cut.pierce_s (t=%s)" % r.get("t"), where, zero_ok=True)
    if "lift_s" in p:
        _num(p["lift_s"], "lift_s", where, zero_ok=True)
    if p.get("mark_mm_s") is not None:
        _num(p["mark_mm_s"], "mark_mm_s", where)
    if not isinstance(p.get("return_to_zero", False), bool):
        raise ValueError("%s: return_to_zero — true или false" % where)
    p.setdefault("name", name)
    return p


def cut_row(profile, thickness):
    for r in profile.get("cut", ()):
        if thickness is not None and abs(float(r["t"]) - float(thickness)) < 1e-6:
            return r
    return None


def estimate(profile, thickness, cut_mm, mark_mm, idle_mm, ret_mm, pierces, moves):
    """Секунды на все листы или None (нет профиля, толщины в нём или скорости гравировки при гравировке). Числа —
    суммы по листам (× количество): рез, гравировка, холостой, возврат в ноль (мм), врезок, переходов."""
    if not profile:
        return None
    r = cut_row(profile, thickness)
    if r is None:
        return None
    t = cut_mm / float(r["mm_s"]) + pierces * float(r.get("pierce_s", 0.0))
    if mark_mm:
        if not profile.get("mark_mm_s"):
            return None
        t += mark_mm / float(profile["mark_mm_s"])
    travel = idle_mm + (ret_mm if profile.get("return_to_zero") else 0.0)
    t += travel / float(profile["travel_mm_s"]) + moves * float(profile.get("lift_s", 0.0))
    return t
